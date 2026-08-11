// ═══════════════════════════════════════════════
// H3 Base Mode Builder (v0.2.0)
// LLM-optimized via 3-layer context engineering.
// Uses system AI provider (via modelConfig) — no hardcoded URLs/models.
// ═══════════════════════════════════════════════

import type { AIProvider } from "@/lib/ai/types";
import type { H3PromptInput, H3PromptOutput } from "./types";
import { buildH3PromptTemplate, resolveLanguage } from "./prompt-template";
import { mapCameraDirection } from "./camera-map";

/**
 * Build H3 prompt via LLM using system-configured AI provider.
 * Falls back to local formatting on failure.
 *
 * @param input           All context data from AICF pipeline
 * @param textProvider    System AI provider (from resolveAIProvider(modelConfig))
 * @param systemOverride  Optional system prompt from prompt registry
 */
export async function buildH3BasePromptLLM(
  input: H3PromptInput,
  textProvider: AIProvider,
  systemOverride?: string
): Promise<H3PromptOutput> {
  const lang = resolveLanguage(input);
  try {
    const { system, user } = buildH3PromptTemplate(input, systemOverride);

    const raw = await textProvider.generateText(user, {
      systemPrompt: system,
      temperature: 0.7,
      maxTokens: 32000,
    });

    if (!raw?.trim()) throw new Error("Empty LLM response");

    return {
      mode: "base",
      taskType: "keyframe_completion",
      languageUsed: lang === "zh" ? "zh" : "en",
      sections: parseLLMSections(raw, input, lang),
    };
  } catch (e) {
    console.warn("[H3] LLM call failed, falling back to local builder:", (e as Error).message);
    return buildH3BasePrompt(input, lang);
  }
}

/**
 * Local builder — format-only, no LLM. Used as fallback.
 */
export function buildH3BasePrompt(
  input: H3PromptInput,
  lang?: "zh" | "en"
): H3PromptOutput {
  const language = lang || resolveLanguage(input);
  const prefix = buildInstructionPrefix(input, language);
  const camera = mapCameraDirection(input.cameraDirection);

  if (language === "zh") {
    return {
      mode: "base",
      taskType: "keyframe_completion",
      languageUsed: "zh",
      sections: [
        prefix
          ? `${prefix}\n\n集成多模态描述 (integrated_multimodal_description):\n[Shot 1] ${input.videoScript} ${camera}。`
          : `集成多模态描述 (integrated_multimodal_description):\n[Shot 1] ${input.videoScript} ${camera}。`,
        `整体环境音 (overall_soundscape): ${input.soundDesign || "N/A"}`,
        input.bgmUrl
          ? "非叙事音乐 (non_diegetic_music): <Audio 1> 作为背景配乐参考。"
          : `非叙事音乐 (non_diegetic_music): ${input.musicCue || "N/A"}`,
      ],
    };
  }

  return {
    mode: "base",
    taskType: "keyframe_completion",
    languageUsed: "en",
    sections: [
      prefix
        ? `${prefix}\n\nintegrated_multimodal_description:\n[Shot 1] ${input.videoScript} ${camera}.`
        : `integrated_multimodal_description:\n[Shot 1] ${input.videoScript} ${camera}.`,
      `overall_soundscape: ${input.soundDesign || "N/A"}`,
      input.bgmUrl
        ? "non_diegetic_music: <Audio 1> is referenced as the background score."
        : `non_diegetic_music: ${input.musicCue || "N/A"}`,
    ],
  };
}

// ── Helpers ──

function buildInstructionPrefix(
  input: H3PromptInput,
  lang: "zh" | "en"
): string | null {
  if (!input.firstFrame?.fileUrl) return null;
  if (input.lastFrame?.fileUrl) {
    if (lang === "zh") {
      return [
        "参考图与目标视频的对齐方式——",
        "<Picture 1>（来自 [Shot 1]）对齐目标视频的第0.00秒；",
        `<Picture 2>（来自 [Shot 1]）对齐目标视频的第${input.duration.toFixed(2)}秒。`,
      ].join("");
    }
    return [
      "How the reference pictures align with the target video — ",
      "<Picture 1> (from [Shot 1]) aligns with the 0.00-second mark of the target video; ",
      `<Picture 2> (from [Shot 1]) aligns with the ${input.duration.toFixed(2)}-second mark of the target video.`,
    ].join("");
  }
  if (lang === "zh") {
    return [
      "目标视频第0.00秒时，",
      "<Picture 1>（来自 [Shot 1]）被完整参考。",
    ].join("");
  }
  return "For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.";
}

function parseLLMSections(
  raw: string,
  input: H3PromptInput,
  lang: "zh" | "en"
): string[] {
  const sections: string[] = [];

  // Extract instruction prefix (EN or ZH)
  const prefixMatch = raw.match(
    /^(How the reference pictures align[\s\S]*?video\.|参考图与目标视频的对齐方式[\s\S]*?秒。|For the target video[\s\S]*?referenced\.|目标视频第[\s\S]*?参考。)/
  );
  const prefix = prefixMatch ? prefixMatch[1] : "";
  const body = prefixMatch ? raw.slice(prefixMatch[0].length).trim() : raw;

  if (lang === "zh") {
    // Match both ZH-prefixed (集成多模态描述 (integrated_multimodal_description):) or bare EN (integrated_multimodal_description:) headers
    const imdMatch = body.match(
      /(?:集成多模态描述\s*[\(（]?integrated_multimodal_description[\)）]?|integrated_multimodal_description)\s*[:：]\s*([\s\S]*?)(?=\n\s*(?:整体环境音|overall_soundscape|非叙事音乐|non_diegetic_music)\s*[:：(（]|$)/i
    );
    const osMatch = body.match(
      /(?:整体环境音\s*[\(（]?overall_soundscape[\)）]?|overall_soundscape)\s*[:：]\s*([\s\S]*?)(?=\n\s*(?:非叙事音乐|non_diegetic_music)\s*[:：(（]|$)/i
    );
    const nmMatch = body.match(
      /(?:非叙事音乐\s*[\(（]?non_diegetic_music[\)）]?|non_diegetic_music)\s*[:：]\s*([\s\S]*)/i
    );

    sections.push(
      imdMatch
        ? (prefix ? `${prefix}\n\n集成多模态描述 (integrated_multimodal_description):\n${imdMatch[1].trim()}` : `集成多模态描述 (integrated_multimodal_description):\n${imdMatch[1].trim()}`)
        : `集成多模态描述 (integrated_multimodal_description):\n[Shot 1] ${input.videoScript}`
    );
    sections.push(
      osMatch ? `整体环境音 (overall_soundscape): ${osMatch[1].trim()}` : `整体环境音 (overall_soundscape): ${input.soundDesign || "N/A"}`
    );
    sections.push(
      nmMatch ? `非叙事音乐 (non_diegetic_music): ${nmMatch[1].trim()}` : `非叙事音乐 (non_diegetic_music): ${input.musicCue || "N/A"}`
    );
  } else {
    const imd = body.match(/integrated_multimodal_description:\s*([\s\S]*?)(?=\n\s*overall_soundscape:|\n\s*non_diegetic_music:|$)/i);
    const os = body.match(/overall_soundscape:\s*([\s\S]*?)(?=\n\s*non_diegetic_music:|$)/i);
    const nm = body.match(/non_diegetic_music:\s*([\s\S]*)/i);

    sections.push(
      imd
        ? (prefix ? `${prefix}\n\nintegrated_multimodal_description:\n${imd[1].trim()}` : `integrated_multimodal_description:\n${imd[1].trim()}`)
        : `integrated_multimodal_description:\n[Shot 1] ${input.videoScript}`
    );
    sections.push(
      os ? `overall_soundscape: ${os[1].trim()}` : `overall_soundscape: ${input.soundDesign || "N/A"}`
    );
    sections.push(
      nm ? `non_diegetic_music: ${nm[1].trim()}` : `non_diegetic_music: ${input.musicCue || "N/A"}`
    );
  }

  return sections;
}