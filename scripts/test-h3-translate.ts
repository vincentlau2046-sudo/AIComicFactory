import { detectLanguage, routeLanguage, translateNarrative } from "@/lib/ai/prompts/h3/language-route";

async function main() {
  const zhScript = `朱重八站在破旧茅屋门口，抬头看着阴云密布的天空，握紧了拳头。
马氏从里屋走出来，轻声说："你真的决定了吗？"
朱重八转过身，目光坚定地回答："我朱重八，从今天起不再是任人宰割的草民！"
屋外的风呼啸着，远处传来隐隐的雷声。`;

  console.log("=== 1. detectLanguage ===");
  console.log(detectLanguage(zhScript));

  console.log("\n=== 2. routeLanguage ===");
  const routed = routeLanguage(zhScript, "auto");
  console.log("hasDialogue:", routed.hasDialogue);

  console.log("\n=== 3. translateNarrative ===");
  // Extract narrative parts (remove <d> dialogue tags)
  const narrativeParts = routed.body
    .replace(/<d>.*?<\/d>/g, "")
    .replace(/\[ZH: ([^\]]+)\]/g, "$1");
  console.log("Narrative to translate:", narrativeParts.slice(0, 150) + "...");

  const translated = await translateNarrative(narrativeParts);
  console.log("\nTranslated:", translated.slice(0, 300));

  console.log("\n=== 4. Final assembled body ===");
  // Rebuild: original body with narrative parts translated
  console.log(routed.body.slice(0, 400) + "\n...");
}

main().catch(console.error);
