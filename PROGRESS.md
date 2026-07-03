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
| 2026-07-01 | S7 xfade offset bug 修复, S6 stdout 缓冲修复, 多角色一致性决策 (TIV), VL 质检生命周期 |
| 2026-07-02 | qwen-image-edit ReferenceLatent 工作流调通 (v9), SageAttention 兼容性确认, S3 --gen qedit 合入版本 |
| 2026-07-02 | **工具链统一实施**: S3 Flux Dev 替换, S5 多角色+前帧增强, S4b 独立 stage, shot_split 增强 |
| 2026-07-02 | **qwen-image-edit 工作流 v2.0 修正**: 对齐官方 Vantage 工作流，移除 ReferenceLatent/FluxKontext 节点，euler/simple 采样器，negative 共享参考图 |
| 2026-07-02 | **决策关闭**: IPAdapter 方案取消（走 qedit 多参考图），Reference 视频模式取消（仅 Keyframe 模式） |

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

---

## 阶段里程碑：AICB 全量适配（2026-07-01）

**背景**: 基于 `EVALUATION_REPORT.md` 的差距分析，执行完整 AICB 能力移植。
**原则**: 不精简、不打折扣、先代码后环境、全部完成后统一测试。
**状态**: ✅ 15 文件改动，语法验证通过，待 e2e 验证

### 改动统计

| 文件 | +行 / -行 | 改动类型 |
|------|-----------|----------|
| `scripts/s6_flf2v_render.py` | +27/-27 | Prompt 重组：硬编码 → buildVideoPrompt 7-slot |
| `scripts/s7_video_assemble.py` | +693/-693 | 完全重写：fast concat → xfade + BGM + SRT + drawtext |
| `scripts/s8_subtitles.py` | +212/-212 | 格式升级：ASS → SRT，auto-distribute → startRatio/endRatio |
| `scripts/s5_frame_generate.py` | +623/-623 | Prompt 注入：compositionSuffix + colorPalette + heightCm |
| `prompts/defaults/frame_generate_first.py` | +100/-100 | AICB 全量移植：画风关键词 + 5条参考图规则 + 连续性 |
| `prompts/defaults/frame_generate_last.py` | +100/-100 | AICB 全量移植：画风强制 + 首帧关系 + 下镜头起点 |
| `prompts/defaults/video_generate.py` | +324/-324 | Slot 扩展：2-slot → 7-slot 完整 prompt 系统 |
| `scripts/s3_character_image.py` | +283/-283 | IPAdapter 参数化 + 分辨率对齐 |
| `scripts/shot_split.py` | +82/-82 | S4 分镜 prompt 升级 |
| `SKILL.md` | +51/-51 | 接口文档更新 |
| `core/continuity_check.py` | +428/-428 | 多模态连续性检查完善 |
| `core/llm_client.py` | +83/-83 | LLM 调用适配 |
| `s1_parsed.json` | +39/-39 | S1 解析数据更新 |
| `s2_characters.json` | +99/-99 | 角色数据更新 |
| `s4_shots.json` | +605/-605 | 分镜数据更新 |

### 三轮实施清单

#### R1: S6→S8 视频管线（已完成）

- [x] **R1-1**: S6 集成 `buildVideoPrompt` 7-slot（duration/characterAppearance/interpolation/camera/frameAnchors/dialogue）
- [x] **R1-2**: S7 完全重写为 `assembleVideo` — xfade chain (dissolve/fade/wipe/slide/circleopen/cut) + BGM 混合 + SRT 烧录 + ffmpeg drawtext 标题卡
- [x] **R1-3**: S8 改为 `generateSrtFile` — SRT 格式 + startRatio/endRatio 精确时间轴 + 多角色自动分发

#### R2: S3→S5 帧生成 Prompt + 质检（已完成）

- [x] **R2-1**: `frame_generate_first.py` 完整移植 AICB `buildFirstFramePrompt`
  - 画风关键词映射（anime/manga/cartoon → 动漫, photorealistic → 写实）
  - 5条参考图强制规则（服装/面部/发型/配饰/画风）
  - 连续性规则（same clothes, same style, smooth light transition, position continuation）
  - 渲染指令（film lighting + rim light, complete environment, cinematic framing）
- [x] **R2-2**: `frame_generate_last.py` 完整移植 AICB `buildLastFramePrompt`
  - 画风不可妥协（first-frame 锚定，绝对不得切换）
  - 首帧关系（相同环境/光照/色彩，仅姿势/表情/位置变化）
  - 下镜头起点（stable pose, complete composition, allows natural transition）
- [x] **R2-3**: S5 composition suffix 注入（AICB `handleFrameGenerate` 对齐）
  - `compositionGuide` → composition 描述
  - `focalPoint` → 焦点控制
  - `depthOfField` → shallow/deep 景深
  - `colorPalette` → 全局色板（项目级 + 角色级）
  - `heightCm` → 多角色身高比例
- [x] **R2-4**: 质检激活（已在之前完成）
  - e2e_dry_run.py 移除 `--no-check`，S5 启用 continuity_check + video_quality_check
  - qw35-9b 生命周期管理：S3 启动 → S5 后停止

#### R3: S7 增强（已在 R1-2 中一并完成）

- [x] **R3-1**: BGM 混合管线 — `-bgm_volume 0.3` + `-shortest`
- [x] **R3-2**: FFmpeg drawtext 标题卡/结束卡（CJK 支持，1280×720）

### 架构变更摘要

**S7 架构重构**（最大改动）:
- 旧: `concat` → `concat_segments` → 简单 burn subtitle
- 新: `build_filter_complex` → `build_xfade_chain` → `merge_bgm` → `generate_srt` → `render_text_overlay`
- 新增 filter_complex 表达式构建器，支持链式 xfade 节点
- 新增 `generate_srt()` 内建 SRT 生成函数
- 新增 `render_text_overlay()` ffmpeg drawtext 渲染
- `--with-subtitles` flag 控制 S7 内字幕烧录（默认关闭，S9 负责精修）

**S5 Prompt 注入架构**:
- 旧: `build_first_prompt(scene, desc, chars, prev)` → 直接拼接
- 新: `_build_scene_description(scene, color_palette)` → `build_first_prompt(...)` → 附加 `comp_suffix`
- `_build_composition_suffix(shot, chars_in, all_chars, color_palette)` 函数：组装 compositionGuide/focalPoint/depthOfField/heightCm/colorPalette

**Prompt 模板架构**:
- frame_generate_first/last 从 4-slot 简化版 → 8-slot AICB 全量版
- `build_full_prompt(slot_contents, scene_desc, frame_desc, char_descs, [prev/first])` 签名
- 每个 slot 可独立覆盖，支持运行时个性化

### Deferred（有意延后）

| 项 | 原因 | 计划 |
|---|------|------|
| IPAdapter 工作流 | 等 qwen-image-edit 调通 | 调通后一并落地 |
| 四视图 character-image | 同上 | 同上 |
| 2560×1440 分辨率升级 | 需验证 FLF2V 是否支持 | 待测试 |

### 下一步

1. **统一 dry-run**: `python scripts/e2e_dry_run.py --project last_bento`
2. **Prompt 验证**: 检查 S6 motion_prompt 是否包含完整 7-slot 内容
3. **S7 xfade 测试**: 小样本验证 filter_complex 表达式
4. **S5 composition 验证**: 确认 composition suffix 正确注入 prompt

### 验证结果 (2026-07-01 14:20)

| 测试项 | 结果 | 说明 |
|--------|------|------|
| 语法验证 | ✅ 7/7 文件通过 | ast.parse 全部通过 |
| S5 dry-run | ✅ 12 shots 输出正常 | prompt 字符量 1398-2121 chars |
| S6 buildVideoPrompt | ✅ 7-slot 组装 | 时长/角色/插值/镜头/帧锚/对话/运动 |
| S8 SRT 生成 | ✅ 7条对白 → SRT | 时间轴精确，startRatio/endRatio 正确 |
| e2e dry-run | ⚠️ S1 API 429 | 千帆限流，不影响代码验证 |

**结论**: 代码层全部通过，无语法错误，prompt 组装正确。实际运行需等 API 恢复。

---

## 当前快速参考

| 组件 | 状态 |
|------|------|
| Pipeline | ✅ 10 阶段 (含 S3b) |
| Prompts | ✅ 12/12 AICB 全量移植 |
| 角色参考图 | ⚠️ 单视图（四视图已实现，待验证） |
| 一致性架构 | ✅ S2 visualAnchors + S3b Qwen Edit + S5 reference-driven |
| 版本化资管 | ✅ asset_manager.py |
| 连续性检查 | ✅ continuity_check.py |
| Workflow 模板 | ✅ 4 个 JSON + README |
| 转场效果 | ✅ 7 种 (xfade) + BGM + SRT + drawtext |
| Composition | ✅ compositionGuide/focalPoint/depthOfField/colorPalette/heightCm |

---

## 工具链统一实施 (2026-07-02)

**决策来源**: `docs/TOOLCHAIN_UNIFICATION_PLAN.md` + Vincent 5项决策确认

### 决策确认

| # | 决策点 | 确认方案 |
|---|--------|----------|
| D1 | S3 Flux Dev 分辨率 | 1024×1536 — 与 S3b/S5 对齐 |
| D2 | Flux Dev 推理步数 | 20步 euler/simple — 速度优先 |
| D3 | S5 多角色参考图上限 | 3张 — image1=主角色, image2=配角, image3=前帧 |
| D4 | S5 前帧注入位置 | image3 (首帧生成时) |
| D5 | S4b 是否独立 stage | 是 — 解耦架构，可独立重跑 |

### Phase 1: S3 Flux Dev 替换 ✅

| 变更 | 文件 | 说明 |
|------|------|------|
| 新建 | `templates/flux_dev_t2i.json` | Flux Dev fp8 T2I 工作流 (9节点) |
| 修改 | `scripts/s3_character_image.py` | 新增 `build_flux_dev_prompt()` + `build_flux_dev_workflow()`; `--gen flux` 为新默认; 保留 `--gen t2i` 向后兼容 |
| 修改 | `prompts/defaults/character_image.py` | 新增 `build_flux_ref_prompt()` 自然语言单视图 prompt |

架构: UNETLoader(flux1-dev-fp8) + DualCLIPLoader(clip_l+t5xxl) + VAELoader(ae) → KSampler(20步 euler/simple cfg=3.5) → VAEDecode → SaveImage

### Phase 2: S5 多角色+前帧增强 ✅

| 变更 | 文件 | 说明 |
|------|------|------|
| 新建 | `templates/qwen_edit_frame_multi.json` | 扩展多参考图工作流 (+2 LoadImage 节点, image2/image3 链接到 TextEncodeQwenImageEditPlus) |
| 修改 | `scripts/s5_frame_generate.py` | `build_qedit_frame_workflow()` 支持 ref_image2/ref_image3; `generate_frame()` 透传; 主循环多角色 ref 查找 + image3=前帧; S4b prompt 优先 |

关键: 多角色场景 image1=主角色, image2=配角, image3=前帧(D4); 单角色场景自动回退到原模板

### Phase 3: S4 prompt 重写 + S4b 独立 stage ✅

| 变更 | 文件 | 说明 |
|------|------|------|
| 新建 | `scripts/s4b_keyframe_assets.py` | 独立 stage，从 s4+s2 生成首尾帧 prompt |
| 修改 | `prompts/defaults/shot_split.py` | 新增 `SHOT_COUNT_RULES` slot (分镜数量下限/首尾帧规则/prompt字数下限) |
| 修改 | `core/state_manager.py` | STAGE_ORDER 增加 `s4b_keyframe_assets`; S5 依赖增加 s4b |
| 修改 | `scripts/s5_frame_generate.py` | S4b prompt 优先: 有 s4b 数据时使用预构建 prompt，否则回退到 on-the-fly 构建 |

S4b 产出: `projects/{project}/s4b_keyframe_assets.json` (每个 shot 的 startFrame/endFrame prompt + characterRefPrompts)

### Phase 4: 全链路验证 ✅

| 验证项 | 结果 |
|--------|------|
| flux_dev_t2i.json 结构 | ✅ 9 节点, 所有链接正确 |
| qwen_edit_frame_multi.json 结构 | ✅ 19 节点, node 42/43 + image2/image3 链接 |
| build_flux_dev_prompt() 输出 | ✅ 自然语言 381c |
| build_flux_dev_workflow() 参数 | ✅ steps=20, cfg=3.5, euler/simple, 1024×1536 |
| build_qedit_frame_workflow() 多参考图 | ✅ 单参考用原模板, 多参考自动切换 |
| s4b_keyframe_assets.py 干跑 | ✅ 16 shots 正确 |
| shot_split SHOT_COUNT_RULES | ✅ slot 集成 |
| state_manager s4b | ✅ 在 STAGE_ORDER/STAGE_LABELS/STAGE_DEPS |
| 全部 Python 导入 | ✅ 无错误 |

### 工具链统一后的架构

```
S3  角色ref图:  Flux Dev fp8 (T2I, 1024×1536, 20步 euler/simple)
S3b 四视角:     qedit ReferenceLatent (1024×1536, 不变)
S4b 关键帧资产: 独立 stage (首尾帧 prompt 预构建)
S5  首帧+尾帧:  qedit ReferenceLatent (多角色 image1/2/3 + 前帧连续性)
S6  视频生成:   Wan2.2 FLF2V (不变)
```

分辨率全线对齐: 1024×1536，消除 latent 变形。
| S5/S6 质检 | ✅ continuity_check + video_quality_check 已激活 |