"""
core/state_manager.py — 管线状态管理器

管理 projects/{project}/state.json 的读写。
支持断点续跑、脏标记、进度跟踪。
"""

import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Optional, List

TZ = timezone(timedelta(hours=8))  # Asia/Shanghai

STAGE_ORDER = [
    "s1_parse",
    "s2_character_extract",
    "s3_character_image",
    "s3b_four_view",
    "s4_shot_split",
    "s4b_keyframe_assets",
    "s5_frame_generate",
    "s6_video_generate",
    "s7_assemble",
    "s8_subtitles",
    "s9_tts_audio",
]

STAGE_LABELS = {
    "s1_parse": "剧本解析",
    "s2_character_extract": "角色提取",
    "s3_character_image": "角色参考图",
    "s3b_four_view": "四视图扩展",
    "s4_shot_split": "分镜拆解",
    "s4b_keyframe_assets": "关键帧资产",
    "s5_frame_generate": "关键帧生成",
    "s6_video_generate": "视频生成",
    "s7_assemble": "视频合成",
    "s8_subtitles": "字幕生成",
    "s9_tts_audio": "TTS语音+ASR对齐",
}

STAGE_DEPS = {
    "s1_parse": [],
    "s2_character_extract": ["s1_parse"],
    "s3_character_image": ["s2_character_extract"],
    "s3b_four_view": ["s3_character_image"],
    "s4_shot_split": ["s1_parse", "s2_character_extract"],
    "s4b_keyframe_assets": ["s4_shot_split", "s2_character_extract"],
    "s5_frame_generate": ["s3_character_image", "s4_shot_split", "s4b_keyframe_assets"],
    "s6_video_generate": ["s5_frame_generate"],
    "s7_assemble": ["s6_video_generate"],
    "s8_subtitles": ["s7_assemble"],
    "s9_tts_audio": ["s4_shot_split"],
}


class StateManager:
    """Manage pipeline state for a project."""
    
    def __init__(self, projects_root: str = None):
        self.root = Path(projects_root or os.environ.get("AICF_PROJECTS_ROOT", str(Path.home() / "AIComicFactory" / "projects")))
    
    def _state_path(self, project: str) -> Path:
        return self.root / project / "state.json"
    
    def init_project(self, project: str) -> dict:
        """Initialize a new project state."""
        proj_dir = self.root / project
        proj_dir.mkdir(parents=True, exist_ok=True)
        
        now = datetime.now(TZ).isoformat()
        state = {
            "project": project,
            "created": now,
            "updated": now,
            "stages": {s: {"status": "pending"} for s in STAGE_ORDER},
            "errors": [],
        }
        self._write(project, state)
        return state
    
    def get(self, project: str) -> dict:
        """Read project state. Auto-initializes if not exists."""
        path = self._state_path(project)
        if not path.exists():
            return self.init_project(project)
        with open(path, "r") as f:
            return json.load(f)
    
    def _write(self, project: str, state: dict):
        state["updated"] = datetime.now(TZ).isoformat()
        path = self._state_path(project)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    
    def update_stage(self, project: str, stage: str, status: str, **kwargs):
        """Update a single stage's status."""
        if stage not in STAGE_ORDER:
            raise ValueError(f"Unknown stage: {stage}. Valid: {STAGE_ORDER}")
        
        state = self.get(project)
        entry = {"status": status, "ts": datetime.now(TZ).isoformat()}
        entry.update(kwargs)
        state["stages"][stage] = entry
        self._write(project, state)
        return state
    
    def mark_completed(self, project: str, stage: str, **kwargs):
        """Mark a stage as completed."""
        return self.update_stage(project, stage, "completed", **kwargs)
    
    def mark_running(self, project: str, stage: str, **kwargs):
        """Mark a stage as running."""
        return self.update_stage(project, stage, "running", **kwargs)
    
    def mark_failed(self, project: str, stage: str, error: str):
        """Mark a stage as failed and record error."""
        state = self.update_stage(project, stage, "failed", error=error)
        state["errors"].append({
            "stage": stage,
            "error": error,
            "ts": datetime.now(TZ).isoformat(),
        })
        self._write(project, state)
        return state

    def add_error(self, project: str, stage: str, error: str):
        """Record a non-fatal error (e.g. quality check warning) without changing stage status."""
        state = self.get(project)
        state["errors"].append({
            "stage": stage,
            "error": error,
            "ts": datetime.now(TZ).isoformat(),
            "severity": "warning",
        })
        self._write(project, state)
        return state
    
    def mark_stale(self, project: str, from_stage: str):
        """Mark a stage and all downstream as pending (dirty)."""
        state = self.get(project)
        start_idx = STAGE_ORDER.index(from_stage)
        for s in STAGE_ORDER[start_idx:]:
            state["stages"][s] = {"status": "pending"}
        self._write(project, state)
        return state
    
    def next_pending(self, project: str) -> Optional[str]:
        """Get the next pending stage, checking dependencies."""
        state = self.get(project)
        
        for stage in STAGE_ORDER:
            s = state["stages"].get(stage, {"status": "pending"})
            if s["status"] == "pending":
                # Check dependencies
                deps_met = all(
                    state["stages"].get(d, {}).get("status") == "completed"
                    for d in STAGE_DEPS.get(stage, [])
                )
                if deps_met:
                    return stage
            elif s["status"] == "failed":
                return stage  # Return failed stage for retry
        return None  # All done
    
    def progress(self, project: str) -> str:
        """Generate a human-readable progress report."""
        state = self.get(project)
        lines = [f"Project: {project}"]
        
        completed = 0
        for stage in STAGE_ORDER:
            s = state["stages"].get(stage, {"status": "pending"})
            label = STAGE_LABELS.get(stage, stage)
            icon = {
                "completed": "✅",
                "running": "🔄",
                "failed": "❌",
                "pending": "⬜",
            }.get(s["status"], "⬜")
            
            detail = ""
            if s.get("progress"):
                detail = f" ({s['progress']})"
            if s.get("error"):
                detail = f" — {s['error'][:60]}"
            
            lines.append(f"  {icon} {stage} {label}{detail}")
            if s["status"] == "completed":
                completed += 1
        
        lines.append(f"\nProgress: {completed}/{len(STAGE_ORDER)} stages complete")
        if state["errors"]:
            lines.append(f"Errors: {len(state['errors'])}")
        
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════════

_DEFAULT = None

def get_state_manager(projects_root: str = None) -> StateManager:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = StateManager(projects_root)
    return _DEFAULT