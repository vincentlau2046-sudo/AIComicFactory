# 模块依赖分析（Module Dependency Analysis）

> 项目：AIComicBuilder（Next.js 16）
> 分析范围：`src/` 下全部 `.ts` / `.tsx`（共 **183** 个文件）
> 分析方法：`grep` 统计 `@/lib/...` 绝对路径 import + 相对路径 `../` 交叉 import，逐文件核对
> 只读分析，未修改任何源码

---

## 1. 模块依赖矩阵

### 1.1 五大核心模块总览

依赖方向统计（基于 `grep -o "@/lib/[a-z-]*"` 对每个模块目录内全部 import 的聚合计数）：

| 模块 | 被依赖方 → 本模块（次数） | 本模块 → 被依赖方（次数） |
|---|---|---|
| `lib/pipeline/` | `lib/ai`(29)、`lib/db`(16)、`lib/task-queue`(9)、`lib/shot-asset-utils`(3)、`lib/id`(2)、`lib/video`(1) | 无（无任何文件 import pipeline，除编排层 `bootstrap.ts`） |
| `lib/ai/` | `lib/pipeline`(29) | `lib/id`(9)、`lib/db`(2) |
| `lib/task-queue/` | `lib/pipeline`(9) | `lib/db`(3)、`lib/id`(1) |
| `lib/db/` | `lib/pipeline`(16)、`lib/task-queue`(3)、`lib/ai`(2) | 无（仅 `./schema` 相对引用与第三方包） |
| `lib/video/` | `lib/pipeline`(1) | `lib/id`(1) |

### 1.2 模块间依赖方向矩阵

行 = 依赖方，列 = 被依赖方；数字为该方向上出现的 import 语句次数：

| 依赖方 \ 被依赖方 | pipeline | ai | task-queue | db | video | id |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| **lib/pipeline** | — | 29 | 9 | 16 | 1 | 2 |
| **lib/ai** | 0 | — | 0 | 2 | 0 | 9 |
| **lib/task-queue** | 0 | 0 | — | 3 | 0 | 1 |
| **lib/db** | 0 | 0 | 0 | — | 0 | 0 |
| **lib/video** | 0 | 0 | 0 | 0 | — | 1 |

> 注：`lib/id`（`src/lib/id.ts`）为纯工具模块（`genId()`），不属于任务指定的五大模块，列在此处仅作完整性说明。

### 1.3 文件级依赖明细（pipeline handler）

| 文件 | 依赖的 `@/lib/*` 模块 | 相对/同模块引用 |
|---|---|---|
| `pipeline/character-extract.ts` | ai, db, id, task-queue | — |
| `pipeline/character-image.ts` | ai, db, task-queue | — |
| `pipeline/continuity-check.ts` | ai | — |
| `pipeline/frame-generate.ts` | ai, db, shot-asset-utils, task-queue | — |
| `pipeline/index.ts` | task-queue | `./character-*` 等 9 个同目录 handler（相对） |
| `pipeline/script-outline.ts` | ai, db, task-queue | — |
| `pipeline/script-parse.ts` | ai, db, task-queue | — |
| `pipeline/shot-split.ts` | ai, db, id, task-queue | — |
| `pipeline/video-assemble.ts` | db, shot-asset-utils, task-queue, video | — |
| `pipeline/video-generate.ts` | ai, db, shot-asset-utils, task-queue | — |
| `pipeline/video-quality-check.ts` | ai | — |

### 1.4 文件级依赖明细（ai / task-queue / video）

| 文件 | 依赖的 `@/lib/*` 模块 | 备注 |
|---|---|---|
| `ai/providers/dashscope-image.ts` | id | `../types`(相对) ×9 系 `TextOptions` 等 |
| `ai/providers/gemini.ts` | id | `../types`、`./providers/seedance` 等 |
| `ai/providers/kling-image.ts` | id | |
| `ai/providers/kling-video.ts` | id | |
| `ai/providers/openai.ts` | id | |
| `ai/providers/seedance.ts` | id | |
| `ai/providers/ucloud-seedance.ts` | id | |
| `ai/providers/veo.ts` | id | |
| `ai/providers/wan-video.ts` | id | |
| `ai/setup.ts` | db/schema, db | 初始化 Provider 时读库 |
| `ai/index.ts` / `types.ts` / `ai-sdk.ts` / `agent-caller.ts` / `provider-factory.ts` | —（仅相对/第三方） | |
| `task-queue/queue.ts` | db, id | |
| `task-queue/types.ts` | db | |
| `task-queue/worker.ts` / `index.ts` | — | `index.ts` 仅重导出 |
| `video/ffmpeg.ts` | id | |

---

## 2. 循环依赖检测

**结论：五大模块间不存在循环依赖。**

依据：
- `lib/db` 是严格依赖树的最底层（叶子）：`lib/db/*` 内**没有任何** `@/lib/*` 内部 import，仅引用 `./schema` 与第三方包（`drizzle-orm`、`better-sqlite3`、`node:*`）。
- `lib/pipeline` 是依赖树的顶层（消费者）：`grep -rln "@/lib/pipeline\|\.\./pipeline" src/lib/` 仅命中 `src/lib/bootstrap.ts`——该文件是应用编排入口（顺序调用 `runMigrations()` → `initializeProviders()` → `registerPipelineHandlers()` → `startWorker()`），**不属于** pipeline 模块内部，且无任何模块反向 import `bootstrap.ts`，不构成环。
- 依赖方向整体呈单向漏斗：`pipeline → {ai, task-queue, db, video} → {db, id} → (无)`。

潜在风险点（非循环，但需注意）：
- `lib/ai/setup.ts` 同时 import `@/lib/db`（初始化时读库获取 Provider 配置），而 `lib/pipeline` 的 handler 又依赖 `lib/ai` 的工厂。若未来 `lib/db` 反向依赖 `lib/ai`（例如在 schema 层做 AI 驱动的迁移），将立即形成 `pipeline → ai → db → ai` 环。
- `lib/task-queue/types.ts` 依赖 `lib/db`（任务表类型），`lib/db` 若反向 import task-queue 类型同样会成环——当前 `types.ts` 仅读取 `db/schema` 表定义，方向安全。

---

## 3. 耦合度量化

### 3.1 Pipeline handler 的 import 统计

统计口径：`grep -c "from \|require("` 计总 import 行数；`grep -c "@/lib"` 计跨模块（`@/lib/*`）import 行数。

| handler 文件 | import 总数 | 跨模块(@/lib) | 同模块/相对 | 跨模块占比 |
|---|---:|---:|---:|---:|
| `pipeline/video-generate.ts` | 13 | 9 | 4 | 69% |
| `pipeline/frame-generate.ts` | 12 | 8 | 4 | 67% |
| `pipeline/character-extract.ts` | 11 | 8 | 3 | 73% |
| `pipeline/shot-split.ts` | 10 | 8 | 2 | 80% |
| `pipeline/index.ts`（注册表） | 9 | 1 | 8 | 11% |
| `pipeline/script-parse.ts` | 8 | 8 | 0 | 100% |
| `pipeline/character-image.ts` | 7 | 6 | 1 | 86% |
| `pipeline/script-outline.ts` | 7 | 6 | 1 | 86% |
| `pipeline/video-assemble.ts` | 7 | 5 | 2 | 71% |
| `pipeline/video-quality-check.ts` | 2 | 1 | 1 | 50% |
| `pipeline/continuity-check.ts` | 1 | 1 | 0 | 100% |

观察：
- 10 个 handler 中 **9 个**跨模块 import 占比 ≥ 50%，`script-parse.ts`、`continuity-check.ts` 甚至达到 100% 跨模块——pipeline 层是典型的**汇聚层（hub）**，高度依赖 `lib/ai` 与 `lib/db`。
- `lib/ai` 是 pipeline 最重的外部依赖（29 次，约占 pipeline 全部 `@/lib` import 的 50%）。
- `pipeline/index.ts` 是唯一低耦合文件（仅 1 个跨模块 import），因为它只做 handler 注册，具体逻辑全部委托给各 handler。

### 3.2 Provider 层的 import 统计

| Provider 文件 | import 总数 | 跨模块(@/lib) | 说明 |
|---|---:|---:|---|
| `ai/provider-factory.ts` | 11 | 0（相对 import 工厂） | 聚合 9 个 Provider |
| `ai/providers/veo.ts` | 7 | 1 | Google GenAI SDK 较重 |
| `ai/providers/openai.ts` | 6 | 1 | |
| `ai/providers/gemini.ts` | 6 | 1 | |
| `ai/providers/kling-image.ts` | 5 | 1 | |
| `ai/providers/kling-video.ts` | 5 | 1 | |
| `ai/providers/dashscope-image.ts` | 4 | 1 | |
| `ai/providers/seedance.ts` | 4 | 1 | |
| `ai/providers/ucloud-seedance.ts` | 4 | 1 | |
| `ai/providers/wan-video.ts` | 4 | 1 | |
| `ai/setup.ts` | 4 | 2（db, db/schema） | 初始化时读库 |
| `ai/ai-sdk.ts` | 4 | 0 | `@ai-sdk/*` 封装 |
| `ai/agent-caller.ts` | 0 | 0 | 仅类型/工具函数 |

观察：
- 单个 Provider 文件 import 数很低（4–7），且对项目内部的唯一依赖是 `@/lib/id`（`genId()` 生成文件名）。**Provider 层是低耦合、高内聚的插件式结构**，每个 Provider 通过 `types.ts` 的接口与外部解耦。
- 真正的"聚合点"在 `provider-factory.ts`（11 个 import，集中了全部 9 个 Provider 的构造逻辑）与 `setup.ts`（引入 db 依赖做初始化配置读取）。
- `kling-image.ts` 与 `kling-video.ts` 各自实现完整的 Kling 鉴权（`generateKlingToken`），存在**跨文件重复代码**（同一算法两处实现），属可合并点。

### 3.3 胖模块识别（import 行数 > 15）

统计口径：全 `src/` 按 `grep -c "^import\|  import\|require("` 计 import 行数。

| import 行数 | 文件 |
|---:|---|
| **31** | `src/app/api/projects/[id]/generate/route.ts` |
| **22** | `src/app/[locale]/project/[id]/episodes/[episodeId]/storyboard/page.tsx` |

观察：
- 全项目仅 2 个文件 import > 15，均位于 `app/` 层（API 路由与页面），**`lib/` 层无胖模块**——核心业务层拆分良好。
- `generate/route.ts`（31）是当前最重模块：聚合了 pipeline 调用、任务队列、多类型生成（文本/图像/视频）参数解析。注意：该统计为 import **行数**（多行 `import { a,\n b }` 会重复计数），若按 import **语句数**统计实际值更低，但作为相对排序指标有效。
- 建议关注 `generate/route.ts`：若继续叠加新生成类型，可考虑将请求参数校验与分发逻辑下沉到 `lib/pipeline` 或独立 schema 层。

---

## 4. 结论摘要

1. **依赖方向清晰**：`pipeline`（消费者）→ `ai` / `task-queue` / `db` / `video`（服务）→ `db`（叶子），无循环依赖。
2. **pipeline 是耦合热点**：9/10 handler 跨模块 import 占比过半，`lib/ai` 是最大外部依赖（29 次）。
3. **Provider 层插件化良好**：单 Provider import 4–7，仅依赖 `lib/id` 工具；复杂度集中在 `provider-factory.ts` 与 `setup.ts`。
4. **lib/ 层无胖模块**：仅 2 个 app 层文件 import > 15。
5. **可优化点**：Kling 鉴权逻辑在 image/video 两处重复；`lib/ai/setup.ts` 对 db 的依赖是未来循环依赖风险的种子。

---

# 附章 A：npm 依赖矩阵（任务包 1 追加）

> 数据来源：`package.json`（声明约束）+ `pnpm-lock.yaml`（锁定解析，lockfileVersion 9.0，8727 行）
> 说明：本机未安装 pnpm（`pnpm list` 不可用），以下锁定版本与 peer 依赖均直接解析自 `pnpm-lock.yaml` 的 `importers.` 段；安装体积因无 `node_modules` 无法实测，改用包特性标注。

## A.1 生产依赖清单（29 项）

| 包 | 声明约束 | 锁定版本 | 关键路径 | 用途 |
|---|---|---|---|---|
| `next` | `16.1.6`（精确） | 16.1.6 | 前端核心 | App Router 框架（`output: standalone`） |
| `react` / `react-dom` | `19.2.3`（精确） | 19.2.3 | 前端核心 | UI 运行时 |
| `next-intl` | `^4.8.3` | 4.8.3 | 前端核心 | 国际化（zh/en/ja/ko 路由与消息） |
| `ai` | `^6.0.116` | 6.0.116 | pipeline/ai 关键 | Vercel AI SDK 核心（文本/图像模型统一入口） |
| `@ai-sdk/google` | `^3.0.43` | 3.0.43 | pipeline/ai 关键 | Google Gemini（文本模型） |
| `@ai-sdk/openai` | `^3.0.41` | 3.0.41 | pipeline/ai 关键 | OpenAI 兼容模型（文本） |
| `@google/genai` | `^1.44.0` | 1.44.0 | ai（Gemini/Veo Provider） | Google GenAI SDK（Veo 视频、Gemini 文本） |
| `openai` | `^6.27.0` | 6.27.0 | ai（OpenAI Provider） | OpenAI Node SDK |
| `drizzle-orm` | `^0.45.1` | 0.45.1 | db 关键 | ORM（SQLite，better-sqlite3 驱动） |
| `better-sqlite3` | `^12.6.2` | 12.6.2 | db 关键 | SQLite 原生驱动（`onlyBuiltDependencies`，需编译） |
| `fluent-ffmpeg` | `^2.1.3` | 2.1.3 | pipeline/video 关键 | 视频合成/抽取（`lib/video/ffmpeg.ts`） |
| `archiver` | `^7.0.1` | 7.0.1 | 前端非核心 | 项目打包下载 ZIP（`download/route.ts`） |
| `mammoth` | `^1.12.0` | 1.12.0 | 前端核心（导入） | docx → 文本（`import-utils.ts` / `upload-script`） |
| `unpdf` | `^1.4.0` | 1.4.0 | 前端核心（导入） | pdf → 文本（`@napi-rs/canvas` 依赖） |
| `pdfjs-dist` | `^5.5.207` | 5.5.207 | 间接 | 被 unpdf 依赖的 PDF 解析核心 |
| `nanoid` | `^5.1.7` | 5.1.7 | 全站基础 | `lib/id.ts` 的 `genId()`（12 位字母数字） |
| `ulid` | `^3.0.2` | 3.0.2 | 全站基础 | ULID 生成（与 nanoid 并存，需查用途） |
| `zustand` | `^5.0.11` | 5.0.11 | 前端核心 | 状态管理（project/episode/model/prompt-template/agent store） |
| `sonner` | `^2.0.7` | 2.0.7 | 前端核心 | toast 通知 |
| `lucide-react` | `^0.577.0` | 0.577.0 | 前端核心 | 图标库 |
| `@base-ui/react` | `^1.2.0` | 1.2.0 | 前端核心 | shadcn/base-nova 底层（无头组件） |
| `class-variance-authority` | `^0.7.1` | 0.7.1 | 前端核心 | shadcn 变体管理 |
| `clsx` | `^2.1.1` | 2.1.1 | 前端核心 | className 合并 |
| `tailwind-merge` | `^3.5.0` | 3.5.0 | 前端核心 | Tailwind 类去重 |
| `tw-animate-css` | `^1.4.0` | 1.4.0 | 前端核心 | Tailwind v4 动画 CSS |
| `shadcn` | `^4.0.2` | 4.0.2 | 前端核心（CLI） | shadcn CLI（运行时依赖，可疑） |
| `@types/archiver` | `^7.0.0` | 7.0.0 | — | **类型包误入 dependencies** |

## A.2 开发依赖清单（11 项）

| 包 | 声明约束 | 锁定版本 | 用途 |
|---|---|---|---|
| `typescript` | `^5` | 5.9.3 | 编译/类型检查 |
| `eslint` | `^9` | 9.39.4 | Lint |
| `eslint-config-next` | `16.1.6`（精确） | 16.1.6 | Next 官方 ESLint 配置（与 next 对齐） |
| `tailwindcss` | `^4` | 4.2.1 | Tailwind v4（CSS-first，无 config 文件） |
| `@tailwindcss/postcss` | `^4` | 4.2.1 | Tailwind v4 PostCSS 插件 |
| `drizzle-kit` | `^0.31.9` | 0.31.9 | 迁移生成（`drizzle/*.sql`） |
| `@types/node` | `^20` | 20.19.37 | Node 类型 |
| `@types/react` / `@types/react-dom` | `^19` | 19.2.14 / 19.2.3 | React 类型 |
| `@types/better-sqlite3` | `^7.6.13` | 7.6.13 | 原生驱动类型 |
| `@types/fluent-ffmpeg` | `^2.1.28` | 2.1.28 | ffmpeg 类型 |

## A.3 版本约束分布

| 约束类型 | 数量 | 包 |
|---|---|---|
| `^`（minor 可浮动） | 37 | 绝大多数（含 `^4` 大版本浮动：tailwindcss、@tailwindcss/postcss；`^5`：typescript；`^9`：eslint；`^19`/`^20`：类型包） |
| 精确（无浮动） | 4 | `next 16.1.6`、`react 19.2.3`、`react-dom 19.2.3`、`eslint-config-next 16.1.6` |
| `~` | 0 | — |

**观察**：
- 框架三件套（next/react/react-dom/eslint-config-next）全部锁死精确版本，避免大版本漂移——合理。
- 生产依赖存在 `^4`/`^5`/`^9` 这种"大版本裸浮动"约束（typescript、eslint、tailwindcss），`pnpm install` 会拉到当前最新大版本内的最新 minor；由于 lockfile 已提交，实际运行版本是锁定的，风险有限。
- `shadcn`（CLI 工具）与 `@types/archiver` 放在 `dependencies` 属误置：前者应属 devDependencies（仅交互式 CLI 使用），后者是纯类型包。

## A.4 风险标记

### A.4.1 版本滞后（对比 2026-08-06 npm 最新版）

| 包 | 锁定 | 最新 | 差距 | 风险说明 |
|---|---|---|---|---|
| `@google/genai` | 1.44.0 | 2.15.0 | 主版本 +1 | 2.x 为 2026 年持续迭代线；1.44 已落后 ~15 个 minor |
| `ai`（AI SDK） | 6.0.116 | 7.0.52 | 主版本 +1 | v7 有破坏性变更（provider API）；v6 仍受维护 |
| `openai` | 6.27.0 | 7.4.0 | 主版本 +1 | 7.x 要求 Node 22+；6.x 仍受支持 |
| `pdfjs-dist` | 5.5.207 | 6.2.108 | 主版本 +1 | 6.x 为 2026 新主线；5.x 仍在维护 |
| `better-sqlite3` | 12.6.2 | 13.0.3 | 主版本 +1 | **13.0 是 N-API 重写**（移除 prebuild-install，跨 Node 版本二进制兼容）；12.x 仍安全 |
| `drizzle-orm` | 0.45.1 | 0.45.2 / 1.0.0-rc.x | minor 差 1 | 1.0 已进入 RC，0.45 是 1.0 前最后稳定线 |
| `next` | 16.1.6 | 16.3.0 | minor 差 4 | 同主版本内滞后，16.3 为 2026-08-03 发布（Instant Navigations） |
| `next-intl` | 4.8.3 | 4.13.5 | minor 差 5 | 同主版本内滞后 |
| `tailwindcss` | 4.2.1 | 4.3.3 | minor 差 2 | 同主版本内滞后 |
| `zustand` | 5.0.11 | 5.0.14 | patch 差 3 | 无风险 |

**结论**：没有任何包落后 ≥2 个主版本；5 个包落后恰好 1 个主版本（均非废弃状态），无紧急升级压力。

### A.4.2 已知废弃/停滞风险

- **`fluent-ffmpeg` 2.1.3**（2021-10 后无新版本）：npm 已标记为长期未维护（unmaintained），仅有 `@types/fluent-ffmpeg` 在维护。它是 `pipeline/video-assemble` 与 `lib/video/ffmpeg.ts` 的**关键路径**（视频合成/抽帧），替代方案为 `ffmpeg-static` + 原生 `child_process` 或 `ffmpeg.wasm`。风险：未来 Node 版本兼容性问题无人修。
- **`mammoth` 1.12.0**（2025 年后更新频率低）：docx 解析仍在维护，风险中低。
- **`ulid` 3.0.2**：与 `nanoid` 并存（`lib/id.ts` 用 nanoid），需确认 ulid 是否有真实调用点（见下）。

### A.4.3 体积敏感包

| 包 | 体积特征 | 说明 |
|---|---|---|
| `better-sqlite3` | 原生二进制，安装 ~10-40MB | `onlyBuiltDependencies` 白名单内；`serverExternalPackages` 排除出 bundle |
| `pdfjs-dist` | 分发包 6MB+ | 被 unpdf 引入，仅服务端解析 |
| `unpdf` | 依赖 `@napi-rs/canvas`（原生） | pdf 渲染路径；与 pdfjs-dist 功能重叠（见 A.5） |
| `@google/genai` | 中（SDK 带 MCP 依赖） | 锁文件显示 peer `@modelcontextprotocol/sdk@1.27.1` |
| `sharp` | 原生 | **在 lockfile `ignoredBuiltDependencies` 中**（postinstall 被忽略，Docker 部署时需显式处理，见 config-audit） |
| `msw` | 中 | 锁文件 `onlyBuiltDependencies` 中出现——但 package.json 无 msw 声明，系传递依赖（疑似测试残留） |

### A.4.4 其他风险

1. **`@types/archiver` 在生产依赖**：类型包放 dependencies，增加无意义生产安装体积（A.1 已标）。
2. **`sharp` 构建脚本被忽略**（`pnpm-workspace.yaml` 的 `ignoredBuiltDependencies: [sharp, unrs-resolver]`）：若 next/image 在运行时用到 sharp 且未单独安装，会退化为纯 JS 或报错——需确认部署镜像是否单独处理（见 Dockerfile 分析，config-audit.md）。
3. **`msw` 出现在 onlyBuiltDependencies 但非直接依赖**：可能来自 `@base-ui/react` 或测试工具链的传递依赖，属残留配置。
4. **Node 版本基线**：`@types/node ^20` 锁定 Node 20 类型，但 openai 7.x 已要求 Node 22+，`next 16` 亦要求 Node 20.9+。当前运行环境 Node 24.17（实测），无冲突；但若按 @types/node 20 部署，需确认实际 Node 版本 ≥20.9。

## A.5 依赖树要点（pnpm-lock.yaml 解析）

- **`ai@6.0.116`** → `@ai-sdk/provider-utils`、`@ai-sdk/gateway` 等（zod@4.3.6 peer）——**zod v4 是 AI SDK 生态的统一 peer**（`@ai-sdk/google`、`@ai-sdk/openai`、`openai` 全部 peer zod@4.3.6）。
- **`next@16.1.6`** peer：react 19.2.3、react-dom 19.2.3、`@opentelemetry/api@1.9.0`（可选）。
- **`unpdf@1.4.0`** → `@napi-rs/canvas@0.1.97`；**`pdfjs-dist@5.5.207`** 同为 unpdf 的解析后端——两者在 `upload-script/route.ts`（unpdf）与 `import-utils.ts`（unpdf）中实际使用；`pdfjs-dist` 无直接 import（经 grep 确认），**疑似冗余依赖**。
- **`drizzle-orm@0.45.1`** 带可选 peer：`@opentelemetry/api`、`@types/better-sqlite3`、`better-sqlite3`——当前均满足。
- **`ulid@3.0.2`**：grep `from "ulid"` 未命中 src 直接引用，**疑似未使用依赖**（与 nanoid 职责重叠，建议核对后移除）。
- **`shadcn@4.0.2`**：dependencies 中的 CLI 包，运行时仅构建期使用。

## A.6 结论摘要（依赖维度）

1. 依赖版本整体健康：无 ≥2 主版本滞后，无已废弃核心包。
2. 关键路径依赖集中在 5 个包：`ai`/`@ai-sdk/*`（文本）、`openai`/`@google/genai`（各 Provider）、`drizzle-orm`+`better-sqlite3`（DB）、`fluent-ffmpeg`（视频）。
3. 需要关注：`fluent-ffmpeg` 停滞维护（关键路径）、`pdfjs-dist` 疑似冗余、`ulid` 疑似未使用、`sharp` 构建脚本被忽略、`@types/archiver` 与 `shadcn` 误置 dependencies。
4. 升级优先级建议：无紧急项；如升级 `better-sqlite3` 至 13.x 应验证 N-API 预编译在目标 Node/架构可用（Docker multi-arch 需特别注意）。
