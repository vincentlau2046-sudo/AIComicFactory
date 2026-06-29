# AIComicFactory 改造方案 v2

## 问题 1：重复图片

### 根因
S3/S5 脚本对每张图做了两次 copy：
1. `shutil.copy2(ComfyUI_output → 项目目录/老周.png)` — 规范命名
2. `am.register()` 内部又 `shutil.copy2(同一源 → 项目目录/char_character_ref_v7.png)` — 版本化命名

同一张图出现两份。

### 方案
**去掉 `shutil.copy2`，统一由 `am.register()` 完成文件归档。**

修改 `am.register()` 支持自定义目标文件名：
- S3 角色图 → `{name}.png`（如 `老周.png`）
- S5 关键帧 → `s{shot_num:02d}_{frame_type}.png`（如 `s01_first.png`）

脚本只调用一次 `am.register(source=ComfyUI输出, dest_name=规范名)`，register 内部做 `shutil.copy2` + 元数据记录 + 旧版本清理。

---

## 问题 2：SDXL → 双路径（动漫/写实）

### 方案

```
                    ┌─ 风格=anime ──→ S3/S5: Animagine XL (SDXL)
用户指定风格 ───────┤
                    └─ 风格=realistic → S3/S5: Flux.1 Dev FP8
```

| 维度 | 动漫路径 (SDXL) | 写实路径 (Flux) |
|------|----------------|----------------|
| **S3 模型** | Animagine XL 3.1 | Flux.1 Dev FP8 |
| **S5 模型** | Animagine XL 3.1 | Flux.1 Dev FP8 |
| **Prompt 格式** | comma-separated tags | 自然语言（T5-XXL 长文本） |
| **与 AICB prompt 兼容** | 需 Nova 转译为 tags | ✅ 天然兼容 |
| **角色一致性** | visualHint + anchors | T5 理解力更强 + Kontext LoRA |
| **VRAM** | ~6GB | FP8 ~12GB（5090D 充裕） |
| **速度** | ~8s/张 | ~25s/张 |
| **默认风格** | — | ✅ 默认写实 |

### 需下载模型

| 组件 | 文件 | 路径 | 大小 | 下载源 |
|------|------|------|------|--------|
| UNet | flux1-dev-fp8.safetensors | models/diffusion_models/ | ~12GB | HF: lllyasviel/flux1_dev |
| T5 | t5xxl_fp8_e4m3fn_scaled.safetensors | models/text_encoders/ | ~5GB | HF: comfyanonymous/flux_text_encoders |
| VAE | ae.safetensors | models/vae/ | ~300MB | HF: comfyanonymous/flux_text_encoders |
| CLIP | clip_l.safetensors | models/clip/ | ~250MB | ✅ 已有 |

总计 ~17.5GB 新下载。磁盘 291GB 可用，充裕。

### 脚本改动

```
s3_character_image.py --style realistic  (默认，Flux)
s3_character_image.py --style anime      (SDXL)

s5_frame_generate.py --style realistic   (默认，Flux)
s5_frame_generate.py --style anime       (SDXL)
```

`--style` 控制：
- checkpoint 选择
- workflow 模板（Flux 用 DualCLIPLoader + FluxGuidance + KSampler，SDXL 不变）
- prompt 构建逻辑（Flux 长自然语言 vs SDXL tags）

---

## 问题 3：S3 角色视图资产

### AICB 原方案
character_image.py prompt 定义了 2×2 四视图：
- 左上：正面视图
- 右上：3/4 侧视图
- 左下：侧面视图
- 右下：背面视图

### 当前问题
S3 只生成单正面全身图 → S5 角色侧面/背面无锚点 → 跨帧一致性差

### 方案：S3 拆为 S3a + S3b

```
S3a: Flux.1 Dev T2I → 单正面参考图 (1280×1280)
     输入: 角色描述 + visualAnchors
     输出: 角色正面全身图（最精确的锚点）

S3b: Flux Kontext / Klein LoRA → 四视图 turnaround (2560×1440)
     输入: S3a 参考图 + "generate turnaround sheet with front, 3/4, side, back views"
     输出: 2×2 四视图（提供多角度锚点给 S5/S6）
```

### S3b 需额外模型
- **Flux Kontext Character Turnaround Sheet LoRA** (reverentelusarca)
  - 或 **Flux.2 Klein 4-View Sprite Sheet LoRA**
  - 大小 ~100-300MB
  - 需调研哪个在 5090D + FP8 下效果最好

### 动漫路径
S3b 对 SDXL 动漫路径**可选**——Animagine XL 对四视图支持较差，
动漫风格可只用 S3a 单正面 + prompt 注入 visualAnchors。

---

## 改造执行顺序

1. **修复重复图片** — 改 am.register() + 清理 S3/S5 脚本
2. **下载 Flux 模型栈** — flux1-dev-fp8 + t5xxl + ae（~17.5GB）
3. **S3/S5 添加 Flux workflow** — --style 参数双路径
4. **S3b 四视图** — 下载 Turnaround LoRA，添加 S3b 步骤
5. **重跑 last_bento（realistic 风格）** — 验证全链路

---

## 分辨率链（不变）

```
S3a: 1280×1280 (角色参考图，正方形)
S3b: 2560×1440 (四视图，2×2 网格)
S5:  1280×720  (关键帧，横屏 720P) / 720×1280 (竖屏)
S6:  1280×720  (FLF2V 视频)
S7+: 1280×720  (成片)
```
