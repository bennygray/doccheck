"""L2: /demo/sse 端点 30 秒内至少收到 1 条 heartbeat 事件

用真实 uvicorn subprocess 启动 app,httpx 连接 + stream。避开 TestClient +
StreamingResponse 在 Windows 下的 buffering 怪异,L2 语义更正(走真正 HTTP)。
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from contextlib import closing

import httpx


def _pick_free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_sse_heartbeat_within_window() -> None:
    port = _pick_free_port()
    env = {
        **os.environ,
        "INFRA_DISABLE_LIFECYCLE": "1",
        "SSE_HEARTBEAT_INTERVAL_S": "0.1",  # 压到 0.1s 加速测试
        "PYTHONIOENCODING": "utf-8",
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__))),  # backend/
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        # 等 uvicorn ready(最多 10s)
        for _ in range(50):
            try:
                r = httpx.get(f"http://127.0.0.1:{port}/api/health", timeout=1.0)
                if r.status_code in (200, 503):
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.2)
        else:
            raise AssertionError(f"uvicorn did not become ready on port {port}")

        # 连 /demo/sse 读前几 KB,断言命中 "event: heartbeat"
        got = False
        bytes_read = 0
        with httpx.Client(timeout=httpx.Timeout(30.0, read=30.0)) as client:
            with client.stream("GET", f"http://127.0.0.1:{port}/demo/sse") as resp:
                assert resp.status_code == 200
                assert resp.headers["content-type"].startswith("text/event-stream")
                for chunk in resp.iter_bytes(chunk_size=256):
                    bytes_read += len(chunk)
                    if b"event: heartbeat" in chunk:
                        got = True
                        break
                    if bytes_read > 8192:
                        break
        assert got, f"未收到 heartbeat(read {bytes_read} bytes)"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
