#!/usr/bin/env python3
"""
scripts/s3b_four_view.py - Stage 3b: 四视图参考图生成 (Qwen Image Edit)

基于 S3 生成的单视图角色图,使用 Qwen Image Edit 2511 扩展为四视图。
输出 front / 3-4 angle / side / back 四张图。

模型: qwen_image_edit_2511_fp8mixed.safetensors
参考节点: TextEncodeQwenImageEditPlus (原生 ComfyUI v0.24+)

用法:
    python scripts/s3b_four_view.py --project last_bento
    python scripts/s3b_four_view.py --project last_bento --character 老周
    python scripts/s3b_four_view.py --project last_bento --checkpoint juggernautXL_v10.safetensors --style realist
"""

import json, sys, argparse, shutil, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from core.comfyui_session import ComfyUISession, ComfyUIError
from core.state_manager import get_state_manager
from core.asset_manager import get_asset_manager
from core.vl_backend import get_vl_backend

# ═══════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════

NEGATIVE_PROMPT = (
    "low quality, worst quality, bad anatomy, bad hands, missing fingers, "
    "extra fingers, fused fingers, ugly, deformed, blurry, watermark, "
    "text, signature, cropped, out of frame, multiple characters, group, crowd"
)

FOUR_VIEW_PROMPT = """请将输入的角色图片转换为一张包含四个视角的设定图,布局为 2x2 网格:

【左上】正面视图 (front view):角色正面站立,正面朝向观众
【右上】左3/4侧视图 (left 3/4 view):角色身体微微转向左侧(约45度),从右前方观看,能看到右半边脸和身体右侧轮廓
【左下】右3/4侧视图 (right 3/4 view):角色身体微微转向右侧(约45度),从左前方观看,能看到左半边脸和身体左侧轮廓
【右下】背面视图 (back view):角色背面站立,背对观众

白色或浅灰色统一背景,专业角色设定图风格,高质量清晰细节。角色站立姿势自然,四个视角之间有明显间距、排列整齐。"""

STYLE_PROMPTS = {
    "comic": "日系动漫风格,动画角色设定图,清晰的线条,鲜明色彩",
    "realist": "写实真人电影风格,专业角色设定图,照片级细节,真实光照",
}

STYLE_ANCHORS = {
    "comic": (
        "日系动漫风格设定图。线条清晰锐利,色彩饱和鲜明,阴影使用赛璐珞分层。"
        "角色比例遵循动漫标准(大眼、小鼻、简化面部结构)。"
        "背景纯色或浅灰渐变,无环境光影干扰。"
        "整体呈现专业动画角色设定集的视觉标准。"
    ),
    "realist": (
        "写实真人电影级设定图。照片级皮肤质感(毛孔、细纹、皮下血管可见),"
        "物理准确的光照(主光+辅光+轮廓光三点布光),自然材质反射。"
        "角色比例遵循真实人体解剖学。"
        "背景纯白或浅灰无缝渐变,如专业摄影棚证件照环境。"
        "整体呈现电影级选角照片的视觉标准。"
    ),
}


def build_four_view_prompt(char_name: str, characters: list, style: str = "realist") -> str:
    """构建四视图 prompt,注入 visualAnchors + 画风锚定 + 一致性硬约束。

    Args:
        char_name: 角色名
        characters: S2 characters 列表
        style: "comic" or "realist"
    """
    # Find character
    char = None
    for c in characters:
        if c["name"] == char_name:
            char = c
            break

    prompt = FOUR_VIEW_PROMPT

    # Inject visualAnchors
    if char:
        anchors = char.get("visualAnchors", {})
        palette = char.get("colorPalette", "")

        anchor_lines = []
        if anchors.get("face"):
            anchor_lines.append(f"- 面部: {anchors['face']}")
        if anchors.get("hair"):
            anchor_lines.append(f"- 发型: {anchors['hair']}")
        if anchors.get("body"):
            anchor_lines.append(f"- 体型: {anchors['body']}")
        if anchors.get("clothing"):
            anchor_lines.append(f"- 服装: {anchors['clothing']}")
        if anchors.get("signature"):
            anchor_lines.append(f"- 标志: {anchors['signature']}")

        if anchor_lines:
            prompt += "\n\n=== 角色视觉锚点(不可偏离)==="
            for line in anchor_lines:
                prompt += f"\n{line}"

        if palette:
            prompt += f"\n- 色板: {palette}"

    # Inject style anchor
    style_anchor = STYLE_ANCHORS.get(style, STYLE_ANCHORS["realist"])
    prompt += f"\n\n=== 画风锚定 ===\n{style_anchor}"

    # 精简一致性约束放末尾
    prompt += (
        "\n\n=== 一致性约束 ==="
        "\n1. 四个视角必须是同一角色:相同面孔、发型发色、服装样式材质、体型身高。"
        "\n2. 左3/4和右3/4必须是对称互补的两个方向(朝左转→见右脸,朝右转→见左脸),禁止同向重复。"
        "\n3. 服装褶皱和光影可因视角自然变化,但款式/颜色/材质必须完全一致。"
    )

    return prompt


def build_qwen_edit_workflow(
    reference_image_path: str,
    prompt: str,
    width: int = 1024,
    height: int = 1536,
    seed: int = None,
    steps: int = 4,
    cfg: float = 1.0,
    unet_name: str = "qwen_image_edit_2511_fp8mixed.safetensors",
    clip_name: str = "qwen_2.5_vl_7b_fp8_scaled.safetensors",
    vae_name: str = "qwen_image_vae.safetensors",
    lora_name: str = "Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors",
    lora_strength: float = 1.0,
    shift: float = 3.1,
    lora_only: bool = True,
) -> dict:
    """
    Build Qwen Image Edit workflow using separate loaders (no CheckpointLoaderSimple).

    Aligned with template qwen_edit_four_view.json v2.1:
    - UNETLoader + CLIPLoader + VAELoader (separate components)
    - Lightning LoRA 4-step, euler/simple, cfg=1.0
    - ModelSamplingAuraFlow (shift=3.1)
    - CFGNorm (strength=1)
    - ImageScale before VAEEncode for resolution alignment
    - TextEncodeQwenImageEditPlus for both positive and negative
    """
    import random
    if seed is None:
        seed = random.randint(0, 2**32 - 1)

    ref_filename = os.path.basename(reference_image_path)

    workflow = {
        # ── Model loaders ──
        "12": {"class_type": "UNETLoader", "inputs": {"unet_name": unet_name, "weight_dtype": "default"}},
        "61": {"class_type": "CLIPLoader", "inputs": {"clip_name": clip_name, "type": "qwen_image"}},
        "10": {"class_type": "VAELoader", "inputs": {"vae_name": vae_name}},
        # ── LoRA ──
        "74": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["12", 0], "lora_name": lora_name, "strength_model": lora_strength}},
        # ── Model patches ──
        "67": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["74", 0], "shift": shift}},
        "64": {"class_type": "CFGNorm", "inputs": {"model": ["67", 0], "strength": 1}},
        # ── Reference image ──
        "41": {"class_type": "LoadImage", "inputs": {"image": ref_filename}},
        "80": {"class_type": "ImageScale", "inputs": {"image": ["41", 0], "width": width, "height": height, "upscale_method": "lanczos", "crop": "disabled"}},
        "75": {"class_type": "VAEEncode", "inputs": {"pixels": ["80", 0], "vae": ["10", 0]}},
        # ── Conditioning ──
        "68": {"class_type": "TextEncodeQwenImageEditPlus", "inputs": {"clip": ["61", 0], "prompt": prompt, "vae": ["10", 0], "image1": ["41", 0]}},
        "69": {"class_type": "TextEncodeQwenImageEditPlus", "inputs": {"clip": ["61", 0], "prompt": NEGATIVE_PROMPT, "vae": ["10", 0], "image1": ["41", 0]}},
        # ── Sampling ──
        "65": {"class_type": "KSampler", "inputs": {"seed": seed, "steps": steps, "cfg": cfg, "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0, "model": ["64", 0], "positive": ["68", 0], "negative": ["69", 0], "latent_image": ["75", 0]}},
        # ── Decode + Save ──
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["65", 0], "vae": ["10", 0]}},
        "60": {"class_type": "SaveImage", "inputs": {"filename_prefix": "aicf_fourview", "images": ["8", 0]}},
    }

    return workflow


# ═══════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="S3b: Four-View Character Reference (Qwen Image Edit)")
    parser.add_argument("--project", "-p", required=True, help="Project name")
    parser.add_argument("--character", "-c", help="Specific character name (optional, defaults to all)")
    parser.add_argument("--style", default="comic", choices=["comic", "realist"], help="Art style")
    parser.add_argument("--checkpoint", default="qwen_image_edit_2511_fp8mixed.safetensors",
                       help="Qwen Image Edit checkpoint")
    parser.add_argument("--vae", default="qwen_image_vae.safetensors", help="VAE name")
    parser.add_argument("--lora", default="Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors",
                       help="LoRA for Lightning sampling (required for Qwen Image Edit)")
    parser.add_argument("--lora-strength", type=float, default=0.8, help="LoRA strength")
    parser.add_argument("--steps", type=int, default=4, help="Sampling steps (4 with Lightning LoRA)")
    parser.add_argument("--cfg", type=float, default=1.0, help="CFG scale")
    parser.add_argument("--width", type=int, default=1024, help="Output width")
    parser.add_argument("--height", type=int, default=1536, help="Output height")
    parser.add_argument("--seed", type=int, help="Random seed (default: random)")
    parser.add_argument("--dry-run", action="store_true", help="Print workflow without running")
    parser.add_argument("--no-check", action="store_true", help="Skip VL quality check")
    parser.add_argument("--check-threshold", type=float, default=7.0,
                       help="VL quality check threshold (default: 7.0)")
    parser.add_argument("--max-vl-retries", type=int, default=2,
                       help="Max VL check retry count when four-view fails (default: 2)")
    args = parser.parse_args()

    project_dir = Path(__file__).parent.parent / "projects" / args.project
    s3_dir = project_dir / "s3_character_refs"

    if not s3_dir.exists():
        print(f"ERROR: {s3_dir} not found. Run S3 first.")
        sys.exit(1)

    # Load manifest to find character images
    manifest_path = s3_dir / "manifest.json"
    if manifest_path.exists():
        with open(manifest_path) as f:
            manifest = json.load(f)
        char_images = manifest.get("characters", {})
    else:
        # Fallback: scan directory for png files
        char_images = {}
        for p in s3_dir.glob("*.png"):
            char_images[p.stem] = str(p)

    if args.character:
        if args.character not in char_images:
            print(f"Character '{args.character}' not found in {s3_dir}")
            sys.exit(1)
        char_images = {args.character: char_images[args.character]}

    if not char_images:
        print(f"No character images found in {s3_dir}")
        sys.exit(1)

    sm = get_state_manager()
    sm.mark_running(args.project, "s3b_four_view", remaining=len(char_images))

    # Output dirs - new: s3_character_refs/{name}/, compat: s3b_four_views/
    fv_dir = project_dir / "s3b_four_views"
    fv_dir.mkdir(parents=True, exist_ok=True)
    ref_dir = project_dir / "s3_character_refs"
    ref_dir.mkdir(parents=True, exist_ok=True)

    # Load S2 characters for visualAnchors injection
    s2_path = project_dir / "s2_characters.json"
    characters = []
    if s2_path.exists():
        import json as _json
        s2_data = _json.loads(s2_path.read_text())
        characters = s2_data.get("characters", [])

    session = ComfyUISession()

    # Copy reference images to ComfyUI input directory
    # Use character-name prefix to avoid basename collision (new per-char dirs all use 'default.png')
    comfyui_input = Path.home() / "ComfyUI" / "input"
    char_input_map = {}  # name → input_filename
    for name, img_path in char_images.items():
        src = Path(img_path)
        # Prefix with sanitized character name to avoid collision
        safe_name = name.replace(" ", "_")
        input_filename = f"s3b_{safe_name}_{src.name}"
        dest = comfyui_input / input_filename
        if str(src) != str(dest):
            shutil.copy2(str(src), str(dest))
        char_input_map[name] = input_filename

    # Ensure VL backend (lazy start — only if needed)
    vl_available = not args.no_check and get_vl_backend().ensure_available(auto_start=True)

    results = {}
    vl_results = []  # VL check results for manifest

    for i, (name, img_path) in enumerate(char_images.items()):
        # Build per-character prompt with visualAnchors
        full_prompt = build_four_view_prompt(name, characters, args.style)
        
        # Per-character output dirs
        char_dir = ref_dir / name
        char_dir.mkdir(parents=True, exist_ok=True)

        for attempt in range(args.max_vl_retries + 1):
            if attempt > 0:
                print(f"\n  [Retry {attempt}/{args.max_vl_retries}] for {name}...")
                import random
                retry_seed = random.randint(0, 2**32 - 1)
                if args.seed is not None:
                    retry_seed = args.seed + attempt
            else:
                retry_seed = args.seed

            print(f"\n{'='*60}")
            print(f"Character {i+1}/{len(char_images)}: {name}")
            if attempt > 0:
                print(f"Attempt {attempt + 1}/{args.max_vl_retries + 1}")
            print(f"Reference: {img_path}")
            print(f"ComfyUI input: {char_input_map[name]}")
            print(f"Prompt: {len(full_prompt)} chars")

            if args.dry_run:
                wf = build_qwen_edit_workflow(
                    reference_image_path=char_input_map[name],
                    prompt=full_prompt,
                    seed=retry_seed,
                    steps=args.steps,
                    cfg=args.cfg,
                    unet_name=args.checkpoint,
                    vae_name=args.vae,
                    lora_name=args.lora,
                    lora_strength=args.lora_strength,
                    width=args.width,
                    height=args.height,
                )
                print(f"Workflow nodes: {list(wf.keys())}")
                print(f"Prompt length: {len(full_prompt)} chars")
                break  # dry-run: one pass is enough

            try:
                wf = build_qwen_edit_workflow(
                    reference_image_path=char_input_map[name],
                    prompt=full_prompt,
                    seed=retry_seed,
                    steps=args.steps,
                    cfg=args.cfg,
                    unet_name=args.checkpoint,
                    vae_name=args.vae,
                    lora_name=args.lora,
                    lora_strength=args.lora_strength,
                    width=args.width,
                    height=args.height,
                )

                prefix = f"aicf_{args.project}_{name}_fourview_{attempt}"
                wf["60"]["inputs"]["filename_prefix"] = prefix

                print(f"Running Qwen Image Edit... (steps={args.steps}, cfg={args.cfg})")
                result = session.run(wf, timeout=600)

                # Find output files
                output_dir = Path.home() / "ComfyUI" / "output"
                files = sorted(output_dir.glob(f"{prefix}_*.png"),
                               key=lambda p: p.stat().st_mtime, reverse=True)

                if not files:
                    print(f"⚠️ {name}: No output file found")
                    if attempt < args.max_vl_retries:
                        continue
                    results[name] = "ERROR: No output"
                    break

                # Copy to output locations
                dest = char_dir / "default_fourview.png"
                shutil.copy2(str(files[0]), str(dest))
                # Backward compat
                compat_dest = fv_dir / f"{name}_fourview.png"
                shutil.copy2(str(files[0]), str(compat_dest))
                print(f"  🖼️ {name}: {dest} ({dest.stat().st_size} bytes)")

                # ── VL Quality Check ──
                if vl_available:
                    from core.four_view_check import FourViewChecker
                    checker = FourViewChecker(threshold=args.check_threshold)

                    temp_dir = str(char_dir / "_tmp_quadrants")
                    print(f"  🔍 VL quality check (threshold={args.check_threshold})...")
                    vl_result = checker.check(str(dest), next(
                        (c for c in characters if c["name"] == name), {}))

                    icon = "✅" if vl_result["pass"] else "⚠️"
                    print(f"  VL: {icon} {vl_result['summary']}")

                    # Record result
                    vl_result["attempt"] = attempt + 1
                    vl_result["image_path"] = str(dest)
                    vl_results.append(vl_result)

                    if vl_result["pass"]:
                        results[name] = str(dest)
                        break
                    elif attempt < args.max_vl_retries:
                        reason = "; ".join(vl_result.get("issues", ["unknown"]))
                        print(f"  → Quality check failed: {reason}")
                        print(f"  → Retrying ({attempt+1}/{args.max_vl_retries})...")
                        continue
                    else:
                        print(f"  → Quality check failed after {args.max_vl_retries+1} attempts")
                        print(f"  → Marking as FAILED, will not flow to S5")
                        results[name] = f"VL_FAIL: {vl_result['summary']}"
                        break
                else:
                    results[name] = str(dest)
                    break  # VL disabled: success = done

            except ComfyUIError as e:
                print(f"  ❌ {name} attempt {attempt+1} failed: {e}")
                if attempt < args.max_vl_retries:
                    continue
                results[name] = f"ERROR: {e}"
                break

    # Release VL backend
    if vl_available:
        try:
            get_vl_backend().stop()
            print(f"  [VL] Backend released")
        except Exception as e:
            print(f"  [VL] Warning: release failed: {e}")

    # Save results manifest
    manifest = {
        "project": args.project,
        "style": args.style,
        "checkpoint": args.checkpoint,
        "resolution": f"{args.width}x{args.height}",
        "characters": results,
    }
    with open(fv_dir / "manifest.json", "w") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    if vl_results:
        vl_report_path = fv_dir / "vl_quality_report.json"
        with open(vl_report_path, "w") as f:
            json.dump(vl_results, f, ensure_ascii=False, indent=2)
        print(f"\n  VL quality report: {vl_report_path}")

    completed = sum(1 for v in results.values()
                    if not str(v).startswith("ERROR") and not str(v).startswith("VL_FAIL"))
    failed_vl = sum(1 for v in results.values() if str(v).startswith("VL_FAIL"))
    sm.mark_completed(args.project, "s3b_four_view",
                      generated=f"{completed}/{len(char_images)}",
                      vl_failed=str(failed_vl),
                      chars=",".join(results.keys()))

    print(f"\n{'='*60}")
    print(f"S3b Complete: {completed}/{len(char_images)} four-views generated")
    if failed_vl:
        print(f"⚠️ {failed_vl} character(s) failed VL quality check")
    print(f"Output: {fv_dir}/")


if __name__ == "__main__":
    main()
