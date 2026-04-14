"""L1 - detect/engine 单元测试 (C6 §9.3)

- CPU_EXECUTOR lazy 初始化 + shutdown
- detect_disabled 环境变量读取
"""

from __future__ import annotations

import os

from app.services.detect import engine as engine_mod
from app.services.detect.engine import (
    detect_disabled,
    get_cpu_executor,
    shutdown_cpu_executor,
)


def test_cpu_executor_lazy_init():
    # 重置
    engine_mod._CPU_EXECUTOR = None

    assert engine_mod._CPU_EXECUTOR is None
    ex = get_cpu_executor()
    assert ex is not None
    assert engine_mod._CPU_EXECUTOR is ex

    # 二次调返同一实例
    ex2 = get_cpu_executor()
    assert ex is ex2

    # shutdown 清理
    shutdown_cpu_executor()
    assert engine_mod._CPU_EXECUTOR is None


def test_detect_disabled_default_false(monkeypatch):
    monkeypatch.delenv("INFRA_DISABLE_DETECT", raising=False)
    assert detect_disabled() is False


def test_detect_disabled_true(monkeypatch):
    monkeypatch.setenv("INFRA_DISABLE_DETECT", "1")
    assert detect_disabled() is True


def test_detect_disabled_non_one_still_false(monkeypatch):
    monkeypatch.setenv("INFRA_DISABLE_DETECT", "0")
    assert detect_disabled() is False

    monkeypatch.setenv("INFRA_DISABLE_DETECT", "true")
    # 只有精确 "1" 才算禁用(契约一致,与其他 INFRA_DISABLE_*)
    assert detect_disabled() is False


def test_env_float_overrides(monkeypatch):
    # 重新 import 以触发 _env_float
    monkeypatch.setenv("AGENT_TIMEOUT_S", "0.5")
    # 已经加载的模块,常量冻结在导入时;这里验证 _env_float 逻辑
    from app.services.detect.engine import _env_float

    assert _env_float("AGENT_TIMEOUT_S", 300.0) == 0.5
    assert _env_float("NONEXISTENT_VAR_XYZ", 42.0) == 42.0
