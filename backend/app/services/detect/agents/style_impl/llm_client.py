"""style L-8 两阶段 LLM (C13)

Stage1: 每 bidder 1 次调用 → 风格特征摘要(用词偏好/句式/标点/段落组织)
Stage2: 全局 1 次调用 → 风格高度一致 bidder 组合列表

任一阶段失败返 None,让上层走 Agent skip 哨兵。
重试机制按 cfg.llm_max_retries。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.services.detect.agents.style_impl.config import StyleConfig
from app.services.detect.agents.style_impl.models import (
    GlobalComparison,
    StyleFeatureBrief,
)
from app.services.llm.base import LLMProvider, Message

logger = logging.getLogger(__name__)


_STAGE1_SYSTEM = (
    "你是文档语言风格分析专家。给定某投标人的若干代表性段落,"
    "提取该投标人的写作风格特征。返回严格 JSON,不允许任何解释或 markdown。"
    'schema:{"用词偏好":string,"句式特点":string,"标点习惯":string,"段落组织":string}'
)

_STAGE2_SYSTEM = (
    "你是文档语言风格比对专家。给定多个投标人的风格特征摘要(已不含原文),"
    "找出风格高度一致的 bidder 组合(可能多组)。返回严格 JSON。"
    'schema:{"consistent_groups":[{"bidder_ids":[int],"consistency_score":float,'
    '"typical_features":string}]}'
)


def _build_stage1_user(paragraphs: list[str]) -> str:
    body = "\n\n".join(f"[段{i + 1}] {p}" for i, p in enumerate(paragraphs))
    return f"投标人的代表性段落({len(paragraphs)} 段):\n\n{body}"


def _build_stage2_user(briefs: dict[int, StyleFeatureBrief]) -> str:
    lines = []
    for bid, brief in briefs.items():
        lines.append(
            f"bidder_id={bid}: 用词={brief.get('用词偏好', '')} | "
            f"句式={brief.get('句式特点', '')} | "
            f"标点={brief.get('标点习惯', '')} | "
            f"段落={brief.get('段落组织', '')}"
        )
    return f"投标人风格摘要({len(briefs)} 家):\n" + "\n".join(lines)


def _strip_md(text: str) -> str:
    s = text.strip()
    if s.startswith("```"):
        s = s.strip("`")
        if s.lower().startswith("json"):
            s = s[4:].strip()
    return s


def _parse_stage1(text: str) -> StyleFeatureBrief | None:
    try:
        data = json.loads(_strip_md(text))
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return {
        "用词偏好": str(data.get("用词偏好", "")),
        "句式特点": str(data.get("句式特点", "")),
        "标点习惯": str(data.get("标点习惯", "")),
        "段落组织": str(data.get("段落组织", "")),
    }


def _parse_stage2(text: str) -> GlobalComparison | None:
    try:
        data = json.loads(_strip_md(text))
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    raw_groups = data.get("consistent_groups", [])
    if not isinstance(raw_groups, list):
        return None
    groups = []
    for g in raw_groups:
        if not isinstance(g, dict):
            continue
        bidder_ids = g.get("bidder_ids", [])
        if not isinstance(bidder_ids, list):
            continue
        groups.append(
            {
                "bidder_ids": [int(b) for b in bidder_ids if isinstance(b, (int, str)) and str(b).lstrip("-").isdigit()],
                "consistency_score": float(g.get("consistency_score", 0.0)),
                "typical_features": str(g.get("typical_features", "")),
            }
        )
    return {"consistent_groups": groups}  # type: ignore[typeddict-item]


async def _call_with_retry_and_parse(
    provider: LLMProvider,
    messages: list[Message],
    retries: int,
    parser,
):
    """共享重试调用 + 解析。返解析结果或 None(全部失败)。

    LLM 调用失败 OR 解析失败都消费一次重试名额(贴 L-5 行为)。
    """
    attempts = retries + 1
    for i in range(attempts):
        result = await provider.complete(messages, temperature=0.0)
        if result.ok:
            parsed = parser(result.text)
            if parsed is not None:
                return parsed
            logger.warning(
                "L-8 attempt %d/%d parse failed", i + 1, attempts
            )
        else:
            logger.warning(
                "L-8 attempt %d/%d failed: %s",
                i + 1,
                attempts,
                result.error,
            )
    return None


async def call_l8_stage1(
    provider: LLMProvider | None,
    bidder_id: int,
    paragraphs: list[str],
    cfg: StyleConfig,
) -> StyleFeatureBrief | None:
    if provider is None or not paragraphs:
        return None
    messages: list[Message] = [
        {"role": "system", "content": _STAGE1_SYSTEM},
        {"role": "user", "content": _build_stage1_user(paragraphs)},
    ]
    return await _call_with_retry_and_parse(
        provider, messages, cfg.llm_max_retries, _parse_stage1
    )


async def call_l8_stage2(
    provider: LLMProvider | None,
    briefs: dict[int, StyleFeatureBrief],
    cfg: StyleConfig,
) -> GlobalComparison | None:
    if provider is None or not briefs:
        return None
    messages: list[Message] = [
        {"role": "system", "content": _STAGE2_SYSTEM},
        {"role": "user", "content": _build_stage2_user(briefs)},
    ]
    return await _call_with_retry_and_parse(
        provider, messages, cfg.llm_max_retries, _parse_stage2
    )


__all__ = ["call_l8_stage1", "call_l8_stage2"]
