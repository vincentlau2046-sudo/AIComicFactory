/**
 * Reference Video Generate Pipeline Handler (task queue Worker).
 *
 * Generates a reference-mode video (H3 R2V) for a single shot.
 * Collects scene frames + character reference images, builds video prompt
 * via Vision LLM, then submits to ComfyUI h3-r2v workflow.
 *
 * Idempotent: skips if a completed reference_video already exists.
 * Pre-flight: checks scene frames are all completed before proceeding.
 */

import { db } from "@/lib/db";
import { shots } from "@/lib/db/schema";
import { resolveAIProvider, resolveVideoProvider } from "@/lib/ai/provider-factory";
import type { ModelConfigPayload } from "@/lib/ai/provider-factory";
import { resolvePrompt } from "@/lib/ai/prompts/resolver";
import { buildRefVideoPromptRequest } from "@/lib/ai/prompts/ref-video-prompt-generate";
import { buildReferenceVideoPrompt } from "@/lib/ai/prompts/video-generate";
import { getModelMaxDuration } from "@/lib/ai/model-limits";
import { eq } from "drizzle-orm";
import type { Task } from "@/lib/task-queue";
import { failTask } from "@/lib/task-queue";
import { getActiveAsset, getActiveAssets, insertAssetVersion, loadShotLegacyView, stripCharHint, copyToUploads } from "@/lib/shot-asset-utils";
import { getEpisodeCharacters } from "@/lib/db/episode-characters";

export async function handleReferenceVideoGenerate(task: Task) {
  const payload = task.payload as {
    shotId: string;
    projectId: string;
    userId?: string;
    modelConfig?: ModelConfigPayload;
    ratio?: string;
  };

  // 1. Load shot
  const [shot] = await db.select().from(shots).where(eq(shots.id, payload.shotId));
  if (!shot) {
    await failTask(task.id, "Shot not found");
    return;
  }

  const view = await loadShotLegacyView(shot.id);

  // 2. Guard: block if another task is already generating this video
  const existing = await getActiveAsset(shot.id, "reference_video", 0);
  if (existing?.status === "generating") {
    await failTask(task.id, "reference_video already generating, retry later");
    return;
  }
  // Regeneration: insertAssetVersion handles deactivation of old active row automatically

  // 3. Collect + validate scene frames (all must be completed)
  const allRefs = await getActiveAssets(shot.id, "reference");
  const pendingRefs = allRefs.filter((r) => r.status === "pending");
  if (pendingRefs.length > 0) {
    await failTask(task.id, `${pendingRefs.length} scene frames still pending, try later`);
    return;
  }
  const sceneFrames = allRefs.filter((r) => r.fileUrl).sort((a, b) => a.sequenceInType - b.sequenceInType);
  const sceneFramePaths = sceneFrames.map((r) => r.fileUrl as string);
  if (sceneFramePaths.length === 0) {
    await failTask(task.id, "No scene reference images available");
    return;
  }

  // 4. Collect character references
  const projectCharacters = await getEpisodeCharacters(payload.projectId, shot.episodeId);
  const shotCharNames = new Set<string>();
  for (const r of allRefs) {
    for (const n of r.characters ?? []) shotCharNames.add(stripCharHint(n));
  }
  const charRefs = projectCharacters
    .filter((c) => !!c.referenceImage &&
      (shotCharNames.has(stripCharHint(c.name)) || shotCharNames.has((c as any).baseName || "")))
    .map((c) => ({ name: c.name, imagePath: (c as any).frontViewImage || c.referenceImage as string }));

  // 5. Ordered reference images: characters first, then scenes
  const orderedRefImages = [...charRefs.map((c) => c.imagePath), ...sceneFramePaths];

  const ratio = payload.ratio ?? "16:9";
  const videoMaxDuration = getModelMaxDuration(payload.modelConfig?.video?.modelId);
  const effectiveDuration = Math.min(shot.duration ?? 10, videoMaxDuration);

  // 6. Build video prompt
  //    Priority: stored reference prompt > Vision LLM > fallback template
  let videoPrompt: string;
  const storedPrompt = shot.videoPrompt || "";
  const hasRefFormat = storedPrompt.includes("<Picture ") || storedPrompt.includes("<Subject ");

  if (hasRefFormat) {
    // Valid H3 R2V prompt (from ref_video_prompt_generate task)
    videoPrompt = storedPrompt.replace(/^\[R2V-[A-Z]+\] /, "");  // strip source prefix
  } else {
    // No stored reference prompt → Vision LLM with fallback
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
          systemPrompt,
          images: sceneFramePaths,
          temperature: 0.7,
        }),
        60_000,
      );

      // Validate LLM output
      if (!rawPrompt || rawPrompt.trim().length < 10) {
        throw new Error("Vision LLM returned empty/invalid prompt");
      }

      videoPrompt = `Duration: ${effectiveDuration}s.\n\n${rawPrompt.trim()}`;
    } catch (err) {
      console.warn("[RefVideo] Vision LLM failed, using fallback:", err instanceof Error ? err.message : String(err));
      const charRefInfos = charRefs.map((c, i) => ({ name: c.name, index: i + 1 }));
      const sceneFrameInfos = sceneFramePaths.map((_, i) => {
        const name = `场景-${i + 1}`;
        return { label: name, index: charRefs.length + i + 1 };
      });
      const fullMapping = [...charRefInfos.map((c) => `@图片${c.index}是${c.name}`),
        ...sceneFrameInfos.map((s) => `@图片${s.index}是${s.label}`)].join("，") + "。";

      videoPrompt = `图像映射：${fullMapping}。\n\n${buildReferenceVideoPrompt({
        videoScript: shot.videoScript || shot.motionScript || shot.prompt || "",
        cameraDirection: shot.cameraDirection || "static",
        duration: effectiveDuration,
        characters: projectCharacters,
      })}`;
    }
  }

  // 7. Generate video
  await db.update(shots).set({ status: "generating" }).where(eq(shots.id, shot.id));

  const videoProvider = resolveVideoProvider(payload.modelConfig);

  // Image order: all scene frames first, then character refs (matches prompt Picture numbering)
  const allRefImages = [...sceneFramePaths, ...charRefs.map(c => c.imagePath)];
  const result = await videoProvider.generateVideo({
    initialImage: allRefImages[0],
    prompt: videoPrompt,
    duration: effectiveDuration,
    ratio,
    referenceImages: allRefImages.slice(1),
  });

  // 8. Persist
  const videoPath = copyToUploads(result.filePath, 'reference_video');
  await insertAssetVersion({
    shotId: shot.id,
    type: "reference_video",
    sequenceInType: 0,
    prompt: videoPrompt,
    fileUrl: videoPath,
    status: "completed",
  });

  await db.update(shots).set({ status: "completed" }).where(eq(shots.id, shot.id));

  return { shotId: shot.id, referenceVideoUrl: result.filePath };
}

// ─── Helpers ───

function withTimeout<T>(promise: Promise<T>, ms: number): Promise<T> {
  let timer: NodeJS.Timeout;
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(new Error(`Timeout after ${ms}ms`)), ms);
  });
  return Promise.race([promise, timeout]).finally(() => clearTimeout(timer!));
}