"""L1 元测试:钉 llm_call_timeout 默认值 = 300.0。

config-llm-timeout-default change:ark-code-latest 类慢模型实测 role_classifier /
price_rule_detector 单次 35~132s,60s cap 一贯超时 → 踢关键词兜底 → 放大假阳性。
默认值升 300s 后若未来有人误改回 60(或更小),此测试会红,提示 review。

**不**测 factory `_cap_timeout` 本身的行为(那是 harden-async-infra 的契约,有独立测试)。
本测试只钉 config.py 的默认值 + env 覆盖机制可用。
"""

from __future__ import annotations

import os

import pytest


def test_llm_call_timeout_default_is_300():
    """默认值必须是 300.0。未来改小请同步改本测试 + spec + handoff 记录理由。"""
    from app.core.config import Settings

    s = Settings(_env_file=None)  # 显式不读 .env,测代码默认值(避免测试机 .env 污染)
    assert s.llm_call_timeout == 300.0, (
        f"llm_call_timeout 默认值应为 300.0,实际 {s.llm_call_timeout}。"
        "若故意调整,请同步 openspec/specs/pipeline-error-handling/spec.md "
        "的 Requirement 'LLM 调用全局 timeout 安全上限' 默认值,并更新 handoff.md。"
    )


def test_llm_call_timeout_env_override(monkeypatch: pytest.MonkeyPatch):
    """env 覆盖仍然生效(pydantic-settings 契约)。"""
    monkeypatch.setenv("LLM_CALL_TIMEOUT", "60")
    from app.core.config import Settings

    s = Settings(_env_file=None)
    assert s.llm_call_timeout == 60.0


def test_llm_timeout_s_default_is_300():
    """per-call 默认值 = cap 默认值 = 300(fix-llm-timeout-default-followup)。

    archive change config-llm-timeout-default 只改了 cap 默认 60→300,
    但 factory 实际生效路径是 min(per_call, cap) — 改 cap 不会反向拉高 per_call。
    本 case 钉 per_call 默认也是 300,确保两个值默认对齐到 300。
    """
    from app.core.config import Settings

    s = Settings(_env_file=None)
    assert s.llm_timeout_s == 300.0, (
        f"llm_timeout_s 默认值应为 300.0(与 cap 对齐),实际 {s.llm_timeout_s}。"
        "若故意调整,请同步 openspec/specs/pipeline-error-handling/spec.md "
        "的 Requirement 'LLM 调用全局 timeout 与 per-call 默认值',并更新 handoff.md。"
    )


def test_llm_timeout_s_env_override(monkeypatch: pytest.MonkeyPatch):
    """env 覆盖 per-call timeout 仍可压低(部署方手工压小生效)。"""
    monkeypatch.setenv("LLM_TIMEOUT_S", "60")
    from app.core.config import Settings

    s = Settings(_env_file=None)
    assert s.llm_timeout_s == 60.0
