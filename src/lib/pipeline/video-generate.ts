import path from "path";
import { db } from "@/lib/db";
import {
  shots, characters, storyboardVersions,
  episodes, projects, scenes, dialogues, characterCostumes,
} from "@/lib/db/schema";
import { resolveVideoProvider, resolveAIProvider } from "@/lib/ai/provider-factory";
import type { ModelConfigPayload } from "@/lib/ai/provider-factory";
import { checkVideoQuality } from "./video-quality-check";
import { buildVideoPrompt } from "@/lib/ai/prompts/video-generate";
import { resolvePrompt, resolveSlotContents } from "@/lib/ai/prompts/resolver";
import { getModelMaxDuration } from "@/lib/ai/model-limits";
import { eq, inArray } from "drizzle-orm";
import type { Task } from "@/lib/task-queue";
import { getActiveAsset, insertAssetVersion } from "@/lib/shot-asset-utils";
import { getUploadDir } from "@/lib/env";

async function getVersionedUploadDirFromPipeline(versionId: string | null | undefined): Promise<string> {
  if (!versionId) return getUploadDir();
  const [version] = await db
    .select({ label: storyboardVersions.label, projectId: storyboardVersions.projectId })
    .from(storyboardVersions)
    .where(eq(storyboardVersions.id, versionId));
  if (!version) return getUploadDir();
  return path.join(getUploadDir(), "projects", version.projectId, version.label);
}

// ── Shared H3 context assembler (exported for batch path) ──
// Single source of truth for all DB context passed to H3 prompt builder.
// Both single-shot and batch paths call this — no duplicate DB reads.

export interface H3ShotContext {
  shot: typeof shots.$inferSelect;
  firstFrameAsset: Awaited<ReturnType<typeof getActiveAsset>>;
  lastFrameAsset: Awaited<ReturnType<typeof getActiveAsset>>;
  projectCharacters: (typeof characters.$inferSelect)[];
  episode: typeof episodes.$inferSelect | null;
  project: typeof projects.$inferSelect | null;
  enrichedDialogues: Array<{
    characterName: string; text: string; sequence: number;
    startRatio: string; endRatio: string; audioUrl: string | null; offscreen: boolean;
  }>;
  sceneDesc?: string;
  sceneLighting?: string;
  sceneColorPalette?: string;
  costumes: (typeof characterCostumes.$inferSelect)[];
  bgmUrl?: string;
  episodeDesc?: string;
  episodeKeywords?: string;
}

export async function assembleH3ShotContext(shotId: string): Promise<H3ShotContext> {
  const [shot] = await db.select().from(shots).where(eq(shots.id, shotId));
  if (!shot) throw new Error("Shot not found");

  const [firstFrameAsset, lastFrameAsset] = await Promise.all([
    getActiveAsset(shotId, "first_frame", 0),
    getActiveAsset(shotId, "last_frame", 0),
  ]);

  const [projectCharacters, episode, project] = await Promise.all([
    db.select().from(characters).where(eq(characters.projectId, shot.projectId)),
    shot.episodeId
      ? db.select().from(episodes).where(eq(episodes.id, shot.episodeId)).then(r => r[0] ?? null)
      : null,
    db.select().from(projects).where(eq(projects.id, shot.projectId)).then(r => r[0] ?? null),
  ]);

  // Dialogues with character name enrichment
  const shotDialogues = await db.select().from(dialogues).where(eq(dialogues.shotId, shotId));
  const dialogueCharIds = [...new Set(shotDialogues.map(d => d.characterId))];
  const dialogueCharacters = dialogueCharIds.length > 0
    ? await db.select().from(characters).where(inArray(characters.id, dialogueCharIds))
    : [];
  const charMap = new Map(dialogueCharacters.map(c => [c.id, c]));
  const enrichedDialogues = shotDialogues.map(d => ({
    characterName: d.characterId ? (charMap.get(d.characterId)?.name ?? "Unknown") : "Unknown",
    text: d.text,
    sequence: d.sequence,
    startRatio: d.startRatio ?? "0",
    endRatio: d.endRatio ?? "1",
    audioUrl: d.audioUrl,
    offscreen: false,
  })).sort((a, b) => a.sequence - b.sequence);

  // Scene context
  let sceneDesc: string | undefined;
  let sceneLighting: string | undefined;
  let sceneColorPalette: string | undefined;
  if (shot.sceneId) {
    const [scene] = await db.select().from(scenes).where(eq(scenes.id, shot.sceneId));
    sceneDesc = scene?.description || undefined;
    sceneLighting = scene?.lighting || undefined;
    sceneColorPalette = scene?.colorPalette || undefined;
  }

  // Costumes
  const allCharacterIds = [
    ...new Set([
      ...projectCharacters.map(c => c.id),
      ...enrichedDialogues
        .map(d => dialogueCharacters.find(c => c.name === d.characterName)?.id)
        .filter(Boolean) as string[],
    ]),
  ];
  const costumes = allCharacterIds.length > 0
    ? await db.select().from(characterCostumes).where(inArray(characterCostumes.characterId, allCharacterIds))
    : [];

  // Audio
  const bgmUrl: string | undefined = episode?.bgmUrl || project?.bgmUrl || undefined;
  const episodeDesc: string | undefined = episode?.description || undefined;
  const episodeKeywords: string | undefined = episode?.keywords || undefined;

  return {
    shot, firstFrameAsset, lastFrameAsset, projectCharacters,
    episode, project, enrichedDialogues,
    sceneDesc, sceneLighting, sceneColorPalette, costumes,
    bgmUrl, episodeDesc, episodeKeywords,
  };
}

export async function handleVideoGenerate(task: Task) {
  const payload = task.payload as { shotId: string; projectId?: string; userId?: string; ratio?: string; modelConfig?: ModelConfigPayload };

  const ctx = await assembleH3ShotContext(payload.shotId);
  const { shot, firstFrameAsset, lastFrameAsset, projectCharacters, episode, project,
    enrichedDialogues, sceneDesc, sceneLighting, sceneColorPalette, costumes,
    bgmUrl, episodeDesc, episodeKeywords } = ctx;

  const firstFrameUrl = firstFrameAsset?.fileUrl;
  const lastFrameUrl = lastFrameAsset?.fileUrl;
  if (!firstFrameUrl || !lastFrameUrl) throw new Error("Shot frames not generated yet");

  const versionedUploadDir = await getVersionedUploadDirFromPipeline(shot.versionId);
  const videoProvider = resolveVideoProvider(payload.modelConfig, versionedUploadDir);

  const videoModelId = payload.modelConfig?.video?.modelId;
  const modelMaxDuration = getModelMaxDuration(videoModelId);
  const effectiveDuration = Math.min(shot.duration ?? 10, modelMaxDuration);

  const userId = payload.userId ?? "";
  const projectId = payload.projectId ?? shot.projectId;
  const videoSlots = await resolveSlotContents("video_generate", { userId, projectId });

  await db.update(shots).set({ status: "generating" }).where(eq(shots.id, payload.shotId));

  const videoScript = shot.videoScript || shot.motionScript || shot.prompt || "";
  const textProvider = resolveAIProvider(payload.modelConfig);
  const useH3Prompt = process.env.H3_PROMPT_MODE !== "seedance";

  let prompt: string;
  if (useH3Prompt) {
    const { buildVideoPromptLLM: buildH3Builder } = await import("@/lib/ai/prompts/h3");
    const generationMode: "keyframe" | "reference" =
      (episode?.generationMode ?? project?.generationMode ?? "keyframe") as "keyframe" | "reference";

    let h3System: string | undefined;
    if (payload.userId && payload.projectId) {
      h3System = await resolvePrompt("video_h3_prompt", { userId: payload.userId, projectId: payload.projectId }).catch(() => undefined);
    }
    const h3Lang = (process.env.H3_LANGUAGE as "zh" | "en" | undefined) || "auto";

    const h3Output = await buildH3Builder({
      videoScript,
      motionScript: shot.motionScript,
      duration: effectiveDuration,
      cameraDirection: shot.cameraDirection || "static",
      generationMode,
      characters: projectCharacters.map(c => ({
        id: c.id, name: c.name,
        description: c.description, visualHint: c.visualHint,
        referenceImage: c.referenceImage, performanceStyle: c.performanceStyle,
        scope: c.scope, heightCm: c.heightCm, bodyType: c.bodyType,
      })),
      firstFrame: firstFrameAsset.fileUrl ? { fileUrl: firstFrameAsset.fileUrl, prompt: firstFrameAsset.prompt } : undefined,
      lastFrame: lastFrameAsset.fileUrl ? { fileUrl: lastFrameAsset.fileUrl, prompt: lastFrameAsset.prompt } : undefined,
      dialogues: enrichedDialogues,
      sceneDescription: sceneDesc,
      sceneLighting,
      sceneColorPalette,
      soundDesign: shot.soundDesign || undefined,
      musicCue: shot.musicCue || undefined,
      bgmUrl,
      costumes: costumes.map(c => ({ name: c.name, description: c.description, referenceImage: c.referenceImage, characterId: c.characterId })),
      compositionGuide: shot.compositionGuide || undefined,
      episodeDescription: episodeDesc,
      episodeKeywords,
      episodeTitle: episode?.title || undefined,
      projectIdea: project?.idea || undefined,
      projectTitle: project?.title || undefined,
      projectOutline: project?.outline || undefined,
      projectWorldSetting: project?.worldSetting || undefined,
      languageMode: h3Lang,
      slotContents: videoSlots,
    }, textProvider, h3System);
    prompt = h3Output.sections.join("\n\n");
  } else {
    prompt = buildVideoPrompt({
      videoScript,
      cameraDirection: shot.cameraDirection || "static",
      startFrameDesc: firstFrameAsset?.prompt ?? undefined,
      endFrameDesc: lastFrameAsset?.prompt ?? undefined,
      duration: effectiveDuration,
      characters: projectCharacters,
      slotContents: videoSlots,
    });
  }

  const result = await videoProvider.generateVideo({
    firstFrame: firstFrameUrl,
    lastFrame: lastFrameUrl,
    prompt,
    duration: effectiveDuration,
    ratio: payload.ratio ?? "16:9",
  });

  await insertAssetVersion({
    shotId: payload.shotId, type: "keyframe_video", sequenceInType: 0,
    prompt, fileUrl: result.filePath, status: "completed",
  });

  await db.update(shots).set({ status: "completed" }).where(eq(shots.id, payload.shotId));

  try {
    const textProvider = resolveAIProvider(payload.modelConfig);
    if (textProvider) {
      const qualityResult = await checkVideoQuality(textProvider, result.filePath, firstFrameUrl);
      console.log(`[VideoQuality] Shot ${payload.shotId}: score=${qualityResult.score}, pass=${qualityResult.pass}`);
      if (!qualityResult.pass) console.warn(`[VideoQuality] Issues: ${qualityResult.issues.join(", ")}`);
      return { videoPath: result.filePath, qualityScore: qualityResult.score, qualityIssues: qualityResult.issues };
    }
  } catch (e) {
    console.warn("[VideoQuality] Quality check skipped:", e);
  }

  return { videoPath: result.filePath };
}
