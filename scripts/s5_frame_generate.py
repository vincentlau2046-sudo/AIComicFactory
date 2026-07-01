#!/usr/bin/env python3
"""
scripts/s5_frame_generate.py — Stage 5: 关键帧生成 (v3.0)

v3.0 重写: qwen-image-edit ReferenceLatent 工作流
  - 删除 SDXL/IPAdapter 路径，统一使用 qwen-image-edit
  - VAEEncode 参考图 → ReferenceLatent → FluxKontextMultiReferenceLatentMethod
  - Lightning 4-step LoRA, er_sde/beta sampler
  - 产出 1024×1536 高质量帧

AICB 对齐:
  - P0-1: 标准化 prompt 构建 (build_full_prompt from prompts/defaults/)
  - P0-4: S2→S5 消费链 (colorPalette / performanceStyle / scene-level / relationships)

用法:
    python scripts/s5_frame_generate.py --project last_bento
    python scripts/s5_frame_generate.py --project last_bento --shot 1
    python scripts/s5_frame_generate.py --project last_bento --dry-run

前置条件:
    - ComfyUI 必须在无 --use-sage-attention 下运行
    - S3 T2I 参考图已存在 (s3_character_refs/{name}.png)
    - S3b qedit 四视角可选 (s3_character_refs/{name}_{view}.png)
"""

import json, sys, argparse, random, os, shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.stdout.reconfigure(line_buffering=True)

from prompts.defaults.frame_generate_first import build_full_prompt as build_first_prompt
from prompts.defaults.frame_generate_last import build_full_prompt as build_last_prompt
from core.comfyui_session import ComfyUISession, ComfyUIError
from core.state_manager import get_state_manager
from core.asset_manager import get_asset_manager
from core.workflow_loader import load_workflow, inject_params
from core.vl_backend import get_vl_backend

# ═══════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════

# qwen-image-edit 默认参数
QEDIT_STEPS = 4
QEDIT_CFG = 1.0
QEDIT_SAMPLER = "er_sde"
QEDIT_SCHEDULER = "beta"
QEDIT_SHIFT = 3.1
QEDIT_SEED = None  # None = random

# 参考图选取优先级: front > minus_angle > plus_angle > 单视图
REF_VIEW_PRIORITY = ["front", "minus_angle", "plus_angle", "back"]


# ═══════════════════════════════════════════════════════════════════
# Prompt builders (AICB 对齐)
# ═══════════════════════════════════════════════════════════════════

def _build_scene_description(scene: dict, color_palette: str = "") -> str:
    """从 scene 数据构建场景环境描述."""
    parts = []
    setting = scene.get("setting", "")
    mood = scene.get("mood", "")
    tod = scene.get("timeOfDay", "")
    if setting:
        parts.append(f"场景: {setting}")
    if tod:
        parts.append(f"时间: {tod}")
    if mood:
        parts.append(f"氛围: {mood}")
    if color_palette:
        parts.append(f"\n\nGLOBAL COLOR PALETTE (mandatory): {color_palette}. All frames must adhere to this color scheme.")
    return ", ".join(parts) if parts else "Unspecified setting"


def _build_character_descriptions(characters: list, shot_char_names: list) -> str:
    """构建角色描述文本. 视觉签名前置 → 最大化 primacy effect."""
    lines = []
    for cn in shot_char_names:
        for c in characters:
            if c["name"] == cn:
                hint = c.get("visualHint", "")
                desc = c.get("description", c.get("appearance", ""))
                anchors = c.get("visualAnchors", {})

                sig_parts = []
                for dim in ["face", "hair", "body", "clothing"]:
                    v = anchors.get(dim, "").strip()
                    if v and v != "无特殊":
                        sig_parts.append(v)
                visual_sig = "【" + " | ".join(sig_parts) + "】" if sig_parts else ""

                cp = c.get("colorPalette", "")
                if cp:
                    visual_sig += f" 配色:[{cp}]"

                line = f"{visual_sig} {cn}"
                if hint:
                    line += f"({hint})"
                line += f": {desc[:400]}"

                ps = c.get("performanceStyle", "")
                if ps:
                    line += f"\n  姿势约束: {ps[:200]}"

                lines.append(line)
                break
        else:
            lines.append(f"角色 {cn}: 无详细描述")
    return "\n\n".join(lines)


def _build_composition_suffix(shot: dict, chars_in_shot: list, characters: list,
                               color_palette: str = "") -> str:
    """构图指导 + 焦点 + 景深 + 角色身高 + 色板."""
    parts = []

    comp = shot.get("compositionGuide", "")
    if comp:
        parts.append(f"{comp.replace('_', ' ')} composition")

    focal = shot.get("focalPoint", "")
    if focal:
        parts.append(f"focus on {focal}")

    dof = shot.get("depthOfField", "")
    if dof == "shallow":
        parts.append("shallow depth of field, bokeh background")
    elif dof == "deep":
        parts.append("deep focus, everything sharp")

    if color_palette:
        parts.append(f"\nGLOBAL COLOR PALETTE (mandatory): {color_palette}. All frames must adhere to this color scheme.")

    if len(chars_in_shot) > 1:
        height_info = []
        for cn in chars_in_shot:
            for c in characters:
                if c["name"] == cn and c.get("heightCm"):
                    height_info.append((c["name"], c["heightCm"], c.get("bodyType", "average")))
                    break
        if height_info:
            height_info.sort(key=lambda x: x[1], reverse=True)
            height_text = ", ".join(
                f"{name}: {h}cm ({bt})" for name, h, bt in height_info
            )
            parts.append(f"Character heights: {height_text}. Maintain correct relative proportions")

    suffix = ", ".join([p for p in parts if not p.startswith('\n')])
    for p in parts:
        if p.startswith('\n'):
            suffix += p
    if suffix and not suffix.startswith('\n'):
        return ", " + suffix
    return suffix


# ═══════════════════════════════════════════════════════════════════
# Reference Image Management
# ═══════════════════════════════════════════════════════════════════

def _find_character_ref_image(char_name: str, project_dir: Path) -> Path | None:
    """查找角色参考图. 优先 front 四视角 > 单视图."""
    ref_dir = project_dir / "s3_character_refs"
    if not ref_dir.exists():
        return None

    # 优先四视角 front
    for view in REF_VIEW_PRIORITY:
        p = ref_dir / f"{char_name}_{view}.png"
        if p.exists():
            return p

    # Fallback: 单视图
    p = ref_dir / f"{char_name}.png"
    if p.exists():
        return p

    return None


def _upload_to_comfyui_input(image_path: Path, project: str, label: str) -> str:
    """Upload image to ComfyUI input dir, return filename."""
    comfyui_input = Path.home() / "ComfyUI" / "input"
    comfyui_input.mkdir(parents=True, exist_ok=True)
    input_name = f"aicf_{project}_{label}.png"
    shutil.copy2(str(image_path), str(comfyui_input / input_name))
    return input_name


# ═══════════════════════════════════════════════════════════════════
# Workflow Builder — qwen-image-edit ReferenceLatent
# ═══════════════════════════════════════════════════════════════════

def build_qedit_frame_workflow(
    ref_image: str,
    prompt: str,
    prefix: str,
    seed: int = None,
    steps: int = QEDIT_STEPS,
    cfg: float = QEDIT_CFG,
    ref_image2: str = None,   # supporting character reference
    ref_image3: str = None,   # previous frame or 3rd character reference
) -> dict:
    """Build qwen-image-edit ReferenceLatent frame generation workflow.
    
    Single-ref: templates/qwen_edit_frame.json (1 LoadImage)
    Multi-ref:  templates/qwen_edit_frame_multi.json (3 LoadImage)
    
    Architecture:
      UNETLoader → LoraLoaderModelOnly (Lightning 4-step) → ModelSamplingAuraFlow → CFGNorm
      CLIPLoader → TextEncodeQwenImageEditPlus (positive + negative)
      VAELoader → VAEEncode (ref image) → ReferenceLatent (×2) → FluxKontextMultiReferenceLatentMethod (×2)
      KSampler: er_sde / beta, steps=4, cfg=1
      latent_image = VAEEncoded reference (NOT EmptyQwenImageLayeredLatentImage)
    
    Multi-reference (ref_image2/ref_image3):
      image1 = main character ref  (node 41)
      image2 = supporting character ref  (node 42)
      image3 = previous frame / 3rd character  (node 43)
      TextEncodeQwenImageEditPlus handles image2/image3 internally.
    
    IMPORTANT: ComfyUI must NOT run with --use-sage-attention!
    """
    if seed is None:
        seed = random.randint(0, 2**32 - 1)

    # Use multi-ref template if image2 or image3 provided
    if ref_image2 or ref_image3:
        wf = load_workflow("qwen_edit_frame_multi.json")
    else:
        wf = load_workflow("qwen_edit_frame.json")

    injections = {
        "41": {"image": ref_image},
        "68": {"prompt": prompt},
        "69": {"prompt": ""},  # negative = empty
        "65": {"seed": seed, "steps": steps, "cfg": cfg},
        "60": {"filename_prefix": prefix},
    }

    # Multi-reference injections (only in multi template)
    if ref_image2:
        injections["42"] = {"image": ref_image2}
    if ref_image3:
        injections["43"] = {"image": ref_image3}

    return inject_params(wf, injections)


# ═══════════════════════════════════════════════════════════════════
# Frame Generation
# ═══════════════════════════════════════════════════════════════════

def generate_frame(
    sess: ComfyUISession,
    prompt: str,
    shot_num: int,
    frame_type: str,       # "first" or "last"
    project: str,
    output_dir: Path,
    ref_image_name: str,   # ComfyUI input filename
    seed: int = None,
    max_retries: int = 2,
    ref_image2_name: str = None,  # supporting character ComfyUI input filename
    ref_image3_name: str = None,  # previous frame / 3rd character ComfyUI input filename
) -> bool:
    """Generate a single frame using qwen-image-edit ReferenceLatent."""
    prefix = f"aicf_{project}_s{shot_num:02d}_{frame_type}"

    for attempt in range(max_retries + 1):
        s = seed if seed is not None else random.randint(0, 2**32 - 1)

        try:
            wf = build_qedit_frame_workflow(
                ref_image=ref_image_name,
                prompt=prompt,
                prefix=prefix,
                seed=s,
                ref_image2=ref_image2_name,
                ref_image3=ref_image3_name,
            )
            result = sess.run(wf, timeout=300)

            # Find output
            output_path = Path.home() / "ComfyUI" / "output"
            files = sorted(output_path.glob(f"{prefix}_*.png"),
                          key=lambda x: x.stat().st_mtime, reverse=True)

            if not files:
                print(f"    ⚠️ No output file found, retry {attempt+1}/{max_retries}")
                continue

            # Copy to project output dir
            dest = output_dir / f"s{shot_num:02d}_{frame_type}.png"
            shutil.copy2(str(files[0]), str(dest))

            # Quality check: black detection
            from PIL import Image as PILImage
            img = PILImage.open(str(dest))
            gray = img.convert('L')
            avg = sum(gray.getdata()) / (img.width * img.height)
            black_pct = sum(1 for p in gray.getdata() if p < 10) / (img.width * img.height) * 100

            if black_pct > 50:
                print(f"    ⚠️ Black output (avg={avg:.1f}, black={black_pct:.1f}%), retry {attempt+1}/{max_retries}")
                dest.unlink(missing_ok=True)
                continue

            # Register asset
            am = get_asset_manager()
            am.register(
                project=project, asset_type=f"{frame_type}_frame",
                shot_id=f"shot_{shot_num:03d}", source_path=files[0],
                relative_dir="s5_frames",
                dest_name=f"s{shot_num:02d}_{frame_type}.png",
                metadata={
                    "prompt": prompt[:200], "seed": s,
                    "mode": "qedit", "resolution": f"{img.width}x{img.height}",
                },
            )

            print(f"    ✅ s{shot_num:02d}_{frame_type}.png ({dest.stat().st_size//1024}KB, {img.width}×{img.height}, avg={avg:.0f})")
            return True

        except ComfyUIError as e:
            print(f"    ❌ ComfyUIError: {e}")
        except Exception as e:
            print(f"    ❌ Error: {e}")

    print(f"    ❌ s{shot_num:02d}_{frame_type} failed after {max_retries+1} attempts")
    return False


# ═══════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════

def main():
    p = argparse.ArgumentParser(description="S5: 关键帧生成 (qwen-image-edit ReferenceLatent)")
    p.add_argument("--project", "-P", required=True)
    p.add_argument("--shot", "-s", type=int, help="Generate specific shot only")
    p.add_argument("--frames", default="both", choices=["first", "last", "both"],
                   help="Which frames to generate")
    p.add_argument("--steps", type=int, default=QEDIT_STEPS)
    p.add_argument("--cfg", type=float, default=QEDIT_CFG)
    p.add_argument("--no-check", action="store_true", help="Skip post-S5 quality checks")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    pd = Path(__file__).parent.parent / "projects" / args.project
    s4 = json.load(open(pd / "s4_shots.json"))
    s2 = json.load(open(pd / "s2_characters.json"))

    project_color_palette = s2.get("colorPalette", "") or s4.get("colorPalette", "")
    chars = s2["characters"]

    # Flatten shots
    scenes = s4.get("scenes", [])
    shots = []
    if scenes:
        for sc in scenes:
            for sh in sc["shots"]:
                shots.append((sc, sh))
    else:
        for sh in s4.get("shots", []):
            shots.append(({}, sh))

    if args.shot:
        shots = [(sc, sh) for sc, sh in shots if sh["shotNumber"] == args.shot]

    # Load S4b keyframe assets if available (prefer S4b prompts over self-built)
    s4b_data = None
    s4b_path = pd / "s4b_keyframe_assets.json"
    if s4b_path.exists():
        s4b_data = json.load(open(s4b_path))
        print(f"  📋 Using S4b keyframe assets ({len(s4b_data.get('shots', []))} shots)")

    # Dry run
    if args.dry_run:
        for sc, sh in shots:
            n = sh["shotNumber"]
            chars_in = sh.get("characters", [])
            scene_desc = _build_scene_description(sc, color_palette=project_color_palette)
            char_desc = _build_character_descriptions(chars, chars_in)
            comp_suffix = _build_composition_suffix(sh, chars_in, chars, project_color_palette)

            fp_first = build_first_prompt(
                scene_description=scene_desc,
                start_frame_desc=sh.get("prompt", sh.get("description", "")),
                character_descriptions=char_desc,
            )
            fp_last = build_last_prompt(
                scene_description=scene_desc,
                end_frame_desc=sh.get("prompt", sh.get("description", "")),
                character_descriptions=char_desc,
            )
            # Find ref images
            refs = {}
            for cn in chars_in:
                ref = _find_character_ref_image(cn, pd)
                refs[cn] = ref.name if ref else "NONE"
            print(f"Shot {n:2d} ({','.join(chars_in)}) -> first={len(fp_first)}c last={len(fp_last)}c refs={refs}")
        return

    # Setup
    sm = get_state_manager()
    total = len(shots) * (2 if args.frames == "both" else 1)
    sm.mark_running(args.project, "s5_frame_generate", remaining=total)

    out = pd / "s5_frames"
    out.mkdir(parents=True, exist_ok=True)

    sess = ComfyUISession()
    total_ok = 0
    prev_last = ""  # 前一个 shot 的尾帧路径

    for i, (sc, sh) in enumerate(shots):
        n = sh["shotNumber"]
        chars_in = sh.get("characters", [])
        scene_desc = _build_scene_description(sc, color_palette=project_color_palette)
        char_desc = _build_character_descriptions(chars, chars_in)
        comp_suffix = _build_composition_suffix(sh, chars_in, chars, project_color_palette)

        # Check S4b for pre-built prompts
        s4b_shot = None
        if s4b_data:
            for s in s4b_data.get("shots", []):
                if s["shotNumber"] == n:
                    s4b_shot = s
                    break

        # 查找所有角色参考图 (最多3个: D3)
        ref_images = []  # list of (char_name, Path)
        for cn in chars_in:
            ref = _find_character_ref_image(cn, pd)
            if ref:
                ref_images.append((cn, ref))

        if not ref_images:
            print(f"\n[{i+1}/{len(shots)}] Shot {n} | ❌ No character ref images found for {chars_in}")
            continue

        # 上传所有参考图到 ComfyUI input
        ref_input_names = []
        for cn, ref_path in ref_images[:3]:  # max 3 (D3)
            input_name = _upload_to_comfyui_input(ref_path, args.project, f"ref_{cn}")
            ref_input_names.append(input_name)

        # image1 = 主角色参考, image2 = 配角参考 (如有)
        main_ref = ref_input_names[0]
        ref2 = ref_input_names[1] if len(ref_input_names) > 1 else None

        # 如果有前shot尾帧，也上传作为额外参考
        prev_input_name = None
        if prev_last and Path(prev_last).exists():
            prev_input_name = _upload_to_comfyui_input(
                Path(prev_last), args.project, f"prev_s{n:02d}"
            )

        ref_names_display = [ref_images[j][0] for j in range(len(ref_input_names))]
        print(f"\n[{i+1}/{len(shots)}] Shot {n} | chars={chars_in} | refs={ref_names_display} | prev={'yes' if prev_input_name else 'no'}")

        if args.frames in ("first", "both"):
            # Use S4b pre-built prompt if available, otherwise build on-the-fly
            if s4b_shot and s4b_shot.get("startFrame", {}).get("prompt"):
                fp = s4b_shot["startFrame"]["prompt"]
                if comp_suffix:
                    fp += comp_suffix
                print(f"  First (S4b, {len(fp)}c): {fp[:80]}...")
            else:
                fp = build_first_prompt(
                    scene_description=scene_desc,
                    start_frame_desc=sh.get("prompt", sh.get("description", "")),
                    character_descriptions=char_desc,
                    previous_last_frame=prev_last if prev_last else "",
                )
                if comp_suffix:
                    fp += comp_suffix
                print(f"  First ({len(fp)}c): {fp[:80]}...")

            # image3 = 前帧连续性参考 (D4: prev frame at image3)
            ref3_for_first = prev_input_name if prev_input_name else None

            ok = generate_frame(
                sess, fp, n, "first", args.project, out,
                ref_image_name=main_ref,
                ref_image2_name=ref2,
                ref_image3_name=ref3_for_first,
            )
            if ok:
                total_ok += 1

        if args.frames in ("last", "both"):
            first_frame_path = str(out / f"s{n:02d}_first.png")

            # Use S4b pre-built prompt if available, otherwise build on-the-fly
            if s4b_shot and s4b_shot.get("endFrame", {}).get("prompt"):
                fl = s4b_shot["endFrame"]["prompt"]
                if comp_suffix:
                    fl += comp_suffix
                print(f"  Last  (S4b, {len(fl)}c): {fl[:80]}...")
            else:
                fl = build_last_prompt(
                    scene_description=scene_desc,
                    end_frame_desc=sh.get("prompt", sh.get("description", "")),
                    character_descriptions=char_desc,
                    first_frame_path=first_frame_path,
                )
                if comp_suffix:
                    fl += comp_suffix
                print(f"  Last  ({len(fl)}c): {fl[:80]}...")

            # 尾帧参考：首帧优先（同一 shot 内连续性），角色参考作为 image1
            last_ref = main_ref
            if Path(first_frame_path).exists():
                last_ref_input = _upload_to_comfyui_input(
                    Path(first_frame_path), args.project, f"first_s{n:02d}"
                )
                # 用首帧作为 VAEEncode 输入（latent_image），角色参考作为 image1
                last_ref = last_ref_input

            ok = generate_frame(
                sess, fl, n, "last", args.project, out,
                ref_image_name=last_ref,
                ref_image2_name=ref2,
                ref_image3_name=None,  # no prev frame needed for last frame
            )
            if ok:
                total_ok += 1
                prev_last = str(out / f"s{n:02d}_last.png")

    sm.mark_completed(args.project, "s5_frame_generate", generated=f"{total_ok}/{total}")
    print(f"\n{'='*60}")
    print(f"S5 Complete: {total_ok}/{total} frames (qedit ReferenceLatent)")

    # ── Post-S5 quality checks ──
    if total_ok > 0 and not args.dry_run and not args.no_check:
        vl = get_vl_backend()
        vl_ok = vl.ensure_available(auto_start=True)
        if vl_ok:
            print(f"\n{'='*60}")
            print("Running post-S5 quality checks...")
            print(f"{'='*60}")
            try:
                from core.continuity_check import ContinuityChecker
                cc = ContinuityChecker()
                c_report = cc.check_project(args.project, threshold=70)
                print(cc.generate_summary(c_report))
                if c_report.get("issues"):
                    print(f"  ⚠️ {len(c_report['issues'])} 对相邻帧连续性低于阈值")
                    for iss in c_report["issues"]:
                        sm.add_error(args.project, "s5_frame_generate",
                                     f"continuity: shot {iss.get('shot_a')}->{iss.get('shot_b')} score={iss.get('overall_score', '?')}")
            except Exception as e:
                print(f"  ⚠️ Continuity check failed: {e}")
            try:
                from core.video_quality_check import VideoQualityChecker
                vc = VideoQualityChecker()
                v_report = vc.check_project(args.project, sample_every=2)
                print(vc.generate_summary(v_report))
                if v_report.get("issues"):
                    print(f"  ⚠️ {len(v_report['issues'])} 帧质量低于阈值")
                    for iss in v_report["issues"]:
                        sm.add_error(args.project, "s5_frame_generate",
                                     f"quality: shot {iss.get('shot', '?')} overall={iss.get('overall', '?')}")
            except Exception as e:
                print(f"  ⚠️ Quality check failed: {e}")
        else:
            print(f"\n  ⚠️ VL 后端不可用，跳过质检")
            print(f"  → 运行 'edge-llm switch qwen35-9b' 后重新执行 S5 可触发质检")


if __name__ == "__main__":
    main()
