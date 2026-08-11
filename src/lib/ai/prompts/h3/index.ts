// ═══════════════════════════════════════════════
// H3 Prompt Builder — Main Export (v0.2.0)
// ═══════════════════════════════════════════════

import type { H3PromptInput, H3PromptOutput } from "./types";
import { buildH3BasePrompt } from "./base-mode";

/**
 * Main entry: build H3 video prompt.
 * Auto-selects Base mode (3 sections) or Ref2VA (6 sections) from generationMode.
 *
 * When H3_PROMPT_MODE=enabled, the handler calls this instead of buildVideoPrompt().
 */
export function buildVideoPrompt(input: H3PromptInput): H3PromptOutput {
  if (input.generationMode === "reference") {
    // Placeholder: P3 will add buildH3Ref2VAPrompt
    // For now, falls through to base mode with a note
    const base = buildH3BasePrompt(input);
    return { ...base, mode: "ref2va" };
  }
  return buildH3BasePrompt(input);
}

// Re-export types for external use
export type { H3PromptInput, H3PromptOutput };