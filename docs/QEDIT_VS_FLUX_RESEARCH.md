# 调研：S5 纯场景 Shot 改用 qwen-image-edit 的可行性

## 问题定义

当前 S5 架构存在双通道：
- **有角色参考图** → qwen-image-edit (qedit) 管线
- **无角色参考图（纯场景/空镜）** → Flux Dev T2I 管线

问题：风格不一致。Flux 原生风格 vs qedit 风格。

## qedit 工作流架构分析

### 核心节点依赖

```
LoadImage (reference.png)    → TextEncodeQwenImageEditPlus (image1)
LoadImage (reference_padded) → VAEEncode                     (latent)
CLIPTextEncode               → KSampler (positive)
```

**TextEncodeQwenImageEditPlus** 节点：
- `image1` 参数：**必填**（ComfyUI 节点定义要求）
- 参考图同时驱动：CLIP text encoder 的视觉 tokenization + 图像条件

### 关键发现

**qedit 不能"裸跑"**——`TextEncodeQwenImageEditPlus` 节点没有 `image1=None` 的路径。即使传入纯色图或空白占位图，VAE encode 后仍然会产生非零 latent，导致输出包含占位图的视觉特征。

## 方案评估

### 方案 A：占位图替代参考图
- **做法**：生成纯色/渐变/噪点图作为参考，纯靠 prompt 驱动
- **结论**：❌ 不可行
  - qedit 是"image editing"模型，参考图 encode 后的 latent 会注入生成
  - 纯色图 → 输出偏向纯色；噪点图 → 输出不可控
  - 官方文档明确：qwen-image-edit = 参考图编辑，非纯文本生成

### 方案 B：场景资产参考图
- **做法**：为纯场景 shot 预生成"风格参考图"（如用 Flux T2I 出图后作为 qedit 参考）
- **结论**：⚠️ 理论可行，实际低效
  - 等于"先用 Flux 出场景底图 → 再用 qedit 编辑"，多跑一步
  - 对纯空镜（无角色、无内容变更），编辑=无操作，浪费 GPU
  - 对半场景半角色（如"老周站在办公室"），qedit 已有角色参考图

### 方案 C：双通道保留 + 统一后处理
- **做法**：保持双通道，但统一色彩分级/风格
- **结论**：✅ 推荐方案
  - Flux T2I 出图质量高，纯场景 prompt 表达力强
  - qedit 适合"角色+场景"混合镜头
  - 风格不一致是真实问题 → 通过 S6 FLF2V 过渡帧 + S7 色彩匹配解决

### 方案 D：Flux Dev T2I → qedit 风格迁移（后处理）
- **做法**：Flux T2I 出图后，用 qedit 做"风格统一编辑"（以项目风格参考图为参考）
- **结论**：❌ 过度复杂
  - 增加 S5.5 stage，GPU 成本翻倍
  - 风格一致性更多靠 prompt engineering 而非模型切换

## 根本原因分析

**风格不一致的根因不是模型选择**，而是：

1. **Prompt 风格不统一**：T2I 和 qedit 使用相同的 `build_first_prompt`，但模型对同一 prompt 的解释不同
2. **色彩分布差异**：Flux fp8 vs qedit fp8mixed 的色彩空间不同
3. **分辨率不一致**：T2I 出 1280×720，qedit 出 1280×720 — 已统一 ✅

## 推荐方案

### 短期（立即可用）

**统一 Prompt + 色彩匹配**：
- S7 已有 Pillow PNG 色彩校正（可增强为 LUT 色彩统一）
- 在 `build_first_prompt` 中注入全局风格锚点（项目级 colorPalette）
- Flux T2I 和 qedit 使用相同的色彩/光影描述

### 中期（架构改进）

**引入项目级风格参考图**：
```
S3 新增: 生成 3-5 张"项目风格参考图"（主场景、色调、构图）
S5 改造: 
  - 纯场景 shot → Flux T2I + 风格参考图注入 prompt
  - 角色 shot → qedit（不变）
S7 增强: 全局 LUT 色彩统一（可选）
```

### 长期（模型层）

**统一为 qedit 的替代路径**：
- 用 **Flux Dev 的 reference 功能**（非 ComfyUI 限制，是模型原生能力）
- 即：Flux Dev 本身有 IPAdapter/reference 能力
- 需要：在 ComfyUI 中为 Flux Dev 添加 reference conditioning

## 结论

**不建议用 qedit 替代 Flux T2I**。原因：
1. qedit 不是 T2I 模型，架构上不支撑无参考图生成
2. 双通道是合理设计：T2I 负责纯文本→图像，qedit 负责参考图→编辑
3. 风格不一致的真正解法是 prompt 统一 + 后处理色彩匹配
4. 强行统一为 qedit 会导致无参考图场景无法工作，或需要多步 pipeline

**建议**：保持双通道，在 S7 增加可选的色彩统一 LUT 处理。
