# PR 2: Frame Reference Character Matching & Prompt Pipeline

## 问题

首尾帧生成时，角色参考图无法正确匹配到分镜中的角色，导致 T2I 代替 Edit-plus 工作流，角色脸部一致性无图像参考保证。

## 根因分析

1. **per-EP 实例行名称匹配错位**：
   - 分镜 `shot_assets.characters` 存的是 stripCharHint 后的名字如 "朱元璋"
   - 但实例行 `c.name = "朱元璋（皮包骨头放牛娃）"`
   - `charMap` 用 `c.name` 做 key → "朱元璋" 永远匹配不到
   - 导致 `filteredChars = []` → `refImages = []` → 降级 T2I

2. **4 处 handler 重复匹配逻辑**：
   - handleBatchFrameGenerate (line 1806)
   - handleSingleFrameGenerate (line 1928)
   - handleSingleVideoGenerate (line 2531)
   - handleBatchVideoGenerate (line 2811)
   - 均使用 `shotCharNameSet.has(c.name)` 模式

3. **导入流程缺少角色名匹配**：
   - `import/generate` 存储时未设 `baseName`

## 已实施的修复（v0.2.3）

- 05b27d0: 4 处 handler 改用 `stripCharHint(c.name)` 或 `baseName` 匹配
- 00a974e: frame-generate.ts charMap 双 key（name + baseName）
- ed25b7e: shot_split 阶段自动创建缺失 guest 角色（LLM 生成描述）
- 6bae96b: guest 角色三层过滤（黑名单 + hint 外观词 + ≥2 shot）
- 修复 `import/generate` 存储 baseName

## 待优化

- [ ] 解除 charMap 匹配对 `c.name` 的完全依赖，统一使用 `baseName` 作为身份锚点
- [ ] 清理剩余的 `stripCharHint` 调用，逐步迁移到 baseName 匹配
- [ ] guest 角色 LLM 生成的时机优化（考虑改为异步，避免阻塞 shot_split）
- [ ] guest 角色的 referenceImage 继承（实例行默认没有图）
- [ ] frame-generate.ts 与 route.ts 的匹配逻辑去重（两套代码做同一件事）