"""
prompts/defaults/script_generate.py — 剧本生成 Prompt

从 AICB registry.ts scriptGenerateDef 原样移植。
从 idea/outline 生成完整剧本。低优先级——通常已有现成剧本。
Slot: role_definition / output_format / writing_rules
"""

PROMPT_KEY = "script_generate"
CATEGORY = "script"

SLOTS = {
    "role_definition": {
        "key": "role_definition",
        "editable": True,
        "defaultContent": """你是一位专业编剧。根据提供的故事创意/大纲，撰写完整的分场剧本。

核心原则：
- 对白必须自然、有个性、推动剧情
- 场景描述必须具体、有画面感
- 每场戏必须有冲突或转折
- 节奏紧凑，无废话场景""",
    },

    "output_format": {
        "key": "output_format",
        "editable": True,
        "defaultContent": """=== 输出格式 ===
JSON 格式：
{
  "title": "剧名",
  "synopsis": "一句话梗概",
  "scenes": [
    {
      "sceneNumber": 1,
      "location": "场景地点",
      "timeOfDay": "时间",
      "description": "场景描述",
      "dialogues": [
        {"character": "角色名", "line": "台词"}
      ]
    }
  ]
}""",
    },

    "writing_rules": {
        "key": "writing_rules",
        "editable": True,
        "defaultContent": """=== 写作规则 ===
- 对白用角色原声，不用旁白代述
- 场景描述用现在时，有画面感
- 每个场景有明确的叙事目的
- 情感通过行动和对白展现，不靠叙述
- 长度: 每集 8-15 场，适合 3-5 分钟动画""",
    },
}


def build_full_prompt(slot_contents: dict = None, idea: str = "") -> str:
    sc = slot_contents or {}
    def resolve(key): return sc.get(key) or SLOTS[key]["defaultContent"]
    return "\n\n".join([resolve("role_definition"), f"=== 故事创意 ===\n{idea}", resolve("output_format"), resolve("writing_rules")])
