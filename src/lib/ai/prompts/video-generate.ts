import { getPromptDefinition } from "./registry";

type CharacterRef = { name: string; visualHint?: string | null };

function detectLanguage(text: string): "zh" | "en" {
  const chineseChars = text.match(/[\u4e00-\u9fff]/g);
  return chineseChars && chineseChars.length > text.length * 0.1 ? "zh" : "en";
}

function getLabels(lang: "zh" | "en") {
  return lang === "zh"
    ? {
        characterAppearance: "角色形象",
        dialogueLipSync: "对白口型",
        offscreenVoice: "画外音",
        camera: "镜头运动",
        duration: "时长",
        interpolation: "关键帧插值",
        openingFrame: "起始帧",
        closingFrame: "结束帧",
        videoScript: "视频脚本",
        frameAnchors: "帧锚点",
        separator: "，",
        period: "。",
        colon: "：",
        paren: { open: "（", close: "）" },
      }
    : {
        characterAppearance: "Character Appearance",
        dialogueLipSync: "Dialogue Lip Sync",
        offscreenVoice: "Off-screen Voice",
        camera: "Camera Movement",
        duration: "Duration",
        interpolation: "Keyframe Interpolation",
        openingFrame: "Opening Frame",
        closingFrame: "Closing Frame",
        videoScript: "Video Script",
        frameAnchors: "Frame Anchors",
        separator: ", ",
        period: ".",
        colon: ": ",
        paren: { open: "(", close: ")" },
      };
}

function buildCharacterLine(characters?: CharacterRef[], lang: "zh" | "en" = "zh"): string | null {
  const withHints = (characters ?? []).filter((c) => c.visualHint);
  if (!withHints.length) return null;
  const L = getLabels(lang);
  return withHints.map((c) => `${c.name}${L.paren.open}${c.visualHint}${L.paren.close}`).join(L.separator);
}

/**
 * Resolve a single slot value: use slotContents override, then registry default, then hardcoded fallback.
 */
function resolveSlot(
  slotContents: Record<string, string> | undefined,
  promptKey: string,
  slotKey: string,
  hardcodedFallback: string
): string {
  if (slotContents && slotKey in slotContents) return slotContents[slotKey];
  const def = getPromptDefinition(promptKey);
  if (def) {
    const s = def.slots.find((sl) => sl.key === slotKey);
    if (s) return s.defaultContent;
  }
  return hardcodedFallback;
}

/**
 * Prompt for reference-image-based video generation (Toonflow/Kling reference mode).
 * Seedance-style format: Shot description (prose) → Camera → 【对白口型】.
 * No frame interpolation header, no [FRAME ANCHORS] — the reference image provides visual context.
 */
export function buildReferenceVideoPrompt(params: {
  videoScript: string;
  cameraDirection: string;
  duration?: number;
  characters?: CharacterRef[];
  dialogues?: Array<{ characterName: string; text: string; offscreen?: boolean; visualHint?: string }>;
  slotContents?: Record<string, string>;
}): string {
  const lang = detectLanguage(params.videoScript);
  const L = getLabels(lang);
  const lines: string[] = [];

  if (params.duration) {
    lines.push(`${L.duration}${L.colon}${params.duration}s${L.period}`);
    lines.push(``);
  }

  const charLine = buildCharacterLine(params.characters, lang);
  if (charLine) {
    lines.push(`${L.characterAppearance}${L.colon}${charLine}${L.period}`);
    lines.push(``);
  }

  lines.push(params.videoScript);

  lines.push(``);
  lines.push(`${L.camera}${L.colon}${params.cameraDirection}${L.period}`);

  if (params.dialogues?.length) {
    // Resolve dialogue format slot to extract labels
    const dialogueFormatText = resolveSlot(
      params.slotContents,
      "ref_video_generate",
      "dialogue_format",
      ""
    );

    // Extract labels from the slot content, or use lang-aware defaults
    const defaultOnScreen = lang === "zh" ? "【对白口型】" : "[Dialogue Lip Sync]";
    const defaultOffScreen = lang === "zh" ? "【画外音】" : "[Off-screen Voice]";
    const onScreenLabel = extractLabel(dialogueFormatText, "画内对白", defaultOnScreen);
    const offScreenLabel = extractLabel(dialogueFormatText, "画外旁白", defaultOffScreen);

    lines.push(``);
    for (const d of params.dialogues) {
      if (d.offscreen) {
        lines.push(`${offScreenLabel}${d.characterName}: "${d.text}"`);
      } else {
        const label = d.visualHint ? `${d.characterName}${L.paren.open}${d.visualHint}${L.paren.close}` : d.characterName;
        lines.push(`${onScreenLabel}${label}: "${d.text}"`);
      }
    }
  }

  return lines.join("\n");
}

export function buildVideoPrompt(params: {
  videoScript: string;
  cameraDirection: string;
  startFrameDesc?: string;
  endFrameDesc?: string;
  sceneDescription?: string;       // kept for call-site compatibility, not used in output
  duration?: number;
  characters?: CharacterRef[];
  dialogues?: Array<{ characterName: string; text: string; offscreen?: boolean; visualHint?: string }>;
  slotContents?: Record<string, string>;
}): string {
  const lang = detectLanguage(params.videoScript);
  const L = getLabels(lang);
  const lines: string[] = [];

  if (params.duration) {
    lines.push(`${L.duration}${L.colon}${params.duration}s${L.period}`);
    lines.push(``);
  }

  const charLine = buildCharacterLine(params.characters, lang);
  if (charLine) {
    lines.push(`${L.characterAppearance}${L.colon}${charLine}${L.period}`);
    lines.push(``);
  }

  // Interpolation header from slot or registry default
  const defaultInterpolation = lang === "zh"
    ? "从起始帧到结束帧进行平滑插值。"
    : "Smoothly interpolate from the opening frame to the closing frame.";
  const interpolationHeader = resolveSlot(
    params.slotContents,
    "video_generate",
    "interpolation_header",
    defaultInterpolation
  );
  lines.push(interpolationHeader);
  lines.push(``);

  lines.push(params.videoScript);

  lines.push(``);
  lines.push(`${L.camera}${L.colon}${params.cameraDirection}${L.period}`);

  const hasStart = !!params.startFrameDesc;
  const hasEnd = !!params.endFrameDesc;
  if (hasStart || hasEnd) {
    // Resolve frame_anchors slot for label text
    const frameAnchorsText = resolveSlot(
      params.slotContents,
      "video_generate",
      "frame_anchors",
      ""
    );

    // Extract anchor header and labels from slot content, or use lang-aware defaults
    const defaultAnchorHeader = lang === "zh" ? "[帧锚点]" : "[FRAME ANCHORS]";
    const defaultOpeningLabel = lang === "zh" ? "起始帧：" : "Opening frame:";
    const defaultClosingLabel = lang === "zh" ? "结束帧：" : "Closing frame:";
    const anchorHeader = extractAnchorHeader(frameAnchorsText, defaultAnchorHeader);
    const openingLabel = extractFrameLabel(frameAnchorsText, "首帧", defaultOpeningLabel);
    const closingLabel = extractFrameLabel(frameAnchorsText, "尾帧", defaultClosingLabel);

    lines.push(``);
    lines.push(anchorHeader);
    if (hasStart) lines.push(`${openingLabel} ${params.startFrameDesc}`);
    if (hasEnd) lines.push(`${closingLabel} ${params.endFrameDesc}`);
  }

  if (params.dialogues?.length) {
    // Resolve dialogue format slot to extract labels
    const dialogueFormatText = resolveSlot(
      params.slotContents,
      "video_generate",
      "dialogue_format",
      ""
    );

    const defaultOnScreen = lang === "zh" ? "【对白口型】" : "[Dialogue Lip Sync]";
    const defaultOffScreen = lang === "zh" ? "【画外音】" : "[Off-screen Voice]";
    const onScreenLabel = extractLabel(dialogueFormatText, "画内对白", defaultOnScreen);
    const offScreenLabel = extractLabel(dialogueFormatText, "画外旁白", defaultOffScreen);

    lines.push(``);
    for (const d of params.dialogues) {
      if (d.offscreen) {
        lines.push(`${offScreenLabel}${d.characterName}: "${d.text}"`);
      } else {
        const label = d.visualHint ? `${d.characterName}${L.paren.open}${d.visualHint}${L.paren.close}` : d.characterName;
        lines.push(`${onScreenLabel}${label}: "${d.text}"`);
      }
    }
  }

  return lines.join("\n");
}

// ── Helpers for extracting labels from slot content ──────

/**
 * Extract dialogue label (e.g. 【对白口型】or 【画外音】) from the slot format text.
 */
function extractLabel(
  slotText: string,
  _lineHint: string,
  fallback: string
): string {
  if (!slotText) return fallback;
  // Match patterns like 【对白口型】 or 【画外音】 from the slot content
  const lines = slotText.split("\n");
  for (const line of lines) {
    if (line.includes(_lineHint)) {
      const match = line.match(/(【[^】]+】)/);
      if (match) return match[1];
    }
  }
  return fallback;
}

/**
 * Extract the anchor section header (e.g. [FRAME ANCHORS] or [帧锚点]) from slot text.
 */
function extractAnchorHeader(slotText: string, fallback: string): string {
  if (!slotText) return fallback;
  const match = slotText.match(/^\[([^\]]+)\]/m);
  if (match) return `[${match[1]}]`;
  return fallback;
}

/**
 * Extract frame label (e.g. "Opening frame:" or "首帧：") from slot text.
 */
function extractFrameLabel(slotText: string, lineHint: string, fallback: string): string {
  if (!slotText) return fallback;
  const lines = slotText.split("\n");
  for (const line of lines) {
    if (line.includes(lineHint)) {
      // Extract label before the placeholder (e.g. "首帧：" from "首帧：{{START_FRAME_DESC}}")
      const match = line.match(/^([^{]+)/);
      if (match) return match[1].trim();
    }
  }
  return fallback;
}
