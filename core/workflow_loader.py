"""
core/workflow_loader.py — ComfyUI Workflow 模板加载 + 参数注入

所有脚本通过此模块加载 templates/ 下的 JSON 模板，
而非在 Python 中硬编码 workflow dict。
"""

import json
from pathlib import Path
from typing import Any, Dict, Optional


TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


def load_workflow(name: str, templates_dir: Path = None) -> Dict[str, Any]:
    """
    加载 ComfyUI workflow 模板 JSON.
    
    自动过滤以 '_' 开头的元数据键 (如 _comment, _requirements),
    这些键不是有效的 ComfyUI 节点。
    
    Args:
        name: 模板文件名 (不含路径), 如 "t2i_character_ref.json"
        templates_dir: 自定义模板目录 (默认: ~/AIComicFactory/templates/)
    
    Returns:
        解析后的 workflow dict
    
    Raises:
        FileNotFoundError: 模板文件不存在
    """
    tdir = templates_dir or TEMPLATES_DIR
    path = tdir / name
    
    if not path.exists():
        raise FileNotFoundError(f"Workflow template not found: {path}")
    
    with open(path) as f:
        data = json.load(f)
    
    # Filter metadata keys (starting with '_')
    return {k: v for k, v in data.items() if not k.startswith('_')}


def inject_param(workflow: Dict[str, Any], node_id: str, 
                  input_key: str, value: Any) -> Dict[str, Any]:
    """
    向 workflow 的指定节点注入参数.
    
    Args:
        workflow: workflow dict (会被原地修改)
        node_id: 节点 ID (如 "6", "9")
        input_key: 输入参数名 (如 "text", "filename_prefix")
        value: 参数值
    
    Returns:
        修改后的 workflow dict
    """
    if node_id in workflow:
        if "inputs" not in workflow[node_id]:
            workflow[node_id]["inputs"] = {}
        workflow[node_id]["inputs"][input_key] = value
    return workflow


def inject_params(workflow: Dict[str, Any], injections: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """
    批量注入参数.
    
    Args:
        workflow: workflow dict
        injections: {node_id: {input_key: value, ...}, ...}
    
    Returns:
        修改后的 workflow dict
    """
    for node_id, params in injections.items():
        for key, value in params.items():
            inject_param(workflow, node_id, key, value)
    return workflow


def list_templates(templates_dir: Path = None) -> list:
    """列出所有可用模板."""
    tdir = templates_dir or TEMPLATES_DIR
    if not tdir.exists():
        return []
    return sorted(p.name for p in tdir.glob("*.json"))
