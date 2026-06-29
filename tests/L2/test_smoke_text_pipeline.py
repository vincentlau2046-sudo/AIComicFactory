"""
L2: 全链路冒烟测试 — 文本管线 (S1→S4)

直接调用千帆 API，验证 prompt → LLM → JSON 解析全链路。
"""

import json
import os
import urllib.request
import urllib.error
import pytest
from pathlib import Path


def get_api_key():
    key = os.environ.get("CODINGPLAN_API_KEY", "")
    if key:
        return key
    try:
        config = json.load(open(os.path.expanduser(
            "~/.openclaw/agents/main/agent/models.json")))
        return config["providers"]["baidu-codingplan"]["apiKey"]
    except Exception:
        return ""

API_KEY = get_api_key()
API_URL = "https://qianfan.baidubce.com/v2/coding/chat/completions"
MODEL = "glm-5.1"

pytestmark = pytest.mark.skipif(
    not API_KEY,
    reason="No API key available for L2 tests"
)


def call_llm(messages: list, model: str = MODEL) -> str:
    """Call baidu-codingplan API."""
    payload = json.dumps({
        "model": model,
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 8192,
    }).encode("utf-8")

    req = urllib.request.Request(
        API_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}",
        },
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=300) as resp:
        result = json.loads(resp.read().decode("utf-8"))
        return result["choices"][0]["message"]["content"]


def extract_json(text: str) -> dict:
    """Robust JSON extraction from LLM response."""
    text = text.strip()

    # Direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # ```json ... ```
    if "```json" in text:
        block = text.split("```json")[1].split("```")[0]
        try:
            return json.loads(block.strip())
        except json.JSONDecodeError:
            pass

    # ``` ... ```
    if "```" in text:
        block = text.split("```")[1].split("```")[0]
        if block.strip().startswith("json"):
            block = block[4:]
        try:
            return json.loads(block.strip())
        except json.JSONDecodeError:
            pass

    # Find balanced { ... } — try progressively larger chunks from start
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        candidate = text[start:end+1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            # Try truncation: find last valid } before a likely truncation point
            for trunc_end in range(len(candidate)-1, max(start, len(candidate)-5000), -1):
                if candidate[trunc_end] == '}':
                    try:
                        return json.loads(candidate[:trunc_end+1])
                    except json.JSONDecodeError:
                        continue
            pass

    # Try to fix common LLM JSON issues: missing quotes around values
    # This is a last resort heuristic
    import re
    # Fix unquoted string values (e.g., "key":value without quotes)
    text_fixed = re.sub(r'"([^"]+)"\s*:\s*([^"\s\[\{][^,\}\]]+)([\s]*[,\}])',
                         r'"\1": "\2"\3', text[start:end+1])
    try:
        return json.loads(text_fixed)
    except json.JSONDecodeError:
        pass

    raise ValueError(f"Could not extract JSON (first 200): {text[:200]}")


SAMPLE_STORY = """少年李慕白站在悬崖边，望着云海翻涌。身后传来脚步声。
"师父，他们来了。"林雪的声音微微颤抖。
李慕白转过身，白衣在风中猎猎作响。他将手中的剑缓缓拔出，剑身映出初升的朝阳。
"既然来了，便战吧。"他说。
远处的山道上，黑衣人影影绰绰，至少百人。"""


class TestS1ScriptParse:
    """S1: 剧本结构化解析"""

    def test_s1_produces_valid_json(self, tmp_path):
        from core.prompt_runner import run_script_parse
        prompt_data = run_script_parse(tmp_path, SAMPLE_STORY)
        response = call_llm(prompt_data["messages"])
        result = extract_json(response)
        assert "title" in result
        assert "scenes" in result
        assert len(result["scenes"]) > 0

    def test_s1_dialogues_preserved(self, tmp_path):
        from core.prompt_runner import run_script_parse
        prompt_data = run_script_parse(tmp_path, SAMPLE_STORY)
        response = call_llm(prompt_data["messages"])
        result = extract_json(response)
        all_dialogues = []
        for scene in result["scenes"]:
            all_dialogues.extend(scene.get("dialogues", []))
        assert len(all_dialogues) >= 2


class TestS2CharacterExtract:
    """S2: 角色提取"""

    def test_s2_extracts_characters(self, tmp_path):
        from core.prompt_runner import run_script_parse, run_character_extract

        prompt_data = run_script_parse(tmp_path, SAMPLE_STORY)
        s1_response = call_llm(prompt_data["messages"])
        s1_result = extract_json(s1_response)

        (tmp_path / "s1_parsed.json").write_text(
            json.dumps(s1_result, ensure_ascii=False, indent=2)
        )

        prompt_data = run_character_extract(tmp_path, parsed_script=s1_result)
        s2_response = call_llm(prompt_data["messages"])
        s2_result = extract_json(s2_response)

        assert "characters" in s2_result
        assert len(s2_result["characters"]) >= 2


class TestS4ShotSplit:
    """S4: 分镜拆分"""

    def test_s4_produces_shots(self, tmp_path):
        from core.prompt_runner import run_script_parse, run_character_extract, run_shot_split

        prompt_data = run_script_parse(tmp_path, SAMPLE_STORY)
        s1_result = extract_json(call_llm(prompt_data["messages"]))

        prompt_data = run_character_extract(tmp_path, parsed_script=s1_result)
        s2_result = extract_json(call_llm(prompt_data["messages"]))

        characters = s2_result.get("characters", [])
        prompt_data = run_shot_split(tmp_path, parsed_script=s1_result, characters=characters)
        s4_result = extract_json(call_llm(prompt_data["messages"]))

        assert "scenes" in s4_result
        total_shots = sum(len(s.get("shots", [])) for s in s4_result["scenes"])
        assert total_shots > 0
