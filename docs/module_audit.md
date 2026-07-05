# AIComicFactory 模块层 + 并行安全审计报告

- **审计日期**: 2026-07-05
- **审计范围**: `core/` 目录 15 个模块 + `scripts/e2e_dry_run.py`
- **基线**: `Phase 1-4` 标准化改造完成，148 单元测试

---

## 目录

1. [模块依赖图](#1-模块依赖图)
2. [接口契约审计](#2-接口契约审计)
3. [并行安全问题清单](#3-并行安全问题清单)
4. [接口兼容性报告](#4-接口兼容性报告)
5. [修复建议](#5-修复建议)
6. [审计结论](#6-审计结论)

---

## 1. 模块依赖图

### 1.1 ASCII 依赖图

```
scripts/e2e_dry_run.py
  ├─ core.llm_client           (S1/S2/S4 LLM 调用)
  ├─ core.prompt_runner         (prompt 组装)
  └─ core.parallel_executor     (并行编排)
       └─ (无 core/ 内部依赖)

scripts/s3_character_image.py
  ├─ core.state_manager
  ├─ core.asset_manager
  ├─ core.comfyui_session
  ├─ core.character_image_check
  │    └─ core.demographics          ◄── 唯一 core→core 依赖链
  ├─ core.demographics
  └─ core.workflow_loader

scripts/s3b_four_view.py
  ├─ core.state_manager
  ├─ core.asset_manager
  ├─ core.comfyui_session
  ├─ core.vl_backend
  ├─ core.four_view_check
  │    └─ core.vl_backend            ◄── 另一 core→core 依赖
  └─ core.workflow_loader    (via lazy import)

scripts/s4b_keyframe_assets.py ── core.state_manager
scripts/s5_frame_generate.py
  ├─ core.state_manager
  ├─ core.asset_manager
  ├─ core.comfyui_session
  ├─ core.workflow_loader
  ├─ core.vl_backend
  ├─ core.continuity_check    (lazy import)
  └─ core.video_quality_check (lazy import)

scripts/s6_flf2v_render.py
  ├─ core.state_manager
  ├─ core.asset_manager
  ├─ core.comfyui_session
  └─ core.workflow_loader

scripts/s7_video_assemble.py ── core.state_manager, core.asset_manager
scripts/s8_subtitles.py ── core.state_manager, core.timeline
scripts/s9_tts_audio.py ── core.state_manager, core.timeline, core.comfyui_session
```

### 1.2 core/ 模块间依赖矩阵

| 模块 | 依赖其他 core/ 模块 | 被依赖 | 等级 |
|---|---|---|---|
| `state_manager` | **无** | `__init__`, 全部 script | **DAG Root** |
| `parallel_executor` | **无** | `e2e_dry_run` | **独立叶子** |
| `asset_manager` | **无** | s3, s3b, s5, s6, s7 | 独立叶子 |
| `llm_client` | **无** | `e2e_dry_run` | 独立叶子 |
| `vl_backend` | **无** | `four_view_check`, s3b, s5 | 独立叶子 |
| `comfyui_session` | **无** | s3, s3b, s5, s6, s9 | 独立叶子 |
| `workflow_loader` | **无** | s3, s3b, s5, s6 | 独立叶子 |
| `prompt_runner` | **无** | `e2e_dry_run` | 独立叶子 |
| `demographics` | **无** | `character_image_check` | 独立叶子 |
| `character_image_check` | `demographics` | s3 | **叶，有依赖** |
| `four_view_check` | `vl_backend` | s3b | **叶，有依赖** |
| `continuity_check` | **无** | s5 (lazy) | 独立叶子 |
| `video_quality_check` | **无** | s5 (lazy) | 独立叶子 |
| `timeline` | **无** | s8, s9 | 独立叶子 |
| `schema_validators` | **无** | (目前未被调用) | 独立叶子 |

**结论**: 依赖图是 DAG，**不存在循环依赖**。`state_manager` 作为纯底层，所有依赖方向为 `script → core/state_manager`，符合单向依赖原则。

---

## 2. 接口契约审计

### 2.1 公共接口清晰度

| 模块 | 公开 API 数 | 接口风格 | 评语 |
|---|---|---|---|
| `state_manager` | 20 | 类 (StateManager) + 函数 (get_state_manager) | ✅ 良好: `__init__.py` 有 explicit re-export |
| `parallel_executor` | 4 | 纯函数 | ✅ 清晰: 四个独立函数，职责明确 |
| `asset_manager` | 12 | 类 (AssetManager) + 函数 | ✅ 良好: CRUD + 批量操作 |
| `llm_client` | 5 | 类 (LLMClient) + 函数 | ✅ 良好 |
| `vl_backend` | 8 | 类 (VLBackend) + 函数 | ✅ 良好 |
| `comfyui_session` | 10 | 类 (ComfyUISession) + dataclass + 函数 | ✅ 良好 |
| `workflow_loader` | 5 | 纯函数 | ✅ 良好 |
| `prompt_runner` | 4 | 纯函数 | ✅ 良好 |
| `demographics` | 4 | 纯函数 | ✅ 良好 |
| `character_image_check` | 5 | 类 (CharacterImageChecker) + 辅助函数 | ✅ 良好 |
| `four_view_check` | 6 | 类 (FourViewChecker) + 辅助函数 | ✅ 良好 |
| `continuity_check` | 8 | 类 (ContinuityChecker) + 辅助函数 | ✅ 良好 |
| `video_quality_check` | 6 | 类 (VideoQualityChecker) + 辅助函数 | ✅ 良好 |
| `timeline` | 12 | 类 (Timeline/ShotTiming) + 纯函数 | ✅ 良好 |
| `schema_validators` | 3 | 纯函数 | ⚠️ **未被调用**（见下方） |
| `core/__init__.py` | 7 | re-export | ✅ 仅导出 `state_manager`，未造成泄露 |

**问题**: `schema_validators` (S1/S2/S4 schema 验证) 当前**没有被任何模块调用**。这是 Phase 1-4 重构遗留 —— 验证逻辑已实现但尚未接入管线。

### 2.2 单向依赖原则验证

- ✅ `state_manager` 不反向依赖任何 core/ 模块
- ✅ `parallel_executor` 不反向依赖任何 core/ 模块
- ✅ 唯一两条 `core→core` 依赖链(`demographics→character_image_check`, `vl_backend→four_view_check`) 均方向正确
- ✅ 所有 scripts → core/ 依赖均为单向
- **无循环依赖**

### 2.3 "上帝类" 检查

| 模块 | 代码行数 | 类/函数数 | 评价 |
|---|---|---|---|
| `state_manager` | 959 行 | 1 类 + 5 函数 | ⚠️ **697 行类**，但职责单一（状态管理），可接受 |
| `parallel_executor` | 309 行 | 4 函数 | ✅ 单文件，多职责清晰的函数 |
| `character_image_check` | 302 行 | 1 类 + 5 函数 | ✅ |
| `four_view_check` | 377 行 | 1 类 + 6 函数 | ✅ |
| `continuity_check` | 227 行 | 1 类 + 5 函数 | ✅ |
| `video_quality_check` | 202 行 | 1 类 + 4 函数 | ✅ |
| `llm_client` | 345 行 | 1 类 + 2 函数 | ✅ |
| `timeline` | 359 行 | 2 类 + 10 函数 | ✅ 函数数量多但职责集中（时间轴） |

**结论**: `StateManager` (697 行) 是最大类，但管理 16 个 stage 的状态、参数哈希、脏状态、checkpoint、进度等，职责集中。不算"上帝类"。

---

## 3. 并行安全问题清单

（按严重度降序排列。基准: `parallel_executor.py` + `e2e_dry_run.py` 的并行执行路径分析。）

### **T1: state.json 写丢失** 🔴 严重

| 属性 | 值 |
|---|---|
| **位置** | `core/state_manager.py:482-493` ( `_write` / `_write_atomic` ), 各 script 的 `mark_completed()` 调用 |
| **影响范围** | S8∥S9 并行组 |
| **根因** | 两个子进程在并行组中各自独立地读-改-写 `state.json`。<br>s8_subtitles.py 第 76 行: `sm.mark_completed("s8_subtitles", ...)`<br>s9_tts_audio.py 第 530 行: `sm.mark_completed("s9_tts_audio", ...)`<br>两者均为 `update_stage()` → `self.get(project)` (读 state.json) → 修改 dict → `self._write(project, state)` (写回)。<br>无文件锁 → **后写者覆盖先写者**。 |
| **后果** | 一个 stage 的 `"status": "completed"` 在 state.json 中永久丢失。恢复后此 stage 被重新判定为 pending，可能触发不必要重跑。 |
| **复现条件** | 每轮并行执行（S8∥S9）必然发生。概率 ≈100%。 |

### **T2: vl_pending 列表线程不安全** 🟠 高

| 属性 | 值 |
|---|---|
| **位置** | `scripts/e2e_dry_run.py:732` (`vl_pending = []`), `scripts/e2e_dry_run.py:688-692` |
| **影响范围** | S8∥S9 并行组中任一带有 `vl_check: post` 的 stage |
| **根因** | `execute_pipeline()` 创建 `vl_pending = []` 后，传递给所有并行线程的 `_run_single_stage()`。<br>线程 A: `vl_pending.append(stage_id)` (L692)<br>线程 B: `vl_pending.append(stage_id)` (L692)<br>CPython GIL 使 `list.append` 原子安全，但 **`vl_pending.clear()` (L690) 在 s5 中调用** ，如果 s5 进入并行组（当前不会，因为 s5 是 comfyui stage），则 clear() 与另一个线程的 append() 并发可能导致数据丢失或 `IndexError`。 |
| **后果** | 当前不影响 S8∥S9（两者都没有 `vl_check: post`），但属于隐藏的地雷。 |
| **复现条件** | 为任何 cpu-only 且 `vl_check: post` 的 stage 启用并行时触发。 |

### **T3: logger 输出交错** 🟡 中

| 属性 | 值 |
|---|---|
| **位置** | `parallel_executor.py:78` (`logger.info`) + 各子进程 stdout |
| **影响范围** | 全部并行组 |
| **根因** | `logging.info()` 本身线程安全，但 `logger.exception(f"Parallel stage {stage_id} threw exception")` 等包含多行文本。Python logging 的 Lock 保护单行原子性，但多行消息可能被其他线程的日志插入中间。<br>此外，子进程的 stdio 通过 `subprocess.run(capture_output=True)` 收集后由主线程打印，不交错；但并行组中两个子进程的 stdout 不会混合（因为由主线程串行收集）。 |
| **后果** | 仅影响 log 可读性，**无功能性影响**。 |

### **T4: comfyui_started 潜在 double-start** 🟢 低

| 属性 | 值 |
|---|---|
| **位置** | `scripts/e2e_dry_run.py:666-668` |
| **影响范围** | 如果未来将两个 comfyui stage 放入同一并行组 |
| **根因** | `comfyui_started[0]` 是跨线程共享的可变列表元素。当前设计确保每组至多一个`gpu=comfyui` stage（`is_parallelizable_stage` 禁止两个 comfyui stage 并行），所以安全。但若未来放宽限制 → 两个线程同时检查 `comfyui_started[0] == False` 并同时调用 `ensure_comfyui()`，造成 ComfyUI 双重启动（幂等但冗余）。 |
| **后果** | 当前无影响。 |

### **T5: ComfyUI prompt_id 隔离** ⚪ 信息

| 属性 | 值 |
|---|---|
| **位置** | `core/comfyui_session.py:38` (`client_id`) |
| **影响范围** | 并行组中任何 `gpu=comfyui` 的 stage |
| **状态** | ✅ **安全** |
| **说明** | 每个子进程创建独立的 `ComfyUISession` 实例，`client_id` 基于 `uuid.uuid4()` 生成。ComfyUI 服务端区分不同 client_id 的 prompt 队列。**无共享状态**。 |

### **T6: 错误隔离验证** ⚪ 信息

| 属性 | 值 |
|---|---|
| **位置** | `parallel_executor.py:53-61` |
| **影响范围** | 全部并行组 |
| **状态** | ✅ **安全** |
| **说明** | `_wrap_task` 包含完整的 `try/except`，任何异常被捕获为 (False, error_detail)。**一个 stage 的失败不会取消或影响其他 stage**。`as_completed` 收集结果时对单个 future 失败有容错。 |

---

## 4. 接口兼容性报告

### 4.1 Phase 1-4 变更对向后兼容的影响

| 模块 | 变更 | 向后兼容 | 说明 |
|---|---|---|---|
| `state_manager` | v2 重构（`__init__` 重导出 + `update_stage` API 细化） | ✅ 兼容 | `migrate_v1_to_v2()` 自动迁移，旧调用 `mark_completed/mark_failed` 保持签名不变 |
| `parallel_executor` | 新增模块 | ✅ N/A | 全新，无历史兼容问题 |
| `asset_manager` | 新增 `get_active_for_shot`, `get_character_active` | ✅ 兼容 | 新增方法不破坏已有 `register/get_active` 签名 |
| `vl_backend` | 新增 `ensure_available` 方法 | ✅ 兼容 | 新增方法，不破坏已有 `is_available/start/stop` |
| `schema_validators` | 新增模块 | ⚠️ 未接入 | 代码就绪但管路未调用，**无 breakage** |
| `demographics` | 修复年龄正则（`re.search` 替代 `in`） | ✅ 兼容 | 行为更加正确，返回值类型不变 |
| `character_image_check` | 新增 `check_batch` | ✅ 兼容 | 新增方法 |

### 4.2 公共 API 签名稳定性

| 签名类型 | 数量 | 已变更 | 破坏性变更 |
|---|---|---|---|
| 类构造器 (`__init__`) | 8 | 0 | 0 |
| 方法 | ~80 | 2（`state_manager.v2`） | 0 |
| 顶层函数 | ~30 | 0 | 0 |
| 全局常量 | ~15 | 0 | 0 |

**结论**: Phase 1-4 重构全部为**非破坏性**(additive)变更。无删除、无重命名、无参数签名变更有语义差异。

---

## 5. 修复建议

### P0-必修: state.json 写丢失 (T1)

**方案 A（推荐）: 文件锁**
在 `_write_atomic` 中引入跨进程文件锁。

```python
import fcntl

def _write_atomic(self, path: Path, data: dict):
    """Write JSON atomically via tmp + os.replace + flock."""
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)     # 独占锁
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
        fcntl.flock(f, fcntl.LOCK_UN)
    os.replace(tmp, path)
```

在 `_write` 和 `load` 中加读锁：

```python
def load(self, project: str) -> dict:
    path = self._state_path(project)
    ...
    with open(path, "r") as f:
        fcntl.flock(f, fcntl.LOCK_SH)     # 共享锁
        state = json.load(f)
        # f.close() 自动释放读锁
    ...
```

**方案 B（轻量）: 在并行组结束后统一合并 state**
在 `execute_pipeline()` 中，为并行组使用`run_parallel_stages`返回后在主线程统一调用 `mark_completed`，绕过子进程直接写 state.json。

### P1-高: vl_pending 线程安全 (T2)

**修复**: 给 `vl_pending` 加 `threading.Lock`：

```python
import threading
vl_pending = []
vl_lock = threading.Lock()
```

```python
with vl_lock:
    vl_pending.append(stage_id)
```

或者在并行路径中禁用 vl_pending 收集（并行 stage 都不带 `vl_check:post`，当前确实如此），加断言：

```python
assert not any(sdef.get("vl_check") for _, sdef in parallel_group), \
    "Parallel group contains vl_check stages — not safe"
```

### P2-中: schema_validators 未接入

将 `validate_s1_output()` / `validate_s2_output()` / `validate_s4_output()` 挂接到 `e2e_dry_run.py` 的 `run_llm_stage()` 和 `run_script_stage()` 中，在 LLM 响应后/脚本完成后执行 schema 校验并记录 warning（不阻塞管线）。

---

## 6. 审计结论

| 维度 | 评分 | 评语 |
|---|---|---|
| **模块化设计** | ✅ A- | 15 模块职责清晰，无循环依赖。`state_manager` 作为纯底层，符合单向依赖。 |
| **接口契约** | ✅ A | 每个模块有明确的公共接口，类型标注良好。`__init__.py` 显式 re-export。 |
| **向后兼容** | ✅ A | Phase 1-4 所有变更为 additive，零破坏性变更。 |
| **并行安全** | ⚠️ C | **T1 state.json 写丢失是 P0 级生产缺陷**，每轮 S8∥S9 必然发生。T2 vl_pending 是地雷。其余项 (T3-T6) 可控或无影响。 |
| **代码健康度** | ✅ B+ | `StateManager` 697 行稍大但可接受。`schema_validators` 代码死码须接入。 |

**整体**: 代码架构质量高（DAG 清晰、单一职责），但并行安全有**一项严重缺陷**（T1）和一个中等风险（T2），建议在下一轮迭代优先修复 P0。

---

*审计结束。总计检查 15 个 `core/` 模块 + 1 个编排脚本 + 1 个管线定义。*
