import { db } from "@/lib/db";
import { tasks } from "@/lib/db/schema";
import { eq, asc, inArray, sql } from "drizzle-orm";
import { id as genId } from "@/lib/id";
import type { TaskType } from "./types";

export async function enqueueTask(params: {
  type: NonNullable<TaskType>;
  projectId?: string;
  payload?: unknown;
  maxRetries?: number;
  scheduledAt?: Date;
  episodeId?: string;
}) {
  const id = genId();
  const [task] = await db
    .insert(tasks)
    .values({
      id,
      type: params.type,
      projectId: params.projectId,
      payload: params.payload,
      maxRetries: params.maxRetries ?? 3,
      scheduledAt: params.scheduledAt,
      episodeId: params.episodeId ?? null,
    })
    .returning();
  return task;
}

export async function dequeueTasks(
  limit: number,
  opts?: { skipComfy?: boolean }
): Promise<Array<typeof tasks.$inferSelect>> {
  const now = new Date();
  const subquery = opts?.skipComfy
    ? sql`(SELECT id FROM tasks
        WHERE status = 'pending'
        AND (scheduled_at IS NULL OR scheduled_at <= ${now.getTime()})
        AND type NOT IN ('frame_generate','video_generate','character_image','scene_frame_generate','reference_video_generate')
        ORDER BY created_at ASC LIMIT ${limit})`
    : sql`(SELECT id FROM tasks
        WHERE status = 'pending'
        AND (scheduled_at IS NULL OR scheduled_at <= ${now.getTime()})
        ORDER BY created_at ASC LIMIT ${limit})`;

  const claimed = await db
    .update(tasks)
    .set({ status: "running" })
    .where(inArray(tasks.id, subquery))
    .returning();

  return claimed;
}

export async function dequeueTask(opts?: {
  skipComfy?: boolean;
}): Promise<
  typeof tasks.$inferSelect | null
> {
  const now = new Date();

  // Build subquery — skip ComfyUI types if ComfyUI is offline
  const subquery = opts?.skipComfy
    ? sql`(SELECT id FROM tasks
        WHERE status = 'pending'
        AND (scheduled_at IS NULL OR scheduled_at <= ${now.getTime()})
        AND type NOT IN ('frame_generate','video_generate','character_image','scene_frame_generate','reference_video_generate')
        ORDER BY created_at ASC LIMIT 1)`
    : sql`(SELECT id FROM tasks
        WHERE status = 'pending'
        AND (scheduled_at IS NULL OR scheduled_at <= ${now.getTime()})
        ORDER BY created_at ASC LIMIT 1)`;

  // Atomic claim: UPDATE ... WHERE in a single statement to avoid race conditions.
  const [task] = await db
    .update(tasks)
    .set({ status: "running" })
    .where(eq(tasks.id, subquery))
    .returning();

  return task || null;
}

export async function completeTask(id: string, result: unknown) {
  await db
    .update(tasks)
    .set({
      status: "completed",
      result: result as Record<string, unknown>,
    })
    .where(eq(tasks.id, id));
}

export async function failTask(id: string, error: string) {
  const [task] = await db
    .select()
    .from(tasks)
    .where(eq(tasks.id, id));

  if (!task) return;

  await db
    .update(tasks)
    .set({
      status: "failed",
      retries: (task.retries ?? 0) + 1,
      error,
    })
    .where(eq(tasks.id, id));
}

export async function getTasksByProject(projectId: string) {
  return db
    .select()
    .from(tasks)
    .where(eq(tasks.projectId, projectId))
    .orderBy(asc(tasks.createdAt));
}