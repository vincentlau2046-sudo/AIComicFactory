import { db } from "@/lib/db";
import { shots, projects, episodes, characterCostumes } from "@/lib/db/schema";
import { resolveImageProvider } from "@/lib/ai/provider-factory";
import type { ModelConfigPayload } from "@/lib/ai/provider-factory";
import {
  buildFirstFramePrompt,
  buildLastFramePrompt,
} from "@/lib/ai/prompts/frame-generate";
import { resolveSlotContents } from "@/lib/ai/prompts/resolver";
import { eq, and, lt, desc } from "drizzle-orm";
import type { Task } from "@/lib/task-queue";
import { getActiveAsset, getLatestCompletedAsset, insertAssetVersion, patchAsset, copyToUploads, stripCharHint, buildCharMap, resolveFrameCharacters } from "@/lib/shot-asset-utils";
import { getEpisodeCharacters } from "@/lib/db/episode-characters";
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

  const projectCharacters = await getEpisodeCharacters(payload.projectId, shot.episodeId);

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
  // Use latest completed asset regardless of is_active — every shot has valid prompts.
  const firstFrameAsset = await getActiveAsset(payload.shotId, "first_frame", 0)
    || await getLatestCompletedAsset(payload.shotId, "first_frame");
  const lastFrameAsset = await getActiveAsset(payload.shotId, "last_frame", 0)
    || await getLatestCompletedAsset(payload.shotId, "last_frame");

  if (!firstFrameAsset?.prompt) {
    throw new Error(`Shot ${shot.sequence}: missing first_frame keyframe prompt. Run keyframe prompt generation first.`);
  }
  if (!lastFrameAsset?.prompt) {
    throw new Error(`Shot ${shot.sequence}: missing last_frame keyframe prompt. Run keyframe prompt generation first.`);
  }

  const startFrameDescText = firstFrameAsset.prompt;
  const endFrameDescText = lastFrameAsset.prompt;

  // Pick character refs to attach as visual anchors. Per-frame: each frame
  // has its own cast — don't merge.
  const charsWithRefs = projectCharacters.filter((c) => !!c.referenceImage);
  const charMap = buildCharMap(charsWithRefs);

  const ffChars = resolveFrameCharacters(firstFrameAsset, charMap);
  const lfChars = resolveFrameCharacters(lastFrameAsset, charMap);
  const ffCharRefImages = ffChars.map((c) => c.referenceImage!);
  const ffCharRefLabels = ffChars.map((c) => (c as any).baseName || stripCharHint(c.name));
  const lfCharRefImages = lfChars.map((c) => c.referenceImage!);
  const lfCharRefLabels = lfChars.map((c) => (c as any).baseName || stripCharHint(c.name));

  console.log(`[FrameGen] Shot ${shot.sequence} FF: chars=${JSON.stringify(firstFrameAsset?.characters)} labels=${JSON.stringify(ffCharRefLabels)} refs=${JSON.stringify(ffCharRefImages.map(p => p.substring(p.lastIndexOf('/')+1)))}`);
  console.log(`[FrameGen] Shot ${shot.sequence} LF: chars=${JSON.stringify(lastFrameAsset?.characters)} labels=${JSON.stringify(lfCharRefLabels)} refs=${JSON.stringify(lfCharRefImages.map(p => p.substring(p.lastIndexOf('/')+1)))}`);

  // Character descriptions are redundant with reference images — the four-view
  // sheets already convey all visual identity info. Set to empty to avoid
  // double-text conditioning that can confuse diffusion models.
  const shotCharacterDescriptions = "";

  console.log(`[FrameGenerate-v2] Shot ${shot.sequence}: ff=${ffChars.length} chars (${ffChars.map(c => c.name).join(", ") || "none"}), lf=${lfChars.length} chars (${lfChars.map(c => c.name).join(", ") || "none"})`);

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
    // Build prompts once — then dispatch to appropriate workflow per frame
    let firstFramePrompt = buildFirstFramePrompt({
      sceneDescription: shot.prompt || "",
      startFrameDesc: startFrameDescText,
      characterDescriptions: shotCharacterDescriptions,
      previousLastFrame: prevLastFrameUrl ?? undefined,
      slotContents: frameFirstSlots,
    });
    if (compositionSuffix) firstFramePrompt += compositionSuffix;

    let lastFramePrompt = buildLastFramePrompt({
      sceneDescription: shot.prompt || "",
      endFrameDesc: endFrameDescText,
      characterDescriptions: shotCharacterDescriptions,
      firstFramePath: "",
      slotContents: frameLastSlots,
    });
    if (compositionSuffix) lastFramePrompt += compositionSuffix;

    // First frame: generate + persist immediately
    if (ffCharRefImages.length === 0) {
      firstFramePath = await ai.generateImage(firstFramePrompt, { quality: "hd", size: frameSize });
    } else {
      firstFramePath = await ai.generateImage(firstFramePrompt, {
        quality: "hd",
        size: frameSize,
        referenceImages: ffCharRefImages,
        referenceLabels: ffCharRefLabels,
        scenePrompt: shot.prompt || "",
      });
    }
    firstFramePath = copyToUploads(firstFramePath, 'first_frame');

    if (firstFrameAsset) {
      await patchAsset(firstFrameAsset.id, { fileUrl: firstFramePath, status: "completed" });
    } else {
      await insertAssetVersion({
        shotId: payload.shotId,
        type: "first_frame",
        sequenceInType: 0,
        prompt: startFrameDescText,
        fileUrl: firstFramePath,
        status: "completed",
        characters: ffChars.map((c: any) => c.name),
      });
    }

    // Last frame: generate + persist immediately
    if (lfCharRefImages.length === 0) {
      lastFramePath = await ai.generateImage(lastFramePrompt, { quality: "hd", size: frameSize });
    } else {
      lastFramePath = await ai.generateImage(lastFramePrompt, {
        quality: "hd",
        size: frameSize,
        referenceImages: lfCharRefImages,
        referenceLabels: lfCharRefLabels,
        scenePrompt: shot.prompt || "",
      });
    }
    lastFramePath = copyToUploads(lastFramePath, 'last_frame');

    if (lastFrameAsset) {
      await patchAsset(lastFrameAsset.id, { fileUrl: lastFramePath, status: "completed" });
    } else {
      await insertAssetVersion({
        shotId: payload.shotId,
        type: "last_frame",
        sequenceInType: 0,
        prompt: endFrameDescText,
        fileUrl: lastFramePath,
        status: "completed",
        characters: lfChars.map((c: any) => c.baseName || stripCharHint(c.name)),
      });
    }
  } catch (err) {
    await db.update(shots).set({ status: "failed" }).where(eq(shots.id, payload.shotId));
    throw err;
  }

  await db
    .update(shots)
    .set({ status: "completed" })
    .where(eq(shots.id, payload.shotId));

  return { firstFrame: firstFramePath, lastFrame: lastFramePath };
}
