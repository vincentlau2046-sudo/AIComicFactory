import { db } from "@/lib/db";
import { characters, episodeCharacters } from "@/lib/db/schema";
import { eq, and, isNull, inArray } from "drizzle-orm";

export async function getEpisodeCharacters(projectId: string, epId?: string | null) {
  if (epId) {
    const linkedIds = await db.select({ characterId: episodeCharacters.characterId }).from(episodeCharacters).where(eq(episodeCharacters.episodeId, epId));
    if (linkedIds.length > 0) return db.select().from(characters).where(inArray(characters.id, linkedIds.map(r => r.characterId)));
    const direct = await db.select().from(characters).where(eq(characters.episodeId, epId));
    if (direct.length > 0) return direct;
    return db.select().from(characters).where(and(eq(characters.projectId, projectId), isNull(characters.episodeId)));
  }
  return db.select().from(characters).where(eq(characters.projectId, projectId));
}