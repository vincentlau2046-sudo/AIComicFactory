"""
core/llm_client.py — 统一 LLM 调用客户端

从 AICB 的 callAgentStream() 适配。
支持 baidu-codingplan API（OpenAI 兼容格式）。

用法:
    from core.llm_client import LLMClient
    client = LLMClient()
    result = client.chat(system="你是一位...", user="请生成...")
"""

import json
import logging
import os
import time
import urllib.request
import urllib.error
from typing import Dict, List, Optional, Any
from pathlib import Path


# ═══════════════════════════════════════════════════════════════════
# Config
# ═══════════════════════════════════════════════════════════════════

CODINGPLAN_URL = "https://qianfan.baidubce.com/v2/coding/chat/completions"

# Model aliases (match OpenClaw config)
MODEL_ALIASES = {
    "DEEPSEEK_FLASH": "deepseek-v4-flash",
    "DEEPSEEK_PRO": "deepseek-v4-pro",
    "ERNIE_45": "ernie-4.5-turbo-20260402",
    "GLM5": "glm-5",
    "PRIMARY": "glm-5.1",
}

DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_TEMPERATURE = 0.7
DEFAULT_MAX_TOKENS = 16384

# Retry / degradation
RETRY_DELAYS = [5, 15, 30]          # exponential backoff schedule (seconds)
MAX_RETRIES = 3
DEGRADATION_THRESHOLD = 5           # consecutive failures before graceful degradation

logger = logging.getLogger(__name__)


def _get_api_key() -> str:
    """Get API key from OpenClaw config or environment."""
    # 1. Environment variable
    key = os.environ.get("CODINGPLAN_API_KEY", "")
    if key:
        return key

    # 2. OpenClaw models.json
    models_path = Path.home() / ".openclaw" / "agents" / "main" / "agent" / "models.json"
    if models_path.exists():
        try:
            d = json.loads(models_path.read_text())
            providers = d.get("providers", {})
            bp = providers.get("baidu-codingplan", {})
            key = bp.get("apiKey", "")
            if key:
                return key
        except Exception:
            pass

    raise RuntimeError(
        "No API key found. Set CODINGPLAN_API_KEY env or configure OpenClaw baidu-codingplan provider."
    )


# ═══════════════════════════════════════════════════════════════════
# Client
# ═══════════════════════════════════════════════════════════════════

class LLMClient:
    """Unified LLM client for AIComicFactory pipeline stages."""

    def __init__(self, api_key: str = None, model: str = None,
                 degradation_threshold: int = DEGRADATION_THRESHOLD):
        self.api_key = api_key or _get_api_key()
        self.model = model or DEFAULT_MODEL
        self.base_url = CODINGPLAN_URL
        self._consecutive_failures = 0
        self._degradation_threshold = degradation_threshold

    def _resolve_model(self, model: str = None) -> str:
        """Resolve model alias to actual model ID."""
        m = model or self.model
        return MODEL_ALIASES.get(m, m)

    def _is_degraded(self) -> bool:
        """Check whether the client has entered degraded mode."""
        return self._consecutive_failures >= self._degradation_threshold

    def _extract_response(self, result: dict, resolved: str) -> str:
        """Extract assistant content from API response, handling thinking models."""
        msg = result["choices"][0]["message"]
        content = msg.get("content", "") or ""

        # Handle thinking models (GLM-5, DeepSeek-R1 etc.)
        if not content:
            reasoning = msg.get("reasoning_content", "") or ""
            if reasoning:
                content = reasoning

        # Log usage
        usage = result.get("usage", {})
        total = usage.get("total_tokens", 0)
        if total > 0:
            print(f"  [LLM] {resolved} → {total} tokens")
        return content

    def chat(
        self,
        system: str = "",
        user: str = "",
        model: str = None,
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        response_format: Optional[Dict] = None,
    ) -> str:
        """
        Send a chat completion request and return the assistant's content.

        Args:
            system: System prompt
            user: User message
            model: Model name or alias
            temperature: Sampling temperature
            max_tokens: Max output tokens
            response_format: Optional {"type": "json_object"} for structured output

        Returns:
            Assistant's text response
        """
        resolved = self._resolve_model(model)

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})

        payload = {
            "model": resolved,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            payload["response_format"] = response_format

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        data = json.dumps(payload).encode("utf-8")

        # Retry with exponential backoff for transient errors
        last_error = None
        for attempt in range(MAX_RETRIES):
            req = urllib.request.Request(self.base_url, data=data, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=300) as resp:
                    result = json.loads(resp.read().decode("utf-8"))
                    self._consecutive_failures = 0  # reset on success
                    return self._extract_response(result, resolved)
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8") if e.fp else ""
                last_error = RuntimeError(f"LLM API error {e.code}: {body[:500]}")
                # Non-4xx errors are potentially transient
                if 400 <= e.code < 500 and e.code not in (429, 408, 409):
                    # Client error (auth, bad request, not found) — no retry
                    break
                # 429 rate-limit, 408/409 timeout/conflict, 5xx server errors → retry
            except (urllib.error.URLError, OSError, TimeoutError) as e:
                last_error = RuntimeError(f"LLM API call failed: {e}")
            except Exception as e:
                # Non-retryable
                self._consecutive_failures += 1
                if self._is_degraded():
                    logger.warning("LLM degradation: consecutive_failures=%d, returning empty",
                                   self._consecutive_failures)
                    return ""
                raise RuntimeError(f"LLM API call failed: {e}")

            # Backoff before next retry
            if attempt < MAX_RETRIES - 1:
                wait = RETRY_DELAYS[attempt] if attempt < len(RETRY_DELAYS) else RETRY_DELAYS[-1]
                import sys as _sys
                print(f"  [API retry {attempt+1}/{MAX_RETRIES}] waiting {wait}s: {last_error}",
                      file=_sys.stderr)
                time.sleep(wait)

        # All retries exhausted
        self._consecutive_failures += 1
        if self._is_degraded():
            logger.warning("LLM degradation: consecutive_failures=%d, returning empty",
                           self._consecutive_failures)
            return ""
        raise last_error or RuntimeError("LLM API call failed (unknown error)")

    def chat_json(
        self,
        system: str = "",
        user: str = "",
        model: str = None,
        temperature: float = 0.3,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        max_retries: int = 3,
    ) -> dict:
        """
        Send a chat request expecting JSON output.
        Uses lower temperature and response_format for reliability.
        Auto-retries on JSON parse failure with increasing temperature.
        Each retry sends the original prompt unchanged (no error concatenation).
        """
        import re

        last_error = None
        for attempt in range(max_retries):
            current_temp = temperature + (attempt * 0.1)  # Increase temp slightly on retry
            try:
                content = self.chat(
                    system=system,
                    user=user,
                    model=model,
                    temperature=current_temp,
                    max_tokens=max_tokens,
                    response_format={"type": "json_object"},
                )
            except RuntimeError as e:
                # Timeout/API errors: retry with backoff (handled inside chat())
                if attempt < max_retries - 1:
                    import sys as _sys
                    print(f"  [API retry {attempt+1}/{max_retries}] {e}", file=_sys.stderr)
                    continue
                # Degradation: chat() already returned "" in degraded mode;
                # but if it raised, fall through to degradation check below
                last_error = e
                break

            # On empty content (degraded mode from chat()), return empty dict
            # Note: chat() already incremented _consecutive_failures and logged
            if not content:
                return {}

            # Strip markdown code blocks if present
            text = content.strip()
            if text.startswith("```"):
                lines = text.split("\n")
                # Remove first and last lines (```json and ```)
                lines = [l for l in lines if not l.strip().startswith("```")]
                text = "\n".join(lines)

            try:
                return json.loads(text)
            except json.JSONDecodeError as e:
                last_error = (e, text)
                # Try regex extraction
                match = re.search(r'\{[\s\S]*\}', text)
                if match:
                    try:
                        return json.loads(match.group())
                    except json.JSONDecodeError:
                        pass

                # Retry — keep original user prompt intact (no error hint appended)
                if attempt < max_retries - 1:
                    import sys as _sys
                    print(f"  [JSON retry {attempt+1}/{max_retries}] parse error: {e}", file=_sys.stderr)
                    # NOTE: user prompt is NOT modified — each retry sends the original

        # All retries exhausted — check degradation
        self._consecutive_failures += 1
        if self._is_degraded():
            logger.warning("LLM degradation in chat_json: returning empty dict")
            return {}

        if isinstance(last_error, tuple):
            e, partial = last_error
            raise RuntimeError(
                f"LLM JSON parse failed after {max_retries} attempts: {e}\n"
                f"Partial output: {partial[:500]}"
            )
        raise last_error or RuntimeError("LLM JSON parse failed (unknown error)")

    def generate_image_prompt(
        self,
        system_prompt: str,
        user_prompt: str,
        target_model: str = "sdxl",
        model: str = None,
    ) -> str:
        """
        Generate an image model prompt via LLM.

        This is the key bridge: LLM reads the AICB-style structured prompt
        (with rules about style matching, reference consistency, rendering quality)
        and outputs a prompt adapted for the target image model.

        target_model: "sdxl" (comma-separated tags) | "qwen_edit" (natural language)
        """
        target_hint = ""
        if target_model == "sdxl":
            target_hint = (
                "输出格式要求：输出一段适合 SDXL (Stable Diffusion XL) 的英文 prompt。"
                "使用逗号分隔的 tag 格式。"
                "包含：quality tags, character description tags, scene/setting tags, "
                "lighting/mood tags, composition tags。"
                "总长度 300-500 字符。不要输出解释，只输出 prompt 文本。"
            )
        elif target_model == "qwen_edit":
            target_hint = (
                "输出格式要求：输出一段适合 Qwen Image Edit 的中文 prompt。"
                "使用自然语言描述，包含：场景、角色外观、姿态、光影、构图。"
                "总长度 100-200 字。不要输出解释，只输出 prompt 文本。"
            )
        else:
            target_hint = "输出适合图像生成模型的 prompt 文本。"

        enhanced_system = system_prompt + "\n\n" + target_hint

        return self.chat(
            system=enhanced_system,
            user=user_prompt,
            model=model,
            temperature=0.5,
            max_tokens=1024,
        )


# Singleton
_default_client: Optional[LLMClient] = None

def get_llm_client(model: str = None) -> LLMClient:
    """Get or create the default LLM client."""
    global _default_client
    if _default_client is None:
        _default_client = LLMClient(model=model)
    return _default_client
