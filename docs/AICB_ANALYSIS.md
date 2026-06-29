# AIComicBuilder 架构分析备忘

**分析日期**: 2026-06-28
**源码位置**: `~/AIComicBuilder/`（仅核心文件，非完整 clone）
**原始仓库**: https://github.com/LingyiChen-AI/AIComicBuilder

---

## 1. 技术栈

- Next.js 16 (App Router) + React 19 + TypeScript
- SQLite + Drizzle ORM
- Zustand (状态管理)
- FFmpeg (fluent-ffmpeg)
- AI SDK (Vercel) — 统一 text/image 调用
- Docker 部署

## 2. Pipeline 8 阶段

```
script_outline → script_parse → character_extract → character_image →
shot_split → frame_generate → video_generate → video_assemble
```

每个阶段 = TaskQueue 中的一个 task type，可独立触发。

### 2.1 script_parse
- 输入: 原始文本
- LLM: 生成结构化 JSON (title/synopsis/scenes/dialogues)
- 完成后自动 enqueue character_extract
- Prompt 核心要求: 原文保真度（逐字保留对白，宁多勿少拆场景）

### 2.2 character_extract
- 输入: 剧本文本
- 输出: characters[] + relationships[]
- 每个角色: name/scope/description/visualHint/personality/heightCm/bodyType/performanceStyle
- 三层铁律: 剧本保真度 > 身份层/风格层分离 > 不覆盖原文
- visualHint: 2-4字速记，下游所有 prompt 自动注入
- performanceStyle: 戏中标志动作，不进 description
- 姿态分层: description 只写中性站立，performanceStyle 写戏中动作

### 2.3 character_image
- 输入: 角色 description
- 输出: 四视图参考图 (2560×1440)
- Prompt: 四视图布局(front/3-4/side/back)、画风匹配、面部高精度、专业布光
- 模型: DALL-E/Imagen/Kling

### 2.4 shot_split
- 输入: 剧本+角色
- 输出: scenes→shots JSON
- 每个 shot 包含: prompt/motionScript/videoScript/cameraDirection/compositionGuide/...
- Prompt 核心约束:
  - 物理常识约束（严禁比喻动词、反物理）
  - 字幕安全区（下方20%保留）
  - 变化幅度比例（短=微变，长=显著）
  - motionScript 3秒分段，四层交织（角色+环境+机位+物理）
  - videoScript Seedance 散文格式（30-60词自然语言）
  - 构图指南（7种专业构图）
  - 转场指南（dissolve/fade/cut）
- 支持场景分组和扁平数组两种输出格式

### 2.5 frame_generate
- 输入: shot + 角色参考图 + 前shot尾帧
- 输出: 首帧+尾帧图像
- 角色 visualHint 强注入 prompt
- 前shot尾帧作为连续性参考
- colorPalette 注入 prompt 后缀
- composition/景深 映射到描述

### 2.6 video_generate
- 两种模式:
  - **Keyframe**: firstFrame + lastFrame → 插值视频
  - **Reference**: initialImage → 参考生成（Seedance 2.0 多参考图，最多9张）
- Seedance 2.0 支持 generate_audio, return_last_frame
- 提交→轮询（5s间隔，最多10min）

### 2.7 video_assemble
- FFmpeg 拼接 + 转场(7种: cut/dissolve/fade_in/fade_out/wipeleft/slideright/circleopen)
- 字幕烧录（dialogue 的 startRatio/endRatio 定位）
- BGM 叠加
- 标题卡 + 片尾卡

### 2.8 可选: continuity_check + video_quality_check
- 连续性: LLM vision 比对相邻帧末帧/首帧
- 质量: LLM vision 评分 0-100
- 都是 best-effort，不阻塞生成

## 3. 数据模型 (schema.ts 关键实体)

### Project
- id, title, script, status, createdAt/updatedAt

### Episode
- id, projectId, episodeNumber, title, synopsis, status

### Scene
- id, episodeId, sceneNumber, setting, description, mood, timeOfDay

### Shot (最丰富)
- id, sceneId, shotNumber, prompt, motionScript, videoScript, videoPrompt
- cameraDirection, compositionGuide, focalPoint, depthOfField
- transitionIn, transitionOut, soundDesign, musicCue
- duration, isStale, costumeOverrides, generationMode(keyframe/reference)

### ShotAsset (版本化资管)
- id, shotId, type(first_frame/last_frame/reference/keyframe_video/reference_video)
- filePath, assetVersion, isActive
- 每次重新生成插入新行，旧行 is_active=0

### Character
- id, projectId, name, scope(main/guest), description, visualHint
- personality, heightCm, bodyType, performanceStyle
- referenceImage

### CharacterCostume
- id, characterId, name, description

### CharacterRelation
- id, characterA, characterB, relationType, description

### Dialogue
- id, shotId, character, text, emotion, startRatio, endRatio

### ShotAction
- id, shotId, type(speech/thought/action/narration), content, orderIndex

### MoodBoardImage
- id, projectId, imageUrl, caption, source

### PromptTemplate + PromptVersion
- 支持 slot 级覆盖，版本管理

### PromptPreset
- 一键应用一组 slot 覆盖

### AgentBinding
- 按项目绑定 Agent（百炼/Dify/Coze）

### Task
- type, status(pending/running/completed/failed), payload, result, error
- maxRetries, attempts, claimedAt, completedAt

## 4. AI Provider 架构

### Text+Image Providers
- OpenAI (GPT + DALL-E)
- Gemini (Gemini + Imagen)
- Kling (Kling Image)
- DashScope (通义万相)

### Video Providers
- Seedance (火山引擎) — keyframe + reference 双模式
- UCloudSeedance
- Kling Video
- Veo (Google)
- Wan Video

### Provider 解析
- `resolveAIProvider()` / `resolveImageProvider()` / `resolveVideoProvider()`
- 模型配置按项目隔离 (ModelConfigPayload 在 pipeline handler 中透传)

## 5. Prompt Registry (核心设计)

### 架构
```typescript
PromptDefinition {
  key, nameKey, descriptionKey, category,
  slots: PromptSlot[],  // 每个 slot: key + defaultContent + editable
  buildFullPrompt(slotContents, params) → string
}
```

### 解析链
slotContents 覆盖 → registry default → hardcoded fallback

### 12 个 Prompt
见 PROJECT.md 第五章

### Slot 示例 (shot_split)
- role_definition (editable)
- language_rules (not editable)
- physics_constraints (editable)
- safe_zone_rules (editable)
- motion_script_rules (editable)
- composition_guide (editable)
- transition_guide (editable)
- output_format (not editable)
- language_rules (not editable)

## 6. Agent 集成
- 百炼: SSE 流式, dashscope API
- Dify: SSE 流式, /v1/workflows/run 或 /v1/chat-messages
- Coze: 非流式, /v1/workflow/run
- 统一 callAgentStream() 接口

## 7. Task Queue
- SQLite 原子 claim: 单条 UPDATE 完成「查找+锁定」
- enqueueTask / dequeueTask / completeTask / failTask
- Worker 轮询: dequeue → execute handler → complete/fail
- 失败: 重试 < maxRetries 则回退 pending，否则标记 failed
