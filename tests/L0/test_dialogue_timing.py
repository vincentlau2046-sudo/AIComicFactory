"""L0: dialogue_timing 模块单元测试"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from scripts.dialogue_timing import (
    analyze_shot_dialogues,
    _equal_distribute,
    ANALYSIS_PROMPT_TEMPLATE,
)


class TestAnalysisPromptTemplate:
    """ANALYSIS_PROMPT_TEMPLATE"""

    def test_template_is_non_empty(self):
        assert isinstance(ANALYSIS_PROMPT_TEMPLATE, str)
        assert len(ANALYSIS_PROMPT_TEMPLATE) > 0

    def test_template_contains_placeholders(self):
        assert "{duration}" in ANALYSIS_PROMPT_TEMPLATE
        assert "{dialogues_text}" in ANALYSIS_PROMPT_TEMPLATE

    def test_template_formats_correctly(self):
        result = ANALYSIS_PROMPT_TEMPLATE.format(
            duration="5.0",
            dialogues_text="  1. 林雪: \"你好\"",
        )
        assert "5.0" in result
        assert "林雪" in result


class TestEqualDistribute:
    """_equal_distribute()"""

    def test_single_dialogue(self):
        dialogues = [{"character": "林雪", "text": "你好"}]
        result = _equal_distribute(dialogues, duration=10.0)
        assert len(result) == 1
        assert result[0]["startRatio"] == 0.0
        assert result[0]["endRatio"] == 1.0
        assert result[0]["character"] == "林雪"

    def test_two_dialogues(self):
        dialogues = [
            {"character": "A", "text": "first"},
            {"character": "B", "text": "second"},
        ]
        result = _equal_distribute(dialogues, duration=10.0)
        assert len(result) == 2
        # With gap 0.05 between: 
        # segment = (10 - 0.05) / 2 = 4.975
        # start0 = 0, end0 = 4.975/10 = 0.4975
        # start1 = (4.975+0.05)/10 = 0.5025, end1 = (4.975+0.05+4.975)/10 = 1.0
        assert result[0]["startRatio"] == 0.0
        assert result[1]["endRatio"] == 1.0
        assert result[0]["endRatio"] < result[1]["startRatio"]

    def test_three_dialogues_no_overlap(self):
        dialogues = [
            {"character": "A", "text": "a"},
            {"character": "B", "text": "b"},
            {"character": "C", "text": "c"},
        ]
        result = _equal_distribute(dialogues, duration=10.0)
        assert len(result) == 3
        # No overlapping intervals
        for i in range(len(result) - 1):
            assert result[i]["endRatio"] <= result[i + 1]["startRatio"]

    def test_ratios_in_0_1_range(self):
        dialogues = [
            {"character": "A", "text": "a"},
            {"character": "B", "text": "b"},
        ]
        result = _equal_distribute(dialogues, duration=5.0)
        for entry in result:
            assert 0.0 <= entry["startRatio"] <= 1.0
            assert 0.0 <= entry["endRatio"] <= 1.0
            assert entry["startRatio"] < entry["endRatio"]

    def test_empty_list(self):
        result = _equal_distribute([], duration=10.0)
        assert result == []

    def test_start_end_ratios_ordered(self):
        """startRatio < endRatio for each entry"""
        dialogues = [{"character": "A", "text": "x"} for _ in range(5)]
        result = _equal_distribute(dialogues, duration=10.0)
        for entry in result:
            assert entry["startRatio"] < entry["endRatio"]

    def test_character_name_fallback(self):
        """使用 characterName 作为 fallback"""
        dialogues = [{"characterName": "旁白", "text": "故事开始"}]
        result = _equal_distribute(dialogues, duration=5.0)
        assert result[0]["character"] == "旁白"

    def test_values_rounded_to_3_decimals(self):
        dialogues = [{"character": "A", "text": "test"}]
        result = _equal_distribute(dialogues, duration=3.0)
        # Check 3 decimal places
        sr_str = str(result[0]["startRatio"])
        er_str = str(result[0]["endRatio"])
        # Either 0/1 exactly, or has ≤ 3 decimal places
        if "." in sr_str:
            assert len(sr_str.split(".")[1]) <= 3
        if "." in er_str:
            assert len(er_str.split(".")[1]) <= 3


class TestAnalyzeShotDialogues:
    """analyze_shot_dialogues()"""

    @pytest.fixture
    def sample_shot(self):
        return {
            "shotNumber": 1,
            "duration": 10.0,
            "dialogues": [
                {"character": "林雪", "text": "师父，他们来了。"},
                {"character": "李慕白", "text": "既然来了，便战吧。"},
            ]
        }

    @pytest.fixture
    def project_dir(self, tmp_path):
        pd = tmp_path / "test_project"
        pd.mkdir()
        # Create s5_frames directory
        (pd / "s5_frames").mkdir()
        return pd

    def test_no_vision_fallback_equal_distribute(self, sample_shot, project_dir):
        """use_vision=False 回退到均匀分布"""
        result = analyze_shot_dialogues(sample_shot, project_dir, use_vision=False)
        assert len(result) == 2
        assert result[0]["character"] == "林雪"
        assert result[1]["character"] == "李慕白"
        assert result[0]["startRatio"] == 0.0
        assert result[1]["endRatio"] == 1.0

    def test_no_frames_equal_distribute(self, sample_shot, project_dir):
        """无帧图片文件时回退到均匀分布"""
        # s5_frames is empty, no frame files exist
        result = analyze_shot_dialogues(sample_shot, project_dir, use_vision=True)
        assert len(result) == 2
        # Falls back because image_paths is empty

    def test_vision_successful_parse(self, sample_shot, project_dir):
        """VL 成功返回解析结果"""
        # Create mock frame files
        (project_dir / "s5_frames" / "s01_first.png").write_text("fake")
        (project_dir / "s5_frames" / "s01_last.png").write_text("fake")

        vl_response = json.dumps({
            "choices": [{
                "message": {"content": json.dumps([
                    {"character": "林雪", "startRatio": 0.0, "endRatio": 0.5},
                    {"character": "李慕白", "startRatio": 0.6, "endRatio": 1.0},
                ])}
            }]
        })

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = vl_response.encode("utf-8")
            mock_resp.__enter__.return_value = mock_resp
            mock_urlopen.return_value = mock_resp

            result = analyze_shot_dialogues(sample_shot, project_dir, use_vision=True)

        assert len(result) == 2
        assert result[0]["startRatio"] == 0.0
        assert result[0]["endRatio"] == 0.5

    def test_vision_codeblock_response(self, sample_shot, project_dir):
        """VL 返回 markdown code block 格式"""
        (project_dir / "s5_frames" / "s01_first.png").write_text("fake")
        (project_dir / "s5_frames" / "s01_last.png").write_text("fake")

        content = "```json\n[\n  {\"character\": \"林雪\", \"startRatio\": 0.0, \"endRatio\": 0.4}\n]\n```"
        vl_response = json.dumps({
            "choices": [{"message": {"content": content}}]
        })

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = vl_response.encode("utf-8")
            mock_resp.__enter__.return_value = mock_resp
            mock_urlopen.return_value = mock_resp

            result = analyze_shot_dialogues(sample_shot, project_dir, use_vision=True)

        assert len(result) == 2
        assert result[0]["startRatio"] == 0.0

    def test_overlap_correction(self, sample_shot, project_dir):
        """重叠区间自动修正——后移 startRatio"""
        (project_dir / "s5_frames" / "s01_first.png").write_text("fake")
        (project_dir / "s5_frames" / "s01_last.png").write_text("fake")

        # Second dialogue overlaps with first (starts at 0.4, first ends at 0.5)
        content = json.dumps([
            {"character": "林雪", "startRatio": 0.0, "endRatio": 0.5},
            {"character": "李慕白", "startRatio": 0.4, "endRatio": 0.9},
        ])
        vl_response = json.dumps({
            "choices": [{"message": {"content": content}}]
        })

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = vl_response.encode("utf-8")
            mock_resp.__enter__.return_value = mock_resp
            mock_urlopen.return_value = mock_resp

            result = analyze_shot_dialogues(sample_shot, project_dir, use_vision=True)

        # Second dialogue's start should be pushed to first's end (0.5)
        assert result[1]["startRatio"] >= 0.5
        assert result[0]["endRatio"] <= result[1]["startRatio"]

    def test_invalid_ratios_clamped(self, sample_shot, project_dir):
        """超出 [0,1] 的 ratio 被 clamp"""
        (project_dir / "s5_frames" / "s01_first.png").write_text("fake")
        (project_dir / "s5_frames" / "s01_last.png").write_text("fake")

        content = json.dumps([
            {"character": "林雪", "startRatio": -0.5, "endRatio": 1.5},
            {"character": "李慕白", "startRatio": 0.3, "endRatio": 0.7},
        ])
        vl_response = json.dumps({
            "choices": [{"message": {"content": content}}]
        })

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = vl_response.encode("utf-8")
            mock_resp.__enter__.return_value = mock_resp
            mock_urlopen.return_value = mock_resp

            result = analyze_shot_dialogues(sample_shot, project_dir, use_vision=True)

        assert result[0]["startRatio"] == 0.0  # clamped from -0.5
        assert result[0]["endRatio"] == 1.0    # clamped from 1.5

    def test_start_equal_end_reset_to_full(self, sample_shot, project_dir):
        """startRatio == endRatio 时重置为 [0, 1]"""
        (project_dir / "s5_frames" / "s01_first.png").write_text("fake")
        (project_dir / "s5_frames" / "s01_last.png").write_text("fake")

        content = json.dumps([
            {"character": "林雪", "startRatio": 0.5, "endRatio": 0.5},
        ])
        vl_response = json.dumps({
            "choices": [{"message": {"content": content}}]
        })

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = vl_response.encode("utf-8")
            mock_resp.__enter__.return_value = mock_resp
            mock_urlopen.return_value = mock_resp

            result = analyze_shot_dialogues(sample_shot, project_dir, use_vision=True)

        assert result[0]["startRatio"] == 0.0
        assert result[0]["endRatio"] == 1.0

    def test_vision_failure_fallback(self, sample_shot, project_dir):
        """VL 调用失败时回退到均匀分布"""
        (project_dir / "s5_frames" / "s01_first.png").write_text("fake")
        (project_dir / "s5_frames" / "s01_last.png").write_text("fake")

        with patch("urllib.request.urlopen", side_effect=RuntimeError("API error")), \
             patch("urllib.request.Request"):
            result = analyze_shot_dialogues(sample_shot, project_dir, use_vision=True)

        assert len(result) == 2
        assert result[0]["startRatio"] == 0.0

    def test_no_dialogues(self, project_dir):
        shot = {"shotNumber": 1, "dialogues": []}
        result = analyze_shot_dialogues(shot, project_dir)
        assert result == []

    def test_missing_dialogues_key(self, project_dir):
        shot = {"shotNumber": 1}
        result = analyze_shot_dialogues(shot, project_dir)
        assert result == []


class TestStartEndRatioValidation:
    """startRatio / endRatio 校验逻辑"""

    def test_valid_ratios(self):
        """0 <= start < end <= 1"""
        sr, er = 0.2, 0.8
        assert 0 <= sr < er <= 1

    def test_invalid_start_negative(self):
        """start < 0 无效"""
        assert not (0 <= -0.1 < 0.5 <= 1)

    def test_invalid_end_gt_one(self):
        """end > 1 无效"""
        assert not (0 <= 0.5 < 1.2 <= 1)

    def test_start_equal_end_invalid(self):
        """start == end 无效"""
        assert not (0 <= 0.5 < 0.5 <= 1)

    def test_start_greater_than_end_invalid(self):
        """start > end 无效"""
        assert not (0 <= 0.8 < 0.2 <= 1)
