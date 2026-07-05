## F6 管线韧性审计

**审计日期**: 2025-07-05
**审计范围**: core/state_manager.py, core/asset_manager.py, core/timeline.py, core/llm_client.py, core/comfyui_session.py, core/workflow_loader.py, scripts/e2e_dry_run.py, scripts/migrate_costumes.py

### 评估结论: 有条件通过

管线具备基本的断点续跑和状态管理能力，但在状态持久化安全、并发保护、长时间运行稳定性方面存在明确风险点，需针对性加固后方可达到生产级可靠。

---

### 关键发现

| 严重度 | 模块 | 问题 | 对管线可靠性的影响 | 建议 |
|--------|------|------|-------------------|------|
| 🔴 高 | state_manager | `_write()` 无原子写入，崩溃/断电时 state.json 可损坏为空文件或半截 JSON | **✅ 已修复 (R5)**: `_write_atomic()` 使用 tmp + `os.replace()` | 改用 write-to-tmp + rename 原子写入 |
| 🔴 高 | asset_manager | 同上，`_write()` 非原子；assets.json 累积大量历史版本记录无上限 | 资产注册表损坏 = 丢失所有版本追踪；长期运行后文件膨胀影响 IO | 同上原子写入；加 assets.json 定期 compact（清除 is_active=False 的旧记录） |
| 🔴 高 | state_manager | 无版本号/schema 字段，结构变更时无向后兼容处理 | **✅ 已修复 (R5)**: `schema_version` 字段 + `load()` 默认 v1 | 加 `"schema_version": 1` 字段；`get()` 里做字段补全（缺失 stages 的 key 自动填充 pending） |
| 🟠 中 | comfyui_session | `wait()` 无重连逻辑，ComfyUI 进程崩溃后 poll 会一直超时 | 10h 管线中 ComfyUI OOM 崩溃 → 当前 shot 超时 → 整个 stage 标记失败，但无自动重启 ComfyUI 能力 | `wait()` 中加 ComfyUI 健康检查；断连时抛特定异常让上层决定是否重启 |
| 🟠 中 | llm_client | `chat()` 超时 300s 无重试；`chat_json()` 有重试但不覆盖 API 级超时 | LLM API 波动时单个 stage 直接失败，需人工重跑 | `chat()` 加可配置重试（默认 2 次，指数退避） |
| 🟠 中 | e2e_dry_run | GPU 资源管理用 `edge-llm` CLI 子进程调用，无进程锁/信号量 | 多 episode 并行时两个 e2e_dry_run 实例可能同时 `ensure_comfyui()` 产生竞争 | 引入文件锁（如 fcntl flock）保护 GPU 切换操作 |
| 🟠 中 | asset_manager | `register()` 的 cleanup_old=True 默认删除旧版本文件，不可逆 | 重生成结果质量更差时无法回退到旧版本 | 改为 cleanup_old=False 默认；或加 `old_versions_dir` 归档而非删除 |
| 🟠 中 | state_manager | `mark_stale()` 将下游全部标记 pending 但不清理对应资产文件 | 重新执行 stage 后，旧的产出文件（s5_frames/*.png 等）可能与新状态不一致 | mark_stale 时同步调用 asset_manager.invalidate_shot 或标记文件为 stale |
| 🟡 低 | timeline | `_ffprobe_duration()` 用 subprocess 无超时保护 | ffprobe 对损坏视频可能挂死 | 加 timeout=10 参数 |
| 🟡 低 | comfyui_session | 无 session 复用/池化，每次 `quick_run()` 创建新 session | 高频调用时 client_id 碎片化，ComfyUI 侧可能堆积无用 client | 使用 singleton 或池 |
| 🟡 低 | migrate_costumes | 无备份机制，`shutil.move` 不可逆 | 迁移失败时原始文件已被移动，无法自动回滚 | 先复制后验证，或加 --backup 选项 |
| 🟡 低 | e2e_dry_run | 日志仅保存在内存 `log_lines`，进程崩溃则丢失 | 长时间运行崩溃后无诊断信息 | 同时写文件日志（logging.FileHandler） |
| 🟡 低 | state_manager / asset_manager | 全局单例 `_DEFAULT` 非线程安全 | 多线程场景下可能的竞态条件 | 加 threading.Lock 或改用 thread-local |
| ✅ 已修复 | state_manager | `_write()` 无原子写入，崩溃/断电时 state.json 可损坏 | **已修复**: `_write_atomic()` 使用 tmp + `os.replace()` | R5: 2026-07-05 |
| ✅ 已修复 | state_manager | 无版本号/schema 字段 | **已修复**: `schema_version` 字段 + `load()` 默认 v1 向后兼容 | R5: 2026-07-05 |
| ✅ 已修复 | state_manager | 损坏恢复 | **已修复**: `load()` 从 `.json.tmp` 备份恢复，不可恢复时 re-init | R5: 2026-07-05 |

---

### 韧性评估

#### ✅ 已有机制

1. **断点续跑**: `next_pending()` 自动找到下一个可执行 stage（依赖检查 + 状态检查），`--from` 参数支持从指定 stage 恢复
2. **Stage 依赖声明**: `pipeline.yaml` 中 `requires` 字段 + `check_requires()` 运行前校验，避免前置缺失导致空跑
3. **跳过已有产出**: `skip_existing: true` + `check_produces()` 避免重复生成（S5/S6 支持）
4. **脏标记传播**: `mark_stale(from_stage)` 将指定 stage 及其下游全部标记 pending，确保重新执行时不会遗漏
5. **错误记录**: `mark_failed()` 记录错误到 state.json 的 `errors[]` 数组，支持非致命错误（`add_error()`）
6. **GPU 生命周期编排**: ComfyUI/qw35-9b 按需启停，VL 质检与 ComfyUI GPU 互斥处理
7. **LLM JSON 重试**: `chat_json()` 最多 3 次重试 + 温度递增 + 正则提取兜底
8. **版本化资产**: `AssetManager` 支持多版本注册，`is_active` 标记当前有效版本，`get_active()` 查最新
9. **失败不中断**: e2e_dry_run 中 stage 失败后继续后续独立 stage（`check_requires` 会自然跳过依赖失败的 stage）
10. **TimeLine ffprobe 校准**: 用实际视频时长修正 shot duration，减少时间轴累积误差

#### ❌ 缺失机制

1. **原子写入**: **✅ 已修复 (R5)**: `_write_atomic()` 实现 tmp + `os.replace()`，崩溃安全
2. **状态文件损坏恢复**: **✅ 已修复 (R5)**: `load()` 从 `.json.tmp` 备份恢复，不可恢复时 re-init
3. **Schema 版本管理**: **✅ 已修复 (R5)**: `schema_version` 字段，向后兼容默认 v1
4. **ComfyUI 崩溃自动恢复**: wait() 超时后不检查 ComfyUI 是否存活，无法自动重启重试当前 shot
5. **并发安全**: 无文件锁/进程锁保护，多 episode 并行会导致 GPU 竞争和状态文件读写冲突
6. **资产文件与状态一致性**: mark_stale 后旧文件残留，state 说 pending 但文件说 completed
7. **长时间运行资源泄漏**: assets.json 无限增长（历史版本不清除）；内存中 log_lines 无上限；ComfyUI output 目录无自动清理
8. **备份/回滚**: migrate_costumes 和 asset_manager 的 cleanup_old 都是不可逆操作，无 undo 能力
9. **LLM 通用重试**: chat() 无重试，API 波动直接失败
10. **持久化日志**: e2e_dry_run 日志仅在内存，进程异常退出则全丢

---

### 各模块韧性评分

| 模块 | 评分 | 说明 |
|------|------|------|
| state_manager | 6/10 | 有完整的状态流转（pending→running→completed/failed）和依赖检查，但原子写入和损坏恢复是致命短板 |
| asset_manager | 7/10 | 版本化设计合理，查询 API 完善；但非原子写入 + 旧版本默认删除降低韧性 |
| timeline | 8/10 | 纯计算模块，ffprobe 校准是亮点，风险点仅在 subprocess 无超时 |
| llm_client | 6/10 | chat_json 重试机制好，但 chat() 零重试是短板；300s 硬编码超时对长输出不友好 |
| comfyui_session | 5/10 | 最简实现，无重连、无错误分类、无健康检查、无输出文件清理；是管线最脆弱环节 |
| workflow_loader | 9/10 | 纯读取+注入，几乎无韧性风险 |
| e2e_dry_run | 7/10 | 编排逻辑完善（依赖检查、GPU 生命周期、VL 质检），但缺少并发保护和持久化日志 |
| migrate_costumes | 5/10 | 功能正确但无回滚，dry-run 可部分缓解 |

---

### 优先修复建议（按影响力排序）

1. **原子写入**（影响：全管线）：`_write()` 改为写入 `.tmp` 后 `os.replace()`，适用于 state_manager 和 asset_manager
2. **损坏恢复**（影响：全管线）：`get()` / `_read()` 加 try/except，JSON 解析失败时返回 init 状态 + 日志告警
3. **ComfyUI 崩溃恢复**（影响：S3/S3b/S5/S6/S9）：`wait()` 中检测 ComfyUI 不健康时抛 `ComfyUICrashedError`，e2e 层捕获后自动重启重试
4. **并发锁**（影响：多 episode）：GPU 切换操作加文件锁，state/asset 读写考虑 filelock
5. **chat() 重试**（影响：S1/S2/S4）：加 2 次重试 + 指数退避
6. **assets.json compact**（影响：长时间运行）：定期清除 is_active=False 的旧记录，或加 `compact()` 方法
7. **持久化日志**（影响：全管线）：e2e_dry_run 同时写文件日志
8. **Schema 版本号**（影响：升级）：state.json 加 `version` 字段，`get()` 里做向前兼容补全
