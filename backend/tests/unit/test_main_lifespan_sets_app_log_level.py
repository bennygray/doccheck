"""L1 - main.py lifespan 顶部设 app logger level = INFO
(test-infra-followup-wave2 Item 4)。

llm-classifier-observability apply 期发现 uvicorn `--log-level info` 不级联到
`app.*` logger 子树,N3 采样时 info 日志取不到,靠 DB + warning 缺席反向推导。

修复:lifespan 顶部 `logging.getLogger("app").setLevel(logging.INFO)`,让整树默认 INFO;
handler 级仍由 uvicorn / prod config 控制(此处只改 logger level,不强推 info 到 handler)。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest

from app.main import app, lifespan


_MAIN_PY = Path(__file__).resolve().parents[2] / "app" / "main.py"


# ------------------------------------------------------------ 静态层


def test_lifespan_source_has_app_setlevel():
    """main.py lifespan 顶部必须有 `logging.getLogger("app").setLevel(logging.INFO)`。"""
    src = _MAIN_PY.read_text(encoding="utf-8")
    assert 'logging.getLogger("app").setLevel(logging.INFO)' in src, (
        "main.py::lifespan 未调用 logging.getLogger('app').setLevel(logging.INFO);"
        "uvicorn --log-level info 不级联到 app logger 子树(Item 4)"
    )


def test_lifespan_setlevel_wrapped_in_try_except():
    """setLevel 必须 try/except 兜底,logging 未就绪不阻塞 lifespan 启动。"""
    src = _MAIN_PY.read_text(encoding="utf-8")
    idx = src.find('logging.getLogger("app").setLevel(logging.INFO)')
    assert idx >= 0
    # 向上扫最多 5 行找 try,向下扫最多 5 行找 except
    before = src[:idx].rsplit("\n", 6)[-1::-1]
    assert any("try:" in ln for ln in before[:6]), (
        "setLevel 必须放在 try 块里(logging 失败不阻塞启动)"
    )
    after = src[idx:].split("\n", 6)[1:7]
    assert any(
        "except" in ln and ("Exception" in ln or ":" in ln)
        for ln in after
    ), "setLevel 必须有 except 兜底"


# ------------------------------------------------------------ 运行期层


@pytest.mark.asyncio
async def test_lifespan_actually_sets_app_logger_level_to_info(monkeypatch):
    """真跑一次 lifespan enter,确认 `app` logger level == INFO。

    禁用 lifespan 内的 DB 依赖 startup task(seed/scanner/admin-llm bootstrap)
    让本 test 纯后端单测不起库。
    """
    # 先强制设成 WARNING,确认随后 lifespan 真的把它改回 INFO
    logging.getLogger("app").setLevel(logging.WARNING)
    assert logging.getLogger("app").level == logging.WARNING

    # 跳过 DB 相关 startup
    monkeypatch.setenv("INFRA_DISABLE_LIFECYCLE", "1")
    monkeypatch.setenv("INFRA_DISABLE_EXPORT_CLEANUP", "1")
    monkeypatch.setenv("INFRA_DISABLE_SEED", "1")
    monkeypatch.setenv("INFRA_DISABLE_SCANNER", "1")

    # 用 patch 把 admin-llm-config bootstrap 里的 DB 调用吞掉(它没 env 开关)
    from app.services.admin import llm_reader as _llm_reader_mod

    async def _fake_read_llm_config(s):
        raise RuntimeError("skipped in test")  # 被 lifespan 的 try/except 吞

    monkeypatch.setattr(
        _llm_reader_mod, "read_llm_config", _fake_read_llm_config
    )

    async with lifespan(app):
        # enter 之后断言
        assert logging.getLogger("app").level == logging.INFO, (
            "lifespan 未把 app logger level 设为 INFO"
        )
