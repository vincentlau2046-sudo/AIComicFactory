#!/usr/bin/env python3
"""scripts/s8_subtitles.py — Stage 8: 字幕生成与烧录

从 s4_shots.json 提取对话时间轴,生成 ASS 字幕并烧入视频。

用法:
    python scripts/s8_subtitles.py --project last_bento
    python scripts/s8_subtitles.py --project last_bento --input s7_assembled.mp4
"""

import json, sys, argparse, subprocess
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from core.state_manager import get_state_manager

W, H = 896, 512
FPS = 25


def fmt_time(sec: float) -> str:
    """Format seconds to ASS time string H:MM:SS.xx"""
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def clean_text(text: str) -> str:
    """Clean dialogue text for ASS (remove characters that break rendering)."""
    return text.replace("……", ",").replace("——", ",").replace("、", ",")


def extract_dialogues(project_dir: Path, title_offset: float = 3.0) -> list:
    """
    Extract dialogues from s4_shots.json with cumulative timing.
    Returns list of {character, text, start, end}.
    """
    s4 = json.load(open(project_dir / "s4_shots.json"))
    s1 = json.load(open(project_dir / "s1_parsed.json"))

    current_time = title_offset
    dialogues = []

    for scene in s4["scenes"]:
        for shot in scene["shots"]:
            dur = shot.get("duration", 5.0)
            for d in shot.get("dialogues", []):
                dialogues.append({
                    "character": d["character"],
                    "text": d["text"],
                    "start": current_time,
                    "end": current_time + dur,
                })
            current_time += dur

    return dialogues


def generate_ass(dialogues: list, output_path: Path, title: str = ""):
    """Generate ASS subtitle file from dialogue list."""
    with open(output_path, "w") as f:
        f.write(f"""[Script Info]
Title: {title}
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: D,Noto Sans CJK SC,28,&H00FFFFFF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,2,0,2,20,20,30,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
""")
        for d in dialogues:
            text = clean_text(d["text"])
            f.write(
                f"Dialogue: 0,{fmt_time(d['start'])},{fmt_time(d['end'])},"
                f"D,{d['character']},0,0,0,,{text}\n"
            )


def burn_subtitles(video_path: Path, ass_path: Path, output_path: Path):
    """Burn ASS subtitles into video using ffmpeg."""
    subprocess.run([
        "ffmpeg", "-y", "-i", str(video_path),
        "-vf", f"ass={ass_path}",
        "-c:v", "libx264", "-crf", "23", "-preset", "fast",
        "-c:a", "copy", str(output_path),
    ], check=True)


def main():
    parser = argparse.ArgumentParser(description="Stage 8: 字幕生成与烧录")
    parser.add_argument("--project", "-P", required=True, help="项目名")
    parser.add_argument("--input", default="s7_assembled.mp4", help="输入视频文件名")
    parser.add_argument("--ass-only", action="store_true", help="只生成 ASS，不烧录")
    parser.add_argument("--title-offset", type=float, default=3.0,
                        help="标题卡时长(秒) — 对话时间轴偏移量")
    args = parser.parse_args()

    pd = Path(__file__).parent.parent / "projects" / args.project
    video_path = pd / args.input

    if not video_path.exists():
        print(f"❌ Input video not found: {video_path}")
        sys.exit(1)

    sm = get_state_manager()
    sm.mark_running(args.project, "s8_subtitles")

    # Extract dialogues with timing
    dialogues = extract_dialogues(pd, title_offset=args.title_offset)
    print(f"Dialogues: {len(dialogues)}")
    for d in dialogues:
        print(f"  {d['start']:.1f}-{d['end']:.1f}s: {d['character']}: {clean_text(d['text'])[:50]}")

    # Generate ASS
    s4 = json.load(open(pd / "s4_shots.json"))
    ass_path = pd / "s8_subtitles.ass"
    generate_ass(dialogues, ass_path, title=s4.get("title", args.project))
    print(f"ASS: {ass_path}")

    if args.ass_only:
        sm.mark_completed(args.project, "s8_subtitles", tts="ass_only")
        return

    # Burn into video
    output = pd / "s7_with_subtitles.mp4"
    print(f"Burning subtitles → {output}...")
    burn_subtitles(video_path, ass_path, output)

    size_mb = output.stat().st_size / (1024 * 1024)
    print(f"✅ S8: {size_mb:.1f}MB → {output}")

    sm.mark_completed(args.project, "s8_subtitles", tts="subtitles_burned", size_mb=f"{size_mb:.1f}")


if __name__ == "__main__":
    main()