"""
core/parallel_executor.py — Parallel Stage Execution Engine

Runs multiple pipeline stages concurrently via ThreadPoolExecutor.
Each stage is isolated: one failure does NOT cancel or affect the others.
Stages update their own state.json entries independently (subprocess handles this).

Design decisions:
  - ThreadPoolExecutor with max_workers=2 (only S8+S9 are ever parallel)
  - Each stage launches as a subprocess (identical to serial execution path)
  - GPU coordination is handled by the caller (ensure_comfyui before parallel)
  - Returns per-stage results with full error isolation

Usage:
    results = run_parallel_stages(project, pipeline, stage_tasks, skip_vl)
"""

import sys
import time
import subprocess
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple, Any

logger = logging.getLogger(__name__)


def run_parallel_stages(
    project: Path,
    stage_tasks: List[Tuple[str, dict, Callable]],
    parallel_label: str = "parallel",
    max_workers: int = 2,
) -> Dict[str, Tuple[bool, Any]]:
    """Run multiple stage tasks concurrently with error isolation.

    Args:
        project: Project directory Path.
        stage_tasks: List of (stage_id, stage_def, run_func) tuples.
                     run_func is a callable(stage_id, stage_def) -> (bool, detail).
        parallel_label: Label for logging.
        max_workers: Max concurrent threads (default 2 — safe for S8+S9).

    Returns:
        Dict mapping stage_id -> (success, result_dict)
        where result_dict includes elapsed time and note.
    """
    results: Dict[str, Tuple[bool, Any]] = {}

    def _wrap_task(stage_id: str, stage_def: dict, run_func: Callable) -> Tuple[str, bool, Any, float]:
        """Wrap a single stage execution with timing and error catching."""
        t0 = time.time()
        try:
            success, detail = run_func(stage_id, stage_def)
            elapsed = time.time() - t0
            return stage_id, success, {"elapsed": elapsed, "note": detail}, elapsed
        except Exception as e:
            elapsed = time.time() - t0
            err_msg = f"EXCEPTION: {e}"
            logger.exception(f"Parallel stage {stage_id} threw exception")
            return stage_id, False, {"elapsed": elapsed, "note": err_msg}, elapsed

    # Launch all tasks concurrently
    n = len(stage_tasks)
    stage_ids_str = ", ".join(sid for sid, _, _ in stage_tasks)
    logger.info(f"🚀 Parallel group [{parallel_label}] ({n} stages): {stage_ids_str}")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {}
        for stage_id, stage_def, run_func in stage_tasks:
            future = executor.submit(_wrap_task, stage_id, stage_def, run_func)
            future_map[future] = stage_id

        # Collect results as they complete (streaming feedback)
        for future in as_completed(future_map):
            sid, success, result, elapsed = future.result()
            icon = "✅" if success else "❌"
            logger.info(f"  {icon} [parallel] {sid} ({elapsed:.1f}s): {result.get('note', '')}")
            results[sid] = (success, result)

    # Summary
    successes = sum(1 for s, _ in results.values() if s)
    failures = n - successes
    logger.info(f"  Parallel group [{parallel_label}] complete: {successes}✅ {failures}❌")

    return results


def find_parallel_groups(
    pipeline: dict,
    completed_stages: set,
    max_group_size: int = 2,
) -> List[List[Tuple[str, dict]]]:
    """Find stages that can be run in parallel based on dependency graph.

    A parallel group is a set of stages where:
      1. All their dependencies are in `completed_stages` (resolved via ID→key map)
      2. They don't depend on each other
      3. They share a common dependency
      4. No GPU contention (one comfyui + one none)

    Args:
        pipeline: Parsed pipeline.yaml dict.
        completed_stages: Set of pipeline keys that have completed.
        max_group_size: Maximum group size (default 2).

    Returns:
        List of groups, where each group is a list of (stage_id, stage_def).
    """
    stages = pipeline.get("stages", {})
    if not stages:
        return []

    # Build ID-to-key mapping
    id_to_key = {}
    for key, sdef in stages.items():
        sid = sdef.get("id", key)
        id_to_key[sid] = key

    def _resolve(name: str) -> str:
        return id_to_key.get(name, name)

    # Build dependency map (resolved to pipeline keys) and GPU map
    deps_map: Dict[str, set] = {}
    gpu_map: Dict[str, str] = {}
    for key, sdef in stages.items():
        raw_deps = sdef.get("depends_on", [])
        deps_map[key] = set(_resolve(d) for d in raw_deps if d)
        gpu_map[key] = sdef.get("gpu", "none")

    # Find pending stages whose deps are all met
    ready = []
    for key, sdef in stages.items():
        if key in completed_stages:
            continue  # Already completed
        if not is_parallelizable_stage(key, sdef):
            continue
        sdef_deps = deps_map.get(key, set())
        if not sdef_deps:
            continue
        if sdef_deps.issubset(completed_stages):
            ready.append((key, sdef))

    # Group ready stages
    groups = []
    used = set()
    ready.sort(key=lambda x: stages[x[0]].get("order", 99))

    for i, (key_a, sdef_a) in enumerate(ready):
        if key_a in used:
            continue
        deps_a = deps_map.get(key_a, set())
        group = [(key_a, sdef_a)]
        used.add(key_a)

        for key_b, sdef_b in ready[i + 1:]:
            if key_b in used:
                continue
            if len(group) >= max_group_size:
                break
            if not is_parallelizable_stage(key_b, sdef_b):
                continue
            deps_b = deps_map.get(key_b, set())
            if key_a in deps_b or key_b in deps_a:
                continue
            if not (deps_a & deps_b):
                continue
            # GPU: one comfyui + one none
            ga, gb = gpu_map.get(key_a, "none"), gpu_map.get(key_b, "none")
            if ga == "comfyui" and gb == "comfyui":
                continue
            if ga == "none" and gb == "none":
                continue
            group.append((key_b, sdef_b))
            used.add(key_b)

        if len(group) >= 2:
            groups.append(group)

    return groups


def find_potential_parallel_groups(
    pipeline: dict,
    max_group_size: int = 2,
) -> List[List[Tuple[str, dict]]]:
    """Analyze the DAG structurally to find stages that COULD be parallelized.

    Finds sibling stages (S8+S9 pattern) that:
      1. Share at least one common dependency
      2. Don't depend on each other
      3. All non-shared dependencies have a lower pipeline order than the
         shared dependency (so they complete before the parallel group)
      4. No GPU contention: exactly one stage uses comfyui, one uses none
         (targets S8∥S9: GPU + CPU without contention)

    Useful for dry-run / validation mode.

    Args:
        pipeline: Parsed pipeline.yaml dict.
        max_group_size: Maximum group size (default 2).

    Returns:
        List of parallelizable groups found in the DAG structure.
    """
    stages = pipeline.get("stages", {})
    if not stages:
        return []

    # Build mappings: state_id → pipeline_key, and pipeline_key → state_id
    key_to_id = {}
    id_to_key = {}
    for key, sdef in stages.items():
        sid = sdef.get("id", key)  # Use explicit id, fallback to key
        key_to_id[key] = sid
        id_to_key[sid] = key

    def resolve_key(name: str) -> str:
        """Resolve a state ID or pipeline key to its pipeline key."""
        return id_to_key.get(name, name)

    # Build dependency map (using pipeline keys) and order map
    deps_map: Dict[str, set] = {}
    order_map: Dict[str, int] = {}
    gpu_map: Dict[str, str] = {}
    for key, sdef in stages.items():
        # Resolve dependency names to pipeline keys
        raw_deps = sdef.get("depends_on", [])
        deps_map[key] = set(resolve_key(d) for d in raw_deps if d)
        order_map[key] = sdef.get("order", 99)
        gpu_map[key] = sdef.get("gpu", "none")

    # Collect all valid sibling pairs
    all_keys = list(stages.keys())
    groups = []
    used_stages = set()

    for i, key_a in enumerate(all_keys):
        if key_a in used_stages or not is_parallelizable_stage(key_a, stages[key_a]):
            continue
        deps_a = deps_map.get(key_a, set())
        if not deps_a:
            continue

        for key_b in all_keys[i + 1:]:
            if key_b in used_stages or not is_parallelizable_stage(key_b, stages[key_b]):
                continue
            deps_b = deps_map.get(key_b, set())
            if not deps_b:
                continue

            # No inter-dependency
            if key_a in deps_b or key_b in deps_a:
                continue

            # Must share at least one common dependency
            shared = deps_a & deps_b
            if not shared:
                continue

            # The shared dependency must be the LATEST common dependency
            shared_order = max(order_map.get(d, 0) for d in shared)

            # All non-shared deps must be at lower order than the shared dep
            other_a = deps_a - shared
            other_b = deps_b - shared
            if not all(order_map.get(d, 0) < shared_order for d in other_a | other_b):
                continue

            # At least one stage must ONLY depend on the shared dep
            # (pure sibling pattern matching S8: only depends on s7_assemble)
            if other_a and other_b:
                continue

            # GPU contention check: exactly one GPU + one CPU (S8∥S9 pattern)
            gpu_a = gpu_map.get(key_a, "none")
            gpu_b = gpu_map.get(key_b, "none")
            if gpu_a == "comfyui" and gpu_b == "comfyui":
                continue  # Two comfyui stages would fight for GPU
            if gpu_a == "none" and gpu_b == "none":
                continue  # CPU-only pair provides no benefit

            group = [(key_a, stages[key_a]), (key_b, stages[key_b])]
            groups.append(group)
            used_stages.add(key_a)
            used_stages.add(key_b)
            break

    # Sort by lowest order in each group
    groups.sort(key=lambda g: min(s[1].get("order", 99) for s in g))
    return groups


def is_parallelizable_stage(stage_id: str, stage_def: dict) -> bool:
    """Check if a stage is safe to run in parallel.

    Only CPU-only stages (gpu=none) are safe for parallelization.
    GPU stages (comfyui, qw35_vl) share the same GPU and cannot run in parallel.

    Args:
        stage_id: Stage ID.
        stage_def: Stage definition from pipeline.yaml.

    Returns:
        True if the stage can safely run in parallel (CPU-only).
    """
    gpu = stage_def.get("gpu", "none")
    # Only CPU-only stages are parallel-safe
    return gpu == "none"
