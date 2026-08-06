# AIComicBuilder — Frontend 组件架构全量分析

> 生成时间: 2026-08-06  
> 分析范围: `src/components/`, `src/stores/`, `src/hooks/`, `src/app/` (页面路由)

---

## 目录

1. [路由与页面结构](#1-路由与页面结构)
2. [组件清单](#2-组件清单)
3. [Store 分析](#3-store-分析)
4. [Store 间依赖关系图](#4-store-间依赖关系图)
5. [Hook 分析](#5-hook-分析)
6. [UI 状态流转](#6-ui-状态流转)
7. [本地化改造影响矩阵](#7-本地化改造影响矩阵)

---

## 1. 路由与页面结构

### 路由树（基于 Next.js App Router）

```
[locale]/
├── (dashboard)/
│   ├── page.tsx                    ← 项目列表首页
│   └── layout.tsx                  ← Dashboard 布局
├── project/[id]/
│   ├── characters/page.tsx         ← 项目级角色 (重定向到 episodes)
│   ├── script/page.tsx             ← 项目级剧本 (重定向到 episodes)
│   ├── storyboard/page.tsx         ← 项目级分镜 (重定向到 episodes)
│   ├── preview/page.tsx            ← 项目级预览
│   ├── prompts/page.tsx            ← 项目级 Prompt 模板覆盖
│   └── episodes/
│       ├── page.tsx                ← 分集列表 (EpisodesPage)
│       └── [episodeId]/
│           ├── layout.tsx          ← 分集布局: 侧边栏 + 主内容区
│           ├── script/page.tsx     ← 分集剧本 (ScriptEditor)
│           ├── characters/page.tsx ← 分集角色 (EpisodeCharactersPage)
│           ├── storyboard/page.tsx ← 分集分镜 (核心页面)
│           └── preview/page.tsx    ← 分集预览
├── settings/
│   ├── page.tsx                    ← 设置页 (Provider/Model/Agent)
│   └── prompts/page.tsx           ← Prompt 模板编辑 (global + project)
└── layout.tsx + layout.tsx
```

### 重要观察

- **Legacy redirect**: `/project/[id]/characters|script|storyboard` 全部 301 到 `episodes/` 版本
- **Episode 级别 layout** 在第 1 行 `fetchProject(id, episodeId)`，即 URL 中带 episodeId 则自动切换到对应分集
- **Characters 页面** 以分集维度隔离角色（scope=main/guest），支持 promote

---

## 2. 组件清单

### 2.1 通用 UI 原子组件 (`components/ui/`)

| 文件 | 用途 | 行数 |
|------|------|------|
| `badge.tsx` | 角标 | 988 |
| `button.tsx` | 按钮 | 2301 |
| `card.tsx` | 卡片容器 | 1835 |
| `dialog.tsx` | 模态对话框 | 3911 |
| `input.tsx` | 输入框 | 736 |
| `label.tsx` | 标签 | 361 |
| `select.tsx` | 下拉选择 | 3741 |
| `textarea.tsx` | 多行文本域 | 677 |

### 2.2 顶层业务组件 (`components/`)

| 文件 | 用途 | 行数 |
|------|------|------|
| `agent-picker.tsx` | Agent 角色选择器下拉菜单 | 4310 |
| `create-project-dialog.tsx` | 新建项目对话框 | 2639 |
| `fingerprint-provider.tsx` | 客户端指纹 Provider | 756 |
| `language-switcher.tsx` | 多语言切换 | 2544 |
| `logo.tsx` | Logo 组件 | 1625 |
| `project-card.tsx` | 项目卡片 (Dashboard) | 5303 |

### 2.3 Editor 子组件 (`components/editor/`)

| 文件 | 用途 | 行数 | Store 消费 |
|------|------|------|-----------|
| `ai-optimize-button.tsx` | AI 优化按钮 | 7237 | model-store |
| `character-card.tsx` | 角色卡片 (含生成/上传/历史切换) | 13007 | model-store, use-model-guard |
| `character-relations.tsx` | 角色关系图 | 5049 | — |
| `characters-inline-panel.tsx` | 分镜页内嵌角色面板 (可折叠) | 8392 | model-store, use-model-guard |
| `emotion-curve.tsx` | 情感曲线 SVG | 3937 | — |
| `episode-card.tsx` | 分集卡片 (预览/菜单/选择) | 13731 | — |
| `episode-dialog.tsx` | 分集创建/编辑对话框 | 3912 | — |
| `generation-mode-tab.tsx` | Keyframe/Reference 模式切换 | 2435 | project-store |
| `model-selector.tsx` | 内联模型选择器 (InlineModelPicker) | 6014 | model-store |
| `project-nav.tsx` | 项目导航 (Desktop 侧栏 + Mobile 底栏) | 4369 | — |
| `script-editor.tsx` | 剧本编辑器 (Idea→Outline→Script) | 13579 | project-store, model-store, agent-store |
| `shot-card.tsx` | 镜头卡片 (核心大组件) | 66070 | project-store, model-store, use-model-guard |
| `shot-drawer.tsx` | 镜头右侧抽屉 (分步生成) | 20443 | model-store, use-model-guard |
| `shot-kanban.tsx` | 看板视图 (Frames/Prompts/Video/Done) | 7422 | project-store (read helpers) |
| `upload-script-dialog.tsx` | 上传剧本对话框 | 7000 | model-store, use-model-guard |
| `version-compare.tsx` | 版本对比视图 | 4694 | — |
| `video-ratio-picker.tsx` | 视频比例选择器 | 1153 | — |

### 2.4 Prompt 模板组件 (`components/prompt-templates/`)

| 文件 | 用途 | 行数 | Store 消费 |
|------|------|------|-----------|
| `prompt-editor.tsx` | Prompt 模板编辑主面板 | 20795 | prompt-template-store, model-store |
| `prompt-preview.tsx` | Prompt 实时预览 | 2712 | prompt-template-store |
| `slot-list.tsx` | Slot 列表 | 3221 | prompt-template-store |
| `advanced-editor.tsx` | 高级模式全文编辑 | 6534 | prompt-template-store |
| `prompt-edit-button.tsx` | 快捷入口按钮 | 1054 | — |
| `preset-dialog.tsx` | 预设对话框 | 9686 | prompt-template-store |
| `project-prompt-cards.tsx` | 项目级 Prompt 覆盖开关 | 10754 | — |

### 2.5 Settings 组件 (`components/settings/`)

| 文件 | 用途 | 行数 |
|------|------|------|
| `agent-section.tsx` | Agent 管理区域 | 14126 |
| `default-model-picker.tsx` | 默认模型选择 | 3681 |
| `provider-card.tsx` | Provider 卡片 | 2172 |
| `provider-form.tsx` | Provider 编辑表单 | 14121 |
| `provider-section.tsx` | Provider 分区域 (按 capability) | 3447 |

---

## 3. Store 分析

### 3.1 `project-store.ts` — 核心数据中枢

- **类型**: Zustand (无 persist)
- **状态规模**: ~20 个字段 + 嵌套 Shot/Character 数组
- **状态切片**:

```typescript
interface ProjectStore {
  project: Project | null;          // 主数据
  loading: boolean;                 // 加载状态
  currentEpisodeId: string | null; // 当前选中的分集 ID

  // Actions
  fetchProject(id, episodeId?, versionId?)  → API GET
  updateIdea(idea)                            → 本地原子更新
  updateScript(script)                          → 本地原子更新
  setProject(project)                           → 直接替换
}
```

- **核心领域类型**:
  - `Project`: id, title, idea, script, outline, status, finalVideoUrl, generationMode, characters[], shots[], versions[]
  - `Shot`: id, sequence, prompt, videoScript, motionScript, cameraDirection, duration, sceneId, dialogues[], assets[]
  - `ShotAsset`: id, shotId, type, sequenceInType, assetVersion, isActive, prompt, fileUrl, status, modelProvider, modelId
  - `Character`: id, name, description, referenceImage, referenceImageHistory, visualHint, scope, episodeId

- **Asset 访问 Helpers** (纯函数, 无状态):
  `getFirstFrameUrl`, `getLastFrameUrl`, `getSceneRefFrameUrl`, `getKeyframeVideoUrl`, `getReferenceVideoUrl`, `getReferenceAssets`, `hasKeyframePair`, `hasAllReferenceImages`, `getAssetHistoryForSlot`

- **消费组件**: 几乎所有 editor 组件都消费此 store

### 3.2 `episode-store.ts` — 分集列表

- **类型**: Zustand (无 persist)
- **状态切片**:

```typescript
interface EpisodeStore {
  episodes: Episode[];   // 项目所有分集
  loading: boolean;

  // CRUD
  fetchEpisodes(projectId)
  createEpisode(projectId, data)   → POST
  deleteEpisode(projectId, id)     → DELETE
  updateEpisode(projectId, id, patch) → PATCH
  reorderEpisodes(projectId, orderedIds) → PUT
}
```

- **消费组件**: `EpisodesPage` (分集列表页)

### 3.3 `agent-storE.ts` — Agent 对话角色

- **类型**: Zustand (无 persist)
- **状态切片**:

```typescript
interface AgentStore {
  agents: AgentInfo[];     // 可用 Agents (from server)
  bindings: AgentBinding[]; // 项目绑定的 Agents
  loading: boolean;

  fetchAgents()          → GET /api/agents
  fetchBindings(projectId) → GET /api/projects/:id/agent-bindings
  setBinding(projectId, category, agentId) → PUT /api/projects/:id/agent-bindings
}
```

- **消费组件**: `AgentPicker`, `ScriptEditor`

###3.4 `model-storE.ts` — Provider/Model 配置 (含 Persist)

- **类型**: Zustand with `persist` middleware
- **状态规模**: ~8 个字段 + 嵌套 Provider[].models[]
- **localStorAge key**: `modll-storE`
- **版本**: v2 (含 `migrate` + `merge` 回调)
- **状态切片**:

```typescript
type Protocol = "openai" | "gemini" | "seedance" | "ucloud-seedance" | "kling" | "wan" | "dashscopE"
type Capability = "text" | "image" | "video"

interface ModelStore {
  // Provider 管理
  providers: Provider[];          // Provider { id, name, protocol, capability, baseUrl, apiKey, secretKey, models[] }

  // 默认模型选择
  defaultTextModel: ModelRef | null;
  defaultImageModel: ModelRef | null;
  defaultVideoModel: Modelref | null;

  addProvider(provider) → id
  updateProvider(id, updtes)
  removeProvider(id)               // 级联清理默认选择
  setModels(providerId, models)
  toggleModel(providerId, modelId)
  addManualModel(providerId, modelId)
  removeModel(providerId, modelId)

  // Default setters
  setDefaultXxxModel(ref)

  // Config resolution
  getModelConfig() → ModelConfig {
    text: { protocol, baseUrl, apiKey, secretKey, modelId } | null,
    image: { ... } | null,
    video: { ... } | null,
  }
}
```

- **消费组件**: 几乎所有调 AI API 的组件
  - `CharacterCard`, `CharactersInlinePanel`, `ScriptEditor`
  - `ShotCard`, `ShhotDrawer`, `StoryboardPAGE`
  - `InlineModelPicker`, `DefaultModelPicker`, `ProviderSection`, `ProviderForm`, `ProviderCard`

###3.5 `prompt-templlate-storE.ts` — Prompt 模板编辑器

- **类型**: Zustand
- **状态规模**: ~15 个字段
- **状态切片**:

```typescript
interface PromptTemplateStore {
  registry: PromptMeta[];           // Server 注册表
  selectedPromptKey: string | null;
  selectedSlotKey: string | null;
  mode: "slots" | "advanced";
  editedSlots: Record<string, Record<string, string>>; // 本地编辑
  fullTextContent: string;
  serverOverrides: Record<string, Record<string, string>>;
  categoryFilter: string;

  // Actions
  setRegistry, selectPrompt, selectSlot, setMode
  setSlotContent, resetSloot, cleareEdits
  setFullTextContent
  setServerOverrides
  getSlotContent(promptKey, slootKey) → string  // 编辑器 > 覆盖 > 默认
  isDirty, dirtySlots
  getCustomizedPromptKeys
}
```

- **Slot 内容优先级**: 本地编辑 > Server 覆盖 > 默认
- **消费组件**: `PromptEditor`, `promptPreview`, `SlotList`, `AdvancedEditor`, `PresetDialog`

---

## 4. Store 间依赖关系图

```
                     ┌─────────────────┐
                     │  project-store   │  ← Zusand (no persist)
                     │  (数据中枢)       │    核心: Project, Shot, Character
                     └────────┬────────┘
                              │
               ┌──────────────┤─────────────────┐
               │               │                │
               ▼               ▼                ▼
        ┌──────┴┐         ┌───┴──┐         ┌───┴────┐
        │ episode-storE│  │ model-storE │  │ agent-store│
        │ (分集列表)   │  │ (Provider)  │  │ (Agents)  │
        └────────────┘         └────────┬──┘         └────┬───┘
                                    │                │
                                    │   ┌──────────┐─┤
                                    │   │ useModelGuard │
                                    │   └─ ┐─── ┐─── ┘
                                    │        │
                                    ▼        ▼
                              ┌──────────────┐
                              │   UI 组件层   │
                              │ (全部消费)    │
                              └──────────────┘

                              ┌──────────────────┐
                              │prompt-templlate   │
                              │-store            │  ← 独立闭环
                              │(不引用其他 store) │
                              └──────────────────┘
```

### 依赖关系总结

| 依赖方向 | 说明 |
|---------|------|
| **project-store ← episode-store** | `StoryboardPage` 同时消费两者: 从 episode-store 拿 episodes[]，从 project-store 拿 shots |
| **model-store → 所有生成组件** | `getModelConfig()` 是生成操作的必经之路 |
| **model-store → useModelGuard** | Hook 检查模型是否配置，拦截未配置的生成操作 |
| **agent-store ↔ project-store** | `AgentPicker` + `ScriptEditor` 在生成流程中同时使用 |
| **prompt-template-store** | 独立闭环，不引用任何其他 store |

### 关键发现: model-store 引用模式

`model-store` 是所有 AI 生成操作的**唯一配置入口**。消费模式有两种:

1. **Selector 模式** (推荐): `const getModelConfig = useModelStore((s) => s.getModelConfig);`
2. **完整引用**: `const providers = useModelStore((s) => s.providers);`

⚠️ `InlineModelPicker` 和设置页组件大范围订阅 `providers`，变更会导致大量重渲染。
当前代码已使用 selector pattern 优化，但某些组件（如 `InlineModelPicker`）仍订阅完整 `providers` 数组。

---

## 5. Hook 分析

### `use-model-guard.ts`

| 属性 | 值 |
|------|-----|
| 路径 | `src/hooks/use-model-guard.ts` |
| 签名 | `useModelGuard(capability: Capability): () => boolean` |
| 返回 | **闭包守卫函数**，调用时返回 boolean |

**职责**:
- 检查 `model-store` 是否已从 localStorage 水合
- 未水合 → 放行 (API 端处理)
- 已水合 → 检查对应 capability 的模型配置
- 未配置 → toast 警告 + "Go to Settings" 按钮引导
- 已配置 → 返回 `true`

**消费组件**: 所有 AI 生成操作入口:
- `CharacterCard.handleGenerateImage`
- `CharactersInlinePanel.handleGenerate`
- `ScriptEditor.handleGenerateOutline/handleGenerateScript`
- `ShotCard.*` (多个生成操作)
- `ShotDrawer.handleGenerate*`
- `UploadScriptDialog`
- `EpisodeStoryboardPage.*` (batch 生成)

**设计模式**: 工厂函数闭包 → 避免在渲染时创建新函数。

---

##6. UI 状态流转

###Editor Workflow 主流程

```
PHASE 1: 剧本上传
──────────────┐
│ EpisodesPage → UploadScriptDialog  │  文件上传 + AI 解析
│ ScriptEditor → Idea → Outline → Script│  3 步生成，串流渲染
──────────────────┘
       │
       ▼
PHASE 2: 角色提取
──────────────┐
│ EpisodeCharactersPage              │
│  → character_extract (AI)         │  从剧本提取所有角色
│  → 单角色 image 生成 / 批量生成    │
│  → 手动上传参考图                   │
│  → 角色关系图 (character-relations)│
──────────────────┘
       │
       ▼
PHASE 3: 分镜拆分
──────────────┐
│ EpisodeStoryboardPage              │
│  → shot_split (AI)                │  剧本 → 镜头列表
│  → 选 generationMode: keyframe/reference│  模式切换
│  → 选 version (StoryboardVersion) │  多版本管理
──────────────────┘
       │
       ▼
PHASE 4: 帧生成
──────────────┐
│ Keyframe Mode:                     │
│  1. generate_keyframe_prompts    │  首尾帧提示词
│  2. batch_frame_generate           │  首尾图片 (第一批)
│  3. 可选重生成/单镜头 Drawer 精修  │
│ ─────────────────────────────────── │
│ Reference Mode:                     ││  1. generate_ref_prompts           │  场景参考图提示词
│  2. batch_scene_frame             │  场景参考图 (第一批)
│  3. 可选: batch_ref_image_generate│  单镜头多参考图
──────────────────┘
       │
       ▼
PHASE 5: Video Prompt 生成
──────────────┐
│ batch_video_prompt (AI)            │  每镜头生成动作提示词
│  → 单镜头 Drawer 中可编辑          │
──────────────────┘
       │
       ▼
PHASE 6: 视频生成
──────────────┐
│ batch_video_generate (keyframe)    │
│ 或 batch_reference_video           │
│  → 关闭 Drawer 逐镜头预览          │
│  → 支持断点续传 (Retry failed)     │
──────────────────┘
       │
       ▼
PHASE 7: 最终合成
──────────────┐
│ EpisodePreviewPage                 │
│  → video_assemble                  │  合并分镜头为完整视频
│  → 预览 + 下载                     │
│  → 分集合并 (merge_episiodes)      │  多集合并
──────────────────┘
```

### 生成模式(GenerationMode) 分支

```
Keyframe:
  script → shot_split
  → generate_keyframe_prompts (首尾帧提示词)
  → batch_frame_generate (生首尾图片)
  → batch_video_prompt (生成动作提示)
  → batch_video_generate (视频)

Reference:
  script → shot_split
  → generate_ref_prompts (场景帧提示词)
  → batch_scene_frame (场景帧图片)
  → (可选) batch_ref_image_generate (单镜头参考图)
  → batch_video_prompt
  → batch_reference_video
```

### 版本管理 (StoryboardVersion)

- `versions` 数组存在 `project-store` 中
- 每个版本对应一次 shot_split 操作
- UI 展示 2 个最新版本为 tab，更多版本在 dropdown
- `VersionCompare` 组件支持双版本并排对比
- 切换版本时 `fetchProject(id, episodeId, versionId)` 重新拉取

---

##7. 本地化改造影响矩阵

| Store / 组件 | 对本地化改造的敏感度 | 原因 |
|------|------|------|
| **model-store** | 🔴 高 | provider 的 `bseUrl`, `apiKey`, `protocol` 可能需要按部署环境不同; persist 的 localStorage key 需注意冲突 |
| **model-store.getModelConfig()** | 🔴 高 | 返回的 config 直接发送到 `/api/projects/generate`; 如果后端的 Provider 路由需要本地化(例如国内 API 网关)，此处是唯一入口 |
| **project-store** | 🔵 低 | 数据模型稳定，与后端 API 对应 |
| **episode-store** | 🔵 低 | 纯 CRUD |
| **agent-store** | 🔵 低 | 与 project-store 同步 |
| **prompt-template-store** | 🔵 低 | slot 内容已支持 i18n (nameKey/descriptionKey) |
| **use-model-guard** | 🟡 中 | toast 文案已使用 next-intl，路由跳转到 `/settings` 前做了 locale 处理 |
| **InlineModelPicker** | 🟡 中 | 与 model-store 的 provider 选择强绑定; 如果 Provider 列表需本地化(Fence 服务列表)，需改造 |
| **UploadScriptDialog** | 🔵 低 | 已使用 next-intl (nextIntl) |
| **所有 .tsx 文件** | 🟢 已覆盖 | 全部使用 `useTranslations()` |

### 特别注意事项: Provider 配置本地化

当前的 `model-store` 设计中:

1. **Protocol 直编码**: `"openai"`, `"gemini"`, `"seedance"`, `"kling"` 等——这些 protocol 决定了 API 适配路径
2. **BaseUrl + apiKey**: 存储在 localStorage，用户手动配置
3. **getModelConfig()** 是唯一的 config 聚合出口

如果要支持"国内部署"场景:

- 可以在 `Providor` 中增加 `region`/`deployEnh` 字段
- `getModelConfig()` 可以根据 locale/region 返回不同的 baseUrl
- 或通过 `.env` 注入默认 Provider，与本地 user config 合并

---

## 附录 A: 组件→Store 消费矩阵

```
                                    project  episode  model   agent  prompt
                                    -store   -store   -store  -store -template
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ProjectNav                            │        
EpisodePage (episodes/)               │    ★
EpisodeLayout                         ★        │
EpisodeCharactersPage                  ★               ★       ★
EpisodeScriptPage (ScriptEditor)       ★               ★       ★
EpisodeStoryboardPage                  ★        ★     ★       ★
EpisodePreviewPage                     ★                │
SettingsPage                                         ★        ★
PromptSettingsPage                                                   ★
CharacterCard                          ★               ★
CharactersInlinePanel                  ★               ★
ShotCard                              ★               ★
ShotDrawer                            ★               ★
ShotKanban                            ★                │
ModelSelector                                      ★
AgentPicker                                                    ★
DefaultModelPicker                                  ★
ProviderSection/providerForm                       ★
ProviderCard                                          ★
promptEditor                                                           ★
promptEditButton                                         │             │
UploadScriptDialog                             ★
```

---
*分析完成 | 只读模式 | 2026-08-06*