import { db } from "@/lib/db";
import { moodBoardImages } from "@/lib/db/schema";
import { eq } from "drizzle-orm";
import { id as genId } from "@/lib/id";
import { NextResponse } from "next/server";
import { assertProjectOwnership } from "@/lib/assert-project-ownership";

export async function GET(
  req: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  if (!(await assertProjectOwnership(req, id))) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }
  const images = await db
    .select()
    .from(moodBoardImages)
    .where(eq(moodBoardImages.projectId, id));
  return NextResponse.json(images);
}

export async function POST(
  req: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  if (!(await assertProjectOwnership(req, id))) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }
  const body = await req.json();
  const image = {
    id: genId(),
    projectId: id,
    imageUrl: body.imageUrl,
    annotation: body.annotation || "",
    extractedStyle: body.extractedStyle || "",
  };
  await db.insert(moodBoardImages).values(image);
  return NextResponse.json(image, { status: 201 });
}
