import { db } from "@/lib/db";
import { moodBoardImages } from "@/lib/db/schema";
import { and, eq } from "drizzle-orm";
import { NextResponse } from "next/server";
import { assertProjectOwnership } from "@/lib/assert-project-ownership";

export async function DELETE(
  req: Request,
  { params }: { params: Promise<{ id: string; imageId: string }> }
) {
  const { id: projectId, imageId } = await params;
  if (!(await assertProjectOwnership(req, projectId))) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }
  await db
    .delete(moodBoardImages)
    .where(
      and(
        eq(moodBoardImages.id, imageId),
        eq(moodBoardImages.projectId, projectId)
      )
    );
  return NextResponse.json({ ok: true });
}
