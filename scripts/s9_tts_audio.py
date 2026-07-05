#!/usr/bin/env python3
"""
scripts/s9_tts_audio.py — Stage 9: TTS 语音 + 时间轴对齐 + 字幕 + 成片

管线:
  1. 从 core/timeline.py 获取统一时间轴（与 S7/S8 一致）
  2. Qwen3-TTS 逐条合成（全局序号命名，避免 shot 内 dial_idx 碰撞）
  3. 构建 timeline 音频（silence base + 逐条 adelay + 2-input amix overlay）
  4. 从 S8 生成的 ASS 字幕烧录
  5. ffmpeg mux: 视频 + timeline 音频 + ASS → 最终成片（无 -shortest）

用法:
    python scripts/s9_tts_audio.py --project last_bento
    python scripts/s9_tts_audio.py --project last_bento --skip-tts  # 使用已有音频
"""

import json, sys, argparse, subprocess, shutil, logging
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from core.state_manager import get_state_manager
from core.comfyui_session import ComfyUISession, ComfyUIError
from core.timeline import (
    build_timeline_from_project, calc_dialogue_timeline,
    fmt_srt_time, fmt_ass_time, clean_subtitle_text,
    generate_ass,
)

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════
# TTS Output Validation & Retry
# ═══════════════════════════════════════

# Avg speaking rate for Mandarin: ~3.5 chars/s used to estimate expected duration
MANDARIN_CHARS_PER_SEC = 3.5
# Duration tolerance: generated audio must be within ±30% of expected
DURATION_TOLERANCE = 0.30
# RMS volume floor: reject audio with RMS below this threshold (normalized 0-1)
RMS_VOLUME_FLOOR = 0.01
# Max retry attempts for TTS generation
MAX_TTS_RETRIES = 1


def estimate_expected_duration(text: str) -> float:
    """Estimate expected TTS duration based on text length.

    Mandarin speaking rate ~3.5 chars/s. Punctuation adds slight pauses.
    Returns a baseline expected duration in seconds.
    """
    # Strip common punctuation for char count estimate
    PUNCT_SET = set("，。！？、；：.,!?;:'\"")
    stripped = text
    for ch in PUNCT_SET:
        stripped = stripped.replace(ch, "")
    char_count = max(len(stripped), 1)
    base = char_count / MANDARIN_CHARS_PER_SEC
    # Add small overhead for natural pauses
    return base * 1.1


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


def get_audio_rms(path: Path) -> float:
    """Compute RMS volume of an audio file via ffmpeg volumedetect.

    Returns normalized RMS (0-1 range). Pure silence returns 0.0.
    """
    r = subprocess.run([
        "ffmpeg", "-y", "-i", str(path),
        "-af", "volumedetect", "-f", "null", "-",
    ], capture_output=True, text=True)
    # Parse overall_volume from volumedetect stderr
    for line in r.stderr.split("\n"):
        if "overall_volume" in line:
            try:
                db = float(line.split(":")[1].strip())
                # Convert dB to linear: 10^(dB/20)
                return 10 ** (db / 20)
            except (ValueError, IndexError):
                pass
    return 0.0


def validate_tts_output(audio_path: Path, text: str) -> tuple:
    """Validate TTS output for quality and correctness.

    Returns (is_valid: bool, reason: str).
    Checks:
      1. Duration is within ±30% of expected duration
      2. Audio is not silent (RMS volume above threshold)
    """
    if not audio_path.exists():
        return False, "output file does not exist"

    # Check 1: Duration
    actual_dur = get_audio_duration(audio_path)
    expected = estimate_expected_duration(text)
    lo = expected * (1 - DURATION_TOLERANCE)
    hi = expected * (1 + DURATION_TOLERANCE)
    if actual_dur < lo or actual_dur > hi:
        return False, (
            f"duration {actual_dur:.2f}s out of range [{lo:.2f}-{hi:.2f}s] "
            f"(expected ~{expected:.2f}s)"
        )

    # Check 2: Volume (not silent)
    rms = get_audio_rms(audio_path)
    if rms < RMS_VOLUME_FLOOR:
        return False, f"silence detected (RMS={rms:.4f} < {RMS_VOLUME_FLOOR})"

    return True, "ok"


# ═══════════════════════════════════════
# Step 1: TTS via Qwen3-TTS (ComfyUI)
# ═══════════════════════════════════════

FPS = 25
W, H = 1280, 720

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


def _cleanup_tts_model(sess):
    """Explicitly release GPU memory after TTS generation.

    unload_models=True only unloads within ComfyUI; we also need to
    clear Python-side references and GPU cache to prevent state pollution
    across batches.
    """
    try:
        import torch
        if hasattr(sess, "_model") and sess._model is not None:
            del sess._model
            sess._model = None
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


def generate_tts_once(sess, text: str, character: str, shot_num: int,
                       global_idx: int, out_dir: Path) -> Path:
    """Generate TTS audio for a single dialogue line (single attempt).
    Raises on failure; caller handles retry."""
    vcfg = VOICE_MAP.get(character, VOICE_MAP["default"])
    wf = build_tts_workflow(text, vcfg["voice"], shot_num * 100 + global_idx)
    wf["2"]["inputs"]["filename_prefix"] = f"aicf_tts_{global_idx:02d}"

    result = sess.run(wf, timeout=300)

    # Explicit model cleanup to prevent state pollution
    _cleanup_tts_model(sess)

    output_dir = Path.home() / "ComfyUI" / "output"
    for ext in ["flac", "wav", "mp3"]:
        candidates = sorted(
            output_dir.glob(f"aicf_tts_{global_idx:02d}_*.{ext}"),
            key=lambda x: x.stat().st_mtime, reverse=True
        )
        if candidates:
            dest = out_dir / f"d{global_idx:02d}_{character}{ext}"
            shutil.copy2(str(candidates[0]), str(dest))
            return dest

    raise RuntimeError(
        f"No TTS output for global_idx {global_idx} (shot {shot_num})"
    )


def generate_tts(sess, text: str, character: str, shot_num: int,
                 global_idx: int, out_dir: Path,
                 max_retries: int = MAX_TTS_RETRIES) -> tuple:
    """Generate TTS audio with validation and retry.

    Returns (path: Path, warnings: list[str]).
    On success: path points to validated audio, warnings may contain info.
    On permanent failure: path points to silence placeholder, warnings list failures.
    """
    warnings = []
    expected = estimate_expected_duration(text)

    for attempt in range(1 + max_retries):
        try:
            audio_path = generate_tts_once(
                sess, text, character, shot_num, global_idx, out_dir
            )
            is_valid, reason = validate_tts_output(audio_path, text)

            if is_valid:
                dur = get_audio_duration(audio_path)
                if attempt > 0:
                    warnings.append(f"validated on attempt {attempt + 1}: {dur:.1f}s")
                return audio_path, warnings

            # Validation failed — clean up bad file and retry
            if attempt < max_retries:
                warnings.append(f"attempt {attempt + 1} failed validation: {reason}")
                try:
                    audio_path.unlink()
                except OSError:
                    pass
            else:
                # Exhausted retries
                warnings.append(f"final attempt failed validation: {reason}")
                try:
                    audio_path.unlink()
                except OSError:
                    pass

        except Exception as e:
            if attempt < max_retries:
                warnings.append(f"attempt {attempt + 1} error: {e}")
            else:
                warnings.append(f"final attempt error: {e}")

    # All attempts failed — create silence placeholder with expected duration
    logger.warning(
        "TTS generation failed after %d attempts for gi=%d: %s",
        1 + max_retries, global_idx, "; ".join(warnings),
    )
    silence = out_dir / f"d{global_idx:02d}_{character}_silence.wav"
    # Silence duration matches expected TTS duration, not hardcoded 2s
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", f"anullsrc=channel_layout=stereo:sample_rate=24000",
        "-t", f"{expected:.2f}", "-c:a", "pcm_s16le", "-ar", "24000",
        str(silence),
    ], check=True, capture_output=True)
    warnings.append(f"replaced with silence ({expected:.1f}s)")
    return silence, warnings


# ═══════════════════════════════════════
# Step 2: Timeline audio construction
# ═══════════════════════════════════════

def build_timeline_audio(audio_files: list, timeline_entries: list,
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
    for i, (af, entry) in enumerate(zip(audio_files, timeline_entries)):
        delay_ms = int(entry["start_s"] * 1000)
        next_out = output.parent / f"_mix_tmp_{i}.wav"

        # Normalize clip to -9 dB LUFS, then delay, then mix
        subprocess.run([
            "ffmpeg", "-y",
            "-i", str(current),
            "-i", str(af),
            "-filter_complex",
            f"[1:a]loudnorm=I=-9:TP=-1.5:LRA=11[normalized];"
            f"[normalized]adelay={delay_ms}|{delay_ms}[delayed];"
            f"[0:a][delayed]amix=inputs=2:duration=longest:dropout_transition=0:normalize=0[aout]",
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
# Step 3: Mux audio + subtitles into video
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
# Main
# ═══════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Stage 9: TTS + 时间轴对齐 + 字幕 + 成片"
    )
    parser.add_argument("--project", "-P", required=True)
    parser.add_argument(
        "--skip-tts", action="store_true",
        help="跳过 TTS 生成（使用已有音频）",
    )
    parser.add_argument(
        "--title-duration", type=float, default=3.0,
        help="标题卡时长(秒) — 必须与 S7 一致",
    )
    parser.add_argument(
        "--credits-duration", type=float, default=4.0,
        help="结束卡时长(秒) — 必须与 S7 一致",
    )
    parser.add_argument("--calibrate", action="store_true", default=True,
                        help="用 ffprobe 校准视频时长 (默认启用)")
    parser.add_argument("--no-calibrate", action="store_true",
                        help="不校准，用 s4 duration")
    args = parser.parse_args()

    pd = Path(__file__).parent.parent / "projects" / args.project
    s4_path = pd / "s4_shots.json"
    s4 = json.load(open(s4_path))
    s7_video = pd / "s7_assembled.mp4"
    tts_dir = pd / "s9_tts_audio"
    tts_dir.mkdir(parents=True, exist_ok=True)

    if not s7_video.exists():
        print(f"❌ {s7_video} not found. Run S7 first.")
        sys.exit(1)

    sm = get_state_manager()
    sm.mark_running(args.project, "s9_tts_audio")

    # ── Step 1: 构建统一时间轴 ──
    print("=== Step 1: 构建统一时间轴 ===")
    calibrate = args.calibrate and not args.no_calibrate
    timeline = build_timeline_from_project(
        pd,
        title_duration=args.title_duration,
        credits_duration=args.credits_duration,
        calibrate_with_videos=calibrate,  # 与 S8 保持一致
    )
    dialogue_entries = calc_dialogue_timeline(s4, timeline)

    # 使用实际视频时长作为总时长
    r = subprocess.run([
        "ffprobe", "-v", "quiet", "-show_entries", "format=duration",
        "-of", "csv=p=0", str(s7_video),
    ], capture_output=True, text=True)
    try:
        total_duration = float(r.stdout.strip())
    except ValueError:
        total_duration = timeline.total_duration

    print(
        f"  s4 时长: {timeline.shots_only_duration:.1f}s, "
        f"视频实际: {total_duration:.1f}s, "
        f"对话数: {len(dialogue_entries)}"
    )
    for e in dialogue_entries:
        print(
            f"    [{e['global_idx']:02d}] s{e['shot']:02d} "
            f"@ {e['start_s']:.2f}s [{e['character']}] "
            f"{e['text'][:35]}..."
        )

    # ── Step 2: TTS Generation ──
    print(f"\n=== Step 2: TTS 生成 ===")
    audio_files = []
    all_warnings = []

    if not args.skip_tts:
        sess = ComfyUISession()
        for entry in dialogue_entries:
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
            audio_path, warnings = generate_tts(
                sess, text, char, sn, gi, tts_dir
            )
            all_warnings.extend(warnings)

            dur = get_audio_duration(audio_path)
            if audio_path.name.endswith("_silence.wav"):
                print(f"    ⚠️ 替换为静音 ({dur:.1f}s): {'; '.join(warnings)}")
            elif warnings:
                print(f"    ✅ {dur:.1f}s → {audio_path.name} (with warnings)")
            else:
                print(f"    ✅ {dur:.1f}s → {audio_path.name}")
            audio_files.append(audio_path)

        # Summary
        if all_warnings:
            print(f"\n  ⚠️ TTS warnings summary ({len(all_warnings)}):")
            for w in all_warnings:
                print(f"     - {w}")
    else:
        # Match existing files by global index
        for entry in dialogue_entries:
            gi = entry["global_idx"]
            char = entry["character"]
            matches = list(tts_dir.glob(f"d{gi:02d}_{char}.*"))
            if matches:
                audio_files.append(matches[0])
            else:
                expected = estimate_expected_duration(entry["text"])
                print(
                    f"  ⚠️ 缺失: d{gi:02d}_{char}，"
                    f"用 silence ({expected:.1f}s) 替代"
                )
                silence = tts_dir / f"d{gi:02d}_{char}_silence.wav"
                subprocess.run([
                    "ffmpeg", "-y", "-f", "lavfi",
                    "-i", f"anullsrc=channel_layout=stereo:sample_rate=24000",
                    "-t", f"{expected:.2f}", "-c:a", "pcm_s16le", "-ar", "24000",
                    str(silence),
                ], check=True, capture_output=True)
                audio_files.append(silence)

    # ── Step 3: Build timeline audio ──
    print(f"\n=== Step 3: 构建 {total_duration:.1f}s 时间轴音频 ===")
    timeline_audio = pd / "s9_timeline_audio.wav"

    build_timeline_audio(
        audio_files, dialogue_entries, total_duration, timeline_audio
    )
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

    # ── Step 4: Generate ASS subtitles (统一时间轴) ──
    print(f"\n=== Step 4: 生成 ASS 字幕 (统一时间轴) ===")
    ass_path = pd / "s8_subtitles.ass"
    generate_ass(dialogue_entries, ass_path, width=W, height=H)
    print(f"  ✅ {ass_path}")

    # ── Step 5: Mux final ──
    print(f"\n=== Step 5: 合成最终成片 ===")
    output = pd / "s9_final.mp4"
    mux_audio_video(s7_video, normalized_audio, ass_path, output)
    size_mb = output.stat().st_size / (1024 * 1024)
    print(f"  ✅ {output} ({size_mb:.1f}MB)")

    sm.mark_completed(
        args.project, "s9_tts_audio",
        tts=f"{len(audio_files)} clips",
        size_mb=f"{size_mb:.1f}",
    )
    print(f"\n🎬 最终成片: {output}")


if __name__ == "__main__":
    main()
