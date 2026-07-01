# AICB vs AICF 全面对比分析

**日期**: 2026-07-02
**目标**: 逐阶段 + 跨阶段功能，穷举待完善项

---

## 一、逐阶段对比

### S1 script_parse

| 层面 | AICB | AICF | 待完善 |
|------|------|------|--------|
| **Prompt 来源** | `registry.ts` scriptParseDef，7 slots | `prompts/defaults/script_parse.py`，4 slots | ⚠️ **P1**: AICF 缺 `parsing_rules` slot（故事编辑原则） |
| **Prompt 内容** | 原文保真度铁律 + 逐字保留对白 + 宁多勿少拆场景 | 已移植，内容一致 | ✅ |
| **输出 Schema** | `title/synopsis/scenes/dialogues` | 同 | ✅ |
| **LLM 调用** | agent (百炼/Dify/Coze) | OpenClaw baidu-codingplan | ✅ D3 已决策 |
| **无独立脚本** | `script-parse.ts` handler | 无 Python 脚本，OpenClaw 直接调用 | ✅ 合理 |
| **scene 字段** | `setting/description/mood/timeOfDay` | AICF 的 schema 需确认是否完整包含 | ⚠️ **P2**: 需对比 s1_parsed.json 实际输出字段 |

### S2 character_extract

| 层面 | AICB | AICF | 待完善 |
|------|------|------|--------|
| **Prompt 来源** | 7 slots | 11 slots | ✅ AICF 更细粒度 |
| **Prompt 内容** | 身份层/风格层分离 + visualHint + performanceStyle + 姿态分层 | 已移植，加了 visualAnchors | ✅ |
| **输出 Schema** | name/scope/description/visualHint/personality/heightCm/bodyType/performanceStyle | 同 + visualAnchors + colorPalette | ✅ AICF 更丰富 |
| **costume** | `CharacterCostume` 独立表 (id/characterId/name/description) | ❌ **未实现** | ⚠️ **P1**: 下游 S5 用 costumeOverrides |
| **scope 全量覆盖** | 硬约束：每个有名字的角色都必须出现 | prompt 已移植 | ✅ |

### S3 character_image + S3b character_4view

| 层面 | AICB | AICF | 待完善 |
|------|------|------|--------|
| **生成方式** | 1步：DALL-E 单次 2560×1440 四视图排版图 | 2步：S3 T2I 单图 → S3b qedit 四视角 | ✅ D1 已决策 |
| **Prompt** | 6 slots: style_matching/face_detail/four_view_layout/lighting_rendering/consistency_rules/name_label。极完备：画风铁律+面部高精度+四视图精确布局+一致性生死线+名字标签 | S3 T2I: `_build_concept_prompt` 三种风格; S3b qedit: `build_qedit_view_prompt()` 通用视角描述 | ⚠️ **P1**: qedit prompt 太简单，缺画风锚定+一致性约束 |
| **Prompt 模板** | `character_image.py` 6 slots 统一注册 | AICF 有 `character_image.py` 但 S3 `_run_t2i()` 和 `_run_qedit()` 都没用它，用自己硬编码的 prompt | ⚠️ **P0**: 应统一走 Prompt 系统 |
| **名字标签** | 四视图底部印角色名 | 无 | ⚠️ **P2**: qedit 不支持文字渲染，可接受 |
| **分辨率** | 2560×1440 (单张) | 1024×1536 × 4张 | ✅ |

### S4 shot_split

| 层面 | AICB | AICF | 待完善 |
|------|------|------|--------|
| **Prompt 来源** | 10 slots: role_definition/script_fidelity/output_format/start_end_frame_rules/motion_script_rules/video_script_rules/proportional_tiers/camera_directions/cinematography_principles/language_rules | 11 slots: role/physics/safe_zone/motion_rules/composition/transition/output_format/consistency/relationships_constraint/performance_style/language | ⚠️ **P0**: **Slot 名称和内容严重不对齐**。AICF 缺 AICB 最关键的约束：`script_fidelity`（保真度+字数硬约束+镜头数量数学下限）、`start_end_frame_rules`（首尾帧直接驱动图像生成）、`video_script_rules`（Seedance 散文按时长分级）、`proportional_tiers`（比例差异规则）、`cinematography_principles`（摄影原则） |
| **Prompt 内容深度** | ~4000字：sceneDescription≥150字、motionScript 3秒分段四层交织、videoScript 按时长分级(短30-60字/中60-120字/长120-200字)、镜头数量数学下限(≥动作动词数)、战斗场景强制规则(攻防交替节拍)、比例差异规则 | ~1500字：physics/safe_zone/composition/transition 各一段 | ⚠️ **P0**: **S4 是全链路质量的瓶颈**。AICB 保真度硬约束+字数下限+镜头数下限+战斗规则必须对齐 |
| **输出字段** | `sequence/sceneDescription/motionScript/videoScript/duration/dialogues/cameraDirection/characters`（不含 startFrame/endFrame） | 需确认 s4_shots.json 实际输出字段 | ⚠️ **P1** |
| **keyframe_assets 解耦** | 独立 prompt `shot_split_keyframe_assets` (3 slots)，专门生成首尾帧图像 prompt | 无此独立步骤 | ⚠️ **P0**: AICB 将元数据生成和帧 prompt 生成解耦。S4 只输出元数据，S4b 生成 startFrame/endFrame。AICF 应对齐 |
| **scene_frame_generate** | 独立 prompt (3 slots)，纯场景参考帧（无人物强制约束） | 无此概念 | ⚠️ **P1** |
| **worldSetting 注入** | 从 project 读取注入 userPrompt | 未实现 | ⚠️ **P2** |
| **targetDuration** | 从 project/episode 读取，注入镜头总时长约束 | 未实现 | ⚠️ **P2** |

### S5 frame_generate

| 层面 | AICB | AICF | 待完善 |
|------|------|------|--------|
| **Prompt 来源** | `frame_generate_first` 4 slots + `frame_generate_last` 4 slots | `prompts/defaults/` 已移植：7 slots + 8 slots | ✅ AICF 更细粒度 |
| **Prompt 调用** | `buildFirstFramePrompt()` / `buildLastFramePrompt()` → 传给 DALL-E | S5 脚本内直接构建 prompt 字符串，绕过 prompt 系统 | ⚠️ **P0**: **应调用 `build_full_prompt()` 构建 prompt 后注入工作流** |
| **多角色参考图** | `referenceImages: charRefImages[]` — N 张角色参考图 | 只传 1 张角色参考图到 LoadImage | ⚠️ **P0**: qedit `TextEncodeQwenImageEditPlus` 支持 image1/2/3 |
| **前帧连续性** | prevLastFrameUrl 同时入 prompt + referenceImages | 上传到 ComfyUI 但未接入工作流 | ⚠️ **P0** |
| **costumeOverrides** | shot 级别换装，逐角色查 CharacterCostume | 未实现 | ⚠️ **P1** |
| **首帧→尾帧参考** | 尾帧 `referenceImages: [firstFrame, ...charRefImages]` | 尾帧用首帧作为 VAEEncode 输入 | ✅ 逻辑等价 |
| **compositionSuffix** | compositionGuide + focalPoint + depthOfField + colorPalette + heightInfo | `_build_composition_suffix()` 已实现 | ✅ |
| **无角色场景** | `scene_frame_generate` 独立 prompt + 无人物强制约束 | T2I fallback 无此约束 | ⚠️ **P1** |
| **角色名→参考图映射** | `charsWithRefs` + `storedCharNames` 精确指定 | `_find_character_ref_image()` 按 char_name 匹配 | ✅ 逻辑等价 |

### S6 video_generate

| 层面 | AICB | AICF | 待完善 |
|------|------|------|--------|
| **模式** | Keyframe + Reference 双模式 | Keyframe only | ✅ D2 已决策 |
| **Prompt** | `buildVideoPrompt()` — 结构化组合：角色外观+对白+镜头+时长+帧锚点+运动约束+插值模式 | FLF2V motionPrompt = shot.videoScript 或 motionScript | ⚠️ **P1**: 应增强 motionPrompt 构建 |
| **视频质检** | `video_quality_check.ts` — LLM vision 评分 0-100 | S3/S5 有 VL 质检，S6 未实现 | ⚠️ **P2** |
| **时长上限** | `getModelMaxDuration()` 按 video model 限制 | `MAX_FLF2V_FRAMES = 125` + Path D 自动分段 | ✅ |

### S7 video_assemble

| 层面 | AICB | AICF | 待完善 |
|------|------|------|--------|
| **转场** | 7种 (cut/dissolve/fade_in/fade_out/wipeleft/slideright/circleopen) | xfade + cut | ⚠️ **P2**: 应增加 fade_in/fade_out |
| **字幕烧录** | dialogue startRatio/endRatio | Whisper ASR 时间轴 | ✅ 各有优劣 |
| **音频轨道** | 未明确 | 串行 (narration→inner_voice→dialogue) + BGM 并行 | ✅ AICF 更完整 |

### S8 subtitles + S9 TTS

| 层面 | AICB | AICF | 待完善 |
|------|------|------|--------|
| **字幕** | 无独立 stage | Whisper ASR → SRT → ASS | ✅ AICF 更完整 |
| **TTS** | 未集成 | Qwen3-TTS | ✅ AICF 更完整 |

---

## 二、跨阶段功能对比

### F1: Prompt 系统

| 层面 | AICB | AICF | 待完善 |
|------|------|------|--------|
| **Registry** | `registry.ts` 统一注册 12 个 PromptDefinition | `prompts/defaults/*.py` 各自独立定义 | ✅ 架构等价 |
| **Slot 系统** | `PromptSlot { key, nameKey, descriptionKey, defaultContent, editable }` | `SLOTS` dict `{ key, editable, defaultContent }` | ⚠️ **P2**: AICF 缺 nameKey/descriptionKey，本地不需 i18n |
| **Override 机制** | `resolveSlotContents()` 从 DB 读 PromptVersion + PromptPreset | `slot_contents` dict 运行时传入 | ⚠️ **P2**: 应增加 `prompts/overrides/*.yaml` |
| **Prompt 解析链** | slotContents 覆盖 → registry default → hardcoded fallback | sc.get(key) → SLOTS[key]["defaultContent"] | ✅ 逻辑等价 |
| **S3/S5 绕过 Prompt 系统** | N/A | S3/S5 脚本内硬编码 prompt，不用 prompts/defaults/ | ⚠️ **P0**: **S3/S5 应统一走 Prompt 系统** |

### F2: 参考图注入机制

| 层面 | AICB | AICF | 待完善 |
|------|------|------|--------|
| **S3→S5 传递** | character.referenceImage URL 存 DB | s3_character_refs/ 目录文件 | ✅ |
| **S5 多角色参考** | `referenceImages: charRefImages[]` 数组 | 只传 1 张 | ⚠️ **P0** |
| **S5 前帧连续性** | prevLastFrameUrl 同时入 prompt + referenceImages | 未接入工作流 | ⚠️ **P0** |
| **S5 尾帧参考** | `referenceImages: [firstFrame, ...charRefImages]` | 首帧作为 VAEEncode 输入 | ✅ |
| **S6 多参考图** | Seedance 2.0 多参考图 (最多9张) | FLF2V 无多参考图 | ✅ D2 |

### F3: Shot 数据模型

| 层面 | AICB | AICF | 待完善 |
|------|------|------|--------|
| **Shot 字段** | 完整: sequence/prompt/motionScript/videoScript/videoPrompt/cameraDirection/compositionGuide/focalPoint/depthOfField/transitionIn/transitionOut/soundDesign/musicCue/duration/costumeOverrides/isStale/generationMode | 需确认 s4_shots.json 实际字段 | ⚠️ **P1**: AICF 可能缺少多个字段 |
| **ShotAsset 版本化** | DB 表: id/shotId/type/sequenceInType/prompt/fileUrl/status/assetVersion/isActive/characters | 文件覆盖式，无版本 | ⚠️ **P1**: 无法回滚 |
| **Dialogue 模型** | id/shotId/characterId/text/emotion/startRatio/endRatio/sequence | shot 内嵌 dialogues[] | ⚠️ **P2**: 缺 emotion/startRatio/endRatio |
| **ShotAction** | id/shotId/type(speech/thought/action/narration)/content/orderIndex | 未实现 | ⚠️ **P2**: TTS 可据此选声线 |

### F4: 连续性检查

| 层面 | AICB | AICF | 待完善 |
|------|------|------|--------|
| **帧连续性** | `continuity-check.ts` — LLM vision 比对相邻帧末帧/首帧 | 未实现 | ⚠️ **P2** |
| **视频质检** | `video-quality-check.ts` — LLM vision 评分 0-100 | S3/S5 有 VL 质检，S6/S7 无 | ⚠️ **P2** |
| **脏标记** | `shot.isStale` — 重新生成时级联标记下游 | 未实现 | ⚠️ **P2** |

### F5: 角色一致性体系

| 层面 | AICB | AICF | 待完善 |
|------|------|------|--------|
| **visualHint** | 2-4字速记，下游所有 prompt 自动注入 | ✅ 已实现 | ✅ |
| **visualAnchors** | 无 | face/hair/body/clothing 四维 | ✅ AICF 更丰富 |
| **performanceStyle** | 戏中标志性动作，不进 description | ✅ 已实现 | ✅ |
| **姿态分层** | description=中性站立, performanceStyle=戏中动作 | ✅ prompt 已对齐 | ✅ |
| **多角色一致性** | referenceImages[] 数组物理注入 | 只传1张 + prompt TIV | ⚠️ **P0**: qedit 支持 image1/2/3，应利用 |

### F6: 调度与状态管理

| 层面 | AICB | AICF | 待完善 |
|------|------|------|--------|
| **任务队列** | SQLite 原子 claim + maxRetries | OpenClaw sessions_spawn | ✅ |
| **state.json** | Task 表 status | projects/{project}/state.json | ✅ |
| **断点续跑** | Worker 轮询 dequeue | 读 state.json | ✅ |

---

## 三、待完善清单（汇总）

### P0 — 必须立即修改（影响产出质量）

| # | 项目 | 阶段 | 说明 |
|---|------|------|------|
| P0-1 | **S4 shot_split prompt 重写** | S4 | AICB prompt 4000+ 字含保真度硬约束/字数下限/镜头数数学下限/战斗规则，AICF 不足 1500 字且 slot 结构不对齐。**这是全 Pipeline 质量的瓶颈** |
| P0-2 | **S5 多角色参考图注入** | S5 | qedit `TextEncodeQwenImageEditPlus` 支持 image1/2/3，多角色场景应注入多张参考图 |
| P0-3 | **S5 前帧连续性接入** | S5 | 前shot尾帧应作为额外 image 输入注入 qedit 工作流 |
| P0-4 | **S3/S5 统一走 Prompt 系统** | S3/S5 | 当前硬编码 prompt 绕过了已有的 character_image/frame_generate 模板。应调用 `build_full_prompt()` 构建 prompt 后注入工作流 |
| P0-5 | **S4 keyframe_assets 解耦** | S4 | AICB 将 shot 元数据生成和首尾帧 prompt 生成拆为两步（shot_split + shot_keyframe_assets）。AICF 应对齐：S4 只输出元数据，新增 S4b 生成 startFrame/endFrame prompt |

### P1 — 下阶段修改（影响完整度）

| # | 项目 | 阶段 | 说明 |
|---|------|------|------|
| P1-1 | **S3b qedit prompt 增强** | S3 | `build_qedit_view_prompt()` 应注入 visualAnchors + 画风锚定 + 一致性约束 |
| P1-2 | **S2 CharacterCostume** | S2 | 角色换装体系：s2_characters.json 增加 costumes[] 字段 |
| P1-3 | **Shot 字段对齐** | S4 | s4_shots.json 应包含 AICB 完整字段 |
| P1-4 | **ShotAsset 版本化** | 全局 | 保留最近 N 版 + 自动清理 |
| P1-5 | **S6 video prompt 增强** | S6 | `buildVideoPrompt()` 应结构化组合 |
| P1-6 | **无角色场景处理** | S5 | 纯场景帧应有"无人物"约束 prompt |
| P1-7 | **S1 parsing_rules slot** | S1 | 缺少故事编辑原则 slot |

### P2 — 可选改进（影响体验/扩展性）

| # | 项目 | 阶段 | 说明 |
|---|------|------|------|
| P2-1 | S7 转场种类 | S7 | 增加 fade_in/fade_out |
| P2-2 | worldSetting 注入 | S4 | 世界观设定注入 prompt |
| P2-3 | targetDuration | S4 | 镜头总时长约束 |
| P2-4 | Dialogue 细分 | S2/S4 | emotion/startRatio/endRatio/类型细分 |
| P2-5 | 帧连续性检查 | S5→S6 | VL 比对相邻帧 |
| P2-6 | Shot 脏标记 | 全局 | isStale 级联 |
| P2-7 | Prompt override 持久化 | 全局 | `prompts/overrides/*.yaml` |
| P2-8 | S6 视频质检 | S6 | VL 评分 |
| P2-9 | S1 scene schema 对齐 | S1 | 确认字段完整 |

---

## 四、关键洞察

### 洞察 1: S4 是全链路质量的瓶颈

AICB 的 shot_split prompt 约 4000 字，含剧本保真度硬约束、字数下限、镜头数量数学下限、首尾帧直接驱动图像生成的规则、videoScript 按时长分级、战斗场景攻防交替节拍模板、比例差异规则。

AICF 当前 shot_split prompt 远未达到这个精度。**S4 产出质量直接决定 S5/S6/S7 的上限**。

### 洞察 2: S4→S5 解耦是架构关键

AICB 将 `shot_split`（元数据）和 `shot_keyframe_assets`（首尾帧 prompt）拆为两步：
- S4 专注镜头切分和叙事节奏
- S4b 专注视觉画面描述，可独立重跑
- 首尾帧 prompt 独立存储在 ShotAsset 表，S5 直接读取

AICF 当前 S4 可能直接输出 startFrame/endFrame 描述，混合了元数据和视觉描述。解耦后两者可独立迭代，大幅提升效率。

### 洞察 3: 参考图注入是角色一致性的物理基础

AICB 的 `referenceImages[]` 数组机制——把所有角色参考图 + 前帧打包传给图像生成 API——是角色一致性和场景连续性的**物理基础**（不是文字约束）。

AICF 当前只传 1 张角色参考图 + prompt 文字约束（TIV），丢失了多角色场景的物理注入能力。qedit 的 image1/2/3 天然支持多参考图，这是 AICF 独有的技术优势，必须利用。
