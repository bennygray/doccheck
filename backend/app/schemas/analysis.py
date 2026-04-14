"""Analysis API schemas (C6 detect-framework)。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.schemas.agent_task import AgentTaskResponse


class AnalysisStartResponse(BaseModel):
    """POST /analysis/start 201 响应。"""

    version: int
    agent_task_count: int


class AnalysisStartConflictResponse(BaseModel):
    """POST /analysis/start 409(项目 analyzing 态)响应。"""

    current_version: int
    started_at: datetime | None
    message: str = "检测正在进行中"


class AnalysisStatusResponse(BaseModel):
    """GET /analysis/status 响应。"""

    version: int | None
    project_status: str
    started_at: datetime | None
    agent_tasks: list[AgentTaskResponse]


AnalysisEventType = Literal[
    "snapshot", "agent_status", "report_ready", "heartbeat"
]
