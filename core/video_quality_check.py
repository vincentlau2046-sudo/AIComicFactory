"""
core/video_quality_check.py — 帧质量检查器 (P1-5)

Uses local vLLM (qw35-9b) for vision quality scoring.
Handles qwen3 reasoning parser (content→null, reasoning has response).
"""

import json
import base64
import os
import re
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

TZ = timezone(timedelta(hours=8))

VLLM_URL = "http://localhost:8002/v1/chat/completions"
DEFAULT_MODEL = "vllm_qw35_gptq"


def _extract_json_block(text: str, key: str = "") -> str:
    """Extract JSON object from LLM response, robust to code fences and nested braces."""
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
    if key:
        m = re.search(rf'\{{[^{{}}]*"{re.escape(key)}"[^{{}}]*\}}', text, re.DOTALL)
        if m:
            return m.group()
    return text


def call_vision_llm(prompt: str, image_paths: List[str], model: str = None, api_key: str = None) -> str:
    """Call local vLLM (qw35-9b) for vision. Handles qwen3 reasoning parser."""
    import urllib.request, urllib.error, io
    from PIL import Image

    content_parts = []
    for img_path in image_paths:
        img = Image.open(img_path).resize((384, 216))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=70)
        b64 = base64.b64encode(buf.getvalue()).decode()
        content_parts.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}"}
        })
    content_parts.append({"type": "text", "text": prompt})

    payload = json.dumps({
        "model": model or DEFAULT_MODEL,
        "messages": [{"role": "user", "content": content_parts}],
        "temperature": 0.3, "max_tokens": 512,
    }).encode("utf-8")

    req = urllib.request.Request(VLLM_URL, data=payload,
        headers={"Content-Type": "application/json"}, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            msg = result["choices"][0]["message"]
            content = (msg.get("content") or "").strip()
            if content and content.lower() != "none":
                return content
            return msg.get("reasoning") or msg.get("reasoning_content") or ""
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8") if e.fp else ""
        raise RuntimeError(f"Vision API error {e.code}: {body[:200]}")
    except Exception as e:
        raise RuntimeError(f"Vision API call failed: {e}")


QUALITY_PROMPT = """你是动画质量评分器。
只输出一个JSON对象，不要额外解释。
维度: composition, clarity, character_fidelity, lighting, overall（各0-10整数）。
示例: {"composition":5,"clarity":5,"character_fidelity":5,"lighting":5,"overall":5,"issues":[],"severity":"none","needs_regeneration":false}
"""

def _heuristic_quality(text: str) -> dict:
    """Fallback: extract integer scores from free-form analysis text."""
    dims = {
        "composition": 5,
        "clarity": 5,
        "character_fidelity": 5,
        "lighting": 5,
        "overall": 5,
    }
    for dim in dims:
        m = re.search(rf"{re.escape(dim)}\s*[:：]\s*(\d+)", text, re.IGNORECASE)
        if m:
            dims[dim] = int(m.group(1))
    dims["issues"] = [
        m.group(1).strip()
        for m in re.finditer(r"[•-]\s*(.+?)(?:\n|$)", text)
        if len(m.group(1).strip()) > 2
    ][:10]
    dims["severity"] = "low" if dims["overall"] >= 6 else "medium" if dims["overall"] >= 4 else "high"
    dims["needs_regeneration"] = dims["overall"] < 5
    return dims


class VideoQualityChecker:

    def __init__(self, projects_root: str = None):
        self.root = Path(projects_root or str(Path.home() / "AIComicFactory" / "projects"))

    def check_frame(self, image_path: str, shot_num: int = 0, frame_type: str = "first") -> dict:
        if not Path(image_path).exists():
            return {"error": "File not found", "shot": shot_num}

        try:
            response = call_vision_llm(QUALITY_PROMPT, [image_path])
        except RuntimeError as e:
            return {"shot": shot_num, "overall": -1, "error": str(e)}

        # Parse JSON from response
        json_str = _extract_json_block(response, key="overall")
        try:
            result = json.loads(json_str.strip())
        except json.JSONDecodeError:
            result = _heuristic_quality(response)

        result.setdefault("overall", 5)
        result["shot"] = shot_num
        result["frame_type"] = frame_type
        return result

    def check_project(self, project: str, sample_every: int = 1) -> dict:
        frames_dir = self.root / project / "s5_frames"
        if not frames_dir.exists():
            return {"error": "s5_frames/ not found"}

        frame_files = sorted(frames_dir.glob("s[0-9][0-9]_first.png"))
        results, issues, scored = [], [], []

        for ff in frame_files[::sample_every]:
            sn = int(ff.stem.split("_")[0][1:])
            print(f"  s{sn:02d}_first... ", end="", flush=True)
            r = self.check_frame(str(ff), sn)
            results.append(r)
            o = r.get("overall", -1)
            if o >= 0:
                scored.append(o)
                print(f"{'✅' if o>=6 else '⚠️'} {o}/10")
            else:
                print("❌")
            if r.get("needs_regeneration"):
                issues.append(r)

        avg = sum(scored) / len(scored) if scored else 0
        report = {
            "project": project,
            "frames_checked": len(results),
            "avg_score": round(avg, 1),
            "min": min(scored) if scored else -1,
            "max": max(scored) if scored else -1,
            "results": results,
            "issues": issues,
            "checked_at": datetime.now(TZ).isoformat(),
        }
        p = self.root / project / "quality_report.json"
        json.dump(report, open(p, "w"), ensure_ascii=False, indent=2)
        return report

    def generate_summary(self, report: dict) -> str:
        lines = [f"帧质量 — {report['project']}"]
        lines.append(f"  检查: {report['frames_checked']}帧 | 均分: {report['avg_score']}/10 | 范围: {report.get('min','?')}-{report.get('max','?')}")
        for r in report.get("results", []):
            o = r.get("overall", -1)
            if o < 0: continue
            dims = f"c={r.get('composition','?')} cl={r.get('clarity','?')} ch={r.get('character_fidelity','?')} lt={r.get('lighting','?')}"
            lines.append(f"  {'✅' if o>=6 else '⚠️'} s{r['shot']:02d}: {o}/10 [{dims}]")
        return "\n".join(lines)