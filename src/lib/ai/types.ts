export interface TextOptions {
  model?: string;
  temperature?: number;
  maxTokens?: number;
  systemPrompt?: string;
  images?: string[];  // local file paths for vision input
}

export interface ImageOptions {
  model?: string;
  size?: string;
  aspectRatio?: string;
  quality?: string;
  referenceImages?: string[];
  /** Labels for reference images, e.g. character names. Must match referenceImages order. */
  referenceLabels?: string[];
  /** Pipeline ID for multi-step workflow orchestration (ComfyUIProvider only) */
  pipeline?: string;
  /** Extra pipeline-specific parameters (e.g. first_prompt, last_prompt, seed) */
  pipelineParams?: Record<string, unknown>;
  /** Scene-only prose description for the baseline environment (Edit-plus scene_prompt).
   *  When set, provider.ts uses this as node_4.text instead of deriving from the primary prompt.
   *  This separate the baseline scene (scenePrompt) from the frame description (prompt). */
  scenePrompt?: string;
}

export interface AIProvider {
  generateText(prompt: string, options?: TextOptions): Promise<string>;
  generateImage(prompt: string, options?: ImageOptions): Promise<string>;
}

// Keyframe mode: both firstFrame and lastFrame must be provided
type KeyframeVideoParams = {
  firstFrame: string;
  lastFrame: string;
  initialImage?: never;
};

// Reference image mode: a single initial image (local path or http URL)
type ReferenceVideoParams = {
  firstFrame?: never;
  lastFrame?: never;
  initialImage: string;
};

export type VideoGenerateParams = (KeyframeVideoParams | ReferenceVideoParams) & {
  prompt: string;
  duration: number;
  ratio: string;
  /** Character/style reference images for consistency (e.g. Veo 3.1 referenceImages) */
  referenceImages?: string[];
};

export interface VideoGenerateResult {
  filePath: string;
  lastFrameUrl?: string;
}

export interface VideoProvider {
  generateVideo(params: VideoGenerateParams): Promise<VideoGenerateResult>;
}
