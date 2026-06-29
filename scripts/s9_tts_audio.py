#!/usr/bin/env python3
"""
scripts/s9_tts_audio.py — Stage 9: TTS 语音 + 时间轴对齐 + 字幕 + 成片

管线:
  1. 从 s4_shots.json 提取全部对话，按 shot duration 计算绝对时间轴
  2. Qwen3-TTS 逐条合成（全局序号命名，避免 shot 内 dial_idx 碰撞）
  3. 构建 95.7s timeline 音频（silence base + 逐条 adelay + 2-input amix overlay）
  4. 直接从 s4_shots.json 生成 ASS 字幕（已知精确时间）
  5. ffmpeg mux: 视频 + timeline 音频 + ASS → 最终成片（无 -shortest）

用法:
    python scripts/s9_tts_audio.py --project last_bento
    python scripts/s9_tts_audio.py --project last_bento --skip-tts  # 使用已有音频
"""

import json, sys, argparse, subprocess, shutil
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from core.state_manager import get_state_manager
from core.comfyui_session import ComfyUISession

FPS = 25
W, H = 896, 512

# ═══════════════════════════════════════
# Step 1: TTS via Qwen3-TTS (ComfyUI)
# ═══════════════════════════════════════

VOICE_MAP = {
    "老周": {"voice": "Aiden"},
    "林姐": {"voice": "Vivian"},
    "小陈": {"voice": "Ryan"},
    "default": {"voice": "Aiden"},
}


def clean_tts_text(text: str) -> str:
    """Clean text for Qwen3-TTS compatibility."""
    return text.replace("……", ",").replace("——", ",").replace("、", ",")


def build_tts_workflow(text: str, voice: str, seed: int = 42) -> dict:
    """Build Qwen3-TTS Advanced workflow."""
    text = clean_tts_text(text)
    return {
        "1": {"class_type": "AILab_Qwen3TTSCustomVoice_Advanced", "inputs": {
            "text": text,
            "speaker": voice,
            "model_size": "1.7B",
            "device": "auto",
            "precision": "bf16",
            "language": "Auto",
            "max_new_tokens": 512,
            "unload_models": True,
            "seed": seed,
        }},
        "2": {"class_type": "SaveAudio", "inputs": {
            "filename_prefix": "aicf_tts",
            "audio": ["1", 0],
        }},
    }


def generate_tts(sess, text: str, character: str, shot_num: int,
                  global_idx: int, out_dir: Path) -> Path:
    """Generate TTS audio for a single dialogue line. Returns local path."""
    vcfg = VOICE_MAP.get(character, VOICE_MAP["default"])
    wf = build_tts_workflow(text, vcfg["voice"], shot_num * 100 + global_idx)
    wf["2"]["inputs"]["filename_prefix"] = f"aicf_tts_{global_idx:02d}"

    result = sess.run(wf, timeout=300)

    output_dir = Path.home() / "ComfyUI" / "output"
    candidates = sorted(
        output_dir.glob(f"aicf_tts_{global_idx:02d}_*.flac"),
        key=lambda x: x.stat().st_mtime, reverse=True
    )
    if not candidates:
        candidates = sorted(
            output_dir.glob(f"aicf_tts_{global_idx:02d}_*.wav"),
            key=lambda x: x.stat().st_mtime, reverse=True
        )
    if not candidates:
        candidates = sorted(
            output_dir.glob(f"aicf_tts_{global_idx:02d}_*.mp3"),
            key=lambda x: x.stat().st_mtime, reverse=True
        )
    if not candidates:
        raise RuntimeError(f"No TTS output for global_idx {global_idx} (shot {shot_num})")

    ext = candidates[0].suffix
    dest = out_dir / f"d{global_idx:02d}_{character}{ext}"
    shutil.copy2(str(candidates[0]), str(dest))
    return dest


# ═══════════════════════════════════════
# Step 2: Timeline audio construction
# ═══════════════════════════════════════

def calc_dialogue_timeline(s4_data: dict) -> list[dict]:
    """
    Calculate absolute timeline positions for each dialogue.
    Returns list of {global_idx, shot, character, text, start_s}.
    Uses global index to avoid naming collisions across shots.
    """
    entries = []
    acc = 0.0
    global_idx = 0
    for scene in s4_data["scenes"]:
        for shot in scene["shots"]:
            sn = shot["shotNumber"]
            dur = shot.get("duration", 5.0)
            dialogues = shot.get("dialogues", [])
            n = len(dialogues)
            for di, d in enumerate(dialogues):
                start_s = acc + (di + 1) / (n + 1) * dur
                entries.append({
                    "global_idx": global_idx,
                    "shot": sn,
                    "character": d["character"],
                    "text": d["text"],
                    "start_s": round(start_s, 2),
                })
                global_idx += 1
            acc += dur
    return entries, acc


def build_timeline_audio(audio_files: list[Path], timeline: list[dict],
                         total_duration: float, output: Path):
    """
    Build timeline audio: silence base + sequential 2-input amix overlay.

    For each clip: delay it to start_s, then amix onto current base.
    This avoids ffmpeg input limits and ensures non-dialogue segments are silence.
    """
    # Create silence base
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"anullsrc=channel_layout=stereo:sample_rate=24000",
        "-t", str(total_duration),
        "-c:a", "pcm_s16le", "-ar", "24000",
        str(output),
    ], check=True, capture_output=True)

    if not audio_files:
        return output

    # Clean up any leftover temp files from previous runs
    for tmp in output.parent.glob("_mix_tmp_*.wav"):
        try:
            tmp.unlink()
        except OSError:
            pass

    # Sequential overlay: normalize, delay, then mix onto current base
    current = output
    for i, (af, entry) in enumerate(zip(audio_files, timeline)):
        delay_ms = int(entry["start_s"] * 1000)
        next_out = output.parent / f"_mix_tmp_{i}.wav"

        # Normalize clip to -9 dB LUFS, then delay, then mix
        subprocess.run([
            "ffmpeg", "-y",
            "-i", str(current),
            "-i", str(af),
            "-filter_complex",
            f"[1:a]loudnorm=I=-9:TP=-1.5:LRA=11[normalized];[normalized]adelay={delay_ms}|{delay_ms}[delayed];[0:a][delayed]amix=inputs=2:duration=longest:dropout_transition=0:normalize=0[aout]",
            "-map", "[aout]",
            "-c:a", "pcm_s16le", "-ar", "24000",
            str(next_out),
        ], check=True, capture_output=True)

        # Clean up previous intermediate
        if i > 0 and current != output:
            try:
                current.unlink()
            except OSError:
                pass
        current = next_out

    # Move final result to output path
    if current != output:
        shutil.move(str(current), str(output))
    return output


# ═══════════════════════════════════════
# Step 3: ASS subtitles from script
# ═══════════════════════════════════════

def generate_ass_from_script(s4_data: dict, ass_path: Path, total_duration: float):
    """
    Generate ASS subtitles directly from s4_shots.json dialogue data.
    Each dialogue line is placed at evenly-spaced position within its shot.
    """
    acc = 0.0
    entries = []
    for scene in s4_data["scenes"]:
        for shot in scene["shots"]:
            sn = shot["shotNumber"]
            dur = shot.get("duration", 5.0)
            dialogues = shot.get("dialogues", [])
            n = len(dialogues)
            for di, d in enumerate(dialogues):
                if n == 1:
                    start = acc + dur * 0.3
                    end = acc + dur * 0.85
                else:
                    slot = dur / (n + 0.5)
                    start = acc + slot * (di + 0.25)
                    end = acc + slot * (di + 0.75)
                entries.append({
                    "start": start,
                    "end": min(end, acc + dur - 0.1),
                    "text": clean_tts_text(d["text"]),
                })
            acc += dur

    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(f"""[Script Info]
Title: {s4_data.get('title', '')}
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Default,Noto Sans CJK SC,28,&H00FFFFFF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,2,0,2,20,20,30,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
""")
        for entry in entries:
            def fmt(sec):
                h = int(sec // 3600)
                m = int((sec % 3600) // 60)
                s = sec % 60
                return f"{h}:{m:02d}:{s:05.2f}"
            f.write(f"Dialogue: 0,{fmt(entry['start'])},{fmt(entry['end'])},Default,,0,0,0,,{entry['text']}\n")
    return ass_path


# ═══════════════════════════════════════
# Step 4: Mux audio + subtitles into video
# ═══════════════════════════════════════

def mux_audio_video(video_path: Path, audio_path: Path, ass_path: Path, output: Path):
    """Mux video + timeline audio + ASS subtitles. No -shortest (audio matches video)."""
    subprocess.run([
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-i", str(audio_path),
        "-vf", f"ass={ass_path}",
        "-c:v", "libx264", "-crf", "23", "-preset", "fast",
        "-c:a", "aac", "-b:a", "128k",
        str(output),
    ], check=True, capture_output=True)


# ═══════════════════════════════════════
# Whisper ASR (optional, kept for reference)
# ═══════════════════════════════════════

def transcribe_audio(audio_path: Path, model: str = "medium") -> list:
    """Run Whisper ASR on audio file. Returns segments with timestamps."""
    import whisper
    m = whisper.load_model(model)
    result = m.transcribe(
        str(audio_path),
        language="zh",
        word_timestamps=True,
        verbose=False,
    )
    return result["segments"]


def segments_to_srt(segments: list, output: Path):
    """Convert Whisper segments to SRT file."""
    with open(output, "w") as f:
        for i, seg in enumerate(segments, 1):
            start = seg["start"]
            end = seg["end"]
            text = seg["text"].strip()

            def fmt(sec):
                h = int(sec // 3600)
                m = int((sec % 3600) // 60)
                s = int(sec % 60)
                ms = int((sec % 1) * 1000)
                return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

            f.write(f"{i}\n{fmt(start)} --> {fmt(end)}\n{text}\n\n")


# ═══════════════════════════════════════
# Main
# ═══════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Stage 9: TTS + 时间轴对齐 + 字幕 + 成片")
    parser.add_argument("--project", "-P", required=True)
    parser.add_argument("--skip-tts", action="store_true", help="跳过 TTS 生成（使用已有音频）")
    parser.add_argument("--whisper-model", default="medium",
                        choices=["tiny", "base", "small", "medium", "large"],
                        help="(保留参数，当前流程不依赖 Whisper)")
    args = parser.parse_args()

    pd = Path(__file__).parent.parent / "projects" / args.project
    s4 = json.load(open(pd / "s4_shots.json"))
    s7_video = pd / "s7_assembled.mp4"
    tts_dir = pd / "s9_tts_audio"
    tts_dir.mkdir(parents=True, exist_ok=True)

    if not s7_video.exists():
        print(f"❌ {s7_video} not found. Run S7 first.")
        sys.exit(1)

    sm = get_state_manager()
    sm.mark_running(args.project, "s9_tts_audio")

    # ── Step 1: Build timeline with global indices ──
    print("=== Step 1: 计算对话时间轴 ===")
    timeline_entries, s4_total = calc_dialogue_timeline(s4)

    # Use actual video duration as total (s4 may not cover intro/outro)
    r = subprocess.run([
        "ffprobe", "-v", "quiet", "-show_entries", "format=duration",
        "-of", "csv=p=0", str(s7_video),
    ], capture_output=True, text=True)
    try:
        total_duration = float(r.stdout.strip())
    except ValueError:
        total_duration = s4_total

    print(f"  s4 时长: {s4_total:.1f}s, 视频实际: {total_duration:.1f}s, 对话数: {len(timeline_entries)}")
    if total_duration > s4_total:
        print(f"  ⚠️ 视频比 s4 多 {total_duration - s4_total:.1f}s（intro/outro），尾部自动填充静音")
    for e in timeline_entries:
        print(f"    [{e['global_idx']:02d}] s{e['shot']:02d} @ {e['start_s']:.2f}s [{e['character']}] {e['text'][:35]}...")


    # ── Step 2: TTS Generation ──
    print(f"\n=== Step 2: TTS 生成 ===")
    audio_files = []

    if not args.skip_tts:
        sess = ComfyUISession()
        for entry in timeline_entries:
            gi = entry["global_idx"]
            sn = entry["shot"]
            char = entry["character"]
            text = entry["text"]
            expected_name = f"d{gi:02d}_{char}"

            # Check if already exists
            existing = list(tts_dir.glob(f"{expected_name}.*"))
            if existing:
                print(f"  ✅ 已有: {existing[0].name}")
                audio_files.append(existing[0])
                continue

            print(f"  生成: [{gi:02d}] s{sn:02d} {char}: {text[:40]}...")
            try:
                af = generate_tts(sess, text, char, sn, gi, tts_dir)
                dur = get_audio_duration(af)
                print(f"    ✅ {dur:.1f}s → {af.name}")
                audio_files.append(af)
            except Exception as e:
                print(f"    ❌ {e}")
                silence = tts_dir / f"d{gi:02d}_{char}_silence.wav"
                subprocess.run([
                    "ffmpeg", "-y", "-f", "lavfi",
                    "-i", "anullsrc=channel_layout=stereo:sample_rate=24000",
                    "-t", "2.0", "-c:a", "pcm_s16le", "-ar", "24000",
                    str(silence),
                ], check=True, capture_output=True)
                audio_files.append(silence)
    else:
        # Match existing files by global index
        for entry in timeline_entries:
            gi = entry["global_idx"]
            char = entry["character"]
            matches = list(tts_dir.glob(f"d{gi:02d}_{char}.*"))
            if matches:
                audio_files.append(matches[0])
            else:
                print(f"  ⚠️ 缺失: d{gi:02d}_{char}，用 silence 替代")
                silence = tts_dir / f"d{gi:02d}_{char}_silence.wav"
                subprocess.run([
                    "ffmpeg", "-y", "-f", "lavfi",
                    "-i", "anullsrc=channel_layout=stereo:sample_rate=24000",
                    "-t", "2.0", "-c:a", "pcm_s16le", "-ar", "24000",
                    str(silence),
                ], check=True, capture_output=True)
                audio_files.append(silence)

    # ── Step 3: Build timeline audio ──
    print(f"\n=== Step 3: 构建 {total_duration:.1f}s 时间轴音频 ===")
    timeline_audio = pd / "s9_timeline_audio.wav"

    tl_with_paths = []
    for entry, af in zip(timeline_entries, audio_files):
        tl_with_paths.append({"start_s": entry["start_s"], "path": af})

    build_timeline_audio(audio_files, tl_with_paths, total_duration, timeline_audio)
    actual_dur = get_audio_duration(timeline_audio)

    # Final normalize pass: bring entire timeline to -12 dB
    normalized_audio = pd / "s9_timeline_audio_normalized.wav"
    subprocess.run([
        "ffmpeg", "-y",
        "-i", str(timeline_audio),
        "-af", "loudnorm=I=-12:TP=-1.5:LRA=11",
        "-c:a", "pcm_s16le", "-ar", "24000",
        str(normalized_audio),
    ], check=True, capture_output=True)
    norm_dur = get_audio_duration(normalized_audio)
    print(f"  ✅ {normalized_audio} ({norm_dur:.1f}s, normalized to -12 dB)")

    # ── Step 4: Generate ASS subtitles ──
    print(f"\n=== Step 4: 生成 ASS 字幕 ===")
    ass_path = pd / "s8_subtitles.ass"
    generate_ass_from_script(s4, ass_path, total_duration)
    print(f"  ✅ {ass_path}")

    # ── Step 5: Mux final ──
    print(f"\n=== Step 5: 合成最终成片 ===")
    output = pd / "s9_final.mp4"
    mux_audio_video(s7_video, normalized_audio, ass_path, output)
    size_mb = output.stat().st_size / (1024 * 1024)
    print(f"  ✅ {output} ({size_mb:.1f}MB)")

    sm.mark_completed(args.project, "s9_tts_audio",
                      tts=f"{len(audio_files)} clips",
                      size_mb=f"{size_mb:.1f}")
    print(f"\n🎬 最终成片: {output}")


# ═══════════════════════════════════════
# Utility
# ═══════════════════════════════════════

def get_audio_duration(path: Path) -> float:
    """Get audio duration via ffprobe."""
    r = subprocess.run([
        "ffprobe", "-v", "quiet", "-show_entries", "format=duration",
        "-of", "csv=p=0", str(path),
    ], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 2.0


if __name__ == "__main__":
    main()
