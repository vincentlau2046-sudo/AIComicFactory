# 本地化改造可行性评估

**评估日期**: 2026-06-28
**评估结论**: ✅ 整体可行，3 个妥协点

---

## 模块映射

| 原模块 | 云端实现 | 本地替代 | 改造量 |
|--------|---------|---------|--------|
| AI Text | OpenAI / Gemini API | vLLM (Qwen3.6-27B) | 中 — prompt 精简+guided_json |
| AI Image | DALL-E / Imagen / Kling | ComfyUI (SDXL + IPAdapter) | 高 — 四视图→单参考图 |
| AI Video | Seedance / Kling / Veo | ComfyUI (Wan2.2 FLF2V) | 高 — 仅keyframe模式 |
| Task Queue | SQLite + 原子 claim | Python 简易队列/串行 | 低 |
| DB | Drizzle + SQLite | 文件系统 (JSON) | 低 |
| Prompt Registry | TypeScript 插槽 | Python dict / YAML | 中 |
| FFmpeg 合成 | fluent-ffmpeg | subprocess + ffmpeg CLI | 低 |
| Agent 集成 | 百炼/Dify/Coze | 删除 | 零 |
| UI | Next.js + React | 删除 | 零 |

---

## 逐阶段可行性

### S1 script_parse ✅
- Qwen3.6-27B 128K 上下文，prompt 长度无压力
- 风险: 指令遵循弱于 GPT-4
- 缓解: 精简 prompt + guided_json + 多轮修正

### S2 character_extract ✅
- 同 S1 风险，但 prompt 更复杂
- 缓解: 三层铁律保留，示例精简

### S3 character_image ⚠️
- 四视图是改造难度最高环节
- ComfyUI SDXL 不原生支持四视图
- 妥协: 放弃四视图，改用单正面参考图 + IPAdapter

### S4 shot_split ✅
- 输出格式复杂（嵌套 scene→shots）
- 缓解: guided_json + prompt 精简

### S5 frame_generate ✅
- ComfyUI T2I/img2img 已成熟
- IPAdapter 注入角色参考图
- 前帧连续性: img2img 或 IPAdapter

### S6 video_generate ⚠️
- Keyframe 模式: FLF2V 直接对应 ✅
- Reference 模式: FLF2V 不支持 ❌
- 妥协: 仅使用 Keyframe 模式

### S7 video_assemble ✅
- FFmpeg 已在本地
- 转场实现需 ffmpeg xfilter

### S8 subtitles ✅
- Whisper ASR + 脚本矫正，已有实现

---

## 本地模型能力瓶颈

| 能力 | GPT-4/Gemini | Qwen3.6-27B | 影响 |
|------|-------------|-------------|------|
| 超长指令遵循 | 极强 | 中等 | 复杂 prompt 可能部分忽略 |
| 结构化 JSON | 稳定 | 较稳定(+guided_json) | 需后处理兜底 |
| 角色视觉描述 | 极高 | 中高 | 可能丢细节 |
| 分镜专业度 | 高 | 中 | motionScript 可能简化 |
| 图像质量 | DALL-E3极强 | SDXL中高 | 靠IPAdapter补 |
| 视频运动 | Seedance2极强 | FLF2V中 | 运镜为主 |
| 视频速度 | API秒级 | ~48s/81帧(已加速) | 可接受 |

---

## 三个妥协点

1. **四视图 → 单参考图 + IPAdapter**: 一致性靠 IPAdapter 而非多角度模板
2. **Reference 视频模式 → 放弃**: FLF2V 只支持 keyframe
3. **Prompt 质量降级**: 27B 对超长指令遵循弱，需精简+guided_json+后处理
