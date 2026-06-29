# ComfyUI Workflow Templates

API-format JSON templates for AIComicFactory stages. Load, fill placeholders, submit.

## Templates

| File | Stage | Engine | Resolution | Notes |
|------|-------|--------|------------|-------|
| `t2i_character_ref.json` | S3 | Animagine XL 3.1 | 1024×1024 | Checkpoint → prompt → VAE decode |
| `qwen_edit_four_view.json` | S3b | Qwen Image Edit 2511 | 1024×1024 | Reference → four-view layout |
| `qwen_edit_frame.json` | S5 | Qwen Image Edit 2511 | 1024×576 | Reference → first/last frame |
| `flf2v_keyframe.json` | S6 | Wan2.2 FLF2V + Lightx2v | 1024×576 | Start/end → interpolated video |

## Usage in Scripts

```python
import json
from pathlib import Path

template = json.load(open(Path(__file__).parent.parent / "templates" / "t2i_character_ref.json"))

# Fill placeholders
template["6"]["inputs"]["text"] = "masterpiece, 1man, solo, ..."
template["9"]["inputs"]["filename_prefix"] = f"aicf_{project}_{character}"

# Run via ComfyUISession
result = session.run(template, timeout=300)
```

## Adding New Templates

1. Export from ComfyUI using "Save (API Format)"
2. Replace specific values (prompts, filenames, seeds) with placeholders or defaults
3. Document the template above
4. Reference in the corresponding `scripts/sN_*.py`