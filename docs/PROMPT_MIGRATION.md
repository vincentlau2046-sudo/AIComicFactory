# Prompt 移植清单

**创建日期**: 2026-06-28
**源码**: ~/AIComicBuilder/src/lib/ai/prompts/registry.ts

---

## 移植策略（更新 - 2026-06-28 D3 决策后）

**主模型 = baidu-codingplan (GPT-4 级)**，不需要精简 prompt。
原样移植 AICB 的 12 个 prompt defaultContent。

仅备选本地模型（Qwen3.6-27B）时考虑精简，但作为降级方案不优先优化。

### 移植原则

1. **原样复制**：AICB 的 prompt defaultContent 直接复制到 Python dict
2. **slot 结构保留**：key/nameKey/descriptionKey/defaultContent/editable/buildFullPrompt 全部保留
3. **中文保持**：原 prompt 中英混合不用改
4. **不需要精简**：GPT-4 级模型完全能驾驭完整 prompt
5. **不需要 guided_json**：纯 prompt 约束即可稳定输出 JSON

---

## P1 Prompt（Phase 1 必须移植）

### 1. script_parse
- **源文件**: `registry.ts` 中 `scriptParseDef`
- **核心 Slot**: role_definition / original_fidelity / output_format / parsing_rules / language_rules
- **移植工作量**: 直接复制，0 精简
- **预估 token**: ~3000

### 2. character_extract
- **源文件**: `registry.ts` 中 `characterExtractDef`
- **核心 Slot**: role_definition / style_detection / output_format / scope_rules / description_requirements / writing_rules / language_rules
- **移植工作量**: 直接复制，0 精简
- **预估 token**: ~4000

### 3. shot_split
- **源文件**: `registry.ts` shot_split prompt 定义
- **核心约束**: 物理常识 / 字幕安全区 / 变化幅度比例 / motionScript 3秒分段 / videoScript Seedance散文 / 构图指南 / 转场指南
- **移植工作量**: 直接复制，0 精简
- **预估 token**: ~5000

### 4. frame_generate (first + last)
- **源文件**: `src/lib/ai/prompts/keyframe-prompts.ts` 或 `registry.ts` keyframePromptsDef
- **移植工作量**: 直接复制，0 精简
- **预估 token**: ~800

---

## P2 Prompt（Phase 2+ 按需移植）

### 5. script_generate
- 从 idea 生成剧本（当没有现成剧本时使用）
- 低优先级，可后续添加

### 6. script_split
- 分集拆分（长篇内容时使用）
- 低优先级

### 7. import_character_extract
- 导入文本角色提取（简化版 character_extract）
- 可作为 character_extract 的降级版

### 8. video_prompts
- 视频生成 prompt 构建器
- 当前 AICF 只用 keyframe 模式，prompt 在 shot_split 中已生成 videoScript

### 9. ref_image_prompts / ref_video_prompts
- Reference 模式专用
- 当前 AICF 不使用 Reference 模式

### 10. character_image (四视图 prompt)
- AICF 用单参考图替代四视图
- 不移植原四视图 prompt，需新写 T2I 参考图 prompt

---

## guided_json Schema（仅备选本地模型模式时启用）

### script_parse schema
```json
{
  "type": "object",
  "properties": {
    "title": {"type": "string"},
    "synopsis": {"type": "string"},
    "visualStyle": {
      "type": "object",
      "properties": {
        "artStyle": {"type": "string"},
        "colorPalette": {"type": "string"},
        "eraAesthetics": {"type": "string"},
        "mood": {"type": "string"},
        "aspectRatio": {"enum": ["16:9 横屏", "9:16 竖屏", "2.35:1 宽银幕", "1:1 方形"]},
        "referenceDirector": {"type": "string"}
      },
      "required": ["artStyle", "colorPalette", "aspectRatio"]
    },
    "scenes": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "sceneNumber": {"type": "integer"},
          "setting": {"type": "string"},
          "description": {"type": "string"},
          "mood": {"type": "string"},
          "dialogues": {
            "type": "array",
            "items": {
              "type": "object",
              "properties": {
                "character": {"type": "string"},
                "text": {"type": "string"},
                "emotion": {"type": "string"}
              },
              "required": ["character", "text"]
            }
          }
        },
        "required": ["sceneNumber", "setting", "description"]
      }
    }
  },
  "required": ["title", "scenes"]
}
```

### character_extract schema
```json
{
  "type": "object",
  "properties": {
    "characters": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "name": {"type": "string"},
          "scope": {"enum": ["main", "guest"]},
          "description": {"type": "string"},
          "visualHint": {"type": "string"},
          "personality": {"type": "string"},
          "heightCm": {"type": "integer"},
          "bodyType": {"enum": ["slim", "average", "athletic", "heavy", "petite", "tall"]},
          "performanceStyle": {"type": "string"}
        },
        "required": ["name", "scope", "description", "visualHint"]
      }
    },
    "relationships": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "characterA": {"type": "string"},
          "characterB": {"type": "string"},
          "relationType": {"enum": ["ally", "enemy", "lover", "family", "mentor", "rival", "stranger", "neutral"]},
          "description": {"type": "string"}
        },
        "required": ["characterA", "characterB", "relationType"]
      }
    }
  },
  "required": ["characters"]
}
```

### shot_split schema — 待定义（结构复杂，嵌套 scene→shots）
