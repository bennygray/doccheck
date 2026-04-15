"""L1 - error_impl/config (C13)"""

from __future__ import annotations

import logging

import pytest

from app.services.detect.agents.error_impl.config import (
    ErrorConsistencyConfig,
    load_config,
)

_ENV_KEYS = [
    "ERROR_CONSISTENCY_ENABLED",
    "ERROR_CONSISTENCY_MAX_CANDIDATE_SEGMENTS",
    "ERROR_CONSISTENCY_MIN_KEYWORD_LEN",
    "ERROR_CONSISTENCY_LLM_TIMEOUT_S",
    "ERROR_CONSISTENCY_LLM_MAX_RETRIES",
]


def _clean_env(monkeypatch):
    for k in _ENV_KEYS:
        monkeypatch.delenv(k, raising=False)


def test_defaults(monkeypatch) -> None:
    _clean_env(monkeypatch)
    assert load_config() == ErrorConsistencyConfig()


def test_env_enabled_false(monkeypatch) -> None:
    _clean_env(monkeypatch)
    monkeypatch.setenv("ERROR_CONSISTENCY_ENABLED", "false")
    assert load_config().enabled is False


def test_max_candidate_segments_override(monkeypatch) -> None:
    _clean_env(monkeypatch)
    monkeypatch.setenv("ERROR_CONSISTENCY_MAX_CANDIDATE_SEGMENTS", "50")
    assert load_config().max_candidate_segments == 50


def test_illegal_max_candidate_zero_raises(monkeypatch) -> None:
    _clean_env(monkeypatch)
    monkeypatch.setenv("ERROR_CONSISTENCY_MAX_CANDIDATE_SEGMENTS", "0")
    with pytest.raises(ValueError, match="must be positive"):
        load_config()


def test_illegal_max_candidate_negative_raises(monkeypatch) -> None:
    _clean_env(monkeypatch)
    monkeypatch.setenv("ERROR_CONSISTENCY_MAX_CANDIDATE_SEGMENTS", "-5")
    with pytest.raises(ValueError, match="must be positive"):
        load_config()


def test_illegal_max_candidate_non_int_raises(monkeypatch) -> None:
    _clean_env(monkeypatch)
    monkeypatch.setenv("ERROR_CONSISTENCY_MAX_CANDIDATE_SEGMENTS", "abc")
    with pytest.raises(ValueError, match="positive integer"):
        load_config()


def test_min_keyword_len_override(monkeypatch) -> None:
    _clean_env(monkeypatch)
    monkeypatch.setenv("ERROR_CONSISTENCY_MIN_KEYWORD_LEN", "3")
    assert load_config().min_keyword_len == 3


def test_illegal_min_keyword_len_zero_raises(monkeypatch) -> None:
    _clean_env(monkeypatch)
    monkeypatch.setenv("ERROR_CONSISTENCY_MIN_KEYWORD_LEN", "0")
    with pytest.raises(ValueError, match="must be positive"):
        load_config()


def test_llm_timeout_lenient_negative_fallback(monkeypatch, caplog) -> None:
    _clean_env(monkeypatch)
    monkeypatch.setenv("ERROR_CONSISTENCY_LLM_TIMEOUT_S", "-10")
    with caplog.at_level(logging.WARNING):
        cfg = load_config()
    assert cfg.llm_timeout_s == 30
    assert any("LLM_TIMEOUT_S" in r.message for r in caplog.records)


def test_llm_max_retries_zero_allowed(monkeypatch) -> None:
    _clean_env(monkeypatch)
    monkeypatch.setenv("ERROR_CONSISTENCY_LLM_MAX_RETRIES", "0")
    assert load_config().llm_max_retries == 0


def test_llm_max_retries_lenient_invalid_fallback(monkeypatch, caplog) -> None:
    _clean_env(monkeypatch)
    monkeypatch.setenv("ERROR_CONSISTENCY_LLM_MAX_RETRIES", "not_a_number")
    with caplog.at_level(logging.WARNING):
        cfg = load_config()
    assert cfg.llm_max_retries == 2
    assert any("LLM_MAX_RETRIES" in r.message for r in caplog.records)
