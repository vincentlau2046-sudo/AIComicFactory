import { NextResponse } from "next/server";
import { generateText } from "ai";
import { createLanguageModel } from "@/lib/ai/ai-sdk";
import { parseLLMJSON } from "@/lib/ai/json-repair";
import type { ProviderConfig } from "@/lib/ai/ai-sdk";
import { db } from "@/lib/db";
import { projects } from "@/lib/db/schema";
import { eq, and } from "drizzle-orm";
import { getUserIdFromRequest } from "@/lib/get-user-id";
import { addImportLog } from "@/lib/import-utils";
import { buildProjectAssessPrompt } from "@/lib/ai/prompts/project-assess";
import { matchVisualStyleKey } from "@/lib/ai/prompts/style-registry";
import { resolvePrompt } from "@/lib/ai/prompts/resolver";

export const maxDuration = 120;

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
    modelConfig: { text: ProviderConfig | null };
  };

  if (!body.modelConfig?.text) {
    return NextResponse.json({ error: "No text model" }, { status: 400 });
  }

  // Truncate to first ~8000 chars for assessment
  const sampleText = body.text.slice(0, 8000);
  const model = createLanguageModel(body.modelConfig.text);
  const assessSystem = await resolvePrompt("project_assess", { userId, projectId });

  await addImportLog(projectId, 2, "running", "开始项目定位分析...");

  try {
    const jsonMode = {
      openai: { response_format: { type: "json_object" } },
    };
    const result = await generateText({
      model,
      system: assessSystem,
      prompt: buildProjectAssessPrompt(sampleText),
      providerOptions: jsonMode,
    });

    const parsed = parseLLMJSON(result.text) as Record<string, string>;

    const output = {
      visualStyle: String(parsed.visualStyle ?? ""),
      visualStyleKey: matchVisualStyleKey(String(parsed.visualStyle ?? "")),
      eraAesthetic: String(parsed.eraAesthetic ?? ""),
      moodDirection: String(parsed.moodDirection ?? ""),
      worldSetting: String(parsed.worldSetting ?? ""),
      genre: String(parsed.genre ?? ""),
      targetAudience: String(parsed.targetAudience ?? ""),
    };

    await addImportLog(
      projectId, 2, "done",
      `项目定位完成: ${output.visualStyle.slice(0, 30)}...`,
      output
    );

    return NextResponse.json(output);
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Unknown error";
    await addImportLog(projectId, 2, "error", `项目定位失败: ${msg}`);
    return NextResponse.json({ error: msg }, { status: 500 });
  }
}