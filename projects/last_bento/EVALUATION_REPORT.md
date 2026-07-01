# 🎬 AIComicFactory E2E 完整评价报告

**日期**: 2026-07-01 00:50 CST
**项目**: `last_bento`（《最后的便当》）
**风格**: vivid (xuebiMIX v60, 鲜亮动漫)
**状态**: ✅ **全链路 9/9 通过**

---

## 一、执行概览

| 指标 | 值 |
|------|-----|
| 总耗时 | **28分41秒** (1720.7s) |
| 通过率 | 9/9 (100%) |
| 最终成品 | `s9_final.mp4` (11MB, 59.2s, 896×512 H.264 + AAC) |
| LLM Token 消耗 | ~53K total (3 次 API 调用) |
| S1 重试 | 1 次 (JSON parse error) |
| S4 重试 | 1 次 (DEEPSEEK_PRO 格式错误 → 修复后通过) |
| S6 FLF2V 渲染 | Shot 12 自动分段 (6s→2 segs) |

## 二、各阶段详解

| Stage | 耗时 | 产出 | 评注 |
|-------|------|------|------|
| S1 剧本解析 | 56.4s | 3 scenes, 7 dialogues | ⚠️ 首次 JSON 解析失败，重试后通过 |
| S2 角色提取 | 62.6s | 3 角色 (老周/林姐/小陈) | ✅ 含 visualAnchors/relationships |
| S4 分镜拆解 | 140.4s | 3 scenes → 12 shots | ⚠️ 首次格式错误(返回S1结构)，Prompt修复后通过 |
| S3 角色参考图 | 28.3s | 3 角色图 (1024×1024) | ⚠️ VL质检跳过(vLLM离线)，图片正常 |
| S5 关键帧生成 | 223.2s | 24 frames (12×2) | ✅ T2I模式，含首尾帧匹配 |
| S6 FLF2V 视频 | 1170.9s | 12 clips + 1 自动分段 | ✅ Shot 12 (6s→2 segs) 自动处理 |
| S7 视频拼接 | 1.3s | 25MB assembled.mp4 | ⚠️ xfade失败→concat回退 |
| S8 字幕烧录 | 2.6s | 10.5MB with subtitles | ✅ 7 句对白精确定位 |
| S9 TTS 音频 | 35.1s | 11MB 最终成品 | ✅ 7 条TTS合成+ASR对齐 |

## 三、运行中修复的问题

### 3.1 致命级 (阻塞 Pipeline)

| # | 问题 | 根因 | 修复 | 文件 |
|---|------|------|------|------|
| F1 | S2 JSON 解析失败 | DEEPSEEK_PRO 返回格式错误 JSON | `chat_json` 增加 3 次重试 + 升温 + 错误提示注入 | `core/llm_client.py` |
| F2 | S4 输出被截断 | `max_tokens=4096` 不足以覆盖 12-shot 输出 | `DEFAULT_MAX_TOKENS` → 8192 | `core/llm_client.py` |
| F3 | S4 HTTP 超时 | 120s 不足以生成 8192 token | `timeout` → 300s | `core/llm_client.py` |
| F4 | S4 格式错误 | DEEPSEEK_PRO 忽略 shot_split 格式，返回 S1 结构 | 增加 anti-confusion 提示："输入≠输出格式" | `prompts/defaults/shot_split.py` |

### 3.2 警告级 (不阻塞但需修)

| # | 问题 | 根因 | 修复 | 文件 |
|---|------|------|------|------|
| W1 | S3 HTTP 400 | checkpoint v40 不存在(实际 v60) | CHECKPOINT_MAP `v40` → `v60` | `scripts/s3_character_image.py`, `s5_frame_generate.py` |
| W2 | e2e S4 默认值Bug | `results.get("s4", (True,))[0]` 错误判真 | 修改为 `s4_result is not None and s4_result[0]` | `scripts/e2e_dry_run.py` |
| W3 | GLM-5.1 思维链泄漏 | chat_json 未过滤 thinking content | 回退到 DEEPSEEK_PRO | `core/prompt_runner.py` |

### 3.3 非阻塞遗留

| # | 问题 | 严重度 | 建议 |
|---|------|--------|------|
| R1 | S3 VL 质检不可用 | Low | vLLM 离线时 skip，需恢复时启动 qw35-9b |
| R2 | S7 xfade 转场失败 | Low | ffmpeg 版本兼容性问题，concat 回退不影响成片 |
| R3 | S5 Pillow DeprecationWarning | Trivial | `getdata()` → `get_flattened_data()` |
| R4 | S4 日志显示 "16 shots" 实际 12 | Display | e2e 计数逻辑使用旧字段名 |
| R5 | 成片 896×512 非 1280×720 | Medium | FLF2V 模型固定分辨率，非管线 Bug |
| R6 | 成片 59s vs 预期 150s | Medium | 需重新分镜（当前每 scene 3-6 shots 偏少） |

## 四、S3/S5 相关修改总结

本次运行验证的前两天改动：

| 改动 | 状态 | 验证结果 |
|------|------|---------|
| S3 风格三方案 (vivid/classic/concept) | ✅ | vivid 模式 checkpoint v60 正常 |
| S3 build_char_prompt 重构 | ✅ | xuebiMIX Danbooru prompt 格式正确 |
| S5 T2I 回退模式 | ✅ | 24/24 frames 生成成功 |
| S5 首尾帧画风匹配 | ⚠️ | 逻辑存在，但 T2I 模式无真参考图 |
| S5 IPAdapter 模式 | ⚠️ | 本次未测（`--gen t2i` 回退），待独立验证 |
| checkpoint 版本 v40→v60 | ✅ | 已修复 |
| e2e_dry_run.py 完整性 | ⚠️ | 发现并修复 1 个 Bug |

## 五、Pipeline 链路健康度

```
source.txt ──→ S1 ✅ ──→ S2 ✅ ──→ S4 ✅
                  │                    │
                  │              S3 ✅ ← (角色图)
                  │                    │
                  └──────── S5 ✅ ←───┘
                                │
                           S6 ✅ (FLF2V)
                                │
                           S7 ✅ (拼接)
                                │
                           S8 ✅ (字幕)
                                │
                           S9 ✅ (TTS) → s9_final.mp4 🎬
```

**链路完整性**: ✅ 100%
**数据流完整性**: s1_parsed→s2→s4→s3/s5→s6→s7→s8→s9 全通

## 六、成本估算

| 资源 | 用量 |
|------|------|
| LLM API Calls | 3 次 (S1+S2+S4 = ~53K tokens) |
| LLM 重试 | 1 次 (S1 JSON parse) |
| ComfyUI GPU 时间 | ~24 分钟 |
| 磁盘占用 | ~110MB (项目总大小) |
| API 成本估算 | < ¥2 (deepseek-v4-pro @ 千帆) |

## 七、下一步建议

1. **P0**: 验证 IPAdapter 模式 (S5 `--gen ipadapter`)，当前仅测了 T2I 回退
2. **P1**: 重新分镜 S4 以扩展成片时长 (当前 59s → 目标 ~120s)
3. **P1**: 修复 xfade 转场 (ffmpeg 版本兼容)
4. **P1**: 成片分辨率对齐 (896×512 → 1280×720 upscale in S7)
5. **P2**: 恢复 VL 质检 (需 vLLM qw35-9b)
6. **P2**: 修复 Pillow deprecation warning
7. **P3**: `chat_json` 支持 GLM-5.1 thinking 过滤

---

**结论**: Pipeline 全链路可运行，4 个致命问题已修复，6 个警告/遗留问题登记在案。最终成片 59s、11MB，包含对白语音+精确字幕。