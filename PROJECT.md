# AIComicFactory — 项目总纲

**创建日期**: 2026-06-28
**状态**: 规划完成，待执行 Phase 1
**定位**: 基于 OpenClaw 调度的 AI 漫剧生产工作流（非独立软件）

---

## 一、项目来源

AIComicFactory 是两个项目的融合：

| 来源 | 贡献 | 仓库/路径 |
|------|------|-----------|
| **AIComicBuilder** (AICB) | Pipeline 拓扑 + Prompt 工程 + 数据模型 | `~/AIComicBuilder/` (已下载核心源码) |
| **westward_factory** (WF) | ComfyUI 基础设施 + TTS/字幕链路 + 加速方案 | `~/westward_factory/` |

**融合原则**: AICB 为主（成熟方案），WF 为辅（已验证基础设施），OpenClaw 为编排层。

## 二、优化原则（项目宪法）

**核心原则：向 AICB 看齐，AICB 有的直接使用，我们仅作本地有先的改造。**

### 2.1 优先级规则

| 优先级 | 规则 | 说明 |
|--------|------|------|
| P0 | **AICB 优先** | 若 AICB 已有对应实现，直接移植/引用，不做二次设计 |
| P1 | **本地验证优先** | 若本地已有验证通过的方案（WF），且 AICB 无对应或方案明显更优，保留本地方案 |
| P2 | **差异记录** | 所有与 AICB 的差异必须记录在本章 2.3 节，含原因和影响范围 |

### 2.2 适用范围

本原则适用于以下所有资产：
- **Prompt 工程**: prompt 内容、slot 定义、参数 — 以 AICB registry.ts 为准
- **数据模型**: JSON schema、字段名、类型 — 以 AICB schema.ts 为准
- **Pipeline 拓扑**: stage 顺序、依赖关系、输入输出 — 以 AICB pipeline handler 为准
- **ComfyUI Workflow**: 节点配置、模型选择、参数 — 以 AICB 模板为准
- **命名规范**: 目录名、文件名、stage ID — 以 AICB 为准

### 2.3 已知差异登记

以下为本项目已确认与 AICB 的差异，每项需定期回顾：

| 差异项 | 我方方案 | AICB 方案 | 差异原因 | 影响范围 | 状态 |
|--------|---------|----------|---------|---------|------|
| LLM 引擎 | baidu-codingplan (GPT-4 级) | 百炼/Dify/Coze agent | 本地无百炼 key，baidu-codingplan 等效 | prompt 内容不变 | ✅ 稳定 |
| 编排层 | OpenClaw Skill + sessions_spawn | 自研 Web UI + API | 不做独立软件 | 调度逻辑内聚在 SKILL.md | ✅ 稳定 |
| 数据持久化 | 文件系统 JSON | SQLite (Prisma) | 零运维，git 友好 | 无下游依赖 | ✅ 稳定 |
| 角色参考图 | S3 单视图 + S3b 四视图 (Qwen Edit) | 四视图 T2I (单次生成) | 本地已有 Qwen Edit 2511 | S3/S3b prompt 有差异 | ⚠️ 待验证 |
| 视频生成 | Wan2.2 FLF2V + Lightx2v 4-step | Seedance 2.0 | WF 已验证，本地模型 | S6 prompt 格式不同 | ✅ 稳定 |
| TTS | Qwen3-TTS (ComfyUI) | 未明确 | WF 已验证 | S9 链路 | ✅ 稳定 |

### 2.4 复评机制

- **触发条件**: AICB 有重大更新时，或本项目积累 3 个以上差异项时
- **动作**: 逐项对比 2.3 节，判断差异是否仍然成立，不成立的合并回 AICB 方案
- **频率**: 每月一次，或 AICB 发版时

---

## 三、核心架构

```
┌─────────────────────────────────────────────────────┐
│                 OpenClaw (编排层)                     │
│                                                     │
│  ┌─────────┐  ┌──────────┐  ┌──────────────────┐   │
│  │ Skill   │  │ Cron     │  │ sessions_spawn   │   │
│  │ 调度入口 │  │ 定时/续跑 │  │ 并行 stage       │   │
│  └────┬────┘  └──────────┘  └──────────────────┘   │
│       │                                             │
│  ┌────▼─────────────────────────────────────────┐   │
│  │          AIComicFactory Skill                │   │
│  │                                             │   │
│  │  "做 ep_001" → 解析状态 → 调度未完成 stage    │   │
│  │  "重做 S4"   → 标记脏 → 从 S4 重新执行       │   │
│  │  "看进度"    → 读 projects/ep_NNN/state.json │   │
│  └─────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
                        │
          ┌─────────────▼──────────────┐
          │   ~/AIComicFactory/        │
          │                            │
          │  prompts/     ← AICB 移植  │
          │  scripts/     ← stage 实现 │
          │  core/        ← 引擎模块   │
          │  projects/    ← 项目数据   │
          │  templates/   ← workflow   │
          └────────────────────────────┘
```

---

## 四、Pipeline（从 AICB 继承）

| # | Stage | 输入 | 引擎 | 输出 | 说明 |
|---|-------|------|------|------|------|
| 1 | `script_parse` | 原始文本 | OpenClaw LLM (baidu-codingplan) | s1_parsed.json | 剧本→结构化 JSON |
| 2 | `character_extract` | s1_parsed.json | OpenClaw LLM (baidu-codingplan) | s2_characters.json | 角色提取+视觉规格 |
| 3 | `character_image` | s2_characters.json | ComfyUI (SDXL T2I + IPAdapter) | s3_character_refs/ | 单参考图（非四视图） |
| 4 | `shot_split` | s1+s2 | OpenClaw LLM (baidu-codingplan) | s4_shots.json | 分镜拆解 |
| 5 | `frame_generate` | s4+s3 | ComfyUI (img2img + IPAdapter) | s5_frames/ | 首帧+尾帧 |
| 6 | `video_generate` | s5+s4 | ComfyUI (Wan2.2 FLF2V) | s6_videos/ | Keyframe 插值视频 |
| 7 | `video_assemble` | s6+s4 | FFmpeg | s7_assembled.mp4 | 拼接+转场+BGM+标题卡 |
| 8 | `subtitles` | s7+TTS音频 | Whisper ASR | s8_subtitles.ass | 字幕烧录 |

> S1/S2/S4 阶段由 OpenClaw 直接调用 baidu-codingplan 完成，不走 Python 脚本。
> 备选方案：sessions_spawn 指定本地模型（vllm_qwen27b / vllm_qw35_gptq）时自动切换。

---

## 五、目录结构

```
~/AIComicFactory/
│
├── prompts/                      ← AICB 移植 (核心资产)
│   ├── registry.py               # 插槽化 prompt 注册表
│   ├── overrides/                # 用户覆盖 (YAML)
│   │   └── shot_split.yaml
│   └── defaults/                 # 12 个 prompt 的 defaultContent
│       ├── script_parse.py
│       ├── character_extract.py
│       ├── shot_split.py
│       └── ...
│
├── core/                         ← 引擎模块
│   ├── comfyui_session.py        # WF 继承
│   ├── vllm_client.py            # vLLM 备选客户端（仅本地 LLM 模式）
│   ├── prompt_runner.py          # prompt 构建器（LLM 调用由 OpenClaw 完成）
│   ├── asset_manager.py          # ShotAsset 版本化管理 (AICB 概念)
│   └── continuity_check.py       # 连续性检查 (Qwen-VL)
│
├── scripts/                      ← 8 个 stage 脚本
│   ├── s1_script_parse.py
│   ├── s2_character_extract.py
│   ├── s3_character_image.py
│   ├── s4_shot_split.py
│   ├── s5_frame_generate.py
│   ├── s6_video_generate.py
│   ├── s7_video_assemble.py
│   └── s8_subtitles.py
│
├── templates/                    ← ComfyUI workflow JSON
│   ├── t2i_character_ref.json
│   ├── img2img_frame.json
│   └── flf2v_keyframe.json
│
├── projects/                     ← 项目数据 (多项目)
│   └── ep_001/
│       ├── source.txt            # 原始剧本
│       ├── state.json            # 管线状态
│       ├── s1_parsed.json
│       ├── s2_characters.json
│       ├── s3_character_refs/
│       ├── s4_shots.json
│       ├── s5_frames/
│       ├── s6_videos/
│       ├── s7_assembled.mp4
│       └── s8_subtitles.ass
│
└── SKILL.md                      # OpenClaw Skill 定义
```

---

## 六、从 AICB 继承的核心资产

### 5.1 Pipeline 拓扑
8 阶段串行链路，每个 stage 可独立触发或批量执行。

### 5.2 Prompt Registry 插槽系统
- 12 个 prompt 拆解为可编辑 slot
- 每个 slot: key + defaultContent + editable 标记
- 覆盖机制: slotContents 覆盖 → registry default → hardcoded fallback
- 版本管理: git（本地不需要 DB 版本表）
- A/B 测试: 暂不实现，预留接口

**12 个 Prompt 清单**:

| Key | Category | 说明 | 优先级 |
|-----|----------|------|--------|
| `script_generate` | script | idea→剧本 | P2 (可选) |
| `script_parse` | script | 原文→结构化 JSON | **P1** |
| `script_split` | script | 分集拆分 | P2 (可选) |
| `character_extract` | character | 角色提取+视觉规格 | **P1** |
| `import_character_extract` | character | 导入文本角色提取 | P2 |
| `shot_split` | shot | 分镜拆解 | **P1** |
| `keyframe_prompts` | shot | 关键帧 prompt 生成 | P2 |
| `video_prompts` | shot | 视频 prompt 生成 | P2 |
| `ref_image_prompts` | shot | 参考图 prompt 生成 | P2 |
| `ref_video_prompts` | shot | 参考视频 prompt 生成 | P2 |
| `frame_generate_first` | frame | 首帧图像 prompt | **P1** |
| `frame_generate_last` | frame | 尾帧图像 prompt | **P1** |

### 5.3 Shot 数据模型（AICB schema 核心）
从 AICB `src/lib/db/schema.ts` 提取的关键字段：

```python
# Shot 核心字段 (映射到 s4_shots.json)
shot = {
    "id": "shot_001",
    "scene_number": 1,
    "shot_number": 1,
    "prompt": "...",              # 图像生成主 prompt
    "motionScript": "...",        # 运动描述 (3秒分段, 四层交织)
    "videoScript": "...",         # Seedance 散文格式 (30-60词)
    "videoPrompt": "...",         # 视频生成 prompt
    "cameraDirection": "slow_push_in",  # 运镜
    "compositionGuide": "rule_of_thirds",  # 构图
    "focalPoint": "...",          # 焦点
    "depthOfField": "shallow",    # 景深
    "transitionIn": "dissolve",   # 入转场
    "transitionOut": "cut",       # 出转场
    "soundDesign": "...",         # 声音设计
    "musicCue": "...",            # 音乐提示
    "costumeOverrides": {},       # 按镜头覆盖服装
    "isStale": False,             # 脏标记
    "duration": 5.0,              # 时长(秒)
    "dialogues": [],              # 对白列表
    "characters": [],             # 出场角色
}
```

### 5.4 ShotAsset 版本化
```python
# ShotAsset (映射到文件系统)
shot_asset = {
    "type": "first_frame|last_frame|reference|keyframe_video|reference_video",
    "shot_id": "shot_001",
    "version": 1,
    "is_active": True,
    "file_path": "...",
}
```
文件命名: `{shot_id}_{type}_v{N}.png`

### 5.5 角色提取核心概念
- **身份层/风格层分离**: 身份层不可删除，风格层可重新诠释
- **visualHint**: 2-4字速记标签，下游所有 prompt 自动注入
- **performanceStyle**: 戏中标志动作，不进 description（description 只写中性站立）
- **relationships**: 角色关系 (ally/enemy/lover/family/mentor/rival/stranger/neutral)

### 5.6 分镜 prompt 核心约束
- 物理常识约束: 严禁比喻动词、反物理行为
- 字幕安全区: 画面下方 20% 保留
- 变化幅度比例: 短镜头=微变化，长镜头=显著变化
- motionScript 3秒分段: 角色+环境+机位+物理四层交织
- videoScript Seedance 散文格式: 30-60词自然语言
- 构图指南: 7种专业构图技法场景匹配
- 转场指南: 场景切换 dissolve，首尾 fade，默认 cut

---

## 七、从 WF 继承的核心资产

### 6.1 ComfyUISession
- 路径: `~/westward_factory/core/comfyui_session.py`
- 特性: prompt_id 事件驱动、WebSocket 监听、自动显存清理、断点续传
- 直接复制到 `core/` 并适配

### 6.2 FLF2V 加速三件套
- **SageAttention**: 1.0.6 + Triton 3.6.0, `--use-sage-attention`
- **Lightx2v**: 4-step distillation LoRA, steps=4, cfg=1.0, shift=5.0
- **TeaCache (EasyCache)**: threshold=0.2, start=0.15, end=0.95
- 实测: ~7-9x 加速 (6min→48s)

### 6.3 TTS 链路
- Qwen3-TTS (ComfyUI 插件)
- 音轨串行: narration → inner_voice → dialogue, 0.3s 间隔
- BGM/ambient 可与语音并行叠合

### 6.4 字幕链路
- Whisper medium ASR 回听 → 精确时间轴
- 脚本原文矫正: 替换错别字，保留时间轴
- ASS 三样式: 旁白(白/44px)、心声(半透明/40px/斜体)、对话(黄/48px/加粗)

### 6.5 文件路由规则
- production/ep_NNN/sX_* 分阶段目录
- 禁止 temp/ 散落
- 命名: `{clip_id}_{ref|start|end}.png` / `{clip_id}_{role}.flac`

### 6.6 episode.json Schema
- 已有 56 集剧本数据在 `~/westward_factory/episodes/`
- 可直接迁移或作为 source.txt 输入

---

## 八、关键决策（不可随意更改）

| # | 决策 | 方案 | 理由 | 备选（需 Vincent 授权才可切换） |
|---|------|------|------|------|
| D1 | 角色参考图 | 单正面全身 + IPAdapter | 实现简单，IPAdapter 已验证 | 四视图（需 LoRA/ControlNet） |
| D2 | 视频生成模式 | 仅 Keyframe (首尾帧插值) | FLF2V 只支持 keyframe | + Reference 模式（需 Wan2.2 I2V） |
| D3 | LLM | **baidu-codingplan (主)** + Qwen3.6-27B (备) | GPT-4 级模型，prompt 不需精简；本地备选可切换 | Gemma4-26B |
| D4 | 结构化输出 | 纯 prompt 约束 | GPT-4 级模型原生稳定输出 JSON | guided_json（仅备选本地模型时） |
| D5 | 并行策略 | S5/S6 按 shot 排队并行 | ComfyUI GPU 独占，排队执行 | 全串行 |
| D6 | TTS | Qwen3-TTS (ComfyUI) | 已验证，音质好 | Edge TTS (fallback) |
| D7 | 字幕 | Whisper ASR + 脚本矫正 | 精确时间轴 | 纯时间轴计算 |
| D8 | 数据持久化 | 文件系统 (JSON + 目录) | 零运维，git 友好 | SQLite |
| D9 | UI | 无（OpenClaw 对话） | 不做独立软件 | Web UI (未来可选) |
| D10 | Agent 集成 | 不集成 | 本地 LLM 直接调用 | 百炼/Dify/Coze |

---

## 九、OpenClaw Skill 设计

### 触发词
- `"做 ep_001"` / `"继续做"` → 从断点续跑
- `"重做 S4 ep_001"` → 标记脏，从指定 stage 重跑
- `"看进度"` → 读 state.json，汇报每个 stage 状态
- `"角色提取 ep_001"` → 单独跑 Stage 2
- `"只跑到 S5"` → 执行到指定 stage 后暂停

### state.json 格式
```json
{
  "project": "ep_001",
  "created": "2026-06-28T19:00:00+08:00",
  "updated": "2026-06-28T19:30:00+08:00",
  "stages": {
    "s1_parse": {"status": "completed", "ts": "2026-06-28T19:00:00+08:00", "duration_s": 12},
    "s2_character_extract": {"status": "completed", "ts": "2026-06-28T19:02:00+08:00", "duration_s": 8},
    "s3_character_image": {"status": "completed", "ts": "2026-06-28T19:05:00+08:00", "duration_s": 45},
    "s4_shot_split": {"status": "completed", "ts": "2026-06-28T19:08:00+08:00", "duration_s": 15},
    "s5_frame_generate": {"status": "running", "progress": "3/9 shots", "ts": "2026-06-28T19:10:00+08:00"},
    "s6_video_generate": {"status": "pending"},
    "s7_assemble": {"status": "pending"},
    "s8_subtitles": {"status": "pending"}
  },
  "errors": []
}
```

### 调度逻辑
1. 读 `projects/{project}/state.json` → 找到最高完成 stage
2. 从下一个 stage 开始串行执行
3. S5 (frame_generate): 每个 shot 可提交到 ComfyUI 排队
4. S6 (video_generate): 每个 shot 可提交到 ComfyUI 排队
5. 每个 stage 完成后更新 state.json
6. 失败 → 写入 state.json.errors + 日志，不阻塞，可重试

---

## 十、风险与缓解

| 风险 | 严重度 | 缓解方案 |
|------|--------|---------|
| API 调用成本 | 中 | baidu-codingplan 定价待确认；单集 LLM cost 约 0.5-2 元 |
| 角色一致性不如四视图 | 中 | IPAdapter 权重调优 + visualHint 强注入每帧 prompt |
| FLF2V 无肢体动作 | 中 | motionScript 精细描述 + 接受局限 + 未来换模型 |
| ComfyUI GPU 独占 | 低 | 排队机制 + cron 不阻塞主 session |
| 本地 LLM 备选质量降级 | 低 | 本地模式只在无网络时使用，备选 qw36-27b 仍可用 |

---

## 十一、实施路线

### Phase 1: 骨架 + 文本链路 (2-3 天)
- [ ] 创建目录结构
- [ ] `core/prompt_runner.py` — prompt 构建器（LLM 调用由 OpenClaw 完成）
- [ ] `prompts/registry.py` — 插槽化 prompt 注册表
- [ ] `prompts/defaults/` — 移植 4 个 P1 prompt 原样（不需精简）
- [ ] S1/S2/S4 在 SKILL.md 中实现（OpenClaw LLM 直接调用 baidu-codingplan）
- [ ] 端到端测试: 原始文本 → s1 → s2 → s4

### Phase 2: 图像链路 (3-4 天)
- [ ] `core/comfyui_session.py` — WF 继承
- [x] `core/asset_manager.py` — ShotAsset 版本化
- [ ] `scripts/s3_character_image.py` — T2I + IPAdapter
- [ ] `scripts/s5_frame_generate.py` — img2img + IPAdapter
- [ ] `templates/t2i_character_ref.json` — ComfyUI workflow
- [ ] `templates/img2img_frame.json` — ComfyUI workflow
- [ ] 端到端测试: s1 → s2 → s3 → s4 → s5

### Phase 3: 视频 + 合成链路 (2-3 天)
- [ ] `scripts/s6_video_generate.py` — FLF2V keyframe
- [ ] `scripts/s7_video_assemble.py` — FFmpeg
- [ ] `scripts/s8_subtitles.py` — Whisper + 矫正
- [ ] `templates/flf2v_keyframe.json` — ComfyUI workflow
- [ ] 端到端测试: 全链路 1 集跑通

### Phase 4: OpenClaw 集成 + 调优 (2-3 天)
- [ ] **SKILL.md 完善** (触发词/调度逻辑) - 部分完成
- [ ] state.json 读写 + 断点续跑
- [ ] prompt 调优（主模型无需精简，仅备选本地模型模式下验证）
- [ ] 端到端测试 + 质量评估

**总计: ~10-12 天**

---

## 十二、本地技术栈参考

| 组件 | 版本/配置 | 路径/端口 |
|------|----------|----------|
| GPU | RTX 5090D, 32GB VRAM | — |
| ComfyUI | comfyui conda env, Python 3.12 | `~/ComfyUI/`, port 8188 |
| vLLM (Qwen3.6-27B) | qw36-27b-vllm env, 128K ctx | port 8000, alias `vllm_qwen27b` |
| vLLM (Gemma4-26B) | gm4-26b-vllm env, 128K ctx | port 8001, alias `vllm_gemma26b` |
| EdgeLLM | v4.1.0 | `~/edge_llm/` |
| Qwen3-TTS | ComfyUI 插件 | — |
| Whisper | medium model | — |
| FFmpeg | system | — |
| SageAttention | 1.0.6 + Triton 3.6.0 | ComfyUI `--use-sage-attention` |
| Lightx2v | 4-step LoRA | steps=4, cfg=1.0, shift=5.0 |
| TeaCache | EasyCache node | threshold=0.2 |

---

## 十三、AICB 源码参考索引

已下载到 `~/AIComicBuilder/`，关键文件：

| 文件 | 内容 |
|------|------|
| `README.md` | 项目说明 |
| `package.json` | 技术栈依赖 |
| `src/lib/db/schema.ts` | 完整数据模型 (Project/Episode/Scene/Shot/ShotAsset/Character/...) |
| `src/lib/pipeline/*.ts` | 8 个 stage handler 实现 |
| `src/lib/ai/provider-factory.ts` | Provider 解析逻辑 |
| `src/lib/ai/types.ts` | AI 类型定义 |
| `src/lib/ai/agent-caller.ts` | 百炼/Dify/Coze 调用器 |
| `src/lib/ai/providers/seedance.ts` | Seedance 2.0 实现 (keyframe + reference 双模式) |
| `src/lib/ai/prompts/registry.ts` | **核心** — Prompt Registry 插槽系统 + 12 个 prompt 定义 |
| `src/lib/ai/prompts/character-extract.ts` | 角色提取 prompt |
| `src/lib/ai/prompts/character-image.ts` | 四视图 prompt |
| `src/lib/ai/prompts/shot-split.ts` | 分镜 prompt |
| `src/lib/ai/prompts/video-generate.ts` | 视频生成 prompt |
| `src/lib/pipeline/continuity-check.ts` | 连续性检查 |
| `src/lib/pipeline/video-quality-check.ts` | 视频质量检查 |
| `src/lib/task-queue/queue.ts` | 任务队列实现 |
