#!/usr/bin/env python3
"""
scripts/s3_character_image.py — Stage 3a: 角色参考图生成

从 s2_characters.json 读取角色描述，生成正面全身参考图。
支持双风格路径：
  --style realistic (Flux.1 Dev FP8, 默认)
  --style anime     (Animagine XL 3.1, SDXL)

Prompt 由 OpenClaw (Nova) 生成并注入，脚本只负责 ComfyUI 调用。

用法:
    python scripts/s3_character_image.py --project last_bento
    python scripts/s3_character_image.py --project last_bento --style anime
    python scripts/s3_character_image.py --project last_bento --character 老周
"""

import json
import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.comfyui_session import ComfyUISession, ComfyUIError
from core.state_manager import get_state_manager
from core.asset_manager import get_asset_manager

# ═══════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════

NEGATIVE_PROMPT = (
    "low quality, worst quality, bad anatomy, bad hands, missing fingers, "
    "extra fingers, fused fingers, ugly, deformed, blurry, watermark, "
    "text, signature, cropped, out of frame, multiple views, split screen, "
    "comic panel, multiple people, group, crowd, duplicate, clone"
)

QUALITY_TAGS = "masterpiece, best quality, very aesthetic, highres, detailed"


def build_char_prompt(character: dict) -> str:
    """Build T2I prompt from character visualAnchors.
    
    Animagine XL responds well to: quality tags, gender/age tags, 
    comma-separated visual descriptors, parentheses for emphasis.
    """
    # Support both "description" (AICB format) and "appearance" (our format)
    desc = character.get("description") or character.get("appearance", "")
    anchors = character.get("visualAnchors", {})
    hint = character.get("visualHint", "")

    # Use explicit gender field (fall back to text search for old format)
    if character.get("gender") == "female":
        gender_tag = "1girl"
    elif character.get("gender") == "male":
        gender_tag = "1man, mature male"
    else:
        is_female = "女" in desc[:80] or "女性" in desc[:80]
        gender_tag = "1girl" if is_female else "1man, mature male"

    base = (
        f"{QUALITY_TAGS}, "
        f"{gender_tag}, "
        "solo, full body, standing, front view, character reference sheet, "
        "white background, simple background, "
        "detailed clothing, detailed face, detailed eyes, "
    )

    # Inject ALL visual anchors — support both key naming conventions
    anchor_parts = []
    for old_key, new_key in [("face", "face_shape"), ("hair", "hair_eyes"), 
                               ("body", "build_posture"), ("clothing", "clothing"),
                               ("signature", "distinctive")]:
        val = anchors.get(old_key, "") or anchors.get(new_key, "")
        if val and val != "无特殊":
            anchor_parts.append(val)

    if anchor_parts:
        visual = ", ".join(anchor_parts)
    else:
        sentences = [s.strip() for s in desc.replace("，", ",").split("。") if len(s.strip()) > 10]
        visual = ", ".join(sentences[:6])

    prompt = base + visual

    if hint:
        prompt += f", ({hint})"

    return prompt


def build_workflow(checkpoint: str, positive: str, width: int = 1280, height: int = 1280, seed: int = None, style: str = "anime") -> dict:
    """Build T2I workflow. Dispatches to Flux or SDXL based on style."""
    if style == "realistic":
        return build_flux_workflow(positive, width, height, seed)
    else:
        return build_sdxl_workflow(checkpoint, positive, width, height, seed)


def build_flux_workflow(positive: str, width: int = 1280, height: int = 1280, seed: int = None) -> dict:
    """Build Flux.1 Dev FP8 T2I workflow.
    
    Flux uses:
      - DualCLIPLoader (clip_l + t5xxl)
      - FluxGuidance (guidance scale, replaces CFG in KSampler)
      - KSampler with cfg=1.0 (Flux handles guidance internally)
      - UNETLoader for fp8 unet
    """
    import random
    if seed is None:
        seed = random.randint(0, 2**32 - 1)
    
    return {
        # Load CLIP (dual: clip_l + t5xxl)
        "10": {
            "class_type": "DualCLIPLoader",
            "inputs": {
                "clip_name1": "clip_l.safetensors",
                "clip_name2": "t5xxl_fp8_e4m3fn_scaled.safetensors",
                "type": "flux",
            }
        },
        # Load UNet (Flux.1 Dev FP8)
        "11": {
            "class_type": "UNETLoader",
            "inputs": {
                "unet_name": "flux1-dev-fp8.safetensors",
                "weight_dtype": "fp8_e4m3fn_fast",
            }
        },
        # Load VAE
        "12": {
            "class_type": "VAELoader",
            "inputs": {"vae_name": "ae.safetensors"}
        },
        # FluxGuidance (replaces CFG — Flux uses guidance internally)
        "13": {
            "class_type": "FluxGuidance",
            "inputs": {
                "guidance": 3.5,
                "conditioning": ["10", 0],  # Will be linked to CLIP encode
            }
        },
        # Encode positive prompt
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": positive, "clip": ["10", 0]}
        },
        # Empty negative (Flux doesn't use negative prompts)
        "7": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": "", "clip": ["10", 0]}
        },
        # Empty latent
        "5": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": width, "height": height, "batch_size": 1}
        },
        # KSampler (cfg=1.0 for Flux)
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed,
                "steps": 20,
                "cfg": 1.0,
                "sampler_name": "euler",
                "scheduler": "normal",
                "denoise": 1.0,
                "model": ["11", 0],
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["5", 0],
            }
        },
        # VAE Decode
        "8": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["3", 0], "vae": ["12", 0]}
        },
        # Save
        "9": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": "aicf_char", "images": ["8", 0]}
        },
    }


def build_sdxl_workflow(checkpoint: str, positive: str, width: int = 1280, height: int = 1280, seed: int = None) -> dict:
    """Build SDXL T2I workflow for character reference image (anime style)."""
    import random
    if seed is None:
        seed = random.randint(0, 2**32 - 1)

    return {
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed, "steps": 25, "cfg": 7.0,
                "sampler_name": "euler_ancestral", "scheduler": "normal",
                "denoise": 1.0, "model": ["4", 0],
                "positive": ["6", 0], "negative": ["7", 0],
                "latent_image": ["5", 0],
            }
        },
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": checkpoint}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": positive, "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": NEGATIVE_PROMPT, "clip": ["4", 1]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "aicf_char", "images": ["8", 0]}},
    }


# ═══════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="S3: Character Image Generation")
    parser.add_argument("--project", "-p", required=True, help="Project name")
    parser.add_argument("--style", default="anime", choices=["anime", "realistic"],
                        help="Image style: realistic=Flux.1 Dev, anime=Animagine XL SDXL")
    parser.add_argument("--character", "-c", help="Specific character name")
    parser.add_argument("--checkpoint", default=None,
                        help="Override checkpoint (auto-selected by --style)")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=1280)
    parser.add_argument("--prompt", help="Override prompt (skip build_char_prompt)")
    parser.add_argument("--prompts-file", help="Path to pre-generated prompts JSON")
    args = parser.parse_args()

    # Auto-select checkpoint based on style
    if args.checkpoint is None:
        if args.style == "anime":
            args.checkpoint = "animagine-xl-3.1.safetensors"
        else:
            args.checkpoint = "flux"  # Flux uses UNETLoader, not CheckpointLoader

    project_dir = Path(__file__).parent.parent / "projects" / args.project
    chars_path = project_dir / "s2_characters.json"

    if not chars_path.exists():
        print(f"ERROR: {chars_path} not found. Run S2 first.")
        sys.exit(1)

    with open(chars_path) as f:
        data = json.load(f)

    characters = data.get("characters", [])
    if args.character:
        characters = [c for c in characters if c["name"] == args.character]

    sm = get_state_manager()
    sm.mark_running(args.project, "s3_character_image", remaining=len(characters))

    ref_dir = project_dir / "s3_character_refs"
    ref_dir.mkdir(parents=True, exist_ok=True)

    session = ComfyUISession()
    results = {}

    for i, char in enumerate(characters):
        name = char["name"]
        hint = char.get("visualHint", "")

        if args.prompts_file:
            prompts_data = json.loads(open(args.prompts_file).read())
            prompt = prompts_data.get("s3_character_prompts", {}).get(name, "")
            if not prompt:
                print(f"  ⚠️ No prompt for {name} in prompts file, skipping")
                continue
        elif args.prompt:
            prompt = args.prompt
        else:
            prompt = build_char_prompt(char)

        print(f"\nCharacter {i+1}/{len(characters)}: {name} ({hint})")
        print(f"  Prompt ({len(prompt)}c): {prompt[:120]}...")

        try:
            workflow = build_workflow(args.checkpoint, prompt, args.width, args.height, style=args.style)
            prefix = f"aicf_{args.project}_{name}"
            workflow["9"]["inputs"]["filename_prefix"] = prefix

            result = session.run(workflow, timeout=300)

            output_dir = Path.home() / "ComfyUI" / "output"
            files = sorted(output_dir.glob(f"{prefix}_*.png"), key=lambda p: p.stat().st_mtime, reverse=True)

            if files:
                am = get_asset_manager()
                am.register(
                    project=args.project, asset_type="character_ref",
                    shot_id=name, source_path=files[0], relative_dir="s3_character_refs",
                    dest_name=f"{name}.png",
                    metadata={"character": name, "checkpoint": args.checkpoint,
                              "resolution": f"{args.width}x{args.height}", "prompt": prompt[:200]}
                )
                dest = ref_dir / f"{name}.png"
                if dest.exists():
                    print(f"  ✅ {dest} ({dest.stat().st_size//1024}KB)")
                results[name] = str(dest)
            else:
                print(f"  ⚠️ No output file found")
                results[name] = "ERROR: no output"
        except ComfyUIError as e:
            print(f"  ❌ {e}")
            results[name] = f"ERROR: {e}"

    # Save manifest with prompts for reproducibility
    manifest = {
        "project": args.project, "checkpoint": args.checkpoint,
        "resolution": f"{args.width}x{args.height}",
        "characters": results,
    }
    with open(ref_dir / "manifest.json", "w") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    completed = sum(1 for v in results.values() if not v.startswith("ERROR"))
    sm.mark_completed(args.project, "s3_character_image",
                      generated=f"{completed}/{len(characters)}",
                      chars=",".join(results.keys()))

    print(f"\n{'='*60}")
    print(f"S3 Complete: {completed}/{len(characters)} characters generated")


if __name__ == "__main__":
    main()
