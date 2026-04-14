"""SQLAlchemy 模型注册入口。

每次新增模型后 import 一下,确保 Base.metadata 在 alembic 环境里能见到。
"""

from app.models.bid_document import BidDocument  # noqa: F401
from app.models.bidder import Bidder  # noqa: F401
from app.models.price_config import ProjectPriceConfig  # noqa: F401
from app.models.price_parsing_rule import PriceParsingRule  # noqa: F401
from app.models.project import Project  # noqa: F401
from app.models.user import User  # noqa: F401

__all__ = [
    "BidDocument",
    "Bidder",
    "PriceParsingRule",
    "Project",
    "ProjectPriceConfig",
    "User",
]
