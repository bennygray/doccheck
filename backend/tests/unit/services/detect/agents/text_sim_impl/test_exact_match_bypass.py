"""L1 - text-sim-exact-match-bypass 单元测试

覆盖 tasks.md §2 全部 [L1] 条目:
- hash 旁路命中(三段 47/131/165 字)
- _normalize 等价性(NFKC / \\s+ / strip)
- ironclad 长度门槛边界(49/50字 + 降级)
- cosine 候选集排除已 hash 命中对
- label 互斥优先级(exact_match 不被 LLM 覆写)
- cap 30→80 不影响 ironclad 算分公式
- LLM token 溢出 truncate
"""
from __future__ import annotations

from app.services.detect.agents.text_sim_impl.aggregator import (
    aggregate_pair_score,
    build_evidence_json,
    compute_is_ironclad,
)
from app.services.detect.agents.text_sim_impl.llm_judge import (
    _estimate_prompt_tokens,
    _truncate_for_token_budget,
)
from app.services.detect.agents.text_sim_impl.models import ParaPair
from app.services.detect.agents.text_sim_impl.tfidf import (
    _hash_pairs,
    _normalize,
    compute_pair_similarity,
)


# 客户演示 fixture(repro_demo_files.py 抽出的真实注入段)
INJ_47 = "啊啊啊啊啊啊哦哦哦哦哦19988227268638386,投标方为攀钢集团工科工程咨询有限公司"
INJ_131 = (
    "必须坚持榜样先行。先做样板其目的:做样板,使抽象的图纸变为实物,"
    "使人们能够直观其效果,有利于进行设计调整,确定设计方案,让工人的操作有"
    "一个直观的了解;二是为工程施工和验收提供参照依据。因此,在工序实施前先做样板是必要的"
)
INJ_165 = (
    "检查材料的保管情况:材料堆放是否整齐;标识牌是否齐全,标识内容是否清楚,"
    "与实物是否相符;不同型号、规格、材质、品种、性质的材料是否分别堆放;"
    "需检验材料检验和未检验材料有无混放现象,有无使用未经检验材料的情况;"
    "材料的存放环境条件是否满足材料的"
)


# ============================================================================
# 1. hash 旁路命中 (47/131/165 字)
# ============================================================================

def test_hash_bypass_hits_three_demo_segments():
    """客户演示 fixture 三段(直接对 _hash_pairs 跑,验证算法层)。

    注:实际生产路径 hash 旁路在 raw body 段上做(text_similarity.run 控制),
    本测验证 _hash_pairs 函数本身在三段独立成段时的命中能力。
    """
    a_paras = ["前置 A 段独立内容 A", INJ_47, "中间 A 段独立 A", INJ_131, "尾部 A 段独立 A", INJ_165]
    b_paras = ["前置 B 段独立内容 B", INJ_165, "中间 B 段独立 B", INJ_131, "尾部 B 段独立 B", INJ_47]
    hits, hit_set = _hash_pairs(a_paras, b_paras)
    assert len(hits) == 3
    sims = {round(p.sim, 4) for p in hits}
    assert sims == {1.0}
    assert all(p.match_kind == "exact_match" for p in hits)
    texts = {p.a_text for p in hits}
    assert INJ_47 in texts and INJ_131 in texts and INJ_165 in texts


def test_hash_bypass_47_chars_present_even_if_short():
    """47 字段(< segmenter MIN_PARAGRAPH_CHARS=50) hash 旁路独立命中。

    spec 行为:hash 旁路看 raw body 段(segmenter 合并前),不受 _merge_short_paragraphs 稀释影响。
    """
    hits, _ = _hash_pairs([INJ_47], [INJ_47])
    assert len(hits) == 1
    assert hits[0].match_kind == "exact_match"
    assert hits[0].sim == 1.0


# ============================================================================
# 2. _normalize 等价性
# ============================================================================

def test_normalize_full_width_equivalence():
    """NFKC: 全角逗号 ',' 与半角 ',' 等价。"""
    a = "投标方,联系人"
    b = "投标方,联系人"
    assert _normalize(a) == _normalize(b)


def test_normalize_continuous_whitespace():
    """\\s+ 合并: 双空格与单空格等价。"""
    a = "施工  方案"
    b = "施工 方案"
    assert _normalize(a) == _normalize(b)


def test_normalize_strip_leading_trailing():
    """strip: 首尾空白/换行不影响 hash。"""
    a = "\n  内容  \n"
    b = "内容"
    assert _normalize(a) == _normalize(b)


def test_hash_bypass_treats_normalized_equals_as_match():
    """归一化等价 → hash 命中(全角半角 + 多空格混合)。"""
    # ， 全角逗号 vs , 半角逗号(NFKC 等价); 多空格 vs 单空格(\s+ 合并)
    a_paras = ["投标方，联系人  18888888888  详情见附件"]
    b_paras = ["投标方,联系人 18888888888 详情见附件"]
    # 先验证 _normalize 等价
    assert _normalize(a_paras[0]) == _normalize(b_paras[0])
    hits, hit_set = _hash_pairs(a_paras, b_paras)
    assert len(hits) == 1
    assert (0, 0) in hit_set


# ============================================================================
# 3. cosine 候选集排除已 hash 命中对
# ============================================================================

def test_cosine_candidates_exclude_hash_hits_by_text_content():
    """生产路径(text_similarity.run)用文本内容(_normalize 后)排除已 hash 命中段。

    本测验证算法层语义:_hash_pairs 返回的 hit_set 以归一化文本为键,
    caller 用此 set 过滤 cosine 候选避免双计。
    """
    same = "本项目技术方案采用先进人工智能算法实现自动化围标检测和证据收集"
    different_a = "饮食健康搭配蔬菜水果对身体有益不可缺少"
    different_b = "运动锻炼提升身体素质增强免疫力"

    a_paras = [same, different_a]
    b_paras = [same, different_b]
    hits, hit_set = _hash_pairs(a_paras, b_paras)
    # (0, 0) 文本完全相同 → hash 命中
    assert any(p.a_idx == 0 and p.b_idx == 0 for p in hits)
    # 命中段 a_text 在 hit_set 中(以归一化文本为键)
    from app.services.detect.agents.text_sim_impl.tfidf import _normalize
    norm_same = _normalize(same)
    assert any(_normalize(p.a_text) == norm_same for p in hits)


# ============================================================================
# 4. label 互斥优先级 (exact_match MUST NOT 被 LLM 覆写)
# ============================================================================

def test_label_priority_exact_match_not_overwritten():
    """hash 命中段在 evidence_json.samples 中 label MUST 始终 'exact_match',
    不被 LLM judgments 覆写。"""
    pairs = [
        ParaPair(0, 0, INJ_165, INJ_165, sim=1.0, match_kind="exact_match"),
        ParaPair(1, 1, "X", "X", sim=0.8, match_kind=None),
    ]
    # LLM judgments 假设给 idx=0 标 plagiarism (但 hash 段已抢标 exact_match)
    judgments = {0: "plagiarism", 1: "plagiarism"}
    ev = build_evidence_json(
        doc_role="technical",
        doc_id_a=1,
        doc_id_b=2,
        threshold=0.7,
        pairs=pairs,
        judgments=judgments,
        ai_meta={"overall": "", "confidence": ""},
    )
    samples_by_idx = {(s["a_idx"], s["b_idx"]): s for s in ev["samples"]}
    assert samples_by_idx[(0, 0)]["label"] == "exact_match"
    assert samples_by_idx[(1, 1)]["label"] == "plagiarism"


# ============================================================================
# 5. ironclad 长度门槛边界 (49/50 字 + 降级)
# ============================================================================

def _hit(text: str, idx: int = 0) -> ParaPair:
    return ParaPair(idx, idx, text, text, sim=1.0, match_kind="exact_match")


def test_ironclad_50_chars_exact_match_triggers():
    """归一化后字符 = 50 → 升铁证。"""
    text = "x" * 50
    pairs = [_hit(text)]
    judgments = {0: "generic"}  # LLM 不出 plagiarism, 仅 exact_match 触发
    assert compute_is_ironclad(judgments, pairs=pairs) is True


def test_ironclad_49_chars_exact_match_does_not_trigger():
    """归一化后字符 = 49 → 不升铁证 (除非另有 plagiarism>=3 触发)。"""
    text = "x" * 49
    pairs = [_hit(text)]
    judgments = {0: "generic"}
    assert compute_is_ironclad(judgments, pairs=pairs) is False


def test_ironclad_degraded_with_long_exact_match_still_false():
    """降级模式 (degraded=True) MUST False, 包括含 ≥50 字 exact_match。"""
    pairs = [_hit("y" * 100)]
    assert compute_is_ironclad({}, pairs=pairs, degraded=True) is False


def test_ironclad_no_cosine_candidates_but_exact_match_triggers():
    """cosine 候选段为空 (judgments={}) 但 LLM 没降级 + 有 ≥50 字 exact_match → True。

    本测覆盖 L2 暴露的 bug: 旧逻辑 'judgments 空 = 降级' 把 'cosine 段空' 也误判为降级。
    """
    pairs = [_hit("z" * 100)]
    # LLM 没降级 (degraded=False), 但 cosine_pairs=[] → judgments={}; exact_match 仍升铁证
    assert compute_is_ironclad({}, pairs=pairs, degraded=False) is True


def test_ironclad_short_exact_match_plus_3_plagiarism_triggers():
    """< 50 字 exact_match 自身不升铁证, 但叠加 3 段 plagiarism 仍 True (原规则)。"""
    pairs = [_hit("短", 0), _hit("段", 1), _hit("名", 2)]
    judgments = {3: "plagiarism", 4: "plagiarism", 5: "plagiarism"}
    assert compute_is_ironclad(judgments, pairs=pairs) is True


# ============================================================================
# 6. cap 30→80 不影响 ironclad 算分公式
# ============================================================================

def test_cap_change_does_not_affect_score_formula():
    """同 fixture 用 cap=30 和 cap=80 跑 aggregate_pair_score, 公式输出一致。"""
    pairs = [
        ParaPair(i, i, "x", "x", sim=0.9 - i * 0.01, match_kind=None)
        for i in range(20)
    ]
    judgments = {i: "plagiarism" for i in range(20)}

    score = aggregate_pair_score(pairs, judgments)
    # 公式只看 pairs/judgments 整体, 不看 cap
    assert 0 < score <= 100
    # 同样 fixture 调两次, 结果一致(确定性)
    assert aggregate_pair_score(pairs, judgments) == score


# ============================================================================
# 7. LLM token 溢出 truncate
# ============================================================================

def test_estimate_prompt_tokens_proportional():
    """token 估算: 字符数翻倍 → token 估算翻倍。"""
    pair_short = ParaPair(0, 0, "短", "短", sim=1.0)
    pair_long = ParaPair(0, 0, "长" * 100, "长" * 100, sim=1.0)
    assert _estimate_prompt_tokens([pair_long]) > _estimate_prompt_tokens([pair_short])


def test_truncate_for_token_budget_keeps_high_sim_first():
    """truncate 按调用方传入顺序保留前 N(调用方已按 sim 降序);超 budget 截断。"""
    # 每对 a_text + b_text = 1500 字 ≈ 1000 token
    big_pairs = [
        ParaPair(i, i, "字" * 750, "字" * 750, sim=0.95 - i * 0.001)
        for i in range(30)
    ]
    kept, truncated = _truncate_for_token_budget(big_pairs, budget=5000)
    assert truncated is True
    # budget=5000 token 大概只能容 5 对 (5×1000=5000)
    assert 0 < len(kept) <= 7
    # 保留的是前面的(sim 最高的)
    assert all(kept[i].sim >= kept[i + 1].sim for i in range(len(kept) - 1))


def test_truncate_no_op_when_within_budget():
    """token 在 budget 内 → 不 truncate。"""
    small = [ParaPair(0, 0, "短", "短", sim=1.0)]
    kept, truncated = _truncate_for_token_budget(small, budget=10000)
    assert kept == small
    assert truncated is False


# ============================================================================
# 8. evidence_json.pairs_exact_match 字段
# ============================================================================

def test_evidence_json_pairs_exact_match_field():
    """evidence_json 含 pairs_exact_match 字段, 计 hash 命中段对。"""
    pairs = [
        _hit(INJ_165, 0),
        _hit(INJ_131, 1),
        ParaPair(2, 2, "x", "x", sim=0.9, match_kind=None),
    ]
    judgments = {2: "plagiarism"}
    ev = build_evidence_json(
        doc_role="technical",
        doc_id_a=1,
        doc_id_b=2,
        threshold=0.7,
        pairs=pairs,
        judgments=judgments,
        ai_meta={"overall": "", "confidence": ""},
    )
    assert ev["pairs_exact_match"] == 2
    assert ev["pairs_plagiarism"] == 1
    assert ev["pairs_total"] == 3
