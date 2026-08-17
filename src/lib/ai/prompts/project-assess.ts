import { buildAssessDimensionsFull } from "./style-registry";

/**
 * Project Assessment prompt — Step 2 of the import pipeline.
 * Determines visual style, era, mood, and world-building direction
 * for the entire project from a sample of the source text.
 *
 * Style options and guidance are generated from style-registry.ts
 * to ensure consistency with C/S/H3 phases.
 *
 * Registry key: "project_assess"  (category: "import")
 */
export const PROJECT_ASSESS_SYSTEM = `你是一位资深影视美术指导和创意总监，拥有20年以上的电影、动画和剧集美术设计经验。

你的任务：通读一部作品的前端文本（前几千字），一次性输出完整、精确、可直接用于制作的项目定位书。`;

/**
 * Dimensions block — auto-generated from style-registry.
 * Exported as a function so it reflects changes to the registry.
 * The Registry slot stores the rendered text; this function provides the initial seed.
 */
export function getAssessDimensions(): string {
  return `═══════ 分析维度 ═══════

${buildAssessDimensionsFull()}`;
}

export const PROJECT_ASSESS_OUTPUT = `═══════ 输出格式 ═══════

仅输出 JSON，无 markdown、无注释：
{
  "visualStyle": "写实真人电影摄影，胶片颗粒质感，85mm浅景深",
  "eraAesthetic": "1960年代老上海，弄堂烟火气与旗袍风情",
  "moodDirection": "怀旧温情中夹杂淡淡哀伤",
  "worldSetting": "1960年代上海弄堂，社会剧烈变迁中...",
  "genre": "历史正剧",
  "targetAudience": "全年龄，偏好年代剧与人文关怀题材"
}

═══════ 判断优先级 ═══════

1. 原文有明确的风格/时代标识 → 优先使用原文 (忠实于作者)
2. 原文暗含风格但未明说 → 从叙事密度、角色类型、场景描写推断
3. 完全无风格信号 → 根据题材类型选择合理的默认值

═══════ 自检清单 ═══════
- visualStyle 含画风类型 + 质感描述?
- eraAesthetic 含时代定位 + 美学特征?
- moodDirection 是整体走向而非逐场景罗列?
- worldSetting 100-200字且涵盖背景/结构/冲突?
- genre/targetAudience 来自预定义列表?
- 所有字段值 ≤ 规定字符数?`;

export const PROJECT_ASSESS_LANGUAGE = `【关键语言规则】
所有字段值必须使用与原文相同的语言。
原文为中文 → 所有字段用中文输出。
原文为英文 → 所有字段用英文输出。
JSON 键名固定为英文。`;

export function buildProjectAssessPrompt(sampleText: string): string {
  return `分析以下作品的全局定位，输出完整的项目定位 JSON。

--- 正文前段 ---
${sampleText}
--- 结束 ---`;
}