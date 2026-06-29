#!/usr/bin/env python3
"""
scripts/s3b_four_view.py — Stage 3b: 四视图参考图生成 (Qwen Image Edit)

基于 S3 生成的单视图角色图，使用 Qwen Image Edit 2511 扩展为四视图。
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
from core.state_manager import get_state_manager

# ═══════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════

NEGATIVE_PROMPT = (
    "low quality, worst quality, bad anatomy, bad hands, missing fingers, "
    "extra fingers, fused fingers, ugly, deformed, blurry, watermark, "
    "text, signature, cropped, out of frame, multiple characters, group, crowd"
)

FOUR_VIEW_PROMPT = """请将输入的角色图片转换为一张包含四个视角的设定图，布局为 2x2 网格：

【左上】正面视图 (front view)：角色正面站立，正面朝向观众
【右上】3/4 侧视图 (3-4 angle view)：角色身体微微转向左侧，从右前方约45度角观看
【左下】侧面视图 (side view)：角色纯侧面站立，身体完全朝向左侧
【右下】背面视图 (back view)：角色背面站立，背对观众

整体要求：
- 四个视角的角色必须完全一致（同一人，相同服装，相同发型，相同身高体型）
- 保持输入图片中的角色特征：服装款式、颜色、发型、面部特征、配饰
- 白色或浅灰色统一背景，专业角色设定图风格
- 四个视角之间有明显间距，排列整齐
- 角色站立姿势自然，正面/背面为正面站立，侧面为纯侧面站立
- 高质量，清晰细节，适合作为动画制作参考"""

STYLE_PROMPTS = {
    "comic": "日系动漫风格，动画角色设定图，清晰的线条，鲜明色彩",
    "realist": "写实真人电影风格，专业角色设定图，照片级细节，真实光照",
}


def build_qwen_edit_workflow(
    reference_image_path: str,
    prompt: str,
    width: int = 1024,
    height: int = 1024,
    seed: int = None,
    steps: int = 20,
    cfg: float = 7.0,
    checkpoint: str = "qwen_image_edit_2511_fp8mixed.safetensors",
    vae_name: str = "qwen_image_vae.safetensors",
    lora_name: str = None,
    lora_strength: float = 0.8,
) -> dict:
    """
    Build Qwen Image Edit workflow for four-view generation.
    
    Uses TextEncodeQwenImageEditPlus node which accepts up to 3 reference images.
    For four-view: we use image1 as the single reference character image.
    """
    import random
    if seed is None:
        seed = random.randint(0, 2**32 - 1)
    
    # Workflow uses TextEncodeQwenImageEditPlus for reference-based editing
    # Node IDs:
    # 4: CheckpointLoaderSimple (Qwen Image Edit)
    # 5: EmptyLatentImage
    # 6: TextEncodeQwenImageEditPlus (prompt + reference image)
    # 7: CLIPTextEncode (negative)
    # 8: VAEDecode
    # 9: LoadImage (reference)
    # 10: SaveImage
    
    workflow = {
        "4": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": checkpoint}
        },
        "5": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": width, "height": height, "batch_size": 1}
        },
        "6": {
            "class_type": "TextEncodeQwenImageEditPlus",
            "inputs": {
                "clip": ["4", 1],
                "prompt": prompt,
                "vae": ["4", 2],
                "image1": ["9", 0],
            }
        },
        "7": {
            "class_type": "CLIPTextEncode",
            "inputs": {
                "text": NEGATIVE_PROMPT,
                "clip": ["4", 1]
            }
        },
        "8": {
            "class_type": "VAEDecode",
            "inputs": {
                "samples": ["3", 0],
                "vae": ["4", 2]
            }
        },
        "9": {
            "class_type": "LoadImage",
            "inputs": {
                "image": os.path.basename(reference_image_path)
            }
        },
        "10": {
            "class_type": "SaveImage",
            "inputs": {
                "filename_prefix": "aicf_fourview",
                "images": ["8", 0]
            }
        },
        # KSampler needs to come after conditioning
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed,
                "steps": steps,
                "cfg": cfg,
                "sampler_name": "euler_ancestral",
                "scheduler": "normal",
                "denoise": 1.0,
                "model": ["4", 0],
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["5", 0],
            }
        },
    }
    
    # Add LoRA if specified
    if lora_name:
        # Insert LoRA loader between checkpoint and KSampler
        workflow["4_lora"] = {
            "class_type": "LoraLoader",
            "inputs": {
                "model": ["4", 0],
                "lora_name": lora_name,
                "strength_model": lora_strength,
                "strength_clip": lora_strength,
            }
        }
        # Update model reference to use LoRA output
        workflow["3"]["inputs"]["model"] = ["4_lora", 0]
        workflow["6"]["inputs"]["clip"] = ["4_lora", 1]
    
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
    parser.add_argument("--lora", default=None, help="Optional LoRA (e.g. Lightning 8-step)")
    parser.add_argument("--lora-strength", type=float, default=0.8, help="LoRA strength")
    parser.add_argument("--steps", type=int, default=20, help="Sampling steps")
    parser.add_argument("--cfg", type=float, default=7.0, help="CFG scale")
    parser.add_argument("--width", type=int, default=1024, help="Output width")
    parser.add_argument("--height", type=int, default=1024, help="Output height")
    parser.add_argument("--seed", type=int, help="Random seed (default: random)")
    parser.add_argument("--dry-run", action="store_true", help="Print workflow without running")
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
    
    # Output dir
    fv_dir = project_dir / "s3b_four_views"
    fv_dir.mkdir(parents=True, exist_ok=True)
    
    session = ComfyUISession()
    style_suffix = STYLE_PROMPTS.get(args.style, "")
    full_prompt = f"{FOUR_VIEW_PROMPT}\n\n风格要求：{style_suffix}"
    
    results = {}
    for i, (name, img_path) in enumerate(char_images.items()):
        print(f"\n{'='*60}")
        print(f"Character {i+1}/{len(char_images)}: {name}")
        print(f"Reference: {img_path}")
        
        if args.dry_run:
            wf = build_qwen_edit_workflow(
                reference_image_path=img_path,
                prompt=full_prompt,
                seed=args.seed,
                steps=args.steps,
                cfg=args.cfg,
                checkpoint=args.checkpoint,
                vae_name=args.vae,
                lora_name=args.lora,
                lora_strength=args.lora_strength,
                width=args.width,
                height=args.height,
            )
            print(f"Workflow nodes: {list(wf.keys())}")
            print(f"Prompt length: {len(full_prompt)} chars")
            continue
        
        try:
            wf = build_qwen_edit_workflow(
                reference_image_path=img_path,
                prompt=full_prompt,
                seed=args.seed,
                steps=args.steps,
                cfg=args.cfg,
                checkpoint=args.checkpoint,
                vae_name=args.vae,
                lora_name=args.lora,
                lora_strength=args.lora_strength,
                width=args.width,
                height=args.height,
            )
            
            prefix = f"aicf_{args.project}_{name}_fourview"
            wf["10"]["inputs"]["filename_prefix"] = prefix
            
            print(f"Running Qwen Image Edit... (steps={args.steps}, cfg={args.cfg})")
            result = session.run(wf, timeout=600)
            
            # Find output files
            output_dir = Path.home() / "ComfyUI" / "output"
            files = sorted(output_dir.glob(f"{prefix}_*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
            
            if files:
                dest = fv_dir / f"{name}_fourview.png"
                shutil.copy2(str(files[0]), str(dest))
                print(f"✅ {name}: {dest} ({dest.stat().st_size} bytes)")
                results[name] = str(dest)
                
                # Register in asset manager
                am = get_asset_manager()
                am.register(
                    project=args.project,
                    asset_type="four_view",
                    shot_id=None,
                    source_path=files[0],
                    relative_dir="s3b_four_views",
                    metadata={
                        "character": name,
                        "style": args.style,
                        "checkpoint": args.checkpoint,
                    }
                )
            else:
                print(f"⚠️ {name}: No output file found")
                results[name] = "ERROR: No output"
                
        except ComfyUIError as e:
            print(f"❌ {name} failed: {e}")
            results[name] = f"ERROR: {e}"
    
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
    
    completed = sum(1 for v in results.values() if not str(v).startswith("ERROR"))
    sm.mark_completed(args.project, "s3b_four_view", 
                      generated=f"{completed}/{len(char_images)}",
                      chars=",".join(results.keys()))
    
    print(f"\n{'='*60}")
    print(f"S3b Complete: {completed}/{len(char_images)} four-views generated")
    print(f"Output: {fv_dir}/")


if __name__ == "__main__":
    main()
