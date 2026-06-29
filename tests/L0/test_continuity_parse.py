"""L0: ContinuityChecker JSON 解析单元测试"""


class TestParseCleanJson:
    def test_parse_good_response(self, mock_vision_good_response):
        from core.continuity_check import ContinuityChecker
        checker = ContinuityChecker()
        result = checker._parse_result(mock_vision_good_response, 1, 2)
        assert result["overall_score"] == 85
        assert result["character_appearance"] == 9
        assert result["severity"] == "none"
        assert result["shot_a"] == 1
        assert result["shot_b"] == 2

    def test_parse_moderate_response(self, mock_vision_moderate_response):
        from core.continuity_check import ContinuityChecker
        checker = ContinuityChecker()
        result = checker._parse_result(mock_vision_moderate_response, 3, 4)
        assert result["overall_score"] == 55
        assert len(result["issues"]) == 2
        assert result["severity"] == "moderate"
        assert "服装颜色" in result["issues"][0]


class TestParseCodeblock:
    def test_parse_json_in_codeblock(self, mock_vision_codeblock_response):
        from core.continuity_check import ContinuityChecker
        checker = ContinuityChecker()
        result = checker._parse_result(mock_vision_codeblock_response, 1, 2)
        assert result["overall_score"] == 90
        assert result["severity"] == "none"

    def test_parse_json_in_backticks(self):
        from core.continuity_check import ContinuityChecker
        checker = ContinuityChecker()
        response = '```\n{"overall_score": 75, "character_appearance": 7, "scene_environment": 8, "lighting_color": 7, "composition": 8, "issues": ["轻微色差"], "severity": "minor", "suggestion": "调整色温"}\n```'
        result = checker._parse_result(response, 5, 6)
        assert result["overall_score"] == 75
        assert result["severity"] == "minor"


class TestParseMalformed:
    def test_malformed_response(self, mock_vision_malformed_response):
        from core.continuity_check import ContinuityChecker
        checker = ContinuityChecker()
        result = checker._parse_result(mock_vision_malformed_response, 1, 2)
        assert result["overall_score"] == -1
        assert "raw_response" in result

    def test_empty_response(self):
        from core.continuity_check import ContinuityChecker
        checker = ContinuityChecker()
        result = checker._parse_result("", 1, 2)
        assert result["overall_score"] == -1

    def test_partial_json(self):
        from core.continuity_check import ContinuityChecker
        checker = ContinuityChecker()
        response = '{"overall_score": 80, "character_appearance": 8'  # Incomplete JSON
        result = checker._parse_result(response, 1, 2)
        assert result["overall_score"] == -1  # Can't parse, should fallback


class TestShotMetadata:
    def test_shot_ids_preserved(self):
        from core.continuity_check import ContinuityChecker
        checker = ContinuityChecker()
        result = checker._parse_result(
            '{"overall_score": 90, "character_appearance": 9, "scene_environment": 9, "lighting_color": 9, "composition": 9, "issues": [], "severity": "none", "suggestion": ""}',
            7, 8
        )
        assert result["shot_a"] == 7
        assert result["shot_b"] == 8


class TestGenerateSummary:
    def test_summary_format(self, mock_vision_good_response):
        from core.continuity_check import ContinuityChecker
        checker = ContinuityChecker()
        result = checker._parse_result(mock_vision_good_response, 1, 2)
        report = {
            "project": "test",
            "pairs_checked": 1,
            "results": [result],
            "issues": [],
            "avg_score": 85,
            "threshold": 70,
        }
        summary = checker.generate_summary(report)
        assert "test" in summary
        assert "85" in summary
        assert "1" in summary  # pairs_checked

    def test_summary_with_issues(self, mock_vision_moderate_response):
        from core.continuity_check import ContinuityChecker
        checker = ContinuityChecker()
        result = checker._parse_result(mock_vision_moderate_response, 1, 2)
        report = {
            "project": "test",
            "pairs_checked": 1,
            "results": [result],
            "issues": [result],
            "avg_score": 55,
            "threshold": 70,
        }
        summary = checker.generate_summary(report)
        assert "1" in summary  # 1 issue
        assert "⚠️" in summary or "55" in summary
