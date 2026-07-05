# AIComicFactory v1.1

基于 OpenClaw 调度的 AI 漫剧生产管线，移植自 AIComicBuilder (AICB) 的 Pipeline 拓扑 + Prompt 工程 + 数据模型，适配本地 ComfyUI + vLLM 环境。

## 管线架构 (12 Stages, v2)

```
source.txt → S1(LLM) → S2(LLM) → S2b(script) → S4(LLM) → S4b(script)
                                                 ↓
                                    S3(ComfyUI) → S3b(ComfyUI) → S5(ComfyUI) → S6(FLF2V) → S7(FFmpeg) → S8(ASS) → S9(TTS)
```

### Stage 定义

| 阶段 | 脚本 | 引擎 | 说明 |
|------|------|------|------|
| S1 | OpenClaw Nova (LLM) | LLM | 剧本解析：原文 → scenes + dialogues |
| S2 | OpenClaw Nova (LLM) | LLM | 角色提取：5-dim visualAnchors + relationships |
| S2b | `scripts/wardrobe_extract.py` | Python | 零 LLM 服饰提取 → costumes[] + defaultCostume |
| S3 | `scripts/s3_character_image.py` | ComfyUI (T2I) | 角色参考图 (1024×1024) |
| S3b | `scripts/s3b_four_view.py` | ComfyUI (Qwen Img Edit) | 四视图扩展 |
| S4 | OpenClaw Nova (LLM) | LLM | 分镜拆解 → shots[] |
| S4b | `scripts/s4b_keyframe_assets.py` | Python | 关键帧 prompt 预构建 + duration 审核 |
| S5 | `scripts/s5_frame_generate.py` | ComfyUI (IPAdapter) | 关键帧生成 (1280×720) |
| S6 | `scripts/s6_flf2v_render.py` | ComfyUI (Wan2.2) | FLF2V 帧插值动画 |
| S7 | `scripts/s7_video_assemble.py` | FFmpeg | 视频拼接 + 转场 |
| S8 | `scripts/s8_subtitles.py` | Python | ASS 字幕生成 |
| S9 | `scripts/s9_tts_audio.py` | ComfyUI (Qwen3-TTS) | TTS 语音 + 成片合成 |

## 核心模块 (core/)

| 模块 | 说明 |
|------|------|
| `state_manager.py` | **Phase 2 重构** — 管线状态管理 (v2)，支持 checkpoint/params_hash/dirty/stale propagation |
| `parallel_executor.py` | **Phase 3 新增** — 并行执行引擎，ThreadPoolExecutor 安全并行 S8+S9 |
| `asset_manager.py` | 版本化资产管理器 |
| `prompt_runner.py` | Prompt 构建器注册表 |
| `llm_client.py` | LLM API 客户端 |
| `schema_validators.py` | JSON Schema 校验 |
| `continuity_check.py` | 连续性检查 (LLM vision) |
| `comfyui_session.py` | ComfyUI 会话管理 |

## 环境依赖

### 基础环境
- Python 3.12+
- Conda (miniconda3)

### ComfyUI
- **版本**: 0.22.0+
- **环境**: `conda activate comfyui`
- **核心模型**:

| 模型 | 用途 | S3/S5 (anime) | S3/S5 (realistic) |
|------|------|:---:|:---:|
| [Animagine XL 3.1](https://huggingface.co/cagliostrolab/animagine-xl-3.1) | SDXL 动漫风格 | ✅ | — |
| [Flux.1 Dev FP8](https://huggingface.co/Kijai/flux-fp8) | Flux 写实风格 | — | ⚠️ 实验 |
| [Wan2.2 I2V 14B](https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI) | FLF2V 视频生成 | S6 | S6 |
| [Lightx2v LoRA](https://huggingface.co/lightx2v/wan2.2) | 4-step 加速 | S6 | S6 |

- **IPAdapter** (角色一致性): `ip-adapter-plus_sdxl_vit-h`, `clip_vision_h`
- **节点插件**: ComfyUI-IPAdapter-Plus, ComfyUI-WanVideoWrapper

### Conda 环境 (comfyui)
```
torch>=2.10.0
transformers==4.57.0
Pillow
requests
```

### 工具链
- **FFmpeg**: S7 视频拼接 + S8 字幕
- **ImageMagick** (可选): 标题卡生成

## 项目结构

```
AIComicFactory/
├── core/               # 引擎模块 (state_manager v2, parallel_executor, ...)
├── prompts/            # AICB prompt 模板
│   └── defaults/       # 原始模板，禁止随意修改
├── scripts/            # S3-S9 管线脚本
├── templates/          # ComfyUI workflow JSON 模板
├── reference/          # AICB 源码参考 (TypeScript)
├── tests/              # L0 (unit) / L1 (integration) / L2 (smoke)
├── docs/               # 架构分析、升级计划、模块文档
│   ├── state_manager_v2.md
│   ├── parallel_execution.md
│   └── audits/
└── projects/           # 项目数据
    └── <project_name>/
        ├── source.txt              # 原始剧本
        ├── state.json              # 管线状态 (v2 schema)
        ├── s1_parsed.json          # S1 输出
        ├── s2_characters.json      # S2 输出
        ├── s4_shots.json           # S4 输出
        ├── s3_character_refs/      # S3 输出 (不入 git)
        ├── s5_frames/              # S5 输出 (不入 git)
        ├── s6_videos/              # S6 输出 (不入 git)
        ├── s7_assembled.mp4        # S7 输出
        ├── s8_subtitles.ass        # S8 输出
        └── s9_final.mp4            # S9 输出
```

## 使用方式

### 自动化管线执行

```bash
python e2e_dry_run.py --project <name> [--parallel] [--to <stage>]
```

- `--parallel`: S8+S9 并行执行
- `--to <stage>`: 仅执行到指定阶段
- 自动断点续跑：已完成的 stage 自动跳过
- 参数变更检测：如果 stage args 变化，自动标记 dirty 并重跑

### 新项目全链路

```bash
# 1. 准备 source.txt
# 2. 执行管线
python e2e_dry_run.py --project <name>
```

### 手动执行 (单步调试)

```bash
conda activate comfyui
python scripts/s3_character_image.py --project <name> --style vivid
python scripts/s5_frame_generate.py --project <name> --style vivid
python scripts/s6_flf2v_render.py --project <name>
python scripts/s7_video_assemble.py --project <name>
python scripts/s8_subtitles.py --project <name>
python scripts/s9_tts_audio.py --project <name>
```

### 风格切换

```bash
--style vivid      # animexl_xuebiMIX_v40 (默认)
--style classic    # Animagine XL 3.1
--style concept    # Juggernaut XL (实验性)
```

## 关键特性

### State Manager v2
- JSON 文件持久化，原子写入防损坏
- 12-stage 依赖图自动拓扑排序
- `checkpoint` 机制：shot-level 进度恢复
- `params_hash` 参数变更检测 → 自动 dirty 标记
- `stale propagation`：上游变更自动重置下游
- 向后兼容：v1 state.json 自动迁移到 v2

### 并行执行
- `ThreadPoolExecutor` 安全并行无 GPU 竞争的 stage
- S8 (subtitles) + S9 (TTS) 可并行 (CPU-only)
- `--parallel` 标志触发，失败隔离 (单 stage 失败不影响其他)

## 设计原则

1. **AICB 移植，非重写**: Prompt 模板来自 `prompts/defaults/`，禁止硬编码 prompt builder
2. **声明式管线**: `pipeline.yaml` 是唯一真相源，stage 顺序/依赖/资源需求由 YAML 定义
3. **自修复**: 失败可重试，断点续跑，参数变更自动感知
4. **文本层 + 图像层双一致**: 角色 visualAnchors 注入 prompt (文本) + IPAdapter 注入 latent (图像)

## License

MIT
