// ═══════════════════════════════════════════════
// H3 R2V Prompt Template — Vision LLM context assembly (v0.3.9)
// Parallel to fl2v/prompt-template.ts.
// Image-aware: maps scene frames + character refs to <Picture N> labels.
// ═══════════════════════════════════════════════

import type { H3PromptInput, H3Language } from "../types";
import { resolveLanguage } from "../shared/base-builder";
import { getDefaultSlotContents } from "@/lib/ai/prompts/registry";

/**
 * Build the user + system prompt for R2V Vision LLM call.
 * Returns { system, user } — images are passed separately by the caller.
 */
export async function buildR2VPromptTemplate(
  input: H3PromptInput,
  systemOverride?: string,
): Promise<{ system: string; user: string }> {
  const lang = resolveLanguage(input);
  
  // System prompt: from Registry slot or override
  let system = "";
  if (systemOverride) {
    system = systemOverride;
  } else {
    const slots = getDefaultSlotContents("ref_video_prompt_h3");
    system = slots?.role_definition || slots?.rules || "";
  }
  
  // User prompt: context assembly
  const user = buildUserContext(input, lang);

  return { system, user };
}

function buildUserContext(input: H3PromptInput, lang: H3Language): string {
  const L = (zh: string, en: string) => lang === "zh" ? zh : en;
  const parts: string[] = [];

  // ── Image Mapping ───────────────────────────
  parts.push(L("## 参考图映射", "## REFERENCE IMAGE MAPPING"));
  parts.push("");
  
  // Scene frames
  if (input.firstFrame?.prompt || input.lastFrame?.prompt) {
    if (input.firstFrame?.prompt) {
      parts.push(L(`<Picture 1> = 首帧场景: ${input.firstFrame.prompt}`, `<Picture 1> = First frame scene`));
    }
    if (input.lastFrame?.prompt) {
      const nextIdx = input.firstFrame?.prompt ? 2 : 1;
      parts.push(L(`<Picture ${nextIdx}> = 尾帧场景: ${input.lastFrame.prompt}`, `<Picture ${nextIdx}> = Last frame scene`));
    }
  }

  // Character references
  let picIdx = (input.firstFrame?.prompt ? 1 : 0) + (input.lastFrame?.prompt ? 1 : 0) + 1;
  for (const char of input.characters) {
    if (char.referenceImage) {
      const desc = [char.description, char.visualHint].filter(Boolean).join("; ");
      parts.push(L(`<Picture ${picIdx}> = 角色 ${char.name}${desc ? `: ${desc}` : ""}`, `<Picture ${picIdx}> = Character ${char.name}`));
      picIdx++;
    }
  }
  parts.push("");

  // ── Project Context ─────────────────────────
  parts.push(L("## 项目背景", "## PROJECT CONTEXT"));
  if (input.projectTitle) parts.push(input.projectTitle);
  if (input.projectOutline) parts.push(input.projectOutline);
  if (input.sceneDescription) parts.push(L(`场景: ${input.sceneDescription}`, `Scene: ${input.sceneDescription}`));
  parts.push("");

  // ── Characters ──────────────────────────────
  parts.push(L("## 登场角色", "## CHARACTERS"));
  for (const char of input.characters) {
    if (!char.referenceImage) continue;
    const desc = [char.description, char.visualHint, char.performanceStyle].filter(Boolean).join("; ");
    parts.push(`- ${char.name}: ${desc}`);
    if (char.heightCm) parts.push(L(`  身高: ${char.heightCm}cm, 体型: ${char.bodyType || "average"}`, `  Height: ${char.heightCm}cm, Build: ${char.bodyType || "average"}`));
  }
  parts.push("");

  // ── Motion & Camera ────────────────────────
  parts.push(L("## 动作与运镜", "## MOTION & CAMERA"));
  if (input.motionScript) parts.push(L(`动作: ${input.motionScript}`, `Motion: ${input.motionScript}`));
  if (input.cameraDirection) parts.push(L(`运镜: ${input.cameraDirection}`, `Camera: ${input.cameraDirection}`));
  parts.push(L(`时长: ${input.duration || 10}s`, `Duration: ${input.duration || 10}s`));
  parts.push("");

  // ── Output Requirements ────────────────────
  parts.push(L("## 输出要求", "## OUTPUT REQUIREMENTS"));
  parts.push(L(
    "1. 按 MiniMax H3 Ref2VA 6-section 格式输出\n2. 用 <Subject N> 引用角色, <Picture N> 引用图片\n3. subject_definitions 基于参考图描述每个角色的实际外观\n4. retention_analysis: fully_preserved/partially_preserved/attribute_transfer/weak_reference\n5. detailed_description: 用 <Subject N> 和 <Picture N> 标签写视频散文\n6. overall_soundscape + non_diegetic_music 基于氛围和 BGM 参考\n7. 禁止真实人名/品牌/IP/艺术家",
    "1. Output in MiniMax H3 Ref2VA 6-section format\n2. Use <Subject N> for characters, <Picture N> for images\n3. subject_definitions describe each character's appearance based on reference images\n4. retention_analysis with proper visual retention levels\n5. detailed_description with <Subject N> and <Picture N> labels\n6. overall_soundscape + non_diegetic_music based on atmosphere and BGM\n7. No real person names/brands/IPs/artists"
  ));

  return parts.join("\n");
}