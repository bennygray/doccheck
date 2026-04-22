"""LLM 配置读取器 (admin-llm-config)

三层回退优先级 (Q4):DB > env > 代码默认值。

- read_llm_config(db):返 dataclass,含 provider/api_key/model/base_url/timeout_s/source
- write_llm_config(db, payload, actor_id):写 SystemConfig + audit_log + 失效 factory cache
- mask_api_key(raw):末 4 位保留,短 key 全脱敏
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.system_config import SystemConfig
from app.services.admin.rules_defaults import DEFAULT_RULES_CONFIG


LLMSource = Literal["db", "env", "default"]


@dataclass(frozen=True)
class LLMConfig:
    """有效 LLM 运行期配置(含来源标识)。"""

    provider: str
    api_key: str
    model: str
    base_url: str | None
    timeout_s: int
    source: LLMSource

    def fingerprint(self) -> tuple[str, str, str, str | None, int]:
        """用于 factory cache 的 key,排除 source(来源不影响 provider 行为)。"""
        return (self.provider, self.api_key, self.model, self.base_url, self.timeout_s)


def _default_llm_config() -> dict[str, Any]:
    """代码默认(from rules_defaults.DEFAULT_RULES_CONFIG.llm)。"""
    return DEFAULT_RULES_CONFIG["llm"]


def _from_env() -> dict[str, Any]:
    """从 pydantic settings(env)构造。"""
    return {
        "provider": settings.llm_provider,
        "api_key": settings.llm_api_key,
        "model": settings.llm_model,
        "base_url": settings.llm_base_url,
        "timeout_s": int(settings.llm_timeout_s),
    }


def _has_meaningful_values(llm_dict: dict[str, Any]) -> bool:
    """判定 DB 的 llm 段是否"有值可用"——provider + model 都非空即算。"""
    provider = (llm_dict.get("provider") or "").strip()
    model = (llm_dict.get("model") or "").strip()
    return bool(provider) and bool(model)


async def read_llm_config(session: AsyncSession) -> LLMConfig:
    """按 Q4 三层优先级读取 LLM 配置。

    DB llm 段存在且有 provider+model → source="db"
    否则 → env 且 api_key 非空(或 provider 非默认) → source="env"
    否则 → source="default"
    """
    stmt = select(SystemConfig).where(SystemConfig.id == 1)
    row = (await session.execute(stmt)).scalar_one_or_none()

    db_llm: dict[str, Any] | None = None
    if row is not None and isinstance(row.config, dict):
        candidate = row.config.get("llm")
        if isinstance(candidate, dict) and _has_meaningful_values(candidate):
            db_llm = candidate

    if db_llm is not None:
        return LLMConfig(
            provider=db_llm.get("provider", "dashscope"),
            api_key=db_llm.get("api_key", "") or "",
            model=db_llm.get("model", "qwen-plus"),
            base_url=db_llm.get("base_url"),
            timeout_s=int(db_llm.get("timeout_s", 30)),
            source="db",
        )

    # env 回退判定:env api_key 非空 or provider 已显式设置
    env_d = _from_env()
    if env_d["api_key"]:
        return LLMConfig(
            provider=env_d["provider"],
            api_key=env_d["api_key"],
            model=env_d["model"],
            base_url=env_d["base_url"],
            timeout_s=env_d["timeout_s"],
            source="env",
        )

    # 代码默认
    d = _default_llm_config()
    return LLMConfig(
        provider=d["provider"],
        api_key=d["api_key"] or "",
        model=d["model"],
        base_url=d["base_url"],
        timeout_s=int(d["timeout_s"]),
        source="default",
    )


def mask_api_key(raw: str | None) -> str:
    """api_key 脱敏 (Q2):末 4 位保留,短于 8 位或空时固定占位。"""
    if not raw:
        return ""
    if len(raw) < 8:
        return "sk-****"
    return f"{raw[:3]}****{raw[-4:]}"


async def write_llm_config(
    session: AsyncSession,
    payload: dict[str, Any],
    actor_id: int | None,
) -> LLMConfig:
    """把 payload 写入 SystemConfig.config.llm,失效 factory cache。

    payload 允许字段:provider / api_key / model / base_url / timeout_s
    - api_key 为空/缺失时保持旧值(Req-3 场景 2)
    - base_url 允许显式设 null(即用 provider 默认)
    """
    stmt = select(SystemConfig).where(SystemConfig.id == 1)
    row = (await session.execute(stmt)).scalar_one_or_none()

    # 旧配置(用于 "api_key 空保持旧值" + audit before)
    old_cfg: LLMConfig = await read_llm_config(session)

    new_llm: dict[str, Any] = {
        "provider": payload.get("provider", old_cfg.provider),
        "model": payload.get("model", old_cfg.model),
        "base_url": payload.get("base_url") if "base_url" in payload else old_cfg.base_url,
        "timeout_s": int(payload.get("timeout_s", old_cfg.timeout_s)),
    }
    new_key = payload.get("api_key")
    if new_key:
        new_llm["api_key"] = new_key
    else:
        new_llm["api_key"] = old_cfg.api_key

    if row is None:
        # 理论上 0009 migration 已插入 id=1,但防御性处理:新建
        full_config = dict(DEFAULT_RULES_CONFIG)
        full_config["llm"] = new_llm
        row = SystemConfig(id=1, config=full_config, updated_by=actor_id)
        session.add(row)
    else:
        # SQLAlchemy 对 JSON/JSONB 字段的 in-place 修改不一定触发脏检测;
        # 拷贝再整体赋值才稳
        current = dict(row.config) if isinstance(row.config, dict) else dict(DEFAULT_RULES_CONFIG)
        current["llm"] = new_llm
        row.config = current
        row.updated_by = actor_id

    await session.flush()

    # 失效 factory cache(lazy import 避免循环)
    try:
        from app.services.llm.factory import invalidate_provider_cache

        invalidate_provider_cache()
    except Exception:  # noqa: BLE001
        # cache 失效不能阻塞写入
        pass

    # 同步 runtime settings:让旧 get_llm_provider()(同步签名,读 settings.llm_*)
    # 也能立刻拿到新值。不这样做的话,pipeline/11 个 Agent 仍走旧 env 配置。
    try:
        settings.llm_provider = new_llm["provider"]
        settings.llm_api_key = new_llm["api_key"]
        settings.llm_model = new_llm["model"]
        settings.llm_base_url = new_llm["base_url"]
        settings.llm_timeout_s = float(new_llm["timeout_s"])
    except Exception:  # noqa: BLE001 — settings 赋值异常不阻塞主流程
        pass

    # 注:admin_llm 配置更新不写 audit_log,
    # 因 AuditLog.project_id 非空(C15 设计),系统级配置不挂项目。
    # 设计 follow-up:AuditLog project_id 改 nullable,或新建 SystemAuditLog 表。

    # 重新读一遍,返 dataclass(包含 source)
    return await read_llm_config(session)
