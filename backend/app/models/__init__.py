"""SQLAlchemy 模型注册入口。

每次新增模型后 import 一下,确保 Base.metadata 在 alembic 环境里能见到。
"""

from app.models.user import User  # noqa: F401

__all__ = ["User"]
