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
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from core.comfyui_session import ComfyUISession, ComfyUIError
from core.state_manager import get_state_manager
from core.asset_manager import get_asset_manager

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
W, H = 1024, 576  # 16:9 landscape, matches S5 frame resolution

MAX_FLF2V_FRAMES = 125   # FLF2V 有效窗口 ~5s@25fps

TEACACHE_THRESHOLD = 0.2
TEACACHE_START = 0.15
TEACACHE_END = 0.95

NEG_PROMPT = "静态, 细节模糊不清, 最差质量, 低质量, 丑陋, 多余手指, 畸形的肢体, 字幕, 水印"

# Mid-frame generation config
MID_CKPT = "animagine-xl-3.1.safetensors"
MID_QUALITY = "masterpiece, best quality, very aesthetic, highres, detailed"
MID_NEG = "low quality, worst quality, bad anatomy, bad hands, blurry, watermark, text, signature, deformed"


def build_flf2v_workflow(start_image: str, end_image: str, motion_prompt: str,
                          duration_frames: int, seed: int = 42) -> dict:
    """Build FLF2V workflow. duration_frames = requested output frames at FPS."""
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
            "width": W, "height": H, "length": duration_frames, "batch_size": 1,
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

def build_midframe_workflow(prompt: str, seed: int) -> dict:
    """Generate a single mid-frame via T2I."""
    return {
        "3": {"class_type": "KSampler", "inputs": {
            "seed": seed, "steps": 20, "cfg": 7.5,
            "sampler_name": "euler_ancestral", "scheduler": "normal",
            "denoise": 1.0, "model": ["4", 0],
            "positive": ["6", 0], "negative": ["7", 0],
            "latent_image": ["5", 0],
        }},
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": MID_CKPT}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": W, "height": H, "batch_size": 1}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": MID_NEG, "clip": ["4", 1]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "aicf_mid", "images": ["8", 0]}},
    }


def generate_mid_frame(sess: ComfyUISession, prompt: str, seed: int, shot_num: int, seg_idx: int,
                        project: str, s5_dir: Path, comfy_input: Path) -> Path:
    """Generate a mid-frame and save to s5_frames. Returns the ComfyUI input filename."""
    wf = build_midframe_workflow(prompt, seed)
    wf["9"]["inputs"]["filename_prefix"] = f"aicf_mid_s{shot_num:02d}_{seg_idx}"

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
    args = parser.parse_args()

    pd = Path(__file__).parent.parent / "projects" / args.project
    s4 = json.load(open(pd / "s4_shots.json"))
    s2 = json.load(open(pd / "s2_characters.json"))
    chars = s2["characters"]
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

    for i, shot in enumerate(shots):
        sn = shot["shotNumber"]
        first = s5_dir / f"s{sn:02d}_first.png"
        last = s5_dir / f"s{sn:02d}_last.png"

        if not first.exists() or not last.exists():
            print(f"Shot {sn}: missing frames — SKIP")
            continue

        duration = shot.get("duration", 5.0)
        total_frames = int(duration * FPS)
        motion = shot.get("videoScript", shot.get("motionScript", ""))

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

            wf = build_flf2v_workflow(start_name, end_name, motion, total_frames, args.seed + sn)
            wf["16"]["inputs"]["filename_prefix"] = f"aicf_flf2v_s{sn:02d}"

            try:
                result = sess.run(wf, timeout=600)
                output_dir = Path.home() / "ComfyUI" / "output"
                candidates = sorted(
                    output_dir.glob(f"aicf_flf2v_s{sn:02d}_*.mp4"),
                    key=lambda x: x.stat().st_mtime, reverse=True
                )
                if candidates:
                    dest = videos_dir / f"s{sn:02d}.mp4"
                    shutil.copy2(str(candidates[0]), str(dest))
                    size_mb = dest.stat().st_size / (1024 * 1024)
                    print(f"  ✅ {size_mb:.1f}MB ({result.elapsed:.0f}s)")
                    
                    # Register asset
                    am = get_asset_manager()
                    am.register(
                        project=args.project,
                        asset_type="keyframe_video",
                        shot_id=f"shot_{sn:03d}",
                        source_path=candidates[0],
                        relative_dir="s6_videos",
                        metadata={
                            "frames": total_frames,
                            "duration_s": duration,
                            "accelerations": "Lightx2v+TeaCache+SageAttention",
                        }
                    )
                else:
                    print(f"  ⚠️ No output file")
            except ComfyUIError as e:
                print(f"  ❌ {e}")
            continue

        # ── Path D: Split FLF2V (>MAX_FLF2V_FRAMES) ──
        num_segments = (total_frames + MAX_FLF2V_FRAMES - 1) // MAX_FLF2V_FRAMES
        remaining = total_frames
        print(f"\nShot {sn}/{len(shots)}: {total_frames}f ({duration}s) → {num_segments} segments | {motion[:60]}...")

        # Copy start/end to ComfyUI input
        start_name = f"aicf_s{sn:02d}_start.png"
        end_name = f"aicf_s{sn:02d}_end.png"
        shutil.copy2(str(first), str(comfy_input / start_name))
        shutil.copy2(str(last), str(comfy_input / end_name))

        segments = []
        current_start = start_name
        total_elapsed = 0

        for seg_idx in range(num_segments):
            seg_frames = min(remaining, MAX_FLF2V_FRAMES)

            if seg_idx == num_segments - 1:
                # Last segment: current_start → end_image
                current_end = end_name
            else:
                # Generate mid-frame for segment boundary
                mid_seed = random.randint(0, 2**32 - 1)
                current_end = generate_mid_frame(
                    sess, t2i_prompt, mid_seed, sn, seg_idx,
                    args.project, s5_dir, comfy_input
                )

            print(f"  seg {seg_idx + 1}/{num_segments}: {seg_frames}f ({seg_frames/FPS:.1f}s)")

            seg_mp4 = render_segment(
                sess, current_start, current_end,
                motion, seg_frames, args.seed + sn * 100 + seg_idx,
                sn, seg_idx
            )
            size_mb = seg_mp4.stat().st_size / (1024 * 1024)
            print(f"    ✅ {size_mb:.1f}MB")
            segments.append(seg_mp4)

            remaining -= seg_frames
            current_start = current_end  # Next segment starts from this mid/end

        # Concatenate all segments
        dest = videos_dir / f"s{sn:02d}.mp4"
        concat_segments(segments, dest)
        print(f"  → concat ✅ {dest.stat().st_size/(1024*1024):.1f}MB")
        
        # Register concatenated asset
        am = get_asset_manager()
        am.register(
            project=args.project,
            asset_type="keyframe_video",
            shot_id=f"shot_{sn:03d}",
            source_path=dest,
            relative_dir="s6_videos",
            metadata={
                "frames": total_frames,
                "duration_s": duration,
                "segments": num_segments,
                "accelerations": "Lightx2v+TeaCache+SageAttention",
            }
        )

    done = len(list(videos_dir.glob("*.mp4")))
    sm.mark_completed(args.project, "s6_video_generate", generated=f"{done}/{len(shots)}")
    print(f"\nS6: {done}/{len(shots)} videos")


if __name__ == "__main__":
    main()