/**
 * Reusable prompt building blocks.
 * Extracted from duplicated text across multiple prompt templates.
 */

export function artStyleBlock(): string {
  return `## 画风一致性
- 在所有生成的图像中保持项目"视觉风格"部分定义的视觉风格
- 风格要素包括：渲染技法、色彩方案、光照氛围、质感品质
- 不得在同一项目中混用风格（例如：不得将写实角色放在卡通背景中）
- 如果声明了特定画风（动漫、写实、水彩等），所有帧都必须匹配`;
}

export function referenceImageBlock(): string {
  return `## 参考图使用规则
- 参考图定义了角色的标准外观
- 必须匹配：脸型、发型/发色、瞳色、肤色、服装细节、配饰
- 可调整：姿势、表情、角度——这些随镜头变化
- 绝不违背参考图中的核心身份特征`;
}

export function languageRuleBlock(defaultLang?: string): string {
  return `## 关键语言规则
输出必须与输入语言一致。如果用户使用中文书写，则全部以中文回复。如果使用英文，则全部以英文回复。不得在输出中混用语言。${
    defaultLang ? `\n语言不明确时的默认语言：${defaultLang}` : ""
  }`;
}

/**
 * Shared theme → art style mapping used by character_image, ref_image_prompts,
 * frame_generate_first, and scene_frame_generate. Single source of truth to
 * prevent style drift across the pipeline (角色图/参考图/首帧图).
 */
export function themeStyleMappingBlock(): string {
  return `**主题 → 画风自动映射表**（全流水线共用，确保角色图/参考图/首帧图画风一致）：
- 仙侠/修真/玄幻 → 3D 国漫渲染风格、中国仙侠概念设计，细腻材质与体积光
- 古风/历史 → 中国风工笔画 / 水墨 / 古典绘画，讲究线条与留白
- 赛博朋克/未来/科幻 → 未来科幻写实 CG、概念设计，硬表面与发光材质
- 现实/都市/人物 → 电影摄影写实风格、胶片质感，自然肤质
- 奇幻/西方魔法 → 西幻概念原画、油画质感
- 日系动漫 → 日漫赛璐珞 / 新海诚柔光 / 吉卜力自然风（按描述细化）
- 国漫 → 国漫 3D 渲染 / 中国新派动画风格
- Q 版/卡通 → 三头身 Q 版、迪士尼/皮克斯卡通风格
- 美食/广告 → 商业广告摄影、微距、柔光棚拍

画风判定原则：
1. 优先遵循剧本或描述里显式指定的画风
2. 若未指定，按主题关键词匹配上表
3. 永远不要默认写实——必须主动判断主题类别`;
}

/**
 * Shared physics/realism constraints used by any image prompt that depicts
 * human figures in realistic settings. Extracted from ref_image_prompts so
 * it can be shared with frame_generate_first/last and scene_frame_generate.
 */
export function physicsRealismBlock(): string {
  return `【⚠️ 严格物理常识约束（最高优先级）】
图像生成模型会按字面理解每一个词。请遵守以下铁律：

1. **绝不使用任何比喻**（动作比喻 和 外观比喻 都禁止）：禁止"如……"、"像……"、"宛如……"、"似……"、"仿佛……"等一切比喻句式——图像模型会按字面把 AI 画成真的比喻物。
   - ❌ 动作比喻："小陈如同矫健的猎豹般从洞口钻出" → ✅ "小陈双手撑地，单膝跪地，从洞口爬出，身体前倾"
   - ❌ 外观比喻："头发乱如杂草" → ✅ "黑色短发参差不齐、多处打结翘起、发梢分叉"
   - ❌ 外观比喻："下颌线如刀削般锋锐" → ✅ "下颌线笔直锋利，棱角分明"
   - ❌ 外观比喻："眼神如鹰般锐利" → ✅ "眯起眼睛，眼角微微上挑，目光聚焦"
   - ❌ 外观比喻："身形如竹" → ✅ "身形纤细笔直，肩宽约40cm"
   - 万一想形容抽象质感（"柔软如丝"、"坚硬如铁"），改写成具体材质+感官描述（"顺滑有光泽的黑发"、"质地坚硬的金属表面"）

2. **写实场景禁止反物理行为**：
   - 人物必须站/坐/走/跑/趴/跪——脚必须接触地面
   - 禁止"半空中"、"飞起"、"漂浮"、"悬空"——除非是科幻/奇幻题材
   - 跳跃必须明确"双脚离地约30cm"等物理细节
   - 禁止"突然出现"、"瞬移"等

3. **必须明确身体姿态**：站立 / 坐姿 / 跪姿 / 蹲姿 / 趴下 / 俯卧 / 仰卧；双脚位置；身体朝向（正面/侧面/背面/3/4 侧）

4. **写实镜头中所有动作都要符合重力**：人物在坠落 → 必须明确"被绳索系住"或"已落到救生垫"；抛物 → 明确起点和落点；烟雾/碎片 → 向上飘散或随重力下落

5. **避免抽象描述**：
   - ❌ "灵动的姿态" → ✅ "右手前伸，左手扶墙，膝盖微弯"
   - ❌ "充满力量感" → ✅ "肩膀前倾，双手紧握扶手，肌肉绷紧"`;
}

/**
 * Shared fidelity block: used by script_parse (fidelity to original text)
 * and shot_split (fidelity from script to shot list). The core principle is
 * "no deletion, no summarization, no paraphrase" — keep the upstream content
 * lossless as it flows through the pipeline.
 */
export function fidelityPrincipleBlock(upstream: string, downstream: string): string {
  return `=== ${upstream} → ${downstream} 保真度（最高优先级）===
核心心态：你是"结构化者"，不是"改编者"。禁止重写、禁止精炼、禁止省略原文内容。
- **对白逐字保留**：语气词（"啊"/"嗯"/"呃"/"……"）、重复、口语化、方言、标点——全部原样保留，禁止"修正"成书面语
- **事件全量落地**：${upstream}里提到的每一个动作、每一个物件、每一个情感转折，都必须在${downstream}里有明确落点
- **角色名不改**：使用${upstream}中出现的原始名字
- **场景宁多勿少**：时间跳跃、地点变化、叙事节拍转折都要拆分，不确定时默认拆分
- 自检：生成完后回头对照${upstream}逐行核查，任何遗漏必须补，不准降低要求`;
}
