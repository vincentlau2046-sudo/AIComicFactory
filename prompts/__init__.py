"""
prompts/__init__.py — Prompt Registry

AIComicFactory Prompt 注册表。从 AIComicBuilder 原样移植。
"""

from prompts._base import PromptDefinition, PromptSlot, slot, resolve
from prompts.registry import REGISTRY, get_prompt, list_prompts, build_prompt, register

__all__ = [
    "PromptDefinition",
    "PromptSlot",
    "slot",
    "resolve",
    "REGISTRY",
    "get_prompt",
    "list_prompts",
    "build_prompt",
    "register",
]