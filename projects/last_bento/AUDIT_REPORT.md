# AICF 端到端审计报告 — last_bento

**日期**: 2026-07-01  
**项目**: 《最后的便当》  
**执行**: Nova (OpenClaw) — 从 source.txt 清理后端到端全链路重跑  
**总耗时**: ~75 分钟 (22:07 - 23:25)

---

## 一、执行摘要

| Stage | 状态 | 耗时 | 产出 |
|-------|------|------|------|
| S1: script_parse | ✅ | ~3min | s1_parsed.json (3KB, 3 scenes, 7 dialogues) |
| S2: character_extract | ✅ | ~1min | s2_characters.json (5KB, 3 characters + 3 relationships) |
| S3: character_image | ✅ | ~7min | 3/3 参考图 (1.8MB, concept风格) |
| S4: shot_split | ✅ | ~2min | s4_shots.json (17KB, 16 shots) |
| S5: frame_generate | ✅ | ~8min | 32/32 帧 (51MB, IPAdapter模式) |
| S6: video_generate | ✅ | ~54min | 16/16 视频 (86MB, FLF2V+Lightx2v+TeaCache) |
| S7: video_assemble | ✅ | ~1min | s7_assembled.mp4 (47.3MB, 84.3s, xfade转场) |
| S8: subtitles | ✅ | <1min | SRT+ASS (7 dialogues) |
| S9: TTS+ASR | ✅ | ~4min | s9_final.mp4 (44.8MB, 88.5s) |

**最终产出**: `s9_final.mp4` — 3.5MB, ~88.5s

---

## 二、问题清单

### 🔴 P0 — 阻断性 Bug (已修复)

| # | Stage | 问题 | 根因 | 修复 | 影响 |
|---|-------|------|------|------|------|
| 1 | S5 | `IndexError: list index out of range` — 无角色镜头走 IPAdapter 路径时 `ipa_ref_nodes[0]` 空引用 | `generate_frame()` 不检查 `ref_images` 是否为空 | 增加 fallback: `not ref_images → T2I` | Shot 1/4/11 无角色场景无法生成 |
| 2 | S7 | xfade offset 计算错误 → 16 shots (85s) 组装后仅 8.5s | `cumulative_offset` 计算逻辑错误：xfade 后输出增长量应为 `next_dur - xfade_dur`，而非 `offset` | 重写 offset 算法：用 `output_dur` 追踪实际输出时长，每次 xfade 后 `output_dur += next_dur - eff_dur` | 成片时长错误，S9 音频对齐全部偏移 |
| 3 | S7 | `SyntaxError: name 'W' is used prior to global declaration` | `global W, H` 在 `default=W` 引用之后声明 | 改为硬编码 default=1280/720 | S7 无法运行 |

### 🟡 P1 — 需要关注

| # | Stage | 问题 | 根因 | 影响 | 状态 |
|---|-------|------|------|------|------|
| 4 | S6 | Python stdout 完全缓冲，`process poll` 看不到输出 | Python buffering | 无法实时监控进度 | ✅ 已修复 (加 `sys.stdout.reconfigure(line_buffering=True)`) |
| 5 | S3/S5 | VL 质检跳过 — qw35-9b 未启动 | `edge-llm switch` 超时 | 角色参考图/帧无 VL 质量把关 | ⚠️ 下次需在 S3 前启动 qw35-9b，S6 前释放 |
| 6 | S5 | 多角色 IPAdapter 只用第一张参考图 | 代码只取 `ipa_ref_nodes[0]` | 多角色同框时一致性下降 | ⚠️ 已决策：IPA 不成熟前走 prompt 特征一致性 TIV 路线 |
| 7 | S4 | 分镜 prompt 为英文，motionScript/videoScript 为中文 | AICB 规范 prompt 英文、script 中文 | 无功能影响，但需确认下游消费端兼容 | ℹ️ 保持现状 |
| 8 | S7 | 标题卡/结束卡使用 ffmpeg drawtext | CJK 字体依赖系统安装 | 需确保 NotoSansCJK 存在 | ℹ️ 已有路径 |

### 🟢 P2 — 改进建议

| # | Stage | 建议 | 说明 |
|---|-------|------|------|
| 9 | S6 | >5s 自动分段 + mid-frame 已生效 | 8/16 shots 触发了 Path D，中帧衔接正常 |
| 10 | S5 | 多角色场景应走 prompt 特征一致性路线 | IPA 方案不成熟，已决策用 TIV prompt-driven 替代 |

---

## 三、质量评估

### 3.1 文本链路 (S1→S2→S4)

| 维度 | 评分 | 说明 |
|------|------|------|
| 原文保真 | 9/10 | 7句对白全部逐字保留，1处省略号规范（「……」→ 原文格式） |
| 角色规格 | 8/10 | visualAnchors/visualHint/performanceStyle 齐全，description 密度高 |
| 分镜质量 | 8/10 | 16 shots 合理拆分，motionScript 3s分段，videoScript 30-60词 |
| 数据格式 | 7/10 | S4 startRatio/endRatio 缺失部分 shot（仅5/16有对白字段） |

### 3.2 图像链路 (S3→S5)

| 维度 | 评分 | 说明 |
|------|------|------|
| 角色一致性 | 6/10 | IPAdapter 单参考图，多角色同框时一致性中等 |
| 画风统一 | 7/10 | concept 风格统一，T2I fallback 场景略有色差 |
| 构图 | 7/10 | compositionGuide 正确注入，但 SDXL 对专业构图术语响应有限 |
| 帧质量 | 7/10 | brightness 检测通过，无纯黑/过曝 |

### 3.3 视频链路 (S6→S9)

| 维度 | 评分 | 说明 |
|------|------|------|
| 运动质量 | 5/10 | FLF2V 以 zoom/pan 为主，缺乏肢体动作（已知局限） |
| 转场 | 8/10 | xfade 7种转场正常工作，dissolve/fade_out 效果好 |
| TTS | 7/10 | Qwen3-TTS 中文质量良好，7 clips 全部生成 |
| 字幕 | 7/10 | ASS 三样式（旁白/心声/对话），时间轴基于 startRatio 对齐 |
| 音视频合轨 | 7/10 | 最终成片正常播放，音频 normalized -12dB |

---

## 四、时间分析

| Phase | 耗时 | 占比 | 瓶颈 |
|-------|------|------|------|
| S1-S2-S4 (文本) | ~6min | 8% | LLM API 响应 |
| S3 (角色参考图) | ~7min | 9% | ComfyUI SDXL 推理 |
| S5 (首尾帧) | ~8min | 11% | ComfyUI IPAdapter + SDXL |
| S6 (FLF2V 视频) | ~54min | 72% | **主瓶颈** — 16 shots × ~3.5min/shot |
| S7-S9 (合成) | ~6min | 8% | FFmpeg + TTS |

**S6 占 72% 时间**，即使有 Lightx2v 4-step + TeaCache 加速。

---

## 五、代码 Bug 汇总

| Bug ID | 文件 | 行号 | 状态 |
|--------|------|------|------|
| BUG-001 | `scripts/s5_frame_generate.py` | ~370 | ✅ 已修复 |
| BUG-002 | `scripts/s7_video_assemble.py` | 464 | ✅ 已修复 |

---

## 六、与上次的对比

| 维度 | 上次 (2026-07-01 凌晨) | 本次 | 变化 |
|------|------------------------|------|------|
| S1 scenes | 3 | 3 | 一致 |
| S2 characters | 3 | 3 | 一致，visualAnchors 更完整 |
| S4 shots | 12 | 16 | +4 shots (更细粒度分镜) |
| S5 frames | 24 | 32 | +8 帧 (对应更多 shots) |
| S6 videos | 12 | 16 | +4 视频 |
| S7 transition | fast concat | xfade 7种 | 转场质量 ↑ |
| S8 format | ASS only | SRT+ASS | 双格式输出 |
| S9 TTS | 已集成 | 已集成 | 一致 |
| Bug 修复 | — | 2 个 | S5 fallback + S7 global |

---

## 七、待办事项 (优先级排序)

1. **P0**: S6 输出缓冲 — 加 `PYTHONUNBUFFERED=1` 或 `sys.stdout.reconfigure(line_buffering=True)`
2. **P0**: S5 多角色 IPAdapter — 实现 Batch Images 或多参考图 concat
3. **P1**: 视频时长与分镜时长对齐 — FLF2V 帧数 vs duration 字段
4. **P1**: VL 质检集成 — S3/S5 启动 qw35-9b 后端
5. **P2**: S7 标题卡 CJK 字体检测 + 自动 fallback
6. **P2**: S4 prompt 统一为中文或英文（AICB 规范确认）

---

**报告生成**: 2026-07-01 23:26 by Nova
