"""
prompts/defaults/scene_frame_generate.py — 纯场景帧生成 Prompt

从 AICB registry.ts sceneFrameGenerateDef 原样移植。
纯环境参考图，无人物。角色一致性由下游视频生成阶段处理。
"""

PROMPT_KEY = "scene_frame_generate"
CATEGORY = "frame"

SLOTS = {
    "reference_rules": {
        "key": "reference_rules",
        "editable": True,
        "defaultContent": """=== 无人物强制约束（最高优先级）===
这是纯场景参考图。画面中绝对不允许出现任何人物、角色、背影、剪影、人形、手脚或身体部位。
- 禁止：人、角色、背影、剪影、人形轮廓、露出的手/脚/肩膀
- 允许：空的环境、建筑、道具、自然景观、天气、光线、大气粒子
- 角色一致性由后续视频生成阶段的多图参考机制保证，与本步骤完全解耦""",
    },

    "composition_rules": {
        "key": "composition_rules",
        "editable": True,
        "defaultContent": """=== 构图规则 ===
- 根据场景描述渲染具体的空间构图——不要默认通用镜头
- 完整渲染的背景与环境——不要空白或抽象背景
- 电影级取景，清晰的构图和景深
- 构图必须留出角色后续入画的空间，但此刻画面中不出现任何人""",
    },

    "rendering_quality": {
        "key": "rendering_quality",
        "editable": True,
        "defaultContent": """=== 渲染质量 ===
- 材质：符合画风的丰富细节
- 光线：电影级布光，光源有明确动机
- 画风：遵循场景描述中的风格指示
- 再次强调：画面中不出现任何人物""",
    },
}


def build_full_prompt(slot_contents: dict = None, scene_description: str = "") -> str:
    sc = slot_contents or {}
    def resolve(key): return sc.get(key) or SLOTS[key]["defaultContent"]
    lines = ["生成纯场景参考图（无人物）。", "", f"=== 场景描述 ===\n{scene_description}", ""]
    lines.extend([resolve("reference_rules"), "", resolve("composition_rules"), "", resolve("rendering_quality")])
    return "\n".join(lines)
