// ═══════════════════════════════════════════════
// H3 FL2V Prompt Template — Registry-sourced (v0.3.0)
// 3-layer context engineering: Content → Constraints → Guide
// All static text read from prompt registry slots, not hardcoded.
// ═══════════════════════════════════════════════

import type { H3PromptInput, H3Language } from "../types";
import { mapCameraDirection } from "../camera-map";
import { resolveLanguage } from "../shared/base-builder";
import { getPromptDefinition, getDefaultSlotContents } from "@/lib/ai/prompts/registry";

// ── Layer 1: Content Assembly ───────────────────────────

function buildContentLayer(
  input: H3PromptInput,
  contentSlots: Record<string, string>,
  lang: H3Language
): string {
  const L = (zh: string, en: string) => lang === "zh" ? zh : en;
  const r = (key: string, fallback: string) => contentSlots[key] || fallback;
  const parts: string[] = [];

  // Video Script
  const scriptLabel = r("script_label", `## ${L("视频剧本", "VIDEO SCRIPT")}`);
  parts.push(scriptLabel.replace("{{VIDEO_SCRIPT}}", input.videoScript || "(no script)"));
  parts.push("");

  // Characters
  if (input.characters?.length) {
    const charLabel = r("character_label", `## ${L("角色", "CHARACTERS")}`);
    const charPrompt = charLabel.replace("{{CHARACTER_LIST}}", input.characters.map(c => {
      const role = c.scope === "guest" ? L("[客串]", "[guest]") : "";
      const style = c.performanceStyle ? `— ${c.performanceStyle}` : "";
      return `- ${c.name} ${role}${style}`;
    }).join("\n"));
    parts.push(charPrompt);
    parts.push("");
  }

  // Dialogues
  if (input.dialogues?.length) {
    const dialLabel = r("dialogue_label", `## ${L("对话台本（必须在视频中呈现！）", "DIALOGUE SCRIPT (MUST be included in the video!)")}`);
    const usedNames: string[] = [];
    for (const d of input.dialogues) {
      if (!usedNames.includes(d.characterName)) usedNames.push(d.characterName);
    }
    const dialLines = input.dialogues.map(d => {
      const sid = usedNames.indexOf(d.characterName) + 1;
      return d.offscreen
        ? L(`(S${sid})画外音`, `(S${sid}) off-screen`)
        : `(S${sid})`;
    }).join("\n");
    parts.push(dialLabel.replace("{{DIALOGUE_LIST}}", dialLines));
    parts.push("");
  }

  // Phase 2: Pre-generated narration lines (injected by builder)
  // Only rendered when narration module is active
  if (input.activeModules?.includes("narration") && input.narrations?.length) {
    const narrSlots = getDefaultSlotContents("video_h3_fl2v_narration");
    const injectTemplate = narrSlots?.content_inject ||
      "## 旁白/画外音（已预生成）\n以下旁白/画外音已根据剧本和剧集背景自动生成，必须嵌入对应时间段中：\n{{NARRATION_LINES}}";
    parts.push(injectTemplate.replace("{{NARRATION_LINES}}", input.narrations.join("\n")));
    parts.push("");
  }

  // Frame Anchors — FL2V mode: only pass composition, not environment
  const hasFrames = input.firstFrame?.prompt || input.lastFrame?.prompt;
  if (hasFrames) {
    const frameLabel = r("frame_label", `## ${L("帧锚点（关键帧图片）", "FRAME ANCHORS (keyframe images)")}`);
    const frameLines: string[] = [frameLabel];
    if (input.firstFrame?.prompt) {
      // Extract only [shot] + [subject] from the structured tag prompt
      const trimmedFF = extractShotSubject(input.firstFrame.prompt);
      frameLines.push(L(
        `<Picture 1>（首帧）：${trimmedFF}`,
        `<Picture 1> (FIRST FRAME): ${trimmedFF}`
      ));
    }
    if (input.lastFrame?.prompt) {
      const trimmedLF = extractShotSubject(input.lastFrame.prompt);
      frameLines.push(L(
        `<Picture 2>（末帧）：${trimmedLF}`,
        `<Picture 2> (LAST FRAME): ${trimmedLF}`
      ));
    }
    parts.push(frameLines.join("\n"));
    parts.push("");
  }

  // Episode context (keep — LLM needs narrative context)
  if (input.episodeDescription) {
    const epLabel = r("episode_label", `## ${L("剧集背景", "EPISODE CONTEXT")}`);
    parts.push(epLabel.replace("{{EPISODE_CONTEXT}}", input.episodeDescription));
    if (input.episodeKeywords) parts.push(`${L("关键词", "Keywords")}: ${input.episodeKeywords}`);
    parts.push("");
  }

  // Audio
  if (input.soundDesign || input.musicCue || input.bgmUrl) {
    const audioLabel = r("audio_label", `## ${L("音频", "AUDIO")}`);
    const audioParts: string[] = [];
    if (input.soundDesign) audioParts.push(`${L("环境音", "Diegetic sound")}: ${input.soundDesign}`);
    if (input.musicCue) audioParts.push(`${L("音乐提示", "Music cue")}: ${input.musicCue}`);
    if (input.bgmUrl) audioParts.push(`${L("BGM参考", "BGM reference")}: <Audio 1>`);
    parts.push(audioLabel.replace("{{AUDIO_CONTEXT}}", audioParts.join("\n")));
    parts.push("");
  }

  // P2 prep: narration hint for dialogue-free shots (opt-in)
  if (input.activeModules?.includes("narration") && !input.dialogues?.length && !input.narrations?.length) {
    const narrHint = r("narration_hint", "");
    if (narrHint) {
      parts.push(narrHint);
      parts.push("");
    }
  }

  return parts.join("\n").trim();
}

/**
 * Extract only [shot] and [subject] tags from a structured tag prompt.
 * Strips [environment], [lighting], [color] — those are provided by reference images.
 */
function extractShotSubject(prompt: string): string {
  // Match [shot] ... and [subject] ... or [scene] ... blocks
  const shotMatch = prompt.match(/\[shot\][^\[]*/);
  const subjectMatch = prompt.match(/\[subject\][^\[]*/);
  const sceneMatch = prompt.match(/\[scene\][^\[]*/);
  const parts: string[] = [];
  if (shotMatch) parts.push(shotMatch[0].trim());
  if (subjectMatch) parts.push(subjectMatch[0].trim());
  else if (sceneMatch) parts.push(sceneMatch[0].trim());
  return parts.join(" | ") || prompt.slice(0, 100);
}

// ── Layer 2: Constraints ────────────────────────────────

function buildConstraintLayer(
  input: H3PromptInput,
  constraintSlots: Record<string, string>,
  lang: H3Language
): string {
  const L = (zh: string, en: string) => lang === "zh" ? zh : en;
  const r = (key: string, fallback: string) => constraintSlots[key] || fallback;
  const camera = mapCameraDirection(input.cameraDirection);
  const duration = input.duration || 10;
  const hasFirst = !!input.firstFrame?.fileUrl;
  const hasLast = !!input.lastFrame?.fileUrl;
  const segments = computeSegments(duration);

  // Build from registry slots with dynamic param injection
  let text = [
    L("## 约束规则", "## CONSTRAINTS"),
    "",
  ].join("\n");

  // Frame alignment header
  if (hasFirst && hasLast) {
    text += [
      L(
        `首行必须严格按照以下原文输出：\n参考图与目标视频的对齐方式——<Picture 1>（来自 [Shot 1]）对齐目标视频的第0.00秒；<Picture 2>（来自 [Shot 1]）对齐目标视频的第${duration.toFixed(2)}秒。`,
        `First line MUST be exactly:\nHow the reference pictures align with the target video — <Picture 1> (from [Shot 1]) aligns with the 0.00-second mark of the target video; <Picture 2> (from [Shot 1]) aligns with the ${duration.toFixed(2)}-second mark of the target video.`
      ),
      "",
    ].join("\n");
  }

  // Output format with segments
  text += L("### 输出格式", "### Output Format") + "\n\n";
  text += L(
    "集成多模态描述 (integrated_multimodal_description):\n  在单个 [Shot 1] 内按时间段拆分，每段独占一行：",
    "integrated_multimodal_description:\n  Break into time segments within a single [Shot 1], each on its own line:"
  ) + "\n";
  for (const seg of segments) {
    text += `  ${seg.label}: {运镜+角色动作}${L("。{对白}", ". {dialogue}")}\n`;
  }
  text += "\n";
  text += L(
    "整体环境音 (overall_soundscape):\n  1-3 句描述环境音和物理音效。禁止填 N/A 除非剧本明确要求完全静音。",
    "overall_soundscape:\n  1-3 sentences describing ambient/physical sounds. Never use N/A unless the script explicitly demands silence."
  ) + "\n\n";
  text += L(
    "非叙事音乐 (non_diegetic_music):\n  1-2 句描述背景配乐。无BGM时填 N/A。",
    "non_diegetic_music:\n  1-2 sentences describing background score. Use N/A if no BGM."
  ) + "\n\n";

  // Registry-sourced hard rules (P0: new FL2V constraints included)
  text += L("### 硬性规则", "### Hard Rules") + "\n\n";

  // Time structure
  text += r("time_structure", L(
    `【时间结构 — 强制执行】\n1. 必须按 ${segments.length} 个时间段拆分（不要创建 [Shot 2]），共 ${segments.map(s => s.label).join(" / ")}。每段独占一行\n2. 每个时间段必须有独立的视觉变化和运镜动作`,
    `【Time Structure — MANDATORY】\n1. Split into exactly ${segments.length} time segments (do NOT create [Shot 2]): ${segments.map(s => s.label).join(" / ")}. Each on its own line\n2. Each segment must have distinct visual change and camera action`
  ))
    .replace("{{SEGMENT_COUNT}}", String(segments.length))
    .replace("{{CAMERA_DIRECTION}}", camera)
    + "\n\n";

  // Action beats
  text += r("action_beats", L(
    "【动作节拍 — 强制执行】\n3. 每 2-3 秒安排一个微动作节点——即使静态镜头也要加入：呼吸节奏、衣物飘动、光线变化、水面波动、镜头微调\n4. 用「先...随即...然后...最终...」串联微动作，禁止把全部动作写成同时发生",
    "【Action Beats — MANDATORY】\n3. Every 2-3s include a micro-action beat\n4. Chain beats with temporal connectors: first... then... subsequently... finally..."
  )) + "\n\n";

  // Dialogue
  const hasDialogues = !!input.dialogues?.length;
  text += r("dialogue", hasDialogues
    ? L(
      "【对白 — 强制执行】\n5. 【⚠️ 此镜头有对话台本！按出场顺序分配 (S1)、(S2)... ID，格式：(S1)说：<d>[中文] 原文台词</d>\n6. 对白必须嵌入对应时间段——先描述角色动作（抬眼、手势、身体语言），再写对白行",
      "【Dialogue — MANDATORY】\n5. This shot HAS dialogue! Assign (S1), (S2)... IDs. Format: (S1) says: <d>[Chinese] text</d>\n6. Embed dialogue in its time segment"
    )
    : L(
      "【对白 — 强制执行】\n5. 对白格式：(S1)说：<d>[中文] 原文台词</d>\n   画外音格式（H3 官方标准）：角色名 (S1) says in an off-screen voiceover: <d>[Chinese] text</d> while his lips remain completely closed.\n6. 对白必须嵌入对应时间段——先描述角色动作，再写对白行",
      "【Dialogue — MANDATORY】\n5. Format: (S1) says: <d>[Chinese] text</d>. Off-screen: Character (S1) says in an off-screen voiceover: <d>[Chinese] text</d> while lips remain completely closed.\n6. Embed dialogue in its time segment"
    )
  ) + "\n\n";

  // Camera
  text += r("camera", L(
    `【运镜 — 第一优先级】\n7. 每个时间段首句必须是运镜动作：\n   格式："镜头 [运动类型] [幅度] [速度]"\n   例："镜头极缓慢推近，小幅度。"\n   运镜写完后，才写角色动作。\n8. 运镜必须含幅度+速度修饰\n9. 主运镜方向：${camera}`,
    `【Camera — MANDATORY】\n7. Each time segment must start with camera action.\n8. Include amplitude + speed modifiers.\n9. Primary motion: ${camera}`
  )) + "\n\n";

  // Format
  text += r("format", L(
    "【格式】\n10. 角色已在帧中——仅描述动作和移动，禁止描述外貌\n11. 禁止 markdown、代码块、注释——纯 H3 格式输出\n12. 禁止逐字复制剧本——转换为丰富的影视级散文",
    "【Format】\n10. Characters already in frames — describe ACTIONS only\n11. NO markdown, NO code blocks, NO commentary\n12. DO NOT copy script verbatim"
  )) + "\n\n";

  // ── P0: New FL2V-specific rules from registry ──

  // Rule 13-14: No environment description
  text += r("no_env", L(
    "【环境 — FL2V 专属规则】\n13. 首尾帧图片已提供全部环境/光线/物件。禁止在 prompt 中描述：静态场景元素、静态光线条件、静态物件细节\n14. 只描述环境变化：火焰忽明忽暗 ✅ / 云遮月 ✅ / 破庙篝火映土墙 ❌",
    "【Environment — FL2V Rule】\n13. First/last frames already provide all environment info. Do NOT describe static elements."
  )) + "\n\n";

  // Rule 15-16: Body vocabulary
  text += r("body_vocab", L(
    "【身体动作 — 白名单】\n15. 使用具体物理动词：转头、抬眼、垂眼、握紧、松开、抬手、放手、迈步、后退、前倾、后仰、起身、坐下、跪地、站起、转体、眯眼、眨眼\n16. 禁止抽象词",
    "【Body Action Vocabulary】\n15. Use concrete physical verbs: turn head, raise eyes, clench, release, step forward, lean back...\n16. No abstract terms"
  )) + "\n\n";

  // Rule 17-18: Voice auto-fill (opt-in via narration module)
  if (input.activeModules?.includes("narration")) {
    const voiceRule = input.narrations?.length
    ? r("voice", L(
      "【声音 — 预生成旁白已提供】\n17. 上方「旁白/画外音（已预生成）」中提供了叙事声音行。你必须将它们嵌入到 integrated_multimodal_description 的对应时间段中。\n18. 每 3-5 秒至少嵌入一句。禁止纯默片 shot。",
      "【Voice — Pre-generated Narration Provided】\n17. The NARRATION section above provides voice lines. Embed them into the corresponding time segments.\n18. At least one spoken line every 3-5s. No pure silent shots."
    ))
    : r("voice", L(
      "【声音 — 主动补位】\n17. 如果本 shot 对话台本为空，必须主动生成画外音或旁白\n18. 每 3-5 秒至少一句声音。禁止纯默片 shot。",
      "【Voice — Active Fill】\n17. If dialogue is empty, actively generate off-screen voiceover or narration.\n18. At least one spoken line every 3-5s. No pure silent shots."
    ));
    text += voiceRule + "\n";
  }

  return text;
}

// ── Segment Calculator ──────────────────────────────────

function computeSegments(duration: number): Array<{ label: string }> {
  if (duration <= 5) return [{ label: `0-${duration}s` }];
  if (duration <= 8) {
    const m = Math.floor(duration / 2);
    return [{ label: `0-${m}s` }, { label: `${m}-${duration}s` }];
  }
  if (duration <= 14) {
    const s = Math.floor(duration / 3);
    return [
      { label: `0-${s}s` },
      { label: `${s}-${s * 2}s` },
      { label: `${s * 2}-${duration}s` },
    ];
  }
  const s = Math.floor(duration / 4);
  return [
    { label: `0-${s}s` },
    { label: `${s}-${s * 2}s` },
    { label: `${s * 2}-${s * 3}s` },
    { label: `${s * 3}-${duration}s` },
  ];
}

// ── Layer 3: Guide ──────────────────────────────────────

/**
 * Hardcoded fallback guide — used when registry lookup fails.
 * Content mirrors the video_h3_fl2v_guide registry entry.
 */
function buildGuideLayerFallback(lang: H3Language): string {
  const L = (zh: string, en: string) => lang === "zh" ? zh : en;
  return [
    `## ${L("角色", "ROLE")}`,
    L(
      "你是 MiniMax H3 FL2VA 模式的专家级提示词工程师。",
      "You are an expert prompt engineer for MiniMax H3 (FL2VA mode)."
    ),
    "",
    `## ${L("任务", "TASK")}`,
    L(
      "将提供的视频剧本+上下文转换为 H3 兼容的结构化提示词。",
      "Transform the provided video script + context into a H3-compatible structured prompt."
    ),
    "",
    `## ${L("输出", "OUTPUT")}`,
    L(
      "仅输出 H3 格式内容。无前言、无 markdown、无注释。",
      "Only the H3 format content. No introduction, no markdown, no commentary."
    ),
  ].join("\n");
}

// ── Public API ──────────────────────────────────────────

/**
 * Build FL2V prompt template for LLM consumption.
 * Layer 1 (Content): assembled dynamically from registry content labels
 * Layer 2 (Constraints): read from registry video_h3_fl2v_constraints
 * Layer 3 (Guide): read from registry video_h3_fl2v_guide or systemOverride
 */
export async function buildFL2VPromptTemplate(
  input: H3PromptInput,
  systemOverride?: string
): Promise<{ system: string; user: string }> {
  const lang = resolveLanguage(input);

  // ── Layer 3: Guide (system prompt) ──
  let system: string;
  if (systemOverride) {
    system = systemOverride;
  } else {
    const guideDef = getPromptDefinition("video_h3_fl2v_guide")
      ?? getPromptDefinition("video_h3_prompt");
    if (guideDef) {
      system = guideDef.buildFullPrompt({});
    } else {
      console.warn("[H3-FL2V] Registry guide lookup failed, using hardcoded fallback");
      system = buildGuideLayerFallback(lang);
    }
  }

  // ── Layer 1: Content labels ──
  let contentSlots: Record<string, string> = {};
  try {
    contentSlots = getDefaultSlotContents("video_h3_fl2v_content") ?? {};
  } catch {
    console.warn("[H3-FL2V] Registry content slots lookup failed, using defaults");
  }

  // ── Layer 2: Constraint rules ──
  let constraintSlots: Record<string, string> = {};
  try {
    constraintSlots = getDefaultSlotContents("video_h3_fl2v_constraints") ?? {};
  } catch {
    console.warn("[H3-FL2V] Registry constraint slots lookup failed, using defaults");
  }

  const userContent = buildContentLayer(input, contentSlots, lang);
  const userConstraints = buildConstraintLayer(input, constraintSlots, lang);

  return {
    system,
    user: [userContent, "", userConstraints].join("\n"),
  };
}