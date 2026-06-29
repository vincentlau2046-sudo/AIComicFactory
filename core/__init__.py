"""
core/__init__.py — AIComicFactory Core Module
"""

from core.state_manager import StateManager, get_state_manager, STAGE_ORDER, STAGE_LABELS

__all__ = [
    "StateManager",
    "get_state_manager",
    "STAGE_ORDER",
    "STAGE_LABELS",
]