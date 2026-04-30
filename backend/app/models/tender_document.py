"""TenderDocument 模型 (detect-tender-baseline D1)

每条记录 = 招标方下发的一份招标文件(项目级 1..N)。

设计要点(详见 openspec/changes/detect-tender-baseline/design.md D1):
- 独立表,**不**走 BidDocument(避免污染 18 个消费方)
- 项目级 1..N,FK 到 projects.id
- 项目内 md5 unique 去重
- 软删除(deleted_at);软删后 baseline_resolver MUST NOT 读取(参 file-upload spec)
- parse_status: pending / parsing / extracted / failed;failed 走 fail-soft 不阻塞 detector
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# parse_status 枚举(应用层校验,不加 DB CHECK,与 BidDocument 风格一致)
PARSE_STATUS_VALUES = frozenset({"pending", "parsing", "extracted", "failed"})


class TenderDocument(Base):
    __tablename__ = "tender_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id"), nullable=False
    )
    file_name: Mapped[str] = mapped_column(String(500), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    md5: Mapped[str] = mapped_column(String(32), nullable=False)
    # pending | parsing | extracted | failed
    parse_status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="pending", default="pending"
    )
    parse_error: Mapped[str | None] = mapped_column(
        String(500), nullable=True, default=None
    )
    # detect-tender-baseline apply 简化决策:tender 段 hash 集合直接存 JSONB,
    # 不污染 DocumentText 表(避免给 bid_document_id 加 nullable + CHECK 双 FK 复杂度)。
    # 第一性原理:baseline_resolver 只需 hash 集合做剔除比对,UI 不展示 tender 段原文。
    # 解析完成后填充;parse_status='extracted' 才有效;'failed' 时为空数组。
    segment_hashes: Mapped[list[str]] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"),
        nullable=False,
        server_default="[]",
        default=list,
    )
    # BOQ 项级 hash 集合,sha256(项目名+描述+单位+Decimal.normalize(工程量))
    boq_baseline_hashes: Mapped[list[str]] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"),
        nullable=False,
        server_default="[]",
        default=list,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # 软删除标记:NULL=活跃;非 NULL=已软删,baseline_resolver MUST 跳过
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )

    __table_args__ = (
        # 项目内 md5 去重(D1 决策,与 BidDocument 项目+投标人维度去重对齐)
        UniqueConstraint(
            "project_id", "md5", name="uq_tender_documents_project_md5"
        ),
        # baseline_resolver 加载场景:WHERE project_id=? AND parse_status='extracted' AND deleted_at IS NULL
        Index(
            "ix_tender_documents_project_status",
            "project_id",
            "parse_status",
            "deleted_at",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return (
            f"<TenderDocument id={self.id} project={self.project_id} "
            f"name={self.file_name!r} status={self.parse_status} "
            f"deleted={self.deleted_at is not None}>"
        )


__all__ = ["TenderDocument", "PARSE_STATUS_VALUES"]
