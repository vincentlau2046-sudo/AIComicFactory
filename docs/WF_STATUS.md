# Westward Factory 现状备忘

**记录日期**: 2026-06-28
**源码位置**: `~/westward_factory/`

---

## 1. 管线流程 (8 Stage)

```
S1: generate_tts_script.py → s1_tts_script.json
S2: generate_tts.py → s2_tts_audio/
S3: calculate_duration.py → s3_duration.json
S4: generate_keyframes_v2.py → s4_composites/
S5: render_flf2v.py → s5_flf2v/
S6+S7: assemble_episode.py → output/
S8: generate_subtitles.py → s8_subtitles/
```

## 2. 与 AIComicFactory 的对应关系

| WF Stage | AICF Stage | 差异 |
|----------|-----------|------|
| — | S1 script_parse | WF 无，剧本是手工 JSON |
| — | S2 character_extract | WF 无，角色是手工贴纸 |
| — | S3 character_image | WF 无，贴纸是手工素材 |
| — | S4 shot_split | WF 无，分镜是手工 episode.json |
| S1 (TTS script) | TTS 前置 | AICF 的 TTS 在 S7 assemble 阶段处理 |
| S4 (关键帧) | S5 frame_generate | WF 用 sticker 合成，AICF 用 img2img+IPAdapter |
| S5 (FLF2V) | S6 video_generate | 基本对应 |
| S6+S7 (合成) | S7 video_assemble | 基本对应 |
| S8 (字幕) | S8 subtitles | 基本对应 |
| S2+S3 (TTS+时长) | S7 前置 | AICF 将 TTS 嵌入 assemble 阶段 |

**关键差异**: WF 的 S1-S4 都是人工前置，AICF 的 S1-S4 全部由 LLM 自动化。

## 3. 可直接复用的模块

| 模块 | 路径 | 说明 |
|------|------|------|
| ComfyUISession | core/comfyui_session.py | 工业级 API 客户端，直接复制 |
| alignment_engine | core/alignment_engine.py | 时空对齐，部分概念可复用 |
| composite_engine | core/composite_engine.py | 贴纸合成，AICF 不用（用 IPAdapter） |
| denoise_calculator | core/denoise_calculator.py | denoise 计算，可复用 |
| alpha_validator | core/alpha_validator.py | 贴纸质检，AICF 不用 |
| asset_version | core/asset_version.py | 版本管理，概念可复用 |
| assemble_episode.py | scripts/assemble_episode.py | FFmpeg 合成，可复用+扩展 |
| generate_subtitles.py | scripts/generate_subtitles.py | Whisper ASR+矫正，可复用 |
| render_flf2v.py | scripts/render_flf2v.py | FLF2V 渲染，可复用 |
| calculate_duration.py | scripts/calculate_duration.py | 时长计算，可复用 |

## 4. WF 已知问题 (AICF 需解决)

1. **FLF2V = 帧插值，非角色动画** → AICF 接受此局限，用 motionScript 描述运镜为主
2. **配乐/环境音缺失** → AICF S7 需实现 BGM 叠加
3. **画面与内容关联弱** → AICF 用 LLM 生成 per-shot prompt，而非通用底图+贴纸
4. **TTS 音质不稳定** → AICF 继续用 Qwen3-TTS，需关注 unload_model_after_generate
5. **amix 混叠 bug** → AICF 已知：语音串行，BGM 可并行叠合

## 5. episode.json Schema (WF 当前)

```json
{
  "episode_id": "ep_001",
  "title": "石破天惊",
  "source": "西游记第一回",
  "resolution": {"width": 896, "height": 512},
  "title_card": {...},
  "scenes": [{
    "scene_id": "s01",
    "narration": "...",
    "background": "assets/scene_bases/huaguoshan.png",
    "clips": [{
      "clip_id": "s01_c01",
      "duration_frames": 149,
      "characters": [{
        "name": "wukong",
        "sticker": "assets/stickers/wukong@v1.0.0.png",
        "start_pose": {x_percent, y_percent, scale, action_label},
        "end_pose": {x_percent, y_percent, scale, action_label}
      }],
      "motion_prompt": "...",
      "camera_movement": {type, start_distance, end_distance, duration, easing}
    }]
  }]
}
```

**与 AICF Shot 模型的差异**:
- WF: clip_id + characters(sticker+pose) + motion_prompt + camera_movement
- AICF: shot_id + prompt + motionScript + videoScript + cameraDirection + compositionGuide + focalPoint + depthOfField + transitionIn/Out + soundDesign + musicCue + costumeOverrides
- AICF 的 shot 模型远比 WF 的 clip 模型丰富（多7个维度）

## 6. 已有剧本资产

- 56 集 episode.json 在 `~/westward_factory/episodes/`
- 可作为 AICF 的 source.txt 输入（S1 script_parse 的原始材料）
- 迁移方式: 将 ep_NNN.json 的 scenes[].narration + clips[].motion_prompt 拼接为纯文本

## 7. GPU/ComfyUI 配置

见 MEMORY.md 和 PROJECT.md 第十一章。
