"""L1 - C9 structure_sim_impl.config"""

from __future__ import annotations

import pytest

from app.services.detect.agents.structure_sim_impl import config


def test_defaults(monkeypatch):
    for var in (
        "STRUCTURE_SIM_MIN_CHAPTERS",
        "STRUCTURE_SIM_MIN_SHEET_ROWS",
        "STRUCTURE_SIM_WEIGHTS",
        "STRUCTURE_SIM_FIELD_JACCARD_SUB_WEIGHTS",
        "STRUCTURE_SIM_MAX_ROWS_PER_SHEET",
    ):
        monkeypatch.delenv(var, raising=False)
    assert config.min_chapters() == 3
    assert config.min_sheet_rows() == 2
    assert config.weights() == (0.4, 0.3, 0.3)
    assert config.field_sub_weights() == (0.4, 0.3, 0.3)
    assert config.max_rows_per_sheet() == 5000


def test_env_override(monkeypatch):
    monkeypatch.setenv("STRUCTURE_SIM_MIN_CHAPTERS", "5")
    monkeypatch.setenv("STRUCTURE_SIM_MIN_SHEET_ROWS", "3")
    monkeypatch.setenv("STRUCTURE_SIM_WEIGHTS", "0.5,0.25,0.25")
    monkeypatch.setenv(
        "STRUCTURE_SIM_FIELD_JACCARD_SUB_WEIGHTS", "0.6,0.2,0.2"
    )
    monkeypatch.setenv("STRUCTURE_SIM_MAX_ROWS_PER_SHEET", "1000")
    assert config.min_chapters() == 5
    assert config.min_sheet_rows() == 3
    assert config.weights() == (0.5, 0.25, 0.25)
    assert config.field_sub_weights() == (0.6, 0.2, 0.2)
    assert config.max_rows_per_sheet() == 1000


@pytest.mark.parametrize(
    "bad",
    ["abc,def,ghi", "0.5,0.5", "0.4,0.3,0.3,0.0", "-1,0.5,0.5", "0,0,0"],
)
def test_weights_invalid_fallback(monkeypatch, bad):
    monkeypatch.setenv("STRUCTURE_SIM_WEIGHTS", bad)
    assert config.weights() == (0.4, 0.3, 0.3)


def test_max_rows_invalid_fallback(monkeypatch):
    monkeypatch.setenv("STRUCTURE_SIM_MAX_ROWS_PER_SHEET", "xxx")
    assert config.max_rows_per_sheet() == 5000
    monkeypatch.setenv("STRUCTURE_SIM_MAX_ROWS_PER_SHEET", "-10")
    assert config.max_rows_per_sheet() == 5000
