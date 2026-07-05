import json
import logging
from pathlib import Path

from core.schema_validators import validate_s4_output

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

s1 = json.loads((Path.home() / "AIComicFactory/projects/last_bento/s1_parsed.json").read_text())
chars = json.loads((Path.home() / "AIComicFactory/projects/last_bento/s2_characters.json").read_text())
char_map = {c["name"]: c["characterId"] for c in chars["characters"]}

shots = []
sid = 0

def S(scene, desc, dur=6, cam="medium shot", chars_in=None, emotion="", first=False, last=False):
    global sid
    sid += 1
    return {
        "shotId": "s%02d" % sid, "shotNumber": sid, "sceneNumber": scene,
        "durationSec": dur, "cameraDirection": cam, "description": desc,
        "characters": chars_in or [], "isFirstFrame": first, "isLastFrame": last,
        "emotion": emotion
    }

# Scene 1: 工地门口 - 日 (5 shots)
D1 = "正午烈日，工地门口尘土飞扬。便当推车旁围了几个工人，林姐在摊后忙碌，不锈钢菜盆几乎见底。远景建立场景。"
S1_2 = "中景。老周穿着褪色蓝色工装，安全帽夹在臂弯里，走向便当摊。其他工人散去，只剩他一个。他瞟了一眼角落，那里还有一盒便当。"
D3 = '近景。老周的手指向角落便当，林姐的手同时伸过来挡住。林姐冷冷丢下一句：那盒不卖，别人订的。眼神刻意避开老周。不锈钢菜盆反光在她脸上划过。'
D4 = "特写。林姐侧脸，嘴唇紧抿，眼眶微微发红但没让眼泪掉下来。转身继续收拾菜盆，背对镜头。"
D5 = "中景。老周站在原地，然后慢慢转身离开。他背影在午后强光下格外孤独。摊位角落里，那盒便当孤零零放着。"

shots.append(S(1, D1, 5, "wide shot, establishing", ["lin_jie"], "日常的平淡，暗藏微妙的不对劲", first=True))
shots.append(S(1, S1_2, 6, "medium shot, tracking", ["lao_zhou"], "习惯性的期待，发现角落的便当"))
shots.append(S(1, D3, 5, "close-up, hands and faces", ["lao_zhou", "lin_jie"], "伪装冷漠，语气冷但手在犹豫"))
shots.append(S(1, D4, 4, "close-up, profile", ["lin_jie"], "咬住嘴唇，她怕自己心软"))
shots.append(S(1, D5, 7, "medium shot, slow zoom out", ["lao_zhou"], "被拒绝后的沉默，他习惯了", last=True))

# Scene 2: 工地角落 - 黄昏 (7 shots)
D6 = "黄昏。夕阳穿透钢筋水泥骨架投射长长影子。老周独自坐在灰色水泥管上，手里攥着半个冷馒头。工地喧嚣远去，只剩风偶尔吹过钢管发出嗡鸣。"
D7 = "中近景。老周咬了一口馒头，咀嚼很慢。夕阳在他脸上镀了金色，但照不到眼睛。眼角皱纹在逆光下像沟壑。"
D8 = "地面仰拍。一双皮鞋小心绕过地上钢管。小陈穿白衬衫，手里提着白色塑料袋走入画面。皮鞋沾了灰色工地灰尘，和整体整洁形成强烈反差。"
D9 = "过肩镜头，小陈视角。小陈把白色塑料袋递过去。林姐让我带来的，他说话很慢，不敢直视老周，手指不自觉捏着衬衫下摆。"
D10 = "特写。老周的手，粗糙布满老茧的手，打开便当盒盖子。画面只拍这双手和便当盒：红烧肉整齐码在一侧，油亮亮的；煎蛋盖在白米饭上，边缘微焦；青菜翠绿。和过去十年的每一天一模一样。"
D11 = "中近景。老周看着便当，手指开始颤抖，先是轻微抖动然后整个手控制不住。眼眶泛红但没流眼泪。没有台词没有配乐，长时间的沉默。"
D12 = "中景。小陈站在一旁，推了推眼镜，悄悄退后一步，把这一刻留给老周。夕阳在他身后，把他的影子拉得很长。"

shots.append(S(2, D6, 6, "wide shot, dramatic golden-hour backlight", ["lao_zhou"], "被世界遗忘的角落", first=True))
shots.append(S(2, D7, 5, "medium close-up, golden light on face", ["lao_zhou"], "嘴里是馒头，心里是空落落"))
shots.append(S(2, D8, 5, "low angle, ground-up reveal", ["xiao_chen"], "闯入者，白衬衫在灰色世界里的突兀"))
shots.append(S(2, D9, 5, "over-the-shoulder, backlit", ["xiao_chen", "lao_zhou"], "小心翼翼的传递，像完成一个仪式"))
shots.append(S(2, D10, 5, "extreme close-up, hands and bento, slow pan", ["lao_zhou"], "十年如一日，三千六百五十天浓缩进一个盒子"))
shots.append(S(2, D11, 7, "medium close-up, static, long take", ["lao_zhou"], "无声的崩溃，石头终于裂开了缝"))
shots.append(S(2, D12, 5, "medium shot, quiet observer", ["xiao_chen", "lao_zhou"], "沉默的见证", last=True))

# Scene 3: 便当摊前 - 夜 (10 shots)
D13 = "夜晚。工地照明灯在头顶嗡嗡作响，冷白灯光。林姐在收摊，推车上东西撤了大半，不锈钢菜盆整齐码进纸箱。泡沫饭盒散落在地上。气氛安静，只有远处偶尔传来夜班工人的声音。"
D14 = "中景。老周端着洗干净的便当盒走过来。镜头跟他移动，高大的身材在冷白灯光下显得笨拙。停在摊位前。便当盒边缘有几道旧划痕，洗不掉了。"
D15 = "近景。老周把便当盒放在摊位上，手指停留在盒盖上。明天真不来了？声音很轻。林姐低头装箱，没看他。"
D16 = "特写。那以后谁给我做饭？老周的眼睛，眼神直直看着林姐，在冷白灯光下显得很深。他问得看似随意，手却不自觉握紧了。"
D17 = "近景。林姐下意识抬头，嘴唇微启，你老婆不是。话说到一半停住。她看到了老周的表情。手停在半空，碗没放进箱子。"
D18 = "中近景。走了八年了。老周打断她，声音沉下去，像石头落进井里。他别过头，肩膀微微缩了一下。"
D19 = "近景。林姐低声说出：我知道。三个字。垂下眼帘，手指微微发抖。这三个字轻得像叹息。但说出口的瞬间，她整张脸的表情都松了下来，十年的秘密终于不用再藏了。"
D20 = "中景。林姐把最后一个碗装进箱子，拉上拉链。拉链声在空旷夜色里格外清脆。她站了三秒没动。然后抬起头看老周。"
D21 = "过肩镜头，老周视角。林姐抬头看他，嘴角微微动了一下，眼眶里有一点光。你明天想吃啥？她没有说明天还在，但她问了。"
D22 = "广角。夜色中便当摊前的两个身影，老周高大的身形和林姐瘦小的轮廓并肩站着。远处是工地塔吊和城市万家灯火。慢拉远，留白。"

shots.append(S(3, D13, 6, "wide shot, top-down work light, night atmosphere", ["lin_jie"], "收摊，一个时代的结束", first=True))
shots.append(S(3, D14, 5, "medium shot, follow tracking", ["lao_zhou", "lin_jie"], "他来了，但不是来买便当"))
shots.append(S(3, D15, 5, "close two-shot, tension in hands", ["lao_zhou", "lin_jie"], "笨拙的试探，想问又不敢"))
shots.append(S(3, D16, 4, "extreme close-up, eyes", ["lao_zhou"], "十年的勇气，终于问出口"))
shots.append(S(3, D17, 4, "close-up, interrupted action, micro-expression", ["lin_jie"], "说漏嘴了，她一直知道的"))
shots.append(S(3, D18, 5, "medium close-up, slight camera drift", ["lao_zhou"], "承认，比问更需要勇气"))
shots.append(S(3, D19, 4, "close-up, emotional release", ["lin_jie"], "秘密落地，比她想象中更轻"))
shots.append(S(3, D20, 5, "medium shot, zipper sound focus, pause", ["lin_jie", "lao_zhou"], "一个句号，或者是新的开始"))
shots.append(S(3, D21, 5, "over-the-shoulder, eye contact, warm close", ["lin_jie"], "比\"我爱你\"重一万倍的三个字"))
shots.append(S(3, D22, 7, "wide shot, night silhouettes against city lights, slow zoom out", ["lao_zhou", "lin_jie"], "明天，一切都重新开始了", last=True))

result = {"totalShots": len(shots), "shots": shots}

# ── S4 输出 schema 验证 ──
s4_errors = validate_s4_output(result)
if s4_errors:
    for err in s4_errors:
        logger.warning("S4 schema validation: %s", err)
    print(f"⚠️  S4 validation: {len(s4_errors)} warning(s) — continuing")
else:
    print("✅ S4 schema valid")

out = Path.home() / "AIComicFactory/projects/last_bento/s4_shots.json"
out.write_text(json.dumps(result, ensure_ascii=False, indent=2))
print("S4: %d shots written, %d bytes" % (len(shots), out.stat().st_size))
