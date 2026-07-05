"""
prompts/registry.py — AIComicFactory Prompt Registry (插槽化模板引擎)

从 AIComicBuilder (AICB) 原样移植，不做精简。
主模型: baidu-codingplan (GPT-4 级)，纯 prompt 约束输出 JSON。
备选: 本地 Qwen3.6-27B + guided_json。

架构:
  PromptDefinition
    ├── key:        "shot_split"
    ├── category:   "script|character|shot|frame|video"
    ├── slots:      PromptSlot[]  (key, defaultContent, editable)
    └── build:      slotContents → 完整 system prompt

解析链:
  overrides/ YAML → registry default → hardcoded fallback
"""

from prompts._base import PromptDefinition, PromptSlot, slot, resolve
from typing import Dict, List, Optional, Any


# ═══════════════════════════════════════════════════════════════════
# Registry
# ═══════════════════════════════════════════════════════════════════

# Phase 1: 3个 P1 Prompt (class-based)
REGISTRY: Dict[str, PromptDefinition] = {}

def register(p: PromptDefinition):
    REGISTRY[p.key] = p

from prompts.defaults.script_parse import ScriptParsePrompt
from prompts.defaults.character_extract import CharacterExtractPrompt
from prompts.defaults.shot_split import ShotSplitPrompt

register(ScriptParsePrompt())
register(CharacterExtractPrompt())
register(ShotSplitPrompt())

# Phase 4: 9个 P2 Prompt (module-based, auto-registered)
def _register_module_prompt(module):
    """Register a module-style prompt (PROMPT_KEY + SLOTS + build_full_prompt)."""
    key = module.PROMPT_KEY
    category = module.CATEGORY
    slots_list = [
        PromptSlot(key=s["key"], default_content=s["defaultContent"], editable=s.get("editable", True))
        for s in module.SLOTS.values()
    ]
    # Create a PromptDefinition that delegates to build_full_prompt
    class ModulePrompt(PromptDefinition):
        def __init__(self):
            super().__init__(key=key, category=category, description=f"{key} prompt")
            self.slots = slots_list
        def build(self, overrides=None, params=None):
            return module.build_full_prompt(slot_contents=overrides, **(params or {}))
    register(ModulePrompt())

# Import and register module-based prompts
from prompts.defaults import (
    frame_generate_first,
    frame_generate_last,
    character_image,
    video_generate,
    script_generate,
    script_split,
    import_character_extract,
    scene_frame_generate,
    ref_video_generate,
)

for mod in [
    frame_generate_first, frame_generate_last, character_image,
    video_generate, script_generate, script_split,
    import_character_extract, scene_frame_generate, ref_video_generate,
]:
    _register_module_prompt(mod)


def get_prompt(key: str) -> Optional[PromptDefinition]:
    """获取已注册的 prompt 定义"""
    return REGISTRY.get(key)


def list_prompts() -> List[str]:
    """列出所有已注册的 prompt key"""
    return list(REGISTRY.keys())


def build_prompt(key: str, overrides: Optional[Dict[str, str]] = None, params: Optional[Dict[str, Any]] = None) -> str:
    """快捷方法: 获取 prompt 并构建"""
    p = get_prompt(key)
    if not p:
        raise ValueError(f"Prompt '{key}' not found in registry. Available: {list_prompts()}")
    return p.build(overrides, params)