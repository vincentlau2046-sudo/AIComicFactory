import { registerHandlers } from "@/lib/task-queue";
import { handleScriptOutline } from "./script-outline";
import { handleScriptParse } from "./script-parse";
import { handleCharacterExtract } from "./character-extract";
import { handleCharacterImage } from "./character-image";
import { handleShotSplit } from "./shot-split";
import { handleFrameGenerate } from "./frame-generate";
import { handleVideoGenerate } from "./video-generate";
import { handleVideoAssemble } from "./video-assemble";
import { handleSceneFrameGenerate } from "./scene-frame-generate";
import { handleReferenceVideoGenerate } from "./reference-video-generate";
import { handleRefVideoPromptGenerate } from "./ref-video-prompt-generate";

export function registerPipelineHandlers() {
  registerHandlers({
    script_outline: handleScriptOutline,
    script_parse: handleScriptParse,
    character_extract: handleCharacterExtract,
    character_image: handleCharacterImage,
    shot_split: handleShotSplit,
    frame_generate: handleFrameGenerate,
    video_generate: handleVideoGenerate,
    video_assemble: handleVideoAssemble,
    ref_video_prompt_generate: handleRefVideoPromptGenerate,
    scene_frame_generate: handleSceneFrameGenerate,
    reference_video_generate: handleReferenceVideoGenerate,
  });
}