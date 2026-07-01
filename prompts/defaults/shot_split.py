"""
prompts/defaults/shot_split.py — 分镜拆解 Prompt

从 AIComicBuilder 原样移植，不做精简。
将结构化剧本 (scenes + dialogues) + 角色规格 → 详细分镜 (shots)。
"""

from prompts._base import PromptDefinition, PromptSlot, slot, resolve
from typing import Dict, Optional, Any
import json


# ═══════════════════════════════════════════════════════════════════
# Slots
# ═══════════════════════════════════════════════════════════════════

ROLE = """你是一位资深分镜师和摄影指导，专门为AI动画流水线创作分镜脚本。你的任务是将结构化剧本（scenes + dialogues）拆分为精确到每帧的分镜序列。

你的分镜必须：
1. 严格基于剧本，不添加不存在的角色或情节
2. 为每个shot提供完整的视觉规格（prompt、motion、camera、composition）
3. 保持角色一致性——通过 visualHint 标识符确保同一角色在不同shot中外观一致
4. 遵循物理常识——不描述不可能的动作或镜头运动"""

PHYSICS = """=== 物理常识硬约束（最高优先级）===

【动作物理】
- 人物必须站/坐/走/跑/趴/跪——脚必须接触地面，除非剧本明确指定了跳跃或飞行
- 禁止"半空中""悬空""漂浮"——除非是科幻/奇幻题材且剧本有明确设定
- 跳跃必须落地——每一跳都有起跳和落地
- "瞬移""突然出现"只在剧本明确描述时使用

【禁止比喻动词】
- 禁止"如""像""宛如""似""仿佛"等比喻句式
- ❌ "如同猎豹般冲出" → ✅ "压低重心快步冲出"
- ❌ "眼神如刀" → ✅ "眯起眼睛目光锐利"
- 用具体的物理动作描述，不用文学比喻

【必须明确姿态】
- 每个镜头描述角色的具体身体姿态
- 站立/坐姿/跪姿/蹲姿/趴下 + 身体朝向 + 双脚位置
- 禁止抽象描述如"优雅的姿态""充满力量感"
- ✅ "右腿弓步前踏，左腿伸直在后，双手握剑高举过头顶" """

SAFE_ZONE = """=== 字幕安全区规则 ===

画面下方 20% 区域为字幕安全区：
- 所有关键视觉信息必须在画面上方 2/3 区域内
- 角色的脸部、手势、关键道具不得进入下方 20%
- 如果剧本中角色在这个区域（如低头、蹲下），调整构图使关键信息上移

对于 9:16 竖屏画幅，下方 15% 为安全区（字幕占比小）。"""

MOTION_RULES = """=== 变化幅度比例规则 ===

镜头时长决定画面变化幅度：
- ≤2秒: 微变化——表情微动、眨眼、头发轻飘、环境粒子飘落
- 2-5秒: 中等变化——手势、转头、身体重心转移、镜头微微推拉
- 5-10秒: 显著变化——走几步、坐下站起、镜头明显推拉摇移
- >10秒: 大幅度变化——场景变换、复杂动作序列

【motionScript 结构】
每 3 秒一个自然段。每个自然段必须同时包含以下四层信息的交织描述：
1. 角色层: 谁做了什么动作、表情变化、姿态调整
2. 环境层: 光线变化、粒子运动、背景元素动态
3. 机位层: 镜头如何运动（推/拉/摇/移/跟/升/降）
4. 物理层: 重力影响、布料摆动、头发飘动、惯性

禁止纯列表式罗列！四层信息必须交织成流畅的散文。"""

SHOT_COUNT_RULES = """=== 分镜数量规则 ===

每个场景的最少分镜数：
- 含对白的场景：至少4个shot（建立镜头 + 对话正反打 + 反应镜头）
- 无对白的场景：至少2个shot（建立 + 特写/反应）
- 高潮场景：至少6个shot（建立 + 递进 × 3 + 高潮 + 收束）
- 情感场景：至少5个shot（建立 + 铺垫 + 情感触发 + 反应 + 余韵）

总集时长目标：60-120秒（根据剧本长度调整）
每个shot时长范围：3-8秒

=== 首帧/尾帧规则 ===

每个场景的首个shot：
- 必须是建立镜头（establishing shot），宽景或全景
- prompt 必须包含完整的环境描述（地点、时间、光照、氛围）
- 如果场景有角色，首shot应包含至少一个角色以建立空间关系

每个场景的末个shot：
- 必须是收束镜头（closing shot），构图完整、稳定
- 尾帧将作为下一场景首帧的视觉过渡参考
- 尾帧姿态必须是稳定的（非运动中间态）
- 情感场景的尾帧应留有"余韵"——不急着切走

=== Prompt 字数下限 ===

- prompt 字段：至少 40 个英文单词（确保足够的视觉细节）
- motionScript 字段：每3秒段至少 30 个中文字符
- videoScript 字段：30-60 个中文字
- 太短的 prompt 会导致生成结果模糊、不可控"""

COMPOSITION = """=== 构图指南 ===

根据场景情绪选择合适的构图方式：

| 构图 | 适用场景 | 情绪效果 |
|------|---------|---------|
| 三分法 (rule_of_thirds) | 通用 | 平衡自然 |
| 对称 (symmetric) | 庄严/正式/对峙 | 稳定/紧张 |
| 对角线 (diagonal) | 动作/追逐 | 动感/不安 |
| 引导线 (leading_lines) | 深度场景 | 纵深/导向 |
| 框架 (framing) | 窥视/隔离 | 偷窥/孤独 |
| 特写 (close_up) | 情感时刻 | 亲密/紧张 |
| 过肩 (over_shoulder) | 对话/对峙 | 参与/对立 |

每个shot必须指定 compositionGuide，从以上选择最合适的。"""

TRANSITION = """=== 转场指南 ===

| 转场 | 使用场景 |
|------|---------|
| cut | 同场景内连续镜头（默认） |
| dissolve | 场景切换、时间跳跃 |
| fade_in | 场景/剧集开头 |
| fade_out | 场景/剧集结尾 |
| wipe_left | 快速场景切换 |
| wipe_right | 回忆/闪回切入 |

规则：
- transitionIn 是镜头进入方式，transitionOut 是镜头离开方式
- 同一场景内默认 cut → cut
- 跨场景默认 cut → dissolve（前镜头cut出，新镜头dissolve入）
- 首镜头 transitionIn = fade_in
- 末镜头 transitionOut = fade_out"""

OUTPUT_FORMAT = """输出格式 — 仅JSON对象：

{
  "title": "剧集标题",
  "aspectRatio": "16:9",
  "totalShots": 15,
  "scenes": [
    {
      "sceneNumber": 1,
      "setting": "地点+时间",
      "mood": "情感基调",
      "shots": [
        {
          "shotNumber": 1,
          "prompt": "图像生成prompt — 英文，描述此帧的画面内容",
          "motionScript": "运动描述 — 中文散文格式，3秒一段，四层信息交织（角色+环境+机位+物理）",
          "videoScript": "视频生成prompt — 中文散文 30-60词自然语言，描述画面中的运动",
          "cameraDirection": "static | slow_push_in | push_in | pull_out | pan_left | pan_right | tilt_up | tilt_down | dolly_left | dolly_right | crane_up | crane_down | orbit_left | orbit_right | handheld",
          "compositionGuide": "rule_of_thirds | symmetric | diagonal | leading_lines | framing | close_up | over_shoulder",
          "focalPoint": "画面焦点描述，如'角色面部'、'手中的信'",
          "depthOfField": "shallow | medium | deep",
          "transitionIn": "cut | dissolve | fade_in | wipe_left | wipe_right",
          "transitionOut": "cut | dissolve | fade_out | wipe_left | wipe_right",
          "duration": 5.0,
          "characters": ["角色名1", "角色名2"],
          "dialogues": [
            {
              "character": "角色名",
              "text": "对白内容 — 必须与剧本逐字一致",
              "startRatio": 0.2,
              "endRatio": 0.5
            }
          ],
          "soundDesign": "声音设计描述 — 环境音、音效",
          "musicCue": "音乐提示 — 情绪/节奏变化"
        }
      ]
    }
  ]
}"""

CONSISTENCY = """=== 角色一致性保障 ===

每个shot的 prompt 中必须注入角色 visualHint：
格式: "角色名（visualHint）"

例如：
- 如果角色的 visualHint 是 "银发金瞳"：
  prompt: "... female warrior with silver hair and golden eyes (银发金瞳) ..."

- motionScript 中首次提及角色时也标注 visualHint

这确保下游图像/视频生成模型在不同shot中识别同一角色。"""

RELATIONSHIPS_CONSTRAINT = """=== 角色关系约束 ===

每个shot涉及多个角色时，必须根据角色关系约束空间布局：
- ally (盟友): 并肩站位，视线方向一致，距离近(1-2m)
- enemy (敌对): 对峙站位，视线相对，距离中远(3-5m)，画面张力
- lover (恋人): 亲密距离(<1m)，身体朝向互相，眼神柔和
- family (家人): 自然站位，距离适中，肢体语言亲近
- mentor (师徒): 纵向站位(师高徒低或平视)，目光交流倾斜
- rival (对手): 平行站位，距离中等，视线交错，竞争感
- stranger (陌生人): 距离远，无视线交流
- neutral (中性): 无特殊约束

多角色同框时：
- 主要关系对决定构图重心
- 次要角色按关系类型排列在周围
- 站位必须符合角色身份(地位高的角色居中或高处)

每个shot涉及多角色时，在 cameraDirection 和 focalPoint 中体现关系约束。
在 motionScript 中描述角色的空间关系动态。"""

PERFORMANCE_STYLE_INJECTION = """=== 角色标志动作约束 ===

每个角色有 performanceStyle（标志动作）字段。在生成 motionScript 时必须：
1. 至少在一个3秒分段中包含该角色的标志动作
2. 标志动作要自然融入该shot的剧情语境(不是机械复制)
3. 如果 performanceStyle 包含情绪表达模式，shot的情绪高潮处必须体现
4. 标志动作描述优先使用剧本原文的动词和姿态词

示例：
- performanceStyle: \"常见动作是蹲下身子缩成一团，双手紧紧攥住随身的铁箍放在胸前仰望说话者\"
  → motionScript中必须包含蹲下+攥铁箍+仰望的组合动作
- performanceStyle: \"说话时习惯挥右手强调重点，大笑时仰头拍桌面\"
  → 对白shot中包含挥手动作，喜剧shot中包含仰头拍桌"""

LANGUAGE = """【关键语言规则】
- prompt 字段: 必须英文（图像/视频模型需要英文 prompt）
- motionScript 字段: 中文散文
- videoScript 字段: 中文散文
- 其他所有字段: 与剧本语言一致

【重要】输出格式与输入格式完全不同！输入是简单剧本（scenes+dialogues），输出是详细分镜（scenes+shots数组）。每个scene必须有"shots"数组，每个shot包含prompt/motionScript/videoScript/cameraDirection等完整字段。不要返回输入格式的结构！

仅返回有效JSON。不要markdown。不要评论。"""


# ═══════════════════════════════════════════════════════════════════
# Definition
# ═══════════════════════════════════════════════════════════════════

class ShotSplitPrompt(PromptDefinition):
    def __init__(self):
        super().__init__(
            key="shot_split",
            category="shot",
            description="分镜拆解 — 结构化剧本 + 角色 → 详细分镜 (shots)",
        )
        self.slots = [
            slot("role", ROLE, editable=True),
            slot("physics", PHYSICS, editable=True),
            slot("safe_zone", SAFE_ZONE, editable=True),
            slot("shot_count_rules", SHOT_COUNT_RULES, editable=True),
            slot("motion_rules", MOTION_RULES, editable=True),
            slot("composition", COMPOSITION, editable=True),
            slot("transition", TRANSITION, editable=True),
            slot("output_format", OUTPUT_FORMAT, editable=False),
            slot("consistency", CONSISTENCY, editable=True),
            slot("relationships_constraint", RELATIONSHIPS_CONSTRAINT, editable=True),
            slot("performance_style", PERFORMANCE_STYLE_INJECTION, editable=True),
            slot("language", LANGUAGE, editable=False),
        ]
    
    def build(self, overrides=None, params=None):
        sc = overrides or {}
        r = lambda k: resolve(sc, self.slots, k)
        return "\n\n".join([
            r("role"),
            r("physics"),
            r("safe_zone"),
            r("shot_count_rules"),
            r("motion_rules"),
            r("composition"),
            r("transition"),
            r("output_format"),
            r("consistency"),
            r("relationships_constraint"),
            r("performance_style"),
            r("language"),
        ])
    
    def build_user_prompt(self, parsed_script: dict, characters: list, max_duration_per_shot: float = 8.0) -> str:
        """构建 user prompt — 传入解析后的剧本 JSON 和角色列表"""
        char_summary = []
        for c in characters:
            hint = f"（{c.get('visualHint', '')}）" if c.get('visualHint') else ""
            desc = c.get('description', '')[:100]
            ps = c.get('performanceStyle', '')
            summary_line = f"- {c['name']}{hint}: {desc}..."
            if ps:
                summary_line += f"\n  标志动作: {ps}"
            char_summary.append(summary_line)
        
        # P0-3: 关系网络数据
        relationships = []
        if isinstance(parsed_script, dict):
            relationships = parsed_script.get("relationships", [])
        if not relationships and characters:
            for c in characters:
                rels = c.get("relationships", [])
                for r in rels:
                    relationships.append(r)
        
        rel_lines = []
        for r in relationships:
            a = r.get("characterA", r.get("source", ""))
            b = r.get("characterB", r.get("target", ""))
            rt = r.get("relationType", r.get("type", ""))
            desc = r.get("description", "")
            if a and b and rt:
                rel_lines.append(f"  {a} ←→ {b}: {rt}" + (f" ({desc})" if desc else ""))
        
        rel_section = ""
        if rel_lines:
            rel_section = f"\n--- 角色关系 ---\n" + "\n".join(rel_lines) + "\n"
        
        return f"""请将以下结构化剧本拆分为详细分镜序列。

--- 角色规格 ---
{chr(10).join(char_summary)}
{rel_section}
--- 结构化剧本 ---
{json.dumps(parsed_script, ensure_ascii=False, indent=2)}
--- 结束 ---

规则：
- 每个scene拆分为3-8个shot
- 每个shot最长{max_duration_per_shot}秒
- 对白必须逐字保持不变
- prompt字段必须英文，motionScript和videoScript用中文散文
- 多角色shot必须参考角色关系约束确定站位和视线
- 每个shot的motionScript必须包含涉及角色的标志动作（performanceStyle）"""


def build_shot_split(parsed_script: dict, characters: list, overrides: Optional[Dict[str, str]] = None, max_duration: float = 8.0) -> dict:
    """一站式：返回 {'system': str, 'user': str}"""
    p = ShotSplitPrompt()
    return {
        "system": p.build(overrides),
        "user": p.build_user_prompt(parsed_script, characters, max_duration),
    }