"""L0: character_image_check + demographics 单元测试"""

import json
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from core.demographics import infer_gender
from core.character_image_check import CharacterImageChecker


class TestInferGender:
    """infer_gender 性别推断"""

    def test_male_description(self):
        """男性描述 → 'male'"""
        assert infer_gender("一个年轻小伙，穿着黑色衣服") == "male"

    def test_male_keywords(self):
        """明确的男性关键词"""
        assert infer_gender("男人") == "male"
        assert infer_gender("男孩") == "male"
        assert infer_gender("大叔") == "male"

    def test_female_description(self):
        """女性描述 → 'female'"""
        assert infer_gender("一位美丽的少女，长发及腰") == "female"

    def test_female_keywords(self):
        """明确的女性关键词"""
        assert infer_gender("女孩") == "female"
        assert infer_gender("姑娘") == "female"
        assert infer_gender("女士") == "female"

    def test_neutral_description(self):
        """中性描述 → 'unknown'"""
        assert infer_gender("一个穿着斗篷的身影") == "unknown"

    def test_empty_string(self):
        """空字符串 → 'unknown'"""
        assert infer_gender("") == "unknown"

    def test_none_text(self):
        """None 输入 → 'unknown'"""
        assert infer_gender(None) == "unknown"

    def test_female_score_higher_than_male(self):
        """女性关键词多于男性关键词 → 'female'"""
        assert infer_gender("小姐姐和阿姨一起去公园") == "female"

    def test_male_score_higher_than_female(self):
        """男性关键词多于女性关键词 → 'male'"""
        assert infer_gender("大哥和小伙子在打球") == "male"

    def test_equal_scores_returns_unknown(self):
        """男女关键词相等 → 'unknown'"""
        result = infer_gender("一个男孩和一个女孩")
        assert result == "unknown"

    def test_gender_field_overrides(self):
        """显式 gender_field 覆盖文本推断"""
        assert infer_gender("一个年轻小伙", gender_field="female") == "female"
        assert infer_gender("一位少女", gender_field="male") == "male"


class TestCharacterImageCheckerInit:
    """CharacterImageChecker 构造函数"""

    def test_default_model(self):
        checker = CharacterImageChecker()
        assert checker.model == "vllm_qw35_gptq"

    def test_custom_model(self):
        checker = CharacterImageChecker(model="custom-vl")
        assert checker.model == "custom-vl"


class TestCharacterImageCheckerCheck:
    """CharacterImageChecker.check()"""

    @pytest.fixture
    def character(self):
        return {
            "name": "林雪",
            "description": "少女剑客，红色发带，眼神坚定",
            "visualHint": "红色发带飘飘",
            "visualAnchors": {
                "hair": "黑色长发",
                "face": "瓜子脸",
                "clothing": "红色劲装",
            }
        }

    @pytest.fixture
    def vl_response(self):
        """模拟 VL 返回的有效 JSON"""
        return json.dumps({
            "g": {"m": True, "s": 3, "n": ""},
            "a": {"m": True, "s": 3, "n": ""},
            "h": {"m": True, "s": 2, "n": ""},
            "f": {"m": True, "s": 3, "n": ""},
            "c": {"m": True, "s": 2, "n": ""},
            "t": {"m": True, "s": 3, "n": ""},
            "o": 10,
            "sum": "角色匹配良好",
            "iss": [],
            "re": False,
        })

    def test_check_returns_expected_keys(self, character, vl_response):
        """check() 返回包含所有预期键的 dict"""
        with patch("core.character_image_check._call_vl", return_value=vl_response), \
             patch("core.character_image_check._image_to_base64", return_value="data:image/png;base64,fake"):
            checker = CharacterImageChecker()
            result = checker.check("/fake/path.png", character)

        assert "character" in result
        assert "pass" in result
        assert "score" in result
        assert "overall_score" in result
        assert "dimensions" in result
        assert "issues" in result
        assert "summary" in result
        assert "needs_regeneration" in result
        assert result["character"] == "林雪"

    def test_check_score_in_range(self, character, vl_response):
        """score 在 0-10 范围内"""
        with patch("core.character_image_check._call_vl", return_value=vl_response), \
             patch("core.character_image_check._image_to_base64", return_value="data:image/png;base64,fake"):
            checker = CharacterImageChecker()
            result = checker.check("/fake/path.png", character)

        assert 0 <= result["score"] <= 10
        assert 0 <= result["overall_score"] <= 10

    def test_check_pass_threshold(self, character, vl_response):
        """pass 状态根据 score >= 7"""
        with patch("core.character_image_check._call_vl", return_value=vl_response), \
             patch("core.character_image_check._image_to_base64", return_value="data:image/png;base64,fake"):
            checker = CharacterImageChecker()
            result = checker.check("/fake/path.png", character)

        # 6 dims * max 3 each = 18, all 3s except 2 hair + 2 clothing = 16 → 16*10/18 = 8.9
        assert result["pass"] is True
        assert result["score"] >= 7

    def test_check_low_score_fails(self, character):
        """低分导致 pass=False"""
        low_response = json.dumps({
            "g": {"m": False, "s": 1, "n": "wrong"},
            "a": {"m": False, "s": 0, "n": ""},
            "h": {"m": False, "s": 0, "n": ""},
            "f": {"m": False, "s": 1, "n": ""},
            "c": {"m": False, "s": 0, "n": ""},
            "t": {"m": False, "s": 0, "n": ""},
            "o": 2,
            "sum": "不匹配",
            "iss": ["完全不像"],
            "re": True,
        })
        with patch("core.character_image_check._call_vl", return_value=low_response), \
             patch("core.character_image_check._image_to_base64", return_value="data:image/png;base64,fake"):
            checker = CharacterImageChecker()
            result = checker.check("/fake/path.png", character)

        assert result["pass"] is False
        assert result["score"] < 7
        assert result["needs_regeneration"] is True

    def test_check_vl_call_failure_handling(self, character):
        """VL 调用失败返回 fallback 结果"""
        with patch("core.character_image_check._call_vl",
                   side_effect=RuntimeError("API timeout")) as mock_vl, \
             patch("core.character_image_check._image_to_base64", return_value="data:image/png;base64,fake"):
            checker = CharacterImageChecker()
            result = checker.check("/fake/path.png", character)

        assert result["pass"] is False
        assert result["score"] == 0
        assert "质检失败" in result["summary"]
        assert len(result["issues"]) > 0

    def test_check_calls_infer_gender(self, character, vl_response):
        """check() 调用 infer_gender"""
        with patch("core.character_image_check._call_vl", return_value=vl_response), \
             patch("core.character_image_check._image_to_base64", return_value="data:image/png;base64,fake"), \
             patch("core.character_image_check.infer_gender", return_value="female") as mock_ig:
            checker = CharacterImageChecker()
            result = checker.check("/fake/path.png", character)

        mock_ig.assert_called_once()
        # infer_gender should be called with description
        assert "少女剑客" in mock_ig.call_args[0][0]

    def test_check_dimensions_parsed_correctly(self, character, vl_response):
        """维度数据正确解析"""
        with patch("core.character_image_check._call_vl", return_value=vl_response), \
             patch("core.character_image_check._image_to_base64", return_value="data:image/png;base64,fake"):
            checker = CharacterImageChecker()
            result = checker.check("/fake/path.png", character)

        dims = result["dimensions"]
        for key in ["gender", "age", "hair", "face", "clothing", "format"]:
            assert key in dims
            assert "match" in dims[key]
            assert "score" in dims[key]
            assert 0 <= dims[key]["score"] <= 3

    def test_check_issues_default_empty(self, character):
        """issues 字段默认空列表"""
        response_no_iss = json.dumps({
            "g": {"m": True, "s": 3, "n": ""},
            "a": {"m": True, "s": 3, "n": ""},
            "h": {"m": True, "s": 3, "n": ""},
            "f": {"m": True, "s": 3, "n": ""},
            "c": {"m": True, "s": 3, "n": ""},
            "t": {"m": True, "s": 3, "n": ""},
            "o": 10,
            "sum": "完美",
            "iss": None,
            "re": False,
        })
        with patch("core.character_image_check._call_vl", return_value=response_no_iss), \
             patch("core.character_image_check._image_to_base64", return_value="data:image/png;base64,fake"):
            checker = CharacterImageChecker()
            result = checker.check("/fake/path.png", character)

        assert isinstance(result["issues"], list)
        assert result["issues"] == []


class TestCharacterImageCheckerCheckBatch:
    """CharacterImageChecker.check_batch()"""

    def test_check_batch_returns_list(self):
        """批量检查返回结果列表"""
        characters = [
            {"name": "林雪", "description": "少女", "visualHint": ""},
            {"name": "李慕白", "description": "少年", "visualHint": ""},
        ]
        vl_resp = json.dumps({
            "g": {"m": True, "s": 3},
            "a": {"m": True, "s": 3},
            "h": {"m": True, "s": 3},
            "f": {"m": True, "s": 3},
            "c": {"m": True, "s": 3},
            "t": {"m": True, "s": 3},
            "o": 10, "sum": "", "iss": [], "re": False,
        })
        with patch("core.character_image_check._call_vl", return_value=vl_resp), \
             patch("core.character_image_check._image_to_base64", return_value="data:image/png;base64,fake"):
            checker = CharacterImageChecker()
            results = checker.check_batch(
                ["/fake/a.png", "/fake/b.png"],
                characters,
            )
        assert len(results) == 2
        assert results[0]["character"] == "林雪"
        assert results[1]["character"] == "李慕白"


class TestCharacterImageCheckerGenerateReport:
    """CharacterImageChecker.generate_report()"""

    def test_generate_report_contains_characters(self):
        """报告包含角色名"""
        results = [
            {"character": "林雪", "pass": True, "score": 8.5, "summary": "好",
             "dimensions": {}, "issues": []},
            {"character": "李慕白", "pass": False, "score": 4.0, "summary": "差",
             "dimensions": {}, "issues": ["服装不符"]},
        ]
        checker = CharacterImageChecker()
        report = checker.generate_report(results)
        assert "林雪" in report
        assert "李慕白" in report
        assert "PASS" in report
        assert "FAIL" in report
        assert "服装不符" in report
