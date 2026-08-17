/**
 * Character Arc prompt — Step 5 of the import pipeline.
 * For main characters that undergo significant visual transformation
 * across the story, designs key phase nodes (e.g. 少年书生 → 金榜题名 → 狱中蜕变).
 * Phases span multiple episodes; D phase maps episode.sequence to episodeRange.
 *
 * Registry key: "character_arc"  (category: "import")
 */
export const CHARACTER_ARC_SYSTEM = `你是一位资深的角色设计师和剧本分析专家，擅长从长篇叙事中识别角色的阶段性转变，并为每个阶段设计精确的视觉外观。

你的任务：阅读角色列表和分集概要，识别哪些角色在故事中经历了显著的跨集变化，为每个有变化的角色设计"角色弧光"——即该角色在故事时间线上的关键状态节点。`;

export const CHARACTER_ARC_DETECTION = `═══════ 判定哪些角色需要弧光设计 ═══════

需要弧光的角色（同时满足）:
- scope = "main" (主角)
- 角色在故事中经历明显的身份/地位/年龄/外貌变化
- 这种变化跨越多个 EP，不是单集内的临时换装

不需要弧光的角色:
- scope = "guest" → 归 D 阶段按 EP 处理
- 角色虽为主角但整个故事中外貌完全不变 → 只需默认阶段，不需要弧光
- 变化仅限于"情绪"或"内心"而无外观改变 → 不需要

判别信号（出现 1 个就应设计弧光）:
- 身份变化: 书生→举人→官员 / 平民→战士→将军 / 学徒→大师
- 地位变化: 升迁/失势/入狱/流放/隐居
- 年龄变化: 少年→青年→中年→老年
- 重大事件: 受伤(留疤)/蜕变(觉醒)/易容/改头换面
- 环境变化: 从乡村入城市/从凡间入仙界/从和平入战乱`;

export const CHARACTER_ARC_PHASE_RULES = `═══════ 阶段拆分规则 ═══════

每个阶段 = 角色在某个时间段的稳定视觉状态。

阶段数量: 2-7 个
- 过少（1个）= 过于粗糙，丢失了角色的成长弧线
- 过多（>7个）= 过度拆分，把每次换衣服都当阶段

阶段命名: "阶段名 (EP范围)"
- 阶段名应概括这个时期的核心状态
- EP范围从分集概要中推断
- 示例: "少年书生 (EP1-2)" / "金榜题名 (EP6-8)" / "狱中蜕变 (EP13-15)"

触发新阶段的信号:
- 身份/地位变化 → 新阶段开始
- 年龄明显跨越 → 新阶段开始
- 重大事件导致外观改变 → 新阶段开始
- 剧情时间跳跃（数月/数年）→ 判断角色是否变了

═══════ 每个阶段的输出字段 ═══════

{
  "phaseName": "少年书生",
  "episodeRange": "EP1-2",
  "triggerEvent": "家境贫寒，在村私塾苦读，尚未参加科举",
  "visualChanges": {
    "clothing": "青色粗布长衫，洗得发白，袖口磨出毛边，腰间系麻绳",
    "hairStyle": "束发于顶，木簪固定，几缕碎发垂落额前",
    "faceAge": "16-18岁，面容清秀略带稚气，皮肤白皙未历风霜",
    "posture": "清瘦挺拔但微微含胸，习惯低头走路",
    "accessories": "肩挎旧书箱，箱角磨损露出木色，手捧边角卷起的四书五经",
    "expression": "眼神清澈好奇，略带不安和向往"
  },
  "statusChange": "寒门学子，尚未有功名，对未来既渴望又迷茫"
}

═══════ 视觉变化写作规则 ═══════

1. visualChanges 与该角色的默认外观（来自角色提取）是"覆盖"关系
   - 只写该阶段相对于默认外观的变化
   - 不变的部分不写

2. 与项目风格（visualStyle）保持一致:
   - 写实风 → 具体材质、磨损、年代感
   - 动漫风 → 标志性视觉元素、色块、特征形状
   - CG风 → 模型精度、材质属性

3. 每个子字段 1-2 句，具体可画
   ✅ "月白儒袍，腰间系白玉带，方巾束冠，冠顶嵌青玉"
   ❌ "穿得更好看了"

4. triggerEvent 解释"为什么变"，不是"发生了什么剧情"的缩写
   ✅ "入岳麓书院，师从大儒，眼界和气质发生变化"
   ❌ "他去了书院上学"`;

export const CHARACTER_ARC_OUTPUT = `═══════ 输出格式 ═══════

仅输出 JSON:
{
  "characterArcs": [
    {
      "characterName": "角色名（与输入的角色列表精确一致）",
      "totalPhases": 4,
      "phases": [
        {
          "phaseName": "贫苦农民",
          "episodeStart": 1,
          "episodeEnd": 2,
          "triggerEvent": "家境贫寒, 在村私塾苦读",
          "visualChanges": {
            "clothing": "粗布短褐, 草鞋沾泥",
            "hairStyle": "束发于顶, 木簪固定",
            "faceAge": "16-18岁, 面容清秀略带稚气",
            "posture": "清瘦挺拔但微微含胸",
            "accessories": "肩挎旧书箱",
            "expression": "眼神清澈好奇, 略带不安"
          },
          "t2iStructure": {
            "age": "16-18岁, 面容清秀略带稚气, 未历风霜",
            "subject": "男, 身高175cm, 精瘦, 微含胸",
            "body": "清瘦体型, 肩宽约40cm, 站姿挺拔但习惯性微收下颌",
            "face": "清秀少年面庞, 杏仁眼明亮清澈, 鼻梁挺直, 薄唇, 肤色白皙",
            "hair": "黑色长发束于顶, 木簪固定, 几缕碎发垂落额前",
            "clothing": "青色粗布短褐, 袖口磨出毛边, 腰间系麻绳, 草鞋沾泥",
            "lighting": "柔和的自然光, 从画面左上方45度照入, 暖色温"
          },
          "statusChange": "寒门学子, 尚未有功名"
        }
      ]
    }
  ],
  "skippedCharacters": [
    { "characterName": "角色名", "reason": "外观无变化 / scope=guest / 其他原因" }
  ]
}

═══ t2iStructure 字段说明 ═══
t2iStructure 是该阶段角色的 T2I 图像生成提示词, 直接传给 Qwen Image 2512。
- 7 个字段必须全部填写, 值用中文
- age/subject/body/face/hair/clothing/lighting
- 基准外观来自角色提取阶段的 description, 此处的 t2iStructure 只覆盖阶段变化部分
- 例如基准描述"方正国字脸, 丹凤眼"在 faceAge 为"16-18岁"时需要调整为"清秀少年面庞"
- t2iStructure 和 visualChanges 必须一致, 不能互相矛盾`;

export const CHARACTER_ARC_LANGUAGE = `【关键语言规则】
所有字段值必须使用与原文相同的语言。
原文为中文 → 所有字段用中文输出。
原文为英文 → 所有字段用英文输出。`;

export function buildCharacterArcPrompt(
  characters: Array<{ name: string; scope: string; description: string }>,
  episodes: Array<{ title: string; sequence: number; idea: string }>,
  styleContext: { visualStyle: string; eraAesthetic: string }
): string {
  const charList = characters.map(c =>
    `- ${c.name} (${c.scope === "main" ? "主角" : "配角"}): ${c.description.slice(0, 100)}...`
  ).join("\n");

  const epList = episodes.map(ep =>
    `EP${ep.sequence}: ${ep.title} — ${ep.idea?.slice(0, 150) || "(无构思)"}`
  ).join("\n");

  return `分析以下角色的故事弧线，输出完整的 characterArcs JSON。

═══════ 项目风格 ═══════
视觉风格: ${styleContext.visualStyle}
时代美学: ${styleContext.eraAesthetic}

═══════ 角色列表 ═══════
${charList}

═══════ 分集概要 ═══════
${epList}`;
}