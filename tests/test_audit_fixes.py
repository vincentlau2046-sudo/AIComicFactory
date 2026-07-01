#!/usr/bin/env python3
"""
tests/test_audit_fixes.py — 审计修复验证测试

验证所有审计发现的修复是否正确：
  A1: S6 双写修复
  A4: S3 年龄正则修复
  C1: S3 公共逻辑提取
  A2/A3: VL 质检闭环
  C3: VL 后端生命周期
  B3: 共享时间轴
  B1: Workflow 模板加载
  B2: S8/S9 字幕链路统一
  B4: S5 auto gen mode
  B5: S7 assets.json fallback
"""

import json
import sys
import os
import tempfile
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# ═══════════════════════════════════════════════════════════════════
# A4 + C1: demographics.py — 年龄正则 + 公共逻辑
# ═══════════════════════════════════════════════════════════════════

def test_demographics_age_regex():
    """A4: 年龄正则 '6[0-9]岁' 应该被 re.search 正确匹配."""
    from core.demographics import infer_age
    
    # 正则模式 "6[0-9]岁" 应该匹配
    label, tag = infer_age("这位65岁的老人")
    assert label == "老年人", f"Expected '老年人' for '65岁', got '{label}'"
    
    label, tag = infer_age("60岁退休工人")
    assert label == "老年人", f"Expected '老年人' for '60岁', got '{label}'"
    
    label, tag = infer_age("45岁的师傅")
    assert label == "中年人", f"Expected '中年人' for '45岁', got '{label}'"
    
    label, tag = infer_age("25岁大学生")
    assert label == "青年人", f"Expected '青年人' for '25岁', got '{label}'"
    
    # 无年龄信息
    label, tag = infer_age("普通角色")
    assert label == "成年人", f"Expected '成年人' for no age info, got '{label}'"
    
    print("✅ test_demographics_age_regex")


def test_demographics_gender():
    """C1: 性别推断应正确."""
    from core.demographics import infer_gender, infer_gender_tag
    
    assert infer_gender("她是一位老师", "female") == "female"
    assert infer_gender("他是一名工人", "male") == "male"
    assert infer_gender("她是一位老师") == "female"
    assert infer_gender("他是一名工人") == "male"
    assert infer_gender("普通角色") == "unknown"
    
    # gender_field 优先
    assert infer_gender("他", "female") == "female"
    
    print("✅ test_demographics_gender")


def test_demographics_gender_tag():
    """C1: Danbooru 性别+年龄标签."""
    from core.demographics import infer_gender_tag
    
    tag = infer_gender_tag("她是一位老师", "female", "old, elderly")
    assert "1girl" in tag and "old" in tag, f"Expected '1girl, old, elderly', got '{tag}'"
    
    tag = infer_gender_tag("他是25岁小伙", "male", "young")
    assert "1man" in tag and "young" in tag, f"Expected '1man, young', got '{tag}'"
    
    tag = infer_gender_tag("普通角色")
    assert tag in ("1girl", "1man"), f"Expected '1girl' or '1man', got '{tag}'"
    
    print("✅ test_demographics_gender_tag")


# ═══════════════════════════════════════════════════════════════════
# A1: S6 双写修复 — am.register 应传入 dest_name
# ═══════════════════════════════════════════════════════════════════

def test_s6_no_double_write():
    """A1: S6 脚本中 Path A (normal FLF2V) 不应有 shutil.copy2 到 s{sn:02d}.mp4 的双写."""
    s6_code = open(Path(__file__).parent.parent / "scripts" / "s6_flf2v_render.py").read()
    
    # 检查: Path A 中不应有 'shutil.copy2(str(candidates[0]), str(dest))' 模式
    # 旧的双写模式是: shutil.copy2 到 dest (s{sn:02d}.mp4) 后紧跟 am.register
    # 新的正确模式是: 只有 am.register 传入 dest_name
    
    # 检查 Path A 的 am.register 是否有 dest_name
    assert 'dest_name=f"s{sn:02d}.mp4"' in s6_code, \
        "S6 am.register missing dest_name parameter in Path A"
    
    # 检查 Path D 的 am.register 也有 dest_name
    # 两个路径的 am.register 都应有 dest_name
    dest_name_count = s6_code.count('dest_name=f"s{sn:02d}.mp4"')
    assert dest_name_count >= 2, \
        f"S6 should have dest_name in both Path A and Path D, found {dest_name_count}"
    
    # 检查: 不应有 'dest = videos_dir / f"s{sn:02d}.mp4"' 后跟 'shutil.copy2(str(candidates[0]), str(dest))'
    # 因为 am.register 会处理文件写入
    lines = s6_code.split('\n')
    for i, line in enumerate(lines):
        if 'shutil.copy2(str(candidates[0]), str(dest))' in line:
            # 这行不应在 videos_dir 的 dest 上下文中出现
            # 检查前后5行是否有 'videos_dir'
            context = '\n'.join(lines[max(0,i-5):i+5])
            assert 'videos_dir' not in context, \
                f"S6 has shutil.copy2 to videos_dir at line {i+1}"
    
    print("✅ test_s6_no_double_write")


# ═══════════════════════════════════════════════════════════════════
# C3: VL 后端生命周期
# ═══════════════════════════════════════════════════════════════════

def test_vl_backend():
    """C3: VLBackend 基本功能."""
    from core.vl_backend import VLBackend, get_vl_backend
    
    # 创建实例
    backend = VLBackend()
    assert backend.model == "vllm_qw35_gptq"
    assert backend.url == "http://localhost:8002/v1/chat/completions"
    
    # Singleton
    b1 = get_vl_backend()
    b2 = get_vl_backend()
    assert b1 is b2, "get_vl_backend should return singleton"
    
    # is_available 在无后端时应返回 False
    available = backend.is_available(force_check=True)
    assert isinstance(available, bool), "is_available should return bool"
    
    print("✅ test_vl_backend")


# ═══════════════════════════════════════════════════════════════════
# B3: 共享时间轴
# ═══════════════════════════════════════════════════════════════════

def test_timeline_basic():
    """B3: Timeline 基本构建."""
    from core.timeline import build_timeline
    
    s4_data = {
        "scenes": [
            {"shots": [
                {"shotNumber": 1, "duration": 5.0, "transitionOut": "dissolve"},
                {"shotNumber": 2, "duration": 3.0, "transitionOut": "cut"},
            ]},
            {"shots": [
                {"shotNumber": 3, "duration": 4.0, "transitionOut": "fade_out"},
            ]},
        ]
    }
    
    tl = build_timeline(s4_data, title_duration=3.0, credits_duration=4.0)
    
    assert len(tl.shots) == 3
    assert tl.shots[0].shot_number == 1
    assert tl.shots[0].start_time == 3.0  # after title card
    assert tl.shots[0].duration == 5.0
    assert tl.shots[1].start_time == 8.0  # 3.0 + 5.0
    assert tl.shots[2].start_time == 11.0  # 3.0 + 5.0 + 3.0
    assert tl.shots[2].end_time == 15.0
    assert tl.total_duration == 19.0  # 15.0 + 4.0 credits
    
    print("✅ test_timeline_basic")


def test_timeline_dialogue():
    """B3: 对话时间轴计算."""
    from core.timeline import build_timeline, calc_dialogue_timeline
    
    s4_data = {
        "scenes": [
            {"shots": [
                {"shotNumber": 1, "duration": 5.0, "transitionOut": "cut",
                 "dialogues": [
                     {"character": "A", "text": "你好", "startRatio": 0.2, "endRatio": 0.6},
                 ]},
                {"shotNumber": 2, "duration": 3.0, "transitionOut": "cut",
                 "dialogues": [
                     {"character": "B", "text": "再见"},
                 ]},
            ]},
        ]
    }
    
    tl = build_timeline(s4_data, title_duration=3.0)
    entries = calc_dialogue_timeline(s4_data, tl)
    
    assert len(entries) == 2
    
    # Shot 1: start_time=3.0, duration=5.0
    # Dialogue at startRatio=0.2 → 3.0 + 5.0*0.2 = 4.0
    assert entries[0]["start_s"] == 4.0, f"Expected 4.0, got {entries[0]['start_s']}"
    # endRatio=0.6 → 3.0 + 5.0*0.6 = 6.0
    assert entries[0]["end_s"] == 6.0, f"Expected 6.0, got {entries[0]['end_s']}"
    
    # Shot 2: auto-distribute (no startRatio/endRatio)
    assert entries[1]["shot"] == 2
    assert entries[1]["character"] == "B"
    
    print("✅ test_timeline_dialogue")


def test_timeline_srt_ass():
    """B3: SRT/ASS 字幕生成."""
    from core.timeline import generate_srt, generate_ass, fmt_srt_time, fmt_ass_time
    
    entries = [
        {"global_idx": 0, "shot": 1, "character": "A", "text": "你好",
         "start_s": 4.0, "end_s": 6.0, "startRatio": None, "endRatio": None},
        {"global_idx": 1, "shot": 2, "character": "B", "text": "再见",
         "start_s": 9.5, "end_s": 11.0, "startRatio": None, "endRatio": None},
    ]
    
    with tempfile.NamedTemporaryFile(suffix=".srt", delete=False, mode="w") as f:
        srt_path = Path(f.name)
    with tempfile.NamedTemporaryFile(suffix=".ass", delete=False, mode="w") as f:
        ass_path = Path(f.name)
    
    try:
        generate_srt(entries, srt_path)
        generate_ass(entries, ass_path)
        
        srt_content = srt_path.read_text()
        assert "1\n" in srt_content
        assert "A: 你好" in srt_content
        assert "B: 再见" in srt_content
        
        ass_content = ass_path.read_text()
        assert "[Script Info]" in ass_content
        assert "Dialogue:" in ass_content
    finally:
        srt_path.unlink(missing_ok=True)
        ass_path.unlink(missing_ok=True)
    
    # Time formatting
    assert fmt_srt_time(3661.5) == "01:01:01,500"
    assert fmt_ass_time(3661.5) == "1:01:01.50"
    
    print("✅ test_timeline_srt_ass")


# ═══════════════════════════════════════════════════════════════════
# B1: Workflow 模板加载
# ═══════════════════════════════════════════════════════════════════

def test_workflow_loader():
    """B1: Workflow 模板加载 + 参数注入."""
    from core.workflow_loader import load_workflow, inject_param, inject_params, list_templates
    
    # 列出模板
    templates = list_templates()
    assert len(templates) > 0, "No workflow templates found"
    print(f"  Templates: {templates}")
    
    # 加载 t2i_character_ref.json
    if "t2i_character_ref.json" in templates:
        wf = load_workflow("t2i_character_ref.json")
        assert isinstance(wf, dict)
        assert len(wf) > 0
    
    # inject_param
    wf = {"1": {"class_type": "KSampler", "inputs": {"seed": 42}}}
    inject_param(wf, "1", "seed", 123)
    assert wf["1"]["inputs"]["seed"] == 123
    
    # inject_params
    inject_params(wf, {"1": {"steps": 25, "cfg": 7.0}})
    assert wf["1"]["inputs"]["steps"] == 25
    assert wf["1"]["inputs"]["cfg"] == 7.0
    
    # FileNotFoundError for missing template
    try:
        load_workflow("nonexistent.json")
        assert False, "Should raise FileNotFoundError"
    except FileNotFoundError:
        pass
    
    print("✅ test_workflow_loader")


# ═══════════════════════════════════════════════════════════════════
# A2: S3 VL 质检闭环 — 重试逻辑
# ═══════════════════════════════════════════════════════════════════

def test_s3_vl_retry_logic():
    """A2: S3 脚本应包含 VL 重试逻辑."""
    s3_code = open(Path(__file__).parent.parent / "scripts" / "s3_character_image.py").read()
    
    # 应有 MAX_VL_RETRIES
    assert "MAX_VL_RETRIES" in s3_code, "S3 missing MAX_VL_RETRIES"
    
    # 应有重试循环
    assert "for attempt in range(args.max_vl_retries" in s3_code, \
        "S3 missing VL retry loop"
    
    # 应有 vl_available 预检
    assert "vl_available" in s3_code, "S3 missing VL availability check"
    
    # 应使用 demographics 模块
    assert "from core.demographics import" in s3_code, \
        "S3 not using demographics module"
    
    print("✅ test_s3_vl_retry_logic")


# ═══════════════════════════════════════════════════════════════════
# A3: S5 VL 质检闭环
# ═══════════════════════════════════════════════════════════════════

def test_s5_vl_backend_integration():
    """A3: S5 应使用 vl_backend 而非裸 try/except."""
    s5_code = open(Path(__file__).parent.parent / "scripts" / "s5_frame_generate.py").read()
    
    assert "from core.vl_backend import get_vl_backend" in s5_code, \
        "S5 not importing vl_backend"
    assert "vl.ensure_available" in s5_code, \
        "S5 not using vl_backend.ensure_available()"
    assert "add_error" in s5_code, \
        "S5 not recording quality check errors to state"
    
    print("✅ test_s5_vl_backend_integration")


# ═══════════════════════════════════════════════════════════════════
# B4: S5 auto gen mode
# ═══════════════════════════════════════════════════════════════════

def test_s5_auto_gen_mode():
    """B4: S5 应支持 --gen auto 模式."""
    s5_code = open(Path(__file__).parent.parent / "scripts" / "s5_frame_generate.py").read()
    
    assert '"auto"' in s5_code, "S5 missing 'auto' gen mode"
    assert "has_refs" in s5_code, "S5 missing auto-detect ref images logic"
    
    print("✅ test_s5_auto_gen_mode")


# ═══════════════════════════════════════════════════════════════════
# B5: S7 assets.json fallback
# ═══════════════════════════════════════════════════════════════════

def test_s7_assets_fallback():
    """B5: S7 应有 assets.json fallback 逻辑."""
    s7_code = open(Path(__file__).parent.parent / "scripts" / "s7_video_assemble.py").read()
    
    assert "am.get_active" in s7_code, "S7 missing assets.json fallback"
    
    print("✅ test_s7_assets_fallback")


# ═══════════════════════════════════════════════════════════════════
# State manager add_error
# ═══════════════════════════════════════════════════════════════════

def test_state_manager_add_error():
    """state_manager 应有 add_error 方法."""
    from core.state_manager import StateManager
    
    sm = StateManager()
    assert hasattr(sm, "add_error"), "StateManager missing add_error method"
    
    # Test with a temp project
    tmpdir = tempfile.mkdtemp()
    try:
        sm2 = StateManager(projects_root=tmpdir)
        project_dir = Path(tmpdir) / "test_project"
        project_dir.mkdir()
        state = {"project": "test_project", "stages": {}, "errors": []}
        with open(project_dir / "state.json", "w") as f:
            json.dump(state, f)
        
        result = sm2.add_error("test_project", "s5_frame_generate", "quality: shot 3 score=4")
        assert len(result["errors"]) == 1
        assert result["errors"][0]["severity"] == "warning"
    finally:
        shutil.rmtree(tmpdir)
    
    print("✅ test_state_manager_add_error")


# ═══════════════════════════════════════════════════════════════════
# Run all tests
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    tests = [
        test_demographics_age_regex,
        test_demographics_gender,
        test_demographics_gender_tag,
        test_s6_no_double_write,
        test_vl_backend,
        test_timeline_basic,
        test_timeline_dialogue,
        test_timeline_srt_ass,
        test_workflow_loader,
        test_s3_vl_retry_logic,
        test_s5_vl_backend_integration,
        test_s5_auto_gen_mode,
        test_s7_assets_fallback,
        test_state_manager_add_error,
    ]
    
    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"❌ {test.__name__}: {e}")
            failed += 1
    
    print(f"\n{'='*60}")
    print(f"Results: {passed} passed, {failed} failed, {passed+failed} total")
    if failed == 0:
        print("✅ ALL TESTS PASSED")
    else:
        print(f"❌ {failed} TESTS FAILED")
        sys.exit(1)
