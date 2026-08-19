// ═══════════════════════════════════════════════
// H3 Prompt Builder — Types (v0.2.0)
// Aligned with: MiniMax H3 official VIDEO_PROMPT_WRITING_GUIDE ref_en.md + base_en.md
// ═══════════════════════════════════════════════

export type H3Language = "zh" | "en";

/** Vision retention levels (official guide §4.1) */
export type RetentionVision =
  | "fully_preserved"
  | "partially_preserved"
  | "attribute_transfer"
  | "weak_reference";

/** Audio retention levels (official guide §4.2) */
export type RetentionAudio =
  | "fully_copy"
  | "partially_copy"
  | "reference"
  | "weak_reference";

/** Task types (official guide §3) */
export type H3TaskType =
  | "keyframe_completion"
  | "reference_generation"
  | "video_editing"
  | "video_continuation"
  | "audio_reuse"
  | "audio_reference";

/** Visual styles (official guide §4, inferred from context) */
export type VisualStyle =
  | "Cinematic" | "live-action" | "2D-animated"
  | "3D CG" | "claymation" | "watercolor" | "vintage film";

export interface SubjectDef {
  label: string;
  definition: string;
  sourceLabels: string[];
}

export interface PictureDef {
  label: string;
  shotIndex: number;
  role: "first_frame" | "last_frame" | "keyframe" | "storyboard";
  description: string;
}

export interface AudioDef {
  label: string;
  role: "voice_timbre" | "bgm_style" | "direct_copy" | "sound_effect";
  sourceSubjectLabel?: string;
  description: string;
}

export interface SpeakerEvent {
  speakerId: string;
  subjectLabel?: string;
  lineText: string;
  language: string;
  isOffscreen: boolean;
  timeInShot: string;
}

export interface ShotScript {
  index: number;
  timestampSeconds: number;
  visualDescription: string;
  cameraMotion: string;
  speakerEvents: SpeakerEvent[];
  diegeticSounds: string[];
}

export interface H3PromptInput {
  videoScript: string;
  motionScript?: string | null;
  duration: number;
  cameraDirection: string;
  generationMode: "keyframe" | "reference";
  characters: {
    id: string; name: string; description?: string | null;
    visualHint?: string | null; referenceImage?: string | null;
    performanceStyle?: string | null; scope: "main" | "guest";
    heightCm?: number | null; bodyType?: string | null;
  }[];
  firstFrame?: { fileUrl: string; prompt?: string | null };
  lastFrame?: { fileUrl: string; prompt?: string | null };
  dialogues?: {
    characterName: string; text: string; sequence?: number;
    startRatio?: string; endRatio?: string;
    audioUrl?: string | null; offscreen: boolean;
  }[];
  sceneDescription?: string;
  sceneLighting?: string;
  sceneColorPalette?: string;
  soundDesign?: string;
  musicCue?: string;
  bgmUrl?: string;
  costumes?: { name: string; description?: string | null; referenceImage?: string | null; characterId: string }[];
  compositionGuide?: string;
  projectTitle?: string;
  projectOutline?: string;
  projectWorldSetting?: string;
  episodeTitle?: string;
  episodeDescription?: string;
  episodeKeywords?: string;
  projectIdea?: string;
  languageMode: "auto" | "en" | "zh";
  slotContents?: Record<string, string>;
  visualStyleKey?: string;
  /** Pre-generated narration lines in H3 voiceover format (Phase 2) */
  narrations?: string[];
  innerMonologues?: string[];
  /** Active optional modules (e.g. ["narration"]). Empty or missing = base only. */
  activeModules?: string[];
}

export interface H3PromptOutput {
  sections: string[];
  mode: "base" | "ref2va";
  taskType: H3TaskType;
  languageUsed: "en" | "zh";
}