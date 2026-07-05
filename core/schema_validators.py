"""
core/schema_validators.py — JSON Schema 验证门控

验证管线各阶段输出是否符合预期 schema。
验证失败记录警告，不阻塞后续 stage。
"""
import logging

logger = logging.getLogger(__name__)


def validate_s1_output(data: dict) -> list[str]:
    """Validate S1 (script_parse) output.

    Checks:
    - Top-level has 'scenes' array
    - Each scene has 'dialogues' list
    - Each dialogue has 'character' and 'text'

    Returns list of error messages (empty = valid).
    """
    errors: list[str] = []

    scenes = data.get("scenes")
    if not isinstance(scenes, list):
        errors.append("Missing top-level 'scenes' array")
        return errors

    for i, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            errors.append(f"scenes[{i}] is not a dict")
            continue

        dialogues = scene.get("dialogues")
        if not isinstance(dialogues, list):
            errors.append(f"scenes[{i}] missing 'dialogues' list")
            continue

        for j, d in enumerate(dialogues):
            if not isinstance(d, dict):
                errors.append(f"scenes[{i}].dialogues[{j}] is not a dict")
                continue
            if not d.get("character"):
                errors.append(f"scenes[{i}].dialogues[{j}] missing 'character'")
            if not d.get("text"):
                errors.append(f"scenes[{i}].dialogues[{j}] missing 'text'")

    return errors


def validate_s2_output(data: dict) -> list[str]:
    """Validate S2 (character_extract) output.

    Checks:
    - Top-level has 'characters' array
    - Each character has 'name', 'description', 'visualHint'

    Returns list of error messages (empty = valid).
    """
    errors: list[str] = []

    characters = data.get("characters")
    if not isinstance(characters, list):
        errors.append("Missing top-level 'characters' array")
        return errors

    for i, c in enumerate(characters):
        if not isinstance(c, dict):
            errors.append(f"characters[{i}] is not a dict")
            continue
        if not c.get("name"):
            errors.append(f"characters[{i}] missing 'name'")
        if not c.get("description"):
            errors.append(f"characters[{i}] missing 'description'")
        if not c.get("visualHint"):
            errors.append(f"characters[{i}] missing 'visualHint'")

    return errors


def validate_s4_output(data: dict) -> list[str]:
    """Validate S4 (shot_split) output.

    Checks:
    - Shots array (scenes[].shots[] or flat shots[])
    - Each shot has 'prompt', 'motionScript'

    Returns list of error messages (empty = valid).
    """
    errors: list[str] = []

    # Collect shots from nested (scenes[].shots[]) or flat (shots[]) format
    shots: list = []
    if "scenes" in data and isinstance(data["scenes"], list):
        for sc in data["scenes"]:
            if isinstance(sc, dict) and "shots" in sc and isinstance(sc["shots"], list):
                shots.extend(sc["shots"])
    elif "shots" in data and isinstance(data["shots"], list):
        shots.extend(data["shots"])

    if not shots:
        errors.append("No 'shots' array found (neither under 'scenes[].shots[]' nor flat 'shots[]')")
        return errors

    for i, sh in enumerate(shots):
        if not isinstance(sh, dict):
            errors.append(f"shots[{i}] is not a dict")
            continue
        if not sh.get("prompt"):
            errors.append(f"shots[{i}] missing 'prompt'")
        if not sh.get("motionScript"):
            errors.append(f"shots[{i}] missing 'motionScript'")

    return errors
