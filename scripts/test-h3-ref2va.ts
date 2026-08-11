import { buildVideoPrompt } from "@/lib/ai/prompts/h3";
import type { H3PromptInput } from "@/lib/ai/prompts/h3/types";

const refInput: H3PromptInput = {
  videoScript: "朱重八站在破旧茅屋门口，抬头看着阴云密布的天空，握紧了拳头。",
  duration: 8,
  cameraDirection: "push in slow",
  generationMode: "reference",
  characters: [
    { id: "c1", name: "朱重八", description: "a tall young peasant in the Yuan Dynasty, wearing patched dark blue cotton", visualHint: "patched dark blue cotton clothing, tall sturdy build", referenceImage: "/uploads/c1/ref.png", scope: "main" },
    { id: "c2", name: "马氏", description: "Zhu's wife, thin build with gentle eyes", scope: "guest" },
  ],
  firstFrame: { fileUrl: "/tmp/hut.png", prompt: "interior of a run-down thatched hut at dusk" },
  lastFrame: { fileUrl: "/tmp/resolve.png", prompt: "Zhu lifts his head with burning resolve, doorway framing the dark sky" },
  dialogues: [
    { characterName: "朱重八", text: "我朱重八，从今天起不再是任人宰割的草民！", sequence: 1, startRatio: "0.5", endRatio: "0.9", offscreen: false },
  ],
  sceneDescription: "A run-down thatched hut in the late Yuan Dynasty, dusk light filtering through cracks in the wall, dust motes in the air.",
  sceneLighting: "Warm dusk light from cracks in the wall, long shadows",
  soundDesign: "Wind howling outside, thatch rustling, slow footsteps on dirt floor.",
  musicCue: "Slow erhu solo with deep drum underneath, gradually building intensity",
  bgmUrl: "/uploads/bgm/ancient_sorrow.mp3",
  languageMode: "auto",
};

const output = buildVideoPrompt(refInput);
console.log("MODE:", output.mode);
console.log("LANGUAGE:", output.languageUsed);
console.log("");
output.sections.forEach((s, i) => {
  console.log(`--- SECTION ${i} ---`);
  console.log(s);
  console.log("");
});
