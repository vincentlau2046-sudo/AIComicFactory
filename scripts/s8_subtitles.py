#!/usr/bin/env python3
"""scripts/s8_subtitles.py — Stage 8: SRT Subtitle Generation (AICB generateSrtFile)

Extracts dialogue timing from s4_shots.json with startRatio/endRatio support,
generates SRT file matching AICB format.

Usage:
    python scripts/s8_subtitles.py --project last_bento
    python scripts/s8_subtitles.py --project last_bento --output subtitles.srt
"""

import json, sys, argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from core.state_manager import get_state_manager


def fmt_srt_time(seconds: float) -> str:
    """Format seconds to SRT time: HH:MM:SS,mmm."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def clean_text(text: str) -> str:
    """Clean dialogue text for TTS/subtitle consistency."""
    # TTS bans: ellipsis, em-dash, enumeration comma
    return text.replace("……", ",").replace("——", ",").replace("、", ",")


def generate_srt(dialogues: list, shot_start_times: list, shot_durations: list,
                 output_path: Path):
    """
    Generate SRT file with precise shot-level timing (AICB generateSrtFile).
    
    dialogues: list of {shotSequence, text, character, dialogueSequence, dialogueCount, startRatio?, endRatio?}
    shot_start_times: cumulative start time of each shot
    shot_durations: duration of each shot
    """
    entries = []
    index = 1

    for sub in dialogues:
        shot_idx = sub["shotSequence"] - 1  # 0-based
        if shot_idx < 0 or shot_idx >= len(shot_durations):
            continue

        shot_start = shot_start_times[shot_idx]
        shot_dur = shot_durations[shot_idx]

        if sub.get("startRatio") is not None and sub.get("endRatio") is not None:
            # Precise timing from shot data
            start_time = shot_start + shot_dur * sub["startRatio"]
            end_time = shot_start + shot_dur * sub["endRatio"]
        else:
            # Auto-distribute within shot duration
            count = sub.get("dialogueCount", 1) or 1
            seq = sub.get("dialogueSequence", 0)
            segment_dur = shot_dur / count
            start_time = shot_start + segment_dur * seq
            end_time = start_time + segment_dur

        text = clean_text(sub["text"])
        entries.append(
            f"{index}\n"
            f"{fmt_srt_time(start_time)} --> {fmt_srt_time(end_time)}\n"
            f"{sub['character']}: {text}\n"
        )
        index += 1

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(entries) + "\n")

    return output_path


def extract_dialogues_from_shots(s4_data: dict, title_offset: float = 0.0) -> tuple:
    """
    Extract dialogues and shot timing from s4_shots.json.
    
    Returns (dialogues_list, shot_start_times, shot_durations)
    """
    dialogues = []
    shot_durations = []
    current_time = title_offset

    for scene in s4_data.get("scenes", []):
        for shot in scene.get("shots", []):
            dur = shot.get("duration", 5.0)
            shot_durations.append(dur)

            shot_index = shot.get("shotNumber", 0)
            shot_dialogues = shot.get("dialogues", [])

            for di, d in enumerate(shot_dialogues):
                dialogues.append({
                    "shotSequence": shot_index,
                    "character": d.get("character", d.get("characterName", "")),
                    "text": d.get("text", ""),
                    "dialogueSequence": di,
                    "dialogueCount": len(shot_dialogues),
                    "startRatio": d.get("startRatio"),
                    "endRatio": d.get("endRatio"),
                })

    # Calculate cumulative start times
    shot_start_times = []
    cumulative = title_offset
    for dur in shot_durations:
        shot_start_times.append(cumulative)
        cumulative += dur

    return dialogues, shot_start_times, shot_durations


def main():
    parser = argparse.ArgumentParser(description="Stage 8: SRT 字幕生成 (AICB)")
    parser.add_argument("--project", "-P", required=True, help="项目名")
    parser.add_argument("--output", "-o", default=None, help="输出 SRT 文件路径 (默认: s8_subtitles.srt)")
    parser.add_argument("--title-offset", type=float, default=3.0,
                        help="标题卡时长(秒) — 时间轴偏移量")
    args = parser.parse_args()

    pd = Path(__file__).parent.parent / "projects" / args.project
    s4_path = pd / "s4_shots.json"
    if not s4_path.exists():
        print(f"❌ {s4_path} not found. Run S4 first.")
        sys.exit(1)

    sm = get_state_manager()
    sm.mark_running(args.project, "s8_subtitles")

    s4 = json.load(open(s4_path))
    dialogues, shot_start_times, shot_durations = extract_dialogues_from_shots(
        s4, title_offset=args.title_offset
    )

    output = Path(args.output) if args.output else pd / "s8_subtitles.srt"
    generate_srt(dialogues, shot_start_times, shot_durations, output)

    # Print summary
    total_duration = shot_start_times[-1] + shot_durations[-1] if shot_start_times else 0
    print(f"✅ S8: {len(dialogues)} dialogues → {output}")
    print(f"   Duration: {total_duration:.1f}s")
    for d in dialogues[:5]:
        print(f"   [{d['shotSequence']}] {fmt_srt_time(shot_start_times[d['shotSequence']-1] + shot_durations[d['shotSequence']-1] * (d.get('startRatio') or 0))}: {d['character']}: {clean_text(d['text'])[:50]}")
    if len(dialogues) > 5:
        print(f"   ... +{len(dialogues) - 5} more")

    sm.mark_completed(args.project, "s8_subtitles",
                      dialogues=len(dialogues),
                      duration=f"{total_duration:.1f}s")


if __name__ == "__main__":
    main()