# Prompt Registry 深度分析

> 项目：AIComicBuilder（Next.js 16 / AI SDK 6）
> 分析对象：`src/lib/ai/prompts/` 全部 17 个文件（registry.ts 2010 行 + resolver.ts 135 行 + 15 个 build 文件）
> 只读分析，未修改任何源码

---

## 1. Registry 架构总览

### 1.1 文件构成

| 文件 | 行数 | 角色 |
|---|---|---|
| `registry.ts` | 2010 | **单一事实源**：16 个 `PromptDefinition`（不是任务描述中的 12 个，见 1.3）+ slot 分解 + `buildFullPrompt` 重组 |
| `resolver.ts` | 135 | **DB override 解析**：`resolvePrompt()` / `resolveSlotContents()` |
| `blocks.ts` | 98 | 共享提示词块（画风映射/物理约束/保真度等 5 个工厂函数） |
| `presets.ts` | 11 | 内置预设（**当前为空数组**，`BUILT_IN_PRESETS = []`） |
| 其余 13 个文件 | — | 各流水线步骤的 **user 侧 prompt 构建函数** |

### 1.2 核心类型（registry.ts L16-56）

```ts
export interface PromptSlot {
  key: string;             // slot 唯一键
  nameKey: string;         // i18n key（promptTemplates.slots.<camelCase>）
  descriptionKey: string;  // i18n key（...Desc）
  defaultContent: string;  // 默认内容（含中文模板全文）
  editable: boolean;       // 是否允许用户编辑（false = 系统锁定）
}

export interface PromptDefinition {
  key: string;             // 机器键，如 "script_generate"
  nameKey / descriptionKey; // i18n
  category: PromptCategory; // "script" | "character" | "shot" | "frame" | "video"
  slots: PromptSlot[];     // 有序 slot 列表
  buildFullPrompt: (slotContents, params?) => string;  // 重组函数
}
```

### 1.3 ⚠️ 数量修正：Registry 实为 **16 个**模板，非 12 个

`registry.ts` 头注释写 "Decomposes all **12** prompt templates"，但 `PROMPT_REGISTRY`（L1966-1983）实际注册 **16 个** def。任务描述中的"12 个"与代码注释均已过时，以实际注册为准：

```ts
export const PROMPT_REGISTRY: PromptDefinition[] = [
  scriptOutlineDef, scriptGenerateDef, scriptParseDef, scriptSplitDef,
  characterExtractDef, importCharacterExtractDef, characterImageDef,
  shotSplitDef, shotKeyframeAssetsDef, frameGenerateFirstDef, frameGenerateLastDef,
  sceneFrameGenerateDef, refImagePromptsDef, videoGenerateDef,
  refVideoGenerateDef, refVideoPromptDef,
];
```

> 新增的 4 个：`script_outline`（L1805）、`shot_split_keyframe_assets`（L1251）、`ref_video_generate`（L1593）、`ref_video_prompt`（L1742）——均在后缀迭代中追加，头注释未同步。

---

## 2. 16 个模板 × slot 清单全表

（T = editable:true 可编辑，F = editable:false 锁定；行内为 slot 默认内容摘要）

| # | key | category | slots（可编辑标记） | slot 数 |
|---|---|---|---|---|
| 1 | `script_outline` | script | `role_definition`(T)、`output_format`(T)、`writing_rules`(T) | 3 |
| 2 | `script_generate` | script | `role_definition`(T)、`language_rules`(F)、`output_format`(F)、`visual_style_section`(T)、`character_section`(T)、`scene_section`(T)、`screenwriting_principles`(T) | 7 |
| 3 | `script_parse` | script | `role_definition`(T)、`original_fidelity`(T)、`output_format`(F)、`parsing_rules`(T)、`language_rules`(F) | 5 |
| 4 | `script_split` | script | `role_definition`(T)、`splitting_rules`(T)、`idea_requirements`(T)、`language_rules`(F)、`output_format`(F) | 5 |
| 5 | `character_extract` | character | `role_definition`(T)、`style_detection`(T)、`output_format`(F)、`scope_rules`(T)、`description_requirements`(T)、`writing_rules`(T)、`language_rules`(F) | 7 |
| 6 | `import_character_extract` | character | `role_definition`(T)、`extraction_rules`(T)、`output_format`(F) | 3 |
| 7 | `character_image` | character | `style_matching`(T)、`face_detail`(T)、`four_view_layout`(T)、`lighting_rendering`(T)、`consistency_rules`(T)、`name_label`(F) | 6 |
| 8 | `shot_split` | shot | `role_definition`(T)、`script_fidelity`(T)、`output_format`(F)、`start_end_frame_rules`(T)、`motion_script_rules`(T)、`video_script_rules`(T)、`proportional_tiers`(T)、`camera_directions`(T)、`cinematography_principles`(T)、`language_rules`(F) | 10 |
| 9 | `shot_split_keyframe_assets` | shot | `role_definition`(T)、`rules`(T)、`output_format`(F) | 3 |
| 10 | `frame_generate_first` | frame | `style_matching`(T)、`reference_rules`(T)、`rendering_quality`(T)、`continuity_rules`(T) | 4 |
| 11 | `frame_generate_last` | frame | `style_matching`(T)、`relationship_to_first`(T)、`next_shot_readiness`(T)、`rendering_quality`(T) | 4 |
| 12 | `scene_frame_generate` | frame | `reference_rules`(T)、`composition_rules`(T)、`rendering`(T) | 3 |
| 13 | `ref_image_prompts` | frame | `ref_image_role`(T)、`ref_image_rules`(T)、`ref_image_output`(F) | 3 |
| 14 | `video_generate` | video | `interpolation_header`(T)、`dialogue_format`(T)、`frame_anchors`(T) | 3 |
| 15 | `ref_video_generate` | video | `consistency_rules`(T)、`duration_strategy`(T)、`dialogue_format`(T) | 3 |
| 16 | `ref_video_prompt` | video | `role_definition`(T)、`motion_rules`(T)、`quality_benchmark`(T)、`language_rules`(F) | 4 |

**汇总**：16 模板 / 共 **73 个 slot**；其中可编辑 55 个，锁定 18 个（均为 `output_format`、`language_rules`、`name_label` 等结构性/格式性 slot——锁定的共同特征：内容包含机器解析格式或语言约束，用户改动会破坏下游 JSON 解析）。

---

## 3. Slot 重叠分析

### 3.1 同名 slot 跨模板复用矩阵

| slot key | 出现模板 | 次数 |
|---|---|---|
| `role_definition` | script_outline, script_generate, script_parse, script_split, character_extract, import_character_extract, shot_split, shot_split_keyframe_assets, ref_video_prompt | **9** |
| `output_format` | script_generate, script_parse, script_split, character_extract, import_character_extract, shot_split, shot_split_keyframe_assets, ref_image_prompts | **8** |
| `language_rules` | script_generate, script_parse, script_split, character_extract, shot_split, ref_video_prompt | **6** |
| `style_matching` | character_image, frame_generate_first, frame_generate_last | 3 |
| `rendering_quality` | frame_generate_first, frame_generate_last | 2 |
| `consistency_rules` | character_image, ref_video_generate | 2 |
| `dialogue_format` | video_generate, ref_video_generate | 2 |
| 其余（rules、extraction_rules、face_detail、four_view_layout…） | 单模板独有 | 1 |

**结论**：
- `role_definition`（9 处）与 `output_format`（8 处）是**最高频共享 slot**，但**每个模板的默认内容互不相同**——共享的是"键名/编辑语义"，不是内容。DB override 按 `promptKey + slotKey` 精确定位，互不污染。
- 任务点题中的 `character_descriptions` **不是 registry slot**，它是 build 函数（frame-generate.ts / scene-frame-generate.ts）的**动态参数**（见 5.2）——slot 层不存在该键，避免误解。
- 不存在"同名 slot 内容复用"的情况：所有重叠仅发生在命名层面。

### 3.2 模板间的共享提示词块（blocks.ts）

| block 工厂 | 被注入的模板（通过 `slot(...)` 默认内容内嵌） | 说明 |
|---|---|---|
| `themeStyleMappingBlock()` | character_image(L768)、frame_generate_first(L1278)、shot_split_keyframe_assets(L1213) | 主题→画风映射表，"全流水线共用防风格漂移"（注释自述） |
| `physicsRealismBlock()` | frame_generate_first(L1281)、shot_split_keyframe_assets(L1211)、ref_image_prompts(L1854) | 物理常识铁律（禁比喻/禁悬空/明确姿态） |
| `artStyleBlock()` | frame_generate_first(L1280) | 画风一致性 |
| `languageRuleBlock(defaultLang?)` | ref_video_prompt(L1740，附 `\nOutput the prompt only` 追加) | 语言跟随输入 |
| `fidelityPrincipleBlock(up, down)` | **0 处使用**（死代码） | blocks.ts 注释声明"供 script_parse/shot_split 使用"，但两模板实际各自硬编码 `SCRIPT_PARSE_FIDELITY_RULES` / `SHOT_SPLIT_FIDELITY_RULES`，未调用此工厂 |

> ⚠️ `fidelityPrincipleBlock` 是**孤儿函数**：定义为流水线共享块，但 script_parse 与 shot_split 的保真度规则都各自内联为私有常量，未复用——存在"共享意图 vs 实际内联"的漂移，若后续修改保真度规则需改 3 处。

---

## 4. 模板"继承"关系分析（frame_generate_first vs frame_generate_last）

**结论：不存在继承，是"同构平级"关系。**

| 维度 | `frame_generate_first` | `frame_generate_last` |
|---|---|---|
| slot 结构 | style_matching / reference_rules / rendering_quality / continuity_rules | style_matching / relationship_to_first / next_shot_readiness / rendering_quality |
| 共享 slot 键 | `style_matching`、`rendering_quality` | 同左 |
| 共享内容 | 均内嵌 `themeStyleMappingBlock()` + `physicsRealismBlock()`（style_matching 内） | 同左 |
| 独有 slot | `reference_rules`（角色设定图）、`continuity_rules`（衔接上一镜头尾帧） | `relationship_to_first`（与首帧关系）、`next_shot_readiness`（作为下一镜头起点） |
| buildFullPrompt 形态 | `params` 注入 sceneDescription/startFrameDesc/characterDescriptions/previousLastFrame | `params` 注入 sceneDescription/endFrameDesc/characterDescriptions（无 previousLastFrame，用 firstFramePath 作视觉锚点） |

- 两模板通过 `blocks.ts` 的**共享块工厂**获得内容一致性（画风映射表、物理约束、语言规则），通过**相同的 slot 键名**获得结构一致性，但**没有代码层面的 extends/复用**——各 def 完全独立定义。
- 数据流差异：`first` 接收"上一镜头尾帧"做连续性锚点，`last` 接收"本镜头首帧路径"做画风锚点 + "下一镜头起点"要求。

---

## 5. 动态解析路径：resolver.ts 的 DB override 机制

### 5.1 两入口对比

| 函数 | 用途 | 是否调用 buildFullPrompt |
|---|---|---|
| `resolvePrompt(promptKey, {userId, projectId?})` | 返回**完整 system prompt 字符串** | ✅ 是（无 full override 时） |
| `resolveSlotContents(promptKey, options)` | 返回 **slot 内容映射**（不重组） | ❌ 否——供调用方自行传参给 buildXxxPrompt |

### 5.2 优先级链（两函数一致）

```
项目级 full override (scope=project, slotKey=null)  >  全局 full override (scope=global, slotKey=null)
  >  项目级 slot override (scope=project, slotKey=K)  >  全局 slot override (scope=global, slotKey=K)
  >  代码默认值 (getDefaultSlotContents)
```

**关键机制**（resolver.ts L26-49）：
- **full override**：`promptTemplates` 表中 `slotKey IS NULL` 的行 = "高级模式"整段替换。`resolvePrompt` 命中后**直接返回 content**，跳过 slot 分解——即用户可放弃 slot 编辑、整体接管 system prompt。
- **slot override**：按 `Object.keys(slotContents)` 逐 slot 查找 DB 覆盖，找到即替换 `slotContents[slotKey]`，最后 `def.buildFullPrompt(slotContents)`。
- `resolveSlotContents` **不查询 full override**（L103-111 只按 slot 查），因为它用于需要动态参数的模板（frame/video），此时 build 函数会再叠加动态 params。

### 5.3 `buildFullPrompt()` vs 纯 slot 注入

| 模式 | 模板 | 特点 |
|---|---|---|
| **纯 slot 注入**（join 分隔） | script_outline, script_generate, script_parse, script_split, character_extract, import_character_extract, shot_split_keyframe_assets, ref_image_prompts, video_generate, ref_video_generate, ref_video_prompt | `[r("slot1"), "", r("slot2"), ...].join("\n")`，slot 顺序固定 |
| **动态参数 + slot 注入** | shot_split, frame_generate_first, frame_generate_last, scene_frame_generate, character_image | `buildFullPrompt(sc, params)` 读取 `params.*` 填充帧描述/角色描述/时长，再与 slot 内容拼装 |

**动态参数替换点**（registry 内）：

| 模板 | params 字段 | 占位符替换 |
|---|---|---|
| `shot_split` | `maxDuration` | `{{MIN_DURATION}}`/`{{MAX_DURATION}}`/`{{DIALOGUE_MAX}}`/`{{ACTION_MAX}}`/`{{ESTABLISHING_MAX}}`/`{{PROPORTIONAL_TIERS}}`（L1114-1172 计算比例分档并替换） |
| `frame_generate_first` | `sceneDescription`/`startFrameDesc`/`characterDescriptions`/`previousLastFrame` | 直接插入 `=== 场景环境 ===` 等段落（L1331-1344） |
| `frame_generate_last` | `sceneDescription`/`endFrameDesc`/`characterDescriptions` | 同上，尾部含"与首帧关系/下一镜头起点" |
| `scene_frame_generate` | `sceneDescription`/`charRefMapping`/`characterDescriptions`/`cameraDirection`/`startFrameDesc`/`motionScript` | 纯场景帧（无人物） |
| `character_image` | `characterName`/`description` | `{{NAME_LABEL_PLACEHOLDER}}` 替换为角色名标签 |

**⚠️ `ref_video_prompt` 的 buildFullPrompt 疑似漏输出**：定义了 4 个 slot（含 `language_rules`），但 `buildFullPrompt` 只 join 3 个（role_definition / motion_rules / quality_benchmark，L1756-1762）——`language_rules` slot 在 registry 中可编辑/可覆盖，**却永远不会出现在最终 prompt 中**（语言规则仅靠 blocks 内联于 motion_rules？需核对 REF_VIDEO_PROMPT_MOTION_RULES 是否内嵌语言规则——经查 motion_rules 无语言规则，实际语言约束缺失，属潜在缺陷）。

---

## 6. Prompt 构建函数（buildXxxPrompt）全表

> 分类依据：system prompt 来源。**新架构** = system 走 `resolvePrompt`（DB 可覆盖）；**旧架构** = system 硬编码于文件常量（无 DB 覆盖）。

| 文件 | 函数签名 | system 来源 | user 拼接逻辑 |
|---|---|---|---|
| `script-generate.ts` | `buildScriptGeneratePrompt(idea: string)` | **新**（registry `script_generate`，route L507） | `detectLanguage()` 正则识别 中/日/韩/英 → 输出语言指令 + 格式提醒 |
| `script-parse.ts` | `buildScriptParsePrompt(script: string)` | **新**（registry `script_parse`，route L604） | 原文包裹 `--- SOURCE TEXT ---` |
| `script-split.ts` | `buildScriptSplitPrompt(scriptChunk, {chunkIndex, totalChunks, episodeOffset})` | **新**（registry `script_split`） | 分块位置提示（第 N/N 块、集数偏移） |
| `shot-split.ts` | `buildShotSplitSystem(maxDuration)` + `buildShotSplitPrompt(screenplay, characters, visualHints?, colorPalette?, performanceStyles?)` | **⚠️ 双轨**：`SHOT_SPLIT_SYSTEM = buildShotSplitSystem(15)` 常量仍导出（旧），但 pipeline 实际用 `resolvePrompt("shot_split", ...)`（pipeline/shot-split.ts L68）；`buildShotSplitPrompt` 仅作 user 侧（含视觉标识块/色彩方案/表演风格注入） | 见左 |
| `character-extract.ts` | `buildCharacterExtractPrompt(screenplay: string)` | **新**（registry `character_extract`，route L687） | 剧本包裹；`CHARACTER_EXTRACT_SYSTEM` 常量（英文版）**已死代码**（无引用） |
| `import-character-extract.ts` | `buildImportCharacterExtractPrompt(textChunk: string)` | **新**（route L76-79 `importCharSystem` 经 resolvePrompt） | 文本包裹；`IMPORT_CHARACTER_EXTRACT_SYSTEM` 常量**已死代码** |
| `character-image.ts` | `buildCharacterTurnaroundPrompt(description: string, characterName?)` | **⚠️ 无 registry 模板**：完全硬编码（四视图/画风/一致性规则内联于函数体），**不走 slot 体系** | 角色描述权威注入 |
| `frame-generate.ts` | `buildFirstFramePrompt({sceneDescription, startFrameDesc, characterDescriptions, previousLastFrame?, slotContents?})` / `buildLastFramePrompt({...endFrameDesc, firstFramePath, slotContents?})` | **新**（registry `frame_generate_first/last`）；`def` 不存在时回退文件内硬编码 prompt（L21-70 fallback 分支） | `slotContents` 优先，否则 registry 默认 |
| `scene-frame-generate.ts` | `buildSceneFramePrompt({sceneDescription, charRefMapping, characterDescriptions, cameraDirection?, startFrameDesc?, motionScript?, slotContents?})` | **新**（registry `scene_frame_generate`）；def 缺失时 **throw**（不静默回退） | 参数注入 + slot |
| `keyframe-prompts.ts` | `buildKeyframePromptsRequest(shots, characters, visualStyle?)` | **新**（registry `shot_split_keyframe_assets`） | 角色（名+视觉标识+描述）与镜头（序号+prompt+动作+镜头运动）组装 |
| `ref-image-prompts.ts` | `buildRefImagePromptsRequest(shots, characters, visualStyle?)` | **新**（registry `ref_image_prompts`） | 场景图定义教学 + 分镜列表 + 场景图数量规则（默认 1/上限 4） |
| `ref-video-prompt-generate.ts` | `buildRefVideoPromptRequest({motionScript, cameraDirection, duration, characters, sceneFrames, dialogues?})` | **新**（registry `ref_video_prompt`） | `@图片N` 引用映射表 + 角色/场景索引 + 对白格式 |
| `video-generate.ts` | `buildVideoPrompt({videoScript, cameraDirection, startFrameDesc?, endFrameDesc?, duration?, characters?, dialogues?, slotContents?})` / `buildReferenceVideoPrompt(...)` | **新**（registry `video_generate` / `ref_video_generate`） | **从 slot 内容正则提取标签**：`extractLabel()`（对白口型/画外音）、`extractAnchorHeader()`（帧锚点头）、`extractFrameLabel()`（首帧/尾帧标签）——slot 内容即运行时配置 |

### 6.1 关键发现：双轨并存与死代码

1. **旧体系常量已死**：`CHARACTER_EXTRACT_SYSTEM`、`IMPORT_CHARACTER_EXTRACT_SYSTEM`、`SCRIPT_PARSE_SYSTEM`（script-parse.ts L1）、`SHOT_SPLIT_SYSTEM`（shot-split.ts L240）——grep 全库无引用（除定义处）。这些是 registry 化之前的内联 system，现由 `resolvePrompt` 替代，**应删除**（保留会误导维护者以为 system 可改）。
2. **`buildShotSplitSystem(15)` 的双轨**：函数仍导出且被 `SHOT_SPLIT_SYSTEM` 使用（死），但 pipeline 走 registry。若未来有人引用 `SHOT_SPLIT_SYSTEM`，会绕过 DB 覆盖。
3. **`character-image.ts` 未 registry 化**：`buildCharacterTurnaroundPrompt` 是 16 模板中唯一 system 完全内联、无 slot 分解、无 DB 覆盖的（虽然 registry 有 `character_image` 模板，但 pipeline/character-image.ts L22 调用的是这个函数而非 `resolvePrompt`）——**任务 C 的最大架构缺口**。
4. **`presets.ts` 空实现**：`BUILT_IN_PRESETS = []`，提示词管理 UI 的"内置预设"能力预留但未落地。

---

## 7. 结论摘要

1. **架构成熟**：registry（单一事实源）→ resolver（DB 三级覆盖）→ build 函数（user 侧拼装）三层解耦清晰；16 个模板 / 73 个 slot，其中 18 个格式/语言类 slot 锁定防破坏。
2. **数量修正**：实际 16 个模板（非 12 个），头注释与任务描述均已过时。
3. **共享机制**：模板间通过 blocks.ts 工厂共享画风映射/物理约束块（3 处注入），通过同名 slot 键共享编辑语义；`frame_generate_first/last` 为同构平级关系，无继承。
4. **风险点**：
   - `fidelityPrincipleBlock` 孤儿函数（保真度规则 3 处内联未复用）；
   - `ref_video_prompt` 的 `language_rules` slot 被定义但未在 buildFullPrompt 输出；
   - `character_image` 模板未接入实际调用链（buildCharacterTurnaroundPrompt 硬编码绕行）；
   - 4 个旧 system 常量死代码待清理；
   - `presets.ts` 空实现。
