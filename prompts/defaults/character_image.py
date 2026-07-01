"""
prompts/defaults/character_image.py — 角色四视图 Prompt

从 AICB registry.ts characterImageDef 原样移植。
用于生成角色设定图（四视角参考图）。
Slot: layout_rules / style_fidelity / quality_rules
"""

PROMPT_KEY = "character_image"
CATEGORY = "character"

SLOTS = {
    "layout_rules": {
        "key": "layout_rules",
        "editable": True,
        "defaultContent": """=== 角色设定图布局 ===
生成一张角色设定图（character reference sheet），包含4个视角：
- 左上：正面视图（front view）
- 右上：3/4侧视图（3/4 angle view，身体微转约45度）
- 左下：侧面视图（side view，纯侧面）
- 右下：背面视图（back view）

布局为 2×2 网格，每个视角占 1/4 画面。
角色名字印在设定图底部居中位置。""",
    },

    "style_fidelity": {
        "key": "style_fidelity",
        "editable": True,
        "defaultContent": """=== 风格保真度（最高优先级）===
- 画风由角色描述中的关键词决定（古风→动漫/插画，现代→写实，科幻→写实+特效）
- 四个视角的画风必须完全一致
- 服装细节在所有视角中必须一致（颜色、款式、材质、配饰）
- 面部特征在所有视角中必须一致（五官、发型、发色）

=== 身份层（不可删除/修改）===
- 面孔特征：五官形状、比例、肤色
- 发型发色：长度、颜色、造型
- 体型：身高比例、体型类别
- 标志性配饰：面具、佩刀、特殊首饰等

=== 风格层（可重新诠释）===
- 服装具体款式可在不同作品间调整，但颜色/材质/风格大类不变
- 妆容浓淡可调，但整体风格不变""",
    },

    "quality_rules": {
        "key": "quality_rules",
        "editable": True,
        "defaultContent": """=== 质量要求 ===
- 分辨率: 高清，细节丰富
- 光线: 均匀的影棚布光，所有视角清晰可见，无过度阴影
- 背景: 纯白或浅灰，不分散注意力
- 每个视角: 角色完整可见（从头到脚），姿态为中性站立
- 表情: 中性/默认表情，不展示特定情绪
- 禁止: 多人、场景、道具（除角色自带配饰外）、文字水印""",
    },
}


def build_full_prompt(
    slot_contents: dict = None,
    character_name: str = "",
    character_description: str = "",
    visual_hint: str = "",
) -> str:
    """Build full prompt for character reference image generation."""
    sc = slot_contents or {}

    def resolve(key: str) -> str:
        override = sc.get(key)
        if override is not None:
            return override
        return SLOTS[key]["defaultContent"]

    lines = [f"生成角色「{character_name}」的设定图。", ""]
    lines.append(resolve("layout_rules"))
    lines.append("")
    lines.append("=== 角色描述 ===")
    lines.append(character_description)
    if visual_hint:
        lines.append(f"视觉速记: {visual_hint}")
    lines.append("")
    lines.append(resolve("style_fidelity"))
    lines.append("")
    lines.append(resolve("quality_rules"))
    return "\n".join(lines)


def build_flux_ref_prompt(
    slot_contents: dict = None,
    character_name: str = "",
    character_description: str = "",
    visual_hint: str = "",
    visual_anchors: dict = None,
) -> str:
    """Build natural language prompt for Flux Dev T2I character reference.
    
    Unlike the 4-view prompt (build_full_prompt), this generates a single
    front-view reference image suitable for Flux Dev T2I pipeline.
    Uses natural language instead of Danbooru tags.
    
    Key design: CHARACTER-FIRST, BACKGROUND-LAST.
    Flux Dev over-weights background instructions — if you say "white background"
    it'll make 75% of the image white. So we put the character description up front
    and keep background instruction minimal and at the end.
    """
    anchors = visual_anchors or {}
    
    # ── CHARACTER-FIRST structure ──
    char_parts = []
    
    # Core identity
    char_parts.append(f"Full body portrait of a character named {character_name}.")
    
    # Face & expression — most critical for reference
    face_parts = []
    if anchors.get("face"):
        face_parts.append(anchors["face"])
    if anchors.get("hair"):
        face_parts.append(anchors["hair"])
    if face_parts:
        char_parts.append(f"Face and head: {', '.join(face_parts)}. Looking directly at camera with neutral expression.")
    else:
        char_parts.append("Looking directly at camera with neutral expression.")
    
    # Body & clothing
    body_parts = []
    if anchors.get("body"):
        body_parts.append(anchors["body"])
    if anchors.get("clothing"):
        body_parts.append(anchors["clothing"])
    if body_parts:
        char_parts.append(f"Body and outfit: {', '.join(body_parts)}.")
    
    if anchors.get("signature"):
        char_parts.append(f"Signature detail: {anchors['signature']}.")
    
    if visual_hint:
        char_parts.append(f"Distinctive feature: {visual_hint}.")
    
    # Pose — fill the frame
    char_parts.append("Standing straight, facing forward, arms at sides. The figure fills most of the frame from head to toe.")
    
    # Style
    style_str = "detailed, high quality"
    if character_description:
        desc_lower = character_description.lower()
        if any(kw in desc_lower for kw in ["写实", "realistic", "photorealistic"]):
            style_str = "photorealistic, cinematic lighting, sharp focus, high detail"
        elif any(kw in desc_lower for kw in ["动漫", "anime", "漫画", "manga"]):
            style_str = "anime illustration, vibrant colors, clean linework, detailed"
    char_parts.append(f"Style: {style_str}.")
    
    # Background — LAST and minimal
    char_parts.append("Simple neutral gray background.")
    
    return " ".join(char_parts)
