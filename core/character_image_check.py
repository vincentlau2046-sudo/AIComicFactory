#!/usr/bin/env python3
"""
core/character_image_check.py — S3a 角色参考图 VL 质检 (P1-2)

在 S3a 生成角色参考图后，用 qw35 VL 模型验证图像是否与角色关键信息一致：
- 性别 (从 description 推断)
- 年龄感 (从 visualHint/description 推断)
- 面部特征 (visualAnchors.face)
- 发型 (visualAnchors.hair)
- 服装 (visualAnchors.clothing)

用法:
    from core.character_image_check import CharacterImageChecker
    checker = CharacterImageChecker()
    result = checker.check(image_path, character_data)
    print(f"pass={result['pass']} score={result['score']}")

集成:
    # 在 s3_character_image.py 生成后自动调用
    result = checker.check(output_path, character)
    if not result['pass']:
        print(f"⚠️ {character['name']}: VL 质检未通过 ({result['score']}/10)")
        print(f"   → {result['summary']}")
"""

import base64
import json
import re
import urllib.request
from pathlib import Path
from typing import Optional

# ═══════════════════════════════════════════════════════════════════
# Config
# ═══════════════════════════════════════════════════════════════════

VLLM_URL = "http://localhost:8002/v1/chat/completions"
DEFAULT_MODEL = "vllm_qw35_gptq"

CHECK_PROMPT = """Output ONLY a JSON object. No explanation.
Compare this anime character image against the description.

Description: {description}

Check: sex({gender}) age({age}) hair({hair}) face({face}) clothes({clothing}) format(full body front white bg)

JSON: {{"g":{{"m":true,"s":2,"n":""}},"a":{{"m":true,"s":2,"n":""}},"h":{{"m":true,"s":2,"n":""}},"f":{{"m":true,"s":2,"n":""}},"c":{{"m":true,"s":2,"n":""}},"t":{{"m":true,"s":2,"n":""}},"o":10,"sum":"","iss":[],"re":false}}"""


def _detect_gender_from_text(text: str) -> str:
    """从角色描述推断性别."""
    if text is None:
        return "unknown"
    t = text.lower()
    if "她" in t or "小姐" in t or "女士" in t or "女" in t[:200]:
        if not ("男" in t.split("女")[0] if "女" in t and "男" in t else False):
            return "female"
    if "他" in t or "先生" in t or "男" in t[:200] or "小伙" in t or "老爹" in t:
        return "male"
    return "unknown"


def _detect_age_from_text(text: str, visual_hint: str = "") -> str:
    """从角色描述推断年龄段."""
    combined = f"{text or ''} {visual_hint or ''}"
    age_hints = [
        ("老年人", ["老年", "老头", "白发", "退休", "年老", "皱纹", "老人", "爷爷", "奶奶"]),
        ("中年人", ["中年", "师傅", "工头", "大姐", "阿姨", "大叔", "鱼尾纹", "灰白", "发际线后退"]),
        ("青年人", ["年轻", "小伙", "青年", "20岁", "大学生", "新手"]),
    ]
    for label, keywords in age_hints:
        for kw in keywords:
            if kw in combined:
                return label
    return "成年人"


def _image_to_base64(image_path: str) -> str:
    """Convert image to base64 data URL."""
    with open(image_path, "rb") as f:
        data = base64.b64encode(f.read()).decode()
    ext = Path(image_path).suffix.lower().replace(".", "")
    mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}.get(ext, "image/png")
    return f"data:{mime};base64,{data}"


def _call_vl(prompt: str, image_path: str, model: str = None) -> str:
    """Call qw35 vision model.
    
    qw35-9b uses --reasoning-parser qwen3 which splits thinking/response.
    During thinking, content=null; after thinking, content has the answer.
    We also check reasoning_content as fallback.
    """
    b64 = _image_to_base64(image_path)
    payload = {
        "model": model or DEFAULT_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": b64}},
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        "max_tokens": 8192,
        "temperature": 0.0,
    }
    req = urllib.request.Request(
        VLLM_URL,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    resp = json.loads(urllib.request.urlopen(req, timeout=120).read())
    msg = resp["choices"][0]["message"]
    # qw35 with reasoning-parser: content may be "None" (string) during thinking
    content = msg.get("content") or ""
    if content.strip().lower() in ("", "none"):
        content = ""
    reasoning = msg.get("reasoning") or msg.get("reasoning_content") or ""
    # Prefer actual content, fallback to reasoning
    result = content.strip() if content.strip() else reasoning.strip()
    if not result:
        raise RuntimeError(f"Empty response from VL model. msg keys: {list(msg.keys())}")
    return result


def _extract_json(text: str) -> dict:
    """Robust JSON extraction from VL response."""
    if not text:
        return {"overall_score": 0, "summary": "empty response", "issues": []}
    # Strip code fences
    for marker in ["```json", "```"]:
        if marker in text:
            text = text.split(marker)[1].split("```")[0]
            break
    text = text.strip()
    start = text.find("{")
    if start >= 0:
        try:
            obj, _ = json.JSONDecoder().raw_decode(text, start)
            return obj
        except Exception:
            pass
    # Fallback regex
    m = re.search(r'\{[^{}]*"overall_score"[^{}]*\}', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    return {"overall_score": 0, "summary": text[:200], "issues": ["JSON parse failed"]}


class CharacterImageChecker:
    """S3a 角色参考图 VL 质检器."""

    def __init__(self, model: str = None):
        self.model = model or DEFAULT_MODEL

    def check(self, image_path: str, character: dict) -> dict:
        """
        检查一张角色图是否与角色描述一致。

        Args:
            image_path: 图片路径
            character: s2_characters.json 中的角色对象

        Returns:
            {
                "character": str,
                "pass": bool,         # overall_score >= 7
                "score": int,
                "overall_score": int,
                "dimensions": {...},
                "issues": [...],
                "summary": str,
                "needs_regeneration": bool,
            }
        """
        name = character.get("name", "?")
        desc = character.get("description", character.get("appearance", ""))
        hint = character.get("visualHint", "")
        anchors = character.get("visualAnchors", {})

        gender = _detect_gender_from_text(desc)
        age = _detect_age_from_text(desc, hint)
        hair = anchors.get("hair", desc[:80])
        face = anchors.get("face", desc[:80])
        clothing = anchors.get("clothing", desc[:80])

        # Build short description for VL (keep under 200 chars)
        short_desc = f"{gender}, {age}; face: {face[:50]}; hair: {hair[:40]}; clothes: {clothing[:60]}"
        if hint:
            short_desc += f"; note: {hint[:30]}"
        short_desc = short_desc[:200]

        prompt = CHECK_PROMPT.format(
            description=short_desc,
            gender=gender,
            age=age,
            hair=hair[:60],
            face=face[:60],
            clothing=clothing[:80],
        )

        try:
            response = _call_vl(prompt, image_path, self.model)
            result = _extract_json(response)
        except Exception as e:
            return {
                "character": name,
                "pass": False,
                "score": 0,
                "overall_score": 0,
                "dimensions": {},
                "issues": [f"VL call failed: {e}"],
                "summary": f"质检失败: {e}",
                "needs_regeneration": False,
                "raw_response": None,
            }

        g = result.get("g", {})
        a = result.get("a", {})
        h = result.get("h", {})
        f = result.get("f", {})
        c = result.get("c", {})
        t = result.get("t", {})

        # Calculate overall from dimension scores (don't trust model's o)
        dim_scores = [g["s"], a["s"], h["s"], f["s"], c["s"], t["s"]]
        overall = sum(dim_scores)  # max 18, normalize to 10
        overall_norm = round(overall * 10 / 18, 1)
        if isinstance(overall, (int, float)):
            overall = int(overall)

        issues = result.get("issues", [])
        if not isinstance(issues, list):
            issues = [str(issues)]

        return {
            "character": name,
            "pass": overall_norm >= 7,
            "score": overall_norm,
            "overall_score": overall_norm,
            "dimensions": {
                "gender": {"match": g.get("m",False), "score": g.get("s",0), "note": g.get("n","")},
                "age": {"match": a.get("m",False), "score": a.get("s",0), "note": a.get("n","")},
                "hair": {"match": h.get("m",False), "score": h.get("s",0), "note": h.get("n","")},
                "face": {"match": f.get("m",False), "score": f.get("s",0), "note": f.get("n","")},
                "clothing": {"match": c.get("m",False), "score": c.get("s",0), "note": c.get("n","")},
                "format": {"match": t.get("m",False), "score": t.get("s",0), "note": t.get("n","")},
            },
            "issues": result.get("iss", []) or [],
            "summary": result.get("sum", ""),
            "needs_regeneration": result.get("re", overall < 5),
            "raw_response": response,
        }

    def check_batch(self, image_paths: list, characters: list) -> list:
        """批量检查多张角色图."""
        results = []
        for ip, char in zip(image_paths, characters):
            print(f"  {char['name']}... ", end="", flush=True)
            r = self.check(ip, char)
            icon = "✅" if r["pass"] else "⚠️"
            print(f"{icon} {r['score']}/10")
            results.append(r)
        return results

    def generate_report(self, results: list) -> str:
        """生成可读报告."""
        lines = ["S3a 角色图 VL 质检报告", "=" * 40]
        for r in results:
            status = "✅ PASS" if r["pass"] else "⚠️ FAIL"
            lines.append(f"\n{r['character']} — {status} ({r['score']}/10)")
            lines.append(f"  {r['summary']}")
            for dim_name, dim in r.get("dimensions", {}).items():
                icon = "✓" if dim["match"] else "✗"
                lines.append(f"  {icon} {dim_name}: {dim['score']}/3 {dim.get('note','')}")
            for iss in r.get("issues", []):
                lines.append(f"  • {iss}")
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="S3a VL 角色图质检")
    p.add_argument("--image", required=True, help="图片路径")
    p.add_argument("--project", default="last_bento")
    p.add_argument("--character", required=True, help="角色名")
    args = p.parse_args()

    # Load character
    s2_path = Path.home() / "AIComicFactory" / "projects" / args.project / "s2_characters.json"
    s2 = json.load(open(s2_path))
    char = next(c for c in s2["characters"] if c["name"] == args.character)

    checker = CharacterImageChecker()
    result = checker.check(args.image, char)
    print(checker.generate_report([result]))
    print()
    print(json.dumps(result, ensure_ascii=False, indent=2))