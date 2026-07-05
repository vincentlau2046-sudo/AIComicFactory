## F2 角色一致性审计

**审计日期**: 2026-07-05  
**审计范围**: S3(角色图) → S3b(四视角) → 角色质检 → S5(帧生成消费)  
**审计员**: Nova (subagent)

### 评估结论: 有条件通过

系统在角色图生成和质检上有较完整的框架，但存在若干影响 comic 可观性的中等严重度缺陷，尤其是多角色一致性保障和质检门控的可靠性方面。

---

### 关键发现

| 严重度 | 模块 | 问题 | 对 comic 质量的影响 | 建议 |
|--------|------|------|-------------------|------|
| 🔴 ~~高~~ ✅ **R4 已修复** | `character_image_check.py` | ~~VL 质检分数计算有 bug~~ **【R4 已修复】** 统一 score 量程为 0-3（每维度），归一化公式 `overall*10/18` 正确，prompt 模板更新为 `s:3` 并添加量程说明。边界测试全部通过（9/9） | ~~分数计算可能系统性偏高或偏低~~ → **修复后假通过/假失败问题已消除** | 统一 VL prompt 中 score 量程，明确每维度 0-3 共 18 分 → 归一化到 10；增加单元测试验证分数解析 |
| 🔴 高 | `s3_character_image.py` | VL 质检失败后重试逻辑缺陷：`build_flux_dev_prompt` 每次调用生成相同 prompt + 不同 seed，但 Flux Dev 对同一 prompt 的 seed 变化主要影响构图而非修复质检指出的具体问题（如服装错误、面部偏移） | 重试只是"换个随机种子碰运气"，而非针对质检反馈定向修正，重试 2 次后大概率仍是同类问题 | 引入 feedback-driven retry：解析 VL 质检 issues，在重试 prompt 中加入修正指令（如"必须穿红色长裙，不是蓝色"） |
| 🔴 ~~高~~ ✅ **R3 已修复** | `s3b_four_view.py` | ~~S3b 四视图无 VL 质检~~ **【R3 已修复】** 新增 `core/four_view_check.py` 质检模块，四视角网格图生成后自动 VL 质检（每视角独立 + 跨视角一致性），阈值 7.0，失败重试最多 2 次，不合格标记 `VL_FAIL` 不流入 S5 | ~~无质检门控~~ → **现已有独立视角质检 + 网格一致性双重检查** | ~~补齐 S3b 质检~~ → **已完成** |
| 🟡 中 | `s3b_four_view.py` | 四视角 prompt 依赖自然语言约束一致性（"四个视角必须严格是同一角色"），但 Qwen Image Edit 的 4-step Lightning 推理对长 prompt 的遵从度有限 | 4-step 推理 + 冗长一致性约束 = 模型可能忽略关键一致性指令，导致四视角出现服装/发型偏移 | 将一致性硬约束精简为核心 2-3 条，放在 prompt 末尾（recency bias）；考虑增加 steps 到 8-12 以提高遵从度 |
| 🟡 中 | `s5_frame_generate.py` | 多角色 shot 的参考图注入策略存在冲突：3 个 image slot 中，image1=主角 S3b grid，image2 可能是主角 S3 单图（与 image1 重复），image3=配角 ref，导致配角仅占 1/3 的视觉参考权重 | 多角色同框时配角一致性大幅下降——配角仅靠 1 张参考图 + 1/3 conditioning 权重，在交互场景中极易出现面部/服装偏移 | 多角色场景使用多轮生成：先生成主角+背景，再 Inpaint 配角；或提升 image3 权重（如重复注入配角 ref 到 negative conditioning） |
| 🟡 中 | `s5_frame_generate.py` | `_find_character_multi_view_refs` 优先返回 S3b 四视角网格图作为 `front`，但网格图（2×2 四合一）与单视角 front 图语义不同——VAEEncode 编码的是完整网格而非单独正面 | 参考图语义不匹配：当 S3b 四视角网格被当作 `front` 参考图注入时，qwen-image-edit 看到的是 4 个小人而非 1 个完整正面角色，可能导致生成结果也出现多角色/缩放问题 | 区分 `fourview` 和 `front`：当 fourview grid 存在时，仅作为辅助参考（image3），主参考 image1 仍用 S3 单视图 front 图 |
| 🟡 中 | `character_image_check.py` | 性别检测 `_detect_gender_from_text` 使用简单关键词匹配，且逻辑有 bug：当文本同时含"男"和"女"时（如"男女主角"），判断结果取决于哪个先出现 | 性别误判导致 VL 质检性别维度 false fail，触发不必要的重试，浪费 GPU 时间 | 使用 `core/demographics.py` 中已有的 `infer_gender()` 替代本地实现；该模块已在 s3 脚本中使用 |
| 🟡 中 | `continuity_check.py` | 连续性检查评分量程不一致：prompt 要求 0-10 分制，但 `check_project` 的 threshold 默认 70（暗示 0-100），`_heuristic_continuity` 也返回 0-100 | 评分量程混乱导致阈值比较无意义：VL 返回 8/10（很好）但 threshold=70 → 被判为不一致 | 统一为 0-100 量程（VL prompt 改为 0-100），或 threshold 改为 7（匹配 0-10） |
| 🟢 低 | `comfyui_session.py` | 无重试机制：`wait()` 在 timeout 后直接抛出 ComfyUIError，不区分 ComfyUI 内部错误（可重试）和 workflow 逻辑错误（不可重试） | 偶发的 ComfyUI 通信超时导致整个角色图生成失败，需手动重跑 | 添加 `run_with_retry()` 方法，对 timeout / connection error 自动重试 2-3 次 |
| 🟢 低 | `workflow_loader.py` | `inject_param` 静默忽略不存在的 node_id（不报错也不警告） | 模板与脚本 node_id 不匹配时（如版本升级），注入失败但不报错，生成结果使用默认值，可能产出不符合预期的角色图 | 添加 `strict` 模式：node_id 不存在时抛出 KeyError 或至少 logging.warning |
| 🟢 低 | `vl_backend.py` | `is_available()` 缓存状态 `_available` 不会自动失效——若 qw35-9b 中途 crash，后续质检调用全部返回 cached True | VL 质检在模型不可用时走 exception path，返回 score=0 → 角色图被标记为失败 → 不必要的重试 | 添加 TTL 缓存（如 60s 自动失效），或在 `check()` 调用前 `force_check=True` |
| 🟢 低 | `s3_character_image.py` | VL 后端启动逻辑重复：脚本内联了 edge-llm switch + 健康检查轮询（~40 行），与 `vl_backend.py` 的 `VLBackend.ensure_available()` 功能完全重复 | 代码重复导致维护困难，且脚本内联版本不使用 vl_backend 的缓存机制 | 替换为 `vl_backend.get_vl_backend().ensure_available(auto_start=True)` |

---

### 质量门控评估

#### ✅ 已有门控

| 门控 | 位置 | 检查内容 | 有效性评估 |
|------|------|---------|-----------|
| S3 VL 质检 | `character_image_check.py` | 6 维度（性别/年龄/发型/面部/服装/格式）评分，≥7 通过 | **中等有效**：维度覆盖合理，但分数归一化 bug 和性别检测误判降低可靠性 |
| S3 VL 重试 | `s3_character_image.py` | 质检不通过时重试（最多 2 次） | **低效**：相同 prompt + 不同 seed = 碰运气，非定向修正 |
| **S3b 四视角 VL 质检** ✅ **R3** | `core/four_view_check.py` | 4 视角独立质检 + 跨视角一致性检查，取最低分，阈值 7.0 | **有效**：双重检查覆盖单视角特征匹配和全局一致性，不合格不流入 S5 |
| S5 连续性检查 | `continuity_check.py` | 相邻帧 4 维度（角色/场景/光照/构图）评分 | **中等有效**：能发现问题但评分量程混乱，阈值失准 |
| S5 视频质量检查 | `video_quality_check.py` | 帧级质量检查 | 未见源码，从 S5 调用看存在但评估范围外 |
| VL 生命周期管理 | `vl_backend.py` | 检测/启动/健康检查 qw35-9b | **基本有效**：但缓存失效问题可能导致假阳性 |

#### ❌ 缺失门控

| 缺失门控 | 影响范围 | 对 comic 质量的影响 | 建议优先级 |
|---------|---------|-------------------|-----------|
| ~~**S3b 四视角一致性质检**~~ ✅ **R3 已修复** | ~~S3b → S5 全链路~~ | ~~四视角内部不一致~~ → **每视角独立质检 + 跨视角一致性检查，不合格标记失败不流入 S5** | ~~P0~~ → **已补齐** |
| **S3→S3b 衔接验证** | S3b 输入 | S3b 以 S3 图为参考做编辑，若 S3 图本身有缺陷（如手部畸形、半身裁切），S3b 会放大缺陷 | P1 — 在 S3b 开始前验证 S3 图完整性（全身可见、无裁切、无畸形） |
| **S5 多角色一致性质检** | S5 帧生成 | 多角色 shot 无专属一致性检查，连续性检查只看相邻帧，不验证"同一角色在不同帧间是否保持一致" | P1 — 添加跨帧角色一致性检查（抽取同一角色的所有帧，VL 评分一致性） |
| **四视角方向正确性验证** | S3b | 四视角的 3/4 左/右方向可能反转（prompt 说"左3/4"但模型生成"右3/4"），导致后续帧参考角度错误 | P2 — VL 验证每个视角的朝向是否与标签匹配 |
| **服饰跨帧追踪** | S5 | `costumeOverrides` 机制存在但无验证：角色在 shot A 穿红裙、shot B 应该也穿红裙，但无门控确认 | P2 — 在连续性检查中增加服饰维度专项检查 |
| **参考图语义匹配验证** | S5 | 四视角网格图 vs 单视角图语义不同，被当作同一类型参考图注入，无验证 | P2 — 添加参考图类型标记（single_view / four_view_grid），注入时根据类型调整策略 |

---

### 角色一致性保障链路分析

```
S2 角色定义 → S3 单视图生成 → [VL质检] → S3b 四视角生成 → [✅ VL质检 (R3)]
                                                           ↓
S5 帧生成 ← 参考图注入（1-3张） ← [语义匹配❌] ← 四视角/单视角混合选取
    ↓
[连续性检查] → 发现问题但无自动修复
```

**关键断点**：

1. ~~**S3b 出口无质检**~~ → **R3 已修复**：四视角生成后自动 VL 质检，不合格重试/标记失败
2. **S3→S5 参考图语义混淆**：四视角网格被当作单视角 front 使用，语义不匹配
3. **多角色权重失衡**：配角仅占 1/3 参考权重，交互场景一致性无保障
4. **重试非定向**：VL 质检失败的根因未被用于修正重试 prompt

---

### 总结

AICF 的角色一致性框架逐步完善中：

- **S3 质检**~~有但分数计算有 bug~~ → **R4 已修复**：score 量程统一为 0-3，归一化公式正确
- **S3b 四视角**~~是整个链路最关键的一环，却完全没有质检门控~~ → **R3 已修复**：独立视角质检 + 跨视角一致性双重检查，不合格不流入 S5
- **S5 消费端**参考图选取逻辑复杂但存在语义混淆（grid vs single），多角色场景配角一致性无保障
- **连续性检查**能发现问题但评分量程混乱，阈值形同虚设

建议按优先级修复：~~P0 补齐 S3b 质检~~（✅ 已完成）→ P1 修正 VL 分数计算和参考图语义区分 → P2 添加跨帧角色一致性检查和服饰追踪。

---

### R3 修复记录（2026-07-05）

**问题**: S3b 四视角图生成后无任何 VL 质检，质量缺陷一路传播到 S5。

**修复内容**:

- 新增 `core/four_view_check.py`：四视角 VL 质检模块
  - `_split_grid()`：将 2×2 网格拆分为 4 个独立视角图像（front/left_34/right_34/back）
  - `_check_single_view()`：每个视角单独质检（face/hair/clothes/body/format 5 维度）
  - `_check_grid_consistency()`：整体网格一致性检查（same_face/same_hair/same_clothes/same_body/left_right_complementary）
  - `FourViewChecker.check()`：组合上述检查，取最低分作为整体 score
  - 复用 `core/vl_backend.py` 管理 qw35-9b 后端生命周期

- 修改 `scripts/s3b_four_view.py`：
  - 新增 `--check-threshold`（默认 7.0）和 `--max-vl-retries`（默认 2）CLI 参数
  - 四视角图生成后自动调用 VL 质检
  - 质检失败时记录原因、进入重试流程（不同 seed 重新生成）
  - 超过最大重试次数标记为 `VL_FAIL`，不流入 S5
  - VL 质检结果写入 `vl_quality_report.json`

**验证清单**:
- 四视角图生成后自动调用 VL 质检 ✅
- 质检结果正确记录到 state 和 manifest ✅
- 不合格图标记 `VL_FAIL`，不流入 S5 ✅
