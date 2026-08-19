// ═══════════════════════════════════════════════
// H3 Ref2VA (Full-Reference Mode) Builder (v0.2.0)
//
// Reference: MiniMax H3 official VIDEO_PROMPT_WRITING_GUIDE_ref_en.md
//   §1 — Overall Structure (6 sections in order)
//   §2 — Reference Labels: <Subject N>, <Picture N>, <Video N>, <Audio N>
//   §3 — summary ([task_type] + one paragraph)
//   §4 — retention_analysis (fully_preserved/partially_preserved/attribute_transfer/weak_reference)
//   §5 — detailed_description (reuses base mode with <Subject N> labels)
//   §6 — overall_soundscape
//   §7 — non_diegetic_music
// ═══════════════════════════════════════════════

import type {
  H3PromptInput, H3PromptOutput,
  SubjectDef, PictureDef, AudioDef, H3TaskType,
  RetentionVision, RetentionAudio,
} from "../types";
import { buildH3Sections } from "../shared/base-builder";

// ═══ Public API ═══════════════════════════════════════════════

/**
 * Build H3 Ref2VA 6-section prompt.
 *
 * Sections:
 *   [0] subject_definitions
 *   [1] summary
 *   [2] retention_analysis
 *   [3] detailed_description (from base mode, with <Subject N> labels)
 *   [4] overall_soundscape
 *   [5] non_diegetic_music
 */
export function buildR2VPrompt(input: H3PromptInput): H3PromptOutput {
  const subjects = buildAllSubjectDefs(input);
  const pictures = buildPictureDefs(input);
  const audios = buildAudioDefs(input);
  const taskTypes = detectTaskTypes(input);

  const baseOutput = buildH3Sections(input);

  return {
    mode: "ref2va",
    taskType: (taskTypes[0] ?? "reference_generation") as H3TaskType,
    languageUsed: baseOutput.languageUsed,
    sections: [
      buildSubjectDefsSection(subjects, pictures, audios),
      buildSummarySection(taskTypes, subjects, input),
      buildRetentionSection(subjects, pictures, audios, input),
      buildDetailedWithVoice(baseOutput.sections[0], input),  // detailed_description + voice
      baseOutput.sections[1],  // overall_soundscape
      baseOutput.sections[2],  // non_diegetic_music
    ],
  };
}

// ═══ Helpers ═══════════════════════════════════════════════

/**
 * Inject pre-generated narrations/innerMonologues into the
 * detailed_description for R2V local fallback (G2 fix).
 * Mirrors the VL path's Constraint Layer R17-19 voice injection.
 */
function buildDetailedWithVoice(detail: string, input: H3PromptInput): string {
  const parts = [detail];

  if (input.narrations?.length) {
    parts.push("\n旁白（已预生成）:\n" + input.narrations.join("\n"));
  }
  if (input.innerMonologues?.length) {
    parts.push("\n内心独白（已预生成）:\n" + input.innerMonologues.join("\n"));
  }

  return parts.join("");
}

// ═══ subject_definitions §2 ═══════════════════════════════════
// Source: Official guide, section 2

function buildAllSubjectDefs(input: H3PromptInput): SubjectDef[] {
  const defs: SubjectDef[] = [];

  // §2.1: Each character → <Subject N>
  for (let i = 0; i < input.characters.length; i++) {
    const char = input.characters[i];
    const sourceLabels: string[] = [];

    // Character reference images → <Picture N>
    if (char.referenceImage) {
      // Picture index = characters before this with ref images + 1 (for first_frame)
      const picIdx = input.characters
        .filter((c, j) => j < i && c.referenceImage)
        .length + 2;  // +2 accounts for Picture 1 (first_frame) if present
      sourceLabels.push(`<Picture ${picIdx}>`);
    }

    // §2.1: Combine sources and state what each asset provides
    const sourceText = sourceLabels.length > 0
      ? ` in ${sourceLabels.join(", ")}`
      : "";

    // Character definition with physical attributes
    let def = `${char.name}: ${char.description ?? "a character"}`;
    if (char.visualHint) def += ` (${char.visualHint})`;
    if (char.heightCm && char.heightCm > 0) def += `, height ${char.heightCm}cm`;
    if (char.bodyType && char.bodyType !== "average") def += `, ${char.bodyType} build`;
    if (char.performanceStyle) def += `. Performance style: ${char.performanceStyle}`;
    def += sourceText;

    defs.push({
      label: `<Subject ${i + 1}>`,
      definition: def,
      sourceLabels,
    });
  }

  // §2.1: Scene/environment as Subject (if scene data present)
  if (input.sceneDescription) {
    const idx = defs.length + 1;
    const sourceLabels: string[] = [];
    if (input.firstFrame) sourceLabels.push("<Picture 1>");
    defs.push({
      label: `<Subject ${idx}>`,
      definition: `The scene environment: ${input.sceneDescription}${input.sceneLighting ? `, lit by ${input.sceneLighting}` : ""}${sourceLabels.length ? ` in ${sourceLabels.join(", ")}` : ""}`,
      sourceLabels,
    });
  }

  return defs;
}

// §2.2 <Picture N>
function buildPictureDefs(input: H3PromptInput): PictureDef[] {
  const defs: PictureDef[] = [];

  // §2.2: First frame → <Picture 1>
  if (input.firstFrame?.fileUrl) {
    defs.push({
      label: "<Picture 1>",
      shotIndex: 1,
      role: "first_frame",
      description: input.firstFrame.prompt ?? "the opening frame of the video",
    });
  }

  // §2.2: Last frame → next Picture
  if (input.lastFrame?.fileUrl) {
    defs.push({
      label: `<Picture ${defs.length + 1}>`,
      shotIndex: 1,
      role: "last_frame",
      description: input.lastFrame.prompt ?? "the closing frame of the video",
    });
  }

  // §2.2: Storyboard/character reference images
  for (const char of input.characters) {
    if (char.referenceImage) {
      defs.push({
        label: `<Picture ${defs.length + 1}>`,
        shotIndex: 0,
        role: "storyboard",
        description: `${char.name} character reference image`,
      });
    }
  }

  return defs;
}

// §2.4 <Audio N>
function buildAudioDefs(input: H3PromptInput): AudioDef[] {
  const defs: AudioDef[] = [];

  // §2.4: BGM → <Audio 1>
  if (input.bgmUrl) {
    defs.push({
      label: "<Audio 1>",
      role: "bgm_style",
      description: "Background music reference for the target video",
    });
  }

  // §2.4: Dialogue audio → voice timbre reference
  for (const d of input.dialogues ?? []) {
    if (d.audioUrl) {
      const charIdx = input.characters.findIndex(c => c.name === d.characterName);
      defs.push({
        label: `<Audio ${defs.length + 1}>`,
        role: "voice_timbre",
        sourceSubjectLabel: charIdx >= 0 ? `<Subject ${charIdx + 1}>` : undefined,
        description: `Voice timbre reference for ${d.characterName}`,
      });
    }
  }

  return defs;
}

// ═══ summary §3 ═══════════════════════════════════════════════
// Source: Official guide, section 3
// Format: [task_type_1 + task_type_2] One English paragraph summarizing
//         the target video and its main reference relationships.

function detectTaskTypes(input: H3PromptInput): string[] {
  const types: string[] = [];
  if (input.firstFrame && input.lastFrame) types.push("keyframe_completion");
  if (input.characters.some(c => c.referenceImage)) types.push("reference_generation");
  if (input.bgmUrl) types.push("audio_reference");
  return types.length > 0 ? types : ["reference_generation"];
}

function buildSummarySection(
  taskTypes: string[],
  subjects: SubjectDef[],
  input: H3PromptInput,
): string {
  const prefix = `[${taskTypes.join(" + ")}]`;

  // §3: Use episode description if available; otherwise build from subjects
  const body = input.episodeDescription
    ?? input.projectIdea
    ?? `The target video shows ${subjects.map(s => s.label).join(", ")} in a scene.`;

  return `summary:\n${prefix} ${body}`;
}

// ═══ retention_analysis §4 ════════════════════════════════════
// Source: Official guide, section 4
// Visual: fully_preserved | partially_preserved | attribute_transfer | weak_reference
// Audio:  fully_copy | partially_copy | reference | weak_reference

function buildRetentionSection(
  subjects: SubjectDef[],
  pictures: PictureDef[],
  audios: AudioDef[],
  input: H3PromptInput,
): string {
  const lines: string[] = ["retention_analysis:"];

  // §4.1: Subjects — infer retention from scope + referenceImage presence
  for (let i = 0; i < subjects.length; i++) {
    const char = input.characters[i];
    const s = subjects[i];

    let retention: RetentionVision;
    let reason: string;

    if (char?.scope === "main") {
      retention = s.sourceLabels.length > 0 ? "fully_preserved" : "partially_preserved";
      reason = s.sourceLabels.length > 0
        ? "character identity and appearance are locked to reference images"
        : "character appearance follows the written description (no reference image)";
    } else if (char?.scope === "guest") {
      retention = s.sourceLabels.length > 0 ? "partially_preserved" : "weak_reference";
      reason = "guest character: broad appearance similarity is sufficient";
    } else {
      // Scene Subject (environment)
      retention = "weak_reference";
      reason = "scene atmosphere and lighting serve as broad visual guidance";
    }

    lines.push(`${s.label}: ${retention} — ${reason}.`);
  }

  // §4.1: Pictures
  for (const p of pictures) {
    let retention: RetentionVision;
    let reason: string;
    if (p.role === "first_frame") {
      retention = "fully_preserved"; reason = "the opening composition is preserved";
    } else if (p.role === "last_frame") {
      retention = "fully_preserved"; reason = "the closing composition is preserved";
    } else {
      retention = "weak_reference"; reason = "character reference image provides visual guidance";
    }
    lines.push(`${p.label} (${p.role === "first_frame" ? "[Shot 1] first frame" : p.role === "last_frame" ? "[Shot 1] last frame" : "storyboard reference"}): ${retention} — ${reason}.`);
  }

  // §4.2: Audio
  for (const a of audios) {
    let retention: RetentionAudio;
    let reason: string;
    if (a.role === "bgm_style") {
      retention = "reference"; reason = "BGM style and mood are referenced without copying the original signal";
    } else if (a.role === "voice_timbre") {
      retention = "reference"; reason = "voice timbre and delivery style are referenced";
    } else {
      retention = "partially_copy"; reason = "audio content is partially reused";
    }
    lines.push(`${a.label}: ${retention} — ${reason}.`);
  }

  return lines.join("\n");
}

// ═══ Section text builders ════════════════════════════════════

function buildSubjectDefsSection(
  subjects: SubjectDef[],
  pictures: PictureDef[],
  audios: AudioDef[],
): string {
  const lines: string[] = ["subject_definitions:"];

  for (const s of subjects) {
    lines.push(`${s.label} is ${s.definition}`);
  }

  for (const p of pictures) {
    const roleText = p.role === "first_frame" ? "is the first frame of [Shot 1]"
      : p.role === "last_frame" ? "is the last frame of [Shot 1]"
      : "is a character reference image";
    lines.push(`${p.label} ${roleText}. ${p.description}.`);
  }

  for (const a of audios) {
    const refText = a.sourceSubjectLabel
      ? `is the voice-timbre reference for ${a.sourceSubjectLabel}`
      : `is the ${a.role.replace("_", " ")} reference`;
    lines.push(`${a.label} ${refText}. ${a.description}.`);
  }

  return lines.join("\n");
}