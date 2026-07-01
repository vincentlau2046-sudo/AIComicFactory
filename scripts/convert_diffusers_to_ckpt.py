#!/usr/bin/env python3
"""Convert HuggingFace Diffusers model to ComfyUI safetensors checkpoint.

Handles the full conversion:
- UNet: Diffusers format → CompVis format (input_blocks/output_blocks)
- VAE: Diffusers format → CompVis format (encoder.down/decoder.up)
- Text encoder 1: clip_l → conditioner.embedders.0.transformer
- Text encoder 2: clip_g → conditioner.embedders.1.model

Usage:
    python3 convert_diffusers_to_ckpt.py --repo stablediffusionapi/animexl-xuebimix --output animexl_xuebiMIX_v60.safetensors
"""
import argparse
import sys
import torch
from safetensors.torch import save_file
from pathlib import Path

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--repo", required=True, help="HuggingFace repo ID")
    p.add_argument("--output", required=True, help="Output safetensors filename")
    p.add_argument("--mirror", default="https://hf-mirror.com", help="HF mirror URL")
    args = p.parse_args()

    import os
    os.environ["HF_ENDPOINT"] = args.mirror

    # Import ComfyUI utilities for key conversion
    sys.path.insert(0, str(Path.home() / "ComfyUI"))
    import comfy.utils
    import comfy.diffusers_convert
    import comfy.model_detection

    print(f"Downloading {args.repo} from {args.mirror}...")
    from diffusers import StableDiffusionXLPipeline
    pipe = StableDiffusionXLPipeline.from_pretrained(
        args.repo,
        torch_dtype=torch.float16,
    )

    print("Converting to checkpoint format...")
    state_dict = {}

    # ═══════════════════════════════════════════════════════════════
    # UNet: Diffusers → CompVis format
    # ═══════════════════════════════════════════════════════════════
    unet_sd = pipe.unet.state_dict()
    print(f"  UNet: {len(unet_sd)} keys (diffusers format)")

    # Detect UNet config to get the key mapping
    unet_config = comfy.model_detection.unet_config_from_diffusers_unet(unet_sd)
    if unet_config is not None:
        # Get diffusers→compvis mapping and invert it
        diffusers_map = comfy.utils.unet_to_diffusers(unet_config)
        # diffusers_map: {diffusers_key → compvis_key}
        # We need: {compvis_key → tensor}
        compvis_unet = {}
        unmapped = 0
        for k, v in unet_sd.items():
            if k in diffusers_map:
                compvis_key = diffusers_map[k]
                compvis_unet[compvis_key] = v
            elif k.startswith("time_embedding.") or k.startswith("add_embedding.") or k.startswith("conv_out.") or k.startswith("conv_in.") or k.startswith("norm_out"):
                # These keys are the same in both formats
                compvis_unet[k] = v
            else:
                unmapped += 1
                compvis_unet[k] = v  # Keep as-is
        if unmapped > 0:
            print(f"  ⚠️ {unmapped} UNet keys unmapped")
        print(f"  UNet: {len(compvis_unet)} keys (compvis format)")
        for k, v in compvis_unet.items():
            state_dict[f"model.diffusion_model.{k}"] = v
    else:
        print("  ⚠️ Could not detect UNet config, using raw keys")
        for k, v in unet_sd.items():
            state_dict[f"model.diffusion_model.{k}"] = v

    # ═══════════════════════════════════════════════════════════════
    # VAE: Diffusers → CompVis format
    # ═══════════════════════════════════════════════════════════════
    vae_sd = pipe.vae.state_dict()
    print(f"  VAE: {len(vae_sd)} keys (diffusers format)")
    
    # Check if VAE is in diffusers format
    if 'decoder.up_blocks.0.resnets.0.norm1.weight' in vae_sd:
        vae_sd = comfy.diffusers_convert.convert_vae_state_dict(vae_sd)
        print(f"  VAE: {len(vae_sd)} keys (compvis format)")
    
    for k, v in vae_sd.items():
        state_dict[f"first_stage_model.{k}"] = v

    # ═══════════════════════════════════════════════════════════════
    # Text encoders
    # ═══════════════════════════════════════════════════════════════
    # Text encoder 1 (CLIP-ViT/L) → conditioner.embedders.0.transformer
    te1_sd = pipe.text_encoder.state_dict()
    for k, v in te1_sd.items():
        state_dict[f"conditioner.embedders.0.transformer.{k}"] = v
    print(f"  Text encoder 1: {len(te1_sd)} keys")

    # Text encoder 2 (CLIP-ViT/G) → conditioner.embedders.1.model
    te2_sd = pipe.text_encoder_2.state_dict()
    for k, v in te2_sd.items():
        state_dict[f"conditioner.embedders.1.model.{k}"] = v
    print(f"  Text encoder 2: {len(te2_sd)} keys")

    out_path = Path(args.output)
    print(f"Saving {len(state_dict)} keys to {out_path}...")
    save_file(state_dict, str(out_path))
    print(f"✅ {out_path} ({out_path.stat().st_size / 1024 / 1024 / 1024:.2f} GB)")

if __name__ == "__main__":
    main()
