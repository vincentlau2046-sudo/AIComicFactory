"""L0: StateManager 纯逻辑单元测试"""

import json
from pathlib import Path


class TestInitProject:
    def test_creates_state_with_all_stages(self, state_manager, projects_root):
        result = state_manager.init_project("test_project")
        assert "stages" in result
        assert len(result["stages"]) == 11  # s1_parse..s9_tts_audio (includes s3b, s4b)

    def test_state_file_created(self, state_manager, projects_root):
        state_manager.init_project("test_project")
        sp = projects_root / "test_project" / "state.json"
        assert sp.exists()

    def test_all_stages_pending(self, state_manager, projects_root):
        result = state_manager.init_project("test_project")
        for stage_name, stage_data in result["stages"].items():
            assert stage_data["status"] == "pending"


class TestGet:
    def test_get_existing(self, state_manager, projects_root):
        state_manager.init_project("test_project")
        result = state_manager.get("test_project")
        assert "stages" in result

    def test_get_nonexistent_auto_inits(self, state_manager, projects_root):
        result = state_manager.get("no_such_project")
        # Auto-initializes
        assert "stages" in result


class TestUpdateStage:
    def test_update_status(self, initialized_project, state_manager):
        state_manager.update_stage(initialized_project, "s1_parse", "running")
        state = state_manager.get(initialized_project)
        assert state["stages"]["s1_parse"]["status"] == "running"

    def test_update_with_metadata(self, initialized_project, state_manager):
        state_manager.update_stage(initialized_project, "s1_parse", "running", model="glm-5.1")
        state = state_manager.get(initialized_project)
        assert state["stages"]["s1_parse"]["model"] == "glm-5.1"

    def test_unknown_stage_raises(self, initialized_project, state_manager):
        import pytest
        with pytest.raises(ValueError, match="Unknown stage"):
            state_manager.update_stage(initialized_project, "s99_nonexistent", "running")


class TestMarkCompleted:
    def test_status_completed(self, initialized_project, state_manager):
        state_manager.mark_completed(initialized_project, "s1_parse", output_file="s1_parsed.json")
        state = state_manager.get(initialized_project)
        assert state["stages"]["s1_parse"]["status"] == "completed"
        assert "ts" in state["stages"]["s1_parse"]


class TestMarkFailed:
    def test_status_failed(self, initialized_project, state_manager):
        state_manager.mark_failed(initialized_project, "s1_parse", error="API timeout")
        state = state_manager.get(initialized_project)
        assert state["stages"]["s1_parse"]["status"] == "failed"
        assert state["stages"]["s1_parse"]["error"] == "API timeout"


class TestMarkStale:
    def test_downstream_reset_to_pending(self, initialized_project, state_manager):
        state_manager.mark_completed(initialized_project, "s1_parse")
        state_manager.mark_completed(initialized_project, "s2_character_extract")
        state_manager.mark_stale(initialized_project, "s2_character_extract")
        state = state_manager.get(initialized_project)
        assert state["stages"]["s1_parse"]["status"] == "completed"
        # mark_stale resets from_stage and downstream to pending (to re-run)
        assert state["stages"]["s2_character_extract"]["status"] == "pending"


class TestNextPending:
    def test_first_pending(self, initialized_project, state_manager):
        result = state_manager.next_pending(initialized_project)
        assert result is not None
        assert "s1" in result

    def test_skips_completed(self, initialized_project, state_manager):
        state_manager.mark_completed(initialized_project, "s1_parse")
        result = state_manager.next_pending(initialized_project)
        assert "s1" not in result

    def test_all_completed(self, initialized_project, state_manager):
        from core.state_manager import STAGE_ORDER
        for stage in STAGE_ORDER:
            state_manager.mark_completed(initialized_project, stage)
        result = state_manager.next_pending(initialized_project)
        assert result is None


class TestProgress:
    def test_progress_format(self, initialized_project, state_manager):
        p = state_manager.progress(initialized_project)
        assert "0" in p

    def test_progress_after_completion(self, initialized_project, state_manager):
        state_manager.mark_completed(initialized_project, "s1_parse")
        p = state_manager.progress(initialized_project)
        assert "1" in p


class TestConcurrentWrite:
    def test_rapid_writes_no_loss(self, initialized_project, state_manager):
        state_manager.update_stage(initialized_project, "s1_parse", "running", key_a="val_a")
        state_manager.update_stage(initialized_project, "s1_parse", "completed", key_b="val_b")
        state = state_manager.get(initialized_project)
        s1 = state["stages"]["s1_parse"]
        assert s1["status"] == "completed"
        assert s1.get("key_b") == "val_b"
