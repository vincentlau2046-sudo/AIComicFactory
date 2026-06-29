"""
prompts/defaults/video_generate.py — FLF2V 视频生成 Prompt

从 AICB registry.ts videoGenerateDef 原样移植。
Slot: interpolation_header / dialogue_format / frame_anchors
"""

PROMPT_KEY = "video_generate"
CATEGORY = "video"

SLOTS = {
    "interpolation_header": {
        "key": "interpolation_header",
        "editable": True,
        "defaultContent": """=== 首尾帧插值动画 ===
你将收到两张帧图像：首帧和尾帧。
生成从首帧到尾帧的平滑过渡动画。
- 动画必须从首帧开始，到尾帧结束
- 中间帧自然过渡，不跳变
- 保持角色外观一致（服装、面孔、体型不变）
- 保持场景环境一致（背景、光影不变）""",
    },

    "dialogue_format": {
        "key": "dialogue_format",
        "editable": True,
        "defaultContent": """=== 对白处理 ===
如果镜头有对白，角色在说话时：
- 口型与对白内容大致匹配（不需要逐帧精确）
- 说话时有自然的面部表情和肢体动作
- 对白节奏与动作节奏协调""",
    },

    "frame_anchors": {
        "key": "frame_anchors",
        "editable": True,
        "defaultContent": """=== 帧锚点 ===
- 首帧是此镜头的起始状态，必须精确匹配
- 尾帧是此镜头的结束状态，必须精确匹配
- 中间帧自然过渡，遵循物理规律
- 运动轨迹平滑，无突变或抖动""",
    },
}


def build_full_prompt(slot_contents: dict = None) -> str:
    """Build full prompt for FLF2V video generation."""
    sc = slot_contents or {}

    def resolve(key: str) -> str:
        override = sc.get(key)
        if override is not None:
            return override
        return SLOTS[key]["defaultContent"]

    return "\n\n".join([
        resolve("interpolation_header"),
        resolve("dialogue_format"),
        resolve("frame_anchors"),
    ])
