## F5 音频质量审计

**审计日期**: 2026-07-05  
**审计范围**: S8(字幕) → S9(TTS音频) + 时间轴 + 角色音色映射  
**涉及文件**: `s8_subtitles.py`, `s9_tts_audio.py`, `dialogue_timing.py`, `core/timeline.py`, `core/demographics.py`

### 评估结论: ⚠️ 有条件通过（部分问题已修复）

音频管线具备基本的端到端能力（统一时间轴、TTS 合成、字幕烧录、成片输出），但在音色匹配的自动化、字幕样式利用、时间轴容错等关键环节存在明显短板。当前可产出"能看"的 comic，但音色错配、字幕单调等问题会让观众出戏。

**2026-07-05 修复记录 (R2)**: TTS 输出验证 + 重试机制 + 模型状态清理 已完成修复（详见下方 🔴→✅ 标记）。

---

### 2026-07-05 R2 修复摘要

| 严重度 | 问题 | 修复状态 | 修复内容 |
|--------|------|----------|----------|
| 🔴→✅ | 无 TTS 输出内容验证 | ✅ 已修复 | 新增 `validate_tts_output()`: 时长±30%校验 + RMS音量检测 |
| 🔴→✅ | TTS 失败时静默插入 2s silence，无告警无重试 | ✅ 已修复 | 新增 `generate_tts()` 重试机制（1次重试）；失败后记录告警而非静默；silence 时长改为匹配预期时长 |
| 🔴→✅ | 模型状态污染（unload_models=True 但无显式清理） | ✅ 已修复 | 新增 `_cleanup_tts_model()`: `del model` + `torch.cuda.empty_cache()` |

---

---

### 关键发现

| 严重度 | 模块 | 问题 | 对 comic 音频质量的影响 | 建议 |
|--------|------|------|-------------------|------|
| 🔴 高 | s9_tts_audio.py | **VOICE_MAP 硬编码，仅 3 角色 + default**；与 demographics.py 完全断裂 | 新项目角色全部命中 default → 所有角色同一音色，观众无法区分谁在说话，多角色对话场景彻底混乱 | 从 demographics.py 的性别/年龄推断动态选择音色，建立 gender→voice 映射 |
| ✅ 已修复 | s9_tts_audio.py | **无 TTS 输出内容验证**（已知 Qwen3-TTS 批量调用有模型状态污染） | ~~污染导致 TTS 输出错误内容/静音/杂音，直接进入成片~~ | ~~每条 TTS 输出做 STT 回验或至少做时长/音量校验；发现异常则重试~~ |
| ✅ 已修复 | s9_tts_audio.py | **TTS 失败时静默插入 2s silence，无告警无重试** | ~~观众看到角色张嘴说话但只有静音，极度出戏~~ | ~~至少重试 1-2 次；失败后记录告警~~ |
| 🟡 中 | core/timeline.py | **ASS 三样式(Narration/InnerVoice/Dialogue)已定义但 generate_ass 永远只用 Dialogue** | 旁白和心声与普通对白视觉无区分；观众难以区分"角色说的话"和"角色的想法" | 根据 dialogue 类型/标记选择 Style；s4 数据需增加 dialogue type 字段 |
| 🟡 中 | s9_tts_audio.py | **TTS 音频时长未校验是否溢出分配的时间槽** | 若 TTS 合成音频比 end_s - start_s 长，会侵入下一条对白时间，造成音频重叠/截断 | 合成后检查时长，超长则截断或调整时间轴 |
| 🟡 中 | dialogue_timing.py | **Vision LLM 分析结果无校验**；LLM 可能输出重叠区间、越界 ratio、格式错误 | 对白时间轴错位 → 字幕与口型不同步，音频重叠或留白 | 解析后做约束校验：0≤start<end≤1，区间不重叠，异常则回退均匀分布 |
| 🟡 中 | s8/s9 | **S8 默认 calibrate_with_videos=True，S9 默认 False**——两阶段时间轴基准不一致 | 若 s4 duration 与实际视频时长有偏差，S8 字幕和 S9 音频可能基于不同时间轴，导致字幕与音频不同步 | 统一 calibrate 策略；或 S9 必须用 S8 同一时间轴 |
| 🟡 中 | s9_tts_audio.py | **逐条 amix overlay 效率低且累计噪声**——N 条对白需 N 次 ffmpeg 调用 | 大量对白时构建时间线性增长；每次 amix 引入量化噪声，多次叠加后音质下降 | 改用一次 ffmpeg 多输入 + complex filter 合并；或使用 sox/ffmpeg amerge |
| 🟢 低 | core/timeline.py | **clean_subtitle_text 将"……"→","、"——"→","**——破坏中文标点语义 | 省略号变成逗号，语气从"沉思/犹豫"变为"停顿"，情感表达失真；但观众可能不太注意 | TTS 文本清洗和字幕文本显示应分开处理；字幕保留原标点 |
| 🟢 低 | core/timeline.py | **字幕无角色名颜色区分**——所有角色同色(黄色 Dialogue) | 多角色快速对话时，观众难以快速区分是谁在说话 | 按角色分配不同字幕颜色（从 demographics 的角色 ID 哈希映射） |
| 🟢 低 | core/demographics.py | **性别推断仅基于关键词计数**，无上下文理解 | 描述"看起来很精神的年轻人，穿着女装"会被误判为女性 → 音色错配 | 可接受，但建议在 s3 角色数据中强制要求 gender 字段 |

---

### 质量门控评估

- ✅ **已有门控**:
  - 统一时间轴模块 (core/timeline.py) —— S7/S8/S9 共享同一时间轴计算，消除三处独立计算的不一致
  - dialogue_timing.py 有 vision 分析 + 均匀分布 fallback 双模式
  - TTS 生成前检查已有文件，避免重复生成
  - 全局音量标准化 (loudnorm -12 dB)，防止爆音
  - 每条 TTS 单独归一化 (-9 dB LUFS) 后再混入时间轴
  - ASS 字幕字体使用 Noto Sans CJK SC，中文渲染基本可靠

- ❌ **缺失门控**:
  - ~~**TTS 输出内容验证**~~ —— ✅ R2 已修复：`validate_tts_output()` 提供时长±30% + RMS 音量校验
  - ~~**Qwen3-TTS 模型状态污染防护**~~ —— ✅ R2 已修复：`_cleanup_tts_model()` 显式 `del model` + `torch.cuda.empty_cache()`
  - **音色-角色匹配验证** —— VOICE_MAP 是静态硬编码，无动态匹配，无 mismatch 检测
  - **TTS 音频时长 vs 时间槽对齐检查** —— 合成后无 "音频是否 fit 分配时间" 的验证
  - **Vision LLM 时间轴输出约束校验** —— 无越界/重叠检测
  - **S8/S9 时间轴一致性校验** —— 两阶段 calibrate 策略不同，无跨阶段一致性断言
  - **字幕样式利用** —— ASS 定义了三样式但未使用，无声画类型区分
  - ~~**TTS 失败重试机制**~~ —— ✅ R2 已修复：`generate_tts()` 提供 1 次重试 + 告警；silence 时长匹配预期对白时长

---

### 逐维度详细分析

#### 1. TTS 音色匹配 🔴

**现状**: `VOICE_MAP` 硬编码 3 个角色名→音色映射，未命中一律走 `default`(Aiden)。

**核心问题**:
- `core/demographics.py` 已实现性别/年龄推断（`infer_gender`, `infer_age`），但 `s9_tts_audio.py` 完全不引用它
- 新项目（不同角色名）100% 命中 default → 所有角色同一男声
- 音色名(Aiden/Vivian/Ryan)是否对应 Qwen3-TTS 实际可用 speaker 未见校验

**对观感的影响**: 多角色对话场景中无法区分谁在说话，comic 的戏剧张力丧失。

**建议**: 
```python
# 动态音色映射示例
from core.demographics import infer_gender, infer_age

GENDER_VOICE_MAP = {
    "male_elderly": "Chelsie",   # 低沉男声
    "male_mature": "Aiden",      # 中年男声
    "male_young": "Ryan",        # 年轻男声
    "female_elderly": "Eleanor", # 低沉女声
    "female_mature": "Vivian",   # 中年女声
    "female_young": "Serena",    # 年轻女声
}

def get_voice_for_character(character_desc, gender_field=None):
    gender = infer_gender(character_desc, gender_field)
    age_label, _ = infer_age(character_desc)
    key = f"{gender}_{age_label}"
    return GENDER_VOICE_MAP.get(key, GENDER_VOICE_MAP["male_mature"])
```

#### 2. 时间轴精准度 🟡

**现状**: 统一时间轴模块设计合理，dialogue_timing.py 用 LLM vision 分析首尾帧推断对白位置。

**核心问题**:
- LLM 输出无约束校验（可能输出重叠/越界的 ratio）
- S8 calibrate=True vs S9 calibrate=False 的不一致
- TTS 音频实际时长与分配时间槽无对齐检查

**对观感的影响**: 字幕/音频与画面不同步时，观众会明显感到"配音对不上嘴型"。

**建议**: 在 `calc_dialogue_timeline` 中添加 ratio 校验；统一 S8/S9 calibrate 策略；合成后校验音频时长。

#### 3. 字幕渲染质量 🟡

**现状**: ASS 定义了三种样式（旁白白字、心声半透明斜体、对话黄字加粗），但 `generate_ass` 全部使用 Dialogue 样式。

**核心问题**:
- Narration 和 InnerVoice 样式是死代码
- 无角色颜色区分
- 中文标点被清洗（……→,），字幕应保留原文

**对观感的影响**: 旁白和对白无法区分，角色心声无法表达——comic 的重要叙事手段缺失。

#### 4. 多角色音频混合 🟢

**现状**: 逐条 amix overlay 方案功能正确，每次归一化后叠加。

**核心问题**:
- 效率低（N 条对白 N 次 ffmpeg）
- 多次 amix 累积量化噪声
- 无角色音量差异化（主角声音应更突出）

**对观感的影响**: 目前可接受，但长片（>10 条对白）可能音质下降。

#### 5. TTS 质量门控 ✅ (R2 已修复)

**修复前**: 仅有的"门控"是 TTS 失败时插入 2s silence。

**修复后 (2026-07-05 R2)**:
- `validate_tts_output()` — 每条 TTS 输出做时长±30% 校验 + RMS 音量检测
- `generate_tts()` — 1 次自动重试；重试后仍失败则 `logger.warning` 告警
- `_cleanup_tts_model()` — 显式 `del model` + `torch.cuda.empty_cache()` 防止状态污染
- silence placeholder 时长改为匹配预期 TTS 时长（`estimate_expected_duration()`），不再硬编码 2s

**残留问题**:
- 无 STT 回验（纯时长/音量校验，无法检测"内容说错"的情况）
- 建议后续集成 Whisper 做 STT 回验（P1 优先级）

---

### 修复优先级建议

| 优先级 | 修复项 | 预估工作量 | 影响面 |
|--------|--------|-----------|--------|
| P0 | TTS 输出验证（时长+音量+可选STT回验） | 2-3h | 防止污染语音进入成片 |
| P0 | 动态音色映射（接入 demographics） | 1-2h | 新项目角色音色正确 |
| P1 | TTS 失败重试 + 告警 + silence 时长修正 | 1h | 消除静音对白 |
| P1 | ASS 样式按对话类型选择 | 1h | 旁白/心声/对白视觉区分 |
| P1 | Vision LLM 输出约束校验 | 0.5h | 防止时间轴越界/重叠 |
| P2 | S8/S9 calibrate 策略统一 | 0.5h | 字幕音频时间轴一致 |
| P2 | TTS 时长 vs 时间槽对齐检查 | 1h | 防止音频溢出 |
| P3 | 多输入一次混音优化 | 2h | 构建效率+音质提升 |
| P3 | 角色字幕颜色区分 | 0.5h | 多角色对话可读性 |
