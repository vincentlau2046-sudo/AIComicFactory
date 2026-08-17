import { NextResponse } from "next/server";
import { db } from "@/lib/db";
import { projects, episodes, characters, episodeCharacters, characterRelations } from "@/lib/db/schema";
import { eq, and, max } from "drizzle-orm";
import { id as genId } from "@/lib/id";
import { getUserIdFromRequest } from "@/lib/get-user-id";
import { addImportLog } from "@/lib/import-utils";

export const maxDuration = 60;

interface EpisodeData {
  title: string;
  description: string;
  keywords: string;
  idea: string;
  characters?: string[];
}

interface CharacterData {
  name: string;
  scope: "main" | "guest";
  description: string;
  visualHint?: string;
}

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id: projectId } = await params;
  const userId = getUserIdFromRequest(request);

  const [project] = await db
    .select()
    .from(projects)
    .where(and(eq(projects.id, projectId), eq(projects.userId, userId)));

  if (!project) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }

  const body = (await request.json()) as {
    episodes: EpisodeData[];
    characters: CharacterData[];
    relationships?: Array<{
      characterA: string;
      characterB: string;
      relationType: string;
      description?: string;
    }>;
    projectAssess?: {
      visualStyle?: string;
      eraAesthetic?: string;
      moodDirection?: string;
    };
    characterArcs?: Array<{
      characterName: string;
      phases: Array<{
        phaseName: string;
        description?: string;
        episodeStart?: number;
        episodeEnd?: number;
        triggerEvent: string;
        visualChanges: Record<string, string>;
        t2iStructure?: Record<string, string>;
        statusChange: string;
      }>;
    }>;
  };

  await addImportLog(
    projectId, 6, "running",
    `开始创建 ${body.episodes.length} 集和 ${body.characters.length} 个角色`
  );

  // 1. Create all characters (main + guest), build name→id map
  const charIdByName = new Map<string, string>();
  for (const char of body.characters) {
    const charId = genId();
    await db.insert(characters).values({
      id: charId,
      projectId,
      baseName: char.name,
      name: char.name,
      description: char.description,
      visualHint: char.visualHint ?? "",
      scope: char.scope,
      episodeId: null,
    });
    charIdByName.set(char.name.toLowerCase().trim(), charId);
  }

  // 1b. Create character relationships
  if (body.relationships?.length) {
    for (const rel of body.relationships) {
      const aId = charIdByName.get(rel.characterA.toLowerCase().trim());
      const bId = charIdByName.get(rel.characterB.toLowerCase().trim());
      if (aId && bId && aId !== bId) {
        try {
          await db.insert(characterRelations).values({
            id: genId(),
            projectId,
            characterAId: aId,
            characterBId: bId,
            relationType: rel.relationType || "neutral",
            description: rel.description || "",
          });
        } catch {
          // skip duplicates
        }
      }
    }
  }

  await addImportLog(
    projectId, 6, "running",
    `已创建 ${body.characters.length} 个角色${body.relationships?.length ? `和 ${body.relationships.length} 个关系` : ""}`
  );

  // 2. Create episodes
  const [seqResult] = await db
    .select({ maxSeq: max(episodes.sequence) })
    .from(episodes)
    .where(eq(episodes.projectId, projectId));

  let seq = (seqResult?.maxSeq ?? 0) + 1;

  const created = [];
  for (const ep of body.episodes) {
    const [row] = await db
      .insert(episodes)
      .values({
        id: genId(),
        projectId,
        title: ep.title,
        description: ep.description || "",
        keywords: ep.keywords || "",
        idea: ep.idea || "",
        sequence: seq++,
      })
      .returning();
    created.push(row);
  }

  // 3. Create episode_characters relations
  let relationCount = 0;
  for (let i = 0; i < body.episodes.length; i++) {
    const epData = body.episodes[i];
    const episodeId = created[i]?.id;
    if (!episodeId || !epData.characters) continue;

    for (const charName of epData.characters) {
      const charId = charIdByName.get(charName.toLowerCase().trim());
      if (!charId) continue;
      await db.insert(episodeCharacters).values({
        id: genId(),
        episodeId,
        characterId: charId,
      });
      relationCount++;
    }
  }

  // 4. Write project assess style fields to projects table
  if (body.projectAssess) {
    await db
      .update(projects)
      .set({
        visualStyle: body.projectAssess.visualStyle ?? "",
        visualStyleKey: (body.projectAssess as any)?.visualStyleKey ?? "",
        eraAesthetic: body.projectAssess.eraAesthetic ?? "",
        moodDirection: body.projectAssess.moodDirection ?? "",
      })
      .where(eq(projects.id, projectId));

    // Propagate to all episodes (can be overridden per-EP later)
    if (body.projectAssess.visualStyle || body.projectAssess.eraAesthetic || body.projectAssess.moodDirection) {
      await db
        .update(episodes)
        .set({
          visualStyle: body.projectAssess.visualStyle ?? "",
          eraAesthetic: body.projectAssess.eraAesthetic ?? "",
          moodDirection: body.projectAssess.moodDirection ?? "",
        })
        .where(eq(episodes.projectId, projectId));
    }
  }

  // 5. Write phase cards as characters rows
  if (body.characterArcs?.length) {
    let phaseCount = 0;
    for (const arc of body.characterArcs) {
      const charId = charIdByName.get(arc.characterName.toLowerCase().trim());
      if (!charId) continue;
      for (let i = 0; i < arc.phases.length; i++) {
        const p = arc.phases[i];
        await db.insert(characters).values({
          id: genId(),
          projectId,
          baseName: arc.characterName,
          name: `${arc.characterName}（${p.phaseName}）`,
          description: p.description || "",
          phaseName: p.phaseName,
          episodeStart: p.episodeStart || p.episodeEnd || 0,
          episodeEnd: p.episodeEnd || p.episodeStart || 0,
          visualChanges: typeof p.visualChanges === "string" ? p.visualChanges : (p.visualChanges ? JSON.stringify(p.visualChanges) : null),
          t2iStructure: p.t2iStructure ? JSON.stringify(p.t2iStructure) : null,
          scope: "main",
        });
        phaseCount++;
      }
    }
    await addImportLog(
      projectId, 6, "running",
      `已写入 ${body.characterArcs.length} 个角色的 ${phaseCount} 个弧光阶段`
    );
  }

  await addImportLog(
    projectId, 6, "done",
    `导入完成！创建了 ${body.characters.length} 个角色和 ${created.length} 集（${relationCount} 个角色分配）`,
    { episodeCount: created.length, characterCount: body.characters.length }
  );

  return NextResponse.json({
    episodes: created,
    characterCount: body.characters.length,
  }, { status: 201 });
}
