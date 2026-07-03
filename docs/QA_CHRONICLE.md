# AICF 质量记录

> 合并自: `docs/TEST_PLAN.md`、`docs/TEST_REPORT.md`、`docs/V2_DRY_RUN_LOG.md`
> 按时间正序排列，后续测试/质量记录直接追加

---

## 2026-06-29 测试计划

测试分层:

| 层级 | 依赖 | 运行条件 |
|------|------|----------|
| L0 | 无 (纯 Python) | 任何时候 |
| L1 | 本地文件系统 | 任何时候 |
| L2 | ComfyUI + vLLM + 千帆 API + GPU | 服务就绪 |

### L0: 纯逻辑单元测试 (6 文件, ~45 用例)

| 文件 | 内容 | 用例数 |
|------|------|--------|
| `test_state_manager.py` | init/get/update/mark/next_pending/progress/并发 | ~12 |
| `test_asset_manager.py` | register/get_active/history/invalidate/并发 | ~15 |
| `test_prompt_registry.py` | 注册/build/override/参数注入/异常 | ~6 |
| `test_prompt_slots.py` | key 唯一/默认内容/build 不崩溃 | ~3 |
| `test_continuity_parse.py` | 解析/异常容错 | ~7 |
| `test_s7_transitions.py` | 转场类型/all-cut 优化/混合序列 | ~11 |

### L1: 模块集成测试 (4 文件, ~15 用例)

| 文件 | 内容 |
|------|------|
| `test_integration_state_asset.py` | StateManager + AssetManager 协作 |
| `test_integration_prompt_runner.py` | PromptRunner + Registry |
| `test_integration_asset_scripts.py` | AssetManager + Scripts |
| `test_integration_continuity_fs.py` | ContinuityChecker + 文件系统 |

### L2: 全链路冒烟测试 (4 文件, ~12 用例)

- 文本链路 S1→S4
- 视觉链路 S3→S6
- 后期链路 S7→S9
- 完整端到端 (200 字输入 → ≤60s 视频)

### 测试基础设施

```
tests/
├── conftest.py              # 共享 fixtures
├── L0/                      # 纯逻辑测试
├── L1/                      # 模块集成测试
├── L2/                      # 全链路冒烟测试
└── fixtures/                # 测试数据
```

### 验收标准

- [ ] L0: ~45 用例通过, 覆盖率 ≥ 80%
- [ ] L1: ~15 用例通过
- [ ] L2: 文本/视觉/后期/端到端冒烟通过

---

## 2026-06-29 测试报告 (执行结果)

**环境**: Python 3.13.13, pytest 9.1.1, RTX 5090 D, ComfyUI on :8188

| 指标 | 值 |
|------|-----|
| 总用例 | 110 |
| 通过 | **110 ✅** |
| 失败 | 0 |
| 覆盖率 (L0+L1) | **81%** |
| 全量耗时 | 64.2s |

### L0: 78 ✅ | L1: 24 ✅ | L2: 8 ✅

| L2 测试 | 耗时 | 说明 |
|---------|------|------|
| S3 角色参考图 | 10s | Animagine XL T2I |
| S5 prompt+workflow | <1s | 结构验证 |
| S5 图像生成 | 44s | Qwen Image Edit (修复后) |
| S6 FLF2V 视频渲染 | 16s | 首尾帧→25fps clip |
| S7 转场+视频验证 | <1s | ffprobe |
| S8 ASS 字幕 | <1s | 格式验证 |
| S9 TTS 音频 | <1s | 音频流验证 |
| S1+S2+S4 文本链路 | ~10min | 千帆 API (单独运行) |

### S5 Bug 修复详情

**根因**: `qwen_image_edit_2511_fp8mixed.safetensors` 不包含标准 CLIP。
`CheckpointLoaderSimple` 返回 CLIP=None → `CLIPTextEncode` 负向节点失败。

**修复**: 架构重构

| 旧架构 | 新架构 |
|--------|--------|
| CheckpointLoaderSimple | UNETLoader + CLIPLoader + VAELoader |
| CLIPTextEncode (负向) | TextEncodeQwenImageEditPlus (负向) |
| euler_ancestral / normal | euler / simple |
| EmptyLatentImage | VAEEncode(参考图) |
| 无 shift | ModelSamplingAuraFlow(shift=3.1) |
| LoraLoader | LoraLoaderModelOnly |

---

## 2026-07-02 V2 全链路 Dry Run

**项目**: last_bento (最后的便当)

### 决策确认

| # | 决策点 | 方案 |
|---|--------|------|
| D1 | S3 Flux Dev 分辨率 | 1024×1536 |
| D2 | Flux Dev 推理步数 | 28步 dpmpp_2m/sgm_uniform, cfg=4.0 |
| D3 | S5 多角色参考图上限 | 3张 |
| D4 | S5 前帧注入位置 | image3 |
| D5 | S4b 独立 stage | 是 |

### 发现并修复的 Bug (4 个)

| # | 问题 | 根因 | 修复 |
|---|------|------|------|
| 1 | Flux '毛玻璃' 图片 | Prompt 中背景指令权重过高 → 75% 白色背景 | character-first 架构重写 |
| 2 | D2 参数不足 | 20步 euler/simple 产出偏柔和 | 28步 dpmpp_2m/sgm_uniform, cfg=4.0 |
| 3 | VL 关闭循环不 break | --no-check 模式下每个角色生成3次 | 添加 break |
| 4 | multi-ref LoadImage 占位符不存在 | 模板中 node 42/43 引用不存在的文件 | fallback 到 ref_image |

### 全链路验证

| Stage | 结果 | 备注 |
|-------|------|------|
| S3 Flux Dev | ✅ 3 chars | prompt 重写后质量提升 (nw 75%→0%) |
| S3b qedit | ✅ 12 views | 四视图无错误 |
| S4b | ✅ 16 shots | 新 stage 正常工作 |
| S5 | ✅ 26/32 frames | 4 shots 无角色跳过 (正确) |
| S6 | ✅ 13/16 videos | 3 shots 无帧跳过 (正确) |
| S7 | ✅ 31.8MB | 组装成功 |
| S8 | ✅ 7 dialogues | SRT+ASS |
| S9 | ✅ 30.9MB | 最终成片 |