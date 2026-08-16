import { NextResponse } from "next/server";
import { db } from "@/lib/db";
import { tasks } from "@/lib/db/schema";
import { eq, desc } from "drizzle-orm";

/**
 * GET /api/projects/[id]/tasks?status=pending,running&type=frame_generate
 *
 * Query task queue progress for a project.
 * Returns all tasks for the project; client can filter by status/type if needed.
 */
export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id: projectId } = await params;
  const url = new URL(_request.url);
  const limit = Math.min(parseInt(url.searchParams.get("limit") ?? "100", 10), 200);

  const rows = await db
    .select({
      id: tasks.id,
      type: tasks.type,
      status: tasks.status,
      retries: tasks.retries,
      maxRetries: tasks.maxRetries,
      error: tasks.error,
      createdAt: tasks.createdAt,
    })
    .from(tasks)
    .where(eq(tasks.projectId, projectId))
    .orderBy(desc(tasks.createdAt))
    .limit(limit);

  // Summary by status
  const summary: Record<string, number> = {};
  for (const r of rows) {
    const s = r.status ?? "unknown";
    summary[s] = (summary[s] ?? 0) + 1;
  }

  return NextResponse.json({ tasks: rows, summary, total: rows.length });
}