// ═══════════════════════════════════════════════
// H3 Prompt Builder — Mode Dispatcher (v0.3.0)
// Routes to mode-specific builders: FL2V | R2V | T2V
// ═══════════════════════════════════════════════

import type { AIProvider } from "@/lib/ai/types";
import type { H3PromptInput, H3PromptOutput } from "./types";

/**
 * Build H3 prompt via LLM (production path).
 * Dispatches to mode-specific builder based on input.generationMode.
 *
 * @param input           All context data from AICF pipeline
 * @param textProvider    System AI provider
 * @param systemOverride  Optional system prompt override
 */
export async function buildVideoPromptLLM(
  input: H3PromptInput,
  textProvider: AIProvider,
  systemOverride?: string,
  images?: string[]
): Promise<H3PromptOutput> {
  if (input.generationMode === "reference") {
    const { buildR2VPrompt } = await import("./r2v/ref-builder");
    return buildR2VPrompt(input);
  }
  // Default: FL2V (keyframe mode)
  const { buildFL2VPromptLLM } = await import("./fl2v/builder");
  return buildFL2VPromptLLM(input, textProvider, systemOverride, images);
}

/** Local builder — no LLM, fast fallback */
export function buildVideoPrompt(input: H3PromptInput): H3PromptOutput {
  if (input.generationMode === "reference") {
    const { buildR2VPrompt } = require("./r2v/ref-builder");
    return buildR2VPrompt(input);
  }
  const { buildFL2VPrompt } = require("./fl2v/builder");
  return buildFL2VPrompt(input);
}

export type { H3PromptInput, H3PromptOutput };
export { buildH3Input } from "./build-input";
export type { BuildH3InputOptions } from "./build-input";
