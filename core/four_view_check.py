#!/usr/bin/env python3
"""
core/four_view_check.py — S3b 四视角图 VL 质检

职责:
  1. 将 2×2 四视角网格图拆分为四个独立视角
  2. 每个视角单独 VL 质检（角色特征一致性）
  3. 跨视角一致性检查（四个视角必须是同一角色）
  4. 取最低分作为整体 score，低于阈值则标记失败

与 core/character_image_check.py 的关系:
  - 复用 _call_vl / _image_to_base64 / _extract_json 工具函数
  - 使用 core/vl_backend.py 管理 qw35-9b 后端生命周期

用法:
    from core.four_view_check import FourViewChecker
    checker = FourViewChecker(threshold=7.0)
    result = checker.check(grid_image_path, character_data)
    # result["pass"] — 整体是否通过
    # result["scores"] — { "front": 8.5, "left_34": 7.0, "right_34": 9.0, "back": 8.0 }
    # result["overall_score"] — min(scores)
"""

import base64
import json
import re
import subprocess
import urllib.request
from pathlib import Path
from typing import Optional

# ═══════════════════════════════════════════════════════════════════
# Config
# ═══════════════════════════════════════════════════════════════════

VLLM_URL = "http://localhost:8002/v1/chat/completions"
DEFAULT_MODEL = "vllm_qw35_gptq"

# 四视角单视角质检 prompt
# 每个视角单独评估：角色特征是否匹配描述
SINGLE_VIEW_PROMPT = """Output ONLY a JSON object. No explanation.
This is ONE quadrant from a 2x2 four-view character sheet.
Compare this view against the character description.

Description: {description}

View type: {view_type}
Check: face({face}) hair({hair}) clothes({clothing}) body_proportions({body})

JSON: {{"face":{{"s":0,"n":""}},"hair":{{"s":0,"n":""}},"clothes":{{"s":0,"n":""}},"body":{{"s":0,"n":""}},"format":{{"s":0,"n":""}},"overall":0,"summary":""}}"""

# 跨视角一致性 prompt — 传入完整网格图
GRID_CONSISTENCY_PROMPT = """Output ONLY a JSON object. No explanation.
This is a 2x2 four-view character sheet grid.
Check that ALL four views show the SAME character: same face, same hair, same clothing, same body type.

Views: front (top-left), left 3/4 (top-right), right 3/4 (bottom-left), back (bottom-right)

JSON: {{"same_face":true,"same_hair":true,"same_clothes":true,"same_body":true,"left_right_complementary":true,"overall":0,"issues":[]}}"""


def _image_to_base64(image_path: str) -> str:
    """Convert image to base64 data URL."""
    with open(image_path, "rb") as f:
        data = base64.b64encode(f.read()).decode()
    ext = Path(image_path).suffix.lower().replace(".", "")
    mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
            "webp": "image/webp"}.get(ext, "image/png")
    return f"data:{mime};base64,{data}"


def _split_grid(image_path: str, output_dir: str) -> dict:
    """Split a 2x2 four-view grid into 4 individual quadrant images.

    Returns dict with keys: front, left_34, right_34, back
    Each value is the path to the saved quadrant image.
    """
    from PIL import Image

    img = Image.open(image_path)
    w, h = img.size
    qw, qh = w // 2, h // 2

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    quadrants = {
        "front": (0, 0, qw, qh),
        "left_34": (qw, 0, w, qh),
        "right_34": (0, qh, qw, h),
        "back": (qw, qh, w, h),
    }

    result = {}
    for name, box in quadrants.items():
        quadrant = img.crop(box)
        path = out / f"{name}.png"
        quadrant.save(str(path))
        result[name] = str(path)

    return result


def _call_vl(prompt: str, image_path: str, model: str = None, timeout: int = 120) -> str:
    """Call qw35 vision model."""
    b64 = _image_to_base64(image_path)
    payload = {
        "model": model or DEFAULT_MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": b64}},
                {"type": "text", "text": prompt},
            ],
        }],
        "max_tokens": 8192,
        "temperature": 0.0,
    }
    req = urllib.request.Request(
        VLLM_URL,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    resp = json.loads(urllib.request.urlopen(req, timeout=timeout).read())
    msg = resp["choices"][0]["message"]
    content = msg.get("content") or ""
    if content.strip().lower() in ("", "none"):
        content = ""
    reasoning = msg.get("reasoning") or msg.get("reasoning_content") or ""
    result = content.strip() if content.strip() else reasoning.strip()
    if not result:
        raise RuntimeError(f"Empty response from VL model. msg keys: {list(msg.keys())}")
    return result


def _extract_json(text: str) -> dict:
    """Robust JSON extraction from VL response."""
    if not text:
        return {}
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
    m = re.search(r'\{[^{}]*"overall"[^{}]*\}', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    return {}


def _build_short_desc(character: dict) -> str:
    """Build a concise character description for VL prompt."""
    desc = character.get("description", character.get("appearance", ""))
    hint = character.get("visualHint", "")
    anchors = character.get("visualAnchors", {})

    parts = []
    if anchors.get("face"):
        parts.append(f"face: {anchors['face'][:50]}")
    if anchors.get("hair"):
        parts.append(f"hair: {anchors['hair'][:40]}")
    if anchors.get("clothing"):
        parts.append(f"clothes: {anchors['clothing'][:60]}")
    if anchors.get("body"):
        parts.append(f"body: {anchors['body'][:40]}")
    if anchors.get("signature"):
        parts.append(f"signature: {anchors['signature'][:40]}")
    if hint:
        parts.append(f"note: {hint[:30]}")
    if desc and not parts:
        parts.append(desc[:100])

    return " | ".join(parts) if parts else (desc[:200] or "unknown character")


class FourViewChecker:
    """S3b 四视角图 VL 质检器.

    检查流程:
      1. 拆分 2×2 网格为 4 个独立视角
      2. 每个视角单独质检（角色特征匹配）
      3. 整体网格一致性检查（四视角是否为同一角色）
      4. 取最低分为整体 score
    """

    def __init__(self, model: str = None, threshold: float = 7.0):
        self.model = model or DEFAULT_MODEL
        self.threshold = threshold

    def _check_single_view(self, image_path: str, character: dict,
                           view_type: str) -> dict:
        """Check a single quadrant image against character description."""
        short_desc = _build_short_desc(character)
        anchors = character.get("visualAnchors", {})

        prompt = SINGLE_VIEW_PROMPT.format(
            description=short_desc,
            view_type=view_type,
            face=anchors.get("face", "N/A")[:60],
            hair=anchors.get("hair", "N/A")[:60],
            clothing=anchors.get("clothing", "N/A")[:80],
            body=anchors.get("body", "N/A")[:60],
        )

        try:
            response = _call_vl(prompt, image_path, self.model)
            result = _extract_json(response)
        except Exception as e:
            return {
                "score": 0.0,
                "pass": False,
                "summary": f"VL call failed: {e}",
                "dimensions": {},
                "raw_response": None,
            }

        dims = ["face", "hair", "clothes", "body", "format"]
        dim_scores = []
        for d in dims:
            val = result.get(d, {})
            if isinstance(val, dict):
                dim_scores.append(val.get("s", 0))
            else:
                dim_scores.append(0)

        # Normalize: 5 dims × 2 = 10 max → score / 10 * 10 = score
        raw_total = sum(dim_scores)
        score = round(raw_total * 10 / 10, 1)  # Already 0-10 range
        if score > 10:
            score = 10.0

        return {
            "score": score,
            "pass": score >= self.threshold,
            "summary": result.get("summary", ""),
            "dimensions": {d: result.get(d, {}) for d in dims},
            "raw_response": response,
        }

    def _check_grid_consistency(self, grid_image_path: str, character: dict) -> dict:
        """Check that all 4 views in the grid show the same character."""
        try:
            response = _call_vl(GRID_CONSISTENCY_PROMPT, grid_image_path, self.model)
            result = _extract_json(response)
        except Exception as e:
            return {
                "score": 0.0,
                "pass": False,
                "summary": f"Grid consistency check failed: {e}",
                "raw_response": None,
            }

        # Score based on consistency dimensions
        checks = ["same_face", "same_hair", "same_clothes", "same_body",
                   "left_right_complementary"]
        matches = 0
        issues = []
        for chk in checks:
            if result.get(chk, False):
                matches += 1
            else:
                issues.append(f"{chk} mismatch")

        # 5 checks × 2 = 10
        score = round(matches * 10 / 5, 1)
        if score > 10:
            score = 10.0

        return {
            "score": score,
            "pass": score >= self.threshold,
            "summary": f"{matches}/5 consistency checks passed",
            "issues": result.get("issues", issues),
            "raw_response": response,
        }

    def check(self, grid_image_path: str, character: dict,
              temp_dir: str = None) -> dict:
        """
        质检四视角网格图。

        Args:
            grid_image_path: 2x2 四视角网格图路径
            character: S2 角色数据
            temp_dir: 临时目录（用于存放拆分后的单视角图）

        Returns:
            {
                "character": str,
                "pass": bool,
                "overall_score": float,       # min of all view scores
                "scores": {"front": x, "left_34": x, "right_34": x, "back": x},
                "consistency_score": float,
                "view_results": {view_name: result_dict, ...},
                "consistency_result": dict,
                "summary": str,
                "needs_regeneration": bool,
            }
        """
        name = character.get("name", "?")
        if temp_dir is None:
            temp_dir = str(Path(grid_image_path).parent / "_tmp_quadrants")

        # Step 1: Split grid
        quadrants = _split_grid(grid_image_path, temp_dir)

        # Step 2: Check each view independently
        view_results = {}
        scores = {}
        for view_name, quad_path in quadrants.items():
            view_results[view_name] = self._check_single_view(
                quad_path, character, view_name
            )
            scores[view_name] = view_results[view_name]["score"]

        # Step 3: Check grid consistency
        consistency_result = self._check_grid_consistency(
            grid_image_path, character
        )

        # Step 4: Overall score = min of all view scores
        view_scores = list(scores.values())
        overall_score = min(view_scores) if view_scores else 0.0

        passed = (overall_score >= self.threshold and
                  consistency_result["pass"])

        # Build issue list
        all_issues = []
        for vn, vr in view_results.items():
            if not vr["pass"]:
                all_issues.append(f"{vn}: {vr['summary'][:80]}")
        if not consistency_result["pass"]:
            for iss in consistency_result.get("issues", []):
                all_issues.append(f"consistency: {iss}")

        summary = (
            f"Views: front={scores['front']} left34={scores['left_34']} "
            f"right34={scores['right_34']} back={scores['back']} | "
            f"consistency={consistency_result['score']}/10 | "
            f"overall={overall_score}/10"
        )

        return {
            "character": name,
            "pass": passed,
            "overall_score": overall_score,
            "scores": scores,
            "consistency_score": consistency_result["score"],
            "view_results": view_results,
            "consistency_result": consistency_result,
            "summary": summary,
            "needs_regeneration": not passed,
            "issues": all_issues,
        }

    def ensure_backend(self, auto_start: bool = True) -> bool:
        """Ensure VL backend is available (reuse vl_backend singleton)."""
        from core.vl_backend import get_vl_backend
        backend = get_vl_backend()
        return backend.ensure_available(auto_start=auto_start)

    def release_backend(self) -> None:
        """Release VL backend after all checks are done."""
        from core.vl_backend import get_vl_backend
        backend = get_vl_backend()
        backend.stop()
