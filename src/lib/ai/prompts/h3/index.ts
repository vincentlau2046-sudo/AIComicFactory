// ═══════════════════════════════════════════════
// H3 Prompt Builder — Main Export (v0.2.0 stub)
// Replaced by full implementation in Phase 2
// ═══════════════════════════════════════════════

import type { H3PromptInput, H3PromptOutput } from "./types";
import { detectLanguage } from "./language-route";
import { mapCameraDirection } from "./camera-map";

/** Placeholder — replaced in Phase 2 */
export function buildVideoPrompt(input: H3PromptInput): H3PromptOutput {
  const lang = input.languageMode === "auto"
    ? detectLanguage(input.videoScript)
    : input.languageMode as "en" | "zh";

  // Stub: output as structured 3-section format
  const camera = mapCameraDirection(input.cameraDirection);
  const lines: string[] = [];

  // Section 1: instruction prefix + integrated_multimodal_description
  if (input.firstFrame?.fileUrl && input.lastFrame?.fileUrl) {
    lines.push(
      "How the reference pictures align with the target video — " +
      `<Picture 1> (from [Shot 1]) aligns with the 0.00-second mark of the target video; ` +
      `<Picture 2> (from [Shot 1]) aligns with the ${input.duration.toFixed(2)}-second mark of the target video.`
    );
    lines.push("");
  }
  lines.push(`integrated_multimodal_description:\n[Shot 1] Cinematic, ${input.videoScript} ${camera}.`);

  // Section 2: overall_soundscape
  lines.push(`\noverall_soundscape:\n${input.soundDesign ?? "N/A"}`);

  // Section 3: non_diegetic_music
  const bgm = input.bgmUrl
    ? "<Audio 1> is referenced as the background score."
    : (input.musicCue ?? "N/A");
  lines.push(`\nnon_diegetic_music:\n${bgm}`);

  return {
    sections: [lines.join("\n")],
    mode: "base",
    taskType: "keyframe_completion",
    languageUsed: lang,
  };
}