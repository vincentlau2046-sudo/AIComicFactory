import { db } from "@/lib/db";
import { characters, episodeCharacters } from "@/lib/db/schema";
import { eq, and, isNull, inArray } from "drizzle-orm";

/**
 * Get characters relevant to a specific episode.
 *
 * Priority:
 *   1. Linked via episode_characters join table (per-EP instance rows)
 *   2. Direct lookup by episode_id on characters table
 *   3. Fallback to project-level template rows (episode_id = NULL)
 *
 * Without episodeId, returns all project characters.
 */
export async function getEpisodeCharacters(
  projectId: string,
  epId?: string | null
) {
  if (epId) {
    // Priority 1: linked via episode_characters join table
    const linkedIds = await db
      .select({ characterId: episodeCharacters.characterId })
      .from(episodeCharacters)
      .where(eq(episodeCharacters.episodeId, epId));
    if (linkedIds.length > 0) {
      return db
        .select()
        .from(characters)
        .where(
          inArray(
            characters.id,
            linkedIds.map((r) => r.characterId)
          )
        );
    }
    // Priority 2: direct lookup by episode_id on characters table
    const directInstances = await db
      .select()
      .from(characters)
      .where(eq(characters.episodeId, epId));
    if (directInstances.length > 0) {
      return directInstances;
    }
    // Priority 3: fallback to project-level template rows
    return db
      .select()
      .from(characters)
      .where(
        and(
          eq(characters.projectId, projectId),
          isNull(characters.episodeId)
        )
      );
  }
  return db
    .select()
    .from(characters)
    .where(eq(characters.projectId, projectId));
}