"""
prompts/defaults/frame_generate_last.py — 尾帧生成 Prompt

从 AICB registry.ts frameGenerateLastDef 原样移植。
Slot: style_matching / relationship_to_first / next_shot_readiness / rendering_quality
"""

PROMPT_KEY = "frame_generate_last"
CATEGORY = "frame"

SLOTS = {
    "style_matching": {
        "key": "style_matching",
        "editable": True,
        "defaultContent": """=== 关键：画风匹配（最高优先级）===
你必须精确匹配首帧图像（已附带）的画风。
如果首帧是动漫/漫画风格 → 此帧也必须是动漫/漫画风格。
如果首帧是写实风格 → 此帧也必须是写实风格。
不要改变或混合画风。这是不可协商的。""",
    },

    "relationship_to_first": {
        "key": "relationship_to_first",
        "editable": True,
        "defaultContent": """=== 与首帧的关系 ===
此尾帧展示镜头动作的结束状态。与首帧相比：
- 相同的环境、布光方案和色彩基调
- 画风绝对相同——不可有任何变化
- 服装完全一致——角色穿着与设定图和首帧中完全相同的服装。不可换装。
- 面孔、发型、配饰相同——只有姿态/表情/位置发生变化
- 角色的位置、姿态和表情已按帧描述中的说明发生变化""",
    },

    "next_shot_readiness": {
        "key": "next_shot_readiness",
        "editable": True,
        "defaultContent": """=== 作为下一个镜头的起始点 ===
此帧将被复用为下一个镜头的首帧。确保：
- 姿态是稳定的——不处于运动中间，不模糊
- 构图完整，可作为独立画面成立
- 取景允许自然过渡到不同的镜头角度""",
    },

    "rendering_quality": {
        "key": "rendering_quality",
        "editable": True,
        "defaultContent": """=== 渲染 ===
材质：匹配首帧风格的丰富细节
光线：与首帧相同的布光方案。仅在动作驱动的情况下变化。
背景：必须匹配首帧的环境。
角色：精确匹配参考图。展示镜头动作结束时的情感状态。
构图：镜头的自然收束，为下一个剪辑做好准备。""",
    },
}


def build_full_prompt(
    slot_contents: dict = None,
    scene_description: str = "",
    end_frame_desc: str = "",
    character_descriptions: str = "",
) -> str:
    """Build full prompt for last frame generation."""
    sc = slot_contents or {}

    def resolve(key: str) -> str:
        override = sc.get(key)
        if override is not None:
            return override
        return SLOTS[key]["defaultContent"]

    lines = ["生成此镜头的尾帧，作为一张高质量图像。", ""]
    lines.append(resolve("style_matching"))
    lines.append("")
    lines.append("=== 场景环境 ===")
    lines.append(scene_description)
    lines.append("")
    lines.append("=== 帧描述 ===")
    lines.append(end_frame_desc)
    lines.append("")
    lines.append("=== 角色描述 ===")
    lines.append(character_descriptions)
    lines.append("")
    lines.append("=== 参考图 ===")
    lines.append("第一张附带图像是此镜头的首帧——以它为视觉锚点。")
    lines.append("其余附带图像是角色设定图（每张4个视角，名字印在底部）。")
    lines.append("将每张设定图的角色名与场景中的角色对应。")
    lines.append("")
    lines.append(resolve("relationship_to_first"))
    lines.append("")
    lines.append(resolve("next_shot_readiness"))
    lines.append("")
    lines.append(resolve("rendering_quality"))
    return "\n".join(lines)
