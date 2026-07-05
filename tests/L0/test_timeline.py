"""L0: timeline 模块单元测试"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.timeline import (
    ShotTiming,
    Timeline,
    build_timeline,
    calc_dialogue_timeline,
    generate_ass,
    generate_srt,
    fmt_ass_time,
    fmt_srt_time,
    clean_subtitle_text,
)


class TestShotTiming:
    """ShotTiming 数据类"""

    def test_instantiation(self):
        st = ShotTiming(shot_number=1, duration=5.0, start_time=0.0,
                        scene_number=1, transition_in="cut", transition_out="dissolve")
        assert st.shot_number == 1
        assert st.duration == 5.0
        assert st.start_time == 0.0
        assert st.end_time == 5.0
        assert st.scene_number == 1
        assert st.transition_in == "cut"
        assert st.transition_out == "dissolve"

    def test_default_transitions(self):
        st = ShotTiming(shot_number=2, duration=3.0, start_time=5.0)
        assert st.transition_in == "cut"
        assert st.transition_out == "cut"

    def test_end_time_calculated(self):
        st = ShotTiming(shot_number=1, duration=4.0, start_time=2.0)
        assert st.end_time == 6.0

    def test_has_required_fields(self):
        st = ShotTiming(shot_number=3, duration=2.5, start_time=1.5)
        assert hasattr(st, "shot_number")
        assert hasattr(st, "duration")
        assert hasattr(st, "start_time")
        assert hasattr(st, "end_time")


class TestTimeline:
    """Timeline 类"""

    def test_init_empty(self):
        tl = Timeline()
        assert tl.title_duration == 0.0
        assert tl.credits_duration == 0.0
        assert tl.xfade_duration == 0.0
        assert tl.shots == []

    def test_total_duration_with_title_and_credits(self):
        tl = Timeline()
        tl.title_duration = 3.0
        tl.credits_duration = 4.0
        tl.shots = [
            ShotTiming(shot_number=1, duration=5.0, start_time=3.0),
            ShotTiming(shot_number=2, duration=4.0, start_time=8.0),
        ]
        assert tl.total_duration == 16.0  # last.end_time(12.0) + credits(4.0)

    def test_total_duration_no_shots(self):
        tl = Timeline()
        tl.title_duration = 3.0
        tl.credits_duration = 4.0
        assert tl.total_duration == 7.0

    def test_total_duration_setter(self):
        tl = Timeline()
        tl.total_duration = 60.0
        assert tl.total_duration == 60.0

    def test_shots_only_duration(self):
        tl = Timeline()
        tl.shots = [
            ShotTiming(shot_number=1, duration=5.0, start_time=3.0),
            ShotTiming(shot_number=2, duration=4.0, start_time=8.0),
        ]
        assert tl.shots_only_duration == 9.0  # 12 - 3

    def test_shots_only_duration_empty(self):
        tl = Timeline()
        assert tl.shots_only_duration == 0.0

    def test_shot_durations_list(self):
        tl = Timeline()
        tl.shots = [
            ShotTiming(shot_number=1, duration=5.0, start_time=3.0),
            ShotTiming(shot_number=2, duration=4.0, start_time=8.0),
        ]
        assert tl.shot_durations_list() == [5.0, 4.0]

    def test_shot_transitions_list(self):
        tl = Timeline()
        tl.shots = [
            ShotTiming(shot_number=1, duration=5.0, start_time=0.0, transition_out="dissolve"),
            ShotTiming(shot_number=2, duration=4.0, start_time=5.0, transition_out="cut"),
        ]
        assert tl.shot_transitions_list() == ["dissolve", "cut"]


class TestBuildTimeline:
    """build_timeline()"""

    def sample_s4(self):
        return {
            "scenes": [
                {
                    "sceneNumber": 1,
                    "shots": [
                        {"shotNumber": 1, "duration": 5.0, "transitionOut": "dissolve"},
                        {"shotNumber": 2, "duration": 3.0, "transitionOut": "cut"},
                    ]
                },
                {
                    "sceneNumber": 2,
                    "shots": [
                        {"shotNumber": 3, "duration": 4.0, "transitionOut": "dissolve"},
                    ]
                }
            ]
        }

    def test_build_timeline_basic(self):
        s4 = self.sample_s4()
        tl = build_timeline(s4, title_duration=2.0, credits_duration=3.0)
        assert len(tl.shots) == 3
        assert tl.title_duration == 2.0
        assert tl.credits_duration == 3.0

    def test_build_timeline_shot_order(self):
        s4 = self.sample_s4()
        tl = build_timeline(s4)
        shot_numbers = [s.shot_number for s in tl.shots]
        assert shot_numbers == [1, 2, 3]

    def test_build_timeline_start_times(self):
        s4 = self.sample_s4()
        tl = build_timeline(s4, title_duration=2.0)
        # shot 1 starts at title_duration
        assert tl.shots[0].start_time == 2.0
        assert tl.shots[0].duration == 5.0

    def test_build_timeline_empty_scenes(self):
        s4 = {"scenes": []}
        tl = build_timeline(s4, title_duration=2.0, credits_duration=3.0)
        assert tl.shots == []
        assert tl.title_duration == 2.0
        assert tl.credits_duration == 3.0

    def test_build_timeline_empty_shots(self):
        s4 = {"scenes": [{"sceneNumber": 1, "shots": []}]}
        tl = build_timeline(s4)
        assert tl.shots == []


class TestCalcDialogueTimeline:
    """calc_dialogue_timeline()"""

    def test_basic_calculation(self):
        s4 = {
            "scenes": [
                {
                    "sceneNumber": 1,
                    "shots": [
                        {
                            "shotNumber": 1,
                            "dialogues": [
                                {"character": "林雪", "text": "你好",
                                 "startRatio": 0.0, "endRatio": 0.5},
                                {"character": "李慕白", "text": "再见",
                                 "startRatio": 0.6, "endRatio": 1.0},
                            ]
                        }
                    ]
                }
            ]
        }
        tl = Timeline()
        tl.shots = [ShotTiming(shot_number=1, duration=10.0, start_time=2.0)]
        entries = calc_dialogue_timeline(s4, tl)
        assert len(entries) == 2
        assert entries[0]["character"] == "林雪"
        assert entries[0]["start_s"] == 2.0   # 2.0 + 10*0.0
        assert entries[0]["end_s"] == 7.0     # 2.0 + 10*0.5
        assert entries[1]["start_s"] == 8.0   # 2.0 + 10*0.6
        assert entries[1]["end_s"] == 12.0    # 2.0 + 10*1.0

    def test_no_dialogues_returns_empty(self):
        s4 = {
            "scenes": [
                {"sceneNumber": 1, "shots": [{"shotNumber": 1, "dialogues": []}]}
            ]
        }
        tl = Timeline()
        tl.shots = [ShotTiming(shot_number=1, duration=5.0, start_time=0.0)]
        entries = calc_dialogue_timeline(s4, tl)
        assert entries == []

    def test_shot_not_in_timeline_skipped(self):
        s4 = {
            "scenes": [
                {"sceneNumber": 1, "shots": [
                    {"shotNumber": 99, "dialogues": [
                        {"character": "A", "text": "hi", "startRatio": 0.0, "endRatio": 1.0}
                    ]}
                ]}
            ]
        }
        tl = Timeline()
        tl.shots = [ShotTiming(shot_number=1, duration=5.0, start_time=0.0)]
        entries = calc_dialogue_timeline(s4, tl)
        assert entries == []

    def test_fallback_equal_distribution(self):
        s4 = {
            "scenes": [
                {"sceneNumber": 1, "shots": [
                    {"shotNumber": 1, "dialogues": [
                        {"character": "A", "text": "first"},
                        {"character": "B", "text": "second"},
                    ]}
                ]}
            ]
        }
        tl = Timeline()
        tl.shots = [ShotTiming(shot_number=1, duration=10.0, start_time=0.0)]
        entries = calc_dialogue_timeline(s4, tl)
        assert len(entries) == 2
        # Without startRatio/endRatio, use equal distribution with 10% margin
        assert entries[0]["startRatio"] is None
        assert entries[0]["start_s"] == pytest.approx(1.0)
        assert entries[1]["start_s"] == pytest.approx(5.0)

    def test_global_idx_increments(self):
        s4 = {
            "scenes": [
                {"sceneNumber": 1, "shots": [
                    {"shotNumber": 1, "dialogues": [
                        {"character": "A", "text": "d1", "startRatio": 0.0, "endRatio": 0.3},
                    ]},
                    {"shotNumber": 2, "dialogues": [
                        {"character": "B", "text": "d2", "startRatio": 0.0, "endRatio": 0.5},
                    ]},
                ]}
            ]
        }
        tl = Timeline()
        tl.shots = [
            ShotTiming(shot_number=1, duration=5.0, start_time=0.0),
            ShotTiming(shot_number=2, duration=5.0, start_time=5.0),
        ]
        entries = calc_dialogue_timeline(s4, tl)
        assert entries[0]["global_idx"] == 0
        assert entries[1]["global_idx"] == 1


class TestFormatTime:
    """fmt_srt_time / fmt_ass_time"""

    def test_fmt_srt_time_zero(self):
        assert fmt_srt_time(0.0) == "00:00:00,000"

    def test_fmt_srt_time_basic(self):
        assert fmt_srt_time(3661.500) == "01:01:01,500"

    def test_fmt_srt_time_milliseconds(self):
        assert fmt_srt_time(12.345) == "00:00:12,345"

    def test_fmt_ass_time_zero(self):
        assert fmt_ass_time(0.0) == "0:00:00.00"

    def test_fmt_ass_time_basic(self):
        assert fmt_ass_time(3661.500) == "1:01:01.50"

    def test_fmt_ass_time_centiseconds(self):
        assert fmt_ass_time(12.345) == "0:00:12.35"


class TestCleanSubtitleText:
    """clean_subtitle_text()"""

    def test_replaces_double_dots(self):
        assert clean_subtitle_text("你好……世界") == "你好,世界"

    def test_replaces_double_dash(self):
        assert clean_subtitle_text("你好——世界") == "你好,世界"

    def test_replaces_dunhao(self):
        assert clean_subtitle_text("你、好") == "你,好"

    def test_keeps_normal_text(self):
        assert clean_subtitle_text("你好世界") == "你好世界"

    def test_empty_string(self):
        assert clean_subtitle_text("") == ""


class TestGenerateSrt:
    """generate_srt()"""

    def test_generates_valid_srt(self, tmp_path):
        entries = [
            {"character": "A", "text": "Hello", "start_s": 0.0, "end_s": 2.0},
            {"character": "B", "text": "World", "start_s": 3.0, "end_s": 5.0},
        ]
        output = tmp_path / "test.srt"
        result = generate_srt(entries, output)
        assert result == output
        assert output.exists()
        content = output.read_text(encoding="utf-8")
        assert "1" in content
        assert "2" in content
        assert "00:00:00,000 --> 00:00:02,000" in content
        assert "A: Hello" in content

    def test_srt_sequential_indexes(self, tmp_path):
        entries = [
            {"character": "X", "text": "a", "start_s": 0.0, "end_s": 1.0},
            {"character": "Y", "text": "b", "start_s": 1.0, "end_s": 2.0},
            {"character": "Z", "text": "c", "start_s": 2.0, "end_s": 3.0},
        ]
        output = tmp_path / "test.srt"
        generate_srt(entries, output)
        content = output.read_text(encoding="utf-8")
        assert content.count("\n\n") == 3  # 3 entries with blank line separator

    def test_srt_empty_entries(self, tmp_path):
        output = tmp_path / "empty.srt"
        generate_srt([], output)
        assert output.read_text(encoding="utf-8") == ""


class TestGenerateAss:
    """generate_ass()"""

    def test_generates_valid_ass(self, tmp_path):
        entries = [
            {"character": "旁白", "text": "故事开始", "start_s": 0.0, "end_s": 5.0},
            {"character": "心声", "text": "我想", "start_s": 5.0, "end_s": 8.0},
            {"character": "林雪", "text": "你好", "start_s": 8.0, "end_s": 12.0},
        ]
        output = tmp_path / "test.ass"
        result = generate_ass(entries, output, width=1920, height=1080)
        assert result == output
        assert output.exists()
        content = output.read_text(encoding="utf-8")

        # Check header
        assert "[Script Info]" in content
        assert "PlayResX: 1920" in content
        assert "PlayResY: 1080" in content

        # Check styles
        assert "Style: Narration" in content
        assert "Style: InnerVoice" in content
        assert "Style: Dialogue" in content

        # Check event lines
        assert "Narration" in content
        assert "InnerVoice" in content
        assert "Dialogue" in content

    def test_ass_empty_entries_has_header(self, tmp_path):
        output = tmp_path / "empty.ass"
        generate_ass([], output)
        content = output.read_text(encoding="utf-8")
        assert "[Script Info]" in content
        assert "[V4+ Styles]" in content
        assert "[Events]" in content



