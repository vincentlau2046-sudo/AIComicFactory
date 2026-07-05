# State Manager v2 — 管线状态管理

## 概述

`state_manager.py` 是 AIComicFactory 管线的状态管理核心。v2 版本从简单的线性状态跟踪升级为健壮的 DAG 驱动执行引擎，支持断点续跑、参数变更检测和脏级联传播。

## 架构

```
                  ┌──────────────────────┐
                  │    pipeline.yaml      │  ← 声明式管线定义（唯一真相源）
                  └──────────┬───────────┘
                             │ load_pipeline_config()
                             ▼
                  ┌──────────────────────┐
                  │    StateManager       │
                  │  ┌────────────────┐   │
                  │  │ _pipeline_config│   │  ← 缓存原始 YAML
                  │  │ _stage_order   │   │  ← 拓扑序 stage ID 列表
                  │  │ _stage_defs    │   │  ← stage_id → def 映射
                  │  │ _stage_deps    │   │  ← DAG 依赖图
                  │  │ _stage_r_deps  │   │  ← 逆依赖图（反向传播用）
                  │  │ _pipeline_key_map │ ← 双向 key 映射
                  │  └────────────────┘   │
                  └──────────┬───────────┘
                             │ load() / get() / _write()
                             ▼
                  ┌──────────────────────┐
                  │  projects/{name}/     │
                  │    state.json (v2)   │  ← JSON 文件持久化
                  └──────────────────────┘
```

## state.json v2 Schema

```json
{
  "version": 2,
  "project": "achieve",
  "stages": {
    "s1_parse": {
      "status": "completed",      // pending | running | completed | failed | dirty
      "ts": "2026-07-05T12:00:00Z",
      "checkpoint": {              // 可选：shot-level 进度
        "total_shots": 72,
        "completed_shots": [1,2,3,4,5],
        "failed_shots": [],
        "last_checkpoint": "2026-07-05T12:05:00Z",
        "shot_metadata": {
          "1": {"path": "s5_frames/s01_first.png", "resolution": "1280x720"}
        }
      },
      "params_hash": "a1b2c3...", // 可选：参数指纹
      "dirty": false,             // dirty 标记
      "dirty_reason": ""          // 脏标记原因
    },
    ...
  },
  "dirty_history": [              // 脏传播审计
    {
      "stage": "s1_parse",
      "reason": "param change",
      "downstream": ["s2_character_extract", "s2b_wardrobe_extract", ...],
      "ts": "2026-07-05T12:00:00Z"
    }
  ]
}
```

## 核心流程

### 1. 初始化管线

```python
sm = StateManager(projects_root="/path/to/projects")
sm.init_project("my_project")
# → 从 pipeline.yaml 读取所有 12 stage，创建 state.json
# → 每个 stage 状态为 pending
```

### 2. 断点续跑

```python
state = sm.load("my_project")            # 自动迁移 v1→v2
nxt = sm.next_pending("my_project")      # 拓扑序找第一个未完成 stage
if nxt:
    sm.mark_running("my_project", nxt)
    # ... 执行 stage ...
    sm.mark_completed("my_project", nxt)
```

### 3. Shot-level Checkpoint

对于包含多个子任务 (如 S5 的 72 个 shot 帧) 的 stage：

```python
# 初始化
sm.init_checkpoint("my_project", "s5_frame_generate", total_shots=72)

# 记录进度
sm.record_checkpoint("my_project", "s5_frame_generate", shot_id=1)
sm.record_checkpoint("my_project", "s5_frame_generate", shot_id=2, status="failed", path="s5_frames/s02_first.png")

# 恢复时
skipped = sm.skip_completed_shots("my_project", "s5_frame_generate")
# → [1]  已完成的跳过
```

### 4. 参数变更检测

```python
args = {"model": "DEEPSEEK_PRO", "temperature": 0.7}
sm.record_params("my_project", "s1_parse", args)

# 下次调用时
new_args = {"model": "QWEN35", "temperature": 0.5}
if sm.params_changed("my_project", "s1_parse", new_args):
    # 参数变了 → 自动标记 dirty
    sm.mark_dirty("my_project", "s1_parse", reason="model changed")
```

### 5. 脏级联传播

```python
# 标记 s1_parse stale → BFS 传播到所有依赖 s1_parse 的 stage
sm.mark_stale("my_project", "s1_parse")
# 效果：
#   s1_parse: dirty=True (status=pending)
#   s2_character_extract: dirty=True (status=pending)  ← 直接依赖
#   s3_character_image: dirty=True (status=pending)     ← 间接依赖
#   ...
#   s7_assemble: status=completed (不受影响)             ← 不依赖 s1_parse
```

## 依赖图 (DAG)

```
s1_parse ──→ s2_character_extract ──→ s2b_wardrobe_extract
   │                                         │
   │                                         ▼
   │                                       s3_character_image
   │                                         │
   │                                         ▼
   │                                       s3b_four_view
   │                                         │
   ▼                                         ▼
s4_shot_split ──→ s4b_keyframe_assets ──→ s5_frame_generate
                                               │
                                               ▼
                                            s6_video_generate
                                               │
                                               ▼
                                            s7_assemble
                                           /            \
                                          ▼              ▼
                                    s8_subtitles    s9_tts_audio
```

## 关键设计决策

| # | 决策 | 方案 | 理由 |
|---|------|------|------|
| D1 | 数据源 | pipeline.yaml | 声明式配置，stage 增删无需改代码 |
| D2 | 持久化 | JSON 文件 | 零依赖，人类可读，git diff 友好 |
| D3 | 写保护 | 原子写入 | write → tmp → rename，防断电损坏 |
| D4 | 拓扑序 | 构建期排序 | 运行时 O(1) next_pending |
| D5 | 参数指纹 | SHA256 | 确定性，碰撞概率可忽略 |
| D6 | 脏传播 | BFS | 精确到影响子图，不碰无关 stage |
| D7 | 向后兼容 | 自动迁移 | v1 state.json 加载时自动升级 |

## 测试覆盖

| 测试文件 | 用例数 | 覆盖内容 |
|----------|--------|----------|
| `tests/L0/test_state_manager.py` | 64 | 核心 API、checkpoint、hash、dirty、migration、YAML 解析 |
| `tests/L0/test_pipeline_integration.py` | 34 | 完整管线执行、断点恢复、参数检测、并行模式、进度报告 |
