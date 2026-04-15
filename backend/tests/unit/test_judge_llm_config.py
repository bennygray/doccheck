"""L1 - judge_llm config env loader (C14)"""

from __future__ import annotations

from app.services.detect.judge_llm import load_llm_judge_config


def test_defaults(monkeypatch):
    for k in [
        "LLM_JUDGE_ENABLED",
        "LLM_JUDGE_TIMEOUT_S",
        "LLM_JUDGE_MAX_RETRY",
        "LLM_JUDGE_SUMMARY_TOP_K",
        "LLM_JUDGE_MODEL",
    ]:
        monkeypatch.delenv(k, raising=False)
    cfg = load_llm_judge_config()
    assert cfg.enabled is True
    assert cfg.timeout_s == 30
    assert cfg.max_retry == 2
    assert cfg.summary_top_k == 3
    assert cfg.model == ""


def test_enabled_bool_parse(monkeypatch):
    monkeypatch.setenv("LLM_JUDGE_ENABLED", "false")
    assert load_llm_judge_config().enabled is False
    monkeypatch.setenv("LLM_JUDGE_ENABLED", "0")
    assert load_llm_judge_config().enabled is False
    monkeypatch.setenv("LLM_JUDGE_ENABLED", "no")
    assert load_llm_judge_config().enabled is False
    monkeypatch.setenv("LLM_JUDGE_ENABLED", "True")
    assert load_llm_judge_config().enabled is True


def test_enabled_invalid_fallback(monkeypatch):
    """非法 bool 值 → fallback default(True)+ warn"""
    monkeypatch.setenv("LLM_JUDGE_ENABLED", "maybe")
    cfg = load_llm_judge_config()
    assert cfg.enabled is True  # default


def test_timeout_out_of_range_fallback(monkeypatch):
    """TIMEOUT_S 超界 → fallback 30"""
    monkeypatch.setenv("LLM_JUDGE_TIMEOUT_S", "-5")
    assert load_llm_judge_config().timeout_s == 30
    monkeypatch.setenv("LLM_JUDGE_TIMEOUT_S", "10000")
    assert load_llm_judge_config().timeout_s == 30
    monkeypatch.setenv("LLM_JUDGE_TIMEOUT_S", "abc")
    assert load_llm_judge_config().timeout_s == 30


def test_max_retry_out_of_range_fallback(monkeypatch):
    """MAX_RETRY 超界 [0,5] → fallback 2"""
    monkeypatch.setenv("LLM_JUDGE_MAX_RETRY", "-1")
    assert load_llm_judge_config().max_retry == 2
    monkeypatch.setenv("LLM_JUDGE_MAX_RETRY", "100")
    assert load_llm_judge_config().max_retry == 2
    monkeypatch.setenv("LLM_JUDGE_MAX_RETRY", "0")
    assert load_llm_judge_config().max_retry == 0  # 合法边界
    monkeypatch.setenv("LLM_JUDGE_MAX_RETRY", "5")
    assert load_llm_judge_config().max_retry == 5


def test_summary_top_k_out_of_range_fallback(monkeypatch):
    """SUMMARY_TOP_K 超界 [1,20] → fallback 3"""
    monkeypatch.setenv("LLM_JUDGE_SUMMARY_TOP_K", "0")
    assert load_llm_judge_config().summary_top_k == 3
    monkeypatch.setenv("LLM_JUDGE_SUMMARY_TOP_K", "25")
    assert load_llm_judge_config().summary_top_k == 3
    monkeypatch.setenv("LLM_JUDGE_SUMMARY_TOP_K", "abc")
    assert load_llm_judge_config().summary_top_k == 3
    monkeypatch.setenv("LLM_JUDGE_SUMMARY_TOP_K", "5")
    assert load_llm_judge_config().summary_top_k == 5


def test_model_string_pass_through(monkeypatch):
    monkeypatch.setenv("LLM_JUDGE_MODEL", "gpt-4o-mini")
    assert load_llm_judge_config().model == "gpt-4o-mini"
    monkeypatch.setenv("LLM_JUDGE_MODEL", "  ")
    assert load_llm_judge_config().model == ""
