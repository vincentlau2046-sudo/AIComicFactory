"""L0: LLMClient 单元测试"""

import json
import time
from unittest.mock import MagicMock, patch, call
from urllib.error import HTTPError

import pytest

from core.llm_client import (
    LLMClient,
    get_llm_client,
    DEFAULT_MODEL,
    MAX_RETRIES,
    RETRY_DELAYS,
    DEGRADATION_THRESHOLD,
)


class TestConstants:
    """检查模块级常量"""

    def test_default_model_is_deepseek_flash(self):
        assert DEFAULT_MODEL == "deepseek-v4-flash"

    def test_max_retries_value(self):
        assert MAX_RETRIES == 3

    def test_retry_delays_exponential_backoff(self):
        """指数退避——间隔递增"""
        assert len(RETRY_DELAYS) == MAX_RETRIES
        for i in range(1, len(RETRY_DELAYS)):
            assert RETRY_DELAYS[i] > RETRY_DELAYS[i - 1]

    def test_retry_delays_expected_values(self):
        assert RETRY_DELAYS == [5, 15, 30]

    def test_degradation_threshold_exists(self):
        assert DEGRADATION_THRESHOLD == 5


class TestGetLLMClient:
    """get_llm_client 单例模式"""

    def teardown_method(self):
        # Reset singleton between tests
        import core.llm_client as m
        m._default_client = None

    def test_singleton_returns_same_instance(self):
        c1 = get_llm_client()
        c2 = get_llm_client()
        assert c1 is c2

    def test_singleton_with_model_resets(self):
        c1 = get_llm_client()
        c2 = get_llm_client(model="ernie-4.5-turbo-20260402")
        assert c1 is c2

    def test_default_model_propagated(self):
        client = get_llm_client()
        assert client.model == DEFAULT_MODEL


class TestLLMClientInit:
    """LLMClient 构造函数"""

    def test_default_init(self):
        with patch("core.llm_client._get_api_key", return_value="test-key"):
            client = LLMClient()
        assert client.model == DEFAULT_MODEL
        assert client._consecutive_failures == 0
        assert client._degradation_threshold == DEGRADATION_THRESHOLD

    def test_custom_model(self):
        with patch("core.llm_client._get_api_key", return_value="test-key"):
            client = LLMClient(model="ernie-4.5-turbo-20260402")
        assert client.model == "ernie-4.5-turbo-20260402"

    def test_custom_api_key(self):
        client = LLMClient(api_key="custom-key")
        assert client.api_key == "custom-key"

    def test_custom_degradation_threshold(self):
        with patch("core.llm_client._get_api_key", return_value="test-key"):
            client = LLMClient(degradation_threshold=3)
        assert client._degradation_threshold == 3


class TestLLMClientChat:
    """LLMClient.chat() 核心逻辑"""

    @pytest.fixture
    def client(self):
        with patch("core.llm_client._get_api_key", return_value="test-key"):
            return LLMClient()

    def make_success_response(self, content="Hello!"):
        """构建模拟的成功 HTTP 响应"""
        body = json.dumps({
            "choices": [{"message": {"content": content, "role": "assistant"}}],
            "usage": {"total_tokens": 10},
        }).encode("utf-8")
        mock_resp = MagicMock()
        mock_resp.read.return_value = body
        mock_resp.__enter__.return_value = mock_resp
        return mock_resp

    def make_http_error(self, code: int, body: str = "error"):
        """构建模拟的 HTTP 错误"""
        mock_err = HTTPError(
            url="http://test",
            code=code,
            msg="Error",
            hdrs={},
            fp=None,
        )
        # Mock the fp (file pointer) for reading body
        fp = MagicMock()
        fp.read.return_value = body.encode("utf-8")
        mock_err.fp = fp
        return mock_err

    def test_chat_success_returns_content(self, client):
        """chat() 对成功请求返回正确格式"""
        mock_resp = self.make_success_response("我是AI助手")
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = client.chat(system="你是一名助手", user="你好")
        assert result == "我是AI助手"

    def test_chat_success_resets_failures(self, client):
        """成功请求重置失败计数"""
        client._consecutive_failures = 3
        mock_resp = self.make_success_response("ok")
        with patch("urllib.request.urlopen", return_value=mock_resp):
            client.chat(user="hi")
        assert client._consecutive_failures == 0

    def test_chat_retries_on_5xx(self, client):
        """chat() 对 5xx 错误执行重试"""
        mock_err = self.make_http_error(500)
        mock_resp = self.make_success_response("最终成功")

        with patch("urllib.request.urlopen", side_effect=[mock_err, mock_err, mock_resp]) as mock_urlopen, \
             patch("time.sleep") as mock_sleep:
            result = client.chat(user="hi")

        assert result == "最终成功"
        # 3 retries (MAX_RETRIES), 2 failures + 1 success = 3 calls
        assert mock_urlopen.call_count == MAX_RETRIES
        # sleep called twice (before retry 2 and 3)
        assert mock_sleep.call_count == 2

    def test_chat_retries_on_429(self, client):
        """429 (rate-limit) 应该重试"""
        mock_err = self.make_http_error(429)
        mock_resp = self.make_success_response("ok")
        with patch("urllib.request.urlopen", side_effect=[mock_err, mock_resp]) as mock_urlopen, \
             patch("time.sleep"):
            result = client.chat(user="hi")
        assert result == "ok"
        assert mock_urlopen.call_count == 2

    def test_chat_no_retry_on_4xx(self, client):
        """4xx 错误（400/401/403）不重试"""
        mock_err = self.make_http_error(400, '{"error":"bad request"}')
        with patch("urllib.request.urlopen", side_effect=mock_err) as mock_urlopen, \
             patch("time.sleep"):
            with pytest.raises(RuntimeError, match="LLM API error 400"):
                client.chat(user="hi")
        # 只调用一次——不重试
        assert mock_urlopen.call_count == 1

    def test_chat_no_retry_on_403(self, client):
        """403 (Forbidden) 不重试"""
        mock_err = self.make_http_error(403)
        with patch("urllib.request.urlopen", side_effect=mock_err) as mock_urlopen, \
             patch("time.sleep"):
            with pytest.raises(RuntimeError, match="LLM API error 403"):
                client.chat(user="hi")
        assert mock_urlopen.call_count == 1

    def test_chat_retries_on_urlerror(self, client):
        """URLError 应该重试"""
        import urllib.error
        with patch("urllib.request.urlopen",
                   side_effect=urllib.error.URLError("connection failed")) as mock_urlopen, \
             patch("time.sleep") as mock_sleep:
            with pytest.raises(RuntimeError):
                client.chat(user="hi")
        assert mock_urlopen.call_count == MAX_RETRIES

    def test_chat_degradation_after_max_retries(self, client):
        """重试耗尽后进入 degradation 模式，返回空字符串"""
        # Set consecutive_failures near threshold so +1 triggers degradation
        client._consecutive_failures = DEGRADATION_THRESHOLD - 1
        mock_err = self.make_http_error(500)
        with patch("urllib.request.urlopen", side_effect=mock_err), \
             patch("time.sleep"):
            result = client.chat(user="hi")
        assert result == ""
        assert client._consecutive_failures == DEGRADATION_THRESHOLD

    def test_chat_degradation_threshold_returns_empty(self, client):
        """consecutive_failures >= threshold 返回空字符串"""
        client._consecutive_failures = DEGRADATION_THRESHOLD
        result = client.chat(user="hi")
        assert result == ""

    def test_chat_passes_system_and_user_messages(self, client):
        """验证发送的 payload 包含 system/user 消息"""
        mock_resp = self.make_success_response("ok")
        captured = {}

        def side_effect(req, **kw):
            captured["body"] = json.loads(req.data)
            return mock_resp

        with patch("urllib.request.urlopen", side_effect=side_effect):
            client.chat(system="SystemPrompt", user="UserMessage")

        msgs = captured["body"]["messages"]
        roles = [m["role"] for m in msgs]
        assert roles == ["system", "user"]
        assert msgs[0]["content"] == "SystemPrompt"
        assert msgs[1]["content"] == "UserMessage"

    def test_chat_empty_system_not_included(self, client):
        """空 system 字符串不加入 messages"""
        mock_resp = self.make_success_response("ok")
        captured = {}

        def side_effect(req, **kw):
            captured["body"] = json.loads(req.data)
            return mock_resp

        with patch("urllib.request.urlopen", side_effect=side_effect):
            client.chat(system="", user="UserMessage")

        msgs = captured["body"]["messages"]
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"


class TestLLMClientChatJSON:
    """LLMClient.chat_json()"""

    @pytest.fixture
    def client(self):
        with patch("core.llm_client._get_api_key", return_value="test-key"):
            return LLMClient()

    def test_chat_json_returns_dict(self, client):
        """chat_json 返回解析后的 dict"""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "choices": [{"message": {"content": '{"key": "value"}', "role": "assistant"}}],
        }).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = client.chat_json(system="test", user="hi")
        assert result == {"key": "value"}

    def test_chat_json_extracts_from_codeblock(self, client):
        """能从 markdown code block 中提取 JSON"""
        content = '```json\n{"key": "value"}\n```'
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "choices": [{"message": {"content": content, "role": "assistant"}}],
        }).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = client.chat_json(system="test", user="hi")
        assert result == {"key": "value"}


class TestLLMClientResolveModel:
    """_resolve_model 模型别名解析"""

    def test_resolve_primary_alias(self, client):
        assert client._resolve_model("PRIMARY") == "glm-5.1"

    def test_resolve_deepseek_flash(self, client):
        assert client._resolve_model("DEEPSEEK_FLASH") == "deepseek-v4-flash"

    def test_resolve_unknown_passthrough(self, client):
        assert client._resolve_model("custom-model") == "custom-model"

    def test_resolve_none_uses_default(self, client):
        assert client._resolve_model() == DEFAULT_MODEL

    @pytest.fixture
    def client(self):
        with patch("core.llm_client._get_api_key", return_value="test-key"):
            return LLMClient()
