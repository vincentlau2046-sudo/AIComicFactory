import { detectLanguage, extractDialogueSegments, routeLanguage } from "@/lib/ai/prompts/h3/language-route";

const zhScript = `朱重八站在破旧茅屋门口，抬头看着阴云密布的天空，握紧了拳头。

马氏从里屋走出来，轻声说："你真的决定了吗？"

朱重八转过身，目光坚定地回答："我朱重八，从今天起不再是任人宰割的草民！"`;

console.log("=== detectLanguage ===");
console.log(detectLanguage(zhScript));

console.log("\n=== extractDialogueSegments ===");
const segs = extractDialogueSegments(zhScript);
segs.forEach(s => console.log(`  [${s.isDialogue ? "DIALOGUE" : "NARRATIVE"}] ${s.text.slice(0, 60)}...`));

console.log("\n=== routeLanguage ===");
const routed = routeLanguage(zhScript, "auto");
console.log("hasDialogue:", routed.hasDialogue);
console.log("needsTranslation:", routed.needsTranslation);
console.log("body:", routed.body.slice(0, 300));

// English test
const enScript = "A man walks through a rainy street. He says: \"I'll be back tomorrow.\"";
console.log("\n=== English ===");
console.log("lang:", detectLanguage(enScript));
console.log("routed:", JSON.stringify(routeLanguage(enScript, "auto")));
