// ═══════════════════════════════════════════════
// H3 Prompt Builder — Main Export (v0.2.0)
// ═══════════════════════════════════════════════

import type { H3PromptInput, H3PromptOutput } from "./types";
import { buildH3BasePrompt } from "./base-mode";
import { buildH3Ref2VAPrompt } from "./ref-mode";

/**
 * Main entry: build H3 video prompt.
 *
 * Auto-selects Base mode (3 sections, T2VA/I2VA/FL2VA) or
 * Ref2VA mode (6 sections) based on input.generationMode.
 *
 * When H3_PROMPT_MODE=enabled, the handler calls this instead of buildVideoPrompt().
 */
export function buildVideoPrompt(input: H3PromptInput): H3PromptOutput {
  if (input.generationMode === "reference") {
    return buildH3Ref2VAPrompt(input);
  }
  return buildH3BasePrompt(input);
}

// Re-export types for external use
export type { H3PromptInput, H3PromptOutput };