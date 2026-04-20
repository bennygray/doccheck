"""backfill system_configs.config.llm default section

Revision ID: 0010_llm_default
Revises: 0009_system_config
Create Date: 2026-04-20

admin-llm-config:
- 给已存在 id=1 的 SystemConfig 行补 llm 子段默认值
- 已有 llm 键则跳过(幂等)
- 无需改表结构
"""

from __future__ import annotations

import json

from alembic import op
from sqlalchemy import text


# revision identifiers
revision = "0010_llm_default"
down_revision = "0009_system_config"
branch_labels = None
depends_on = None


DEFAULT_LLM = {
    "provider": "dashscope",
    "api_key": "",
    "model": "qwen-plus",
    "base_url": None,
    "timeout_s": 30,
}


def upgrade() -> None:
    bind = op.get_bind()
    # 读 id=1 行;若无则跳过(新库里由 0009 已插入)
    row = bind.execute(
        text("SELECT config FROM system_configs WHERE id = 1")
    ).fetchone()
    if row is None:
        return
    config = row[0]
    # JSONB 列在 postgres 直接返回 dict;SQLite JSON 返字符串
    if isinstance(config, str):
        config = json.loads(config)
    if not isinstance(config, dict):
        # 异常数据,安全起见不动
        return
    if "llm" in config:
        # 已有 llm 段,幂等跳过
        return
    config["llm"] = DEFAULT_LLM
    bind.execute(
        text("UPDATE system_configs SET config = :config WHERE id = 1"),
        {"config": json.dumps(config)},
    )


def downgrade() -> None:
    bind = op.get_bind()
    row = bind.execute(
        text("SELECT config FROM system_configs WHERE id = 1")
    ).fetchone()
    if row is None:
        return
    config = row[0]
    if isinstance(config, str):
        config = json.loads(config)
    if not isinstance(config, dict) or "llm" not in config:
        return
    del config["llm"]
    bind.execute(
        text("UPDATE system_configs SET config = :config WHERE id = 1"),
        {"config": json.dumps(config)},
    )
