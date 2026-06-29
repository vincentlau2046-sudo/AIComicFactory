"""L1: ContinuityChecker + 文件系统集成测试"""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock


class TestCheckProjectMissingData:
    def test_missing_s4(self, tmp_path):
        """check_project should return error if s4_shots.json missing."""
        from core.continuity_check import ContinuityChecker
        root = tmp_path / "projects"
        root.mkdir()
        (root / "test_project").mkdir()

        checker = ContinuityChecker(projects_root=str(root))
        result = checker.check_project("test_project")
        assert "error" in result

    def test_missing_frames(self, tmp_path, sample_s4_output):
        """check_project should skip pairs with missing frame files."""
        from core.continuity_check import ContinuityChecker
        root = tmp_path / "projects"
        root.mkdir()
        pd = root / "test_project"
        pd.mkdir()
        (pd / "s5_frames").mkdir()

        # Write s4 but no frames
        (pd / "s4_shots.json").write_text(json.dumps(sample_s4_output, ensure_ascii=False))

        checker = ContinuityChecker(projects_root=str(root))
        result = checker.check_project("test_project")
        # Should have results but with errors for missing frames
        assert result["pairs_checked"] > 0
        for r in result["results"]:
            assert r.get("error") == "missing frame files"


class TestCheckProjectMockVision:
    def test_check_project_with_mock_api(self, tmp_path, sample_s4_output, mock_vision_good_response):
        """Full project check with mocked vision API."""
        from core.continuity_check import ContinuityChecker
        root = tmp_path / "projects"
        root.mkdir()
        pd = root / "test_project"
        pd.mkdir()
        frames_dir = pd / "s5_frames"
        frames_dir.mkdir()

        # Write s4
        (pd / "s4_shots.json").write_text(json.dumps(sample_s4_output, ensure_ascii=False))

        # Create fake frame files
        (frames_dir / "s01_last.png").write_bytes(b"fake_png")
        (frames_dir / "s02_first.png").write_bytes(b"fake_png")

        checker = ContinuityChecker(projects_root=str(root))

        with patch("core.continuity_check.call_vision_llm", return_value=mock_vision_good_response):
            result = checker.check_project("test_project")

        assert result["pairs_checked"] == 1
        assert result["avg_score"] == 85
        assert len(result["issues"]) == 0  # Score 85 > threshold 70

        # Verify report file saved
        assert (pd / "continuity_report.json").exists()

    def test_check_project_with_issues(self, tmp_path, sample_s4_output, mock_vision_moderate_response):
        """Project check with moderate issues flagged."""
        from core.continuity_check import ContinuityChecker
        root = tmp_path / "projects"
        root.mkdir()
        pd = root / "test_project"
        pd.mkdir()
        frames_dir = pd / "s5_frames"
        frames_dir.mkdir()

        (pd / "s4_shots.json").write_text(json.dumps(sample_s4_output, ensure_ascii=False))
        (frames_dir / "s01_last.png").write_bytes(b"fake_png")
        (frames_dir / "s02_first.png").write_bytes(b"fake_png")

        checker = ContinuityChecker(projects_root=str(root))

        with patch("core.continuity_check.call_vision_llm", return_value=mock_vision_moderate_response):
            result = checker.check_project("test_project", threshold=70)

        # Score 55 < threshold 70, should be flagged
        assert len(result["issues"]) == 1
        assert result["issues"][0]["severity"] == "moderate"


class TestCheckProjectReportGeneration:
    def test_report_saved(self, tmp_path, sample_s4_output, mock_vision_good_response):
        from core.continuity_check import ContinuityChecker
        root = tmp_path / "projects"
        root.mkdir()
        pd = root / "test_project"
        pd.mkdir()
        frames_dir = pd / "s5_frames"
        frames_dir.mkdir()

        (pd / "s4_shots.json").write_text(json.dumps(sample_s4_output, ensure_ascii=False))
        (frames_dir / "s01_last.png").write_bytes(b"fake")
        (frames_dir / "s02_first.png").write_bytes(b"fake")

        checker = ContinuityChecker(projects_root=str(root))

        with patch("core.continuity_check.call_vision_llm", return_value=mock_vision_good_response):
            result = checker.check_project("test_project")

        # Verify JSON report
        report_file = pd / "continuity_report.json"
        assert report_file.exists()
        report = json.loads(report_file.read_text())
        assert "project" in report
        assert "checked_at" in report
        assert report["pairs_checked"] == 1

    def test_summary_readable(self, tmp_path, sample_s4_output, mock_vision_good_response):
        from core.continuity_check import ContinuityChecker
        root = tmp_path / "projects"
        root.mkdir()
        pd = root / "test_project"
        pd.mkdir()
        frames_dir = pd / "s5_frames"
        frames_dir.mkdir()

        (pd / "s4_shots.json").write_text(json.dumps(sample_s4_output, ensure_ascii=False))
        (frames_dir / "s01_last.png").write_bytes(b"fake")
        (frames_dir / "s02_first.png").write_bytes(b"fake")

        checker = ContinuityChecker(projects_root=str(root))

        with patch("core.continuity_check.call_vision_llm", return_value=mock_vision_good_response):
            result = checker.check_project("test_project")

        summary = checker.generate_summary(result)
        assert isinstance(summary, str)
        assert "test_project" in summary
        assert "85" in summary
