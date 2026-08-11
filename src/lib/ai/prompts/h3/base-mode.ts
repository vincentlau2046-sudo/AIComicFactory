// ═══════════════════════════════════════════════
// H3 Base Mode Builder (v0.2.0)
// LLM-optimized via 3-layer context engineering
// ═══════════════════════════════════════════════

import type { H3PromptInput, H3PromptOutput } from "./types";
import { buildH3PromptTemplate } from "./prompt-template";
import { mapCameraDirection } from "./camera-map";
import { detectLanguage } from "./language-route";

/**
 * Build H3 prompt via LLM with 3-layer context template.
 * Single IFF call: system=guide, user=content+constraints.
 * Falls back to local formatting on failure.
 */
export async function buildH3BasePromptLLM(
  input: H3PromptInput,
  apiBase = "http://localhost:8999/v1"
): Promise<H3PromptOutput> {
  try {
    const { system, user } = buildH3PromptTemplate(input);

    const response = await fetch(`${apiBase}/chat/completions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: "deepseek-v4-flash",
        messages: [
          { role: "system", content: system },
          { role: "user", content: user },
        ],
        temperature: 0.7,
        max_tokens: 3000,
      }),
    });

    if (!response.ok) throw new Error(`IFF ${response.status}`);
    const data = await response.json();
    const raw: string = data.choices?.[0]?.message?.content?.trim() || "";
    if (!raw) throw new Error("Empty LLM response");

    return {
      mode: "base",
      taskType: "keyframe_completion",
      languageUsed: "en",
      sections: parseLLMSections(raw, input),
    };
  } catch (e) {
    console.warn("[H3] LLM fallback:", (e as Error).message);
    return buildH3BasePrompt(input);
  }
}

/**
 * Local builder — format-only, no LLM. Used as fallback.
 */
export function buildH3BasePrompt(input: H3PromptInput): H3PromptOutput {
  const prefix = buildInstructionPrefix(input);
  const camera = mapCameraDirection(input.cameraDirection);
  return {
    mode: "base",
    taskType: "keyframe_completion",
    languageUsed: "en",
    sections: [
      prefix
        ? `${prefix}\n\nintegrated_multimodal_description:\n[Shot 1] ${input.videoScript} ${camera}.`
        : `integrated_multimodal_description:\n[Shot 1] ${input.videoScript} ${camera}.`,
      `overall_soundscape: ${input.soundDesign || "N/A"}`,
      input.bgmUrl
        ? "non_diegetic_music: <Audio 1> is referenced as the background score."
        : `non_diegetic_music: ${input.musicCue || "N/A"}`,
    ],
  };
}

// ── Helpers ──

function buildInstructionPrefix(input: H3PromptInput): string | null {
  if (!input.firstFrame?.fileUrl) return null;
  if (input.lastFrame?.fileUrl) {
    return [
      "How the reference pictures align with the target video — ",
      "<Picture 1> (from [Shot 1]) aligns with the 0.00-second mark of the target video; ",
      `<Picture 2> (from [Shot 1]) aligns with the ${input.duration.toFixed(2)}-second mark of the target video.`,
    ].join("");
  }
  return "For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.";
}

function parseLLMSections(raw: string, input: H3PromptInput): string[] {
  const sections: string[] = [];

  // Extract instruction prefix
  const prefixMatch = raw.match(
    /^(How the reference pictures align[\s\S]*?video\.|For the target video[\s\S]*?referenced\.)/
  );
  const prefix = prefixMatch ? prefixMatch[1] : "";
  const body = prefixMatch ? raw.slice(prefixMatch[0].length).trim() : raw;

  // Extract 3 H3 fields
  const imd = body.match(/integrated_multimodal_description:\s*([\s\S]*?)(?=\n\s*overall_soundscape:|\n\s*non_diegetic_music:|$)/i);
  const os = body.match(/overall_soundscape:\s*([\s\S]*?)(?=\n\s*non_diegetic_music:|$)/i);
  const nm = body.match(/non_diegetic_music:\s*([\s\S]*)/i);

  sections.push(
    imd
      ? (prefix ? `${prefix}\n\nintegrated_multimodal_description:\n${imd[1].trim()}` : `integrated_multimodal_description:\n${imd[1].trim()}`)
      : `integrated_multimodal_description:\n[Shot 1] ${input.videoScript}`
  );
  sections.push(
    os ? `overall_soundscape: ${os[1].trim()}` : `overall_soundscape: ${input.soundDesign || "N/A"}`
  );
  sections.push(
    nm ? `non_diegetic_music: ${nm[1].trim()}` : `non_diegetic_music: ${input.musicCue || "N/A"}`
  );

  return sections;
}