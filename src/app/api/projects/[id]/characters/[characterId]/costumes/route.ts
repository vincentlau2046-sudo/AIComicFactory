import { db } from "@/lib/db";
import { characterCostumes, characters } from "@/lib/db/schema";
import { and, eq } from "drizzle-orm";
import { id as genId } from "@/lib/id";
import { NextResponse } from "next/server";
import { assertProjectOwnership } from "@/lib/assert-project-ownership";

async function assertCharacterInProject(characterId: string, projectId: string) {
  const [row] = await db
    .select({ id: characters.id })
    .from(characters)
    .where(and(eq(characters.id, characterId), eq(characters.projectId, projectId)));
  return !!row;
}

export async function GET(
  req: Request,
  { params }: { params: Promise<{ id: string; characterId: string }> }
) {
  const { id: projectId, characterId } = await params;
  if (!(await assertProjectOwnership(req, projectId))) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }
  if (!(await assertCharacterInProject(characterId, projectId))) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }
  const costumes = await db
    .select()
    .from(characterCostumes)
    .where(eq(characterCostumes.characterId, characterId));
  return NextResponse.json(costumes);
}

export async function POST(
  req: Request,
  { params }: { params: Promise<{ id: string; characterId: string }> }
) {
  const { id: projectId, characterId } = await params;
  if (!(await assertProjectOwnership(req, projectId))) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }
  if (!(await assertCharacterInProject(characterId, projectId))) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }
  const body = await req.json();
  const costume = {
    id: genId(),
    characterId,
    name: body.name || "default",
    description: body.description || "",
    referenceImage: body.referenceImage || null,
  };
  await db.insert(characterCostumes).values(costume);
  return NextResponse.json(costume, { status: 201 });
}
