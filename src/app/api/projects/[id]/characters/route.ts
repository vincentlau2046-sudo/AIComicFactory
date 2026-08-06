import { NextResponse } from "next/server";
import { db } from "@/lib/db";
import { characters } from "@/lib/db/schema";
import { eq } from "drizzle-orm";
import { assertProjectOwnership } from "@/lib/assert-project-ownership";

export async function GET(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id: projectId } = await params;
  if (!(await assertProjectOwnership(request, projectId))) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }
  const result = await db
    .select()
    .from(characters)
    .where(eq(characters.projectId, projectId));
  return NextResponse.json(result);
}
