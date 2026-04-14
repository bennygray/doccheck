"""AgentTask Pydantic schemas (C6 detect-framework)。"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class AgentTaskResponse(BaseModel):
    """AgentTask 行对外响应,用于 status / events snapshot。"""

    id: int
    agent_name: str
    agent_type: str  # pair | global
    pair_bidder_a_id: int | None
    pair_bidder_b_id: int | None
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    elapsed_ms: int | None
    score: Decimal | None
    summary: str | None
    error: str | None

    model_config = {"from_attributes": True}
