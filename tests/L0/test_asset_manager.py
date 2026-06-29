"""L0: AssetManager 纯逻辑单元测试"""

import json
from pathlib import Path


def _make_file(parent, name):
    f = parent / name
    f.write_bytes(b"test_data")
    return f


def _setup_project(projects_root, name="test_project", subdirs=None):
    pd = projects_root / name
    for d in (subdirs or ["s3_refs", "s5_frames", "s6_clips"]):
        (pd / d).mkdir(parents=True, exist_ok=True)
    return pd


class TestRegister:
    def test_register_new(self, asset_manager, projects_root):
        pd = _setup_project(projects_root)
        f = _make_file(pd / "s3_refs", "s01_ref_v1.png")
        result = asset_manager.register("test_project", "character_ref", "s01", f, "s3_refs")
        assert result["version"] == 1
        assert result["is_active"] is True
        assert "file_path" in result

    def test_register_v2_deactivates_v1(self, asset_manager, projects_root):
        pd = _setup_project(projects_root)
        f1 = _make_file(pd / "s3_refs", "s01_ref_v1.png")
        asset_manager.register("test_project", "character_ref", "s01", f1, "s3_refs")

        f2 = _make_file(pd / "s3_refs", "s01_ref_v2.png")
        result = asset_manager.register("test_project", "character_ref", "s01", f2, "s3_refs")

        assert result["version"] == 2
        assert result["is_active"] is True

        # v1 should be inactive
        history = asset_manager.get_history("test_project", "s01", "character_ref")
        assert len(history) == 2
        v1_entry = [h for h in history if h["version"] == 1][0]
        assert v1_entry["is_active"] is False

    def test_register_different_type_independent(self, asset_manager, projects_root):
        pd = _setup_project(projects_root)
        f1 = _make_file(pd / "s5_frames", "s01_first_v1.png")
        f2 = _make_file(pd / "s5_frames", "s01_last_v1.png")

        r1 = asset_manager.register("test_project", "first_frame", "s01", f1, "s5_frames")
        r2 = asset_manager.register("test_project", "last_frame", "s01", f2, "s5_frames")

        assert r1["version"] == 1
        assert r2["version"] == 1

        # Both should be active (different types)
        active = asset_manager.get_active_for_shot("test_project", "s01")
        assert len(active) == 2
        types = {a["asset_type"] for a in active}
        assert types == {"first_frame", "last_frame"}

    def test_register_multiple_shots(self, asset_manager, projects_root):
        pd = _setup_project(projects_root)
        for sn in ["s01", "s02"]:
            f = _make_file(pd / "s3_refs", f"{sn}_ref_v1.png")
            asset_manager.register("test_project", "character_ref", sn, f, "s3_refs")

        report = asset_manager.list_project("test_project")
        assert report["by_type"]["character_ref"] == 2


class TestGetActive:
    def test_get_active(self, asset_manager, projects_root):
        pd = _setup_project(projects_root)
        f = _make_file(pd / "s3_refs", "s01_ref_v1.png")
        asset_manager.register("test_project", "character_ref", "s01", f, "s3_refs")

        active = asset_manager.get_active("test_project", "s01", "character_ref")
        assert active is not None
        assert active["version"] == 1

    def test_get_active_not_found(self, asset_manager, projects_root):
        active = asset_manager.get_active("test_project", "s99", "character_ref")
        assert active is None


class TestGetActiveForShot:
    def test_returns_list(self, asset_manager, projects_root):
        pd = _setup_project(projects_root)
        f1 = _make_file(pd / "s5_frames", "s01_first_v1.png")
        f2 = _make_file(pd / "s5_frames", "s01_last_v1.png")
        asset_manager.register("test_project", "first_frame", "s01", f1, "s5_frames")
        asset_manager.register("test_project", "last_frame", "s01", f2, "s5_frames")

        active = asset_manager.get_active_for_shot("test_project", "s01")
        assert isinstance(active, list)
        assert len(active) == 2
        types = {a["asset_type"] for a in active}
        assert "first_frame" in types
        assert "last_frame" in types

    def test_empty_for_no_assets(self, asset_manager, projects_root):
        _setup_project(projects_root)
        active = asset_manager.get_active_for_shot("test_project", "s99")
        assert isinstance(active, list)
        assert len(active) == 0


class TestGetHistory:
    def test_get_history_multi_version(self, asset_manager, projects_root):
        pd = _setup_project(projects_root)
        for v in range(1, 4):
            f = _make_file(pd / "s3_refs", f"s01_ref_v{v}.png")
            asset_manager.register("test_project", "character_ref", "s01", f, "s3_refs")

        history = asset_manager.get_history("test_project", "s01", "character_ref")
        assert len(history) == 3
        versions = [h["version"] for h in history]
        assert 1 in versions
        assert 2 in versions
        assert 3 in versions
        # Latest should be active, earlier inactive
        v3 = [h for h in history if h["version"] == 3][0]
        v1 = [h for h in history if h["version"] == 1][0]
        assert v3["is_active"] is True
        assert v1["is_active"] is False

    def test_get_history_empty(self, asset_manager, projects_root):
        history = asset_manager.get_history("test_project", "s99", "character_ref")
        assert history == []


class TestGetCharacterActive:
    def test_get_by_character_name(self, asset_manager, projects_root):
        pd = _setup_project(projects_root)
        f = _make_file(pd / "s3_refs", "李慕白_ref_v1.png")
        # get_character_active looks for metadata.character, so we need to pass it
        asset_manager.register("test_project", "character_ref", "李慕白", f, "s3_refs", metadata={"character": "李慕白"})

        active = asset_manager.get_character_active("test_project", "李慕白")
        assert active is not None
        assert active["shot_id"] == "李慕白"

    def test_get_character_not_found(self, asset_manager, projects_root):
        active = asset_manager.get_character_active("test_project", "不存在角色")
        assert active is None


class TestInvalidateShot:
    def test_invalidate_all_types(self, asset_manager, projects_root):
        pd = _setup_project(projects_root)
        f1 = _make_file(pd / "s5_frames", "s01_first_v1.png")
        f2 = _make_file(pd / "s5_frames", "s01_last_v1.png")
        asset_manager.register("test_project", "first_frame", "s01", f1, "s5_frames")
        asset_manager.register("test_project", "last_frame", "s01", f2, "s5_frames")

        asset_manager.invalidate_shot("test_project", "s01")

        active = asset_manager.get_active_for_shot("test_project", "s01")
        assert len(active) == 0


class TestListProject:
    def test_list_empty(self, asset_manager, projects_root):
        report = asset_manager.list_project("test_project")
        assert isinstance(report, dict)
        assert "total_versions" in report
        assert "by_type" in report

    def test_list_with_assets(self, asset_manager, projects_root):
        pd = _setup_project(projects_root)
        f = _make_file(pd / "s3_refs", "s01_ref_v1.png")
        asset_manager.register("test_project", "character_ref", "s01", f, "s3_refs")

        report = asset_manager.list_project("test_project")
        assert report["by_type"]["character_ref"] == 1


class TestExportReport:
    def test_export_report(self, asset_manager, projects_root):
        pd = _setup_project(projects_root)
        f = _make_file(pd / "s3_refs", "s01_ref_v1.png")
        asset_manager.register("test_project", "character_ref", "s01", f, "s3_refs")

        report = asset_manager.export_report("test_project")
        assert isinstance(report, str)
        assert "character_ref" in report
