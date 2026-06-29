# AIComicFactory 测试报告 (最终版)

**日期**: 2026-06-29 21:10 CST
**环境**: Python 3.13.13, pytest 9.1.1, RTX 5090 D, ComfyUI on :8188

---

## 总览

| 指标 | 值 |
|------|-----|
| **总用例** | 110 |
| **通过** | **110 ✅** |
| **失败** | 0 |
| **覆盖率 (L0+L1)** | **81%** |
| **全量耗时** | 64.2s |

---

## L0: 纯逻辑 — 78 ✅ | L1: 集成 — 24 ✅ | L2: 冒烟 — 8 ✅

| L2 测试 | 状态 | 耗时 | 说明 |
|---------|------|------|------|
| S3 角色参考图 | ✅ | 10s | Animagine XL T2I |
| S5 prompt+workflow | ✅ | <1s | 结构验证 |
| S5 图像生成 | ✅ | 44s | Qwen Image Edit (修复后) |
| S6 FLF2V 视频渲染 | ✅ | 16s | 首尾帧→25fps clip |
| S7 转场+视频验证 | ✅ | <1s | ffprobe |
| S8 ASS 字幕 | ✅ | <1s | 格式验证 |
| S9 TTS 音频 | ✅ | <1s | 音频流验证 |
| S1+S2+S4 文本链路 | ✅ | ~10min | 千帆 API (单独运行) |

---

## S5 Bug 修复详情

### 根因
`qwen_image_edit_2511_fp8mixed.safetensors` checkpoint **不包含标准 CLIP**。
`CheckpointLoaderSimple` 返回 CLIP=None → `CLIPTextEncode` 负向节点失败。

### 调查过程
1. ComfyUI 报错: `clip input is invalid: None`
2. 检查 checkpoint 内部: `txt_in.weight: shape=[3072, 3584]` → Qwen2.5-VL 7B 维度，非标准 CLIP
3. 找到 ComfyUI 已有工作流 `Vantage-Qwen-Image-Edit-2511.json` → **正确架构**
4. 验证: UNETLoader + CLIPLoader(type=qwen_image) + VAELoader → ✅ 成功生成图像

### 修复方案 (非 CLIPLoader，而是架构重构)

| 旧架构 (broken) | 新架构 (fixed) |
|------------------|----------------|
| CheckpointLoaderSimple | UNETLoader + CLIPLoader + VAELoader |
| CLIPTextEncode (负向) | TextEncodeQwenImageEditPlus (负向) |
| euler_ancestral / normal | euler / simple |
| EmptyLatentImage | VAEEncode(参考图) |
| 无 shift | ModelSamplingAuraFlow(shift=3.1) |
| LoraLoader | LoraLoaderModelOnly |

### 关键发现
- **CLIP 来自独立 CLIPLoader**: `qwen_2.5_vl_7b_fp8_scaled.safetensors`, type=`qwen_image`
- **负向编码也用 TextEncodeQwenImageEditPlus**: Qwen 的 CLIP 不兼容 CLIPTextEncode
- **latent 来自 VAEEncode(参考图)**: 而非 EmptyLatentImage，因为 Edit 模式需要参考图 latent
- **需要 ModelSamplingAuraFlow**: shift=3.1 (Qwen Image Edit 专用)
