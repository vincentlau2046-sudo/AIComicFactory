# AIComicFactory 原子工作流参考手册

## 概述

7 个原子工作流，覆盖动漫漫画管线全部 AI 生成环节。
每个工作流=ComfyUI JSON + .meta.yaml（参数映射）。
工作流之间通过 Pipeline YAML 编排，不直接耦合。

---

## 1. `qwen-2512-t2i` — 纯文生图

| 维度 | 内容 |
|------|------|
| **用途** | 从文本描述直接生成图像。无参考图依赖 |
| **场景** | 场景帧（纯背景）、角色正面参考图、任何需要"从零生成"的图像 |
| **模型** | Qwen Image 2512 fp8 UNET (20.4GB) + nvfp4 TE (5.7GB) |
| **输入** | prompt(string), seed, steps, cfg, width, height |
| **输出** | 单张 PNG |
| **默认参数** | steps=20, cfg=3.5, 1024×1024 |
| **VRAM** | ~26GB |
| **耗时** | ~35s (20步) |
| **验证** | ✅ 人像全身、猫、狗、公园场景均通过 |

---

## 2. `qwen-2511-edit` — 场景+单角色合成

| 维度 | 内容 |
|------|------|
| **用途** | 内嵌T2I生成场景 → latent直通Edit → 嵌入角色参考图 |
| **场景** | 分镜帧生成：角色在指定场景中，（如人像→公园战斗） |
| **模型** | Qwen Image 2511 Edit fp8mixed UNET (20.5GB) + nvfp4 TE (5.7GB) |
| **输入** | scene_prompt(string), composite_prompt(string), character_ref(image), seed, steps, cfg |
| **关键输入** | `scene_prompt`: T2I场景描述；`composite_prompt`: 合成描述，用"Picture 1"引用角色ref |
| **架构** | 双KSampler: T2I→scene latent→Edit→output。**不经过VAE decode/encode**, latent直通 |
| **输出** | 单张PNG（角色嵌入场景） |
| **默认参数** | steps=20, cfg=3.0, 1024×1024 |
| **VRAM** | ~27GB |
| **耗时** | ~70s (20+20步) |
| **验证** | ✅ 角色一致性OK, 色彩自然（latent直通修复后） |
| **注意** | 角色ref图的分辨率应与目标输出分辨率匹配，避免拉伸 |

---

## 3. `qwen-2511-edit-plus` — 场景+多角色合成(≤3)

| 维度 | 内容 |
|------|------|
| **用途** | 内嵌T2I生成场景 → latent直通EditPlus → 嵌入≤3张角色参考图 |
| **场景** | 多角色同框：英雄+反派同场景、人+宠物同镜 |
| **模型** | 同`qwen-2511-edit` |
| **输入** | scene_prompt, composite_prompt, character_ref_1~3(image), seed, steps, cfg |
| **关键输入** | `composite_prompt`中用"Picture 1/2/3"分别引用各角色ref |
| **架构** | 同`qwen-2511-edit`, 但使用TextEncodeQwenImageEditPlus + 多LoadImage |
| **输出** | 单张PNG（多角色嵌入场景）|
| **默认参数** | steps=20, cfg=3.0 |
| **VRAM** | ~27-28GB（3 refs时略高）|
| **耗时** | ~35s |
| **验证** | ✅ 人+猫+狗+公园场景合成, 一致性可接受 |
| **注意** | ref图用"Picture N"标签引用；ref图分辨率应与输出匹配 |

---

## 4. `qwen-2511-edit-multiangle` — 多角度相机控制

| 维度 | 内容 |
|------|------|
| **用途** | 输入正面全身像 → 生成指定视角（3/4侧面/侧面/背面） |
| **场景** | 角色四视图、角色设定稿 |
| **模型** | Qwen 2511 Edit fp8mixed + Multi-Angle LoRA (281MB) + Lightning LoRA (811MB) |
| **依赖** | `qwen-image-edit-2511-multiple-angles-lora.safetensors` (已下载) |
| **依赖** | `Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors` (已下载) |
| **输入** | source_image, prompt(角度描述), seed, steps, lightning_strength, angle_strength |
| **Prompt格式** | `<sks> [azimuth] [elevation] [distance]` |
| **示例** | `"<sks> right side view eye-level shot medium shot"` |
| **支持角度** | 8方位×4高度×3距离 = 96预设位置 |
| **关键节点** | FluxKontextMultiReferenceLatentMethod, FluxKontextImageScale, CFGNorm |
| **输出** | 单张PNG（新视角） |
| **默认参数** | steps=4 (Lightning LoRA), cfg=1.0, angle_strength=1.0, lightning_strength=0.8 |
| **VRAM** | ~27GB |
| **耗时** | ~5-10s (4步) |
| **验证** | ✅ `right side view`, `front-right quarter view`, `back view`均通过 |
| **注意** | • 输入必须是**全身正面像**（非半身）<br>• 参考图分辨率影响视角质量<br>• 配合`merge_fourview.py`合成四视图 |

---

## 5. `h3-t2v` — H3 文生视频+音频

| 维度 | 内容 |
|------|------|
| **用途** | 纯文本描述 → 生成短视频+原生立体声 |
| **场景** | 概念展示、纯文字驱动的动画片段 |
| **模型** | MiniMax H3 FL2VA nvfp4 UNET (12GB) + 32B TE (15GB) + VAEx2 |
| **输入** | prompt(string), seed, steps, cfg, width, height, length(帧数) |
| **架构** | KSamplerSelect(res_multistep) + BasicScheduler + RandomNoise + BasicGuider + SamplerCustomAdvanced |
| **关键参数** | **sampler=res_multistep, cfg=1.0**（否则雪花严重）|
| **输出** | MP4视频（含音频） |
| **默认参数** | steps=20, cfg=1.0, sampler=res_multistep, scheduler=simple |
| **VRAM** | ~27GB（TE 15G + UNET 12G） |
| **耗时** | ~100s (20步) |
| **修复记录** | 原sampler=uni_pc_bh2, cfg=7.0 → 雪花严重。改为官方配置后雪花消失 |

---

## 6. `h3-i2v` — H3 首帧→视频+音频

| 维度 | 内容 |
|------|------|
| **用途** | 输入一张参考图 → 生成视频+音频 |
| **场景** | 关键帧动画：取分镜帧的首帧/尾帧生成动画片段 |
| **模型** | 同`h3-t2v` |
| **输入** | first_frame(image), prompt, seed, steps, cfg, width, height, length |
| **关键要求** | **参考图分辨率必须与视频输出分辨率一致**（否则人物拉伸）|
| **架构** | 同`h3-t2v`，加LoadImage→first_frame |
| **输出** | MP4视频（含音频） |
| **默认参数** | steps=20, cfg=1.0 |
| **VRAM** | ~27GB |
| **耗时** | ~100s (20步) |
| **验证** | ✅ 一致性OK, 雪花已消除 |
| **注意** | 参考图比例不对→人物被拉扁。生产中用同分辨率的合成图 |

---

## 7. `h3-r2v` — H3 多参考图→视频+音频

| 维度 | 内容 |
|------|------|
| **用途** | 输入≤10张参考图+文字 → 生成视频+音频 |
| **场景** | 角色参考动画：用多张角色设定图生成动画 |
| **模型** | MiniMax H3 Ref2VA nvfp4 UNET (12GB) + 32B TE (15GB) + VAEx2 |
| **输入** | ref_images(≤10张), prompt, seed, steps, cfg, width, height, length |
| **Prompt格式** | `<Picture 1> / <Picture 2>` 等标签引用参考图 |
| **架构** | 同`h3-i2v`，但使用MiniMaxH3ReferenceToVideo节点 |
| **输出** | MP4视频（含音频） |
| **默认参数** | steps=20, cfg=1.0 |
| **VRAM** | ~27GB |
| **耗时** | ~160s (20步, 多ref加载) |
| **验证** | ✅ API格式修复(ref_images dict), 雪花已消除 |
| **注意** | ref_images需用API dict格式：`{"ref_image_1": [node, 0]}` |

---

## GPU 调度速查

| 模型组 | 包含工作流 | 总VRAM | 切换成本 |
|--------|----------|--------|---------|
| Qwen Image 2512 | `qwen-2512-t2i` | ~26GB | — |
| Qwen Image 2511 | `qwen-2511-edit`, `edit-plus`, `multiangle` | ~27GB | ComfyUI自动卸载 |
| MiniMax H3 | `h3-t2v`, `h3-i2v`, `h3-r2v` | ~27GB | ComfyUI自动卸载 |

文本推理（IFF Proxy :8999）独立于ComfyUI，无GPU冲突。

## 辅助工具

| 工具 | 用途 |
|------|------|
| `merge_fourview.py` | 四视图→横向合成图, 自动对齐+角度标签+角色名 |
| `validate_workflow.py` | 完整性验证: SHA256+模型存在+参数白名单 |
| `Pipeline YAML` (待Phase 2) | 原子工作流编排引擎 |