#!/usr/bin/env python3
"""
merge_fourview.py — 将四张角度角色图合成为一张 2×2 四视图。

Environment variables (set by PipelineEngine):
  PIPELINE_FRONT   — 正面图路径
  PIPELINE_LEFT    — 左45度路径
  PIPELINE_SIDE    — 正侧面路径
  PIPELINE_BACK    — 背面路径
  PIPELINE_OUTPUT_DIR — 输出目录

Output:
  merged.png — 合成后的四视图
"""
import os
import sys
from PIL import Image

def main():
    front_path = os.environ.get('PIPELINE_FRONT')
    left_path = os.environ.get('PIPELINE_LEFT')
    side_path = os.environ.get('PIPELINE_SIDE')
    back_path = os.environ.get('PIPELINE_BACK')
    out_dir = os.environ.get('PIPELINE_OUTPUT_DIR', '.')

    if not all([front_path, left_path, side_path, back_path]):
        print("Error: Missing input paths", file=sys.stderr)
        sys.exit(1)

    # Load images
    images = []
    for label, p in [('front', front_path), ('left', left_path),
                     ('side', side_path), ('back', back_path)]:
        if not os.path.exists(p):
            print(f"Error: {label} image not found: {p}", file=sys.stderr)
            sys.exit(1)
        img = Image.open(p)
        # Convert to RGB if needed
        if img.mode in ('RGBA', 'P'):
            img = img.convert('RGB')
        images.append(img)

    # Determine target size (uniform: smallest dimension)
    min_w = min(img.width for img in images)
    min_h = min(img.height for img in images)
    resized = [img.resize((min_w, min_h), Image.LANCZOS) for img in images]

    # Create 1x4 grid canvas
    canvas = Image.new('RGB', (min_w * 4, min_h), (255, 255, 255))

    # Place images: front, left, side, back horizontally
    placements = [
        (resized[0], 0, 0),              # front
        (resized[1], min_w, 0),           # left
        (resized[2], min_w * 2, 0),       # side
        (resized[3], min_w * 3, 0),       # back
    ]
    for img, x, y in placements:
        canvas.paste(img, (x, y))

    # Save
    out_path = os.path.join(out_dir, 'merged.png')
    canvas.save(out_path, 'PNG')
    print(f"Four-view saved: {out_path}")
    sys.exit(0)

if __name__ == '__main__':
    main()