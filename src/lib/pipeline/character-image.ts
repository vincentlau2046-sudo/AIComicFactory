import { db } from "@/lib/db";
import { characters } from "@/lib/db/schema";
import { resolveImageProvider } from "@/lib/ai/provider-factory";
import type { ModelConfigPayload } from "@/lib/ai/provider-factory";
import { resolveSlotContents } from "@/lib/ai/prompts/resolver";
import { eq } from "drizzle-orm";
import type { Task } from "@/lib/task-queue";

function buildFrontViewPrompt(
  styleMatching: string, faceDetail: string, frontLayout: string,
  description: string
): string {
  return [
    `角色正面参考图——四视图流程第一步。`,
    ``,
    styleMatching,
    ``,
    `=== 角色描述 ===`,
    `${description}`,
    ``,
    faceDetail,
    ``,
    frontLayout,
  ].join("\n");
}

export async function handleCharacterImage(task: Task) {
  const payload = task.payload as { characterId: string; modelConfig?: ModelConfigPayload };

  const [character] = await db
    .select()
    .from(characters)
    .where(eq(characters.id, payload.characterId));

  if (!character) {
    throw new Error("Character not found");
  }

  // Build front-view prompt from template system (NOT buildCharacterTurnaroundPrompt)
  const frontPrompt = await (async () => {
    const slotContents = await resolveSlotContents("character_image", { userId: "", projectId: character.projectId });
    const styleMatching = (slotContents as any)["style_matching"] || "";
    const faceDetail = (slotContents as any)["face_detail"] || "";
    const frontLayout = (slotContents as any)["front_view_layout"] || "";
    return buildFrontViewPrompt(
      styleMatching, faceDetail, frontLayout,
      character.description || character.name
    );
  })();

  const ai = resolveImageProvider(payload.modelConfig);
  const imagePath = await ai.generateImage(frontPrompt, {
    size: "2560x1440",
    aspectRatio: "16:9",
    quality: "hd",
    pipeline: "character-image",
    pipelineParams: {
      character_name: character.name,
      character_desc: character.description || character.name,
      character_prompt: frontPrompt,
    },
  });

  await db
    .update(characters)
    .set({ referenceImage: imagePath })
    .where(eq(characters.id, payload.characterId));

  return { imagePath };
}