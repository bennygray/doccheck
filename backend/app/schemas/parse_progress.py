"""SSE 解析进度事件 schema (C5 parser-pipeline B1 / D6)。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

EventType = Literal[
    "snapshot",
    "bidder_status_changed",
    "document_role_classified",
    "project_price_rule_ready",
    "bidder_price_filled",
    "error",
    "heartbeat",
]


class ParseProgressEvent(BaseModel):
    """SSE 一条事件的序列化结构。

    按 text/event-stream 协议,上层会序列化为:
        event: <event_type>
        data: <json(data)>
    """

    event_type: EventType
    data: dict[str, Any]


__all__ = ["ParseProgressEvent", "EventType"]
