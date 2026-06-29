# AIComicFactory v1.0

基于 OpenClaw 调度的 AI 漫剧生产管线，移植自 AIComicBuilder (AICB) 的 Pipeline 拓扑 + Prompt 工程 + 数据模型，适配本地 ComfyUI + vLLM 环境。

## 管线架构 (8 Stages)

```
source.txt → S1(LLM) → S2(LLM) → S3(ComfyUI) → S4(LLM) → S5(ComfyUI) → S6(FLF2V) → S7(FFmpeg) → S8+S9(TTS)
```

| 阶段 | 脚本 | 引擎 | 说明 |
|------|------|------|------|
| S1 | Nova (OpenClaw) | LLM | 剧本解析：原文 → scenes + dialogues |
| S2 | Nova (OpenClaw) | LLM | 角色提取：5-dim visualAnchors |
| S3 | `scripts/s3_character_image.py` | ComfyUI SDXL | 角色参考图 (1280×1280) |
| S4 | `scripts/gen_s4_shots.py` / Nova | — | 分镜拆解 |
| S5 | `scripts/s5_frame_generate.py` | ComfyUI SDXL | 关键帧生成 (1280×720) |
| S6 | `scripts/s6_flf2v_render.py` | ComfyUI Wan2.2 | FLF2V 帧插值动画 |
| S7 | `scripts/s7_video_assemble.py` | FFmpeg | 视频拼接 + 转场 |
| S8 | `scripts/s8_subtitles.py` | FFmpeg | 字幕生成与烧录 |
| S9 | `scripts/s9_tts_audio.py` | ComfyUI Qwen3-TTS | TTS 语音 + 成片合成 |

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
完整依赖见 `conda run -n comfyui pip list`

### 工具链
- **FFmpeg**: S7 视频拼接 + S8 字幕
- **ImageMagick** (可选): 标题卡生成

## 项目结构

```
AIComicFactory/
├── core/               # ComfyUI session, asset manager, state manager
├── prompts/            # AICB prompt 模板 (character_extract, frame_generate, etc.)
│   └── defaults/       # 原始模板，禁止随意修改
├── scripts/            # S3-S9 管线脚本
├── templates/          # ComfyUI workflow JSON 模板
├── reference/          # AICB 源码参考 (TypeScript)
├── tests/              # L0 (unit) / L1 (integration) / L2 (smoke)
├── docs/               # 架构分析、升级计划
└── projects/           # 项目数据
    └── <project_name>/
        ├── source.txt          # 原始剧本
        ├── s1_parsed.json      # S1 输出
        ├── s2_characters.json  # S2 输出
        ├── prompts.json        # S3+S5 预生成 prompt
        ├── s4_shots.json       # S4 输出
        ├── s3_character_refs/  # S3 输出 (不入 git)
        ├── s5_frames/          # S5 输出 (不入 git)
        └── ...
```

## 使用方式

### 新项目全链路

```bash
# 1. 准备 source.txt
# 2. OpenClaw: Nova 生成 S1/S2/S4
# 3. 生成 prompt
conda activate comfyui
python scripts/gen_prompts.py  # 从 S2+S4 生成 SDXL prompts
# 4. 执行 S3-S9
python scripts/s3_character_image.py --project <name> --style anime
python scripts/s5_frame_generate.py --project <name> --style anime --prompts-file projects/<name>/prompts.json
python scripts/s6_flf2v_render.py --project <name>
python scripts/s7_video_assemble.py --project <name>
python scripts/s8_subtitles.py --project <name>
python scripts/s9_tts_audio.py --project <name>
```

### 风格切换

```bash
--style anime      # SDXL Animagine XL 3.1 (默认)
--style realistic  # Flux.1 Dev FP8 (实验性)
```

## 设计原则

1. **AICB 移植，非重写**: Prompt 模板来自 `prompts/defaults/`，禁止硬编码 prompt builder
2. **Nova 是 LLM**: S1/S2/S4 由 Nova 直接生成，不通过 Python 调用外部 LLM API
3. **SD 是默认**: `--style anime` 为默认路径，realistic/Flux 为实验分支
4. **文本层 + 图像层双一致**: 角色 visualAnchors 注入 prompt (文本) + IPAdapter 注入 latent (图像，待实现)

## License

MIT