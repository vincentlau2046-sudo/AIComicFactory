"""
prompts/defaults/frame_generate_first.py — 首帧生成 Prompt (AICB Full)

完整移植 AICB buildFirstFramePrompt from src/lib/ai/prompts/frame-generate.ts
Slot: style_matching / scene_environment / frame_description / character_descriptions /
      reference_rules / continuity_rules / rendering_quality
"""

PROMPT_KEY = "frame_generate_first"
CATEGORY = "frame"

SLOTS = {
    "style_matching": {
        "key": "style_matching",
        "editable": True,
        "defaultContent": """=== 关键：画风（最高优先级）===
阅读下方的角色描述和场景描述，它们指定或暗示了一种画风。
你必须完全匹配该画风。不得默认使用写实风格。
- 如果描述中提到 动漫/漫画/anime/manga/卡通/cartoon → 生成动漫/漫画风格插画
- 如果描述中提到 写实/真人/photorealistic → 生成写实风格图像
- 如果附有参考图，其视觉风格即为标准——必须精确匹配
- 输出的画风必须与角色参考图保持一致""",
    },

    "scene_environment": {
        "key": "scene_environment",
        "editable": False,
        "defaultContent": "",
    },

    "frame_description": {
        "key": "frame_description",
        "editable": False,
        "defaultContent": "",
    },

    "character_descriptions": {
        "key": "character_descriptions",
        "editable": False,
        "defaultContent": "",
    },

    "costume_consistency": {
        "key": "costume_consistency",
        "editable": True,
        "defaultContent": "",
    },

    "reference_rules": {
        "key": "reference_rules",
        "editable": True,
        "defaultContent": """=== 参考图（角色设定图）===
每张附带的参考图是一张角色设定图，展示 4 个视角（正面、四分之三侧面、侧面、背面）。
角色名印在每张设定图底部——用它来识别对应的角色。
强制一致性规则：
- 将设定图中的角色名与场景描述中的角色名匹配
- 服装必须与参考完全一致——相同的衣物类型、颜色、材质、配饰。不得替换（例如：不得将青色常服替换为龙袍）
- 面部、发型、发色、体型、肤色必须精确匹配
- 参考图中展示的所有配饰（帽子、佩刀、发簪、首饰）都必须出现
- 画风必须与参考图精确匹配""",
    },

    "continuity_rules": {
        "key": "continuity_rules",
        "editable": True,
        "defaultContent": """=== 连续性要求 ===
该镜头紧接上一个镜头。附带的参考包含上一个镜头的末帧。保持视觉连续性：
- 相同角色必须穿着一致的服装并保持一致的比例
- 相同画风——不得在动漫和写实之间切换
- 环境光照和色温应平滑过渡
- 角色位置应从上一个镜头结束时的位置自然延续""",
    },

    "rendering_quality": {
        "key": "rendering_quality",
        "editable": True,
        "defaultContent": """=== 渲染 ===
质感：与画风相称的丰富细节
光照：电影级打光，具有合理的光源。使用轮廓光分离角色。
背景：完整渲染、细节丰富的环境。不得使用空白或抽象背景。
角色：外观和画风精确匹配参考图。表情生动，姿势自然动感。
构图：电影式取景，具有清晰的焦点和景深。""",
    },
}


def build_full_prompt(
    slot_contents: dict = None,
    scene_description: str = "",
    start_frame_desc: str = "",
    character_descriptions: str = "",
    previous_last_frame: str = "",
    costume_consistency: str = "",
) -> str:
    """
    Build full first-frame prompt (AICB buildFirstFramePrompt).
    
    Uses slot system for customizable sections.
    """
    sc = slot_contents or {}

    def resolve(key: str) -> str:
        override = sc.get(key)
        if override is not None:
            return override
        return SLOTS[key]["defaultContent"]

    lines = ["生成该镜头的开场帧，作为一张高质量图像。", ""]
    lines.append(resolve("style_matching"))
    lines.append("")
    lines.append("=== 场景环境 ===")
    lines.append(scene_description)
    lines.append("")
    lines.append("=== 画面描述 ===")
    lines.append(start_frame_desc)
    lines.append("")
    lines.append("=== 角色描述 ===")
    lines.append(character_descriptions)
    lines.append("")

    if costume_consistency:
        lines.append(costume_consistency)
        lines.append("")

    lines.append(resolve("reference_rules"))
    lines.append("")

    if previous_last_frame:
        lines.append(resolve("continuity_rules"))
        lines.append("")

    lines.append(resolve("rendering_quality"))
    return "\n".join(lines)