#!/usr/bin/env python3
"""
scripts/dialogue_timing.py — 对白时间轴分析 (P0-6)

使用 qw35-9b (vllm_qw35_gptq @ localhost:8002) 的多模态能力，
分析 shot 首帧/尾帧图片，判断每句对白的 startRatio 和 endRatio。

原理: LLM 观察画面中角色的口型/表情/动作，结合对白文本，
推导每句话在 shot 时间线中的合理位置。

用法:
    python scripts/dialogue_timing.py --project last_bento
    python scripts/dialogue_timing.py --project last_bento --shot 1
"""

import json
import sys
import argparse
import base64
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

# ═══════════════════════════════════════════════════════════════════
# Config
# ═══════════════════════════════════════════════════════════════════

VLLM_URL = "http://localhost:8002/v1/chat/completions"
MODEL_NAME = "vllm_qw35_gptq"  # Qwen3.5-9B GPTQ @ edge-llm
DEFAULT_DURATION = 5.0  # fallback duration if shot has no explicit duration


# ═══════════════════════════════════════════════════════════════════
# Image encoding
# ═══════════════════════════════════════════════════════════════════

def encode_image_base64(image_path: str) -> str:
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def build_image_content(image_paths: list) -> list:
    """Build content parts for vision API with inline images."""
    parts = []
    for p in image_paths:
        if Path(p).exists():
            b64 = encode_image_base64(p)
            ext = Path(p).suffix.lstrip(".") or "png"
            parts.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/{ext};base64,{b64}"}
            })
    return parts


# ═══════════════════════════════════════════════════════════════════
# Qwen3.5 Vision call
# ═══════════════════════════════════════════════════════════════════

ANALYSIS_PROMPT_TEMPLATE = """你是一位专业的动画剪辑师。我正在制作一部动画短片，需要对镜头中的对白进行精确的时间轴定位。

我会提供:
1. 这个 shot 的首帧和尾帧图像
2. shot 的总时长 ({duration}s)
3. 这个 shot 的所有对白列表

请分析每句对白在 shot 时间线中的合理位置，输出 startRatio 和 endRatio (0.0-1.0)。

分析依据:
- 首帧: shot 开始时的画面状态——角色姿态、表情、口型
- 尾帧: shot 结束时的画面状态
- 对白内容: 每句话的长度、情绪、节奏
- 画面线索: 角色的口型开合程度、表情张力、身体姿态是否暗示说话

规则:
- 每句对白的 startRatio/endRatio 必须在 0.0-1.0 之间
- endRatio 必须大于 startRatio
- 多条对白的区间不能重叠（除非是同时说话）
- 如果首帧中角色已经张着嘴巴，对白应从开头附近开始
- 如果尾帧中角色表情平静/嘴巴闭合，对白应在结尾之前完成
- 长对白分配更大的区间，短对白分配更小的区间
- 对白之间的停顿至少 0.05-0.1

对白列表:
{dialogues_text}

请以 JSON 格式输出（不要输出其他内容）:
```json
[
  {{"character": "角色名", "startRatio": 0.0, "endRatio": 0.5}},
  {{"character": "角色名", "startRatio": 0.6, "endRatio": 1.0}}
]
```"""


def call_vision_llm(prompt: str, image_paths: list, timeout: int = 120) -> str:
    """Call vllm_qw35_gptq with images."""
    import urllib.request
    import urllib.error

    content_parts = build_image_content(image_paths)
    content_parts.append({"type": "text", "text": prompt})

    payload = json.dumps({
        "model": MODEL_NAME,
        "messages": [{"role": "user", "content": content_parts}],
        "temperature": 0.2,
        "max_tokens": 1024,
    }).encode("utf-8")

    headers = {"Content-Type": "application/json"}

    req = urllib.request.Request(VLLM_URL, data=payload, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result["choices"][0]["message"].get("content", "")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Vision API error {e.code}: {e.read().decode('utf-8')[:200]}")
    except Exception as e:
        raise RuntimeError(f"Vision API call failed: {e}")


# ═══════════════════════════════════════════════════════════════════
# Dialogue timing analysis
# ═══════════════════════════════════════════════════════════════════

def _equal_distribute(dialogues: list, duration: float) -> list:
    """Fallback: 对白均匀分布在 duration 内."""
    n = len(dialogues)
    if n == 0:
        return []
    gap = 0.05  # 停顿间隔
    total_gap = (n - 1) * gap
    available = duration - total_gap
    segment = available / n
    results = []
    offset = 0.0
    for d in dialogues:
        start = offset / duration
        end = (offset + segment) / duration
        results.append({
            "character": d.get("character", d.get("characterName", "")),
            "text": d.get("text", ""),
            "startRatio": round(start, 3),
            "endRatio": round(end, 3),
        })
        offset += segment + gap
    return results


def analyze_shot_dialogues(
    shot: dict,
    project_dir: Path,
    use_vision: bool = True,
) -> list:
    """
    分析一个 shot 的所有对白时间轴。

    参数:
        shot: s4_shots.json 中的 shot 对象
        project_dir: 项目目录
        use_vision: 是否使用 qw35-9b vision 分析 (False=fallback均匀分布)

    返回:
        带 startRatio/endRatio 的 dialogues 列表
    """
    dialogues = shot.get("dialogues", [])
    if not dialogues:
        return []

    duration = shot.get("duration", DEFAULT_DURATION)
    shot_num = shot["shotNumber"]

    # Collect frame images
    frame_dir = project_dir / "s5_frames"
    image_paths = []
    first_frame = frame_dir / f"s{shot_num:02d}_first.png"
    last_frame = frame_dir / f"s{shot_num:02d}_last.png"
    if first_frame.exists():
        image_paths.append(str(first_frame))
    if last_frame.exists():
        image_paths.append(str(last_frame))

    if not use_vision or not image_paths:
        return _equal_distribute(dialogues, duration)

    # Build dialogue text for prompt
    dialogue_lines = []
    for i, d in enumerate(dialogues):
        ch = d.get("character", d.get("characterName", "?"))
        txt = d.get("text", "")
        dialogue_lines.append(f"  {i+1}. {ch}: \"{txt}\"")
    dialogues_text = "\n".join(dialogue_lines)

    prompt = ANALYSIS_PROMPT_TEMPLATE.format(
        duration=duration,
        dialogues_text=dialogues_text,
    )

    try:
        response = call_vision_llm(prompt, image_paths)
        # Parse JSON from response
        json_str = response
        if "```json" in response:
            json_str = response.split("```json")[1].split("```")[0]
        elif "```" in response:
            json_str = response.split("```")[1].split("```")[0]

        result = json.loads(json_str.strip())

        # 校验+修正 Vision LLM 输出:
        # 1. 0 <= startRatio < endRatio <= 1
        # 2. 同一 shot 内 intervals 不重叠
        prev_er = 0.0
        for i, d in enumerate(dialogues):
            if i < len(result):
                sr = result[i].get("startRatio", 0.0)
                er = result[i].get("endRatio", 1.0)
            else:
                sr, er = 0.0, 1.0

            # clamp [0, 1]
            sr = max(0.0, min(1.0, sr))
            er = max(0.0, min(1.0, er))

            # sr < er
            if sr >= er:
                sr, er = 0.0, 1.0

            # 不与前一个 interval 重叠
            if sr < prev_er:
                sr = prev_er
            if sr >= er:  # 修正后仍然无效，回退
                sr, er = 0.0, 1.0

            d["startRatio"] = round(sr, 4)
            d["endRatio"] = round(er, 4)
            prev_er = er

        return dialogues
    except Exception as e:
        print(f"  ⚠️ Vision analysis failed for shot {shot_num}: {e}")
        print(f"     Falling back to equal distribution")
        return _equal_distribute(dialogues, duration)


def analyze_project(project: str, vision: bool = True) -> dict:
    """Analyze all shots in a project."""
    pd = Path(__file__).parent.parent / "projects" / project
    s4_path = pd / "s4_shots.json"

    if not s4_path.exists():
        return {"error": f"{s4_path} not found"}

    s4 = json.load(open(s4_path))
    scenes = s4.get("scenes", [])
    total_shots = 0
    total_dialogues = 0
    analyzed = 0

    for sc in scenes:
        for sh in sc["shots"]:
            total_shots += 1
            dialogues = sh.get("dialogues", [])
            if not dialogues:
                continue
            total_dialogues += len(dialogues)
            shot_num = sh["shotNumber"]
            print(f"  Shot {shot_num}: {len(dialogues)} dialogues...", end=" ", flush=True)

            result = analyze_shot_dialogues(sh, pd, use_vision=vision)
            sh["dialogues"] = result
            analyzed += 1
            vision_mode = "vision" if vision else "uniform"
            print(f"done ({vision_mode})")

    # Save updated s4
    with open(s4_path, "w") as f:
        json.dump(s4, f, ensure_ascii=False, indent=2)

    return {
        "project": project,
        "total_shots": total_shots,
        "shots_with_dialogues": analyzed,
        "total_dialogues": total_dialogues,
        "mode": "vision" if vision else "uniform",
    }


# ═══════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════

def main():
    p = argparse.ArgumentParser(description="对白时间轴分析 (qw35-9b vision)")
    p.add_argument("--project", "-P", required=True, help="项目名")
    p.add_argument("--shot", "-s", type=int, help="只分析指定 shot")
    p.add_argument("--no-vision", action="store_true", help="不使用 vision 分析(均匀分布回退)")
    p.add_argument("--dry-run", action="store_true", help="仅打印，不修改文件")
    args = p.parse_args()

    pd = Path(__file__).parent.parent / "projects" / args.project
    s4_path = pd / "s4_shots.json"
    if not s4_path.exists():
        print(f"Error: {s4_path} not found")
        sys.exit(1)

    if args.dry_run:
        s4 = json.load(open(s4_path))
        scenes = s4.get("scenes", [])
        dialogues_count = 0
        for sc in scenes:
            for sh in sc["shots"]:
                dialogues_count += len(sh.get("dialogues", []))
        print(f"Project: {args.project}")
        print(f"Shots: {sum(len(sc['shots']) for sc in scenes)}")
        print(f"Dialogues: {dialogues_count}")
        print(f"Mode: {'uniform' if args.no_vision else 'vision (vllm_qw35_gptq)'}")
        return

    use_vision = not args.no_vision
    result = analyze_project(args.project, vision=use_vision)

    print(f"\n{'='*60}")
    print(f"Dialogue timing complete: {args.project}")
    print(f"  Shots analyzed: {result['shots_with_dialogues']}/{result['total_shots']}")
    print(f"  Total dialogues: {result['total_dialogues']}")
    print(f"  Mode: {result['mode']}")


if __name__ == "__main__":
    main()