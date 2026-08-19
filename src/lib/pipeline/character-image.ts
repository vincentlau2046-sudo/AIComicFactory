import { db } from "@/lib/db";
import { characters } from "@/lib/db/schema";
import { resolveImageProvider } from "@/lib/ai/provider-factory";
import type { ModelConfigPayload } from "@/lib/ai/provider-factory";
import { eq } from "drizzle-orm";
import type { Task } from "@/lib/task-queue";
import { buildCharacterFrontViewPrompt } from "@/lib/ai/prompts/character-image";
import { copyToUploads } from "@/lib/shot-asset-utils";

export async function handleCharacterImage(task: Task) {
  const payload = task.payload as { characterId: string; modelConfig?: ModelConfigPayload };

  const [character] = await db
    .select()
    .from(characters)
    .where(eq(characters.id, payload.characterId));

  if (!character) {
    throw new Error("Character not found");
  }

  const prompt = buildCharacterFrontViewPrompt(character.t2iStructure ?? null, character.description || character.name);

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
      seed: Math.floor(Math.random() * 1000000),
    },
  });

  // Extract front view from pipeline intermediates (character-image pipeline gen_front step)
  const frontViewRaw = (ai as any).lastPipelineResult?.intermediates?.["gen_front.front_image"];
  const frontViewPath = frontViewRaw ? copyToUploads(frontViewRaw, 'character_front') : undefined;

  await db
    .update(characters)
    .set({
      referenceImage: imagePath,
      ...(frontViewPath ? { frontViewImage: frontViewPath as string } : {}),
    })
    .where(eq(characters.id, payload.characterId));

  return { imagePath };
}