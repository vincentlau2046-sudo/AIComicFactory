#!/usr/bin/env python3
"""
scripts/s3_character_image.py — Stage 3: 角色参考图生成

三种生成模式:
  --gen flux    (Flux Dev fp8 T2I，单正面参考图，默认)
  --gen t2i     (SDXL T2I，单正面参考图，旧版)
  --gen qedit   (qwen-image-edit ReferenceLatent，四视角)

SDXL T2I 风格 (仅 --gen t2i 时生效):
  --style vivid    (xuebiMIX，鲜亮动漫)
  --style classic  (Animagine XL 3.1，经典动漫，默认)
  --style concept  (JuggernautXL，写实概念)

用法:
    python scripts/s3_character_image.py --project last_bento
    python scripts/s3_character_image.py --project last_bento --gen qedit
    python scripts/s3_character_image.py --project last_bento --gen qedit --character 老周
    python scripts/s3_character_image.py --project last_bento --gen t2i --style classic
"""

import json
import sys
import argparse
import shutil
import random
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.stdout.reconfigure(line_buffering=True)

from core.comfyui_session import ComfyUISession, ComfyUIError
from core.state_manager import get_state_manager
from core.character_image_check import CharacterImageChecker
from core.asset_manager import get_asset_manager
from core.demographics import infer_gender, infer_age, infer_gender_tag, infer_concept_gender
from core.workflow_loader import load_workflow, inject_params

# ═══════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════

NEGATIVE_PROMPT = (
    "low quality, worst quality, bad anatomy, bad hands, missing fingers, "
    "extra fingers, fused fingers, ugly, deformed, blurry, watermark, "
    "text, signature, cropped, out of frame, multiple views, split screen, "
    "comic panel, multiple people, group, crowd, duplicate, clone"
)

CLASSIC_QUALITY = "masterpiece, best quality, very aesthetic, highres, detailed"
VIVID_QUALITY = "masterpiece, best quality, very aesthetic, ultra detailed, highres, vivid colors"

MAX_VL_RETRIES = 2  # VL 质检不通过时最大重试次数

# Flux Dev T2I uses node "18" for SaveImage (vs "9" in SDXL)
FLUX_SAVE_NODE = "18"
SDXL_SAVE_NODE = "9"


# ═══════════════════════════════════════════════════════════════════
# Prompt builders — T2I (风格映射方案 A)
# ═══════════════════════════════════════════════════════════════════

def build_char_prompt(character: dict, style: str = "vivid") -> str:
    """Build T2I prompt from character visualAnchors."""
    desc = character.get("description") or character.get("appearance", "")
    anchors = character.get("visualAnchors", {})
    hint = character.get("visualHint", "")
    combined_text = f"{desc} {hint}"
    gender_field = character.get("gender")

    if style == "concept":
        return _build_concept_prompt(character, desc, anchors, hint, combined_text, gender_field)
    elif style == "classic":
        return _build_classic_prompt(character, desc, anchors, hint, combined_text, gender_field)
    else:
        return _build_vivid_prompt(character, desc, anchors, hint, combined_text, gender_field)


def _build_concept_prompt(character, desc, anchors, hint, combined_text, gender_field):
    """CG render style (JuggernautXL SDXL base)."""
    _, age_visual = infer_age(combined_text)
    gender_term = infer_concept_gender(combined_text, gender_field)
    age_prefix = f"{age_visual}, " if age_visual else ""
    
    face = anchors.get("face", "").replace("，", ", ")
    hair = anchors.get("hair", "").replace("，", ", ")
    body = anchors.get("body", "").replace("，", ", ")
    clothing = anchors.get("clothing", "").replace("，", ", ")
    
    prompt = (
        f"CG render, character concept art, character reference sheet, "
        f"{age_prefix}Chinese {gender_term}, full body, standing, front view, "
        f"plain white background. "
        f"Face: {face}. Hair: {hair}. "
        f"Body: {body}. Clothing: {clothing}. "
        f"Style: semi-realistic CG, detailed character design, "
        f"high quality, 8k, sharp focus. "
        f"{hint}"
    )
    return prompt


def _build_vivid_prompt(character, desc, anchors, hint, combined_text, gender_field):
    """xuebiMIX vibrant anime style."""
    _, age_tag = infer_age(combined_text)
    gender_tag = infer_gender_tag(combined_text, gender_field, age_tag)

    base = (
        f"{VIVID_QUALITY}, "
        f"{gender_tag}, "
        "solo, full body, standing, front view, character reference sheet, "
        "white background, simple background, vivid colors, detailed eyes"
    )
    return _inject_anchors(base, anchors, desc, hint)


def _build_classic_prompt(character, desc, anchors, hint, combined_text, gender_field):
    """SDXL/Danbooru tag style prompt."""
    _, age_tag = infer_age(combined_text)
    gender_tag = infer_gender_tag(combined_text, gender_field, age_tag)

    base = (
        f"{CLASSIC_QUALITY}, "
        f"{gender_tag}, "
        "solo, full body, standing, front view, character reference sheet, "
        "white background, simple background"
    )
    return _inject_anchors(base, anchors, desc, hint)


def _inject_anchors(base, anchors, desc, hint):
    """Inject visual anchors into prompt."""
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

    prompt = base + ", " + visual
    if hint:
        prompt += f", ({hint})"
    return prompt


# ═══════════════════════════════════════════════════════════════════
# Flux Dev T2I prompt builder (自然语言, 非 Danbooru 标签)
# ═══════════════════════════════════════════════════════════════════

def build_flux_dev_prompt(character: dict) -> str:
    """Build natural language prompt for Flux Dev T2I character reference.
    
    Unlike SDXL prompts which use Danbooru-style tags, Flux Dev works
    best with natural language descriptions.
    
    Key insight: Flux Dev gives excessive weight to background instructions.
    For character reference images, we need to:
    1. Put character description FIRST and in detail
    2. Use minimal background instruction (neutral gray, not white)
    3. Emphasize the figure fills the frame
    """
    desc = character.get("description") or character.get("appearance", "")
    anchors = character.get("visualAnchors", {})
    hint = character.get("visualHint", "")
    name = character.get("name", "")
    gender_field = character.get("gender")
    combined_text = f"{desc} {hint}"
    
    # Infer demographics
    gender = infer_gender(combined_text, gender_field)
    _, age_visual = infer_age(combined_text)
    
    # ── CHARACTER-FIRST structure ──
    # Start with the most important: who is this person, what do they look like
    char_parts = []
    
    # Core identity
    identity = f"Full body portrait of a character named {name}"
    demo_parts = []
    if age_visual:
        demo_parts.append(age_visual)
    if gender:
        demo_parts.append(gender)
    if demo_parts:
        identity += f", {', '.join(demo_parts)}"
    char_parts.append(identity + ".")
    
    # Face & expression — most critical for reference
    face_parts = []
    if anchors.get("face"):
        face_parts.append(anchors["face"])
    if anchors.get("hair"):
        face_parts.append(anchors["hair"])
    if face_parts:
        char_parts.append(f"Face and head: {', '.join(face_parts)}. Looking directly at camera with neutral expression.")
    else:
        char_parts.append("Looking directly at camera with neutral expression.")
    
    # Body & clothing — second most important
    body_parts = []
    if anchors.get("body"):
        body_parts.append(anchors["body"])
    if anchors.get("clothing"):
        body_parts.append(anchors["clothing"])
    if body_parts:
        char_parts.append(f"Body and outfit: {', '.join(body_parts)}.")
    
    if anchors.get("signature"):
        char_parts.append(f"Signature detail: {anchors['signature']}.")
    
    # Visual hint
    if hint:
        char_parts.append(f"Distinctive feature: {hint}.")
    
    # Pose — fill the frame
    char_parts.append("Standing straight, facing forward, arms at sides. The figure fills most of the frame from head to toe.")
    
    # Style
    style_str = "detailed, high quality"
    if desc:
        desc_lower = desc.lower()
        if any(kw in desc_lower for kw in ["写实", "realistic", "photorealistic"]):
            style_str = "photorealistic, cinematic lighting, sharp focus, high detail"
        elif any(kw in desc_lower for kw in ["动漫", "anime", "漫画", "manga"]):
            style_str = "anime illustration, vibrant colors, clean linework, detailed"
    char_parts.append(f"Style: {style_str}.")
    
    # Background — LAST and minimal (Flux over-weights background instructions)
    char_parts.append("Simple neutral gray background.")
    
    return " ".join(char_parts)


# ═══════════════════════════════════════════════════════════════════
# Flux Dev T2I workflow builder
# ═══════════════════════════════════════════════════════════════════

def build_flux_dev_workflow(positive: str, width: int = 1024, height: int = 1536,
                            seed: int = None, steps: int = 20, cfg: float = 1.0,
                            sampler: str = "euler", scheduler: str = "simple") -> dict:
    """Build Flux Dev fp8 T2I workflow from template.
    
    v2.0: Aligned with official ComfyUI Flux.1 Dev blueprint.
    - 20 steps euler/simple, cfg=1.0 (guidance-distilled model)
    - Negative uses ConditioningZeroOut (not separate CLIPTextEncode)
    - EmptySD3LatentImage (not EmptyLatentImage)
    """
    wf = load_workflow("flux_dev_t2i.json")
    return inject_params(wf, {
        "13": {"width": width, "height": height},
        "14": {"text": positive},
        "16": {
            "seed": seed if seed is not None else random.randint(0, 2**32 - 1),
            "steps": steps,
            "cfg": cfg,
            "sampler_name": sampler,
            "scheduler": scheduler,
        },
        "18": {"filename_prefix": "aicf_char"},
    })


# ═══════════════════════════════════════════════════════════════════
# Qwen-Image-Edit 4-view (ReferenceLatent 工作流)
# ═══════════════════════════════════════════════════════════════════

QEDIT_VIEW_PROMPTS = {
    "front": "Front view portrait of the same character, facing directly at camera, neutral expression. Same clothing and appearance as the reference image.",
    "minus_angle": "Three-quarter left view of the same character, head turned 45 degrees to the left showing the left side of the face. Same clothing and appearance as the reference image.",
    "plus_angle": "Three-quarter right view of the same character, head turned 45 degrees to the right showing the right side of the face. Same clothing and appearance as the reference image.",
    "back": "Back view of the same character, seen from behind, showing the back of the head and body. Same clothing and appearance as the reference image.",
}


def build_qedit_view_prompt(character: dict, view: str) -> str:
    """Build qwen-image-edit prompt for a specific view."""
    base = QEDIT_VIEW_PROMPTS.get(view, QEDIT_VIEW_PROMPTS["front"])
    anchors = character.get("visualAnchors", {})
    hint = character.get("visualHint", "")

    details = []
    for key in ("face", "hair", "body", "clothing"):
        val = anchors.get(key, "")
        if val and val != "无特殊":
            details.append(val)
    if details:
        base += " " + ". ".join(details) + "."
    if hint:
        base += f" {hint}."
    return base


def build_qedit_workflow(ref_image: str, prompt: str, prefix: str,
                         seed: int = 42, steps: int = 4, cfg: float = 1.0) -> dict:
    """Build qwen-image-edit ReferenceLatent workflow from template.
    
    Template: templates/qwen_edit_four_view.json
    Key architecture: VAEEncode ref → ReferenceLatent → FluxKontextMultiReferenceLatentMethod
    Lightning LoRA 4-step, er_sde/beta sampler.
    
    IMPORTANT: ComfyUI must NOT run with --use-sage-attention!
    
    NOTE: Do NOT inject image1 into node 68 — the template already links
    image1 to node 41 (LoadImage) via ["41", 0]. Only inject the image
    filename into node 41's "image" field.
    """
    wf = load_workflow("qwen_edit_four_view.json")
    return inject_params(wf, {
        "41": {"image": ref_image},
        "68": {"prompt": prompt},
        "65": {"seed": seed, "steps": steps, "cfg": cfg},
        "60": {"filename_prefix": prefix},
    })


# ═══════════════════════════════════════════════════════════════════
# T2I Workflow builder (从模板加载)
# ═══════════════════════════════════════════════════════════════════

def build_workflow(checkpoint: str, positive: str, width: int = 1024, height: int = 1536, seed: int = None, style: str = "vivid", gen: str = "flux") -> dict:
    """Build T2I workflow. Delegates to Flux Dev or SDXL based on gen mode."""
    if gen == "flux":
        return build_flux_dev_workflow(positive, width, height, seed)
    
    # Legacy SDXL path
    if seed is None:
        seed = random.randint(0, 2**32 - 1)
    
    try:
        wf = load_workflow("t2i_character_ref.json")
        return inject_params(wf, {
            "4": {"ckpt_name": checkpoint},
            "5": {"width": width, "height": height, "batch_size": 1},
            "6": {"text": positive},
            "7": {"text": NEGATIVE_PROMPT},
            "3": {"seed": seed},
        })
    except FileNotFoundError:
        pass
    
    return build_sdxl_workflow(checkpoint, positive, width, height, seed)


def build_sdxl_workflow(checkpoint: str, positive: str, width: int = 1280, height: int = 1280, seed: int = None) -> dict:
    """Build SDXL T2I workflow for character reference image (fallback)."""
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
    parser.add_argument("--gen", default="flux", choices=["t2i", "qedit", "flux"],
                        help="flux=Flux Dev T2I (default), t2i=SDXL T2I legacy, qedit=qwen-image-edit 4-view")
    parser.add_argument("--style", default="classic", choices=["vivid", "classic", "concept"],
                        help="classic=Animagine XL (default), vivid=xuebiMIX, concept=JuggernautXL")
    parser.add_argument("--character", "-c", help="Specific character name")
    parser.add_argument("--checkpoint", default=None,
                        help="Override checkpoint (auto-selected by --style)")
    parser.add_argument("--width", type=int, default=1024)
    parser.add_argument("--height", type=int, default=1536)
    parser.add_argument("--prompt", help="Override prompt (skip build_char_prompt)")
    parser.add_argument("--prompts-file", help="Path to pre-generated prompts JSON")
    parser.add_argument("--no-check", action="store_true", help="Skip VL quality check")
    parser.add_argument("--max-vl-retries", type=int, default=MAX_VL_RETRIES,
                        help="Max VL quality check retries (default: 2)")
    parser.add_argument("--views", default="front,minus_angle,plus_angle,back",
                        help="Views to generate for --gen qedit (comma-separated)")
    args = parser.parse_args()

    if args.gen == "qedit":
        _run_qedit(args)
    else:
        _run_t2i(args)  # handles both flux and legacy t2i


# ═══════════════════════════════════════════════════════════════════
# _run_qedit — qwen-image-edit ReferenceLatent 四视角
# ═══════════════════════════════════════════════════════════════════

def _run_qedit(args):
    """Run qwen-image-edit ReferenceLatent 4-view generation.
    
    Prerequisites:
    - ComfyUI running WITHOUT --use-sage-attention (causes black output)
    - Reference images exist in s3_character_refs/ from prior --gen t2i run
    """
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

    views = [v.strip() for v in args.views.split(",")]
    ref_dir = project_dir / "s3_character_refs"
    ref_dir.mkdir(parents=True, exist_ok=True)

    sm = get_state_manager()
    total = len(characters) * len(views)
    sm.mark_running(args.project, "s3_character_image", remaining=total)

    session = ComfyUISession()
    results = {}

    for char in characters:
        name = char["name"]
        hint = char.get("visualHint", "")
        print(f"\nCharacter: {name} ({hint})")

        # Reference image must exist from prior T2I run or manual upload
        ref_img_path = ref_dir / f"{name}.png"
        if not ref_img_path.exists():
            print(f"  ❌ No reference image for {name} at {ref_img_path}")
            print(f"  → Run with --gen t2i first, or upload manually")
            for v in views:
                results[f"{name}_{v}"] = "ERROR: no ref image"
            continue

        # Upload ref image to ComfyUI input
        comfyui_input = Path.home() / "ComfyUI" / "input"
        ref_input_name = f"aicf_{args.project}_{name}_ref.png"
        shutil.copy2(str(ref_img_path), str(comfyui_input / ref_input_name))

        for view in views:
            print(f"  View: {view}")
            prompt = build_qedit_view_prompt(char, view)
            prefix = f"aicf_{args.project}_{name}_{view}"

            try:
                workflow = build_qedit_workflow(ref_input_name, prompt, prefix)
                result = session.run(workflow, timeout=300)

                output_dir = Path.home() / "ComfyUI" / "output"
                files = sorted(output_dir.glob(f"{prefix}_*.png"),
                              key=lambda p: p.stat().st_mtime, reverse=True)

                if files:
                    char_dir = ref_dir / name
                    char_dir.mkdir(parents=True, exist_ok=True)
                    dest = char_dir / f"{view}.png"
                    shutil.copy2(str(files[0]), str(dest))
                    print(f"    ✅ {name}/{dest.name} ({dest.stat().st_size//1024}KB)")
                    results[f"{name}_{view}"] = str(dest)
                else:
                    print(f"    ❌ No output")
                    results[f"{name}_{view}"] = "ERROR: no output"
            except ComfyUIError as e:
                print(f"    ❌ {e}")
                results[f"{name}_{view}"] = f"ERROR: {e}"

    # Save manifest
    manifest = {
        "project": args.project, "gen_mode": "qedit",
        "views": views, "characters": results,
        "structure": "per_character_dir",
    }
    with open(ref_dir / "manifest.json", "w") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    completed = sum(1 for v in results.values() if not v.startswith("ERROR"))
    sm.mark_completed(args.project, "s3_character_image",
                      generated=f"{completed}/{total}",
                      mode="qedit")
    print(f"\n{'='*60}")
    print(f"S3 qedit Complete: {completed}/{total} views generated")


# ═══════════════════════════════════════════════════════════════════
# _run_t2i — SDXL T2I 单正面参考图
# ═══════════════════════════════════════════════════════════════════

def _run_t2i(args):
    """Run T2I single-view character reference generation.
    
    Supports both Flux Dev (--gen flux, default) and legacy SDXL (--gen t2i).
    """
    # Flux Dev optimal params
    FLUX_STEPS = 20
    FLUX_CFG = 1.0
    FLUX_SAMPLER = "euler"
    FLUX_SCHEDULER = "simple"

    is_flux = (args.gen == "flux")
    
    # SDXL checkpoint selection (only used when gen=t2i)
    CHECKPOINT_MAP = {
        "vivid": "animexl_xuebiMIX_v60.safetensors",
        "classic": "animagine-xl-3.1.safetensors",
        "concept": "juggernautXL_v10.safetensors",
    }
    checkpoint = args.checkpoint
    if not is_flux and checkpoint is None:
        checkpoint = CHECKPOINT_MAP.get(args.style, CHECKPOINT_MAP["classic"])

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
    vl_results_list = []
    vl_available = not args.no_check

    # SaveImage node ID differs between Flux and SDXL
    save_node = FLUX_SAVE_NODE if is_flux else SDXL_SAVE_NODE

    # 预检 + 启动 VL 后端 (qw35-9b)
    if vl_available:
        print(f"\n  [VL] 启动 qw35-9b 后端 (用于质检)...")
        import subprocess, time
        try:
            result = subprocess.run(
                ["edge-llm", "switch", "qwen35-9b"],
                capture_output=True, text=True, timeout=180
            )
            if result.returncode != 0:
                print(f"  [VL] ⚠️ edge-llm switch qwen35-9b failed: {result.stderr[-200:]}")
                vl_available = False
            else:
                # 等待就绪 (最多 150s)
                print(f"  [VL] 等待 qw35-9b 就绪...")
                deadline = time.time() + 150
                import urllib.request
                while time.time() < deadline:
                    try:
                        urllib.request.urlopen("http://localhost:8002/health", timeout=3)
                        print(f"  [VL] ✅ qw35-9b 就绪")
                        break
                    except:
                        time.sleep(5)
                else:
                    print(f"  [VL] ⚠️ qw35-9b 启动超时，跳过质检")
                    vl_available = False
        except subprocess.TimeoutExpired:
            print(f"  [VL] ⚠️ edge-llm switch 超时，跳过质检")
            vl_available = False
        except Exception as e:
            print(f"  [VL] ⚠️ 启动失败: {e}")
            vl_available = False

    for i, char in enumerate(characters):
        name = char["name"]
        hint = char.get("visualHint", "")

        # Build prompt based on generation mode
        if args.prompts_file:
            prompts_data = json.loads(open(args.prompts_file).read())
            prompt = prompts_data.get("s3_character_prompts", {}).get(name, "")
            if not prompt:
                print(f"  ⚠️ No prompt for {name} in prompts file, skipping")
                continue
        elif args.prompt:
            prompt = args.prompt
        elif is_flux:
            prompt = build_flux_dev_prompt(char)
        else:
            prompt = build_char_prompt(char, args.style)

        print(f"\nCharacter {i+1}/{len(characters)}: {name} ({hint})")
        gen_label = "Flux Dev" if is_flux else f"SDXL/{args.style}"
        print(f"  Mode: {gen_label}")
        print(f"  Prompt ({len(prompt)}c): {prompt[:120]}...")

        for attempt in range(args.max_vl_retries + 1):
            try:
                workflow = build_workflow(
                    checkpoint or "", prompt, args.width, args.height,
                    style=args.style, gen=args.gen,
                )
                prefix = f"aicf_{args.project}_{name}"
                workflow[save_node]["inputs"]["filename_prefix"] = prefix

                result = session.run(workflow, timeout=300)

                output_dir = Path.home() / "ComfyUI" / "output"
                files = sorted(output_dir.glob(f"{prefix}_*.png"), key=lambda p: p.stat().st_mtime, reverse=True)

                if files:
                    # Per-character per-costume directory
                    char_dir = ref_dir / name
                    char_dir.mkdir(parents=True, exist_ok=True)
                    am = get_asset_manager()
                    am.register(
                        project=args.project, asset_type="character_ref",
                        shot_id=name, source_path=files[0], relative_dir=f"s3_character_refs/{name}",
                        dest_name="default.png",
                        metadata={"character": name, "costume_id": "default",
                                  "generator": "flux_dev" if is_flux else "sdxl",
                                  "checkpoint": checkpoint if not is_flux else "flux1-dev-fp8",
                                  "resolution": f"{args.width}x{args.height}", "prompt": prompt[:200],
                                  "attempt": attempt + 1}
                    )
                    dest = char_dir / "default.png"
                    if dest.exists():
                        print(f"  ✅ {dest} ({dest.stat().st_size//1024}KB)")
                        
                        if vl_available:
                            checker = CharacterImageChecker()
                            vl_result = checker.check(str(dest), char)
                            if not isinstance(vl_result, dict):
                                print(f"  ⚠️ VL质检返回异常类型: {type(vl_result)}, 跳过")
                                vl_result = {"pass": True, "score": 0, "summary": "VL返回异常"}
                            icon = "✅" if vl_result.get("pass", True) else "⚠️"
                            score = vl_result.get("score", "?")
                            summary = vl_result.get("summary", "")
                            print(f"  VL质检: {icon} {score}/10 {summary[:60]}")
                            vl_result["generated_at"] = str(dest.stat().st_mtime)
                            vl_result["attempt"] = attempt + 1
                            vl_results_list.append(vl_result)
                            
                            if vl_result.get("pass", True):
                                results[name] = str(dest)
                                break
                            elif attempt < args.max_vl_retries:
                                print(f"  → 质检未通过，重试 ({attempt+1}/{args.max_vl_retries})...")
                                continue
                            else:
                                print(f"  → 质检未通过，已达最大重试次数，保留当前图片")
                                results[name] = str(dest)
                        else:
                            results[name] = str(dest)
                            break  # VL disabled: success = done
                else:
                    print(f"  ⚠️ No output file found")
                    results[name] = "ERROR: no output"
            except ComfyUIError as e:
                print(f"  ❌ {e}")
                results[name] = f"ERROR: {e}"
                break

    manifest = {
        "project": args.project,
        "gen_mode": "flux" if is_flux else "t2i",
        "checkpoint": "flux1-dev-fp8" if is_flux else checkpoint,
        "resolution": f"{args.width}x{args.height}",
        "characters": results,
        "structure": "per_character_dir",
    }
    if vl_results_list:
        vl_report_path = ref_dir / "vl_quality_report.json"
        with open(vl_report_path, "w") as f:
            json.dump(vl_results_list, f, ensure_ascii=False, indent=2)
        print(f"\n  VL质检报告: {vl_report_path}")

        # 释放 qw35-9b
        print(f"  [VL] 释放 qw35-9b (edge-llm switch idle)...")
        try:
            subprocess.run(["edge-llm", "switch", "idle"],
                          capture_output=True, timeout=120)
            print(f"  [VL] ✅ qw35-9b 已释放")
        except Exception as e:
            print(f"  [VL] ⚠️ 释放失败: {e}")

    with open(ref_dir / "manifest.json", "w") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    completed = sum(1 for v in results.values() if not v.startswith("ERROR"))
    sm.mark_completed(args.project, "s3_character_image",
                      generated=f"{completed}/{len(characters)}",
                      chars=",".join(results.keys()))

    mode_label = "Flux Dev" if is_flux else "SDXL t2i"
    print(f"\n{'='*60}")
    print(f"S3 {mode_label} Complete: {completed}/{len(characters)} characters generated")


if __name__ == "__main__":
    main()
