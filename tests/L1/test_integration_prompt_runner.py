"""L1: PromptRunner + Registry 集成测试"""

import json
from pathlib import Path


class TestPromptRunnerWithRegistry:
    def test_run_script_parse_returns_messages(self, tmp_path):
        from core.prompt_runner import run_script_parse
        result = run_script_parse(tmp_path, "少年站在悬崖边")
        assert "messages" in result
        assert result["stage"] == "s1_parse"
        assert len(result["messages"]) == 2
        assert result["messages"][0]["role"] == "system"
        assert result["messages"][1]["role"] == "user"

    def test_run_script_parse_system_prompt_substantial(self, tmp_path):
        from core.prompt_runner import run_script_parse
        result = run_script_parse(tmp_path, "少年站在悬崖边")
        system = result["messages"][0]["content"]
        assert len(system) > 200  # Should have substantial prompt content

    def test_run_character_extract_returns_messages(self, tmp_path):
        from core.prompt_runner import run_character_extract
        # Need a parsed script input
        script = {"title": "测试", "scenes": [{"sceneNumber": 1, "dialogues": []}]}
        result = run_character_extract(tmp_path, parsed_script=script)
        assert "messages" in result
        assert result["stage"] == "s2_character_extract"

    def test_run_shot_split_returns_messages(self, tmp_path):
        from core.prompt_runner import run_shot_split
        script = {"title": "测试", "scenes": [{"sceneNumber": 1, "dialogues": []}]}
        result = run_shot_split(tmp_path, parsed_script=script, characters=[])
        assert "messages" in result


class TestSaveStageOutput:
    def test_save_json_output(self, tmp_path):
        from core.prompt_runner import save_stage_output
        test_data = {"title": "test", "scenes": []}
        save_stage_output(tmp_path, "s1_parse", test_data)

        output_file = tmp_path / "s1_parsed.json"
        assert output_file.exists()

        loaded = json.loads(output_file.read_text())
        assert loaded["title"] == "test"

    def test_save_preserves_unicode(self, tmp_path):
        from core.prompt_runner import save_stage_output
        test_data = {"角色": "李慕白", "描述": "白衣剑客"}
        save_stage_output(tmp_path, "s2_character_extract", test_data)

        output_file = tmp_path / "s2_characters.json"
        loaded = json.loads(output_file.read_text())
        assert loaded["角色"] == "李慕白"
