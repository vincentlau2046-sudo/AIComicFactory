"""
prompts/defaults/script_split.py — 分集拆分 Prompt

从 AICB registry.ts scriptSplitDef 原样移植。
将长篇剧本拆分为多集。低优先级。
"""

PROMPT_KEY = "script_split"
CATEGORY = "script"

SLOTS = {
    "role_definition": {
        "key": "role_definition",
        "editable": True,
        "defaultContent": """你是一位专业编剧。将提供的长篇剧本拆分为多集短剧。

拆分原则：
- 每集 8-15 场，时长 3-5 分钟
- 每集有完整的叙事弧（开端→发展→高潮/悬念）
- 集间衔接自然，有钩子（hook）引导观众继续观看
- 角色出场连续，不跨集消失再出现""",
    },

    "output_format": {
        "key": "output_format",
        "editable": True,
        "defaultContent": """=== 输出格式 ===
JSON 格式：
{
  "episodes": [
    {
      "episode": 1,
      "title": "集标题",
      "scenes": [场景编号列表],
      "hook": "结尾钩子描述"
    }
  ]
}""",
    },
}


def build_full_prompt(slot_contents: dict = None, script_summary: str = "") -> str:
    sc = slot_contents or {}
    def resolve(key): return sc.get(key) or SLOTS[key]["defaultContent"]
    return "\n\n".join([resolve("role_definition"), f"=== 剧本概要 ===\n{script_summary}", resolve("output_format")])
