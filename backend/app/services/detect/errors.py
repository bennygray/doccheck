"""检测子系统的异常与 skip reason 常量 (harden-async-infra)

- `AgentSkippedError`:agent 运行期的"应跳过"信号 — engine `_execute_agent_task`
  专门捕获后走 `_mark_skipped`,产出 `AgentTask.status="skipped"`。
- `SKIP_REASON_*`:集中的中文 skipped 文案常量(design D6),禁止站点硬编码。
- `llm_error_to_skip_reason`:将 LLMProvider 返回的 `LLMErrorKind` 映射到对应文案。

设计原则:
- 文案集中一处,变更只改这里;L1 `test_skip_reason_constants.py` 断言值等于 D6 表。
- 本模块**不**依赖 detect 子模块,避免循环导入(agent impl / engine 都 import 这里)。
"""

from __future__ import annotations

from app.services.llm.base import ErrorKind as LLMErrorKind


class AgentSkippedError(Exception):
    """Agent 运行期要求 engine 标 skipped 的信号异常。

    engine `_execute_agent_task` MUST 在通用 `except Exception` 之前捕获此类。
    `str(exc)` 返回 reason,直接写入 `AgentTask.summary`。
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason

    def __str__(self) -> str:
        return self.reason


# ---- skip reason 文案常量(design D6,格式 `"<具体原因>,已跳过"`,≤50 字) ----

SKIP_REASON_SUBPROC_CRASH = "解析崩溃,已跳过"
SKIP_REASON_SUBPROC_TIMEOUT = "解析超时,已跳过"
SKIP_REASON_LLM_TIMEOUT = "LLM 超时,已跳过"
SKIP_REASON_LLM_RATE_LIMIT = "LLM 限流,已跳过"
SKIP_REASON_LLM_AUTH = "LLM 鉴权失败,已跳过"
SKIP_REASON_LLM_NETWORK = "LLM 网络错误,已跳过"
SKIP_REASON_LLM_BAD_RESPONSE = "LLM 返回异常,已跳过"


_LLM_KIND_TO_REASON: dict[LLMErrorKind, str] = {
    "timeout": SKIP_REASON_LLM_TIMEOUT,
    "rate_limit": SKIP_REASON_LLM_RATE_LIMIT,
    "auth": SKIP_REASON_LLM_AUTH,
    "network": SKIP_REASON_LLM_NETWORK,
    "bad_response": SKIP_REASON_LLM_BAD_RESPONSE,
    "other": SKIP_REASON_LLM_BAD_RESPONSE,  # 未分类错误归到"返回异常"
}


def llm_error_to_skip_reason(kind: LLMErrorKind) -> str:
    """把 `LLMResult.error.kind` 映射到中文 skip reason 常量。"""
    return _LLM_KIND_TO_REASON[kind]


__all__ = [
    "AgentSkippedError",
    "SKIP_REASON_SUBPROC_CRASH",
    "SKIP_REASON_SUBPROC_TIMEOUT",
    "SKIP_REASON_LLM_TIMEOUT",
    "SKIP_REASON_LLM_RATE_LIMIT",
    "SKIP_REASON_LLM_AUTH",
    "SKIP_REASON_LLM_NETWORK",
    "SKIP_REASON_LLM_BAD_RESPONSE",
    "llm_error_to_skip_reason",
]
