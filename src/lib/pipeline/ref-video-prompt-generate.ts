/**
 * Reference Video Prompt Generate Pipeline Handler.
 *
 * Generates a reference-mode video prompt via Vision LLM (gemma4-31b-vl)
 * and stores it in shot.videoPrompt. This is a standalone step — video
 * generation is handled separately by reference-video-generate.ts.
 *
 * Input: scene frame images (shot_assets type='reference')
 * Output: shot.videoPrompt (text, with @图片N reference format)
 */

import { db } from "@/lib/db";
import { shots } from "@/lib/db/schema";
import { resolveAIProvider } from "@/lib/ai/provider-factory";
import type { ModelConfigPayload } from "@/lib/ai/provider-factory";
import { resolvePrompt } from "@/lib/ai/prompts/resolver";
import { buildRefVideoPromptRequest } from "@/lib/ai/prompts/ref-video-prompt-generate";
import { buildReferenceVideoPrompt } from "@/lib/ai/prompts/video-generate";
import { getModelMaxDuration } from "@/lib/ai/model-limits";
import { eq } from "drizzle-orm";
import type { Task } from "@/lib/task-queue";
import { failTask } from "@/lib/task-queue";
import { getActiveAssets, loadShotLegacyView, stripCharHint } from "@/lib/shot-asset-utils";
import { getEpisodeCharacters } from "@/lib/db/episode-characters";

export async function handleRefVideoPromptGenerate(task: Task) {
  const payload = task.payload as {
    shotId: string;
    projectId: string;
    userId?: string;
    modelConfig?: ModelConfigPayload;
  };

  // 1. Load shot
  const [shot] = await db.select().from(shots).where(eq(shots.id, payload.shotId));
  if (!shot) { await failTask(task.id, "Shot not found"); return; }

  // 2. Collect scene frames
  const allRefs = await getActiveAssets(shot.id, "reference");
  const pendingRefs = allRefs.filter(r => r.status === "pending");
  if (pendingRefs.length > 0) {
    await failTask(task.id, `${pendingRefs.length} scene frames pending — generate them first`);
    return;
  }
  const sceneFrames = allRefs.filter(r => r.fileUrl).sort((a, b) => a.sequenceInType - b.sequenceInType);
  const sceneFramePaths = sceneFrames.map(r => r.fileUrl as string);
  if (sceneFramePaths.length === 0) {
    await failTask(task.id, "No scene reference images — generate scene frames first");
    return;
  }

  // 3. Collect character info for reference labels
  const projectCharacters = await getEpisodeCharacters(payload.projectId, shot.episodeId);
  const shotCharNames = new Set<string>();
  for (const r of allRefs) {
    for (const n of r.characters ?? []) shotCharNames.add(stripCharHint(n));
  }
  const charRefs = projectCharacters
    .filter(c => !!c.referenceImage &&
      (shotCharNames.has(stripCharHint(c.name)) || shotCharNames.has((c as any).baseName || "")))
    .map(c => ({ name: c.name, imagePath: c.referenceImage as string }));

  const effectiveDuration = Math.min(shot.duration ?? 10,
    getModelMaxDuration(payload.modelConfig?.video?.modelId));

  // 4. Vision LLM: generate video prompt
  let videoPrompt: string;
  try {
    const textProvider = resolveAIProvider(payload.modelConfig);
    const systemPrompt = await resolvePrompt("ref_video_prompt", {
      userId: payload.userId ?? "", projectId: payload.projectId,
    });
    const charInfos = charRefs.map((c, i) => ({ name: c.name, index: i + 1 }));
    const sceneInfos = sceneFramePaths.map((_, i) => {
      const name = (sceneFrames[i]?.meta as any)?.sceneName || `场景-${i + 1}`;
      return { label: name, index: charRefs.length + i + 1 };
    });

    const promptReq = buildRefVideoPromptRequest({
      motionScript: shot.motionScript || shot.videoScript || shot.prompt || "",
      cameraDirection: shot.cameraDirection || "static",
      duration: effectiveDuration,
      characters: charInfos,
      sceneFrames: sceneInfos,
    });

    const rawPrompt = await withTimeout(
      textProvider.generateText(promptReq, {
        systemPrompt, images: sceneFramePaths, temperature: 0.7,
      }),
      60_000,
    );

    if (!rawPrompt || rawPrompt.trim().length < 10) {
      throw new Error("Vision LLM returned empty/invalid prompt");
    }

    videoPrompt = `Duration: ${effectiveDuration}s.\n\n${rawPrompt.trim()}`;
  } catch (err) {
    // Fallback: static template (no Vision LLM)
    console.warn(`[RefVideoPrompt] Vision LLM failed, using fallback: ${err instanceof Error ? err.message : String(err)}`);
    const charRefInfos = charRefs.map((c, i) => ({ name: c.name, index: i + 1 }));
    const sceneFrameInfos = sceneFramePaths.map((_, i) => ({ label: `场景-${i + 1}`, index: charRefs.length + i + 1 }));
    const fullMapping = [...charRefInfos.map(c => `@图片${c.index}是${c.name}`),
      ...sceneFrameInfos.map(s => `@图片${s.index}是${s.label}`)].join("，") + "。";
    videoPrompt = `图像映射：${fullMapping}。\n\n${buildReferenceVideoPrompt({
      videoScript: shot.videoScript || shot.motionScript || shot.prompt || "",
      cameraDirection: shot.cameraDirection || "static",
      duration: effectiveDuration,
      characters: projectCharacters,
    })}`;
  }

  // 5. Store
  await db.update(shots).set({ videoPrompt }).where(eq(shots.id, shot.id));

  return { shotId: shot.id, videoPrompt };
}

function withTimeout<T>(promise: Promise<T>, ms: number): Promise<T> {
  let timer: NodeJS.Timeout;
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(new Error(`Timeout after ${ms}ms`)), ms);
  });
  return Promise.race([promise, timeout]).finally(() => clearTimeout(timer!));
}