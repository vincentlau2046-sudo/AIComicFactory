#!/usr/bin/env python3
"""
scripts/s5_frame_generate.py — Stage 5: 关键帧生成 (v3.0)

v3.0 重写: qwen-image-edit ReferenceLatent 工作流
  - 删除 SDXL/IPAdapter 路径，统一使用 qwen-image-edit
  - VAEEncode 参考图 → ReferenceLatent → FluxKontextMultiReferenceLatentMethod
  - Lightning 4-step LoRA, er_sde/beta sampler
  - 产出 1280×720 横版帧（与 S6 FLF2V 对齐）

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

# qwen-image-edit 默认参数 (aligned with official Vantage workflow)
QEDIT_STEPS = 4
QEDIT_CFG = 1.0
QEDIT_SAMPLER = "euler"
QEDIT_SCHEDULER = "simple"
QEDIT_SHIFT = 3.1
QEDIT_SEED = None  # None = random

# 参考图选取优先级: front > minus_angle > plus_angle > 单视图
REF_VIEW_PRIORITY = ["front", "minus_angle", "plus_angle", "back"]


def _get_frame_desc(shot: dict, frame: str, fallback_field: str = "prompt") -> str:
    """Get frame description with fallback chain.
    
    Priority: startFrameDesc/endFrameDesc → prompt → description → ""
    """
    key = "startFrameDesc" if frame == "start" else "endFrameDesc"
    return shot.get(key, shot.get(fallback_field, shot.get("description", "")))


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

def _find_character_ref_image(char_name: str, project_dir: Path, costume_id: str = "default") -> Path | None:
    """查找角色参考图.
    
    优先级: S3b 四视图网格 > S3b 四视图分镜 > S3 单视图.
    S3b four-view grid provides more comprehensive angle info for consistency.
    
    支持新目录: s3_character_refs/{name}/{costume_id}.png / {costume_id}_{view}.png
    兼容旧目录: s3_character_refs/{name}.png / s3b_four_views/{name}_fourview.png
    """
    s3b_dir = project_dir / "s3b_four_views"
    ref_dir = project_dir / "s3_character_refs"
    char_dir = ref_dir / char_name  # new per-character directory

    # 1. Per-character directory with costume_id
    if char_dir.exists():
        # S3b four-view grid (best) — shows all angles in one image
        p = char_dir / f"{costume_id}_fourview.png"
        if p.exists():
            return p
        # Single costume ref
        p = char_dir / f"{costume_id}.png"
        if p.exists():
            return p
        # View-specific refs
        for view in REF_VIEW_PRIORITY:
            p = char_dir / f"{costume_id}_{view}.png"
            if p.exists():
                return p
        # Fallback to default.png in char dir
        p = char_dir / "default.png"
        if p.exists():
            return p

    # 2. S3b four-view grid (legacy flat directory)
    if s3b_dir.exists():
        p = s3b_dir / f"{char_name}_fourview.png"
        if p.exists():
            return p

    # 3. S3b split views (legacy flat directory)
    if ref_dir.exists():
        for view in REF_VIEW_PRIORITY:
            p = ref_dir / f"{char_name}_{view}.png"
            if p.exists():
                return p

    # 4. S3 single front view (legacy flat directory)
    if ref_dir.exists():
        p = ref_dir / f"{char_name}.png"
        if p.exists():
            return p

    return None


def _find_character_multi_view_refs(char_name: str, project_dir: Path, costume_id: str = "default") -> dict:
    """查找角色多视角参考图, 返回 {view_name: Path}.
    
    Returns at most: front, plus_angle, minus_angle, fourview.
    Used for qwen-image-edit multi-ref: image1=front, image2=plus_angle, image3=minus_angle.
    
    支持新目录: s3_character_refs/{name}/{costume_id}_{view}.png
    兼容旧目录: s3_character_refs/{name}_{view}.png / s3b_four_views/{name}_fourview.png
    """
    ref_dir = project_dir / "s3_character_refs"
    s3b_dir = project_dir / "s3b_four_views"
    char_dir = ref_dir / char_name
    result = {}

    # 1. Per-character dir: costume-specific views (new)
    if char_dir.exists():
        for view in ["front", "plus_angle", "minus_angle"]:
            p = char_dir / f"{costume_id}_{view}.png"
            if p.exists():
                result[view] = p
            else:
                p = char_dir / f"{view}.png"
                if p.exists():
                    result[view] = p

        # Four-view grid
        for pattern in [f"{costume_id}_*fourview", f"{costume_id}_fourview", "fourview"]:
            files = sorted(char_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
            if files:
                result["fourview"] = files[0]
                break

    # 2. Old flat structure (backward compat)
    if not result and ref_dir.exists():
        for view in ["front", "plus_angle", "minus_angle"]:
            p = ref_dir / f"{char_name}_{view}.png"
            if p.exists():
                result[view] = p

    # 3. S3b four-view grid (backward compat)
    if "front" not in result and "fourview" not in result and s3b_dir.exists():
        p = s3b_dir / f"{char_name}_fourview.png"
        if p.exists():
            result["front"] = p

    # 4. Fallback: S3 single view as front
    if "front" not in result and "fourview" not in result:
        if char_dir.exists():
            p = char_dir / f"{costume_id}.png"
            if p.exists():
                result["front"] = p
            p = char_dir / "default.png"
            if p.exists():
                result["front"] = p
        if ref_dir.exists():
            p = ref_dir / f"{char_name}.png"
            if p.exists():
                result["front"] = p

    return result


def _resolve_shot_costumes(shot: dict, characters: list, ref_dir: Path) -> dict:
    """解析每 shot 每角色的活动服饰。
    
    返回 { char_name: { "id": str, "description": str, "ref_image": Path|None } }
    
    解析链:
      1. shot.costumeOverrides[char_name] → 显式覆盖
      2. char.defaultCostume → 默认服饰
      3. fallback: visualAnchors.clothing / description
    """
    overrides = (shot.get("costumeOverrides") or {}).copy()
    result = {}
    
    for c in characters:
        name = c["name"]
        costumes = c.get("costumes", [])
        default_id = c.get("defaultCostume", "default")
        
        active_id = overrides.get(name, default_id)
        
        # Find costume description
        desc = ""
        for cos in costumes:
            if cos.get("id") == active_id:
                desc = cos.get("description", "")
                break
        if not desc:
            anchors = c.get("visualAnchors", {})
            desc = anchors.get("clothing", "")
        
        # Find reference image for this costume
        ref_img = _find_character_ref_image(name, ref_dir.parent, active_id)
        
        result[name] = {"id": active_id, "description": desc, "ref_image": ref_img}
    
    return result


def _build_costume_consistency(shot_costumes: dict) -> str:
    """构建 costume_consistency slot 内容。
    
    返回硬约束文本，强制服装精确匹配。
    无服饰信息时返回空字符串。
    """
    if not shot_costumes:
        return ""
    
    lines = ["=== 服饰硬约束（不可妥协）==="]
    has_any = False
    for name, info in shot_costumes.items():
        desc = info["description"].strip()
        if desc:
            lines.append(f"- {name} 必须穿: {desc}")
            has_any
    
    if not has_any:
        return ""
    
    lines.append("")
    lines.append("此为本镜头各角色必须穿着的精确服装。生成的画面中所有角色的服装必须与此描述完全一致，")
    lines.append("颜色、材质、款式、配饰不得有任何改动。")
    return "\n".join(lines)


def _upload_to_comfyui_input(image_path: Path, project: str, label: str) -> str:
    """Upload image to ComfyUI input dir, return filename."""
    comfyui_input = Path.home() / "ComfyUI" / "input"
    comfyui_input.mkdir(parents=True, exist_ok=True)
    input_name = f"aicf_{project}_{label}.png"
    shutil.copy2(str(image_path), str(comfyui_input / input_name))
    return input_name


def _create_padded_ref(image_path: Path, target_w: int = 1280, target_h: int = 720,
                       pad_color: tuple = None) -> Path:
    """Fit+pad: 等比缩放到目标高度，左右边缘色填充到目标宽高。
    
    Example: 1024×1536 → 480×720 (fit height) → 1280×720 (pad sides).
    No distortion, no cropping. Auto-detects background color from source edges.
    """
    from PIL import Image as PILImage
    img = PILImage.open(str(image_path))
    
    # 等比缩放: fit to target height
    scale = target_h / img.height
    new_w = int(img.width * scale)
    resized = img.resize((new_w, target_h), PILImage.LANCZOS)
    
    # 自动检测背景色: 采样源图四周边缘像素，取众数
    if pad_color is None:
        edge_pixels = []
        w, h = img.width, img.height
        # 采样四边 + 四角 (各取 10% 宽/高区域的像素)
        sample_w = max(1, w // 10)
        sample_h = max(1, h // 10)
        for x in range(0, w, 5):
            for y in list(range(0, sample_h)) + list(range(h - sample_h, h)):
                edge_pixels.append(img.getpixel((x, y)))
        for y in range(0, h, 5):
            for x in list(range(0, sample_w)) + list(range(w - sample_w, w)):
                edge_pixels.append(img.getpixel((x, y)))
        # 取 RGB 均值作为背景色
        if edge_pixels:
            r = int(sum(p[0] for p in edge_pixels) / len(edge_pixels))
            g = int(sum(p[1] for p in edge_pixels) / len(edge_pixels))
            b = int(sum(p[2] for p in edge_pixels) / len(edge_pixels))
            pad_color = (r, g, b)
        else:
            pad_color = (255, 255, 255)
    
    # 填充
    canvas = PILImage.new("RGB", (target_w, target_h), pad_color)
    x_offset = (target_w - new_w) // 2
    canvas.paste(resized, (x_offset, 0))
    
    # 保存到同一目录，文件名加 _padded 后缀
    padded_path = image_path.parent / f"{image_path.stem}_padded{image_path.suffix}"
    canvas.save(str(padded_path))
    return padded_path


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
    ref_image_padded: str = None,  # fit+pad version for VAEEncode (no distortion)
) -> dict:
    """Build qwen-image-edit frame generation workflow.
    
    v2.1: Resolution alignment via fit+pad (no distortion).
    
    Architecture (matching official Vantage):
      UNETLoader → LoraLoaderModelOnly (Lightning 4-step) → ModelSamplingAuraFlow → CFGNorm
      CLIPLoader → TextEncodeQwenImageEditPlus (positive + negative, both with images)
      LoadImage(original) → TextEncodeQwenImageEditPlus (image1/2/3, full detail)
      LoadImage(padded) → VAEEncode → KSampler latent_image (output resolution)
      KSampler: euler / simple, steps=4, cfg=1
    
    Resolution chain (no distortion):
      S3 ref (1024×1536) → fit+pad (480×720 centered in 1280×720 white) → VAEEncode
      TextEncode gets original 1024×1536 for character detail
    
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
        "81": {"image": ref_image_padded or ref_image},  # padded ref → VAEEncode
        "68": {"prompt": prompt},
        "69": {"prompt": ""},  # negative = empty prompt
        "65": {"seed": seed, "steps": steps, "cfg": cfg},
        "60": {"filename_prefix": prefix},
    }

    # Multi-reference injections (only in multi template)
    # IMPORTANT: When using multi-ref template, ALL LoadImage nodes must have valid
    # filenames in ComfyUI input dir. If image2/image3 not provided, duplicate image1
    # as fallback — the model will simply give it less weight.
    if ref_image2:
        injections["42"] = {"image": ref_image2}
    else:
        injections["42"] = {"image": ref_image}  # fallback: same as image1
    if ref_image3:
        injections["43"] = {"image": ref_image3}
    else:
        injections["43"] = {"image": ref_image}  # fallback: same as image1

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
    ref_padded_name: str = None,  # fit+pad version for VAEEncode (no distortion)
) -> bool:
    """Generate a single frame using qwen-image-edit."""
    prefix = f"aicf_{project}_s{shot_num:02d}_{frame_type}"

    for attempt in range(max_retries + 1):
        s = seed if seed is not None else random.randint(0, 2**32 - 1)

        try:
            wf = build_qedit_frame_workflow(
                ref_image=ref_image_name,
                ref_image_padded=ref_padded_name,
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
# Flux Dev T2I — Path B for shots without character refs
# ═══════════════════════════════════════════════════════════════════

def build_flux_t2i_workflow(prompt: str, width: int = 1280, height: int = 720,
                             seed: int = None) -> dict:
    """Build Flux Dev fp8 T2I workflow for pure scene/object shots.
    
    Same architecture as S3 character generation but 1280×720 landscape.
    Aligned with official Flux.1 Dev Blueprint:
    - cfg=1.0, euler/simple, 20 steps
    - ConditioningZeroOut for negative
    - EmptySD3LatentImage
    """
    if seed is None:
        seed = random.randint(0, 2**32 - 1)

    return {
        "10": {"class_type": "UNETLoader", "inputs": {
            "unet_name": "flux1-dev-fp8.safetensors", "weight_dtype": "default"}},
        "11": {"class_type": "DualCLIPLoader", "inputs": {
            "clip_name1": "clip_l.safetensors",
            "clip_name2": "t5xxl_fp8_e4m3fn_scaled.safetensors",
            "type": "flux"}},
        "12": {"class_type": "VAELoader", "inputs": {
            "vae_name": "ae.safetensors"}},
        "13": {"class_type": "EmptySD3LatentImage", "inputs": {
            "width": width, "height": height, "batch_size": 1}},
        "14": {"class_type": "CLIPTextEncode", "inputs": {
            "text": prompt, "clip": ["11", 0]}},
        "15": {"class_type": "ConditioningZeroOut", "inputs": {
            "conditioning": ["14", 0]}},
        "16": {"class_type": "KSampler", "inputs": {
            "seed": seed, "steps": 20, "cfg": 1.0,
            "sampler_name": "euler", "scheduler": "simple",
            "denoise": 1.0, "model": ["10", 0],
            "positive": ["14", 0], "negative": ["15", 0],
            "latent_image": ["13", 0]}},
        "17": {"class_type": "VAEDecode", "inputs": {
            "samples": ["16", 0], "vae": ["12", 0]}},
        "18": {"class_type": "SaveImage", "inputs": {
            "filename_prefix": "aicf_t2i", "images": ["17", 0]}},
    }


def generate_frame_t2i(
    sess: ComfyUISession,
    prompt: str,
    shot_num: int,
    frame_type: str,  # "first" or "last"
    project: str,
    output_dir: Path,
    seed: int = None,
    max_retries: int = 2,
) -> bool:
    """Generate a frame via Flux Dev T2I (no character ref needed)."""
    prefix = f"aicf_{project}_t2i_s{shot_num:02d}_{frame_type}"

    for attempt in range(max_retries + 1):
        s = seed if seed is not None else random.randint(0, 2**32 - 1)

        try:
            wf = build_flux_t2i_workflow(prompt, seed=s)
            wf["18"]["inputs"]["filename_prefix"] = prefix
            result = sess.run(wf, timeout=300)

            output_path = Path.home() / "ComfyUI" / "output"
            files = sorted(output_path.glob(f"{prefix}_*.png"),
                          key=lambda x: x.stat().st_mtime, reverse=True)

            if not files:
                print(f"    ⚠️ No T2I output, retry {attempt+1}/{max_retries}")
                continue

            dest = output_dir / f"s{shot_num:02d}_{frame_type}.png"
            shutil.copy2(str(files[0]), str(dest))

            from PIL import Image as PILImage
            img = PILImage.open(str(dest))
            gray = img.convert('L')
            avg = sum(gray.getdata()) / (img.width * img.height)

            am = get_asset_manager()
            am.register(
                project=project, asset_type=f"{frame_type}_frame",
                shot_id=f"shot_{shot_num:03d}", source_path=files[0],
                relative_dir="s5_frames",
                dest_name=f"s{shot_num:02d}_{frame_type}.png",
                metadata={"prompt": prompt[:200], "seed": s, "mode": "flux_t2i",
                          "resolution": f"{img.width}x{img.height}"},
            )

            print(f"    ✅ s{shot_num:02d}_{frame_type}.png (T2I, {dest.stat().st_size//1024}KB, {img.width}×{img.height}, avg={avg:.0f})")
            return True

        except ComfyUIError as e:
            print(f"    ❌ T2I ComfyUIError: {e}")
        except Exception as e:
            print(f"    ❌ T2I Error: {e}")

    print(f"    ❌ s{shot_num:02d}_{frame_type} T2I failed after {max_retries+1} attempts")
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
        for i, (sc, sh) in enumerate(shots):
            global_shot = i + 1
            n = global_shot
            chars_in = sh.get("characters", [])
            scene_desc = _build_scene_description(sc, color_palette=project_color_palette)
            char_desc = _build_character_descriptions(chars, chars_in)
            comp_suffix = _build_composition_suffix(sh, chars_in, chars, project_color_palette)

            fp_first = build_first_prompt(
                scene_description=scene_desc,
                start_frame_desc=_get_frame_desc(sh, "start"),
                character_descriptions=char_desc,
            )
            fp_last = build_last_prompt(
                scene_description=scene_desc,
                end_frame_desc=_get_frame_desc(sh, "end"),
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
    # Per-character ref directory for costume resolution
    ref_dir = pd / "s3_character_refs"
    
    sm = get_state_manager()
    total = len(shots) * (2 if args.frames == "both" else 1)
    sm.mark_running(args.project, "s5_frame_generate", remaining=total)

    out = pd / "s5_frames"
    out.mkdir(parents=True, exist_ok=True)

    sess = ComfyUISession()
    total_ok = 0
    prev_last = ""  # 前一个 shot 的尾帧路径

    for i, (sc, sh) in enumerate(shots):
        # 全局 shot 编号 (1-based)，避免场景内编号重复导致文件覆盖
        global_shot = i + 1
        n = global_shot  # 用全局编号做文件名 s01, s02, ...
        local_shot = sh["shotNumber"]  # 保留原始场景内编号用于 S4b 匹配
        chars_in = sh.get("characters", [])
        scene_desc = _build_scene_description(sc, color_palette=project_color_palette)
        char_desc = _build_character_descriptions(chars, chars_in)
        comp_suffix = _build_composition_suffix(sh, chars_in, chars, project_color_palette)

        # Resolve costumes for this shot
        shot_costumes = _resolve_shot_costumes(sh, chars, ref_dir)
        costume_text = _build_costume_consistency(shot_costumes)

        # Check S4b for pre-built prompts
        s4b_shot = None
        if s4b_data:
            for s in s4b_data.get("shots", []):
                if s["shotNumber"] == local_shot:
                    s4b_shot = s
                    break

        # 查找所有角色参考图 (最多3个: D3) — 服饰感知
        ref_images = []  # list of (char_name, Path)
        main_char_multi_views = {}  # {view: Path} for main character
        
        for ci, cn in enumerate(chars_in):
            active_costume = shot_costumes.get(cn, {}).get("id", "default")
            
            if ci == 0:
                # 主角色: 获取多视角（服饰感知）
                main_char_multi_views = _find_character_multi_view_refs(cn, pd, active_costume)
                ref = _find_character_ref_image(cn, pd, active_costume)
                if ref:
                    ref_images.append((cn, ref))
                elif not main_char_multi_views:
                    ref = _find_character_ref_image(cn, pd, "default")
                    if ref:
                        ref_images.append((cn, ref))
            else:
                # 配角: 服饰感知参考图
                ref = _find_character_ref_image(cn, pd, active_costume)
                if ref:
                    ref_images.append((cn, ref))

        if not ref_images and not main_char_multi_views:
            # Path B: 无角色 ref 的纯场景/道具镜头 → Flux Dev T2I
            print(f"\n[{i+1}/{len(shots)}] Shot {n} | 🎨 No character ref → Flux T2I")

            if args.frames in ("first", "both"):
                if s4b_shot and s4b_shot.get("startFrame", {}).get("prompt"):
                    fp = s4b_shot["startFrame"]["prompt"]
                else:
                    fp = build_first_prompt(
                        scene_description=scene_desc,
                        start_frame_desc=_get_frame_desc(sh, "start"),
                        character_descriptions="",  # no characters
                    )
                print(f"  First (T2I, {len(fp)}c): {fp[:80]}...")
                ok = generate_frame_t2i(sess, fp, n, "first", args.project, out)
                if ok:
                    total_ok += 1

            if args.frames in ("last", "both"):
                if s4b_shot and s4b_shot.get("endFrame", {}).get("prompt"):
                    fl = s4b_shot["endFrame"]["prompt"]
                else:
                    first_frame_path = str(out / f"s{n:02d}_first.png")
                    fl = build_last_prompt(
                        scene_description=scene_desc,
                        end_frame_desc=_get_frame_desc(sh, "end"),
                        character_descriptions="",
                        first_frame_path=first_frame_path,
                    )
                print(f"  Last  (T2I, {len(fl)}c): {fl[:80]}...")
                ok = generate_frame_t2i(sess, fl, n, "last", args.project, out)
                if ok:
                    total_ok += 1
                    prev_last = str(out / f"s{n:02d}_last.png")
            continue

        # 上传参考图到 ComfyUI input
        # image1/2/3 分配策略:
        #   多角色 shot: image1=主角front, image2=配角front, image3=第三角色front
        #   单角色 shot: image1=front, image2=plus_angle, image3=minus_angle
        ref_input_names = []  # for single-view fallback
        for cn, ref_path in ref_images[:3]:  # max 3 (D3)
            input_name = _upload_to_comfyui_input(ref_path, args.project, f"ref_{cn}")
            ref_input_names.append(input_name)

        # 多视角: 上传主角的 front/plus_angle/minus_angle
        mv_input_names = {}  # {view: input_name}
        for view, ref_path in main_char_multi_views.items():
            input_name = _upload_to_comfyui_input(ref_path, args.project, f"ref_{chars_in[0]}_{view}")
            mv_input_names[view] = input_name

        # 构建 image1/image2/image3
        if len(chars_in) > 1:
            # 多角色 shot: image1=主角 S3b grid, image2=主角 S3 single, image3=配角 ref
            main_ref = mv_input_names.get("front", ref_input_names[0] if ref_input_names else None)
            # ref_input_names[0] = main char's S3 single (auxiliary when S3b grid is primary)
            aux_ref = ref_input_names[0] if ref_input_names and ref_input_names[0] != main_ref else None
            # ref_input_names[1] = first supporting character's ref
            ref2 = aux_ref or (ref_input_names[1] if len(ref_input_names) > 1 else None)
            # If aux_ref is ref2, supporting char moves to ref3
            if aux_ref and len(ref_input_names) > 1:
                ref3_candidate = ref_input_names[1]
            elif len(ref_input_names) > 2:
                ref3_candidate = ref_input_names[2]
            elif not aux_ref and len(ref_input_names) > 1:
                ref3_candidate = ref_input_names[1] if ref2 == ref_input_names[0] else None
            else:
                ref3_candidate = None
        else:
            # 单角色 shot: image1=S3b front (grid), image2=S3 single (auxiliary), image3=plus_angle
            if mv_input_names:
                main_ref = mv_input_names.get("front", ref_input_names[0] if ref_input_names else None)
                # Prefer S3 single image as aux ref2 when S3b grid is primary
                # ref_input_names[0] = S3 single (from ref_images), only use if different from grid
                ref2 = ref_input_names[0] if ref_input_names and ref_input_names[0] != main_ref else mv_input_names.get("plus_angle")
                ref3_candidate = mv_input_names.get("minus_angle")
            else:
                main_ref = ref_input_names[0] if ref_input_names else None
                ref2 = None
                ref3_candidate = None

        # 创建 fit+pad 版本的主角色参考图 (1024×1536→480×720→1280×720白边)
        main_ref_padded_name = None
        # 用主角 front 视图做 fit+pad
        if main_char_multi_views and "front" in main_char_multi_views:
            padded_path = _create_padded_ref(main_char_multi_views["front"], target_w=1280, target_h=720)
        elif ref_images:
            padded_path = _create_padded_ref(ref_images[0][1], target_w=1280, target_h=720)
        else:
            padded_path = None
        if padded_path:
            main_ref_padded_name = _upload_to_comfyui_input(padded_path, args.project, f"ref_{chars_in[0]}_padded")

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
                    start_frame_desc=_get_frame_desc(sh, "start"),
                    character_descriptions=char_desc,
                    previous_last_frame=prev_last if prev_last else "",
                    costume_consistency=costume_text,
                )
                if comp_suffix:
                    fp += comp_suffix
                print(f"  First ({len(fp)}c): {fp[:80]}...")

            # image3 = 主角 minus_angle (如有) else 前帧连续性参考
            ref3_for_first = ref3_candidate if ref3_candidate else (prev_input_name if prev_input_name else None)

            ok = generate_frame(
                sess, fp, n, "first", args.project, out,
                ref_image_name=main_ref,
                ref_image2_name=ref2,
                ref_image3_name=ref3_for_first,
                ref_padded_name=main_ref_padded_name,
            )
            if ok:
                total_ok += 1

        if args.frames in ("last", "both"):
            first_frame_path = str(out / f"s{n:02d}_first.png")

            # 尾帧前提: 首帧必须存在
            if not Path(first_frame_path).exists():
                print(f"  ⚠️ Skip last frame: first frame not found")
            else:
                # Use S4b pre-built prompt if available, otherwise build on-the-fly
                if s4b_shot and s4b_shot.get("endFrame", {}).get("prompt"):
                    fl = s4b_shot["endFrame"]["prompt"]
                    if comp_suffix:
                        fl += comp_suffix
                    print(f"  Last  (S4b, {len(fl)}c): {fl[:80]}...")
                else:
                    fl = build_last_prompt(
                        scene_description=scene_desc,
                        end_frame_desc=_get_frame_desc(sh, "end"),
                        character_descriptions=char_desc,
                        first_frame_path=first_frame_path,
                        costume_consistency=costume_text,
                    )
                    if comp_suffix:
                        fl += comp_suffix
                    print(f"  Last  ({len(fl)}c): {fl[:80]}...")

                # 尾帧参考: 首帧作为 VAEEncode 输入 (首帧已是 1280×720)
                last_ref_input = _upload_to_comfyui_input(
                    Path(first_frame_path), args.project, f"first_s{n:02d}"
                )
                last_ref = last_ref_input
                last_ref_padded = last_ref_input  # 首帧本身就是 1280×720

                ok = generate_frame(
                    sess, fl, n, "last", args.project, out,
                    ref_image_name=last_ref,
                    ref_image2_name=ref2,
                    ref_image3_name=None,
                    ref_padded_name=last_ref_padded,
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

            # 释放 qw35-9b
            print(f"  [VL] 释放 qw35-9b (edge-llm switch idle)...")
            try:
                import subprocess
                subprocess.run(["edge-llm", "switch", "idle"],
                              capture_output=True, timeout=60)
                print(f"  [VL] ✅ qw35-9b 已释放")
            except Exception as e:
                print(f"  [VL] ⚠️ 释放失败: {e}")
        else:
            print(f"\n  ⚠️ VL 后端不可用，跳过质检")
            print(f"  → 运行 'edge-llm switch qwen35-9b' 后重新执行 S5 可触发质检")


if __name__ == "__main__":
    main()
