"""
core/state_manager.py — 管线状态管理器 (v2)

管理 projects/{project}/state.json 的读写。
支持断点续跑、Checkpoint、参数哈希、脏标记、v1→v2 迁移。

单一真相源: pipeline.yaml
 - 从 pipeline.yaml 动态加载 stage 列表 (id + 依赖 + 描述)
 - 不再硬编码 STAGE_ORDER / STAGE_LABELS / STAGE_DEPS
 - 通过 stage 定义中的 `id` 字段保持向后兼容
"""

import fcntl
import hashlib
import json
import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any

TZ = timezone(timedelta(hours=8))  # Asia/Shanghai

# ── 简单的 YAML 解析器 (独立依赖, 无需 pip install pyyaml) ──────────
# 只支持 pipeline.yaml 用到的子集: 无嵌套 dict/list, 纯 scalar

def _parse_yaml_simple(text: str) -> dict:
    """Parse a minimal YAML that pipeline.yaml uses (flat keys, list-of-scalars only).

    WARNING: This is a best-effort parser.  Complex YAML structures
    (nested dicts, multi-line strings, anchors, tags) will be lost.
    Install pyyaml for full support.
    """
    import re
    result = {}
    current_key = None
    current_list = []
    in_list = False
    list_key = None   # which stage key owns the current list
    stage_key = None  # current stage being processed

    for line in text.split("\n"):
        stripped = line.strip()
        # Skip blank / comment
        if not stripped or stripped.startswith("#"):
            continue
        # Detect section break `# ── ... ──` or `# ══`
        if stripped.startswith("#"):
            continue
        # Top-level "stages:" key — only match lines with no leading whitespace
        top_match = re.match(r"^(\w[\w-]*):\s*$", line)
        if top_match:
            if current_key and in_list:
                result[current_key] = current_list
                current_list = []
                in_list = False
            current_key = top_match.group(1)
            result[current_key] = {}  # Nested dict for stages
            continue
        # Indented block under "stages:"
        indent_match = re.match(r"^  (\w[\w-]*):\s*(.*)", line)
        if indent_match:
            if current_key == "stages":
                if in_list:
                    result["stages"].setdefault(list_key, {})
                    result["stages"][list_key][list_field] = current_list
                    current_list = []
                    in_list = False
                stage_key = indent_match.group(1)
                stage_val = indent_match.group(2).strip()
                result["stages"].setdefault(stage_key, {})
                if stage_val:
                    result["stages"][stage_key]["__name"] = stage_val.strip('"')
            # else: could be other top-level keys, ignore for now
            continue
        # Indented stage fields:  s1_script_parse:
        field_match = re.match(r"^    (\w[\w-]*):\s*(.*)", line)
        if field_match:
            if stage_key is None:
                # Field-level line before any stage definition — should not
                # happen in valid pipeline.yaml, but be defensive.
                continue
            fk = field_match.group(1)
            fv = field_match.group(2).strip().strip('"')
            if in_list and fk != "-":
                # List ended, store it under the owning stage
                result["stages"].setdefault(list_key, {})
                result["stages"][list_key][list_field] = current_list
                current_list = []
                in_list = False

            if fv == "":
                # Might be a list next
                list_field = fk
                list_key = stage_key  # track which stage owns this list
                current_list = []
                in_list = True
            elif fv.startswith("["):
                # Inline list: [a, b, c]
                items = [x.strip().strip("'\"") for x in fv.strip("[]").split(",") if x.strip()]
                result["stages"].setdefault(stage_key, {})
                result["stages"][stage_key][fk] = items
            else:
                result["stages"].setdefault(stage_key, {})
                result["stages"][stage_key][fk] = fv
            continue
        # List items:   - item
        if in_list and stripped.startswith("- "):
            current_list.append(stripped[2:].strip().strip("'\""))

    # Flush last inline list
    if in_list and current_key == "stages":
        result["stages"].setdefault(list_key, {})
        result["stages"][list_key][list_field] = current_list

    return result


def _load_yaml(path: Path) -> dict:
    """Load YAML safely — try pyyaml first, fall back to simple parser."""
    try:
        import yaml
        with open(path, "r") as f:
            return yaml.safe_load(f)
    except ImportError:
        import warnings
        warnings.warn(
            "pyyaml not available; using fallback YAML parser which may "
            "lose complex fields (nested dicts, arrays, multi-line strings). "
            "Install pyyaml for full pipeline.yaml support."
        )
        return _parse_yaml_simple(path.read_text())


# ═══════════════════════════════════════════════════════════════════
# 参数哈希
# ═══════════════════════════════════════════════════════════════════

def compute_params_hash(args: dict) -> str:
    """Compute SHA256 hash of a parameter dict for change detection.

    Args:
        args: Flat dict of parameter name → value.

    Returns:
        Short hex digest prefix like "sha256:a1b2c3d4".
    """
    # Sort keys for deterministic serialization
    serialized = json.dumps(args, sort_keys=True, ensure_ascii=False)
    h = hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:12]
    return f"sha256:{h}"


# ═══════════════════════════════════════════════════════════════════
# Schema 迁移
# ═══════════════════════════════════════════════════════════════════

def migrate_v1_to_v2(state: dict, target_stages: List[str]) -> dict:
    """Migrate a v1 state dict to v2 schema (in-place + return).

    v1 → v2 changes:
      - Add schema_version: 2
      - Fill in missing stages from the canonical stage list (pipeline.yaml)
      - Add checkpoint sub-object to each stage
      - Add params_hash / dirty / dirty_reason fields

    Args:
        state: Existing state dict (v1 or already v2).
        target_stages: Canonical list of stage IDs from pipeline.yaml.

    Returns:
        The same state dict, upgraded to v2 in place.
    """
    version = state.setdefault("schema_version", 1)
    if version >= 2:
        return state  # Already v2+

    # Move to v2
    state["schema_version"] = 2
    state.setdefault("checkpoint_history", [])
    state.setdefault("dirty_history", [])

    # Ensure all canonical stages exist
    stages = state.setdefault("stages", {})
    for sid in target_stages:
        entry = stages.setdefault(sid, {"status": "pending"})
        if isinstance(entry, str):
            # v0 format: "completed" → dict
            entry = stages[sid] = {"status": entry}
        entry.setdefault("status", "pending")
        # Add v2 fields if missing
        if "checkpoint" not in entry:
            entry["checkpoint"] = None
        if "params_hash" not in entry:
            entry["params_hash"] = None
        if "dirty" not in entry:
            entry["dirty"] = False
        if "dirty_reason" not in entry:
            entry["dirty_reason"] = None

    state["_migrated_from_v1"] = True
    return state


# ═══════════════════════════════════════════════════════════════════
# StateManager
# ═══════════════════════════════════════════════════════════════════

# Legacy constants kept for backward compatibility (deprecated, will warn)
_LEGACY_STAGE_ORDER = [
    "s1_parse", "s2_character_extract", "s3_character_image", "s3b_four_view",
    "s4_shot_split", "s4b_keyframe_assets", "s5_frame_generate",
    "s6_video_generate", "s7_assemble", "s8_subtitles", "s9_tts_audio",
]


class StateManager:
    """Manage pipeline state for a project.

    Single source of truth for the stage list is *pipeline.yaml*.
    Backward-compatible: all existing scripts using old short names still work.
    """

    def __init__(self, projects_root: str = None, pipeline_path: str = None):
        self.root = Path(projects_root or os.environ.get(
            "AICF_PROJECTS_ROOT",
            str(Path.home() / "AIComicFactory" / "projects")
        ))
        # Resolve pipeline.yaml
        if pipeline_path:
            self._pipeline_file = Path(pipeline_path)
        else:
            self._pipeline_file = self.root.parent / "pipeline.yaml"
            if not self._pipeline_file.exists():
                # Fallback: cwd / pipeline.yaml
                self._pipeline_file = Path.cwd() / "pipeline.yaml"

        # Caches (lazy-loaded)
        self._pipeline_config = None    # raw dict from YAML
        self._stage_order: List[str] = None   # sorted state IDs
        self._stage_defs: Dict[str, dict] = None  # state_id → def
        self._stage_deps: Dict[str, List[str]] = None  # state_id → [dep_ids]
        self._pipeline_key_map: Dict[str, str] = None  # state_id → pipeline_key
        self._reverse_key_map: Dict[str, str] = None   # pipeline_key → state_id

    # ── Pipeline config loading ──────────────────────────────────

    def _default_pipeline_path(self) -> Path:
        return self.root.parent / "pipeline.yaml"

    def load_pipeline_config(self) -> dict:
        """Load and parse pipeline.yaml; return the raw config dict.

        Caches the result so subsequent calls are O(1).
        """
        if self._pipeline_config is not None:
            return self._pipeline_config

        path = self._pipeline_file
        if not path.exists():
            # Fall back to default location
            fallback = self._default_pipeline_path()
            if fallback.exists():
                path = fallback
                self._pipeline_file = path
            else:
                raise FileNotFoundError(
                    f"pipeline.yaml not found at {self._pipeline_file} "
                    f"or {fallback}"
                )

        config = _load_yaml(path)
        self._pipeline_config = config
        self._build_stage_index(config)
        return config

    def _build_stage_index(self, config: dict):
        """Build internal stage indexes from the pipeline config."""
        stages_def = config.get("stages", {})
        if not stages_def:
            raise ValueError("pipeline.yaml has no 'stages' section")

        # Build state_id → pipeline_key mapping
        pkey_map: Dict[str, str] = {}   # state_id → pipeline_key
        rev_map: Dict[str, str] = {}    # pipeline_key → state_id
        defs: Dict[str, dict] = {}      # state_id → stage_def

        for key, sdef in stages_def.items():
            state_id = sdef.get("id", key)  # explicit id or fallback to key
            pkey_map[state_id] = key
            rev_map[key] = state_id
            defs[state_id] = sdef

        self._stage_defs = defs
        self._pipeline_key_map = pkey_map
        self._reverse_key_map = rev_map

        # Sort by order
        self._stage_order = sorted(
            defs.keys(),
            key=lambda sid: defs[sid].get("order", 99)
        )

        # Build dependency graph from `depends_on`
        deps: Dict[str, List[str]] = {}
        for sid in self._stage_order:
            raw = defs[sid].get("depends_on", [])
            # Resolve: depends_on can reference by state_id or pipeline_key
            resolved = []
            for dep in raw:
                # dep might be a state_id or a pipeline_key
                if dep in self._pipeline_key_map:
                    resolved.append(dep)  # already a state_id
                elif dep in self._reverse_key_map:
                    resolved.append(self._reverse_key_map[dep])  # it's a pipeline_key
                else:
                    # Fallback: treat as state_id directly
                    resolved.append(dep)
            deps[sid] = resolved

        self._stage_deps = deps

        # Build reverse dependency graph: who depends on whom
        r_deps: Dict[str, List[str]] = {sid: [] for sid in self._stage_order}
        for sid, dep_list in deps.items():
            for dep in dep_list:
                if dep in r_deps:
                    r_deps[dep].append(sid)
        self._stage_r_deps = r_deps

    def get_pipeline_key(self, state_id: str) -> str:
        """Get the pipeline.yaml key for a given state ID."""
        self.load_pipeline_config()
        return self._pipeline_key_map.get(state_id, state_id)

    def get_stage_def(self, state_id: str) -> dict:
        """Get the full pipeline definition for a stage."""
        self.load_pipeline_config()
        return self._stage_defs.get(state_id, {})

    # ── Read pipeline stage info ─────────────────────────────────

    def load_pipeline_stages(self) -> List[str]:
        """Return the canonical stage list (state IDs), sorted by pipeline order.

        This is the key method that makes pipeline.yaml the single source of truth.
        The returned list is cached — subsequent calls return the same object.
        """
        self.load_pipeline_config()
        return self._stage_order

    @property
    def stages(self) -> List[str]:
        return self.load_pipeline_stages()

    def load_pipeline_deps(self) -> Dict[str, List[str]]:
        """Return the dependency graph, keyed by state ID."""
        self.load_pipeline_config()
        return dict(self._stage_deps)

    def get_stage_label(self, state_id: str) -> str:
        """Get the human-readable label for a stage from pipeline.yaml."""
        sdef = self.get_stage_def(state_id)
        return sdef.get("description", state_id)

    # ── Stage name resolution (backward compat) ──────────────────

    def resolve_stage_id(self, name: str) -> str:
        """Resolve a stage name to its canonical state ID.

        Accepts either the short state ID, the pipeline.yaml key, or a legacy short name.
        Raises ValueError if the name cannot be resolved.
        """
        self.load_pipeline_config()

        # 1. Direct match (most common — scripts use state IDs)
        if name in self._stage_order:
            return name

        # 2. It's a pipeline.yaml key
        if name in self._reverse_key_map:
            return self._reverse_key_map[name]

        # 3. Legacy/unknown
        raise ValueError(
            f"Unknown stage: '{name}'. Valid IDs: {self._stage_order}"
        )

    # ── State file I/O ───────────────────────────────────────────

    def _state_path(self, project: str) -> Path:
        return self.root / project / "state.json"

    def init_project(self, project: str) -> dict:
        """Initialize a new project state with v2 schema."""
        proj_dir = self.root / project
        proj_dir.mkdir(parents=True, exist_ok=True)

        stage_ids = self.load_pipeline_stages()
        now = datetime.now(TZ).isoformat()
        state = {
            "schema_version": 2,
            "project": project,
            "created": now,
            "updated": now,
            "stages": {
                sid: {
                    "status": "pending",
                    "checkpoint": None,
                    "params_hash": None,
                    "dirty": False,
                    "dirty_reason": None,
                }
                for sid in stage_ids
            },
            "errors": [],
            "checkpoint_history": [],
            "dirty_history": [],
        }
        self._write(project, state)
        return state

    def load(self, project: str) -> dict:
        """Load project state with corruption recovery and auto-migration.

        - Missing state.json → fresh init (v2)
        - v1 state.json → auto-migrate to v2
        - Corrupt state.json → try .tmp backup → fallback to fresh init
        """
        path = self._state_path(project)
        if not path.exists():
            return self.init_project(project)

        try:
            with open(path, "r") as f:
                state = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError) as e:
            tmp = path.with_suffix(".json.tmp")
            if tmp.exists():
                try:
                    with open(tmp, "r") as f:
                        state = json.load(f)
                    import shutil
                    shutil.copy2(tmp, path)
                except (json.JSONDecodeError, FileNotFoundError):
                    # Unrecoverable
                    logging.warning(
                        "state.json for '%s' was corrupt and unrecoverable; reinitializing",
                        project,
                    )
                    return self.init_project(project)
            else:
                logging.warning(
                    "state.json for '%s' was corrupt; reinitializing",
                    project,
                )
                return self.init_project(project)

        # Auto-migrate from v1 to v2
        stage_ids = self.load_pipeline_stages()
        state = migrate_v1_to_v2(state, stage_ids)

        # Ensure all pipeline stages exist in state (add new ones as pending)
        stages = state.setdefault("stages", {})
        now = datetime.now(TZ).isoformat()
        for sid in stage_ids:
            if sid not in stages:
                stages[sid] = {
                    "status": "pending",
                    "checkpoint": None,
                    "params_hash": None,
                    "dirty": False,
                    "dirty_reason": None,
                }

        # Bump updated timestamp (subtle: don't force-write on load, only on explicit save)
        return state

    def get(self, project: str) -> dict:
        """Read project state. Auto-initializes if not exists; recovers from corruption."""
        return self.load(project)

    def _write_atomic(self, path: Path, data: dict):
        """Write JSON atomically via tmp + os.replace, with file lock.

        Uses fcntl.flock to prevent concurrent writes from parallel stages
        from corrupting state.json.
        """
        # Acquire exclusive lock on the target file (not tmp)
        # This ensures only one writer at a time
        lock_path = path.with_suffix(".json.lock")
        fd = open(lock_path, "w")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
        except Exception:
            fd.close()
            raise

        tmp = path.with_suffix(".json.tmp")
        try:
            with open(tmp, "w") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            fd.close()
            # Do NOT unlink lock file — keep it so all processes
            # use the same inode for proper flock coordination.

    def _write(self, project: str, state: dict):
        state["updated"] = datetime.now(TZ).isoformat()
        path = self._state_path(project)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._write_atomic(path, state)

    # ── Stage status methods ─────────────────────────────────────

    def update_stage(self, project: str, stage: str, status: str, **kwargs):
        """Update a single stage's status.

        Args:
            project: Project name.
            stage: Stage ID (short name or pipeline key — both are accepted).
            status: New status (pending / running / completed / failed / skipped).
            **kwargs: Extra metadata to store (output, generated, etc.).

        Raises:
            ValueError: If the stage name cannot be resolved.
        """
        sid = self.resolve_stage_id(stage)
        state = self.get(project)
        entry = {
            "status": status,
            "ts": datetime.now(TZ).isoformat(),
        }
        entry.update(kwargs)
        # Preserve v2 fields
        existing = state["stages"].get(sid, {})
        for v2field in ("checkpoint", "params_hash", "dirty", "dirty_reason"):
            if v2field in existing:
                entry.setdefault(v2field, existing[v2field])
        state["stages"][sid] = entry
        self._write(project, state)
        return state

    def mark_completed(self, project: str, stage: str, **kwargs):
        """Mark a stage as completed."""
        return self.update_stage(project, stage, "completed", **kwargs)

    def mark_running(self, project: str, stage: str, **kwargs):
        """Mark a stage as running."""
        return self.update_stage(project, stage, "running", **kwargs)

    def mark_failed(self, project: str, stage: str, error: str):
        """Mark a stage as failed and record error (single read-modify-write)."""
        sid = self.resolve_stage_id(stage)
        state = self.get(project)
        entry = state["stages"].get(sid, {"status": "pending"})
        entry["status"] = "failed"
        entry["error"] = error
        entry["ts"] = datetime.now(TZ).isoformat()
        # Preserve v2 fields
        for v2field in ("checkpoint", "params_hash", "dirty", "dirty_reason"):
            existing = state["stages"].get(sid, {})
            if v2field in existing:
                entry.setdefault(v2field, existing[v2field])
        state["stages"][sid] = entry
        state.setdefault("errors", []).append({
            "stage": sid,
            "error": error,
            "ts": datetime.now(TZ).isoformat(),
            "severity": "error",
        })
        self._write(project, state)
        return state

    def add_error(self, project: str, stage: str, error: str):
        """Record a non-fatal error (e.g. quality check warning) without changing status."""
        sid = self.resolve_stage_id(stage)
        state = self.get(project)
        state["errors"].append({
            "stage": sid,
            "error": error,
            "ts": datetime.now(TZ).isoformat(),
            "severity": "warning",
        })
        self._write(project, state)
        return state

    # ── Dirty marking (v2 enhanced) ──────────────────────────────

    def mark_dirty(self, project: str, stage: str, reason: str = ""):
        """Mark a stage as dirty (needs re-run) with an optional reason.

        Unlike the old mark_stale(), this only marks the *specified* stage.
        Downstream stages are NOT automatically marked — use mark_stale()
        for that behavior.

        Records the dirty mark in dirty_history for audit.
        """
        sid = self.resolve_stage_id(stage)
        state = self.get(project)
        entry = state["stages"].get(sid, {"status": "pending"})
        entry["status"] = "pending"
        entry["dirty"] = True
        entry["dirty_reason"] = reason
        state["stages"][sid] = entry

        # Record in dirty_history
        state.setdefault("dirty_history", []).append({
            "stage": sid,
            "reason": reason,
            "ts": datetime.now(TZ).isoformat(),
        })

        self._write(project, state)
        return state

    def mark_stale(self, project: str, from_stage: str):
        """Mark *from_stage* and all downstream stages as pending (dirty).

        Enhanced v2 version: uses the dependency graph — only stages that
        *transitively* depend on *from_stage* are marked.  Stages in the
        linear pipeline order that don't actually depend on *from_stage*
        are left untouched.

        Records why each stage was marked stale.
        """
        sid = self.resolve_stage_id(from_stage)

        # Build the set of stages to mark via BFS on the reverse dep graph
        affected = {sid}
        queue = [sid]
        self.load_pipeline_config()  # ensures _stage_r_deps is built
        while queue:
            current = queue.pop(0)
            for downstream in self._stage_r_deps.get(current, []):
                if downstream not in affected:
                    affected.add(downstream)
                    queue.append(downstream)

        state = self.get(project)

        for s in affected:
            entry = state["stages"].get(s, {"status": "pending"})
            reason = f"upstream {sid} re-run" if s != sid else f"manual stale from {sid}"
            state["stages"][s] = {
                "status": "pending",
                "dirty": True,
                "dirty_reason": reason,
                # Preserve checkpoint data so we know what was done before
                "checkpoint": entry.get("checkpoint") if isinstance(entry, dict) else None,
                "params_hash": entry.get("params_hash") if isinstance(entry, dict) else None,
            }

        state.setdefault("dirty_history", []).append({
            "stage": sid,
            "reason": "mark_stale cascade",
            "downstream": sorted(affected),
            "ts": datetime.now(TZ).isoformat(),
        })

        self._write(project, state)
        return state

    def get_dirty_stages(self, project: str) -> List[Dict[str, Any]]:
        """Return all stages currently marked as dirty, with reasons.

        Returns:
            List of {stage, reason, status} dicts.
        """
        state = self.get(project)
        dirty = []
        for sid, entry in state.get("stages", {}).items():
            if isinstance(entry, dict) and entry.get("dirty"):
                dirty.append({
                    "stage": sid,
                    "reason": entry.get("dirty_reason", ""),
                    "status": entry.get("status", "pending"),
                })
        return dirty

    def clear_dirty(self, project: str, stage: str):
        """Clear the dirty flag on a specific stage (without changing its status)."""
        sid = self.resolve_stage_id(stage)
        state = self.get(project)
        entry = state["stages"].get(sid, {"status": "pending"})
        if isinstance(entry, dict):
            entry["dirty"] = False
            entry["dirty_reason"] = None
            state["stages"][sid] = entry
        self._write(project, state)
        return state

    # ── Checkpoint mechanism (v2) ────────────────────────────────

    def record_checkpoint(self, project: str, stage: str,
                          shot_id: int, status: str = "completed",
                          **metadata):
        """Record the status of an individual shot/item within a stage.

        Args:
            project: Project name.
            stage: Stage ID.
            shot_id: Integer shot/item identifier (1-based).
            status: "completed" | "failed" | "skipped".
            **metadata: Extra info (e.g. {"path": "s5_frames/s01_first.png"}).

        The checkpoint data is stored in the stage's 'checkpoint' field.
        """
        sid = self.resolve_stage_id(stage)
        state = self.get(project)
        entry = state["stages"].get(sid, {"status": "running"})

        cp = entry.get("checkpoint")
        if cp is None:
            cp = {
                "total_shots": 0,
                "completed_shots": [],
                "failed_shots": [],
                "last_checkpoint": None,
                "shot_metadata": {},
            }
            entry["checkpoint"] = cp

        cp["last_checkpoint"] = datetime.now(TZ).isoformat()
        if status == "completed":
            if shot_id not in cp["completed_shots"]:
                cp["completed_shots"].append(shot_id)
            if shot_id in cp["failed_shots"]:
                cp["failed_shots"].remove(shot_id)
        elif status == "failed":
            if shot_id not in cp["failed_shots"]:
                cp["failed_shots"].append(shot_id)
            if shot_id in cp["completed_shots"]:
                cp["completed_shots"].remove(shot_id)

        # Preserve total_shots from init_checkpoint; auto-detect only when not initialized
        if cp["total_shots"] == 0:
            all_shots = set(cp.get("completed_shots", [])) | set(cp.get("failed_shots", []))
            cp["total_shots"] = len(all_shots)

        # Store metadata
        if metadata:
            cp.setdefault("shot_metadata", {})
            cp["shot_metadata"][str(shot_id)] = metadata

        state["stages"][sid] = entry
        self._write(project, state)
        return state

    def get_checkpoint(self, project: str, stage: str) -> Optional[dict]:
        """Get the current checkpoint data for a stage.

        Returns:
            Dict with total_shots, completed_shots, failed_shots, last_checkpoint, shot_metadata.
            None if no checkpoint has been recorded.
        """
        sid = self.resolve_stage_id(stage)
        state = self.get(project)
        entry = state["stages"].get(sid, {})
        if isinstance(entry, dict):
            return entry.get("checkpoint")
        return None

    def skip_completed_shots(self, project: str, stage: str) -> List[int]:
        """Get the list of shot IDs that have been completed for this stage.

        Convenience method: returns the completed_shots list, or empty list.
        """
        cp = self.get_checkpoint(project, stage)
        if cp is None:
            return []
        return cp.get("completed_shots", [])

    def init_checkpoint(self, project: str, stage: str, total_shots: int):
        """Initialize a checkpoint for a stage with a known total shot count."""
        sid = self.resolve_stage_id(stage)
        state = self.get(project)
        entry = state["stages"].get(sid, {"status": "running"})
        entry["checkpoint"] = {
            "total_shots": total_shots,
            "completed_shots": [],
            "failed_shots": [],
            "last_checkpoint": None,
            "shot_metadata": {},
        }
        state["stages"][sid] = entry
        self._write(project, state)
        return state

    # ── Parameter hash support ───────────────────────────────────

    def record_params(self, project: str, stage: str, args: dict):
        """Record the params hash for a stage upon execution start.

        The hash is stored alongside the stage status, and is used by
        params_changed() on subsequent runs.
        """
        sid = self.resolve_stage_id(stage)
        state = self.get(project)
        entry = state["stages"].get(sid, {"status": "pending"})
        entry["params_hash"] = compute_params_hash(args)
        state["stages"][sid] = entry
        self._write(project, state)
        return state

    def params_changed(self, project: str, stage: str, new_args: dict) -> bool:
        """Check if a stage's parameters have changed since last run.

        If the stage has never been run (no params_hash), returns False
        (no prior params to compare against — caller should run normally).

        If params have changed, also marks the stage as dirty automatically.

        Returns:
            True if params differ from last recorded run, False otherwise.
        """
        sid = self.resolve_stage_id(stage)
        state = self.get(project)
        entry = state["stages"].get(sid, {"status": "pending"})
        old_hash = entry.get("params_hash") if isinstance(entry, dict) else None

        if old_hash is None:
            return False  # Never run — no change to detect

        new_hash = compute_params_hash(new_args)
        if new_hash != old_hash:
            self.mark_dirty(project, sid,
                            f"params changed: {old_hash} → {new_hash}")
            return True
        return False

    def get_params_hash(self, project: str, stage: str) -> Optional[str]:
        """Get the stored params hash for a stage."""
        sid = self.resolve_stage_id(stage)
        state = self.get(project)
        entry = state["stages"].get(sid, {})
        if isinstance(entry, dict):
            return entry.get("params_hash")
        return None

    # ── Pipeline orchestration helpers ───────────────────────────

    def next_pending(self, project: str) -> Optional[str]:
        """Get the next pending stage, checking dependencies.

        Skips completed and running stages. Returns the first pending stage
        whose dependencies are all completed.

        If a stage is dirty, it's treated as pending (needs re-run).
        If a stage is failed, it returns that stage for retry.
        """
        state = self.get(project)
        deps = self.load_pipeline_deps()

        for sid in self.load_pipeline_stages():
            entry = state["stages"].get(sid, {"status": "pending"})
            if isinstance(entry, str):
                entry = {"status": entry}
            status = entry.get("status", "pending")

            # Dirty stages are effectively pending
            if status == "completed" and not entry.get("dirty"):
                continue
            if status == "running":
                continue

            # Check dependencies
            dep_list = deps.get(sid, [])
            deps_met = all(
                state["stages"].get(d, {}).get("status") == "completed"
                if isinstance(state["stages"].get(d), dict)
                else state["stages"].get(d) == "completed"
                for d in dep_list
            )
            if deps_met:
                return sid
            if status == "failed":
                return sid  # Failed stage is always "next" for retry

        return None

    def progress(self, project: str) -> str:
        """Generate a human-readable progress report."""
        state = self.get(project)
        stage_ids = self.load_pipeline_stages()
        lines = [f"Project: {project}"]

        completed = 0
        for sid in stage_ids:
            entry = state["stages"].get(sid, {"status": "pending"})
            if isinstance(entry, str):
                entry = {"status": entry}
            status = entry.get("status", "pending")
            label = self.get_stage_label(sid)

            icon = {
                "completed": "✅",
                "running": "🔄",
                "failed": "❌",
                "pending": "⬜",
            }.get(status, "⬜")

            # Dirty indicator
            dirty_mark = " ⚠️ dirty" if entry.get("dirty") else ""

            detail = ""
            if entry.get("progress"):
                detail = f" ({entry['progress']})"
            if entry.get("error"):
                detail = f" — {entry['error'][:60]}"

            # Checkpoint summary
            cp = entry.get("checkpoint")
            if cp and isinstance(cp, dict):
                done = len(cp.get("completed_shots", []))
                total = cp.get("total_shots", 0)
                if total > 0:
                    detail += f" [{done}/{total} shots]"

            lines.append(f"  {icon} {sid} {label}{dirty_mark}{detail}")
            if status == "completed" and not entry.get("dirty"):
                completed += 1

        lines.append(f"\nProgress: {completed}/{len(stage_ids)} stages complete")
        if state.get("errors"):
            lines.append(f"Errors: {len(state['errors'])}")
        if state.get("dirty_history"):
            lines.append(f"Dirty events: {len(state['dirty_history'])}")

        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════
# Backward-compatible exports
# ═══════════════════════════════════════════════════════════════════

# Deprecated — kept for scripts that import these directly.
# New code should use StateManager.stages / load_pipeline_stages().
STAGE_ORDER = _LEGACY_STAGE_ORDER
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

# ═══════════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════════

_DEFAULT = None


def get_state_manager(projects_root: str = None) -> StateManager:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = StateManager(projects_root)
    return _DEFAULT
