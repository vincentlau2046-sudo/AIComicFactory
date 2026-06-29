#!/usr/bin/env python3
"""scripts/s7_video_assemble.py — Stage 7: 视频拼接 + 7种转场

从 s6_videos/ 读取 MP4 clips，按 shot 顺序拼接，支持 7 种 AICB 转场效果。
使用 FFmpeg xfade filter（需重编码，比 concat 慢但支持平滑转场）。

转场映射 (transitionOut → xfade transition):
  cut       → 直切 (concat, 无 xfade)
  dissolve  → 溶解 (dissolve)
  fade_in   → 淡入 (fade)
  fade_out  → 淡出 (fadeblack)
  wipeleft  → 左擦 (wipeleft)
  slideright→ 右滑 (slideright)
  circleopen→ 圆形展开 (circleopen)

用法:
    python scripts/s7_video_assemble.py --project last_bento
    python scripts/s7_video_assemble.py --project last_bento --transition-duration 0.8
    python scripts/s7_video_assemble.py --project last_bento --no-title
"""

import json
import sys
import argparse
import subprocess
import shutil
from pathlib import Path
from typing import List, Tuple, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.state_manager import get_state_manager

# ═══════════════════════════════════════════════════════════════════
# Config
# ═══════════════════════════════════════════════════════════════════

W, H = 896, 512
FPS = 25
TITLE_DURATION = 3.0
END_DURATION = 4.0
DEFAULT_TRANSITION_DURATION = 0.5
FONT_PATH = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"

# AICB → xfade transition name mapping
TRANSITION_MAP = {
    "cut":        None,          # No xfade, fast concat
    "dissolve":   "dissolve",
    "fade_in":    "fade",
    "fade_out":   "fadeblack",
    "wipeleft":   "wipeleft",
    "slideright": "slideright",
    "circleopen": "circleopen",
}

# Fallback for unknown transition types
DEFAULT_TRANSITION = "dissolve"


# ═══════════════════════════════════════════════════════════════════
# Card generation (unchanged)
# ═══════════════════════════════════════════════════════════════════

def generate_title_card(pd: Path, title: str, output_mp4: Path) -> Path:
    """Pillow → title card PNG → MP4 with fade-in."""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (W, H), (20, 20, 30))
    draw = ImageDraw.Draw(img)
    try:
        font_title = ImageFont.truetype(FONT_PATH, 48)
        font_sub = ImageFont.truetype(FONT_PATH, 24)
    except (OSError, IOError):
        font_title = ImageFont.load_default()
        font_sub = font_title

    bbox = draw.textbbox((0, 0), title, font=font_title)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((W - tw) / 2, H / 2 - th - 10), title, fill=(255, 230, 180), font=font_title)

    subtitle = "—— 一个关于告别与延续的故事 ——"
    bbox2 = draw.textbbox((0, 0), subtitle, font=font_sub)
    sw, sh = bbox2[2] - bbox2[0], bbox2[3] - bbox2[1]
    draw.text(((W - sw) / 2, H / 2 + 20), subtitle, fill=(180, 180, 200), font=font_sub)

    png_path = pd / "s7_title.png"
    img.save(str(png_path))

    subprocess.run([
        "ffmpeg", "-y", "-loop", "1", "-i", str(png_path),
        "-c:v", "libx264", "-t", str(TITLE_DURATION), "-pix_fmt", "yuv420p",
        "-vf", f"scale={W}:{H},fade=t=in:d=1", str(output_mp4),
    ], check=True, capture_output=True)
    return output_mp4


def generate_end_card(pd: Path, output_mp4: Path) -> Path:
    """Pillow → end card PNG → MP4 with fade-out."""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (W, H), (15, 15, 25))
    draw = ImageDraw.Draw(img)
    try:
        font_end = ImageFont.truetype(FONT_PATH, 36)
    except (OSError, IOError):
        font_end = ImageFont.load_default()

    end_text = "—— 完 ——"
    bbox = draw.textbbox((0, 0), end_text, font=font_end)
    ew, eh = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((W - ew) / 2, (H - eh) / 2), end_text, fill=(200, 200, 220), font=font_end)

    png_path = pd / "s7_end.png"
    img.save(str(png_path))

    subprocess.run([
        "ffmpeg", "-y", "-loop", "1", "-i", str(png_path),
        "-c:v", "libx264", "-t", str(END_DURATION), "-pix_fmt", "yuv420p",
        "-vf", f"scale={W}:{H},fade=t=out:d=1", str(output_mp4),
    ], check=True, capture_output=True)
    return output_mp4


# ═══════════════════════════════════════════════════════════════════
# Transition assembly
# ═══════════════════════════════════════════════════════════════════

def get_clip_duration(clip_path: Path) -> float:
    """Get clip duration in seconds using ffprobe."""
    result = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
        str(clip_path),
    ], capture_output=True, text=True)
    return float(result.stdout.strip())


def get_xfade_name(transition: str) -> Optional[str]:
    """Map AICB transition name to xfade filter name. Returns None for cut."""
    mapped = TRANSITION_MAP.get(transition.lower(), DEFAULT_TRANSITION)
    if transition.lower() == "cut":
        return None
    return mapped


def build_xfade_filtergraph(
    clips: List[Tuple[Path, str]],  # (path, transitionOut)
    transition_duration: float,
) -> Tuple[str, str]:
    """
    Build ffmpeg xfade filtergraph for N clips with transitions.

    Returns (filter_complex_string, last_output_label).
    """
    if len(clips) == 0:
        raise ValueError("No clips to assemble")

    # Single clip: no transition needed
    if len(clips) == 1:
        return "", "0"

    filter_parts = []
    prev_label = "[0]"

    cumulative_offset = 0.0
    durations = [get_clip_duration(p) for p, _ in clips]

    for i in range(1, len(clips)):
        clip_path, transition = clips[i]

        xfade = get_xfade_name(transition)
        if xfade is None:
            # Cut: no xfade, just use next clip
            prev_label = f"[{i}]"
            continue

        # Offset: cumulative duration up to current clip minus transition overlap
        offset = sum(durations[:i]) - transition_duration * (i + 1 - len([c for c in clips[:i] if get_xfade_name(c[1]) is None]))

        # Recalculate offset more carefully
        offset = cumulative_offset + durations[i - 1] - transition_duration
        cumulative_offset += durations[i - 1] - transition_duration

        out_label = f"[v{i}]"
        filter_parts.append(
            f"{prev_label}[{i}]xfade=transition={xfade}:duration={transition_duration}"
            f":offset={offset:.2f}{out_label}"
        )
        prev_label = out_label

    if not filter_parts:
        return "", "0"

    return ";\n".join(filter_parts), prev_label


def assemble_with_xfade(
    output: Path,
    clips: List[Tuple[Path, str]],
    transition_duration: float = DEFAULT_TRANSITION_DURATION,
) -> None:
    """
    Assemble clips using xfade transitions.

    Falls back to simple concat if only 1 clip or all cuts.
    """
    if len(clips) == 0:
        return

    # Check if all transitions are cuts → use fast concat
    all_cuts = all(
        get_xfade_name(transition) is None
        for _, transition in clips[1:]
    )
    if all_cuts or len(clips) == 1:
        simple_concat(output, [p for p, _ in clips])
        return

    # Build xfade command
    inputs = []
    for clip_path, _ in clips:
        inputs.extend(["-i", str(clip_path)])

    filtergraph, last_label = build_xfade_filtergraph(clips, transition_duration)

    if not filtergraph:
        # Fallback: only 1 clip or first clip with remaining cuts
        simple_concat(output, [p for p, _ in clips])
        return

    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", filtergraph,
        "-map", last_label,
        "-c:v", "libx264", "-preset", "medium",
        "-pix_fmt", "yuv420p",
        "-r", str(FPS),
        str(output),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        # Fallback: try simple concat
        print(f"  ⚠️ xfade failed ({result.returncode}), falling back to concat")
        print(f"  stderr: {result.stderr[:200]}")
        simple_concat(output, [p for p, _ in clips])


def simple_concat(output: Path, clip_paths: List[Path]) -> None:
    """Simple FFmpeg concat (no transition effects)."""
    concat_file = output.parent / "s7_concat.txt"
    with open(concat_file, "w") as f:
        for clip in clip_paths:
            f.write(f"file '{clip}'\n")

    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(concat_file),
        "-c", "copy", str(output),
    ], check=True)


# ═══════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Stage 7: 视频拼接 (7种转场)")
    parser.add_argument("--project", "-P", required=True, help="项目名")
    parser.add_argument("--no-title", action="store_true", help="跳过标题卡")
    parser.add_argument("--transition-duration", "-t", type=float,
                        default=DEFAULT_TRANSITION_DURATION,
                        help=f"转场时长(秒) (默认: {DEFAULT_TRANSITION_DURATION})")
    parser.add_argument("--no-xfade", action="store_true",
                        help="禁用 xfade，强制使用 fast concat")
    args = parser.parse_args()

    pd = Path(__file__).parent.parent / "projects" / args.project

    # Load shots to get transition info
    s4_path = pd / "s4_shots.json"
    if not s4_path.exists():
        print(f"❌ {s4_path} not found. Run S4 first.")
        sys.exit(1)
    s4 = json.load(open(s4_path))

    videos_dir = pd / "s6_videos"
    if not videos_dir.exists():
        print(f"❌ s6_videos/ not found. Run S6 first.")
        sys.exit(1)

    sm = get_state_manager()
    sm.mark_running(args.project, "s7_assemble",
                    transition_duration=args.transition_duration)

    # ── Generate cards ──
    if not args.no_title:
        title = s4.get("title", args.project)
        print(f"Generating title card: {title}")
        title_mp4 = pd / "s7_title.mp4"
        generate_title_card(pd, title, title_mp4)
    else:
        title_mp4 = None

    end_mp4 = pd / "s7_end.mp4"
    print("Generating end card...")
    generate_end_card(pd, end_mp4)

    # ── Collect clips with transition info ──
    # Build ordered list: title → shots → end card
    clips: List[Tuple[Path, str]] = []

    if title_mp4:
        clips.append((title_mp4, "fade_in"))  # Title fades into first clip

    for scene in s4["scenes"]:
        for shot in scene["shots"]:
            sn = shot["shotNumber"]
            clip = videos_dir / f"s{sn:02d}.mp4"
            if clip.exists():
                transit = shot.get("transitionOut", "cut")
                clips.append((clip, transit))
            else:
                print(f"  ⚠️ Missing clip: s{sn:02d}.mp4")

    # End card transition
    if clips:
        clips.append((end_mp4, "fade_out"))

    if not clips:
        print("❌ No clips found.")
        sys.exit(1)

    print(f"\nClips: {len(clips)} items (title + {len(clips)-2} shots + end)")
    for i, (p, t) in enumerate(clips):
        dur = get_clip_duration(p)
        print(f"  {i}: {p.name:30s} ({dur:.1f}s, transition: {t})")

    # ── Assemble ──
    output = pd / "s7_assembled.mp4"
    print(f"\nAssembling → {output} (transition={args.transition_duration}s)...")

    if args.no_xfade:
        simple_concat(output, [p for p, _ in clips])
    else:
        assemble_with_xfade(output, clips, args.transition_duration)

    size_mb = output.stat().st_size / (1024 * 1024)
    shot_count = len(clips) - 2  # Exclude title and end card
    print(f"✅ S7: {size_mb:.1f}MB, {shot_count} shots → {output}")

    sm.mark_completed(args.project, "s7_assemble",
                      size_mb=f"{size_mb:.1f}",
                      clips=shot_count,
                      transition=args.transition_duration)


if __name__ == "__main__":
    main()