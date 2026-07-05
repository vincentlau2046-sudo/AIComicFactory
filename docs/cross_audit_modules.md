# L2 模块层 + 并行安全审计（Claude Cross-Review）

> 审计日期：2026-07-05
> 目标：验证 AtomCode L2 审计结论的正确性

---

## 1. 模块依赖 DAG（15 个 core/ 模块）

**结论：DAG 成立，无循环依赖。模块化结构优秀。**

核心模块间仅有 **2 条跨模块边**：

```
demographics.py          → 无依赖
vl_backend.py             → 无依赖
state_manager.py           → 无依赖
parallel_executor.py      → 无依赖
character_image_check.py  → demographics.py
four_view_check.py        → vl_backend.py
其余 12 个模块            → 无跨模块依赖（完全独立）
```

13 个模块（87%）无跨模块依赖。`state_manager.py` 是唯一的共享状态中心，仅通过 `core/__init__.py` 和 scripts/ 层导入。

**DAG 验证：✅ 通过。无循环，无分层违规。**

---

## 2. T1: state.json 写丢失（无文件锁）— 是否属实？

### AtomCode 问题描述
> 多线程并发写入 state.json 导致写丢失，无文件锁保护。

### 分析

**读写路径：**

| 方法 | 实现 | 原子性 |
|------|------|--------|
| `_write_atomic()` | write → `.json.tmp` → `os.replace()` | ✅ 单写原子 |
| `update_stage()` | `get()` → modify → `_write()` | ❌ RMW 整体不原子 |
| `mark_failed()` | 同左 | ❌ RMW 整体不原子 |
| `record_checkpoint()` | 同左 | ❌ RMW 整体不原子 |

`os.replace()` 保证单个写操作原子（不会出现文件截断 + 崩溃 = 数据损坏）。但 **Read-Modify-Write 整体不原子** — 两个线程并发更新同一个 state.json 时可能丢失另一个线程的更新。

### 实战影响评估

**关键：state.json 的并发写入何时发生？**

```
线程 A (S8) → _run_single_stage() → run_script_stage() → [脚本内部写 state.json]
线程 B (S9) → _run_single_stage() → run_script_stage() → [脚本内部写 state.json]
```

`_run_single_stage()` 本身不直接调用 `StateManager`。state.json 更新由被调用的脚本内部完成（如 `s8_subtitles.py` 调用 `mark_completed()`）。

当 S8∥S9 并行时：
- 两线程各自 update 自己的 stage 字段（`s8_subtitles` / `s9_tts_audio`）
- 写入的是 **不同的 key**，碰撞概率极低
- 但全局字段（`errors[]`, `updated`）可能丢失一个线程的写入

**判决：部分属实（理论 Race Condition 存在），但实战影响 = 可忽略。**

| 维度 | 评级 | 原因 |
|------|------|------|
| 正确性风险 | **极低** | 各线程写不同 key，JSON 结构不损坏 |
| 完整性风险 | **低** | `updated` 时间戳可能丢失，`errors[]` 可能漏一条 |
| 触发条件 | **苛刻** | 仅 `parallel=True` 且两脚本同时写入 state.json |

**建议（非阻塞）：** 如需 100% 安全，加一个 `threading.Lock` 包裹 RMW 操作。当前影响不足以阻塞合入。

---

## 3. T2: vl_pending 列表线程不安全 — 是否属实？

### AtomCode 问题描述
> `vl_pending` 列表在多线程环境下无锁保护，`append()` 不安全。

### 分析

共享可变对象传递路径（`e2e_dry_run.py`）：

```python
# Line 731-732: 创建共享状态
comfyui_started = [False]
vl_pending = []

# Line 777-779: 传递给并行线程
vl_pending=vl_pending,
comfyui_started=comfyui_started,
```

两个并行线程共享同一 `vl_pending` 列表和 `comfyui_started` 单元素列表。

**`vl_pending.append()` — 线程安全性：**
- CPython GIL 保证 `list.append()` 原子（不会被其他线程打断）
- 不会崩溃、不会数据损坏
- 但 **无法保证 append 顺序** 与线程完成顺序一致

**`comfyui_started[0] = True` — 线程安全性：**
- `comfyui_started[0] = True` 本身不原子（list `__setitem__`）
- 但实际行为：两线程读到 `False` → 都调用 `ensure_comfyui()` → 第一个启动，第二个 `_comfyui_healthy()` 检测到已运行 → 安全

**`_flush_vl_checks()` 重复调用风险：**
- `_run_single_stage()` line 689: `if stage_id == "s5_frame_generate": _flush_vl_checks(...)`
- S5 不参与并行（需要 comfyui GPU），此路径在并行时不触发
- 即使触发，`vl_pending.clear()` + `append()` 的组合在 CPython 下安全

**判决：T2 属实（列表共享无锁），但实战后果 = 可忽略。**

| 风险 | 严重度 | 说明 |
|------|--------|------|
| `vl_pending` 数据损坏 | **不可能** | CPython GIL 保护 list append |
| VL 质检顺序错误 | **理论存在** | 两个 append 顺序不确定 |
| 重复 VL flush | **不会发生** | S5（触发 flush）不参与并行 |
| ComfyUI 重复启动 | **无害** | `_comfyui_healthy()` 幂等 |

---

## 4. 并行执行引擎评估（`parallel_executor.py`）

### 架构
- `ThreadPoolExecutor` (max_workers=2)
- `run_parallel_stages()` — 纯执行，不碰 state.json
- `find_parallel_groups()` — 运行时依赖解析
- `find_potential_parallel_groups()` — DAG 结构分析
- `is_parallelizable_stage()` — GPU 门控

### GPU 门控（line 294-309）
```python
def is_parallelizable_stage(stage_id: str, stage_def: dict) -> bool:
    gpu = stage_def.get("gpu", "none")
    return gpu == "none"  # Only CPU-only stages are parallel-safe
```

**问题：当前 pipeline.yaml 中 S8(gpu:none) ∥ S9(gpu:comfyui)**
- S8 通过 `is_parallelizable_stage()` ✅
- S9 不通过 ❌
- **`find_parallel_groups()` 只能找到 S8 一个可并行化 stage，无法组成组**

这意味着 `find_parallel_groups()` 在当前配置下 **找不到 S8∥S9 组**。

**`_detect_parallel_group()` 的 GPU 检查（line 906-911）：**
```python
if gpu_a == "comfyui" and gpu_b == "comfyui":
    continue
if gpu_a == "none" and gpu_b == "none":
    continue
```

这个检查要求 **恰好一个 GPU + 一个 CPU** — 但 `_detect_parallel_group()` 在 line 850 先检查 `is_parallelizable_stage(stage_id)`，只放行 `gpu=none` 的 stage。S9 被 `is_parallelizable_stage()` 过滤掉。

**这意味着 `_detect_parallel_group()` 仍然能配对 S8(none) + S9(comfyui)** — 因为 gate 只检查发起者（stage_id），不是后续配对。line 884 `is_parallelizable_stage(next_id, next_def)` **也会过滤掉 S9**。

所以当前逻辑：**S8 作为发起者通过 gate，S9 作为配对者被 gate 拒绝。S8∥S9 无法并行。**

需要确认：如果 S9 的 GPU 标记改为 `none`，则两组都能通过 gate 且通过 GPU 差异化检查。

### 闭包陷阱检查（line 773-782）
```python
def make_task(sid, sdef):
    def _task(_sid, _sdef):
        return _run_single_stage(project, _sid, _sdef, ...)
    return _task
parallel_tasks.append((psid, psdef, make_task(psid, psdef)))
```
✅ **闭包正确** — `make_task` 的参数 `sid, sdef` 作为形参捕获了正确的值（不是循环变量的引用）。

### 错误隔离
✅ **优秀** — `_wrap_task()` 用 try/except 包裹每个 stage，单个异常不影响其他。

---

## 5. 并行安全总评

| 组件 | 风险 | 实战影响 | 评级 |
|------|------|----------|------|
| `_write_atomic` os.replace | 单写原子，RMW 不原子 | 低 — 不同 key 不碰撞 | B |
| `vl_pending` 共享列表 | GIL 保护不崩溃 | 可忽略 — 仅顺序不确定 | B- |
| `comfyui_started` 共享标志 | 重复检查无害 | 无 — ensure_comfyui 幂等 | A |
| 闭包变量捕获 | 无 bug | — | A |
| 错误隔离 | 完善 | — | A |
| GPU 门控 | 正确但限制强 | S8∥S9 无法并行 | C- |

---

## 6. AtomCode 结论验证

| AtomCode 结论 | 实际评估 | 判定 |
|---|---|---|
| **模块化 A-** | ✅ 13/15 模块零耦合，DAG 干净 | **同意** |
| **并行安全 C** | ⚠️ 降级理由不够精准。真正问题是 GPU 门控过严（S9 无法并行），而非线程安全 | **修正为 C+** — 线程安全实际是 B-，GPU 门控是 C- |

**AtomCode 对 T1/T2 的判断方向正确，但严重度评估偏保守。**

---

## 7. 建议（优先级排序）

1. **P0（阻塞）：无** — 没有需要立即修复的阻塞问题
2. **P1（改进）：**
   - 放松 `is_parallelizable_stage()` 的 GPU 门控 — 允许 comfyui + none 组合并行（两线程各自管理 GPU 生命周期）
   - 或在 `parallel_executor.py` 中为 RMW 加 `threading.Lock`（防御性编程）
3. **P2（可选）：**
   - `vl_pending` 使用 `queue.Queue` 替代裸 list（跨解释器安全）
   - 为 `comfyui_started` 使用 `threading.Event` 代替 `[False]` 列表

---

## 附录：模块依赖图（完整）

```
core/__init__.py ──→ state_manager.py (re-export)

scripts/ ──→ core/:
  e2e_dry_run.py  → llm_client, prompt_runner, parallel_executor, character_image_check
  s3_*.py        → comfyui_session, state_manager, asset_manager, demographics, workflow_loader
  s5_*.py        → comfyui_session, state_manager, asset_manager, workflow_loader, vl_backend
  s6_*.py        → comfyui_session, state_manager, asset_manager, workflow_loader
  s7_*.py        → state_manager, asset_manager
  s8_*.py        → state_manager, timeline
  s9_*.py        → state_manager, comfyui_session, timeline
```

所有脚本 → core 方向的依赖。**无 core → scripts 反向依赖。** 单向依赖良好。
