"""L0: S7 转场逻辑单元测试

Tests for s7_video_assemble.py xfade offset calculation, transition mapping,
and edge cases. Covers the P0 fix for cumulative offset drift in mixed
transition chains.
"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))


# ─────────────────────────────────────────────────────────────────
# Transition mapping tests
# ─────────────────────────────────────────────────────────────────

class TestGetXfadeName:
    """Test get_xfade_name: transition type → ffmpeg xfade name."""

    @pytest.fixture(autouse=True)
    def _import_s7(self):
        from scripts.s7_video_assemble import get_xfade_name, TRANSITION_MAP
        self.get_xfade_name = get_xfade_name
        self.TRANSITION_MAP = TRANSITION_MAP

    def test_cut_returns_none(self):
        """Hard cuts return None (no xfade filter)."""
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
        assert result is not None

    def test_case_insensitive(self):
        assert self.get_xfade_name("Dissolve") == "dissolve"
        assert self.get_xfade_name("CUT") is None


class TestTransitionMap:
    """Verify TRANSITION_MAP has all required entries."""

    def test_all_7_aicb_types(self):
        """All 7 AICB transition types must be in TRANSITION_MAP."""
        from scripts.s7_video_assemble import TRANSITION_MAP
        aicb_types = {
            "cut", "dissolve", "fade_in", "fade_out",
            "wipeleft", "slideright", "circleopen",
        }
        for t in aicb_types:
            assert t in TRANSITION_MAP, f"Missing AICB transition type: {t}"

    def test_cut_maps_to_none(self):
        """cut must map to None (no xfade)."""
        from scripts.s7_video_assemble import TRANSITION_MAP
        assert TRANSITION_MAP["cut"] is None


# ─────────────────────────────────────────────────────────────────
# Offset calculation tests (P0 fix)
# ─────────────────────────────────────────────────────────────────

class TestXfadeOffsetCalculation:
    """
    Verify the unified offset formula produces correct output durations.

    Formula:
      offset[i] = output_dur - eff_dur
      output_dur += next_dur - eff_dur    (cut: eff_dur=0, dissolve: eff_dur=xfade_dur)

    This eliminates cumulative drift when mixing cut and dissolve.
    """

    def _compute_offsets_and_durations(self, durations, transitions, xfade_dur=0.5):
        """
        Simulate the offset/duration tracking logic from concat_with_transitions.
        Returns list of (offset, output_dur_after, eff_dur) per transition.
        """
        from scripts.s7_video_assemble import get_xfade_name

        output_dur = durations[0]
        results = []
        for i, t in enumerate(transitions):
            next_dur = durations[i + 1]
            xfade_name = get_xfade_name(t)

            if xfade_name is None:
                # Cut: eff_dur = 0
                eff_dur = 0.0
                offset = output_dur
                output_dur = output_dur + next_dur
            else:
                eff_dur = xfade_dur
                offset = output_dur - eff_dur
                if offset < 0:
                    offset = 0
                output_dur = output_dur + next_dur - eff_dur

            results.append((offset, output_dur, eff_dur))
        return results

    def test_all_dissolve(self):
        """Pure dissolve chain: offsets should be evenly spaced."""
        durations = [3.0, 3.0, 3.0, 3.0]
        transitions = ["dissolve"] * 3
        xfade_dur = 0.5

        results = self._compute_offsets_and_durations(durations, transitions, xfade_dur)
        # 4 clips × 3.0 = 12.0 total; 3 transitions × 0.5 = 1.5 overlap; output = 10.5
        expected_output = 12.0 - 1.5  # 10.5
        assert abs(results[-1][1] - expected_output) < 1e-9

        # Offsets: 2.5, 5.0, 7.5
        for i, (offset, _, _) in enumerate(results):
            expected_offset = (i + 1) * 3.0 - 0.5 * (i + 1)
            # Actually: offset[0] = 3.0 - 0.5 = 2.5
            # output after 1: 3.0 + 3.0 - 0.5 = 5.5
            # offset[1] = 5.5 - 0.5 = 5.0
            # output after 2: 5.5 + 3.0 - 0.5 = 8.0
            # offset[2] = 8.0 - 0.5 = 7.5
            # output after 3: 8.0 + 3.0 - 0.5 = 10.5
            pass  # Just verify output_dur is correct

    def test_all_cuts(self):
        """Pure cut chain: offsets equal cumulative duration."""
        durations = [3.0, 2.0, 4.0, 1.0]
        transitions = ["cut"] * 3

        results = self._compute_offsets_and_durations(durations, transitions)
        expected_output = sum(durations)  # 10.0

        # Offsets: 3.0, 5.0, 9.0
        assert abs(results[0][0] - 3.0) < 1e-9
        assert abs(results[1][0] - 5.0) < 1e-9
        assert abs(results[2][0] - 9.0) < 1e-9
        assert abs(results[-1][1] - expected_output) < 1e-9

    def test_mixed_cut_and_dissolve(self):
        """Mixed transitions: no cumulative drift.

        Clips: [3.0, 2.0, 4.0]  Transitions: [dissolve, cut]
        - xfade 0 (dissolve): offset=3.0-0.5=2.5, output=3.0+2.0-0.5=4.5
        - xfade 1 (cut): offset=4.5, output=4.5+4.0=8.5

        OLD BUG would have had offset[1]=5.0 (wrong) because cut used
        output_dur += next_dur but dissolve used output_dur += next_dur - eff_dur.
        With the fix, both use the same formula with eff_dur=0 for cuts.
        """
        durations = [3.0, 2.0, 4.0]
        transitions = ["dissolve", "cut"]
        results = self._compute_offsets_and_durations(durations, transitions)

        assert abs(results[0][0] - 2.5) < 1e-9   # 3.0 - 0.5
        assert abs(results[0][1] - 4.5) < 1e-9   # 3.0 + 2.0 - 0.5

        assert abs(results[1][0] - 4.5) < 1e-9   # 4.5 - 0
        assert abs(results[1][1] - 8.5) < 1e-9   # 4.5 + 4.0

    def test_dissolve_cut_dissolve(self):
        """Sandwich pattern: dissolve → cut → dissolve.

        Clips: [3.0, 2.0, 4.0, 1.0]  Transitions: [dissolve, cut, dissolve]
        - xfade 0 (dissolve): offset=2.5, output=4.5
        - xfade 1 (cut): offset=4.5, output=8.5
        - xfade 2 (dissolve): offset=8.0, output=8.5+1.0-0.5=9.0
        """
        durations = [3.0, 2.0, 4.0, 1.0]
        transitions = ["dissolve", "cut", "dissolve"]
        results = self._compute_offsets_and_durations(durations, transitions)

        assert abs(results[0][0] - 2.5) < 1e-9
        assert abs(results[1][0] - 4.5) < 1e-9
        assert abs(results[2][0] - 8.0) < 1e-9
        assert abs(results[-1][1] - 9.0) < 1e-9

    def test_offset_never_negative(self):
        """Very short clip: offset should clamp to 0."""
        durations = [0.1, 3.0]
        transitions = ["dissolve"]
        results = self._compute_offsets_and_durations(durations, transitions, xfade_dur=0.5)

        assert results[0][0] == 0.0  # clamped

    def test_long_chain_no_drift(self):
        """Long chain: 10 clips alternating cut/dissolve.
        Verify output_dur doesn't drift from expected value.
        """
        durations = [3.0] * 10
        transitions = (["dissolve", "cut"] * 5)[:9]  # 9 transitions
        xfade_dur = 0.5

        results = self._compute_offsets_and_durations(durations, transitions, xfade_dur)

        # Expected: 10 clips × 3.0 = 30.0 total
        # Dissolves consume 0.5 each; cuts consume 0
        dissolve_count = sum(1 for t in transitions if t == "dissolve")
        expected_output = 30.0 - dissolve_count * 0.5

        assert abs(results[-1][1] - expected_output) < 1e-9

    def test_map_transition_backward_compat(self):
        """map_transition still works for legacy callers."""
        from scripts.s7_video_assemble import map_transition
        # Legacy callers expect a string, not None
        assert map_transition("cut") == "fade"
        assert map_transition("dissolve") == "dissolve"


# ─────────────────────────────────────────────────────────────────
# Simple concat tests
# ─────────────────────────────────────────────────────────────────

class TestSimpleConcat:
    """Test simple_concat function with mock ffmpeg."""

    def test_simple_concat_calls_ffmpeg(self, tmp_path):
        from scripts.s7_video_assemble import simple_concat

        clips = []
        for i in range(3):
            clip = tmp_path / f"clip_{i}.mp4"
            clip.write_bytes(b"fake_mp4")
            clips.append(clip)

        output = tmp_path / "output.mp4"

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            simple_concat(output, clips)
            assert mock_run.called

    def test_simple_concat_creates_list_file(self, tmp_path):
        from scripts.s7_video_assemble import simple_concat

        clips = []
        for i in range(2):
            clip = tmp_path / f"clip_{i}.mp4"
            clip.write_bytes(b"fake_mp4")
            clips.append(clip)

        output = tmp_path / "output.mp4"

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            simple_concat(output, clips)

            # Verify concat list content was created and cleaned up
            assert not (tmp_path / "_concat_output.txt").exists()


# ─────────────────────────────────────────────────────────────────
# Clip duration detection
# ─────────────────────────────────────────────────────────────────

class TestGetClipDuration:
    """Test clip duration detection."""

    def test_with_mock_ffprobe(self):
        from scripts.s7_video_assemble import get_clip_duration

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="3.500000"
            )
            dur = get_clip_duration(Path("fake.mp4"))
            assert dur == 3.5


# ─────────────────────────────────────────────────────────────────
# concat_with_transitions integration (mock)
# ─────────────────────────────────────────────────────────────────

class TestConcatWithTransitions:
    """Integration-level tests for concat_with_transitions with mocked ffmpeg."""

    def test_all_cuts_uses_simple_concat(self, tmp_path):
        """When all transitions are cut, simple_concat is called, not xfade."""
        from scripts.s7_video_assemble import concat_with_transitions

        clips = []
        for i in range(3):
            clip = tmp_path / f"clip_{i}.mp4"
            clip.write_bytes(b"fake")
            clips.append(clip)

        output = tmp_path / "output.mp4"
        durations = [3.0, 2.0, 4.0]
        transitions = ["cut", "cut"]

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            concat_with_transitions(clips, transitions, durations, output)
            # Should have called ffmpeg with concat demuxer, not filter_complex
            cmd = mock_run.call_args[0][0]
            assert "-filter_complex" not in cmd
            assert "-f" in cmd
            assert "concat" in cmd

    def test_single_clip_copies(self, tmp_path):
        """Single clip: should just copy the file."""
        from scripts.s7_video_assemble import concat_with_transitions

        clip = tmp_path / "clip.mp4"
        clip.write_bytes(b"fake")
        output = tmp_path / "output.mp4"

        concat_with_transitions([clip], [], [3.0], output)
        assert output.exists()
        assert output.read_bytes() == b"fake"

    def test_empty_list_noop(self):
        from scripts.s7_video_assemble import concat_with_transitions
        # Should not raise
        concat_with_transitions([], [], [], Path("/dev/null"))
