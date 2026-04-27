"""L-9 LLM 综合研判 (C14 detect-llm-judge)

三函数平铺,judge.py 内部 import:
- summarize(pcs, oas, per_dim_max, ironclad_dims, ...) -> dict  预聚合摘要
- call_llm_judge(summary, formula_total, provider, cfg) -> (conclusion, suggested_total)  LLM 调用
- fallback_conclusion(final_total, final_level, per_dim_max, ironclad_dims) -> str  降级模板

设计约定(来自 openspec/changes/detect-llm-judge/design.md):
- LLM 输入走预聚合摘要,不喂 raw evidence_json(token 爆炸)
- 失败判据统一返 (None, None),由调用方走降级
- 降级模板前缀固定 "AI 综合研判暂不可用",前端前缀 match 识别降级态
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass

from app.services.llm.base import LLMProvider, Message

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------- Config ----

FALLBACK_PREFIX = "AI 综合研判暂不可用"

# honest-detection-results D1: 信号型 agent 白名单
# 这些 agent 的 score=0 表示"真的没算出信号",算进证据充分性判定分母
# 不在此集合的 agent (metadata_* / price_consistency) score=0 表示"查了没发现异常",
# 不代表"无信号",不进分母 — 避免干净项目被误标 indeterminate
SIGNAL_AGENTS: frozenset[str] = frozenset({
    "text_similarity",
    "section_similarity",
    "structure_similarity",
    "image_reuse",
    "style",
    "error_consistency",
})

INSUFFICIENT_EVIDENCE_CONCLUSION = "证据不足,无法判定围标风险(有效信号维度全部为零)"


def _has_sufficient_evidence(
    agent_tasks,
    pair_comparisons,
    overall_analyses,
    *,
    adjusted_pcs: dict[int, dict] | None = None,
    adjusted_oas: dict[int, dict] | None = None,
) -> bool:
    """honest-detection-results D1:证据充分性判定。

    CH-2 detect-template-exclusion:扩 keyword-only `adjusted_pcs / adjusted_oas`
    可选参数(向后兼容,默认 None 时行为完全不变)。

    Step 1 铁证短路:任一 PC.is_ironclad(adjusted) 或 OA.has_iron_evidence(adjusted)
        → True;avoid agent.score=0 但铁证存在时产出 total_score=85 + indeterminate 矛盾

    Step 2 信号判定:
        - 老路径(adjusted 全 None):AgentTask.score 分母 + 过滤 succeeded + SIGNAL_AGENTS
        - 新路径(任一 adjusted dict 非 None):OA.score 分母,过滤 SIGNAL_AGENTS 维度
          OA + adjusted-or-raw score>0
    """
    use_adjusted = adjusted_pcs is not None or adjusted_oas is not None
    apcs = adjusted_pcs or {}
    aoas = adjusted_oas or {}

    # Step 1:铁证短路(读 adjusted iron 优先,缺失回落 raw)
    for pc in pair_comparisons or []:
        adj = apcs.get(pc.id) if use_adjusted else None
        iron = (
            adj["is_ironclad"]
            if adj is not None and "is_ironclad" in adj
            else pc.is_ironclad
        )
        if iron:
            return True
    for oa in overall_analyses or []:
        adj = aoas.get(oa.id) if use_adjusted else None
        if adj is not None and "has_iron_evidence" in adj:
            has_iron = adj["has_iron_evidence"]
        else:
            ev = getattr(oa, "evidence_json", None) or {}
            has_iron = (
                isinstance(ev, dict) and ev.get("has_iron_evidence") is True
            )
        if has_iron:
            return True

    if use_adjusted:
        # Step 2 新路径:OA.score 分母(SIGNAL_AGENTS 维度 OA score>0)
        for oa in overall_analyses or []:
            if oa.dimension not in SIGNAL_AGENTS:
                continue
            adj = aoas.get(oa.id)
            if adj is not None and "score" in adj:
                score = float(adj["score"])
            else:
                score = float(oa.score) if oa.score is not None else 0.0
            if score > 0:
                return True
        return False

    # Step 2 老路径:AgentTask.score 分母
    signals = [
        t for t in (agent_tasks or [])
        if t.status == "succeeded" and t.agent_name in SIGNAL_AGENTS
    ]
    if not signals:
        return False
    return any(
        (float(t.score) if t.score is not None else 0.0) > 0
        for t in signals
    )


@dataclass(frozen=True)
class LLMJudgeConfig:
    """L-9 LLM 综合研判配置,env 命名空间 LLM_JUDGE_*"""

    enabled: bool = True
    timeout_s: int = 30
    max_retry: int = 2
    summary_top_k: int = 3
    model: str = ""  # 空 = 使用 LLM 客户端默认;非空留 follow-up


def _env_bool(key: str, default: bool) -> bool:
    raw = os.environ.get(key, "").strip().lower()
    if not raw:
        return default
    if raw in ("true", "1", "yes", "on"):
        return True
    if raw in ("false", "0", "no", "off"):
        return False
    logger.warning("%s parse failed %r — fallback %s", key, raw, default)
    return default


def _env_int_lenient(
    key: str, default: int, *, lo: int, hi: int
) -> int:
    raw = os.environ.get(key, "").strip()
    if not raw:
        return default
    try:
        v = int(raw)
    except ValueError:
        logger.warning("%s parse failed %r — fallback %s", key, raw, default)
        return default
    if v < lo or v > hi:
        logger.warning(
            "%s must be in [%s, %s], got %s — fallback %s",
            key,
            lo,
            hi,
            raw,
            default,
        )
        return default
    return v


def load_llm_judge_config() -> LLMJudgeConfig:
    """从 env 读配置,非法值 fallback default + warn log(宽松风格,贴 C11/C12)"""
    return LLMJudgeConfig(
        enabled=_env_bool("LLM_JUDGE_ENABLED", True),
        timeout_s=_env_int_lenient("LLM_JUDGE_TIMEOUT_S", 30, lo=1, hi=300),
        max_retry=_env_int_lenient("LLM_JUDGE_MAX_RETRY", 2, lo=0, hi=5),
        summary_top_k=_env_int_lenient(
            "LLM_JUDGE_SUMMARY_TOP_K", 3, lo=1, hi=20
        ),
        model=os.environ.get("LLM_JUDGE_MODEL", "").strip(),
    )


# ------------------------------------------------------------- Summarize ----


_DIM_ORDER = [
    "text_similarity",
    "section_similarity",
    "structure_similarity",
    "metadata_author",
    "metadata_time",
    "metadata_machine",
    "price_consistency",
    "price_anomaly",
    "error_consistency",
    "style",
    "image_reuse",
]

_EVIDENCE_BRIEF_MAX = 200


def _shape_evidence_brief(evidence_json: object) -> str:
    """从 evidence_json 抽关键字段拼短字符串(≤200 字)

    策略:
    - 非 dict → 空串
    - 取 skip_reason / matched_keywords / direct_evidence / llm_explanation 等关键字段
    - 无关键字段 → 前几对 key:value 的 repr,截断 200 字
    """
    if not isinstance(evidence_json, dict):
        return ""

    preferred_keys = [
        "skip_reason",
        "direct_evidence",
        "has_iron_evidence",
        "llm_explanation",
        "matched_keywords",
        "mean_price",
        "md5_match_count",
        "phash_match_count",
        "participating_subdims",
        "participating_fields",
        "participating_dimensions",
        "group_count",
    ]
    parts: list[str] = []
    for k in preferred_keys:
        if k not in evidence_json:
            continue
        v = evidence_json[k]
        if v is None or v == "" or v == [] or v == {}:
            continue
        if isinstance(v, list):
            v_str = ",".join(str(x) for x in v[:5])
            if len(v) > 5:
                v_str += "..."
        else:
            v_str = str(v)
        parts.append(f"{k}={v_str}")
        if sum(len(p) + 2 for p in parts) > _EVIDENCE_BRIEF_MAX:
            break

    brief = "; ".join(parts)
    if len(brief) > _EVIDENCE_BRIEF_MAX:
        brief = brief[: _EVIDENCE_BRIEF_MAX - 3] + "..."
    return brief


def _is_pc_ironclad(
    pc,
    *,
    adjusted_pcs: dict[int, dict] | None = None,
) -> bool:
    """CH-2:adjusted_pcs 非 None 时优先读 adjusted is_ironclad。"""
    if adjusted_pcs is not None:
        adj = adjusted_pcs.get(pc.id)
        if adj is not None and "is_ironclad" in adj:
            return bool(adj["is_ironclad"])
    return bool(getattr(pc, "is_ironclad", False))


def _is_oa_ironclad(
    oa,
    *,
    adjusted_oas: dict[int, dict] | None = None,
) -> bool:
    """CH-2:adjusted_oas 非 None 时优先读 adjusted has_iron_evidence。"""
    if adjusted_oas is not None:
        adj = adjusted_oas.get(oa.id)
        if adj is not None and "has_iron_evidence" in adj:
            return bool(adj["has_iron_evidence"])
    ev = getattr(oa, "evidence_json", None) or {}
    return isinstance(ev, dict) and ev.get("has_iron_evidence") is True


def summarize(
    pcs,
    oas,
    per_dim_max: dict[str, float],
    ironclad_dims: list[str],
    *,
    formula_total: float,
    formula_level: str,
    has_ironclad: bool,
    project_info: dict | None = None,
    top_k: int = 3,
    adjusted_pcs: dict[int, dict] | None = None,
    adjusted_oas: dict[int, dict] | None = None,
) -> dict:
    """预聚合结构化摘要(token 稳定 3~8k),喂给 L-9 LLM

    规则:
    - 覆盖 13 维度(哪怕 skip 也列出,top_k_examples=[])
    - top_k 按 score 倒序;铁证 pair/OA 无条件入 top_k(哪怕不在前 k)
    - global 型 Agent 的 top_k_examples 仅 1 条 OA 摘要(bidder_a/b 填 "全局")
    """
    # 按 dim 分桶 pair_comparisons + overall_analyses
    pc_by_dim: dict[str, list] = {}
    oa_by_dim: dict[str, list] = {}
    for pc in pcs:
        pc_by_dim.setdefault(pc.dimension, []).append(pc)
    for oa in oas:
        oa_by_dim.setdefault(oa.dimension, []).append(oa)

    dimensions: dict[str, dict] = {}
    ironclad_dim_set = set(ironclad_dims)
    for dim in _DIM_ORDER:
        pc_list = pc_by_dim.get(dim, [])
        oa_list = oa_by_dim.get(dim, [])

        # skip_reason 从 OA evidence_json 透出(global 型)或 pair 的第一行(兜底)
        skip_reason = None
        enabled = True
        for oa in oa_list:
            ev = getattr(oa, "evidence_json", None) or {}
            if isinstance(ev, dict):
                if ev.get("enabled") is False:
                    enabled = False
                    skip_reason = ev.get("skip_reason") or "disabled"
                elif ev.get("skip_reason"):
                    skip_reason = ev["skip_reason"]

        # participating_bidders(从 pc.bidder_a_id/bidder_b_id 去重)
        bidders: set = set()
        for pc in pc_list:
            if getattr(pc, "bidder_a_id", None) is not None:
                bidders.add(pc.bidder_a_id)
            if getattr(pc, "bidder_b_id", None) is not None:
                bidders.add(pc.bidder_b_id)

        # ironclad_count(CH-2:消费 adjusted dict)
        ironclad_count = sum(
            1 for pc in pc_list if _is_pc_ironclad(pc, adjusted_pcs=adjusted_pcs)
        )
        ironclad_count += sum(
            1 for oa in oa_list if _is_oa_ironclad(oa, adjusted_oas=adjusted_oas)
        )

        # top_k_examples
        examples: list[dict] = []
        if pc_list:
            # pair 型:score 倒序取 top_k + 铁证 pair 无条件入
            # CH-2:_pc_score 是 nested function,inline 处理 adjusted dict 兜底
            def _pc_score(pc):
                if adjusted_pcs is not None:
                    adj = adjusted_pcs.get(pc.id)
                    if adj is not None and "score" in adj:
                        return float(adj["score"])
                s = getattr(pc, "score", None)
                return float(s) if s is not None else 0.0

            sorted_pcs = sorted(pc_list, key=_pc_score, reverse=True)
            picked = list(sorted_pcs[:top_k])
            picked_ids = {id(pc) for pc in picked}
            # 铁证无条件入(不在 top_k 时追加)
            for pc in sorted_pcs:
                if _is_pc_ironclad(pc, adjusted_pcs=adjusted_pcs) and id(pc) not in picked_ids:
                    picked.append(pc)
                    picked_ids.add(id(pc))

            for pc in picked:
                examples.append(
                    {
                        "bidder_a": getattr(pc, "bidder_a_id", None),
                        "bidder_b": getattr(pc, "bidder_b_id", None),
                        "score": _pc_score(pc),
                        "is_ironclad": _is_pc_ironclad(
                            pc, adjusted_pcs=adjusted_pcs
                        ),
                        "evidence_brief": _shape_evidence_brief(
                            getattr(pc, "evidence_json", None)
                        ),
                    }
                )
        elif oa_list:
            # global 型:填 1 条 OA 摘要(CH-2:消费 adjusted_oas)
            for oa in oa_list:
                if adjusted_oas is not None:
                    adj = adjusted_oas.get(oa.id)
                    if adj is not None and "score" in adj:
                        oa_score = float(adj["score"])
                    else:
                        s = getattr(oa, "score", None)
                        oa_score = float(s) if s is not None else 0.0
                else:
                    s = getattr(oa, "score", None)
                    oa_score = float(s) if s is not None else 0.0
                examples.append(
                    {
                        "bidder_a": "全局",
                        "bidder_b": "全局",
                        "score": oa_score,
                        "is_ironclad": _is_oa_ironclad(
                            oa, adjusted_oas=adjusted_oas
                        ),
                        "evidence_brief": _shape_evidence_brief(
                            getattr(oa, "evidence_json", None)
                        ),
                    }
                )

        dimensions[dim] = {
            "max_score": per_dim_max.get(dim),  # None 若维度完全缺失
            "ironclad_count": ironclad_count,
            "participating_bidders": sorted(bidders),
            "top_k_examples": examples,
            "skip_reason": skip_reason,
            "enabled": enabled,
        }

    return {
        "project": project_info or {},
        "formula": {
            "total": formula_total,
            "level": formula_level,
            "has_ironclad": has_ironclad,
            "ironclad_dimensions": list(ironclad_dim_set),
        },
        "dimensions": dimensions,
    }


# --------------------------------------------------------- Call LLM Judge ----


_JUDGE_SYSTEM = (
    "你是投标围标/串标综合研判专家。基于给定的 13 维度证据摘要和加权公式初步结论,"
    "产出一段自然语言的综合研判结论(≤200 字),并给出一个建议总分(suggested_total)。\n"
    "\n"
    "重要约束:\n"
    "1. suggested_total 必须在 [formula_total, 100] 区间内(只能升分,不能降)\n"
    "2. conclusion 不得以 'AI 综合研判暂不可用' 开头(该前缀保留给降级态)\n"
    "3. 必须返回严格 JSON,schema: "
    '{"suggested_total": float, "conclusion": string, "reasoning": string}\n'
    "4. 不允许任何 markdown、解释、代码块包裹"
)


def _strip_md(text: str) -> str:
    s = text.strip()
    if s.startswith("```"):
        s = s.strip("`")
        if s.lower().startswith("json"):
            s = s[4:].strip()
    return s


def _build_user_prompt(summary: dict, formula_total: float) -> str:
    summary_json = json.dumps(summary, ensure_ascii=False, default=str)
    return (
        f"加权公式初步总分 formula_total={formula_total}(级别 "
        f"{summary.get('formula', {}).get('level', 'unknown')})。\n\n"
        f"建议总分区间 [{formula_total}, 100]。\n\n"
        f"13 维度证据摘要(JSON):\n{summary_json}"
    )


def _parse_llm_judge(
    text: str, formula_total: float
) -> tuple[str, float] | None:
    """解析 LLM 返回 JSON,校验 schema。返回 (conclusion, suggested_total) 或 None。"""
    try:
        data = json.loads(_strip_md(text))
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None

    suggested = data.get("suggested_total")
    conclusion = data.get("conclusion")

    # 缺字段
    if suggested is None or conclusion is None:
        return None

    # conclusion 必须是非空字符串
    if not isinstance(conclusion, str) or not conclusion.strip():
        return None

    # suggested 必须是数字 + [0, 100] 内
    try:
        suggested_f = float(suggested)
    except (TypeError, ValueError):
        return None
    if suggested_f < 0.0 or suggested_f > 100.0:
        return None

    # 不允许以降级前缀开头(LLM 违反约束时视为失败)
    if conclusion.strip().startswith(FALLBACK_PREFIX):
        return None

    return conclusion.strip(), suggested_f


async def call_llm_judge(
    summary: dict,
    formula_total: float,
    *,
    provider: LLMProvider | None,
    cfg: LLMJudgeConfig | None = None,
) -> tuple[str | None, float | None]:
    """调 L-9 LLM,含 retry + JSON 解析容错。

    失败统一返 (None, None),调用方走降级分支。
    """
    if provider is None:
        logger.warning("L-9 provider is None, skip")
        return None, None
    cfg = cfg or load_llm_judge_config()

    messages: list[Message] = [
        {"role": "system", "content": _JUDGE_SYSTEM},
        {"role": "user", "content": _build_user_prompt(summary, formula_total)},
    ]

    attempts = cfg.max_retry + 1
    for i in range(attempts):
        result = await provider.complete(messages, temperature=0.0)
        if result.ok:
            parsed = _parse_llm_judge(result.text, formula_total)
            if parsed is not None:
                conclusion, suggested = parsed
                logger.info(
                    "L-9 attempt %d/%d ok: suggested=%s",
                    i + 1,
                    attempts,
                    suggested,
                )
                return conclusion, suggested
            logger.warning(
                "L-9 attempt %d/%d parse failed (text=%r)",
                i + 1,
                attempts,
                result.text[:200],
            )
        else:
            logger.warning(
                "L-9 attempt %d/%d failed: %s",
                i + 1,
                attempts,
                result.error,
            )
    return None, None


# ---------------------------------------------------- Fallback Conclusion ----


def _level_cn(level: str) -> str:
    return {"high": "高", "medium": "中", "low": "低"}.get(level, level)


def fallback_conclusion(
    final_total: float,
    final_level: str,
    per_dim_max: dict[str, float] | None,
    ironclad_dims: list[str] | None,
) -> str:
    """LLM 失败/降级时的结论模板。

    前缀固定 "AI 综合研判暂不可用"(前端前缀 match 识别降级态加 banner)。
    纯函数,输入为 None / 空 dict 时不抛异常。
    """
    per_dim_max = per_dim_max or {}
    ironclad_dims = ironclad_dims or []

    parts: list[str] = [
        f"{FALLBACK_PREFIX},以下为规则公式结论:",
        f"本项目加权总分 {final_total} 分,风险等级 {final_level}"
        f"({_level_cn(final_level)})。",
    ]

    # 铁证维度段(可选)
    if ironclad_dims:
        dims_str = "、".join(ironclad_dims)
        parts.append(f"铁证维度:{dims_str}(共 {len(ironclad_dims)} 项)。")

    # top 3 高分维度
    sorted_dims = sorted(
        (
            (dim, score)
            for dim, score in per_dim_max.items()
            if score is not None and score > 0
        ),
        key=lambda x: x[1],
        reverse=True,
    )
    top3 = sorted_dims[:3]
    if top3:
        top_str = "、".join(f"{dim} {score:g}" for dim, score in top3)
        parts.append(f"维度最高分:{top_str}。")

    # 建议关注(铁证优先 + top 高分 dedup)
    focus_dims: list[str] = []
    seen: set[str] = set()
    for dim in ironclad_dims:
        if dim not in seen:
            focus_dims.append(dim)
            seen.add(dim)
    for dim, _ in top3:
        if dim not in seen:
            focus_dims.append(dim)
            seen.add(dim)
    if focus_dims:
        parts.append(f"建议关注:{'、'.join(focus_dims[:5])}。")

    return "".join(parts)


__all__ = [
    "LLMJudgeConfig",
    "load_llm_judge_config",
    "summarize",
    "call_llm_judge",
    "fallback_conclusion",
    "FALLBACK_PREFIX",
]
