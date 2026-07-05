# Parallel Execution — 管线并行执行引擎

## 概述

`parallel_executor.py` 提供安全的 stage 级并行执行能力。通过 `ThreadPoolExecutor` 并发运行无 GPU 竞争的 pipeline stage，减少总管线执行时间。

## 问题背景

AIComicFactory 有 12 个 stage，大部分是串行的（上游→下游）。但有些 stage 之间没有数据依赖，且不共享 GPU 资源：

- **S7** (视频拼接, FFmpeg, CPU) 依赖 S6
- **S8** (字幕生成, Python, CPU) 依赖 S7
- **S9** (TTS 语音, ComfyUI, GPU) 依赖 S7 + S4

S8 和 S9 都依赖 S7 完成后启动，但它们互相独立 → **可并行**。

## API 参考

### `run_parallel_stages()`

```python
from core.parallel_executor import run_parallel_stages

results = run_parallel_stages(
    project=project_path,
    stage_tasks=[
        ("s8_subtitles", stage_def_s8, run_s8_func),
        ("s9_tts_audio", stage_def_s9, run_s9_func),
    ],
    parallel_label="S8+S9",
    max_workers=2,
)
# Returns: {"s8_subtitles": (True, {...}), "s9_tts_audio": (False, {...})}
```

### `find_parallel_groups()`

自动发现可并行 stage：

```python
from core.parallel_executor import find_parallel_groups

groups = find_parallel_groups(
    pipeline=pipeline_dict,       # pipeline.yaml parsed
    completed_stages=completed,   # pipeline keys of completed stages
    max_group_size=2,
)
# Returns: [
#   [("s8_subtitles", def), ("s9_tts_audio", def)],
# ]
```

### `is_parallelizable_stage()`

判断单个 stage 是否可并行：

```python
from core.parallel_executor import is_parallelizable_stage

is_parallelizable_stage("s8_subtitles", stage_def)
# → True  (gpu: none)

is_parallelizable_stage("s5_frame_generate", stage_def)
# → True  (gpu: comfyui, shared)

is_parallelizable_stage("some_vl_stage", {"gpu": "qw35_vl"})
# → False (exclusive GPU)
```

## 并行化规则

### GPU 分类

| GPU 类型 | 含义 | 可并行? |
|----------|------|---------|
| `none` | CPU/API，无 GPU | ✅ 是 |
| `comfyui` | ComfyUI shared 模式 | ✅ 是（与其他 type） |
| `qw35_vl` | Exclusive 模式 | ❌ 否 |

### 组合矩阵

| Stage A | Stage B | 可并行? | 示例 |
|---------|---------|---------|------|
| none | none | ✅ | S7 + S8 |
| none | comfyui | ✅ | S4 (LLM) + S3 (T2I) |
| none | qw35_vl | ❌ | — |
| comfyui | comfyui | ❌ | S3 + S5 (同 GPU) |
| qw35_vl | anything | ❌ | — |

### find_parallel_groups 条件

`find_parallel_groups` 使用更严格的规则来形成并行组：

1. **依赖就绪**: 两个 stage 的所有 `depends_on` 都已 completed
2. **非空依赖**: stage 必须至少有一个依赖（根 stage 不参与并行）
3. **共享依赖**: 必须有共同依赖（同一 parent）
4. **GPU 互补**: 一个 `none` + 一个 `comfyui`（两个 `none` 或两个 `comfyui` 不组队）
5. **无互依赖**: A 不依赖 B，B 不依赖 A

### 组大小限制

- `max_workers=2`：最多 2 个 stage 并行
- 单 GPU 机器上 2 个 worker 是安全上限
- 所有 stage 失败隔离：一个失败不影响另一个

## 与 State Manager 集成

并行执行时每个 stage 各自写 state.json，互不干扰：

```python
# e2e_dry_run.py 中的并行执行路径
def _run_single_stage(project, stage_id, stage_def):
    # ... 每个 stage 自己的 state 更新逻辑
    state_manager.mark_running(project, stage_id)
    # ... 执行 ...
    state_manager.mark_completed(project, stage_id)

# 并行
if args.parallel:
    groups = find_parallel_groups(pipeline, completed)
    for group in groups:
        stage_tasks = [(sid, sdef, _run_single_stage) for sid, sdef in group]
        run_parallel_stages(project, stage_tasks)
```

## 性能预期

| 场景 | 串行 | 并行 | 节省 |
|------|------|------|------|
| S8 (5s) + S9 (120s) | 125s | 120s | ~5s |
| S4 (30s) + S3 (60s) | 90s | 60s | ~30s |

对于有 26 个 shot 的典型项目，S8 耗时约 5s（纯计算），S9 耗时约 120s（TTS + ASR），并行可节省约 5s。

## 实现细节

### 线程模型

```
main thread          ThreadPoolExecutor
     │                     │          │
     ├─ submit(s8) ─────→ │ Worker 1 │
     ├─ submit(s9) ─────→ │ Worker 2 │
     │                     │          │
     ├─ as_completed() ←── │          │
     │                     └──────────┘
```

### 错误处理

- 每个 stage 在 `_wrap_task` 内 try/except
- 异常不传播：`exc_info` 记录到 result dict
- `as_completed` 无需等待所有完成即可处理结果

### 子进程隔离

每个 stage 作为独立 subprocess 启动（通过 `subprocess.run`），而非在同一个进程中调用函数。这确保了：

1. **环境隔离**: 不同 stage 可以有不同 conda env
2. **内存隔离**: ComfyUI 进程崩溃不影响主进程
3. **状态隔离**: state.json 写入不会交叉

## 测试覆盖

| 测试文件 | 用例数 | 覆盖内容 |
|----------|--------|----------|
| `tests/L0/test_pipeline_integration.py` | 8 | 基本并行、单失败、组发现、GPU 规则、可并行性判断 |
