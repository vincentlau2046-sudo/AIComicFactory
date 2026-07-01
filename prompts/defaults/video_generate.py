"""
prompts/defaults/video_generate.py — FLF2V 视频生成 Prompt (v2.0)

P0-5: 从 AICB video-generate.ts 完整移植 buildVideoPrompt 逻辑.
扩展到 7 slot: interpolation_header / character_appearance / dialogue_format /
           frame_anchors / motion_constraints / duration_timing / safe_zone_reminder

对齐 AICB 设计:
- buildVideoPrompt(): Keyframe 模式, 首尾帧插值
- buildReferenceVideoPrompt(): Reference 模式 (保留给未来)
- detectLanguage(): 中英文自动检测
- buildCharacterLine(): visualHint 标注的角色行
- dialogue 按 offscreen/onscreen 分流
"""

import re
from typing import Optional

PROMPT_KEY = "video_generate"
CATEGORY = "video"

# Slot text constants (avoiding triple-quote parser issues)
_INTERPOLATION_HEADER = "=== 首尾帧插值动画 ===\n" \
    "你将收到两张帧图像：首帧（镜头起始状态）和尾帧（镜头结束状态）。\n" \
    "生成从首帧到尾帧的平滑过渡动画。\n" \
    "- 动画必须从首帧开始，到尾帧结束——不可跳跃\n" \
    "- 中间帧自然过渡，运动曲线平滑\n" \
    "- 保持角色外观一致（服装、面孔、体型不变）\n" \
    "- 保持场景环境一致（背景、光影不变）\n" \
    "- 遵循物理规律：重力、惯性、碰撞"

_CHARACTER_APPEARANCE = "=== 角色形象 ===\n" \
    "角色形象必须与首尾帧中的角色精确匹配。\n" \
    "每个角色用 visualHint（视觉标识符）标注，确保跨镜头一致：\n" \
    "- 面孔特征：脸型、眼型、鼻型、唇型\n" \
    "- 发型发色：颜色、长度、质地、样式\n" \
    "- 体型：高矮、胖瘦、比例\n" \
    "- 服装：款式、颜色、材质、配饰\n" \
    "- 标识特征：武器、伤疤、纹身、眼镜等"

_DIALOGUE_FORMAT = "=== 对白处理 ===\n" \
    "画内对白: 【对白口型】角色名(visualHint): \"对白内容...\"\n" \
    "  - 口型与对白内容大致匹配（不需要逐帧精确）\n" \
    "  - 说话时有自然的面部表情和肢体动作\n" \
    "  - 对白节奏与动作节奏协调\n" \
    "画外旁白: 【画外音】角色名: \"旁白内容...\"\n" \
    "  - 画面中不需要口型匹配\n" \
    "  - 画面内容与旁白内容形成互补或对比"

_FRAME_ANCHORS = "[帧锚点]\n" \
    "首帧: {{START_FRAME_DESC}}\n" \
    "尾帧: {{END_FRAME_DESC}}\n" \
    "- 首帧是镜头起始状态，必须精确匹配\n" \
    "- 尾帧是镜头结束状态，必须精确匹配\n" \
    "- 中间帧自然过渡，遵循物理规律\n" \
    "- 运动轨迹平滑，无突变或抖动"

_MOTION_CONSTRAINTS = "=== 运动约束 (四层交织) ===\n\n" \
    "运动描述必须同时包含以下四层信息，交织成流畅的散文：\n\n" \
    "【角色层 — 谁做什么】\n" \
    "- 角色的具体动作：走/跑/跳/坐下/站起/转身/举手/点头/摇头\n" \
    "- 表情变化：从什么表情过渡到什么表情\n" \
    "- 姿态调整：身体重心转移、肢体协调\n" \
    "- 禁止悬浮、瞬移、反重力\n\n" \
    "【环境层 — 周围发生什么】\n" \
    "- 背景元素：树叶摇动、旗帜飘扬、水波荡漾\n" \
    "- 光线变化：阳光移动、灯光闪烁、阴影拉长\n" \
    "- 粒子运动：雨雪飘落、尘埃飞舞、烟雾升腾\n" \
    "- 布料物理：衣袖飘动、裙摆摆动、披风翻飞\n\n" \
    "【机位层 — 镜头怎么动】\n" \
    "- 镜头运动：推/拉/摇/移/跟/升/降/手持\n" \
    "- 运动速度：缓慢/匀速/加速/减速\n" \
    "- 运动范围：微调/中等/大幅度\n" \
    "- 焦点转移：从谁到谁、从人到物\n\n" \
    "【物理层 — 自然规律】\n" \
    "- 重力约束：下落有速度、落地有缓冲\n" \
    "- 惯性约束：急停有晃动、转头有跟随\n" \
    "- 碰撞约束：接触有反馈、力有作用与反作用"

_DURATION_TIMING = "=== 时长策略 ===\n" \
    "视频长度决定运动描述颗粒度：\n" \
    "- <=2秒: 微变化——表情微动、眨眼、头发轻飘、环境粒子飘落、镜头微推\n" \
    "- 2-5秒: 中等变化——手势、转头、身体重心转移、镜头微微推拉、光线渐变\n" \
    "- 5-8秒: 显著变化——走几步、坐下站起、镜头明显推拉摇移、情绪转换\n" \
    "- >8秒: 大幅度变化——完整动作序列、场景局部变化、复杂镜头运动\n\n" \
    "根据实际时长选择对应的运动复杂度。"

_SAFE_ZONE_REMINDER = "=== 字幕安全区 ===\n" \
    "画面下方 20% 区域为字幕安全区：\n" \
    "- 所有关键视觉信息必须在画面上方 2/3 区域内\n" \
    "- 角色的脸部、手势、关键道具不得进入下方 20%\n" \
    "- 如果角色在画面下方（如蹲下、低头），调整构图使关键信息上移\n\n" \
    "16:9 横屏: 下方 20% 安全区\n" \
    "9:16 竖屏: 下方 15% 安全区"

SLOTS = {
    "interpolation_header": {
        "key": "interpolation_header",
        "editable": True,
        "defaultContent": _INTERPOLATION_HEADER,
    },
    "character_appearance": {
        "key": "character_appearance",
        "editable": True,
        "defaultContent": _CHARACTER_APPEARANCE,
    },
    "dialogue_format": {
        "key": "dialogue_format",
        "editable": True,
        "defaultContent": _DIALOGUE_FORMAT,
    },
    "frame_anchors": {
        "key": "frame_anchors",
        "editable": True,
        "defaultContent": _FRAME_ANCHORS,
    },
    "motion_constraints": {
        "key": "motion_constraints",
        "editable": True,
        "defaultContent": _MOTION_CONSTRAINTS,
    },
    "duration_timing": {
        "key": "duration_timing",
        "editable": True,
        "defaultContent": _DURATION_TIMING,
    },
    "safe_zone_reminder": {
        "key": "safe_zone_reminder",
        "editable": True,
        "defaultContent": _SAFE_ZONE_REMINDER,
    },
}


def detect_language(text: str) -> str:
    """Detect if text is primarily Chinese or English."""
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
    return "zh" if chinese_chars > len(text) * 0.1 else "en"


def _get_labels(lang: str) -> dict:
    """Localized labels."""
    if lang == "zh":
        return {
            "characterAppearance": "角色形象",
            "camera": "镜头运动",
            "duration": "时长",
            "separator": "，",
            "period": "。",
            "colon": "：",
            "paren": {"open": "（", "close": "）"},
        }
    return {
        "characterAppearance": "Character Appearance",
        "camera": "Camera Movement",
        "duration": "Duration",
        "separator": ", ",
        "period": ".",
        "colon": ": ",
        "paren": {"open": "(", "close": ")"},
    }


def _build_character_line(characters: list, lang: str = "zh") -> Optional[str]:
    """Build visualHint-annotated character line."""
    with_hints = [c for c in characters if c.get("visualHint")]
    if not with_hints:
        return None
    L = _get_labels(lang)
    return L["separator"].join(
        f"{c['name']}{L['paren']['open']}{c['visualHint']}{L['paren']['close']}"
        for c in with_hints
    )


def _resolve_slot(slot_contents, slot_key, default_key):
    """Resolve a single slot value from overrides or defaults."""
    if slot_contents and slot_key in slot_contents:
        return slot_contents[slot_key]
    slot = SLOTS.get(default_key)
    if slot:
        return slot["defaultContent"]
    return ""


def build_reference_video_prompt(
    video_script: str,
    camera_direction: str,
    duration: float = 0,
    characters: list = None,
    dialogues: list = None,
    slot_contents: dict = None,
) -> str:
    """
    参考图模式视频 Prompt (AICB Toonflow/Kling reference mode).
    Seedance 格式: Shot描述(散文) -> Camera -> 【对白口型】.
    """
    lang = detect_language(video_script)
    L = _get_labels(lang)
    lines = []

    if duration:
        lines.append(f"{L['duration']}{L['colon']}{duration}s{L['period']}")
        lines.append("")

    char_line = _build_character_line(characters or [], lang)
    if char_line:
        lines.append(f"{L['characterAppearance']}{L['colon']}{char_line}{L['period']}")
        lines.append("")

    lines.append(video_script)
    lines.append("")
    lines.append(f"{L['camera']}{L['colon']}{camera_direction}{L['period']}")

    if dialogues:
        for d in dialogues:
            ch = d.get("character", d.get("characterName", ""))
            txt = d.get("text", "")
            offscreen = d.get("offscreen", False)
            hint = d.get("visualHint", "")
            if offscreen:
                label = "【画外音】" if lang == "zh" else "[Off-screen Voice]"
                lines.append(f"{label}{ch}: \"{txt}\"")
            else:
                label = "【对白口型】" if lang == "zh" else "[Dialogue Lip Sync]"
                ch_label = f"{ch}{L['paren']['open']}{hint}{L['paren']['close']}" if hint else ch
                lines.append(f"{label}{ch_label}: \"{txt}\"")

    return "\n".join(lines)


def build_video_prompt(
    video_script: str,
    camera_direction: str,
    start_frame_desc: str = "",
    end_frame_desc: str = "",
    scene_description: str = "",
    duration: float = 0,
    characters: list = None,
    dialogues: list = None,
    slot_contents: dict = None,
    aspect_ratio: str = "16:9",
) -> str:
    """
    Keyframe 模式视频 Prompt (主要使用).
    对齐 AICB buildVideoPrompt — 首尾帧插值 + 四层运动约束.
    """
    lang = detect_language(video_script)
    L = _get_labels(lang)
    lines = []

    # 1. Duration
    if duration:
        lines.append(f"{L['duration']}{L['colon']}{duration}s{L['period']}")
        lines.append("")

    # 2. Character appearance
    char_line = _build_character_line(characters or [], lang)
    if char_line:
        lines.append(f"{L['characterAppearance']}{L['colon']}{char_line}{L['period']}")
        lines.append("")

    # 3. Interpolation header
    lines.append(_resolve_slot(slot_contents, "interpolation_header", "interpolation_header"))
    lines.append("")

    # 4. Scene + Video script
    if scene_description:
        lines.append(f"场景: {scene_description}")
    lines.append(video_script)

    # 5. Camera direction
    lines.append("")
    lines.append(f"{L['camera']}{L['colon']}{camera_direction}{L['period']}")

    # 6. Frame anchors
    has_start = bool(start_frame_desc)
    has_end = bool(end_frame_desc)
    if has_start or has_end:
        anchor_text = _resolve_slot(slot_contents, "frame_anchors", "frame_anchors")
        anchor_text = anchor_text.replace("{{START_FRAME_DESC}}", start_frame_desc or "无")
        anchor_text = anchor_text.replace("{{END_FRAME_DESC}}", end_frame_desc or "无")
        lines.append("")
        lines.append(anchor_text)

    # 7. Motion constraints (P0-5 新增)
    lines.append("")
    lines.append(_resolve_slot(slot_contents, "motion_constraints", "motion_constraints"))

    # 8. Duration timing (P0-5 新增)
    if duration > 0:
        lines.append("")
        lines.append(_resolve_slot(slot_contents, "duration_timing", "duration_timing"))

    # 9. Safe zone (P0-5 新增)
    safe = _resolve_slot(slot_contents, "safe_zone_reminder", "safe_zone_reminder")
    if aspect_ratio == "9:16":
        safe = safe.replace("下方 20%", "下方 15%")
    lines.append("")
    lines.append(safe)

    # 10. Dialogues
    if dialogues:
        lines.append("")
        for d in dialogues:
            ch = d.get("character", d.get("characterName", ""))
            txt = d.get("text", "")
            offscreen = d.get("offscreen", False)
            hint = d.get("visualHint", "")
            if offscreen:
                label = "【画外音】" if lang == "zh" else "[Off-screen Voice]"
                lines.append(f"{label}{ch}: \"{txt}\"")
            else:
                label = "【对白口型】" if lang == "zh" else "[Dialogue Lip Sync]"
                ch_label = f"{ch}{L['paren']['open']}{hint}{L['paren']['close']}" if hint else ch
                lines.append(f"{label}{ch_label}: \"{txt}\"")

    return "\n".join(lines)


def build_full_prompt(slot_contents: dict = None) -> str:
    """Legacy: basic FLF2V prompt (backward compatible). 推荐使用 build_video_prompt()."""
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
        resolve("motion_constraints"),
    ])