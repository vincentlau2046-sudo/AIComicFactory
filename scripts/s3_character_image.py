#!/usr/bin/env python3
"""
scripts/s3_character_image.py — Stage 3a: 角色参考图生成

从 s2_characters.json 读取角色描述，生成正面全身参考图。
支持三风格路径：
  --style vivid    (xuebiMIX，鲜亮动漫，默认)
  --style classic  (Animagine XL 3.1，经典动漫)
  --style concept  (JuggernautXL，写实概念)

Prompt 由 OpenClaw (Nova) 生成并注入，脚本只负责 ComfyUI 调用。

用法:
    python scripts/s3_character_image.py --project last_bento
    python scripts/s3_character_image.py --project last_bento --style classic
    python scripts/s3_character_image.py --project last_bento --style concept
    python scripts/s3_character_image.py --project last_bento --character 老周
"""

import json
import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.comfyui_session import ComfyUISession, ComfyUIError
from core.state_manager import get_state_manager
from core.character_image_check import CharacterImageChecker
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

classic_quality = "masterpiece, best quality, very aesthetic, highres, detailed"


def build_char_prompt(character: dict, style: str = "vivid") -> str:
    """Build T2I prompt from character visualAnchors.
    
    风格映射 (方案 A):
      vivid   - xuebiMIX 鲜亮动漫 (默认), Danbooru tags + vivid colors
      classic - Animagine XL 经典动漫, Danbooru tags + year/quality
      concept - JuggernautXL 写实概念, 自然语言 CG render
    """
    desc = character.get("description") or character.get("appearance", "")
    anchors = character.get("visualAnchors", {})
    hint = character.get("visualHint", "")
    combined_text = f"{desc} {hint}"

    if style == "concept":
        return _build_concept_prompt(character, desc, anchors, hint, combined_text)
    elif style == "classic":
        return _build_classic_prompt(character, desc, anchors, hint, combined_text)
    else:
        return _build_vivid_prompt(character, desc, anchors, hint, combined_text)


def _build_concept_prompt(character, desc, anchors, hint, combined_text):
    """CG render style (JuggernautXL SDXL base). 
    
    Key difference from anime: uses photorealism tags + detailed age/feature descriptors
    to avoid the 'everyone looks like a handsome young idol' problem.
    """
    # Age — use stronger descriptors for older characters
    age_visual = ""
    for kw, tag in [
        (["老年", "老头", "退休", "爷爷", "年老", "6[0-9]岁"], "elderly, wrinkled face, weathered skin"),
        (["中年", "师傅", "工头", "大姐", "阿姨", "大叔", "4[0-9]岁", "5[0-9]岁", "鱼尾纹", "灰白", "发际线后退"], "middle-aged, mature face, laugh lines, crow's feet"),
        (["年轻", "小伙", "青年", "2[0-9]岁", "新手", "大学生", "学生", "清澈"], "young adult"),
    ]:
        if any(k in combined_text for k in kw):
            age_visual = tag
            break
    
    # Gender
    if character.get("gender") == "female":
        gender_term = "woman"
    elif character.get("gender") == "male":
        gender_term = "man"
    else:
        gender_term = "woman" if ("女" in combined_text[:80] or "女性" in combined_text[:80]) else "man"
    
    age_prefix = f"{age_visual}, " if age_visual else ""
    
    # Build visual details from anchors
    face = anchors.get("face", "").replace("，", ", ")
    hair = anchors.get("hair", "").replace("，", ", ")
    body = anchors.get("body", "").replace("，", ", ")
    clothing = anchors.get("clothing", "").replace("，", ", ")
    
    # Build prompt: CG style + realistic details
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


def _build_vivid_prompt(character, desc, anchors, hint, combined_text):
    """xuebiMIX vibrant anime style. Similar to anime but with xuebi-specific quality tags."""
    # xuebiMIX quality tags
    vivid_quality = "masterpiece, best quality, very aesthetic, ultra detailed, highres"
    
    age_tags = ""
    for kw, tag in [
        (["老年", "老头", "退休", "爷爷", "年老", "6[0-9]岁"], "old"),
        (["中年", "师傅", "工头", "大姐", "阿姨", "大叔", "4[0-9]岁", "5[0-9]岁", "鱼尾纹", "灰白", "发际线后退"], "mature"),
        (["年轻", "小伙", "青年", "2[0-9]岁", "新手", "大学生", "学生", "清澈"], "young"),
    ]:
        if any(k in combined_text for k in kw):
            age_tags = {"old": "old, elderly", "mature": "mature, middle-aged", "young": "young"}.get(tag, "")
            break

    if character.get("gender") == "female":
        gender_tag = f"1girl, {age_tags}" if age_tags else "1girl"
    elif character.get("gender") == "male":
        gender_tag = f"1man, {age_tags}" if age_tags else "1man"
    else:
        is_female = "女" in combined_text[:80] or "女性" in combined_text[:80]
        base_gender = "1girl" if is_female else "1man"
        gender_tag = f"{base_gender}, {age_tags}" if age_tags else base_gender

    base = (
        f"{vivid_quality}, "
        f"{gender_tag}, "
        "solo, full body, standing, front view, character reference sheet, "
        "white background, simple background, vivid colors, detailed eyes"
    )
    return _inject_anchors(base, anchors, desc, hint)


def _build_classic_prompt(character, desc, anchors, hint, combined_text):
    """SDXL/Danbooru tag style prompt."""
    age_tags = ""
    for kw, tag in [
        (["老年", "老头", "退休", "爷爷", "年老", "6[0-9]岁"], "old"),
        (["中年", "师傅", "工头", "大姐", "阿姨", "大叔", "4[0-9]岁", "5[0-9]岁", "鱼尾纹", "灰白", "发际线后退"], "mature"),
        (["年轻", "小伙", "青年", "2[0-9]岁", "新手", "大学生", "学生", "清澈"], "young"),
    ]:
        if any(k in combined_text for k in kw):
            age_tags = {"old": "old, elderly", "mature": "mature, middle-aged", "young": "young"}.get(tag, "")
            break

    if character.get("gender") == "female":
        gender_tag = f"1girl, {age_tags}" if age_tags else "1girl"
    elif character.get("gender") == "male":
        gender_tag = f"1man, {age_tags}" if age_tags else "1man"
    else:
        is_female = "女" in combined_text[:80] or "女性" in combined_text[:80]
        base_gender = "1girl" if is_female else "1man"
        gender_tag = f"{base_gender}, {age_tags}" if age_tags else base_gender

    base = (
        f"{classic_quality}, "
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


def build_workflow(checkpoint: str, positive: str, width: int = 1024, height: int = 1536, seed: int = None, style: str = "vivid") -> dict:
    """Build SDXL T2I workflow. All three styles use SDXL architecture."""
    return build_sdxl_workflow(checkpoint, positive, width, height, seed)


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
    parser.add_argument("--style", default="vivid", choices=["vivid", "classic", "concept"],
                        help="vivid=xuebiMIX (default), classic=Animagine XL, concept=JuggernautXL")
    parser.add_argument("--character", "-c", help="Specific character name")
    parser.add_argument("--checkpoint", default=None,
                        help="Override checkpoint (auto-selected by --style)")
    parser.add_argument("--width", type=int, default=1024)
    parser.add_argument("--height", type=int, default=1536)
    parser.add_argument("--prompt", help="Override prompt (skip build_char_prompt)")
    parser.add_argument("--prompts-file", help="Path to pre-generated prompts JSON")
    args = parser.parse_args()

    # Auto-select checkpoint based on style (方案 A: vivid/classic/concept)
    CHECKPOINT_MAP = {
        "vivid": "animexl_xuebiMIX_v60.safetensors",
        "classic": "animagine-xl-3.1.safetensors",
        "concept": "juggernautXL_v10.safetensors",
    }
    if args.checkpoint is None:
        args.checkpoint = CHECKPOINT_MAP.get(args.style, CHECKPOINT_MAP["vivid"])

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
            prompt = build_char_prompt(char, args.style)

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
                    # P1-2: VL 质检
                    checker = CharacterImageChecker()
                    vl_result = checker.check(str(dest), char)
                    icon = "✅" if vl_result["pass"] else "⚠️"
                    print(f"  VL质检: {icon} {vl_result['score']}/10 {vl_result['summary'][:60]}")
                    vl_result["generated_at"] = str(dest.stat().st_mtime)
                    vl_results_list.append(vl_result)
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
    # P1-2: Save VL quality report
    if vl_results_list:
        vl_report_path = ref_dir / "vl_quality_report.json"
        with open(vl_report_path, "w") as f:
            json.dump(vl_results_list, f, ensure_ascii=False, indent=2)
        print(f"\n  VL质检报告: {vl_report_path}")

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
