// ═══════════════════════════════════════════════
// H3 Language Router (v0.2.0)
// Rule: prompt body MUST be English (official guide §1).
//       Only dialogue inside <d> keeps original language.
// ═══════════════════════════════════════════════

/** Detect if text is primarily Chinese (threshold: 10% CJK chars) */
export function detectLanguage(text: string): "zh" | "en" {
  const chineseChars = text.match(/[\u4e00-\u9fff]/g);
  return chineseChars && chineseChars.length > text.length * 0.1 ? "zh" : "en";
}