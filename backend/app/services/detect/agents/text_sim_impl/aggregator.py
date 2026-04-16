"""pair 级 score 汇总 + is_ironclad 判定 + evidence_json 构造 (C7)

对齐 design D4 + D7。
"""

from __future__ import annotations

from typing import Any

from app.services.detect.agents.text_sim_impl.models import ParaPair

# 段落级权重(judgment -> weight)
_WEIGHTS: dict[str | None, float] = {
    "plagiarism": 1.0,
    "template": 0.6,
    "generic": 0.2,
    None: 0.3,  # 降级模式(LLM 失败)全部按 None 权重
}

# is_ironclad 触发:plagiarism 段数 ≥ 绝对阈值 或 占比 ≥ 比例阈值
_IRONCLAD_ABS = 3
_IRONCLAD_RATIO = 0.5

# max + mean 混合权重
_MAX_WEIGHT = 0.7
_MEAN_WEIGHT = 0.3

# evidence_json.samples 上限
_SAMPLES_LIMIT = 30


def aggregate_pair_score(
    pairs: list[ParaPair], judgments: dict[int, str]
) -> float:
    """根据段落对 sim 和 judgment 汇总 pair 级 score ∈ [0, 100]。

    - 空 pair:0.0
    - 每段对 score_i = sim * 100 * W[judgment]
    - 汇总: max(scored) * 0.7 + mean(scored) * 0.3
    """
    if not pairs:
        return 0.0
    scored: list[float] = []
    for i, p in enumerate(pairs):
        j = judgments.get(i)
        w = _WEIGHTS.get(j, _WEIGHTS[None])
        scored.append(p.sim * 100.0 * w)
    top = max(scored)
    avg = sum(scored) / len(scored)
    total = top * _MAX_WEIGHT + avg * _MEAN_WEIGHT
    # clip 并保留 2 位小数
    total = max(0.0, min(100.0, total))
    return round(total, 2)


def compute_is_ironclad(judgments: dict[int, str]) -> bool:
    """is_ironclad 判定:

    - 降级模式(judgments 空)→ False
    - plagiarism 段数 ≥ 3 → True
    - plagiarism 占比 ≥ 50% → True
    - 其他 → False
    """
    if not judgments:
        return False
    plag = sum(1 for v in judgments.values() if v == "plagiarism")
    if plag >= _IRONCLAD_ABS:
        return True
    return plag / len(judgments) >= _IRONCLAD_RATIO


def build_evidence_json(
    *,
    doc_role: str,
    doc_id_a: int,
    doc_id_b: int,
    threshold: float,
    pairs: list[ParaPair],
    judgments: dict[int, str],
    ai_meta: dict | None,
) -> dict[str, Any]:
    """按 design D7 schema 构造 evidence_json。

    degraded = (ai_meta is None)
    """
    degraded = ai_meta is None
    plag = sum(1 for v in judgments.values() if v == "plagiarism")
    tmpl = sum(1 for v in judgments.values() if v == "template")
    gen = sum(1 for v in judgments.values() if v == "generic")

    # 降级模式下 judgments 为空;按 spec evidence_json:
    # pairs_plagiarism = 0, pairs_template = 0, pairs_generic = pairs_total
    if degraded:
        plag = 0
        tmpl = 0
        gen = len(pairs)

    samples = []
    # 已按 sim 降序(compute_pair_similarity 保证),取前 N
    for i, p in enumerate(pairs[:_SAMPLES_LIMIT]):
        label = judgments.get(i) if not degraded else None
        samples.append(
            {
                "a_idx": p.a_idx,
                "b_idx": p.b_idx,
                "a_text": p.a_text,
                "b_text": p.b_text,
                "sim": p.sim,
                "label": label,
            }
        )

    evidence: dict[str, Any] = {
        "algorithm": "tfidf_cosine_v1",
        "doc_role": doc_role,
        "doc_id_a": doc_id_a,
        "doc_id_b": doc_id_b,
        "threshold": threshold,
        "pairs_total": len(pairs),
        "pairs_plagiarism": plag,
        "pairs_template": tmpl,
        "pairs_generic": gen,
        "degraded": degraded,
        "ai_judgment": (
            {
                "overall": ai_meta.get("overall", ""),
                "confidence": ai_meta.get("confidence", ""),
            }
            if ai_meta is not None
            else None
        ),
        "samples": samples,
    }
    return evidence


__all__ = [
    "aggregate_pair_score",
    "compute_is_ironclad",
    "build_evidence_json",
]
