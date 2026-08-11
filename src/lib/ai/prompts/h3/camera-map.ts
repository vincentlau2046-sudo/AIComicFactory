// ═══════════════════════════════════════════════
// H3 Camera Vocabulary Mapper (v0.2.0)
// Maps AICF free-text cameraDirection → H3 official vocabulary
// Source: Official VIDEO_PROMPT_WRITING_GUIDE_base_en.md §4.3
// ═══════════════════════════════════════════════

const CAMERA_TYPES: Record<string, string> = {
  "zoom in": "zooms in", "zoom out": "zooms out",
  "push in": "pushes in", "push": "pushes in",
  "pull out": "pulls out", "pull": "pulls out",
  "dolly in": "pushes in", "dolly out": "pulls out",
  "pan left": "pans left", "pan right": "pans right", "pan": "pans left",
  "truck left": "trucks left", "truck right": "trucks right",
  "tilt up": "tilts up", "tilt down": "tilts down",
  "pedestal up": "pedestals up", "pedestal down": "pedestals down",
  "arc": "arcs around the subject", "arc shot": "arcs around the subject",
  "tracking": "tracks the moving subject", "tracking shot": "tracks the moving subject",
  "follow": "tracks the moving subject",
  "static": "holds a static shot", "still": "holds a static shot",
  "shake slight": "shakes slightly", "shake strong": "shakes strongly",
  "handheld": "shakes slightly as a handheld shot",
  "pov": "shows the subject's point of view",
  "roll cw": "rolls clockwise around the lens axis",
  "roll ccw": "rolls counterclockwise around the lens axis",
  "推镜": "zooms in", "拉镜": "zooms out",
  "固定": "holds a static shot", "静止": "holds a static shot",
  "手持": "shakes slightly as a handheld shot",
};

export function mapCameraDirection(raw: string): string {
  const lower = raw.toLowerCase().trim();
  if (!lower) return "the camera holds a static shot";

  // Try exact match
  if (CAMERA_TYPES[lower]) return `the camera ${CAMERA_TYPES[lower]}`;

  // Try prefix match
  for (const [key, val] of Object.entries(CAMERA_TYPES)) {
    if (lower.startsWith(key)) return `the camera ${val}`;
  }

  // Fallback
  return `the camera moves: [Raw: ${raw}]`;
}