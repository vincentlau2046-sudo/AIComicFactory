// ═══════════════════════════════════════════════
// H3 FL2V Builder — LLM + local fallback (v0.3.0)
// Reads Guide/Content/Constraint layers from prompt registry.
// Phase 2: auto-generates narration for dialogue-free shots.
// ═══════════════════════════════════════════════

import type { AIProvider } from "@/lib/ai/types";
import type { H3PromptInput, H3PromptOutput } from "../types";
import { buildFL2VPromptTemplate } from "./prompt-template";
import { resolveLanguage, buildH3Sections, parseLLMSections } from "../shared/base-builder";
import { generateNarration } from "./narration-gen";

/**
 * FL2V LLM builder — calls system AI provider with registry-sourced template.
 * Falls back to local formatting on failure.
 *
 * Phase 2: If the shot has no dialogues, automatically generates narration lines
 * (historical context / inner monologue) via the same textProvider before
 * building the main prompt template.
 */
export async function buildFL2VPromptLLM(
  input: H3PromptInput,
  textProvider: AIProvider,
  systemOverride?: string
): Promise<H3PromptOutput> {
  const lang = resolveLanguage(input);

  // Phase 2: Auto-generate narration only when explicitly enabled per shot
  const narrationEnabled = input.activeModules?.includes("narration") && input.enableNaration;
  if (narrationEnabled && !input.narrations?.length) {
    try {
      const narration = await generateNarration(
        {
          videoScript: input.videoScript,
          episodeDescription: input.episodeDescription,
          episodeKeywords: input.episodeKeywords,
          characters: input.characters.map(c => ({
            name: c.name,
            scope: c.scope,
            performanceStyle: c.performanceStyle,
          })),
          duration: input.duration,
        },
        textProvider
      );
      if (narration.generated && narration.lines.length > 0) {
        input = { ...input, narrations: narration.lines };
      }
    } catch (e) {
      console.warn("[H3-FL2V] Narration generation skipped:", (e as Error).message);
    }
  }

  try {
    const { system, user } = await buildFL2VPromptTemplate(input, systemOverride);

    const raw = await textProvider.generateText(user, {
      systemPrompt: system,
      temperature: 0.7,
      maxTokens: 32000,
    });

    if (!raw?.trim()) throw new Error("[H3-FL2V] Empty LLM response");

    return {
      mode: "base",
      taskType: "keyframe_completion",
      languageUsed: lang === "zh" ? "zh" : "en",
      sections: parseLLMSections(raw, input, lang),
    };
  } catch (e) {
    console.warn("[H3-FL2V] LLM call failed, falling back to local builder:", (e as Error).message);
    return buildFL2VPrompt(input);
  }
}

/** Local fallback — no LLM, uses shared base builder. */
export function buildFL2VPrompt(input: H3PromptInput): H3PromptOutput {
  return buildH3Sections(input);
}