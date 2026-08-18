// ═══════════════════════════════════════════════
// H3 R2V Prompt Template (v2) — full context injection
// Now includes: dialogues, time-seg, camera mapping, BGM, episode context.
// Outputs: <Picture N> / <Subject N> labeled 6-section H3 prompt.
// ═══════════════════════════════════════════════

import type { H3PromptInput, H3Language } from "../types";
import { resolveLanguage } from "../shared/base-builder";
import { getDefaultSlotContents } from "@/lib/ai/prompts/registry";

export async function buildR2VPromptTemplate(
  input: H3PromptInput,
  systemOverride?: string,
): Promise<{ system: string; user: string }> {
  const lang = resolveLanguage(input);
  
  // System prompt: from Registry slot or override
  let system = systemOverride || "";
  if (!system) {
    const slots = getDefaultSlotContents("ref_video_prompt_h3");
    system = slots?.role_definition || slots?.rules || "";
  }
  
  // User prompt: full context assembly
  const user = buildUserContext(input, lang);
  return { system, user };
}

function buildUserContext(input: H3PromptInput, lang: H3Language): string {
  const L = (zh: string, en: string) => lang === "zh" ? zh : en;
  const parts: string[] = [];

  // ── Section 0: Role & Task ──────────────────
  parts.push(L(
    "你是一位专业的 MiniMax H3 Ref2VA 视频提示词工程师。",
    "You are a professional MiniMax H3 Ref2VA video prompt engineer."
  ));
  parts.push(L(
    "给定场景帧（首帧/尾帧）和角色参考图，你的任务是为该镜头生成完整的 6-section H3 R2V 视频生成提示词。",
    "Given scene frames (first/last frame) and character reference images, generate a complete 6-section H3 R2V video prompt for this shot."
  ));
  parts.push("");

  // ── Section 1: Image Mapping ─────────────────
  parts.push(`=== ${L("参考图映射", "REFERENCE IMAGE MAPPING")} ===`);
  parts.push(L(
    "使用 <Picture N> 标签引用参考图。严格按以下顺序编号：",
    "Use <Picture N> tags to reference images. Numbering strictly follows this order:"
  ));
  parts.push("");
  
  if (input.firstFrame?.prompt) {
    parts.push(`<Picture 1> = ${L("首帧场景", "First frame scene")}: ${input.firstFrame.prompt}`);
  }
  if (input.lastFrame?.prompt) {
    const idx = input.firstFrame?.prompt ? 2 : 1;
    parts.push(`<Picture ${idx}> = ${L("尾帧场景", "Last frame scene")}: ${input.lastFrame.prompt}`);
  }
  
  let picIdx = (input.firstFrame?.prompt ? 1 : 0) + (input.lastFrame?.prompt ? 1 : 0) + 1;
  for (const char of input.characters) {
    if (char.referenceImage) {
      parts.push(L(
        `<Picture ${picIdx}> = 角色 ${char.name}${char.visualHint ? `（${char.visualHint}）` : ""}`,
        `<Picture ${picIdx}> = Character ${char.name}`
      ));
      picIdx++;
    }
  }
  parts.push("");

  // ── Section 2: Characters ────────────────────
  parts.push(`=== ${L("登场角色", "CHARACTERS")} ===`);
  for (let i = 0; i < input.characters.length; i++) {
    const c = input.characters[i];
    if (!c.referenceImage) continue;
    const attrs = [
      c.description, c.visualHint,
      c.heightCm && c.heightCm > 0 ? `${c.heightCm}cm/${c.bodyType || "average"}` : null,
      c.performanceStyle
    ].filter(Boolean).join(" — ");
    parts.push(L(
      `<Subject ${i + 1}> = ${c.name}: ${attrs}`,
      `<Subject ${i + 1}> = ${c.name}: ${attrs || "character"}`
    ));
  }
  if (input.sceneDescription) {
    const sceneIdx = input.characters.length + 1;
    parts.push(L(
      `<Subject ${sceneIdx}> = 场景环境: ${input.sceneDescription}${input.sceneLighting ? ` / 光照: ${input.sceneLighting}` : ""}`,
      `<Subject ${sceneIdx}> = Scene: ${input.sceneDescription}`
    ));
  }
  parts.push("");

  // ── Section 3: Scene & Shot Context ──────────
  parts.push(`=== ${L("场景与分镜", "SCENE & SHOT CONTEXT")} ===`);
  if (input.projectTitle) parts.push(L(`项目: ${input.projectTitle}`, `Project: ${input.projectTitle}`));
  if (input.projectOutline) parts.push(L(`大纲: ${input.projectOutline}`, `Outline: ${input.projectOutline}`));
  if (input.projectWorldSetting) parts.push(L(`世界观: ${input.projectWorldSetting}`, `World Setting: ${input.projectWorldSetting}`));
  parts.push("");

  // ── Section 4: Motion & Camera ──────────────
  parts.push(`=== ${L("动作脚本与运镜", "MOTION & CAMERA")} ===`);
  parts.push(L(
    "以下为镜头的完整动作脚本。你需要：\n1. 按照动作节拍自然切分为 2-3 秒的子段落\n2. 每个子段落标注精确的时间起点\n3. 每个子段落注入对应的运镜动作（幅度: 小/中/大/快速）\n4. 所有时间标注使用精确到小数点后一位的秒数",
    "Below is the shot's complete motion script. You must:\n1. Split into 2-3 second sub-beats naturally\n2. Label each with precise time start\n3. Inject corresponding camera movement (amplitude: small/medium/large/rapid)\n4. All timestamps use seconds with one decimal place"
  ));
  parts.push("");
  if (input.motionScript) parts.push(L(`动作脚本: ${input.motionScript}`, `Motion: ${input.motionScript}`));
  if (input.videoScript) parts.push(L(`视频脚本: ${input.videoScript}`, `Video Script: ${input.videoScript}`));
  if (input.cameraDirection) parts.push(L(`运镜指令: ${input.cameraDirection}`, `Camera: ${input.cameraDirection}`));
  parts.push(L(`时长: ${input.duration || 10}s`, `Duration: ${input.duration || 10}s`));
  parts.push("");

  // ── Section 5: Dialogue ──────────────────────
  if (input.dialogues?.length) {
    parts.push(`=== ${L("对白", "DIALOGUES")} ===`);
    parts.push(L(
      "对白使用 <d>[语言] 文本</d> 格式。脚本语言=中文时用 [中文]，英文时用 [English]。",
      "Dialogues use <d>[language] text</d> format."
    ));
    for (const d of input.dialogues) {
      const subjIdx = input.characters.findIndex(c => c.name === d.characterName);
      const subjLabel = subjIdx >= 0 ? ` (S${subjIdx + 1})` : "";
      parts.push(L(
        `${d.characterName}${subjLabel} 说：<d>[中文] ${d.text}</d>`,
        `${d.characterName}${subjLabel} says: <d>[English] ${d.text}</d>`
      ));
    }
    parts.push("");
  } else {
    parts.push(L(
      `=== ${L("对白", "DIALOGUES")} ===\n${L("本镜头无对白，通过动作和画面叙事。", "No dialogue in this shot. Tell the story through action and visuals.")}`,
      `=== DIALOGUES ===\nNo dialogue. Use motion and visuals only.`
    ));
    parts.push("");
  }

  // ── Section 6: Audio ────────────────────────
  parts.push(`=== ${L("音频参考", "AUDIO REFERENCES")} ===`);
  if (input.bgmUrl) {
    parts.push(L(`BGM 风格参考: ${input.bgmUrl}`, `BGM reference: ${input.bgmUrl}`));
  } else {
    parts.push(L("BGM: 基于项目氛围和剧情自行设计", "BGM: Design based on project atmosphere"));
  }
  if (input.soundDesign) {
    parts.push(L(`音效设计: ${input.soundDesign}`, `Sound Design: ${input.soundDesign}`));
  }
  if (input.musicCue) {
    parts.push(L(`音乐提示: ${input.musicCue}`, `Music cue: ${input.musicCue}`));
  }
  parts.push("");

  // ── Section 7: Output Format Requirements ────
  parts.push(`=== ${L("输出格式要求", "OUTPUT FORMAT REQUIREMENTS")} ===`);
  parts.push(L(
    "严格按系统提示词中的 6-section 格式输出。\n\n" +
    "特别注意：summary 必须用与脚本相同的语言书写（本条中文脚本 → summary 用中文），\n" +
    "首行保留 [reference_generation] 标记，正文紧跟其后。\n\n" +
    "禁止：重复输出任何 section、省略任何 section、输出 markdown 代码块、前言或总结。",
    "Output in the exact 6-section format specified in the system prompt.\n" +
    "CRITICAL: summary must be in the same language as the script. Do NOT force English.\n" +
    "FORBIDDEN: duplicate sections, omitted sections, markdown blocks, preambles."
  ));

  return parts.join("\n");
}