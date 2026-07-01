"""
core/vl_backend.py — VL (Vision-Language) 后端生命周期管理

职责:
  1. 检测 qw35-9b 可用性
  2. 按需启停（通过 edge-llm）
  3. 健康检查
  4. 为质检模块提供统一后端状态

所有需要 VL 的 stage (S3, S5, S6) 通过此模块获取后端状态，
避免各自重复检测/启停逻辑。
"""

import json
import urllib.request
import urllib.error
import subprocess
import time
from pathlib import Path
from typing import Optional


# ═══════════════════════════════════════════════════════════════════
# Config
# ═══════════════════════════════════════════════════════════════════

VLLM_URL = "http://localhost:8002/v1/chat/completions"
HEALTH_URL = "http://localhost:8002/health"
MODELS_URL = "http://localhost:8002/v1/models"
DEFAULT_MODEL = "vllm_qw35_gptq"

HEALTH_TIMEOUT = 5       # 秒
STARTUP_TIMEOUT = 120     # qw35-9b 启动最大等待秒数
STARTUP_POLL_INTERVAL = 5 # 启动轮询间隔


class VLBackend:
    """VL 后端生命周期管理器."""

    def __init__(self, url: str = VLLM_URL, model: str = DEFAULT_MODEL):
        self.url = url
        self.health_url = url.replace("/v1/chat/completions", "/health")
        self.models_url = url.replace("/v1/chat/completions", "/v1/models")
        self.model = model
        self._available = None  # 缓存状态

    def is_available(self, force_check: bool = False) -> bool:
        """检测 VL 后端是否可用."""
        if self._available is not None and not force_check:
            return self._available

        try:
            req = urllib.request.Request(self.health_url, method="GET")
            with urllib.request.urlopen(req, timeout=HEALTH_TIMEOUT) as resp:
                self._available = resp.status == 200
                return self._available
        except Exception:
            self._available = False
            return False

    def get_model_name(self) -> Optional[str]:
        """获取当前 VL 模型名称."""
        try:
            req = urllib.request.Request(self.models_url, method="GET")
            with urllib.request.urlopen(req, timeout=HEALTH_TIMEOUT) as resp:
                data = json.loads(resp.read().decode())
                if data.get("data"):
                    return data["data"][0].get("id")
        except Exception:
            pass
        return None

    def start(self, timeout: int = STARTUP_TIMEOUT) -> bool:
        """通过 edge-llm 启动 qw35-9b 后端."""
        if self.is_available(force_check=True):
            return True

        print(f"  [VL] 启动 qw35-9b 后端...")
        try:
            result = subprocess.run(
                ["edge-llm", "switch", "qwen35-9b"],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode != 0:
                print(f"  [VL] edge-llm switch failed: {result.stderr[:200]}")
                return False
        except FileNotFoundError:
            print(f"  [VL] edge-llm 命令不存在，跳过自动启动")
            return False
        except subprocess.TimeoutExpired:
            print(f"  [VL] edge-llm switch 超时")
            return False

        # 等待就绪
        print(f"  [VL] 等待 qw35-9b 就绪 (最多 {timeout}s)...")
        start_time = time.time()
        while time.time() - start_time < timeout:
            if self.is_available(force_check=True):
                model_name = self.get_model_name()
                print(f"  [VL] ✅ qw35-9b 就绪 (model: {model_name})")
                return True
            time.sleep(STARTUP_POLL_INTERVAL)

        print(f"  [VL] ❌ qw35-9b 启动超时 ({timeout}s)")
        return False

    def stop(self) -> bool:
        """停止 qw35-9b 后端 (通过 edge-llm switch idle)."""
        if not self.is_available():
            return True

        try:
            result = subprocess.run(
                ["edge-llm", "switch", "idle"],
                capture_output=True, text=True, timeout=30
            )
            self._available = False
            return result.returncode == 0
        except Exception as e:
            print(f"  [VL] 停止失败: {e}")
            return False

    def ensure_available(self, auto_start: bool = True) -> bool:
        """
        确保 VL 后端可用。不可用时根据 auto_start 决定是否自动启动。
        
        Args:
            auto_start: True=自动启动 qw35-9b, False=仅检测
        
        Returns:
            True=后端可用, False=后端不可用且无法启动
        """
        if self.is_available():
            return True

        if not auto_start:
            print(f"  ⚠️ VL 后端不可用 (qw35-9b @ {self.health_url})")
            print(f"  → 提示: 运行 'edge-llm switch qwen35-9b' 启动")
            return False

        return self.start()


# Singleton
_backend: Optional[VLBackend] = None


def get_vl_backend() -> VLBackend:
    """获取全局 VL 后端实例."""
    global _backend
    if _backend is None:
        _backend = VLBackend()
    return _backend
