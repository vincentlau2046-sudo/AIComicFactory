// ═══════════════════════════════════════════════
// H3 Base Mode Builder (v0.2.0)
// Handles T2VA / I2VA / FL2VA modes
//
// Reference: MiniMax H3 official VIDEO_PROMPT_WRITING_GUIDE_base_en.md
//   §2.1  — Instruction prefix per mode
//   §4    — integrated_multimodal_description format
//   §4.2  — Shots and cuts ([Shot 1], [Shot N] At MM:SS.SSS)
//   §4.3  — Camera motion vocabulary
//   §4.4  — Speakers, dialogue, singing ((Sx), <d>)
//   §4.6  — overall_soundscape
//   §4.7  — non_diegetic_music
// ═══════════════════════════════════════════════

import type {
  H3PromptInput, H3PromptOutput,
  VisualStyle, ShotScript, SpeakerEvent,
  RetentionVision, RetentionAudio,
} from "./types";
import { mapCameraDirection } from "./camera-map";
import { detectLanguage } from "./language-route";

// ═══ Public API ═══════════════════════════════════════════════

/**
 * Build H3 Base Mode prompt (3 sections + instruction prefix).
 *
 * Returns H3PromptOutput with sections:
 *   sections[0] = instruction_prefix + integrated_multimodal_description
 *   sections[1] = overall_soundscape
 *   sections[2] = non_diegetic_music
 */
export function buildH3BasePrompt(input: H3PromptInput): H3PromptOutput {
  const lang = input.languageMode === "auto"
    ? detectLanguage(input.videoScript)
    : input.languageMode as "en" | "zh";

  const style = inferVisualStyle(input);
  const speakers = buildSpeakerEvents(input);
  const shots = buildShotScripts(input, speakers);
  const prefix = buildInstructionPrefix(input);

  return {
    mode: "base",
    taskType: input.generationMode === "reference" ? "reference_generation" : "keyframe_completion",
    languageUsed: lang,
    sections: [
      buildIntegratedSection(prefix, style, shots, lang),
      buildSoundscape(input),
      buildNonDiegeticMusic(input),
    ],
  };
}

// ═══ Instruction Prefix §2.1 ═══════════════════════════════════
// Source: Official guide, section 2.1

function buildInstructionPrefix(input: H3PromptInput): string | null {
  if (!input.firstFrame?.fileUrl) return null;

  if (input.lastFrame?.fileUrl) {
    // FL2VA: first+last frame
    return [
      "How the reference pictures align with the target video — ",
      "<Picture 1> (from [Shot 1]) aligns with the 0.00-second mark of the target video; ",
      `<Picture 2> (from [Shot 1]) aligns with the ${input.duration.toFixed(2)}-second mark of the target video.`
    ].join("");
  }

  // I2VA: first frame only
  return "For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.";
}

// ═══ Visual Style Inference ══════════════════════════════════
// Source: Official guide §4.1 — style stated at [Shot 1] opening

function inferVisualStyle(input: H3PromptInput): VisualStyle {
  const combined = (
    input.videoScript + " " +
    (input.sceneDescription ?? "") + " " +
    (input.episodeDescription ?? "")
  ).toLowerCase();

  if (combined.includes("anime") || combined.includes("cartoon") || combined.includes("2d"))
    return "2D-animated";
  if (combined.includes("claymation") || combined.includes("stop-motion"))
    return "claymation";
  if (combined.includes("watercolor"))
    return "watercolor";
  if (combined.includes("3d") || combined.includes("cg"))
    return "3D CG";
  if (combined.includes("vintage") || combined.includes("old film"))
    return "vintage film";

  return input.characters.some(c => c.referenceImage) ? "live-action" : "Cinematic";
}

// ═══ Speaker Events §4.4 ══════════════════════════════════════
// Source: Official guide, section 4.4
// Rules:
//   - Stable (S1), (S2) IDs assigned by first-appearance order
//   - Same character across shots keeps same ID
//   - Dialogue inside <d>[Language] text</d>

function buildSpeakerEvents(input: H3PromptInput): SpeakerEvent[] {
  if (!input.dialogues?.length) return [];

  const seen = new Map<string, string>();
  let nextId = 1;
  const events: SpeakerEvent[] = [];

  for (const d of input.dialogues) {
    if (!d.text?.trim()) continue;

    let speakerId = seen.get(d.characterName);
    if (!speakerId) {
      speakerId = `S${nextId++}`;
      seen.set(d.characterName, speakerId);
    }

    const charIdx = input.characters.findIndex(c => c.name === d.characterName);
    const subjectLabel = charIdx >= 0 ? `<Subject ${charIdx + 1}>` : undefined;

    events.push({
      speakerId,
      subjectLabel,
      lineText: d.text,
      language: detectLanguage(d.text) === "zh" ? "Chinese" : "English",
      isOffscreen: d.offscreen,
      timeInShot: `after ${d.startRatio} of shot duration`,
    });
  }

  return events;
}

// ═══ Shot Scripts §4.2 ════════════════════════════════════════
// Source: Official guide, section 4.2
// Rules:
//   - [Shot 1] has no timestamp
//   - [Shot N] starts with "At MM:SS.SSS,"
//   - H3 max 15s per shot → split if duration > 15

function buildShotScripts(
  input: H3PromptInput,
  speakers: SpeakerEvent[],
): ShotScript[] {
  const MAX_PER_SHOT = 15;
  const shotCount = Math.max(1, Math.ceil(input.duration / MAX_PER_SHOT));

  if (shotCount === 1) {
    return [{
      index: 1,
      timestampSeconds: 0,
      visualDescription: input.videoScript,
      cameraMotion: mapCameraDirection(input.cameraDirection),
      speakerEvents: speakers,
      diegeticSounds: [],
    }];
  }

  // Multi-shot split: divide duration evenly
  const shots: ShotScript[] = [];
  const perShotDuration = input.duration / shotCount;

  for (let i = 0; i < shotCount; i++) {
    const ratioStart = i / shotCount;
    const ratioEnd = (i + 1) / shotCount;

    // Distribute speakers evenly across shots by position
    const speakerPerShot = Math.ceil(speakers.length / shotCount);
    const startIdx = i * speakerPerShot;
    const shotSpeakers = speakers.slice(startIdx, startIdx + speakerPerShot);

    shots.push({
      index: i + 1,
      timestampSeconds: i * perShotDuration,
      visualDescription: i === 0
        ? input.videoScript
        : `[Shot ${i + 1} continuation of previous action]`,
      cameraMotion: mapCameraDirection(input.cameraDirection),
      speakerEvents: shotSpeakers,
      diegeticSounds: [],
    });
  }

  return shots;
}

// ═══ Integrated Multimodal Description §4 ════════════════════
// Source: Official guide, section 4
// Format: "[Shot 1] {style}, ... [Shot 2] At MM:SS.SSS, ..."

function buildIntegratedSection(
  prefix: string | null,
  style: VisualStyle,
  shots: ShotScript[],
  lang: "en" | "zh",
): string {
  const lines: string[] = [];

  // Instruction prefix line + blank line separator
  if (prefix) {
    lines.push(prefix);
    lines.push("");
  }

  lines.push("integrated_multimodal_description:");

  for (const shot of shots) {
    let shotLine: string;

    if (shot.index === 1) {
      // §4.2: First shot has no timestamp, opens with style
      shotLine = `[Shot 1] ${style}, ${shot.visualDescription}`;
    } else {
      // §4.2: Subsequent shots start with cut time
      const ts = formatTimestamp(shot.timestampSeconds);
      shotLine = `[Shot ${shot.index}] At ${ts}, the camera cuts to ${shot.visualDescription}`;
    }

    // §4.3: Camera motion
    if (shot.cameraMotion) {
      shotLine += ` ${shot.cameraMotion}.`;
    }

    // §4.4: Speaker events
    for (const spk of shot.speakerEvents) {
      const idPart = spk.subjectLabel
        ? `${spk.subjectLabel} (${spk.speakerId})`
        : `the speaker (${spk.speakerId})`;

      if (spk.isOffscreen) {
        shotLine += ` ${idPart} says in an off-screen voiceover: <d>[${spk.language}] ${spk.lineText}</d> while their lips remain completely closed.`;
      } else {
        shotLine += ` ${idPart} says: <d>[${spk.language}] ${spk.lineText}</d>`;
      }
    }

    // §4.2: Cross-shot continuity markers
    // <scenetrans> for dialogue crossing cuts (handled by speaker assignment)
    // <cutoff> for speech truncated by video end (not needed for single video)

    lines.push(shotLine);
    lines.push("");  // blank line between shots
  }

  return lines.join("\n").trim();
}

// ═══ overall_soundscape §4.6 ══════════════════════════════════
// Source: Official guide, section 4.6
// 1-4 English sentences summarizing ambience + physical sounds + non-verbal human sounds

function buildSoundscape(input: H3PromptInput): string {
  const raw = input.soundDesign?.trim();
  if (!raw) return "overall_soundscape: N/A";

  // If already English, use as-is
  if (detectLanguage(raw) === "en") {
    return `overall_soundscape: ${raw}`;
  }

  // Chinese: mark for translation (P4 will integrate IFF)
  return `overall_soundscape: [ZH: ${raw}]`;
}

// ═══ non_diegetic_music §4.7 ══════════════════════════════════
// Source: Official guide, section 4.7
// 1-3 sentences: instrumentation, tempo, dynamic development
// Use <Audio N> label when BGM file is available

function buildNonDiegeticMusic(input: H3PromptInput): string {
  if (input.bgmUrl) {
    return "non_diegetic_music: <Audio 1> is referenced as the complete background score.";
  }
  if (input.musicCue?.trim()) {
    return `non_diegetic_music: ${input.musicCue}`;
  }
  return "non_diegetic_music: N/A";
}

// ═══ Helpers ═══════════════════════════════════════════════════

/** Format seconds to H3 MM:SS.SSS format */
function formatTimestamp(seconds: number): string {
  const mm = Math.floor(seconds / 60).toString().padStart(2, "0");
  const ss = (seconds % 60).toFixed(3);
  return `${mm}:${ss.padStart(6, "0")}`;
}