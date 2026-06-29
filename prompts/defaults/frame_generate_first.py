"""
prompts/defaults/frame_generate_first.py — 首帧生成 Prompt

从 AICB registry.ts frameGenerateFirstDef 原样移植。
Slot: style_matching / reference_rules / rendering_quality / continuity_rules
"""

PROMPT_KEY = "frame_generate_first"
CATEGORY = "frame"

SLOTS = {
    "style_matching": {
        "key": "style_matching",
        "editable": True,
        "defaultContent": """=== 关键：画风匹配（最高优先级）===
仔细阅读下方的角色描述和场景描述。它们指定或暗示了画风。
你必须精确匹配该画风。不要默认使用写实风格。
- 如果附有参考图，参考图的视觉风格就是真理——精确匹配
- 输出的画风必须与角色设定图一致

=== 画风映射 ===
- 古风/武侠/仙侠 → 动漫/插画风格，中国古风美学
- 现代/都市/校园 → 写实或半写实风格
- 科幻/未来 → 写实+特效风格
- 奇幻/魔幻 → 动漫/概念艺术风格

=== 物理常识 ===
- 严禁比喻动词（"飞起如箭"→"快速跃起"）
- 严禁反物理行为（人不会凭空悬浮）
- 重力、惯性、碰撞遵循现实物理""",
    },

    "reference_rules": {
        "key": "reference_rules",
        "editable": True,
        "defaultContent": """=== 参考图（角色设定图）===
每张附带的参考图是一张角色设定图，展示4个视角（正面、四分之三侧面、侧面、背面）。
角色的名字印在每张设定图底部——用它来识别对应的角色。
强制一致性规则：
- 将设定图中的角色名与场景描述中的角色名对应
- 服装必须与参考图完全一致——相同的衣物类型、颜色、材质、配饰。不要替换（如不要把青色常服换成龙袍）
- 面孔、发型、发色、体型、肤色必须精确匹配
- 参考图中展示的所有配饰（帽子、佩刀、发簪、首饰）必须出现
- 画风必须与参考图精确匹配""",
    },

    "rendering_quality": {
        "key": "rendering_quality",
        "editable": True,
        "defaultContent": """=== 渲染 ===
材质：符合画风的丰富细节
光线：具有动机的电影级布光。使用轮廓光分离角色。
背景：完整渲染的详细环境。不要空白或抽象背景。
角色：精确匹配参考图的外貌和画风。表情生动，姿态自然有动感。
构图：电影级取景，明确的视觉焦点和景深。""",
    },

    "continuity_rules": {
        "key": "continuity_rules",
        "editable": True,
        "defaultContent": """=== 连续性要求 ===
此镜头紧接上一个镜头。附带的参考中包含上一个镜头的尾帧。保持视觉连续性：
- 相同的角色必须穿着一致的服装和比例
- 画风相同——不要在动漫和写实之间切换
- 环境光线和色温应平滑过渡
- 角色位置应从上一个镜头结束时的位置逻辑延续""",
    },
}


def build_full_prompt(
    slot_contents: dict = None,
    scene_description: str = "",
    start_frame_desc: str = "",
    character_descriptions: str = "",
    previous_last_frame: str = "",
) -> str:
    """Build full prompt for first frame generation."""
    sc = slot_contents or {}

    def resolve(key: str) -> str:
        override = sc.get(key)
        if override is not None:
            return override
        return SLOTS[key]["defaultContent"]

    lines = ["生成此镜头的首帧，作为一张高质量图像。", ""]
    lines.append(resolve("style_matching"))
    lines.append("")
    lines.append("=== 场景环境 ===")
    lines.append(scene_description)
    lines.append("")
    lines.append("=== 帧描述 ===")
    lines.append(start_frame_desc)
    lines.append("")
    lines.append("=== 角色描述 ===")
    lines.append(character_descriptions)
    lines.append("")
    lines.append(resolve("reference_rules"))
    lines.append("")

    if previous_last_frame:
        lines.append(resolve("continuity_rules"))
        lines.append("")

    lines.append(resolve("rendering_quality"))
    return "\n".join(lines)
