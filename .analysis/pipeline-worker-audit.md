# AIComicBuilder — AI Pipeline 编排机制与 Worker 模型深度分析

> 分析时间: 2026-08-06 | 只读审计，未修改源码

---

## 1. 总体架构概览

AIComicBuilder 的 AI 执行管线采用 **双轨并行架构**：

```
┌─────────────────────────────────────────────────────────────────┐
│                     POST /api/projects/[id]/generate              │
│  ┌─────────────────────── dual dispatch ──────────────────────┐  │
│  │                                                           │  │
│  │  轨道 A: 同步流式处理          轨道 B: 后台任务队列            │  │
│  │  (text-heavy, low latency)   (asset-heavy, long-running)   │  │
│  │                                                           │  │
│  │  script_outline ──────────→  handleScriptOutlineAction     │  │
│  │  script_generate  ─────────→  handleScriptGenerate          │  │
│  │  script_parse ─────────────→  handleScriptParseStream       │  │
│  │  character_extract ────────→  handleCharacterExtract        │  │
│  │  shot_split ───────────────→  handleShotSplitStream          │  │
│  │  ··· (其他同步 action) ···                               │  │
│  │                                                           │  │
│  │  frame_generate ───────────→  enqueueTask → Worker          │  │
│  │  video_generate ───────────→  enqueueTask → Worker          │  │
│  │  video_assemble ───────────→  handleVideoAssembleSync*     │  │
│  │  (fallback 未匹配的 action) →  enqueueTask → Worker          │  │
│  └─────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

**核心发现**：管线中的 8 个 pipeline handler 并非全部走任务队列——大部分在 `route.ts` 中有对应的**同步处理器**（流式返回），仅 `frame_generate`、`video_generate` 等重度资产生成任务落入后台队列。

---

## 2. Pipeline 编排 — 8 个阶段

### 2.1 阶段总览

| # | 阶段 | Pipeline Handler | Route Handler | 执行模式 | 数据产出 |
|---|------|-----------------|---------------|----------|----------|
| 1 | script_outline | `handleScriptOutline` | `handleScriptOutlineAction` | 同步流式 | 文本大纲 → projects/episodes.outline |
| 2 | script_parse | `handleScriptParse` | `handleScriptParseStream` | 同步流式 | 结构化 screenplay JSON |
| 3 | character_extract | `handleCharacterExtract` | `handleCharacterExtract` | 同步 (非流式) | characters[] + relations |
| 4 | character_image | `handleCharacterImage` | `handleSingleCharacterImage` / `handleBatchCharacterImage` | 同步 | referenceImage → characters 表 |
| 5 | shot_split | `handleShotSplit` | `handleShotSplitStream` | 同步流式 | shots[] + scenes + dialogues |
| 6 | frame_generate | `handleFrameGenerate` | `handleSingleFrameGenerate` / `handleBatchFrameGenerate` | **后台队列** | firstFrame + lastFrame → shot_assets |
| 7 | video_generate | `handleVideoGenerate` | `handleSingleVideoGenerate` / `handleBatchVideoGenerate` | **后台队列** | keyframe_video → shot_assets |
| 8 | video_assemble | `handleVideoAssemble` | `handleVideoAssembleSync` | 同步 (直接调用 FFmpeg) | 最终成片 + SRT |

### 2.2 阶段间数据传递机制

管线采用 **DB 为中繼 + 显式 enqueue 串联** 的模式：

```
script_outline ──(save to DB)──→ script_parse
                                    │
                                    │ 读 project.script
                                    ↓
                              character_extract ◄── 自动 enqueue
                                    │
                                    │ 写 characters 表
                                    ↓
                              character_image ◄── 手动触发
                                    │
                                    │ 写 characters.referenceImage
                                    ↓
                              shot_split ◄── 读 characters 表
                                    │
                                    │ 写 shots + dialogues + scenes 表
                                    ↓
                              frame_generate ◄── 读 shots, characters
                                    │
                                    │ 写 shot_assets (first_frame, last_frame)
                                    ↓
                              video_generate ◄── 读 shot_assets
                                    │
                                    │ 写 shot_assets (keyframe_video)
                                    ↓
                              video_assemble ◄── 读 shots + shot_assets
                                    │
                                    │ FFmpeg 合成 → 写 project 表
```

**关键串联机制（自动 chaining）**：
- `handleScriptParse` 完成后**自动 enqueue** `character_extract` 任务（script-parse.ts:40）
- `handleShotSplit` 读入全部角色描述 + 角色关系 + 世界设定构建分镜 prompt
- `handleFrameGenerate` 通过 `getActiveAsset` 读取 shot_assets 中已由 keyframe prompt 阶段生成的首帧/尾帧 prompt
- `handleVideoGenerate` 依赖 `getActiveAsset(shotId, "first_frame"/"last_frame")` 获取帧 URL

**没有中央 Pipeline Orchestrator**——每个 handler 独立执行，通过 DB 表和显式 `enqueueTask` 串联。

---

## 3. Worker 模型深度分析

### 3.1 Worker 架构

**类型：进程内轮询 Worker（In-Process Polling Worker）**

```
┌─────────────────────────────────────────────────┐
│              Next.js Standalone Server           │
│  ┌───────────────────────────────────────────┐   │
│  │  HTTP Request Thread (Node.js Event Loop)  │   │
│  │  ┌───────────────────────────────────────┐ │   │
│  │  │  API Routes                           │ │   │
│  │  │  - enqueueTask() → DB INSERT         │ │   │
│  │  │  - 同步 action → 直接执行+流式返回    │ │   │
│  │  └───────────────────────────────────────┘ │   │
│  │                                            │   │
│  │  ┌───────────────────────────────────────┐ │   │
│  │  │  Background Worker (同进程, 2s 轮询)  │ │   │
│  │  │  poll() → dequeueTask() → handler()   │ │   │
│  │  │  ── 单线程处理，一次只处理一个任务 ───  │ │   │
│  │  └───────────────────────────────────────┘ │   │
│  └─────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────┘
```

**关键参数**：
- **POLL_INTERVAL_MS = 2000ms**（worker.ts:1）
- **串行处理**：一次只 dequeue 一个任务，完成后才进入下一轮轮询
- **单实例**：`isRunning` flag 确保 `startWorker()` 只调用一次

### 3.2 Worker 不是 Web Worker

```typescript
// worker.ts — 关键证据
const POLL_INTERVAL_MS = 2000;
let isRunning = false;
let handlers: TaskHandlerMap = {};

export function startWorker() {
  if (isRunning) return;
  isRunning = true;
  console.log("[TaskWorker] Started polling every", POLL_INTERVAL_MS, "ms");
  poll();  // ← 普通 async 函数，在 Node.js 主线程中运行
}

async function poll() {
  if (!isRunning) return;
  try {
    const task = await dequeueTask();  // ← SQL 原子 claim
    if (task) {
      await processTask(task);  // ← 阻塞 await（image/video 生成可能几十秒）
    }
  } catch (err) {
    console.error("[TaskWorker] Poll error:", err);
  }
  if (isRunning) {
    setTimeout(poll, POLL_INTERVAL_MS);  // ← 递归 setTimeout 链
  }
}
```

**结论**：这是经典的 **DB-backed 轮询 worker**，在 Node.js 主线程通过 `setTimeout` 递归实现轮询，与浏览器 Web Worker 无关。

### 3.3 Bootstrap 时序

```
bootstrap() [src/lib/bootstrap.ts]
  ├── runMigrations()           → DB 表结构初始化
  ├── initializeProviders()     → AI 提供商连接初始化
  ├── registerPipelineHandlers() → 注册 8 个 handler 到 worker
  └── startWorker()            → 启动 2s 轮询循环
```

Worker 启动后持续运行，直到进程退出。**不支持** worker 池、并发处理或独立部署。

---

## 4. Job / Task 模型

### 4.1 Task Schema

```sql
CREATE TABLE tasks (
  id            TEXT PRIMARY KEY,
  project_id    TEXT REFERENCES projects,
  type          TEXT CHECK (type IN ('script_outline', 'script_parse', 
                    'character_extract', 'character_image',
                    'shot_split', 'frame_generate', 
                    'video_generate', 'video_assemble')),
  status        TEXT CHECK (status IN ('pending', 'running', 
                    'completed', 'failed')) DEFAULT 'pending',
  payload       TEXT (JSON),
  result        TEXT (JSON),
  error         TEXT,
  retries       INT DEFAULT 0,
  max_retries   INT DEFAULT 3,
  created_at    INT (timestamp),
  scheduled_at  INT (timestamp),    -- 可选: 延迟调度
  episode_id    TEXT REFERENCES episodes
);
```

### 4.2 任务生命周期

```
pending ──(dequeue: atomic UPDATE)──→ running ──(handler success)──→ completed
  │                                         │
  │                                          ↓
  │                                   handler throws
  │                                          │
  │                                   retries < max? 
  │                                   Yes  ↘      ↘ No
  │                              pending ←──        failed
  │                              (retries++)
```

### 4.3 原子 Claim 机制（并发安全）

```sql
-- queue.ts — dequeueTask()
UPDATE tasks
SET status = 'running'
WHERE id = (
  SELECT id FROM tasks
  WHERE status = 'pending'
    AND (scheduled_at IS NULL OR scheduled_at <= now_ms)
  ORDER BY created_at ASC
  LIMIT 1
)
RETURNING *;
```

单个 SQL 原子操作完成 **选取 + 状态变更**，避免多实例竞争。但当前架构是单实例 worker，此机制主要是为未来多实例扩展预留。

### 4.4 错误恢复 / 重试

| 机制 | 实现 | 细节 |
|------|------|------|
| 重试上限 | `maxRetries` (默认 3) | `failTask()` 中 retries < maxRetries → 回 pending |
| 重试策略 | 无指数退避 | 纯轮询，重试后重新排队按 createdAt 排序 |
| 调度延迟 | `scheduledAt` | enqueue 时可指定延迟执行时间 |
| 质量检查 | best-effort | `checkVideoQuality()` 失败不阻塞，降级 pass |
| 连续性检查 | best-effort | `checkContinuity()` 同上 |

**注意**：没有指数退避、没有死信队列（DLQ）、没有任务优先级排序。

---

## 5. Pipeline Route.ts 双轨分析

### 5.1 Action 分发逻辑

`route.ts` (3895 行) 通过 `action` 字段分发到不同处理器：

```
POST body.action ──→ 路由器
  ├─ "script_outline" → handleScriptOutlineAction() [同步流式]
  ├─ "script_generate" → handleScriptGenerate() [同步流式]
  ├─ "script_parse" → handleScriptParseStream() [同步流式]
  ├─ "character_extract" → handleCharacterExtract() [同步]
  ├─ "single_character_image" → handleSingleCharacterImage() [同步]
  ├─ "batch_character_image" → handleBatchCharacterImage() [同步]
  ├─ "shot_split" → handleShotSplitStream() [同步流式]
  ├─ "generate_keyframe_prompts" → handleGenerateKeyframePrompts() [同步]
  ├─ "batch_frame_generate" → handleBatchFrameGenerate() [同步，内部 await all]
  ├─ "single_frame_generate" → handleSingleFrameGenerate() [同步]
  ├─ "single_video_generate" → handleSingleVideoGenerate() [同步]
  ├─ "batch_video_generate" → handleBatchVideoGenerate() [同步]
  ├─ "video_assemble" → handleVideoAssembleSync() [同步]
  ├─ ... (ref_image, scene_frame, reference_video, video_prompt 等)
  └─ 未匹配 action → enqueueTask() [异步后台队列]
```

### 5.2 智能体路由层

每个同步 action 处理器都有**智能体路由**（Agent Binding）分支：

```
请求到达
  │
  ├─ findBoundAgent(projectId, category) → 有绑定?
  │     ├─ YES → callAgentStream() / callAgent() → 流式/同步返回外部智能体结果
  │     └─ NO  → 内置 AI Provider → streamText/generateText
  │
  └─ 统一返回 Response
```

支持的智能体平台：百炼 (bailian)、Dify、扣子 (Coze)。

### 5.3 maxDuration

```typescript
export const maxDuration = 300; // 5 分钟
```

Next.js standalone 模式下，API 路由最长 300 秒。这对同步视频生成任务（可能超时）意味着需要靠后台队列完成。

---

## 6. 实时反馈机制

### 6.1 当前状态：**无 WebSocket，无 SSE（管线任务）**

项目没有 WebSocket 或 Server-Sent Events 用于管线进度上报。

### 6.2 两种反馈路径

| 路径 | 机制 | 场景 |
|------|------|------|
| **同步流式** | `streamText().toTextStreamResponse()` | script_outline, script_generate, script_parse, shot_split |
| **轮询** | `GET /api/tasks/[id]` — 返回完整 task 对象 (含 status) | 后台任务查询 |

### 6.3 Provider 内部轮询

视频/图像 provider（Kling、Seedance、Wan、UCloud）各有内部 `pollForResult()`：

```
handleVideoGenerate → videoProvider.generateVideo()
                          │
                          ↓
                     provider.pollForResult(taskId)
                          │
                          ├─ Kling: 每 5s 轮询 task_status
                          ├─ Seedance: 轮询 tasks/status
                          ├─ Wan: 轮询 output.task_status
                          └─ UCloud Seedance: 轮询 tasks/status
```

这些是**provider SDK 级别的轮询**（非用户可见），worker 在等待 provider 返回时阻塞。

### 6.4 前端进度获取

前端通过 `GET /api/tasks/[id]` 获取单个任务状态，或 `getTasksByProject(projectId)` 查询项目下全部任务。前端需自行实现轮询间隔。

---

## 7. Asset 版本化模型

### 7.1 shot_assets 表

管线产物存储在 `shot_assets` 表（通过 `shot-asset-utils` 管理）：

```
shot_assets:
  - type: "first_frame" | "last_frame" | "keyframe_video" | "reference_video" | "referenceImage"
  - sequenceInType: 版本号 (0-based)
  - prompt: 生成时使用的 prompt
  - fileUrl: 输出文件路径/URL
  - status: "pending" | "generating" | "completed" | "failed"
  - characters: 关联角色名数组
```

### 7.2 级联失效机制

`handleSingleCharacterImage` 中：角色参考图重新生成后，所有关联的 shot `referenceImages` 被标记为 `pending`（stale），触发下游重新生成。

---

## 8. 架构评估

### 8.1 优势

| 维度 | 评价 |
|------|------|
| **原子性** | dequeue 使用单 SQL 原子 claim，并发安全 |
| **双轨分流** | 轻量 text 任务同步流式，重资产任务异步队列 |
| **智能体路由** | 统一 agent binding 层，可插拔外部 AI |
| **资产版本化** | shot_assets 支持多版本、级联失效 |
| **最佳努力** | 质量/连续性检查不阻塞管线 |

### 8.2 风险与改进空间

| 风险 | 影响 | 建议 |
|------|------|------|
| **Worker 单线程串行** | 一个慢任务（如 video 60s）阻塞后续所有任务 | 改为 worker 池 或 独立进程 |
| **无进度上报** | 用户不知道后台任务进度 | SSE / WebSocket 推送 |
| **无指数退避** | 重试间隔固定 2s，高频重试浪费 | 加入 backoff 策略 |
| **无 DLQ** | 失败任务反复重试直到耗尽 | 超过 maxRetries 后入死信队列 |
| **路由与 handler 分离** | 同一逻辑在 route.ts 和 pipeline/*.ts 中各一份，维护双副本 | 抽取纯 handler 逻辑，route 只做 dispatch |
| **2s 轮询空转** | 无任务时仍每 2s 查 DB | 可用信号量/notify 优化 |
| **maxDuration 5min** | 同步视频任务可能超时 | 确保所有长任务走队列 |

### 8.3 关键设计决策总结

```
┌──────────────────────────────────────────────────────────┐
│  Worker = Node.js 进程内轮询 (非 Web Worker, 非独立进程)  │
│  Pipeline = DB-backed 任务队列 + 显式 chain (非 DAG)     │
│  Dispatch = action 路由 → 同步流式 or 后台队列           │
│  Feedback = 同步 SSE (text) + 前端轮询 (task status)     │
│  Assets = versioned shot_assets + 级联 stale 机制        │
└──────────────────────────────────────────────────────────┘
```

---

## 附录：文件清单

| 文件 | 职责 |
|------|------|
| `src/lib/bootstrap.ts` | 启动入口：migrations → providers → handlers → worker |
| `src/lib/task-queue/worker.ts` | Worker 核心：轮询 + 任务分发 |
| `src/lib/task-queue/queue.ts` | 队列操作：enqueue/dequeue/complete/fail + 原子 claim |
| `src/lib/task-queue/types.ts` | 类型定义：Task, TaskType, TaskHandler, TaskHandlerMap |
| `src/lib/task-queue/index.ts` | 模块导出 |
| `src/lib/pipeline/index.ts` | Handler 注册：8 个 stage → registerHandlers |
| `src/lib/pipeline/script-outline.ts` | Stage 1: 创意 → 大纲 |
| `src/lib/pipeline/script-parse.ts` | Stage 2: 剧本 → 结构化 (auto-chain → character_extract) |
| `src/lib/pipeline/character-extract.ts` | Stage 3: 角色提取 + 关系 + 去重 |
| `src/lib/pipeline/character-image.ts` | Stage 4: 角色参考图生成 |
| `src/lib/pipeline/shot-split.ts` | Stage 5: 分镜拆解 + 场景 + 台词 |
| `src/lib/pipeline/frame-generate.ts` | Stage 6: 首帧/尾帧图像生成 |
| `src/lib/pipeline/video-generate.ts` | Stage 7: 视频生成 + 质量检查 |
| `src/lib/pipeline/video-assemble.ts` | Stage 8: FFmpeg 合成 |
| `src/lib/pipeline/video-quality-check.ts` | 视频质量评分 (best-effort) |
| `src/lib/pipeline/continuity-check.ts` | 帧间连续性检查 (best-effort) |
| `src/app/api/projects/[id]/generate/route.ts` | Pipeline 触发入口 (3895 行, 双轨路由) |
| `src/app/api/tasks/[id]/route.ts` | 任务状态查询端点 |
