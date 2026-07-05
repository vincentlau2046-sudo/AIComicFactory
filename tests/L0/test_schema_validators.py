"""L0: schema_validators 单元测试"""

from core.schema_validators import validate_s1_output, validate_s2_output, validate_s4_output


class TestValidateS1Output:
    """validate_s1_output: scenes + dialogues + character_names"""

    def test_full_valid_output(self):
        """完整有效 S1 输出——无错误"""
        data = {
            "scenes": [
                {
                    "dialogues": [
                        {"character": "林雪", "text": "你好"},
                        {"character": "李慕白", "text": "再见"},
                    ]
                }
            ],
            "character_names": ["林雪", "李慕白"],
        }
        errors = validate_s1_output(data)
        assert errors == []

    def test_empty_scenes_list(self):
        """空 scenes 列表——合法边界"""
        data = {"scenes": [], "character_names": []}
        errors = validate_s1_output(data)
        assert errors == []

    def test_missing_scenes_field(self):
        """缺少 scenes 字段"""
        data = {"character_names": ["林雪"]}
        errors = validate_s1_output(data)
        assert errors == ["Missing top-level 'scenes' array"]

    def test_scenes_is_none(self):
        """scenes 为 None"""
        data = {"scenes": None, "character_names": []}
        errors = validate_s1_output(data)
        assert errors == ["Missing top-level 'scenes' array"]

    def test_scenes_not_list(self):
        """scenes 不是 list"""
        data = {"scenes": "not_a_list"}
        errors = validate_s1_output(data)
        assert errors == ["Missing top-level 'scenes' array"]

    def test_missing_character_names(self):
        """缺少 character_names 字段（不在校验逻辑中，只检查不报错）"""
        data = {"scenes": []}
        # validate_s1_output 不校验 character_names
        errors = validate_s1_output(data)
        # Only checks scenes[]
        assert "character_names" not in data
        assert errors == []  # empty scenes is valid

    def test_dialogue_missing_character_field(self):
        """dialogue 缺少 character 字段"""
        data = {
            "scenes": [
                {
                    "dialogues": [
                        {"text": "没有角色名的对白"},
                    ]
                }
            ]
        }
        errors = validate_s1_output(data)
        assert any("character" in e for e in errors)

    def test_dialogue_missing_text_field(self):
        """dialogue 缺少 text 字段"""
        data = {
            "scenes": [
                {
                    "dialogues": [
                        {"character": "无名"},
                    ]
                }
            ]
        }
        errors = validate_s1_output(data)
        assert any("text" in e for e in errors)

    def test_dialogue_both_missing(self):
        """dialogue 同时缺少 character 和 text"""
        data = {
            "scenes": [
                {
                    "dialogues": [
                        {"emotion": "平静"},
                    ]
                }
            ]
        }
        errors = validate_s1_output(data)
        assert any("character" in e for e in errors)
        assert any("text" in e for e in errors)

    def test_multiple_dialogues_errors(self):
        """多个 dialogue 报错"""
        data = {
            "scenes": [
                {
                    "dialogues": [
                        {"character": "A", "text": "ok"},
                        {"text": "missing_char"},
                        {"character": "B"},
                    ]
                }
            ]
        }
        errors = validate_s1_output(data)
        assert len(errors) >= 2
        assert any("character" in e for e in errors)
        assert any("text" in e for e in errors)

    def test_scene_is_not_dict(self):
        """scenes 元素不是 dict"""
        data = {
            "scenes": [
                "not_a_dict",
            ]
        }
        errors = validate_s1_output(data)
        assert any("not a dict" in e for e in errors)


class TestValidateS2Output:
    """validate_s2_output: characters[] with name + description + visualHint"""

    def test_full_valid_output(self):
        """完整有效 S2 输出"""
        data = {
            "characters": [
                {"name": "林雪", "description": "少女剑客", "visualHint": "红色发带"},
                {"name": "李慕白", "description": "白衣少年", "visualHint": "长剑"},
            ]
        }
        errors = validate_s2_output(data)
        assert errors == []

    def test_empty_characters_list(self):
        """空 characters 列表"""
        data = {"characters": []}
        errors = validate_s2_output(data)
        assert errors == []

    def test_missing_characters_field(self):
        """缺少 characters 字段"""
        data = {}
        errors = validate_s2_output(data)
        assert errors == ["Missing top-level 'characters' array"]

    def test_characters_is_none(self):
        """characters 为 None"""
        data = {"characters": None}
        errors = validate_s2_output(data)
        assert errors == ["Missing top-level 'characters' array"]

    def test_character_missing_name(self):
        """character 缺少 name"""
        data = {
            "characters": [
                {"description": "少女剑客", "visualHint": "红色发带"},
            ]
        }
        errors = validate_s2_output(data)
        assert any("name" in e for e in errors)

    def test_character_missing_description(self):
        """character 缺少 description"""
        data = {
            "characters": [
                {"name": "林雪", "visualHint": "红色发带"},
            ]
        }
        errors = validate_s2_output(data)
        assert any("description" in e for e in errors)

    def test_character_missing_visual_hint(self):
        """character 缺少 visualHint"""
        data = {
            "characters": [
                {"name": "林雪", "description": "少女剑客"},
            ]
        }
        errors = validate_s2_output(data)
        assert len(errors) == 1
        assert "visualHint" in errors[0]

    def test_character_all_fields_missing(self):
        """character 所有字段缺失"""
        data = {
            "characters": [
                {},
            ]
        }
        errors = validate_s2_output(data)
        assert len(errors) >= 3

    def test_character_not_dict(self):
        """characters 元素不是 dict"""
        data = {
            "characters": [
                "not_a_dict",
            ]
        }
        errors = validate_s2_output(data)
        assert any("not a dict" in e for e in errors)

    def test_multiple_characters_multiple_errors(self):
        """多个 character 报错"""
        data = {
            "characters": [
                {"name": "A"},  # missing desc + visual
                {},            # missing all
            ]
        }
        errors = validate_s2_output(data)
        assert len(errors) >= 4

    def test_name_empty_string_counts_as_missing(self):
        """name 为空字符串视为缺失"""
        data = {
            "characters": [
                {"name": "", "description": "desc", "visualHint": "hint"},
            ]
        }
        errors = validate_s2_output(data)
        assert any("name" in e for e in errors)


class TestValidateS4Output:
    """validate_s4_output: shots[] with prompt + motionScript + startFrameDesc"""

    def test_full_valid_output_nested(self):
        """完整有效 S4 输出——nested scenes[].shots[] 格式"""
        data = {
            "scenes": [
                {
                    "sceneNumber": 1,
                    "shots": [
                        {"prompt": "白衣剑客", "motionScript": "站立", "startFrameDesc": "悬崖边"},
                        {"prompt": "少女走来", "motionScript": "行走", "startFrameDesc": "小路上"},
                    ]
                }
            ]
        }
        errors = validate_s4_output(data)
        assert errors == []

    def test_full_valid_output_flat(self):
        """完整有效 S4 输出——flat shots[] 格式"""
        data = {
            "shots": [
                {"prompt": "白衣剑客", "motionScript": "站立", "startFrameDesc": "悬崖边"},
            ]
        }
        errors = validate_s4_output(data)
        assert errors == []

    def test_empty_shots_list(self):
        """空 shots 列表"""
        data = {"scenes": [{"shots": []}]}
        errors = validate_s4_output(data)
        assert len(errors) == 1

    def test_missing_shots_field(self):
        """缺少 shots 字段"""
        data = {}
        errors = validate_s4_output(data)
        assert any("shots" in e for e in errors)

    def test_no_scenes_and_no_shots(self):
        """scenes 存在但无 shots"""
        data = {"scenes": [{}]}
        errors = validate_s4_output(data)
        assert any("shots" in e for e in errors)

    def test_shot_missing_prompt(self):
        """shot 缺少 prompt"""
        data = {
            "scenes": [
                {"shots": [
                    {"motionScript": "站立", "startFrameDesc": "悬崖边"},
                ]}
            ]
        }
        errors = validate_s4_output(data)
        assert any("prompt" in e for e in errors)

    def test_shot_missing_motion_script(self):
        """shot 缺少 motionScript"""
        data = {
            "scenes": [
                {"shots": [
                    {"prompt": "白衣剑客", "startFrameDesc": "悬崖边"},
                ]}
            ]
        }
        errors = validate_s4_output(data)
        assert any("motionScript" in e for e in errors)

    def test_shot_all_fields_missing(self):
        """shot 所有必填字段缺失"""
        data = {
            "scenes": [
                {"shots": [
                    {},
                ]}
            ]
        }
        errors = validate_s4_output(data)
        assert len(errors) >= 2

    def test_shot_not_dict(self):
        """shot 不是 dict"""
        data = {
            "scenes": [
                {"shots": [
                    "not_a_dict",
                ]}
            ]
        }
        errors = validate_s4_output(data)
        assert any("not a dict" in e for e in errors)

    def test_multiple_scenes_multiple_shots(self):
        """多个 scene 多个 shot"""
        data = {
            "scenes": [
                {"sceneNumber": 1, "shots": [{"prompt": "A", "motionScript": "a"}]},
                {"sceneNumber": 2, "shots": [
                    {"prompt": "B"},  # missing motionScript
                    {"motionScript": "c"},  # missing prompt
                ]},
            ]
        }
        errors = validate_s4_output(data)
        assert len(errors) >= 2
