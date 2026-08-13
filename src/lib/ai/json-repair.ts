/**
 * JSON repair utilities for LLM output.
 *
 * LLMs frequently produce near-valid JSON with common issues:
 * - trailing commas in objects/arrays
 * - unescaped literal newlines inside string values
 * - truncated output (missing closing brackets/braces)
 *
 * This module provides a multi-pass repair pipeline.
 */

/** Extract JSON text (supports ```json``` wrapping and raw text) */
export function extractJSON(text: string): string {
  const match = text.match(/```(?:json)?\s*([\s\S]*?)```/);
  const raw = match ? match[1].trim() : text.trim();
  // Remove control characters that break JSON.parse (except \n \r \t)
  let result = raw.replace(/[\x00-\x08\x0b\x0c\x0e-\x1f]/g, "");
  // Sanitize invalid escape sequences (e.g. \x, \g) by removing the backslash
  result = result.replace(/\\([^"\\\/bfnrtu])/g, "$1");
  return result;
}

/**
 * Attempt to repair common LLM JSON output errors before JSON.parse.
 *
 * Handles:
 *  1. Trailing commas in objects and arrays
 *  2. Unescaped literal newlines inside JSON string values
 *  3. Truncated output (missing closing brackets/braces)
 */
export function repairJSON(raw: string): string {
  let result = raw;

  // ── Pass 1: Strip trailing commas ──────────────────────────
  result = result.replace(/,(\s*[}\]])/g, "$1");

  // ── Pass 2: Fix unescaped newlines inside string values ────
  // Walk character-by-character to track in-string state.
  // Inside a JSON string: literal \n → escaped \\n.
  const chars: string[] = [];
  let inString = false;
  let escape = false;
  for (let i = 0; i < result.length; i++) {
    const ch = result[i];
    if (escape) {
      chars.push(ch);
      escape = false;
      continue;
    }
    if (ch === "\\") {
      chars.push(ch);
      escape = true;
      continue;
    }
    if (ch === '"') {
      inString = !inString;
      chars.push(ch);
      continue;
    }
    if (inString && ch === "\n") {
      chars.push("\\n");
      continue;
    }
    chars.push(ch);
  }
  result = chars.join("");

  // ── Pass 3: Close truncated JSON ───────────────────────────
  // Count bracket depth and append missing closers.
  const openStack: string[] = [];
  let inStr = false;
  let esc = false;
  for (const ch of result) {
    if (esc) { esc = false; continue; }
    if (ch === "\\") { esc = true; continue; }
    if (ch === '"') { inStr = !inStr; continue; }
    if (inStr) continue;
    if (ch === "{" || ch === "[") openStack.push(ch);
    else if (ch === "}") {
      if (openStack[openStack.length - 1] === "{") openStack.pop();
    } else if (ch === "]") {
      if (openStack[openStack.length - 1] === "[") openStack.pop();
    }
  }
  while (openStack.length > 0) {
    result += openStack.pop()! === "{" ? "}" : "]";
  }

  return result;
}

/**
 * Extract + repair + parse JSON from LLM output.
 * Returns parsed result or throws with the original error.
 */
export function parseLLMJSON(text: string): any {
  const cleaned = extractJSON(text);
  const repaired = repairJSON(cleaned);
  return JSON.parse(repaired);
}

/**
 * Try extract + repair + parse, returning the error message on failure.
 */
export function tryParseLLMJSON(
  text: string
): { ok: true; data: unknown } | { ok: false; error: string } {
  try {
    const data = parseLLMJSON(text);
    return { ok: true, data };
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : String(err) };
  }
}