#!/usr/bin/env python3
"""
scripts/s8_subtitles.py — Stage 8: 字幕生成 (统一时间轴)

使用 core/timeline.py 的共享时间轴计算，与 S7/S9 保持一致。
生成 SRT + ASS 双格式字幕文件。

用法:
    python scripts/s8_subtitles.py --project last_bento
    python scripts/s8_subtitles.py --project last_bento --output subtitles.srt
"""

import json, sys, argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from core.state_manager import get_state_manager
from core.timeline import (
    build_timeline_from_project, calc_dialogue_timeline,
    generate_srt, generate_ass, fmt_srt_time, clean_subtitle_text
)


def main():
    parser = argparse.ArgumentParser(description="Stage 8: 字幕生成 (统一时间轴)")
    parser.add_argument("--project", "-P", required=True, help="项目名")
    parser.add_argument("--output", "-o", default=None, help="输出 SRT 文件路径")
    parser.add_argument("--title-duration", type=float, default=3.0,
                        help="标题卡时长(秒)")
    parser.add_argument("--credits-duration", type=float, default=4.0,
                        help="结束卡时长(秒)")
    parser.add_argument("--calibrate", action="store_true", default=True,
                        help="用 ffprobe 校准视频时长 (默认启用)")
    parser.add_argument("--no-calibrate", action="store_true",
                        help="不校准，用 s4 duration")
    args = parser.parse_args()

    pd = Path(__file__).parent.parent / "projects" / args.project
    s4_path = pd / "s4_shots.json"
    if not s4_path.exists():
        print(f"❌ {s4_path} not found. Run S4 first.")
        sys.exit(1)

    sm = get_state_manager()
    sm.mark_running(args.project, "s8_subtitles")

    # 构建统一时间轴
    calibrate = args.calibrate and not args.no_calibrate
    timeline = build_timeline_from_project(
        pd,
        title_duration=args.title_duration,
        credits_duration=args.credits_duration,
        calibrate_with_videos=calibrate,
    )

    s4 = json.load(open(s4_path))
    dialogue_entries = calc_dialogue_timeline(s4, timeline)

    # 生成 SRT
    srt_path = Path(args.output) if args.output else pd / "s8_subtitles.srt"
    generate_srt(dialogue_entries, srt_path)

    # 生成 ASS (供 S9 使用)
    ass_path = pd / "s8_subtitles.ass"
    generate_ass(dialogue_entries, ass_path)

    # 打印摘要
    total_duration = timeline.total_duration
    print(f"✅ S8: {len(dialogue_entries)} dialogues → {srt_path}")
    print(f"   ASS: {ass_path}")
    print(f"   Duration: {total_duration:.1f}s (title={args.title_duration}s, credits={args.credits_duration}s)")
    for d in dialogue_entries[:5]:
        print(f"   [{d['shot']:02d}] {fmt_srt_time(d['start_s'])}: {d['character']}: {clean_subtitle_text(d['text'])[:50]}")
    if len(dialogue_entries) > 5:
        print(f"   ... +{len(dialogue_entries) - 5} more")

    sm.mark_completed(args.project, "s8_subtitles",
                      dialogues=len(dialogue_entries),
                      duration=f"{total_duration:.1f}s")


if __name__ == "__main__":
    main()
