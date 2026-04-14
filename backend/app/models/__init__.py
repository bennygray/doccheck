"""SQLAlchemy 模型注册入口。

每次新增模型后 import 一下,确保 Base.metadata 在 alembic 环境里能见到。
"""

from app.models.agent_task import AgentTask  # noqa: F401
from app.models.analysis_report import AnalysisReport  # noqa: F401
from app.models.async_task import AsyncTask  # noqa: F401
from app.models.bid_document import BidDocument  # noqa: F401
from app.models.bidder import Bidder  # noqa: F401
from app.models.document_image import DocumentImage  # noqa: F401
from app.models.document_metadata import DocumentMetadata  # noqa: F401
from app.models.document_sheet import DocumentSheet  # noqa: F401
from app.models.document_text import DocumentText  # noqa: F401
from app.models.overall_analysis import OverallAnalysis  # noqa: F401
from app.models.pair_comparison import PairComparison  # noqa: F401
from app.models.price_config import ProjectPriceConfig  # noqa: F401
from app.models.price_item import PriceItem  # noqa: F401
from app.models.price_parsing_rule import PriceParsingRule  # noqa: F401
from app.models.project import Project  # noqa: F401
from app.models.user import User  # noqa: F401

__all__ = [
    "AgentTask",
    "AnalysisReport",
    "AsyncTask",
    "BidDocument",
    "Bidder",
    "DocumentImage",
    "DocumentMetadata",
    "DocumentSheet",
    "DocumentText",
    "OverallAnalysis",
    "PairComparison",
    "PriceItem",
    "PriceParsingRule",
    "Project",
    "ProjectPriceConfig",
    "User",
]
