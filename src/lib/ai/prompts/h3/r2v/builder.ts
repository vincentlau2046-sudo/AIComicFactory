// ═══════════════════════════════════════════════
// H3 R2V Builder — Vision LLM + local fallback (v0.3.9)
// Follows FL2V pattern: LLM → Registry template → parse → fallback.
// R2V unique: includes reference images (scene frames + characters).
// ═══════════════════════════════════════════════

import type { AIProvider } from "@/lib/ai/types";
import type { H3PromptInput, H3PromptOutput } from "../types";
import { buildR2VPromptTemplate } from "./prompt-template";
import { buildR2VPrompt } from "./ref-builder";
import { resolveLanguage, parseLLMSections } from "../shared/base-builder";

/**
 * R2V Vision LLM builder.
 *
 * Phase 1 (try): Vision LLM with reference images → 6-section H3 prompt.
 * Phase 2 (fallback): local heuristics via buildR2VPrompt (no images).
 *
 * @param input — full H3PromptInput (characters, scenes, motion, etc.)
 * @param visionProvider — AI provider with vision support (gemma4-31b-vl, qwen3-vl, etc.)
 * @param sceneFramePaths — file paths for scene frame images (0-4 per shot)
 * @param systemOverride — optional Registry slot override for system prompt
 */
export async function buildR2VPromptLLM(
  input: H3PromptInput,
  visionProvider: AIProvider,
  sceneFramePaths: string[],
  systemOverride?: string,
): Promise<{ output: H3PromptOutput; source: "vl" | "fallback" }> {
  const lang = resolveLanguage(input);

  try {
    const { system, user } = await buildR2VPromptTemplate(input, systemOverride);

    const raw = await visionProvider.generateText(user, {
      systemPrompt: system,
      images: sceneFramePaths,
      temperature: 0.7,
    });

    if (!raw?.trim()) throw new Error("[H3-R2V] Empty VL response");

    const sections = parseLLMSections(raw, input, lang);

    return {
      output: {
        mode: "ref2va" as const,
        taskType: "reference_generation" as const,
        languageUsed: lang === "zh" ? "zh" : "en",
        sections,
      },
      source: "vl",
    };
  } catch (e) {
    console.warn("[H3-R2V] VL call failed, falling back to local builder:", (e as Error).message);
    return {
      output: buildR2VPrompt(input),
      source: "fallback",
    };
  }
}