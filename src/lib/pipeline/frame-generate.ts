import { db } from "@/lib/db";
import { shots, characters, projects, episodes, characterCostumes } from "@/lib/db/schema";
import { resolveImageProvider } from "@/lib/ai/provider-factory";
import type { ModelConfigPayload } from "@/lib/ai/provider-factory";
import {
  buildFirstFramePrompt,
  buildLastFramePrompt,
} from "@/lib/ai/prompts/frame-generate";
import { resolveSlotContents } from "@/lib/ai/prompts/resolver";
import { eq, and, lt, desc } from "drizzle-orm";
import type { Task } from "@/lib/task-queue";
import { getActiveAsset, insertAssetVersion, patchAsset, copyToUploads } from "@/lib/shot-asset-utils";
import { ratioToSize } from "@/lib/ai/size";

export async function handleFrameGenerate(task: Task) {
  const payload = task.payload as {
    shotId: string;
    projectId: string;
    userId?: string;
    modelConfig?: ModelConfigPayload;
    ratio?: string;
  };
  const frameSize = ratioToSize(payload.ratio);

  const [shot] = await db
    .select()
    .from(shots)
    .where(eq(shots.id, payload.shotId));

  if (!shot) throw new Error("Shot not found");

  const projectCharacters = await db
    .select()
    .from(characters)
    .where(eq(characters.projectId, payload.projectId));

  // Parse costume overrides from shot
  const rawCostumeOverrides = shot.costumeOverrides as string | null | undefined;
  const costumeOverrides: Record<string, string> = rawCostumeOverrides && rawCostumeOverrides.trim()
    ? JSON.parse(rawCostumeOverrides)
    : {};

  // Build character descriptions, applying costume overrides when present
  const characterDescParts: string[] = [];
  for (const c of projectCharacters) {
    let description = c.description;
    const costumeId = costumeOverrides[c.id];
    if (costumeId) {
      const [costume] = await db
        .select()
        .from(characterCostumes)
        .where(eq(characterCostumes.id, costumeId));
      if (costume?.description) {
        description = `${c.description}. Current outfit: ${costume.description}`;
      }
    }
    let desc = `${c.name}: ${description}`;
    if (c.performanceStyle) {
      desc += ` [Performance: ${c.performanceStyle}]`;
    }
    characterDescParts.push(desc);
  }
  const characterDescriptions = characterDescParts.join("\n");

  const [previousShot] = await db
    .select()
    .from(shots)
    .where(
      and(
        eq(shots.projectId, payload.projectId),
        lt(shots.sequence, shot.sequence)
      )
    )
    .orderBy(desc(shots.sequence))
    .limit(1);

  const ai = resolveImageProvider(payload.modelConfig);

  const userId = payload.userId ?? "";
  const projectId = payload.projectId;
  const frameFirstSlots = await resolveSlotContents("frame_generate_first", { userId, projectId });
  const frameLastSlots = await resolveSlotContents("frame_generate_last", { userId, projectId });

  // Fetch color palette from project (or episode)
  let colorPalette = "";
  if (shot.episodeId) {
    const [episode] = await db.select().from(episodes).where(eq(episodes.id, shot.episodeId));
    if (episode?.colorPalette) colorPalette = episode.colorPalette;
  }
  if (!colorPalette) {
    const [project] = await db.select().from(projects).where(eq(projects.id, payload.projectId));
    if (project?.colorPalette) colorPalette = project.colorPalette;
  }

  // Build composition suffix
  let compositionSuffix = "";
  if (shot.compositionGuide) {
    compositionSuffix += `, ${shot.compositionGuide.replace(/_/g, " ")} composition`;
  }
  if (shot.focalPoint) {
    compositionSuffix += `, focus on ${shot.focalPoint}`;
  }
  if (shot.depthOfField === "shallow") {
    compositionSuffix += `, shallow depth of field, bokeh background`;
  } else if (shot.depthOfField === "deep") {
    compositionSuffix += `, deep focus, everything sharp`;
  }
  if (colorPalette) {
    compositionSuffix += `\n\nGLOBAL COLOR PALETTE (mandatory): ${colorPalette}. All frames must adhere to this color scheme.`;
  }

  // Build character height context for multi-character shots
  const shotPrompt = shot.prompt || "";
  const charsInPrompt = projectCharacters.filter(c => shotPrompt.includes(c.name));
  if (charsInPrompt.length > 1) {
    const heightInfo = charsInPrompt
      .filter(c => c.heightCm && c.heightCm > 0)
      .sort((a, b) => (b.heightCm || 170) - (a.heightCm || 170))
      .map(c => `${c.name}: ${c.heightCm}cm (${c.bodyType || "average"})`)
      .join(", ");
    if (heightInfo) {
      compositionSuffix += `. Character heights: ${heightInfo}. Maintain correct relative proportions`;
    }
  }

  await db
    .update(shots)
    .set({ status: "generating" })
    .where(eq(shots.id, payload.shotId));

  // Read first/last frame ASSET PROMPTS from the unified shot_assets table.
  // These were generated independently by `shot_keyframe_assets_generate`.
  // Fall back to legacy startFrameDesc/endFrameDesc if no asset rows exist (back-compat).
  const firstFrameAsset = await getActiveAsset(payload.shotId, "first_frame", 0);
  const lastFrameAsset = await getActiveAsset(payload.shotId, "last_frame", 0);

  const startFrameDescText = firstFrameAsset?.prompt || shot.prompt || "";
  const endFrameDescText = lastFrameAsset?.prompt || shot.prompt || "";

  // Pick character refs to attach as visual anchors. Prefer characters listed
  // on the asset row; fall back to first 3 chars with reference images.
  const charsWithRefs = projectCharacters.filter((c) => !!c.referenceImage);
  const storedCharNames: string[] =
    firstFrameAsset?.characters && firstFrameAsset.characters.length > 0
      ? firstFrameAsset.characters
      : [];

  const relevantChars =
    storedCharNames.length > 0
      ? charsWithRefs.filter((c) => storedCharNames.includes(c.name))
      : charsWithRefs.slice(0, 3);
  const charRefImages = relevantChars.map((c) => c.referenceImage as string);

  console.log(`[FrameGenerate] Shot ${shot.sequence}: using ${relevantChars.length} chars: ${relevantChars.map(c => c.name).join(", ") || "fallback"}`);

  // Mark assets as generating
  if (firstFrameAsset) await patchAsset(firstFrameAsset.id, { status: "generating" });
  if (lastFrameAsset) await patchAsset(lastFrameAsset.id, { status: "generating" });

  // For visual continuity, look up the previous shot's last_frame asset.
  const prevLastFrameUrl = previousShot
    ? (await getActiveAsset(previousShot.id, "last_frame", 0))?.fileUrl ?? undefined
    : undefined;

  // ─── Generate frames ───────────────────────────────────
  let firstFramePath: string;
  let lastFramePath: string;

  try {
    if (charRefImages.length === 0) {
      // No character refs — fallback to atomic T2I (pipeline requires refs)
      let firstFramePrompt = buildFirstFramePrompt({
        sceneDescription: shot.prompt || "",
        startFrameDesc: startFrameDescText,
        characterDescriptions,
        previousLastFrame: prevLastFrameUrl ?? undefined,
        slotContents: frameFirstSlots,
      });
      if (compositionSuffix) firstFramePrompt += compositionSuffix;
      firstFramePath = await ai.generateImage(firstFramePrompt, { quality: "hd", size: frameSize });

      let lastFramePrompt = buildLastFramePrompt({
        sceneDescription: shot.prompt || "",
        endFrameDesc: endFrameDescText,
        characterDescriptions,
        firstFramePath,
        slotContents: frameLastSlots,
      });
      if (compositionSuffix) lastFramePrompt += compositionSuffix;
      lastFramePath = await ai.generateImage(lastFramePrompt, {
        quality: "hd",
        size: frameSize,
        referenceImages: [firstFramePath],
      });
    } else {
      // Pipeline mode: single orchestrated call generates both frames
      let firstFramePrompt = buildFirstFramePrompt({
        sceneDescription: shot.prompt || "",
        startFrameDesc: startFrameDescText,
        characterDescriptions,
        previousLastFrame: prevLastFrameUrl ?? undefined,
        slotContents: frameFirstSlots,
      });
      if (compositionSuffix) firstFramePrompt += compositionSuffix;

      let lastFramePrompt = buildLastFramePrompt({
        sceneDescription: shot.prompt || "",
        endFrameDesc: endFrameDescText,
        characterDescriptions,
        firstFramePath: "",  // not needed — pipeline passes first frame as image
        slotContents: frameLastSlots,
      });
      if (compositionSuffix) lastFramePrompt += compositionSuffix;

      const scenePrompt = relevantChars.length > 0
        ? `A scene with ${relevantChars[0].name}`
        : "A scene with characters";

      lastFramePath = await ai.generateImage(lastFramePrompt, {
        quality: "hd",
        size: frameSize,
        referenceImages: charRefImages,
        pipeline: "frame-generate",
        pipelineParams: {
          first_prompt: firstFramePrompt,
          last_prompt: lastFramePrompt,
          scene_prompt: scenePrompt,
          seed: shot.sequence,
        },
      });

      // Extract first frame from pipeline intermediates
      const pipelineResult = 'lastPipelineResult' in ai
        ? (ai as any).lastPipelineResult
        : undefined;
      firstFramePath = pipelineResult?.intermediates?.gen_first_frame;
      if (!firstFramePath) {
        throw new Error(`Pipeline produced no first frame intermediate: gen_first_frame not found in pipeline result`);
      }

      // Copy to uploads for browser serving
      firstFramePath = copyToUploads(firstFramePath, 'first_frame');
      lastFramePath = copyToUploads(lastFramePath, 'last_frame');
    }
  } catch (err) {
    await db.update(shots).set({ status: "failed" }).where(eq(shots.id, payload.shotId));
    throw err;
  }

  // Patch asset rows with the resulting file URLs (or insert if they didn't
  // exist yet — happens for shots whose keyframe asset prompts haven't been
  // generated by the LLM step).
  if (firstFrameAsset) {
    await patchAsset(firstFrameAsset.id, {
      fileUrl: firstFramePath,
      status: "completed",
    });
  } else {
    await insertAssetVersion({
      shotId: payload.shotId,
      type: "first_frame",
      sequenceInType: 0,
      prompt: startFrameDescText,
      fileUrl: firstFramePath,
      status: "completed",
      characters: relevantChars.map((c) => c.name),
    });
  }
  if (lastFrameAsset) {
    await patchAsset(lastFrameAsset.id, {
      fileUrl: lastFramePath,
      status: "completed",
    });
  } else {
    await insertAssetVersion({
      shotId: payload.shotId,
      type: "last_frame",
      sequenceInType: 0,
      prompt: endFrameDescText,
      fileUrl: lastFramePath,
      status: "completed",
      characters: relevantChars.map((c) => c.name),
    });
  }

  await db
    .update(shots)
    .set({ status: "completed" })
    .where(eq(shots.id, payload.shotId));

  return { firstFrame: firstFramePath, lastFrame: lastFramePath };
}
