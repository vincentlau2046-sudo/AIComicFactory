# 配置层全量审计（Config Audit）

> 项目：AIComicBuilder（Next.js 16.1.6 / React 19.2.3 / Tailwind v4 / drizzle-orm 0.45）
> 分析日期：2026-08-06
> 方法：逐文件读取全部配置文件 + `grep -rhoE 'process\.env\.[A-Z_]+'` 全量对照
> 只读分析，未修改任何源码

---

## 1. 配置文件清单总览

| 文件 | 类型 | 核心职责 | 风险等级 |
|---|---|---|---|
| `next.config.ts` | Next.js 配置 | standalone 输出、serverExternalPackages、turbopack、next-intl 插件 | 🟢 正常 |
| `drizzle.config.ts` | DB 迁移配置 | SQLite 方言、schema 路径、DATABASE_URL | 🟢 正常 |
| `tsconfig.json` | TypeScript | strict、bundler resolution、`@/*` 路径别名 | 🟢 正常 |
| `postcss.config.mjs` | PostCSS | Tailwind v4 插件（仅此一项） | 🟢 正常 |
| `eslint.config.mjs` | ESLint 扁平配置 | next core-web-vitals + typescript 规则 | 🟢 正常 |
| `components.json` | shadcn 配置 | base-nova 风格、Tailwind v4 无 config 模式 | 🟢 正常 |
| `src/proxy.ts` | 中间件（Next 16） | 国际化路由 + 匿名用户 cookie | 🟡 注意（见 5.3） |
| `src/instrumentation.ts` | 启动钩子 | bootstrap 入口 | 🟢 正常 |
| `src/lib/bootstrap.ts` | 编排启动 | 迁移 → Provider → handler → worker | 🟢 正常 |
| `.env.example` | 环境变量模板 | 仅 2 个变量（覆盖率 11%） | 🔴 风险（见 6） |
| `pnpm-workspace.yaml` | pnpm 构建白名单 | onlyBuilt / ignoredBuilt 依赖 | 🟡 注意（见 8） |
| `Dockerfile` | 部署镜像 | Node 20 + ffmpeg + standalone | 🟡 注意（见 8） |
| `src/i18n/routing.ts` / `request.ts` | 国际化配置 | 4 locale 路由 + 消息加载 | 🟢 正常 |

**Tailwind 配置说明**：项目**没有 `tailwind.config.*`**——Tailwind v4 采用 CSS-first 配置（`@import "tailwindcss"` + `@theme inline` 于 `src/app/globals.css`），这是 v4 的官方推荐模式，`components.json` 中 `"config": ""` 与之呼应。

---

## 2. `next.config.ts` 详解

```ts
import type { NextConfig } from "next";
import path from "node:path";
import createNextIntlPlugin from "next-intl/plugin";

const withNextIntl = createNextIntlPlugin("./src/i18n/request.ts");

const nextConfig: NextConfig = {
  output: "standalone",                 // 产出可独立部署的 server.js（Dockerfile 依赖此产物）
  serverExternalPackages: ["better-sqlite3"], // 原生模块不参与打包（Node 侧 require）
  turbopack: {
    root: path.resolve(process.cwd()),  // 显式指定 turbopack 根目录
  },
};

export default withNextIntl(nextConfig);
```

| 配置项 | 值 | 作用 | 备注 |
|---|---|---|---|
| `output` | `"standalone"` | 最小化 server 产物，`Dockerfile` 直接 `COPY .next/standalone` | 与 Docker 部署强耦合 |
| `serverExternalPackages` | `["better-sqlite3"]` | 原生二进制排除出 bundle，运行期动态 require | 与 `lib/db/index.ts` 的"dynamic require 避免构建期加载"注释吻合 |
| `turbopack.root` | `process.cwd()` | 显式根目录 | Next 16 默认 turbopack |
| next-intl 插件 | `./src/i18n/request.ts` | 每个请求按 `requestLocale` 加载消息 | 依赖 `src/proxy.ts` 提供 locale 前缀 |

**未配置项（默认值，无需关注）**：无 `i18n`（next-intl 接管）、无 `rewrites`/`redirects`、无 `images.remotePatterns`、无 `experimental` 选项。

---

## 3. `drizzle.config.ts` 详解

```ts
export default defineConfig({
  schema: "./src/lib/db/schema.ts",
  out: "./drizzle",
  dialect: "sqlite",
  dbCredentials: {
    url: process.env.DATABASE_URL || "file:./data/aicomic.db",
  },
});
```

| 配置项 | 值 | 说明 |
|---|---|---|
| `schema` | `./src/lib/db/schema.ts` | 唯一 schema 源 |
| `out` | `./drizzle` | 迁移文件输出（当前 53 个迁移 `0000`–`0053`） |
| `dialect` | `sqlite` | better-sqlite3 驱动 |
| `dbCredentials.url` | `process.env.DATABASE_URL \|\| "file:./data/aicomic.db"` | 与代码默认值一致（`lib/db/index.ts:20` 同样兜底 `./data/aicomic.db`） |

**一致性确认**：drizzle.config 的默认路径与运行时代码的兜底路径完全一致，无漂移。Dockerfile 中通过 `ENV DATABASE_URL=file:/app/data/aicomic.db` 覆盖为绝对路径。

---

## 4. `tsconfig.json` 要点

| 配置项 | 值 | 影响 |
|---|---|---|
| `target` | `ES2017` | 偏低，但 Next 会按需转换；影响原生 API 类型可用性 |
| `strict` | `true` | 全程严格模式 |
| `moduleResolution` | `"bundler"` | Next 16 推荐（turbopack 兼容） |
| `paths` | `"@/*": ["./src/*"]` | 全项目统一别名 |
| `plugins` | `[{ "name": "next" }]` | Next 类型插件 |
| `jsx` | `"react-jsx"` | 自动 JSX runtime |
| `include` | 含 `.next/types/**/*.ts`、`.next/dev/types/**/*.ts`、`**/*.mts` | 覆盖 Next 生成的类型 |

无 `noUncheckedIndexedAccess`、无 `exactOptionalPropertyTypes`——类型强度中等，未开启最大严格度。

---

## 5. 中间件与启动链

### 5.1 `src/proxy.ts`（Next.js 16 中间件，原 `middleware.ts` 更名）

```ts
import createMiddleware from "next-intl/middleware";
import { routing } from "./i18n/routing";

const COOKIE_NAME = "ai_comic_uid";
const intlMiddleware = createMiddleware(routing);

export default function proxy(request: NextRequest) {
  const response = intlMiddleware(request);
  // 匿名用户 cookie：缺失则写入 crypto.randomUUID()（无横线）
  if (!request.cookies.get(COOKIE_NAME)) {
    const uid = crypto.randomUUID().replace(/-/g, "");
    response.cookies.set(COOKIE_NAME, uid, { maxAge: 365*24*60*60, path: "/", sameSite: "lax" });
  }
  return response;
}

export const config = { matcher: ["/((?!api|_next|_vercel|.*\\..*).*)"] };
```

**职责**：
1. **locale 检测/重定向**：`createMiddleware(routing)` 处理 `[locale]` 段（zh/en/ja/ko，默认 zh）——替换传统 `i18n` 配置。
2. **匿名身份 cookie**：`ai_comic_uid`（365 天，lax）→ 服务端组件按 `userId` 查询数据；客户端 `FingerprintProvider` 会覆盖为真实指纹。
3. **matcher 排除**：`api`、`_next`、`_vercel`、带扩展名的静态资源不经过中间件。

### 5.2 `src/instrumentation.ts`（启动钩子）↔ `src/lib/bootstrap.ts`

```ts
// instrumentation.ts —— Next.js 生命周期钩子
export async function register() {
  if (process.env.NEXT_RUNTIME === "nodejs") {
    const { bootstrap } = await import("@/lib/bootstrap"); // 动态 import，避免打包期执行
    bootstrap();
  }
}
```

```ts
// bootstrap.ts —— 应用编排入口（幂等，bootstrapped 标志防重复）
export function bootstrap() {
  if (bootstrapped) return;
  bootstrapped = true;
  runMigrations();          // lib/db —— 执行 drizzle 迁移
  initializeProviders();    // lib/ai/setup —— 读库初始化 9 个 Provider
  registerPipelineHandlers(); // lib/pipeline —— 注册 10 个任务 handler
  startWorker();            // lib/task-queue —— 启动后台 worker
}
```

**关系结论**：
- `instrumentation.ts` 是 **Next.js 的注册点**（build/dev/prod 的 server 启动时调用），`bootstrap.ts` 是**实际编排逻辑**——两者通过一层薄封装解耦，便于直接调用测试。
- 启动顺序固定：**迁移 → Provider → handler 注册 → worker**。`initializeProviders` 读库依赖迁移先完成，顺序正确。
- 约束：仅在 `NEXT_RUNTIME === "nodejs"` 执行（排除 edge runtime 与构建期），符合注释"not during build or edge runtime"。
- **一致性确认**：`instrumentation.ts` 只做环境判断 + 委托，无重复逻辑。

### 5.3 中间件风险点

- **`ai_comic_uid` 无前缀作用域**：`path: "/"` + 无 `domain`，在子域名部署或同域多应用时会互相覆盖 cookie。
- **matcher 未排除 `favicon` 等**：`.*\..*` 已覆盖带扩展名路径；`favicon.ico` 命中排除规则，正常。
- **uid 用 `crypto.randomUUID()` 而非 `genId()`**：两套 ID 体系（24 位 hex vs nanoid 12 位字母数字）——若 DB 中 `userId` 有格式校验需注意（当前为 TEXT 列，无校验）。
- **`NODE_ENV` 未参与**：cookie 始终写入（包括 build 期预渲染——但 build 期无请求，实际无影响）。

---

## 6. 环境变量审计（核心风险）

### 6.1 `.env.example` 现状（仅 2 个变量）

```
DATABASE_URL=file:./data/aicomic.db
UPLOAD_DIR=./uploads
```

### 6.2 代码实际使用（`grep -rhoE 'process\.env\.[A-Z_]+' src/ scripts/` 全量统计）

| 变量 | 出现次数 | 使用位置 | `.env.example` 有？ |
|---|---|---|---:|
| `UPLOAD_DIR` | 24 | pipeline/video-generate、generate route、upload route、gemini provider 等 | ✅ |
| `DATABASE_URL` | 1 | `lib/db/index.ts:20` | ✅ |
| `GEMINI_API_KEY` | 3 | `providers/gemini.ts:14` | ❌ |
| `SEEDANCE_API_KEY` | 2 | `providers/seedance.ts:40` | ❌ |
| `OPENAI_API_KEY` | 2 | `providers/openai.ts` | ❌ |
| `KLING_SECRET_KEY` | 2 | `providers/kling-image/video.ts`（generateKlingToken） | ❌ |
| `KLING_ACCESS_KEY` | 2 | 同上 | ❌ |
| `DASHSCOPE_API_KEY` | 2 | `providers/dashscope-image.ts` | ❌ |
| `WAN_MODEL` | 1 | `providers/wan-video.ts` | ❌ |
| `WAN_BASE_URL` | 1 | `providers/wan-video.ts` | ❌ |
| `WAN_API_KEY` | 1 | `providers/wan-video.ts` | ❌ |
| `SEEDANCE_MODEL` | 1 | `providers/seedance.ts:47` | ❌ |
| `SEEDANCE_BASE_URL` | 1 | `providers/seedance.ts:43` | ❌ |
| `OPENAI_MODEL` | 1 | `providers/openai.ts` | ❌ |
| `OPENAI_BASE_URL` | 1 | `providers/openai.ts` | ❌ |
| `DASHSCOPE_IMAGE_MODEL` | 1 | `providers/dashscope-image.ts` | ❌ |
| `DASHSCOPE_BASE_URL` | 1 | `providers/dashscope-image.ts` | ❌ |
| `NEXT_RUNTIME` | 1 | `instrumentation.ts`（Next 注入，无需配置） | —（框架变量） |
| `NODE_ENV` | 2 | `lib/db/index.ts`（全局缓存开关） | —（框架变量） |

### 6.3 覆盖率结论

- **代码引用 17 个业务变量，`.env.example` 仅覆盖 2 个（`DATABASE_URL`、`UPLOAD_DIR`），覆盖率 ≈ 11.8%**。
- 缺失的 15 个全部是 **Provider API Key / BaseURL / Model**（Gemini、OpenAI、Dashscope、Kling、Seedance、WAN）。
- **缓解因素**：项目是**无登录的匿名本地/自托管工具**，API Key 主要经 UI（`model-store.ts` → DB `agents`/`modelConfig` 表）持久化，环境变量仅是 Provider 构造时的兜底（`params?.apiKey || process.env.X || ""`）。因此"未入 example"不等于"不可用"，但新部署者无法仅凭 `.env.example` 得知存在这些变量。
- **建议**：将 6.2 表完整加入 `.env.example`（注释标记为可选兜底），并说明 UI 配置优先。

---

## 7. 其余配置文件

### 7.1 `postcss.config.mjs`

```js
const config = { plugins: { "@tailwindcss/postcss": {} } };
```
Tailwind v4 唯一入口，与 globals.css 的 `@import "tailwindcss"` 配套。无 autoprefixer（v4 内置）。

### 7.2 `eslint.config.mjs`

扁平配置（ESLint 9）：`eslint-config-next/core-web-vitals` + `typescript` 规则 + `globalIgnores`（`.next/**`、`out/**`、`build/**`、`next-env.d.ts`）。**未启用 `strict` 变体**（eslint-config-next 提供 `core-web-vitals`/`typescript`/`strict` 三档），Lint 强度为中等。

### 7.3 `components.json`（shadcn）

| 项 | 值 |
|---|---|
| style | `base-nova`（新 shadcn 默认风格） |
| tailwind.config | `""`（v4 无配置文件） |
| css | `src/app/globals.css` |
| baseColor | neutral |
| iconLibrary | lucide |
| aliases | `@/components`、`@/components/ui`、`@/lib/utils` 等 |

### 7.4 `src/i18n/`

```ts
// routing.ts
export const routing = defineRouting({
  locales: ["zh", "en", "ja", "ko"],
  defaultLocale: "zh",
});
```

- `request.ts`：`getRequestConfig` 按 `requestLocale` 动态 `import("../../messages/${locale}.json")`，无效 locale 回退 zh。与 `messages/`（zh/en/ja/ko 4 个 JSON）对应。

---

## 8. 部署与构建配置（pnpm-workspace.yaml / Dockerfile）

### 8.1 `pnpm-workspace.yaml`（构建脚本白名单）

```yaml
ignoredBuiltDependencies:
  - sharp        # 🔴 next/image 依赖，postinstall 被忽略
  - unrs-resolver
onlyBuiltDependencies:
  - better-sqlite3   # 原生驱动，必须编译
  - esbuild
  - protobufjs
  - '@parcel/watcher'
  - '@swc/core'
  - msw
```

**风险点**：
1. **`sharp` 在 `ignoredBuiltDependencies`**：Next 16 的 `next/image` 默认用 sharp 做图像优化。忽略其 postinstall 后，若项目未显式安装 sharp 二进制（v0.33+ 默认随 npm 包带预编译），standalone 产物可能缺优化能力或运行时报错。**但**：当前项目未配置 `images`，前端图像多为 AI 生成的远程/本地文件，需实测 `next/image` 路径是否真正触发 sharp。
2. **`msw` 出现在 onlyBuiltDependencies 但 package.json 无此依赖**：系传递依赖（测试/开发工具链残留），白名单冗余但不影响生产。

### 8.2 `Dockerfile`

```dockerfile
FROM node:20-alpine AS base          # Node 20（非 22+，openai 7.x 需 Node 22 —— 当前锁定 openai 6.x 兼容）
RUN apk add --no-cache ffmpeg font-noto-cjk   # ffmpeg 系统级安装 → fluent-ffmpeg 无需 npm 二进制
...
COPY --from=builder /app/.next/standalone ./
ENV DATABASE_URL="file:/app/data/aicomic.db"
ENV UPLOAD_DIR="/app/uploads"
CMD ["node", "server.js"]
```

**与配置层的关系**：
- `output: "standalone"` 与 Docker 部署方式强一致 ✅。
- ffmpeg 由 Alpine 包提供（`apk add ffmpeg`），与 `fluent-ffmpeg`（npm 包装层）配套——**系统需含 `ffmpeg` 可执行文件**，本 Dockerfile 已满足。
- `font-noto-cjk` 为中文字幕烧录（video-assemble）提供字体。
- **注意**：`deps` 阶段 `apk add python3 make g++` 仅为 better-sqlite3 编译；但 runner 阶段未再装编译工具，说明 better-sqlite3 预编译产物已进入 standalone（与 pnpm onlyBuiltDependencies 编译步骤匹配）。

---

## 9. 配置层风险汇总

| # | 风险 | 严重度 | 位置 | 建议 |
|---|---|---|---|---|
| 1 | `.env.example` 覆盖率 11.8%，15 个 API Key/Model 变量缺失 | 🔴 中 | `.env.example` | 补齐 6.2 表全部变量（标注可选） |
| 2 | `sharp` postinstall 被忽略，next/image 优化能力存疑 | 🟡 低 | `pnpm-workspace.yaml` | 验证 `next/image` 实际路径；如未用可忽略 |
| 3 | `ai_comic_uid` cookie 全路径无 domain 限制 | 🟡 低 | `src/proxy.ts` | 多应用同域部署时加前缀/作用域 |
| 4 | 匿名 ID 双体系（randomUUID vs nanoid） | 🟡 低 | `proxy.ts` vs `lib/id.ts` | 统一为 `genId()` |
| 5 | `target: ES2017` + 未开 `noUncheckedIndexedAccess` 等 | 🟢 低 | `tsconfig.json` | 可按需收紧 |
| 6 | eslint 未启用 `strict` 档 | 🟢 低 | `eslint.config.mjs` | 可选升级 |
| 7 | Docker Node 20 基线（openai 7.x 要求 Node 22+） | 🟢 低 | `Dockerfile` | 若升级 openai 7.x 需同步升 Node 镜像 |
| 8 | `msw` 残留于 onlyBuiltDependencies | 🟢 无 | `pnpm-workspace.yaml` | 清理 |

## 10. 结论摘要

1. **核心配置自洽**：`next.config.ts`（standalone）↔ `Dockerfile`、`drizzle.config.ts` ↔ 运行时代码默认路径、`instrumentation.ts` ↔ `bootstrap.ts` 三层启动链全部一致，无配置漂移。
2. **中间件**：Next 16 已用 `src/proxy.ts` 取代 `middleware.ts`（next-intl 路由 + 匿名 cookie），matcher 正确排除 api/静态资源。
3. **最大缺口是环境变量文档**：`.env.example` 仅覆盖 2/17 业务变量，新部署者无法发现 Provider 兜底变量。
4. Tailwind v4 采用 CSS-first 配置（无 tailwind.config 文件），`components.json` 与 postcss 配套完整。
