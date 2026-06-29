"""L1: StateManager + AssetManager 协作集成测试"""

import json
from pathlib import Path


def _make_file(parent, name):
    f = parent / name
    f.write_bytes(b"test_data")
    return f


class TestInitAndRegister:
    def test_init_then_register(self, state_manager, asset_manager, projects_root):
        pd = projects_root / "test_project"
        refs = pd / "s3_refs"
        refs.mkdir(parents=True, exist_ok=True)

        state_manager.init_project("test_project")

        f = _make_file(refs, "s01_ref_v1.png")
        result = asset_manager.register("test_project", "character_ref", "s01", f, "s3_refs")

        state = state_manager.get("test_project")
        assert "stages" in state

        active = asset_manager.get_active("test_project", "s01", "character_ref")
        assert active is not None
        assert active["version"] == 1


class TestInvalidateAndStale:
    def test_invalidate_asset_mark_stale(self, state_manager, asset_manager, projects_root):
        pd = projects_root / "test_project"
        frames = pd / "s5_frames"
        frames.mkdir(parents=True, exist_ok=True)

        state_manager.init_project("test_project")

        f = _make_file(frames, "s01_first_v1.png")
        asset_manager.register("test_project", "first_frame", "s01", f, "s5_frames")

        # Complete then mark stale (resets to pending for re-run)
        state_manager.mark_completed("test_project", "s5_frame_generate")
        asset_manager.invalidate_shot("test_project", "s01")

        active = asset_manager.get_active("test_project", "s01", "first_frame")
        assert active is None

        state_manager.mark_stale("test_project", "s5_frame_generate")
        state = state_manager.get("test_project")
        assert state["stages"]["s5_frame_generate"]["status"] == "pending"


class TestFullLifecycle:
    def test_register_invalidate_reregister(self, state_manager, asset_manager, projects_root):
        pd = projects_root / "test_project"
        refs = pd / "s3_refs"
        refs.mkdir(parents=True, exist_ok=True)

        state_manager.init_project("test_project")

        f1 = _make_file(refs, "s01_ref_v1.png")
        asset_manager.register("test_project", "character_ref", "s01", f1, "s3_refs")

        asset_manager.invalidate_shot("test_project", "s01")

        f2 = _make_file(refs, "s01_ref_v2.png")
        asset_manager.register("test_project", "character_ref", "s01", f2, "s3_refs")

        history = asset_manager.get_history("test_project", "s01", "character_ref")
        assert len(history) == 2

        active = asset_manager.get_active("test_project", "s01", "character_ref")
        assert active["version"] == 2
