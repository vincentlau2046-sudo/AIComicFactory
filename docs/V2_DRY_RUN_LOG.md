# V2 全链路 Dry Run 记录

**日期**: 2026-07-02
**项目**: last_bento (最后的便当)
**目标**: 验证工具链统一后的全链路产出质量

## 决策确认

| # | 决策点 | 方案 |
|---|--------|------|
| D1 | S3 Flux Dev 分辨率 | 1024×1536 |
| D2 | Flux Dev 推理步数 | **28步 dpmpp_2m/sgm_uniform, cfg=4.0** (原20步 euler/simple 质量不足，已调整) |
| D3 | S5 多角色参考图上限 | 3张 |
| D4 | S5 前帧注入位置 | image3 |
| D5 | S4b 独立 stage | 是 |

---

## S3: Flux Dev T2I 角色参考图

### Bug #1: "毛玻璃"图片 — Flux Dev 输出 75% 白色背景

**症状**: Flux Dev 生成的参考图几乎全白（near_white=75.7%），人物只占画面 25%，看起来像隔了一层毛玻璃。

**根因**: Prompt `"Plain white background, studio lighting"` + `"no background elements, clean composition"` 导致 Flux Dev 将 75% 的画面给了白色背景。Flux Dev 对背景指令的响应权重远高于 SDXL。

**修复**: 重写 `build_flux_dev_prompt()` 架构:
- 人物描述前置（face → hair → body → clothing → pose → style）
- 背景指令后置且极简: `"Simple neutral gray background."`
- 强调人物填满画面: `"The figure fills most of the frame from head to toe."`

**验证**: near_white 从 75.7% → 0%, avg brightness 从 222 → 97-172

### Bug #2: D2 参数不足 — 20步 euler/simple 产出偏柔和

**症状**: 即使修复背景问题，Flux Dev 产出仍然偏"柔和"（Laplacian var=1-2 vs qedit 的 65-460）。

**分析**: Laplacian var=2 是 Flux 16通道 latent space 的正常值，不是锐度问题。但 dpmpp_2m/sgm_uniform 比 euler/simple 在细节保留上更优，28步比20步更充分。

**调整**: D2 从 20步 euler/simple → **28步 dpmpp_2m/sgm_uniform, cfg=4.0**
- `build_flux_dev_workflow()` 默认参数已更新
- 产出文件体积从 440KB → 687-803KB（细节更丰富）

### Bug #3: VL 关闭时 S3 循环不 break

**症状**: `--no-check` 模式下每个角色生成3次（max_vl_retries=2）。

**根因**: VL 关闭时成功后没有 `break`，for loop 继续到 max_vl_retries。

**修复**: 添加 `break  # VL disabled: success = done`

---

## S3b: qedit 四视图

**结果**: 12/12 views ✅ 无错误
- 老周: front(1609KB), minus_angle(1412KB), plus_angle(1470KB), back(1576KB)
- 林姐: front(1661KB), minus_angle(1599KB), plus_angle(1558KB), back(1490KB)
- 小陈: front(1276KB), minus_angle(1023KB), plus_angle(1028KB), back(1087KB)

---

## S4b: 关键帧资产

**结果**: 16/16 shots ✅
- Prompt 长度: 970c-1872c（多角色场景更长）

---

## S5: 关键帧生成

### Bug #4: multi-ref 模板 LoadImage 占位符文件名不存在 → 400 Bad Request

**症状**: 当只有 image3（前帧）没有 image2（配角）时，`qwen_edit_frame_multi.json` 中 node 42 的 `image` 字段仍为模板默认的 `"reference2.png"`，该文件在 ComfyUI input 中不存在 → 400。

**根因**: `build_qedit_frame_workflow()` 只在有 ref_image2 时注入 node 42，但 multi-ref 模板中 node 42 已存在且引用了不存在的占位符文件名。

**修复**: 当 ref_image2/ref_image3 未提供时，fallback 到 ref_image（主角色参考图）：
```python
if ref_image2:
    injections["42"] = {"image": ref_image2}
else:
    injections["42"] = {"image": ref_image}  # fallback
if ref_image3:
    injections["43"] = {"image": ref_image3}
else:
    injections["43"] = {"image": ref_image}  # fallback
```

**验证**: Shot 3 (单角色+前帧) 从 3次400失败 → 1次成功

### S5 运行结果 ✅
- Shot 1: 跳过（无角色）
- Shot 2: ✅ first(1633KB) + last(1582KB)
- Shot 3: ✅ first(1674KB) + last(1596KB) — 修复后成功
- Shot 4: 跳过（无角色）
- Shot 5: ✅ first(1720KB) + last(1668KB) — 多角色+前帧
- Shot 6: ✅ first(1727KB) + last(1673KB)
- Shot 7: ✅ first(1583KB) + last(1586KB)
- Shot 8: ✅ first(1646KB) + last(1569KB)
- Shot 9: ✅ first(1576KB) + last(1420KB)
- Shot 10: ✅ first(1648KB) + last(1658KB) — 多角色+前帧
- Shot 11: 跳过（无角色）
- Shot 12: ✅ first(1584KB) + last(1690KB)
- Shot 13: ✅ first(1644KB) + last(1516KB)
- Shot 14: ✅ first(1622KB) + last(1608KB) — 多角色+前帧
- Shot 15: ✅ first(1587KB) + last(1549KB)
- Shot 16: ✅ first(1601KB) + last(1525KB)

**总计**: 26/32 帧（4 shots × 2帧 = 8帧因无角色跳过，正确行为）

**场景3(夜晚)亮度偏低** (avg=41-46) — 符合剧本'便当摊前·夜晚'的氛围

---

## S6: FLF2V 视频生成 ✅

- Shot 2: ✅ 4.1MB (286s)
- Shot 3: ✅ 4.0MB (286s)
- Shot 4: 跳过（无角色帧）
- Shot 5: ✅ 5.4MB (2 segments)
- Shot 6: ✅ 4.3MB (286s)
- Shot 7: ✅ 3.2MB (2 segments)
- Shot 8: ✅ 4.2MB (2 segments)
- Shot 9: ✅ 3.7MB (284s)
- Shot 10: ✅ 4.9MB (2 segments)
- Shot 11: 跳过（无角色帧）
- Shot 12: ✅ 2.9MB (186s)
- Shot 13: ✅ 5.2MB (2 segments)
- Shot 14: ✅ 4.3MB (2 segments)
- Shot 15: ✅ 3.3MB (286s)
- Shot 16: ✅ 4.2MB (2 segments)

**总计**: 13/16 videos (3 shots 无角色帧跳过)

---

## S7: 视频组装 ✅

31.8MB, 16 shots → s7_assembled.mp4

---

## S8: 字幕生成 ✅

7 条对白 → SRT + ASS

---

## S9: TTS + 最终成片 ✅

- 7 条对白 TTS 生成 (Qwen3-TTS)
- 时间轴音频: 88.5s
- 最终成片: 30.9MB

---

## 全链路验证总结

| Stage | 结果 | 备注 |
|-------|------|------|
| S3 Flux Dev | ✅ 3 chars | prompt重写后质量提升(nw 75%→0%) |
| S3b qedit | ✅ 12 views | 四视图无错误 |
| S4b | ✅ 16 shots | 新 stage 正常工作 |
| S5 | ✅ 26/32 frames | 4 shots无角色跳过(正确) |
| S6 | ✅ 13/16 videos | 3 shots无帧跳过(正确) |
| S7 | ✅ 31.8MB | 组装成功 |
| S8 | ✅ 7 dialogues | SRT+ASS |
| S9 | ✅ 30.9MB | 最终成片 |

### 发现并修复的 Bug (4个)

1. **Flux '毛玻璃'**: prompt 背景权重过高 → character-first 架构重写
2. **D2 参数不足**: 20步 euler/simple → 28步 dpmpp_2m/sgm_uniform
3. **VL关闭循环不break**: 添加 break
4. **multi-ref LoadImage 占位符不存在**: fallback 到 ref_image
