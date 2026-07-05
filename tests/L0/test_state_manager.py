"""L0: StateManager 纯逻辑单元测试 (v2)"""

import json
from pathlib import Path

EXPECTED_STAGES = 12  # s1..s9 + s2b + s3b + s4b


class TestPipelineConfig:
    """Verify pipeline.yaml is the single source of truth."""

    def test_loads_12_stages(self, state_manager):
        stages = state_manager.load_pipeline_stages()
        assert len(stages) == EXPECTED_STAGES
        # Must include s2b_wardrobe_extract (the one previously missing)
        assert "s2b_wardrobe_extract" in stages

    def test_order_matches_pipeline(self, state_manager):
        stages = state_manager.load_pipeline_stages()
        # s2b comes after s2, before s4
        s2_idx = stages.index("s2_character_extract")
        s2b_idx = stages.index("s2b_wardrobe_extract")
        s4_idx = stages.index("s4_shot_split")
        assert s2_idx < s2b_idx < s4_idx, f"wrong order: {stages}"

    def test_stage_def_loaded(self, state_manager):
        sdef = state_manager.get_stage_def("s1_parse")
        assert sdef.get("description") == "剧本解析"
        assert sdef.get("runner") == "llm"

    def test_pipeline_key_mapping(self, state_manager):
        # State ID → pipeline key
        assert state_manager.get_pipeline_key("s1_parse") == "s1_script_parse"
        # Pipeline key → state ID
        assert state_manager.resolve_stage_id("s1_script_parse") == "s1_parse"
        assert state_manager.resolve_stage_id("s1_parse") == "s1_parse"

    def test_deps_loaded(self, state_manager):
        deps = state_manager.load_pipeline_deps()
        assert "s5_frame_generate" in deps
        assert "s3_character_image" in deps["s5_frame_generate"]
        assert deps["s1_parse"] == []


class TestInitProject:
    def test_creates_state_with_all_stages(self, state_manager, projects_root):
        result = state_manager.init_project("test_project")
        assert "stages" in result
        assert len(result["stages"]) == EXPECTED_STAGES

    def test_state_file_created(self, state_manager, projects_root):
        state_manager.init_project("test_project")
        sp = projects_root / "test_project" / "state.json"
        assert sp.exists()

    def test_all_stages_pending(self, state_manager, projects_root):
        result = state_manager.init_project("test_project")
        for stage_name, stage_data in result["stages"].items():
            assert stage_data["status"] == "pending"

    def test_v2_schema(self, state_manager, projects_root):
        result = state_manager.init_project("test_project")
        assert result["schema_version"] == 2
        # v2 fields exist
        for sid, entry in result["stages"].items():
            assert "checkpoint" in entry
            assert "params_hash" in entry
            assert "dirty" in entry
            assert "dirty_reason" in entry

    def test_checkpoint_history(self, state_manager, projects_root):
        result = state_manager.init_project("test_project")
        assert "checkpoint_history" in result
        assert "dirty_history" in result


class TestGet:
    def test_get_existing(self, state_manager, projects_root):
        state_manager.init_project("test_project")
        result = state_manager.get("test_project")
        assert "stages" in result

    def test_get_nonexistent_auto_inits(self, state_manager, projects_root):
        result = state_manager.get("no_such_project")
        assert "stages" in result


class TestUpdateStage:
    def test_update_status(self, initialized_project, state_manager):
        state_manager.update_stage(initialized_project, "s1_parse", "running")
        state = state_manager.get(initialized_project)
        assert state["stages"]["s1_parse"]["status"] == "running"

    def test_update_with_metadata(self, initialized_project, state_manager):
        state_manager.update_stage(initialized_project, "s1_parse", "running", model="test-model")
        state = state_manager.get(initialized_project)
        assert state["stages"]["s1_parse"]["model"] == "test-model"

    def test_unknown_stage_raises(self, initialized_project, state_manager):
        import pytest
        with pytest.raises(ValueError, match="Unknown stage"):
            state_manager.update_stage(initialized_project, "s99_nonexistent", "running")

    def test_update_with_pipeline_key(self, initialized_project, state_manager):
        """Can use pipeline.yaml key instead of state ID."""
        state_manager.update_stage(initialized_project, "s1_script_parse", "running")
        state = state_manager.get(initialized_project)
        assert state["stages"]["s1_parse"]["status"] == "running"

    def test_update_s2b(self, initialized_project, state_manager):
        """s2b_wardrobe_extract is now a valid stage."""
        state_manager.update_stage(initialized_project, "s2b_wardrobe_extract", "running")
        state = state_manager.get(initialized_project)
        assert state["stages"]["s2b_wardrobe_extract"]["status"] == "running"


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
        assert state["stages"]["s2_character_extract"]["status"] == "pending"
        assert state["stages"]["s2_character_extract"]["dirty"] is True

    def test_stale_downstream_dirty(self, initialized_project, state_manager):
        state_manager.mark_completed(initialized_project, "s1_parse")
        state_manager.mark_completed(initialized_project, "s2_character_extract")
        state_manager.mark_stale(initialized_project, "s2_character_extract")
        state = state_manager.get(initialized_project)
        # s2b, s4, s4b, ... should all be dirty
        assert state["stages"]["s2b_wardrobe_extract"]["dirty"] is True

    def test_stale_isolates_unrelated_stages(self, initialized_project, state_manager):
        """mark_stale on s4_shot_split must NOT mark s3_character_image.

        s3_character_image depends on s2_character_extract only, NOT on
        s4_shot_split.  The old sequential-slice approach would incorrectly
        mark s3 because it comes after s4 in pipeline order.
        """
        # Mark several stages completed
        state_manager.mark_completed(initialized_project, "s1_parse")
        state_manager.mark_completed(initialized_project, "s2_character_extract")
        state_manager.mark_completed(initialized_project, "s3_character_image")
        state_manager.mark_completed(initialized_project, "s4_shot_split")
        state_manager.mark_completed(initialized_project, "s4b_keyframe_assets")

        # Now mark s4_shot_split stale
        state_manager.mark_stale(initialized_project, "s4_shot_split")
        state = state_manager.get(initialized_project)

        # s3_character_image does NOT depend on s4 → must remain completed
        assert state["stages"]["s3_character_image"]["status"] == "completed", \
            "s3 should be untouched by s4 stale"

        # s4b depends on s4 → must be stale
        assert state["stages"]["s4b_keyframe_assets"]["dirty"] is True

        # s5 depends on s4 (via s4b) → must be stale
        assert state["stages"]["s5_frame_generate"]["dirty"] is True

    def test_stale_line_chain(self, initialized_project, state_manager):
        """mark_stale on s6 should cascade only to s7→s8→s9, not earlier stages."""
        stages = state_manager.load_pipeline_stages()
        for s in stages:
            state_manager.mark_completed(initialized_project, s)

        state_manager.mark_stale(initialized_project, "s6_video_generate")
        state = state_manager.get(initialized_project)

        # s6 is stale
        assert state["stages"]["s6_video_generate"]["dirty"] is True
        # s7, s8, s9 depend on s6 (transitively)
        assert state["stages"]["s7_assemble"]["dirty"] is True
        assert state["stages"]["s8_subtitles"]["dirty"] is True
        assert state["stages"]["s9_tts_audio"]["dirty"] is True

        # Earlier stages untouched
        assert state["stages"]["s1_parse"]["status"] == "completed"
        assert state["stages"]["s5_frame_generate"]["status"] == "completed"


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
        stages = state_manager.load_pipeline_stages()
        for stage in stages:
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

    def test_progress_12_stages(self, initialized_project, state_manager):
        p = state_manager.progress(initialized_project)
        assert "12" in p or "12 stages" in p


class TestConcurrentWrite:
    def test_rapid_writes_no_loss(self, initialized_project, state_manager):
        state_manager.update_stage(initialized_project, "s1_parse", "running", key_a="val_a")
        state_manager.update_stage(initialized_project, "s1_parse", "completed", key_b="val_b")
        state = state_manager.get(initialized_project)
        s1 = state["stages"]["s1_parse"]
        assert s1["status"] == "completed"
        assert s1.get("key_b") == "val_b"


# ═══════════════════════════════════════════════════════════════════
# v2 Feature Tests
# ═══════════════════════════════════════════════════════════════════

class TestCheckpoint:
    """Checkpoint mechanism: per-shot progress tracking."""

    def test_record_checkpoint(self, initialized_project, state_manager):
        state_manager.init_checkpoint(initialized_project, "s5_frame_generate", total_shots=72)
        state_manager.record_checkpoint(initialized_project, "s5_frame_generate", shot_id=1)
        state_manager.record_checkpoint(initialized_project, "s5_frame_generate", shot_id=2)
        state_manager.record_checkpoint(initialized_project, "s5_frame_generate", shot_id=3, status="failed")
        cp = state_manager.get_checkpoint(initialized_project, "s5_frame_generate")
        assert cp is not None
        assert cp["total_shots"] == 72
        assert 1 in cp["completed_shots"]
        assert 2 in cp["completed_shots"]
        assert 3 in cp["failed_shots"]

    def test_skip_completed(self, initialized_project, state_manager):
        state_manager.init_checkpoint(initialized_project, "s5_frame_generate", total_shots=50)
        for i in range(1, 38):
            state_manager.record_checkpoint(initialized_project, "s5_frame_generate", i)
        skipped = state_manager.skip_completed_shots(initialized_project, "s5_frame_generate")
        assert len(skipped) == 37
        assert 37 in skipped
        assert 38 not in skipped

    def test_checkpoint_preserved_across_writes(self, initialized_project, state_manager):
        state_manager.init_checkpoint(initialized_project, "s5_frame_generate", total_shots=10)
        state_manager.record_checkpoint(initialized_project, "s5_frame_generate", 1)
        state_manager.mark_completed(initialized_project, "s5_frame_generate", generated="1/10")
        cp = state_manager.get_checkpoint(initialized_project, "s5_frame_generate")
        assert cp is not None
        assert 1 in cp["completed_shots"]

    def test_no_checkpoint_returns_none(self, initialized_project, state_manager):
        cp = state_manager.get_checkpoint(initialized_project, "s1_parse")
        assert cp is None

    def test_checkpoint_with_metadata(self, initialized_project, state_manager):
        state_manager.init_checkpoint(initialized_project, "s5_frame_generate", total_shots=5)
        state_manager.record_checkpoint(
            initialized_project, "s5_frame_generate", 1,
            path="s5_frames/s01_first.png", resolution="1024x768"
        )
        cp = state_manager.get_checkpoint(initialized_project, "s5_frame_generate")
        meta = cp["shot_metadata"]["1"]
        assert meta["path"] == "s5_frames/s01_first.png"
        assert meta["resolution"] == "1024x768"


class TestParamsHash:
    """Parameter hashing: detect config changes."""

    def test_compute_hash(self):
        from core.state_manager import compute_params_hash
        h1 = compute_params_hash({"style": "vivid", "frames": "both"})
        h2 = compute_params_hash({"frames": "both", "style": "vivid"})
        assert h1 == h2  # deterministic regardless of key order
        assert h1.startswith("sha256:")

    def test_different_params_different_hash(self):
        from core.state_manager import compute_params_hash
        h1 = compute_params_hash({"style": "vivid"})
        h2 = compute_params_hash({"style": "classic"})
        assert h1 != h2

    def test_record_params(self, initialized_project, state_manager):
        state_manager.record_params(initialized_project, "s1_parse",
                                     {"model": "deepseek-pro", "temp": 0.3})
        h = state_manager.get_params_hash(initialized_project, "s1_parse")
        assert h is not None
        assert h.startswith("sha256:")

    def test_params_changed(self, initialized_project, state_manager):
        state_manager.record_params(initialized_project, "s1_parse",
                                     {"model": "deepseek-pro", "temp": 0.3})
        changed = state_manager.params_changed(initialized_project, "s1_parse",
                                                {"model": "deepseek-pro", "temp": 0.7})
        assert changed is True

    def test_params_unchanged(self, initialized_project, state_manager):
        state_manager.record_params(initialized_project, "s1_parse",
                                     {"model": "deepseek-pro", "temp": 0.3})
        changed = state_manager.params_changed(initialized_project, "s1_parse",
                                                {"model": "deepseek-pro", "temp": 0.3})
        assert changed is False

    def test_params_changed_marks_dirty(self, initialized_project, state_manager):
        state_manager.record_params(initialized_project, "s1_parse",
                                     {"model": "glm-5.1"})
        state_manager.params_changed(initialized_project, "s1_parse",
                                      {"model": "deepseek-pro"})
        dirty = state_manager.get_dirty_stages(initialized_project)
        assert any(d["stage"] == "s1_parse" for d in dirty)

    def test_params_never_run_returns_false(self, initialized_project, state_manager):
        changed = state_manager.params_changed(initialized_project, "s1_parse",
                                                {"model": "deepseek-pro"})
        assert changed is False  # no prior hash to compare


class TestDirtyMarking:
    """Enhanced dirty marking with reasons and history."""

    def test_mark_dirty(self, initialized_project, state_manager):
        state_manager.mark_dirty(initialized_project, "s1_parse", reason="params changed")
        state = state_manager.get(initialized_project)
        assert state["stages"]["s1_parse"]["dirty"] is True
        assert "params changed" in state["stages"]["s1_parse"]["dirty_reason"]

    def test_get_dirty_stages(self, initialized_project, state_manager):
        state_manager.mark_dirty(initialized_project, "s1_parse", reason="test")
        state_manager.mark_dirty(initialized_project, "s2_character_extract", reason="upstream")
        dirty = state_manager.get_dirty_stages(initialized_project)
        assert len(dirty) == 2
        stages = {d["stage"] for d in dirty}
        assert "s1_parse" in stages
        assert "s2_character_extract" in stages

    def test_clear_dirty(self, initialized_project, state_manager):
        state_manager.mark_dirty(initialized_project, "s1_parse", reason="test")
        dirty = state_manager.get_dirty_stages(initialized_project)
        assert len(dirty) == 1
        state_manager.clear_dirty(initialized_project, "s1_parse")
        dirty = state_manager.get_dirty_stages(initialized_project)
        assert len(dirty) == 0

    def test_dirty_history(self, initialized_project, state_manager):
        state_manager.mark_dirty(initialized_project, "s1_parse", reason="param change")
        state_manager.mark_dirty(initialized_project, "s2_character_extract", reason="manual")
        state = state_manager.get(initialized_project)
        assert len(state["dirty_history"]) == 2
        assert state["dirty_history"][0]["stage"] == "s1_parse"
        assert state["dirty_history"][1]["reason"] == "manual"

    def test_dirty_affects_next_pending(self, initialized_project, state_manager):
        """Dirty stages should be picked up by next_pending()."""
        state_manager.mark_completed(initialized_project, "s1_parse")
        state_manager.mark_completed(initialized_project, "s2_character_extract")
        # Mark s1_parse dirty again
        state_manager.mark_dirty(initialized_project, "s1_parse", reason="re-run")
        # next_pending should find s1_parse (it's dirty)
        next_stage = state_manager.next_pending(initialized_project)
        assert next_stage == "s1_parse"


class TestMigration:
    """v1 → v2 schema migration."""

    def test_migrate_v1_to_v2(self, initialized_project, state_manager):
        """Direct migration test."""
        from core.state_manager import migrate_v1_to_v2
        stages = state_manager.load_pipeline_stages()
        v1_state = {
            "schema_version": 1,
            "project": "test",
            "created": "2026-01-01T00:00:00+08:00",
            "updated": "2026-01-01T00:00:00+08:00",
            "stages": {
                "s1_parse": {"status": "completed", "ts": "2026-01-01T00:00:00+08:00"},
                "s2_character_extract": {"status": "completed", "ts": "2026-01-01T00:00:00+08:00"},
            },
            "errors": [],
        }
        v2 = migrate_v1_to_v2(v1_state, stages)
        assert v2["schema_version"] == 2
        assert v2["_migrated_from_v1"] is True
        # v2 fields added
        for sid in ["s1_parse", "s2_character_extract"]:
            entry = v2["stages"][sid]
            assert "checkpoint" in entry
            assert "params_hash" in entry
            assert "dirty" in entry
        # Missing stages filled in
        assert "s2b_wardrobe_extract" in v2["stages"]
        assert v2["stages"]["s2b_wardrobe_extract"]["status"] == "pending"

    def test_auto_migrate_on_load(self, state_manager, projects_root):
        """Writing a v1 state.json and loading it should auto-migrate."""
        stages = state_manager.load_pipeline_stages()
        v1_state = {
            "schema_version": 1,
            "project": "legacy_project",
            "created": "2026-06-01T00:00:00+08:00",
            "updated": "2026-06-01T00:00:00+08:00",
            "stages": {
                "s1_parse": {"status": "completed"},
                "s2_character_extract": {"status": "completed"},
                "s3_character_image": {"status": "completed"},
                "s3b_four_view": {"status": "completed"},
                "s4_shot_split": {"status": "completed"},
                "s4b_keyframe_assets": {"status": "completed"},
                "s5_frame_generate": {"status": "completed"},
                "s6_video_generate": {"status": "completed"},
                "s7_assemble": {"status": "completed"},
                "s8_subtitles": {"status": "completed"},
                "s9_tts_audio": {"status": "completed"},
            },
            "errors": [],
        }
        # Write v1 state.json
        proj_dir = projects_root / "legacy_project"
        proj_dir.mkdir()
        state_path = proj_dir / "state.json"
        with open(state_path, "w") as f:
            json.dump(v1_state, f)

        # Load should auto-migrate
        loaded = state_manager.get("legacy_project")
        assert loaded["schema_version"] == 2
        assert "s2b_wardrobe_extract" in loaded["stages"]
        assert loaded["stages"]["s1_parse"]["status"] == "completed"

    def test_migrate_idempotent(self, initialized_project, state_manager):
        """Migrating an already v2 state should be a no-op."""
        from core.state_manager import migrate_v1_to_v2
        stages = state_manager.load_pipeline_stages()
        v2_state = state_manager.get(initialized_project)
        original_updated = v2_state["updated"]
        result = migrate_v1_to_v2(v2_state, stages)
        assert result["schema_version"] == 2
        assert result["updated"] == original_updated  # no changes


class TestS2BIntegration:
    """s2b_wardrobe_extract is now a first-class stage."""

    def test_s2b_in_pipeline(self, state_manager):
        stages = state_manager.load_pipeline_stages()
        assert "s2b_wardrobe_extract" in stages

    def test_s2b_deps(self, state_manager):
        deps = state_manager.load_pipeline_deps()
        assert "s2_character_extract" in deps["s2b_wardrobe_extract"]

    def test_s2b_works_in_pipeline(self, initialized_project, state_manager):
        state_manager.mark_completed(initialized_project, "s1_parse")
        state_manager.mark_completed(initialized_project, "s2_character_extract")
        nxt = state_manager.next_pending(initialized_project)
        assert nxt == "s2b_wardrobe_extract"


class TestLoadPipelineStages:
    """Verify load_pipeline_stages() is the primary entry point."""

    def test_returns_list(self, state_manager):
        stages = state_manager.load_pipeline_stages()
        assert isinstance(stages, list)
        assert len(stages) == EXPECTED_STAGES

    def test_cached(self, state_manager):
        s1 = state_manager.load_pipeline_stages()
        s2 = state_manager.load_pipeline_stages()
        assert s1 is s2  # same cached object

    def test_contains_specific_stages(self, state_manager):
        stages = state_manager.load_pipeline_stages()
        expected = [
            "s1_parse", "s2_character_extract", "s2b_wardrobe_extract",
            "s4_shot_split", "s4b_keyframe_assets",
            "s3_character_image", "s3b_four_view",
            "s5_frame_generate", "s6_video_generate",
            "s7_assemble", "s8_subtitles", "s9_tts_audio",
        ]
        for s in expected:
            assert s in stages, f"Missing stage: {s}"

    def test_compute_params_hash_function(self):
        """compute_params_hash is importable from core."""
        from core.state_manager import compute_params_hash
        h = compute_params_hash({"test": 1})
        assert isinstance(h, str)
        assert h.startswith("sha256:")


class TestYamlParsing:
    """YAML parser handles all pipeline.yaml fields correctly."""

    def test_parse_yaml_simple_importable(self):
        from core.state_manager import _parse_yaml_simple
        assert callable(_parse_yaml_simple)

    def test_parse_inline_list_field(self):
        """_parse_yaml_simple must handle fields like 'args: [--style, vivid]'."""
        from core.state_manager import _parse_yaml_simple
        text = """stages:
  s3_character_image:
    id: s3_character_image
    args: [--style, vivid]
    description: "test"
"""
        result = _parse_yaml_simple(text)
        stages = result.get("stages", {})
        assert "s3_character_image" in stages
        assert stages["s3_character_image"].get("args") == ["--style", "vivid"]
        assert stages["s3_character_image"].get("description") == "test"

    def test_parse_multiline_list_field(self):
        """_parse_yaml_simple must handle multi-line list under a stage field."""
        from core.state_manager import _parse_yaml_simple
        text = """stages:
  test_stage:
    id: test
    depends_on:
      - s1_parse
      - s2_character_extract
    args:
      - --style
      - vivid
    description: "multi-line test"
"""
        result = _parse_yaml_simple(text)
        stages = result.get("stages", {})
        assert "test_stage" in stages
        dep_list = stages["test_stage"].get("depends_on")
        assert dep_list == ["s1_parse", "s2_character_extract"], f"got {dep_list}"
        arg_list = stages["test_stage"].get("args")
        assert arg_list == ["--style", "vivid"], f"got {arg_list}"
        assert stages["test_stage"].get("description") == "multi-line test"

    def test_parse_multiple_stages_with_lists(self):
        """Each stage's lists must be stored under the correct stage key."""
        from core.state_manager import _parse_yaml_simple
        text = """stages:
  stage_a:
    id: a
    deps:
      - x
      - y
  stage_b:
    id: b
    tags:
      - foo
      - bar
"""
        result = _parse_yaml_simple(text)
        stages = result.get("stages", {})
        assert stages["stage_a"].get("deps") == ["x", "y"], f"got {stages['stage_a'].get('deps')}"
        assert stages["stage_b"].get("tags") == ["foo", "bar"], f"got {stages['stage_b'].get('tags')}"


class TestBackwardCompat:
    """Legacy STAGE_ORDER and STAGE_LABELS still work."""

    def test_stage_order_exists(self):
        from core.state_manager import STAGE_ORDER
        assert len(STAGE_ORDER) == 11  # legacy, does NOT include s2b

    def test_stage_labels_exists(self):
        from core.state_manager import STAGE_LABELS
        assert "s1_parse" in STAGE_LABELS

    def test_stage_deps_exists(self):
        from core.state_manager import STAGE_DEPS
        assert "s1_parse" in STAGE_DEPS
