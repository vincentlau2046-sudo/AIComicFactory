"""
prompts/defaults/import_character_extract.py — 导入文本角色提取 Prompt

从 AICB registry.ts importCharacterExtractDef 原样移植。
简化版 character_extract，用于从文本直接提取角色信息。
"""

PROMPT_KEY = "import_character_extract"
CATEGORY = "character"

SLOTS = {
    "role_definition": {
        "key": "role_definition",
        "editable": True,
        "defaultContent": """你是一位角色分析师。从提供的文本中提取所有出场角色。

提取原则：
- 只提取有台词或被明确描述的角色
- 描述基于文本事实，不脑补
- visualHint: 2-4字视觉速记（如"白发剑客""红衣少女"）
- scope: major（主要）/ minor（次要）/ background（背景）""",
    },

    "output_format": {
        "key": "output_format",
        "editable": True,
        "defaultContent": """=== 输出格式 ===
JSON 格式：
{
  "characters": [
    {
      "name": "角色名",
      "scope": "major|minor|background",
      "description": "基于文本的外貌描述",
      "visualHint": "2-4字速记",
      "personality": "性格关键词"
    }
  ]
}""",
    },
}


def build_full_prompt(slot_contents: dict = None, text: str = "") -> str:
    sc = slot_contents or {}
    def resolve(key): return sc.get(key) or SLOTS[key]["defaultContent"]
    return "\n\n".join([resolve("role_definition"), f"=== 原文 ===\n{text}", resolve("output_format")])
