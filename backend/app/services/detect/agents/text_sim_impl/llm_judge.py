"""LLM 定性判定 (C7 detect-agent-text-similarity)

对齐 requirements §10.8 L-4;按 pair × doc_role 发一次 LLM 调用,
对超阈值段落对打 plagiarism / template / generic 标签。

降级触发:
- LLMResult.error 非空
- JSON 解析失败(初 + 重试 1 次)

降级行为返 ({}, None),调用方按"全部 None 权重 0.3"计分。
"""

from __future__ import annotations

import json
import logging
import re

from app.services.detect.agents.text_sim_impl.models import ParaPair
from app.services.llm.base import LLMProvider, Message

logger = logging.getLogger(__name__)

# 有效的 judgment 取值
_VALID_JUDGMENTS = frozenset({"plagiarism", "template", "generic"})
# 默认补齐标签(LLM 漏返时)
_DEFAULT_JUDGMENT = "generic"

_SYSTEM_PROMPT = (
    "你是围标文本抄袭检测专家。对下列两家投标人 A / B 的高相似段落对,"
    "判断每对属于以下三类之一:\n"
    "- template:行业模板雷同(双方都用了公开模板)\n"
    "- generic:行业通用表述(技术领域常见措辞)\n"
    "- plagiarism:同源抄袭(表述个性化、非通用,高度疑似同源)\n"
    "请仅返回 JSON,不要解释文本,不要加 markdown 代码块。"
)


def build_prompt(
    bidder_a_name: str,
    bidder_b_name: str,
    doc_role: str,
    pairs: list[ParaPair],
) -> list[Message]:
    """组装 L-4 prompt。每对段落按 idx 0..N-1 编号,LLM 返回必须带 idx 对齐。"""
    pair_payload = [
        {
            "idx": i,
            "a": p.a_text,
            "b": p.b_text,
            "sim": p.sim,
        }
        for i, p in enumerate(pairs)
    ]
    user_content = (
        f"投标人 A:{bidder_a_name}\n"
        f"投标人 B:{bidder_b_name}\n"
        f"文档角色:{doc_role}\n\n"
        "段落对列表(JSON):\n"
        f"{json.dumps(pair_payload, ensure_ascii=False)}\n\n"
        "请严格返回以下 JSON:\n"
        "{\n"
        '  "pairs": [\n'
        '    {"idx": 0, "judgment": "plagiarism|template|generic", "note": "说明"}\n'
        "  ],\n"
        '  "overall": "该 pair 整体结论(1-2 句)",\n'
        '  "confidence": "high|medium|low"\n'
        "}"
    )
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


_ParseResult = tuple[dict[int, str], dict | None]


def parse_response(text: str, pair_count: int) -> _ParseResult | None:
    """解析 LLM JSON 响应。

    返:
    - 成功: ({idx: judgment}, {"overall": str, "confidence": str})
    - 解析失败: None(调用方决定是否重试)

    段数不匹配(< pair_count)→ 缺失补 generic,不视为失败。
    """
    if not text or not text.strip():
        return None

    # 尝试 1:直接 json.loads
    data = _try_json_loads(text)
    if data is None:
        # 尝试 2:剥除 markdown code fence
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            data = _try_json_loads(m.group())
    if data is None:
        return None

    pairs_raw = data.get("pairs")
    if not isinstance(pairs_raw, list):
        return None

    judgments: dict[int, str] = {}
    for item in pairs_raw:
        if not isinstance(item, dict):
            continue
        idx = item.get("idx")
        judgment = item.get("judgment")
        if not isinstance(idx, int) or not isinstance(judgment, str):
            continue
        if judgment not in _VALID_JUDGMENTS:
            continue
        if 0 <= idx < pair_count:
            judgments[idx] = judgment

    # 漏返补齐
    for i in range(pair_count):
        judgments.setdefault(i, _DEFAULT_JUDGMENT)

    overall = data.get("overall")
    confidence = data.get("confidence")
    meta = {
        "overall": overall if isinstance(overall, str) else "",
        "confidence": confidence if isinstance(confidence, str) else "",
    }
    return judgments, meta


def _try_json_loads(text: str) -> dict | None:
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except (json.JSONDecodeError, ValueError):
        return None


async def call_llm_judge(
    provider: LLMProvider | None,
    bidder_a_name: str,
    bidder_b_name: str,
    doc_role: str,
    pairs: list[ParaPair],
) -> tuple[dict[int, str], dict | None]:
    """调 LLM 给段落对定性;失败返 ({}, None) 表示降级。

    provider 为 None(未注入)→ 直接降级,不调用。
    """
    if provider is None or not pairs:
        return {}, None

    messages = build_prompt(bidder_a_name, bidder_b_name, doc_role, pairs)

    # harden-async-infra N7:text_similarity 有本地 TF-IDF 兜底(agent 返 degraded
    # summary),符合"有兜底则保留"规则 — LLM 失败时返 ({}, None) 让 agent 走本地
    # 降级路径,**不**抛 AgentSkippedError。精细化日志供 N3 explore 分析根因。
    for attempt in range(2):  # 初次 + 1 次重试
        result = await provider.complete(messages)
        if result.error is not None:
            kind = result.error.kind
            logger.warning(
                "text_sim_llm_judge error attempt=%s kind=%s: %s",
                attempt, kind, result.error.message,
            )
            # 瞬态错误(bad_response / other)可能是解析抖动或未分类错,给 1 次重试机会;
            # 其余(timeout / rate_limit / auth / network)同一请求再试意义不大,直接降级
            if kind not in ("bad_response", "other"):
                return {}, None
            continue

        parsed = parse_response(result.text, len(pairs))
        if parsed is not None:
            judgments, meta = parsed
            return judgments, meta
        logger.warning(
            "text_sim_llm_judge parse failed attempt=%s text_head=%r",
            attempt,
            result.text[:200],
        )

    return {}, None


__all__ = ["build_prompt", "parse_response", "call_llm_judge"]
