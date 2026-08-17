import { NextResponse } from "next/server";
import { generateText } from "ai";
import { createLanguageModel } from "@/lib/ai/ai-sdk";
import { parseLLMJSON } from "@/lib/ai/json-repair";
import type { ProviderConfig } from "@/lib/ai/ai-sdk";
import { db } from "@/lib/db";
import { projects, episodes } from "@/lib/db/schema";
import { eq, and } from "drizzle-orm";
import { getUserIdFromRequest } from "@/lib/get-user-id";
import { addImportLog } from "@/lib/import-utils";
import { buildCharacterArcPrompt } from "@/lib/ai/prompts/character-arc";
import { resolvePrompt } from "@/lib/ai/prompts/resolver";

export const maxDuration = 120;

interface ArcPhase {
  phaseName: string;
  episodeRange?: string;
  episodeStart?: number;
  episodeEnd?: number;
  triggerEvent: string;
  visualChanges: Record<string, string>;
  t2iStructure?: Record<string, string>;
  statusChange: string;
}

interface CharacterArc {
  characterName: string;
  totalPhases: number;
  phases: ArcPhase[];
}

interface SkippedChar {
  characterName: string;
  reason: string;
}

interface AssessResult {
  visualStyle: string;
  eraAesthetic: string;
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
    characters: Array<{ name: string; scope: string; description: string }>;
    projectAssess: AssessResult;
    modelConfig: { text: ProviderConfig | null };
  };

  if (!body.modelConfig?.text) {
    return NextResponse.json({ error: "No text model" }, { status: 400 });
  }

  // Load episodes for EP range context
  const eps = await db
    .select({ title: episodes.title, sequence: episodes.sequence, idea: episodes.idea })
    .from(episodes)
    .where(eq(episodes.projectId, projectId))
    .orderBy(episodes.sequence);

  const model = createLanguageModel(body.modelConfig.text);
  const arcSystem = await resolvePrompt("character_arc", { userId, projectId });

  await addImportLog(projectId, 5, "running", "开始角色弧光设计...");

  try {
    const jsonMode = {
      openai: { response_format: { type: "json_object" } },
    };
    const result = await generateText({
      model,
      system: arcSystem,
      prompt: buildCharacterArcPrompt(
        body.characters,
        eps.map(e => ({ title: e.title, sequence: e.sequence, idea: e.idea ?? "" })),
        { visualStyle: body.projectAssess.visualStyle, eraAesthetic: body.projectAssess.eraAesthetic }
      ),
      providerOptions: jsonMode,
    });

    const parsed = parseLLMJSON(result.text) as {
      characterArcs?: CharacterArc[];
      skippedCharacters?: SkippedChar[];
    };

    const characterArcs = (parsed.characterArcs ?? []).map((arc: any) => ({
      ...arc,
      phases: (arc.phases || []).map((p: any) => {
        // Parse episodeRange → start/end if not already provided
        let episodeStart = p.episodeStart || 0;
        let episodeEnd = p.episodeEnd || 0;
        if (!episodeStart && p.episodeRange) {
          const rangeMatch = p.episodeRange.match(/EP?(\d+)\s*[-–]\s*EP?(\d+)/i);
          episodeStart = rangeMatch ? parseInt(rangeMatch[1]) : 0;
          episodeEnd = rangeMatch ? parseInt(rangeMatch[2]) : episodeStart;
        }
        return { ...p, episodeStart, episodeEnd };
      }),
    }));
    const skippedCharacters = parsed.skippedCharacters ?? [];

    const mainChars = body.characters.filter(c => c.scope === "main");
    const totalPhases = characterArcs.reduce((sum, a) => sum + a.phases.length, 0);

    await addImportLog(
      projectId, 5, "done",
      `弧光设计完成: ${characterArcs.length} 个角色 / ${totalPhases} 个阶段${skippedCharacters.length ? ` (跳过 ${skippedCharacters.length} 个)` : ""} / ${mainChars.length} 个主角处理完毕`,
      { characterArcs, skippedCharacters }
    );

    return NextResponse.json({ characterArcs, skippedCharacters });
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Unknown error";
    await addImportLog(projectId, 5, "error", `弧光设计失败: ${msg}`);
    return NextResponse.json({ error: msg }, { status: 500 });
  }
}