import { db } from "@/lib/db";
import { characters } from "@/lib/db/schema";
import { resolveImageProvider } from "@/lib/ai/provider-factory";
import type { ModelConfigPayload } from "@/lib/ai/provider-factory";
import { resolveSlotContents } from "@/lib/ai/prompts/resolver";
import { eq } from "drizzle-orm";
import type { Task } from "@/lib/task-queue";

function buildFrontViewPrompt(
  frontLayout: string,
  description: string
): string {
  return [
    `角色正面参考图。全身站立，纯白背景。`,
    ``,
    `${description}`,
    ``,
    `注意：严格遵从上述角色描述中关于头发/光头的具体状态（如上文写了"光头"就绝对不能画头发）。`,
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
    const frontLayout = (slotContents as any)["front_view_layout"] || "";
    return buildFrontViewPrompt(
      frontLayout,
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