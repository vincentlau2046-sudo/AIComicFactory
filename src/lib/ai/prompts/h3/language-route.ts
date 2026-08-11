// ═══════════════════════════════════════════════
// H3 Language Router (v0.2.0)
//
// Reference: MiniMax H3 official guide §1:
//   "Write all rewrite sections in English. Preserve the original
//    language only for dialogue and lyrics inside <d> and for text
//    visibly present in the scene."
//
// Strategy:
//   1. Detect script language (zh/en)
//   2. If zh: extract dialogue segments, translate body to EN
//   3. Restore dialogue as <d>[Language] text</d>
// ═══════════════════════════════════════════════

/** Detect if text is primarily Chinese (threshold: 10% CJK chars) */
export function detectLanguage(text: string): "zh" | "en" {
  const chineseChars = text.match(/[\u4e00-\u9fff]/g);
  return chineseChars && chineseChars.length > text.length * 0.1 ? "zh" : "en";
}

/**
 * Segment text into dialogue vs non-dialogue parts.
 *
 * Recognized dialogue patterns (Chinese + English):
 *   - {name}说：\"{text}\"
 *   - {name} says: \"{text}\"
 *   - {name}喊道：\"{text}\"
 *   - \"{text}\" {name}说
 *   - —{text}  (em-dash dialogue)
 */
export function extractDialogueSegments(
  text: string
): { text: string; isDialogue: boolean; speaker?: string }[] {
  if (!text?.trim()) return [];

  // Match dialogue patterns
  const pat = /(?:([\u4e00-\u9fff\w]+)(?:说|says|喊道|问道|回答|said|shouts|asks|replies)[:：]\s*)?[""]([^""]+)[""]|(?:(?:——|—)\s*)([^\n]+)/g;

  const segments: { text: string; isDialogue: boolean; speaker?: string }[] = [];
  let lastIdx = 0;
  let m: RegExpExecArray | null;

  while ((m = pat.exec(text)) !== null) {
    // Non-dialogue before this match
    if (m.index > lastIdx) {
      const nonDialogue = text.slice(lastIdx, m.index).trim();
      if (nonDialogue) segments.push({ text: nonDialogue, isDialogue: false });
    }

    // Dialogue match
    const speaker = m[1] || undefined;
    const dialogueText = m[2] || m[3];
    segments.push({ text: dialogueText?.trim() || m[0], isDialogue: true, speaker });

    lastIdx = m.index + m[0].length;
  }

  // Remaining text
  if (lastIdx < text.length) {
    const remaining = text.slice(lastIdx).trim();
    if (remaining) segments.push({ text: remaining, isDialogue: false });
  }

  return segments.length > 0
    ? segments
    : [{ text, isDialogue: false }];
}

/**
 * Process a full video script: translate non-dialogue body to English,
 * preserve dialogue in original language with <d> tags.
 *
 * Returns { body, needsTranslation } where body is ready for H3 prompt.
 */
export function routeLanguage(
  script: string,
  mode: "auto" | "en" | "zh"
): { body: string; hasDialogue: boolean; needsTranslation: boolean } {
  const lang = mode === "auto" ? detectLanguage(script) : mode;

  // Already English: pass through
  if (lang === "en") {
    return { body: script, hasDialogue: false, needsTranslation: false };
  }

  // Chinese: extract dialogue, translate body
  const segments = extractDialogueSegments(script);
  const hasDialogue = segments.some(s => s.isDialogue);

  if (!hasDialogue) {
    return {
      body: `[ZH: ${script}]`,  // P4+: replace with IFF translation
      hasDialogue: false,
      needsTranslation: true,
    };
  }

  const parts: string[] = [];
  let needsTranslation = false;

  for (const seg of segments) {
    if (seg.isDialogue) {
      const langTag = detectLanguage(seg.text) === "zh" ? "Chinese" : "English";
      parts.push(`<d>[${langTag}] ${seg.text}</d>`);
    } else if (seg.text.trim()) {
      parts.push(`[ZH: ${seg.text.trim()}]`);  // fallback if translation unavailable
      needsTranslation = true;
    }
  }

  return {
    body: parts.join(" "),
    hasDialogue: true,
    needsTranslation,
  };
}

/**
 * Translate Chinese narrative text to English via IFF Proxy.
 * Uses deepseek-v4-flash (fast, free) for translation.
 *
 * Call this in the handler BEFORE building the H3 prompt when
 * detectLanguage(videoScript) === "zh" and H3_PROMPT_MODE=enabled.
 */
export async function translateNarrative(
  chineseText: string,
  apiBase: string = "http://localhost:8999/v1"
): Promise<string> {
  const response = await fetch(`${apiBase}/chat/completions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      model: "deepseek-v4-flash",
      messages: [
        {
          role: "system",
          content: [
            "You are a video script translator. Translate Chinese to natural English.",
            "Rules:",
            "- Preserve character names, place names, and camera directions unchanged",
            "- Convert Chinese action descriptions to natural English prose",
            "- Output ONLY the translation, no commentary, no markdown",
          ].join(" "),
        },
        { role: "user", content: chineseText },
      ],
      temperature: 0.3,
      max_tokens: Math.max(chineseText.length, 500),
    }),
  });

  if (!response.ok) {
    throw new Error(`IFF translation failed: ${response.status}`);
  }

  const data = await response.json();
  return data.choices?.[0]?.message?.content?.trim() ?? `[ZH: ${chineseText}]`;
}