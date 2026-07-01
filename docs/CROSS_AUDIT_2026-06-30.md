# AIComicFactory 全链路审计报告

**日期**: 2026-06-30  
**方法**: 4 路并行子 agent 审计 + 主 agent 交叉验证  
**覆盖**: 架构、功能、Prompt、图像/视频技术、一致性（5 维度）

---

## 一、总分矩阵

| 维度 | AICF 评分 | vs AICB 对齐度 | 审计 agent | 风险等级 |
|------|-----------|----------------|-----------|---------|
| 架构 | 58/100 | — | audit-architecture | 🟡 |
| 功能 - P1 文本 | 85% | — | audit-features-prompts | 🟢 |
| 功能 - P2 图像 | 80% | — | audit-features-prompts | 🟡 |
| 功能 - P3 视频 | 75% | — | audit-features-prompts | 🔴 |
| 功能 - P4 集成 | 55% | — | audit-features-prompts | 🟡 |
| Prompt - P1 保真度 | 95-98% | ✅ 几乎完整 | audit-features-prompts | 🟢 |
| Prompt - P2 质量 | 70/100 | — | audit-features-prompts | 🟡 |
| 图像链路 (S3/S3b) | 55/100 | — | audit-tech | 🔴 |
| 帧生成 (S5) | 35/100 | — | audit-tech | 🔴 |
| 视频生成 (S6) | 60/100 | — | audit-tech | 🟡 |
| 合成 (S7) | 65/100 | — | audit-tech | 🟡 |
| TTS/字幕 (S8/S9) | 50/100 | — | audit-tech | 🟡 |
| 角色一致性 | 52/100 | 48% | audit-consistency-v2 | 🔴 |
| 场景一致性 | 30/100 | 30% | audit-consistency-v2 | 🔴 |
| 连续性检查 | partial | — | audit-consistency-v2 | 🟡 |
| 资管版本化 | partial | — | audit-consistency-v2 | 🟡 |

---

## 二、交叉验证发现的 5 个结构性问题

### 🔴 CRITICAL-1: S5 帧生成全线断裂（4/4 agent 独立发现）

**问题**: `scripts/s5_frame_generate.py` 的 `build_frame_prompt()` 是独立文本拼接函数，完全绕过了 `prompts/defaults/frame_generate_first.py` 的 `build_full_prompt()`。

**断裂链路**:
```
prompts/defaults/frame_generate_first.py ← 有 continuity_rules/reference_rules/previous_last_frame 等 slot
                      ↓  (从未被 S5 调用)
scripts/s5_frame_generate.py → build_frame_prompt() ← 自建函数，纯文本拼接
                      ↓
              ComfyUI (纯 T2I，无 IPAdapter，无参考图注入)
```

**影响的审计维度**: 架构(58分)、功能(80%→实际更低)、Prompt(标准化 prompt 被绕过)、技术(S5=35分)、一致性(一致性结构性缺陷)

**修复**: 一次重构（用 build_full_prompt() 替换 build_frame_prompt()）修复 3 个 gap（continuity_rules + reference_rules + previous_last_frame）

---

### 🔴 CRITICAL-2: 角色参考图有产出无使用（3/4 agent 独立发现）

**问题**: S3/S3b 产出的角色参考图（单视图+四视图）在 S5 完全不传给 ComfyUI——纯 T2I，无 IPAdapter，无 ControlNet，无 reference image。

**AICB vs AICF 差距**:
- AICB: img2img + IPAdapter，S3 角色参考图 → S5 作为 IPAdapter reference 输入
- AICF: 纯 T2I，prompt 中仅注入 visualAnchors **文本** 描述

**影响**: 角色一致性从「视觉锚定」降级为「文本描述匹配」，S3 生成的角色图形同虚设。

---

### 🔴 CRITICAL-3: S2 三个关键字段全链路无人消费（一致性审计发现）

**问题**: S2 character_extract 完整提取了 performanceStyle / colorPalette / relationships，但 S4 和 S5 都不消费。

| 字段 | S2 提取 | S4 消费 | S5 消费 | AICB 如何使用 |
|------|---------|---------|---------|--------------|
| performanceStyle | ✅ | ❌ | ❌ | 注入 motionScript 生成标志性动作 |
| colorPalette | ✅ | ❌ | ❌ | 注入 frame prompt 后缀保持配色一致 |
| relationships | ✅ | ❌ | ❌ | 注入 shot_split 控制多角色站位/视线 |

---

### 🟡 MAJOR-4: video_generate prompt 极简（2/4 agent 发现）

**问题**: video_generate 仅 3 个 slot（interpolation_header/dialogue_format/frame_anchors），而 AICB 的 Seedance Keyframe prompt 包含详细运动约束。

**影响**: FLF2V 生成时缺乏角色动作/环境动态/镜头运动/物理规律四层交织的运动描述，视频质量不稳定。

---

### 🟡 MAJOR-5: continuity_check 已实现但未集成（一致性审计发现）

**问题**: `continuity_check.py` 完整实现了 4 维 VL 评分，但管线中没有任何 stage 自动调用。S5→S6 之间无质量闸门。

**修复**: S5 完成后自动触发 check_project()，低于阈值(70)自动重生成（最多 3 次）。

---

## 三、下一步行动计划（按优先级排序）

### Phase 1: 止血（P0，2-3 天）

| # | 任务 | 工时 | 影响维度 | 类型 |
|---|------|------|---------|------|
| P0-1 | **S5 调用链重构**：用 frame_generate_first/last.build_full_prompt() 替换 build_frame_prompt() | 4h | 一致性+Prompt+功能 | 必须开发 |
| P0-2 | **S5 ComfyUI workflow 升级**：纯 T2I → img2img + IPAdapter，S3 参考图作为 IPAdapter 输入 | 8h | 一致性+技术 | 必须开发 |
| P0-3 | **S2→S4 消费链补全**：shot_split 注入 relationships/performanceStyle | 2h | 一致性 | 必须适配 |
| P0-4 | **S2→S5 消费链补全**：frame prompt 注入 colorPalette/performanceStyle | 2h | 一致性 | 必须适配 |
| P0-5 | **video_generate prompt 扩展**：3 slot → 6-7 slot（motion_constraints + duration_timing + safe_zone） | 3h | Prompt | 必须从 AICB 移植 |
| P0-6 | **s4_shots.json 增加 startRatio/endRatio**：shot_split output_format 补字段 + S8/S9 消费 | 3h | 功能+Prompt | 必须从 AICB 移植 |

### Phase 2: 加固（P1，3-5 天）

| # | 任务 | 工时 | 类型 |
|---|------|------|------|
| P1-1 | **continuity_check 管线集成**：S5完成后自动触发 + 低于阈值重试循环 | 4h | 必须适配 |
| P1-2 | **S7 BGM 叠加**：--bgm 参数 + FFmpeg amix 混音 | 3h | 必须从 AICB 移植 |
| P1-3 | **provider_config.py**：按 stage 配置 LLM/图像/视频 provider | 8h | 必须开发 |
| P1-4 | **StateManager 重试机制**：max_retries=3 + backoff=30s + 超时 10min | 4h | 必须开发 |
| P1-5 | **video_quality_check 模块**：LLM vision 评分 + severity 分级 | 4h | 必须从 AICB 移植 |
| P1-6 | **asset_manager 安全化**：cleanup_old=False + restore_version() API | 2h | 必须适配 |

### Phase 3: 扩展（P2，按需推进）

| # | 任务 | 类型 |
|---|------|------|
| P2-1 | **Episode 层级管理**：projects/{project}/episodes/{ep}/ 目录 + state.json episode 级追踪 | 必须开发 |
| P2-2 | **S6 Reference 模式**：ComfyUI 多参考图视频生成节点调研+集成 | 必须开发 |
| P2-3 | **OpenClaw Skill 正式注册**：通过 skill_workshop 注册 SKILL.md | 必须开发 |
| P2-4 | **S3 分辨率提升**：1024→1536+（角色面部细节） | 必须适配 |
| P2-5 | **S9 TTS voice_map LLM 化**：动态角色-声音匹配替代硬编码 dict | 必须开发 |
| P2-6 | **多 GPU/shot 级并行调度** | 必须开发 |

---

## 四、必须从 AICB 直接移植

| 资产 | 优先级 | 移植方式 | 说明 |
|------|--------|---------|------|
| video_generate motion_constraints slot | P0 | 逐字移植 | 角色/环境/镜头/物理四层交织的运动描述规则 |
| dialogue.startRatio/endRatio schema | P0 | 字段移植 | shot_split output_format + S8/S9 计算逻辑 |
| BGM 叠加逻辑 | P1 | 逻辑移植 | s7_video_assemble.py 增加 amix 混音 |
| video_quality_check LLM vision prompt | P1 | 逐字移植 | 0-100 评分 + severity 分级 |
| PromptPreset 数据结构 | P1 | 概念移植 | slot 覆盖组定义 |
| continuity_rules/reference_rules slot 文字 | P0 | 已有文字，需调用 | frame_generate_first.py 中已存在但未使用 |
| 角色四视图 2560×1440 layout prompt | P2 | 逐字移植 | 当前 S3+S3b 两步方案非一步四视图 |
| character_image prompt 完整内容 | P1 | 已有文件，需调用 | prompts/defaults/ 中存在但 S3 脚本未用 |

---

## 五、必须本地适配

| 项目 | 原因 |
|------|------|
| IPAdapter 集成 → ComfyUI IPAdapter Apply 节点 | AICB 用云端 API，AICF 本地 ComfyUI 需不同实现 |
| colorPalette/景深映射 → ComfyUI T2I prompt 语法 | AICB 用 DALL-E/Imagen，AICF 用 SDXL/Flux |
| continuity_check → 从手动 CLI 改为管线自动触发 | 代码已实现，需改调用方式 |
| Reference 模式 → ComfyUI 替代节点 | AICB 用 Seedance API，AICF 需 ComfyUI 生态方案 |
| Episode 层级 → projects/ 文件结构调整 | AICB 用关系型 DB |
| S3→S3b 自动化串联 | AICB 单步完成，AICF 需两步编排 |

---

## 六、P0 执行摘要（一句话定性）

**AICF 最大的问题不是「缺什么」，而是「有但没用」**：

- ✅ 有 prompt 系统 → S5 绕过去了
- ✅ 有角色参考图 → S5 没用
- ✅ 有 performanceStyle/colorPalette/relationships → 全链路无人消费
- ✅ 有连续性检查器 → 管线没集成

**一个重构修复三个问题**：让 S5 走 prompts/defaults/frame_generate_first.py 的 build_full_prompt()，一次性接通 continuity_rules + reference_rules + previous_last_frame + colorPalette + performanceStyle 五条断裂链路。

**一个升级解决核心矛盾**：S5 从纯 T2I → img2img+IPAdapter，把 S3 的角色参考图真正用作视觉锚定输入，结束「有图不用」的荒诞局面。

---

## 附：审计 agent 调用记录

| agent | 模型 | 状态 | tokens | 产出 |
|-------|------|------|--------|------|
| audit-architecture | glm-5.1 | ✅ | 31k | 架构评分 58/100，12 gaps |
| audit-tech | glm-5.1 | ✅ | 61k | S3=55, S5=35, S6=60, S7=65, S8=50 |
| audit-features-prompts | deepseek-v4-pro | ✅ | 117k | P1=85%, P2=80%, P3=75%, P4=55%; Prompt P1=95-98% |
| audit-consistency-v2 | deepseek-v4-pro | ✅ | 78k | 一致性 48%, 7 risks |
| audit-features | glm-5.1 | ❌ rate limit | — | — |
| audit-prompts | glm-5.1 | ❌ rate limit | — | — |
| audit-consistency | glm-5.1 | ❌ rate limit | — | — |