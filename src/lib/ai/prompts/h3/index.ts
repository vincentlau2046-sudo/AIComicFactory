// ═══════════════════════════════════════════════
// H3 Prompt Builder — Main Export (v0.2.0)
// ═══════════════════════════════════════════════

import type { AIProvider } from "@/lib/ai/types";
import type { H3PromptInput, H3PromptOutput } from "./types";
import { buildH3BasePrompt, buildH3BasePromptLLM } from "./base-mode";
import { buildH3Ref2VAPrompt } from "./ref-mode";

/**
 * LLM-optimized builder (preferred for production — uses system AI provider).
 *
 * @param input           All context data from AICF pipeline
 * @param textProvider    System AI provider from resolveAIProvider(modelConfig)
 * @param systemOverride  Optional system prompt from prompt registry
 */
export async function buildVideoPromptLLM(
  input: H3PromptInput,
  textProvider: AIProvider,
  systemOverride?: string
): Promise<H3PromptOutput> {
  if (input.generationMode === "reference") return buildH3Ref2VAPrompt(input);
  return buildH3BasePromptLLM(input, textProvider, systemOverride);
}

/** Local builder (format-only, no LLM — fast fallback) */
export function buildVideoPrompt(input: H3PromptInput): H3PromptOutput {
  if (input.generationMode === "reference") return buildH3Ref2VAPrompt(input);
  return buildH3BasePrompt(input);
}

export type { H3PromptInput, H3PromptOutput };