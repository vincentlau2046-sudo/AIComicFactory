"""
core/continuity_check.py — 连续性检查器 (P1-1)

Uses local vLLM (qw35-9b) 4-dimension VL scoring for adjacent shot consistency.
"""

import json, base64, os, re, io
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

TZ = timezone(timedelta(hours=8))

VLLM_URL = "http://localhost:8002/v1/chat/completions"
DEFAULT_MODEL = "vllm_qw35_gptq"


def _extract_json_block(text: str, key: str = "") -> str:
    """Extract JSON object from LLM response, robust to code fences and nested braces."""
    # Strip code fences first
    for marker in ["```json", "```"]:
        if marker in text:
            text = text.split(marker)[1].split("```")[0]
            break
    text = text.strip()
    start = text.find("{")
    if start >= 0:
        try:
            obj, _ = json.JSONDecoder().raw_decode(text, start)
            return json.dumps(obj, ensure_ascii=False)
        except Exception:
            pass
    # Fallback: simple regex for flat objects
    if key:
        m = re.search(rf'\{{[^{{}}]*"{re.escape(key)}"[^{{}}]*\}}', text, re.DOTALL)
        if m:
            return m.group()
    return text


def _resize_encode(img_path: str, size=(384, 216)) -> str:
    """Resize image and encode as base64 JPEG for vLLM."""
    from PIL import Image
    img = Image.open(img_path).resize(size)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=70)
    return base64.b64encode(buf.getvalue()).decode()


def _extract_content(message: dict) -> str:
    """Handle qwen3 reasoning parser: content→"None" string during thinking."""
    c = (message.get("content") or "").strip()
    if c and c.lower() != "none":
        return c
    r = message.get("reasoning_content") or message.get("reasoning") or ""
    # Try to extract final answer after thinking markers
    for marker in ["最终回答", "the answer is", "回答:", "ASSISTANT:"]:
        parts = r.split(marker, 1)
        if len(parts) > 1:
            return parts[1].strip()
    # Try JSON extraction from reasoning
    m = re.search(r'\{[^{}]*"overall_score"[^{}]*\}', r, re.DOTALL)
    if m:
        return m.group()
    return r


def call_vision_llm(prompt: str, image_paths: List[str], model: str = None) -> str:
    """Call local vLLM (qw35-9b) for vision."""
    import urllib.request, urllib.error

    content_parts = []
    for p in image_paths:
        b64 = _resize_encode(p)
        content_parts.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}"}
        })
    content_parts.append({"type": "text", "text": prompt})

    payload = json.dumps({
        "model": model or DEFAULT_MODEL,
        "messages": [{"role": "user", "content": content_parts}],
        "temperature": 0.3, "max_tokens": 1024,
    }).encode("utf-8")

    req = urllib.request.Request(VLLM_URL, data=payload,
        headers={"Content-Type": "application/json"}, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return _extract_content(result["choices"][0]["message"])
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8") if e.fp else ""
        raise RuntimeError(f"Vision API error {e.code}: {body[:200]}")
    except Exception as e:
        raise RuntimeError(f"Vision API call failed: {e}")


COMPARISON_PROMPT = """你是一位专业的动画连续性审查员。请对比以下两张帧图像：

【帧 A】是 shot {shot_a} 的尾帧
【帧 B】是 shot {shot_b} 的首帧

从以下维度评估连续性 (0-10):
1. character_appearance: 角色面部、发型、服装、体型是否一致？
2. scene_environment: 背景、道具、空间布局是否连贯？
3. lighting_color: 光源方向、色温、明暗是否匹配？
4. composition: 机位、视角、画面重心是否合理过渡？

请只输出JSON:
{{"overall_score":0,"character_appearance":0,"scene_environment":0,"lighting_color":0,"composition":0,"issues":[],"severity":"none","suggestion":""}}"""


class ContinuityChecker:

    def __init__(self, projects_root: str = None):
        self.root = Path(projects_root or str(Path.home() / "AIComicFactory" / "projects"))

    def check_pair(self, frame_a: str, frame_b: str, shot_a: int, shot_b: int, model: str = None) -> dict:
        prompt = COMPARISON_PROMPT.format(shot_a=shot_a, shot_b=shot_b)
        try:
            response = call_vision_llm(prompt, [frame_a, frame_b], model=model)
        except RuntimeError as e:
            return {"shot_a": shot_a, "shot_b": shot_b, "overall_score": -1, "error": str(e)}

        # Parse JSON
        return self._parse(response, shot_a, shot_b)

    def _parse(self, response: str, shot_a: int, shot_b: int) -> dict:
        json_str = _extract_json_block(response, key="overall_score")
        try:
            result = json.loads(json_str.strip())
        except json.JSONDecodeError:
            result = _heuristic_continuity(response)
        result["shot_a"] = shot_a
        result["shot_b"] = shot_b
        return result

    def check_project(self, project: str, threshold: int = 70, model: str = None) -> dict:
        pd = self.root / project
        s4_path = pd / "s4_shots.json"
        frames_dir = pd / "s5_frames"

        if not s4_path.exists() or not frames_dir.exists():
            return {"error": "s4_shots.json or s5_frames/ not found"}

        s4 = json.load(open(s4_path))
        shots = []
        for sc in s4.get("scenes", []):
            for sh in sc["shots"]:
                shots.append(sh)

        results, issues = [], []
        for i in range(len(shots) - 1):
            sn_a = shots[i]["shotNumber"]
            sn_b = shots[i + 1]["shotNumber"]
            last_a = frames_dir / f"s{sn_a:02d}_last.png"
            first_b = frames_dir / f"s{sn_b:02d}_first.png"

            if not last_a.exists() or not first_b.exists():
                continue

            same_scene = shots[i].get("sceneNumber", i) == shots[i + 1].get("sceneNumber", i)
            print(f"  {sn_a}->{sn_b}... ", end="", flush=True)
            r = self.check_pair(str(last_a), str(first_b), sn_a, sn_b, model=model)
            r["same_scene"] = same_scene
            results.append(r)

            s = r.get("overall_score", -1)
            if s >= 0:
                print(f"{'✅' if s >= threshold else '⚠️'} {s}/100")
            else:
                print("❌")

            if same_scene and 0 <= s < threshold:
                issues.append(r)

        scores = [r["overall_score"] for r in results if r.get("overall_score", -1) >= 0]
        avg = sum(scores) / len(scores) if scores else 0

        report = {
            "project": project, "pairs_checked": len(results),
            "results": results, "issues": issues,
            "avg_score": round(avg, 1), "threshold": threshold,
            "checked_at": datetime.now(TZ).isoformat(),
        }
        json.dump(report, open(pd / "continuity_report.json", "w"), ensure_ascii=False, indent=2)
        return report

    def generate_summary(self, report: dict) -> str:
        lines = [f"连续性 — {report['project']}"]
        lines.append(f"  检查: {report['pairs_checked']}对 | 均分: {report['avg_score']}/100 | 阈值: {report['threshold']}")
        for r in report["results"]:
            s = r.get("overall_score", -1)
            if s < 0: continue
            sc = "同场景" if r.get("same_scene") else "跨场景"
            icon = "✅" if s >= report["threshold"] else "⚠️"
            lines.append(f"  {icon} {r['shot_a']}->{r['shot_b']} [{sc}]: {s}/100")
            for iss in r.get("issues", [])[:2]:
                lines.append(f"      • {iss}")
        return "\n".join(lines)


def _heuristic_continuity(text: str) -> dict:
    score = 50
    if "完全不同" in text or "completely different" in text.lower():
        score = 10
    elif "不一致" in text or "mismatch" in text.lower() or "不统一" in text:
        score = 30
    elif "连续" in text or "consistent" in text.lower():
        score = 80
    issues = [
        m.group(1).strip()
        for m in re.finditer(r"[•-]\s*(.+?)(?:\n|$)", text)
        if len(m.group(1).strip()) > 2
    ][:10]
    return {
        "overall_score": score,
        "character_appearance": score,
        "scene_environment": score,
        "lighting_color": score,
        "composition": score,
        "issues": issues,
        "severity": "low" if score >= 70 else "medium" if score >= 40 else "high",
        "suggestion": ""
    }
