"""
L2: 全链路冒烟测试 — 后期管线 (S7→S9)

前置条件: last_bento 项目有 S6 视频输出

运行: AICF_RUN_POST_TESTS=1 pytest tests/L2/test_smoke_post_pipeline.py -v --tb=short
"""

import json
import os
import sys
import subprocess
import pytest
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

PROJECT = "last_bento"
PROJECT_DIR = ROOT / "projects" / PROJECT

FFPROBE = "/home/vince/miniconda3/envs/comfyui/bin/ffprobe"

pytestmark = pytest.mark.skipif(
    not os.environ.get("AICF_RUN_POST_TESTS"),
    reason="Set AICF_RUN_POST_TESTS=1 to run post pipeline tests"
)


@pytest.fixture
def project_data():
    shots = json.loads((PROJECT_DIR / "s4_shots.json").read_text())
    return shots


class TestS7VideoAssemble:
    """S7: 视频组装 + 转场效果"""

    def test_s7_transition_types(self):
        """Verify all 7 transition types are mapped."""
        from scripts.s7_video_assemble import get_xfade_name

        # cut = no xfade (just concat), returns None
        assert get_xfade_name("cut") is None

        # All others should return an xfade filter name
        for ttype in ["dissolve", "fade_in", "fade_out", "wipeleft", "slideright", "circleopen"]:
            xfade = get_xfade_name(ttype)
            assert xfade is not None, f"No xfade for {ttype}"
            assert isinstance(xfade, str), f"xfade for {ttype} is not string"

    def test_s7_assembled_video_valid(self):
        """Verify assembled video is a valid MP4."""
        assembled = PROJECT_DIR / "s7_assembled.mp4"
        if not assembled.exists():
            pytest.skip("No assembled video (run S7 first)")

        assert assembled.stat().st_size > 1000, "Assembled video too small"
        result = subprocess.run(
            [FFPROBE, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1", str(assembled)],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0, f"ffprobe failed: {result.stderr}"
        assert "duration" in result.stdout


class TestS8Subtitles:
    """S8: 字幕生成"""

    def test_s8_produces_ass(self):
        """Verify ASS subtitle file is valid."""
        ass_file = PROJECT_DIR / "s8_subtitles.ass"
        if not ass_file.exists():
            pytest.skip("No ASS subtitle file (run S8 first)")

        content = ass_file.read_text()
        assert "[Script Info]" in content, "Missing ASS header"
        assert "Dialogue:" in content, "No dialogue entries"

        lines = [l for l in content.split("\n") if l.startswith("Dialogue:")]
        assert len(lines) > 0, "No dialogue lines in ASS file"


class TestS9TTS:
    """S9: TTS 音频"""

    def test_s9_final_video_has_audio(self):
        """Verify final video with TTS audio exists and has audio stream."""
        final = PROJECT_DIR / "s7_final.mp4"
        if not final.exists():
            pytest.skip("No final video (run S9 first)")

        assert final.stat().st_size > 1000000, "Final video too small (<1MB)"

        result = subprocess.run(
            [FFPROBE, "-v", "error", "-select_streams", "a",
             "-show_entries", "stream=codec_type",
             "-of", "default=noprint_wrappers=1", str(final)],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0, "No audio stream in final video"
        assert "codec_type" in result.stdout, "Audio stream missing"
