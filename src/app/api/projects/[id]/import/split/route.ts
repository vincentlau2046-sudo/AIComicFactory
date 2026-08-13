import { NextResponse } from 'next/server'
import { generateText } from 'ai'
import { createLanguageModel } from '@/lib/ai/ai-sdk'
import type { ProviderConfig } from '@/lib/ai/ai-sdk'
import { RetryStrategy } from '@/lib/retry'
import { db } from '@/lib/db'
import { projects } from '@/lib/db/schema'
import { eq, and } from 'drizzle-orm'
import { getUserIdFromRequest } from '@/lib/get-user-id'
import { addImportLog, chunkText } from '@/lib/import-utils'
import { buildScriptSplitPrompt } from '@/lib/ai/prompts/script-split'
import { resolvePrompt } from '@/lib/ai/prompts/resolver'

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

// --- Deterministic text parser (prompt asks for structured text, not JSON) ---

const EPISODE_SEP = /^=== (?:分集|Episode|episode|EPISODE) \d+ ===\r?$/m;
const FIELD_TITLE = /^\u6807\u9898[\uFF1A:] (.+)/m;
const FIELD_DESC = /^\u63cf\u8ff0[\uFF1A:] (.+)/m;
const FIELD_KW = /^\u5173\u952e\u8bcd[\uFF1A:] (.+)/m;
const FIELD_CHARS = /^\u89d2\u8272[\uFF1A:] (.+)/m;
const FIELD_IDEA_LABEL = /^\u5267\u60c5\u6784\u601d[\uFF1A:]/m;

function parseSplitText(text: string): SplitEpisode[] {
  const episodes: SplitEpisode[] = [];

  // Normalize: replace CRLF with LF, full-width colon with half-width
  let normalized = text.replace(/\r\n/g, "\n").replace(/\uff1a/g, ":");

  // Split by episode markers
  const blocks = normalized.split(EPISODE_SEP);

  for (const block of blocks) {
    const trimmed = block.trim();
    if (!trimmed) continue;

    // Find the header portion: everything before 剧情构思: label
    // This prevents idea content from polluting field regex matches.
    const ideaMatch = trimmed.match(FIELD_IDEA_LABEL);
    const header = ideaMatch ? trimmed.slice(0, ideaMatch.index!).trim() : trimmed;
    const idea = ideaMatch
      ? trimmed.slice(ideaMatch.index! + ideaMatch[0].length).trim()
      : "";

    // Only extract single-line fields from the header (not from idea content)
    const title = header.match(FIELD_TITLE)?.[1]?.trim();
    if (!title) continue;  // Skip blocks that don't look like episode data

    const description = header.match(FIELD_DESC)?.[1]?.trim() ?? "";
    const keywords = header.match(FIELD_KW)?.[1]?.trim() ?? "";

    // characters is comma-separated on one line
    const charsLine = header.match(FIELD_CHARS)?.[1];
    const characters = charsLine
      ? charsLine.split(/[,，]\s*/).filter(Boolean)
      : undefined;

    episodes.push({ title, description, keywords, idea, characters });
  }

  if (episodes.length === 0) {
    console.error(`[ImportSplit] parseSplitText produced 0 episodes. Raw:\n${text.slice(0, 500)}...`);
  }

  return episodes;
}

// --- Handler ---

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

  const chunks = chunkText(body.text)
  const model = createLanguageModel(body.modelConfig.text)
  const scriptSplitSystem = await resolvePrompt('script_split', { userId, projectId })
  const retryStrategy = new RetryStrategy({ maxRetries: 2, baseDelay: 1000, jitter: true })

  await addImportLog(
    projectId, 3, 'running',
    `开始自动分集，共 ${chunks.length} 块`,
  )

  // Build character context for prompt
  const allNames = body.allCharacters.map((c) => c.name)
  const charContext =
    allNames.length > 0
      ? `\n\nAll extracted characters (assign each to ONLY the episodes where they actually appear): ${allNames.join(', ')}`
      : ''

  let allEpisodes: SplitEpisode[];
  try {
    const chunkResults = await Promise.all(
      chunks.map(async (chunk, idx) => {
        await addImportLog(
          projectId, 3, 'running',
          `正在处理第 ${idx + 1}/${chunks.length} 块...`
        )

        const prompt = buildScriptSplitPrompt(
          chunk + charContext,
          { chunkIndex: idx, totalChunks: chunks.length, episodeOffset: 0 },
        )

        const result = await retryStrategy.execute(async () => {
          return generateText({
            model,
            system: scriptSplitSystem,
            prompt,
          })
        })

        const episodes = parseSplitText(result.text)
        if (episodes.length > 0) return episodes

        // Retry on parse failure with emphasis on structured text format
        console.error(`[ImportSplit] Chunk ${idx + 1} parse produced 0 episodes. Raw:\n${result.text.slice(0, 500)}...`)
        await addImportLog(
          projectId, 3, 'running',
          `第 ${idx + 1} 块解析失败，正在重试...`,
        )
        const retryResult = await retryStrategy.execute(async () => {
          return generateText({
            model,
            system: scriptSplitSystem,
            prompt: prompt + '\n\nIMPORTANT: Use EXACTLY the === 分集 N === format with field labels as specified.',
          })
        })
        return parseSplitText(retryResult.text)
      }),
    )
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