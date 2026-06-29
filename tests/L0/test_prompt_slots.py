"""L0: Prompt Slot 结构验证"""


class TestSlotIntegrity:
    def test_slot_keys_unique_per_prompt(self):
        from prompts.registry import REGISTRY
        for key, p in REGISTRY.items():
            keys = [s.key for s in p.slots]
            assert len(keys) == len(set(keys)), f"{key} has duplicate slot keys: {keys}"

    def test_default_content_nonempty(self):
        from prompts.registry import REGISTRY
        for key, p in REGISTRY.items():
            for slot in p.slots:
                assert len(slot.default_content) > 0, f"{key}.{slot.key} has empty defaultContent"

    def test_slot_editable_flag(self):
        from prompts.registry import REGISTRY
        for key, p in REGISTRY.items():
            for slot in p.slots:
                assert isinstance(slot.editable, bool), f"{key}.{slot.key} editable not bool"


class TestBuildNoParams:
    """Test that prompts that don't require params can build without them."""

    def test_video_generate_no_params(self):
        from prompts.registry import build_prompt
        result = build_prompt("video_generate")
        assert len(result) > 0

    def test_ref_video_generate_no_params(self):
        from prompts.registry import build_prompt
        result = build_prompt("ref_video_generate")
        assert len(result) > 0


class TestPromptCategories:
    def test_script_prompts(self):
        from prompts.registry import REGISTRY
        script_keys = [k for k, p in REGISTRY.items() if p.category == "script"]
        assert "script_parse" in script_keys
        assert "script_generate" in script_keys
        assert "script_split" in script_keys

    def test_character_prompts(self):
        from prompts.registry import REGISTRY
        char_keys = [k for k, p in REGISTRY.items() if p.category == "character"]
        assert "character_extract" in char_keys
        assert "character_image" in char_keys
        assert "import_character_extract" in char_keys

    def test_frame_prompts(self):
        from prompts.registry import REGISTRY
        frame_keys = [k for k, p in REGISTRY.items() if p.category == "frame"]
        assert "frame_generate_first" in frame_keys
        assert "frame_generate_last" in frame_keys
        assert "scene_frame_generate" in frame_keys

    def test_video_prompts(self):
        from prompts.registry import REGISTRY
        video_keys = [k for k, p in REGISTRY.items() if p.category == "video"]
        assert "video_generate" in video_keys
        assert "ref_video_generate" in video_keys

    def test_shot_prompts(self):
        from prompts.registry import REGISTRY
        shot_keys = [k for k, p in REGISTRY.items() if p.category == "shot"]
        assert "shot_split" in shot_keys
