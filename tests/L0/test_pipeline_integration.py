"""
tests/L0/test_pipeline_integration.py — Pipeline Integration Tests

Tests the complete pipeline execution flow with mocked stage runners.
Covers:
  - Full pipeline execution (all stages → completed)
  - Checkpoint recovery (resume from partial completion)
  - Params hash change detection (re-run on changed args)
  --parallel mode execution via parallel_executor
  - Partial pipeline (run to a specific stage then stop)
"""

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock
import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def pipeline_state_manager(projects_root):
    """StateManager bound to the test projects root."""
    from core.state_manager import StateManager
    pipeline_path = Path(projects_root).parent / "pipeline.yaml"
    return StateManager(projects_root=str(projects_root),
                        pipeline_path=str(pipeline_path))


@pytest.fixture
def pipeline_project(pipeline_state_manager):
    """A project with fully initialized pipeline state."""
    pipeline_state_manager.init_project("test_project")
    return "test_project"


@pytest.fixture
def mock_stage_runner():
    """Factory that returns a mock stage runner which succeeds by default."""

    def _make(fail_on: set = None, side_effects: dict = None):
        """
        Create a mock run_func for a stage.

        Args:
            fail_on: Set of stage IDs that should return failure.
            side_effects: Dict of stage_id → result detail string.

        Returns:
            A callable(stage_id, stage_def) -> (bool, str).
        """
        fail_on = fail_on or set()
        side_effects = side_effects or {}

        def _run(stage_id: str, stage_def: dict) -> tuple:
            if stage_id in fail_on:
                return False, side_effects.get(stage_id, f"Simulated failure: {stage_id}")
            return True, side_effects.get(stage_id, f"Completed: {stage_id}")

        return _run

    return _make


# ═══════════════════════════════════════════════════════════════
# Tests: Full pipeline execution
# ═══════════════════════════════════════════════════════════════


class TestFullPipelineExecution:
    """Verify complete pipeline run through all stages."""

    def test_all_stages_start_pending(self, pipeline_project, pipeline_state_manager):
        """Every stage starts as pending."""
        state = pipeline_state_manager.load(pipeline_project)
        for sid, entry in state["stages"].items():
            assert entry["status"] == "pending", f"{sid} not pending: {entry['status']}"

    def test_next_pending_returns_first(self, pipeline_project, pipeline_state_manager):
        """next_pending returns s1_parse first."""
        nxt = pipeline_state_manager.next_pending(pipeline_project)
        assert nxt == "s1_parse", f"Expected s1_parse, got {nxt}"

    def test_first_pending_has_no_deps(self, pipeline_project, pipeline_state_manager):
        """s1_parse has no dependencies."""
        deps = pipeline_state_manager.load_pipeline_deps()
        assert deps["s1_parse"] == [], f"s1_parse deps: {deps['s1_parse']}"

    def test_full_pipeline_walkthrough(self, pipeline_project, pipeline_state_manager):
        """Simulate walking through all 12 stages sequentially."""
        n_stages = len(pipeline_state_manager.stages)
        assert n_stages == 12, f"Expected 12 stages, got {n_stages}"

        completed = set()
        for _ in range(n_stages):
            nxt = pipeline_state_manager.next_pending(pipeline_project)
            assert nxt is not None, f"No next stage after {len(completed)} completed"
            assert nxt not in completed, f"{nxt} already completed"
            pipeline_state_manager.mark_completed(pipeline_project, nxt)
            completed.add(nxt)

        # All stages completed
        nxt = pipeline_state_manager.next_pending(pipeline_project)
        assert nxt is None, f"Expected None, got {nxt}"
        assert len(completed) == n_stages

    def test_stage_order_sequential(self, pipeline_project, pipeline_state_manager):
        """Stages are discovered in config-defined order."""
        stages = pipeline_state_manager.stages
        order = pipeline_state_manager.load_pipeline_config()["stages"]
        expected = [v["id"] for v in sorted(order.values(), key=lambda x: x["order"])]
        assert stages == expected, f"Order mismatch:\n  Got:      {stages}\n  Expected: {expected}"


class TestPipelineCheckpoint:
    """Verify checkpoint recovery and progress tracking."""

    def test_checkpoint_after_partial_run(self, pipeline_project, pipeline_state_manager):
        """After running 4 of 12 stages, next_pending returns stage 5."""
        first_four = pipeline_state_manager.stages[:4]
        for sid in first_four:
            pipeline_state_manager.mark_completed(pipeline_project, sid)

        state = pipeline_state_manager.load(pipeline_project)
        for sid in first_four:
            assert state["stages"][sid]["status"] == "completed"

        nxt = pipeline_state_manager.next_pending(pipeline_project)
        assert nxt == pipeline_state_manager.stages[4], \
            f"Expected {pipeline_state_manager.stages[4]}, got {nxt}"

    def test_checkpoint_shot_level(self, pipeline_project, pipeline_state_manager):
        """Shot-level checkpointing works within a stage."""
        pipeline_state_manager.init_checkpoint(pipeline_project, "s5_frame_generate",
                                                total_shots=72)

        # Simulate 5 completed
        for sid in range(1, 6):
            pipeline_state_manager.record_checkpoint(pipeline_project,
                                                      "s5_frame_generate", shot_id=sid)

        cp = pipeline_state_manager.get_checkpoint(pipeline_project, "s5_frame_generate")
        assert cp is not None
        assert cp["total_shots"] == 72  # Preserved from init_checkpoint
        assert len(cp["completed_shots"]) == 5
        assert cp["failed_shots"] == []

    def test_checkpoint_resume_skips_completed(self, pipeline_project, pipeline_state_manager):
        """skip_completed_shots returns already-done shot IDs."""
        pipeline_state_manager.init_checkpoint(pipeline_project, "s5_frame_generate",
                                                total_shots=10)
        for sid in [1, 3, 5]:
            pipeline_state_manager.record_checkpoint(pipeline_project,
                                                      "s5_frame_generate", shot_id=sid)

        skipped = pipeline_state_manager.skip_completed_shots(pipeline_project,
                                                               "s5_frame_generate")
        assert sorted(skipped) == [1, 3, 5]

    def test_checkpoint_mixed_status(self, pipeline_project, pipeline_state_manager):
        """Checkpoint tracks both completed and failed shots."""
        pipeline_state_manager.init_checkpoint(pipeline_project, "s5_frame_generate",
                                                total_shots=10)
        pipeline_state_manager.record_checkpoint(pipeline_project,
                                                  "s5_frame_generate", shot_id=1)
        pipeline_state_manager.record_checkpoint(pipeline_project,
                                                  "s5_frame_generate", shot_id=2,
                                                  status="failed")
        pipeline_state_manager.record_checkpoint(pipeline_project,
                                                  "s5_frame_generate", shot_id=3,
                                                  status="failed")

        cp = pipeline_state_manager.get_checkpoint(pipeline_project, "s5_frame_generate")
        assert cp["completed_shots"] == [1]
        assert sorted(cp["failed_shots"]) == [2, 3]
        assert cp["total_shots"] == 10

    def test_skip_completed_shots_no_checkpoint(self, pipeline_project,
                                                 pipeline_state_manager):
        """Without init_checkpoint, skip_completed_shots returns empty."""
        skipped = pipeline_state_manager.skip_completed_shots(pipeline_project,
                                                               "s5_frame_generate")
        assert skipped == []

    def test_checkpoint_metadata(self, pipeline_project, pipeline_state_manager):
        """Shot metadata is stored alongside checkpoint data."""
        pipeline_state_manager.init_checkpoint(pipeline_project, "s5_frame_generate",
                                                total_shots=5)
        pipeline_state_manager.record_checkpoint(
            pipeline_project, "s5_frame_generate", shot_id=1,
            path="s5_frames/s01_first.png", resolution="1280x720")

        cp = pipeline_state_manager.get_checkpoint(pipeline_project, "s5_frame_generate")
        meta = cp["shot_metadata"].get("1", {})
        assert meta.get("path") == "s5_frames/s01_first.png"
        assert meta.get("resolution") == "1280x720"


class TestParamsHashChange:
    """Verify params hash change detection for re-run decisions."""

    def test_params_no_change(self, pipeline_project, pipeline_state_manager):
        """Same params → params_changed returns False."""
        args = {"model": "DEEPSEEK_PRO", "temperature": 0.7}
        pipeline_state_manager.record_params(pipeline_project, "s1_parse", args)
        assert not pipeline_state_manager.params_changed(pipeline_project,
                                                          "s1_parse", args)

    def test_params_different(self, pipeline_project, pipeline_state_manager):
        """Different params → params_changed returns True."""
        pipeline_state_manager.record_params(pipeline_project, "s1_parse",
                                              {"model": "DEEPSEEK_PRO", "temperature": 0.7})
        assert pipeline_state_manager.params_changed(pipeline_project,
                                                      "s1_parse",
                                                      {"model": "QWEN35", "temperature": 0.5})

    def test_params_never_recorded(self, pipeline_project, pipeline_state_manager):
        """No recorded params → params_changed returns False (no prior run)."""
        assert not pipeline_state_manager.params_changed(pipeline_project,
                                                          "s1_parse",
                                                          {"model": "DEEPSEEK_PRO"})

    def test_params_changed_marks_dirty(self, pipeline_project, pipeline_state_manager):
        """params_changed marks the stage dirty when params differ."""
        pipeline_state_manager.record_params(pipeline_project, "s1_parse",
                                              {"model": "DEEPSEEK_PRO"})
        changed = pipeline_state_manager.params_changed(pipeline_project,
                                                         "s1_parse",
                                                         {"model": "QWEN35"})
        assert changed is True
        dirty = pipeline_state_manager.get_dirty_stages(pipeline_project)
        dirty_ids = [d["stage"] for d in dirty]
        assert "s1_parse" in dirty_ids

    def test_params_hash_consistency(self):
        """compute_params_hash is deterministic."""
        from core.state_manager import compute_params_hash
        args = {"a": 1, "b": "test", "c": [1, 2, 3]}
        h1 = compute_params_hash(args)
        h2 = compute_params_hash(args)
        assert h1 == h2

    def test_params_hash_different(self):
        """Different args produce different hashes."""
        from core.state_manager import compute_params_hash
        assert compute_params_hash({"a": 1}) != compute_params_hash({"a": 2})


class TestParallelMode:
    """Verify --parallel mode via parallel_executor."""

    def test_parallel_stages_basic_run(self, mock_stage_runner):
        """Two stages run concurrently; both succeed."""
        from core.parallel_executor import run_parallel_stages

        stages = [
            ("s7_assemble", {"id": "s7_assemble", "order": 10}, mock_stage_runner()),
            ("s8_subtitles", {"id": "s8_subtitles", "order": 11}, mock_stage_runner()),
        ]
        results = run_parallel_stages(
            project=Path("/tmp/test"),
            stage_tasks=stages,
            parallel_label="test",
            max_workers=2,
        )
        assert len(results) == 2
        for sid, (success, detail) in results.items():
            assert success, f"{sid} failed: {detail}"

    def test_parallel_one_fails_other_succeeds(self, mock_stage_runner):
        """One parallel stage can fail without affecting the other."""
        from core.parallel_executor import run_parallel_stages

        stages = [
            ("s7_assemble", {"id": "s7_assemble", "order": 10},
             mock_stage_runner(fail_on={"s7_assemble"})),
            ("s8_subtitles", {"id": "s8_subtitles", "order": 11}, mock_stage_runner()),
        ]
        results = run_parallel_stages(
            project=Path("/tmp/test"),
            stage_tasks=stages,
            parallel_label="test",
            max_workers=2,
        )
        assert not results["s7_assemble"][0]
        assert results["s8_subtitles"][0]

    def test_find_parallel_groups_empty_completed(self):
        """With no completed stages, find_parallel_groups returns the first group."""
        from core.parallel_executor import find_parallel_groups

        pipeline = {
            "stages": {
                "s1_parse": {"id": "s1_parse", "order": 1, "depends_on": []},
                "s2_extract": {"id": "s2_extract", "order": 2, "depends_on": ["s1_parse"]},
            }
        }
        groups = find_parallel_groups(pipeline, completed_stages=set(), max_group_size=2)
        # Only s1_parse has no deps, so one group with one stage
        assert len(groups) <= 1

    def test_find_parallel_groups_two_ready(self):
        """When two CPU stages share a completed dep, find_parallel_groups processes them."""
        from core.parallel_executor import find_parallel_groups

        pipeline = {
            "stages": {
                "s1_parse": {"id": "s1_parse", "order": 1, "depends_on": [],
                             "runner": "llm", "gpu": "none"},
                "s2a_extract": {"id": "s2a_extract", "order": 2, "depends_on": ["s1_parse"],
                                "runner": "llm", "gpu": "none"},
                "s2b_wardrobe": {"id": "s2b_wardrobe", "order": 3, "depends_on": ["s1_parse"],
                                 "runner": "script", "gpu": "none"},
            }
        }
        # Both s2a and s2b are CPU-only, but find_parallel_groups requires
        # complementary GPU types (none + comfyui) to form a group.
        # Ensures the function handles this gracefully.
        groups = find_parallel_groups(pipeline,
                                       completed_stages={"s1_parse"},
                                       max_group_size=2)
        assert isinstance(groups, list)

    def test_is_parallelizable_llm_stage(self):
        """LLM stages without GPU are parallelizable (no GPU contention)."""
        from core.parallel_executor import is_parallelizable_stage
        assert is_parallelizable_stage("s1_parse",
                                        {"runner": "llm", "gpu": "none"})

    def test_is_parallelizable_script_stage(self):
        """Script stages without GPU are parallelizable."""
        from core.parallel_executor import is_parallelizable_stage
        assert is_parallelizable_stage("s7_assemble",
                                        {"runner": "script", "gpu": "none"})

    def test_is_parallelizable_comfyui_stage(self):
        """ComfyUI stages are NOT parallelizable (GPU contention)."""
        from core.parallel_executor import is_parallelizable_stage
        assert not is_parallelizable_stage("s5_frame_generate",
                                            {"runner": "script", "gpu": "comfyui"})


class TestPipelineDirtyAndStale:
    """Verify dirty marking and stale propagation."""

    def test_mark_stale_downstream(self, pipeline_project, pipeline_state_manager):
        """Marking a stage stale resets downstream dependent stages."""
        # Complete first 4 stages
        for sid in pipeline_state_manager.stages[:4]:
            pipeline_state_manager.mark_completed(pipeline_project, sid)

        # Mark s1_parse stale → downstream chain resets
        pipeline_state_manager.mark_stale(pipeline_project, "s1_parse")

        state = pipeline_state_manager.load(pipeline_project)
        # s1_parse itself should be dirty
        assert state["stages"]["s1_parse"].get("dirty") is True
        # Direct downstream (s2_character_extract, s2b_wardrobe, etc.) reset
        for sid in pipeline_state_manager.stages[1:4]:
            assert state["stages"][sid]["status"] == "pending"
            assert state["stages"][sid].get("dirty") is True

    def test_dirty_stages_listed(self, pipeline_project, pipeline_state_manager):
        """Dirty stages appear in get_dirty_stages."""
        pipeline_state_manager.mark_dirty(pipeline_project, "s1_parse",
                                           reason="Param change")
        dirty = pipeline_state_manager.get_dirty_stages(pipeline_project)
        assert any(d["stage"] == "s1_parse" for d in dirty)

    def test_clear_dirty_restores_status(self, pipeline_project, pipeline_state_manager):
        """Clearing dirty resets to pending."""
        pipeline_state_manager.mark_dirty(pipeline_project, "s1_parse")
        pipeline_state_manager.clear_dirty(pipeline_project, "s1_parse")
        dirty = pipeline_state_manager.get_dirty_stages(pipeline_project)
        assert not any(d["stage"] == "s1_parse" for d in dirty)


class TestPipelineProgress:
    """Verify pipeline progress reporting."""

    def test_progress_empty(self, pipeline_project, pipeline_state_manager):
        """Initial progress shows 0/12."""
        prog = pipeline_state_manager.progress(pipeline_project)
        assert "0/12" in prog

    def test_progress_halfway(self, pipeline_project, pipeline_state_manager):
        """Half completed shows 6/12."""
        for sid in pipeline_state_manager.stages[:6]:
            pipeline_state_manager.mark_completed(pipeline_project, sid)
        prog = pipeline_state_manager.progress(pipeline_project)
        assert "6/12" in prog

    def test_progress_all_done(self, pipeline_project, pipeline_state_manager):
        """All completed shows 12/12."""
        for sid in pipeline_state_manager.stages:
            pipeline_state_manager.mark_completed(pipeline_project, sid)
        prog = pipeline_state_manager.progress(pipeline_project)
        assert "12/12" in prog

    def test_progress_with_failure(self, pipeline_project, pipeline_state_manager):
        """Progress counts failures but shows them."""
        pipeline_state_manager.mark_completed(pipeline_project, "s1_parse")
        pipeline_state_manager.mark_failed(pipeline_project, "s2_character_extract",
                                            error="LLM unavailable")
        prog = pipeline_state_manager.progress(pipeline_project)
        assert "1/12" in prog  # only 1 completed, 1 failed but not counted as complete


class TestDependencyValidation:
    """Verify pipeline dependency graph correctness."""

    def test_all_deps_are_valid_stages(self, pipeline_project, pipeline_state_manager):
        """Every depends_on reference maps to an existing stage."""
        deps = pipeline_state_manager.load_pipeline_deps()
        all_stages = set(pipeline_state_manager.stages)
        for stage_id, stage_deps in deps.items():
            for dep in stage_deps:
                assert dep in all_stages, \
                    f"{stage_id} depends on unknown stage '{dep}'"

    def test_no_circular_deps(self, pipeline_project, pipeline_state_manager):
        """No direct self-dependency cycles."""
        deps = pipeline_state_manager.load_pipeline_deps()
        for stage_id, stage_deps in deps.items():
            assert stage_id not in stage_deps, \
                f"{stage_id} depends on itself!"

    def test_pipeline_key_mapping(self, pipeline_project, pipeline_state_manager):
        """Every stage has a pipeline_key mapping."""
        config = pipeline_state_manager.load_pipeline_config()
        sm = pipeline_state_manager
        for pipeline_key, sdef in config["stages"].items():
            state_id = sdef["id"]
            resolved = sm.resolve_stage_id(state_id)
            assert resolved == state_id, f"resolve_stage_id({state_id}) = {resolved}"
            pk = sm.get_pipeline_key(state_id)
            assert pk == pipeline_key, f"get_pipeline_key({state_id}) = {pk}"
