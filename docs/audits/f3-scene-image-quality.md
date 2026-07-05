## F3 场景图像质量审计

**审计日期**: 2026-07-05  
**审计范围**: S4b(关键帧预构建) → S5(帧生成) 全链路  
**审计员**: Nova (subagent)

### 评估结论: 有条件通过

帧生成管线架构合理，qwen-image-edit 工作流对齐官方 Vantage 架构，fit+pad 分辨率方案正确解决了参考图畸变问题，prompt 槽位系统完整覆盖画风/角色/场景/连续性/渲染质量。但多角色权重分配存在盲区、尾帧一致性保障薄弱、质检为后置非阻塞，存在 comic 画面质量下降的实质风险。

---

### 关键发现

| 严重度 | 模块 | 问题 | 对 comic 画面质量的影响 | 建议 |
|--------|------|------|------------------------|------|
| 🔴 高 | s5_frame_generate (多角色 ref 注入) | 多角色 shot 的 image1/image2/image3 权重完全等权——主角四视角网格和配角单视图注入同一个 `TextEncodeQwenImageEditPlus`，模型无法区分主次 | 多角色同帧时配角可能"抢"画面焦点，主角面部/服装细节被稀释，导致角色辨识度下降——这是 comic 最致命的问题之一 | 引入权重参数或排序提示：主角四视角 grid 作为 image1（主参考），配角单视图作为 image2 辅助参考，在 prompt 中用"主要角色"/"次要角色"显式标注优先级 |
| 🔴 高 | s5_frame_generate (尾帧一致性) | 尾帧的 VAEEncode 输入是首帧本身（1280×720），角色参考图仅通过 TextEncode 间接注入，不参与 VAEEncode | 尾帧角色面部/服装可能偏离首帧和参考图，因为 qwen-image-edit 的 latent space 主要由 VAEEncode 输入决定。首帧→尾帧的服装/面部漂移是 comic 角色不一致的主因 | 尾帧生成时，VAEEncode 应注入首帧 + 角色参考的混合 latent（如将角色参考图 fit+pad 后与首帧按比例混合），或在 KSampler 中降低 denoise 以保留更多首帧信息 |
| 🟡 中 | s5_frame_generate (黑帧检测阈值) | 黑帧检测仅用 `black_pct > 50` 且 `avg < 10`，覆盖了极端黑帧但无法检测"大面积偏色""低对比度灰雾""角色缺失"等质量退化 | 半黑/灰雾帧会直接进入 S6 视频生成，导致整段 comic 画面发灰/无细节，观感大幅下降 | 增加 VL 质检为**前置阻塞门控**（而非仅后置报告）：每帧生成后立即调用 VL 评分，低于阈值自动重试（当前 max_retries=2 不含 VL 判断） |
| 🟡 中 | s5_frame_generate (首帧→尾帧过渡) | 首帧和尾帧独立生成（仅共享 prompt 中的场景描述和角色描述），无 latent-level 连续性约束 | 首尾帧可能产生"跳切"——位置/姿势/表情突变，S6 FLF2V 插帧时无法平滑过渡，导致 comic 动作不自然 | 考虑尾帧从首帧 latent 出发、降低 denoise（如 0.7-0.85）而非完全从参考图 latent 重新生成；或使用 img2img 模式以首帧为 init |
| 🟡 中 | s5_frame_generate (multi-ref fallback) | 当 image2/image3 未提供时，用 image1 副本填充：`injections["42"] = {"image": ref_image}` | 模型收到两张相同参考图，可能误判为"同一角色的两个视角"而非"两个不同角色"，导致生成画面中角色特征混淆 | 无配角参考图时不应使用 multi-ref 模板，应回退到单角色模板；或多角色 shot 缺少某角色参考图时发出显式警告 |
| 🟡 中 | continuity_check / video_quality_check | 质检为后置非阻塞——检查结果仅打印/写入报告，不触发自动重生成。`sm.add_error()` 仅记录不干预流程 | 低质量帧直接流入 S6，最终 comic 中出现连续性断裂或画面质量不达标的镜头 | 将质检设为阻塞门控：`needs_regeneration=True` 的帧自动触发重生成（换 seed），最多重试 N 次后升级为人工审核 |
| 🟢 低 | s4b_keyframe_assets (prompt 重复构建) | S4b 和 S5 包含完全相同的 `_build_scene_description`、`_build_character_descriptions`、`_build_composition_suffix` 三个函数 | 代码重复导致维护风险：若某处修改了 prompt 构建逻辑而另一处未同步，首帧 prompt 可能不一致——但 S5 优先使用 S4b 预构建 prompt，实际影响有限 | 将这三个函数提取到 `core/prompt_utils.py` 共享模块 |
| 🟢 低 | s5_frame_generate (T2I Path B) | 无角色参考图时回退到 Flux Dev T2I（20 steps），但 T2I 和 qedit 生成的画风差异大 | 同一 comic 中可能出现画风跳变：有角色帧=qedit 风格，无角色帧=Flux Dev 风格，视觉不统一 | 无角色帧也使用 qedit 工作流（以场景参考图作为 VAEEncode 输入），或至少统一 prompt 中的画风指令 |
| 🟢 低 | workflow templates (negative prompt) | 节点 69（negative TextEncode）使用空 prompt `""` 且复用了与 positive 相同的参考图（image1/2/3） | 空 negative prompt + 参考图注入可能无实际效果但浪费计算；理论上负面条件应不加参考图 | 负面 TextEncode 节点不注入参考图（移除 image1/2/3 输入），或改为通用的"低质量"负面 prompt |
| 🟢 低 | s5_frame_generate (seed 管理) | 首帧重试时 seed 会在 `generate_frame` 内随机生成（`s = seed if seed is not None else random.randint(...)`），但尾帧使用首帧相同的 seed 逻辑 | 无可复现性——相同参数两次运行产出不同帧，调试困难。但对最终画面质量无直接影响 | 增加 `--seed` 全局参数支持确定性重跑 |

---

### 质量门控评估

#### ✅ 已有门控

1. **黑帧检测** — `black_pct > 50` 自动重试（覆盖极端失败）
2. **分辨率对齐** — fit+pad 方案：S3 参考图(1024×1536) → 等比缩放到 720 高 → 白边填充到 1280×720 → VAEEncode，无畸变
3. **Vantage 官方架构** — UNETLoader → Lightning 4-step LoRA → ModelSamplingAuraFlow(shift=3.1) → CFGNorm → euler/simple，与官方一致
4. **服饰一致性约束** — `costumeOverrides` + `_build_costume_consistency()` 硬约束文本注入 prompt
5. **S4b 预构建 prompt** — 优先使用 S4b 生成的高质量 prompt，而非 S5 即时构建
6. **分镜时长校验** — S4b 中自动截断超过 6s 的 shot，避免帧间过渡压力
7. **VL 连续性检查** — 4 维评分（character_appearance / scene_environment / lighting_color / composition）
8. **VL 帧质量检查** — 5 维评分（composition / clarity / character_fidelity / lighting / overall）
9. **首帧存在性检查** — 尾帧生成前验证首帧文件存在
10. **ComfyUI 重试机制** — `max_retries=2`，3 次尝试

#### ❌ 缺失门控

1. **VL 前置阻塞门控** — 质检结果不阻塞流程，低质量帧直接流入下游
2. **多角色权重分配** — image1/2/3 等权注入，无主次区分机制
3. **首尾帧 latent 连续性** — 尾帧独立生成，不从首帧 latent 派生
4. **画风一致性门控** — T2I Path B 与 qedit 画风差异无检测/修正
5. **配角参考图缺失告警** — multi-ref 模板用主角参考图填充空位，静默降级
6. **偏色/灰雾检测** — 仅检测纯黑帧，不检测低对比度/偏色/角色缺失
7. **分辨率验证** — 生成后未验证输出是否确实为 1280×720（依赖 ComfyUI 正确执行）
8. **重复帧检测** — 同 shot 首尾帧视觉相似度过高时无告警（动作无变化）

---

### 架构评估

| 维度 | 评价 | 说明 |
|------|------|------|
| 工作流模板 | ✅ 优秀 | qwen-image-edit + Lightning 4-step LoRA + fit+pad 分辨率链，与 Vantage 官方架构对齐 |
| Prompt 系统 | ✅ 优秀 | 槽位系统完整，覆盖画风/场景/角色/服饰/连续性/渲染质量，可编辑可覆盖 |
| 参考图管理 | ✅ 良好 | 服饰感知、多视角优先级、四视图网格支持、新旧目录兼容 |
| 多角色处理 | ⚠️ 薄弱 | 等权注入 + 静默 fallback，无权重机制无主次区分 |
| 首尾帧一致性 | ⚠️ 薄弱 | 尾帧从首帧 VAEEncode 重新生成（denoise=1.0），latent 空间无连续性保障 |
| VL 质检 | ⚠️ 薄弱 | 架构合理（4维连续性 + 5维质量），但非阻塞、非前置 |
| 容错/重试 | ✅ 良好 | 黑帧检测 + 3次重试 + T2I fallback，但缺乏 VL 驱动的质量重试 |

---

### 改进优先级建议

1. **P0 (必须)**: 将 VL 质检改为前置阻塞门控——帧生成后立即评分，低于阈值自动重试
2. **P0 (必须)**: 多角色 shot 引入主次区分——prompt 中显式标注"主要角色"/"次要角色"，或调整 image 注入顺序
3. **P1 (重要)**: 尾帧降低 denoise（0.7-0.85）从首帧 latent 派生，增强首尾帧一致性
4. **P1 (重要)**: multi-ref fallback 策略——缺配角参考图时回退单角色模板而非用主角参考图填充
5. **P2 (改进)**: 增加偏色/灰雾/低对比度检测，扩大黑帧检测的覆盖面
6. **P2 (改进)**: 统一 Path B (T2I) 的画风输出，避免 comic 内画风跳变
