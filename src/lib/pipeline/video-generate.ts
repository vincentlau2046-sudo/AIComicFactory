import path from "path";
import { db } from "@/lib/db";
import { shots, characters, storyboardVersions } from "@/lib/db/schema";
import { resolveVideoProvider, resolveAIProvider } from "@/lib/ai/provider-factory";
import type { ModelConfigPayload } from "@/lib/ai/provider-factory";
import { checkVideoQuality } from "./video-quality-check";
import { buildVideoPrompt } from "@/lib/ai/prompts/video-generate";
import { resolveSlotContents } from "@/lib/ai/prompts/resolver";
import { getModelMaxDuration } from "@/lib/ai/model-limits";
import { eq } from "drizzle-orm";
import type { Task } from "@/lib/task-queue";
import { getActiveAsset, insertAssetVersion } from "@/lib/shot-asset-utils";

async function getVersionedUploadDirFromPipeline(versionId: string | null | undefined): Promise<string> {
  if (!versionId) return process.env.UPLOAD_DIR || "./uploads";
  const [version] = await db
    .select({ label: storyboardVersions.label, projectId: storyboardVersions.projectId })
    .from(storyboardVersions)
    .where(eq(storyboardVersions.id, versionId));
  if (!version) return process.env.UPLOAD_DIR || "./uploads";
  return path.join(process.env.UPLOAD_DIR || "./uploads", "projects", version.projectId, version.label);
}

export async function handleVideoGenerate(task: Task) {
  const payload = task.payload as { shotId: string; projectId?: string; userId?: string; ratio?: string; modelConfig?: ModelConfigPayload };

  const [shot] = await db
    .select()
    .from(shots)
    .where(eq(shots.id, payload.shotId));

  if (!shot) throw new Error("Shot not found");

  // Read first/last frame URL from shot_assets
  const firstFrameAsset = await getActiveAsset(payload.shotId, "first_frame", 0);
  const lastFrameAsset = await getActiveAsset(payload.shotId, "last_frame", 0);

  const firstFrameUrl = firstFrameAsset?.fileUrl;
  const lastFrameUrl = lastFrameAsset?.fileUrl;

  if (!firstFrameUrl || !lastFrameUrl) {
    throw new Error("Shot frames not generated yet");
  }

  const projectCharacters = await db
    .select()
    .from(characters)
    .where(eq(characters.projectId, shot.projectId));

  const versionedUploadDir = await getVersionedUploadDirFromPipeline(shot.versionId);
  const videoProvider = resolveVideoProvider(payload.modelConfig, versionedUploadDir);

  const videoModelId = payload.modelConfig?.video?.modelId;
  const modelMaxDuration = getModelMaxDuration(videoModelId);
  const effectiveDuration = Math.min(shot.duration ?? 10, modelMaxDuration);

  const userId = payload.userId ?? "";
  const projectId = payload.projectId ?? shot.projectId;
  const videoSlots = await resolveSlotContents("video_generate", { userId, projectId });

  await db
    .update(shots)
    .set({ status: "generating" })
    .where(eq(shots.id, payload.shotId));

  const videoScript = shot.videoScript || shot.motionScript || shot.prompt || "";
  const prompt = buildVideoPrompt({
    videoScript,
    cameraDirection: shot.cameraDirection || "static",
    startFrameDesc: firstFrameAsset?.prompt ?? undefined,
    endFrameDesc: lastFrameAsset?.prompt ?? undefined,
    duration: effectiveDuration,
    characters: projectCharacters,
    slotContents: videoSlots,
  });

  const result = await videoProvider.generateVideo({
    firstFrame: firstFrameUrl,
    lastFrame: lastFrameUrl,
    prompt,
    duration: effectiveDuration,
    ratio: payload.ratio ?? "16:9",
  });

  // Persist the keyframe video output as a new versioned asset row.
  await insertAssetVersion({
    shotId: payload.shotId,
    type: "keyframe_video",
    sequenceInType: 0,
    prompt,
    fileUrl: result.filePath,
    status: "completed",
  });

  await db
    .update(shots)
    .set({ status: "completed" })
    .where(eq(shots.id, payload.shotId));

  // Best-effort video quality check — does not block or fail generation
  try {
    const textProvider = resolveAIProvider(payload.modelConfig);
    if (textProvider) {
      const qualityResult = await checkVideoQuality(
        textProvider,
        result.filePath,
        firstFrameUrl
      );

      console.log(
        `[VideoQuality] Shot ${payload.shotId}: score=${qualityResult.score}, pass=${qualityResult.pass}`
      );

      if (!qualityResult.pass) {
        console.warn(`[VideoQuality] Issues: ${qualityResult.issues.join(", ")}`);
      }

      return {
        videoPath: result.filePath,
        qualityScore: qualityResult.score,
        qualityIssues: qualityResult.issues,
      };
    }
  } catch (e) {
    console.warn("[VideoQuality] Quality check skipped:", e);
  }

  return { videoPath: result.filePath };
}
