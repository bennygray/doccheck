"""L1 - factory._cap_timeout + 两路径 cap 覆盖 (harden-async-infra N7 / H3 / M1)

验证:
- DB 路径 cap(admin 超 cap)
- DB 路径 cap(admin 低于 cap,保留)
- env 路径 cap(reviewer H3 回归)
- env override cap
- None/0/负数 防御(reviewer M1 回归)
"""

from __future__ import annotations

import pytest

from app.services.llm import factory as factory_mod


@pytest.fixture(autouse=True)
def _clear_cache():
    factory_mod.invalidate_provider_cache()
    yield
    factory_mod.invalidate_provider_cache()


# ---- _cap_timeout helper 单测 ----


class TestCapTimeoutHelper:
    def test_admin_larger_than_cap_capped(self, monkeypatch):
        monkeypatch.setattr(factory_mod.settings, "llm_call_timeout", 60.0)
        assert factory_mod._cap_timeout(600) == 60.0

    def test_admin_smaller_than_cap_preserved(self, monkeypatch):
        monkeypatch.setattr(factory_mod.settings, "llm_call_timeout", 60.0)
        assert factory_mod._cap_timeout(15) == 15.0

    def test_admin_equal_to_cap(self, monkeypatch):
        monkeypatch.setattr(factory_mod.settings, "llm_call_timeout", 60.0)
        assert factory_mod._cap_timeout(60) == 60.0

    def test_none_defends_to_cap(self, monkeypatch):
        """M1:admin_timeout=None → cap(不塌缩成 0)。"""
        monkeypatch.setattr(factory_mod.settings, "llm_call_timeout", 60.0)
        assert factory_mod._cap_timeout(None) == 60.0

    def test_zero_defends_to_cap(self, monkeypatch):
        """M1:admin_timeout=0 → cap(否则 asyncio.wait_for(0) 立即超时)。"""
        monkeypatch.setattr(factory_mod.settings, "llm_call_timeout", 60.0)
        assert factory_mod._cap_timeout(0) == 60.0

    def test_negative_defends_to_cap(self, monkeypatch):
        """M1:admin_timeout 负数 → cap。"""
        monkeypatch.setattr(factory_mod.settings, "llm_call_timeout", 60.0)
        assert factory_mod._cap_timeout(-5) == 60.0

    def test_env_overrides_cap(self, monkeypatch):
        """用户 `export LLM_CALL_TIMEOUT=30` 后,cap 降到 30。"""
        monkeypatch.setattr(factory_mod.settings, "llm_call_timeout", 30.0)
        assert factory_mod._cap_timeout(60) == 30.0
        assert factory_mod._cap_timeout(10) == 10.0


# ---- 两路径端到端 cap ----


class TestEnvPathCap:
    """H3 回归:env 路径 (get_llm_provider) 也过 cap。"""

    def test_env_timeout_over_cap_capped(self, monkeypatch):
        monkeypatch.setattr(factory_mod.settings, "llm_provider", "dashscope")
        monkeypatch.setattr(factory_mod.settings, "llm_api_key", "k")
        monkeypatch.setattr(factory_mod.settings, "llm_model", "m")
        monkeypatch.setattr(factory_mod.settings, "llm_base_url", None)
        monkeypatch.setattr(factory_mod.settings, "llm_timeout_s", 600.0)
        monkeypatch.setattr(factory_mod.settings, "llm_call_timeout", 60.0)

        provider = factory_mod.get_llm_provider()
        assert provider._timeout_s == 60.0, (
            f"env 路径 timeout 应被 cap 到 60,实际 {provider._timeout_s}"
        )

    def test_env_timeout_under_cap_preserved(self, monkeypatch):
        monkeypatch.setattr(factory_mod.settings, "llm_provider", "dashscope")
        monkeypatch.setattr(factory_mod.settings, "llm_api_key", "k")
        monkeypatch.setattr(factory_mod.settings, "llm_model", "m")
        monkeypatch.setattr(factory_mod.settings, "llm_base_url", None)
        monkeypatch.setattr(factory_mod.settings, "llm_timeout_s", 20.0)
        monkeypatch.setattr(factory_mod.settings, "llm_call_timeout", 60.0)

        provider = factory_mod.get_llm_provider()
        assert provider._timeout_s == 20.0


class TestDBPathCap:
    """DB 路径 (get_llm_provider_db) 也过 cap(与 env 路径对称)。"""

    @pytest.mark.asyncio
    async def test_db_timeout_over_cap_capped(self, monkeypatch):
        monkeypatch.setattr(factory_mod.settings, "llm_call_timeout", 60.0)

        # mock read_llm_config 返一个 timeout=600 的配置
        class _FakeCfg:
            provider = "dashscope"
            api_key = "k"
            model = "m"
            base_url = None
            timeout_s = 600

        async def _fake_read(_session):
            return _FakeCfg()

        import app.services.admin.llm_reader as llm_reader
        monkeypatch.setattr(llm_reader, "read_llm_config", _fake_read)

        provider = await factory_mod.get_llm_provider_db(session=None)  # type: ignore[arg-type]
        assert provider._timeout_s == 60.0

    @pytest.mark.asyncio
    async def test_db_timeout_none_defends_to_cap(self, monkeypatch):
        """M1:DB 路径 timeout_s=None(误配)→ cap,不塌缩。"""
        monkeypatch.setattr(factory_mod.settings, "llm_call_timeout", 60.0)

        class _FakeCfg:
            provider = "dashscope"
            api_key = "k"
            model = "m"
            base_url = None
            timeout_s = None  # 模拟 admin-llm-config DB 初始化 NULL

        async def _fake_read(_session):
            return _FakeCfg()

        import app.services.admin.llm_reader as llm_reader
        monkeypatch.setattr(llm_reader, "read_llm_config", _fake_read)

        provider = await factory_mod.get_llm_provider_db(session=None)  # type: ignore[arg-type]
        assert provider._timeout_s == 60.0, (
            f"DB None timeout 应 cap 到 60,实际 {provider._timeout_s}"
        )
