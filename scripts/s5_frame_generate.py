#!/usr/bin/env python3
"""
scripts/s5_frame_generate.py — Stage 5: 关键帧生成

从 s4_shots.json + s2_characters.json 读取分镜和角色数据，生成首帧/尾帧。
支持双风格路径：
  --style realistic (Flux.1 Dev FP8, 默认)
  --style anime     (Animagine XL 3.1, SDXL)

Prompt 由 OpenClaw (Nova) 生成并注入，脚本只负责 ComfyUI 调用。

用法:
    python scripts/s5_frame_generate.py --project last_bento
    python scripts/s5_frame_generate.py --project last_bento --style anime
    python scripts/s5_frame_generate.py --project last_bento --shot 1
    python scripts/s5_frame_generate.py --project last_bento --dry-run
"""

import json, sys, argparse, shutil, random, os
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
    "comic panel, crowd, duplicate, clone"
)

QUALITY_TAGS = "masterpiece, best quality, very aesthetic, highres, detailed, cinematic lighting, dramatic"


def build_frame_prompt(shot: dict, characters: list, frame_type: str = "first") -> str:
    """Build SDXL T2I prompt for frame generation.
    
    frame_type: "first" | "last"
    """
    parts = [QUALITY_TAGS]

    # Characters in this shot — inject visual anchors
    char_names = shot.get("characters", [])
    for cn in char_names:
        for c in characters:
            if c["name"] == cn:
                # Use explicit gender field, fall back to text search
                if c.get("gender") == "female":
                    parts.append("1girl")
                elif c.get("gender") == "male":
                    parts.append("1man, mature male")
                else:
                    desc = c.get("appearance") or c.get("description", "")
                    parts.append(f"1{'girl' if '女' in desc[:80] else 'man'}")
                hint = c.get("visualHint", "")
                if hint:
                    parts.append(f"({hint})")
                anchors = c.get("visualAnchors", {})
                # Support both AICB and our key naming conventions
                for old_key, new_key in [("face", "face_shape"), ("hair", "hair_eyes"),
                                          ("body", "build_posture"), ("clothing", "clothing"),
                                          ("signature", "distinctive")]:
                    val = anchors.get(old_key, "") or anchors.get(new_key, "")
                    if val and val != "无特殊":
                        parts.append(val)

    if not char_names:
        parts.append("scenery, no humans, landscape")

    # Shot-level scene description (support both 'prompt' and 'description' keys)
    shot_prompt = shot.get("prompt") or shot.get("description", "")
    if shot_prompt:
        parts.append(shot_prompt)

    # Frame type specific
    if frame_type == "last":
        motion = shot.get("motionScript", "")
        if motion:
            parts.append("end of motion sequence")

    # Composition guide
    comp = shot.get("compositionGuide", "")
    comp_map = {
        "rule_of_thirds": "rule of thirds composition",
        "symmetric": "symmetric composition",
        "diagonal": "diagonal composition",
        "leading_lines": "leading lines composition",
        "framing": "framing composition",
        "close_up": "close-up shot",
        "over_shoulder": "over the shoulder shot",
    }
    if comp:
        parts.append(comp_map.get(comp, comp))

    # Depth of field
    dof = shot.get("depthOfField", "")
    if dof == "shallow":
        parts.append("shallow depth of field, bokeh")
    elif dof == "deep":
        parts.append("deep focus, everything sharp")

    # Camera direction
    camera = shot.get("cameraDirection", "")
    if camera and camera != "static":
        parts.append(f"{camera} camera")

    parts.append("16:9 aspect ratio, widescreen, landscape orientation")

    return ", ".join(parts)


def build_sdxl_workflow(checkpoint, positive, width=1280, height=720, seed=None, steps=25, cfg=7.0):
    if seed is None:
        seed = random.randint(0, 2**32 - 1)
    return {
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": checkpoint}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": positive, "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": NEGATIVE_PROMPT, "clip": ["4", 1]}},
        "3": {"class_type": "KSampler", "inputs": {
            "seed": seed, "steps": steps, "cfg": cfg,
            "sampler_name": "euler_ancestral", "scheduler": "normal",
            "denoise": 1.0, "model": ["4", 0],
            "positive": ["6", 0], "negative": ["7", 0],
            "latent_image": ["5", 0]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "aicf_frame", "images": ["8", 0]}},
    }


def build_flux_workflow(positive, width=1280, height=720, seed=None, steps=20, guidance=3.5):
    """Build Flux.1 Dev FP8 T2I workflow."""
    if seed is None:
        seed = random.randint(0, 2**32 - 1)
    return {
        "10": {"class_type": "DualCLIPLoader", "inputs": {
            "clip_name1": "clip_l.safetensors",
            "clip_name2": "t5xxl_fp8_e4m3fn_scaled.safetensors",
            "type": "flux"}},
        "11": {"class_type": "UNETLoader", "inputs": {
            "unet_name": "flux1-dev-fp8.safetensors",
            "weight_dtype": "fp8_e4m3fn_fast"}},
        "12": {"class_type": "VAELoader", "inputs": {"vae_name": "ae.safetensors"}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": positive, "clip": ["10", 0]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["10", 0]}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
        "3": {"class_type": "KSampler", "inputs": {
            "seed": seed, "steps": steps, "cfg": 1.0,
            "sampler_name": "euler", "scheduler": "normal",
            "denoise": 1.0, "model": ["11", 0],
            "positive": ["6", 0], "negative": ["7", 0],
            "latent_image": ["5", 0]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["12", 0]}},
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "aicf_frame", "images": ["8", 0]}},
    }


def generate_frame(sess, prompt, shot_num, frame_type, project, output_dir,
                   style="anime", checkpoint="animagine-xl-3.1.safetensors",
                   width=1280, height=720, steps=25, cfg=7.0, seed=None, max_retries=2):
    for attempt in range(max_retries + 1):
        s = seed if seed is not None else random.randint(0, 2**32 - 1)
        if style == "realistic":
            wf = build_flux_workflow(prompt, width, height, s, steps=steps, guidance=3.5)
        else:
            wf = build_sdxl_workflow(checkpoint, prompt, width, height, s, steps, cfg)
        prefix = f"aicf_{project}_s{shot_num:02d}_{frame_type}"
        wf["9"]["inputs"]["filename_prefix"] = prefix

        try:
            result = sess.run(wf, timeout=300)
            files = sorted(Path.home().glob(f"ComfyUI/output/{prefix}_*.png"),
                          key=lambda x: x.stat().st_mtime, reverse=True)
            if files:
                # Register asset (copy + metadata + cleanup old)
                am = get_asset_manager()
                am.register(project=project, asset_type=f"{frame_type}_frame",
                           shot_id=f"shot_{shot_num:03d}", source_path=files[0],
                           relative_dir="s5_frames",
                           dest_name=f"s{shot_num:02d}_{frame_type}.png",
                           metadata={"prompt": prompt[:200], "seed": s, "checkpoint": checkpoint})

                dest = output_dir / f"s{shot_num:02d}_{frame_type}.png"
                from PIL import Image as PILImage
                img = PILImage.open(str(dest))
                avg = sum(img.convert('L').getdata()) / (img.width * img.height)
                if avg < 5.0:
                    print(f"    ⚠️ Dark image (brightness={avg:.1f}), retry {attempt+1}/{max_retries}")
                    dest.unlink(missing_ok=True)
                    continue

                print(f"    ✅ s{shot_num:02d}_{frame_type}.png ({dest.stat().st_size//1024}KB, brightness={avg:.0f})")
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
    p = argparse.ArgumentParser(description="S5: 关键帧生成 (SDXL T2I)")
    p.add_argument("--style", default="anime", choices=["anime", "realistic"],
                   help="Image style: realistic=Flux.1 Dev, anime=Animagine XL SDXL")
    p.add_argument("--project", "-P", required=True)
    p.add_argument("--shot", "-s", type=int, help="Only generate specified shot number")
    p.add_argument("--mode", default="both", choices=["first", "last", "both"])
    p.add_argument("--checkpoint", default="animagine-xl-3.1.safetensors",
                   help="SDXL checkpoint (only used with --style anime)")
    p.add_argument("--prompts-file", help="Path to pre-generated frame prompts JSON")
    p.add_argument("--steps", type=int, default=25)
    p.add_argument("--cfg", type=float, default=7.0)
    p.add_argument("--width", type=int, default=1280)
    p.add_argument("--height", type=int, default=720)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    pd = Path(__file__).parent.parent / "projects" / args.project
    s4 = json.load(open(pd / "s4_shots.json"))
    s2 = json.load(open(pd / "s2_characters.json"))
    chars = s2["characters"]

    # Flatten shots — support both nested and flat formats
    shots = []
    if "scenes" in s4:
        for sc in s4["scenes"]:
            for sh in sc["shots"]:
                shots.append(sh)
    else:
        shots = s4.get("shots", [])
    if args.shot:
        shots = [s for s in shots if s["shotNumber"] == args.shot]

    if args.dry_run:
        fp = {}
        if args.prompts_file:
            fp = json.loads(open(args.prompts_file).read()).get("s5_frame_prompts", {})
        for s in shots:
            n = s["shotNumber"]
            pp_first = fp.get(f"s{n:02d}_first") if fp else build_frame_prompt(s, chars, "first")
            pp_last = fp.get(f"s{n:02d}_last") if fp else build_frame_prompt(s, chars, "last")
            chars_str = ','.join(s.get('characters', []))
            print(f"Shot {n:2d} ({chars_str}): first={len(pp_first)}c, last={len(pp_last)}c")
        return

    sm = get_state_manager()
    sm.mark_running(args.project, "s5_frame_generate", remaining=len(shots))
    out = pd / "s5_frames"
    out.mkdir(parents=True, exist_ok=True)
    sess = ComfyUISession()

    total_ok = 0
    total = len(shots) * (2 if args.mode == "both" else 1)

    # Load pre-generated prompts if provided
    frame_prompts = {}
    if args.prompts_file:
        frame_prompts = json.loads(open(args.prompts_file).read()).get("s5_frame_prompts", {})

    for i, s in enumerate(shots):
        n = s["shotNumber"]
        chars_in_shot = s.get("characters", [])
        print(f"\n[{i+1}/{len(shots)}] Shot {n} | chars={chars_in_shot} | {s.get('cameraDirection','')}")

        if args.mode in ("first", "both"):
            pp_key = f"s{n:02d}_first"
            pp = frame_prompts.get(pp_key) if frame_prompts else build_frame_prompt(s, chars, "first")
            print(f"  First ({len(pp)}c): {pp[:100]}...")
            if generate_frame(sess, pp, n, "first", args.project, out,
                              style=args.style, checkpoint=args.checkpoint,
                              steps=args.steps, cfg=args.cfg,
                              width=args.width, height=args.height):
                total_ok += 1

        if args.mode in ("last", "both"):
            pp_key = f"s{n:02d}_last"
            pp_last = frame_prompts.get(pp_key) if frame_prompts else build_frame_prompt(s, chars, "last")
            print(f"  Last  ({len(pp_last)}c): {pp_last[:100]}...")
            if generate_frame(sess, pp_last, n, "last", args.project, out,
                              style=args.style, checkpoint=args.checkpoint,
                              steps=args.steps, cfg=args.cfg,
                              width=args.width, height=args.height):
                total_ok += 1

    sm.mark_completed(args.project, "s5_frame_generate", generated=f"{total_ok}/{total}")
    print(f"\n{'='*60}")
    print(f"S5 Complete: {total_ok}/{total} frames")


if __name__ == "__main__":
    main()
