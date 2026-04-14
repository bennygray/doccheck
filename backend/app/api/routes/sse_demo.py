"""SSE 演示端点 - C1 infra-base

GET /demo/sse 周期性推送心跳事件,验证 SSE 推送基础。
客户端断开时捕获 CancelledError,记录日志后正常结束(服务端幂等)。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)
router = APIRouter()

# 心跳间隔(秒):默认 15;测试可通过 SSE_HEARTBEAT_INTERVAL_S 环境变量覆盖
HEARTBEAT_INTERVAL_S = float(os.environ.get("SSE_HEARTBEAT_INTERVAL_S", "15.0"))


async def _heartbeat_stream(request: Request):
    """异步生成器:每 HEARTBEAT_INTERVAL_S 秒推一次 heartbeat 事件。

    客户端断开由 asyncio.CancelledError 检测(StreamingResponse 会在下游断开时
    cancel generator task),不用 request.is_disconnected() 轮询 —— 后者在
    ASGITransport 测试环境下会立即返 True,导致无法触发测试。
    """
    seq = 0
    try:
        while True:
            seq += 1
            payload = json.dumps(
                {"seq": seq, "ts": datetime.now(timezone.utc).isoformat()}
            )
            yield f"event: heartbeat\ndata: {payload}\n\n"
            await asyncio.sleep(HEARTBEAT_INTERVAL_S)
    except asyncio.CancelledError:
        logger.info("SSE demo stream cancelled (seq=%s)", seq)
        raise


@router.get("/sse")
async def sse_demo(request: Request) -> StreamingResponse:
    return StreamingResponse(
        _heartbeat_stream(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # 防止 nginx 等反代缓冲
        },
    )
