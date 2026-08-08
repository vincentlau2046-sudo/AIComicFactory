/**
 * size.ts — 分辨率尺寸公共函数层
 *
 * 所有图像/视频生成路径统一从此映射 ratio → 像素尺寸。
 * 单点维护，避免各 handler 各自硬编码。
 *
 * 来源: storyboard 页面的 VideoRatioPicker → payload.ratio
 *
 *   storyboard page (videoRatio state)
 *     └─ payload.ratio
 *        ├─ 图像 handler  → ratioToSize() → "2560x1440"
 *        └─ 视频 handler  → ensureResolution() → 960×544 (H3 专用)
 */

const RATIO_TO_SIZE: Record<string, string> = {
  "16:9": "2560x1440",
  "9:16": "1440x2560",
  "1:1":  "2048x2048",
};

const DEFAULT_RATIO = "16:9";

/** 根据 ratio 获取尺寸字符串，如 "16:9" → "2560x1440" */
export function ratioToSize(ratio?: string | null): string {
  return RATIO_TO_SIZE[ratio || DEFAULT_RATIO] || RATIO_TO_SIZE[DEFAULT_RATIO];
}

/** 解析 "WxH" 字符串为 { width, height } */
export function parseSize(size: string): { width: number; height: number } {
  const [w, h] = size.split("x").map(Number);
  return { width: w || 1024, height: h || 1024 };
}

/** 一步到位: ratio → { width, height } */
export function sizeFromRatio(ratio?: string | null) {
  return parseSize(ratioToSize(ratio));
}