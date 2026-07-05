"""
core/__init__.py — AIComicFactory Core Module
"""

from core.state_manager import (
    StateManager,
    get_state_manager,
    compute_params_hash,
    migrate_v1_to_v2,
    STAGE_ORDER,
    STAGE_LABELS,
    STAGE_DEPS,
)

__all__ = [
    "StateManager",
    "get_state_manager",
    "compute_params_hash",
    "migrate_v1_to_v2",
    "STAGE_ORDER",
    "STAGE_LABELS",
    "STAGE_DEPS",
]
