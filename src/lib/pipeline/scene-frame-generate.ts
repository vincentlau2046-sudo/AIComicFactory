/**
 * Scene Frame Generate Pipeline Handler (task queue Worker).
 *
 * Generates pure-environment reference images for reference-mode shots.
 * One task = one shot; serial generation of all pending reference frames
 * within that shot via ComfyUI qwen-2512-t2i.
 *
 * Works opposite of frame-generate.ts (which generates per-frame):
 * here we iterate over pending shot_assets(type='reference') and generate each.
 */

import { db } from "@/lib/db";
import { shots } from "@/lib/db/schema";
import { resolveImageProvider } from "@/lib/ai/provider-factory";
import type { ModelConfigPayload } from "@/lib/ai/provider-factory";
import { eq } from "drizzle-orm";
import type { Task } from "@/lib/task-queue";
import { failTask } from "@/lib/task-queue";
import { getActiveAssets, insertAssetVersion, copyToUploads } from "@/lib/shot-asset-utils";
import { ratioToSize } from "@/lib/ai/size";

export async function handleSceneFrameGenerate(task: Task) {
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

  // 2. Idempotency: skip if all reference assets already completed
  const active = await getActiveAssets(payload.shotId, "reference");
  const pending = active.filter((r) => r.status === "pending" && r.prompt?.trim());
  if (pending.length === 0) {
    // All done or nothing to generate
    const alreadyDone = active.filter((r) => r.status === "completed").length;
    return { shotId: shot.id, generated: 0, skipped: alreadyDone, message: "no pending refs" };
  }

  // 3. Generate
  const imageProvider = resolveImageProvider(payload.modelConfig);
  const ratio = payload.ratio ?? "16:9";
  const batchImageOpts = { size: ratioToSize(ratio), aspectRatio: ratio };

  await db.update(shots).set({ status: "generating" }).where(eq(shots.id, shot.id));

  let generated = 0;
  let failed = 0;
  const generatedPaths: string[] = [];

  for (const entry of pending) {
    try {
      const imagePath = await imageProvider.generateImage(entry.prompt, {
        quality: "hd",
        ...batchImageOpts,
      });
      const uploadPath = copyToUploads(imagePath, 'reference');
      await insertAssetVersion({
        shotId: shot.id,
        type: "reference",
        sequenceInType: entry.sequenceInType,
        prompt: entry.prompt,
        fileUrl: uploadPath,
        status: "completed",
        characters: entry.characters ?? undefined,
      });
      generatedPaths.push(uploadPath);
      generated++;
    } catch (err) {
      failed++;
      console.warn(`[SceneFrame] Shot ${shot.sequence}/${entry.sequenceInType}: failed`, err instanceof Error ? err.message : String(err));
    }
  }

  // 4. Status transition
  if (generated === 0) {
    // All failed → task fails, Worker will retry
    await db.update(shots).set({ status: "failed" }).where(eq(shots.id, shot.id));
    throw new Error(`Scene frames for shot ${shot.sequence}: all ${pending.length} failed`);
  }

  // Partial success → shot ready for video generation, note degraded if partial
  if (failed > 0) {
    console.warn(`[SceneFrame] Shot ${shot.sequence}: ${failed}/${pending.length} failed, ${generated} completed (degraded)`);
  }

  await db.update(shots).set({ status: "pending" as any }).where(eq(shots.id, shot.id));

  return {
    shotId: shot.id,
    generated,
    failed,
    total: pending.length,
    degraded: failed > 0,
  };
}