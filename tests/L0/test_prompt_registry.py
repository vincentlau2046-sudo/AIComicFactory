"""L0: Prompt Registry 单元测试"""


class TestRegistryCompleteness:
    def test_all_12_registered(self):
        from prompts.registry import REGISTRY
        assert len(REGISTRY) == 12

    def test_expected_keys(self):
        from prompts.registry import REGISTRY
        expected = {
            "script_parse", "character_extract", "shot_split",
            "frame_generate_first", "frame_generate_last",
            "character_image", "video_generate",
            "script_generate", "script_split",
            "import_character_extract", "scene_frame_generate",
            "ref_video_generate",
        }
        assert set(REGISTRY.keys()) == expected

    def test_each_has_category(self):
        from prompts.registry import REGISTRY
        valid_cats = {"script", "character", "shot", "frame", "video"}
        for key, p in REGISTRY.items():
            assert p.category in valid_cats, f"{key} has invalid category: {p.category}"


class TestBuildEach:
    def test_build_all_no_crash(self):
        from prompts.registry import REGISTRY
        for key, p in REGISTRY.items():
            try:
                result = p.build()
                assert isinstance(result, str), f"{key} build returned {type(result)}"
            except TypeError:
                # Some prompts require params — try with minimal params
                result = p.build(params={
                    "scene_description": "test",
                    "start_frame_desc": "test",
                    "end_frame_desc": "test",
                    "character_descriptions": "test",
                    "character_name": "test",
                    "character_description": "test",
                    "visual_hint": "test",
                    "idea": "test",
                    "script_summary": "test",
                    "text": "test",
                })
                assert isinstance(result, str)

    def test_build_nonempty(self):
        from prompts.registry import REGISTRY
        for key, p in REGISTRY.items():
            try:
                result = p.build()
            except TypeError:
                result = p.build(params={
                    "scene_description": "test",
                    "start_frame_desc": "test",
                    "end_frame_desc": "test",
                    "character_descriptions": "test",
                    "character_name": "test",
                    "character_description": "test",
                })
            assert len(result) > 0, f"{key} build returned empty string"


class TestBuildWithOverrides:
    def test_override_replaces_slot(self):
        from prompts.registry import REGISTRY
        p = REGISTRY["frame_generate_first"]
        custom_style = "CUSTOM_STYLE_OVERRIDE_12345"
        result = p.build(overrides={"style_matching": custom_style})
        assert custom_style in result

    def test_override_partial(self):
        from prompts.registry import REGISTRY
        p = REGISTRY["frame_generate_first"]
        result_default = p.build(params={
            "scene_description": "test",
            "start_frame_desc": "test",
            "character_descriptions": "test",
        })
        result_overridden = p.build(
            overrides={"rendering_quality": "OVERRIDDEN_RENDERING"},
            params={
                "scene_description": "test",
                "start_frame_desc": "test",
                "character_descriptions": "test",
            },
        )
        assert "OVERRIDDEN_RENDERING" in result_overridden
        # The rest should still be there
        assert len(result_overridden) > 10


class TestGetPrompt:
    def test_get_existing(self):
        from prompts.registry import get_prompt
        p = get_prompt("script_parse")
        assert p is not None
        assert p.key == "script_parse"

    def test_get_missing(self):
        from prompts.registry import get_prompt
        p = get_prompt("nonexistent_prompt")
        assert p is None


class TestBuildPrompt:
    def test_build_missing_raises(self):
        from prompts.registry import build_prompt
        import pytest
        with pytest.raises(ValueError, match="not found"):
            build_prompt("nonexistent_prompt")

    def test_build_existing(self):
        from prompts.registry import build_prompt
        result = build_prompt("video_generate")
        assert isinstance(result, str)
        assert len(result) > 0


class TestFramePrompts:
    def test_first_frame_with_continuity(self):
        from prompts.registry import build_prompt
        result = build_prompt("frame_generate_first", params={
            "scene_description": "竹林小径",
            "start_frame_desc": "白衣剑客立于林中",
            "character_descriptions": "李慕白：白衣少年剑客",
            "previous_last_frame": "上一镜尾帧描述",
        })
        assert "连续性" in result or "continuity" in result.lower()

    def test_first_frame_without_continuity(self):
        from prompts.registry import build_prompt
        result = build_prompt("frame_generate_first", params={
            "scene_description": "竹林小径",
            "start_frame_desc": "白衣剑客立于林中",
            "character_descriptions": "李慕白：白衣少年剑客",
        })
        # Without previous_last_frame, continuity section should not appear
        # (it's conditionally included)
        assert "画风必须" in result

    def test_last_frame_references_first(self):
        from prompts.registry import build_prompt
        result = build_prompt("frame_generate_last", params={
            "scene_description": "竹林小径",
            "end_frame_desc": "剑客拔剑出鞘",
            "character_descriptions": "李慕白：白衣少年剑客",
        })
        assert "首帧" in result or "first" in result.lower()
        assert "参考图" in result
