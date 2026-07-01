# AICF 工具链统一方案 — 关联分析与实施计划

**日期**: 2026-07-02
**输入**: Vincent 确认工具链统一决策
**核心变更**: S3 ref 用 Flux Dev → S3b/S5 统一用 qedit → S6 不变

---

## 一、工具链统一后的架构

```
S3  角色ref图:  Flux Dev fp8 (T2I, 1024×1024)
S3b 四视角:     qwen-image-edit ReferenceLatent (qedit, 1024×1536)
S5  首帧+尾帧:  qwen-image-edit ReferenceLatent (qedit, 1024×1536)
S6  视频生成:   Wan2.2 FLF2V (不变)
```

### 变更前后对比

| Stage | 变更前 | 变更后 | 变化 |
|-------|--------|--------|------|
| S3 ref | Animagine XL / xuebiMIX / JuggernautXL (SDXL) | **Flux Dev fp8** | 模型替换 |
| S3b 四视角 | qedit (已验证) | qedit (不变) | ✅ |
| S5 首帧 | qedit (已验证) | qedit (不变) | ✅ |
| S5 尾帧 | qedit (已验证，首帧作VAEEncode输入) | qedit + **多角色参考图注入** | 增强 |
| S6 视频 | FLF2V | FLF2V | ✅ 不变 |

---

## 二、关联分析

### 2.1 S3: Animagine XL → Flux Dev

**直接影响**:
- **模板替换**: `t2i_character_ref.json` (9节点, SDXL CheckpointLoaderSimple) → 新 Flux Dev 工作流
- **Prompt 体系变更**: SDXL 用 Danbooru tags / 自然语言混合 → Flux Dev 纯自然语言 prompt，效果更优
- **分辨率**: SDXL 1024×1024 → Flux Dev 可选 1024×1024 或 1024×1536（推荐 1024×1536，与 S3b/S5 对齐）
- **推理步数**: SDXL 25步 euler_ancestral → Flux Dev 20-28步 euler（无 LoRA 加速时）
- **VRAM**: SDXL ~6GB → Flux Dev fp8 ~12GB（5090D 32GB 充足）

**对 S3b 的关联影响**:
- S3b qedit 的输入参考图 = S3 产出。**Flux Dev 画质优于 Animagine XL**，S3b qedit 四视角的质量上限随之提升
- 参考图分辨率从 1024×1024 → 1024×1536，与 S3b/S5 完全对齐，**消除分辨率不一致导致的 qedit latent 变形**
- 当前 S3b qedit 使用 `ref_dir / f"{name}.png"` 作为参考图，路径不变，只是源图质量提升

**对 S5 的关联影响**:
- S5 `_find_character_ref_image()` 查找 `s3_character_refs/{name}_front.png`（qedit 四视角产出），不直接依赖 S3 ref 图
- 但 S3b 的四视角质量受 S3 ref 影响，间接影响 S5

**对 Prompt 系统的关联影响**:
- 当前 `_build_concept_prompt()` 生成的 prompt 是 Danbooru tags 风格（`1girl, silver hair, ...`）
- Flux Dev 纯自然语言 prompt，需重写 prompt 构建函数
- 这与 P0-4（S3/S5 统一走 Prompt 系统）可以合并处理

**必须新增**:
| # | 项目 | 说明 |
|---|------|------|
| N1 | **Flux Dev T2I 工作流模板** | `templates/flux_dev_t2i.json`，需新建 |
| N2 | **Flux Dev prompt 构建函数** | 替换 `_build_concept_prompt()`，自然语言描述式 |
| N3 | **S3 `_run_t2i()` 重写** | 从 CheckpointLoaderSimple → UNETLoader + DualCLIPLoader + VAELoader 架构 |

**Flux Dev 工作流架构** (预估 12 节点):
```
UNETLoader(flux1-dev-fp8) → KSampler
DualCLIPLoader(clip_l + t5xxl) → CLIPTextEncode(positive + negative)
VAELoader(ae.safetensors) → VAEDecode
EmptyLatentImage(1024×1536) → KSampler.latent_image
SaveImage
```

### 2.2 S3b: qedit 四视角 (不变，但需增强 prompt)

**与 S3 的关联**:
- S3b 依赖 S3 产出的 `{name}.png` 作为参考图
- S3 换 Flux Dev 后，参考图质量提升 → S3b 产出质量间接提升
- ✅ 无需改 S3b 工作流

**待完善** (P1-1 已列出):
- `build_qedit_view_prompt()` 应注入 visualAnchors + 画风锚定 + 一致性约束

### 2.3 S5: qedit 首帧+尾帧 (需增强多角色+前帧)

**核心变更**: 多角色参考图注入 + 前帧连续性接入

**当前问题**:
- `generate_frame()` 只接收1张 `ref_image_name`，传入 node 41 (LoadImage)
- 多角色场景只取第一个角色的参考图
- 前帧 `prev_input_name` 已上传但未注入工作流

**解决方案**: 扩展 qedit 工作流模板，支持多参考图

#### 方案: 扩展 `qwen_edit_frame.json` 支持多参考图

`TextEncodeQwenImageEditPlus` 支持 `image1/image2/image3` 三个可选输入。当前模板中 node 68 的 `image1` 已链接到 node 41 (LoadImage)。需要：

1. **新增 LoadImage 节点**: node 42 (image2)、node 43 (image3)
2. **链接到 node 68**: `image2: ["42", 0]`, `image3: ["43", 0]`
3. **新增 VAEEncode 节点**: node 76 (image2)、node 77 (image3) — 仅在 image 需要作为 latent 时
4. **S5 `inject_params()` 扩展**: 支持注入 `42: {image: ...}`, `43: {image: ...}`

**简化方案**: 由于 `image1/image2/image3` 是可选输入，且 node 68 已有 `image1`，只需要：
- 新增 node 42, 43 (LoadImage)
- 链接 `image2: ["42", 0]`, `image3: ["43", 0]`
- `inject_params` 中可选注入 `42: {image: ...}` 和 `43: {image: ...}`

**前帧连续性**:
- 前帧作为 `image2` 注入 node 68（多角色场景时 image2=角色2, image3=前帧）
- 或前帧作为 VAEEncode 输入（当前逻辑，首帧作 VAEEncode 用于尾帧生成）

**关联影响**:
- `build_qedit_frame_workflow()` 签名需扩展：增加 `ref_image2`, `ref_image3` 参数
- `generate_frame()` 签名需扩展：增加 `ref_images: list[str]` 参数
- S5 主循环中多角色 ref 查找逻辑需改写：取所有角色参考图而非只取第一个
- 模板 `qwen_edit_frame.json` 从 19 节点 → ~21 节点

### 2.4 S6: FLF2V (不变)

✅ 无关联影响。

### 2.5 跨阶段关联

**Prompt 系统统一 (P0-4)**:
- S3 换 Flux Dev 后，prompt 构建函数需重写（N2）
- 正好可以同时让 S3/S5 统一走 `prompts/defaults/` 模板系统
- S3 应调用 `character_image.py` 的 `build_full_prompt()` → 结果传入 Flux Dev 工作流
- S5 应调用 `frame_generate_first.py` / `frame_generate_last.py` 的 `build_full_prompt()` → 结果传入 qedit 工作流

**S4 keyframe_assets 解耦 (P0-5)**:
- 与工具链统一无直接关联，但 S5 prompt 来源依赖 S4 产出
- S4 解耦后，S5 的 `sh.get("prompt")` 改为从 S4b 产出的 `startFrame/endFrame` prompt 读取
- 这会影响 S5 prompt 的构建方式，应在 S5 重写时一并考虑

**参考图分辨率一致性**:
- 当前: S3 Animagine XL 1024×1024 → S3b qedit 1024×1536 → S5 qedit 1024×1536
- 统一后: S3 Flux Dev 1024×1536 → S3b qedit 1024×1536 → S5 qedit 1024×1536
- **全部对齐为 1024×1536**，消除分辨率不一致

---

## 三、工作流模板变更汇总

| 模板 | 变更 | 新增节点 |
|------|------|---------|
| `t2i_character_ref.json` | **替换**为 `flux_dev_t2i.json` | 12节点 (原9节点) |
| `qwen_edit_four_view.json` | 不变 | 19节点 |
| `qwen_edit_frame.json` | **扩展**: +2 LoadImage + 链接 | ~21节点 (原19节点) |

### 新模板 `flux_dev_t2i.json` 设计

```json
{
  "10": {"class_type": "UNETLoader", "inputs": {"unet_name": "flux1-dev-fp8.safetensors", "weight_dtype": "default"}},
  "11": {"class_type": "DualCLIPLoader", "inputs": {"clip_name1": "clip_l.safetensors", "clip_name2": "t5xxl_fp8_e4m3fn_scaled.safetensors", "type": "flux"}},
  "12": {"class_type": "VAELoader", "inputs": {"vae_name": "ae.safetensors"}},
  "13": {"class_type": "EmptyLatentImage", "inputs": {"width": 1024, "height": 1536, "batch_size": 1}},
  "14": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["11", 0]}},
  "15": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["11", 0]}},
  "16": {"class_type": "KSampler", "inputs": {"seed": 0, "steps": 20, "cfg": 3.5, "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0, "model": ["10", 0], "positive": ["14", 0], "negative": ["15", 0], "latent_image": ["13", 0]}},
  "17": {"class_type": "VAEDecode", "inputs": {"samples": ["16", 0], "vae": ["12", 0]}},
  "18": {"class_type": "SaveImage", "inputs": {"filename_prefix": "aicf_char", "images": ["17", 0]}}
}
```

9 节点，架构清晰。

### 扩展 `qwen_edit_frame.json` 多参考图

新增节点:
- `42`: `LoadImage` — image2 (角色2参考图)
- `43`: `LoadImage` — image3 (前帧/角色3参考图)

修改链接:
- Node 68 `TextEncodeQwenImageEditPlus`: 增加 `image2: ["42", 0]`, `image3: ["43", 0]`

`inject_params` 扩展:
```python
inject_params(wf, {
    "41": {"image": ref_image1},      # 主角色参考图
    "42": {"image": ref_image2},      # 角色2参考图 (可选)
    "43": {"image": ref_image3},      # 前帧/角色3 (可选)
    "68": {"prompt": prompt},
    "65": {"seed": seed, "steps": steps, "cfg": cfg},
    "60": {"filename_prefix": prefix},
})
```

---

## 四、实施计划

### Phase 1: S3 Flux Dev 替换 (P0-4 合并)

**目标**: S3 ref 图从 SDXL 切换到 Flux Dev，同时统一 Prompt 系统

| 步骤 | 内容 | 依赖 |
|------|------|------|
| 1.1 | 创建 `flux_dev_t2i.json` 模板 (9节点) | 无 |
| 1.2 | 重写 `_build_concept_prompt()` → 自然语言 prompt，调用 `character_image.py` 的 `build_full_prompt()` | 1.1 |
| 1.3 | 重写 `_run_t2i()` → Flux Dev 工作流 | 1.1, 1.2 |
| 1.4 | 验证: 单角色 Flux Dev ref → qedit 四视角 → 画质比对 | 1.3 |
| 1.5 | 全量 S3 重跑 (3角色) | 1.4 |

**预估时间**: 2-3h (含验证)

### Phase 2: S5 多角色+前帧增强 (P0-2, P0-3 合并)

**目标**: S5 支持多角色参考图注入 + 前帧连续性

| 步骤 | 内容 | 依赖 |
|------|------|------|
| 2.1 | 扩展 `qwen_edit_frame.json` (+2 LoadImage 节点) | 无 |
| 2.2 | 重写 `build_qedit_frame_workflow()` — 增加 ref_image2, ref_image3 参数 | 2.1 |
| 2.3 | 重写 S5 主循环 — 多角色 ref 查找 + 前帧注入逻辑 | 2.2 |
| 2.4 | S5 prompt 统一走 `frame_generate_first/last.py` 的 `build_full_prompt()` | 无 (与2.3并行) |
| 2.5 | 验证: 多角色场景 (老周+林姐) → 检查角色一致性 | 2.3, 2.4 |
| 2.6 | 验证: 前帧连续性 → 相邻 shot 首帧应延续前 shot 尾帧 | 2.3 |

**预估时间**: 3-4h (含验证)

### Phase 3: S4 prompt 重写 (P0-1)

**目标**: S4 shot_split prompt 对齐 AICB 精度

| 步骤 | 内容 | 依赖 |
|------|------|------|
| 3.1 | 重写 `shot_split.py` slot 结构: 对齐 AICB 10 slots | 无 |
| 3.2 | 重写 prompt 内容: 保真度硬约束/字数下限/镜头数下限/战斗规则/首尾帧规则 | 3.1 |
| 3.3 | 新增 S4b keyframe_assets: 独立首尾帧 prompt 生成 (P0-5) | 3.1 |
| 3.4 | 验证: S4 产出字段完整性 + S4b 首尾帧 prompt 质量 | 3.2, 3.3 |

**预估时间**: 3-4h (含验证)

### Phase 4: 全链路验证

**目标**: S1→S9 全链路跑通，验证工具链统一后的产出质量

| 步骤 | 内容 | 依赖 |
|------|------|------|
| 4.1 | 清理 last_bento 旧产出 | Phase 1-3 |
| 4.2 | S1→S9 全链路执行 | 4.1 |
| 4.3 | 产出质量比对 (vs 旧链路) | 4.2 |
| 4.4 | 更新 PROJECT.md / MEMORY.md | 4.3 |

**预估时间**: 2-3h

---

## 五、优先级排序与依赖图

```
Phase 1 (S3 Flux Dev) ──→ Phase 4 (全链路验证)
Phase 2 (S5 多角色)   ──→ Phase 4
Phase 3 (S4 prompt)   ──→ Phase 4

Phase 1 和 Phase 2 可并行（无交叉依赖）
Phase 3 独立（只改 prompt，不改工作流）
```

### 总预估: 10-14h

---

## 六、关键决策确认

| # | 决策点 | 选项 | 建议 |
|---|--------|------|------|
| D1 | S3 Flux Dev 分辨率 | 1024×1024 / 1024×1536 | **1024×1536** — 与 S3b/S5 对齐 |
| D2 | Flux Dev 推理步数 | 20步 / 28步 | **20步 euler/simple** — 速度优先，质量足够 |
| D3 | S5 多角色参考图上限 | image1+2+3 (3张) / image1 (1张) | **3张** — image1=主角色, image2=配角, image3=前帧 |
| D4 | S5 前帧注入位置 | image3 / VAEEncode | **image3** (首帧生成时) / **VAEEncode** (尾帧生成时，当前逻辑) |
| D5 | S4b 是否独立 stage | 是 (新增 s4b_keyframe_assets.py) / 否 (合入 s4) | **是** — 解耦架构，可独立重跑 |

---

## 七、风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| Flux Dev fp8 在 5090D 上 OOM | 低 | S3 阻塞 | VRAM ~12GB + KV overhead ~2GB < 32GB |
| Flux Dev 画风与 qedit 不匹配 | 中 | S3b 四视角质量下降 | Flux Dev 和 qedit 同属 Flux 系，画风兼容性好 |
| 多角色 image2/3 注入效果不明显 | 中 | P0-2 无实际提升 | 先验证单角色 vs 多角色 qedit 产出差异 |
| S4 prompt 重写后 LLM 不遵守约束 | 中 | S4 产出质量不达标 | AICB 已验证该 prompt 有效，移植应无问题 |
| S4b 解耦增加复杂度 | 低 | 开发时间增加 | 简化：S4b 只是独立 LLM 调用，无 ComfyUI |
