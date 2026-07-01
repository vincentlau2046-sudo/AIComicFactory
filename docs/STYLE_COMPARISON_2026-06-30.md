# S3/S5 风格对比测试 — 2026-06-30

## 测试目标
对比 3 种 SDXL 动漫模型在 last_bento 项目上的 S3 角色参考图 + S5 关键帧效果。

## 模型

| 模型 | 文件 | 大小 | 状态 |
|------|------|------|------|
| Animagine XL 3.1 | animagine-xl-3.1.safetensors | 6.5GB | ✅ 已安装，可工作 |
| AnimeXL-xuebiMIX v6.0 | animexl_xuebiMIX_v60.safetensors | 6.5GB | ✅ 已转换，可工作 |
| SDXL-Anime 天空之境 V3.1 | — | — | ❌ Civitai 不可达，无法下载 |
| ~~JuggernautXL v10~~ | ~~juggernautXL_v10.safetensors~~ | 6.7GB | ❌ 写实风格，不适合动漫 |

## xuebiMIX 转换过程

从 HuggingFace `stablediffusionapi/animexl-xuebimix` 下载 Diffusers 格式，转换为 ComfyUI safetensors checkpoint。

关键问题及修复：
1. **CLIP key 前缀**: `embedders.1.transformer` → `embedders.1.model`（SDXL 格式要求）
2. **UNet key 格式**: Diffusers (`down_blocks/up_blocks`) → CompVis (`input_blocks/output_blocks`)
3. **VAE key 格式**: Diffusers → CompVis（通过 `diffusers_convert.convert_vae_state_dict`）
4. **权限**: `chmod 644`（ComfyUI 需要可读权限）

## 生成进度

| 风格 | S3 参考图 | S5 first frames | S5 last frames | 备份 |
|------|----------|----------------|---------------|------|
| anime (Animagine XL) | ✅ 3/3 | ✅ 15/15 | ✅ 15/15 | s3_character_refs_anime/ s5_frames_anime/ |
| xuebi (xuebiMIX v6.0) | 🔄 生成中 | 🔄 生成中 | 🔄 生成中 | s3_character_refs_xuebi/ s5_frames_xuebi/ |
| sky (SDXL-Anime) | ❌ 模型未下载 | — | — | — |

## VL 质量评分 (anime 风格)

Animagine XL 3.1 平均 6.4/10（qw35-9b VL 评分不稳定，仅供参考）

## 下一步

1. 等 xuebi 生成完成
2. 运行 VL 质量检查对比
3. 尝试下载 SDXL-Anime 天空之境（需要 Civitai 访问或代理）
4. 让 Vincent 对比视觉效果选择默认风格
5. 更新 AICF SKILL.md 风格映射
