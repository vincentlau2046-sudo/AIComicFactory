#!/usr/bin/env python3
"""
scripts/e2e_dry_run.py — End-to-End Dry Run Driver

从 source.txt 开始，逐 stage 执行，记录耗时、状态、问题。
输出: projects/{project}/e2e_report.md
"""

import json, sys, os, time, subprocess, traceback, urllib.request
from pathlib import Path
from datetime import datetime, timezone, timedelta

TZ = timezone(timedelta(hours=8))
PROJECT = Path(__file__).parent.parent / "projects" / "last_bento"
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.llm_client import LLMClient, get_llm_client
from core.prompt_runner import run_script_parse, run_character_extract, run_shot_split
from core.state_manager import get_state_manager

log_lines = []
start_global = time.time()

def log(msg: str, level: str = "INFO"):
    ts = datetime.now(TZ).strftime("%H:%M:%S")
    line = f"[{ts}] [{level}] {msg}"
    print(line)
    log_lines.append(line)

def log_header(stage: str):
    log("="*60)
    log(f"  STAGE: {stage}")
    log("="*60)

# ═══════════════════════════════════════════════════════════════════
# S1: Script Parse (LLM)
# ═══════════════════════════════════════════════════════════════════

def run_s1(project: Path):
    log_header("S1: script_parse (LLM)")
    t0 = time.time()
    issues = []

    source = (project / "source.txt").read_text()
    if not source.strip():
        log("ERROR: source.txt is empty", "ERROR")
        return False, "source.txt empty"

    log(f"  source.txt: {len(source)} chars")

    prompt_data = run_script_parse(project, source)
    client = get_llm_client()
    try:
        result = client.chat_json(
            system=prompt_data["messages"][0]["content"],
            user=prompt_data["messages"][1]["content"],
            model="DEEPSEEK_PRO",
        )
        (project / "s1_parsed.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
        elapsed = time.time() - t0
        log(f"  ✅ s1_parsed.json ({elapsed:.1f}s, {len(json.dumps(result))} chars)", "OK")
        return True, result
    except Exception as e:
        log(f"  ❌ S1 failed: {e}", "ERROR")
        issues.append(f"S1: {e}")
        return False, str(e)

# ═══════════════════════════════════════════════════════════════════
# S2: Character Extract (LLM)
# ═══════════════════════════════════════════════════════════════════

def run_s2(project: Path):
    log_header("S2: character_extract (LLM)")
    t0 = time.time()

    prompt_data = run_character_extract(project)
    client = get_llm_client()
    try:
        result = client.chat_json(
            system=prompt_data["messages"][0]["content"],
            user=prompt_data["messages"][1]["content"],
            model="DEEPSEEK_PRO",
        )
        (project / "s2_characters.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
        elapsed = time.time() - t0
        n_chars = len(result.get("characters", []))
        names = [c["name"] for c in result.get("characters", [])]
        log(f"  ✅ s2_characters.json ({elapsed:.1f}s, {n_chars} chars: {', '.join(names)})", "OK")
        return True, result
    except Exception as e:
        log(f"  ❌ S2 failed: {e}", "ERROR")
        return False, str(e)

# ═══════════════════════════════════════════════════════════════════
# S4: Shot Split (LLM) — note: S4 after S2, S3 is image gen
# ═══════════════════════════════════════════════════════════════════

def run_s4(project: Path):
    log_header("S4: shot_split (LLM)")
    t0 = time.time()

    prompt_data = run_shot_split(project)
    client = get_llm_client()
    model = prompt_data.get("model", "DEEPSEEK_PRO")
    try:
        result = client.chat_json(
            system=prompt_data["messages"][0]["content"],
            user=prompt_data["messages"][1]["content"],
            model=model,
        )
        (project / "s4_shots.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
        elapsed = time.time() - t0
        n_shots = 0
        for scene in result.get("scenes", []):
            n_shots += len(scene.get("shots", []))
        log(f"  ✅ s4_shots.json ({elapsed:.1f}s, {n_shots} shots)", "OK")
        return True, result
    except Exception as e:
        log(f"  ❌ S4 failed: {e}", "ERROR")
        return False, str(e)

# ═══════════════════════════════════════════════════════════════════
# S3: Character Image (ComfyUI)
# ═══════════════════════════════════════════════════════════════════

def run_s3(project: Path, style: str = "vivid"):
    log_header(f"S3: character_image ({style})")
    t0 = time.time()

    script = Path(__file__).parent.parent / "scripts" / "s3_character_image.py"
    result = subprocess.run(
        [sys.executable, "-u", str(script), "--project", project.name, "--style", style],
        capture_output=True, text=True, timeout=300,
        cwd=script.parent.parent,
    )
    log(f"  stdout:\n{result.stdout[-500:]}")
    if result.stderr:
        log(f"  stderr:\n{result.stderr[-500:]}")

    elapsed = time.time() - t0
    success = result.returncode == 0
    icon = "✅" if success else "❌"
    log(f"  {icon} S3 complete ({elapsed:.1f}s, rc={result.returncode})", "OK" if success else "ERROR")
    return success, result.stdout

# ═══════════════════════════════════════════════════════════════════
# S5: Frame Generate (ComfyUI)
# ═══════════════════════════════════════════════════════════════════

def run_s5(project: Path, style: str = "vivid"):
    log_header(f"S5: frame_generate ({style})")
    t0 = time.time()

    script = Path(__file__).parent.parent / "scripts" / "s5_frame_generate.py"
    result = subprocess.run(
        [sys.executable, "-u", str(script), "--project", project.name,
         "--gen", "t2i", "--frames", "both", "--style", style],
        capture_output=True, text=True, timeout=900,
        cwd=script.parent.parent,
    )
    # Only show last lines
    stdout_lines = result.stdout.strip().split("\n")
    tail = "\n".join(stdout_lines[-20:])
    log(f"  stdout (tail):\n{tail}")
    if result.stderr:
        log(f"  stderr:\n{result.stderr[-500:]}")

    elapsed = time.time() - t0
    success = result.returncode == 0
    n_files = len(list((project / "s5_frames").glob("*.png"))) if (project / "s5_frames").exists() else 0
    icon = "✅" if success else "❌"
    log(f"  {icon} S5 complete ({elapsed:.1f}s, rc={result.returncode}, {n_files} frames)", "OK" if success else "ERROR")
    return success, result.stdout

# ═══════════════════════════════════════════════════════════════════
# S6: FLF2V Video Render (ComfyUI)
# ═══════════════════════════════════════════════════════════════════

def run_s6(project: Path):
    log_header("S6: flf2v_render")
    t0 = time.time()

    # Check if s6 script exists and which version
    scripts_dir = Path(__file__).parent.parent / "scripts"
    script = scripts_dir / "s6_flf2v_render.py"
    if not script.exists():
        script = scripts_dir / "s6_video_assemble.py"

    result = subprocess.run(
        [sys.executable, "-u", str(script), "--project", project.name],
        capture_output=True, text=True, timeout=1200,
        cwd=script.parent.parent,
    )
    tail = "\n".join(result.stdout.strip().split("\n")[-15:])
    log(f"  stdout (tail):\n{tail}")
    if result.stderr:
        log(f"  stderr:\n{result.stderr[-500:]}")

    elapsed = time.time() - t0
    success = result.returncode == 0
    icon = "✅" if success else "❌"
    log(f"  {icon} S6 complete ({elapsed:.1f}s, rc={result.returncode})", "OK" if success else "ERROR")
    return success, result.stdout

# ═══════════════════════════════════════════════════════════════════
# S7: Video Assemble (FFmpeg)
# ═══════════════════════════════════════════════════════════════════

def run_s7(project: Path):
    log_header("S7: video_assemble")
    t0 = time.time()

    script = Path(__file__).parent.parent / "scripts" / "s7_video_assemble.py"
    result = subprocess.run(
        [sys.executable, "-u", str(script), "--project", project.name],
        capture_output=True, text=True, timeout=300,
        cwd=script.parent.parent,
    )
    tail = "\n".join(result.stdout.strip().split("\n")[-10:])
    log(f"  stdout (tail):\n{tail}")
    if result.stderr:
        log(f"  stderr:\n{result.stderr[-500:]}")

    elapsed = time.time() - t0
    success = result.returncode == 0
    icon = "✅" if success else "❌"
    output = project / "s7_assembled.mp4"
    sz = output.stat().st_size // 1024 if output.exists() else 0
    log(f"  {icon} S7 complete ({elapsed:.1f}s, output={sz}KB)", "OK" if success else "ERROR")
    return success, result.stdout

# ═══════════════════════════════════════════════════════════════════
# S8: Subtitles
# ═══════════════════════════════════════════════════════════════════

def run_s8(project: Path):
    log_header("S8: subtitles")
    t0 = time.time()

    script = Path(__file__).parent.parent / "scripts" / "s8_subtitles.py"
    result = subprocess.run(
        [sys.executable, "-u", str(script), "--project", project.name],
        capture_output=True, text=True, timeout=300,
        cwd=script.parent.parent,
    )
    tail = "\n".join(result.stdout.strip().split("\n")[-10:])
    log(f"  stdout (tail):\n{tail}")
    if result.stderr:
        log(f"  stderr:\n{result.stderr[-500:]}")

    elapsed = time.time() - t0
    success = result.returncode == 0
    icon = "✅" if success else "❌"
    log(f"  {icon} S8 complete ({elapsed:.1f}s, rc={result.returncode})", "OK" if success else "ERROR")
    return success, result.stdout

# ═══════════════════════════════════════════════════════════════════
# S9: TTS Audio
# ═══════════════════════════════════════════════════════════════════

def run_s9(project: Path):
    log_header("S9: tts_audio")
    t0 = time.time()

    script = Path(__file__).parent.parent / "scripts" / "s9_tts_audio.py"
    result = subprocess.run(
        [sys.executable, "-u", str(script), "--project", project.name],
        capture_output=True, text=True, timeout=600,
        cwd=script.parent.parent,
    )
    tail = "\n".join(result.stdout.strip().split("\n")[-10:])
    log(f"  stdout (tail):\n{tail}")
    if result.stderr:
        log(f"  stderr:\n{result.stderr[-500:]}")

    elapsed = time.time() - t0
    success = result.returncode == 0
    icon = "✅" if success else "❌"
    log(f"  {icon} S9 complete ({elapsed:.1f}s, rc={result.returncode})", "OK" if success else "ERROR")
    return success, result.stdout

# ═══════════════════════════════════════════════════════════════════
# qw35-9b Lifecycle (VL 质检 + S5 质量检查)
# ═══════════════════════════════════════════════════════════════════

EDGE_LLM = os.path.expanduser("~/bin/edge-llm")
QW35_HEALTH_URL = "http://localhost:8002/health"
QW35_PORT = 8002


def _check_qw35_health(retries: int = 30, interval: float = 2.0) -> bool:
    """Poll qw35-9b health endpoint until ready or timeout."""
    for i in range(retries):
        try:
            req = urllib.request.Request(QW35_HEALTH_URL)
            resp = urllib.request.urlopen(req, timeout=3)
            if resp.status == 200:
                return True
        except Exception:
            pass
        time.sleep(interval)
    return False


def start_qw35() -> bool:
    """Start qw35-9b via edge-llm. Returns True if ready, False if failed.
    
    Used for S3 VL quality check and S5 post-render quality checks.
    If qw35-9b is already running, skip start and return True.
    """
    # Quick health check first — already running?
    if _check_qw35_health(retries=1, interval=0.5):
        log("  qw35-9b already running (health OK)", "INFO")
        return True

    if not os.path.exists(EDGE_LLM):
        log(f"  ⚠️ edge-llm not found at {EDGE_LLM}, cannot start qw35-9b", "WARN")
        return False

    log("  Starting qw35-9b for VL quality checks...", "INFO")
    try:
        result = subprocess.run(
            [EDGE_LLM, "switch", "qwen35-9b"],
            capture_output=True, text=True, timeout=120,
        )
        log(f"  edge-llm switch: rc={result.returncode}", "INFO")
        if result.returncode != 0:
            log(f"  ⚠️ edge-llm switch failed:\n{result.stderr[-300:]}", "WARN")
            return False

        # Wait for vLLM to be ready
        log("  Waiting for qw35-9b health check...", "INFO")
        ok = _check_qw35_health(retries=45, interval=2.0)
        if ok:
            log("  ✅ qw35-9b ready", "OK")
        else:
            log("  ⚠️ qw35-9b health check timed out", "WARN")
        return ok
    except subprocess.TimeoutExpired:
        log("  ⚠️ edge-llm switch timed out", "WARN")
        return False
    except Exception as e:
        log(f"  ⚠️ qw35-9b start error: {e}", "WARN")
        return False


def stop_qw35() -> bool:
    """Stop qw35-9b to free GPU for S6 FLF2V rendering."""
    if not os.path.exists(EDGE_LLM):
        log(f"  ⚠️ edge-llm not found, skip qw35-9b stop", "WARN")
        return False

    log("  Releasing qw35-9b GPU resources...", "INFO")
    try:
        result = subprocess.run(
            [EDGE_LLM, "stop", "qwen35-9b"],
            capture_output=True, text=True, timeout=60,
        )
        log(f"  edge-llm stop: rc={result.returncode}", "INFO")
        if result.returncode != 0:
            log(f"  ⚠️ edge-llm stop failed:\n{result.stderr[-300:]}", "WARN")
            return False
        # Confirm released
        time.sleep(3)
        if not _check_qw35_health(retries=1, interval=0.5):
            log("  ✅ qw35-9b released", "OK")
            return True
        else:
            log("  ⚠️ qw35-9b still responding after stop", "WARN")
            return False
    except Exception as e:
        log(f"  ⚠️ qw35-9b stop error: {e}", "WARN")
        return False

# ═══════════════════════════════════════════════════════════════════
# Report Generator
# ═══════════════════════════════════════════════════════════════════

def generate_report(results: dict):
    log_header("GENERATING REPORT")
    report_path = PROJECT / "e2e_report.md"

    lines = [
        "# AIComicFactory E2E Dry Run Report",
        "",
        f"**日期**: {datetime.now(TZ).strftime('%Y-%m-%d %H:%M')} CST",
        f"**项目**: last_bento",
        f"**风格**: vivid (xuebiMIX, 默认)",
        f"**总耗时**: {time.time() - start_global:.1f}s",
        "",
        "---",
        "",
        "## 各阶段结果",
        "",
        "| Stage | 状态 | 耗时 | 备注 |",
        "|-------|------|------|------|",
    ]

    stage_names = {
        "s1": "S1 剧本解析 (LLM)",
        "s2": "S2 角色提取 (LLM)",
        "s4": "S4 分镜拆解 (LLM)",
        "s3": "S3 角色参考图 (ComfyUI)",
        "s5": "S5 关键帧生成 (ComfyUI)",
        "s6": "S6 FLF2V 视频渲染 (ComfyUI)",
        "s7": "S7 视频拼接 (FFmpeg)",
        "s8": "S8 字幕 (ASS)",
        "s9": "S9 TTS 语音 (Qwen3-TTS)",
    }

    for stage, (success, detail) in results.items():
        name = stage_names.get(stage, stage)
        status = "✅" if success else "❌"
        elapsed = detail.get("elapsed", 0) if isinstance(detail, dict) else 0
        note = detail.get("note", "") if isinstance(detail, dict) else str(detail)[:80]
        lines.append(f"| {name} | {status} | {elapsed:.1f}s | {note} |")

    lines += [
        "",
        "---",
        "",
        "## 产出文件",
        "",
    ]

    for f in sorted(PROJECT.glob("**/*"), key=lambda p: p.stat().st_mtime if p.exists() else 0):
        if f.is_file() and f.name != "source.txt" and ".git" not in str(f):
            sz = f.stat().st_size
            lines.append(f"- `{f.relative_to(PROJECT)}` ({sz//1024}KB)")

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
    log(f"🚀 AIComicFactory E2E Dry Run — {datetime.now(TZ).strftime('%Y-%m-%d %H:%M')}")
    log(f"  Project: {PROJECT}")
    log(f"  Style: vivid (xuebiMIX)")

    if not (PROJECT / "source.txt").exists():
        log("FATAL: source.txt not found", "ERROR")
        sys.exit(1)

    results = {}
    STYLE = "vivid"

    # === Text Stages (LLM) ===
    for stage, fn in [("s1", run_s1), ("s2", run_s2), ("s4", run_s4)]:
        t0 = time.time()
        success, detail = fn(PROJECT)
        elapsed = time.time() - t0
        note = ""
        if not success:
            log(f"  ⛔ Pipeline blocked at {stage}", "FATAL")
            note = str(detail)[:80]
        results[stage] = (success, {"elapsed": elapsed, "note": note})
        if not success:
            break

    # === Image/Video Stages (ComfyUI) ===
    # Check if s4 actually completed (not just default fallback)
    s4_result = results.get("s4")
    if s4_result is not None and s4_result[0]:
        # ── Start qw35-9b for VL quality checks (S3 + S5 post-check) ──
        qw35_ready = start_qw35()
        if not qw35_ready:
            log("  ⚠️ qw35-9b not available, VL checks will be skipped", "WARN")

        for stage, fn in [
            ("s3", lambda p: run_s3(p, STYLE)),
            ("s5", lambda p: run_s5(p, STYLE)),
        ]:
            t0 = time.time()
            try:
                success, detail = fn(PROJECT)
            except Exception as e:
                success = False
                detail = traceback.format_exc()[-200:]
                log(f"  ❌ {stage} exception: {e}", "ERROR")
            elapsed = time.time() - t0
            results[stage] = (success, {"elapsed": elapsed, "note": str(detail)[:80] if not success else ""})
            if not success:
                log(f"  ⚠️ {stage} failed, continuing pipeline", "WARN")

        # ── Release qw35-9b to free GPU for S6 FLF2V ──
        if qw35_ready:
            stop_qw35()

        for stage, fn in [
            ("s6", run_s6),
            ("s7", run_s7),
            ("s8", run_s8),
            ("s9", run_s9),
        ]:
            t0 = time.time()
            try:
                success, detail = fn(PROJECT)
            except Exception as e:
                success = False
                detail = traceback.format_exc()[-200:]
                log(f"  ❌ {stage} exception: {e}", "ERROR")
            elapsed = time.time() - t0
            results[stage] = (success, {"elapsed": elapsed, "note": str(detail)[:80] if not success else ""})
            if not success:
                log(f"  ⚠️ {stage} failed, continuing pipeline", "WARN")

    generate_report(results)
    total = time.time() - start_global
    successes = sum(1 for s, d in results.values() if s)
    log(f"\n{'='*60}")
    log(f"E2E COMPLETE: {successes}/{len(results)} stages passed in {total:.1f}s")


if __name__ == "__main__":
    main()