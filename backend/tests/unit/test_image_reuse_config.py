"""L1 - image_impl/config (C13)"""

from __future__ import annotations

import logging

import pytest

from app.services.detect.agents.image_impl.config import (
    ImageReuseConfig,
    load_config,
)

_ENV_KEYS = [
    "IMAGE_REUSE_ENABLED",
    "IMAGE_REUSE_PHASH_DISTANCE_THRESHOLD",
    "IMAGE_REUSE_MIN_WIDTH",
    "IMAGE_REUSE_MIN_HEIGHT",
    "IMAGE_REUSE_MAX_PAIRS",
]


def _clean_env(monkeypatch):
    for k in _ENV_KEYS:
        monkeypatch.delenv(k, raising=False)


def test_defaults(monkeypatch) -> None:
    _clean_env(monkeypatch)
    assert load_config() == ImageReuseConfig()


def test_env_enabled_false(monkeypatch) -> None:
    _clean_env(monkeypatch)
    monkeypatch.setenv("IMAGE_REUSE_ENABLED", "false")
    assert load_config().enabled is False


def test_phash_distance_boundary_lo(monkeypatch) -> None:
    _clean_env(monkeypatch)
    monkeypatch.setenv("IMAGE_REUSE_PHASH_DISTANCE_THRESHOLD", "0")
    assert load_config().phash_distance_threshold == 0


def test_phash_distance_boundary_hi(monkeypatch) -> None:
    _clean_env(monkeypatch)
    monkeypatch.setenv("IMAGE_REUSE_PHASH_DISTANCE_THRESHOLD", "64")
    assert load_config().phash_distance_threshold == 64


def test_phash_distance_out_of_range_raises(monkeypatch) -> None:
    _clean_env(monkeypatch)
    monkeypatch.setenv("IMAGE_REUSE_PHASH_DISTANCE_THRESHOLD", "128")
    with pytest.raises(ValueError, match=r"\[0, 64\]"):
        load_config()


def test_min_width_zero_raises(monkeypatch) -> None:
    _clean_env(monkeypatch)
    monkeypatch.setenv("IMAGE_REUSE_MIN_WIDTH", "0")
    with pytest.raises(ValueError, match="must be positive"):
        load_config()


def test_min_height_negative_raises(monkeypatch) -> None:
    _clean_env(monkeypatch)
    monkeypatch.setenv("IMAGE_REUSE_MIN_HEIGHT", "-5")
    with pytest.raises(ValueError, match="must be positive"):
        load_config()


def test_max_pairs_lenient_invalid_fallback(monkeypatch, caplog) -> None:
    _clean_env(monkeypatch)
    monkeypatch.setenv("IMAGE_REUSE_MAX_PAIRS", "not_a_number")
    with caplog.at_level(logging.WARNING):
        cfg = load_config()
    assert cfg.max_pairs == 10000
    assert any("MAX_PAIRS" in r.message for r in caplog.records)
