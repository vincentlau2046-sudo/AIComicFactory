# PR: Pipeline 模型缓存 keep-alive

**状态:** 待处理
**创建:** 2026-08-09
**相关版本:** v0.1.2

## 问题

character-image 管线 4 步（gen_front + 3 angle）每次调用 ComfyUI API 都重载模型，即使 angle 三步使用完全相同的 workflow（qwen-2511-edit-multiangle）和相同的模型（qwen_image_2511）。

## 原因

- `classifyModelFamily()` 的前缀匹配 `qwen_2512`/`qwen_2511` 不命中实际 `gpu_model` 值（`qwen_image_2512`/`qwen_image_2511`），导致两步都归类为 `'unknown'`
- 但即使分类正确（同为 `'qwen-image'` 族），GPU Scheduler 的 `freeMemory()` 只控制跨族卸载，不控制同族缓存
- ComfyUI 每次 API 调用默认重载模型，无 keep-alive 机制

## 影响

- 单条角色图生成多出 2 次不必要的模型加载（~5GB 模型 x 2 ≈ 10GB 无谓 IO）
- frame-generate 管线类似（gen_first_frame + gen_last_frame 可能共享模型）

## 可能的修复方向

1. **IFF 侧 keep-alive**：ComfyUI API 调用间保持模型驻留
2. **ComfyUI native caching**：Workflow JSON 共享模型加载
3. **同族步骤合并**：Pipeline 引擎内对相同 workflow_id 的连续步骤做一次模型加载
