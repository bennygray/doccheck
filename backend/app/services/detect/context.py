"""Agent 执行上下文 + preflight / run 返回值 (C6 detect-framework)

所有 Agent 通过 AgentContext 访问项目级数据,不直接 query DB。
便于 L1 单元测试用 Mock。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, NamedTuple, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_task import AgentTask
from app.models.bidder import Bidder


class PreflightResult(NamedTuple):
    """Agent 前置自检结果。

    - ok         : 前置条件满足,继续 run
    - skip       : 前置不满足,AgentTask status=skipped,reason 写入 summary
    - downgrade  : 仅 error_consistency 使用;ctx.downgrade=True 继续 run
    """

    status: Literal["ok", "skip", "downgrade"]
    reason: Optional[str] = None


class AgentRunResult(NamedTuple):
    """Agent 执行结果。

    run 内部已写入 PairComparison / OverallAnalysis 行;
    这里返回的 score / summary 用于 UPDATE agent_tasks 行。
    """

    score: float
    summary: str
    evidence_json: Optional[dict[str, Any]] = None


@dataclass
class AgentContext:
    project_id: int
    version: int
    agent_task: AgentTask
    # pair 型 Agent 两侧 bidder;global 型全 None
    bidder_a: Optional[Bidder]
    bidder_b: Optional[Bidder]
    all_bidders: list[Bidder] = field(default_factory=list)
    # C6 不调 LLM;C14 综合研判 / C7~C13 真 Agent 会用到
    llm_provider: Optional[Any] = None
    session: Optional[AsyncSession] = None
    # error_consistency preflight 返 downgrade 时置 True
    downgrade: bool = False


__all__ = ["AgentContext", "PreflightResult", "AgentRunResult"]
