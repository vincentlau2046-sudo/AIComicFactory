# ComfyUI Workflow Mirror

This directory mirrors the production workflows used by AIComicFactory.
Production path: /home/vince/ComfyUI/workflows/AIComicFactory/atomic/

These files are kept in git for version tracking. The production runtime
reads from the ComfyUI installation path directly via COMFYUI_WORKFLOWS_DIR.

## Sync command

```bash
cp /home/vince/ComfyUI/workflows/AIComicFactory/atomic/*.json src/lib/comfyui/workflows/atomic/
cp /home/vince/ComfyUI/workflows/AIComicFactory/atomic/*.yaml src/lib/comfyui/workflows/atomic/
```
