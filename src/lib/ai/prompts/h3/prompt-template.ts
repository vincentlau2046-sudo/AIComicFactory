// ═══════════════════════════════════════════════
// H3 Video Prompt — 3-Layer Context Engineering
// Based on MiniMax official h3-prompt-writing Skill
//   + VIDEO_PROMPT_WRITING_GUIDE_base_en.md
// ═══════════════════════════════════════════════

import type { H3PromptInput } from "./types";
import { mapCameraDirection } from "./camera-map";

/**
 * Layer 1: Content Assembly
 * Gather all context from AICF data pipeline:
 *   script → episode → shot → characters → scene → audio
 */
function buildContentLayer(input: H3PromptInput): string {
  const parts: string[] = [];

  // ── Video Script (from shot_split pipeline) ──
  parts.push("## VIDEO SCRIPT");
  parts.push(input.videoScript || "(no script)");
  parts.push("");

  // ── Characters (from character_extract) ──
  if (input.characters?.length) {
    parts.push("## CHARACTERS");
    for (const c of input.characters) {
      const details = [
        c.name,
        c.description ? `— ${c.description}` : "",
        c.visualHint ? `(visual: ${c.visualHint})` : "",
        c.performanceStyle ? `[performance: ${c.performanceStyle}]` : "",
        c.scope === "guest" ? "[guest role]" : "",
      ].filter(Boolean).join(" ");
      parts.push(`- ${details}`);
    }
    parts.push("");
  }

  // ── Scene Context ──
  if (input.sceneDescription || input.sceneLighting || input.sceneColorPalette) {
    parts.push("## SCENE");
    if (input.sceneDescription) parts.push(`Location: ${input.sceneDescription}`);
    if (input.sceneLighting) parts.push(`Lighting: ${input.sceneLighting}`);
    if (input.sceneColorPalette) parts.push(`Color palette: ${input.sceneColorPalette}`);
    parts.push("");
  }

  // ── Episode Context ──
  if (input.episodeDescription) {
    parts.push("## EPISODE CONTEXT");
    parts.push(input.episodeDescription);
    if (input.episodeKeywords) parts.push(`Keywords: ${input.episodeKeywords}`);
    parts.push("");
  }

  // ── Audio ──
  const hasSound = input.soundDesign || input.musicCue || input.bgmUrl;
  if (hasSound) {
    parts.push("## AUDIO");
    if (input.soundDesign) parts.push(`Diegetic sound: ${input.soundDesign}`);
    if (input.musicCue) parts.push(`Music cue: ${input.musicCue}`);
    if (input.bgmUrl) parts.push(`BGM reference: <Audio 1>`);
    parts.push("");
  }

  return parts.join("\n").trim();
}

/**
 * Layer 2: Constraints & Format Rules
 * H3-specific output requirements aligned with official guide.
 */
function buildConstraintLayer(input: H3PromptInput): string {
  const camera = mapCameraDirection(input.cameraDirection);
  const duration = input.duration || 10;
  const hasFirst = !!input.firstFrame?.fileUrl;
  const hasLast = !!input.lastFrame?.fileUrl;

  const rules: string[] = [
    "## CONSTRAINTS",
    "",
    "### Format (exact output structure):",
  ];

  // Instruction prefix
  if (hasFirst && hasLast) {
    rules.push(
      `First line MUST be exactly:\n` +
      `How the reference pictures align with the target video — <Picture 1> (from [Shot 1]) aligns with the 0.00-second mark of the target video; <Picture 2> (from [Shot 1]) aligns with the ${duration.toFixed(2)}-second mark of the target video.`
    );
    rules.push("");
  }

  rules.push(
    "Then output exactly these 3 sections:",
    "",
    "integrated_multimodal_description:",
    "  [Shot 1] {Cinematic/live-action/2D-animated}, {detailed scene description in English}. {camera motion}. For each speaking character, use (S1), (S2) speaker IDs and <d>[Chinese] dialogue text</d>.",
    "",
    "overall_soundscape:",
    "  1-2 sentences in English describing ambient and physical sounds (rain, wind, footsteps, impacts, breathing). Use N/A only if the script explicitly requests complete silence.",
    "",
    "non_diegetic_music:",
    "  1-2 sentences describing background score: instrumentation, tempo, dynamics. Use N/A if no BGM.",
    "",
    "### Hard Rules:",
    "1. ALL output in English EXCEPT dialogue inside <d> tags (preserve original Chinese)",
    `2. Camera motion: ${camera}`,
    `3. Duration: ${duration}s — pace the action to fit this timeframe`,
    "4. [Shot 1] has NO timestamp. If splitting into multiple shots, use [Shot 2] At MM:SS.SSS format",
    "5. For each speaking character, assign stable (S1), (S2) IDs in first-appearance order",
    "6. Dialogue format: (S1) says: <d>[Chinese] 原文台词</d>",
    "7. Off-screen voices: (S1) says in an off-screen voiceover: <d>...</d> while lips remain completely closed",
    "8. NO markdown, NO code blocks, NO commentary — pure H3 format output",
    "9. DO NOT copy the Chinese video script verbatim — translate and enrich into cinematic English prose",
  );

  return rules.join("\n");
}

/**
 * Layer 3: Guide — System prompt with format reference
 * Based on official MiniMax VIDEO_PROMPT_WRITING_GUIDE + h3-prompt-writing Skill.
 */
function buildGuideLayer(): string {
  return [
    "## ROLE",
    "You are an expert prompt engineer for MiniMax H3 (I2VA/FL2VA mode), a video generation model that produces synchronized video+audio from structured text prompts.",
    "",
    "## TASK",
    "Transform the provided video script + context data into a H3-compatible 3-section prompt. The output will be sent directly to MiniMax H3 for video generation.",
    "",
    "## PROCESS",
    "1. Read the VIDEO SCRIPT — this is the primary narrative source",
    "2. Read CHARACTERS — understand who appears and their visual traits",
    "3. Read SCENE context — lighting, location, color palette if provided",
    "4. Read AUDIO — diegetic sound and music cues if provided",
    "5. Apply CONSTRAINTS — follow the exact output format and hard rules",
    "6. Generate the 3-section H3 prompt in English",
    "",
    "## TRANSLATION RULES",
    "- Translate Chinese script to cinematic English prose (do NOT copy verbatim)",
    "- Preserve character names, place names, and dialogue in original language",
    "- Enrich descriptions: add atmospheric detail, lighting, composition notes",
    "- Camera motion: expand to full H3 vocabulary with amplitude+speed modifiers",
    "",
    "## OUTPUT",
    "Only the 3-section H3 prompt. No introduction, no markdown, no commentary.",
  ].join("\n");
}

/**
 * Assemble the full 3-layer prompt for a single LLM call.
 */
export function buildH3PromptTemplate(input: H3PromptInput): { system: string; user: string } {
  return {
    system: buildGuideLayer(),
    user: [
      buildContentLayer(input),
      "",
      buildConstraintLayer(input),
    ].join("\n"),
  };
}