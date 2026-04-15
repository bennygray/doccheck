"""L1 - price_impl/config (C11)"""

from __future__ import annotations

import pytest

from app.services.detect.agents.price_impl.config import load_price_config


def _clear_env(monkeypatch):
    for key in list(__import__("os").environ.keys()):
        if key.startswith("PRICE_CONSISTENCY_"):
            monkeypatch.delenv(key, raising=False)


def test_default_values(monkeypatch):
    _clear_env(monkeypatch)
    cfg = load_price_config()
    assert cfg.tail.tail_n == 3
    assert cfg.tail.enabled is True
    assert cfg.amount_pattern.threshold == 0.5
    assert cfg.item_list.threshold == 0.95
    assert cfg.series.ratio_variance_max == 0.001
    assert cfg.series.diff_cv_max == 0.01
    assert cfg.series.min_pairs == 3
    assert cfg.scorer.weights == {
        "tail": 0.25, "amount_pattern": 0.25, "item_list": 0.3, "series": 0.2
    }
    assert all(cfg.scorer.enabled[k] for k in ("tail", "amount_pattern", "item_list", "series"))
    assert cfg.max_rows_per_bidder == 5000
    assert cfg.scorer.ironclad_threshold == 85.0


def test_env_overrides(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("PRICE_CONSISTENCY_TAIL_N", "4")
    monkeypatch.setenv("PRICE_CONSISTENCY_ITEM_LIST_THRESHOLD", "0.8")
    monkeypatch.setenv("PRICE_CONSISTENCY_SERIES_MIN_PAIRS", "5")
    cfg = load_price_config()
    assert cfg.tail.tail_n == 4
    assert cfg.item_list.threshold == 0.8
    assert cfg.series.min_pairs == 5


def test_subdim_weights_parse(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("PRICE_CONSISTENCY_SUBDIM_WEIGHTS", "0.2,0.2,0.4,0.2")
    cfg = load_price_config()
    assert cfg.scorer.weights == {
        "tail": 0.2, "amount_pattern": 0.2, "item_list": 0.4, "series": 0.2
    }


def test_subdim_weights_parse_failure_fallback(monkeypatch, caplog):
    _clear_env(monkeypatch)
    # 5 个值,期望 4 个 → fallback
    monkeypatch.setenv("PRICE_CONSISTENCY_SUBDIM_WEIGHTS", "0.1,0.1,0.1,0.1,0.6")
    with caplog.at_level("WARNING"):
        cfg = load_price_config()
    assert cfg.scorer.weights == {
        "tail": 0.25, "amount_pattern": 0.25, "item_list": 0.3, "series": 0.2
    }
    assert any("PRICE_CONSISTENCY_SUBDIM_WEIGHTS" in rec.message for rec in caplog.records)


def test_subdim_weights_negative_fallback(monkeypatch, caplog):
    _clear_env(monkeypatch)
    monkeypatch.setenv("PRICE_CONSISTENCY_SUBDIM_WEIGHTS", "0.5,-0.1,0.3,0.3")
    with caplog.at_level("WARNING"):
        cfg = load_price_config()
    # 负值 fallback 默认
    assert cfg.scorer.weights["tail"] == 0.25


@pytest.mark.parametrize(
    "key,value,attr_path",
    [
        ("PRICE_CONSISTENCY_TAIL_ENABLED", "false", ("tail", "enabled")),
        ("PRICE_CONSISTENCY_AMOUNT_PATTERN_ENABLED", "0",
         ("amount_pattern", "enabled")),
        ("PRICE_CONSISTENCY_ITEM_LIST_ENABLED", "off", ("item_list", "enabled")),
        ("PRICE_CONSISTENCY_SERIES_ENABLED", "no", ("series", "enabled")),
    ],
)
def test_enabled_bool_parse(monkeypatch, key, value, attr_path):
    _clear_env(monkeypatch)
    monkeypatch.setenv(key, value)
    cfg = load_price_config()
    obj = cfg
    for a in attr_path:
        obj = getattr(obj, a)
    assert obj is False


def test_numeric_threshold_parse_failure_fallback(monkeypatch, caplog):
    _clear_env(monkeypatch)
    monkeypatch.setenv("PRICE_CONSISTENCY_ITEM_LIST_THRESHOLD", "not_a_number")
    with caplog.at_level("WARNING"):
        cfg = load_price_config()
    assert cfg.item_list.threshold == 0.95  # fallback


def test_negative_int_fallback(monkeypatch, caplog):
    _clear_env(monkeypatch)
    monkeypatch.setenv("PRICE_CONSISTENCY_TAIL_N", "-1")
    with caplog.at_level("WARNING"):
        cfg = load_price_config()
    assert cfg.tail.tail_n == 3  # fallback
