#!/usr/bin/env python3
"""
scripts/s4b_keyframe_assets.py — Stage 4b: 关键帧资产 (独立 Stage)

从 s4_shots.json + s2_characters.json 生成每个 shot 的首帧/尾帧 prompt。
D5 决策: S4b 独立于 S4，可单独重跑。

产出:
  projects/{project}/s4b_keyframe_assets.json
  {
    "shots": [
      {
        "shotNumber": 1,
        "startFrame": { "prompt": "...", "ref_characters": ["老周"] },
        "endFrame":   { "prompt": "...", "ref_characters": ["老周", "林姐"] }
      }
    ]
  }

用法:
    python scripts/s4b_keyframe_assets.py --project last_bento
    python scripts/s4b_keyframe_assets.py --project last_bento --shot 1
"""

import json, sys, argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.stdout.reconfigure(line_buffering=True)

from core.state_manager import get_state_manager
from prompts.defaults.frame_generate_first import build_full_prompt as build_first_prompt
from prompts.defaults.frame_generate_last import build_full_prompt as build_last_prompt

# Costume helpers (shared with S5)
import s5_frame_generate
_resolve_shot_costumes = s5_frame_generate._resolve_shot_costumes
_build_costume_consistency = s5_frame_generate._build_costume_consistency
from prompts.defaults.character_image import build_flux_ref_prompt


# ═══════════════════════════════════════════════════════════════════
# Prompt builders
# ═══════════════════════════════════════════════════════════════════

def _build_scene_description(scene: dict, color_palette: str = "") -> str:
    """从 scene 数据构建场景环境描述."""
    parts = []
    setting = scene.get("setting", "")
    mood = scene.get("mood", "")
    tod = scene.get("timeOfDay", "")
    if setting:
        parts.append(f"场景: {setting}")
    if tod:
        parts.append(f"时间: {tod}")
    if mood:
        parts.append(f"氛围: {mood}")
    if color_palette:
        parts.append(f"\n\nGLOBAL COLOR PALETTE (mandatory): {color_palette}. All frames must adhere to this color scheme.")
    return ", ".join(parts) if parts else "Unspecified setting"


def _build_character_descriptions(characters: list, shot_char_names: list) -> str:
    """构建角色描述文本. 视觉签名前置 → 最大化 primacy effect."""
    lines = []
    for cn in shot_char_names:
        for c in characters:
            if c["name"] == cn:
                hint = c.get("visualHint", "")
                desc = c.get("description", c.get("appearance", ""))
                anchors = c.get("visualAnchors", {})

                sig_parts = []
                for dim in ["face", "hair", "body", "clothing"]:
                    v = anchors.get(dim, "").strip()
                    if v and v != "无特殊":
                        sig_parts.append(v)
                visual_sig = "【" + " | ".join(sig_parts) + "】" if sig_parts else ""

                cp = c.get("colorPalette", "")
                if cp:
                    visual_sig += f" 配色:[{cp}]"

                line = f"{visual_sig} {cn}"
                if hint:
                    line += f"({hint})"
                line += f": {desc[:400]}"

                ps = c.get("performanceStyle", "")
                if ps:
                    line += f"\n  姿势约束: {ps[:200]}"

                lines.append(line)
                break
        else:
            lines.append(f"角色 {cn}: 无详细描述")
    return "\n\n".join(lines)


def _build_composition_suffix(shot: dict, chars_in_shot: list, characters: list,
                               color_palette: str = "") -> str:
    """构图指导 + 焦点 + 景深 + 角色身高 + 色板."""
    parts = []

    comp = shot.get("compositionGuide", "")
    if comp:
        parts.append(f"{comp.replace('_', ' ')} composition")

    focal = shot.get("focalPoint", "")
    if focal:
        parts.append(f"focus on {focal}")

    dof = shot.get("depthOfField", "")
    if dof == "shallow":
        parts.append("shallow depth of field, bokeh background")
    elif dof == "deep":
        parts.append("deep focus, everything sharp")

    if color_palette:
        parts.append(f"\nGLOBAL COLOR PALETTE (mandatory): {color_palette}. All frames must adhere to this color scheme.")

    if len(chars_in_shot) > 1:
        height_info = []
        for cn in chars_in_shot:
            for c in characters:
                if c["name"] == cn and c.get("heightCm"):
                    height_info.append((c["name"], c["heightCm"], c.get("bodyType", "average")))
                    break
        if height_info:
            height_info.sort(key=lambda x: x[1], reverse=True)
            height_text = ", ".join(
                f"{name}: {h}cm ({bt})" for name, h, bt in height_info
            )
            parts.append(f"Character heights: {height_text}. Maintain correct relative proportions")

    suffix = ", ".join([p for p in parts if not p.startswith('\n')])
    for p in parts:
        if p.startswith('\n'):
            suffix += p
    if suffix and not suffix.startswith('\n'):
        return ", " + suffix
    return suffix


def _build_character_ref_prompts(characters: list, shot_char_names: list) -> dict:
    """为每个角色构建 Flux Dev 风格参考图 prompt (用于 S3)."""
    result = {}
    for cn in shot_char_names:
        for c in characters:
            if c["name"] == cn:
                result[cn] = build_flux_ref_prompt(
                    character_name=c["name"],
                    character_description=c.get("description", c.get("appearance", "")),
                    visual_hint=c.get("visualHint", ""),
                    visual_anchors=c.get("visualAnchors", {}),
                )
                break
    return result


# ═══════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════

def main():
    p = argparse.ArgumentParser(description="S4b: 关键帧资产生成 (独立 Stage)")
    p.add_argument("--project", "-P", required=True)
    p.add_argument("--shot", "-s", type=int, help="Specific shot only")
    args = p.parse_args()

    pd = Path(__file__).parent.parent / "projects" / args.project
    s4_path = pd / "s4_shots.json"
    s2_path = pd / "s2_characters.json"

    if not s4_path.exists():
        print(f"ERROR: {s4_path} not found. Run S4 first.")
        sys.exit(1)
    if not s2_path.exists():
        print(f"ERROR: {s2_path} not found. Run S2 first.")
        sys.exit(1)

    s4 = json.load(open(s4_path))
    s2 = json.load(open(s2_path))

    # ── S4b 审核: 分镜时长校验 ──
    MAX_SHOT_DURATION = 6.0  # 秒
    scenes = s4.get("scenes", [])
    all_shots = []
    if scenes:
        for sc in scenes:
            for sh in sc["shots"]:
                all_shots.append(sh)
    else:
        all_shots = s4.get("shots", [])

    over_limit = [sh for sh in all_shots if sh.get("duration", 5.0) > MAX_SHOT_DURATION]
    if over_limit:
        print(f"⚠️ S4b 审核: {len(over_limit)}/{len(all_shots)} shots 超过 {MAX_SHOT_DURATION}s 限制，自动截断:")
        for sh in over_limit:
            n = sh["shotNumber"]
            dur = sh.get("duration", 5.0)
            sh["duration"] = MAX_SHOT_DURATION
            print(f"  s{n:02d}: {dur}s → {MAX_SHOT_DURATION}s")
        # 写回修正后的 s4_shots.json
        s4_path.write_text(json.dumps(s4, ensure_ascii=False, indent=2))
        print(f"  已自动修正并写回 s4_shots.json")
    else:
        print(f"✅ S4b 审核: {len(all_shots)} shots 全部 ≤{MAX_SHOT_DURATION}s")

    chars = s2["characters"]
    project_color_palette = s2.get("colorPalette", "") or s4.get("colorPalette", "")

    # Flatten shots
    scenes = s4.get("scenes", [])
    shots = []
    if scenes:
        for sc in scenes:
            for sh in sc["shots"]:
                shots.append((sc, sh))
    else:
        for sh in s4.get("shots", []):
            shots.append(({}, sh))

    if args.shot:
        shots = [(sc, sh) for sc, sh in shots if sh["shotNumber"] == args.shot]

    sm = get_state_manager()
    sm.mark_running(args.project, "s4b_keyframe_assets", remaining=len(shots))

    assets = []
    for i, (sc, sh) in enumerate(shots):
        n = sh["shotNumber"]
        chars_in = sh.get("characters", [])

        scene_desc = _build_scene_description(sc, color_palette=project_color_palette)
        char_desc = _build_character_descriptions(chars, chars_in)
        comp_suffix = _build_composition_suffix(sh, chars_in, chars, project_color_palette)

        # Build first frame prompt — prefer startFrameDesc (中文散文), fallback to prompt
        start_desc = sh.get("startFrameDesc", sh.get("prompt", sh.get("description", "")))
        first_prompt = build_first_prompt(
            scene_description=scene_desc,
            start_frame_desc=start_desc,
            character_descriptions=char_desc,
        )
        if comp_suffix:
            first_prompt += comp_suffix

        # Build last frame prompt — prefer endFrameDesc (中文散文), fallback to prompt
        end_desc = sh.get("endFrameDesc", sh.get("prompt", sh.get("description", "")))
        last_prompt = build_last_prompt(
            scene_description=scene_desc,
            end_frame_desc=end_desc,
            character_descriptions=char_desc,
        )
        if comp_suffix:
            last_prompt += comp_suffix

        # Build character ref prompts for this shot
        ref_prompts = _build_character_ref_prompts(chars, chars_in)

        asset = {
            "shotNumber": n,
            "sceneNumber": sh.get("sceneNumber", sc.get("sceneNumber", 0)),
            "startFrame": {
                "prompt": first_prompt,
                "ref_characters": chars_in,
                "cameraDirection": sh.get("cameraDirection", ""),
                "compositionGuide": sh.get("compositionGuide", ""),
                "focalPoint": sh.get("focalPoint", ""),
                "depthOfField": sh.get("depthOfField", "medium"),
            },
            "endFrame": {
                "prompt": last_prompt,
                "ref_characters": chars_in,
                "cameraDirection": sh.get("cameraDirection", ""),
                "compositionGuide": sh.get("compositionGuide", ""),
                "focalPoint": sh.get("focalPoint", ""),
                "depthOfField": sh.get("depthOfField", "medium"),
            },
            "characterRefPrompts": ref_prompts,
        }
        assets.append(asset)
        print(f"  Shot {n:2d} ({','.join(chars_in)}) → first={len(first_prompt)}c last={len(last_prompt)}c")

    # Save output
    output = {
        "project": args.project,
        "source": "s4_shots.json + s2_characters.json",
        "totalShots": len(assets),
        "shots": assets,
    }

    out_path = pd / "s4b_keyframe_assets.json"
    with open(out_path, "w") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    sm.mark_completed(args.project, "s4b_keyframe_assets", total=len(assets))
    print(f"\n{'='*60}")
    print(f"S4b Complete: {len(assets)} shots, {out_path}")


if __name__ == "__main__":
    main()
