"""
core/prompt_runner.py — Prompt 执行器

构建 prompt 并准备 LLM 调用参数。
LLM 调用由 OpenClaw 完成（通过 baidu-codingplan），
本模块仅负责组装 prompt 内容。
"""

import json
from pathlib import Path
from typing import Dict, Optional, Any, Tuple

from prompts.registry import get_prompt, REGISTRY
from prompts.defaults.script_parse import build_script_parse
from prompts.defaults.character_extract import build_character_extract
from prompts.defaults.shot_split import build_shot_split


def _load_json(path: Path) -> dict:
    """Load JSON file, return empty dict if not found."""
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


def run_script_parse(project_dir: Path, source_text: str, overrides: Optional[Dict[str, str]] = None) -> dict:
    """Stage 1: 构建 script_parse 的 system + user prompt。
    返回适合直接送给 LLM 的 messages 格式。
    """
    prompts = build_script_parse(source_text, overrides)
    return {
        "stage": "s1_parse",
        "model": "DEEPSEEK_PRO",
        "messages": [
            {"role": "system", "content": prompts["system"]},
            {"role": "user", "content": prompts["user"]},
        ],
    }


def run_character_extract(project_dir: Path, parsed_script: Optional[dict] = None, 
                           overrides: Optional[Dict[str, str]] = None) -> dict:
    """Stage 2: 构建 character_extract 的 system + user prompt。
    
    Args:
        project_dir: 项目目录
        parsed_script: 已解析的剧本 JSON（若不传则从 s1_parsed.json 读）
        overrides: 用户覆盖的 prompt slot
    """
    if parsed_script is None:
        parsed_script = _load_json(project_dir / "s1_parsed.json")
    
    # Convert script to text form for the prompt
    script_text = _script_to_text(parsed_script)
    
    prompts = build_character_extract(script_text, overrides)
    return {
        "stage": "s2_character_extract",
        "model": "DEEPSEEK_PRO",
        "messages": [
            {"role": "system", "content": prompts["system"]},
            {"role": "user", "content": prompts["user"]},
        ],
    }


def run_shot_split(project_dir: Path, parsed_script: Optional[dict] = None,
                   characters: Optional[list] = None,
                   overrides: Optional[Dict[str, str]] = None,
                   max_duration: float = 8.0) -> dict:
    """Stage 4: 构建 shot_split 的 system + user prompt。
    
    Args:
        project_dir: 项目目录
        parsed_script: 已解析的剧本 JSON
        characters: 角色列表
        overrides: 用户覆盖的 prompt slot
        max_duration: 每个 shot 最长秒数
    """
    if parsed_script is None:
        parsed_script = _load_json(project_dir / "s1_parsed.json")
    if characters is None:
        chars_data = _load_json(project_dir / "s2_characters.json")
        characters = chars_data.get("characters", [])
    
    prompts = build_shot_split(parsed_script, characters, overrides, max_duration)
    return {
        "stage": "s4_shot_split",
        "model": "DEEPSEEK_PRO",
        "messages": [
            {"role": "system", "content": prompts["system"]},
            {"role": "user", "content": prompts["user"]},
        ],
    }


def _script_to_text(script: dict) -> str:
    """Convert parsed JSON script back to text form for character_extract."""
    lines = [f"# {script.get('title', '未命名')}"]
    if script.get("synopsis"):
        lines.append(f"\n{script['synopsis']}")
    
    for scene in script.get("scenes", []):
        lines.append(f"\n## 场景 {scene.get('sceneNumber', '?')}: {scene.get('setting', '')}")
        if scene.get("mood"):
            lines.append(f"情绪: {scene['mood']}")
        if scene.get("description"):
            lines.append(scene["description"])
        for d in scene.get("dialogues", []):
            lines.append(f"{d['character']}: \"{d['text']}\"")
    
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════
# Stage runner — convenience functions for OpenClaw skill
# ═══════════════════════════════════════════════════════════════════

def save_stage_output(project_dir: Path, stage: str, result: dict):
    """Save LLM output to the appropriate file."""
    project_dir.mkdir(parents=True, exist_ok=True)
    
    file_map = {
        "s1_parse": "s1_parsed.json",
        "s2_character_extract": "s2_characters.json",
        "s4_shot_split": "s4_shots.json",
    }
    
    filename = file_map.get(stage, f"{stage}_output.json")
    path = project_dir / filename
    
    with open(path, "w") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    return path