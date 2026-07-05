## F4 视频连贯性审计
### 评估结论: 有条件通过

### 关键发现
| 严重度 | 模块 | 问题 | 对 comic 动态质量的影响 | 建议 |
|--------|------|------|-------------------|------|
| 🔴 高 (✅ 2026-07-05 已修复) | s7_video_assemble.py | xfade offset 累积计算在混合转场类型下有偏移风险：`cut` 被映射为 `xfade=fade:duration=0`，但 `output_dur` 仍按 `+next_dur` 累加（不减重叠），而非 cut 转场按 `+next_dur-eff_dur` 累加。当 cut 和非 cut 混合时，后续 offset 会逐个漂移 | 混合转场序列中，后面的 xfade 起始点偏移，导致画面闪烁、重叠错位、音画不同步，直接破坏流畅感 | 统一 offset 累加逻辑：cut 转场 eff_dur=0 时也不应有分支差异；或改用 `timeline.py` 的精确计算 |
| 🔴 高 | s6_flf2v_render.py | 长镜头分段逻辑已定义（`render_segment`/`concat_segments`/`generate_mid_frame`），但 main() 中只有 Path A（≤150f）和 Path D（>150f 打回），**Path B/C（分段渲染+中帧衔接）从未被调用** | >6s 镜头直接拒绝，若 S4 未修正则该镜头完全缺失，导致叙事断裂；且中帧衔接代码成为死代码 | 补充 Path B/C 调用逻辑，或在 S4 强制 max_duration 约束并验证 |
| 🟡 中 (✅ 2026-07-05 已修复) | s7_video_assemble.py | `map_transition("cut")` 返回 `"fade"`，而实际 duration=0，语义不一致。ffmpeg xfade `fade:duration=0` 在某些版本可能产生 1 帧黑闪 | 硬切场景可能出现极短黑闪，打断节奏 | cut 转场应走 fast concat 路径（stream copy），不走 xfade filter chain；或至少在混合序列中对 cut 单独用 concat 拼接后再接 xfade |
| 🟡 中 | s7_video_assemble.py | 字幕时间轴使用 `shotSequence`（基于 `len(video_paths)` 即实际存在的 clip 数），而非 `shotNumber`。当有镜头缺失时，对话会错位到错误的镜头 | 对白出现在错误画面上，角色口型不匹配，观众困惑 | 使用 `shotNumber` 而非 `len(video_paths)` 做 shotSequence 映射 |
| 🟡 中 | timeline.py | xfade 重叠修正仅计算 `non_cut` 数量并注释"修正只在 S7 的 xfade offset 计算中体现"，但 `build_timeline` 并未实际修正 shot 的 `start_time/end_time`。`calc_dialogue_timeline` 使用的 `start_time` 是未修正的逻辑时间 | 字幕/对话时间轴与实际视频（含 xfade 重叠）有累积偏移，镜头越多偏移越大 | 在 `build_timeline` 中实际修正 start_time（每个非 cut 转场后减 xfade_duration），或标注此为"逻辑时间"并让 S7/S8 调用修正版 |
| 🟡 中 | s6_flf2v_render.py / s7_video_assemble.py | 两套 FPS 不一致：S6 用 FPS=25，旧 S6 用 FPS=24。S7 默认 FPS=25。若混用旧 S6 产出的 clip，帧率不匹配会导致播放速度异常 | 不同帧率的 clip 拼接后会出现加速/减速，节奏感被破坏 | 统一全局 FPS 常量到 `core/config.py`，所有脚本引用同一值 |
| 🟡 中 | video_quality_check.py | 质检仅检查 S5 静态帧（`s5_frames/`），不检查 S6 视频输出。没有运动质量评估（如帧间一致性、运动伪影检测） | 帧插值产生的伪影（morphing 变形、角色闪烁、背景扭曲）无法被拦截，直接流入最终 comic | 新增 S6 视频质检：采样关键帧序列，检测帧间一致性、morphing 伪影、首尾帧对齐度 |
| 🟡 中 | video_quality_check.py | 图像缩放至 384×216 再送 vLLM，分辨率损失严重，无法检测细节问题（手指、文字、小道具） | 低分辨率质检可能放过细节错误（多余手指、文字乱码），在高清播放时暴露 | 对质检图像使用至少 640×360 或原图 50% 以上的分辨率 |
| 🟢 低 | s6_video_assemble.py (旧版) | 旧版 S6 用 Ken Burns 缩放，与 FLF2V 管线完全不同。若误调用会产出静态帧+缓动的低质量视频 | 误用旧版会产出缺乏角色运动的"假视频"，动态质量大幅下降 | 在文件头部标注 deprecated，或直接移除 |
| 🟢 低 | s7_video_assemble.py | `concat_with_transitions` 在 xfade 失败时静默降级到 fast concat（stream copy），不报错不重试 | 观众看到硬切而非预期转场，节奏感打折扣但不算严重 | 降级时打印警告（已有 ⚠️），同时记录到 state_manager 供后续审查 |
| 🟢 低 | video_generate.py | Prompt 中 `safe_zone_reminder` 对横屏/竖屏分别设 20%/15%，但 S6 render 不感知 aspect_ratio（硬编码 1280×720） | 竖屏项目时安全区提示与实际分辨率矛盾，但当前无竖屏管线所以影响有限 | 将 aspect_ratio 传入 S6 render 的 build_flf2v_workflow |
| 🟢 低 | flf2v_keyframe.json | 模板中默认分辨率 1024×576，与 S6 代码默认 1280×720 不一致。`inject_params` 会覆盖，但模板本身是过时配置 | 新开发者直接用模板测试时会得到低分辨率输出 | 更新模板默认值为 1280×720 |

### 质量门控评估

- ✅ 已有门控:
  - **MAX_FLF2V_FRAMES=150 限制**：拒绝超长镜头，强制打回 S4 重分镜
  - **vLLM 帧质检**：对 S5 静态帧进行 5 维度评分（composition/clarity/character_fidelity/lighting/overall），低分标记 needs_regeneration
  - **ffprobe 时长校准**：timeline.py 支持从实际视频文件校准时长，修正 S4 标注偏差
  - **xfade 失败降级**：S7 在 xfade 失败时自动降级为 fast concat，不中断管线
  - **首尾帧存在性检查**：S6 在 first/last 帧缺失时跳过该镜头
  - **asset_manager fallback**：S7 在 s6_videos/ 找不到文件时尝试 assets.json 中的 active 路径

- ❌ 缺失门控:
  - **S6 视频输出质检**：FLF2V 产出的视频未经任何自动化质量检查（伪影、morphing、首尾帧对齐度）
  - **首尾帧对齐验证**：未验证首尾帧与 S5 原图的一致性（CLIP 相似度/SSIM），FLF2V 可能输出与输入帧不匹配的视频
  - **帧率一致性检查**：S7 拼接前未验证所有 clip 的 FPS 是否一致
  - **分辨率一致性检查**：S7 拼接前未验证所有 clip 的分辨率是否一致
  - **xfade offset 合法性验证**：未检查 offset 是否小于前一段时长（ffmpeg 要求 offset < 前段时长，否则报错）
  - **对话时间轴 vs 视频时长交叉验证**：未检查对话的 end_time 是否超出视频总时长
  - **转场类型合理性验证**：未检查 transitionOut 值是否在 TRANSITION_MAP 范围内（非法值静默降级为 dissolve）
  - **S6→S7 数据完整性校验**：未验证 S6 产出数量是否等于 S4 shot 数量（部分缺失会静默跳过）

### 详细分析

#### 1. FLF2V 视频质量

**首尾帧对齐**：FLF2V 的工作原理是接收首帧+尾帧图像，通过 CLIPVision 编码后插值生成中间帧。代码中 `build_flf2v_workflow` 将首尾帧分别通过 `LoadImage→CLIPVisionEncode` 送入 `WanFirstLastFrameToVideo` 节点，这是正确的流程。但存在以下风险：

- **CLIPVisionEncode 使用 `crop=center`**：如果首尾帧的长宽比与目标分辨率不一致，裁剪可能丢失关键视觉信息（角色被切掉），导致插值帧与原帧不对齐
- **4 步蒸馏（Lightx2v）**：极速推理换来的是更粗粒度的运动，可能在复杂运动场景产生 morphing 伪影（角色面部融合、肢体扭曲）
- **TeaCache 阈值 0.2**：缓存复用在静态场景有效，但在运动密集场景可能导致帧间不连续

**对 comic 动态质量的影响**：FLF2V 是整个管线的动态核心。如果首尾帧对齐偏差，观众会看到角色"变形过渡"而非"运动过渡"，直接破坏沉浸感。TeaCache 造成的帧跳变在 25fps 下尤为明显。

#### 2. xfade 链正确性

**✅ 已修复 (2026-07-05)**。详见下方修复说明。

**修复前**的关键代码：

```python
output_dur = shot_durations[0]  # 初始化为第一段时长
for i, t in enumerate(transitions):
    offset = output_dur - eff_dur  # offset = 已输出时长 - 重叠
    if cut:
        output_dur = output_dur + next_dur  # cut: 无重叠
    else:
        output_dur = output_dur + next_dur - eff_dur  # 非cut: 减去重叠
```

**问题**：当混合 cut 和 dissolve 时，cut 被映射为 `xfade=fade:duration=0`。虽然 eff_dur=0 使得两条分支的 output_dur 累加结果相同，但 `map_transition("cut")` 返回 `"fade"` 而非真正的 cut。这意味着 ffmpeg 仍然要执行 xfade filter，只是 duration=0。在某些 ffmpeg 版本中，`xfade=fade:duration=0` 会产生 1 帧的黑闪或异常帧。

**更严重的问题**：`all_cuts` 快速路径要求**所有**转场都是 cut 才走 stream copy。如果只有一个 dissolve，所有 cut 也要走 xfade filter chain（重新编码），不仅损失画质还引入上述 duration=0 的风险。

**对 comic 动态质量的影响**：混合转场序列中的黑闪/错位会在关键转场点产生视觉跳变，破坏叙事节奏的流畅性。

#### 3. 时序对齐

`timeline.py` 提供了统一的时间轴计算，但存在逻辑/实际时间的分裂：

- `build_timeline` 注释说"shot 的 start_time/end_time 不修正（它们是'逻辑'时间），修正只在 S7 的 xfade offset 计算中体现"
- 但 `calc_dialogue_timeline` 直接用 `st.start_time` 计算对话时间轴，这是未修正的逻辑时间
- S7 的 xfade 重叠会使得实际视频时长短于逻辑时长，差异 = `non_cut_count × xfade_duration`
- 对于 10 个镜头 5 个 dissolve（0.5s）的项目，差异 = 2.5s，足以让后面的对话时间轴偏移

**对 comic 动态质量的影响**：对话与画面的时间错位会让观众感觉"声音和画面不匹配"，特别是旁白说的内容和画面展示的内容对不上时。

#### 4. 转场效果

转场映射基本合理，但有几个问题：

- `circleopen`/`wipeleft`/`slideright` 等"花哨"转场在 ffmpeg xfade 中可能不如 dissolve 稳定，某些版本有渲染 bug
- 没有转场与镜头内容的适配逻辑（如：对话镜头应避免花哨转场、动作场景可用快速 cut）
- `DEFAULT_TRANSITION = "dissolve"` 是合理的安全选择

**对 comic 动态质量的影响**：不合适的转场类型会破坏叙事节奏。例如在紧张动作场景用 dissolve 会拖慢节奏，在安静对话场景用 wipeleft 会分散注意力。

#### 5. 视频质检

当前质检系统只覆盖 S5 静态帧，完全缺失对 S6 视频输出的质量保障：

- **无运动伪影检测**：FLF2V 的 morphing 变形、角色面部融合、背景扭曲无法被发现
- **无首尾帧对齐验证**：不知道视频的首尾帧是否与 S5 原图匹配
- **无帧间一致性检测**：不知道中间帧是否有突变/闪烁
- **静态帧质检分辨率过低**（384×216），可能放过细节错误
- **质检结果未被管线消费**：`needs_regeneration` 标记了但 S6 不读取，不会自动重试

**对 comic 动态质量的影响**：低质量视频（morphing 伪影、角色变形、背景扭曲）会直接流入最终产出，在观众看来就是"AI 生成的典型缺陷"，严重损害作品的专业感。

### 改进优先级

1. **P0 - xfade offset 修复 ✅ 已完成 (2026-07-05)**：
   - 新增 `get_xfade_name()` 函数：`cut → None`，其他转场 → xfade 名称字符串
   - `TRANSITION_MAP["cut"]` 改为 `None`，语义一致
   - 新增 `simple_concat()` 函数，封装 concat demuxer 调用
   - 统一 offset 公式：`offset = output_dur - eff_dur`，`output_dur += next_dur - eff_dur`
   - cut 在混合链中使用 `concat=n=2` 而非 `xfade=fade:duration=0`，消除黑闪风险
   - 全 cut 链走 `simple_concat`（stream copy，无 re-encode）
   - `map_transition()` 保留为向后兼容 alias
   - 单元测试：`tests/L0/test_s7_transitions.py`（含 offset 累积验证）
2. **P0 - S6 视频质检**：新增 FLF2V 视频质检（首帧/尾帧/中间采样帧与原图对比 + 运动一致性评估）
3. **P1 - timeline xfade 修正**：`build_timeline` 应实际修正 start_time/end_time（减去重叠），`calc_dialogue_timeline` 应使用修正后的时间
4. **P1 - 字幕 shotSequence 修复**：使用 shotNumber 而非 len(video_paths) 做映射
5. **P1 - 帧率/分辨率一致性检查**：S7 拼接前验证所有 clip 参数一致
6. **P2 - 全局 FPS 常量**：统一到 core/config.py
7. **P2 - 质检分辨率提升**：至少 640×360
8. **P3 - 旧版 S6 标注 deprecated**
9. **P3 - 模板默认分辨率更新**
