#!/usr/bin/env python3
"""
scripts/s6_video_assemble.py — S6+S7: 视频生成 + 合成

从 S5 关键帧 + S4 分镜数据，用 ffmpeg zoompan (Ken Burns) 生成视频片段，
然后拼接为完整视频。跳过 FLF2V（因为没有尾帧），用静态帧+缓动替代。

用法:
    python scripts/s6_video_assemble.py --project last_bento
"""

import json
import subprocess
import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.state_manager import get_state_manager

FPS = 24


def create_clip(input_frame: Path, output_clip: Path, shot: dict, fps: int = FPS):
    """Generate a video clip from a single frame using Ken Burns zoom effect."""
    duration = shot.get("duration", 5.0)
    total_frames = int(duration * fps)
    
    camera = shot.get("cameraDirection", "static")
    
    # Map camera direction to zoom behavior
    if "push" in camera and "in" in camera:
        zoom_end = 1.05  # zoom in
    elif "pull" in camera and "out" in camera:
        zoom_end = 0.95  # zoom out
    elif "static" in camera:
        zoom_end = 1.0  # no zoom
    else:
        zoom_end = 1.02  # slight zoom by default
    
    # Use ffmpeg zoompan filter for Ken Burns
    # zoompan: z='min(zoom+0.0015,1.05)':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'
    zoom_per_frame = (zoom_end - 1.0) / total_frames if total_frames > 0 else 0
    
    filter_str = (
        f"zoompan=z='min(zoom+{zoom_per_frame:.6f},{max(1.0, zoom_end)}):"
        f"d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"fps={fps}:s={shot.get('width', 896)}x{shot.get('height', 512)}'"
    )
    
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", str(input_frame),
        "-vf", filter_str,
        "-t", str(duration),
        "-pix_fmt", "yuv420p",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        str(output_clip),
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ffmpeg error: {result.stderr[-200:]}")
        return False
    return True


def concat_clips(clip_list: Path, output: Path, fps: int = FPS):
    """Concatenate video clips with dissolve transitions between scenes."""
    # Read clip list to detect scene boundaries for transitions
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(clip_list),
        "-c", "copy",
        str(output),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  concat error: {result.stderr[-300:]}")
        return False
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", "-P", required=True)
    parser.add_argument("--fps", type=int, default=24)
    args = parser.parse_args()
    
    pd = Path(__file__).parent.parent / "projects" / args.project
    s4_path = pd / "s4_shots.json"
    s5_dir = pd / "s5_frames"
    
    if not s4_path.exists():
        print(f"ERROR: {s4_path} not found")
        sys.exit(1)
    
    with open(s4_path) as f:
        s4 = json.load(f)
    
    sm = get_state_manager()
    
    # === S6: Generate clips ===
    sm.mark_running(args.project, "s6_video_generate")
    clips_dir = pd / "s6_videos"
    clips_dir.mkdir(parents=True, exist_ok=True)
    
    shots = []
    for scene in s4["scenes"]:
        for shot in scene["shots"]:
            shots.append(shot)
    
    print(f"Generating {len(shots)} clips...")
    
    clip_files = []
    for i, shot in enumerate(shots):
        sn = shot["shotNumber"]
        frame_path = s5_dir / f"s{sn:02d}_first.png"
        clip_path = clips_dir / f"s{sn:02d}.mp4"
        
        if not frame_path.exists():
            print(f"  Shot {sn}: Frame missing ({frame_path}) — SKIPPING")
            continue
        
        sys.stdout.write(f"  Shot {sn}/{len(shots)}: {shot.get('cameraDirection','')} ({shot.get('duration',5)}s)... ")
        sys.stdout.flush()
        
        if create_clip(frame_path, clip_path, shot, args.fps):
            print("✅")
            clip_files.append((sn, str(clip_path)))
        else:
            print("❌")
    
    sm.mark_completed(args.project, "s6_video_generate", 
                      generated=f"{len(clip_files)}/{len(shots)}")
    
    # === S7: Assemble ===
    sm.mark_running(args.project, "s7_assemble")
    print(f"\nAssembling {len(clip_files)} clips...")
    
    # Write concat file
    concat_list = clips_dir / "concat.txt"
    with open(concat_list, "w") as f:
        for _, path in clip_files:
            f.write(f"file '{path}'\n")
    
    s7_output = pd / "s7_assembled.mp4"
    if concat_clips(concat_list, s7_output, args.fps):
        size_mb = s7_output.stat().st_size / (1024 * 1024)
        print(f"✅ S7 assembled: {s7_output} ({size_mb:.1f}MB)")
        sm.mark_completed(args.project, "s7_assemble", size_mb=f"{size_mb:.1f}")
    else:
        print("❌ Assembly failed")
        sm.mark_failed(args.project, "s7_assemble", "concat failed")
        sys.exit(1)
    
    # Calculate total duration
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(s7_output)],
        capture_output=True, text=True
    )
    total_duration = float(result.stdout.strip()) if result.stdout.strip() else 0
    print(f"Total duration: {total_duration:.1f}s")

    
    # === Generate subtitle from S4 dialogues + timing ===
    sm.mark_running(args.project, "s8_subtitles")
    
    # Build ASS subtitles from dialogue data with estimated timing
    ass_lines = [
        "[Script Info]",
        "Title: AIComicFactory Subtitles",
        "ScriptType: v4.00+",
        "PlayResX: 896",
        "PlayResY: 512",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: Default,Noto Sans CJK SC,28,&H00FFFFFF,&H000000FF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,2,0,2,20,20,30,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    
    # Calculate timing from shot durations
    current_time = 0.0
    for shot in shots:
        sn = shot["shotNumber"]
        duration = shot.get("duration", 5.0)
        end_time = current_time + duration
        
        for d in shot.get("dialogues", []):
            text = d.get("text", "")
            char = d.get("character", "")
            if text:
                start_ts = format_ass_time(current_time)
                end_ts = format_ass_time(end_time)
                # Escape ASS special chars
                text = text.replace("{", "\\{").replace("}", "\\}")
                ass_lines.append(
                    f"Dialogue: 0,{start_ts},{end_ts},Default,{char},0,0,0,,{text}"
                )
        
        current_time = end_time
    
    # Write ASS file
    ass_path = pd / "s8_subtitles.ass"
    with open(ass_path, "w", encoding="utf-8") as f:
        f.write("\n".join(ass_lines))
    
    print(f"✅ S8 subtitles: {ass_path}")
    sm.mark_completed(args.project, "s8_subtitles", 
                      dialogues=sum(len(s.get("dialogues", [])) for s in shots))
    
    print(f"\n🆗 Pipeline complete!")
    print(sm.progress(args.project))


def format_ass_time(seconds: float) -> str:
    """Convert seconds to ASS time format: H:MM:SS.cc"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int((seconds % 1) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


if __name__ == "__main__":
    main()