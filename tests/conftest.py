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


@pytest.fixture
def projects_root(tmp_path):
    """Create a projects root with test_project inside."""
    root = tmp_path / "projects"
    root.mkdir()
    pd = root / "test_project"
    pd.mkdir()
    (pd / "s5_frames").mkdir()
    (pd / "s6_clips").mkdir()
    return root


@pytest.fixture
def state_manager(projects_root):
    """StateManager bound to tmp projects_root."""
    from core.state_manager import StateManager
    return StateManager(projects_root=str(projects_root))


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
