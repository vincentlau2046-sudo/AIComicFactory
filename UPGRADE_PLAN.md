# AICB Full-Fidelity Upgrade Plan (2026-07-01)

**原则**: 完整抄 AICB，不打折扣；先代码层优化，不动实际环境；全部完成后统一测试。
**状态**: ✅ 全部代码优化已完成，待统一测试

---

## 改动文件清单（7 files）

| 文件 | 改动内容 | AICB 来源 |
|------|---------|-----------|
| `scripts/s6_flf2v_render.py` | 集成 `buildVideoPrompt` 7-slot，替代硬取 `shot["videoScript"]` | `prompts/video-generate.ts` → `buildVideoPrompt()` |
| `scripts/s7_video_assemble.py` | 完全重写：xfade filter chain + BGM + SRT subtitle burn(opt-in) + ffmpeg drawtext title/credits | `video/ffmpeg.ts` → `assembleVideo()` + `concatWithTransitions()` |
| `scripts/s8_subtitles.py` | 改为 SRT 生成器，支持 startRatio/endRatio 精确时间轴 | `video/ffmpeg.ts` → `generateSrtFile()` |
| `scripts/s5_frame_generate.py` | 注入 AICB composition suffix：compositionGuide, focalPoint, depthOfField, colorPalette, heightCm | `pipeline/frame-generate.ts` → `handleFrameGenerate()` |
| `prompts/defaults/video_generate.py` | 已有 7-slot，无需改动（S6 已正确调用） | — |
| `prompts/defaults/frame_generate_first.py` | 完整移植 AICB：画风关键词映射 + 5条参考图规则 + 连续性 + 渲染 | `prompts/frame-generate.ts` → `buildFirstFramePrompt()` |
| `prompts/defaults/frame_generate_last.py` | 完整移植 AICB：画风不可妥协 + 首帧关系 + 下镜头起点 + 渲染 | `prompts/frame-generate.ts` → `buildLastFramePrompt()` |

## 已完成 vs AICB 对照

| AICB 能力 | AICF 状态 |
|-----------|----------|
| buildVideoPrompt 7-slot (duration + charAppearance + interpolation + camera + frameAnchors + dialogue) | ✅ S6 集成 |
| assembleVideo: xfade (dissolve/fade/wipe/slide/circleopen) + cut | ✅ S7 集成 |
| assembleVideo: SRT subtitle burn via ffmpeg subtitles filter | ✅ S7 opt-in |
| assembleVideo: BGM mix (bgmVolume=0.3, -shortest) | ✅ S7 --bgm |
| assembleVideo: ffmpeg drawtext title/credits cards | ✅ S7 |
| generateSrtFile: startRatio/endRatio + auto-distribute | ✅ S8 |
| buildFirstFramePrompt: 画风关键词 + 5条参考图规则 + 连续性 + 渲染 | ✅ 移植 |
| buildLastFramePrompt: 画风强制 + 首帧关系 + 下镜头起点 + 渲染 | ✅ 移植 |
| compositionSuffix: compositionGuide + focalPoint + depthOfField + colorPalette + heightCm | ✅ S5 注入 |
| previousLastFrame continuity injection | ✅ S5 (已有) |
| SRT precise timing via Whisper ASR | ✅ S9 (已有) |
| continuity_check VL 双帧比对 | ✅ 已激活 |
| video_quality_check VL 单帧评分 | ✅ 已激活 |
| IPAdapter (角色参考图绑定) | ⚠️ 延期 (等 qwen-image-edit) |
| 四视图 character-image (2560×1440) | ⚠️ 延期 (同上) |

## Deferred

| 项 | 原因 |
|---|------|
| IPAdapter workflow integration | 等 qwen-image-edit 调通 |
| S3b 四视图 → S5 IPAdapter input | 同上 |
| character-image 改为 AICB turnaround prompt | 同上 |

## 待测试验证

1. `python scripts/e2e_dry_run.py --project last_bento` — 全链路 dry-run
2. 检查 S6 输出的 motion_prompt 是否包含完整 7-slot
3. `python scripts/s7_video_assemble.py --project last_bento` — xfade + BGM 组装
4. `python scripts/s8_subtitles.py --project last_bento` — SRT 时间轴
5. 实际 ComfyUI 运行 S5 → S6 → S7 → S8 → S9 全链路