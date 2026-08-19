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
import { eq, inArray, asc, and } from "drizzle-orm";
import type { Task } from "@/lib/task-queue";
import { getActiveAsset, insertAssetVersion, stripCharHint } from "@/lib/shot-asset-utils";
import { getEpisodeCharacters } from "@/lib/db/episode-characters";
import { getUploadDir } from "@/lib/env";

// ── Voice Line utilities ───────────────────────────────

interface VoiceLine {
  text: string;
  type: "narration" | "inner_monologue";
  character?: string;
  timeHint?: string;
}

function parseVoiceField(raw: string | null | undefined): VoiceLine[] {
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function detectLanguageQuick(text: string): string {
  const chineseChars = text.match(/[\u4e00-\u9fff]/g);
  return chineseChars && chineseChars.length > text.length * 0.1 ? "Chinese" : "English";
}

function voiceLinesToH3(lines: VoiceLine[]): string[] {
  return lines.map(v => {
    const lang = detectLanguageQuick(v.text);
    if (v.type === "narration") {
      return `Narrator (S0) says in an off-screen voiceover: <d>[${lang}] ${v.text}</d> while the narrator's lips remain completely closed.`;
    }
    const name = v.character || "Unknown";
    return `${name} says in an off-screen voiceover: <d>[${lang}] ${v.text}</d> while his lips remain completely closed.`;
  });
}

async function getVersionedUploadDirFromPipeline(versionId: string | null | undefined): Promise<string> {
  if (!versionId) return getUploadDir();
  const [version] = await db
    .select({ label: storyboardVersions.label, projectId: storyboardVersions.projectId })
    .from(storyboardVersions)
    .where(eq(storyboardVersions.id, versionId));
  if (!version) return getUploadDir();
  return path.join(getUploadDir(), "projects", version.projectId, version.label);
}

/** Build project-level story arc from all episode titles + descriptions. */
function buildEpisodeOutline(
  episodes: Array<{ title: string; description: string | null }>
): string | undefined {
  if (!episodes.length) return undefined;
  return episodes
    .map((ep, i) => `EP${i + 1}. ${ep.title}：${ep.description || ""}`)
    .join("\n");
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

  // Idempotency: skip if a completed video already exists for this shot
  const existingVideo = await getActiveAsset(payload.shotId, "keyframe_video", 0);
  if (existingVideo?.status === "completed" && existingVideo.fileUrl) {
    await db.update(shots).set({ status: "completed" }).where(eq(shots.id, payload.shotId));
    return { videoPath: existingVideo.fileUrl, skipped: true };
  }

  const projectCharacters = await getEpisodeCharacters(payload.projectId ?? shot.projectId, shot.episodeId);

  // Filter to only characters present in the frames
  const parseCharList = (raw: unknown): string[] => {
    if (!raw) return [];
    if (Array.isArray(raw)) return raw.map(String);
    if (typeof raw === 'string') {
      try { const p = JSON.parse(raw); return Array.isArray(p) ? p.map(String) : []; } catch { return []; }
    }
    return [];
  };
  const ffChars = parseCharList(firstFrameAsset?.characters);
  const lfChars = parseCharList(lastFrameAsset?.characters);
  const frameCharNames = [...new Set([...ffChars, ...lfChars])];
  const frameCharacters = frameCharNames.length > 0
    ? projectCharacters.filter(c =>
        frameCharNames.some(n =>
          c.baseName === n || stripCharHint(c.name) === n
        )
      )
    : projectCharacters;

  // ─── Read context tables (v0.2.0: H3 prompt enrichment) ───

  // Episode metadata
  let episode: typeof episodes.$inferSelect | null = null;
  if (shot.episodeId) {
    [episode] = await db.select().from(episodes).where(eq(episodes.id, shot.episodeId));
  }

  // Project metadata
  const [project] = await db.select().from(projects).where(eq(projects.id, shot.projectId));

  // All episodes for project-level story arc (used as outline fallback)
  const allEpisodes = await db
    .select({ title: episodes.title, description: episodes.description })
    .from(episodes)
    .where(eq(episodes.projectId, shot.projectId))
    .orderBy(asc(episodes.sequence));

  // Dialogues with character enrichment
  const shotDialogues = await db
    .select()
    .from(dialogues)
    .where(eq(dialogues.shotId, payload.shotId));
  const dialogueCharIds = [...new Set(shotDialogues.map(d => d.characterId))];
  const dialogueCharacters = dialogueCharIds.length > 0
    ? await db.select().from(characters).where(inArray(characters.id, dialogueCharIds))
    : [];
  const charMap = new Map(dialogueCharacters.map(c => [c.id, c]));
  const enrichedDialogues = shotDialogues.map(d => ({
    characterName: d.characterId
      ? (charMap.get(d.characterId)?.name ?? "Unknown")
      : "Unknown",
    text: d.text,
    sequence: d.sequence,
    startRatio: d.startRatio ?? "0",
    endRatio: d.endRatio ?? "1",
    audioUrl: d.audioUrl,
    offscreen: false,
  })).sort((a, b) => a.sequence - b.sequence);

  // Scene context (by shot.sceneId FK)
  let sceneDesc: string | undefined;
  let sceneLighting: string | undefined;
  let sceneColorPalette: string | undefined;
  if (shot.sceneId) {
    const [scene] = await db.select().from(scenes).where(eq(scenes.id, shot.sceneId));
    sceneDesc = scene?.description || undefined;
    sceneLighting = scene?.lighting || undefined;
    sceneColorPalette = scene?.colorPalette || undefined;
  }

  // Character costumes
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

  // Audio reference: BGM URL from episode > project
  const bgmUrl: string | undefined = episode?.bgmUrl || project?.bgmUrl || undefined;
  const episodeDesc: string | undefined = episode?.description || undefined;
  const episodeKeywords: string | undefined = episode?.keywords || undefined;

  // ─── End context reads ───

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
  const textProvider = resolveAIProvider(payload.modelConfig);
  const useH3Prompt = process.env.H3_PROMPT_MODE !== "seedance"; // H3 is default, set seedance to opt out

  let prompt: string;
  if (useH3Prompt) {
    // v0.2.0: H3 structured prompt (based on official MiniMax VIDEO_PROMPT_WRITING_GUIDE)
    const { buildVideoPromptLLM: buildH3Builder, buildH3Input } = await import("@/lib/ai/prompts/h3");
    const generationMode: "keyframe" | "reference" =
      (episode?.generationMode ?? project?.generationMode ?? "keyframe") as "keyframe" | "reference";

    // Resolve H3 guide prompt from registry if userId/projectId available
    let h3System: string | undefined;
    if (payload.userId && payload.projectId) {
      h3System = await resolvePrompt("video_h3_prompt", { userId: payload.userId, projectId: payload.projectId }).catch(() => undefined);
    }
    const h3Lang = (process.env.H3_LANGUAGE as "zh" | "en" | undefined) || "auto";

  // Build episode structure (story outline + shot list)
  const allEpShots = (shot.episodeId && shot.versionId)
    ? await db.select().from(shots)
        .where(and(eq(shots.episodeId, shot.episodeId!), eq(shots.versionId, shot.versionId!)))
        .orderBy(asc(shots.sequence))
    : [];
  const epOutline = episode?.outline || '';
  const shotList = allEpShots.map(s => {
    const marker = s.id === shot.id ? '▶' : ' ';
    const scene = (s.prompt || '').replace(/\n/g, ' ');
    const act = (s.videoScript || '').replace(/\d+-\d+s[:\uff1a]\s*/g, '').replace(/\n/g, ' ');
    return `${marker} Shot ${s.sequence}: ${scene} \u2014 ${act}`;
  }).join('\n');
  const episodeStructure = epOutline
    ? `\u672c\u5267\u96c6\u5171 ${allEpShots.length} \u4e2a\u955c\u5934\u3002\u25b6 \u6807\u8bb0\u4e3a\u5f53\u524d\u6b63\u5728\u5904\u7406\u7684\u955c\u5934\uff1a\n\n${shotList}`
    : shotList;


    const h3Input = await buildH3Input({
      userId, projectId,
      shot,
      shotCharacters: frameCharacters,
      firstFrame: firstFrameAsset.fileUrl ? { fileUrl: firstFrameAsset.fileUrl, prompt: firstFrameAsset.prompt } : undefined,
      lastFrame: lastFrameAsset.fileUrl ? { fileUrl: lastFrameAsset.fileUrl, prompt: lastFrameAsset.prompt } : undefined,
      extraFields: {
        bgmUrl,
        costumes: costumes.map(c => ({
          name: c.name, description: c.description,
          referenceImage: c.referenceImage, characterId: c.characterId,
        })),
        episodeDescription: episodeStructure || episodeDesc,
        episodeTitle: episode?.title || undefined,
        episodeKeywords,
        projectIdea: project?.idea || undefined,
        projectTitle: project?.title || undefined,
        projectOutline: project?.outline || buildEpisodeOutline(allEpisodes),
        projectWorldSetting: project?.worldSetting || undefined,
        languageMode: h3Lang,
        slotContents: videoSlots,
      },
    });
    const keyframeImages: string[] = [];
    if (firstFrameAsset.fileUrl) keyframeImages.push(firstFrameAsset.fileUrl);
    if (lastFrameAsset.fileUrl) keyframeImages.push(lastFrameAsset.fileUrl);
    const h3Output = await buildH3Builder(h3Input, textProvider, h3System, keyframeImages.length > 0 ? keyframeImages : undefined);
    prompt = h3Output.sections.join("\n\n");
  } else {
    // Legacy path: Seedance-style prompt (unchanged from v0.1.x)
    prompt = buildVideoPrompt({
      videoScript,
      cameraDirection: shot.cameraDirection || "static",
      startFrameDesc: firstFrameAsset?.prompt ?? undefined,
      endFrameDesc: lastFrameAsset?.prompt ?? undefined,
      duration: effectiveDuration,
      characters: frameCharacters.length > 0 ? frameCharacters : projectCharacters,
      slotContents: videoSlots,
    });
  }

  let videoPath: string;
  try {
    const result = await videoProvider.generateVideo({
      firstFrame: firstFrameUrl,
      lastFrame: lastFrameUrl,
      prompt,
      duration: effectiveDuration,
      ratio: payload.ratio ?? "16:9",
    });
    videoPath = result.filePath;

    // Persist the keyframe video output as a new versioned asset row.
    await insertAssetVersion({
      shotId: payload.shotId,
      type: "keyframe_video",
      sequenceInType: 0,
      prompt,
      fileUrl: videoPath,
      status: "completed",
    });

    await db
      .update(shots)
      .set({ status: "completed" })
      .where(eq(shots.id, payload.shotId));
  } catch (err) {
    await db.update(shots).set({ status: "failed" }).where(eq(shots.id, payload.shotId));
    throw err;
  }

  // Best-effort video quality check — does not block or fail generation
  try {
    const textProvider = resolveAIProvider(payload.modelConfig);
    if (textProvider) {
      const qualityResult = await checkVideoQuality(
        textProvider,
        videoPath,
        firstFrameUrl
      );

      console.log(
        `[VideoQuality] Shot ${payload.shotId}: score=${qualityResult.score}, pass=${qualityResult.pass}`
      );

      if (!qualityResult.pass) {
        console.warn(`[VideoQuality] Issues: ${qualityResult.issues.join(", ")}`);
      }

      return {
        videoPath: videoPath,
        qualityScore: qualityResult.score,
        qualityIssues: qualityResult.issues,
      };
    }
  } catch (e) {
    console.warn("[VideoQuality] Quality check skipped:", e);
  }

  return { videoPath: videoPath };
}
