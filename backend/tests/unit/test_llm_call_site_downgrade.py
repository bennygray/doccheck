"""L1 - LLM 调用点降级归一完成校验 (harden-async-infra N7)

验证 6 个 LLM 调用点按 design D3 完成归一:
- style_impl (无本地兜底)→ raise AgentSkippedError(kind → skip reason)
- error_impl / text_sim llm_judge (有兜底)→ 返 None/{}, 精细化 kind 日志
- judge_llm (判方式依赖 _has_sufficient_evidence)→ 走 fallback_conclusion 或 indeterminate
- role_classifier (parser)→ 走 classify_by_keywords fallback,日志带 kind
- price_rule_detector (parser)→ 返 None,日志带 kind

策略:
1. style_impl raise 路径在 test_style_llm_client.py 已覆盖 3 kind → 此处不重复
2. 其他 5 个站点只做源码级校验(logger.warning 带 kind 参数),轻量快速
"""

from __future__ import annotations

from pathlib import Path

import pytest

# ---- style_impl raise (already covered in test_style_llm_client.py) ----


def test_style_client_raises_agent_skipped_error():
    """Sanity check:style_impl 模块 import 层面含 AgentSkippedError raise 语句。"""
    import app.services.detect.agents.style_impl.llm_client as mod

    src = Path(mod.__file__).read_text(encoding="utf-8")
    assert "raise AgentSkippedError" in src, (
        "style_impl/llm_client.py 应 raise AgentSkippedError(归一无本地兜底路径)"
    )
    assert "llm_error_to_skip_reason" in src, (
        "style_impl/llm_client.py 应调 llm_error_to_skip_reason 映射 kind"
    )


# ---- 其他 5 站点:logger.warning 精细化 kind 校验 ----


@pytest.mark.parametrize(
    "module_path,expected_kind_log",
    [
        (
            "app/services/detect/agents/error_impl/llm_judge.py",
            "kind=",
        ),
        (
            "app/services/detect/agents/text_sim_impl/llm_judge.py",
            "kind=",
        ),
        (
            "app/services/detect/judge_llm.py",
            "result.error",  # L-9 里 _call_llm_judge 记 result.error
        ),
        (
            "app/services/parser/llm/role_classifier.py",
            "kind=",
        ),
        (
            "app/services/parser/llm/price_rule_detector.py",
            "kind=",
        ),
    ],
)
def test_call_site_logs_kind(module_path: str, expected_kind_log: str):
    """每个 LLM 调用点的 error 分支都应在日志里带 kind 信息(N7 归一要求)。"""
    from app.core.config import settings  # noqa: F401

    # 项目根相对路径
    src = Path(module_path).read_text(encoding="utf-8")
    assert expected_kind_log in src, (
        f"{module_path} 应在 LLM error 日志里带 kind 信息(实际缺 {expected_kind_log!r})"
    )


# ---- judge_llm 的三路径对齐 ----


def test_judge_layer_three_paths_preserved():
    """judge.py 按 _has_sufficient_evidence 三路径正确:
    - False → indeterminate + INSUFFICIENT_EVIDENCE_CONCLUSION
    - True + LLM ok → clamp
    - True + LLM fail → fallback_conclusion(保留公式信号)
    """
    import app.services.detect.judge as judge_mod

    src = Path(judge_mod.__file__).read_text(encoding="utf-8")
    # indeterminate 分支
    assert "risk_level" not in src or "indeterminate" in src, (
        "judge.py 必须支持 indeterminate 路径(honest-detection-results 已建立)"
    )
    assert "INSUFFICIENT_EVIDENCE_CONCLUSION" in src, (
        "judge.py 必须引用 INSUFFICIENT_EVIDENCE_CONCLUSION"
    )
    assert "fallback_conclusion" in src, (
        "judge.py 必须保留 fallback_conclusion 路径"
        "(证据充分但 LLM 失败 → 保留公式 level + fallback_conclusion)"
    )


def test_style_exception_order_guards_agent_skipped():
    """style.py 的 try/except 里 `except AgentSkippedError: raise` MUST 出现在
    `except Exception` 之前,否则通用 except 吞掉 skipped 语义 → failed。"""
    import app.services.detect.agents.style as style_mod

    src = Path(style_mod.__file__).read_text(encoding="utf-8")
    idx_skipped = src.find("except AgentSkippedError")
    idx_exception = src.find("except Exception")
    assert idx_skipped != -1, "style.py MUST 捕获并 re-raise AgentSkippedError"
    assert idx_exception != -1, "style.py 仍需 except Exception 兜底"
    assert idx_skipped < idx_exception, (
        "style.py 的 except AgentSkippedError MUST 在 except Exception 之前"
    )
