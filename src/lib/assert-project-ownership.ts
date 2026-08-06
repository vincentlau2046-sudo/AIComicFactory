import { db } from "@/lib/db";
import { projects } from "@/lib/db/schema";
import { and, eq } from "drizzle-orm";
import { getUserIdFromRequest } from "@/lib/get-user-id";

/**
 * Verify that the request's user owns the given project.
 * Returns the project row if owned, otherwise null.
 */
export async function assertProjectOwnership(
  request: Request,
  projectId: string
) {
  const userId = getUserIdFromRequest(request);
  if (!userId) return null;
  const [project] = await db
    .select()
    .from(projects)
    .where(and(eq(projects.id, projectId), eq(projects.userId, userId)));
  return project ?? null;
}
