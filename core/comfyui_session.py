"""
core/comfyui_session.py — 轻量级 ComfyUI API 客户端

简化自 westward_factory，去掉 GPU watchdog 等外部依赖。
用于 AIComicFactory 的图像/视频生成阶段。
"""

import json
import time
import uuid
import urllib.request
import urllib.error
import shutil
import logging
from pathlib import Path
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, field

logger = logging.getLogger("comfyui_session")

@dataclass
class TaskResult:
    prompt_id: str
    outputs: Dict = field(default_factory=dict)
    elapsed: float = 0.0
    error: Optional[str] = None

class ComfyUIError(Exception):
    pass

class ComfyUISession:
    """Simplified ComfyUI client for AIComicFactory."""
    
    def __init__(self, host: str = "127.0.0.1", port: int = 8188):
        self.host = host
        self.port = port
        self.base = f"http://{host}:{port}"
        self.client_id = f"aicf-{uuid.uuid4().hex[:8]}"
    
    def submit(self, workflow: dict) -> str:
        """Submit workflow, return prompt_id."""
        url = f"{self.base}/prompt"
        payload = json.dumps({"prompt": workflow, "client_id": self.client_id}).encode()
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
            pid = data.get("prompt_id")
            if not pid:
                raise ComfyUIError(f"No prompt_id: {data}")
            logger.info(f"Submitted: {pid}")
            return pid
    
    def wait(self, prompt_id: str, timeout: int = 600) -> TaskResult:
        """Poll history until completion."""
        start = time.time()
        while time.time() - start < timeout:
            try:
                url = f"{self.base}/history/{prompt_id}"
                with urllib.request.urlopen(url, timeout=10) as r:
                    history = json.loads(r.read())
                if prompt_id in history:
                    entry = history[prompt_id]
                    outputs = entry.get("outputs", {})
                    if entry.get("status", {}).get("status_str") == "error":
                        err = entry["status"].get("messages", ["?"])[0]
                        raise ComfyUIError(err)
                    elapsed = time.time() - start
                    logger.info(f"Completed: {prompt_id} in {elapsed:.1f}s")
                    return TaskResult(prompt_id=prompt_id, outputs=outputs, elapsed=elapsed)
            except ComfyUIError:
                raise
            except Exception as e:
                logger.debug(f"Poll: {e}")
            time.sleep(2)
        raise ComfyUIError(f"Timeout after {timeout}s")
    
    def run(self, workflow: dict, timeout: int = 600) -> TaskResult:
        """Submit + wait."""
        pid = self.submit(workflow)
        return self.wait(pid, timeout)
    
    def upload(self, src: Path, name: str = None) -> Path:
        """Copy file to ComfyUI input dir."""
        src = Path(src)
        target = Path.home() / "ComfyUI" / "input" / (name or src.name)
        shutil.copy2(str(src), str(target))
        return target
    
    def get_outputs(self, result: TaskResult) -> List[Path]:
        """Extract output file paths from result."""
        files = []
        for node_id, outputs in result.outputs.items():
            if "images" in outputs:
                for img in outputs["images"]:
                    fname = img.get("filename") or img.get("name", "")
                    if fname:
                        files.append(Path.home() / "ComfyUI" / "output" / fname)
        return files


def quick_run(workflow: dict, timeout: int = 600) -> TaskResult:
    """One-shot: submit + wait + return result."""
    session = ComfyUISession()
    return session.run(workflow, timeout)