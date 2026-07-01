#!/usr/bin/env python3
"""Download anime SDXL models from HuggingFace and convert to ComfyUI checkpoint format.

Uses hf-mirror.com for China access.
Converts diffusers format → single safetensors checkpoint.
"""
import os, sys, json, shutil, tempfile
from pathlib import Path

HF_MIRROR = "https://hf-mirror.com"
CHECKPOINT_DIR = Path.home() / "ComfyUI/models/checkpoints"

MODELS = {
    "xuebi": {
        "repo": "stablediffusionapi/animexl-xuebimix",
        "output": "animexl_xuebiMIX_v40.safetensors",
        "desc": "AnimeXL-xuebiMIX (国产鲜艳动漫)",
    },
    "sky": {
        "repo": "stablediffusionapi/sdxl-anime-sky-realm",  # may not exist
        "output": "sdxl_anime_sky_realm_v31.safetensors",
        "desc": "SDXL-Anime 天空之境 V3.1",
    },
}

def download_diffusers(repo_id: str, output_name: str):
    """Download diffusers format and convert to single safetensors."""
    from huggingface_hub import snapshot_download
    
    print(f"Downloading {repo_id} from HF mirror...")
    tmpdir = tempfile.mkdtemp(prefix="aicf_model_")
    
    try:
        local_dir = snapshot_download(
            repo_id,
            local_dir=tmpdir,
            endpoint=HF_MIRROR,
        )
        print(f"Downloaded to {local_dir}")
        
        # Check if it's diffusers format (has unet/ directory)
        if (Path(local_dir) / "unet").is_dir():
            print("Converting diffusers → safetensors checkpoint...")
            convert_to_checkpoint(local_dir, output_name)
        else:
            # Maybe it's already a safetensors
            sfts = list(Path(local_dir).glob("*.safetensors"))
            if sfts:
                print(f"Found safetensors: {sfts[0]}")
                shutil.copy2(sfts[0], CHECKPOINT_DIR / output_name)
            else:
                print("ERROR: No safetensors found and not diffusers format")
                return False
        return True
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

def convert_to_checkpoint(diffusers_dir: str, output_name: str):
    """Convert diffusers format to single safetensors checkpoint for ComfyUI."""
    import torch
    from safetensors.torch import save_file
    
    state_dict = {}
    dp = Path(diffusers_dir)
    
    # Load UNET
    unet_dir = dp / "unet"
    if (unet_dir / "diffusion_pytorch_model.safetensors").exists():
        from safetensors.torch import load_file
        unet_sd = load_file(str(unet_dir / "diffusion_pytorch_model.safetensors"))
    elif (unet_dir / "diffusion_pytorch_model.fp16.safetensors").exists():
        from safetensors.torch import load_file
        unet_sd = load_file(str(unet_dir / "diffusion_pytorch_model.fp16.safetensors"))
    else:
        # Sharded
        shards = sorted(unet_dir.glob("diffusion_pytorch_model-*.safetensors"))
        unet_sd = {}
        for shard in shards:
            from safetensors.torch import load_file
            unet_sd.update(load_file(str(shard)))
    
    for k, v in unet_sd.items():
        state_dict[f"model.diffusion_model.{k}"] = v
    
    # Load text encoders
    for te_idx, te_name in enumerate(["text_encoder", "text_encoder_2"]):
        te_dir = dp / te_name
        te_file = te_dir / "model.safetensors"
        if te_file.exists():
            from safetensors.torch import load_file
            te_sd = load_file(str(te_file))
            prefix = f"conditioner.embedders.{te_idx}.transformer."
            for k, v in te_sd.items():
                state_dict[f"{prefix}{k}"] = v
    
    # Load VAE
    vae_file = dp / "vae" / "diffusion_pytorch_model.safetensors"
    if vae_file.exists():
        from safetensors.torch import load_file
        vae_sd = load_file(str(vae_file))
        for k, v in vae_sd.items():
            state_dict[f"first_stage_model.{k}"] = v
    
    # Save
    output_path = CHECKPOINT_DIR / output_name
    print(f"Saving checkpoint to {output_path} ({len(state_dict)} keys)...")
    save_file(state_dict, str(output_path))
    print(f"✅ {output_path} ({output_path.stat().st_size // 1024 // 1024}MB)")

def main():
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    
    for key, info in MODELS.items():
        output_path = CHECKPOINT_DIR / info["output"]
        if output_path.exists() and output_path.stat().st_size > 1_000_000:
            print(f"⏭️ {info['desc']} already exists: {output_path}")
            continue
        
        print(f"\n{'='*60}")
        print(f"📦 {info['desc']} ({info['repo']})")
        try:
            ok = download_diffusers(info["repo"], info["output"])
            if ok:
                print(f"✅ {info['desc']} installed")
            else:
                print(f"❌ {info['desc']} failed")
        except Exception as e:
            print(f"❌ {info['desc']}: {e}")

if __name__ == "__main__":
    main()
