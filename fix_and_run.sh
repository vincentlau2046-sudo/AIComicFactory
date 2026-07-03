#!/bin/bash
# AIComicFactory Full Pipeline Reset & Run
# Fixes: gender field in S2, demographics keyword list, S3b workflow

set -e

PROJECT="last_bento"
AICF="$HOME/AIComicFactory"
PROJDIR="$AICF/projects/$PROJECT"

echo "=== Step 0: Clean project ==="
rm -rf "$PROJDIR"/*
ls "$PROJDIR"

echo "=== Step 1: Fix character_extract.py - add gender field ==="
# Fix applied already via edit

echo "=== Step 2: Fix demographics.py - add keyword list ==="
# Fix applied already via edit

echo "=== Step 3: S1 Script Parse ==="
cd "$AICF" && python3 _run_s1.py

echo "=== Step 4: S2 Character Extract ==="
cd "$AICF" && python3 _run_s2.py

echo "=== Step 5: Start ComfyUI ==="
# Kill any existing ComfyUI
pkill -f "ComfyUI/main.py" 2>/dev/null || true
sleep 2
cd ~/ComfyUI && source ~/miniconda3/bin/activate comfyui
nohup python main.py --listen 0.0.0.0 --port 8188 --cache-none > /tmp/comfyui.log 2>&1 &
COMPYUI_PID=$!
echo "ComfyUI PID: $COMPYUI_PID"
for i in $(seq 1 40); do
  if curl -sf http://localhost:8188/system_stats > /dev/null 2>&1; then
    echo "ComfyUI ready"
    break
  fi
  sleep 2
done

echo "=== Step 6: S3 Character Images ==="
cd "$AICF" && python3 scripts/s3_character_image.py --project "$PROJECT" --gen flux --no-check

echo "=== Step 7: S3b Four Views ==="
cd "$AICF" && python3 scripts/s3b_four_view.py --project "$PROJECT"

echo "=== Step 8: S4 Shot Split ==="
cd "$AICF" && python3 _run_s4.py

echo "=== Step 9: S4b Keyframe Assets ==="
cd "$AICF" && python3 scripts/s4b_keyframe_assets.py --project "$PROJECT"

echo "=== Step 10: S5 Frame Generate ==="
cd "$AICF" && python3 scripts/s5_frame_generate.py --project "$PROJECT" --gen flux --no-check

echo "=== Step 11: S6 FLF2V ==="
cd "$AICF" && python3 scripts/s6_flf2v_render.py --project "$PROJECT"

echo "=== Step 12: S7 Assemble ==="
cd "$AICF" && python3 scripts/s7_video_assemble.py --project "$PROJECT"

echo "=== Step 13: S8 Subtitles ==="
cd "$AICF" && python3 scripts/s8_subtitles.py --project "$PROJECT"

echo "=== Step 14: S9 TTS Audio ==="
cd "$AICF" && python3 scripts/s9_tts_audio.py --project "$PROJECT"

echo "=== DONE ==="
