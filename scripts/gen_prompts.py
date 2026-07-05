import json
import logging
from pathlib import Path

from core.schema_validators import validate_s1_output

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

PROJECT = Path.home() / "AIComicFactory/projects/last_bento"

# ── S1 验证 ──
s1_path = PROJECT / "s1_parsed.json"
if s1_path.exists():
    s1 = json.loads(s1_path.read_text())
    s1_errors = validate_s1_output(s1)
    if s1_errors:
        for err in s1_errors:
            logger.warning("S1 schema validation: %s", err)
        print(f"⚠️  S1 validation: {len(s1_errors)} warning(s) — continuing")
    else:
        print("✅ S1 schema valid")
else:
    print("⚠️  s1_parsed.json not found — skipping S1 validation")

s2 = json.loads((PROJECT / "s2_characters.json").read_text())
s4 = json.loads((PROJECT / "s4_shots.json").read_text())

chars = s2["characters"]
# Build lookup by both name and characterId
char_by_name = {}
for c in chars:
    char_by_name[c["name"]] = c
    char_by_name[c["characterId"]] = c
QUALITY = "masterpiece, best quality, very aesthetic, highres, detailed"

# ============ S3: Character Prompts ============
char_prompts = {}
for c in chars:
    name = c["name"]
    anchors = c.get("visualAnchors", {})
    is_female = c.get("gender") == "female"
    gender_tag = "1girl" if is_female else "1man, mature male"

    base = f"{QUALITY}, {gender_tag}, solo, full body, standing, front view, character reference sheet, white background, simple background"

    visual_tags = []
    for k, v in anchors.items():
        if v and v != "无特殊":
            visual_tags.append(v)

    prompt = base
    if visual_tags:
        prompt += ", " + ", ".join(visual_tags)
    prompt += ", detailed clothing, detailed face, detailed eyes"

    char_prompts[name] = prompt

# ============ S5: Frame Prompts ============
frame_prompts = {}

# Support flat format
shots = s4.get("shots", [])
# Detect sceneNumber — if not in shot, try to infer from shotId
for sh in shots:
    sn = sh["shotNumber"]
    desc = sh["description"]
    cam = sh.get("cameraDirection", "")
    char_names = sh.get("characters", [])
    scene_num = sh.get("sceneNumber", 1)  # fallback

    # Build character tags
    char_tags = []
    for cn in char_names:
        c = char_by_name.get(cn)
        if c:
            gender_t = "1girl" if c.get("gender") == "female" else "1man, mature male"
            char_tags.append(gender_t)
            anchors = c.get("visualAnchors", {})
            for k in ["face_shape", "hair_eyes", "build_posture", "clothing", "distinctive"]:
                v = anchors.get(k, "")
                if v and v != "无特殊":
                    char_tags.append(v)

    # Camera mapping
    cam_tags = []
    if "close-up" in cam or "close up" in cam:
        cam_tags.append("close-up")
    elif "wide" in cam:
        cam_tags.append("wide shot, establishing shot")
    elif "medium" in cam:
        cam_tags.append("medium shot")
    if "backlit" in cam or "backlight" in cam:
        cam_tags.append("backlighting, dramatic light, golden hour")
    if "night" in cam or "night" in desc[:20]:
        cam_tags.append("night, dark, artificial light")
    if "over-the-shoulder" in cam or "over the shoulder" in cam:
        cam_tags.append("from behind, over the shoulder")

    # Scene location hints
    scene_hints = {
        1: "construction site gate, daytime, dusty, food stall cart, steel lunch containers",
        2: "construction site corner, sunset, cement pipes, industrial background, warm golden light",
        3: "night, construction site, work lights, cold white lighting, packing up food stall",
    }
    location = scene_hints.get(scene_num, "")

    scene_desc = desc.replace("。", ",").replace("，", ",").replace("、", ",")

    first_prompt = (
        f"{QUALITY}, cinematic lighting, dramatic, "
        f"{', '.join(cam_tags)}, "
        f"{', '.join(char_tags)}, "
        f"{location}, "
        f"{scene_desc[:200]}, "
        f"16:9 aspect ratio, widescreen, landscape orientation"
    )
    last_prompt = (
        f"{QUALITY}, cinematic lighting, dramatic, "
        f"{', '.join(cam_tags)}, "
        f"{', '.join(char_tags)}, "
        f"{location}, "
        f"{scene_desc[:200]}, "
        f"end of action, settled pose, "
        f"16:9 aspect ratio, widescreen, landscape orientation"
    )

    frame_prompts[f"s{sn:02d}_first"] = first_prompt
    frame_prompts[f"s{sn:02d}_last"] = last_prompt

out = {
    "s3_character_prompts": char_prompts,
    "s5_frame_prompts": frame_prompts,
}
out_path = PROJECT / "prompts.json"
out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2))
print(f"Prompts: {len(char_prompts)} chars + {len(frame_prompts)} frames → {out_path}")
