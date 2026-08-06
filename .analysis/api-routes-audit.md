# AIComicBuilder — API Routes 全量审计

> 审计日期: 2026-08-06
> 项目: `/home/vince/projects/AIComicBuilder/`
> 总 route handler 数: **47**

---

## 1. Route 全量表

| # | Route Path | Methods | Auth | 错误格式 | 分页 | Try/Catch | 备注 |
|---|---|---|---|---|---|---|---|
| 1 | `GET /api/agents` | GET | `getUserIdFromRequest` | `{ error: string }` | ❌ | ❌ | 查询当前用户所有 agent |
| 2 | `POST /api/agents` | POST | `getUserIdFromRequest` | `{ error: string }` | ❌ | ❌ | 创建 agent，含字段校验 |
| 3 | `PATCH /api/agents/[id]` | PATCH | `getUserIdFromRequest` | `{ error: string }` | ❌ | ❌ | 更新 agent |
| 4 | `DELETE /api/agents/[id]` | DELETE | `getUserIdFromRequest` | `{ error: string }` | ❌ | ❌ | 删除 agent |
| 5 | `POST /api/models/list` | POST | **无认证** | `{ error: string }` | ❌ | ✅ | 反向代理模型列表查询；失败时返回 502 |
| 6 | `GET /api/projects` | GET | `getUserIdFromRequest` | `{ error: string }` | ❌ | ❌ | 全部返回，无分页 |
| 7 | `POST /api/projects` | POST | `getUserIdFromRequest` | `{ error: string }` | ❌ | ❌ | 创建项目 |
| 8 | `GET /api/projects/[id]` | GET | `resolveProject` (自定义) | `{ error: string }` | ❌ | ❌ | 获取项目详情，含 shots/characters/episodes |
| 9 | `PA`TCH /api/projects/[id]` | PATCH | `resolveProject` | `{ error: string }` | ❌ | ❌ | 更新项目字段；script 变更触发 `markDownstreamStale` |
| 10 | `DELETE /api/projects/[id]` | DELETE | `resolveProject` | `{ error: string }` | ❌ | ❌ | 删除项目 (硬删除) |
| 11 | `GET /api/projects/[id]/episodes` | GET | `resolveProject` (自定义) | `{ error: string }` | ❌ | ❌ | 获取所有 episodes，含预览图 |
| 12 | `POST /api/projects/[id]/episodes` | POST | `resolveProject` | `{ error: string }` | ❌ | ❌ | 创建 episode |
| 13 | `GET /api/projects/[id]/episodes/[episodeId]` | GET | `resolveProjectAndEpisode` | `{ error: string }` | ❌ | ❌ | 含版本化 shots/assets/dialogues 查询 |
| 14 | `PATCH /api/projects/[id]/episodes/[episodeId]` | PATCH | `resolveProjectAndEpisode` | `{ error: string }` | ❌ | ❌ | script 变更触发 `markDownstreamStale` |
| 15 | `DELETE /api/projects/[id]/episodes/[episodeId]` | DELETE | `resolveProjectAndEpisode` | `{ error: string }` | ❌ | ❌ | 禁止删除最后一个 episode；返回 204 |
| 16 | `PUT /api/projects/[id]/episodes/reorder` | PUT | `resolveProject` | `{ error: string }` | ❌ | ❌ | 批量更新 sequence |
| 17 | `POST /api/projects/[id]/generate` | POST | `getUserIdFromRequest` + DB 查 | `{ error: string }` | ❌ | ✅ (部分) | 大型路由，>20 种 action；部分 handler 含 try/catch，部分无 |
| 18 | `POST /api/projects/[id]/upload-script` | POST | `getUserIdFromRequest` + DB 查 | `{ error: string }` | ❌ | ✅ | 文件上传 + AI 分集写入 DB；multipart |
| 19 | `GET /api/projects/[id]/characters` | GET | `assertProjectOwnership` | `{ error: string }` | ❌ | ❌ | 无 |
| 20 | `PATCH /api/projects/[id]/characters/[characterId]` | PATCH | `assertProjectOwnership` | `{ error: string }` | ❌ | ❌ | 角色更新；scope→main 自动清 episodeId |
| 21 | `DELETE /api/projects/[id]/characters/[characterId]` | DELETE | `assertProjectOwnership` | `{ error: string }` | ❌ | ❌ | 返回 204 |
| 22 | `POST /api/projects/[id]/characters/[characterId]/upload` | POST | `assertProjectOwnership` | `{ error: string }` | ❌ | ❌ | multipart 文件上传；历史记录管理 |
| 23 | `GET /api/projects/[id]/characters/[characterId]/costumes` | GET | `assertProjectOwnership` | `{ error: string }` | ❌ | ❌ | 多层所有权断言|
| 24 | `POST /api/projects/[id]/characters/[characterId]/costumes` | POST | `assertProjectOwnership` | `{ error: string }` | ❌ | ❌ |
| 25 | `GET /api/projects/[id]/shots` | GET | `assertProjectOwnership` | `{ error: string }` | ❌ | ❌ | 含对话联表查询|
| 26 | `PA`TCH /api/projects/[id]/shots/[shotId]` | PATCH | `assertProjectOwnership` | `{ error: string }` | ❌ | ❌ | 白名单字段更新|
| 27 | `DELETE /api/projects/[id]/shots/[shotId]` | DELETE | `assertProjectOwnership` | `{ error: string }` | ❌ | ❌ | 返回 204 |
| 28 | `POST /api/projects/[id]/shots/[shotId]/upload` | POST | `assertProjectOwnership` | `{ error: string }` | ❌ | ❌ | multipart；field 白名单校验|
| 29 | `PU`T /api/projects/[id]/shots/[shotId]/assets` | PUT | `assertProjectOwnership` | `{ error: string }` | ❌ | ❌ | shot_assets CRUD 批量接口|
| 30 | `POST /api/projects/[id]/shots/[shotId]/assets/[assetId]/activate` | POST | `assertProjectOwnership` | `{ error: string }` | ❌ | ❌ | 版本切换激活|
| 31 | `GET /api/projects/[id]/character-relations` | GET | `assertProjectOwnership` | `{ error: string }` | ❌ | ❌ | |
| 32 | `POST /api/projects/[id]/character-relations` | POST | `assertProjectOwnership` | `{ error: string }` | ❌ | ❌ | 字符绑定校验 |
| 33 | `DELETE /api/projects/[id]/character-relations/[relationId]` | DELETE | `assertProjectOwnership` | `{ error: string }` | ❌ | ❌ | |
| 34 | `GET /api/projects/[id]/mood-board` | GET | `assertProjectOwnership` | `{ error: string }` | ❌ | ❌ | |
| 35 | `POST /api/projects/[id]/mood-board` | POST | `assertProjectOwnership` | `{ error: string }` | ❌ | ❌ | |
| 36 | `DELETE /api/projects/[id]/mood-board/[imageId]` | DELETE | `assertProjectOwnership` | `{ error: string }` | ❌ | ❌ | |
| 37 | `POST /api/projects/[id]/continuity-check` | POST | `assertProjectOwnership` | `{ error: string }` | ❌ | ❌ | AI 连续性检查 |
| 38 | `POST /api/projects/[id]/emotion-analysis` | POST | `assertProjectOwnership` | `{ error: string }` | ❌ | ✅ | AI 情绪分析 |
| 39 | `GET /api/projects/[id]/download` | GET | `getUserIdFromRequest` | **`new Response("…")` 纯文本** | ❌ | ❌ | ⚠️ 错误格式不一致，纯文本而非 `{ error }` |
| 40 | `POST /api/projects/[id]/merge-episodes` | POST | `getUserIdFromRequest` + DB 查 | `{ error: string }` | ❌ | ✅ | FFmpeg 视频合并 |
| 41 | `GET /api/projects/[id]/agent-bindings` | GET | **无认证** | `{ error: string }` | ❌ | ❌ | ⚠️ 无所有权检查 |
| 42 | `PUT /api/projects/[id]/agent-bindings` | PUT | **无认证** | `{ error: string }` | ❌ | ❌ | ⚠️ 无所有权检查 |
| 43 | `GET /api/projects/[id]/import/logs` | GET | `getUserIdFromRequest` | `{ error: string }` | ❌ | ❌ | |
| 44 | `DELETE /api/projects/[id]/import/logs` | DELETE | `getUserIdFromRequest` | `{ error: string }` | ❌ | ❌ | 返回 204 |
| 45 | `POST /api/projects/[id]/import/parse` | POST | `getUserIdFromRequest` | `{ error: string }` | ❌ | ✅ | 文件上传 + 文本提取|
| 46 | `POST /api/projects/[id]/import/characters` | POST | `getUserIdFromRequest` | `{ error: string }` | ❌ | ✅ | AI 角色提取; 含 JSON 解析失败重试|
| 47 | `POST /api/projects/[id]/import/split` | POST | `getUserIdFromRequest` | `{ error: string }` | ❌ | ✅ | AI 分集; 含 JSON 解析失败重试|
| 48 | `POST /api/projects/[id]/import/generate` | POST | `getUserIdFromRequest` | `{ error: string }` | ❌ | ❌ | 批量创建角色+episodes+关系 |
| 49 | `GET /api/prompt-templates` | GET | `getUserIdFromRequest` | `{ error: string }` | ❌ | ❌ | 全局 prompt 覆盖列表 |
| 50 | `PUT /api/prompt-templates/[promptKey]` | PUT | `getUserIdFromRequest` | `{ error: string }` | ❌ | ❌ | 全局 prompt 保存 |
| 51 | `DELETE /api/prompt-templates/[promptKey]` | DELETE | `getUserIdFronRequest` | `{ error: string }` | ❌ | ❌ | 返回 204 |
| 52 | `GET /a`pi/projects/[id]/prompt-templates` | GET | `getUserIdFronRequest` + DB 查 | `{ error: string }` | ❌ | ❌ | 项目级 prompt 覆盖列表 |
| 53 | `PUT /a`pi/projects/[id]/prompt-templates/[promptKey]` | PUT | `getUserIdFronRequest` + DB 查 | `{ error: string }` | ❌ | ❌ | 项目级 prompt 保存 |
| 54 | `DELETE /api/projects/[id]/prompt-templates/[promptKey]` | DELETE | `getUserIdFromRequest` + DBB 查 | `{ error: string }` | ❌ | ❌ | 返回 204 |
| 55 | `POST /api/prompt-templates/preview` | POST | **无认证** | `{ error: string }` | ❌ | ❌ | 预览 assemble 的 prompt |
| 56 | `GET /a`pi/prompt-templates/registry` | GET | **无认证** | `{ error: string }` | ❌ | ❌ | 返回注册表定义 |
| 57 | `POST /api/prompt-templates/validate` | POST | **无认证** | `{ error: string }` | ❌ | ❌ | 验证 full-text 编辑保留锁定 slots |
| 58 | `GET /api/prompt-templates/[promptKey]/versions` | GET | `getUserIdFromRequest` | `{ error: string }` | ❌ | ❌ | 列出所有版本历史 |
| 59 | `POST /api/prompt-templates/[promptKey]/versions/[vid]/restore` | POST | `getUserIdFromRequest` + DDB 查 | `{ error: string }` | ❌ | ❌ | 恢复某个历史版本 |
| 60 | `GET /api/prompt-presets` | GET | `getUserIdFromRequest` | `{ error: string }` | ❌ | ❌ | 列出内置+用户预设 |
| 61 | `POST /api/prompt-presets` | POST | `getUserIdFromRequest` | `{ error: string }` | ❌ | ❌ | 保存预设 |
| 62 | `DELETE /api/prompt-presets/[presetId]` | DELETE | `getUserIdFromRequest` | `{ error: string }` | ❌ | ❌ | 返回 204 |
| 63 | `POST /api/prompt-presets/[presetId]/apply` | POST | `getUserIdFromRequest` | `{ error: string }` | ❌ | ❌ | 应用预设到全局/项目 |
| 64 | `GET /api/tasks/[id]` | GET | `getUserIdFromRequest` + LEFT JOIN | `{ error: string }` | ❌ | ❌ | 任务状态查询 |
| 65 | `GET /api/uploads/[...path]` | GET | **无认证** | `new Response(…text…)` | ❌ | ❌ | ⚠️ 文件服务；目录遍历防护, 无认证 |

---

## 2. 认证模式分析

### 2.1 核心机制

- **无通用中间件** (`src/middleware.ts` 不存在)
- `x-user-id` header 由客户端 SPA 注入（通过 `src/lib/api-fetch.ts`）
- `getUserIdFromRequest()`: 简单读取 header，空值时为 `""`
- `assertProjectOwnership()`: 两步验证 — 读取 userId → 查 DB 确认 project.userId 匹配

### 2.2 认证分层

| 级别 | 使用函数 | Routes 数 | 特征 |
|---|---|---|
| **A — 无认证** | 无 | **7** | `models/list`, `prompt-templates/preview`, `registry`, `validate`, `uploads/[...path]`, `agent-bindings/*`|
| **B — 仅用户标识** | `getUserIdFromRequest` | 约 18 | 只读 userId，不做 ownership 校验 |
| **C — 所有权断言** | `assertProjectOwnership` | 约 15 | 完整的 project ownership 校验 |
| **D — 自定!** | `resolveProject` / `resolveProjectAndEpisode` | 约 8 | 功能同 C，但代码重复 |

### 2.3 认证不一致

- **`agent-bindings/*` (GET/PUT)** 完全不验证`：任何知道 projectId 的请求者都可操作
- `projects/[id]/download` 使用 `getUserIdFromRequest` 但在 userId 为空时优雅降级（返回 404 而不是 401/403）
- **同一个项目路由同时存在三种认证风格**（B/C/D），无统一抽象

---

## 3. 错误处理一致性

### 3.1 错误格式

| 格式 | 使用 Routes | 占比 |
|---|---|---|
| `NextResponse.json({ error: string }, status)` | **41** | 主流格式 ✅ |
| `new Response("plain text", status)` | **2** (`download`, `uploads/[...path]`) | ⚠️ 不一致 |
| `new Response(null, { status: 204 })` | **9** | ✅ 标准 204 |
| `result.toTextStreamResponse()` | 4 (stream 路由) | ✅ streaming 场景 |

### 3.2 HTTP Status Code 分布

| Code | 语义 | 一致性 |
|---|---|
| 200 | 成功 | ✅ |
| 201 | Created | ✅ |
| 204 | No Content (DELETE 标准) | ✅ |
| 400 | 请求参数错误 | ✅ |
| 403 | Forbidden (prompt-presets apply/restore 有使用) | ✅ |
| 404 | Not Found | ✅ |
| 422 | 语义错误 / AI 输出校验失败 | ✅ 仅在 `generate/route.ts` 中使用 |
| 500 | 服务器内部错误 | ✅ |
| 502 | 上游 API 失败 (`models/list`) | ✅ |

### 3.3 问题点

1. **`download/route.ts`** 返回 `new Response("Project not found")` 而非 `{ error: "…" }` — 格式不一致
2. **`uploads/[...path]/route.ts`** 返回纯文本错误（"Forbidden", "Not found"）
3. **大量 route 的 try/catch 缺失**: 大多数 route handler 没有包裹 try/catch，DB 查询异常会导致未处理的 Promise rejection

---

## 4. Try/Catch 覆盖率

| 覆盖情况 | Routes 数 | 具体 |
|---|---|---|
| **完全无 try/catch** | **~35** | 统计多数 — DB 查询、JSON 解析不在 try 保护中 |
| **部分覆盖** | ~10 | `generate/route.ts` 内部 handler 函数部分覆盖 |
| **完整覆盖** | ~5 | `models/list`, `import/*` 等 |
| **catch 中吞掉错误只有部分 | **emotion-analysis** — 返回 `{ scores: [] }` 而非错误详情 |

### 风险

- **非 protected DB 查询风险**：绝大多数 `db.select()` / `db.update()` / `db.delete()` 没有任何 try/catch 保护
- **JSON 解析风险**：`request.json()` 在多个 route 中直接 await，没有异常处理

---

## 5. 分页策略

**当前状态：所有列表路由均无分页。**

受影响的 route:
- `GET /api/projects` — 全部返回
- `GET /api/projects/[id]/episodes` — 全部返回
- `GET /api/projects/[id]/shots` — 全部返回
- `GET /api/projects/[id]/characters` — 全部返回

---

## 6. 文件上传处理

### 6.1 Upload Routes

| Route | 方法 | 文件来源 | 落地目录 | 字段校验 |
|---|---|---|---|
| `POST /api/projects/[id]/upload-script` | `formData()` | 单文件 | 解析出文本后存 DB | 有 (`modelConfig` JSON 字段) |
| `POST /api/projects/[id]/characters/[characterId]/upload` | `formData()` | `file` field | `$UPLOAD_DIR/characters/` | 有 (file 非空校验) |
| `POST /api/projects/[id]/shots/[shotId]/upload` | `formData()` | `file` + `field` | `$UPLOAD_DIR/frames/` | ✅ field whitelist (`ALLOWED_FIELDS`) |
| `GET /api/uploads/[...path]` | 静态文件服务 | 文件系统 | `$UPLOAD_DIR` 下任意 | ✅ 目录遍历防护 |

### 6.2 问题点

- `upload-script/route.ts` 是项目根路由（`/api/projects/[id]/upload-script`），但是和 `uploads/` 分离
- `generate/route.ts` 中的 `handleSingleCharacterImage` 通过 AI 生成图片并保存，不走 upload route
- **无文件大小限制**、无类型 MIME 白名单、无双人限制
- `uploads/**`  file 服務无认证 — 知道路径即可以访问任何上传文件

---

## 7. 不一致汇总

### 7.1 P0 (潜在安全风险)

| # | 问题 | 影响 |
|---|---|
| 1 | `agent-bindings/*` GET/PUT 完全无认证 | 任意用户（知道 projectId）可读取/修改 agent 绑定 |
| 2 | `uploads/[...path]` 无认证 | 知道文件路径即可访问任意上传文件 |
| 3 | `models/list` 无认证 | 可被滥用为代理（回传 API Key 至控制端点） |
| 4 | `var` 路由使用 `getUserIdFronRequest` 但不做 ownership 校验 | 知道 projectId 即可 DELETE 非自己的项目的 import logs |

### 7.2 P1 (架构一致性问题)

| # | 问题 | 影响 |
|---|---|---|
| 1 | 三种认证风格并存（B/C/D） | 维护成本高，审计困难 |
| 2 | 大多数 route 无 try/catch | DB 异常导致 500，用户体验差 |
| 3 | `download` 和 `uploads` 错误格式不一致 | 客户端错误处理复杂性|
| 4 | 所有列表接口无分页 | 项目/episode 多时内存压力，响应慢 |

### 7.2 P2 (代码质量问题)

| # | 问题 |
|---|
| 1 | `resolveProject`, `resolveProjectAndEpisode` 和 `assertProjectOwnership` 功能重复，散落在多个文件中 |
| 2 | `generate/route.ts` 单一文件包含 ~2000+ 行，20+ 个 handler 函数，难以维护 |
| 3 | `upload-script/route.ts` 复制了 import-utils 中的 chunking/extractText 逻辑 |
| 4 | 部分 route `console.error` 打印可能包含敏感信息（API Key 等） |

---

## 8. 架构图（路由树）

```
/api
├── agents
│   ├── GET/POST  (/)               — 列表 / 创建
│   └── PATCH/DELETE (/{id})        — 更新 / 删除
├── models/list
│   └── POST                        — 模型列表代理
├── projects
│   ├── GET/POST  (/)               — 列表 / 创建
│   └── projects/{id}
│       ├── GET/PATCH/DELETE         — 详情 / 更新 / 删除
│       ├── episodes
│       │   ├── GET/POST             — 列表 / 创建
│       │   ├── reorder → PUT        — 排序
│       │   └── {episodeId}
│       │       ├── GET/PATCH/DELETE  — 详情 / 更新 / 删除
│       ├── generate → POST         — 核心 AI 生成引擎（20+ action）
│       ├── upload-script → POST     — 文件上传 + AI 分集
│       ├── characters
│       │   ├── GET                   — 角色列表
│       │   └── {characterId}
│       │       ├── PATCH/DELETE      — 更新 / 删除
│       │       ├── upload → POST    — 参考图上传
│       │       └── costumes
│       │           ├── GET/POST      — 服装列表 / 创建
│       ├── shots
│       │   ├── GET                    — 镜头列表
│       │   └── {shotId}
│       │       ├── PATCH/DELETE     — 更新 / 删除│
│       │       ├── upload → POST      — 帧 / ref 图上传│
│       │       └── assets
│       │           ├── PUT            — 批量管理 shot_assets│
│       │           └── {assetId}/
│       │               activate → POST  — 版本激活
│       ├── character-relations
│       │   ├── GET/POST              — 列表 / 创建
│       │   └── {relationId} → DELETE  — 删除
│       ├── mood-board
│       │   ├── GET/POST              — 列表 / 创建
│       │   └── {imageId} → DELETE    — 删除
│       ├── continuity-check → POST   — 连续性检测
│       ├── emotion-analysis → POST    — 情绪分析
│       ├── download → GET            — ZIP 打包下载
│       ├── merge-episodes → POST    — FFmpeg 合并
│       ├── agent-bindings
│       │   ├── GET                   — 列表
│       │   └── PUT                  — 绑定 / 解绑
│       ├── import
│       │   ├── parse → POST         — 文件解析│
│       │   ├── characters → POST     — AI 角色提取│
│       │   ├── split → POST          — AI 分集│
│       │   ├── generate → POST       — 批量生成│
│       │   └── logs
│       │       ├── GET               — 导入日志
│       │       └── DELTE             —　清空日志
│       └── prompt-templates
│           ├── GET                   — 项目级 override 列表
│           └── {promptKey}
│               ├── PUT              — 保存 override│
│               └── DELET            — 删除 override├── prompt-templates
│   ├── GET                          — 全局 override 列表│
│   ├── preiew → POST                — 预览│
│   ├── registry → GET               — 注册表定义│
│   ├── validate → POST              — 编辑验证│
│   └── {promptKey}
│       ├── PUT/DELETE               — 全局 override 增删││
│       └── versions
│           ├── GET                  — 版本历史│
│           └── {vid}/
│               └── restore → POST   — 版本恢复├── prompt-presets│
│   ├── GET/POST                    — 列表 / 创建│
│   └── {presetId}
│       ├── DELTE                   — 删除（仅用户自定）││
│       └── apply → POST             — 应用到全局/项目├── tasks/{id}
│   └── GET                         — 任务状态├── uploads/[...path]
│   └── GET                          — 文件服务
```

---

## 9. 建议

### 短期 (P0 fixes)
1. **`agent-bindings/*` 增加 assertProjectOwnership**
2. **`uploads/[...path]` 考虑加认证**（通过 referrer 还是 token 需评估）
3. **`models/list` 加 rate-limit / IP‑whiteist**

### 中期 (P1)
4. **统一 `assertProjectOwnership` 抽象** — 替代所有 `resolveProject`/`resolveProjectAndEpisode` 的自定义实现
5. **错误格式统一化** — `download/route.ts` 和 `uploads/[...path]/route.ts` 改为 `{ error }` 格式
6. **尝试 /atch 包装所有 DB 查询** — 至少包装 `db.select/update/delete` 在 try/catch 内
7. **重构 `generate/route.ts`** — 每个 action handler 拆分到独立文件

### 长期 (P2)
8. **列表接口加分页** — 至少 `projects` 和 `episodes` 接
9. **文件上传加安全限制** — 大小限制、MIME 白名单
10. **加统一中间件** — 处理 `x-user-id` 解析和标准 cors 头