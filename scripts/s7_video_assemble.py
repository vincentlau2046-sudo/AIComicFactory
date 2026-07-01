#!/usr/bin/env python3
"""scripts/s7_video_assemble.py — Stage 7: Video Assembly (AICB Full)

Implements AICB assembleVideo from src/lib/video/ffmpeg.ts:
  1. Title/credits card generation (ffmpeg drawtext)
  2. Multi-type xfade transitions (cut/dissolve/fade/wipeleft/slideright/circleopen)
  3. Subtitle burn-in (SRT + ffmpeg subtitles filter)
  4. BGM mixing (--bgm, volume=0.3)
  5. Fast concat fallback for all-cut sequences

AICB transition mapping:
  cut       → xfade=fade:duration=0 (hard cut)
  dissolve  → xfade=dissolve
  fade_in   → xfade=fade (in)
  fade_out  → xfade=fadeblack (out)
  wipeleft  → xfade=wipeleft
  slideright→ xfade=slideright
  circleopen→ xfade=circleopen

Usage:
    python scripts/s7_video_assemble.py --project last_bento
    python scripts/s7_video_assemble.py --project last_bento --bgm music.mp3 --bgm-volume 0.3
    python scripts/s7_video_assemble.py --project last_bento --transition-duration 0.5 --no-title
"""

import json, sys, argparse, subprocess, os, tempfile
from pathlib import Path
from typing import List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.state_manager import get_state_manager
from core.asset_manager import get_asset_manager

# ═══════════════════════════════════════════════════════════════════
# Config
# ═══════════════════════════════════════════════════════════════════

W, H = 1280, 720  # AICB standard 16:9
FPS = 25
TITLE_DURATION = 3.0
CREDITS_DURATION = 4.0
DEFAULT_XFADE_DURATION = 0.5

FONT_SEARCH_PATHS = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
]
FONT_PATH = None
for fp in FONT_SEARCH_PATHS:
    if os.path.exists(fp):
        FONT_PATH = fp
        break

TRANSITION_MAP = {
    "cut":        "cut",
    "dissolve":   "dissolve",
    "fade_in":    "fade",
    "fade_out":   "fadeblack",
    "wipeleft":   "wipeleft",
    "slideright": "slideright",
    "circleopen": "circleopen",
}
DEFAULT_TRANSITION = "dissolve"


# ═══════════════════════════════════════════════════════════════════
# FFprobe helpers
# ═══════════════════════════════════════════════════════════════════

def get_clip_duration(path: Path) -> float:
    """Get clip duration in seconds."""
    result = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ], capture_output=True, text=True, check=True)
    return float(result.stdout.strip())


def get_clip_fps(path: Path) -> float:
    """Get clip FPS."""
    result = subprocess.run([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=r_frame_rate",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ], capture_output=True, text=True, check=True)
    num, den = result.stdout.strip().split("/")
    return float(num) / float(den)


# ═══════════════════════════════════════════════════════════════════
# Card generation (AICB: ffmpeg drawtext)
# ═══════════════════════════════════════════════════════════════════

def _escape_ffmpeg_text(text: str) -> str:
    """Escape text for ffmpeg drawtext filter (single-quote safe)."""
    return text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "'\\\\\\''")


def generate_title_card(out_dir: Path, text: str, project_id: str) -> Path:
    """Generate title card with ffmpeg drawtext (AICB style)."""
    import uuid
    card_path = out_dir / f"title-{uuid.uuid4().hex[:8]}.mp4"
    escaped = _escape_ffmpeg_text(text)
    font_arg = f":fontfile='{FONT_PATH}'" if FONT_PATH else ""

    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c=black:s={W}x{H}:d={TITLE_DURATION}",
        "-vf", (
            f"drawtext=text='{escaped}'"
            f":fontsize=48:fontcolor=white"
            f":x=(w-text_w)/2:y=(h-text_h)/2{font_arg}"
            f",fade=t=in:d=1"
        ),
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-t", str(TITLE_DURATION),
        "-pix_fmt", "yuv420p",
        str(card_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return card_path


def generate_credits_card(out_dir: Path, text: str, project_id: str) -> Path:
    """Generate end credits card (AICB style)."""
    import uuid
    card_path = out_dir / f"credits-{uuid.uuid4().hex[:8]}.mp4"
    escaped = _escape_ffmpeg_text(text)
    font_arg = f":fontfile='{FONT_PATH}'" if FONT_PATH else ""

    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c=black:s={W}x{H}:d={CREDITS_DURATION}",
        "-vf", (
            f"drawtext=text='{escaped}'"
            f":fontsize=36:fontcolor=white"
            f":x=(w-text_w)/2:y=(h-text_h)/2{font_arg}"
            f",fade=t=out:d=1"
        ),
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-t", str(CREDITS_DURATION),
        "-pix_fmt", "yuv420p",
        str(card_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return card_path


# ═══════════════════════════════════════════════════════════════════
# SRT subtitle generation (AICB: generateSrtFile)
# ═══════════════════════════════════════════════════════════════════

def format_srt_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def generate_srt(subtitles: List[dict], shot_durations: List[float],
                 output_path: Path) -> Path:
    """
    Generate SRT subtitle file (AICB generateSrtFile).
    
    subtitles: list of {shotSequence, text, dialogueSequence, dialogueCount, startRatio?, endRatio?}
    shot_durations: cumulative durations per shot in order
    
    Uses startRatio/endRatio for precise timing, or auto-distributes by dialogueCount.
    """
    srt_path = Path(str(output_path).replace(".mp4", ".srt"))

    # Calculate cumulative start times
    shot_start_times = []
    cumulative = 0.0
    for dur in shot_durations:
        shot_start_times.append(cumulative)
        cumulative += dur

    entries = []
    index = 1
    for sub in subtitles:
        shot_idx = sub["shotSequence"] - 1  # 0-based
        if shot_idx < 0 or shot_idx >= len(shot_durations):
            continue

        shot_start = shot_start_times[shot_idx]
        shot_dur = shot_durations[shot_idx]

        if sub.get("startRatio") is not None and sub.get("endRatio") is not None:
            start_time = shot_start + shot_dur * sub["startRatio"]
            end_time = shot_start + shot_dur * sub["endRatio"]
        else:
            # Auto-distribute within shot duration
            count = sub.get("dialogueCount", 1) or 1
            seq = sub.get("dialogueSequence", 0)
            segment_dur = shot_dur / count
            start_time = shot_start + segment_dur * seq
            end_time = start_time + segment_dur

        entries.append(
            f"{index}\n"
            f"{format_srt_time(start_time)} --> {format_srt_time(end_time)}\n"
            f"{sub['text']}\n"
        )
        index += 1

    with open(srt_path, "w") as f:
        f.write("\n".join(entries) + "\n")

    return srt_path


# ═══════════════════════════════════════════════════════════════════
# Xfade assembly (AICB: concatWithTransitions)
# ═══════════════════════════════════════════════════════════════════

def map_transition(t: str) -> str:
    """Map our transition type to ffmpeg xfade transition name."""
    mapped = TRANSITION_MAP.get(t.lower(), DEFAULT_TRANSITION)
    if mapped == "cut":
        return "fade"
    return mapped


def concat_with_transitions(
    video_paths: List[Path],
    transitions: List[str],
    shot_durations: List[float],
    output_path: Path,
    xfade_duration: float = DEFAULT_XFADE_DURATION,
):
    """
    Concatenate videos with xfade transitions (AICB concatWithTransitions).
    
    video_paths: N paths
    transitions: N-1 transitions between adjacent clips
    shot_durations: N durations (actual ffprobe durations)
    """
    if len(video_paths) == 0:
        return

    # Single video: just copy
    if len(video_paths) == 1:
        import shutil
        shutil.copy2(str(video_paths[0]), str(output_path))
        return

    # All cuts: use fast concat demuxer
    all_cuts = all(TRANSITION_MAP.get(t.lower(), "") == "cut" for t in transitions)
    if all_cuts:
        concat_list = output_path.parent / f"_concat_{output_path.stem}.txt"
        with open(concat_list, "w") as f:
            for p in video_paths:
                f.write(f"file '{p.absolute()}'\n")
        subprocess.run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", str(concat_list), "-c", "copy", str(output_path),
        ], check=True, capture_output=True)
        concat_list.unlink(missing_ok=True)
        return

    # Mixed transitions: xfade filter chain
    cmd = ["ffmpeg", "-y"]
    for vp in video_paths:
        cmd.extend(["-i", str(vp)])

    filter_parts = []
    prev_label = "0:v"
    cumulative_offset = 0.0

    for i, t in enumerate(transitions):
        duration = shot_durations[i]
        out_label = f"v{i}" if i < len(transitions) - 1 else "vout"

        if t == "cut":
            # Hard cut: xfade with duration=0 at exact boundary
            offset = cumulative_offset + duration
            filter_parts.append(
                f"[{prev_label}][{i + 1}:v]xfade=transition=fade:duration=0"
                f":offset={offset:.3f}[{out_label}]"
            )
            cumulative_offset = offset
        else:
            xfade_name = map_transition(t)
            offset = cumulative_offset + duration - xfade_duration
            filter_parts.append(
                f"[{prev_label}][{i + 1}:v]xfade=transition={xfade_name}"
                f":duration={xfade_duration}:offset={offset:.3f}[{out_label}]"
            )
            cumulative_offset = offset

        prev_label = out_label

    cmd.extend([
        "-filter_complex", ";".join(filter_parts),
        "-map", f"[{prev_label}]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-r", str(FPS),
        str(output_path),
    ])

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        # Fallback to simple concat
        print(f"  ⚠️ Xfade failed, falling back to fast concat: {result.stderr[-200:]}")
        concat_list = output_path.parent / f"_concat_fallback_{output_path.stem}.txt"
        with open(concat_list, "w") as f:
            for p in video_paths:
                f.write(f"file '{p.absolute()}'\n")
        subprocess.run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", str(concat_list), "-c", "copy", str(output_path),
        ], check=True)
        concat_list.unlink(missing_ok=True)


# ═══════════════════════════════════════════════════════════════════
# Main assembly (AICB: assembleVideo)
# ═══════════════════════════════════════════════════════════════════

def escape_subtitle_path(p: str) -> str:
    """Escape path for ffmpeg subtitles filter."""
    return p.replace("\\", "/").replace(":", "\\:").replace("'", "'\\\\\\''")


def assemble_video(
    video_paths: List[Path],
    shot_transitions: List[str],
    shot_durations: List[float],
    output_path: Path,
    project_id: str,
    output_dir: Path,
    subtitles: Optional[List[dict]] = None,
    title_text: Optional[str] = None,
    credits_text: Optional[str] = None,
    bgm_path: Optional[str] = None,
    bgm_volume: float = 0.3,
    xfade_duration: float = DEFAULT_XFADE_DURATION,
):
    """
    Full AICB assembleVideo pipeline.

    Builds: title → [fade_in] → s1 → [t1] → s2 → ... → sN → [fade_out] → credits
    Then: subtitle burn → BGM mix
    """
    all_paths = []
    all_durations = []

    # Add title card
    if title_text:
        title_path = generate_title_card(output_dir, title_text, project_id)
        all_paths.append(title_path)
        all_durations.append(TITLE_DURATION)

    # Add shot clips
    for vp, dur in zip(video_paths, shot_durations):
        all_paths.append(vp)
        all_durations.append(dur)

    # Add credits card
    if credits_text:
        credits_path = generate_credits_card(output_dir, credits_text, project_id)
        all_paths.append(credits_path)
        all_durations.append(CREDITS_DURATION)

    # Build transition array: N-1 for N clips
    # title→s1 uses fade_in, s1→s2 uses shot's transitionOut, sN→credits uses fade_out
    all_transitions = []
    if len(all_paths) >= 2:
        if title_text:
            all_transitions.append("fade_in")
        all_transitions.extend(shot_transitions[:len(all_paths) - len(all_transitions) - (1 if credits_text else 0)])
        if credits_text and len(all_transitions) < len(all_paths) - 1:
            all_transitions.append("fade_out")
        # Fill remaining with cut
        while len(all_transitions) < len(all_paths) - 1:
            all_transitions.append("cut")

    # Step 1: Concatenate with transitions
    concat_output = output_dir / f"{project_id}-concat-tmp.mp4"
    concat_with_transitions(all_paths, all_transitions, all_durations,
                            concat_output, xfade_duration)
    print(f"  ✅ Concat: {len(all_paths)} clips → {concat_output.stat().st_size/1024/1024:.1f}MB")

    # Step 2: Burn in subtitles
    srt_path = None
    if subtitles and len(subtitles) > 0:
        srt_path = generate_srt(subtitles, all_durations, output_path)
        escaped_srt = escape_subtitle_path(str(srt_path.absolute()))

        try:
            subprocess.run([
                "ffmpeg", "-y",
                "-i", str(concat_output),
                "-vf", f"subtitles='{escaped_srt}'",
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-c:a", "aac",
                str(output_path),
            ], check=True, capture_output=True)
            concat_output.unlink(missing_ok=True)
            print(f"  ✅ Subtitles burned: {len(subtitles)} entries")
        except subprocess.CalledProcessError as e:
            # Fallback: use concat output directly
            print(f"  ⚠️ Subtitle burn failed, using concat output: {e.stderr[-200:] if e.stderr else e}")
            import shutil
            shutil.move(str(concat_output), str(output_path))
    else:
        import shutil
        shutil.move(str(concat_output), str(output_path))

    # Step 3: Mix BGM
    if bgm_path and os.path.exists(bgm_path):
        bgm_output = output_dir / f"{project_id}-final-bgm.mp4"
        try:
            subprocess.run([
                "ffmpeg", "-y",
                "-i", str(output_path),
                "-i", bgm_path,
                "-map", "0:v",
                "-map", "1:a",
                "-c:v", "copy",
                "-c:a", "aac",
                "-af", f"volume={bgm_volume}",
                "-shortest",
                str(bgm_output),
            ], check=True, capture_output=True)
            output_path.unlink(missing_ok=True)
            import shutil
            shutil.move(str(bgm_output), str(output_path))
            print(f"  ✅ BGM mixed: volume={bgm_volume}")
        except subprocess.CalledProcessError as e:
            print(f"  ⚠️ BGM mix failed, skipping: {e.stderr[-200:] if e.stderr else e}")

    return output_path, srt_path


# ═══════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Stage 7: 视频组装 (AICB full)")
    parser.add_argument("--project", "-P", required=True, help="项目名")
    parser.add_argument("--no-title", action="store_true", help="跳过标题卡")
    parser.add_argument("--transition-duration", "-t", type=float,
                        default=DEFAULT_XFADE_DURATION,
                        help=f"转场时长(秒) (默认: {DEFAULT_XFADE_DURATION})")
    parser.add_argument("--no-xfade", action="store_true",
                        help="禁用 xfade，强制 fast concat")
    parser.add_argument("--bgm", type=str, default=None, help="背景音乐文件路径")
    parser.add_argument("--bgm-volume", type=float, default=0.3,
                        help="BGM 音量 (0.0-1.0, 默认: 0.3)")
    parser.add_argument("--with-subtitles", action="store_true",
                        help="在组装阶段烧录字幕（粗略时间轴，S9 会精修）")
    parser.add_argument("--width", type=int, default=W, help=f"宽度 (默认: {W})")
    parser.add_argument("--height", type=int, default=H, help=f"高度 (默认: {H})")
    args = parser.parse_args()

    global W, H
    W, H = args.width, args.height

    pd = Path(__file__).parent.parent / "projects" / args.project

    # Load shots
    s4_path = pd / "s4_shots.json"
    if not s4_path.exists():
        print(f"❌ {s4_path} not found. Run S4 first.")
        sys.exit(1)
    s4 = json.load(open(s4_path))

    # Load characters for dialogue info
    s2_path = pd / "s2_characters.json"
    s2 = json.load(open(s2_path)) if s2_path.exists() else {"characters": []}

    videos_dir = pd / "s6_videos"
    if not videos_dir.exists():
        print(f"❌ s6_videos/ not found. Run S6 first.")
        sys.exit(1)

    sm = get_state_manager()
    sm.mark_running(args.project, "s7_assemble",
                    transition_duration=args.transition_duration)

    # ── Collect clips ──
    total_shots = sum(len(scene["shots"]) for scene in s4["scenes"])
    video_paths = []
    shot_durations = []
    transitions = []
    subtitles = []

    for scene in s4["scenes"]:
        for shot in scene["shots"]:
            sn = shot["shotNumber"]
            clip = videos_dir / f"s{sn:02d}.mp4"
            if not clip.exists():
                print(f"  ⚠️ Missing clip: s{sn:02d}.mp4")
                continue

            video_paths.append(clip)
            dur = get_clip_duration(clip)
            shot_durations.append(dur)
            transit = shot.get("transitionOut", "cut")
            transitions.append(transit)

            # Build subtitle entries for this shot
            shot_dialogues = shot.get("dialogues", [])
            for di, d in enumerate(shot_dialogues):
                subtitles.append({
                    "shotSequence": len(video_paths),  # 1-based
                    "text": d.get("text", ""),
                    "dialogueSequence": di,
                    "dialogueCount": len(shot_dialogues),
                    "startRatio": d.get("startRatio"),
                    "endRatio": d.get("endRatio"),
                })

    if not video_paths:
        print("❌ No clips found.")
        sys.exit(1)

    print(f"\nClips: {len(video_paths)} shots")
    for i, (p, d, t) in enumerate(zip(video_paths, shot_durations, transitions)):
        print(f"  {i}: {p.name:30s} ({d:.1f}s, transition: {t})")

    # ── Assemble ──
    title = None if args.no_title else s4.get("title", args.project)
    credits = "—— 完 ——"
    output = pd / "s7_assembled.mp4"

    print(f"\nAssembling → {output} (xfade={args.transition_duration}s)...")

    video_path, srt_path = assemble_video(
        video_paths=video_paths,
        shot_transitions=transitions,
        shot_durations=shot_durations,
        output_path=output,
        project_id=args.project,
        output_dir=pd,
        subtitles=subtitles if (args.with_subtitles and subtitles) else None,
        title_text=title,
        credits_text=credits,
        bgm_path=args.bgm,
        bgm_volume=args.bgm_volume,
        xfade_duration=args.transition_duration if not args.no_xfade else 0,
    )

    size_mb = output.stat().st_size / (1024 * 1024)
    print(f"✅ S7: {size_mb:.1f}MB, {total_shots} shots → {output}")
    if srt_path:
        print(f"   SRT: {srt_path}")

    # Register asset
    am = get_asset_manager()
    am.register(
        project=args.project,
        asset_type="assembled_video",
        shot_id=f"project",
        source_path=output,
        relative_dir=".",
        metadata={
            "shots": total_shots,
            "transition": args.transition_duration,
            "bgm": bool(args.bgm),
            "subtitles": len(subtitles),
        },
    )

    sm.mark_completed(args.project, "s7_assemble",
                      size_mb=f"{size_mb:.1f}",
                      clips=total_shots,
                      transition=args.transition_duration)


if __name__ == "__main__":
    main()