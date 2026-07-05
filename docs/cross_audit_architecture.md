# 角色交换审计: AtomCode L1 架构层 + A 数据流连续性

**审计角色**: 架构审计专家（AtomCode 扮演 L1 角色，交叉验证 Claude 的 L1 审计）
**审计日期**: 2026-07-05
**基线版本**: 129e990 (Phase 1-4 标准化改造 + 148 单元测试)
**审计范围**: pipeline.yaml 数据流连续性 + state_manager 单一真相源 + 依赖图拓扑一致性

---

## 1. 数据流图 (ASCII)

```
source.txt
    │
    ▼
┌──────────────────────────────────────────────────────┐
│ s1_parse  (source.txt → s1_parsed.json)              │
│ depends_on: []  order:1                               │
└──────┬───────────────────────┬────────────────────────┘
       │                       │
       ▼                       ▼
┌──────────────────┐  ┌──────────────────────────────┐
│ s2_character_ext │  │ s4_shot_split                 │
│ s1_parsed.json   │  │ s1_parsed.json                │
│ → s2_characters  │  │ s2_characters.json            │
│ depends: [s1]   │  │ → s4_shots.json                │
│ order:2          │  │ depends: [s1, s2]  order:4    │
└──────┬───────────┘  └──────┬────────────────────────┘
       │                     │
       ▼                     ▼
┌──────────────────┐  ┌──────────────────────────────┐
│ s2b_wardrobe_ext │  │ s4b_keyframe_assets           │
│ s2_characters    │  │ s4_shots.json                 │
│ → (in-place)     │  │ s2_characters.json            │
│ depends: [s2]   │  │ → s4b_keyframe_assets.json    │
│ order:3          │  │ depends: [s4, s2]  order:5    │
└──────────────────┘  └──────┬────────────────────────┘
                             │
       ┌─────────────────────┘
       ▼
┌──────────────────────────────┐
│ s3_character_image            │
│ s2_characters.json           │
│ → s3_character_refs/         │
│ depends: [s2]  order:6       │
│ gpu: comfyui                 │
└───────────┬──────────────────┘
            │
            ▼
┌──────────────────────────────┐
│ s3b_four_view                 │
│ s3_character_refs/manifest   │
│ → s3b_four_views/            │
│ depends: [s3]  order:7       │
│ gpu: comfyui                 │
└───────────┬──────────────────┘
            │
            ▼  ┌───────────────────────┐
     ┌──────── │  s4b_keyframe_assets  │
     │        └───────────┬───────────┘
     ▼                    ▼
┌─────────────────────────────────────────────────┐
│ s5_frame_generate                                 │
│ requires: [s4b_keyframe_assets.json,              │
│            s3_character_refs/,                     │
│            s3b_four_views/]    ← s3b_four_views/! │
│ depends_on: [s3_character_image, s4_shot_split,   │
│              s4b_keyframe_assets]                  │
│ ⚠️ MISSING: s3b_four_view                         │
│ → s5_frames/*.png  order:8  gpu:comfyui          │
└────────────────────┬─────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────┐
│ s6_video_generate                                 │
│ s5_frames/, s4b_keyframe_assets.json             │
│ → s6_videos/*.mp4                                │
│ depends: [s5]  order:9  gpu:comfyui              │
└────────────────────┬─────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────┐
│ s7_assemble                                       │
│ s6_videos/                                        │
│ → s7_assembled.mp4                                │
│ depends: [s6]  order:10  gpu:none                 │
└─────────────────┬────────────────────────────────┘
                  │
          ┌───────┴───────┐
          │   PARALLEL    │  (S8 ∥ S9)
          │   GROUP       │
          ▼               ▼
┌─────────────────┐ ┌────────────────────────┐
│ s8_subtitles    │ │ s9_tts_audio           │
│ s7_assembled    │ │ s7_assembled.mp4       │
│ .mp4,           │ │ s4_shots.json          │
│ s4_shots.json   │ │ → s9_final.mp4         │
│ → s8_subtitles │ │ depends: [s7, s4] ✅   │
│ .ass            │ │ gpu: comfyui           │
│ depends: [s7]  │ │ order:12               │
│ ⚠️ MISSING: s4 │ │                        │
│ gpu: none       │ │                        │
│ order:11        │ │                        │
└─────────────────┘ └────────────────────────┘
```

---

## 2. 交叉对比: 与 Claude L1 审计的比较

### 2.1 同意项目

| 编号 | 发现 | 我在本审计中的立场 | Claude 评级 | 我的评级 | 理由 |
|------|------|-------------------|-------------|---------|------|
| ✅-1 | 双 YAML 解析器风险 | 同意存在问题，但严重度降级 | **P0** | **P1** | 主路径使用 pyyaml，回退解析器触发概率低；真正的修复成本较低（提取公共 yaml_parser.py） |
| ✅-2 | STAGE_DEPS s9 缺少 s7 | 同意，并新增一个矛盾点(见下) | **P1** | **P1** | 硬编码与 YAML 的事实偏差会误导导入者 |
| ✅-3 | S8 depends_on 缺少 s4 | 同意是 ghost dependency | **P2** | **P2** | 运行时由 check_requires 兜底 |
| ✅-4 | e2e_dry_run 不使用 SM | 同意 | **P2** | **P2** | 设计选择而非 bug |

### 2.2 分歧项目

| 编号 | 发现 | Claude 立场 | 我的立场 | 论据 |
|------|------|------------|---------|------|
| ❌-1 | s5 依赖 s4 是"冗余" | **P1** — 认为 s4 不应在 s5 的 depends_on 中 | **P2 或 not-a-bug** | `depends_on` 是**阶段完成约束**，`requires` 是**文件读取需求**，两者不可互换。s5 间接需要 s4 完成 (s4→s4b→s5), 明确写下 s4 是保守但安全的设计。真正的 bug 是 **s5 缺少 s3b 的 depends_on** (见下) |
| ❌-2 | 架构无回归 | **无回归判定** | **有回归: 2 个幽灵依赖** | Claude 宣称"数据流连续无断点"，但 s5→s3b 和 s8→s4 两个缺失边构成数据流断裂。s5 的缺失比 s8 更严重(详见 §3) |

### 2.3 Claude 未覆盖的盲区

以下发现完全未出现在 Claude 的 L1 审计中:

| ID | 发现 | 严重度 | 说明 |
|----|------|--------|------|
| **BLIND-1** | S5 `depends_on` 缺少 `s3b_four_view` | **P0** | §3.1 详述 |
| **BLIND-2** | 依赖图无拓扑环检测 | **P1** | §3.3 详述 |
| **BLIND-3** | `_build_stage_index` 无未知依赖验证 | **P1** | §3.4 详述 |
| **BLIND-4** | STAGE_DEPS 硬编码 s9 缺少 s7 的同时也缺少 s4b 的新依赖 | **P1** | §3.2 详述 |
| **BLIND-5** | `_LEGACY_STAGE_ORDER` 缺少 s2b (11 vs 12) | **P2** | §3.5 详述 |
| **BLIND-6** | `_stage_order` 按 order 字段排序而非拓扑排序 | **P2** | §3.6 详述 |
| **BLIND-7** | `compute_params_hash` 的 ensure_ascii=False 跨平台风险 | **P2** | §3.7 详述 |

---

## 3. 独立发现 (Claude 盲区)

### 3.1 🔴 P0: S5 `depends_on` 缺失 `s3b_four_view` — 真正的数据流断点

**位置**: `pipeline.yaml` 第 100-112 行

```yaml
s5_frame_generate:
  id: s5_frame_generate
  order: 8
  requires: [s4b_keyframe_assets.json, s3_character_refs/, s3b_four_views/]
  produces: [s5_frames/*.png]
  depends_on: [s3_character_image, s4_shot_split, s4b_keyframe_assets]
  #                    ^^^^ present        ^^^^ present     ^^^^ present
  #                    s3b_four_view MISSING!
```

**问题**: `requires` 明确需要 `s3b_four_views/`，该目录由 `s3b_four_view` (order:7) 产出。但 `depends_on` 中仅有 `s3_character_image`（s3b 的**上游**），无 `s3b_four_view`。这意味着：
1. **调度错误**: `next_pending()` 只检查 `depends_on`，s5 会在 s3_character_image 完成后即被视为"准备就绪"，即使 s3b_four_view 尚未开始
2. **Check_requires 兜底但浪费**: `e2e_dry_run.py` 的 `check_requires()` 会因 `s3b_four_views/` 目录不存在而跳过 s5，但这发生在尝试执行之后
3. **幽灵依赖 vs 真实断点**: 与 s8 的 ghost dependency (Claude 注明"安全因线性顺序")不同，s3b 在 order 7 而 s5 在 order 8，正常串行时 s3b 会先完成。但若 future 并行化跳过 order 检查，或有人用 `--from s3_character_image`，s5 会**静默失败**

**风险**: 
- 串行执行: 低风险 (order 7 < order 8，安全)
- 并行执行/部分重跑: **高风险** — s5 会在 s3b 尚未完成时启动

**修复**:
```yaml
s5_frame_generate:
  depends_on: [s3_character_image, s3b_four_view, s4b_keyframe_assets]
```

> **对 Claude 审计的批评**: Claude 在 P1-1 中关注了 s4_shot_split 在 s5 depends_on 中的"冗余"，却完全忽略了**真正缺失**的 s3b_four_view。这是一个方向性错误 — 审查了多余边但漏掉了必要边。

### 3.2 🟡 P1: STAGE_DEPS 硬编码的多处不一致

**位置**: `core/state_manager.py` 第 934-946 行

Claude 发现 s9 缺少 s7。我更进一步发现:

```
                    pipeline.yaml (truth)        | STAGE_DEPS (hardcoded)
s8_subtitles        [s7_assemble]                | ["s7_assemble"]          ✅
s9_tts_audio        [s7_assemble, s4_shot_split] | ["s4_shot_split"]        ❌ 缺少 s7
```

但更关键的是 — 硬编码列表还缺少 `s2b_wardrobe_extract` 的所有相关依赖:

```python
STAGE_DEPS = {
    "s2_character_extract": ["s1_parse"],          # s2b 不存在于任何 deps 中!
    # s2b_wardrobe_extract 完全缺失!
    # ...
}
```

**问题**: `s2b_wardrobe_extract` 是 Phase 4 新增 stage，从 `_LEGACY_STAGE_ORDER` 到 `STAGE_DEPS` 都没有它。如果有人通过 `STAGE_DEPS` 查询依赖，会看不到 s2b 的任何信息。

### 3.3 🟡 P1: 依赖图无拓扑环检测

**位置**: `core/state_manager.py` — `_build_stage_index()` 第 276-328 行

```python
def _build_stage_index(self, config: dict):
    # ... builds deps from depends_on ...
    # NO cycle detection!
```

如果某人错误地在 pipeline.yaml 中引入环路 (如 `s8 → s9 → s8`):

| 受影响的函数 | 后果 |
|-------------|------|
| `mark_stale()` BFS | **无限循环** — BFS 在环路上永不停歇 |
| `next_pending()` | 依赖永远无法满足，stage 被永久跳过 |
| `load_pipeline_deps()` | 返回含环路的错误图 |

**建议**: 在 `_build_stage_index()` 中添加 Kahn 拓扑排序或 DFS 环检测:

```python
# Pseudo-code
def _validate_dag(self, deps):
    """Verify no cycles in dependency graph — raise ValueError if found."""
    visited, stack = set(), set()
    def dfs(node):
        if node in stack: raise ValueError(f"Cycle detected: {node}")
        if node in visited: return
        visited.add(node); stack.add(node)
        for dep in deps.get(node, []): dfs(dep)
        stack.remove(node)
    for node in deps: dfs(node)
```

### 3.4 🟡 P1: 未知依赖静默吞没

**位置**: `core/state_manager.py` 第 315-317 行

```python
else:
    # Fallback: treat as state_id directly
    resolved.append(dep)
```

如果一个 stage 的 `depends_on` 引用了不存在的 stage ID，代码**静默将其作为原始字符串添加**。该 dep 永远不会在 `_stage_deps` 中作为 key 出现，因此 `next_pending()` 中 `deps_met` 检查会永远返回 `False`，**该 stage 被永久卡在 pending 状态** — 无错误日志、无告警。

**建议**: 在 fallback 路径上增加 warn 日志:

```python
else:
    logger.warning(f"Stage '{sid}' depends on '{dep}' which is not a known stage ID or pipeline key")
    resolved.append(dep)
```

### 3.5 🟢 P2: `_LEGACY_STAGE_ORDER` 缺少 s2b

**位置**: `core/state_manager.py` 第 209-213 行

```python
_LEGACY_STAGE_ORDER = [
    "s1_parse", "s2_character_extract", "s3_character_image", "s3b_four_view",
    "s4_shot_split", "s4b_keyframe_assets", "s5_frame_generate",
    "s6_video_generate", "s7_assemble", "s8_subtitles", "s9_tts_audio",
]  # 11 stages — missing s2b_wardrobe_extract!
```

`pipeline.yaml` 有 12 个 stage (含 s2b)，但 `_LEGACY_STAGE_ORDER` 只有 11 个。此常量通过 `STAGE_ORDER` 导出，任何仍使用 `STAGE_ORDER` 的遗留代码都会遗漏 s2b。

### 3.6 🟢 P2: `_stage_order` 按 order 排序而非拓扑排序

**位置**: `core/state_manager.py` 第 297-301 行

```python
self._stage_order = sorted(
    defs.keys(),
    key=lambda sid: defs[sid].get("order", 99)
)
```

如果 `order` 值与 `depends_on` 图矛盾，线性顺序会违反依赖约束。例如，假设错误地将 s4 设为 order:2 而 s2 设为 order:4:

```
order 排序: [s1, s4, s2, s2b, ...] 
依赖约束: s4 需要 s1 + s2 → 但 s2 排在 s4 之后!
```

`next_pending()` 通过 `deps_met` 检查可以正确跳过，但 `progress()` 的线性迭代可能会给用户产生误导性顺序。建议在开发模式下增加一个验证断言:

```python
# Verify order respects deps
for sid in self._stage_order:
    for dep in deps.get(sid, []):
        assert self._stage_order.index(dep) < self._stage_order.index(sid), \
            f"Stage '{dep}' must run before '{sid}' per depends_on, but order field contradicts"
```

### 3.7 🟢 P2: `compute_params_hash` 的编码确定性风险

**位置**: `core/state_manager.py` 第 147-149 行

```python
serialized = json.dumps(args, sort_keys=True, ensure_ascii=False)
```

- `sort_keys=True` ✅ — 保证 key 顺序确定性
- `ensure_ascii=False` ⚠️ — 中文字符按 unescaped 原样输出，这在 CPython 3.x 中是稳定的，但不同 JSON 支持库可能产生不同输出
- `hashlib.sha256` ✅ — 确保同串同哈希

**风险**: 极低。仅当 args 含非 ASCII 值且 JSON 序列化器不同时可能出现。更安全的做法是使用 `ensure_ascii=True` 来保证所有字符都被 ASCII 转义。

---

## 4. 数据流断点清单

| ID | Stage | 类型 | 描述 | 触发条件 | 严重度 |
|----|-------|------|------|---------|--------|
| F-1 | s5_frame_generate | **缺失边** | `requires` 需要 s3b_four_views/，但 `depends_on` 缺 s3b_four_view | 部分重跑 `--from s3_character_image` 时 s5 在 s3b 之前启动 | **P0** |
| F-2 | s8_subtitles | **缺失边** | `requires` 需要 s4_shots.json，但 `depends_on` 缺 s4_shot_split | `check_requires` 运行时兜底捕获；但调度器可能在 s4 未完成时认为 s8 就绪 | **P2** |
| F-3 | 全图 | **无验证** | 依赖图无拓扑环检测 | 任何人在 pipeline.yaml 中引入环路（如误操作）→ mark_stale 无限循环 | **P1** |
| F-4 | 全图 | **静默吞没** | 未知的 dep name 被静默设为 state_id，永久不满足 | 录入笔误写错 `depends_on` stage ID | **P1** |
| F-5 | STAGE_DEPS | **硬编码偏差** | s9_tts_audio 硬编码 deps 缺少 s7_assemble；s2b 完全缺失于所有硬编码列表 | 旧代码导入 STAGE_DEPS 获得错误依赖图 | **P1** |
| F-6 | _LEGACY | **过时** | _LEGACY_STAGE_ORDER 缺 s2b (11 vs 12) | 旧代码通过 STAGE_ORDER 获取 stage 列表遗漏 s2b | **P2** |

---

## 5. `requires` vs `depends_on` 一致性矩阵

按 pipeline.yaml 逐 stage 验证:

| Stage ID | `requires` (Files) | `depends_on` (Stages) | 存在 ghost dep? | 存在缺失边? | 备注 |
|----------|-------------------|-----------------------|-----------------|-------------|------|
| s1_parse | source.txt | [] | — | — | 根节点 |
| s2_character_extract | s1_parsed.json | [s1_parse] | ❌ | ❌ | ✅ |
| s2b_wardrobe_extract | s2_characters.json | [s2_character_extract] | ❌ | ❌ | ✅ |
| s4_shot_split | s1_parsed.json, s2_characters.json | [s1_parse, s2_character_extract] | ❌ | ❌ | ✅ |
| s4b_keyframe_assets | s4_shots.json, s2_characters.json | [s4_shot_split, s2_character_extract] | ❌ | ❌ | ✅ |
| s3_character_image | s2_characters.json | [s2_character_extract] | ❌ | ❌ | ✅ |
| s3b_four_view | s3_character_refs/manifest.json | [s3_character_image] | ❌ | ❌ | ✅ |
| **s5_frame_generate** | s4b_keyframe_assets.json, s3_character_refs/, **s3b_four_views/** | [s3_character_image, s4_shot_split, s4b_keyframe_assets] | s4 为冗余边 | **s3b_four_view 缺失** 🔴 | 漏掉 s3b 是最严重的问题 |
| s6_video_generate | s5_frames/, s4b_keyframe_assets.json | [s5_frame_generate] | ❌ | ❌ | ✅ |
| s7_assemble | s6_videos/ | [s6_video_generate] | ❌ | ❌ | ✅ |
| **s8_subtitles** | s7_assembled.mp4, **s4_shots.json** | [s7_assemble] | ❌ | **s4_shot_split 缺失** 🟡 | ghost dep，但运行时有 check_requires 兜底 |
| s9_tts_audio | s7_assembled.mp4, s4_shots.json | [s7_assemble, s4_shot_split] | ❌ | ❌ | ✅ — 正确示例 |

---

## 6. 单一真相源审计: 谁真的在读取 pipeline.yaml？

| 组件 | 读取方式 | 使用 YAML? | 独立解析? | 与 pipeline.yaml 一致? | 备注 |
|------|---------|-----------|-----------|----------------------|------|
| `StateManager.load_pipeline_stages()` | `_load_yaml()` → `_build_stage_index()` | ✅ pyyaml / fallback | 是 | ✅ | 主 SST |
| `e2e_dry_run.py` `load_pipeline()` | 文件内 `parse_yaml_simple` / pyyaml | ✅ pyyaml / fallback | **是（独立实现）** | ⚠️ 功能等价但实现不同 | §6.1 |
| `parallel_executor.py` | 接收 `pipeline` dict 参数 | ❌ 不读文件 | 否 | ✅ 数据来自调用者 | 无风险 |
| 各 script (s3-s9) | `StateManager` 或直接硬编码 | ✅ 通过 SM | 否 | ✅ 推荐使用 SM | 依赖导入方 |

### 6.1 双 YAML 解析器对比

| 特性 | `state_manager._parse_yaml_simple()` | `e2e_dry_run.parse_yaml_simple()` |
|------|--------------------------------------|-----------------------------------|
| 行数 | 90 行 (L26-115) | 102 行 (L73-174) |
| 解析阶段 | 按缩进深度解析 (0→2→4→6 spaces) | 按缩进 + 关键词解析 (0→4→6 spaces) |
| 列表处理 | 跟踪 `in_list` 布尔标志 | 跟踪 `in_list` + `list_key` |
| Inline list `[a,b]` | ✅ 支持 | ❌ 不支持 |
| `vl_check_strategy` | ❌ 不解析 | ✅ 单独处理 |
| `depends_on` 解析 | 存入列表 | 存入列表 |
| 健壮性 | 对混合缩进敏感 | 对 `stripped.endswith(':')` 敏感 |

**风险**: 主路径 `pyyaml` 可用时两者不会产生差异。但回退路径下的不同解析策略可能在有边缘情况的 YAML (如混合缩进、空值字段) 下产生差异。

### 6.2 `core/__init__.py` 导出审查

```python
from core.state_manager import (
    StateManager, get_state_manager, compute_params_hash, migrate_v1_to_v2,
    STAGE_ORDER, STAGE_LABELS, STAGE_DEPS,  # ← 过时硬编码常量
)
```

**问题**: `STAGE_ORDER`, `STAGE_LABELS`, `STAGE_DEPS` 被导出为公共 API，但它们是硬编码的 `_LEGACY_*` 常量。任何使用 `from core import STAGE_DEPS` 的代码都绕过了 pipeline.yaml 单一真相源。

**建议**: 从 `__all__` 移除这三项，添加 deprecation warning，或改为指向 SM 的实例方法代理:

```python
# 替代方案: 动态代理
@property
def STAGE_ORDER(self):
    return get_state_manager().load_pipeline_stages()
```

---

## 7. 状态管理一致性审计

### 7.1 v1→v2 迁移

| 检查点 | 状态 | 备注 |
|--------|------|------|
| 填充所有 canonical stage 到 state | ✅ | `for sid in target_stages` 遍历 |
| 已有 v2 state 不做修改 | ✅ | `if version >= 2: return state` |
| v0 string 格式兼容 | ✅ | `if isinstance(entry, str): entry = {"status": entry}` |
| v2 字段 (checkpoint/params_hash/dirty) | ✅ | setdefault 处理缺失 |
| 迁移后写入磁盘 | ✅ | 调用者负责（从 `load()` 调用） |

**结论**: ✅ 无问题

### 7.2 `mark_stale()` 级联逻辑

| 检查点 | 状态 | 备注 |
|--------|------|------|
| 使用 `_stage_r_deps` (reverse deps) | ✅ | BFS 遍历 |
| 仅影响下游 (非所有后序 stage) | ✅ | 测试用例 `test_stale_isolates_unrelated_stages` 确认 |
| s4→s4b→s5→s6→s7→s8→s9 级联通 | ✅ | 测试 `test_stale_line_chain` 确认 |
| s8 通过 s7 间接级联到 s4 | ✅ | s4 → s4b → s5 → s6 → s7 → s8 |
| 已知环路上的行为 | ❌ | 无环检测，环路导致无限 BFS |

**结论**: ⚠️ 级联逻辑正确但依赖图无环检测

### 7.3 `record_checkpoint()` 类型安全

| 检查点 | 状态 | 备注 |
|--------|------|------|
| `shot_id` 类型 | ⚠️ 非强制 | 文档说 `int`，但未做类型检查 |
| `status` 值域 | ⚠️ 非强制 | 文档说 `"completed"|"failed"|"skipped"`，但在 set/del 操作中只有 completed/failed 被处理 |
| 幂等性 | ✅ | 重复 `record_checkpoint(same_shot, "completed")` 不重复添加 |
| `total_shots` 自动检测 | ⚠️ 有竞态风险 | `if total_shots == 0: total_shots = len(all_unique_shots)` — 如果两条记录并发写入，total_shots 可能不一致 |

**结论**: ✅ 功能正确但类型约束可加强

### 7.4 `compute_params_hash()` 确定性

| 检查点 | 状态 | 备注 |
|--------|------|------|
| 同一 dict 产生同一 hash | ✅ | `sort_keys=True` |
| 不同 dict 产生不同 hash | ✅ | 哈希雪崩保证 |
| 跨 Python 版本确定性 | ⚠️ | `ensure_ascii=False` 依赖 CPython json 行为 |
| 跨平台 (Windows/Linux) | ✅ | SHA256 与编码无关 |
| 短前缀格式 `sha256:...` | ✅ | 便于人类阅读和调试 |
| None 值处理 | ⚠️ | `json.dumps({"key": None})` 输出 `{"key": null}`，这可能是无意中的 — null 和 "None" 字符串区别对待 |

**结论**: ✅ 功能正确，但有微小跨平台风险 (P2)

---

## 8. 架构风险总评

### P0 (Critical — 立即修复)

| ID | 发现 | 模块 | 修复难度 | 推荐行动 |
|----|------|------|---------|---------|
| **F-1** | S5 `depends_on` 缺 `s3b_four_view` — 数据流断点 | `pipeline.yaml` | 1 行 | 加入 `s3b_four_view` 到 s5 的 depends_on |

### P1 (Important — 本 Sprint)

| ID | 发现 | 模块 | 修复难度 | 推荐行动 |
|----|------|------|---------|---------|
| **F-3** | 依赖图无拓扑环检测 | `state_manager.py` | 15 行 | 在 `_build_stage_index()` 增加 Kahn/DFS 循环检测 |
| **F-4** | 未知 dep 静默吞没 | `state_manager.py` | 2 行 | fallback 路径加 `logger.warning` |
| **F-5** | `STAGE_DEPS` 硬编码偏离 YAML | `state_manager.py` | 2 行 | 从 `__all__` 移除或加 deprecation warning |
| **Dual YAML** (✅-1) | 双 YAML 解析器分歧风险 | `state_manager.py` + `e2e_dry_run.py` | 30 行 | 提取公共 `core/yaml_parser.py` |

### P2 (Nice to have)

| ID | 发现 | 模块 | 修复难度 | 推荐行动 |
|----|------|------|---------|---------|
| **F-2** | S8 缺 s4 依赖 | `pipeline.yaml` | 1 行 | s8 depends_on 加入 s4_shot_split |
| **F-6** | `_LEGACY_STAGE_ORDER` 缺 s2b | `state_manager.py` | 1 行 | 加入 s2b_wardrobe_extract |
| **BLIND-6** | order 字段与 deps 无一致性校验 | `state_manager.py` | 10 行 | 断言 `order` 不违反 `depends_on` |
| **BLIND-7** | `compute_params_hash` 编码风险 | `state_manager.py` | 1 行 | `ensure_ascii=True` |

---

## 9. 审计结论

### 总体评级: ⚠️ 条件通过

```
                                                  ┌──────────────────────┐
                                                  │  Yes                 │
                    ┌── pipeline.yaml 是 SST? ──►  │  (12 stages from    │
                    │                             │   YAML, no hc path)  │
                    │                             └──────────────────────┘
                    │
评估树:             ├── Data flow 连续? ────────►  │  ⚠️ 2 个缺失边       │
                    │                             │  (P0: s5→s3b,        │
                    │                             │   P2: s8→s4)         │
                    │                             └──────────────────────┘
                    │
                    ├── Dep graph 无环? ──────────► │  ❌ 无环检测         │
                    │                             │  (P1: silent cycle)  │
                    │                             └──────────────────────┘
                    │
                    ├── SST 无分歧? ──────────────► │  ⚠️ 双 YAML 解析器  │
                    │                             │  (P1: divergence)    │
                    │                             └──────────────────────┘
                    │
                    └── 导出 API 一致? ──────────► │  ❌ STAGE_DEPS 偏差  │
                                                  │  (P1: s9 + s2b)     │
                                                  └──────────────────────┘
```

### 与 Claude 审计结论的差异

Claude 判定"Phase 1-4 标准化改造后无架构回归，数据流连续无断点"。

**我不同意**。尽管改造方向正确，但 s5→s3b 的缺失依赖边是一个真实的架构回归 — s5 在并行或部分重跑时会"准备好"但实际运行失败。Claude 关注了多余的 `s4` 边却漏掉了缺失的 `s3b` 边，这表明审计流程仍需交叉验证。

### 下一步行动建议

1. **立即**: 修复 `s5_frame_generate.depends_on` 加 `s3b_four_view` —— 1 行，风险最低
2. **本周**: 给 `_build_stage_index` 加拓扑环检测 + 未知 dep warning —— 防止未来静默问题
3. **本周**: 统一双 YAML 解析器为公共模块 —— 消除长期分歧风险
4. **可选**: 从 `core/__init__.py` 的 `__all__` 移除 `STAGE_ORDER/STAGE_LABELS/STAGE_DEPS`

---

*AtomCode L1 审计 • 2026-07-05 • 交叉验证 Claude L1 审计 (architecture_audit.md)*
