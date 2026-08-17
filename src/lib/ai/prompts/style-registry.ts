/**
 * Canonical Style Registry — single source of truth for all visual/era/mood
 * guidance across the entire AICF pipeline (C → D → S → H3).
 *
 * Three dimensions:
 *   visualStyle  — canonical enum (12 options), maps to H3 + S phase
 *   eraAesthetic — guided free-text with categorization hints
 *   moodDirection — guided free-text with arc pattern templates
 *
 * Usage:
 *   C phase:   buildAssessStyleOptions() / buildEraAestheticGuide() / buildMoodDirectionGuide()
 *              → injected into Registry project_assess slot as seed text
 *   S phase:   buildStyleMappingBlock() → replaces themeStyleMappingBlock() in 6 slots
 *   H3 phase:  mapStyleToH3(key) → runtime lookup
 */

// ═══════════════════════════════════════════════════
// Dimension 1: visualStyle (canonical enum, 12 options)
// ═══════════════════════════════════════════════════

export interface CanonicalStyle {
  key: string;
  label: string;
  description: string;
  qualityHint: string;
  h3Style: "Cinematic" | "live-action" | "2D-animated" | "3D CG" | "claymation" | "watercolor" | "vintage film";
  themes: string[];
}

export const VISUAL_STYLE_ENTRIES: CanonicalStyle[] = [
  { key: "cinematic-realistic", label: "写实电影", description: "写实真人电影摄影，胶片颗粒质感，自然肤质与真实材质，85mm浅景深", qualityHint: "电影级写实质感", h3Style: "Cinematic", themes: ["现实", "都市", "人物", "历史正剧", "战争/军事", "现实主义/文艺"] },
  { key: "3d-cg-pixar", label: "3D CG", description: "3D CG渲染，皮克斯/迪士尼风格，PBR材质高精度，全局光照", qualityHint: "3D CG高精度渲染", h3Style: "3D CG", themes: ["科幻", "奇幻/西方魔法", "美食/广告", "喜剧"] },
  { key: "3d-guoman", label: "3D 国漫", description: "3D国漫渲染风格，中国仙侠概念设计，细腻材质与体积光，敦煌壁画色彩体系", qualityHint: "3D国漫仙侠质感", h3Style: "3D CG", themes: ["仙侠", "修真", "玄幻", "国漫", "奇幻/仙侠"] },
  { key: "anime-japanese", label: "日漫赛璐珞", description: "日漫赛璐珞风格，新海诚柔光与高饱和色彩，吉卜力自然风可选", qualityHint: "日漫赛璐珞风格", h3Style: "2D-animated", themes: ["日系动漫", "言情"] },
  { key: "anime-american", label: "美漫风格", description: "美漫风格，强烈线条与明暗对比，超级英雄视觉语言，半色调网点", qualityHint: "美漫英雄风格", h3Style: "2D-animated", themes: [] },
  { key: "comic-hk", label: "港漫画风", description: "港漫画风，强烈动态线条与武术美学，水墨与CG结合，招式特效华丽", qualityHint: "港漫武打风格", h3Style: "2D-animated", themes: [] },
  { key: "ink-wash", label: "水墨写意", description: "水墨写意风格，中国风工笔画，讲究线条与留白，古典绘画质感，金碧山水可选", qualityHint: "水墨工笔质感", h3Style: "watercolor", themes: ["古风", "历史"] },
  { key: "watercolor", label: "水彩手绘", description: "水彩手绘风格，柔和色调与自然晕染，轻盈通透，手绘温度感", qualityHint: "水彩手绘质感", h3Style: "watercolor", themes: [] },
  { key: "paper-cut", label: "剪纸定格", description: "剪纸定格动画风格，层叠质感与传统美学，皮影戏光影效果可选", qualityHint: "剪纸定格风格", h3Style: "claymation", themes: [] },
  { key: "live-action", label: "真人实拍", description: "真人实拍/电影摄影风格，自然光与真实环境，纪录片质感", qualityHint: "真人实拍质感", h3Style: "live-action", themes: [] },
  { key: "vintage-film", label: "复古胶片", description: "复古胶片质感，褪色彩色或黑白，年代感强烈，柯达/富士胶片模拟", qualityHint: "复古胶片质感", h3Style: "vintage film", themes: [] },
  { key: "cyberpunk", label: "赛博朋克", description: "未来科幻写实CG，霓虹灯光与硬表面材质，雨夜金属反光，全息投影与粒子特效", qualityHint: "赛博朋克质感", h3Style: "Cinematic", themes: ["赛博朋克", "未来", "恐怖/惊悚"] },
];

// ═══════════════════════════════════════════════════
// Dimension 2: eraAesthetic (guided free-text template)
// ═══════════════════════════════════════════════════

export interface EraCategory {
  key: string;
  label: string;
  description: string;
  /** Common visual markers that help identify this era */
  markers: string[];
  /** Typical social structures */
  socialStructures: string[];
}

export const ERA_CATEGORIES: EraCategory[] = [
  {
    key: "ancient-china",
    label: "古代中国",
    description: "唐风/宋韵/明制/清代 — 传统中式建筑、服饰、礼制、器物",
    markers: ["木构建筑飞檐斗拱", "丝绸/棉麻服装层次分明", "园林/山水/屏风/卷轴", "兵器冷兵器为主", "灯笼/烛光照明"],
    socialStructures: ["皇权-官僚-士绅-庶民 阶层分明", "家族宗法体系", "科举制度"],
  },
  {
    key: "medieval-west",
    label: "西方中世纪/古典",
    description: "欧洲中世纪/古希腊罗马/文艺复兴 — 石构建筑、骑士文化、宗教主导",
    markers: ["石砌城堡/哥特教堂", "铠甲/长袍/束腰", "烛台/壁炉/挂毯", "羊皮纸/羽毛笔/纹章"],
    socialStructures: ["封建领主-骑士-农奴", "教会权威", "行会制度"],
  },
  {
    key: "early-modern",
    label: "近代 (1800-1950)",
    description: "清末民初/民国/维多利亚/工业革命 — 东西方碰撞、社会巨变",
    markers: ["中西合璧建筑", "旗袍/长衫/西装", "电车/黄包车/蒸汽火车", "报纸/电报/留声机", "霓虹灯/煤油灯过渡"],
    socialStructures: ["殖民/半殖民地体系", "新兴资产阶级崛起", "传统与现代化冲突"],
  },
  {
    key: "modern-contemporary",
    label: "现代当代 (1950-至今)",
    description: "新中国/改革开放/当代都市 — 现代化进程中的社会变迁",
    markers: ["钢筋混凝土城市", "现代时装/制服", "汽车/手机/互联网", "LED/荧光灯照明", "消费主义符号"],
    socialStructures: ["城市化进程", "阶层流动", "信息社会"],
  },
  {
    key: "near-future",
    label: "近未来 (2030-2100)",
    description: "赛博朋克/后赛博朋克/气候危机 — 科技加速但未脱离当代人类形态",
    markers: ["霓虹全息广告", "义体改造/可穿戴设备", "摩天楼贫民窟垂直分层", "无人机/自动驾驶", "酸雨/雾霾/极端气候"],
    socialStructures: ["企业寡头 vs 底层", "AI 治理", "环境难民"],
  },
  {
    key: "far-future",
    label: "远未来/太空",
    description: "星际文明/后人类/戴森球 — 超越当代科技范式",
    markers: ["太空站/外星殖民地", "能量武器/力场护盾", "光速旅行/星门", "外星生态/异星地貌", "后稀缺经济"],
    socialStructures: ["星系联邦/帝国", "AI 与人类共存/对立", "物种进化分支"],
  },
  {
    key: "fantasy-constructed",
    label: "架空世界",
    description: "完全虚构的世界观 — 需从原文推断其美学谱系",
    markers: ["混合时代元素", "独特物理/魔法法则", "虚构种族/文明", "原创建筑/服饰体系"],
    socialStructures: ["需从原文推断", "通常包含独特的权力体系"],
  },
];

/** Era judgment hints for LLM prompt — how to determine era from text */
export const ERA_JUDGMENT_HINTS = `### 时代判断依据（按优先级排序）

1. **器物**: 文中出现的工具、交通工具、武器、通信手段、科技产品
   - 马车/蒸汽机/汽车/飞行器 → 时代分水岭
   - 书信/电报/电话/手机 → 通信水平锚定时代

2. **服饰**: 服装材质、款式、社会身份的视觉标识
   - 长袍/西装/T恤 → 时代窗口
   - 丝绸/化纤/智能面料 → 技术水平

3. **建筑**: 建筑风格、材料、城市形态
   - 木构/砖石/钢筋混凝土/玻璃幕墙 → 时代+地域

4. **社会结构**: 权力体系、阶级关系、性别角色
   - 皇权/民主/企业/AI 治理

5. **自然环境**: 气候描述、生态系统状态、天象
   - 正常气候/极端气候/外星环境

输出格式: 时代定位 + 美学特征 + 视觉参考，一行 ≤50字
示例: "1960年代老上海，弄堂烟火气与旗袍风情，褪色柯达胶片色调"
      "古代唐风盛世，敦煌壁画色彩体系，金碧山水美学"
      "近未来赛博2077，霓虹废土美学，雨夜金属反光"
      "架空仙侠世界，唐宋美学+道教符箓，飘渺云雾与灵石光泽"`;

// ═══════════════════════════════════════════════════
// Dimension 3: moodDirection (guided free-text template)
// ═══════════════════════════════════════════════════

export interface MoodArcPattern {
  key: string;
  label: string;
  description: string;
  /** How this mood arc maps to soundscape direction in S3 */
  soundscapeHint: string;
  /** Example outputs */
  examples: string[];
}

export const MOOD_ARC_PATTERNS: MoodArcPattern[] = [
  {
    key: "consistent-warm",
    label: "统一温暖基调",
    description: "从头至尾保持一种温暖、治愈、或宁静的情感氛围",
    soundscapeHint: "温和环境音为主，音乐舒缓，避免尖锐音效。人声柔和、节奏缓慢。",
    examples: [
      "怀旧温情中夹杂淡淡哀伤，底色是化不开的乡愁",
      "平和宁静的田园诗意，偶尔泛起生活的小确幸",
      "治愈温暖，像冬日里的一杯热茶",
    ],
  },
  {
    key: "consistent-dark",
    label: "统一压抑/悬疑基调",
    description: "全程保持紧张、压抑、或神秘的氛围，不给观众喘息",
    soundscapeHint: "低频持续音垫底，环境音稀疏但有威胁感，音乐用弦乐长音和不和谐和弦。",
    examples: [
      "全程紧绷的压迫感，每一步都像踩在刀尖上",
      "阴郁压抑的末日氛围，希望若有若无",
      "悬疑层层递进，真相永远差最后一步",
    ],
  },
  {
    key: "ascent",
    label: "渐强弧线（压抑→爆发）",
    description: "从低谷出发，逐步升级，最终在高潮处爆发或释放",
    soundscapeHint: "前期安静、低声 → 中期加入节奏性元素 → 高潮处全声道展开。音乐从单乐器到全编制。",
    examples: [
      "从压抑隐忍到爆发决绝，小人物反抗命运的史诗感",
      "从迷惘无助到觉醒崛起，热血燃向的成长之路",
      "绝境求生 → 拼死一搏 → 最后的胜利",
    ],
  },
  {
    key: "descent",
    label: "渐弱弧线（辉煌→陨落）",
    description: "从高处坠落，逐步失去，最终在低谷中沉思或毁灭",
    soundscapeHint: "前期饱满宏大 → 中期声音层次剥离 → 后期只剩单一元素。音乐从史诗到悲凉。",
    examples: [
      "史诗般的壮阔悲凉，英雄末路的苍茫感",
      "从意气风发到穷途末路，理想主义者的悲剧",
      "繁华落尽后的沉寂，功成名就后的空虚",
    ],
  },
  {
    key: "oscillating",
    label: "起伏跌宕（喜悲交替）",
    description: "情绪多次转换，大喜大悲穿插，节奏紧凑",
    soundscapeHint: "音频动态范围大，频繁切换。乐章节拍清晰，音效节奏快。",
    examples: [
      "悲喜交织的命运过山车，你永远不知道下一秒是哭是笑",
      "热血与泪水交替，燃点与泪点密集穿插",
    ],
  },
  {
    key: "mystery-reveal",
    label: "悬疑揭露（未知→真相）",
    description: "从不完整的信息开始，逐步揭示真相，伴随紧张感的起伏",
    soundscapeHint: "大量使用留白和突然的音效。音乐用迷离的合成器垫音, 揭示时刻用清晰的旋律。",
    examples: [
      "疑云密布 → 抽丝剥茧 → 真相大白",
      "每一个线索都是假象，最后一块拼图颠覆一切",
    ],
  },
];

/** Mood judgment hints for LLM prompt */
export const MOOD_JUDGMENT_HINTS = `### 情绪基调判断依据

1. **叙事语气**: 叙述者的态度 — 冷眼旁观/深情投入/讽刺挖苦/悲悯同情
2. **冲突类型**: 人与人的对抗/人与社会的冲突/人与自己的挣扎/人与自然的搏斗
3. **节奏控制**: 快节奏/慢节奏/先慢后快/快慢交替
4. **结局暗示**: 胜利/失败/和解/开放/悲剧

输出格式: 一行 ≤40字，描述整体走向
示例: "怀旧温情中夹杂淡淡哀伤"
      "从压抑隐忍到爆发决绝，全程紧绷"
      "悲喜交织的命运过山车，燃点与泪点密集"`;

// ═══════════════════════════════════════════════════
// Lookup maps
// ═══════════════════════════════════════════════════

const visualByKey = new Map(VISUAL_STYLE_ENTRIES.map(s => [s.key, s]));
const visualByTheme = new Map<string, CanonicalStyle>();
for (const s of VISUAL_STYLE_ENTRIES) {
  for (const t of s.themes) {
    if (!visualByTheme.has(t)) visualByTheme.set(t, s);
  }
}
const eraByKey = new Map(ERA_CATEGORIES.map(e => [e.key, e]));
const moodByKey = new Map(MOOD_ARC_PATTERNS.map(m => [m.key, m]));

// ═══════════════════════════════════════════════════
// Public API — visualStyle
// ═══════════════════════════════════════════════════

export function getStyle(key: string): CanonicalStyle | undefined {
  return visualByKey.get(key);
}

export function inferStyleFromGenre(genre?: string): CanonicalStyle {
  if (!genre) return visualByKey.get("cinematic-realistic")!;
  const matched = visualByTheme.get(genre);
  if (matched) return matched;
  for (const [theme, style] of visualByTheme) {
    if (genre.includes(theme) || theme.includes(genre)) return style;
  }
  return visualByKey.get("cinematic-realistic")!;
}

export function mapStyleToH3(key: string): "Cinematic" | "live-action" | "2D-animated" | "3D CG" | "claymation" | "watercolor" | "vintage film" {
  return visualByKey.get(key)?.h3Style ?? "Cinematic";
}

/** Match a free-text visualStyle description to the closest canonical key */
export function matchVisualStyleKey(freeText: string): string {
  const lower = freeText.toLowerCase();
  let bestKey = "cinematic-realistic";
  let bestScore = 0;
  for (const s of VISUAL_STYLE_ENTRIES) {
    let score = 0;
    if (lower.includes(s.label)) score += 10;
    for (const word of s.description.split(/[,，、]/)) {
      if (lower.includes(word.trim())) score += 1;
    }
    for (const t of s.themes) {
      if (lower.includes(t)) score += 2;
    }
    if (score > bestScore) { bestScore = score; bestKey = s.key; }
  }
  return bestKey;
}

// ═══════════════════════════════════════════════════
// Public API — eraAesthetic
// ═══════════════════════════════════════════════════

export function getEraCategory(key: string): EraCategory | undefined {
  return eraByKey.get(key);
}

// ═══════════════════════════════════════════════════
// Public API — moodDirection
// ═══════════════════════════════════════════════════

export function getMoodPattern(key: string): MoodArcPattern | undefined {
  return moodByKey.get(key);
}

// ═══════════════════════════════════════════════════
// Prompt text generators (for Registry slot seeding)
// ═══════════════════════════════════════════════════

/** Build the visualStyle options block for the project_assess prompt */
export function buildAssessStyleOptions(): string {
  const lines = VISUAL_STYLE_ENTRIES.map(s => `- ${s.label}: ${s.description}`);
  return `画风类型（从以下选择最匹配的）:\n${lines.join("\n")}\n- 其他（自定义，需具体描述）`;
}

/** Build the eraAesthetic guidance block for the project_assess prompt */
export function buildEraAestheticGuide(): string {
  const eraLines = ERA_CATEGORIES.map(e =>
    `- ${e.label}: ${e.description}\n  标志: ${e.markers.slice(0, 3).join(" / ")}`
  );
  return `### 2. eraAesthetic — 时代美学

${ERA_JUDGMENT_HINTS}

时代分类参考（帮助定位，不强制选择）:
${eraLines.join("\n")}`;
}

/** Build the moodDirection guidance block for the project_assess prompt */
export function buildMoodDirectionGuide(): string {
  const moodLines = MOOD_ARC_PATTERNS.map(m =>
    `- ${m.label}: ${m.description}\n  示例: ${m.examples[0]}`
  );
  return `### 3. moodDirection — 整体情绪基调

${MOOD_JUDGMENT_HINTS}

情绪弧线分类参考（帮助定位，不强制选择）:
${moodLines.join("\n")}`;
}

/** Build the full dimensions block (replaces PROJECT_ASSESS_DIMENSIONS hardcode) */
export function buildAssessDimensionsFull(): string {
  return [
    buildAssessStyleOptions(),
    "",
    buildEraAestheticGuide(),
    "",
    buildMoodDirectionGuide(),
  ].join("\n");
}

/** Build theme→style mapping block for S phase prompts */
export function buildStyleMappingBlock(): string {
  const lines = VISUAL_STYLE_ENTRIES
    .filter(s => s.themes.length > 0)
    .map(s => `- ${s.themes.join("/")} → ${s.label}: ${s.qualityHint}`);
  return `**项目画风 → 视觉风格映射表**（C/S全流水线共用）:\n${lines.join("\n")}\n\n画风判定原则:\n1. 优先遵循项目设置里显式指定的视觉风格\n2. 若未指定，按题材类型匹配上表\n3. 永远不要默认写实——必须主动判断`;
}

// ═══════════════════════════════════════════════════
// Schema helpers
// ═══════════════════════════════════════════════════

export const VISUAL_STYLE_KEYS = VISUAL_STYLE_ENTRIES.map(s => s.key) as readonly string[];
export type VisualStyleKey = (typeof VISUAL_STYLE_KEYS)[number];

export const VISUAL_STYLE_LABELS = VISUAL_STYLE_ENTRIES.map(s => ({ key: s.key, label: s.label }));
export const ERA_CATEGORY_LABELS = ERA_CATEGORIES.map(e => ({ key: e.key, label: e.label }));
export const MOOD_PATTERN_LABELS = MOOD_ARC_PATTERNS.map(m => ({ key: m.key, label: m.label }));