# AIComicFactory 测试计划

**创建日期**: 2026-06-29
**目标**: 为 AICF 全部核心模块和脚本建立单元测试 + 全链路集成测试

---

## 测试分层

```
L0: 纯逻辑单元测试 (无外部依赖, mock 一切)
L1: 模块集成测试 (模块间交互, mock 外部服务)
L2: 全链路冒烟测试 (真实 GPU/API, 端到端)
```

| 层级 | 依赖 | 运行条件 | CI 友好 |
|------|------|----------|---------|
| L0 | 无 (纯 Python) | 任何时候 | ✅ |
| L1 | 本地文件系统 | 任何时候 | ✅ |
| L2 | ComfyUI + vLLM + 千帆 API + GPU | 服务就绪 | ❌ 手动 |

---

## L0: 纯逻辑单元测试

### 0.1 StateManager (`tests/test_state_manager.py`)

| 用例 | 测试内容 | 预期 |
|------|----------|------|
| init_project | 创建新项目状态 | 返回含 10 阶段的初始 state |
| get | 读取不存在的项目 | 返回空 dict |
| update_stage | 更新单阶段状态 | status/error/metadata 正确写入 |
| mark_completed | 标记完成 | status=completed, completed_at 非空 |
| mark_failed | 标记失败 | status=failed, error 有值 |
| mark_stale | 下游标记过期 | from_stage 之后的所有阶段 status=stale |
| next_pending | 获取下一待执行阶段 | 跳过 completed, 返回第一个 pending |
| progress | 进度字符串 | N/10 格式 |
| concurrent_write | 两次快速写入不丢失 | 第二次写入保留第一次部分字段 |
| _write_idempotent | 同一 state 连续写两次 | 文件内容一致 |

### 0.2 AssetManager (`tests/test_asset_manager.py`)

| 用例 | 测试内容 | 预期 |
|------|----------|------|
| register_new | 注册全新资产 | v1, is_active=True |
| register_v2 | 同一 shot+type 注册两次 | v1 is_active=False, v2 is_active=True |
| register_different_type | 同 shot 不同 type | 两条独立记录 |
| get_active | 获取活跃版本 | 返回最新版本 |
| get_active_not_found | 不存在的资产 | 返回 None |
| get_active_for_shot | 获取 shot 所有活跃资产 | dict: {type: path} |
| get_history | 获取版本历史 | 按版本号降序 |
| get_character_active | 角色资产查询 | 返回指定角色的活跃资产 |
| invalidate_shot | 作废 shot 所有资产 | 全部 is_active=False |
| list_project | 列出项目所有资产 | 按类别分组 |
| export_report | 导出文本报告 | 包含所有资产条目 |
| race_condition | 并发注册同一资产 | 版本号不重复, 无数据丢失 |

### 0.3 Prompt Registry (`tests/test_prompt_registry.py`)

| 用例 | 测试内容 | 预期 |
|------|----------|------|
| all_registered | 12 个 prompt 全部注册 | len(REGISTRY) == 12 |
| build_each | 每个 prompt 都能 build | 返回非空字符串, 无异常 |
| build_with_overrides | slot 覆盖生效 | 覆盖内容出现在输出中 |
| build_with_params | 动态参数注入 | 参数值出现在输出中 |
| get_prompt_missing | 查询不存在的 key | 返回 None |
| build_prompt_missing | build 不存在的 key | 抛出 ValueError |

### 0.4 Prompt Slot 结构 (`tests/test_prompt_slots.py`)

| 用例 | 测试内容 | 预期 |
|------|----------|------|
| slot_keys_unique | 每个 prompt 内 slot key 不重复 | len(keys) == len(set(keys)) |
| default_content_nonempty | 所有 slot 有默认内容 | defaultContent 非空字符串 |
| build_no_params | 无参数 build 不崩溃 | 返回字符串 (可含空段落) |

### 0.5 ContinuityChecker 解析 (`tests/test_continuity_parse.py`)

| 用例 | 测试内容 | 预期 |
|------|----------|------|
| parse_clean_json | 完美 JSON 响应 | 正确解析所有字段 |
| parse_json_in_codeblock | ```json 包裹的响应 | 正确提取 JSON |
| parse_json_in_backticks | ``` 包裹的响应 | 正确提取 JSON |
| parse_json_with_prefix | 有前缀文字的响应 | 正确提取 JSON |
| parse_malformed | 畸形 JSON | overall_score=-1, raw_response 有值 |
| parse_empty_response | 空响应 | overall_score=-1 |
| generate_summary | 报告生成 | 包含项目名/平均分/问题数 |

### 0.6 S7 转场逻辑 (`tests/test_s7_transitions.py`)

| 用例 | 测试内容 | 预期 |
|------|----------|------|
| xfade_name_cut | cut 转场 | 返回 None (fast concat) |
| xfade_name_dissolve | dissolve | 返回 "dissolve" |
| xfade_name_fade_in | fade_in | 返回 "fade" |
| xfade_name_fade_out | fade_out | 返回 "fade" |
| xfade_name_wipeleft | wipeleft | 返回 "wipeleft" |
| xfade_name_slideright | slideright | 返回 "slideright" |
| xfade_name_circleopen | circleopen | 返回 "circleopen" |
| xfade_name_unknown | 未知类型 | 返回默认 dissolve |
| all_cut_optimization | 全 cut 序列 | filtergraph=None, 走 simple_concat |
| mixed_transitions | 混合转场序列 | 正确构建 filtergraph |
| single_clip | 单 clip | 直接复制 |

---

## L1: 模块集成测试

### 1.1 StateManager + AssetManager 协作 (`tests/test_integration_state_asset.py`)

| 用例 | 测试内容 | 预期 |
|------|----------|------|
| init_and_register | 初始化项目后注册资产 | state 存在 + 资产文件存在 |
| invalidate_and_stale | 作废资产 + 标记下游 stale | 资产 inactive + 下游阶段 stale |
| full_lifecycle | init→register→get→invalidate→register_again | 版本历史完整 |

### 1.2 PromptRunner + Registry (`tests/test_integration_prompt_runner.py`)

| 用例 | 测试内容 | 预期 |
|------|----------|------|
| run_script_parse_mock | mock LLM 调用, 验证 prompt 构建 | 正确的 system prompt + 输出保存 |
| run_character_extract_mock | 同上 | 同上 |
| run_shot_split_mock | 同上 | 同上 |
| save_stage_output | 保存阶段输出 | 文件存在 + JSON 合法 |

### 1.3 AssetManager + Scripts 集成 (`tests/test_integration_asset_scripts.py`)

| 用例 | 测试内容 | 预期 |
|------|----------|------|
| s3_register | mock ComfyUI, 验证 s3 调用 asset_manager.register | 参数正确 (shot_id/type/version/path) |
| s3b_register | 同上 (四视图) | 参数正确 |
| s5_register | 同上 (帧生成) | 参数正确 |
| s6_register | 同上 (FLF2V) | 参数正确 |

### 1.4 ContinuityChecker + 文件系统 (`tests/test_integration_continuity_fs.py`)

| 用例 | 测试内容 | 预期 |
|------|----------|------|
| check_project_missing_s4 | 缺少 s4_shots.json | 返回 error |
| check_project_missing_frames | 缺少帧文件 | 跳过, score=-1 |
| check_project_mock_vision | mock vision API, 完整流程 | 报告 JSON 合法 |

---

## L2: 全链路冒烟测试

### 前置条件

| 服务 | 检查方式 |
|------|----------|
| ComfyUI | `curl http://127.0.0.1:8188/system_stats` |
| 千帆 API | `curl -H "Authorization: Bearer $KEY" https://qianfan.baidubce.com/v2/models` |
| GPU 可用 | `nvidia-smi` |

### 2.1 文本链路 (S1→S4)

| 步骤 | 输入 | 验证 |
|------|------|------|
| S1 script_parse | 100 字短故事文本 | s1_parsed_script.json 存在 + scenes 非空 |
| S2 character_extract | s1 输出 | s2_characters.json 存在 + characters 非空 |
| S4 shot_split | s1+s2 输出 | s4_shots.json 存在 + shots 非空 + videoScript 非空 |

### 2.2 视觉链路 (S3→S6)

| 步骤 | 输入 | 验证 |
|------|------|------|
| S3 character_image | s2 角色 | PNG 存在 + 文件 > 10KB |
| S3b four_view | s3 参考 + s2 角色 | 四视图 PNG 存在 |
| S5 frame_generate | s4 shots + s3b 参考 | 首帧/尾帧 PNG 存在 |
| S6 flf2v_render | s5 帧 + s4 videoScript | MP4 存在 + 时长 2-5s |

### 2.3 后期链路 (S7→S9)

| 步骤 | 输入 | 验证 |
|------|------|------|
| S7 video_assemble | s6 clips + s4 transitions | 最终 MP4 存在 + 转场正确 |
| S8 subtitles | s7 视频 + s4 对白 | SRT/ASS 存在 + 时间轴合理 |
| S9 tts_audio | s4 对白 | WAV 存在 + 时长合理 |

### 2.4 质量链路

| 步骤 | 输入 | 验证 |
|------|------|------|
| continuity_check | s5 帧 | 报告 JSON + 评分合理 |
| asset_report | 全程资管记录 | 版本历史完整 |

### 2.5 完整端到端

**输入**: 一个 200 字的短故事
**预期输出**: 含转场+字幕+旁白的完整视频 (≤60s)

| 检查项 | 标准 |
|--------|------|
| 视频时长 | 30-90s |
| 帧率 | 25fps |
| 分辨率 | 896×512 |
| 转场 | 与 s4 指定一致 |
| 字幕 | 时间轴与语音对齐 |
| 连续性评分 | 平均分 ≥ 60 |

---

## 测试基础设施

### 目录结构

```
tests/
├── conftest.py              # 共享 fixtures (tmp_project, mock_comfyui, etc.)
├── L0/                      # 纯逻辑测试
│   ├── test_state_manager.py
│   ├── test_asset_manager.py
│   ├── test_prompt_registry.py
│   ├── test_prompt_slots.py
│   ├── test_continuity_parse.py
│   └── test_s7_transitions.py
├── L1/                      # 模块集成测试
│   ├── test_integration_state_asset.py
│   ├── test_integration_prompt_runner.py
│   ├── test_integration_asset_scripts.py
│   └── test_integration_continuity_fs.py
├── L2/                      # 全链路冒烟测试
│   ├── test_smoke_text_pipeline.py
│   ├── test_smoke_visual_pipeline.py
│   ├── test_smoke_post_pipeline.py
│   └── test_smoke_e2e.py
└── fixtures/                # 测试数据
    ├── sample_story.txt     # 200字测试故事
    ├── sample_parsed.json   # 预生成的 s1 输出
    ├── sample_characters.json
    ├── sample_shots.json
    └── mock_vision_response.json
```

### Fixtures (conftest.py)

```python
# 核心 fixtures:
- tmp_project: tmp_path 下的完整项目目录结构
- state_manager: 绑定 tmp_project 的 StateManager
- asset_manager: 绑定 tmp_project 的 AssetManager
- mock_comfyui_response: 预构建的 ComfyUI 返回结构
- mock_vision_api: mock call_vision_llm 的返回
- sample_story: 200 字测试文本
- sample_s1_output: 预生成的 parsed script JSON
- sample_s4_output: 预生成的 shots JSON
```

### 运行方式

```bash
# L0: 随时可运行
pytest tests/L0/ -v

# L1: 随时可运行 (mock 外部服务)
pytest tests/L1/ -v

# L2: 需要服务就绪
pytest tests/L2/ -v --require-comfyui --require-api

# 全部
pytest tests/ -v

# 覆盖率
pytest tests/L0/ tests/L1/ --cov=core --cov=prompts --cov-report=term-missing
```

### 依赖

```
pytest >= 7.0
pytest-cov >= 4.0
pytest-mock >= 3.0
```

---

## 实施计划

| Phase | 内容 | 用例数 | 预估时间 |
|-------|------|--------|----------|
| **Phase A** | 测试基础设施 (conftest + fixtures + pytest 安装) | — | 0.5h |
| **Phase B** | L0 全部 (6 个测试文件) | ~45 | 2h |
| **Phase C** | L1 全部 (4 个测试文件) | ~15 | 1.5h |
| **Phase D** | L2 测试数据 + 脚本 | ~12 | 1h (编写) + 手动执行 |
| **合计** | | ~72 | ~5h |

### 优先级

1. **L0 先行** — 确保核心逻辑正确, 这是最重要的
2. **L0.2 AssetManager** — 最多边界条件, 最容易出 bug
3. **L0.5 ContinuityChecker 解析** — LLM 输出不稳定, 解析必须健壮
4. **L0.6 S7 转场** — filtergraph 构建逻辑复杂
5. **L1** — 模块间交互验证
6. **L2** — 需要全部服务就绪, 最后执行

---

## 验收标准

- [ ] L0: 全部 ~45 用例通过, 覆盖率 ≥ 80% (core + prompts)
- [ ] L1: 全部 ~15 用例通过
- [ ] L2: 文本链路 (S1→S4) 冒烟通过
- [ ] L2: 视觉链路 (S3→S6) 冒烟通过 (需 ComfyUI)
- [ ] L2: 后期链路 (S7→S9) 冒烟通过
- [ ] L2: 端到端完整视频产出
