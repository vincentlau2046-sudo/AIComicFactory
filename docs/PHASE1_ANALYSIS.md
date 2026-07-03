# Phase 1 落地方案 — 关联分析

**日期**: 2026-07-03
**范围**: P1-1, P1-3, P1-5, P1-7

---

## 一、修改点依赖图

```
P1-7 (S1 parsing_rules)
  ↓ s1_parsed.json 的字段影响下游所有 stage
  
P1-1 (S3b qedit prompt)
  ↓ 依赖 S2 visualAnchors（已存在）
  ↓ 产出 s3_character_refs/{name}/ 四视图（S5 消费）
  
P1-3 (Shot 字段对齐)
  ↓ s4_shots.json 字段影响 S4b / S5 / S6 / S7
  
P1-5 (S6 video prompt)
  ↑ 依赖 P1-3 的 Shot 字段（cameraDirection, videoScript 等）
  ↑ 依赖 S2 visualHint（已存在）
```

**关键依赖**: P1-5 依赖 P1-3。Shot 字段不全 → S6 无法消费新字段。

---

## 二、逐项分析

### P1-7: S1 parsing_rules slot

**当前状态**: `script_parse.py` 有 5 个 slot（role/fidelity/format/rules/language），缺 `parsing_rules`（故事编辑原则）

**修改内容**: 新增 `parsing_rules` slot，内容为：
- 场景拆分原则：宁多勿少，每场景≤3个对白轮
- 对白保真：逐字保留原文，不意译不压缩
- 描述保真：场景描写原文保留
- 时间标注：日/夜/晨/昏 必须标注

**影响范围**:
| 消费方 | 影响 | 风险 |
|--------|------|------|
| `s1_parsed.json` | 可能多拆几个场景（更细粒度） | ⚠️ **下游 S2/S4 需重跑** |
| S2 character_extract | 角色可能微调（场景更细→角色出场更明确） | 低 |
| S4 shot_split | shot 数量可能变化 | 低 |

**风险**: 
- ⚠️ 改 S1 prompt 后重跑 → s1_parsed.json 变化 → 下游全部需要重跑
- ✅ 但 S1 是最上游，改它不会引入代码 bug，只是数据变化
- ✅ 如果不重跑 S1，新 slot 只对**未来项目**生效

**建议**: 先落地代码，不立即重跑 last_bento 的 S1。

---

### P1-1: S3b qedit prompt 增强

**当前状态**: 
```python
FOUR_VIEW_PROMPT = """请将输入的角色图片转换为一张包含四个视角的设定图..."""
full_prompt = f"{FOUR_VIEW_PROMPT}\n\n风格要求：{style_suffix}"
```
- ❌ 没有注入 `visualAnchors`（面部/发型/体型/服装关键词）
- ❌ 没有注入 `colorPalette`（角色主色）
- ❌ 没有画风锚定（"写实真人" vs "日系动漫" 只靠 style_suffix 一句话）
- ❌ 没有一致性硬约束（"四个视角必须是同一人"只靠自然语言）

**修改内容**: 
```python
# 新增: 从 s2_characters.json 读取 visualAnchors 注入 prompt
def build_four_view_prompt(char_name, characters, style="realist"):
    c = find_char(char_name, characters)
    anchors = c.get("visualAnchors", {})
    palette = c.get("colorPalette", "")
    
    prompt = FOUR_VIEW_PROMPT  # 基础布局指令
    prompt += f"\n\n=== 角色视觉锚点（不可偏离）==="
    if anchors.get("face"):
        prompt += f"\n- 面部: {anchors['face']}"
    if anchors.get("hair"):
        prompt += f"\n- 发型: {anchors['hair']}"
    if anchors.get("body"):
        prompt += f"\n- 体型: {anchors['body']}"
    if anchors.get("clothing"):
        prompt += f"\n- 服装: {anchors['clothing']}"
    if anchors.get("signature"):
        prompt += f"\n- 标志: {anchors['signature']}"
    if palette:
        prompt += f"\n- 色板: {palette}"
    
    prompt += f"\n\n=== 画风锚定 ==="
    prompt += STYLE_ANCHORS.get(style, STYLE_ANCHORS["realist"])
    
    prompt += "\n\n=== 一致性硬约束 ==="
    prompt += "四个视角必须严格是同一角色：相同面孔、相同发型发色、相同服装款式颜色、相同体型。"
    prompt += "任何视角间的外观差异（换装/换发型/换配饰）都是错误。"
    
    return prompt
```

**影响范围**:
| 消费方 | 影响 | 风险 |
|--------|------|------|
| S3b 产出 | 四视图一致性提升 | ✅ 正向 |
| S5 frame_generate | 消费 S3b 产出 → 参考图质量提升 | ✅ 正向 |
| S3b 脚本 | 需读取 s2_characters.json | ⚠️ 需加参数/逻辑 |

**风险**:
- ⚠️ S3b 当前不读 s2_characters.json，需要新增读取逻辑
- ✅ 改 prompt 不改工作流 JSON，ComfyUI 层零风险
- ✅ 向后兼容：无 visualAnchors 时退化为当前行为

**建议**: 低风险，可直接实施。

---

### P1-3: Shot 字段对齐

**当前状态**: s4_shots.json 已有 15 个字段
```
shotNumber, prompt, motionScript, videoScript, cameraDirection,
compositionGuide, focalPoint, depthOfField, transitionIn, transitionOut,
duration, characters, dialogues, soundDesign, musicCue
```

**AICB 完整字段（缺的）**:
| 字段 | 说明 | 下游消费方 | 优先级 |
|------|------|-----------|--------|
| `costumeOverrides` | 逐角色换装 | S5 | ✅ 已实现 |
| `sceneDescription` | 场景描述（≠ prompt） | S5/S6 | ⚠️ 缺 |
| `startFrame` | 首帧描述/prompt | S4b→S5 | ✅ S4b已有 |
| `endFrame` | 尾帧描述/prompt | S4b→S5 | ✅ S4b已有 |
| `videoPrompt` | 视频生成专用prompt | S6 | ⚠️ 缺 |
| `generationMode` | keyframe/reference | S6 | ⚠️ 缺 |
| `isStale` | 脏标记 | 全局 | P2 |

**关键发现**: 
- `costumeOverrides` — ✅ 已在 S4 prompt schema 中，S5 已消费
- `sceneDescription` — ⚠️ **S5/S6 都需要但 shot 里没有**。S5 用的是 `_build_scene_description(sc)` 从 scene 级别构建，不是 shot 级别
- `videoPrompt` — ⚠️ **S6 直接用 `build_video_prompt()` 拼装**，不读 shot.videoPrompt。如果 shot 有 videoPrompt，S6 可以跳过拼装直接用
- `generationMode` — 当前硬编码为 keyframe，未来 reference 模式需要

**修改内容**:
1. S4 prompt schema 新增 `sceneDescription` + `videoPrompt` + `generationMode` 输出字段
2. S4 shot_split.py 的 JSON 输出格式增加这三个字段
3. S6 优先读 `shot.videoPrompt`，fallback 到 `build_video_prompt()` 拼装

**影响范围**:
| 消费方 | 影响 | 风险 |
|--------|------|------|
| S4 LLM 输出 | 多 3 个字段 | ✅ JSON 新字段不影响旧字段 |
| S4b | 已独立，不受影响 | ✅ |
| S5 | 可选读 sceneDescription | ✅ 向后兼容 |
| S6 | 优先 videoPrompt，fallback 拼装 | ✅ 向后兼容 |
| S7 | 不受影响 | ✅ |

**风险**:
- ⚠️ S4 LLM 输出 JSON 多字段 → 需验证 LLM 是否稳定输出新字段
- ✅ 所有新字段有 fallback，旧数据不会断

**建议**: 中风险，需测试 S4 LLM 输出稳定性。

---

### P1-5: S6 video prompt 结构化

**当前状态**: S6 已调用 `build_video_prompt()`（7 slot 完整版），但：
- ❌ `scene_description` 参数传空（S6 不读 scene 描述）
- ❌ `start_frame_desc` / `end_frame_desc` 传空（S6 不读 S4b 的首尾帧描述）
- ❌ `characters` 只传 name + visualHint，不传 visualAnchors
- ❌ 不读 `shot.videoPrompt`（P1-3 新增字段）

**修改内容**:
1. S6 读 S4b keyframe_assets 获取首尾帧描述
2. S6 读 scene 描述传给 `scene_description`
3. S6 优先读 `shot.videoPrompt`，fallback 到 `build_video_prompt()` 拼装
4. `characters` 注入更多视觉信息（visualAnchors.clothing）

**依赖**: P1-3（shot.videoPrompt 字段）

**影响范围**:
| 消费方 | 影响 | 风险 |
|--------|------|------|
| S6 产出 | motion_prompt 更精确 → FLF2V 质量提升 | ✅ 正向 |
| S7 | 不受影响（S7 只组装视频） | ✅ |
| ComfyUI | prompt 变长 → FLF2V 可能略慢 | ⚠️ 微 |

**风险**:
- ⚠️ prompt 过长可能影响 FLF2V 效果（FLF2V 的 CLIP 对长 prompt 敏感度低）
- ✅ 有 fallback 机制，不会断

**建议**: 低风险，但需验证 prompt 长度对 FLF2V 的影响。

---

## 三、实施顺序

```
P1-7 (S1 parsing_rules)     ← 最上游，代码改动最小，不影响现有数据
  ↓
P1-1 (S3b qedit prompt)     ← 独立改动，零下游风险
  ↓
P1-3 (Shot 字段对齐)        ← P1-5 的前置依赖
  ↓
P1-5 (S6 video prompt)      ← 依赖 P1-3 的新字段
```

**理由**:
1. P1-7 最安全 — 只加 slot，不改现有逻辑
2. P1-1 独立 — S3b 不被其他 stage 依赖（S5 只消费产出图）
3. P1-3 必须在 P1-5 前 — S6 需要新字段
4. P1-5 最后 — 消费 P1-3 的产出

---

## 四、断点风险汇总

| 风险点 | 来源 | 缓解 |
|--------|------|------|
| S1 重跑后数据变化 | P1-7 | 不重跑 last_bento，新 slot 对未来项目生效 |
| S3b 需读 s2_characters.json | P1-1 | 新增读取逻辑，无 visualAnchors 时退化 |
| S4 LLM 可能不稳定输出新字段 | P1-3 | 新字段有 fallback，旧数据不断 |
| S6 prompt 过长影响 FLF2V | P1-5 | 验证 prompt 长度，必要时截断 |
| **P1-3→P1-5 依赖** | 顺序 | 必须先 P1-3 后 P1-5 |

---

## 五、不建议做的事

1. ❌ 不重跑 last_bento 的 S1 — 数据变化太大，且当前 S1 数据够用
2. ❌ 不改 S4 的核心 prompt 逻辑 — 只加输出字段，不改约束规则
3. ❌ 不在 S6 加 VL 质检 — 属于 P2，不在本 phase
4. ❌ 不改 ComfyUI 工作流 JSON — 只改 prompt 文本
