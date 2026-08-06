import { db } from "@/lib/db";
import { characters, characterRelations } from "@/lib/db/schema";
import { resolveAIProvider } from "@/lib/ai/provider-factory";
import type { ModelConfigPayload } from "@/lib/ai/provider-factory";
import { buildCharacterExtractPrompt } from "@/lib/ai/prompts/character-extract";
import { resolvePrompt } from "@/lib/ai/prompts/resolver";
import { and, eq } from "drizzle-orm";
import { id as genId } from "@/lib/id";
import type { Task } from "@/lib/task-queue";

interface ExtractedChar {
  name: string;
  description: string;
  visualHint?: string;
  heightCm?: number;
  bodyType?: string;
  performanceStyle?: string;
}

interface ExtractedRelation {
  characterA: string;
  characterB: string;
  relationType: string;
  description?: string;
}

export async function handleCharacterExtract(task: Task) {
  const payload = task.payload as {
    projectId: string;
    screenplay: string;
    modelConfig?: ModelConfigPayload;
    episodeId?: string;
    userId?: string;
  };

  const systemPrompt = await resolvePrompt("character_extract", {
    userId: payload.userId ?? "",
    projectId: payload.projectId,
  });

  const ai = resolveAIProvider(payload.modelConfig);
  const result = await ai.generateText(
    buildCharacterExtractPrompt(payload.screenplay),
    { systemPrompt, temperature: 0.5 }
  );

  const parsed = JSON.parse(result);

  // Support both formats: new { characters, relationships } and legacy array
  let extracted: ExtractedChar[];
  let relationships: ExtractedRelation[] = [];

  if (Array.isArray(parsed)) {
    // Legacy format: plain array of characters
    extracted = parsed;
  } else {
    // New format: { characters: [...], relationships: [...] }
    extracted = parsed.characters || [];
    relationships = parsed.relationships || [];
  }

  let newCharacters = extracted;

  // AI deduplication when extracting for an episode with existing main chars
  if (payload.episodeId) {
    const existingChars = await db
      .select()
      .from(characters)
      .where(
        and(eq(characters.projectId, payload.projectId), eq(characters.scope, "main"))
      );

    if (existingChars.length > 0) {
      try {
        const existingNames = existingChars.map((c) => c.name);
        const dedupeResult = await ai.generateText(
          `Existing characters: ${JSON.stringify(existingNames)}\n\nNewly extracted characters: ${JSON.stringify(extracted.map(c => c.name))}\n\nReturn a JSON array of ONLY the truly new character names that are NOT variants or aliases of existing characters. Consider nicknames, shortened names, and honorific variations as the same character.`,
          { systemPrompt: "You are a character deduplication assistant. Return only a JSON array of strings.", temperature: 0 }
        );
        const newNames = new Set(JSON.parse(dedupeResult) as string[]);
        newCharacters = extracted.filter((c) => newNames.has(c.name));
      } catch (dedupeErr) {
        console.warn("[CharacterExtract] Deduplication failed, inserting all:", dedupeErr);
      }
    }
  }

  const scope = payload.episodeId ? "guest" : "main";
  const created = [];
  for (const char of newCharacters) {
    const id = genId();
    const [record] = await db
      .insert(characters)
      .values({
        id,
        projectId: payload.projectId,
        name: char.name,
        description: char.description,
        visualHint: char.visualHint ?? "",
        heightCm: char.heightCm || 0,
        bodyType: char.bodyType || "average",
        performanceStyle: char.performanceStyle || "",
        scope,
        episodeId: payload.episodeId ?? null,
      })
      .returning();
    created.push(record);
  }

  // Auto-create character relationships from AI extraction
  if (relationships.length > 0) {
    // Build name→id map from ALL project characters (existing + newly created)
    const allChars = await db
      .select()
      .from(characters)
      .where(eq(characters.projectId, payload.projectId));
    const nameToId = new Map(allChars.map((c) => [c.name, c.id]));

    for (const rel of relationships) {
      const aId = nameToId.get(rel.characterA);
      const bId = nameToId.get(rel.characterB);
      if (aId && bId && aId !== bId) {
        try {
          await db.insert(characterRelations).values({
            id: genId(),
            projectId: payload.projectId,
            characterAId: aId,
            characterBId: bId,
            relationType: rel.relationType || "neutral",
            description: rel.description || "",
          });
        } catch (e) {
          // Skip duplicates or other errors silently
          console.warn(`[CharacterExtract] Skipped relation ${rel.characterA}↔${rel.characterB}:`, e);
        }
      }
    }
  }

  return { characters: created };
}
