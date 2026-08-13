#!/usr/bin/env python3
"""
merge_fourview.py — 将四张角度角色图合成为一张四视图（2560x1440），含标题和角度标注。

Environment variables (set by PipelineEngine):
  PIPELINE_FRONT     — 正面图路径
  PIPELINE_LEFT      — 左45度路径
  PIPELINE_SIDE      — 正侧面路径
  PIPELINE_BACK      — 背面路径
  PIPELINE_OUTPUT_DIR     — 输出目录

Output:
  merged.png — 2560x1440 合成四视图
"""
import os
import sys
from PIL import Image, ImageDraw, ImageFont

# --- Output constants ---
TARGET_W = 2560
TARGET_H = 1440
PANEL_W = TARGET_W // 4  # 640
PAD_TOP = 55   # 标题区高度
PAD_BTM = 40   # 标签区高度
IMG_AVAIL_H = TARGET_H - PAD_TOP - PAD_BTM  # 1345

# --- Text constants ---
TITLE_TEXT = "FOUR VIEW CHARACTER SHEET"
LABELS = ["Front", "Quarter", "Side", "Back"]

# --- Font paths ---
FONT_PATHS = {
    "title": "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "label": "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
}
FONT_SIZES = {"title": 24, "label": 16}

# Colors (high contrast against white)
COLOR_TITLE = "#1a1a1a"   # near-black
COLOR_LABEL = "#444444"   # dark gray


def load_fonts():
    """Load title and label fonts with graceful fallback."""
    font_title = None
    font_label = None
    try:
        font_title = ImageFont.truetype(FONT_PATHS["title"], FONT_SIZES["title"])
    except (IOError, OSError):
        pass
    try:
        font_label = ImageFont.truetype(FONT_PATHS["label"], FONT_SIZES["label"])
    except (IOError, OSError):
        pass
    # Fallback: if title font missing, try label font at title size
    if font_title is None and font_label is not None:
        try:
            font_title = ImageFont.truetype(FONT_PATHS["label"], FONT_SIZES["title"])
        except (IOError, OSError):
            pass
    # Final fallback
    if font_title is None:
        font_title = ImageFont.load_default()
    if font_label is None:
        font_label = ImageFont.load_default()
    return font_title, font_label


def text_width(font, text):
    """Get text width (compatible PIL >= 8)."""
    try:
        bbox = font.getbbox(text)
        return bbox[2] - bbox[0]
    except AttributeError:
        return font.getlength(text)


def scale_and_center(img, panel_w, avail_h):
    """
    Scale image to fit within (panel_w x avail_h) preserving aspect ratio.
    Returns (resized_img, x_offset_within_panel).
    """
    scale = min(panel_w / img.width, avail_h / img.height)
    new_w = round(img.width * scale)
    new_h = round(img.height * scale)
    resized = img.resize((new_w, new_h), Image.LANCZOS)
    # Center horizontally within panel
    x_off = (panel_w - new_w) // 2
    return resized, x_off


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
        if img.mode in ('RGBA', 'P'):
            img = img.convert('RGB')
        images.append(img)

    # --- Create canvas 2560x1440 ---
    canvas = Image.new('RGB', (TARGET_W, TARGET_H), (255, 255, 255))

    # --- Scale and place each image ---
    placements = [0, PANEL_W * 1, PANEL_W * 2, PANEL_W * 3]
    for i, (img, x) in enumerate(zip(images, placements)):
        scaled, x_off = scale_and_center(img, PANEL_W, IMG_AVAIL_H)
        y_off = PAD_TOP
        canvas.paste(scaled, (x + x_off, y_off))

    # --- Draw text annotations ---
    try:
        draw = ImageDraw.Draw(canvas)
        font_title, font_label = load_fonts()

        # Title: centered on top
        tw = text_width(font_title, TITLE_TEXT)
        tx = (TARGET_W - tw) / 2
        ty = (PAD_TOP - FONT_SIZES["title"]) // 2
        draw.text((tx, ty), TITLE_TEXT, fill=COLOR_TITLE, font=font_title)

        # Labels: centered under each panel
        for i, label in enumerate(LABELS):
            lw = text_width(font_label, label)
            lx = i * PANEL_W + (PANEL_W - lw) / 2
            ly = PAD_TOP + IMG_AVAIL_H + (PAD_BTM - FONT_SIZES["label"]) // 2
            draw.text((lx, ly), label, fill=COLOR_LABEL, font=font_label)
    except Exception as e:
        # Text rendering failure should not block the composite
        print(f"Warning: Text annotation failed ({e}), saving image-only.", file=sys.stderr)

    # --- Save (deterministic name — avoids stale-file accumulation in runner) ---
    out_path = os.path.join(out_dir, 'merged.png')
    canvas.save(out_path, 'PNG')
    print(f"Four-view saved: {out_path}")
    sys.exit(0)


if __name__ == '__main__':
    main()
