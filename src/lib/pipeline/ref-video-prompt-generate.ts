/**
 * Reference Video Prompt Generate Pipeline Handler (v0.3.9).
 *
 * Generates a H3 R2V 6-section video prompt via Vision LLM.
 * Tier 1: gemma4-31b-vl (or any VL model) with scene frame images.
 * Tier 2: buildR2VPrompt local heuristics (no images, fallback).
 *
 * Output: shot.videoPrompt with [R2V-VL] or [R2V-LOCAL] prefix.
 */

import { db } from "@/lib/db";
import { shots } from "@/lib/db/schema";
import { resolveAIProvider } from "@/lib/ai/provider-factory";
import type { ModelConfigPayload } from "@/lib/ai/provider-factory";
import { getActiveAssets } from "@/lib/shot-asset-utils";
import { getEpisodeCharacters } from "@/lib/db/episode-characters";
import { buildH3Input } from "@/lib/ai/prompts/h3";
import { buildR2VPromptLLM } from "@/lib/ai/prompts/h3/r2v/builder";
import { buildR2VPrompt } from "@/lib/ai/prompts/h3/r2v/ref-builder";
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

  // 1. Load shot
  const [shot] = await db.select().from(shots).where(eq(shots.id, payload.shotId));
  if (!shot) { await failTask(task.id, "Shot not found"); return; }

  // 2. Collect scene frames
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

  // 3. Build H3PromptInput (same struct as FL2V)
  const projectCharacters = await getEpisodeCharacters(payload.projectId, shot.episodeId);
  const charactersForH3 = projectCharacters.map(c => ({
    id: c.id, name: c.name,
    description: c.description ?? undefined,
    visualHint: c.visualHint ?? undefined,
    referenceImage: c.referenceImage ?? undefined,
    performanceStyle: c.performanceStyle ?? undefined,
    scope: (c.scope as "main" | "guest") || "main",
    heightCm: c.heightCm ?? undefined,
    bodyType: c.bodyType ?? undefined,
  }));

  const h3Input = {
    videoScript: shot.videoScript || shot.motionScript || shot.prompt || "",
    motionScript: shot.motionScript,
    duration: shot.duration ?? 10,
    cameraDirection: shot.cameraDirection || "static",
    generationMode: "reference" as const,
    characters: charactersForH3,
    languageMode: "zh" as const,
    // Scene frames as firstFrame/lastFrame for H3 context
    firstFrame: sceneFrames[0] ? { fileUrl: sceneFrames[0].fileUrl!, prompt: sceneFrames[0].prompt } : undefined,
    lastFrame: sceneFrames[sceneFrames.length - 1] ? { fileUrl: sceneFrames[sceneFrames.length - 1].fileUrl!, prompt: sceneFrames[sceneFrames.length - 1].prompt } : undefined,
  };

  // 4. Try Vision LLM, fallback to local
  const visionProvider = resolveAIProvider(payload.modelConfig);

  let sections: string[];
  let source: "vl" | "fallback";

  try {
    const result = await buildR2VPromptLLM(h3Input, visionProvider, sceneFramePaths);
    sections = result.output.sections;
    source = result.source;
  } catch (err) {
    // Final fallback: pure local
    console.warn(`[RefVideoPrompt] VL+fallback failed, using pure local: ${err}`);
    const local = buildR2VPrompt(h3Input);
    sections = local.sections;
    source = "fallback";
  }

  // 5. Store with source prefix
  const prefix = source === "vl" ? "[R2V-VL] " : "[R2V-LOCAL] ";
  const promptText = prefix + sections.join("\n\n");

  await db.update(shots).set({ videoPrompt: promptText }).where(eq(shots.id, shot.id));

  return { shotId: shot.id, source, sections };
}