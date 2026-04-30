"""pair 级 score 汇总 + is_ironclad 判定 + evidence_json 构造 (C7)

对齐 design D4 + D7;text-sim-exact-match-bypass: exact_match label + ironclad 长度门槛;
detect-tender-baseline §3:段级 baseline 命中跳过 ironclad 触发(段仍计入 score)+
evidence_json.samples[i] 段级 baseline_matched/baseline_source 字段。
"""

from __future__ import annotations

import hashlib
from typing import Any

from app.services.detect.agents.text_sim_impl.models import ParaPair
from app.services.detect.agents.text_sim_impl.tfidf import _normalize

# 段落级权重(label -> weight);text-sim-exact-match-bypass: exact_match 与 plagiarism 同权 1.0
_WEIGHTS: dict[str | None, float] = {
    "exact_match": 1.0,
    "plagiarism": 1.0,
    "template": 0.6,
    "generic": 0.2,
    None: 0.3,  # 降级模式(LLM 失败)全部按 None 权重
}

# is_ironclad 触发:plagiarism 段数 ≥ 绝对阈值 或 占比 ≥ 比例阈值
_IRONCLAD_ABS = 3
_IRONCLAD_RATIO = 0.5
# text-sim-exact-match-bypass D8: exact_match 升铁证的归一化字符长度门槛
_IRONCLAD_EXACT_MATCH_MIN_LEN = 50

# max + mean 混合权重
_MAX_WEIGHT = 0.7
_MEAN_WEIGHT = 0.3

# evidence_json.samples 上限(text-sim-exact-match-bypass:30→60,与 cap 同步;L3 实测 80 timeout 折中到 60)
_SAMPLES_LIMIT = 60

# detect-tender-baseline §3:段级 baseline_source 优先级(tender > consensus > none)
_BASELINE_SOURCE_PRIORITY: dict[str, int] = {"tender": 3, "consensus": 2, "none": 0}


def _segment_hash_for(text: str) -> str:
    """与 detect-tender-baseline D2 + parser content._compute_segment_hash 口径统一:
    NFKC + \\s+→' ' + strip(_normalize)+ sha256 hexdigest。
    """
    return hashlib.sha256(_normalize(text).encode("utf-8")).hexdigest()


def _label_for(p: ParaPair, idx: int, judgments: dict[int, str]) -> str | None:
    """统一 label 解析:hash 命中段直接 exact_match 终态,其余看 LLM judgments。"""
    if p.match_kind == "exact_match":
        return "exact_match"
    return judgments.get(idx)


def aggregate_pair_score(
    pairs: list[ParaPair], judgments: dict[int, str]
) -> float:
    """根据段落对 sim 和 label 汇总 pair 级 score ∈ [0, 100]。

    - 空 pair:0.0
    - 每段对 score_i = sim * 100 * W[label];hash 命中段 label 固定 exact_match(权重 1.0)
    - 汇总: max(scored) * 0.7 + mean(scored) * 0.3
    """
    if not pairs:
        return 0.0
    scored: list[float] = []
    for i, p in enumerate(pairs):
        label = _label_for(p, i, judgments)
        w = _WEIGHTS.get(label, _WEIGHTS[None])
        scored.append(p.sim * 100.0 * w)
    top = max(scored)
    avg = sum(scored) / len(scored)
    total = top * _MAX_WEIGHT + avg * _MEAN_WEIGHT
    # clip 并保留 2 位小数
    total = max(0.0, min(100.0, total))
    return round(total, 2)


def compute_is_ironclad(
    judgments: dict[int, str],
    pairs: list[ParaPair] | None = None,
    degraded: bool = False,
    *,
    baseline_excluded_segment_hashes: set[str] | None = None,
) -> bool:
    """is_ironclad 完整判定(text-sim-exact-match-bypass D8 自包含规则):

    非降级模式下,以下任一条件 → True:
      - pairs_plagiarism ≥ 3
      - pairs_plagiarism / pairs_total ≥ 0.5(以 cosine 候选段为基数;hash 段不计入分母)
      - pairs_exact_match 中含 ≥ 1 段归一化后字符长度 ≥ 50(需传 pairs 才能判定)

    降级模式(degraded=True 或 LLM 调用未成功)始终 False,**包括** evidence 中含 ≥ 50 字 exact_match。
    < 50 字 exact_match MUST 计入 score(权重 1.0),MUST NOT 单独触发 ironclad。

    pairs 为 None 时跳过 exact_match 长度门槛(向后兼容 section_similarity 复用调用)。
    degraded 默认 False;旧调用者(section_similarity)不传 → 由 judgments 空兜底为 True(旧行为)。

    detect-tender-baseline §3:`baseline_excluded_segment_hashes` 段级跳过 ironclad
    触发(段仍计入 score 不变);hash 命中段(归一化 sha256 ∈ excluded set)被跳过,
    剩余非 baseline 段仍按原规则判 ironclad。**spec 关键约束**:部分命中 baseline 不
    豁免整 PC 的 ironclad — 即只要存在 ≥1 非 baseline 命中且 ≥50 字 exact_match,
    is_ironclad 仍 = True;基线缺失 ≠ 信号无效(L3 ≤2 投标方亦不抑制 ironclad)。
    """
    # 旧调用兼容:section_similarity 等不传 degraded 但传空 judgments,沿用旧"判降级"行为
    if degraded:
        return False

    excluded = baseline_excluded_segment_hashes or set()

    # exact_match ≥ 50 字门槛(D8: 用归一化后字符长度,与 hash 比对口径统一)
    # 无论是否有 LLM judgments(可能 cosine 候选段为空),只要 hash 命中段达标就升铁证
    if pairs:
        for p in pairs:
            if (
                p.match_kind == "exact_match"
                and len(_normalize(p.a_text)) >= _IRONCLAD_EXACT_MATCH_MIN_LEN
            ):
                # detect-tender-baseline §3:段 hash ∈ baseline excluded → 跳过该段触发
                if excluded and _segment_hash_for(p.a_text) in excluded:
                    continue
                return True

    if not judgments:
        # judgments 空且无 exact_match 触发 → 不升铁证(等同旧降级判定)
        return False

    # 原 plagiarism 规则(分母为 LLM 见过的 cosine 候选段;hash 段已被 exact_match 抢标)
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
    baseline_hash_to_source: dict[str, str] | None = None,
    baseline_warnings: list[str] | None = None,
) -> dict[str, Any]:
    """按 design D7 schema 构造 evidence_json。

    degraded = (ai_meta is None)
    text-sim-exact-match-bypass: 加 pairs_exact_match 字段 + samples.label 取 exact_match。

    detect-tender-baseline §3 扩展:
    - samples[i] 加 `baseline_matched: bool` + `baseline_source: str ∈ {tender, consensus, none}`
      段级字段;前端直接读 baseline_matched 决定段灰底/Tag,**不复算 hash**。
    - PC 顶级 `baseline_source` = 所有命中段中最强 source(tender > consensus > none),
      供报告页 Badge 渲染。
    - PC 顶级 `warnings` = baseline_resolver L3 警示数组(如 baseline_unavailable_low_bidder_count);
      老 evidence 缺该字段时前端 fallback 空数组(向后兼容)。
    """
    degraded = ai_meta is None

    # 计数(hash 命中段以 match_kind 识别;LLM judgment 仅适用于 cosine 候选)
    exact = sum(1 for p in pairs if p.match_kind == "exact_match")
    plag = sum(1 for v in judgments.values() if v == "plagiarism")
    tmpl = sum(1 for v in judgments.values() if v == "template")
    gen = sum(1 for v in judgments.values() if v == "generic")

    # 降级模式下 judgments 为空;按 spec:
    # pairs_plagiarism/template = 0, pairs_generic = pairs_total - pairs_exact_match
    if degraded:
        plag = 0
        tmpl = 0
        gen = max(0, len(pairs) - exact)

    # detect-tender-baseline §3:段级 baseline_source 解析 + PC 顶级 source 取最强
    hash_to_source = baseline_hash_to_source or {}
    pc_baseline_source = "none"

    samples = []
    for i, p in enumerate(pairs[:_SAMPLES_LIMIT]):
        label = _label_for(p, i, judgments) if not degraded else (
            "exact_match" if p.match_kind == "exact_match" else None
        )
        # 段级 baseline 判定(算法层 hash 命中已先 exact_match 抢标;cosine 段一般不参与
        # baseline,但保险起见对全部 sample 做 hash 查询,不区分 match_kind)
        seg_baseline_source = "none"
        if hash_to_source:
            seg_hash = _segment_hash_for(p.a_text)
            seg_baseline_source = hash_to_source.get(seg_hash, "none")
        # PC 顶级取最强(tender > consensus > none)
        if (
            _BASELINE_SOURCE_PRIORITY[seg_baseline_source]
            > _BASELINE_SOURCE_PRIORITY[pc_baseline_source]
        ):
            pc_baseline_source = seg_baseline_source
        samples.append(
            {
                "a_idx": p.a_idx,
                "b_idx": p.b_idx,
                "a_text": p.a_text,
                "b_text": p.b_text,
                "sim": p.sim,
                "label": label,
                # detect-tender-baseline §3 段级 baseline 标记
                "baseline_matched": seg_baseline_source != "none",
                "baseline_source": seg_baseline_source,
            }
        )

    evidence: dict[str, Any] = {
        "algorithm": "tfidf_cosine_v1",
        "doc_role": doc_role,
        "doc_id_a": doc_id_a,
        "doc_id_b": doc_id_b,
        "threshold": threshold,
        "pairs_total": len(pairs),
        "pairs_exact_match": exact,
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
        # detect-tender-baseline §3:PC 顶级 baseline_source + warnings
        "baseline_source": pc_baseline_source,
        "warnings": list(baseline_warnings or []),
    }
    # text-sim-exact-match-bypass D5: token 溢出 truncate 标记进 evidence,便于排查
    if ai_meta is not None and ai_meta.get("prompt_truncated"):
        evidence["degraded_reason"] = "token_overflow"
        evidence["prompt_kept_pairs"] = ai_meta.get("prompt_kept_pairs")
        evidence["prompt_total_pairs"] = ai_meta.get("prompt_total_pairs")
    return evidence


__all__ = [
    "aggregate_pair_score",
    "compute_is_ironclad",
    "build_evidence_json",
]
