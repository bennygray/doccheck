"""pytest 全局配置 - C1 infra-base

- 加载共享 fixtures(LLM mock 等)
- 配置 asyncio 自动模式(pyproject.toml 已配 asyncio_mode=auto,此处留空即可)
- harden-async-infra N5:testdb 容器化,e2e 测试 MUST 指向 TEST_DATABASE_URL

IMPORTANT:TEST_DATABASE_URL → DATABASE_URL 覆盖 MUST 在 module 顶层执行,
因为 `pytest_plugins = [...]` 会在 `pytest_configure` **之前** import fixture
文件(auth_fixtures.py 里 `from app.db.session import async_session` 会立刻
实例化 `Settings()`),此时若 DATABASE_URL 还没覆盖,settings 就锁死在 dev DB URL。
"""

from __future__ import annotations

import os
import sys

# ---- harden-async-infra N5:TEST_DATABASE_URL → DATABASE_URL 前置覆盖 ----
# 只在 e2e 路径触发(通过 sys.argv 粗判),避免影响 L1 单元测试运行。


def _wants_e2e() -> bool:
    argv_joined = " ".join(sys.argv).replace("\\", "/")
    return "tests/e2e" in argv_joined


if _wants_e2e():
    _test_db_url = os.environ.get("TEST_DATABASE_URL")
    if not _test_db_url:
        # 无法用 pytest.exit(还没进 pytest lifecycle);用 SystemExit(2) 等价
        sys.stderr.write(
            "TEST_DATABASE_URL not set. "
            "Run `docker-compose -f docker-compose.test.yml up -d` then "
            "`export TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres"
            "@localhost:55432/documentcheck_test`\n"
        )
        raise SystemExit(2)
    # 前置覆盖,确保后续 fixture import 时 Settings 读到 testdb URL
    os.environ["DATABASE_URL"] = _test_db_url


pytest_plugins = [
    "tests.fixtures.llm_mock",
    "tests.fixtures.auth_fixtures",
]
