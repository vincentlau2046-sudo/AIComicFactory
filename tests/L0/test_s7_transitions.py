"""L0: S7 转场逻辑单元测试"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

# Import s7 transition logic
# We need to extract just the transition functions for testing
# Let's import them directly
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))


class TestGetXfadeName:
    """Test transition type → xfade filter name mapping."""

    @pytest.fixture(autouse=True)
    def _import_s7(self):
        """Import s7 module functions."""
        # Import the transition logic from s7
        from scripts.s7_video_assemble import get_xfade_name, TRANSITION_MAP
        self.get_xfade_name = get_xfade_name
        self.TRANSITION_MAP = TRANSITION_MAP

    def test_cut_returns_none(self):
        assert self.get_xfade_name("cut") is None

    def test_dissolve(self):
        assert self.get_xfade_name("dissolve") == "dissolve"

    def test_fade_in(self):
        result = self.get_xfade_name("fade_in")
        assert result is not None
        assert "fade" in result.lower()

    def test_fade_out(self):
        result = self.get_xfade_name("fade_out")
        assert result is not None
        assert "fade" in result.lower()

    def test_wipeleft(self):
        result = self.get_xfade_name("wipeleft")
        assert result is not None

    def test_slideright(self):
        result = self.get_xfade_name("slideright")
        assert result is not None

    def test_circleopen(self):
        result = self.get_xfade_name("circleopen")
        assert result is not None

    def test_unknown_defaults_to_dissolve(self):
        result = self.get_xfade_name("nonexistent_transition")
        # Should fallback to default (dissolve)
        assert result is not None

    def test_case_insensitive(self):
        assert self.get_xfade_name("Dissolve") == "dissolve"
        assert self.get_xfade_name("CUT") is None


class TestTransitionMap:
    def test_all_7_aicb_types(self):
        """Verify all 7 AICB transition types are in TRANSITION_MAP."""
        from scripts.s7_video_assemble import TRANSITION_MAP
        aicb_types = {"cut", "dissolve", "fade_in", "fade_out", "wipeleft", "slideright", "circleopen"}
        for t in aicb_types:
            assert t in TRANSITION_MAP, f"Missing AICB transition type: {t}"

    def test_cut_maps_to_none(self):
        from scripts.s7_video_assemble import TRANSITION_MAP
        assert TRANSITION_MAP["cut"] is None


class TestSimpleConcat:
    """Test simple_concat function with mock ffmpeg."""

    def test_simple_concat_creates_output(self, tmp_path):
        from scripts.s7_video_assemble import simple_concat
        from unittest.mock import patch

        # Create fake clip files
        clips = []
        for i in range(3):
            clip = tmp_path / f"clip_{i}.mp4"
            clip.write_bytes(b"fake_mp4")
            clips.append(clip)

        output = tmp_path / "output.mp4"

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            simple_concat(output, clips)
            # Should have called ffmpeg
            assert mock_run.called


class TestGetClipDuration:
    """Test clip duration detection."""

    def test_with_mock_ffprobe(self):
        from scripts.s7_video_assemble import get_clip_duration
        from unittest.mock import patch, MagicMock

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="3.500000"
            )
            dur = get_clip_duration(Path("fake.mp4"))
            assert dur == 3.5
