import { db } from "@/lib/db";
import { characters } from "@/lib/db/schema";
import { resolveImageProvider } from "@/lib/ai/provider-factory";
import type { ModelConfigPayload } from "@/lib/ai/provider-factory";
import { eq } from "drizzle-orm";
import type { Task } from "@/lib/task-queue";

export async function handleCharacterImage(task: Task) {
  const payload = task.payload as { characterId: string; modelConfig?: ModelConfigPayload };

  const [character] = await db
    .select()
    .from(characters)
    .where(eq(characters.id, payload.characterId));

  if (!character) {
    throw new Error("Character not found");
  }

  // T2I prompt: character description IS the prompt
  // (template sections like FACE_DETAIL/STYLE_MATCHING are for LLM, not direct injection)
  const prompt = [
    `角色正面参考图。全身站立正面视图，纯白背景。`,
    ``,
    `${character.description || character.name}`,
    ``,
    `全身比例正确，从头顶到脚底完整展示，禁止半身图。`,
  ].join("\n");

  const ai = resolveImageProvider(payload.modelConfig);
  const imagePath = await ai.generateImage(prompt, {
    size: "2560x1440",
    aspectRatio: "16:9",
    quality: "hd",
    pipeline: "character-image",
    pipelineParams: {
      character_name: character.name,
      character_desc: character.description || character.name,
      character_prompt: prompt,
    },
  });

  await db
    .update(characters)
    .set({ referenceImage: imagePath })
    .where(eq(characters.id, payload.characterId));

  return { imagePath };
}