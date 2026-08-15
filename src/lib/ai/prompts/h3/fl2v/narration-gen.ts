// ═══════════════════════════════════════════════
// H3 FL2V Narration Generator (v0.3.0)
// Auto-generates off-screen voiceover/narration lines
// for dialogue-free shots in FL2V mode.
// ═══════════════════════════════════════════════

import type { AIProvider } from "@/lib/ai/types";
import { getPromptDefinition } from "@/lib/ai/prompts/registry";

export interface NarrationInput {
  videoScript: string;
  episodeDescription?: string;
  episodeKeywords?: string;
  characters: Array<{ name: string; scope: "main" | "guest"; performanceStyle?: string | null }>;
  duration: number;
}

export interface NarrationOutput {
  /** Narration lines in H3 voiceover format, ready to embed in the prompt */
  lines: string[];
  /** Whether narration was generated (false if no LLM or input insufficient) */
  generated: boolean;
}

/**
 * Generate narration/voiceover lines for a dialogue-free shot.
 *
 * Uses the system AI provider to write:
 * - Historical narration (S0, third-person narrator)
 * - Inner monologue (S1/S2, character offscreen voiceover)
 *
 * Reads system prompt from registry `video_h3_fl2v_narration`.
 *
 * @returns formatted narration lines ready for injection into the H3 prompt.
 */
export async function generateNarration(
  input: NarrationInput,
  textProvider: AIProvider
): Promise<NarrationOutput> {
  // Check minimum input requirements
  if (!input.videoScript?.trim()) {
    return { lines: [], generated: false };
  }

  // Resolve system prompt from registry, with hardcoded fallback
  let systemPrompt: string;
  try {
    const def = getPromptDefinition("video_h3_fl2v_narration");
    if (def) {
      systemPrompt = def.buildFullPrompt({});
    } else {
      systemPrompt = buildFallbackNarrationSystem();
    }
  } catch {
    systemPrompt = buildFallbackNarrationSystem();
  }

  // Build user message with shot context
  const userMessage = buildNarrationUserMessage(input);

  try {
    const raw = await textProvider.generateText(userMessage, {
      systemPrompt,
      temperature: 0.8,
      maxTokens: 500,
    });

    if (!raw?.trim()) {
      console.warn("[H3-FL2V] Narration LLM returned empty response");
      return { lines: [], generated: false };
    }

    // Parse lines — each line should be a valid H3 voiceover format
    const lines = parseNarrationLines(raw);
    if (lines.length === 0) {
      return { lines: [], generated: false };
    }

    console.log(`[H3-FL2V] Generated ${lines.length} narration lines for shot`);
    return { lines, generated: true };
  } catch (e) {
    console.warn("[H3-FL2V] Narration generation failed:", (e as Error).message);
    return { lines: [], generated: false };
  }
}

// ── Helpers ──

function buildNarrationUserMessage(input: NarrationInput): string {
  const parts: string[] = [];

  parts.push("## 镜头视频脚本");
  parts.push(input.videoScript);
  parts.push("");

  if (input.episodeDescription) {
    parts.push("## 剧集背景");
    parts.push(input.episodeDescription);
    if (input.episodeKeywords) parts.push(`关键词: ${input.episodeKeywords}`);
    parts.push("");
  }

  if (input.characters?.length) {
    parts.push("## 出场角色");
    for (const c of input.characters) {
      const role = c.scope === "guest" ? "[客串]" : "[主要]";
      const style = c.performanceStyle ? ` — ${c.performanceStyle}` : "";
      parts.push(`- ${c.name} ${role}${style}`);
    }
    parts.push("");
  }

  parts.push(`## 要求`);
  parts.push(`- 时长: ${input.duration}s`);
  parts.push("- 类型: 旁白（S0 第三人称叙述者）或 内心独白（角色 offscreen voiceover）");
  parts.push("- 格式: (S0) says in an off-screen voiceover: <d>[Chinese] text</d>");
  parts.push("- 旁白解说背景、推进叙事、揭示内心冲突");
  parts.push("- 内心独白自然口语化，符合角色性格");
  parts.push("- 生成 1-3 句");
  parts.push("");
  parts.push("仅输出声音行，不要前言/解释/markdown。");

  return parts.join("\n");
}

function buildFallbackNarrationSystem(): string {
  return [
    "你是一位历史剧旁白编剧。给定镜头上下文，撰写叙事声音。",
    "输出格式: (S0) says in an off-screen voiceover: <d>[Chinese] text</d>",
    "仅输出声音行，不要前言。",
  ].join("\n");
}

/**
 * Parse raw LLM output into individual voiceover lines.
 * Recognizes lines starting with (S0), (S1), (S2) etc.
 */
function parseNarrationLines(raw: string): string[] {
  const lines = raw
    .split("\n")
    .map(l => l.trim())
    .filter(l => l.length > 0);

  // Filter for lines that look like voiceover format
  const voiceoverPattern = /^\(S\d+\)\s/;
  const narrationLines = lines.filter(l => voiceoverPattern.test(l));

  if (narrationLines.length > 0) return narrationLines;

  // Fallback: if no lines match the pattern, treat the whole output as narration
  // (LLM may have omitted speaker IDs)
  if (lines.length > 0) {
    return [`(S0) says in an off-screen voiceover: <d>[Chinese] ${lines.join(" ")}</d>`];
  }

  return [];
}