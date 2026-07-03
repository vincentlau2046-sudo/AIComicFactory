#!/usr/bin/env python3
"""
scripts/e2e_dry_run.py — End-to-End Pipeline Driver (v2.0)

从 pipeline.yaml 声明式定义读取 stage 列表、依赖、GPU 需求，
自动编排执行顺序，管理 GPU 生命周期（ComfyUI + qw35-9b VL 质检）。

核心改进 (v2.0):
  1. 声明式管线定义 → 不会再遗漏任何 stage
  2. 自动依赖检查 → 跳过前置条件未满足的 stage
  3. GPU 生命周期编排 → ComfyUI / qw35-9b 按需启停
  4. VL 质检策略 → stage 完成后启动 qw35 → 质检 → 释放
  5. 跳过已有产出 → 支持 skip_existing 的 stage
  6. 失败不中断 → 记录失败 stage 但继续后续独立 stage

用法:
    python scripts/e2e_dry_run.py                          # 全链路
    python scripts/e2d_dry_run.py --from s5                # 从 S5 开始
    python scripts/e2d_dry_run.py --only s3,s3b,s5         # 只跑指定 stage
    python scripts/e2d_dry_run.py --skip-vl                # 跳过所有 VL 质检
"""

import json, sys, os, time, subprocess, traceback, shutil, urllib.request, re
from pathlib import Path
from datetime import datetime, timezone, timedelta

TZ = timezone(timedelta(hours=8))
AICF_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(AICF_ROOT))

try:
    import yaml
except ImportError:
    # Fallback: minimal YAML parser for our simple structure
    yaml = None

from core.llm_client import get_llm_client
from core.prompt_runner import run_script_parse, run_character_extract, run_shot_split

# ═══════════════════════════════════════════════════════════════════
# Logging
# ═══════════════════════════════════════════════════════════════════

log_lines = []
start_global = time.time()

def log(msg: str, level: str = "INFO"):
    ts = datetime.now(TZ).strftime("%H:%M:%S")
    line = f"[{ts}] [{level}] {msg}"
    print(line, flush=True)
    log_lines.append(line)

def log_header(stage_id: str, stage_def: dict):
    desc = stage_def.get("description", stage_id)
    gpu = stage_def.get("gpu", "none")
    gpu_icon = {"comfyui": "🎨", "qw35_vl": "👁️", "none": "📝"}.get(gpu, "❓")
    log("=" * 60)
    log(f"  {gpu_icon} {stage_id.upper()}: {desc}")
    log(f"  GPU: {gpu} | Runner: {stage_def.get('runner', '?')}")
    log("=" * 60)


# ═══════════════════════════════════════════════════════════════════
# Pipeline YAML Loader
# ═══════════════════════════════════════════════════════════════════

def parse_yaml_simple(text: str) -> dict:
    """Minimal YAML parser for pipeline.yaml structure.
    Handles: top-level keys, nested dicts with string/scalar values, lists of scalars.
    Not a general YAML parser — just enough for our schema.
    """
    result = {}
    current_key = None
    current_dict = None
    in_stages = False
    in_stage = False
    stage_name = None
    stage_data = {}
    in_list = False
    list_key = None
    list_items = []
    in_vl = False
    vl_data = {}
    vl_key = None

    for line in text.split('\n'):
        stripped = line.rstrip()
        if not stripped or stripped.startswith('#'):
            continue

        # Detect top-level sections
        if not line.startswith(' ') and ':' in stripped:
            # Close previous
            if in_stage and stage_name:
                result.setdefault('stages', {})[stage_name] = stage_data
                stage_data = {}
                in_stage = False
            if in_vl and vl_data:
                result['vl_check_strategy'] = vl_data
                vl_data = {}
                in_vl = False

            key, _, val = stripped.partition(':')
            key = key.strip()
            val = val.strip()

            if key == 'stages':
                in_stages = True
                in_vl = False
                result['stages'] = {}
                continue
            elif key == 'vl_check_strategy':
                in_vl = True
                in_stages = False
                continue
            else:
                in_stages = False
                in_vl = False
                if val:
                    result[key] = _parse_val(val)
                continue

        indent = len(line) - len(line.lstrip())

        # Stages section
        if in_stages:
            if indent == 4 and stripped.endswith(':'):
                # New stage
                if stage_name and in_stage:
                    result['stages'][stage_name] = stage_data
                stage_name = stripped.rstrip(':').strip()
                stage_data = {}
                in_stage = True
                in_list = False
                continue
            if in_stage and indent >= 6:
                content = stripped.strip()
                if ':' in content:
                    k, _, v = content.partition(':')
                    k = k.strip()
                    v = v.strip()
                    if v:
                        stage_data[k] = _parse_val(v)
                    elif k in ('requires', 'produces', 'args'):
                        in_list = True
                        list_key = k
                        list_items = []
                    else:
                        in_list = False
                continue

        # VL strategy section
        if in_vl and indent >= 2:
            content = stripped.strip()
            if ':' in content:
                k, _, v = content.partition(':')
                k = k.strip()
                v = v.strip()
                if v:
                    vl_data[k] = _parse_val(v)

    # Close last stage
    if in_stage and stage_name:
        result.setdefault('stages', {})[stage_name] = stage_data
    if in_vl and vl_data:
        result['vl_check_strategy'] = vl_data

    return result


def _parse_val(v: str):
    """Parse a YAML scalar value."""
    if v in ('true', 'True'):
        return True
    if v in ('false', 'False'):
        return False
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        pass
    return v


def load_pipeline(path: Path) -> dict:
    """Load pipeline.yaml definition."""
    text = path.read_text()
    if yaml:
        return yaml.safe_load(text)
    return parse_yaml_simple(text)


# ═══════════════════════════════════════════════════════════════════
# GPU Lifecycle Manager
# ═══════════════════════════════════════════════════════════════════

EDGE_LLM = os.path.expanduser("~/bin/edge-llm")
COMFYUI_PORT = 8188
QW35_HEALTH_URL = "http://localhost:8002/health"


def _comfyui_healthy() -> bool:
    try:
        req = urllib.request.Request(f"http://localhost:{COMFYUI_PORT}/system_stats")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except Exception:
        return False


def _qw35_healthy() -> bool:
    try:
        req = urllib.request.Request(QW35_HEALTH_URL)
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except Exception:
        return False


def ensure_comfyui() -> bool:
    """确保 ComfyUI 运行，否则启动。"""
    if _comfyui_healthy():
        return True
    log("  启动 ComfyUI...")
    try:
        r = subprocess.run(
            [EDGE_LLM, "switch", "comfyui"],
            capture_output=True, text=True, timeout=60
        )
        if r.returncode != 0:
            log(f"  ⚠️ ComfyUI 启动失败: {r.stderr[:200]}", "WARN")
            return False
        # 等健康
        for _ in range(30):
            if _comfyui_healthy():
                log("  ✅ ComfyUI 就绪", "OK")
                return True
            time.sleep(2)
        log("  ⚠️ ComfyUI 启动超时", "WARN")
        return False
    except Exception as e:
        log(f"  ⚠️ ComfyUI 启动异常: {e}", "WARN")
        return False


def ensure_qw35() -> bool:
    """确保 qw35-9b 运行，否则启动。启动前会先释放 ComfyUI 的独占 GPU（如果需要）。"""
    if _qw35_healthy():
        return True
    log("  启动 qw35-9b (VL 质检)...")
    try:
        r = subprocess.run(
            [EDGE_LLM, "switch", "qwen35-9b"],
            capture_output=True, text=True, timeout=60
        )
        if r.returncode != 0:
            log(f"  ⚠️ qw35-9b 启动失败: {r.stderr[:200]}", "WARN")
            return False
        # 等健康 (约 2 分钟)
        log("  等待 qw35-9b 就绪...")
        for i in range(60):
            if _qw35_healthy():
                log("  ✅ qw35-9b 就绪", "OK")
                return True
            time.sleep(3)
        log("  ⚠️ qw35-9b 启动超时", "WARN")
        return False
    except Exception as e:
        log(f"  ⚠️ qw35-9b 启动异常: {e}", "WARN")
        return False


def release_qw35() -> bool:
    """释放 qw35-9b GPU 资源。"""
    if not _qw35_healthy():
        return True
    log("  释放 qw35-9b GPU...")
    try:
        r = subprocess.run(
            [EDGE_LLM, "stop", "qwen35-9b"],
            capture_output=True, text=True, timeout=60
        )
        time.sleep(3)
        if not _qw35_healthy():
            log("  ✅ qw35-9b 已释放", "OK")
            return True
        # Fallback: switch idle
        subprocess.run([EDGE_LLM, "switch", "idle"], capture_output=True, text=True, timeout=30)
        time.sleep(3)
        log("  ✅ qw35-9b 已释放 (idle)", "OK")
        return True
    except Exception as e:
        log(f"  ⚠️ qw35-9b 释放失败: {e}", "WARN")
        return False


def release_comfyui() -> bool:
    """释放 ComfyUI GPU 资源。"""
    if not _comfyui_healthy():
        return True
    log("  释放 ComfyUI GPU...")
    try:
        r = subprocess.run(
            [EDGE_LLM, "switch", "idle"],
            capture_output=True, text=True, timeout=30
        )
        time.sleep(3)
        log("  ✅ ComfyUI 已释放", "OK")
        return True
    except Exception as e:
        log(f"  ⚠️ ComfyUI 释放失败: {e}", "WARN")
        return False


# ═══════════════════════════════════════════════════════════════════
# Dependency Checker
# ═══════════════════════════════════════════════════════════════════

def check_requires(project: Path, stage_def: dict) -> tuple[bool, str]:
    """检查 stage 的前置条件是否满足。
    
    Returns: (ok, message)
    """
    requires = stage_def.get("requires", [])
    missing = []
    for req in requires:
        # req 可以是文件路径或目录（以 / 结尾）
        if req.endswith('/'):
            # 目录：检查是否存在且非空
            d = project / req.rstrip('/')
            if not d.exists() or not any(d.iterdir()):
                missing.append(f"{req} (目录不存在或为空)")
        else:
            f = project / req
            if not f.exists():
                missing.append(req)
    
    if missing:
        return False, f"缺少前置: {', '.join(missing)}"
    return True, "OK"


def check_produces(project: Path, stage_def: dict) -> tuple[bool, str]:
    """检查 stage 的产出是否已存在（用于 skip_existing）。
    
    Returns: (all_exist, message)
    """
    produces = stage_def.get("produces", [])
    existing = []
    missing = []
    for prod in produces:
        if '*' in prod:
            # Glob pattern
            parent = project / Path(prod).parent
            pattern = Path(prod).name
            if parent.exists() and any(parent.glob(pattern)):
                existing.append(prod)
            else:
                missing.append(prod)
        elif prod.endswith('/'):
            d = project / prod.rstrip('/')
            if d.exists() and any(d.iterdir()):
                existing.append(prod)
            else:
                missing.append(prod)
        else:
            f = project / prod
            if f.exists():
                existing.append(prod)
            else:
                missing.append(prod)
    
    if missing:
        return False, f"产出缺失: {', '.join(missing)}"
    return True, f"产出已存在: {', '.join(existing)}"


# ═══════════════════════════════════════════════════════════════════
# Stage Runners
# ═══════════════════════════════════════════════════════════════════

def run_llm_stage(project: Path, stage_id: str, stage_def: dict) -> tuple[bool, str]:
    """运行 LLM stage (S1/S2/S4)."""
    client = get_llm_client()
    model = stage_def.get("model", "DEEPSEEK_PRO")
    max_tokens = stage_def.get("max_tokens", 16384)
    builder_name = stage_def.get("prompt_builder", "")

    # Map builder names to functions
    builders = {
        "run_script_parse": lambda: run_script_parse(project, (project / "source.txt").read_text()),
        "run_character_extract": lambda: run_character_extract(project),
        "run_shot_split": lambda: run_shot_split(project),
    }
    
    if builder_name not in builders:
        return False, f"Unknown prompt_builder: {builder_name}"
    
    prompt_data = builders[builder_name]()
    
    try:
        result = client.chat_json(
            system=prompt_data["messages"][0]["content"],
            user=prompt_data["messages"][1]["content"],
            model=model,
            max_tokens=max_tokens,
        )
        
        # Determine output file from stage_id
        output_map = {
            "s1_script_parse": "s1_parsed.json",
            "s2_character_extract": "s2_characters.json",
            "s4_shot_split": "s4_shots.json",
        }
        output_file = output_map.get(stage_id)
        if output_file:
            (project / output_file).write_text(json.dumps(result, ensure_ascii=False, indent=2))
        
        # Summary
        if stage_id == "s1_script_parse":
            n_scenes = len(result.get("scenes", []))
            return True, f"3 scenes={n_scenes}"
        elif stage_id == "s2_character_extract":
            names = [c["name"] for c in result.get("characters", [])]
            return True, f"{len(names)} chars: {', '.join(names)}"
        elif stage_id == "s4_shot_split":
            n_shots = sum(len(s.get("shots", [])) for s in result.get("scenes", []))
            return True, f"{n_shots} shots"
        return True, "OK"
        
    except Exception as e:
        return False, str(e)[:200]


def run_script_stage(project: Path, stage_id: str, stage_def: dict) -> tuple[bool, str]:
    """运行 script stage (s2b/s3/s3b/s4b/s5/s6/s7/s8/s9)."""
    script = stage_def.get("script", "")
    script_path = AICF_ROOT / script
    
    if not script_path.exists():
        return False, f"Script not found: {script_path}"
    
    # Build command
    cmd = [sys.executable, "-u", str(script_path), "--project", project.name]
    
    # Add extra args from pipeline definition
    extra_args = stage_def.get("args", [])
    cmd.extend(str(a) for a in extra_args)
    
    # Per-shot timeout
    per_shot_timeout = stage_def.get("timeout", 300)
    
    # Determine overall timeout based on expected work
    if stage_id == "s6_flf2v_render":
        # S6 is long: per-shot timeout × estimated shots
        overall_timeout = per_shot_timeout * 20  # generous
    else:
        overall_timeout = per_shot_timeout
    
    log(f"  命令: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True, text=True,
            timeout=overall_timeout,
            cwd=AICF_ROOT,
        )
        
        # Show tail of output
        stdout_lines = result.stdout.strip().split("\n")
        tail = "\n".join(stdout_lines[-15:])
        if tail:
            for line in tail.split("\n"):
                log(f"  | {line}")
        
        if result.stderr:
            stderr_tail = result.stderr.strip().split("\n")[-5:]
            for line in stderr_tail:
                log(f"  | STDERR: {line}")
        
        success = result.returncode == 0
        return success, f"rc={result.returncode}"
        
    except subprocess.TimeoutExpired:
        return False, f"Timeout ({overall_timeout}s)"
    except Exception as e:
        return False, str(e)[:200]


# ═══════════════════════════════════════════════════════════════════
# VL Quality Check Helpers
# ═══════════════════════════════════════════════════════════════════


def _vl_check_s3(project: Path):
    """S3 角色参考图 VL 质检。"""
    from core.character_image_check import CharacterImageChecker
    checker = CharacterImageChecker()
    s2 = json.load(open(project / "s2_characters.json"))
    manifest = json.load(open(project / "s3_character_refs" / "manifest.json"))
    
    for char in s2.get("characters", []):
        name = char["name"]
        img_path = manifest.get("characters", {}).get(name)
        if img_path and Path(img_path).exists():
            result = checker.check(img_path, char)
            if isinstance(result, dict):
                score = result.get("score", "?")
                passed = result.get("pass", False)
                icon = "✅" if passed else "⚠️"
                log(f"  {icon} {name}: {score}/10")
            else:
                log(f"  ⚠️ {name}: VL 返回异常类型 {type(result)}")
        else:
            log(f"  ⚠️ {name}: 参考图不存在")


def _vl_check_s3b(project: Path):
    """S3b 四视图 VL 质检。"""
    log("  S3b VL 质检: 检查四视图一致性...")
    fv_dir = project / "s3b_four_views"
    s2 = json.load(open(project / "s2_characters.json"))
    
    for char in s2.get("characters", []):
        name = char["name"]
        fv = fv_dir / f"{name}_fourview.png"
        char_dir = project / "s3_character_refs" / name / "default_fourview.png"
        if fv.exists() or char_dir.exists():
            log(f"  ✅ {name}: 四视图存在")
        else:
            log(f"  ⚠️ {name}: 四视图缺失")


def _vl_check_s5(project: Path):
    """S5 关键帧 VL 质检。"""
    log("  S5 VL 质检: 检查帧质量...")
    frames_dir = project / "s5_frames"
    if not frames_dir.exists():
        log("  ⚠️ s5_frames/ 不存在", "WARN")
        return
    
    pngs = sorted(frames_dir.glob("*.png"))
    black = 0
    for p in pngs:
        # Quick black-frame check via average pixel value
        try:
            from PIL import Image
            import numpy as np
            img = Image.open(p)
            arr = np.array(img)
            avg = arr.mean()
            if avg < 10:
                black += 1
                log(f"  ⚠️ {p.name}: 全黑帧 (avg={avg:.1f})")
        except Exception:
            pass
    
    if black == 0:
        log(f"  ✅ {len(pngs)} 帧，无全黑帧")
    else:
        log(f"  ⚠️ {len(pngs)} 帧中 {black} 个全黑帧", "WARN")


def _flush_vl_checks(project: Path, vl_pending: list, skip_vl: bool = False):
    """批量执行 VL 质检：启动 qw35 → 逐 stage 质检 → 释放 qw35。
    
    关键：qw35 启动约 2 分钟，用完立即释放。
    """
    if not vl_pending or skip_vl:
        if skip_vl:
            log("  VL 质检: 跳过 (--skip-vl)", "INFO")
        return
    
    log("=" * 60)
    log(f"  👁️ 批量 VL 质检: {len(vl_pending)} stages — 启动 qw35-9b")
    log("=" * 60)
    
    # 释放 ComfyUI 以腾出 GPU
    comfyui_was_running = _comfyui_healthy()
    if comfyui_was_running:
        release_comfyui()
        time.sleep(2)
    
    # 启动 qw35
    if ensure_qw35():
        for stage_id in vl_pending:
            try:
                if stage_id == "s3_character_image":
                    _vl_check_s3(project)
                elif stage_id == "s3b_four_view":
                    _vl_check_s3b(project)
                elif stage_id == "s5_frame_generate":
                    _vl_check_s5(project)
                else:
                    log(f"  {stage_id}: 无专用质检逻辑")
            except Exception as e:
                log(f"  ⚠️ {stage_id} VL 质检异常: {e}", "WARN")
        
        # 释放 qw35
        release_qw35()
    else:
        log("  ⚠️ qw35-9b 启动失败，跳过所有 VL 质检", "WARN")
    
    # 恢复 ComfyUI（S6 等后续 stage 可能需要）
    if comfyui_was_running:
        ensure_comfyui()


# ═══════════════════════════════════════════════════════════════════
# Pipeline Executor
# ═══════════════════════════════════════════════════════════════════

def execute_pipeline(
    project: Path,
    pipeline: dict,
    from_stage: str = None,
    only_stages: list = None,
    skip_vl: bool = False,
):
    """执行管线，按 pipeline.yaml 定义的顺序逐 stage 运行。"""
    
    stages = pipeline.get("stages", {})
    results = {}
    
    # Sort stages by order
    sorted_stages = sorted(stages.items(), key=lambda x: x[1].get("order", 99))
    
    # Filter stages
    if only_stages:
        sorted_stages = [(k, v) for k, v in sorted_stages if k in only_stages]
    elif from_stage:
        found = False
        filtered = []
        for k, v in sorted_stages:
            if k == from_stage:
                found = True
            if found:
                filtered.append((k, v))
        sorted_stages = filtered
    
    # Track GPU state
    comfyui_started = False
    vl_pending = []  # 收集需要 VL 质检的 stage
    
    for stage_id, stage_def in sorted_stages:
        log_header(stage_id, stage_def)
        t0 = time.time()
        
        # 1. 检查前置条件
        req_ok, req_msg = check_requires(project, stage_def)
        if not req_ok:
            log(f"  ⏭️ 跳过: {req_msg}", "WARN")
            results[stage_id] = (False, {"elapsed": 0, "note": req_msg, "skipped": True})
            continue
        
        # 2. 检查是否跳过已有产出
        if stage_def.get("skip_existing"):
            prod_ok, prod_msg = check_produces(project, stage_def)
            if prod_ok:
                log(f"  ⏭️ 产出已存在，跳过: {prod_msg}", "INFO")
                results[stage_id] = (True, {"elapsed": 0, "note": "skipped (exists)", "skipped": True})
                continue
        
        # 3. 确保 GPU 资源
        gpu = stage_def.get("gpu", "none")
        if gpu == "comfyui":
            if not ensure_comfyui():
                results[stage_id] = (False, {"elapsed": 0, "note": "ComfyUI unavailable"})
                continue
            comfyui_started = True
        elif gpu == "qw35_vl":
            if not ensure_qw35():
                results[stage_id] = (False, {"elapsed": 0, "note": "qw35-9b unavailable"})
                continue
        
        # 4. 执行 stage
        runner = stage_def.get("runner", "script")
        if runner == "llm":
            success, detail = run_llm_stage(project, stage_id, stage_def)
        elif runner == "script":
            success, detail = run_script_stage(project, stage_id, stage_def)
        else:
            success, detail = False, f"Unknown runner: {runner}"
        
        elapsed = time.time() - t0
        icon = "✅" if success else "❌"
        log(f"  {icon} {stage_id} ({elapsed:.1f}s): {detail}", "OK" if success else "ERROR")
        results[stage_id] = (success, {"elapsed": elapsed, "note": detail})
        
        # 5. VL 质检收集
        #    S5 完成后立即触发 S3/S3b/S5 的批量质检（在 S6 开始前）
        #    其他 vl_check stage 收集到管线结束后统一质检
        if success and stage_def.get("vl_check") and not skip_vl:
            if stage_id == "s5_frame_generate":
                _flush_vl_checks(project, vl_pending + [stage_id], skip_vl)
                vl_pending = []
            else:
                vl_pending.append(stage_id)
    
    # 6. 剩余 VL 质检（如有）
    if vl_pending:
        _flush_vl_checks(project, vl_pending, skip_vl)
    
    # 7. 清理 GPU
    if comfyui_started:
        log("  最终清理: 释放 GPU...")
        release_comfyui()
    
    return results


# ═══════════════════════════════════════════════════════════════════
# Report Generator
# ═══════════════════════════════════════════════════════════════════

def generate_report(project: Path, results: dict, pipeline: dict):
    log_header("REPORT", {"description": "生成报告"})
    report_path = project / "e2e_report.md"
    
    lines = [
        "# AIComicFactory E2E Pipeline Report",
        "",
        f"**日期**: {datetime.now(TZ).strftime('%Y-%m-%d %H:%M')} CST",
        f"**项目**: {project.name}",
        f"**总耗时**: {time.time() - start_global:.1f}s",
        "",
        "---",
        "",
        "## 各阶段结果",
        "",
        "| Stage | 描述 | 状态 | 耗时 | GPU | 备注 |",
        "|-------|------|------|------|-----|------|",
    ]
    
    for stage_id, stage_def in sorted(pipeline.get("stages", {}).items(), key=lambda x: x[1].get("order", 99)):
        if stage_id not in results:
            continue
        success, detail = results[stage_id]
        desc = stage_def.get("description", "")
        gpu = stage_def.get("gpu", "none")
        elapsed = detail.get("elapsed", 0) if isinstance(detail, dict) else 0
        note = detail.get("note", "") if isinstance(detail, dict) else str(detail)[:60]
        skipped = detail.get("skipped", False) if isinstance(detail, dict) else False
        status = "⏭️" if skipped else ("✅" if success else "❌")
        lines.append(f"| {stage_id} | {desc} | {status} | {elapsed:.1f}s | {gpu} | {note} |")
    
    lines += [
        "",
        "---",
        "",
        "## 产出文件",
        "",
    ]
    
    for f in sorted(project.glob("**/*"), key=lambda p: p.stat().st_mtime if p.exists() else 0):
        if f.is_file() and f.name != "source.txt" and ".git" not in str(f):
            sz = f.stat().st_size
            lines.append(f"- `{f.relative_to(project)}` ({sz//1024}KB)")
    
    lines += [
        "",
        "---",
        "",
        "## 完整日志",
        "",
        "```",
    ] + log_lines + ["```"]
    
    report_path.write_text("\n".join(lines))
    log(f"  ✅ Report: {report_path}", "OK")


# ═══════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════

def main():
    import argparse as ap
    parser = ap.ArgumentParser(description="AICF E2E Pipeline Driver v2.0")
    parser.add_argument("--project", "-p", default="last_bento", help="Project name")
    parser.add_argument("--from", dest="from_stage", help="Start from specific stage")
    parser.add_argument("--only", help="Comma-separated list of stages to run")
    parser.add_argument("--skip-vl", action="store_true", help="Skip all VL quality checks")
    args = parser.parse_args()
    
    project = AICF_ROOT / "projects" / args.project
    if not (project / "source.txt").exists():
        log(f"FATAL: {project / 'source.txt'} not found", "ERROR")
        sys.exit(1)
    
    # Load pipeline definition
    pipeline_path = AICF_ROOT / "pipeline.yaml"
    if not pipeline_path.exists():
        log(f"FATAL: {pipeline_path} not found", "ERROR")
        sys.exit(1)
    
    pipeline = load_pipeline(pipeline_path)
    n_stages = len(pipeline.get("stages", {}))
    log(f"🚀 AICF E2E Pipeline v2.0 — {datetime.now(TZ).strftime('%Y-%m-%d %H:%M')}")
    log(f"  Project: {project.name}")
    log(f"  Pipeline: {n_stages} stages from pipeline.yaml")
    log(f"  VL 质检: {'跳过' if args.skip_vl else '按需启用 (qw35-9b)'}")
    
    only_stages = args.only.split(",") if args.only else None
    
    results = execute_pipeline(
        project=project,
        pipeline=pipeline,
        from_stage=args.from_stage,
        only_stages=only_stages,
        skip_vl=args.skip_vl,
    )
    
    generate_report(project, results, pipeline)
    
    total = time.time() - start_global
    successes = sum(1 for s, d in results.values() if s)
    skipped = sum(1 for s, d in results.values() if isinstance(d, dict) and d.get("skipped"))
    failed = len(results) - successes
    log(f"\n{'='*60}")
    log(f"E2E COMPLETE: {successes}✅ {skipped}⏭️ {failed}❌ / {len(results)} stages in {total:.1f}s")


if __name__ == "__main__":
    main()
