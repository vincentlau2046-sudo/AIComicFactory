# AICF 审计日志

> 合并自: `docs/CROSS_AUDIT_2026-06-30.md`、`AUDIT_REPORT.md`、`projects/last_bento/AUDIT_REPORT.md`
> 按时间正序排列，后续审计直接追加

---

## 2026-06-30 跨角色审查

**方法**: 4 路并行子 agent 审计 + 主 agent 交叉验证
**覆盖**: 架构、功能、Prompt、图像/视频技术、一致性（5 维度）

### 总分矩阵

| 维度 | AICF 评分 | vs AICB 对齐度 | 风险等级 |
|------|-----------|----------------|---------|
| 架构 | 58/100 | — | 🟡 |
| 功能 - P1 文本 | 85% | — | 🟢 |
| 功能 - P2 图像 | 80% | — | 🟡 |
| 功能 - P3 视频 | 75% | — | 🔴 |
| 功能 - P4 集成 | 55% | — | 🟡 |
| Prompt - P1 保真度 | 95-98% | ✅ 几乎完整 | 🟢 |
| Prompt - P2 质量 | 70/100 | — | 🟡 |
| 图像链路 (S3/S3b) | 55/100 | — | 🔴 |
| 帧生成 (S5) | 35/100 | — | 🔴 |
| 视频生成 (S6) | 60/100 | — | 🟡 |
| 合成 (S7) | 65/100 | — | 🟡 |
| TTS/字幕 (S8/S9) | 50/100 | — | 🟡 |
| 角色一致性 | 52/100 | 48% | 🔴 |
| 场景一致性 | 30/100 | 30% | 🔴 |
| 连续性检查 | partial | — | 🟡 |
| 资管版本化 | partial | — | 🟡 |

### 5 个结构性问题

**CRITICAL-1: S5 帧生成全线断裂** — `build_frame_prompt()` 绕过 `prompts/defaults/frame_generate_first.py` 的 `build_full_prompt()`，3 个 gap（continuity_rules + reference_rules + previous_last_frame）

**CRITICAL-2: 角色参考图有产出无使用** — S3 参考图在 S5 纯 T2I 中完全不传给 ComfyUI

**CRITICAL-3: S2 三个关键字段全链路无人消费** — performanceStyle/colorPalette/relationships 从 S2 到 S4/S5 无人消费

**MAJOR-4: video_generate prompt 极简** — 仅 3 slot vs AICB 的详细运动约束

**MAJOR-5: continuity_check 已实现但未集成** — 管线中没有任何 stage 自动调用

### 下一步行动计划

| 阶段 | 内容 | 工时 |
|------|------|------|
| Phase 1: 止血 (P0) | S5 调用链重构 + ComfyUI workflow 升级 + S2→S4/S5 消费链 + video_generate prompt 扩展 + s4 startRatio/endRatio | 22h |
| Phase 2: 加固 (P1) | continuity_check 集成 + BGM + provider_config + StateManager 重试 + quality_check + asset_manager 安全 | 25h |
| Phase 3: 扩展 (P2) | Episode 管理 + Reference 视频 + OpenClaw Skill + 分辨率提升 + TTS voice_map + 多 GPU | 按需 |

---

## 2026-07-01 系统审计（根目录）

**审计范围**: last_bento 端到端生成 (2026-06-30 夜间 ~ 07-01 凌晨)

### 审计总览

| 维度 | 评分 | 说明 |
|------|------|------|
| 架构一致性 | 7/10 | Pipeline 拓扑对齐 AICB，但数据流有多处断裂 |
| 流程调用 | 5/10 | S3/S5 质检形同虚设，S6 双写 bug，S7→S9 链路有设计冲突 |
| 功能完整性 | 6/10 | 12 prompt + 7 转场 + 版本化资管已到位，但关键质检闭环未通 |
| 脚本质量 | 6/10 | 大量代码可用但有 bug/冗余，多处硬编码和不一致 |
| 产出质量 | 4/10 | S3 VL 质检全部 Connection refused，S5/S6 无有效质检输出 |

### 跨 Stage 架构问题

**3.1 质检闭环未通 (P0)**: 生成→质检→❌不触发重生成
**3.2 S6 双写 Bug (P0)**: 每个视频写两份到同一目录
**3.3 Workflow 模板未使用 (P1)**: Python 硬编码 vs templates/ 模板
**3.4 S8/S9 字幕链路冲突 (P1)**: 两套独立字幕系统，时间轴计算不同
**3.5 数据流不一致 (P1)**: 多个 stage 各自独立解析，无共享时间轴
**3.6 S5 IPAdapter 链路未验证 (P2)**: 默认 --gen t2i，IPAdapter 代码未实际跑通

### 改进计划

| Phase | 任务 | 工时 |
|-------|------|------|
| A (P0) | S6 双写修复 + S3 VL 质检闭环 + S5/S6 VL 质检闭环 + S3 年龄正则修复 | 5h |
| B (P1) | Workflow 模板统一 + S8/S9 字幕链路合并 + 共享时间轴 + S3b→S5 链路 + asset_manager 消费 | 11h |
| C (P2) | S3 prompt 公共逻辑提取 + S9 时间轴优化 + VL 后端生命周期 + e2e 验证脚本 | 6h |

---

## 2026-07-01 项目审计（last_bento）

**项目**: 《最后的便当》
**总耗时**: ~75 分钟 (22:07 - 23:25)

### 执行摘要

| Stage | 状态 | 耗时 | 产出 |
|-------|------|------|------|
| S1: script_parse | ✅ | ~3min | 3 scenes, 7 dialogues |
| S2: character_extract | ✅ | ~1min | 3 characters + 3 relationships |
| S3: character_image | ✅ | ~7min | 3/3 参考图 (1.8MB, concept 风格) |
| S4: shot_split | ✅ | ~2min | 16 shots |
| S5: frame_generate | ✅ | ~8min | 32/32 帧 (51MB, IPAdapter 模式) |
| S6: video_generate | ✅ | ~54min | 16/16 视频 (86MB, FLF2V+Lightx2v+TeaCache) |
| S7: video_assemble | ✅ | ~1min | 47.3MB, 84.3s, xfade 转场 |
| S8: subtitles | ✅ | <1min | SRT+ASS (7 dialogues) |
| S9: TTS+ASR | ✅ | ~4min | 44.8MB, 88.5s |

### 已修复 Bug

| # | Stage | 问题 | 修复 |
|---|-------|------|------|
| 1 | S5 | `IndexError: list index out of range` — 无角色镜头走 IPAdapter 路径空引用 | 增加 fallback: not ref_images → T2I |
| 2 | S7 | xfade offset 计算错误 → 16 shots (85s) 组装后仅 8.5s | 重写 offset 算法 |
| 3 | S7 | `SyntaxError: name 'W' is used prior to global declaration` | 硬编码 default=1280/720 |
| 4 | S6 | Python stdout 完全缓冲 | 加 `sys.stdout.reconfigure(line_buffering=True)` |

### 待办事项

| 优先级 | 事项 | 说明 |
|--------|------|------|
| P0 | S6 输出缓冲 | 已修复 |
| P0 | S5 多角色 IPAdapter | Batch Images 或多参考图 concat |
| P1 | 视频时长与分镜时长对齐 | FLF2V 帧数 vs duration 字段 |
| P1 | VL 质检集成 | S3/S5 启动 qw35-9b 后端 |
| P2 | S7 标题卡 CJK 字体检测 + 自动 fallback | |
| P2 | S4 prompt 统一中/英文 | AICB 规范确认 |