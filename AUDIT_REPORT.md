# AIComicFactory 端到端审计报告

**审计日期**: 2026-07-01
**审计范围**: last_bento 端到端生成 (2026-06-30 夜间 ~ 07-01 凌晨)
**审计基准**: AICB (AIComicBuilder) 成熟方案
**审计人**: Nova

---

## 一、审计总览

| 维度 | 评分 | 说明 |
|------|------|------|
| 架构一致性 | **7/10** | Pipeline 拓扑对齐 AICB，但数据流有多处断裂 |
| 流程调用 | **5/10** | S3/S5 质检形同虚设，S6 双写 bug，S7→S9 链路有设计冲突 |
| 功能完整性 | **6/10** | 12 prompt + 7 转场 + 版本化资管已到位，但关键质检闭环未通 |
| 脚本质量 | **6/10** | 大量代码可用但有 bug/冗余，多处硬编码和不一致 |
| 产出质量 | **4/10** | S3 VL 质检全部 Connection refused，S5/S6 无有效质检输出 |

**核心问题**: 管线骨架已通，但「生成→质检→重生成」闭环没有真正跑通。

---

## 二、逐 Stage 审计

### S3: 角色参考图生成

| 项目 | 状态 | 说明 |
|------|------|------|
| T2I 生成 | ✅ 正常 | 3/3 角色图生成成功 |
| VL 质检 | ❌ **失效** | 3 个角色全部 `Connection refused` (qw35-9b 未启动) |
| 质检→重生成闭环 | ❌ **缺失** | 即使质检失败也不会触发重生成 |
| prompt 构建 | ⚠️ 可改进 | 年龄关键词匹配用 `any(k in combined_text for k in kw)` 但列表含正则 `"6[0-9]岁"` 不会被正确匹配 |
| checkpoint 映射 | ⚠️ 不一致 | `vivid` 映射到 `animexl_xuebiMIX_v60.safetensors`，但 MEMORY.md 记录为 `animexl_xuebiMIX_v40.safetensors` |
| workflow 构建 | ⚠️ 硬编码 | workflow JSON 在 Python 代码中硬编码，而非从 `templates/t2i_character_ref.json` 加载 |

**Bug**: `_build_vivid_prompt` 和 `_build_classic_prompt` 有完全重复的年龄判断+性别判断逻辑（~40行），应提取为公共函数。

### S3b: 四视图扩展

| 项目 | 状态 | 说明 |
|------|------|------|
| state.json | ❌ **pending** | S3b 未在 last_bento 中执行 |
| Qwen Edit 节点 | ✅ 已验证 | 原生节点可用 |

### S5: 关键帧生成

| 项目 | 状态 | 说明 |
|------|------|------|
| 首尾帧生成 | ✅ 24/24 帧 | 12 shots × 2 帧 |
| IPAdapter 模式 | ⚠️ 未实际使用 | 默认 `--gen t2i`，IPAdapter 链路未验证 |
| 连续性检查 | ❌ **未执行** | Post-S5 质检代码存在但依赖 qw35-9b VL，运行时必然失败 |
| 帧质量检查 | ❌ **未执行** | 同上 |
| 前帧链式传递 | ⚠️ 仅 T2I 模式 | `prev_last` 传递给了 `build_first_prompt()` 但 T2I 模式不用它 |
| 暗帧重试 | ✅ | brightness < 5.0 自动重试 |

**关键缺陷**: S5 的质检代码 (`continuity_check` + `video_quality_check`) 在 `--no-check` 未设置时会自动触发，但如果 qw35-9b 没启动，只打印 `⚠️ ... failed` 然后跳过，不阻塞也不重试。这不是「质检」，是「装饰」。

### S6: FLF2V 视频渲染

| 项目 | 状态 | 说明 |
|------|------|------|
| FLF2V 渲染 | ✅ 12/12 视频生成 | |
| Lightx2v + TeaCache | ✅ | 4-step 加速生效 |
| **双写 Bug** | ❌ **严重** | 每个视频输出两份：`s01.mp4` + `shot_001_keyframe_video_v1.mp4`，完全相同内容 |
| 分段渲染 | ✅ | >5s 自动分段+中帧生成+拼接 |
| buildVideoPrompt | ✅ | 7-slot AICB 对齐 |
| Workflow 模板 | ❌ 未使用 | 硬编码在 Python 中，不读 `templates/flf2v_keyframe.json` |

**双写 Bug 根因分析**:

```python
# Path A (line 279-280):
dest = videos_dir / f"s{sn:02d}.mp4"
shutil.copy2(str(candidates[0]), str(dest))   # ← 写入 s01.mp4

# Path A (line 286-293):
am.register(
    project=args.project,
    asset_type="keyframe_video",
    shot_id=f"shot_{sn:03d}",
    source_path=candidates[0],   # ← 再次以 candidates[0] 为源
    relative_dir="s6_videos",    # ← 同一目录
    # dest_name 未指定! → am.register 使用默认命名:
    # shot_001_keyframe_video_v1.mp4
    # 并且 am.register 内部也会 shutil.copy2 !
)
```

**修复方案**: 去掉 `shutil.copy2` 那行，只靠 `am.register` 写入文件，并传入 `dest_name=f"s{sn:02d}.mp4"` 确保下游 S7 按约定路径找到文件。

**额外问题**: Path D (分段渲染) 也有同样的双写——line 348 `concat_segments(segments, dest)` 写入 `s{sn:02d}.mp4`，然后 line 354 `am.register(source_path=dest, ...)` 又写入 `shot_00X_keyframe_video_v1.mp4`。分段场景的 `am.register` 以 `dest`（已经是项目目录内的文件）为 source，会导致 `shutil.copy2` 同目录内复制。

### S7: 视频组装

| 项目 | 状态 | 说明 |
|------|------|------|
| xfade 转场 | ⚠️ 未验证 | last_bento 无转场数据（全 cut），xfade 代码未实际触发 |
| 标题卡/结束卡 | ✅ | drawtext 生成 |
| SRT 生成 | ✅ | startRatio/endRatio 支持 |
| BGM 混合 | ⚠️ 未验证 | `--bgm` 参数未传入 |
| S7→S9 重复 | ❌ **设计冲突** | S7 可选烧录字幕 (`--with-subtitles`)，S9 也烧录 ASS 字幕。两次烧录无协调 |

**设计问题**: S7 的 `assemble_video()` 是完整 AICB 移植（含字幕+BGM），但本地流程中 S8+S9 负责精修字幕+TTS。应该让 S7 只做「转场+标题卡」不碰字幕，S9 才烧录最终字幕。目前 `--with-subtitles` 默认关闭，但代码逻辑冗余。

### S8: SRT 字幕生成

| 项目 | 状态 | 说明 |
|------|------|------|
| SRT 输出 | ✅ | 7 条对话 → SRT |
| startRatio/endRatio | ⚠️ 无数据 | s4_shots.json 的 dialogues 无 startRatio/endRatio，回退 auto-distribute |
| 与 S9 重复 | ❌ | S8 生成 SRT，S9 生成 ASS——两种字幕格式共存但互不关联 |

**问题**: S8 和 S9 的时间轴计算逻辑不同。S8 用 `title_offset` (默认 3s)，S9 用实际视频 `ffprobe` 时长。当 S7 加了标题卡后，S8 的 `title_offset` 与实际不对齐。

### S9: TTS + 成片

| 项目 | 状态 | 说明 |
|------|------|------|
| TTS 生成 | ✅ | 7 条对话 → FLAC |
| 时间轴构建 | ⚠️ 有偏移 | `calc_dialogue_timeline()` 用 s4 的 duration 累加，不含标题卡偏移 |
| 2-input amix 链 | ⚠️ 效率低 | N 条对话 = N 次 ffmpeg 调用，串行叠加 |
| ASS 字幕 | ⚠️ 时间轴不同 | S9 的 ASS 时间轴与 S8 的 SRT 时间轴计算方式不同 |
| 最终成片 | ✅ | s9_final.mp4 输出正常 |

---

## 三、跨 Stage 架构问题

### 3.1 质检闭环未通 (P0 优先级)

```
生成 → 质检 → [不通过] → 重生成
      ↑                      │
      └──────────────────────┘
```

当前状态：
- S3: `CharacterImageChecker.check()` → VL 调用失败 → 打印 ⚠️ → **不触发重生成**
- S5: `ContinuityChecker.check_project()` → VL 调用失败 → 打印 ⚠️ → **不触发重生成**
- S5: `VideoQualityChecker.check_project()` → VL 调用失败 → 打印 ⚠️ → **不触发重生成**
- S6: **完全没有质检**

**结论**: 质检代码 100% 是死代码——在 VL 模型未启动时静默失败，在 VL 模型启动时仅打分不行动。需要：
1. 启动 qw35-9b 作为质检后端
2. 质检失败时自动重试（最多 N 次）
3. 重试仍失败时写入 state.json.errors 并暂停

### 3.2 S6 双写 Bug (P0 优先级)

每个视频写两份到同一目录，浪费存储且让下游困惑应读哪个文件。S7 读的是 `s{sn:02d}.mp4`，而 `shot_00X_keyframe_video_v1.mp4` 纯粹是 `am.register` 的副作用。

### 3.3 Workflow 模板未使用 (P1)

`templates/` 下有 4 个 JSON 模板文件，但所有脚本都在 Python 中硬编码 workflow dict。模板文件形同虚设。

**影响**: 
- 修改 workflow 需要改 Python 代码而非编辑 JSON
- 模板与实际执行不一致，无法保证模板是最新

### 3.4 S8/S9 字幕链路冲突 (P1)

- S8 生成 SRT（给 S7 用，但 S7 默认不烧录）
- S9 生成 ASS + 最终成片
- 两者时间轴计算方式不同
- S8 的存在意义模糊——如果 S9 负责最终字幕，S8 只需生成中间文件供 S9 参考

### 3.5 数据流不一致 (P1)

| 数据 | 消费者 | 问题 |
|------|--------|------|
| s4_shots.json dialogues | S7, S8, S9 | 三个 stage 各自独立解析，无共享时间轴 |
| s6_videos | S7 | S7 只认 `s{sn:02d}.mp4`，不读 assets.json |
| s7_assembled.mp4 | S9 | 硬编码文件名 |
| assets.json | 无人消费 | 资管系统写入但无下游读取 |

### 3.6 S5 IPAdapter 链路未验证 (P2)

默认 `--gen t2i`，IPAdapter 模式代码存在但从未实际跑通：
- `build_ipadapter_workflow()` 构建了 IPAdapter 节点但未验证 ComfyUI 是否有对应插件
- `_find_character_ref_images()` 查找 S3b 四视图但 S3b 在 last_bento 未执行
- 缺少 IPAdapter model 文件检查

---

## 四、与 AICB 差距矩阵（更新版）

| 维度 | AICB 能力 | AICF 当前 | 差距等级 |
|------|-----------|----------|---------|
| 质检闭环 | vision→评分→不通过→重生成 | vision→评分→静默失败 | 🔴 P0 |
| S6 资管 | 单一输出路径 | 双写 bug | 🔴 P0 |
| Workflow 模板 | 外部 JSON，可编辑 | Python 硬编码 | 🟡 P1 |
| S8/S9 协调 | 统一字幕管线 | 两套独立字幕系统 | 🟡 P1 |
| S3b → S5 链路 | 四视图→IPAdapter | 未跑通 | 🟡 P1 |
| startRatio/endRatio | S4 自动生成 | 缺失 | 🟡 P1 |
| VL 后端可用性 | 云端多模态 API | 本地 qw35-9b (未自动启停) | 🟡 P1 |
| asset_manager 消费 | 下游读 active 版本 | 只写不读 | 🟢 P2 |
| Reference 视频模式 | Seedance 2.0 | 未实现 (D2 决策) | ⚪ Deferred |
| Episode 多集管理 | Project/Episode 两级 | 单 project | ⚪ Deferred |

---

## 五、改进计划

### Phase A: P0 修复（预估 1 天）

| # | 任务 | 改动 | 预估 |
|---|------|------|------|
| A1 | **S6 双写修复** | 去掉 `shutil.copy2`，只靠 `am.register(dest_name=f"s{sn:02d}.mp4")` 写入；Path D 同理 | 0.5h |
| A2 | **S3 VL 质检闭环** | 1) 检测 qw35-9b 可用性，不可用时自动 `edge-llm switch qwen35-9b` 启动<br>2) 质检不通过 → 自动重生成（最多 2 次）<br>3) 2 次仍不通过 → 写 error 到 state.json | 2h |
| A3 | **S5/S6 VL 质检闭环** | 1) S5 后自动触发 continuity + quality check<br>2) quality < 阈值 → 标记 shot 为 needs_regen<br>3) S6 后无 VL 质检（视频质量由 S5 帧质量间接保证） | 2h |
| A4 | **S3 年龄正则修复** | `"6[0-9]岁"` → 用 `re.search()` 替代 `in` 判断 | 0.5h |

### Phase B: P1 架构改进（预估 1.5 天）

| # | 任务 | 改动 | 预估 |
|---|------|------|------|
| B1 | **Workflow 模板统一** | 所有脚本从 `templates/` 加载 JSON，Python 中只做参数注入 | 3h |
| B2 | **S8/S9 字幕链路合并** | 删除 S8 独立 SRT 生成，S9 统一负责 ASS+SRT<br>S7 `--with-subtitles` 改为从 S9 取字幕 | 2h |
| B3 | **共享时间轴计算** | 提取 `core/timeline.py`，S7/S8/S9 共用同一时间轴逻辑<br>含标题卡偏移、xfade 重叠修正 | 3h |
| B4 | **S3b → S5 自动链路** | S3 完成后自动检测 qw35-9b 可用性 → 执行 S3b → S5 默认启用 IPAdapter | 2h |
| B5 | **asset_manager 下游消费** | S7 读 assets.json 获取 active video 路径而非硬编码 `s{sn:02d}.mp4` | 1h |

### Phase C: P2 质量提升（预估 1 天）

| # | 任务 | 改动 | 预估 |
|---|------|------|------|
| C1 | **S3 prompt 公共逻辑提取** | 年龄+性别判断提取为 `_infer_demographics()` | 1h |
| C2 | **S9 时间轴优化** | `calc_dialogue_timeline()` 加入标题卡偏移参数 | 1h |
| C3 | **VL 后端生命周期管理** | `core/vl_backend.py`: 检测→启停→健康检查 | 2h |
| C4 | **e2e 端到端验证脚本** | 全链路跑通 + 质检闭环 + 断言验证 | 2h |

### 总预估: 3.5 天

---

## 六、立即行动项

以下改动可在今晚完成：

1. **A1: S6 双写修复** — 最高优先级，5 分钟可修
2. **A4: S3 年龄正则** — 小修，防止年龄判断失效
3. **清理 last_bento/s6_videos 中的重复文件** — 磁盘清理

---

*审计完成。请 Vincent 确认改进计划优先级和执行顺序。*
