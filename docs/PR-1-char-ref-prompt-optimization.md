# PR 1: Character Reference Image Prompt Optimization

## 问题

角色参考图生成时，图像风格与 character description 声明不一致。具体表现为：
- 描述为"写实真人电影风格"，但生成的图是 stylized/CGI
- 描述为"光头戒疤破僧袍"，但生成锦衣公子
- 模板系统（FACE_DETAIL/STYLE_MATCHING/FRONT_VIEW_LAYOUT）被错误地直接注入 T2I prompt

## 根因分析

1. **buildCharacterTurnaroundPrompt** 硬编码 "Default to stylized illustration, NOT photography" 覆盖了 description 的风格声明
2. **模板系统误用**：FACE_DETAIL/STYLE_MATCHING 等元指令被直接拼入 T2I prompt，而不是作为 LLM prompt 生成指南
3. **character-image.yaml** 管线覆盖 "Flat lighting" 导致 CGI 感
4. **名字污染**：角色名 "朱元璋" 出现在 prompt 中，T2I 模型用自身知识覆盖了 description
5. **FACE_DETAIL** "头发：清晰的发量/颜色/动态感" 与 "光头" 冲突

## 已实施的临时修复（v0.2.3）

- 6ef8feb: 移除 T2I prompt 中的模板注入，仅使用 description + 布局指令
- 5a7c69b: FACE_DETAIL 头发指令改为遵从 description（光头→不画头发）
- 9376e38: 修复两个入口（route.ts + pipeline/character-image.ts）传 character_prompt
- FRONT_VIEW_LAYOUT 模板保留在 registry.ts，用于未来 LLM prompt 生成工作流

## 待优化

- [ ] buildCharacterTurnaroundPrompt 彻底废弃，替换为模板系统构建的 prompt（LLM 生成，非直接 T2I）
- [ ] qwen-image T2I prompt 工程：评估最佳 prompt 长度/结构/权重分配
- [ ] 角色名污染问题：T2I prompt 不应包含知名人物名字
- [ ] "头皮泛青"等中文文化概念在 T2I 中的正确传达
- [ ] 戒疤/比例等精确细节的生成质量提升