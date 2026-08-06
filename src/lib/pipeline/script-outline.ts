import { db } from "@/lib/db";
import { projects, episodes } from "@/lib/db/schema";
import { resolveAIProvider } from "@/lib/ai/provider-factory";
import type { ModelConfigPayload } from "@/lib/ai/provider-factory";
import { resolvePrompt } from "@/lib/ai/prompts/resolver";
import { eq } from "drizzle-orm";
import type { Task } from "@/lib/task-queue";

export async function handleScriptOutline(task: Task) {
  const payload = task.payload as {
    projectId: string;
    episodeId?: string;
    idea: string;
    modelConfig?: ModelConfigPayload;
    userId?: string;
  };

  const { projectId, episodeId, idea } = payload;

  const systemPrompt = await resolvePrompt("script_outline", {
    userId: payload.userId ?? "",
    projectId,
  });

  const ai = resolveAIProvider(payload.modelConfig);
  const result = await ai.generateText(`创意构想：${idea}`, {
    systemPrompt,
    temperature: 0.7,
  });

  const outline = result.trim();

  // Save outline
  if (episodeId) {
    await db
      .update(episodes)
      .set({ outline, updatedAt: new Date() })
      .where(eq(episodes.id, episodeId));
  } else {
    await db
      .update(projects)
      .set({ outline, updatedAt: new Date() })
      .where(eq(projects.id, projectId));
  }

  return { outline };
}
