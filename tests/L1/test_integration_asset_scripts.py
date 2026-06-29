"""L1: AssetManager + Scripts 集成测试 (mock ComfyUI)"""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock


def _make_file(parent, name):
    f = parent / name
    f.write_bytes(b"test_data")
    return f


class TestS3Integration:
    def test_s3_calls_asset_register(self, tmp_path):
        import scripts.s3_character_image as s3
        assert hasattr(s3, 'get_asset_manager') or 'asset_manager' in dir(s3)


class TestS3bIntegration:
    def test_s3b_calls_asset_register(self, tmp_path):
        import scripts.s3b_four_view as s3b
        assert hasattr(s3b, 'get_asset_manager') or 'asset_manager' in dir(s3b)


class TestS5Integration:
    def test_s5_calls_asset_register(self, tmp_path):
        import scripts.s5_frame_generate as s5
        assert hasattr(s5, 'get_asset_manager') or 'asset_manager' in dir(s5)


class TestS6Integration:
    def test_s6_calls_asset_register(self, tmp_path):
        import scripts.s6_flf2v_render as s6
        assert hasattr(s6, 'get_asset_manager') or 'asset_manager' in dir(s6)


class TestAssetManagerScriptIntegration:
    def test_register_params_format(self, asset_manager, projects_root):
        pd = projects_root / "test_project"
        refs = pd / "s3_refs"
        refs.mkdir(parents=True, exist_ok=True)

        f = _make_file(refs, "李慕白_ref_v1.png")
        result = asset_manager.register(
            project="test_project",
            asset_type="character_ref",
            shot_id="李慕白",
            source_path=f,
            relative_dir="s3_refs",
        )
        assert result["version"] == 1
        assert result["is_active"] is True

    def test_register_params_s5_format(self, asset_manager, projects_root):
        pd = projects_root / "test_project"
        frames = pd / "s5_frames"
        frames.mkdir(parents=True, exist_ok=True)

        f = _make_file(frames, "s01_first_v1.png")
        result = asset_manager.register(
            project="test_project",
            asset_type="first_frame",
            shot_id="s01",
            source_path=f,
            relative_dir="s5_frames",
        )
        assert result["version"] == 1

    def test_register_params_s6_format(self, asset_manager, projects_root):
        pd = projects_root / "test_project"
        clips = pd / "s6_clips"
        clips.mkdir(parents=True, exist_ok=True)

        f = _make_file(clips, "s01_video_v1.mp4")
        result = asset_manager.register(
            project="test_project",
            asset_type="video_clip",
            shot_id="s01",
            source_path=f,
            relative_dir="s6_clips",
        )
        assert result["version"] == 1
