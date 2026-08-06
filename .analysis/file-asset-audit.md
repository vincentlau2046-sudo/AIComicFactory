# AIComicBuilder 文件系统与资产管理审计

> 审计日期: 2026-08-06  
> 范围: 上传目录、临时文件、上传路由、清理策略、大文件处理  
> 状态: 只读分析，未修改源码

---

## 1. UPLOAD_DIR 环境变量

### 1.1 配置

| 项目 | 值 |
|------|-----|
| 环境变量名 | `UPLOAD_DIR` |
| 默认值 | `./uploads`（相对于 `process.cwd()`） |
| 声明位置 | `.env.example` 中声明为 `UPLOAD_DIR=./uploads` |

### 1.2 传播路径

`UPLOAD_DIR` 通过 **三层传递** 到达各消费者：

```
.env (UPLOAD_DIR)
  → 各 route / provider 构造函数 (process.env.UPLOAD_DIR || "./uploads")
    → provider 实例.uploadDir 字段
      → path.join(this.uploadDir, "frames") 等子目录
```

| 消费者 | 文件 | 获取方式 |
|--------|------|----------|
| Shot upload route | `src/app/api/projects/[id]/shots/[shotId]/upload/route.ts` | `process.env.UPLOAD_DIR` |
| Character upload route | `src/app/api/projects/[id]/characters/[characterId]/upload/route.ts` | `process.env.UPLOAD_DIR` |
| Upload serving route | `src/app/api/uploads/[...path]/route.ts` | `process.env.UPLOAD_DIR` |
| FFmpeg 装配 | `src/lib/video/ffmpeg.ts` | `process.env.UPLOAD_DIR` |
| Video pipeline | `src/lib/pipeline/video-generate.ts` | `getVersionedUploadDirFromPipeline()` |
| Generate route | `src/app/api/projects/[id]/generate/route.ts` | `getVersionedUploadDir()` |
| 全部 AI Provider | `src/lib/ai/providers/*.ts` | 构造函数 `params?.uploadDir || process.env.UPLOAD_DIR` |
| Provider 工厂 | `src/lib/ai/provider-factory.ts` | `resolveImageProvider(modelConfig, uploadDir)` |

### 1.3 版本化上传目录

**仅视频生成** 支持版本化子目录：

```typescript
// 有 versionId → projects/{projectId}/{versionLabel}/
// 无 versionId  → UPLOAD_DIR 根目录
path.join(process.env.UPLOAD_DIR, "projects", version.projectId, version.label)
```

此机制在 `video-generate.ts` 和 `generate/route.ts` 中重复实现（同名函数 `getVersionedUploadDir`/`getVersionedUploadDirFromPipeline`），属于 **代码重复**（未提取到共享工具函数）。

---

## 2. 目录结构与存储路径

### 2.1 物理目录树（逻辑布局）

```
UPLOAD_DIR/
├── frames/              # AI 生成的帧图片 (first_frame, last_frame)
│   └── {nanoid}.{ext}  # 由 AI Provider (Gemini/OpenAI/Kling 等) 写入
├── videos/              # AI 生成的视频
│   ├── {nanoid}.mp4     # AI Provider 直接写入
│   ├── {projectId}-concat-{nanoid}.mp4  # FFmpeg 中间产物
│   ├── {projectId}-final-{nanoid}.mp4 # FFmpeg 最终产物
│   └── title-{nanoid}.mp4              # FFmpeg 标题卡片
├── images/              # Kling/DashScope 图片输出
│   └── {nanoid}.{ext}
├── characters/            # 角色参考图片
│   └── {nanoid}.{ext}
└── projects/
    └── {projectId}/
        └── {versionLabel}/
            ├── frames/   # 版本化帧（视频 provider 写入）
            └── videos/   # 版本化视频
```

### 2.2 各组件的存储约定

| 来源 | 子目录 | 命名模式 | 写入者 |
|------|--------|----------|--------|
| User → Shot 上传 | `frames/` | `{nanoid}.{ext}` | `writeFileSync` (同步) |
| User → Character 上传 | `characters/` | `{nanoid}.{ext}` | `writeFileSync` (同步) |
| AI 图片 Provider | `frames/` 或 `images/` | `{nanoid}.{ext}` | Provider `writeFileSync` |
| AI 视频 Provider | `videos/` | `{nanoid}.mp4` | Provider `writeFileSync` |
| FFmpeg 输出 | `videos/` | `{projectId}-{type}-{nanoid}.mp4` | fluent-ffmpeg 异步 |
| 版本化产物 | `projects/{id}/{label}/` | 同 Provider 规则 | Provider |

### 2.3 文件命名

全部使用 **nanoid**（12 字符，62 进制字母数字）+ 原始扩展名：

```typescript
import { customAlphabet } from "nanoid";
const generate = customAlphabet("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz", 12);
// 例: "a3Kq9LmX2pRb"  →  "a3Kq9LmX2pRb.png"
```

- ✅ 全局唯一（62^12 ≈ 3.2×10^21 空间）
- ✅ URL-safe，无需编码
- ❌ 无时间戳信息，无法从文件名判断创建时间

---

## 3. 文件上传路由

### 3.1 Shot 上传 (`/api/projects/[id]/shots/[shotId]/upload`)

```
POST /api/projects/{id}/shots/{shotId}/upload
  Content-Type: multipart/form-data
  Body: { file: File, field: string }
```

| 特性 | 实现 |
|------|------|
| 认证 | `assertProjectOwnership(request, projectId)` — 请求者必须拥有该项目 |
| 校验 | `field` 白名单: `firstFrame`, `lastFrame`, `sceneRefFrame`, `reference_image` |
| 存储 | `fs.writeFileSync(filepath, buffer)` — 同步写入，阻塞事件循环 |
| DB 更新 | 写入 shots 表对应字段（`reference_image` 除外，仅返回路径） |
| 覆盖策略 | **不覆盖** — 每次上传生成新文件名，旧路径保留在 DB 中但磁盘文件成为孤儿 |

### 3.2 Character 上传 (`/api/projects/[id]/characters/[characterId]/upload`)

```
POST /api/projects/{id}/characters/{characterId}/upload
  Content-Type: multipart/form-data
  Body: { file: File }
```

| 特性 | 实现 |
|------|------|
| 认证 | `assertProjectOwnership` |
| 存储 | `fs.writeFileSync` — 同步写入 `characters/` 目录 |
| 历史管理 | `referenceImageHistory` (JSON 数组) 追加式，**仅记录路径不删除旧文件** |
| 覆盖策略 | 同 Shot — 新文件名，旧文件成为磁盘孤儿 |

### 3.3 文件服务 (`/api/uploads/[...path]`)

```
GET /api/uploads/{...path}
```

| 特性 | 实现 |
|------|------|
| 安全 | 目录穿越防护: `resolved.startsWith(resolvedUploadDir)` |
| 读取 | `fs.readFileSync` — 同步全量读取到内存，直接返回 buffer |
| MIME | 硬编码映射表 (png, jpg, webp, mp4, webm) |
| 缓存头 | **无** — 没有 Cache-Control / ETag / Last-Modified |

### 3.4 缺失功能

| 功能 | 状态 | 影响 |
|------|------|------|
| 分片上传 | ❌ 无 | 大文件（>100MB）依赖 `arrayBuffer()` 全量加载 |
| 断点续传 | ❌ 无 | 上传中断需重新上传 |
| 文件大小限制 | ❌ 无硬限制 | Next.js 默认 ~100MB body 限制 |
| 并发上传 | ⚠️ 无锁 | 同一 shot/character 并发上传无互斥 |

---

## 4. 文件清理策略

### 4.1 现状：**无清理机制**

对全部代码库搜索 `cleanup`、`prune`、`gc`、`purge`、`sweep`、`expire`、`stale`、`housekeep`、`temp` 等关键词，**均未找到** 任何文件清理逻辑。

### 4.2 孤儿文件来源

| 场景 | 产生原因 | 示例 |
|------|----------|------|
| Shot 重新上传 | 新文件名写入 DB，旧文件留在磁盘 | `frames/a3Kq9LmX2pRb.png` 被 `frames/b7Np2QxR5tYz.png` 替换 |
| Character 历史 | `referenceImageHistory` 追加，旧图片不删除 | `characters/` 目录随时间线性增长 |
| Asset 版本 | `insertAssetVersion` 插入新行 + 新文件，旧行 `is_active=0` 但文件保留 | 每重生成一次 = 1 个新文件 |
| FFmpeg 中间件 | `concatListPath` 在 `concatWithTransitions` 末尾 `unlinkSync` ✅ | **已清理** |
| FFmpeg concat 中间产物 | `concatOutputPath` 在字幕烧录后 `unlinkSync` ✅ | **已清理** |
| 版本化目录 | `projects/{id}/{label}/` 无删除机制 | 旧版本持续占用磁盘 |

### 4.3 清理建议（非本次修改）

```
优先级 | 建议 | 理由
-------|------|-----
P0     | Shot/Character 上传时 unlink 旧文件 | 最直接，避免孤儿积累
P1     | insertAssetVersion 时清理旧版本文件 | DB 有 isActive 标记，可安全识别
P2     | 定时任务扫描 projects/ 下过期版本 | 版本化目录的长期维护
P3     | 配置上传大小限制 + 分片 | 防止 OOM 和上传失败
```

---

## 5. 大文件处理

### 5.1 上传路径 — 全量内存加载

```typescript
// 所有上传路由采用同一模式:
const buffer = Buffer.from(await file.arrayBuffer());
fs.writeFileSync(filepath, buffer);
```

- **流式写入缺失**: `arrayBuffer()` 全量加载到内存 → `Buffer.from()` 复制 → `writeFileSync` 同步写入
- 对 50-100MB 视频文件意味着 **~100-200MB 峰值内存**
- 无 `stream` 或 `WriteStream.pipe()` 机制

### 5.2 AI Provider 输出 — 全量内存加载

```typescript
// 视频 Provider (Seedance, Kling, Wan 等):
const videoResponse = await fetch(videoUrl);
const buffer = Buffer.from(await videoResponse.arrayBuffer());
fs.writeFileSync(filepath, buffer);
```

- 从远程 API 下载视频 → 全量缓冲 → 同步写入
- 对于 1080p 5-10 秒视频（~50-200MB），同上内存压力

### 5.3 FFmpeg 视频装配 — 文件流

```typescript
// assembleVideo() 使用 fluent-ffmpeg 的流式处理:
ffmpeg()
  .input(concatListPath)
  .inputOptions(["-f", "concat", "-safe", "0"])
  .outputOptions(["-c", "copy"])
  .output(outputPath)
  .run();  // 进程流式，不将全部视频载入内存
```

- FFmpeg 基于 **磁盘文件流**，不将完整视频载入内存
- 中间产物（concat list、concat 中间视频）在流程内 `unlinkSync` 清理 ✅
- 字幕烧录 (`subtitles` filter) 和 BGM 混音 也是流式

### 5.4 文件服务 — 全量内存读取

```typescript
const buffer = fs.readFileSync(resolved);
return new NextResponse(buffer, { headers: { "Content-Type": contentType } });
```

- 大视频文件通过 `/api/uploads/...` 读取时 **全量加载到内存**
- 无 Range 头支持，不支持视频进度条 (seek)
- 无缓存头，浏览器无法利用 HTTP cache

### 5.5 内存压力汇总

| 操作 | 模式 | 100MB 文件峰值内存 | 可优化 |
|------|------|---------------------|---------|
| 用户上传 | `arrayBuffer()` + `writeFileSync` | ~200MB | ✅ 改用 `streaming body` |
| AI Provider 下载 | `arrayBuffer()` + `writeFileSync` | ~200MB | ✅ 改用 `stream` + `WriteStream` |
| FFmpeg 处理 | 进程流式 | ~100MB (ffmpeg 进程) | ✅ 已优化 |
| 文件服务 GET | `readFileSync` → Response | ~100MB | ✅ 改用 `stream` 响应 |

---

## 6. 资产版本管理 (shot_assets 表)

### 6.1 设计

`src/lib/shot-asset-utils.ts` 实现了完整的资产版本控制系统：

```
shot_assets 表:
  shot_id, type, sequence_in_type, asset_version, is_active
  prompt, file_url, status, characters, model_provider, model_id, meta
```

- **版本语义**: `insertAssetVersion` 自动递增 `asset_version`，旧版本 `is_active = 0`
- **恢复能力**: `activateAssetVersion` 可恢复历史版本
- **遗留兼容**: `loadShotLegacyView` 映射旧表列名到资产表

### 6.2 DB-磁盘脱节

| 维度 | DB 状态 | 磁盘状态 |
|------|----------|----------|
| 当前活跃 | `is_active = 1` → 唯一 | 文件存在 |
| 历史版本 | `is_active = 0` → 可恢复 | 文件存在（无清理） |
| 删除 | `deleteAssetsByType` 仅删除 DB 行 | 文件残留（孤儿） |

---

## 7. 发现的问题汇总

### 7.1 架构级

| # | 问题 | 严重度 | 说明 |
|---|------|--------|------|
| 1 | **无文件清理机制** | 🔴 高 | 磁盘持续增长，无 GC/prune 策略 |
| 2 | **DB-磁盘脱节** | 🟡 中 | `deleteAssetsByType` 删 DB 不删文件；版本切换留孤儿 |
| 3 | **同步 IO 阻塞** | 🟡 中 | 全部 `writeFileSync`/`readFileSync`，无流式处理 |
| 4 | **代码重复** | 🟢 低 | `getVersionedUploadDir` 在 `video-generate.ts` 和 `generate/route.ts` 重复实现 |

### 7.2 功能级

| # | 问题 | 严重度 | 说明 |
|---|------|--------|------|
| 5 | **无上传分片/断点续传** | 🟡 中 | 大文件上传可靠性依赖网络稳定性 |
| 6 | **文件服务无缓存头** | 🟢 低 | `/api/uploads/...` 缺少 Cache-Control/ETag |
| 7 | **无 Range 支持** | 🟢 低 | 视频文件不支持 seek/进度条 |
| 8 | **上传无大小限制** | 🟡 中 | 无 `maxBodySize` 配置，依赖 Next.js 默认 |

### 7.3 亮点

| # | 亮点 | 说明 |
|---|------|------|
| 1 | **统一资产模型** | `shot_assets` 表 + 版本控制，设计清晰 |
| 2 | **目录穿越防护** | uploads GET 路由的 `startsWith` 校验 |
| 3 | **FFmpeg 中间件自清理** | concat list 和中间视频在流程内 `unlinkSync` |
| 4 | **Provider 抽象一致** | 所有 Provider 共享 `uploadDir` 参数 + 存储模式 |

---

## 8. 结论

AIComicBuilder 的文件资产管理采取 **简单直接** 的策略：环境变量驱动的路径 + nanoid 文件名 + 同步写入。这适合开发和中小规模生产，但缺少：

1. **生命周期管理** — 文件只增不减，磁盘必然持续增长
2. **流式 IO** — 大文件场景的内存效率和可靠性
3. **清理一致性** — DB 操作与磁盘文件操作的原子性脱节

推荐优先解决 **问题 1（清理机制）** 和 **问题 2（DB-磁盘一致性）**，这两项是成本最低但收益最高的改进。
