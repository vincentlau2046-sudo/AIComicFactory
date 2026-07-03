# AICF 改造记录

> 合并自: `docs/UPGRADE_PLAN_V2.md`、`UPGRADE_PLAN.md`、`docs/TOOLCHAIN_UNIFICATION_PLAN.md`
> 按时间正序排列，后续改造方案直接追加

---

## 2026-06-29 改造方案 v2

### 问题 1：重复图片

**根因**: S3/S5 对每张图做了两次 copy：`shutil.copy2` + `am.register()` 内部第二次 copy

**方案**: 去掉 `shutil.copy2`，统一由 `am.register()` 完成文件归档。
修改 `am.register()` 支持 `dest_name` 参数。

### 问题 2：SDXL → 双路径（动漫/写实）

```
用户指定风格 ───┬─ anime ──→ Animagine XL (SDXL)
                └─ realistic → Flux.1 Dev FP8 (默认)
```

需下载模型: flux1-dev-fp8 (~12GB) + t5xxl_fp8 (~5GB) + ae (~300MB) + clip_l (~250MB 已有)

**脚本改动**: `s3_character_image.py` / `s5_frame_generate.py` 增加 `--style realistic|anime`

### 问题 3：S3 角色视图资产

**方案**: S3 拆为 S3a + S3b
- S3a: Flux.1 Dev T2I → 单正面参考图 (1280×1280)
- S3b: Flux Kontext/Klein LoRA → 四视图 turnaround (2560×1440)

### 改造执行顺序

1. 修复重复图片 → 2. 下载 Flux 模型 → 3. S3/S5 添加 Flux workflow → 4. S3b 四视图 → 5. 重跑 last_bento

---

## 2026-07-01 AICB Full-Fidelity Upgrade Plan

**原则**: 完整抄 AICB，不打折扣；先代码层优化，不动实际环境

### 改动文件（7 files）

| 文件 | 改动内容 |
|------|---------|
| `s6_flf2v_render.py` | 集成 `buildVideoPrompt` 7-slot |
| `s7_video_assemble.py` | 完全重写: xfade + BGM + SRT + drawtext |
| `s8_subtitles.py` | 改为 SRT 生成器, 支持 startRatio/endRatio |
| `s5_frame_generate.py` | 注入 AICB composition suffix |
| `prompts/defaults/frame_generate_first.py` | 完整移植 AICB: 画风 + 5条参考图规则 + 连续性 |
| `prompts/defaults/frame_generate_last.py` | 完整移植 AICB: 画风强制 + 首帧关系 + 下镜头起点 |

### 完成 vs AICB 对照

| AICB 能力 | 状态 |
|-----------|------|
| buildVideoPrompt 7-slot | ✅ S6 集成 |
| assembleVideo: xfade + cut | ✅ S7 集成 |
| assembleVideo: SRT subtitle burn | ✅ S7 opt-in |
| assembleVideo: BGM mix | ✅ S7 --bgm |
| assembleVideo: drawtext title/credits | ✅ S7 |
| generateSrtFile: startRatio/endRatio | ✅ S8 |
| FirstFramePrompt: 画风 + 5条规则 + 连续性 | ✅ 移植 |
| LastFramePrompt: 画风强制 + 首帧关系 + 渲染 | ✅ 移植 |
| compositionSuffix | ✅ S5 注入 |
| continuity_check VL | ✅ 已激活 |
| video_quality_check VL | ✅ 已激活 |
| IPAdapter (角色参考图绑定) | ⚠️ 延期 |
| 四视图 character-image | ⚠️ 延期 |

---

## 2026-07-02 工具链统一方案

**核心变更**: S3 ref 用 Flux Dev → S3b/S5 统一用 qedit → S6 不变

### 统一后架构

| Stage | 工具 | 分辨率 |
|-------|------|--------|
| S3 ref | Flux Dev fp8 (T2I) | 1024×1536 |
| S3b 四视角 | qwen-image-edit ReferenceLatent | 1024×1536 |
| S5 首尾帧 | qwen-image-edit ReferenceLatent | 1024×1536 |
| S6 视频 | Wan2.2 FLF2V | 1280×720 |

### 工作流模板变更

| 模板 | 变更 |
|------|------|
| `t2i_character_ref.json` | 替换为 `flux_dev_t2i.json` (12节点) |
| `qwen_edit_frame.json` | 扩展: +2 LoadImage (多参考图) |
| `qwen_edit_four_view.json` | 不变 |

### 实施计划

| Phase | 内容 | 工时 |
|-------|------|------|
| Phase 1: S3 Flux Dev | 创建模板 + 重写 prompt + 重写 T2I + 验证 | 2-3h |
| Phase 2: S5 多角色+前帧 | 扩展模板 + 重写 workflow + 多角色 ref 查找 + 验证 | 3-4h |
| Phase 3: S4 prompt 重写 | 对齐 AICB 10 slots + S4b keyframe_assets | 3-4h |
| Phase 4: 全链路验证 | S1→S9 全链路执行 + 质量比对 | 2-3h |

### 风险

| 风险 | 缓解 |
|------|------|
| Flux Dev fp8 OOM | VRAM ~12GB < 32GB (5090D) |
| Flux Dev 画风与 qedit 不匹配 | 同属 Flux 系，画风兼容性好 |
| 多角色 image2/3 注入无效 | 先验证单角色 vs 多角色差异 |
| S4 prompt 重写后 LLM 不遵守 | AICB 已验证有效 |