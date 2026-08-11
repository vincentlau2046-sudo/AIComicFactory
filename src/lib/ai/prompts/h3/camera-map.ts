// ═══════════════════════════════════════════════
// H3 Camera Vocabulary Mapper (v0.2.0)
//
// Reference: MiniMax H3 official VIDEO_PROMPT_WRITING_GUIDE_base_en.md §4.3
//
// Format: "the camera {motion_type} {amplitude?} {speed?}"
//   Motion type: Zoom In/Out, Push/Pull, Pan, Truck, Tilt, etc.
//   Amplitude: "with small amplitude" | "with large amplitude"
//   Speed: "at slow speed" | "at fast speed"
// ═══════════════════════════════════════════════

const MOTION: Record<string, string> = {
  "zoom in": "zooms in", "zoom out": "zooms out",
  "推镜": "zooms in", "拉镜": "zooms out",
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
  "固定": "holds a static shot", "静止": "holds a static shot",
  "shake slight": "shakes slightly", "shake strong": "shakes strongly",
  "handheld": "shakes slightly as a handheld shot",
  "手持": "shakes slightly as a handheld shot",
  "pov": "shows the subject's point of view",
  "roll cw": "rolls clockwise around the lens axis",
  "roll ccw": "rolls counterclockwise around the lens axis",
};

type AmpModifier = "" | "with small amplitude" | "with large amplitude";
type SpeedModifier = "" | "at slow speed" | "at fast speed";

/**
 * Map AICF free-text cameraDirection → H3 official camera vocabulary.
 *
 * Parsing: [motion_type] [speed?] [amplitude?]
 *
 * Examples:
 *   "static"          → "the camera holds a static shot"
 *   "push in"         → "the camera pushes in with small amplitude at slow speed"
 *   "push in fast"    → "the camera pushes in with small amplitude at fast speed"
 *   "pan left large"  → "the camera pans left with large amplitude at slow speed"
 *   "push in fast large" → "the camera pushes in with large amplitude at fast speed"
 */
export function mapCameraDirection(raw: string): string {
  const lower = raw.toLowerCase().trim();
  if (!lower) return "the camera holds a static shot";

  // Parse tokens
  const tokens = lower.split(/\s+/);
  let motionType = "";
  let amplitude: AmpModifier = "";
  let speed: SpeedModifier = "";

  // Try multi-word motion matches first (2-3 tokens)
  for (let len = Math.min(3, tokens.length); len >= 1; len--) {
    const phrase = tokens.slice(0, len).join(" ");
    if (MOTION[phrase]) {
      motionType = MOTION[phrase];
      tokens.splice(0, len);
      break;
    }
  }

  // Single word fallback
  if (!motionType) {
    for (const [key, val] of Object.entries(MOTION)) {
      if (lower.startsWith(key)) {
        motionType = val;
        tokens.splice(0, key.split(/\s+/).length);
        break;
      }
    }
  }

  if (!motionType) {
    return `the camera: [Raw: ${raw}]`;
  }

  // Parse remaining tokens for speed/amplitude modifiers
  const SPEED_MAP: Record<string, SpeedModifier> = {
    "slow": "at slow speed", "fast": "at fast speed",
    "慢": "at slow speed", "快": "at fast speed",
  };
  const AMP_MAP: Record<string, AmpModifier> = {
    "small": "with small amplitude", "large": "with large amplitude",
    "微": "with small amplitude", "大": "with large amplitude",
  };

  for (const t of tokens) {
    if (SPEED_MAP[t]) speed = SPEED_MAP[t];
    else if (AMP_MAP[t]) amplitude = AMP_MAP[t];
  }

  // Apply defaults based on motion type
  const needsAmp = !["holds", "shows", "shakes"].some(k => motionType.includes(k));
  const needsSpeed = !["holds", "shows"].some(k => motionType.includes(k));

  if (!amplitude && needsAmp) amplitude = "with small amplitude";
  if (!speed && needsSpeed) speed = "at slow speed";

  const parts = [`the camera ${motionType}`];
  if (amplitude) parts.push(amplitude);
  if (speed) parts.push(speed);

  return parts.join(" ");
}