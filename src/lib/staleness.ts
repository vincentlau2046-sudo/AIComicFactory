import { db } from "@/lib/db";
import { shots, characters } from "@/lib/db/schema";
import { eq } from "drizzle-orm";
import { createHash } from "crypto";

export function hashScript(script: string): string {
  return createHash("sha256").update(script || "").digest("hex").slice(0, 16);
}

/**
 * Mark downstream assets as stale when script changes.
 */
export async function markDownstreamStale(
  entityType: "episode" | "project",
  entityId: string
): Promise<void> {
  if (entityType === "episode") {
    await db
      .update(shots)
      .set({ isStale: 1 })
      .where(eq(shots.episodeId, entityId));
    await db
      .update(characters)
      .set({ isStale: 1 })
      .where(eq(characters.episodeId, entityId));
  } else {
    await db
      .update(shots)
      .set({ isStale: 1 })
      .where(eq(shots.projectId, entityId));
    await db
      .update(characters)
      .set({ isStale: 1 })
      .where(eq(characters.projectId, entityId));
  }
}

/**
 * Clear stale flag after regeneration.
 */
export async function clearStale(
  table: "shots" | "characters",
  id: string
): Promise<void> {
  const target = table === "shots" ? shots : characters;
  await db
    .update(target)
    .set({ isStale: 0 })
    .where(eq(target.id, id));
}
