/**
 * Reference Video Prompt Generate Pipeline Handler (v2).
 *
 * Generates H3 R2V 6-section video prompt via Vision LLM.
 * Now uses buildH3Input() for full context (dialogues, BGM, camera, episode).
 * Fallback: buildR2VPrompt local heuristics.
 */

import { db } from "@/lib/db";
import { shots } from "@/lib/db/schema";
import { resolveAIProvider } from "@/lib/ai/provider-factory";
import type { ModelConfigPayload } from "@/lib/ai/provider-factory";
import { getActiveAssets } from "@/lib/shot-asset-utils";
import { getEpisodeCharacters } from "@/lib/db/episode-characters";
import { buildR2VPromptLLM } from "@/lib/ai/prompts/h3/r2v/builder";
import { buildR2VPrompt } from "@/lib/ai/prompts/h3/r2v/ref-builder";
import { resolvePrompt } from "@/lib/ai/prompts/resolver";
import { eq } from "drizzle-orm";
import type { Task } from "@/lib/task-queue";
import { failTask } from "@/lib/task-queue";

export async function handleRefVideoPromptGenerate(task: Task) {
  const payload = task.payload as {
    shotId: string;
    projectId: string;
    userId?: string;
    modelConfig?: ModelConfigPayload;
  };

  const userId = payload.userId ?? "";
  const projectId = payload.projectId;

  // 1. Load shot
  const [shot] = await db.select().from(shots).where(eq(shots.id, payload.shotId));
  if (!shot) { await failTask(task.id, "Shot not found"); return; }

  // 2. Collect scene frames (for images + firstFrame/lastFrame context)
  const allRefs = await getActiveAssets(shot.id, "reference");
  const pendingRefs = allRefs.filter(r => r.status === "pending");
  if (pendingRefs.length > 0) {
    await failTask(task.id, `${pendingRefs.length} scene frames pending`);
    return;
  }
  const sceneFrames = allRefs.filter(r => r.fileUrl).sort((a, b) => a.sequenceInType - b.sequenceInType);
  const sceneFramePaths = sceneFrames.map(r => r.fileUrl as string);
  if (sceneFramePaths.length === 0) {
    await failTask(task.id, "No scene reference images");
    return;
  }

  // 3. Load full context via buildH3Input (same as FL2V path)
  const projectCharacters = await getEpisodeCharacters(projectId, shot.episodeId);
  const shotCharacters = projectCharacters.filter(c => c.referenceImage);

  const { buildH3Input } = await import("@/lib/ai/prompts/h3");
  const h3Input = await buildH3Input({
    userId,
    projectId,
    shot,
    shotCharacters,
    sceneFrames: sceneFrames.map(sf => ({ prompt: sf.prompt || null })),
    extraFields: {
      bgmUrl: undefined,  // buildH3Input loads this from episode/project
      costumes: projectCharacters
        .filter(c => c.referenceImage)
        .map(c => ({ name: c.name, description: c.description, referenceImage: c.referenceImage, characterId: c.id })),
    },
  });

  // 4. Resolve H3 system prompt from Registry (like FL2V)
  const h3System = await resolvePrompt("ref_video_prompt_h3", { userId, projectId })
    .catch(() => undefined);

  // 5. Vision LLM with fallback
  const visionProvider = resolveAIProvider(payload.modelConfig);

  let promptText: string;
  let source: "vl" | "fallback";

  try {
    const result = await buildR2VPromptLLM(h3Input, visionProvider, sceneFramePaths, h3System);
    source = result.source;
    const prefix = source === "vl" ? "[R2V-VL] " : "[R2V-LOCAL] ";
    promptText = prefix + result.output.sections.join("\n\n");
  } catch (err) {
    console.warn(`[RefVideoPrompt] VL+fallback failed, using pure local: ${err}`);
    const local = buildR2VPrompt(h3Input);
    source = "fallback";
    promptText = "[R2V-LOCAL] " + local.sections.join("\n\n");
  }

  // 6. Store
  await db.update(shots).set({ videoPrompt: promptText }).where(eq(shots.id, shot.id));

  return { shotId: shot.id, source };
}