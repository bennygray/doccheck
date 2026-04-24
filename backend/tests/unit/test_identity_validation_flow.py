"""L1:identity_validator.apply_identity_validation DB 层行为(parser-accuracy-fixes P0-1)

4 场景:
- LLM 与规则一致 → 保留 LLM,无 _llm_original,role_confidence 不降级
- LLM 与规则不一致 → 规则覆盖 + _llm_original 审计 + role_confidence 全 low
- 规则未命中 → 保留 LLM
- LLM 缺 company_full_name 但规则命中 → rule 值补齐,无 _llm_original
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session
from app.models.bid_document import BidDocument
from app.models.bidder import Bidder
from app.models.document_text import DocumentText
from app.models.project import Project
from app.models.user import User
from app.services.parser.identity_validator import apply_identity_validation


# 使用前缀 "iv_" 和上面 rc_ 前缀隔离,不互相污染
_PREFIX = "iv_"


async def _seed(
    session: AsyncSession,
    docx_body_text: str | None,
    llm_identity: dict | None,
) -> int:
    user = User(
        username=f"{_PREFIX}{id(session)}",
        password_hash="x",
        role="reviewer",
        login_fail_count=0,
    )
    session.add(user)
    await session.flush()
    project = Project(name="P", owner_id=user.id)
    session.add(project)
    await session.flush()
    bidder = Bidder(
        name="B",
        project_id=project.id,
        parse_status="identified",
        identity_info=llm_identity,
    )
    session.add(bidder)
    await session.flush()
    # 2 份 docx,body 首段装 docx_body_text(若非 None)
    for i in range(2):
        bd = BidDocument(
            bidder_id=bidder.id,
            file_name=f"doc{i}.docx",
            file_path=f"/tmp/iv_{i}_{id(session)}",
            file_size=100,
            file_type=".docx",
            md5=(f"iv{i:02d}" + str(id(session))[-10:] + "x" * 30)[:32],
            source_archive="a.zip",
            parse_status="identified",
            file_role="technical",
            role_confidence="high",
        )
        session.add(bd)
        await session.flush()
        if docx_body_text is not None and i == 0:
            session.add(
                DocumentText(
                    bid_document_id=bd.id,
                    paragraph_index=0,
                    text=docx_body_text,
                    location="body",
                )
            )
    # xlsx 一份,无 body 文本(rule 不该扫 xlsx)
    bdx = BidDocument(
        bidder_id=bidder.id,
        file_name="price.xlsx",
        file_path=f"/tmp/iv_x_{id(session)}",
        file_size=100,
        file_type=".xlsx",
        md5=("ivxx" + str(id(session))[-10:] + "x" * 30)[:32],
        source_archive="a.zip",
        parse_status="identified",
        file_role="pricing",
        role_confidence="high",
    )
    session.add(bdx)
    await session.commit()
    return bidder.id


@pytest_asyncio.fixture
async def clean_iv():
    """清本测试 seed 的行(前缀 iv_)。"""
    async def _purge():
        async with async_session() as session:
            user_ids = (
                await session.execute(
                    select(User.id).where(User.username.like(f"{_PREFIX}%"))
                )
            ).scalars().all()
            if not user_ids:
                return
            project_ids = (
                await session.execute(
                    select(Project.id).where(Project.owner_id.in_(user_ids))
                )
            ).scalars().all()
            bidder_ids = (
                (
                    await session.execute(
                        select(Bidder.id).where(
                            Bidder.project_id.in_(project_ids)
                        )
                    )
                ).scalars().all()
                if project_ids
                else []
            )
            doc_ids = (
                (
                    await session.execute(
                        select(BidDocument.id).where(
                            BidDocument.bidder_id.in_(bidder_ids)
                        )
                    )
                ).scalars().all()
                if bidder_ids
                else []
            )
            if doc_ids:
                await session.execute(
                    delete(DocumentText).where(
                        DocumentText.bid_document_id.in_(doc_ids)
                    )
                )
                await session.execute(
                    delete(BidDocument).where(BidDocument.id.in_(doc_ids))
                )
            if bidder_ids:
                await session.execute(
                    delete(Bidder).where(Bidder.id.in_(bidder_ids))
                )
            if project_ids:
                await session.execute(
                    delete(Project).where(Project.id.in_(project_ids))
                )
            await session.execute(
                delete(User).where(User.id.in_(user_ids))
            )
            await session.commit()

    await _purge()
    yield
    await _purge()


async def _reload(bidder_id: int) -> tuple[dict | None, list[str | None]]:
    async with async_session() as session:
        bidder = await session.get(Bidder, bidder_id)
        docs = (
            await session.execute(
                select(BidDocument.role_confidence).where(
                    BidDocument.bidder_id == bidder_id
                ).order_by(BidDocument.id)
            )
        ).scalars().all()
        return (bidder.identity_info if bidder else None), list(docs)


@pytest.mark.asyncio
async def test_llm_rule_match_keep_llm(clean_iv):
    """LLM 与规则一致(或子串) → 保留 LLM,不写 _llm_original,role_confidence 不降级"""
    async with async_session() as s:
        bid_id = await _seed(
            s,
            docx_body_text="投标人(盖章):  攀钢集团工科工程咨询有限公司",
            llm_identity={"company_full_name": "攀钢集团工科工程咨询有限公司"},
        )
    async with async_session() as s:
        await apply_identity_validation(s, bid_id)
        await s.commit()
    info, confs = await _reload(bid_id)
    assert info == {"company_full_name": "攀钢集团工科工程咨询有限公司"}
    assert "_llm_original" not in info
    assert confs == ["high", "high", "high"]  # 未降级


@pytest.mark.asyncio
async def test_llm_rule_mismatch_override_and_audit(clean_iv):
    """LLM 与规则不一致 → 规则覆盖 + _llm_original 审计 + role_confidence 全 low"""
    async with async_session() as s:
        bid_id = await _seed(
            s,
            docx_body_text="投标人(盖章):  攀钢集团工科工程咨询有限公司",
            llm_identity={"company_full_name": "锂源(江苏)科技有限公司"},
        )
    async with async_session() as s:
        await apply_identity_validation(s, bid_id)
        await s.commit()
    info, confs = await _reload(bid_id)
    assert info["company_full_name"] == "攀钢集团工科工程咨询有限公司"
    # M5:审计字段写入
    assert info["_llm_original"] == "锂源(江苏)科技有限公司"
    # 该 bidder 所有 docx/xlsx 的 role_confidence 降级 low
    assert confs == ["low", "low", "low"]


@pytest.mark.asyncio
async def test_rule_unmatched_keep_llm(clean_iv):
    """规则未命中(body 无"投标人盖章"锚点)→ 保留 LLM,不写 _llm_original,不降级"""
    async with async_session() as s:
        bid_id = await _seed(
            s,
            docx_body_text="本公司提交本次投标文件。",  # 无"投标人盖章"
            llm_identity={"company_full_name": "某公司"},
        )
    async with async_session() as s:
        await apply_identity_validation(s, bid_id)
        await s.commit()
    info, confs = await _reload(bid_id)
    assert info == {"company_full_name": "某公司"}
    assert "_llm_original" not in info
    assert confs == ["high", "high", "high"]


@pytest.mark.asyncio
async def test_llm_empty_rule_matched_fill_not_downgrade(clean_iv):
    """H1 review 修:LLM 缺 company_full_name 但规则命中 → 补齐,不降级 role_confidence

    spec 契约:"LLM 未返 identity_info ... role_confidence 维持 LLM 原判
    (因为是补齐不是纠正)"。此 case 断言 confs 保持 high(不降 low)。
    """
    async with async_session() as s:
        bid_id = await _seed(
            s,
            docx_body_text="投标人(盖章):  江苏省华厦工程项目管理有限公司",
            llm_identity={"project_manager": "张三"},  # 无 company_full_name
        )
    async with async_session() as s:
        await apply_identity_validation(s, bid_id)
        await s.commit()
    info, confs = await _reload(bid_id)
    assert info["company_full_name"] == "江苏省华厦工程项目管理有限公司"
    assert info["project_manager"] == "张三"
    # LLM 原值为空 → _llm_original 不写入(无原值可审计)
    assert "_llm_original" not in info
    # H1 修:补齐路径不降级 role_confidence
    assert confs == ["high", "high", "high"]


@pytest.mark.asyncio
async def test_llm_substring_of_rule_is_match(clean_iv):
    """LLM 返简称,规则返全称 → 子串一致,保留 LLM"""
    async with async_session() as s:
        bid_id = await _seed(
            s,
            docx_body_text="投标人(盖章):  浙江华建工程监理有限公司",
            llm_identity={
                "company_full_name": "浙江华建",
                "company_short_name": "华建",
            },
        )
    async with async_session() as s:
        await apply_identity_validation(s, bid_id)
        await s.commit()
    info, confs = await _reload(bid_id)
    assert info["company_full_name"] == "浙江华建"  # 保留 LLM
    assert "_llm_original" not in info
    assert confs == ["high", "high", "high"]
