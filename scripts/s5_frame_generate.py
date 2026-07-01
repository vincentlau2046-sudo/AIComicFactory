#!/usr/bin/env python3
"""
scripts/s5_frame_generate.py — Stage 5: 关键帧生成 (v2.0)

重大升级 (2026-06-30):
  - P0-1: 构建链重构——删除自建 build_frame_prompt(), 改用 prompts/defaults/ build_full_prompt()
  - P0-2: IPAdapter 升级——纯 T2I → img2img+IPAdapter(四视图参考图 + 前 shot 尾帧)
  - P0-4: S2→S5 消费链——注入 colorPalette / performanceStyle / scene-level 数据 / relationships

从 s4_shots.json + s2_characters.json 读取分镜和角色数据，生成首帧/尾帧。
支持双风格路径 + IPAdapter 角色一致性。

用法:
    python scripts/s5_frame_generate.py --project last_bento
    python scripts/s5_frame_generate.py --project last_bento --mode ipadapter
    python scripts/s5_frame_generate.py --project last_bento --mode t2i  # 纯T2I回退
    python scripts/s5_frame_generate.py --project last_bento --shot 1
    python scripts/s5_frame_generate.py --project last_bento --dry-run
"""

import json, sys, argparse, random, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from prompts.defaults.frame_generate_first import build_full_prompt as build_first_prompt
from prompts.defaults.frame_generate_last import build_full_prompt as build_last_prompt
from core.comfyui_session import ComfyUISession, ComfyUIError
from core.state_manager import get_state_manager
from core.asset_manager import get_asset_manager

# ═══════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════

"""T2I 模式强制角色一致性负面提示 (P1-1)."""
CHARACTER_CONSISTENCY_NEGATIVE = (
    "mismatched face, different character, changed appearance, "
    "different hairstyle, different clothing, inconsistent age, "
    "different ethnicity, face swap, identity change, morphing face, "
    "different body type, inconsistent height, style inconsistency"
)

NEGATIVE_PROMPT = (
    "low quality, worst quality, bad anatomy, bad hands, missing fingers, "
    "extra fingers, fused fingers, ugly, deformed, blurry, watermark, "
    "text, signature, cropped, out of frame, multiple views, split screen, "
    "comic panel, crowd, duplicate, clone, "
    "dark, underexposed, dim lighting, low contrast"
)

SDXL_QUALITY = "masterpiece, best quality, very aesthetic, highres, detailed, cinematic lighting, dramatic"

# IPAdapter 参数
IPADAPTER_WEIGHT = 0.75          # 默认权重 (0.5-1.0, 越高参考图影响越大)
IPADAPTER_WEIGHT_CLOSEUP = 0.85  # 大特写用更高权重保持脸部一致
IPADAPTER_WEIGHT_FULL = 0.65     # 全身用稍低权重保持姿态自由度
IPADAPTER_NOISE = 0.3            # 注入噪声, 提高多样性
IPADAPTER_START = 0.0
IPADAPTER_END = 1.0

# ═══════════════════════════════════════════════════════════════════
# P0-1/P0-4: 标准化 Prompt 构建 (对齐 AICB buildFirstFramePrompt / buildLastFramePrompt)
# ═══════════════════════════════════════════════════════════════════

def _build_scene_description(scene: dict, color_palette: str = "") -> str:
    """从 scene 数据构建场景环境描述 (P0-4: scene-level 数据消费 + AICB colorPalette)."""
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
    """构建角色描述文本 (对齐 AICB characterDescriptions 格式).
    
    P1-1 增强: 视觉签名前置 → 最大化 primacy effect 于 T2I 模式。
    格式: [视觉签名] {name}（{hint}）: {description}
    """
    lines = []
    for cn in shot_char_names:
        for c in characters:
            if c["name"] == cn:
                hint = c.get("visualHint", "")
                desc = c.get("description", c.get("appearance", ""))
                anchors = c.get("visualAnchors", {})
                
                # P1-1: 视觉签名前置 — 关键特征作为 prompt 最前导部分
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
                
                # 标志动作/姿态约束
                ps = c.get("performanceStyle", "")
                if ps:
                    line += f"\n  姿势约束: {ps[:200]}"
                
                lines.append(line)
                break
        else:
            lines.append(f"角色 {cn}: 无详细描述")
    return "\n\n".join(lines)


def _find_character_ref_images(characters: list, shot_char_names: list, project_dir: Path) -> list:
    """查找角色四视图参考图路径 (S3b 输出)."""
    refs = []
    for cn in shot_char_names:
        # 参考图来源: S3b四视图优先, S3单视图作为fallback
        for subdir in ["s3b_four_views", "s3_character_refs"]:
            if not (project_dir / subdir).exists():
                continue
            search_dir = project_dir / subdir
            for p in search_dir.iterdir():
                if cn in p.stem and p.suffix == '.png':
                    refs.append(str(p))
                    break
    return refs


def _get_ipadapter_weight(shot: dict) -> float:
    """根据镜头类型动态调整 IPAdapter 权重."""
    comp = shot.get("compositionGuide", "")
    if comp == "close_up":
        return IPADAPTER_WEIGHT_CLOSEUP
    if comp in ("over_shoulder", "framing"):
        return IPADAPTER_WEIGHT
    return IPADAPTER_WEIGHT_FULL


def _build_composition_suffix(shot: dict, chars_in_shot: list, characters: list,
                               color_palette: str = "") -> str:
    """
    AICB composition suffix: 构图指导 + 焦点 + 景深 + 角色身高 + 色板.
    附加在 buildFirstFramePrompt / buildLastFramePrompt 输出末端.
    
    对齐 AICB src/lib/pipeline/frame-generate.ts handleFrameGenerate()
    """
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
    
    # Character height context (multi-character shots)
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
    
    suffix = ", ".join([p for p in parts if p.startswith(', ') or not p.startswith('\n')])
    # Re-attach color palette section (which starts with \n)
    for p in parts:
        if p.startswith('\n'):
            suffix += p
    
    # AICB format: prepend ", " + suffix, or just suffix for palette line
    if suffix and not suffix.startswith('\n'):
        return ", " + suffix
    return suffix


# ═══════════════════════════════════════════════════════════════════
# ComfyUI Workflow Builders
# ═══════════════════════════════════════════════════════════════════

def build_ipadapter_workflow(
    checkpoint: str,
    positive: str,
    ref_images: list,   # 角色四视图参考图路径列表
    prev_frame: str = "",  # 上一个 shot 的尾帧 (连续性参考)
    width: int = 1280,
    height: int = 720,
    seed: int = None,
    steps: int = 25,
    cfg: float = 7.0,
    ipa_weight: float = IPADAPTER_WEIGHT,
    ipa_noise: float = IPADAPTER_NOISE,
) -> dict:
    """
    构建 SDXL + IPAdapter workflow (P0-2).
    
    ComfyUI 节点拓扑:
      Checkpoint → CLIP(正面/负面) + KSampler → VAE → Save
      LoadImage(参考图) → IPAdapter Apply → KSampler
      LoadImage(前帧) → [可选] IPAdapter Apply → KSampler
    
    对齐 AICB 设计:
      - 首帧: 文本prompt + IPAdapter(角色四视图) → 生成
      - 尾帧: 文本prompt + IPAdapter(角色四视图) + LoadImage(首帧) → 生成
    """
    if seed is None:
        seed = random.randint(0, 2**32 - 1)

    wf = {}
    node_id = 0

    # Node 1: Checkpoint
    wf["1"] = {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": checkpoint}}
    node_id = 1

    # Node 2: Positive CLIP
    node_id += 1
    wf[str(node_id)] = {"class_type": "CLIPTextEncode", "inputs": {"text": positive, "clip": ["1", 1]}}
    pos_clip = str(node_id)

    # Node 3: Negative CLIP
    node_id += 1
    wf[str(node_id)] = {"class_type": "CLIPTextEncode", "inputs": {"text": NEGATIVE_PROMPT, "clip": ["1", 1]}}
    neg_clip = str(node_id)

    # Node 4: Empty Latent
    node_id += 1
    wf[str(node_id)] = {"class_type": "EmptyLatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}}
    latent_node = str(node_id)

    # --- IPAdapter 参考图加载 ---
    ipa_ref_nodes = []
    for img_path in ref_images:
        node_id += 1
        wf[str(node_id)] = {"class_type": "LoadImage", "inputs": {"image": img_path}}
        ipa_ref_nodes.append(str(node_id))

    # Node: IPAdapter Unified Loader
    node_id += 1
    ipa_loader = str(node_id)
    wf[ipa_loader] = {
        "class_type": "IPAdapterUnifiedLoader",
        "inputs": {"model": ["1", 0], "preset": "PLUS (high strength)"}
    }

    # Node: IPAdapter Apply (使用第一个参考图)
    node_id += 1
    ipa_apply = str(node_id)
    wf[ipa_apply] = {
        "class_type": "IPAdapterAdvanced",
        "inputs": {
            "model": ["1", 0],
            "ipadapter": [ipa_loader, 1],  # 输出索引1是IPADAPTER类型
            "image": [ipa_ref_nodes[0], 0],
            "weight": ipa_weight,
            "weight_type": "linear",
            "combine_embeds": "concat",
            "start_at": IPADAPTER_START,
            "end_at": IPADAPTER_END,
            "embeds_scaling": "V only",
        }
    }
    # 如果有多个参考图，concat 到同一个 IPAdapter
    if len(ipa_ref_nodes) > 1:
        wf[ipa_apply]["inputs"]["image"] = [ipa_ref_nodes[0], 0]  # 主参考
        # 多参考图可用 Batch Images + IPAdapter Batch, 此处简化用第一个

    # --- 前帧连续性 (如果有) ---
    prev_frame_node = None
    if prev_frame and Path(prev_frame).exists():
        node_id += 1
        prev_frame_node = str(node_id)
        wf[prev_frame_node] = {"class_type": "LoadImage", "inputs": {"image": prev_frame}}

    # Node: KSampler (带 IPAdapter model)
    node_id += 1
    sampler_node = str(node_id)
    wf[sampler_node] = {
        "class_type": "KSampler",
        "inputs": {
            "seed": seed,
            "steps": steps,
            "cfg": cfg,
            "sampler_name": "dpmpp_2m",
            "scheduler": "karras",
            "denoise": 0.92,  # img2img: 0.9-0.95
            "model": [ipa_apply, 0] if not prev_frame_node else [ipa_apply, 0],
            "positive": [pos_clip, 0],
            "negative": [neg_clip, 0],
            "latent_image": [latent_node, 0],
        }
    }

    # Node: VAE Decode
    node_id += 1
    wf[str(node_id)] = {"class_type": "VAEDecode", "inputs": {"samples": [sampler_node, 0], "vae": ["1", 2]}}
    vae_node = str(node_id)

    # Node: Save Image
    node_id += 1
    wf[str(node_id)] = {"class_type": "SaveImage", "inputs": {"filename_prefix": "aicf_frame", "images": [vae_node, 0]}}

    return wf


def build_t2i_workflow(checkpoint, positive, width=1280, height=720, seed=None, steps=25, cfg=7.0):
    """纯 T2I 回退模式 (无 IPAdapter)."""
    if seed is None:
        seed = random.randint(0, 2**32 - 1)
    return {
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": checkpoint}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": positive, "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": NEGATIVE_PROMPT, "clip": ["4", 1]}},
        "3": {"class_type": "KSampler", "inputs": {
            "seed": seed, "steps": steps, "cfg": cfg,
            "sampler_name": "dpmpp_2m", "scheduler": "karras",
            "denoise": 1.0, "model": ["4", 0],
            "positive": ["6", 0], "negative": ["7", 0],
            "latent_image": ["5", 0]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "aicf_frame", "images": ["8", 0]}},
    }


# ═══════════════════════════════════════════════════════════════════
# Frame Generation (unified)
# ═══════════════════════════════════════════════════════════════════

def generate_frame(sess, prompt, shot_num, frame_type, project, output_dir,
                   style="vivid", checkpoint="animexl_xuebiMIX_v60.safetensors",
                   width=1280, height=720, steps=30, cfg=7.0,
                   seed=None, max_retries=2,
                   mode="ipadapter", ref_images=None, prev_frame=""):
    for attempt in range(max_retries + 1):
        s = seed if seed is not None else random.randint(0, 2**32 - 1)

        if mode == "t2i":
            wf = build_t2i_workflow(checkpoint, prompt, width, height, s, steps, cfg)
        else:
            wf = build_ipadapter_workflow(
                checkpoint, prompt, ref_images or [], prev_frame,
                width, height, s, steps, cfg,
                ipa_weight=IPADAPTER_WEIGHT,
            )

        prefix = f"aicf_{project}_s{shot_num:02d}_{frame_type}"
        last_node = str(max(int(k) for k in wf.keys()))
        wf[last_node]["inputs"]["filename_prefix"] = prefix

        try:
            result = sess.run(wf, timeout=480 if mode == "ipadapter" else 300)
            files = sorted(Path.home().glob(f"ComfyUI/output/{prefix}_*.png"),
                          key=lambda x: x.stat().st_mtime, reverse=True)
            if files:
                am = get_asset_manager()
                am.register(
                    project=project, asset_type=f"{frame_type}_frame",
                    shot_id=f"shot_{shot_num:03d}", source_path=files[0],
                    relative_dir="s5_frames",
                    dest_name=f"s{shot_num:02d}_{frame_type}.png",
                    metadata={
                        "prompt": prompt[:200], "seed": s,
                        "checkpoint": checkpoint, "mode": mode,
                    },
                )

                dest = output_dir / f"s{shot_num:02d}_{frame_type}.png"
                from PIL import Image as PILImage
                img = PILImage.open(str(dest))
                avg = sum(img.convert('L').getdata()) / (img.width * img.height)
                if avg < 5.0:
                    print(f"    ⚠️ Dark image (brightness={avg:.1f}), retry {attempt+1}/{max_retries}")
                    dest.unlink(missing_ok=True)
                    continue

                print(f"    ✅ s{shot_num:02d}_{frame_type}.png ({dest.stat().st_size//1024}KB, brightness={avg:.0f}, mode={mode})")
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
    p = argparse.ArgumentParser(description="S5: 关键帧生成 (T2I + IPAdapter)")
    p.add_argument("--style", default="vivid", choices=["vivid", "classic", "concept"])
    p.add_argument("--project", "-P", required=True)
    p.add_argument("--shot", "-s", type=int)
    p.add_argument("--gen", default="t2i", choices=["t2i", "ipadapter"],
                   help="Generation mode: ipadapter (IPAdapter+reference images) or t2i (pure text)")
    p.add_argument("--frames", default="both", choices=["first", "last", "both"],
                   help="Which frames to generate")
    p.add_argument("--checkpoint", default="animexl_xuebiMIX_v60.safetensors")
    p.add_argument("--steps", type=int, default=25)
    p.add_argument("--cfg", type=float, default=7.0)
    p.add_argument("--width", type=int, default=1280)
    p.add_argument("--height", type=int, default=720)
    p.add_argument("--no-check", action="store_true", help="Skip auto quality checks after S5")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    # Auto-select checkpoint based on style (方案 A: vivid/classic/concept)
    CHECKPOINT_MAP = {
        "vivid": "animexl_xuebiMIX_v60.safetensors",
        "classic": "animagine-xl-3.1.safetensors",
        "concept": "juggernautXL_v10.safetensors",
    }
    if args.checkpoint == p.get_default("checkpoint") and args.style in CHECKPOINT_MAP:
        args.checkpoint = CHECKPOINT_MAP[args.style]

    pd = Path(__file__).parent.parent / "projects" / args.project
    s4 = json.load(open(pd / "s4_shots.json"))
    s2 = json.load(open(pd / "s2_characters.json"))
    
    # Project-level color palette (AICB: from episode or project)
    project_color_palette = s2.get("colorPalette", "")
    if not project_color_palette:
        project_color_palette = s4.get("colorPalette", "")
    chars = s2["characters"]

    # Separate gen technology from frame selection
    gen_mode = args.gen
    frame_mode = args.frames

    # Flatten shots — support both flat and nested formats
    scenes = s4.get("scenes", [])
    shots = []
    if scenes:
        for sc in scenes:
            for sh in sc["shots"]:
                shots.append((sc, sh))
    else:
        # Backward compat: flat shots array (旧格式)
        flat_shots = s4.get("shots", [])
        for sh in flat_shots:
            shots.append(({}, sh))  # empty scene dict
    if args.shot:
        shots = [(sc, sh) for sc, sh in shots if sh["shotNumber"] == args.shot]

    if args.dry_run:
        for sc, sh in shots:
            n = sh["shotNumber"]
            chars_in = sh.get("characters", [])
            scene_desc = _build_scene_description(sc, color_palette=project_color_palette)
            char_desc = _build_character_descriptions(chars, chars_in)
            comp_suffix = _build_composition_suffix(sh, chars_in, chars, project_color_palette)
            refs = _find_character_ref_images(chars, chars_in, pd)

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
            print(f"Shot {n:2d} ({','.join(chars_in)}) -> first={len(fp_first)}c last={len(fp_last)}c refs={len(refs)}")
        return

    sm = get_state_manager()
    sm.mark_running(args.project, "s5_frame_generate",
                    remaining=len(shots), gen_mode=gen_mode, frame_mode=frame_mode)
    out = pd / "s5_frames"
    out.mkdir(parents=True, exist_ok=True)
    sess = ComfyUISession()

    total_ok = 0
    total = len(shots) * (2 if frame_mode == "both" else 1)
    prev_last = ""  # 前一个 shot 的尾帧路径

    for i, (sc, sh) in enumerate(shots):
        n = sh["shotNumber"]
        chars_in = sh.get("characters", [])
        scene_desc = _build_scene_description(sc, color_palette=project_color_palette)
        char_desc = _build_character_descriptions(chars, chars_in)
        comp_suffix = _build_composition_suffix(sh, chars_in, chars, project_color_palette)
        ref_images = _find_character_ref_images(chars, chars_in, pd)
        ipa_weight = _get_ipadapter_weight(sh)

        print(f"\n[{i+1}/{len(shots)}] Shot {n} | chars={chars_in} | refs={len(ref_images)} | ipa_w={ipa_weight}")

        if frame_mode in ("first", "both"):
            # P0-1: 使用标准化 build_full_prompt (对齐 AICB buildFirstFramePrompt)
            fp = build_first_prompt(
                scene_description=scene_desc,
                start_frame_desc=sh.get("prompt", sh.get("description", "")),
                character_descriptions=char_desc,
                previous_last_frame=prev_last if prev_last else "",
            )
            if comp_suffix:
                fp += comp_suffix
            print(f"  First ({len(fp)}c): {fp[:80]}...")
            ok = generate_frame(
                sess, fp, n, "first", args.project, out,
                style=args.style, checkpoint=args.checkpoint,
                steps=args.steps, cfg=args.cfg,
                width=args.width, height=args.height,
                mode=gen_mode, ref_images=ref_images, prev_frame=prev_last,
            )
            if ok:
                total_ok += 1

        if frame_mode in ("last", "both"):
            # P0-1: 使用标准化 build_full_prompt (对齐 AICB buildLastFramePrompt)
            first_frame_path = str(out / f"s{n:02d}_first.png")
            fl = build_last_prompt(
                scene_description=scene_desc,
                end_frame_desc=sh.get("prompt", sh.get("description", "")),
                character_descriptions=char_desc,
            )
            if comp_suffix:
                fl += comp_suffix
            print(f"  Last  ({len(fl)}c): {fl[:80]}...")
            ok = generate_frame(
                sess, fl, n, "last", args.project, out,
                style=args.style, checkpoint=args.checkpoint,
                steps=args.steps, cfg=args.cfg,
                width=args.width, height=args.height,
                mode=gen_mode, ref_images=ref_images, prev_frame=first_frame_path,
            )
            if ok:
                total_ok += 1
                prev_last = str(out / f"s{n:02d}_last.png")  # 下一 shot 的连续性参考

    sm.mark_completed(args.project, "s5_frame_generate", generated=f"{total_ok}/{total}")
    print(f"\n{'='*60}")
    print(f"S5 Complete: {total_ok}/{total} frames (mode={gen_mode})")

    # ── P1-1+P1-5: Auto-trigger quality checks after S5 ──
    if total_ok > 0 and not args.dry_run and not getattr(args, 'no_check', False):
        print(f"\n{'='*60}")
        print("Running post-S5 quality checks...")
        print(f"{'='*60}")
        # Continuity check
        try:
            from core.continuity_check import ContinuityChecker
            print("\n[Continuity Check — adjacent shot consistency]")
            cc = ContinuityChecker()
            c_report = cc.check_project(args.project, threshold=70)
            print(cc.generate_summary(c_report))
        except Exception as e:
            print(f"  ⚠️ Continuity check failed: {e}")
        # Video quality check
        try:
            from core.video_quality_check import VideoQualityChecker
            print("\n[Video Quality Check — individual frame scoring]")
            vc = VideoQualityChecker()
            v_report = vc.check_project(args.project, sample_every=2)
            print(vc.generate_summary(v_report))
        except Exception as e:
            print(f"  ⚠️ Quality check failed: {e}")


if __name__ == "__main__":
    main()