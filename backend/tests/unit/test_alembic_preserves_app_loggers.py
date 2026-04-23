"""L1 - alembic upgrade 不 disable 应用 logger 回归防御 (test-infra-followup-wave2 Item 1)。

根因:`alembic/env.py` 默认 `fileConfig(config_file)` 会 disable 所有非白名单 logger
(`root/sqlalchemy/alembic`)。llm-classifier-observability apply 期 recon 锁定此 bug
导致 L2 `test_xlsx_truncates_oversized_sheet` 的 caplog 丢警告。

修复后 `env.py:27` 显式传 `disable_existing_loggers=False`。本文件静态 + 运行期双重
防护,防未来回退(例如误删关键参数 / 换 fileConfig 回归 dictConfig 默认 True 等)。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest


# ------------------------------------------------------------ 静态层(不起 DB)

_ENV_PY = Path(__file__).resolve().parents[2] / "alembic" / "env.py"


def test_env_py_passes_disable_existing_loggers_false():
    """源码层断言:alembic/env.py 必须显式传 disable_existing_loggers=False。"""
    src = _ENV_PY.read_text(encoding="utf-8")
    assert "fileConfig(" in src, "env.py 不再调用 fileConfig?测试失效"
    # 允许任何参数顺序,只要显式带 disable_existing_loggers=False
    assert "disable_existing_loggers=False" in src, (
        "alembic/env.py::fileConfig 未显式传 disable_existing_loggers=False。"
        "这会让 L2 session fixture alembic upgrade head 静默 disable 所有 app logger,"
        "导致 caplog 类测试静默失败(见 test-infra-followup-wave2 Item 1 根因)。"
    )


# ------------------------------------------------------------ 运行期层(需 DB)


APP_LOGGER_NAMES = [
    "app.services.parser.content",
    "app.services.detect.engine",
    "app.services.llm.openai_compat",
    "app.services.parser.llm.role_classifier",
    "app.startup",
]


def _testdb_url() -> str | None:
    return os.environ.get("TEST_DATABASE_URL")


@pytest.mark.skipif(
    _testdb_url() is None,
    reason="需要 TEST_DATABASE_URL 才能跑 alembic upgrade head",
)
@pytest.mark.parametrize("logger_name", APP_LOGGER_NAMES)
def test_alembic_upgrade_does_not_disable_app_logger(
    logger_name: str, monkeypatch
):
    """运行期:预先 prime logger → 跑 alembic upgrade head → assert 未被 disable。"""
    # prime logger 使其被 Python logging 系统注册
    lg = logging.getLogger(logger_name)
    lg.warning("prime %s", logger_name)
    assert lg.disabled is False, f"{logger_name} prime 后已被 disable?基线异常"

    # 让 alembic 用 test DB URL
    monkeypatch.setenv("DATABASE_URL", _testdb_url())

    from alembic import command
    from alembic.config import Config

    alembic_ini = (
        Path(__file__).resolve().parents[2] / "alembic.ini"
    )
    cfg = Config(str(alembic_ini))
    command.upgrade(cfg, "head")

    after = logging.getLogger(logger_name)
    assert after.disabled is False, (
        f"alembic upgrade head 后 {logger_name} 被 disabled = True;"
        "env.py 的 disable_existing_loggers=False 未生效?"
    )
