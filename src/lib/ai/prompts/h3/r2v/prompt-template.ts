// ═══════════════════════════════════════════════
// H3 R2V Prompt Template (v4) — Registry-backed
// ═══════════════════════════════════════════════

import type { H3PromptInput, H3Language } from "../types";
import { mapCameraDirection } from "../camera-map";
import { resolveLanguage } from "../shared/base-builder";
import { getDefaultSlotContents } from "@/lib/ai/prompts/registry";

export async function buildR2VPromptTemplate(
  input: H3PromptInput,
  systemOverride?: string,
): Promise<{ system: string; user: string }> {
  const lang = resolveLanguage(input);
  let system = systemOverride || "";
  if (!system) {
    const slots = getDefaultSlotContents("ref_video_prompt_h3");
    system = slots?.role_definition || slots?.rules || "";
  }
  const user = [
    buildContentLayer(input, lang),
    buildRefConstraintLayer(input, lang),
    buildOutputFormat(input, lang),
  ].join("\n\n");
  return { system, user };
}

// ═══ Layer 1: Content (Registry-backed) ═══════════════════

function buildContentLayer(input: H3PromptInput, lang: H3Language): string {
  const L = (zh: string, en: string) => lang === "zh" ? zh : en;
  const slots = getDefaultSlotContents("ref_video_h3_content") ?? {};
  const r = (key: string, fallback: string) => slots[key] || fallback;
  const out: string[] = [];

  out.push(r("role_task", L("你是R2V工程师", "You are an R2V engineer")));

  out.push("");
  out.push(r("image_mapping", L("=== 参考图映射 ===", "=== IMAGE MAPPING ===")));

  // Dynamic: iterate ALL scene reference images (R2V — not keyframes)
  let picIdx = 1;
  for (const sf of input.sceneFrames ?? []) {
    const label = sf.prompt || L("场景参考", "Scene reference");
    out.push(L(`<Picture ${picIdx}> = ${L("场景参考图", "Scene ref")}: ${label.slice(0, 80)}`,
      `<Picture ${picIdx}> = Scene ref: ${label.slice(0, 80)}`));
    picIdx++;
  }
  // Dynamic: iterate character reference images
  for (const ch of input.characters) {
    if (ch.referenceImage) {
      out.push(L(`<Picture ${picIdx}> = 角色 ${ch.name}`, `<Picture ${picIdx}> = ${ch.name}`));
      picIdx++;
    }
  }

  out.push("");
  out.push(r("characters", L("=== 登场角色 ===", "=== CHARACTERS ===")));
  for (let i = 0; i < input.characters.length; i++) {
    const ch = input.characters[i];
    if (!ch.referenceImage) continue;
    const desc = (ch.description || "").length > 80
      ? (ch.description || "").slice(0, 80) + "..." : (ch.description || "");
    const attrs = [desc, ch.visualHint,
      ch.heightCm && ch.heightCm > 0 ? `${ch.heightCm}cm/${ch.bodyType || "average"}` : null,
      ch.performanceStyle].filter(Boolean).join(" — ");
    out.push(L(`<Subject ${i+1}> = ${ch.name}: ${attrs}`, `<Subject ${i+1}> = ${ch.name}: ${attrs || "character"}`));
  }
  if (input.sceneDescription) {
    const si = input.characters.length + 1;
    out.push(L(`<Subject ${si}> = 场景: ${input.sceneDescription}`, `<Subject ${si}> = Scene: ${input.sceneDescription}`));
  }

  out.push("");
  out.push(r("scene_shot", L("=== 场景与分镜 ===", "=== SCENE & SHOT ===")));
  if (input.projectTitle) out.push(L(`项目: ${input.projectTitle}`, `Project: ${input.projectTitle}`));
  if (input.projectOutline) out.push(L(`大纲: ${input.projectOutline}`, `Outline: ${input.projectOutline}`));
  if (input.projectWorldSetting) out.push(L(`世界观: ${input.projectWorldSetting}`, `World: ${input.projectWorldSetting}`));

  out.push("");
  out.push(r("motion_camera", L("=== 动作脚本与运镜 ===", "=== MOTION & CAMERA ===")));
  if (input.motionScript) out.push(L(`动作: ${input.motionScript}`, `Motion: ${input.motionScript}`));
  if (input.videoScript) out.push(L(`视频: ${input.videoScript}`, `Video: ${input.videoScript}`));
  if (input.cameraDirection) out.push(L(`运镜: ${input.cameraDirection}`, `Camera: ${input.cameraDirection}`));
  out.push(L(`时长: ${input.duration || 10}s`, `Duration: ${input.duration || 10}s`));

  out.push("");
  if (input.dialogues?.length) {
    out.push(r("dialogue_header", L(`=== 对白 ===`, `=== DIALOGUES ===`)));
    for (const d of input.dialogues) {
      const si = input.characters.findIndex(c => c.name === d.characterName);
      const sl = si >= 0 ? ` (S${si+1})` : "";
      out.push(L(`${d.characterName}${sl} 说：<d>[中文] ${d.text}</d>`,
        `${d.characterName}${sl} says: <d>[English] ${d.text}</d>`));
    }
  } else {
    out.push(L("=== 对白 ===\n无对话", "=== DIALOGUES ===\nNo dialogue"));
  }

  if (input.narrations?.length) {
    out.push("");
    out.push(r("narration_header", L("=== 旁白（已预生成）===", "=== Narration ===")));
    out.push(input.narrations.join("\n"));
  }
  if (input.innerMonologues?.length) {
    out.push("");
    out.push(r("inner_monologue_header", L("=== 内心独白（已预生成）===", "=== Inner Monologue ===")));
    out.push(input.innerMonologues.join("\n"));
  }

  out.push("");
  out.push(r("audio_header", L("=== 音频参考 ===", "=== AUDIO ===")));
  if (input.bgmUrl) out.push(L(`BGM: ${input.bgmUrl}`, `BGM: ${input.bgmUrl}`));
  if (input.soundDesign) out.push(L(`音效: ${input.soundDesign}`, `Sound: ${input.soundDesign}`));

  return out.join("\n");
}

// ═══ Layer 2: Constraints (Registry-backed) ═══════════════

function buildRefConstraintLayer(input: H3PromptInput, lang: H3Language): string {
  const L = (zh: string, en: string) => lang === "zh" ? zh : en;
  const camera = mapCameraDirection(input.cameraDirection);
  const duration = input.duration || 10;
  const segments = computeSegments(duration);
  const segLabels = segments.map(s => s.label);
  const hasDialogues = !!input.dialogues?.length;
  const hasNarrations = !!input.narrations?.length;
  const hasInnerMonologues = !!input.innerMonologues?.length;

  const slots = getDefaultSlotContents("ref_video_h3_constraints") ?? {};
  function r(key: string, fallback: string): string {
    return (slots[key] || fallback)
      .replaceAll("{{CAMERA_DIRECTION}}", camera)
      .replaceAll("{{SEGMENT_COUNT}}", String(segments.length))
      .replaceAll("{{SEGMENT_LABELS}}", segLabels.join(" / "));
  }

  const core: string[] = [];
  core.push(r("core_format", L("【6-Section 格式】", "【6-Section Format】")));
  core.push(r("core_subject", L("【Subject/Picture 闭环】", "【Subject/Picture Closure】")));
  core.push(r("core_env", L("【环境-标签引用】", "【Environment-Reference】")));

  const detail: string[] = [];
  detail.push(r("time_structure", L("【时间结构】", "【Time Structure】")));
  detail.push(r("camera", L("【运镜优先】", "【Camera Priority】")));
  detail.push(r("action_detail", L("【动作颗粒度】", "【Action Detail】")));
  detail.push(r("body_vocab", L("【身体动词】", "【Body Vocab】")));
  detail.push(r("voice", L("【声音】", "【Voice】")));
  detail.push(r("format", L("【格式】", "【Format】")));

  return L("=== 核心约束 — 必须严格遵守 ===", "=== CORE CONSTRAINTS ===") + "\n\n"
    + core.join("\n\n")
    + "\n\n" + L("=== 详细约束", "=== DETAILED CONSTRAINTS") + "\n\n"
    + detail.join("\n\n");
}

// ═══ Layer 3: Output Format ═══════════════════════════════

function buildOutputFormat(input: H3PromptInput, lang: H3Language): string {
  const L = (zh: string, en: string) => lang === "zh" ? zh : en;
  return L(
    `=== 输出格式要求 ===
严格按上方的 6-section 格式输出。
• summary 首行 [reference_generation]，正文用脚本语言
• detailed_description 用 "0.0s-3.0s:" 时间戳格式
• 对白嵌入: <Subject N> (S1) says: <d>[中文] text</d>
• 旁白/独白（如有）嵌入对应时间段
禁止：重复/省略 section、markdown、前言总结`,
    `=== OUTPUT FORMAT ===
Follow the 6-section format from CONSTRAINTS above.
• summary starts with [reference_generation] tag
• detailed_description uses "0.0s-3.0s:" timestamps
• Dialogue: <Subject N> (S1) says: <d>[Chinese] text</d>
• Narration/monologue embedded in time segments
FORBIDDEN: duplicate/omit sections, markdown, preambles`
  );
}

// ═══ Helpers ═════════════════════════════════════════════

function computeSegments(duration: number): Array<{ label: string }> {
  if (duration <= 5) return [{ label: "0-5s" }];
  if (duration <= 8) { const m = Math.floor(duration / 2); return [{ label: `0-${m}s` }, { label: `${m}-${duration}s` }]; }
  if (duration <= 14) { const s = Math.floor(duration / 3); return [{ label: `0-${s}s` }, { label: `${s}-${s*2}s` }, { label: `${s*2}-${duration}s` }]; }
  const s = Math.floor(duration / 4);
  return [{ label: `0-${s}s` }, { label: `${s}-${s*2}s` }, { label: `${s*2}-${s*3}s` }, { label: `${s*3}-${duration}s` }];
}