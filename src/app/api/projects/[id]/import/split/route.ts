import { NextResponse } from "next/server";
import { generateText } from "ai";
import { createLanguageModel } from "@/lib/ai/ai-sdk";
import type { ProviderConfig } from "@/lib/ai/ai-sdk";
import { db } from "@/lib/db";
import { projects } from "@/lib/db/schema";
import { eq, and } from "drizzle-orm";
import { getUserIdFromRequest } from "@/lib/get-user-id";
import { addImportLog, chunkText } from "@/lib/import-utils";
import { buildScriptSplitPrompt } from "@/lib/ai/prompts/script-split";
import { resolvePrompt } from "@/lib/ai/prompts/resolver";

export const maxDuration = 300;

interface SplitEpisode {
  title: string;
  description: string;
  keywords: string;
  idea: string;
  characters?: string[];
}

interface CharacterSummary {
  name: string;
  scope: string;
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
    text: string;
    allCharacters: CharacterSummary[];
    modelConfig: { text: ProviderConfig | null };
  };

  if (!body.modelConfig?.text) {
    return NextResponse.json({ error: "No text model" }, { status: 400 });
  }

  const chunks = chunkText(body.text);
  const model = createLanguageModel(body.modelConfig.text);
  const scriptSplitSystem = await resolvePrompt("script_split", { userId, projectId });

  await addImportLog(
    projectId, 3, "running",
    `开始自动分集，共 ${chunks.length} 块`
  );

  // Build character context for prompt
  const allNames = body.allCharacters.map((c) => c.name);
  const charContext = allNames.length > 0
    ? `\n\nAll extracted characters (assign each to ONLY the episodes where they actually appear): ${allNames.join(", ")}`
    : "";

  let allEpisodes: SplitEpisode[];
  try {
    const chunkResults = await Promise.all(
      chunks.map(async (chunk, idx) => {
        await addImportLog(
          projectId, 3, "running",
          `正在处理第 ${idx + 1}/${chunks.length} 块...`
        );

        const prompt = buildScriptSplitPrompt(
          chunk + charContext,
          { chunkIndex: idx, totalChunks: chunks.length, episodeOffset: 0 }
        );

        const result = await generateText({
          model,
          system: scriptSplitSystem,
          prompt,
        });

        return parseSplitText(result.text);
      })
    );
    allEpisodes = chunkResults.flat();
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Unknown error";
    await addImportLog(projectId, 3, "error", `分集失败: ${msg}`);
    return NextResponse.json({ error: msg }, { status: 500 });
  }

  await addImportLog(
    projectId, 3, "done",
    `分集完成，共 ${allEpisodes.length} 集`,
    { episodes: allEpisodes }
  );

  return NextResponse.json({ episodes: allEpisodes });
}

// ── Deterministic text parser — replaces JSON mode for robustness ──
// LLM outputs structured text with markers instead of JSON.
// This parser extracts fields losslessly and handles multi-line 剧情构思.

const EPISODE_SEP = /^=== (?:分集|Episode) \d+ ===$/m;
const FIELD_TITLE = /^标题: (.+)/m;
const FIELD_DESC = /^描述: (.+)/m;
const FIELD_KW = /^关键词: (.+)/m;
const FIELD_CHARS = /^角色: (.+)/m;
const FIELD_IDEA_LABEL = /^剧情构思:/m;

function parseSplitText(text: string): SplitEpisode[] {
  const episodes: SplitEpisode[] = [];

  // Split by episode markers
  const blocks = text.split(EPISODE_SEP);

  for (const block of blocks) {
    const trimmed = block.trim();
    if (!trimmed) continue;

    const title = trimmed.match(FIELD_TITLE)?.[1]?.trim();
    // Skip blocks that don't look like episode data (pre-amble, etc.)
    if (!title) continue;

    const description = trimmed.match(FIELD_DESC)?.[1]?.trim() ?? "";
    const keywords = trimmed.match(FIELD_KW)?.[1]?.trim() ?? "";

    // characters is comma-separated on one line
    const charsLine = trimmed.match(FIELD_CHARS)?.[1];
    const characters = charsLine
      ? charsLine.split(/,\s*/).filter(Boolean)
      : undefined;

    // 剧情构思: everything after the label until end of block
    const ideaMatch = trimmed.match(FIELD_IDEA_LABEL);
    let idea = "";
    if (ideaMatch) {
      idea = trimmed.slice(ideaMatch.index! + ideaMatch[0].length).trim();
      // Remove trailing whitespace lines
      idea = idea.replace(/\s+$/, "");
    }

    episodes.push({ title, description, keywords, idea, characters });
  }

  return episodes;
}
