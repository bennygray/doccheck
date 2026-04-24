"""error_consistency L-5 LLM 调用 (C13)

按 spec §L-5:输入候选可疑段落 + 双方 bidder 名,
返 {is_cross_contamination, direct_evidence, evidence[], confidence}。

所有 LLM 失败(provider=None / LLMResult.error / JSON 解析错)→ 返 None,
让上层走兜底路径(仅展示关键词命中,不铁证,标 "AI 研判暂不可用")。
重试机制按 cfg.llm_max_retries(含 0)。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.services.detect.agents.error_impl.config import ErrorConsistencyConfig
from app.services.detect.agents.error_impl.models import (
    LLMJudgment,
    SuspiciousSegment,
)
from app.services.llm.base import LLMProvider, Message

logger = logging.getLogger(__name__)


_SYSTEM_PROMPT = (
    "你是围标检测专家。下面给你两个投标人 A、B 之间的可疑段落,"
    "段落中含 A 或 B 的标识关键词(公司名/人员/资质号)出现在对方文档里。"
    "请判断这些段落是否构成「真正的交叉污染」(如:A 标书出现 B 的项目经理姓名"
    "未提公司名 / 共用罕见错别字 / 引用同一项目案例但措辞不同等)。"
    "返回严格 JSON,不允许任何解释文字、markdown 标记。"
    "schema:{\"is_cross_contamination\":bool,\"direct_evidence\":bool,"
    "\"confidence\":float,\"evidence\":[{\"type\":string,\"snippet\":string,\"position\":string}]}"
)


def _build_user_prompt(
    segments: list[SuspiciousSegment],
    bidder_a_name: str,
    bidder_b_name: str,
) -> str:
    seg_lines = []
    for i, seg in enumerate(segments):
        seg_lines.append(
            f"[{i + 1}] 来源关键词={seg['source_bidder_id']} 位置={seg['position']} "
            f"命中关键词={','.join(seg['matched_keywords'])} "
            f"段落={seg['paragraph_text'][:300]}"
        )
    return (
        f"投标人 A:{bidder_a_name}\n投标人 B:{bidder_b_name}\n"
        f"可疑段落({len(segments)} 条):\n" + "\n".join(seg_lines)
    )


def _parse_response(text: str) -> LLMJudgment | None:
    """JSON 解析容错。失败返 None。"""
    s = text.strip()
    if not s:
        return None
    # 容错:剥 markdown ```json ... ```
    if s.startswith("```"):
        s = s.strip("`")
        if s.lower().startswith("json"):
            s = s[4:].strip()
    try:
        data = json.loads(s)
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    judgment: LLMJudgment = {
        "is_cross_contamination": bool(data.get("is_cross_contamination", False)),
        "direct_evidence": bool(data.get("direct_evidence", False)),
        "confidence": float(data.get("confidence", 0.0)),
        "evidence": data.get("evidence", []) if isinstance(data.get("evidence"), list) else [],
    }
    return judgment


async def call_l5(
    provider: LLMProvider | None,
    segments: list[SuspiciousSegment],
    bidder_a_name: str,
    bidder_b_name: str,
    cfg: ErrorConsistencyConfig,
) -> LLMJudgment | None:
    """调 L-5 LLM,返 LLMJudgment;失败返 None。

    重试 cfg.llm_max_retries 次;每次 JSON 解析失败也算"失败"消费 1 次重试名额。
    provider=None 直接返 None(LLM 未配置 / 测试 mock 注入)。
    """
    if provider is None:
        return None
    if not segments:
        return None

    messages: list[Message] = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": _build_user_prompt(
                segments, bidder_a_name, bidder_b_name
            ),
        },
    ]

    attempts = cfg.llm_max_retries + 1  # 首次 + 重试
    last_error: Any = None
    last_kind: str = "other"
    for i in range(attempts):
        result = await provider.complete(messages, temperature=0.0)
        if not result.ok:
            last_error = result.error
            last_kind = result.error.kind if result.error else "other"
            logger.warning(
                "L-5 attempt %d/%d failed kind=%s msg=%s",
                i + 1, attempts, last_kind,
                result.error.message if result.error else "",
            )
            continue
        judgment = _parse_response(result.text)
        if judgment is not None:
            return judgment
        last_error = "json_parse_failed"
        last_kind = "bad_response"
        logger.warning("L-5 attempt %d/%d JSON parse failed", i + 1, attempts)

    # harden-async-infra N7:error_consistency agent 有本地兜底(segs-based pair_score),
    # 符合 "有兜底则保留" 规则 — 此处返 None 保持原行为,仅日志精细化 last_kind。
    # 当前 kind 可作为 N3 explore 的根因统计信号。
    logger.warning(
        "L-5 all %d attempts failed last_kind=%s last_error=%s",
        attempts, last_kind, last_error,
    )
    return None


__all__ = ["call_l5"]
