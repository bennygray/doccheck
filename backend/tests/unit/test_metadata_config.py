"""L1 - metadata_impl/config (C10)"""

from __future__ import annotations

from app.services.detect.agents.metadata_impl.config import (
    load_author_config,
    load_machine_config,
    load_time_config,
)


def test_defaults(monkeypatch) -> None:
    for k in [
        "METADATA_AUTHOR_ENABLED",
        "METADATA_TIME_ENABLED",
        "METADATA_MACHINE_ENABLED",
        "METADATA_TIME_CLUSTER_WINDOW_MIN",
        "METADATA_AUTHOR_SUBDIM_WEIGHTS",
        "METADATA_TIME_SUBDIM_WEIGHTS",
        "METADATA_IRONCLAD_THRESHOLD",
        "METADATA_MAX_HITS_PER_AGENT",
    ]:
        monkeypatch.delenv(k, raising=False)

    ac = load_author_config()
    assert ac.enabled is True
    assert ac.subdim_weights == {"author": 0.5, "last_saved_by": 0.3, "company": 0.2}
    assert ac.ironclad_threshold == 85.0
    assert ac.max_hits_per_agent == 50

    tc = load_time_config()
    assert tc.enabled is True
    assert tc.window_min == 5
    assert tc.subdim_weights == {"modified_at_cluster": 0.7, "created_at_match": 0.3}

    mc = load_machine_config()
    assert mc.enabled is True


def test_enabled_false_variations(monkeypatch) -> None:
    for raw, expected in [
        ("false", False),
        ("FALSE", False),
        ("0", False),
        ("no", False),
        ("off", False),
        ("true", True),
        ("1", True),
        ("anything", True),
    ]:
        monkeypatch.setenv("METADATA_AUTHOR_ENABLED", raw)
        assert load_author_config().enabled == expected, raw


def test_window_min_override(monkeypatch) -> None:
    monkeypatch.setenv("METADATA_TIME_CLUSTER_WINDOW_MIN", "30")
    assert load_time_config().window_min == 30


def test_window_min_invalid_falls_back(monkeypatch) -> None:
    monkeypatch.setenv("METADATA_TIME_CLUSTER_WINDOW_MIN", "abc")
    assert load_time_config().window_min == 5
    monkeypatch.setenv("METADATA_TIME_CLUSTER_WINDOW_MIN", "-1")
    assert load_time_config().window_min == 5


def test_author_weights_override(monkeypatch) -> None:
    monkeypatch.setenv("METADATA_AUTHOR_SUBDIM_WEIGHTS", "0.4,0.4,0.2")
    ac = load_author_config()
    assert ac.subdim_weights == {
        "author": 0.4,
        "last_saved_by": 0.4,
        "company": 0.2,
    }


def test_author_weights_invalid_falls_back(monkeypatch) -> None:
    monkeypatch.setenv("METADATA_AUTHOR_SUBDIM_WEIGHTS", "abc,xyz")
    ac = load_author_config()
    assert ac.subdim_weights == {"author": 0.5, "last_saved_by": 0.3, "company": 0.2}


def test_author_weights_wrong_count_falls_back(monkeypatch) -> None:
    monkeypatch.setenv("METADATA_AUTHOR_SUBDIM_WEIGHTS", "0.5,0.5")  # 只 2 个
    ac = load_author_config()
    assert ac.subdim_weights == {"author": 0.5, "last_saved_by": 0.3, "company": 0.2}


def test_ironclad_threshold_override(monkeypatch) -> None:
    monkeypatch.setenv("METADATA_IRONCLAD_THRESHOLD", "90")
    assert load_author_config().ironclad_threshold == 90.0
    assert load_time_config().ironclad_threshold == 90.0
    assert load_machine_config().ironclad_threshold == 90.0
