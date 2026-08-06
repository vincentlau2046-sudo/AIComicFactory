import { db } from "@/lib/db";
import { characterRelations, characters } from "@/lib/db/schema";
import { and, eq, inArray } from "drizzle-orm";
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
  const relations = await db
    .select()
    .from(characterRelations)
    .where(eq(characterRelations.projectId, id));
  return NextResponse.json(relations);
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
  // Ensure both characters belong to this project
  if (!body.characterAId || !body.characterBId) {
    return NextResponse.json({ error: "Missing character ids" }, { status: 400 });
  }
  const chars = await db
    .select({ id: characters.id })
    .from(characters)
    .where(
      and(
        eq(characters.projectId, id),
        inArray(characters.id, [body.characterAId, body.characterBId])
      )
    );
  if (chars.length !== 2) {
    return NextResponse.json({ error: "Invalid character ids" }, { status: 400 });
  }
  const relation = {
    id: genId(),
    projectId: id,
    characterAId: body.characterAId,
    characterBId: body.characterBId,
    relationType: body.relationType || "neutral",
    description: body.description || "",
  };
  await db.insert(characterRelations).values(relation);
  return NextResponse.json(relation, { status: 201 });
}
