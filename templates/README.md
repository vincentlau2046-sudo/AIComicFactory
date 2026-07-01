# ComfyUI Workflow Templates

API-format JSON templates for AIComicFactory stages. Load, fill placeholders, submit.

## Templates

| File | Stage | Engine | Resolution | Notes |
|------|-------|--------|------------|-------|
| `t2i_character_ref.json` | S3 | Animagine XL 3.1 | 1024×1536 | Checkpoint → prompt → VAE decode |
| `qwen_edit_four_view.json` | S3b | Qwen Image Edit 2511 + ReferenceLatent | 1024×1536 | VAEEncode ref → ReferenceLatent → FluxKontextMultiReferenceLatentMethod |
| `qwen_edit_frame.json` | S5 | Qwen Image Edit 2511 | 1024×576 | Reference → first/last frame |
| `flf2v_keyframe.json` | S6 | Wan2.2 FLF2V + Lightx2v | 1024×576 | Start/end → interpolated video |

## qwen_edit_four_view.json — Node Graph

```
UNETLoader → LoraLoaderModelOnly (Lightning 4-step) → ModelSamplingAuraFlow (shift=3.1) → CFGNorm → KSampler
CLIPLoader → TextEncodeQwenImageEditPlus (×2: positive + negative)
VAELoader → VAEEncode (ref image) → ReferenceLatent (×2) → FluxKontextMultiReferenceLatentMethod (×2)
KSampler: er_sde / beta, steps=4, cfg=1.0
latent_image = VAEEncoded reference (NOT EmptyQwenImageLayeredLatentImage)
```

### ⚠️ Compatiblity Warnings

- **SageAttention**: `--use-sage-attention` causes black output with qwen-image-edit. Must NOT use.
- **TeaCache**: May also conflict. Ensure disabled.
- **Lightning LoRA**: `Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors` (539MB, in models/loras/)
- **Checkpoint**: `qwen_image_edit_2511_fp8mixed.safetensors` (in models/diffusion_models/, NOT checkpoints/)

## Usage in Scripts

```python
from core.workflow_loader import load_workflow, inject_params

# S3 T2I
wf = load_workflow("t2i_character_ref.json")
wf = inject_params(wf, {"6": {"text": prompt}, "3": {"seed": 42}})

# S3b QEdit 4-view
wf = load_workflow("qwen_edit_four_view.json")
wf = inject_params(wf, {
    "41": {"image": ref_image_name},
    "68": {"prompt": view_prompt, "image1": ref_image_name},
    "65": {"seed": 42},
    "60": {"filename_prefix": output_prefix},
})
```

## Adding New Templates

1. Export from ComfyUI using "Save (API Format)"
2. Replace specific values (prompts, filenames, seeds) with placeholders or defaults
3. Document the template above
4. Reference in the corresponding `scripts/sN_*.py`
