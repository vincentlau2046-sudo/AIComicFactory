"""
prompts/defaults/frame_generate_last.py — 尾帧生成 Prompt (AICB Full)

完整移植 AICB buildLastFramePrompt from src/lib/ai/prompts/frame-generate.ts
Slot: style_matching / frame_description / first_frame_anchor / character_descriptions /
      reference_rules / first_frame_relationship / next_shot_readiness / rendering_quality
"""

PROMPT_KEY = "frame_generate_last"
CATEGORY = "frame"

SLOTS = {
    "style_matching": {
        "key": "style_matching",
        "editable": True,
        "defaultContent": """=== 关键：画风（最高优先级）===
你必须精确匹配首帧图像（已附带）的画风。
如果首帧是动漫/漫画风格 → 此帧也必须是动漫/漫画风格。
如果首帧是写实风格 → 此帧也必须是写实风格。
不得更改或混用画风。这是不可妥协的。""",
    },

    "frame_description": {
        "key": "frame_description",
        "editable": False,
        "defaultContent": "",
    },

    "first_frame_anchor": {
        "key": "first_frame_anchor",
        "editable": True,
        "defaultContent": """=== 参考图 ===
第一张附带图像是该镜头的开场帧——以它作为你的视觉锚点。
其余附带图像是角色设定图（每张 4 个视角，名字印在底部）。
将每张角色设定图的名字与场景中的角色匹配。""",
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
        "defaultContent": """=== 参考图一致性 ===
- 服装必须与参考完全一致——相同的衣物类型、颜色、材质、配饰
- 面部、发型、发色、体型、肤色必须精确匹配参考图
- 所有配饰必须出现""",
    },

    "first_frame_relationship": {
        "key": "first_frame_relationship",
        "editable": True,
        "defaultContent": """=== 与首帧的关系 ===
此结束帧展示镜头动作完成后的终止状态。与首帧相比：
- 相同的环境、光照设置和色彩方案
- 相同画风——绝对不得更改风格
- 服装完全一致——角色穿着与参考设定图和首帧中完全相同的服装。不得更换服装。
- 相同的面部、发型、配饰——仅姿势/表情/位置发生变化
- 角色的位置、姿势和表情已按上方画面描述发生变化""",
    },

    "next_shot_readiness": {
        "key": "next_shot_readiness",
        "editable": True,
        "defaultContent": """=== 作为下一镜头的起始点 ===
此帧将被复用为下一个镜头的开场帧。确保：
- 姿势是稳定的——非运动中间态或模糊的
- 构图是完整的，可作为独立画面成立
- 取景允许自然过渡到不同的机位角度""",
        },
    "rendering_quality": {
        "key": "rendering_quality",
        "editable": True,
        "defaultContent": """=== 渲染 ===
质感：与首帧风格匹配的丰富细节
光照：与首帧相同的光照设置。仅在动作需要时才变化。
背景：必须与首帧的环境一致。
角色：精确匹配参考图。展示镜头动作结束时的情绪状态。
构图：镜头的自然收束，为切换到下一个镜头做好准备。""",
    },
}


def build_full_prompt(
    slot_contents: dict = None,
    scene_description: str = "",
    end_frame_desc: str = "",
    character_descriptions: str = "",
    first_frame_path: str = "",
    costume_consistency: str = "",
) -> str:
    """
    Build full last-frame prompt (AICB buildLastFramePrompt).

    Uses slot system for customizable sections.
    """
    sc = slot_contents or {}

    def resolve(key: str) -> str:
        override = sc.get(key)
        if override is not None:
            return override
        return SLOTS[key]["defaultContent"]

    lines = ["生成该镜头的结束帧，作为一张高质量图像。", ""]
    lines.append(resolve("style_matching"))
    lines.append("")
    lines.append("=== 场景环境 ===")
    lines.append(scene_description)
    lines.append("")
    lines.append("=== 画面描述 ===")
    lines.append(end_frame_desc)
    lines.append("")
    lines.append("=== 角色描述 ===")
    lines.append(character_descriptions)
    lines.append("")

    if costume_consistency:
        lines.append(costume_consistency)
        lines.append("")

    lines.append(resolve("first_frame_anchor"))
    lines.append("")
    lines.append(resolve("first_frame_relationship"))
    lines.append("")
    lines.append(resolve("next_shot_readiness"))
    lines.append("")
    lines.append(resolve("rendering_quality"))
    return "\n".join(lines)