# AIComicFactory Skill

**版本**: v1.1.0
**创建**: 2026-06-28
**更新**: 2026-06-29 (T2/T3/T4: 一致性专项)
**定位**: AI 驱动的漫剧生产工作流 — 基于 OpenClaw 调度

---

## 概述

AIComicFactory 是一条完整 AI 漫剧生产管线。输入原始剧本，输出成片视频+字幕。

10 个阶段，前 3 个（S1/S2/S4）由 OpenClaw 直接调用 LLM 完成，后 7 个（S3/S3b/S5/S6/S7/S8/S9）由 Python 脚本驱动 ComfyUI + FFmpeg + Whisper。

### 触发词

| 命令 | 说明 |
|------|------|
| `做 {project}` | 从断点续跑指定项目 |
| `继续做` | 续跑当前项目 |
| `重做 {stage} {project}` | 标记脏，从指定阶段重跑 |
| `看进度` | 读 state.json，汇报所有阶段状态 |
| `执行 {stage} {project}` | 单独跑指定阶段 |
| `只跑到 {stage}` | 执行到指定阶段后暂停 |

### 项目结构

```
~/AIComicFactory/
├── SKILL.md              # 本文件
├── PROJECT.md            # 项目总纲
├── PROGRESS.md           # 实施进度
├── prompts/              # Prompt Registry（12 个 prompt）
│   ├── registry.py       # 注册表
│   ├── defaults/         # 原样移植 AICB prompt
│   └── overrides/        # 用户覆盖
├── core/                 # 引擎模块
│   ├── state_manager.py  # 管线状态管理
│   ├── prompt_runner.py  # prompt 构建器
│   ├── asset_manager.py  # 版本化资管
│   ├── continuity_check.py # 连续性检查 (LLM vision)
│   └── __init__.py
├── scripts/              # Python 脚本（S3/S3b/S5/S6/S7/S8/S9）
├── templates/            # ComfyUI workflow JSON
├── projects/             # 项目数据
└── docs/                 # 文档
```

---

## 工作流

### 1. 准备项目

```
mkdir -p projects/{project}
cp /path/to/source.txt projects/{project}/source.txt
```

### 2. 执行流程

每阶段完成后自动更新 state.json，下一阶段根据依赖关系自动触发。

```
source.txt → s1_parse → s2_character_extract → s3_character_image → s3b_four_view → s4_shot_split → s5_frame_generate → s6_video_generate → s7_assemble → s8_subtitles → s9_tts_audio
```

---

## 实现细节

### S1: 剧本解析 (script_parse)

**引擎**: OpenClaw LLM（baidu-codingplan DEEPSEEK_PRO）
**输入**: `projects/{project}/source.txt`
**输出**: `projects/{project}/s1_parsed.json`
**Prompt**: `prompts/defaults/script_parse.py → ScriptParsePrompt`

### S2: 角色提取 (character_extract)

**引擎**: OpenClaw LLM
**输入**: `s1_parsed.json`
**输出**: `s2_characters.json`（含 name/scope/description/visualHint/visualAnchors/personality/heightCm/bodyType/performanceStyle + relationships）
**一致性增强**: `visualAnchors` 字段提供高密度视觉关键词（face/hair/body/clothing/signature），注入下游 S3/S5 prompt

### S3: 角色参考图 (character_image)

**引擎**: ComfyUI (Animagine XL 3.1 T2I)
**输入**: `s2_characters.json`
**输出**: `s3_character_refs/{name}.png`
**脚本**: `scripts/s3_character_image.py --project {project}`
**分辨率**: 1024×1024 (SDXL 原生 square，面部精度最大化)
**风格**: comic (Animagine XL 3.1) / realist (Juggernaut XL v2)

### S3b: 四视图扩展 (four_view)

**引擎**: ComfyUI (Qwen Image Edit 2511 + Lightning LoRA)
**输入**: `s3_character_refs/{name}.png`
**输出**: `s3b_four_views/{name}_fourview.png`
**脚本**: `scripts/s3b_four_view.py --project {project} [--style comic|realist]`
**说明**: 基于 S3 单视图，使用 Qwen Image Edit 扩展为 front/3-4/side/back 四视图
**分辨率**: 1024×1024 (与 S3 一致，零降级)

### S4: 分镜拆解 (shot_split)

**引擎**: OpenClaw LLM
**输入**: `s1_parsed.json` + `s2_characters.json`
**输出**: `s4_shots.json`（scene→shot 分组，含 prompt/motionScript/videoScript/cameraDirection/compositionGuide/transitionIn·Out 等）

### S5: 关键帧生成 (frame_generate)

**引擎**: ComfyUI (Qwen Image Edit 2511, reference-driven)
**输入**: `s4_shots.json` + 角色参考图 (S3/S3b)
**输出**: `s5_frames/s{NN}_first.png` + `s5_frames/s{NN}_last.png`
**脚本**: `scripts/s5_frame_generate.py --project {project} [--mode first|last|both]`
**T4 重构**: 首帧从角色参考图生成，尾帧基于首帧生成，保证首尾帧逻辑关联
**分辨率**: 1024×576 (16:9 landscape，与 S6 完全匹配)

### S6: FLF2V 视频渲染 (video_generate)

**引擎**: ComfyUI (Wan2.2 FLF2V + Lightx2v 4-step + TeaCache + SageAttention)
**输入**: `s5_frames/` 首尾帧 + `s4_shots.json` videoScript
**输出**: `s6_videos/s{NN}.mp4`
**脚本**: `scripts/s6_flf2v_render.py --project {project}`
**分辨率**: 1024×576 (16:9 landscape，与 S5 完全匹配，零 resize)

**5s 上限处理**: >125 帧 (5s@25fps) 的 shot 自动分段——生成中帧 → 多段 FLF2V → ffmpeg concat。对分镜透明。

### S7: 视频拼接 (video_assemble)

**引擎**: Pillow + FFmpeg xfade + concat
**输入**: `s6_videos/` MP4 clips + `s4_shots.json` title + transitions
**输出**: `s7_assembled.mp4` (标题卡 + xfade 转场 + 全 clip 拼接 + 结束卡)
**转场**: 7 种 AICB 转场 (cut/dissolve/fade_in/fade_out/wipeleft/slideright/circleopen)
**脚本**: `scripts/s7_video_assemble.py --project {project} [--transition-duration 0.5]`

### S8: 字幕 (subtitles)

**引擎**: ASS 时间轴计算 + FFmpeg ass filter
**输入**: `s4_shots.json` dialogues + `s7_assembled.mp4`
**输出**: `s8_subtitles.ass` + `s7_with_subtitles.mp4`
**脚本**: `scripts/s8_subtitles.py --project {project}`

### S9: TTS 语音 + ASR 对齐 (tts_audio)

**引擎**: Qwen3-TTS + Whisper ASR + ffmpeg mux
**管线**: TTS 逐条合成 → 串行拼接 → Whisper 回听 → SRT → 脚本矫正 → ASS → 音视频合轨
**输出**: `s7_final.mp4` (含语音+精确字幕)
**脚本**: `scripts/s9_tts_audio.py --project {project}`

---

## 关键决策

| # | 决策 | 方案 |
|---|------|------|
| D3 | LLM | baidu-codingplan (主) + Qwen3.6-27B (备) |
| D4 | 结构化输出 | 纯 prompt 约束（GPT-4 级不须 guided_json） |
| D8 | 数据持久化 | 文件系统 JSON（projects/{project}/state.json） |
| D9 | UI | 无（OpenClaw 对话调度） |
| D10 | 角色一致性 | Qwen Image Edit 2511 (S3b 四视图 + S5 参考图驱动) |
| D11 | 风格 | comic (Animagine XL 3.1) / realist (Juggernaut XL v2) |

详见 `PROJECT.md` 第七章。

---

## 文件路由

```
projects/
└── {project}/
    ├── source.txt            # 原始剧本
    ├── state.json            # 管线状态
    ├── s1_parsed.json        # S1: 结构化剧本
    ├── s2_characters.json    # S2: 角色规格
    ├── s3_character_refs/    # S3: 角色参考图 PNG
    ├── s3b_four_views/       # S3b: 四视图参考图 PNG
    ├── s4_shots.json         # S4: 分镜 (含 shotNumber 顺序编号)
    ├── s5_frames/            # S5: 首尾帧 PNG
    ├── s6_videos/            # S6: FLF2V 视频片段 MP4
    ├── s7_assembled.mp4      # S7: 拼接视频 (含标题卡)
    ├── s7_with_subtitles.mp4 # S8: 字幕烧录版
    ├── s9_final.mp4          # S9: 最终成品
└── assets.json           # 资产版本表
```

---

## 环境依赖

### ComfyUI 模型

| 用途 | 模型文件 | 路径 |
|------|---------|------|
| S3 T2I (comic) | animagine-xl-3.1.safetensors | models/checkpoints/ |
| S3b/S5 Qwen Edit | qwen_image_edit_2511_fp8mixed.safetensors | models/diffusion_models/ |
| S3b/S5 VAE | qwen_image_vae.safetensors | models/vae/ |
| S3b LoRA (可选) | Qwen-Image-Edit-2511-Lightning-8steps-V1.0-fp32.safetensors | models/loras/ |
| S5 T2I (realist) | juggernautXL_v10.safetensors | models/checkpoints/ |

### ComfyUI 节点

| 节点 | 来源 | 说明 |
|------|------|------|
| TextEncodeQwenImageEdit | ComfyUI v0.24+ 原生 | 单参考图编码 |
| TextEncodeQwenImageEditPlus | ComfyUI v0.24+ 原生 | 多参考图编码（最多3张） |
| LoraLoader | ComfyUI 原生 | LoRA 加载 |

### Python 环境

- **ComfyUI env** (Python 3.12): 运行所有 S3/S5/S6/S7/S8/S9 脚本
- 依赖: torch, transformers, diffusers, whisper, TTS, ffmpeg

---

## 风格切换

Comic 和 Realist 两套风格通过 `--checkpoint` + `--style` 参数切换：

| 风格 | S3 Checkpoint | S5/S3b Checkpoint | 风格参数 |
|------|--------------|-------------------|---------|
| comic | animagine-xl-3.1.safetensors | qwen_image_edit_2511_fp8mixed.safetensors | --style comic |
| realist | juggernautXL_v10.safetensors | qwen_image_edit_2511_fp8mixed.safetensors | --style realist |

**注意**: Qwen Image Edit 模型通用，风格通过 prompt 中的风格标签控制。
