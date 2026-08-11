// ═══════════════════════════════════════════════
// H3 Prompt Builder — Main Export (v0.2.0)
// ═══════════════════════════════════════════════

import type { H3PromptInput, H3PromptOutput } from "./types";
import { buildH3BasePrompt, buildH3BasePromptLLM } from "./base-mode";
import { buildH3Ref2VAPrompt } from "./ref-mode";

/** LLM-optimized builder (preferred for production — uses IFF to enrich content) */
export async function buildVideoPromptLLM(input: H3PromptInput): Promise<H3PromptOutput> {
  if (input.generationMode === "reference") return buildH3Ref2VAPrompt(input);
  return buildH3BasePromptLLM(input);
}

/** Local builder (format-only, no LLM — fast fallback) */
export function buildVideoPrompt(input: H3PromptInput): H3PromptOutput {
  if (input.generationMode === "reference") return buildH3Ref2VAPrompt(input);
  return buildH3BasePrompt(input);
}

export type { H3PromptInput, H3PromptOutput };