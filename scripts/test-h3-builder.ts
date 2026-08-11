// Quick smoke test for H3 Base Mode builder
import { buildVideoPrompt } from "@/lib/ai/prompts/h3";
import type { H3PromptInput } from "@/lib/ai/prompts/h3/types";

const input: H3PromptInput = {
  videoScript: "A young man stands by a rain-covered window in an old apartment, looking out at the city lights. He turns slowly toward the door as someone knocks.",
  duration: 8,
  cameraDirection: "static",
  generationMode: "keyframe",
  characters: [
    { id: "c1", name: "李明", description: "a young man in his 20s, wearing a grey hoodie", scope: "main" },
    { id: "c2", name: "张伟", description: "an older man in a suit", scope: "guest" },
  ],
  firstFrame: { fileUrl: "/tmp/frame1.png", prompt: "interior of an old apartment with rain on the window" },
  lastFrame: { fileUrl: "/tmp/frame2.png", prompt: "the young man turns to face the door" },
  dialogues: [
    { characterName: "张伟", text: "你在等谁？", sequence: 1, startRatio: "0.3", endRatio: "0.5", offscreen: true },
    { characterName: "李明", text: "一个不会回来的人", sequence: 2, startRatio: "0.6", endRatio: "0.8", offscreen: false },
  ],
  soundDesign: "Rain pattering on glass, soft footsteps, a knock on the door.",
  musicCue: "Slow solo piano, melancholic",
  languageMode: "auto",
};

console.log("Input:", JSON.stringify(input, null, 2).slice(0, 200) + "...");
console.log("");

const output = buildVideoPrompt(input);
console.log("MODE:", output.mode);
console.log("LANGUAGE:", output.languageUsed);
console.log("TASK TYPE:", output.taskType);
console.log("");
output.sections.forEach((s, i) => {
  console.log(`--- SECTION ${i} ---`);
  console.log(s);
  console.log("");
});
