import { db } from "@/lib/db";
import { characterRelations } from "@/lib/db/schema";
import { and, eq } from "drizzle-orm";
import { NextResponse } from "next/server";
import { assertProjectOwnership } from "@/lib/assert-project-ownership";

export async function DELETE(
  req: Request,
  { params }: { params: Promise<{ id: string; relationId: string }> }
) {
  const { id: projectId, relationId } = await params;
  if (!(await assertProjectOwnership(req, projectId))) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }
  await db
    .delete(characterRelations)
    .where(
      and(
        eq(characterRelations.id, relationId),
        eq(characterRelations.projectId, projectId)
      )
    );
  return NextResponse.json({ ok: true });
}
