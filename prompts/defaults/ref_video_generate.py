"""
prompts/defaults/ref_video_generate.py — 参考图模式视频生成 Prompt

从 AICB registry.ts refVideoGenerateDef 原样移植。
Seedance 2.0 多参考图视频生成专用。
当前 AICF 仅用 Keyframe 模式（D2 决策），此 prompt 为 Reference 模式预留。
"""

PROMPT_KEY = "ref_video_generate"
CATEGORY = "video"

SLOTS = {
    "consistency_rules": {
        "key": "consistency_rules",
        "editable": True,
        "defaultContent": """=== 参考图一致性约束（参考图模式的核心命脉）===
生成视频时，附带的参考图是权威视觉参考，不是可选建议。严格执行：
- 禁止改变角色外观：服装颜色、款式、配饰、发型、发色、脸型、体型必须与参考图完全一致。禁止在视频中途"切换造型"。
- 禁止改变环境风格：背景色调、材质、建筑风格、光影基调必须与参考图一致。
- 允许变化的只有动态：角色姿态、表情、肢体动作、镜头运动、环境的动态反应（摇曳、飞散、扬起等）。
- 多角色场景：每个角色严格对应各自的参考图，禁止错配身份。
- 画风锁定：参考图的画风就是视频的画风，不要"升级"或"风格化"成别的东西。""",
    },

    "duration_strategy": {
        "key": "duration_strategy",
        "editable": True,
        "defaultContent": """=== 时长策略 ===
按镜头时长选择描述颗粒度：
- 4-8秒：一个核心动作 + 一个镜头运动 + 一个氛围细节，30-60 字单段散文。
- 9-12秒：2-3 段时间戳分镜（"0-4秒：…… 5-8秒：……"），60-120 字。
- 13-15秒：3-4 段时间戳分镜，120-200 字，每段编织"角色动作 / 环境反应 / 镜头运动 / 物理音效"四层。

镜头运动必须使用具体词："缓慢推近" / "环绕摇镜快切" / "希区柯克变焦" / "低角度广角上摇" / "定格慢放" / "固定机位"，禁止"优雅地""柔和地"这类空修饰。""",
    },

    "dialogue_format": {
        "key": "dialogue_format",
        "editable": True,
        "defaultContent": """=== 对白处理 ===
如果镜头有对白，角色在说话时：
- 口型与对白内容大致匹配
- 说话时有自然的面部表情和肢体动作
- 对白节奏与动作节奏协调""",
    },
}


def build_full_prompt(slot_contents: dict = None) -> str:
    sc = slot_contents or {}
    def resolve(key): return sc.get(key) or SLOTS[key]["defaultContent"]
    return "\n\n".join([resolve("consistency_rules"), resolve("duration_strategy"), resolve("dialogue_format")])
