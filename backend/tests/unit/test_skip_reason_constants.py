"""L1 - skip reason 常量 + kind → reason 映射 (harden-async-infra M2)

防未来字符串漂移:常量值必须精确等于 design D6 表文字。
"""

from __future__ import annotations

import pytest

from app.services.detect.errors import (
    SKIP_REASON_LLM_AUTH,
    SKIP_REASON_LLM_BAD_RESPONSE,
    SKIP_REASON_LLM_NETWORK,
    SKIP_REASON_LLM_RATE_LIMIT,
    SKIP_REASON_LLM_TIMEOUT,
    SKIP_REASON_SUBPROC_CRASH,
    SKIP_REASON_SUBPROC_TIMEOUT,
    AgentSkippedError,
    llm_error_to_skip_reason,
)


class TestSkipReasonConstants:
    """design D6 表的 7 条文案常量值锁定。"""

    def test_subproc_crash_text(self):
        assert SKIP_REASON_SUBPROC_CRASH == "解析崩溃,已跳过"

    def test_subproc_timeout_text(self):
        assert SKIP_REASON_SUBPROC_TIMEOUT == "解析超时,已跳过"

    def test_llm_timeout_text(self):
        assert SKIP_REASON_LLM_TIMEOUT == "LLM 超时,已跳过"

    def test_llm_rate_limit_text(self):
        assert SKIP_REASON_LLM_RATE_LIMIT == "LLM 限流,已跳过"

    def test_llm_auth_text(self):
        assert SKIP_REASON_LLM_AUTH == "LLM 鉴权失败,已跳过"

    def test_llm_network_text(self):
        assert SKIP_REASON_LLM_NETWORK == "LLM 网络错误,已跳过"

    def test_llm_bad_response_text(self):
        assert SKIP_REASON_LLM_BAD_RESPONSE == "LLM 返回异常,已跳过"

    def test_all_reasons_end_with_suffix(self):
        """所有新增文案 MUST 以 `,已跳过` 结尾(D6 规范)。"""
        for reason in (
            SKIP_REASON_SUBPROC_CRASH,
            SKIP_REASON_SUBPROC_TIMEOUT,
            SKIP_REASON_LLM_TIMEOUT,
            SKIP_REASON_LLM_RATE_LIMIT,
            SKIP_REASON_LLM_AUTH,
            SKIP_REASON_LLM_NETWORK,
            SKIP_REASON_LLM_BAD_RESPONSE,
        ):
            assert reason.endswith(",已跳过"), f"违反 D6 格式: {reason!r}"
            assert len(reason) <= 50, f"超过 50 字: {reason!r}"


class TestLLMErrorToSkipReason:
    """6 种 LLMErrorKind 到 reason 常量的映射。"""

    @pytest.mark.parametrize(
        "kind,expected",
        [
            ("timeout", SKIP_REASON_LLM_TIMEOUT),
            ("rate_limit", SKIP_REASON_LLM_RATE_LIMIT),
            ("auth", SKIP_REASON_LLM_AUTH),
            ("network", SKIP_REASON_LLM_NETWORK),
            ("bad_response", SKIP_REASON_LLM_BAD_RESPONSE),
            ("other", SKIP_REASON_LLM_BAD_RESPONSE),
        ],
    )
    def test_mapping(self, kind, expected):
        assert llm_error_to_skip_reason(kind) == expected

    def test_all_6_kinds_covered(self):
        """LLMErrorKind Literal 的 6 个值全部要有映射(未覆盖会 KeyError)。"""
        # 和 base.py ErrorKind Literal 同步
        all_kinds = ("timeout", "rate_limit", "auth", "network", "bad_response", "other")
        for kind in all_kinds:
            # 不抛 KeyError 即可
            reason = llm_error_to_skip_reason(kind)
            assert reason.endswith(",已跳过")


class TestAgentSkippedError:
    """异常类最小行为验证。"""

    def test_reason_preserved(self):
        exc = AgentSkippedError("测试原因,已跳过")
        assert str(exc) == "测试原因,已跳过"
        assert exc.reason == "测试原因,已跳过"

    def test_is_exception_subclass(self):
        """MUST 继承自 Exception(engine 的 `except Exception` 才能作为后手兜底)。"""
        assert issubclass(AgentSkippedError, Exception)
