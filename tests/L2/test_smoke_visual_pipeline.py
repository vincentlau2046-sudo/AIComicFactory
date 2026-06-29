"""
L2: 全链路冒烟测试 — 视觉管线 (S3→S6)

前置条件:
  - ComfyUI 运行中 (http://127.0.0.1:8188)
  - last_bento 项目有 s1_parsed.json + s2_characters.json + s4_shots.json
  - GPU 可用

运行: AICF_RUN_VISUAL_TESTS=1 pytest tests/L2/test_smoke_visual_pipeline.py -v --tb=short
"""

import json
import os
import sys
import shutil
import time
import urllib.request
import pytest
from pathlib import Path

# Project root
ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

PROJECT = "last_bento"
PROJECT_DIR = ROOT / "projects" / PROJECT

pytestmark = pytest.mark.skipif(
    not os.environ.get("AICF_RUN_VISUAL_TESTS"),
    reason="Set AICF_RUN_VISUAL_TESTS=1 to run visual pipeline tests"
)


def comfyui_is_up():
    """Check ComfyUI is reachable."""
    try:
        with urllib.request.urlopen("http://127.0.0.1:8188/system_stats", timeout=5) as r:
            return r.status == 200
    except Exception:
        return False


@pytest.fixture(autouse=True)
def check_comfyui():
    if not comfyui_is_up():
        pytest.skip("ComfyUI not running on :8188")


@pytest.fixture
def project_data():
    """Load last_bento project data."""
    chars = json.loads((PROJECT_DIR / "s2_characters.json").read_text())
    shots = json.loads((PROJECT_DIR / "s4_shots.json").read_text())
    return {"characters": chars, "shots": shots}


# ═══════════════════════════════════════════════════════════════════
# S3: Character Reference Image
# ═══════════════════════════════════════════════════════════════════

class TestS3CharacterImage:
    """S3: 角色参考图生成 — 只测第 1 个角色"""

    def test_s3_single_character(self, project_data, tmp_path):
        from scripts.s3_character_image import build_char_prompt, build_workflow
        from core.comfyui_session import ComfyUISession

        characters = project_data["characters"]["characters"]
        if not characters:
            pytest.skip("No characters in project data")

        char = characters[0]
        prompt = build_char_prompt(char)
        assert len(prompt) > 20, f"Prompt too short: {prompt}"

        workflow = build_workflow("animagine-xl-3.1.safetensors", prompt, 1024, 1024)
        assert "9" in workflow, "Workflow missing output node"

        session = ComfyUISession()
        prefix = f"aicf_test_s3_{char['name']}"
        workflow["9"]["inputs"]["filename_prefix"] = prefix

        result = session.run(workflow, timeout=300)
        assert result is not None, "ComfyUI returned None"

        output_dir = Path.home() / "ComfyUI" / "output"
        files = sorted(output_dir.glob(f"{prefix}_*.png"),
                       key=lambda p: p.stat().st_mtime, reverse=True)
        assert len(files) > 0, f"No output file with prefix {prefix}"
        assert files[0].stat().st_size > 10000, "Output image too small (<10KB)"


# ═══════════════════════════════════════════════════════════════════
# S5: Frame Generation
# ═══════════════════════════════════════════════════════════════════

class TestS5FrameGenerate:
    """S5: 关键帧生成 — prompt 构建 + workflow 结构验证"""

    def test_s5_prompt_and_workflow(self, project_data, tmp_path):
        """Verify prompt builds correctly and workflow structure is valid."""
        from scripts.s5_frame_generate import build_frame_prompt, build_qwen_edit_workflow

        characters = project_data["characters"]["characters"]
        scenes = project_data["shots"]["scenes"]
        if not scenes or not scenes[0].get("shots"):
            pytest.skip("No shots in project data")

        shot = scenes[0]["shots"][0]
        prompt = build_frame_prompt(shot, characters, frame_type="first")
        assert len(prompt) > 20, f"Prompt too short: {prompt}"

        # Verify workflow structure
        ref_dir = PROJECT_DIR / "s3_character_refs"
        ref_files = list(ref_dir.glob("*.png"))
        if not ref_files:
            pytest.skip("No character reference images available")

        workflow = build_qwen_edit_workflow(str(ref_files[0]), prompt, width=896, height=512)
        assert workflow is not None
        assert "65" in workflow  # KSampler
        assert "41" in workflow  # LoadImage
        assert "9" in workflow  # SaveImage
        assert "61" in workflow  # CLIPLoader
        assert "12" in workflow  # UNETLoader

    def test_s5_image_generation(self, project_data, tmp_path):
        """Full image generation - currently fails due to Qwen checkpoint CLIP issue."""
        from scripts.s5_frame_generate import build_frame_prompt, build_qwen_edit_workflow
        from core.comfyui_session import ComfyUISession

        characters = project_data["characters"]["characters"]
        scenes = project_data["shots"]["scenes"]
        if not scenes or not scenes[0].get("shots"):
            pytest.skip("No shots in project data")

        shot = scenes[0]["shots"][0]
        prompt = build_frame_prompt(shot, characters, frame_type="first")

        ref_dir = PROJECT_DIR / "s3_character_refs"
        ref_files = list(ref_dir.glob("*.png"))
        if not ref_files:
            pytest.skip("No character reference images available")

        session = ComfyUISession()
        uploaded = session.upload(ref_files[0])
        workflow = build_qwen_edit_workflow(str(uploaded), prompt, width=896, height=512)

        prefix = f"aicf_test_s5_shot{shot.get('shotNumber', 1)}"
        for node_id, node in workflow.items():
            if "inputs" in node and "filename_prefix" in node.get("inputs", {}):
                node["inputs"]["filename_prefix"] = prefix

        result = session.run(workflow, timeout=300)
        assert result is not None


# ═══════════════════════════════════════════════════════════════════
# S6: FLF2V Video Rendering
# ═══════════════════════════════════════════════════════════════════

class TestS6FLF2V:
    """S6: FLF2V 视频渲染 — 用已有首尾帧渲染 1 个 clip"""

    def test_s6_single_clip(self, project_data, tmp_path):
        """Use existing first/last frames from last_bento to render a clip."""
        from scripts.s6_flf2v_render import build_flf2v_workflow
        from core.comfyui_session import ComfyUISession

        frames_dir = PROJECT_DIR / "s5_frames"
        frame_files = sorted(frames_dir.glob("s*_first.png"))
        last_files = sorted(frames_dir.glob("s*_last.png"))

        if not frame_files or not last_files:
            pytest.skip("No frame images available (run S5 first)")

        first_frame = frame_files[0]
        last_frame = last_files[0]

        # Find matching last frame for same shot
        shot_id = first_frame.name.split("_")[0]  # e.g., 's01'
        matching_last = [f for f in last_files if f.name.startswith(f"{shot_id}_last")]
        if matching_last:
            last_frame = matching_last[0]

        session = ComfyUISession()
        # Upload both frames to ComfyUI input dir
        uploaded_first = session.upload(first_frame)
        uploaded_last = session.upload(last_frame)

        workflow = build_flf2v_workflow(
            start_image=str(uploaded_first),
            end_image=str(uploaded_last),
            motion_prompt="cinematic, high quality, smooth motion",
            duration_frames=25,
        )
        assert workflow is not None

        prefix = f"aicf_test_s6_shot{shot_id}"
        for node_id, node in workflow.items():
            if "inputs" in node and "filename_prefix" in node.get("inputs", {}):
                node["inputs"]["filename_prefix"] = prefix

        result = session.run(workflow, timeout=600)
        assert result is not None

        output_dir = Path.home() / "ComfyUI" / "output"
        video_files = sorted(
            list(output_dir.glob(f"{prefix}_*.mp4")) + list(output_dir.glob(f"{prefix}_*.webm")),
            key=lambda p: p.stat().st_mtime, reverse=True
        )
        assert len(video_files) > 0, f"No video output with prefix {prefix}"
