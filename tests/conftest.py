# AIComicFactory Test Configuration

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ═══════════════════════════════════════════════════════════════
# Fixtures: Project directories
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def tmp_project(tmp_path):
    """Create a minimal project directory structure."""
    pd = tmp_path / "test_project"
    pd.mkdir()
    # Create expected subdirs
    (pd / "s1_parsed").mkdir()
    (pd / "s2_characters").mkdir()
    (pd / "s3_refs").mkdir()
    (pd / "s3b_four_view").mkdir()
    (pd / "s5_frames").mkdir()
    (pd / "s6_clips").mkdir()
    (pd / "s7_assembled").mkdir()
    return pd


@pytest.fixture(scope="session")
def test_pipeline_yaml(tmp_path_factory):
    """Create a minimal pipeline.yaml for testing (12 stages)."""
    base = tmp_path_factory.mktemp("aicf_test_base")
    yaml_path = base / "pipeline.yaml"
    yaml_path.write_text("""stages:
  s1_script_parse:
    id: s1_parse
    order: 1
    requires: [source.txt]
    produces: [s1_parsed.json]
    depends_on: []
    gpu: none
    runner: llm
    description: "剧本解析"

  s2_character_extract:
    id: s2_character_extract
    order: 2
    requires: [s1_parsed.json]
    produces: [s2_characters.json]
    depends_on: [s1_parse]
    gpu: none
    runner: llm
    description: "角色提取"

  s2b_wardrobe_extract:
    id: s2b_wardrobe_extract
    order: 3
    requires: [s2_characters.json]
    produces: [s2_characters.json]
    depends_on: [s2_character_extract]
    gpu: none
    runner: script
    description: "服饰提取"

  s4_shot_split:
    id: s4_shot_split
    order: 4
    requires: [s1_parsed.json, s2_characters.json]
    produces: [s4_shots.json]
    depends_on: [s1_parse, s2_character_extract]
    gpu: none
    runner: llm
    description: "分镜拆解"

  s4b_keyframe_assets:
    id: s4b_keyframe_assets
    order: 5
    requires: [s4_shots.json, s2_characters.json]
    produces: [s4b_keyframe_assets.json]
    depends_on: [s4_shot_split, s2_character_extract]
    gpu: none
    runner: script
    description: "关键帧资产"

  s3_character_image:
    id: s3_character_image
    order: 6
    requires: [s2_characters.json]
    produces: [s3_character_refs/manifest.json]
    depends_on: [s2_character_extract]
    gpu: comfyui
    runner: script
    description: "角色参考图"

  s3b_four_view:
    id: s3b_four_view
    order: 7
    requires: [s3_character_refs/manifest.json]
    produces: [s3b_four_views/manifest.json]
    depends_on: [s3_character_image]
    gpu: comfyui
    runner: script
    description: "四视图扩展"

  s5_frame_generate:
    id: s5_frame_generate
    order: 8
    requires: [s4b_keyframe_assets.json, s3_character_refs/, s3b_four_views/]
    produces: [s5_frames/*.png]
    depends_on: [s3_character_image, s3b_four_view, s4_shot_split, s4b_keyframe_assets]
    gpu: comfyui
    runner: script
    description: "关键帧生成"

  s6_flf2v_render:
    id: s6_video_generate
    order: 9
    requires: [s5_frames/, s4b_keyframe_assets.json]
    produces: [s6_videos/*.mp4]
    depends_on: [s5_frame_generate]
    gpu: comfyui
    runner: script
    description: "视频渲染"

  s7_video_assemble:
    id: s7_assemble
    order: 10
    requires: [s6_videos/]
    produces: [s7_assembled.mp4]
    depends_on: [s6_video_generate]
    gpu: none
    runner: script
    description: "视频合成"

  s8_subtitles:
    id: s8_subtitles
    order: 11
    requires: [s7_assembled.mp4, s4_shots.json]
    produces: [s8_subtitles.ass]
    depends_on: [s7_assemble, s4_shot_split]
    gpu: none
    runner: script
    description: "字幕生成"

  s9_tts_audio:
    id: s9_tts_audio
    order: 12
    requires: [s7_assembled.mp4, s4_shots.json]
    produces: [s9_final.mp4]
    depends_on: [s7_assemble, s4_shot_split]
    gpu: comfyui
    runner: script
    description: "TTS语音"
""")
    return str(base)


@pytest.fixture
def projects_root(tmp_path, test_pipeline_yaml):
    """Create a projects root with test_project inside + symlinked pipeline.yaml."""
    # Use the session-scoped pipeline.yaml
    pipeline_src = Path(test_pipeline_yaml) / "pipeline.yaml"
    root = tmp_path / "projects"
    root.mkdir()
    pd = root / "test_project"
    pd.mkdir()
    (pd / "s5_frames").mkdir()
    (pd / "s6_clips").mkdir()
    # Symlink or copy pipeline.yaml for StateManager to find
    import shutil
    shutil.copy2(str(pipeline_src), str(tmp_path / "pipeline.yaml"))
    return root


@pytest.fixture
def state_manager(projects_root):
    """StateManager bound to tmp projects_root."""
    from core.state_manager import StateManager
    # Explicitly point to the test pipeline.yaml
    pipeline_path = Path(projects_root).parent / "pipeline.yaml"
    return StateManager(projects_root=str(projects_root),
                        pipeline_path=str(pipeline_path))


@pytest.fixture
def asset_manager(projects_root):
    """AssetManager bound to tmp projects_root."""
    from core.asset_manager import AssetManager
    return AssetManager(projects_root=str(projects_root))


@pytest.fixture
def initialized_project(state_manager):
    """A project with initialized state."""
    state_manager.init_project("test_project")
    return "test_project"


# ═══════════════════════════════════════════════════════════════
# Fixtures: Test data
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def sample_story():
    """A short test story for pipeline testing."""
    return """少年李慕白站在悬崖边，望着云海翻涌。身后传来脚步声。
"师父，他们来了。"林雪的声音微微颤抖。
李慕白转过身，白衣在风中猎猎作响。他将手中的剑缓缓拔出，剑身映出初升的朝阳。
"既然来了，便战吧。"他说。
远处的山道上，黑衣人影影绰绰，至少百人。"""


@pytest.fixture
def sample_s1_output():
    """Pre-generated S1 (script_parse) output."""
    return {
        "title": "崖上之战",
        "synopsis": "李慕白在悬崖边面对百名黑衣人的围攻",
        "scenes": [
            {
                "sceneNumber": 1,
                "setting": "悬崖边——清晨",
                "description": "少年李慕白站在悬崖边，望着云海翻涌。",
                "mood": "壮阔而紧张",
                "dialogues": []
            },
            {
                "sceneNumber": 2,
                "setting": "悬崖边——清晨",
                "description": "林雪走来通报，李慕白拔剑迎敌。",
                "mood": "决然",
                "dialogues": [
                    {"character": "林雪", "text": "师父，他们来了。", "emotion": "声音微微颤抖"},
                    {"character": "李慕白", "text": "既然来了，便战吧。", "emotion": "平静而坚定"}
                ]
            }
        ]
    }


@pytest.fixture
def sample_s4_output():
    """Pre-generated S4 (shot_split) output."""
    return {
        "scenes": [
            {
                "sceneNumber": 1,
                "shots": [
                    {
                        "shotNumber": 1,
                        "sceneNumber": 1,
                        "startFrame": "少年白衣剑客立于悬崖，云海翻涌",
                        "endFrame": "剑客转身面向来路，白衣猎猎",
                        "transitionOut": "dissolve",
                        "videoScript": "悬崖边白衣剑客伫立，风吹衣袂"
                    },
                    {
                        "shotNumber": 2,
                        "sceneNumber": 1,
                        "startFrame": "少女从后方走近，神情紧张",
                        "endFrame": "剑客拔剑出鞘，朝阳映剑身",
                        "transitionOut": "cut",
                        "videoScript": "少女走来，剑客拔剑"
                    }
                ]
            }
        ]
    }


# ═══════════════════════════════════════════════════════════════
# Fixtures: Mock responses
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def mock_vision_good_response():
    """A well-formed vision API response."""
    return json.dumps({
        "overall_score": 85,
        "character_appearance": 9,
        "scene_environment": 8,
        "lighting_color": 9,
        "composition": 8,
        "issues": [],
        "severity": "none",
        "suggestion": ""
    })


@pytest.fixture
def mock_vision_moderate_response():
    """A moderate-score vision API response with issues."""
    return json.dumps({
        "overall_score": 55,
        "character_appearance": 5,
        "scene_environment": 6,
        "lighting_color": 5,
        "composition": 6,
        "issues": ["角色服装颜色不一致", "光影方向变化"],
        "severity": "moderate",
        "suggestion": "重新生成帧以匹配参考图服装"
    })


@pytest.fixture
def mock_vision_codeblock_response():
    """Vision response with JSON inside code block."""
    return '这是分析结果：\n```json\n{"overall_score": 90, "character_appearance": 9, "scene_environment": 9, "lighting_color": 9, "composition": 9, "issues": [], "severity": "none", "suggestion": ""}\n```'


@pytest.fixture
def mock_vision_malformed_response():
    """Malformed vision API response."""
    return "I think the frames look mostly the same but the lighting changed a bit."
