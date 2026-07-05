## F1 叙事质量审计

**审计日期**: 2026-07-05
**审计范围**: S1(剧本解析) → S2(角色提取) → S4(分镜拆分) 叙事链路
**审计文件**: `core/llm_client.py`, `core/prompt_runner.py`, `prompts/registry.py`, `prompts/_base.py`, `prompts/defaults/{script_parse,character_extract,shot_split,script_generate,script_split}.py`, ~~`scripts/gen_prompts.py`~~, ~~`scripts/gen_s4_shots.py`~~ *(已删除)*

### 评估结论: ⚠️ 有条件通过

叙事链路的核心 prompt 质量极高（AICB 移植的 prompt 在保真度、角色一致性、物理约束方面设计完善），但存在若干数据流断裂、schema 不对齐和缺失门控问题，需修复后方可稳定产出。

---

### 关键发现

| 严重度 | 模块 | 问题 | 对 comic 质量的影响 | 建议 |
|--------|------|------|-------------------|------|
| 🔴 高 | `core/prompt_runner.py` — `_script_to_text()` | S2 调用时将 s1_parsed.json 转回文本，**丢弃 dialogue.emotion 字段**。S2 收到的文本只有 `角色名: "台词"` 格式，丢失了 S1 精心保留的表演提示 | 角色提取阶段无法感知原文中的情感语境，角色 performanceStyle 推断缺少关键输入；下游分镜的 motionScript 情绪描写降级 | 改为传递原始 s1 JSON（或至少保留 emotion），让 S2 prompt 直接消费结构化数据 |
| 🔴 高 | ~~`scripts/gen_prompts.py`~~ *(已删除)* | visualAnchors key 名与 S2 输出不对齐：gen_prompts 用 `face_shape/hair_eyes/build_posture/clothing/distinctive`，而 S2 输出的是 `face/hair/body/clothing/signature` | S3/S5 的角色一致性 prompt 拿不到任何锚点数据，角色参考图和帧生成的一致性完全依赖 description 全文——visualAnchors 等于白提取 | 统一 key 名为 `face/hair/body/clothing/signature`（与 S2 输出一致） |
| 🔴 高 | ~~`scripts/gen_s4_shots.py`~~ *(已删除)* | 手工分镜脚本产出 schema（shotId/durationSec/description/isFirstFrame/isLastFrame/emotion）与 S4 prompt 要求的 schema（prompt/startFrameDesc/endFrameDesc/motionScript/videoScript/cameraDirection/compositionGuide/transitionIn/Out 等）**完全不兼容** | 手工分镜无法被下游 S5/S6 消费；两种 schema 共存导致管线分裂，且手工版缺少 motionScript/startFrameDesc 等视频生成必需字段 | 废弃手工脚本，全部走 prompt 驱动的 LLM 分镜；或写 schema 迁移适配层 |
| 🟡 中 | `prompts/defaults/script_parse.py` — FORMAT slot | JSON 示例缺少闭合 `}`（第 18 行 `]` 后无 `}`），导致 LLM 可能输出不完整 JSON | S1 产出解析失败，触发 chat_json 重试（浪费 token），或产出截断的结构化数据 | 补上闭合 `}` |
| 🟡 中 | `prompts/registry.py` | 与 `prompts/_base.py` 存在**完全重复**的 `PromptSlot`/`PromptDefinition`/`slot()`/`resolve()` 定义。registry.py 还内嵌了一套未使用的 SCRIPT_PARSE_* 常量（5-slot 版本），与 defaults/ 的 6-slot 版本不同步 | 维护风险：修改一处忘记另一处。若有人误用 registry 内嵌常量会拿到缺少 `parsing_rules` slot 的过时 prompt | 删除 registry.py 中的重复类定义和内嵌常量，统一从 `_base.py` 导入 |
| 🟡 中 | 全链路 | **零 schema 验证**：S1/S2/S4 输出的 JSON 无任何字段校验。损坏/缺失的中间数据直接传递给下游 | S4 消费损坏的 s1_parsed.json 时，可能静默产出不完整的分镜（缺场景、缺角色），直到 S5/S6 生成时才暴露，返工成本高 | 增加 JSON schema 验证门控：S1 至少校验 scenes/dialues 存在；S2 校验 characters[].name/description/visualHint 存在；S4 校验 shots[].prompt/motionScript/startFrameDesc 存在 |
| 🟡 中 | `core/llm_client.py` — `chat_json()` | API 超时（timeout=300s）仅重试 1 次后直接 raise；JSON 解析失败的重试会**累积拼接错误提示到 user prompt 末尾**，3 次重试后 user prompt 膨胀 | 超时场景下管线直接中断无降级；JSON 重试时 prompt 膨胀可能导致 LLM 输出更混乱而非更好 | 超时重试增加等待间隔；JSON 重试用新的 messages 列表而非拼接原 prompt |
| 🟡 中 | `prompts/defaults/shot_split.py` | costumeOverride 规则写在 OUTPUT_FORMAT slot（editable=False）里，但没有独立的 costume_override slot，且 S2 不输出 costumes 数组 | 换装逻辑在 prompt 里描述了但 S2 不提供数据支持，costumeOverrides 在分镜中永远是空或错误 | S2 增加 wardrobe_extract 后（已有 `scripts/wardrobe_extract.py`），确保 costume_id 能在 S4 中被引用 |
| 🟢 低 | `core/prompt_runner.py` | model 硬编码为 `"DEEPSEEK_PRO"`，但 `e2e_dry_run.py` 通过 `stage_def.get("model", "DEEPSEEK_PRO")` 覆盖，两处默认值需保持同步 | 如果 pipeline.yaml 没指定 model，两处默认可能不一致 | prompt_runner 的 model 默认值改为从配置读取，或直接移除（让调用方决定） |
| 🟢 低 | `prompts/defaults/script_generate.py` | 输出 schema 与 script_parse 的 schema 不对齐（dialogues 用 `line` 而非 `text`，无 `emotion` 字段） | 如果用户走 script_generate → script_parse 流程，中间需要适配；但此为 P2 可选阶段 | 在 script_generate 中统一为 `text` + `emotion` 字段 |
| 🟢 低 | `prompts/defaults/shot_split.py` — CONSISTENCY slot | 要求注入 visualHint，但 user prompt 中只传了 `visualHint + description[:100]`，character 的完整信息被截断 | LLM 在分镜时可能无法充分理解角色特征来编排站位和动作 | 在 user prompt 的角色摘要中增加 visualAnchors 关键词（face + signature 即可） |
| 🟢 低 | ~~`scripts/gen_prompts.py`~~ *(已删除)* | 硬编码项目路径 `projects/last_bento`，且只处理 3 个 scene 的 location hint | 无法复用于其他项目 | 改为接受命令行参数，或从 s4_shots.json 的 setting 字段自动提取 |

---

### 质量门控评估

#### ✅ 已有门控
1. **S1 叙事保真度门控**：script_parse prompt 包含极详尽的保真度约束（逐字对白、自检清单、反例），是整个管线最扎实的设计
2. **S2 角色身份层保护**：character_extract prompt 的"身份层/风格层分离"机制，有效防止角色描述被泛化为通用模板
3. **S4 物理常识硬约束**：shot_split prompt 明确禁止比喻动词、反物理行为，强制具体姿态描述
4. **S4 变化幅度比例**：按时长分级的变化幅度规则，避免短镜头出现不可能的大幅度运动
5. **S4 角色一致性注入**：visualHint 机制 + performanceStyle 注入 + 关系约束，三维保障角色跨镜头一致
6. **LLM JSON 重试**：chat_json 自带 3 次重试 + markdown 代码块剥离 + regex 提取
7. **VL 质检（S3/S3b）**：e2e_dry_run.py 已集成 qw35-9b VL 质检

#### ❌ 缺失门控
1. **S1→S2 数据契约验证**：无校验 s1_parsed.json 是否包含必需字段（scenes/dialogues），损坏数据静默传入 S2
2. **S2→S4 数据契约验证**：无校验 s2_characters.json 的 characters[].name/visualHint/visualAnchors 是否完整
3. **S4 输出完整性校验**：无校验 s4_shots.json 每个 shot 是否包含 prompt/motionScript/startFrameDesc/endFrameDesc（这些是 S5/S6 的硬依赖）
4. **S1↔S2 角色名一致性校验**：S1 对白中的角色名与 S2 提取的角色名无交叉验证，可能出现 S1 用"老周"但 S2 提取为"周大明"的不一致
5. **对白逐字保真自动验证**：S1 prompt 要求对白逐字不变，但无程序化校验——依赖 LLM 自觉遵守
6. **S4 duration 硬约束执行**：prompt 要求 duration ≤ max_duration，但无程序化截断——若 LLM 输出超时值，FLF2V 直接失败
7. **S2→S3 visualAnchors 消费链验证**：S2 输出的锚点 key 与 ~~gen_prompts.py~~ *(已删除)* 的消费 key 不一致，无门控拦截
8. **YAML Override 加载**：registry.py 声明了 `overrides/ YAML → registry default` 解析链，但 YAML 加载逻辑未实现，override 机制形同虚设
9. **LLM 降级策略**：API 不可用时无 fallback（如切本地 vLLM），管线直接中断

---

### 叙事保真度专项评估

**S1 剧本解析** — 评分: **9/10**

prompt 设计极优秀：保真度最高优先级、自检清单、反例演示、场景拆分"宁多勿少"。唯一扣分点：FORMAT slot 中 JSON 示例未闭合，可能误导 LLM。

**S2 角色提取** — 评分: **8/10**

身份层/风格层分离是亮点，visualAnchors 为下游一致性提供锚点。扣分点：(1) `_script_to_text()` 丢弃 emotion 字段，S2 无法感知 S1 的表演提示；(2) costumes 数组未在 prompt 输出中定义（由 wardrobe_extract 后处理），但 S4 的 costumeOverrides 已经引用 costume_id——数据流断裂。

**S4 分镜拆分** — 评分: **8/10**

物理约束、构图指南、转场规则、motionScript 四层交织——设计完善。扣分点：(1) 缺少程序化校验，prompt 约束依赖 LLM 自觉；(2) 手工脚本 ~~gen_s4_shots.py~~ *(已删除)* 产出完全不同 schema 的数据，造成管线混乱。

**端到端保真度** — 评分: **6/10**

S1 的精心保真在 S2→S4 传递过程中被削弱：emotion 丢失、角色名无交叉验证、visualAnchors key 不对齐。管线最薄弱的环节不是 prompt 质量，而是**数据流的工程严谨性**。

---

### 修复优先级建议

1. **P0 (阻断级)**：修复 `_script_to_text()` 保留 emotion，统一 visualAnchors key 名
2. **P1 (关键)**：增加 S1/S2/S4 输出的 JSON schema 验证门控
3. **P1 (关键)**：修复 FORMAT slot JSON 示例闭合问题
4. **P2 (重要)**：清理 registry.py 死代码，~~废弃 gen_s4_shots.py 或写适配层~~ *(脚本已删除)*
5. **P2 (重要)**：实现 LLM 降级策略（API 超时→本地 vLLM）
6. **P3 (改进)**：实现 YAML override 加载，增加角色名交叉验证
