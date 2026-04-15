"""L1 - style_impl/config (C13)"""

from __future__ import annotations

import logging

import pytest

from app.services.detect.agents.style_impl.config import StyleConfig, load_config

_ENV_KEYS = [
    "STYLE_ENABLED",
    "STYLE_GROUP_THRESHOLD",
    "STYLE_SAMPLE_PER_BIDDER",
    "STYLE_TFIDF_FILTER_RATIO",
    "STYLE_LLM_TIMEOUT_S",
    "STYLE_LLM_MAX_RETRIES",
]


def _clean_env(monkeypatch):
    for k in _ENV_KEYS:
        monkeypatch.delenv(k, raising=False)


def test_defaults(monkeypatch) -> None:
    _clean_env(monkeypatch)
    assert load_config() == StyleConfig()


def test_enabled_false(monkeypatch) -> None:
    _clean_env(monkeypatch)
    monkeypatch.setenv("STYLE_ENABLED", "false")
    assert load_config().enabled is False


def test_group_threshold_boundary(monkeypatch) -> None:
    _clean_env(monkeypatch)
    monkeypatch.setenv("STYLE_GROUP_THRESHOLD", "2")
    assert load_config().group_threshold == 2


def test_group_threshold_below_min_raises(monkeypatch) -> None:
    _clean_env(monkeypatch)
    monkeypatch.setenv("STYLE_GROUP_THRESHOLD", "1")
    with pytest.raises(ValueError, match=">= 2"):
        load_config()


def test_sample_per_bidder_boundary_lo(monkeypatch) -> None:
    _clean_env(monkeypatch)
    monkeypatch.setenv("STYLE_SAMPLE_PER_BIDDER", "5")
    assert load_config().sample_per_bidder == 5


def test_sample_per_bidder_boundary_hi(monkeypatch) -> None:
    _clean_env(monkeypatch)
    monkeypatch.setenv("STYLE_SAMPLE_PER_BIDDER", "10")
    assert load_config().sample_per_bidder == 10


def test_sample_per_bidder_out_of_range_raises(monkeypatch) -> None:
    _clean_env(monkeypatch)
    monkeypatch.setenv("STYLE_SAMPLE_PER_BIDDER", "20")
    with pytest.raises(ValueError, match=r"\[5, 10\]"):
        load_config()


def test_tfidf_filter_ratio_out_of_range_fallback(monkeypatch, caplog) -> None:
    _clean_env(monkeypatch)
    monkeypatch.setenv("STYLE_TFIDF_FILTER_RATIO", "2.5")
    with caplog.at_level(logging.WARNING):
        cfg = load_config()
    assert cfg.tfidf_filter_ratio == 0.3
    assert any("TFIDF_FILTER_RATIO" in r.message for r in caplog.records)


def test_llm_timeout_s_negative_fallback(monkeypatch, caplog) -> None:
    _clean_env(monkeypatch)
    monkeypatch.setenv("STYLE_LLM_TIMEOUT_S", "-5")
    with caplog.at_level(logging.WARNING):
        cfg = load_config()
    assert cfg.llm_timeout_s == 60


def test_llm_max_retries_zero_allowed(monkeypatch) -> None:
    _clean_env(monkeypatch)
    monkeypatch.setenv("STYLE_LLM_MAX_RETRIES", "0")
    assert load_config().llm_max_retries == 0
