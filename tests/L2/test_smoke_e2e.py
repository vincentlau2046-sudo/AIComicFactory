"""L2: 全链路端到端测试

前置条件: 全部服务就绪 (ComfyUI + API + GPU)
设置 AICF_RUN_E2E=1 启用
"""

import os
import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("AICF_RUN_E2E"),
    reason="E2E tests require full environment (set AICF_RUN_E2E=1)"
)


class TestEndToEnd:
    """完整端到端: 输入故事 → 输出视频"""

    def test_e2e_short_story(self, tmp_path):
        """200字短故事 → 完整视频 (≤60s)"""
        # Will be implemented when all services are available
        pass
