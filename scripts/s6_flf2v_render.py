#!/usr/bin/env python3
"""
scripts/s6_flf2v_render.py — Stage 6: FLF2V Keyframe Video Rendering

使用 Wan2.2 FLF2V + Lightx2v 4-step + TeaCache + SageAttention
首帧+尾帧 → 插值动画片段。

>5s 的 shot 自动分段渲染: 将长 shot 拆为 ≤125f 的 FLF2V 段落，生成中帧衔接，拼接输出。

用法:
    python scripts/s6_flf2v_render.py --project last_bento
    python scripts/s6_flf2v_render.py --project last_bento --shot 1
"""

import json, sys, argparse, shutil, os, random, subprocess, tempfile
# Force unbuffered stdout for real-time progress monitoring
sys.stdout.reconfigure(line_buffering=True)
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from core.comfyui_session import ComfyUISession, ComfyUIError
from core.state_manager import get_state_manager
from core.asset_manager import get_asset_manager
from core.workflow_loader import load_workflow, inject_params
from prompts.defaults.video_generate import build_video_prompt


def _extract_frame_desc(s4b_prompt: str) -> str:
    """从 S4b keyframe prompt 中提取 '画面描述' 段落作为帧描述。
    
    S4b prompt 格式:
        生成该镜头的...
        === 关键：画风 ===
        ...
        === 场景环境 ===
        ...
        === 画面描述 ===
        <这是我们需要的内容>
        === (下一个段落或结束) ===
    
    Returns:
        纯画面描述文本，不含生成指令/画风指令/场景环境。
        如果提取失败，返回整个 prompt（退化 fallback）。
    """
    import re
    # Match === 画面描述 === block
    m = re.search(r'===\s*画面描述\s*===\s*\n(.*?)(?=\n===\s|$)', s4b_prompt, re.DOTALL)
    if m:
        desc = m.group(1).strip()
        if desc:
            return desc
    # Fallback: return full prompt (better than nothing)
    return s4b_prompt

# ═══════════════════════════════════════
# Config
# ═══════════════════════════════════════

UNET_HIGH = "wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors"
VAE_NAME  = "wan_2.1_vae.safetensors"
CLIP_NAME = "umt5_xxl_fp8_e4m3fn_scaled.safetensors"
CLIP_VISION = "clip_vision_h.safetensors"
LORA_HIGH = "Wan_2_2_I2V_A14B_HIGH_lightx2v_4step_lora_v1030_rank_64_bf16.safetensors"

STEPS = 4
CFG = 1.0
SHIFT = 5.0
FPS = 25
W, H = 1280, 720  # 16:9 landscape, matches S5 frame resolution (unified 2026-07-01)

MAX_FLF2V_FRAMES = 150   # FLF2V 有效窗口 ~6s@25fps; >6s 镜头应打回重分镜

TEACACHE_THRESHOLD = 0.2
TEACACHE_START = 0.15
TEACACHE_END = 0.95

NEG_PROMPT = "静态, 细节模糊不清, 最差质量, 低质量, 丑陋, 多余手指, 畸形的肢体, 字幕, 水印"

# Mid-frame generation config
# Mid-frame uses Flux Dev T2I (same as S5 Path B), not Animagine XL
# MID_CKPT/MID_NEG removed — Flux Dev uses ConditioningZeroOut
MID_QUALITY = "masterpiece, best quality, very aesthetic, highres, detailed"


def build_flf2v_workflow(start_image: str, end_image: str, motion_prompt: str,
                          duration_frames: int, seed: int = 42,
                          width: int = 1280, height: int = 720) -> dict:
    """Build FLF2V workflow. Try loading from template first, fallback to inline."""
    try:
        wf = load_workflow("flf2v_keyframe.json")
        return inject_params(wf, {
            "1": {"unet_name": UNET_HIGH},
            "3": {"vae_name": VAE_NAME},
            "4": {"clip_name": CLIP_NAME},
            "lora": {"lora_name": LORA_HIGH},
            "shift": {"shift": SHIFT},
            "cache": {"threshold": TEACACHE_THRESHOLD, "start_percent": TEACACHE_START, "end_percent": TEACACHE_END},
            "6a": {"text": motion_prompt},
            "6b": {"text": NEG_PROMPT},
            "7": {"image": start_image},
            "8": {"image": end_image},
            "12": {"width": width, "height": height, "length": duration_frames},
            "13": {"seed": seed, "steps": STEPS, "cfg": CFG},
            "16": {"frame_rate": FPS},
        })
    except FileNotFoundError:
        pass  # Fallback to inline workflow below
    
    return _build_flf2v_inline(start_image, end_image, motion_prompt, duration_frames, seed, width, height)


def _build_flf2v_inline(start_image: str, end_image: str, motion_prompt: str,
                          duration_frames: int, seed: int = 42,
                          width: int = 1280, height: int = 720) -> dict:
    """Fallback inline FLF2V workflow (when template not available)."""
    return {
        "1":  {"class_type": "UNETLoader", "inputs": {"unet_name": UNET_HIGH, "weight_dtype": "default"}},
        "3":  {"class_type": "VAELoader", "inputs": {"vae_name": VAE_NAME}},
        "4":  {"class_type": "CLIPLoader", "inputs": {"clip_name": CLIP_NAME, "type": "wan"}},
        "lora": {"class_type": "LoraLoaderModelOnly", "inputs": {
            "model": ["1", 0], "lora_name": LORA_HIGH, "strength_model": 1.0}},
        "shift": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["lora", 0], "shift": SHIFT}},
        "cache": {"class_type": "EasyCache", "inputs": {
            "model": ["shift", 0], "threshold": TEACACHE_THRESHOLD,
            "start_percent": TEACACHE_START, "end_percent": TEACACHE_END,
            "reuse_threshold": 0.1, "verbose": False}},
        "6a": {"class_type": "CLIPTextEncode", "inputs": {"text": motion_prompt, "clip": ["4", 0]}},
        "6b": {"class_type": "CLIPTextEncode", "inputs": {"text": NEG_PROMPT, "clip": ["4", 0]}},
        "7":  {"class_type": "LoadImage", "inputs": {"image": start_image}},
        "8":  {"class_type": "LoadImage", "inputs": {"image": end_image}},
        "9":  {"class_type": "CLIPVisionLoader", "inputs": {"clip_name": CLIP_VISION}},
        "10": {"class_type": "CLIPVisionEncode", "inputs": {"clip_vision": ["9", 0], "image": ["7", 0], "crop": "center"}},
        "11": {"class_type": "CLIPVisionEncode", "inputs": {"clip_vision": ["9", 0], "image": ["8", 0], "crop": "center"}},
        "12": {"class_type": "WanFirstLastFrameToVideo", "inputs": {
            "positive": ["6a", 0], "negative": ["6b", 0], "vae": ["3", 0],
            "clip_vision_start_image": ["10", 0], "clip_vision_end_image": ["11", 0],
            "start_image": ["7", 0], "end_image": ["8", 0],
            "width": width, "height": height, "length": duration_frames, "batch_size": 1,
        }},
        "13": {"class_type": "KSampler", "inputs": {
            "model": ["cache", 0],
            "positive": ["12", 0], "negative": ["12", 1],
            "latent_image": ["12", 2],
            "seed": seed, "steps": STEPS, "cfg": CFG,
            "sampler_name": "uni_pc", "scheduler": "simple", "denoise": 1.0,
        }},
        "15": {"class_type": "VAEDecode", "inputs": {"vae": ["3", 0], "samples": ["13", 0]}},
        "16": {"class_type": "VHS_VideoCombine", "inputs": {
            "images": ["15", 0], "frame_rate": FPS, "loop_count": 0,
            "filename_prefix": "aicf_flf2v", "format": "video/h264-mp4",
            "pix_fmt": "yuv420p", "save_output": True, "pingpong": False,
        }},
    }


# ═══════════════════════════════════════
# Mid-frame generator (T2I, reused from S5 pattern)
# ═══════════════════════════════════════

def build_midframe_workflow(prompt: str, seed: int, width: int = 1280, height: int = 720) -> dict:
    """Generate a single mid-frame via Flux Dev T2I.
    
    v2.0: Replaced Animagine XL with Flux Dev (style consistency with S5 Path B).
    Aligned with official Flux.1 Dev Blueprint: cfg=1.0, euler/simple, 20 steps,
    ConditioningZeroOut negative, EmptySD3LatentImage.
    """
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
            "filename_prefix": "aicf_mid", "images": ["17", 0]}},
    }


def generate_mid_frame(sess: ComfyUISession, prompt: str, seed: int, shot_num: int, seg_idx: int,
                        project: str, s5_dir: Path, comfy_input: Path) -> Path:
    """Generate a mid-frame (Flux Dev T2I) and save to s5_frames. Returns the ComfyUI input filename."""
    wf = build_midframe_workflow(prompt, seed)
    wf["18"]["inputs"]["filename_prefix"] = f"aicf_mid_s{shot_num:02d}_{seg_idx}"

    try:
        result = sess.run(wf, timeout=300)
        output_dir = Path.home() / "ComfyUI" / "output"
        candidates = sorted(
            output_dir.glob(f"aicf_mid_s{shot_num:02d}_{seg_idx}_*.png"),
            key=lambda x: x.stat().st_mtime, reverse=True
        )
        if not candidates:
            raise ComfyUIError("No mid-frame output")

        # Save to s5_frames
        dest = s5_dir / f"s{shot_num:02d}_mid_{seg_idx}.png"
        shutil.copy2(str(candidates[0]), str(dest))

        # Copy to ComfyUI input for FLF2V
        input_name = f"aicf_s{shot_num:02d}_mid_{seg_idx}.png"
        shutil.copy2(str(candidates[0]), str(comfy_input / input_name))

        print(f"    mid_{seg_idx} ✅ {dest.stat().st_size/1024:.0f}KB")
        return input_name
    except ComfyUIError as e:
        print(f"    mid_{seg_idx} ❌ {e}")
        raise


# ═══════════════════════════════════════
# FLF2V segment render + concat
# ═══════════════════════════════════════

def render_segment(sess: ComfyUISession, start_img: str, end_img: str,
                    motion_prompt: str, frames: int, seed: int,
                    shot_num: int, seg_idx: int) -> Path:
    """Render a single FLF2V segment. Returns path to output MP4."""
    wf = build_flf2v_workflow(start_img, end_img, motion_prompt, frames, seed)
    wf["16"]["inputs"]["filename_prefix"] = f"aicf_flf2v_s{shot_num:02d}_seg{seg_idx}"

    result = sess.run(wf, timeout=600)
    output_dir = Path.home() / "ComfyUI" / "output"
    candidates = sorted(
        output_dir.glob(f"aicf_flf2v_s{shot_num:02d}_seg{seg_idx}_*.mp4"),
        key=lambda x: x.stat().st_mtime, reverse=True
    )
    if not candidates:
        raise ComfyUIError(f"No output for segment {seg_idx}")
    return candidates[0]


def concat_segments(segments: list, output: Path):
    """Concatenate MP4 segments into final clip using ffmpeg stream copy."""
    concat_file = output.parent / f"concat_{output.stem}.txt"
    with open(concat_file, "w") as f:
        for seg in segments:
            f.write(f"file '{seg}'\n")

    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(concat_file), "-c", "copy", str(output),
    ], check=True, capture_output=True)
    concat_file.unlink(missing_ok=True)


# ═══════════════════════════════════════
# Main
# ═══════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Stage 6: FLF2V video rendering")
    parser.add_argument("--project", "-P", required=True)
    parser.add_argument("--shot", "-s", type=int)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--width", type=int, default=1280, help="FLF2V frame width (default 1280)")
    parser.add_argument("--height", type=int, default=720, help="FLF2V frame height (default 720)")
    args = parser.parse_args()
    frame_width, frame_height = args.width, args.height

    pd = Path(__file__).parent.parent / "projects" / args.project
    s4 = json.load(open(pd / "s4_shots.json"))
    s2 = json.load(open(pd / "s2_characters.json"))
    chars = s2["characters"]
    
    # Load S4b keyframe assets for frame descriptions
    s4b_path = pd / "s4b_keyframe_assets.json"
    s4b_data = json.load(open(s4b_path)) if s4b_path.exists() else None
    s5_dir = pd / "s5_frames"

    shots = []
    for sc in s4["scenes"]:
        for sh in sc["shots"]:
            shots.append(sh)
    if args.shot:
        shots = [s for s in shots if s["shotNumber"] == args.shot]

    sm = get_state_manager()
    sm.mark_running(args.project, "s6_video_generate", remaining=len(shots))

    videos_dir = pd / "s6_videos"
    videos_dir.mkdir(parents=True, exist_ok=True)
    comfy_input = Path.home() / "ComfyUI" / "input"
    sess = ComfyUISession()

    done = 0
    for i, shot in enumerate(shots):
        global_shot = i + 1
        sn = global_shot  # 全局编号做文件名
        local_sn = shot["shotNumber"]  # 场景内编号，用于 S4b 匹配
        first = s5_dir / f"s{sn:02d}_first.png"
        last = s5_dir / f"s{sn:02d}_last.png"

        if not first.exists() or not last.exists():
            print(f"Shot {sn}: missing frames — SKIP")
            continue

        duration = shot.get("duration", 5.0)
        total_frames = int(duration * FPS)
        # ── AICB buildVideoPrompt: full 7-slot assembly ──
        shot_chars = []
        for cn in shot.get("characters", []):
            for c in chars:
                if c["name"] == cn:
                    shot_chars.append({"name": c["name"], "visualHint": c.get("visualHint")})
                    break

        # P1-5: 优先读 shot.videoPrompt，fallback 到 build_video_prompt() 拼装
        if shot.get("videoPrompt"):
            motion = shot["videoPrompt"]
        else:
            # P1-3: 消费新字段 sceneDescription + startFrameDesc/endFrameDesc
            scene_desc = shot.get("sceneDescription", "")
            # Read S4b keyframe assets for frame descriptions
            start_desc = shot.get("startFrameDesc", "")
            end_desc = shot.get("endFrameDesc", "")
            # Also check S4b data — extract 画面描述 only (not full gen prompt)
            if s4b_data and (not start_desc or not end_desc):
                for s4b_s in s4b_data.get("shots", []):
                    if s4b_s["shotNumber"] == local_sn:
                        if not start_desc:
                            raw = s4b_s.get("startFrame", {}).get("prompt", "")
                            start_desc = _extract_frame_desc(raw) if raw else ""
                        if not end_desc:
                            raw = s4b_s.get("endFrame", {}).get("prompt", "")
                            end_desc = _extract_frame_desc(raw) if raw else ""
                        break
            
            motion = build_video_prompt(
                video_script=shot.get("videoScript", shot.get("motionScript", "")),
                camera_direction=shot.get("cameraDirection", "静态"),
                start_frame_desc=start_desc,
                end_frame_desc=end_desc,
                scene_description=scene_desc,
                duration=duration,
                characters=shot_chars,
                dialogues=shot.get("dialogues", []),
                aspect_ratio="16:9",
            )

        # Build T2I prompt for mid-frame generation (same as S5 prompt)
        t2i_prompt = f"{MID_QUALITY}, {shot.get('prompt', '')}"
        for cn in shot.get("characters", []):
            for c in chars:
                if c["name"] == cn and c.get("visualHint"):
                    t2i_prompt += f", ({c['visualHint']})"

        # ── Path A: Normal FLF2V (≤MAX_FLF2V_FRAMES) ──
        if total_frames <= MAX_FLF2V_FRAMES:
            start_name = f"aicf_s{sn:02d}_start.png"
            end_name = f"aicf_s{sn:02d}_end.png"
            shutil.copy2(str(first), str(comfy_input / start_name))
            shutil.copy2(str(last), str(comfy_input / end_name))

            print(f"\nShot {sn}/{len(shots)}: {total_frames}f ({duration}s) | {motion[:60]}...")

            wf = build_flf2v_workflow(start_name, end_name, motion, total_frames, args.seed + sn, frame_width, frame_height)
            wf["16"]["inputs"]["filename_prefix"] = f"aicf_flf2v_s{sn:02d}"

            try:
                result = sess.run(wf, timeout=600)
                output_dir = Path.home() / "ComfyUI" / "output"
                candidates = sorted(
                    output_dir.glob(f"aicf_flf2v_s{sn:02d}_*.mp4"),
                    key=lambda x: x.stat().st_mtime, reverse=True
                )
                if candidates:
                    # Register asset (am.register writes the file with dest_name)
                    am = get_asset_manager()
                    am.register(
                        project=args.project,
                        asset_type="keyframe_video",
                        shot_id=f"shot_{sn:03d}",
                        source_path=candidates[0],
                        relative_dir="s6_videos",
                        dest_name=f"s{sn:02d}.mp4",
                        metadata={
                            "frames": total_frames,
                            "duration_s": duration,
                            "accelerations": "Lightx2v+TeaCache+SageAttention",
                        }
                    )
                    dest = videos_dir / f"s{sn:02d}.mp4"
                    size_mb = dest.stat().st_size / (1024 * 1024)
                    print(f"  ✅ {size_mb:.1f}MB ({result.elapsed:.0f}s)")
                    done += 1
                else:
                    print(f"  ⚠️ No output file")
            except ComfyUIError as e:
                print(f"  ❌ {e}")
            continue

        # ── Path D: Shot too long (>6s) — reject, must re-split in S4 ──
        if total_frames > MAX_FLF2V_FRAMES:
            print(f"\n  ❌ Shot {sn}: {total_frames}f ({duration}s) > {MAX_FLF2V_FRAMES}f ({MAX_FLF2V_FRAMES/FPS:.1f}s)")
            print(f"     → 打回重分镜: S4 max_duration 应 ≤{MAX_FLF2V_FRAMES/FPS:.0f}s")
            sm.add_error(args.project, "s6_flf2v_render",
                         f"shot {sn} too long: {duration}s > {MAX_FLF2V_FRAMES/FPS:.0f}s, re-run S4 with max_duration={MAX_FLF2V_FRAMES/FPS:.0f}")
            continue

    sm.mark_completed(args.project, "s6_video_generate", generated=f"{done}/{len(shots)}")
    print(f"\nS6: {done}/{len(shots)} videos")


if __name__ == "__main__":
    main()