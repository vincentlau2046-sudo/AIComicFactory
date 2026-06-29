# AIComicFactory — 实施进度

**创建日期**: 2026-06-28
**当前状态**: ✅ 全链路可运行,last_bento 已验证通过

---

## 主要变更

| 日期 | 变更 |
|------|------|
| 2026-06-28 | 初始规划 |
| 2026-06-28 | D3/D4 决策: LLM 改用 baidu-codingplan，prompt 不需精简 |
| 2026-06-28 | Phase 1 骨架完成: 3 个 prompt + state manager + prompt runner + SKILL.md |
| 2026-06-28 夜间 | 全链路跑通: last_bento 端到端 (S1-S8), IPAdapter v3 角色参考图, FLF2V CLIPVision 修复, Qwen3-TTS 集成 |
| 2026-06-29 凌晨 | 从零重跑: 修复 S5 尾帧缺失, S6 Wan 节点 schema 适配, S7/S8 脚本正式化, D方案(FLF2V 自动分段), S9 TTS-ASR 对齐管线 |

---

## Phase 1: 骨架 + 文本链路 ✅ 完成

- [x] 创建目录结构
- [x] `core/state_manager.py` — 管线状态管理（断点续跑、依赖检查、进度汇报）
- [x] `core/prompt_runner.py` — prompt 构建器（LLM 调用由 OpenClaw 完成）
- [x] `prompts/_base.py` — 基类 (PromptDefinition, PromptSlot, slot, resolve)
- [x] `prompts/registry.py` — 插槽化 prompt 注册表（3 prompts）
- [x] `prompts/defaults/` — 移植 3 个 P1 prompt 原样（不需精简）
  - [x] script_parse (3135 chars, 5 slots)
  - [x] character_extract (6533 chars, 7 slots)
  - [x] shot_split (3589 chars, 9 slots)
- [x] `SKILL.md` — S1/S2/S4 接口定义（OpenClaw LLM 直接调用）
- [x] 端到端文本测试: last_bento 原始剧本 → s1 → s2 → s4 ✅

## Phase 2: 图像链路 ✅ 完成

- [x] `core/comfyui_session.py` — WF 继承 (prompt_id 隔离 + WebSocket)
- [x] `scripts/s3_character_image.py` — T2I 角色参考图
- [x] `scripts/s5_frame_generate.py` — 首尾帧生成 (--mode both)
- [x] `core/asset_manager.py` — ShotAsset 版本化 ✅
- [x] `templates/t2i_character_ref.json` — ComfyUI workflow ✅
- [x] `templates/qwen_edit_frame.json` — ComfyUI workflow ✅
- [x] `templates/flf2v_keyframe.json` — ComfyUI workflow ✅
- [x] 端到端测试: s1 → s2 → s3 → s4 → s5 ✅

## Phase 3: 视频 + 合成链路 ✅ 完成

- [x] `scripts/s6_flf2v_render.py` — FLF2V keyframe (Wan2.2 + Lightx2v + TeaCache) + >5s 自动分段
- [x] `scripts/s7_video_assemble.py` — FFmpeg 标题卡+拼接+结束卡
- [x] `scripts/s8_subtitles.py` — ASS 字幕时间轴+烧录 (无 TTS 对齐)
- [x] `scripts/s9_tts_audio.py` — Qwen3-TTS + Whisper ASR 对齐 + 音视频合轨
- [ ] `templates/flf2v_keyframe.json` — ComfyUI workflow (待导出)
- [x] `core/prompt_runner.py` — prompt 构建器（LLM 调用由 OpenClaw 完成）
- [x] 端到端测试: 全链路 last_bento ✅

## Phase 4: OpenClaw 集成 + 调优 (进行中)

- [ ] SKILL.md 注册为 OpenClaw Skill
- [ ] state.json 断点续跑验证
- [ ] 多项目管理 (ep_002)
- [ ] prompt 调优 + 质量评估
- [ ] continuity_check.py 实现

---

## AICB 差距审核 + 补齐计划 (2026-06-29)

**审核结论**: 整体符合度 75%，管线骨架已通，缺口集中在「数据模型精度」和「质量保障闭环」。

### 差距矩阵

| 维度 | AICB 能力 | AIComicFactory | 差距 |
|------|-----------|----------------|------|
| Prompt Registry | 12 个 prompt + slot 覆盖 | 3 个 P1 prompt | ⚠️ 缺 9 个 |
| 数据模型 | 10+ 实体 (Project/Episode/Scene/Shot/ShotAsset/Character/CharacterCostume/CharacterRelation/Dialogue/ShotAction/MoodBoardImage) | s1-s9 JSON 文件 | ⚠️ 缺多个实体 |
| 角色管理 | identity/style 分离 + visualHint + performanceStyle + 关系网络 + 服装层 | description + visualHint | ⚠️ 缺关系/服装/姿态分层 |
| 版本化资管 | ShotAsset 版本表 (每次重生成插入新行，旧行 is_active=0) | 目录结构，覆盖式生成 | ❌ 缺失 |
| 连续性检查 | LLM vision 比对相邻帧 | 无 | ❌ 缺失 |
| 质量检查 | LLM vision 评分 0-100 | 无 | ❌ 缺失 |
| 视频生成模式 | Keyframe + Reference 双模式 | 仅 Keyframe | ⚠️ 可扩展 |
| 转场效果 | 7 种 (cut/dissolve/fade_in/fade_out/wipeleft/slideright/circleopen) | 基础 concat | ⚠️ 需补齐 |
| Dialogue 时间轴 | startRatio/endRatio 定位 | 缺失 | ⚠️ 缺失字段 |
| ComfyUI 模板 | 3 个 workflow JSON | 待导出 | ⚠️ 未固化 |
| 多项目管理 | Project/Episode 两级 | 仅 project 目录 | ⚠️ 缺 episode 层级 |

### 补齐优先级

| 优先级 | 事项 | 预估 | 影响 |
|--------|------|------|------|
| **P0** | asset_manager.py (版本化资管) ✅ | 0.5 天 | 版本追踪/回滚 |
| **P0** | s2 schema 扩展 (relationships/costumes/dialogue time) | 0.5 天 | 角色一致性 |
| **P1** | 导出 ComfyUI workflow 模板 | 0.5 天 | 可维护性 |
| **P1** | 转场效果升级 (7种) ✅ | 0.5 天 | 成品质量 |
| **P2** | 单元测试 + 集成测试 + L2冒烟 ✅ | 0.5 天 | 质量保障 |
| **P2** | 补齐剩余 9 个 prompt ✅ | 0.5 天 | 灵活性 |
| **P3** | video_quality_check | 1 天 | 质量保障 |
| **P3** | Episode 多集管理 | 1 天 | 项目规模 |

### 执行顺序
1. asset_manager.py → s2 schema 扩展 (P0，影响迭代效率的关键瓶颈) ✅ 完成
2. 转场效果升级 + workflow 模板导出 (P1) ✅ 完成
3. continuity_check.py (P2)
4. Prompt 补齐 (P2，按需进行)

---

## T1: Qwen Edit 环境确认 (2026-06-29)

- ComfyUI v0.24 原生支持 `TextEncodeQwenImageEdit` / `TextEncodeQwenImageEditPlus`
- Qwen Image Edit 2511 模型已就位：
  - UNet: `models/unet/qwen-image-edit-2511-Q4_K_M.gguf`
  - Diffusion: `models/diffusion_models/qwen_image_edit_2511_fp8mixed.safetensors`
  - VAE: `models/vae/qwen_image_vae.safetensors`
  - Lightning LoRA: `models/loras/Qwen-Image-Edit-2511-Lightning-8steps-V1.0-fp32.safetensors`
- 外部 zip `Comfyui-QwenEditUtils.zip` 为 404 坏链，跳过，原生节点已够用
- 真实风格 checkpoint 已确认：`juggernautXL_v10.safetensors`

## T2: S2 schema 扩展 (2026-06-29) ✅ 完成

- [x] `prompts/defaults/character_extract.py` 增加 `visualAnchors` 字段 (face/hair/body/clothing/signature)
- [x] `SKILL.md` S2 接口文档更新
- [x] `core/state_manager.py` 增加 `s3b_four_view` 阶段
- [x] 向后兼容：`visualAnchors` 可选字段，现有数据无此字段时 graceful fallback

## T3: S3b 四视图工作流 (2026-06-29) ✅ 完成

- [x] `scripts/s3b_four_view.py` — 基于 Qwen Image Edit 2511 的四视图生成
- [x] `templates/qwen_edit_four_view.json` — ComfyUI workflow 模板
- [x] 支持 `--style comic|realist` 风格切换
- [x] 支持 `--lora` 加载 Lightning LoRA (8-step 加速)
- [x] 原生节点验证：`TextEncodeQwenImageEditPlus` ✅

## T4: S5 重构（参考图驱动）✅ 完成

- [x] `scripts/s5_frame_generate.py` 重构为 Qwen Image Edit reference-driven
- [x] 首帧: 角色参考图 + shot prompt → Qwen Edit
- [x] 尾帧: 首帧 PNG 作为参考 → Qwen Edit (首尾帧逻辑关联)
- [x] 支持 `--checkpoint` / `--style` 切换 comic/realist
- [x] 支持 `--lora` 加载 Lightning LoRA (8-step加速)
- [x] SKILL.md 更新 (10阶段流程 + D10/D11 决策)

---

## 一致性专项完成总结 (2026-06-29)

### 完成事项

| 任务 | 状态 | 产出 |
|------|------|------|
| T1: Qwen Edit 环境确认 | ✅ | 原生节点可用，无需 external node |
| T2: S2 schema 扩展 | ✅ | visualAnchors 字段加入 character_extract prompt |
| T3: S3b 四视图工作流 | ✅ | s3b_four_view.py + qwen_edit_four_view.json |
| T4: S5 重构 | ✅ | 参考图驱动首尾帧，首帧→尾帧链式生成 |

### 下一批任务 (待执行)

| 优先级 | 事项 | 预估 |
|--------|------|------|
| **P0** | asset_manager.py (版本化资管) ✅ | 已完成 |
| **P1** | 转场效果升级 (7种) ✅ | 已完成 |
| **P1** | 导出 ComfyUI workflow 模板 (固化 S3/S3b/S5) | 0.5 天 |
| **P2** | continuity_check.py (LLM vision 比对) | 1 天 |
| **P2** | 补齐剩余 9 个 prompt | 2-3 天 |

### 验证计划

1. 用 last_bento 项目端到端测试 S3b + S5 新链路
2. 对比新旧 S5 输出的一致性差异
3. Comic 风格验证通过后，测试 Realist (Juggernaut XL v2)

---

## T5: asset_manager.py 版本化资管 (2026-06-29) ✅ 完成

- [x] `core/asset_manager.py` — ShotAsset 版本表实现
  - 8 种资产类型: character_ref, four_view, first_frame, last_frame, keyframe_video, assembled_video, subtitled_video, final_video
  - 文件命名: `{shot_id}_{asset_type}_v{N}.{ext}` (AICB 规范一致)
  - 版本管理: 新版本插入 → 旧版本 is_active=False
  - 持久化: `projects/{project}/assets.json`
  - API: register / get_active / get_history / get_active_for_shot / get_character_active / invalidate_shot / list_project / export_report
  - Singleton: `get_asset_manager()`
- [x] 集成到 S3/S3b/S5/S6 脚本
- [x] 功能测试通过

---

---

## T6: 转场效果升级 (2026-06-29) ✅ 完成

- [x] `scripts/s7_video_assemble.py` 重构为 xfade 架构
  - 7 种 AICB 转场: cut/dissolve/fade_in/fade_out/wipeleft/slideright/circleopen
  - FFmpeg xfade filter 实现平滑过渡 (替换旧 concat -c copy)
  - 读 s4_shots.json 的 `transitionOut` 字段自动匹配转场
  - 全 cut 时自动回退 fast concat (零质量损失)
  - `--transition-duration` 可调转场时长 (默认 0.5s)
  - `--no-xfade` 强制 fast concat 模式

## T7: ComfyUI Workflow 模板导出 (2026-06-29) ✅ 完成

- [x] `templates/t2i_character_ref.json` — S3 T2I workflow
- [x] `templates/qwen_edit_four_view.json` — S3b 四视图 workflow (已有)
- [x] `templates/qwen_edit_frame.json` — S5 关键帧 workflow
- [x] `templates/flf2v_keyframe.json` — S6 FLF2V workflow
- [x] `templates/README.md` — 模板说明文档

## T8: continuity_check.py 连续性检查 (2026-06-29) ✅ 完成

- [x] `core/continuity_check.py` — LLM vision 相邻帧比对
  - 后端: baidu-codingplan GLM-5.1 多模态
  - 4 维度评分: 角色外观/场景环境/光影色调/构图衔接 (各 0-10)
  - 总分 0-100 + severity (none/minor/moderate/severe)
  - 同场景内低于阈值标记为 issue
  - 输出 `continuity_report.json` + 人类可读摘要
  - CLI: `python -m core.continuity_check --project last_bento`

## T9: Prompt 积植补齐 (2026-06-29) ✅ 完成

- [x] 9 个新 prompt 文件 (prompts/defaults/)
  - **frame_generate_first** — 首帧生成 (4 slots: style/reference/continuity/rendering)
  - **frame_generate_last** — 尾帧生成 (4 slots: style/relationship/readiness/rendering)
  - **character_image** — 角色四视图 (3 slots: layout/style_fidelity/quality)
  - **video_generate** — FLF2V 视频生成 (3 slots: interpolation/dialogue/anchors)
  - **script_generate** — 剧本生成 (3 slots: role/format/rules)
  - **script_split** — 分集拆分 (2 slots: role/format)
  - **import_character_extract** — 简化角色提取 (2 slots: role/format)
  - **scene_frame_generate** — 纯场景帧 (3 slots: reference/composition/rendering)
  - **ref_video_generate** — 参考图视频 (3 slots: consistency/duration/dialogue)
- [x] `prompts/registry.py` 更新: 12/12 prompt 注册 + module-based prompt 适配器
- [x] 全部 build 测试通过

---

## 当前快速参考

| 组件 | 状态 |
|------|------|
| Pipeline | ✅ 10 阶段 (含 S3b) |
| Prompts | ✅ 12/12 已移植 |
| 角色参考图 | ⚠️ 单视图（四视图已实现，待验证） |
| 一致性架构 | ✅ S2 visualAnchors + S3b Qwen Edit + S5 reference-driven |
| 版本化资管 | ✅ asset_manager.py |
| 连续性检查 | ✅ continuity_check.py |
| Workflow 模板 | ✅ 4 个 JSON + README |
| 转场效果 | ✅ 7 种 (xfade) |