/**
 * User-message builder for the `ref_image_prompts` AI call.
 *
 * NOTE: The system prompt is NOT defined here — it lives in
 * `registry.ts` under `refImagePromptsDef` (single source of truth, also
 * exposed in the prompt management UI so users can override it).
 * This file only constructs the per-request user payload: visual style,
 * character context (for reasoning, not drawing), and shot list.
 */

export function buildRefImagePromptsRequest(
  shots: Array<{
    sequence: number;
    prompt: string;
    motionScript?: string | null;
    cameraDirection?: string | null;
    duration?: number | null;
  }>,
  characters: Array<{ name: string; description?: string | null }>,
  visualStyle?: string
): string {
  // Characters are passed as CONTEXT for the AI to reason about which
  // characters will act in which shot → populates the `characters` field
  // in the JSON output. The scene prompts themselves must NOT depict any
  // characters.
  const charContext = characters
    .map((c) => `- ${c.name}${c.description ? `：${c.description}` : ""}`)
    .join("\n");

  const shotDescriptions = shots
    .map((s) => {
      const duration = s.duration ?? 10;
      const lines = [
        `镜头 ${s.sequence}（时长 ${duration}s）：${s.prompt}`,
      ];
      if (s.motionScript) lines.push(`  剧情动作（用于判断角色所处的物理地点，不要画人）：${s.motionScript}`);
      if (s.cameraDirection) lines.push(`  镜头运动：${s.cameraDirection}`);
      return lines.join("\n");
    })
    .join("\n\n");

  return [
    visualStyle ? `项目视觉风格基调：${visualStyle}` : "",
    ``,
    `角色列表（仅用于思考：（1）他们所处的物理地点决定场景（2）判断哪些角色在每个镜头登场。图像 prompt 中不要提及他们）：`,
    charContext || "（无）",
    ``,
    `## 什么是"场景图"`,
    `场景图 = **角色所在的物理地点 / 环境空间**（例如：太和殿广场、竹林深处、悬崖边缘、破败宫门前、禅房内部）。`,
    `场景图**不是**：抽象特效（能量光、烙印闪耀）、单独的道具特写（只有一把剑、只有一个符咒）、角色肖像、人物配饰。`,
    `判断标准：如果你只看这张图能说出"这是一个 XX 地方"，那就是场景图；如果只能说出"这是一团光/一个物件"，那就不是。`,
    ``,
    `## 场景图数量（默认 1 条，最多 4 条）`,
    `**默认每个镜头只生成 1 条场景图**——角色所在的那个地点，就是这个镜头的场景。`,
    `只有以下情况才生成多条（最多 4 条）：`,
    `- **角色在镜头内跨越不同物理地点**：例如打斗从地面打到空中（竹林地面 → 竹梢高空）、追逐从室内冲到室外（书房 → 走廊 → 庭院）、从桥上跳入水下（桥面 → 水下）`,
    `- **场景光线/时间大幅跳变**：黄昏→深夜、室内昏暗→走出室外强光`,
    `一般的对话、站立、近景特写、蓄力、挥拳爆发、开门、转身这类**单一地点内的动作节拍**，只需要 1 条场景图——后续视频生成会在这同一个地点里完成所有节拍。`,
    ``,
    `## 分镜列表`,
    shotDescriptions,
    ``,
    `再次强调：`,
    `- 默认每镜头 1 条场景图，只有角色跨越物理地点时才 >1 条，**上限 4 条**`,
    `- 场景图必须是"地点/环境"，不是"特效/道具/光效/符号"`,
    `- 图像中不出现任何人物（没有人、没有背影、没有剪影、没有手脚）`,
    `- characters 字段必须列出会在此镜头登场的角色名，名字要和上方角色列表完全一致`,
    `- 禁止真实人名（导演/演员/艺术家/品牌/IP）——违反会导致图像 API 400 报错`,
    `- 输出格式严格按 system prompt 要求的 scenes 数组（{ name, prompt }），无 markdown 包裹`,
  ]
    .filter(Boolean)
    .join("\n");
}
