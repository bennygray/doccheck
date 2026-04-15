"""L1 - anomaly_impl/config (C12)"""

from __future__ import annotations

import logging

import pytest

from app.services.detect.agents.anomaly_impl.config import (
    AnomalyConfig,
    load_anomaly_config,
)

_ENV_KEYS = [
    "PRICE_ANOMALY_ENABLED",
    "PRICE_ANOMALY_MIN_SAMPLE_SIZE",
    "PRICE_ANOMALY_DEVIATION_THRESHOLD",
    "PRICE_ANOMALY_DIRECTION",
    "PRICE_ANOMALY_BASELINE_ENABLED",
    "PRICE_ANOMALY_MAX_BIDDERS",
    "PRICE_ANOMALY_WEIGHT",
]


def _clean_env(monkeypatch):
    for k in _ENV_KEYS:
        monkeypatch.delenv(k, raising=False)


def test_defaults(monkeypatch) -> None:
    _clean_env(monkeypatch)
    cfg = load_anomaly_config()
    assert cfg == AnomalyConfig(
        enabled=True,
        min_sample_size=3,
        deviation_threshold=0.30,
        direction="low",
        baseline_enabled=False,
        max_bidders=50,
        weight=1.0,
    )


def test_env_enabled_false(monkeypatch) -> None:
    _clean_env(monkeypatch)
    monkeypatch.setenv("PRICE_ANOMALY_ENABLED", "false")
    assert load_anomaly_config().enabled is False


def test_env_threshold_override(monkeypatch) -> None:
    _clean_env(monkeypatch)
    monkeypatch.setenv("PRICE_ANOMALY_DEVIATION_THRESHOLD", "0.20")
    assert load_anomaly_config().deviation_threshold == 0.20


def test_illegal_negative_threshold_raises(monkeypatch) -> None:
    _clean_env(monkeypatch)
    monkeypatch.setenv("PRICE_ANOMALY_DEVIATION_THRESHOLD", "-0.10")
    with pytest.raises(ValueError, match="must be > 0"):
        load_anomaly_config()


def test_illegal_zero_threshold_raises(monkeypatch) -> None:
    _clean_env(monkeypatch)
    monkeypatch.setenv("PRICE_ANOMALY_DEVIATION_THRESHOLD", "0")
    with pytest.raises(ValueError, match="must be > 0"):
        load_anomaly_config()


def test_illegal_sample_size_zero_raises(monkeypatch) -> None:
    _clean_env(monkeypatch)
    monkeypatch.setenv("PRICE_ANOMALY_MIN_SAMPLE_SIZE", "0")
    with pytest.raises(ValueError, match="must be positive"):
        load_anomaly_config()


def test_illegal_sample_size_non_int_raises(monkeypatch) -> None:
    _clean_env(monkeypatch)
    monkeypatch.setenv("PRICE_ANOMALY_MIN_SAMPLE_SIZE", "abc")
    with pytest.raises(ValueError, match="positive integer"):
        load_anomaly_config()


def test_max_bidders_lenient_invalid_fallback(monkeypatch, caplog) -> None:
    _clean_env(monkeypatch)
    monkeypatch.setenv("PRICE_ANOMALY_MAX_BIDDERS", "not_a_number")
    with caplog.at_level(logging.WARNING):
        cfg = load_anomaly_config()
    assert cfg.max_bidders == 50
    assert any("MAX_BIDDERS" in r.message for r in caplog.records)


def test_baseline_enabled_true_warns(monkeypatch, caplog) -> None:
    _clean_env(monkeypatch)
    monkeypatch.setenv("PRICE_ANOMALY_BASELINE_ENABLED", "true")
    with caplog.at_level(logging.WARNING):
        cfg = load_anomaly_config()
    assert cfg.baseline_enabled is True  # 读到值但 run 不会用
    assert any(
        "baseline path not implemented" in r.message for r in caplog.records
    )


def test_direction_override(monkeypatch) -> None:
    _clean_env(monkeypatch)
    monkeypatch.setenv("PRICE_ANOMALY_DIRECTION", "high")
    # 本期 config 仅读,运行期 detector 会 fallback + warn
    assert load_anomaly_config().direction == "high"
