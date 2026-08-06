import { NextResponse } from "next/server";
import { db } from "@/lib/db";
import { tasks, projects } from "@/lib/db/schema";
import { and, eq } from "drizzle-orm";
import { getUserIdFromRequest } from "@/lib/get-user-id";

export async function GET(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const userId = getUserIdFromRequest(request);
  if (!userId) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }

  const [row] = await db
    .select({ task: tasks })
    .from(tasks)
    .leftJoin(projects, eq(tasks.projectId, projects.id))
    .where(and(eq(tasks.id, id), eq(projects.userId, userId)));

  if (!row) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }

  return NextResponse.json(row.task);
}
