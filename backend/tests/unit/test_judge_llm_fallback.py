"""L1 - judge_llm.fallback_conclusion (C14)"""

from __future__ import annotations

from app.services.detect.judge_llm import FALLBACK_PREFIX, fallback_conclusion


def test_normal_template_contains_all_segments():
    text = fallback_conclusion(
        72.5,
        "high",
        {
            "text_similarity": 88,
            "error_consistency": 92,
            "price_consistency": 75,
        },
        ["error_consistency"],
    )
    assert text.startswith(FALLBACK_PREFIX)
    assert "72.5" in text
    assert "high" in text
    assert "error_consistency" in text
    assert "text_similarity 88" in text
    assert "price_consistency 75" in text
    assert "92" in text


def test_no_ironclad_skips_iron_segment():
    text = fallback_conclusion(55, "medium", {"text_similarity": 50}, [])
    assert "铁证维度" not in text
    assert text.startswith(FALLBACK_PREFIX)


def test_empty_per_dim_max_degrades():
    text = fallback_conclusion(0.0, "low", {}, [])
    assert text.startswith(FALLBACK_PREFIX)
    assert "0" in text
    assert "low" in text
    assert "维度最高分" not in text
    assert "建议关注" not in text


def test_none_inputs_do_not_raise():
    text = fallback_conclusion(0.0, "low", None, None)
    assert text.startswith(FALLBACK_PREFIX)
    assert "建议关注" not in text


def test_prefix_is_fixed_constant():
    """前缀必须稳定,用于前端前缀 match 识别降级态"""
    for args in [
        (0.0, "low", {}, []),
        (85.0, "high", {"text_similarity": 90}, ["text_similarity"]),
        (50.0, "medium", {"foo": 10}, []),
    ]:
        text = fallback_conclusion(*args)
        assert text.startswith("AI 综合研判暂不可用"), text[:50]


def test_top_3_dims_listed_in_descending_order():
    per_dim = {
        "dim_a": 10,
        "dim_b": 90,
        "dim_c": 50,
        "dim_d": 80,
        "dim_e": 30,
    }
    text = fallback_conclusion(40, "medium", per_dim, [])
    # 应列 dim_b 90, dim_d 80, dim_c 50 (top 3)
    idx_b = text.find("dim_b 90")
    idx_d = text.find("dim_d 80")
    idx_c = text.find("dim_c 50")
    assert idx_b >= 0 and idx_d >= 0 and idx_c >= 0
    assert idx_b < idx_d < idx_c
    assert "dim_a" not in text  # 第 4/5 名不列
    assert "dim_e" not in text


def test_ironclad_dims_appear_first_in_focus():
    """建议关注:铁证维度优先,然后 top 高分"""
    text = fallback_conclusion(
        85,
        "high",
        {"text_similarity": 90, "error_consistency": 60},
        ["error_consistency"],
    )
    # 找到"建议关注:"后的文本
    idx = text.find("建议关注:")
    tail = text[idx:]
    # error_consistency 应在 text_similarity 之前
    assert tail.find("error_consistency") < tail.find("text_similarity")


def test_zero_score_dims_excluded_from_top3():
    """per_dim_max 中 0 分或 None 的维度不入 top3"""
    per_dim = {"dim_a": 0, "dim_b": 50, "dim_c": None}
    text = fallback_conclusion(5, "low", per_dim, [])
    assert "dim_a" not in text.split("建议关注")[0].split("维度最高分")[1] if "维度最高分" in text else True
    assert "dim_b 50" in text
