// ═══════════════════════════════════════════════
// H3 Base Mode Builder (v0.2.0)
// Handles T2VA / I2VA / FL2VA modes
//
// Reference: MiniMax H3 official h3-prompt-writing Skill
//   + VIDEO_PROMPT_WRITING_GUIDE_base_en.md §2-4
// ═══════════════════════════════════════════════

import type { H3PromptInput, H3PromptOutput, VisualStyle, ShotScript, SpeakerEvent } from "./types";
import { mapCameraDirection } from "./camera-map";
import { detectLanguage } from "./language-route";

// ═══ LLM-Powered Builder (matches official h3-prompt-writing Skill) ═══

/**
 * Build H3 prompt via IFF LLM optimization.
 * Translates Chinese→English, enriches camera/audio descriptions,
 * structures into 3-section H3 format.
 * Falls back to local buildH3BasePrompt() if LLM unavailable.
 */
export async function buildH3BasePromptLLM(
  input: H3PromptInput,
  apiBase = "http://localhost:8999/v1"
): Promise<H3PromptOutput> {
  try {
    const systemPrompt = buildLLMSystemPrompt(input);
    const response = await fetch(`${apiBase}/chat/completions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: "deepseek-v4-flash",
        messages: [{ role: "system", content: systemPrompt }],
        temperature: 0.7,
        max_tokens: 2000,
      }),
    });
    if (!response.ok) throw new Error(`IFF ${response.status}`);
    const data = await response.json();
    const raw: string = data.choices?.[0]?.message?.content?.trim() || "";
    if (!raw) throw new Error("Empty LLM response");
    return { mode: "base", taskType: "keyframe_completion", languageUsed: "en", sections: parseLLMSections(raw, input) };
  } catch (e) {
    console.warn("[H3] LLM fallback to local:", (e as Error).message);
    return buildH3BasePrompt(input);
  }
}

function buildLLMSystemPrompt(input: H3PromptInput): string {
  const script = input.videoScript || "";
  const camera = mapCameraDirection(input.cameraDirection);
  const duration = input.duration || 10;
  const chars = input.characters?.map(c => `${c.name}: ${c.description || ""} ${c.visualHint || ""}`.trim()).join("; ") || "none";
  const sound = input.soundDesign || "no specific sounds";
  const bgm = input.musicCue || input.bgmUrl ? (input.musicCue || "background music") : "none";
  const hasFirst = !!input.firstFrame?.fileUrl;
  const hasLast = !!input.lastFrame?.fileUrl;

  let prefix = "";
  if (hasFirst && hasLast) {
    prefix = `How the reference pictures align with the target video — <Picture 1> (from [Shot 1]) aligns with the 0.00-second mark of the target video; <Picture 2> (from [Shot 1]) aligns with the ${duration.toFixed(2)}-second mark of the target video.`;
  } else if (hasFirst) {
    prefix = `For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.`;
  }

  return [
    "You are a video prompt engineer for MiniMax H3 (I2VA/FL2VA mode).",
    "Transform the user input into a 3-section H3 structured prompt.",
    "",
    "OUTPUT FORMAT (exactly):",
    prefix ? `${prefix}\n\nintegrated_multimodal_description:\n[Shot 1] ...` : "integrated_multimodal_description:\n[Shot 1] ...",
    "",
    "overall_soundscape: ...",
    "non_diegetic_music: ...",
    "",
    "RULES:",
    "- ALL output in English (translate Chinese input to cinematic English prose)",
    "- integrated_multimodal_description: describe the scene in rich cinematic detail",
    `  Camera: ${camera}`,
    "- DO NOT add extra commentary, markdown, or section labels beyond the 3 fields",
    "- overall_soundscape: 1-2 sentences of ambient and diegetic sounds",
    "- non_diegetic_music: instrumentation, tempo, dynamics — use N/A if none",
    "",
    "INPUT DATA:",
    `Script: ${script}`,
    `Characters: ${chars}`,
    `Duration: ${duration}s`,
    `Camera: ${camera}`,
    `Sound Design: ${sound}`,
    `Music Cue: ${bgm}`,
  ].join("\n");
}

function parseLLMSections(raw: string, input: H3PromptInput): string[] {
  const sections: string[] = [];
  
  // Extract instruction prefix if present
  const prefixMatch = raw.match(/^(How the reference pictures align[\s\S]*?video\.|For the target video[\s\S]*?referenced\.)/);
  let prefix = prefixMatch ? prefixMatch[1] : "";
  let body = prefixMatch ? raw.slice(prefixMatch[0].length).trim() : raw;

  // Try parsing the 3 H3 fields
  const imdMatch = body.match(/integrated_multimodal_description:\s*([\s\S]*?)(?=\n\s*overall_soundscape:|$)/i);
  const osMatch = body.match(/overall_soundscape:\s*([\s\S]*?)(?=\n\s*non_diegetic_music:|$)/i);
  const nmMatch = body.match(/non_diegetic_music:\s*([\s\S]*)/i);

  const imd = imdMatch ? `integrated_multimodal_description:\n${imdMatch[1].trim()}` : `integrated_multimodal_description:\n[Shot 1] ${input.videoScript}`;
  const os = osMatch ? `overall_soundscape: ${osMatch[1].trim()}` : `overall_soundscape: ${input.soundDesign || "N/A"}`;
  const nm = nmMatch ? `non_diegetic_music: ${nmMatch[1].trim()}` : `non_diegetic_music: ${input.musicCue || "N/A"}`;

  sections.push(prefix ? `${prefix}\n\n${imd}` : imd);
  sections.push(os);
  sections.push(nm);
  return sections;
}

// ═══ Local Builder (format-only, no LLM) ═══

export function buildH3BasePrompt(input: H3PromptInput): H3PromptOutput {
  const lang = input.languageMode === "auto" ? detectLanguage(input.videoScript) : input.languageMode as "en" | "zh";
  const style = inferVisualStyle(input);
  const speakers = buildSpeakerEvents(input);
  const shots = buildShotScripts(input, speakers);
  const prefix = buildInstructionPrefix(input);

  return {
    mode: "base",
    taskType: input.generationMode === "reference" ? "reference_generation" : "keyframe_completion",
    languageUsed: lang,
    sections: [
      buildIntegratedSection(prefix, style, shots, lang),
      buildSoundscape(input),
      buildNonDiegeticMusic(input),
    ],
  };
}

// ═══ Local helpers (unchanged) ═══

function buildInstructionPrefix(input: H3PromptInput): string | null {
  if (!input.firstFrame?.fileUrl) return null;
  if (input.lastFrame?.fileUrl) {
    return [
      "How the reference pictures align with the target video — ",
      "<Picture 1> (from [Shot 1]) aligns with the 0.00-second mark of the target video; ",
      `<Picture 2> (from [Shot 1]) aligns with the ${input.duration.toFixed(2)}-second mark of the target video.`
    ].join("");
  }
  return "For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.";
}

function inferVisualStyle(input: H3PromptInput): VisualStyle {
  const combined = (input.videoScript + " " + (input.sceneDescription ?? "")).toLowerCase();
  if (combined.includes("anime") || combined.includes("cartoon")) return "2D-animated";
  if (combined.includes("3d") || combined.includes("cg")) return "3D CG";
  return input.characters.some(c => c.referenceImage) ? "live-action" : "Cinematic";
}

function buildSpeakerEvents(input: H3PromptInput): SpeakerEvent[] {
  if (!input.dialogues?.length) return [];
  const seen = new Map<string, string>();
  let nextId = 1;
  return input.dialogues.filter(d => d.text?.trim()).map(d => {
    let sid = seen.get(d.characterName);
    if (!sid) { sid = `S${nextId++}`; seen.set(d.characterName, sid); }
    return {
      speakerId: sid,
      subjectLabel: undefined,
      lineText: d.text,
      language: detectLanguage(d.text) === "zh" ? "Chinese" : "English",
      isOffscreen: d.offscreen,
      timeInShot: `after ${d.startRatio}`,
    };
  });
}

function buildShotScripts(input: H3PromptInput, speakers: SpeakerEvent[]): ShotScript[] {
  return [{
    index: 1, timestampSeconds: 0,
    visualDescription: input.videoScript,
    cameraMotion: mapCameraDirection(input.cameraDirection),
    speakerEvents: speakers,
    diegeticSounds: [],
  }];
}

function buildIntegratedSection(prefix: string | null, style: VisualStyle, shots: ShotScript[], _lang: string): string {
  const lines: string[] = [];
  if (prefix) { lines.push(prefix); lines.push(""); }
  lines.push("integrated_multimodal_description:");
  for (const s of shots) {
    let line = `[Shot 1] ${style}, ${s.visualDescription} ${s.cameraMotion}.`;
    for (const spk of s.speakerEvents) {
      line += ` (${spk.speakerId}) says: <d>[${spk.language}] ${spk.lineText}</d>`;
    }
    lines.push(line);
  }
  return lines.join("\n");
}

function buildSoundscape(input: H3PromptInput): string {
  return `overall_soundscape: ${input.soundDesign || "N/A"}`;
}

function buildNonDiegeticMusic(input: H3PromptInput): string {
  if (input.bgmUrl) return "non_diegetic_music: <Audio 1> is referenced as the background score.";
  return `non_diegetic_music: ${input.musicCue || "N/A"}`;
}