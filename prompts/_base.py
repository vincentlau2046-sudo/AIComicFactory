"""
prompts/_base.py — 基类和工具函数
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any


@dataclass
class PromptSlot:
    """单个可编辑插槽"""
    key: str
    default_content: str
    editable: bool = True


@dataclass
class PromptDefinition:
    """Prompt 定义基类"""
    key: str
    category: str
    description: str
    slots: List[PromptSlot] = field(default_factory=list)
    
    def build(self, overrides: Optional[Dict[str, str]] = None, params: Optional[Dict[str, Any]] = None) -> str:
        raise NotImplementedError("Subclass must implement build()")


def slot(k: str, content: str, editable: bool = True) -> PromptSlot:
    return PromptSlot(key=k, default_content=content, editable=editable)


def resolve(overrides: Dict[str, str], slots: List[PromptSlot], key: str) -> str:
    """解析 slot: overrides > default"""
    if key in overrides:
        return overrides[key]
    for s in slots:
        if s.key == key:
            return s.default_content
    return ""