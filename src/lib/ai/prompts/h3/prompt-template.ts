// ═══════════════════════════════════════════════
// H3 Video Prompt — 3-Layer Context Engineering
// v0.2.1: time-segmentation + action beats + dialogue injection
// ═══════════════════════════════════════════════

import type { H3PromptInput } from "./types";
import { mapCameraDirection } from "./camera-map";
import { detectLanguage } from "./language-route";

export type H3Language = "zh" | "en";

export function resolveLanguage(input: H3PromptInput): H3Language {
  if (input.languageMode === "zh") return "zh";
  if (input.languageMode === "en") return "en";
  return detectLanguage(input.videoScript);
}

// ── Layer 1: Content Assembly ───────────────────────────

function buildContentLayer(input: H3PromptInput, lang: H3Language): string {
  const L = (zh: string, en: string) => lang === "zh" ? zh : en;
  const parts: string[] = [];

  // ── 1. Project Overview ───────────────────────────
  if (input.projectTitle || input.projectOutline || input.projectWorldSetting) {
    parts.push(`## ${L("项目纲要", "PROJECT OVERVIEW")}`);
    if (input.projectTitle) parts.push(L(`项目：${input.projectTitle}`, `Project: ${input.projectTitle}`));
    if (input.projectOutline) {
      parts.push(L("故事大纲：", "Story Outline:"));
      parts.push(input.projectOutline);
    }
    if (input.projectWorldSetting) {
      parts.push(L(`世界观：${input.projectWorldSetting}`, `World Setting: ${input.projectWorldSetting}`));
    }
    parts.push("");
  }

  // ── 2. Episode Context ────────────────────────────
  if (input.episodeTitle || input.episodeDescription) {
    parts.push(`## ${L("剧集背景", "EPISODE CONTEXT")}`);
    if (input.episodeTitle) parts.push(L(`集标题：${input.episodeTitle}`, `Episode: ${input.episodeTitle}`));
    if (input.episodeDescription) parts.push(input.episodeDescription);
    if (input.episodeKeywords) parts.push(`${L("关键词", "Keywords")}: ${input.episodeKeywords}`);
    parts.push("");
  }

  // ── 3. Scene ──────────────────────────────────────
  if (input.sceneDescription || input.sceneLighting || input.sceneColorPalette) {
    parts.push(`## ${L("场景", "SCENE")}`);
    if (input.sceneDescription) parts.push(`${L("地点", "Location")}: ${input.sceneDescription}`);
    if (input.sceneLighting) parts.push(`${L("光线", "Lighting")}: ${input.sceneLighting}`);
    if (input.sceneColorPalette) parts.push(`${L("色调", "Color palette")}: ${input.sceneColorPalette}`);
    parts.push("");
  }

  // ── 4. Frame Anchors ──────────────────────────────
  const hasFrames = input.firstFrame?.prompt || input.lastFrame?.prompt;
  if (hasFrames) {
    parts.push(`## ${L("帧锚点（关键帧图片）", "FRAME ANCHORS (keyframe images)")}`);
    parts.push(L(
      "以下是实际用作首/末帧锚点的图片。你必须描述从首帧到末帧的视觉过渡。",
      "These are the actual images that will be used as first/last frame anchors. You must describe the visual transition from the first frame to the last frame."
    ));
    if (input.firstFrame?.prompt) {
      parts.push(L(
        `<Picture 1>（首帧——视频从此图开始）：${input.firstFrame.prompt}`,
        `<Picture 1> (FIRST FRAME — video opens from this image): ${input.firstFrame.prompt}`
      ));
    }
    if (input.lastFrame?.prompt) {
      parts.push(L(
        `<Picture 2>（末帧——视频必须以此图结束）：${input.lastFrame.prompt}`,
        `<Picture 2> (LAST FRAME — video must end at this image): ${input.lastFrame.prompt}`
      ));
    }
    parts.push("");
  }

  // ── 5. Characters ─────────────────────────────────
  if (input.characters?.length) {
    parts.push(`## ${L("角色", "CHARACTERS")}`);
    parts.push(L(
      "（这些角色已出现在首尾帧中。仅描述他们的动作和对话，不要描述外貌。）",
      "(These characters are already present in the first/last frames. Describe their ACTIONS and DIALOGUE only, NOT their appearance.)"
    ));
    parts.push(L("分配说话人 ID（按出场顺序：S1, S2, ...）：", "Assign speaker IDs (first-appearance order: S1, S2, ...):"));
    for (const c of input.characters) {
      const role = c.scope === "guest" ? L("[客串]", "[guest]") : "";
      const style = c.performanceStyle ? `— ${c.performanceStyle}` : "";
      parts.push(`- ${c.name} ${role}${style}`);
    }
    parts.push("");
  }

  // ── 6. Video Script ───────────────────────────────
  parts.push(`## ${L("视频剧本", "VIDEO SCRIPT")}`);
  parts.push(input.videoScript || "(no script)");
  parts.push("");

  // ── 7. Dialogues ──────────────────────────────────
  if (input.dialogues?.length) {
    parts.push(`## ${L("对话台本（必须在视频中呈现！）", "DIALOGUE SCRIPT (MUST be included in the video!)")}`);
    const usedNames: string[] = [];
    for (const d of input.dialogues) {
      if (!usedNames.includes(d.characterName)) usedNames.push(d.characterName);
    }
    for (const d of input.dialogues) {
      const sid = usedNames.indexOf(d.characterName) + 1;
      const tag = d.offscreen
        ? L(`(S${sid})画外音`, `(S${sid}) off-screen`)
        : `(S${sid})`;
      parts.push(L(`${tag}说：<d>[中文] ${d.text}</d>`, `${tag} says: <d>[Chinese] ${d.text}</d>`));
    }
    parts.push("");
  }

  // ── 8. Audio ──────────────────────────────────────
  if (input.soundDesign || input.musicCue || input.bgmUrl) {
    parts.push(`## ${L("音频", "AUDIO")}`);
    if (input.soundDesign) parts.push(`${L("环境音", "Diegetic sound")}: ${input.soundDesign}`);
    if (input.musicCue) parts.push(`${L("音乐提示", "Music cue")}: ${input.musicCue}`);
    if (input.bgmUrl) parts.push(`${L("BGM参考", "BGM reference")}: <Audio 1>`);
    parts.push("");
  }

  return parts.join("\n").trim();
}

// ── Layer 2: Constraints ────────────────────────────────

function buildConstraintLayer(input: H3PromptInput, lang: H3Language): string {
  const L = (zh: string, en: string) => lang === "zh" ? zh : en;
  const camera = mapCameraDirection(input.cameraDirection);
  const duration = input.duration || 10;
  const hasFirst = !!input.firstFrame?.fileUrl;
  const hasLast = !!input.lastFrame?.fileUrl;
  const hasDialogues = !!input.dialogues?.length;
  const segments = computeSegments(duration);

  const rules: string[] = [L("## 约束规则", "## CONSTRAINTS"), ""];

  // Frame alignment
  if (hasFirst && hasLast) {
    rules.push(L(
      `首行必须严格按照以下原文输出：
参考图与目标视频的对齐方式——<Picture 1>（来自 [Shot 1]）对齐目标视频的第0.00秒；<Picture 2>（来自 [Shot 1]）对齐目标视频的第${duration.toFixed(2)}秒。`,
      `First line MUST be exactly:\nHow the reference pictures align with the target video — <Picture 1> (from [Shot 1]) aligns with the 0.00-second mark of the target video; <Picture 2> (from [Shot 1]) aligns with the ${duration.toFixed(2)}-second mark of the target video.`
    ));
    rules.push("");
  }

  // Output format with time segments
  rules.push(L("### 输出格式", "### Output Format"), "");
  rules.push(L(
    "集成多模态描述 (integrated_multimodal_description):\n  在单个 [Shot 1] 内按时间段拆分，每段独占一行：",
    "integrated_multimodal_description:\n  Break into time segments within a single [Shot 1], each on its own line:"
  ));
  for (const seg of segments) {
    rules.push(`  ${seg.label}: {视觉描述+角色动作+运镜}${L("。{对白}", ". {dialogue}")}`);
  }
  rules.push("");
  rules.push(L(
    "整体环境音 (overall_soundscape):\n  1-3 句描述环境音和物理音效。禁止填 N/A 除非剧本明确要求完全静音。",
    "overall_soundscape:\n  1-3 sentences describing ambient/physical sounds. Never use N/A unless the script explicitly demands silence."
  ));
  rules.push("");
  rules.push(L(
    "非叙事音乐 (non_diegetic_music):\n  1-2 句描述背景配乐。无BGM时填 N/A。",
    "non_diegetic_music:\n  1-2 sentences describing background score. Use N/A if no BGM."
  ));
  rules.push("");

  // Hard Rules
  rules.push(L("### 硬性规则", "### Hard Rules"), "");

  // Time structure
  rules.push(L("【时间结构 — 强制执行】", "【Time Structure — MANDATORY】"));
  rules.push(L(
    `1. 必须按 ${segments.length} 个时间段拆分（不要创建 [Shot 2]），共 ${segments.map(s => s.label).join(" / ")}。每段独占一行`,
    `1. Split into exactly ${segments.length} time segments (do NOT create [Shot 2]): ${segments.map(s => s.label).join(" / ")}. Each on its own line`
  ));
  rules.push(L(
    "2. 每个时间段必须有独立的视觉变化和运镜动作",
    "2. Each segment must have distinct visual change and camera action"
  ));

  // Action beats
  rules.push("");
  rules.push(L("【动作节拍 — 强制执行】", "【Action Beats — MANDATORY】"));
  rules.push(L(
    "3. 每 2-3 秒安排一个微动作节点——即使静态镜头也要加入：呼吸节奏、衣物飘动、光线变化、水面波动、镜头微调",
    "3. Every 2-3s include a micro-action beat — even static shots need: breathing rhythm, fabric movement, light changes, water ripples, subtle camera adjustments"
  ));
  rules.push(L(
    "4. 用「先...随即...然后...最终...」串联微动作，禁止把全部动作写成同时发生",
    "4. Chain beats with temporal connectors: first... then... subsequently... finally... Never write all actions as simultaneous"
  ));

  // Dialogue
  rules.push("");
  rules.push(L("【对白 — 强制执行】", "【Dialogue — MANDATORY】"));
  if (hasDialogues) {
    rules.push(L(
      "5. 【⚠️ 此镜头有对话台本！按出场顺序分配 (S1)、(S2)... ID，格式：(S1)说：<d>[中文] 原文台词</d>",
      "5. 【⚠️ This shot HAS dialogue! Assign (S1), (S2)... in order of first appearance. Format: (S1) says: <d>[Chinese] text</d>"
    ));
  } else {
    rules.push(L(
      "5. 对白格式：(S1)说：<d>[中文] 原文台词</d>。画外音：(S1)以画外音方式说：<d>...</d>，同时嘴唇完全闭合",
      "5. Dialogue format: (S1) says: <d>[Chinese] text</d>. Off-screen: (S1) says in an off-screen voiceover: <d>...</d> while lips remain completely closed"
    ));
  }
  rules.push(L(
    "6. 对白必须嵌入对应时间段——先描述角色动作（抬眼、手势、身体语言），再写对白行",
    "6. Embed dialogue in its time segment — first describe character action (glance up, gesture, body language), then the dialogue line"
  ));

  // Camera
  rules.push("");
  rules.push(L("【运镜 — 强制执行】", "【Camera — MANDATORY】"));
  rules.push(L(
    `7. 主运镜方向：${camera}。每个时间段必须写独立的运镜动作`,
    `7. Primary motion: ${camera}. Each time segment must have its own explicit camera action`
  ));
  rules.push(L(
    "8. 运镜必须含幅度+速度修饰（如：极缓慢向右平移、小幅推近、中速拉远）",
    "8. Include amplitude + speed modifiers (e.g., slowly pans right with small amplitude, pushes in at medium speed, gently pulls back)"
  ));

  // Format
  rules.push("");
  rules.push(L("【格式】", "【Format】"));
  rules.push(L(
    "9. 全部输出为中文（对白 <d> 标签内保留原文）",
    "9. ALL output in English EXCEPT dialogue inside <d> tags (preserve original Chinese)"
  ));
  rules.push(L(
    "10. 角色已在帧中——仅描述动作和移动，禁止描述外貌",
    "10. Characters already in frames — describe ACTIONS and MOVEMENT only, never appearance"
  ));
  rules.push(L(
    "11. 禁止 markdown、代码块、注释——纯 H3 格式输出",
    "11. NO markdown, NO code blocks, NO commentary — pure H3 format output"
  ));
  rules.push(L(
    "12. 禁止逐字复制剧本——转换为丰富的影视级散文",
    "12. DO NOT copy script verbatim — translate into cinematic prose"
  ));

  return rules.join("\n");
}

// ── Layer 3: Guide ──────────────────────────────────────

function buildGuideLayer(lang: H3Language): string {
  const L = (zh: string, en: string) => lang === "zh" ? zh : en;
  return [
    `## ${L("角色", "ROLE")}`,
    L(
      "你是 MiniMax H3（I2VA/FL2VA 模式）的专家级提示词工程师。",
      "You are an expert prompt engineer for MiniMax H3 (I2VA/FL2VA mode)."
    ),
    "",
    `## ${L("任务", "TASK")}`,
    L(
      "将提供的视频剧本+上下文转换为 H3 兼容的结构化提示词。",
      "Transform the provided video script + context into a H3-compatible structured prompt."
    ),
    "",
    `## ${L("流程", "PROCESS")}`,
    L(
      "1. 阅读视频剧本——理解叙事核心和情绪走向",
      "1. Read the VIDEO SCRIPT — understand narrative core and emotional arc"
    ),
    L(
      "2. 阅读角色列表和对话台本——分配说话人 ID，确认谁在什么时候说话",
      "2. Read CHARACTERS and DIALOGUE — assign speaker IDs, determine who speaks when"
    ),
    L(
      "3. 阅读场景和音频上下文",
      "3. Read SCENE and AUDIO context"
    ),
    L(
      "4. 按约束规则中的时间段拆分——为每个时间段写独立的视觉描述+角色动作+运镜",
      "4. Split into time segments per the constraint rules — write independent visual + action + camera per segment"
    ),
    L(
      "5. 将对话台本嵌入对应时间段",
      "5. Embed dialogue lines into their time segments"
    ),
    L(
      "6. 生成完整的 H3 提示词",
      "6. Generate the complete H3 prompt"
    ),
    "",
    `## ${L("关键原则", "KEY PRINCIPLES")}`,
    L(
      "- 视频是时间艺术——描述必须是「动作推进链」而非「静态画面并列」",
      "- Video is a TIME MEDIUM — description must be an ACTION PROGRESSION, not a static snapshot"
    ),
    L(
      "- 每秒必须有视觉变化：光线移动、物体微动、角色微表情、镜头微调",
      "- Every second needs visual change: light movement, micro-motion, micro-expressions, subtle camera drift"
    ),
    L(
      "- 首帧→末帧过渡必须是因果推进的：先发生A→随即触发B→然后导致C",
      "- First→Last frame transition must be CAUSAL: A happens → triggering B → leading to C"
    ),
    L(
      "- 运镜必须绑定到具体时间段——不能只写一个方向粘在末尾",
      "- Camera must be BOUND to specific time segments — not one direction tacked on at the end"
    ),
    "",
    `## ${L("输出", "OUTPUT")}`,
    L(
      "仅输出 H3 格式内容。无前言、无 markdown、无注释。",
      "Only the H3 format content. No introduction, no markdown, no commentary."
    ),
  ].join("\n");
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

// ── Public API ──────────────────────────────────────────

export function buildH3PromptTemplate(
  input: H3PromptInput,
  systemOverride?: string
): { system: string; user: string } {
  const lang = resolveLanguage(input);
  return {
    system: systemOverride || buildGuideLayer(lang),
    user: [
      buildContentLayer(input, lang),
      "",
      buildConstraintLayer(input, lang),
    ].join("\n"),
  };
}