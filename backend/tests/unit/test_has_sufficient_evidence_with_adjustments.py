"""L1 - _has_sufficient_evidence 扩 adjusted_pcs/adjusted_oas kwarg (CH-2)

覆盖 spec MOD Req "证据不足判定规则" 的新老路径 scenario。
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from app.services.detect.judge_llm import _has_sufficient_evidence


def _at(name: str, status: str, score: float):
    return SimpleNamespace(agent_name=name, status=status, score=Decimal(str(score)))


def _pc(pc_id: int, dim: str, score: float, iron: bool):
    return SimpleNamespace(
        id=pc_id,
        dimension=dim,
        score=Decimal(str(score)),
        is_ironclad=iron,
        bidder_a_id=1,
        bidder_b_id=2,
        evidence_json={},
    )


def _oa(oa_id: int, dim: str, score: float, has_iron: bool = False):
    return SimpleNamespace(
        id=oa_id,
        dimension=dim,
        score=Decimal(str(score)),
        evidence_json={
            "source": "pair_aggregation",
            "has_iron_evidence": has_iron,
        },
    )


# ============================================================ 老路径(adjusted=None)


def test_old_path_signal_zero_returns_false():
    """信号型 agent 全 0 → False(走 indeterminate)— 老 AgentTask 分母"""
    ats = [_at("text_similarity", "succeeded", 0)]
    assert _has_sufficient_evidence(ats, [], []) is False


def test_old_path_metadata_only_returns_false():
    """metadata_author 非 SIGNAL,只有它非零 → False"""
    ats = [_at("metadata_author", "succeeded", 50)]
    assert _has_sufficient_evidence(ats, [], []) is False


def test_old_path_iron_short_circuit_returns_true():
    """任一 PC.is_ironclad → True 即使 score 全 0"""
    pcs = [_pc(1, "image_reuse", 0, True)]
    ats = []
    assert _has_sufficient_evidence(ats, pcs, []) is True


def test_old_path_no_succeeded_returns_false():
    ats = [_at("text_similarity", "skipped", 0)]
    assert _has_sufficient_evidence(ats, [], []) is False


def test_old_path_signal_nonzero_returns_true():
    ats = [_at("text_similarity", "succeeded", 24.5)]
    assert _has_sufficient_evidence(ats, [], []) is True


# ============================================================ 新路径(adjusted dict 传入)


def test_new_path_oa_signal_zero_returns_false():
    """OA SIGNAL 全 0 → False(走 indeterminate),与 AgentTask 无关"""
    ats = [_at("text_similarity", "succeeded", 99)]  # 旧分母会返 True
    oas = [
        _oa(1, "text_similarity", 0),
        _oa(2, "section_similarity", 0),
        _oa(3, "structure_similarity", 0),
        _oa(4, "image_reuse", 0),
        _oa(5, "style", 0),
        _oa(6, "error_consistency", 0),
    ]
    # 新路径:走 OA.score 分母,全 0 → False
    assert (
        _has_sufficient_evidence(ats, [], oas, adjusted_pcs={}, adjusted_oas={})
        is False
    )


def test_new_path_oa_signal_nonzero_returns_true():
    ats = [_at("text_similarity", "skipped", 0)]  # 旧分母会返 False
    oas = [_oa(1, "text_similarity", 45.5)]
    assert (
        _has_sufficient_evidence(ats, [], oas, adjusted_pcs={}, adjusted_oas={})
        is True
    )


def test_new_path_iron_suppressed_no_short_circuit():
    """adjusted_pcs 抑制 PC.is_ironclad=true → 铁证短路不命中"""
    pcs = [_pc(1, "metadata_author", 100, True)]  # raw iron=true
    apcs = {1: {"is_ironclad": False, "score": 0.0}}  # adjusted 抑制
    oas = []
    ats = []
    assert _has_sufficient_evidence(ats, pcs, oas, adjusted_pcs=apcs, adjusted_oas={}) is False


def test_new_path_real_iron_via_error_consistency():
    """error_consistency OA has_iron_evidence=true 未被抑制 → 铁证短路命中"""
    oas = [_oa(1, "error_consistency", 0, has_iron=True)]
    ats = []
    pcs = []
    # adjusted_oas 不抑制此 OA
    assert (
        _has_sufficient_evidence(
            ats, pcs, oas, adjusted_pcs={}, adjusted_oas={}
        )
        is True
    )


def test_new_path_text_sim_downgrade_nonzero_returns_true():
    """text_sim DEF-OA adjusted=45.5(降权后)→ 走 LLM 路径,非 indeterminate"""
    oas = [_oa(1, "text_similarity", 91.59)]  # raw
    aoas = {1: {"score": 45.5}}
    ats = []
    pcs = []
    assert (
        _has_sufficient_evidence(ats, pcs, oas, adjusted_pcs={}, adjusted_oas=aoas)
        is True
    )


def test_new_path_oa_list_must_have_11_rows_to_be_meaningful():
    """前置条件锁:DEF-OA list 同步契约 — 调用时 oa list 长度=11(4 global + 7 pair DEF-OA)。

    本测试断言"oa list 短缺时 SIGNAL 维度缺席 → 仍可正确返 False",
    模拟 DEF-OA append 缺失后的退化形态(reviewer round 4 H2 锁)。
    """
    # 仅 4 global OA(模拟 DEF-OA 未 append 的 bug 形态)
    oas = [
        _oa(1, "image_reuse", 0),
        _oa(2, "style", 0),
        _oa(3, "error_consistency", 0),
        _oa(4, "price_anomaly", 0),
    ]
    # SIGNAL 中 text/section/structure_similarity OA 缺席 → 新分母看不到信号
    assert (
        _has_sufficient_evidence([], [], oas, adjusted_pcs={}, adjusted_oas={})
        is False
    )
    # 完整 11 行 + text_sim OA 非零 → 返 True
    oas_full = oas + [
        _oa(5, "text_similarity", 30),
        _oa(6, "section_similarity", 0),
        _oa(7, "structure_similarity", 0),
        _oa(8, "metadata_author", 0),
        _oa(9, "metadata_time", 0),
        _oa(10, "metadata_machine", 0),
        _oa(11, "price_consistency", 0),
    ]
    assert (
        _has_sufficient_evidence(
            [], [], oas_full, adjusted_pcs={}, adjusted_oas={}
        )
        is True
    )
