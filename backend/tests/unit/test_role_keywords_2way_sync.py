"""L1 - ROLE_KEYWORDS 两处副本同步约束 (honest-detection-results N2)

机械校验 role_keywords.py 和 rules_defaults.py 的一致性约束:
- key 集合完全一致
- value 非空
- authorization 含"授权委托书"
- "允许短子串" 正面断言

**prompts.py 故意不在内** — 自然语言描述无可靠关键词提取规则,
它的同步靠文件顶部 docstring + 人工 review。
"""

from __future__ import annotations

from app.services.admin.rules_defaults import DEFAULT_RULES_CONFIG
from app.services.parser.llm.role_keywords import ROLE_KEYWORDS


def test_key_sets_equal() -> None:
    ssot_keys = set(ROLE_KEYWORDS.keys())
    defaults_keys = set(DEFAULT_RULES_CONFIG["doc_role_keywords"].keys())
    assert ssot_keys == defaults_keys, (
        f"role_keywords.py 与 rules_defaults.py 的 role 键集合不一致。"
        f"SSOT only: {ssot_keys - defaults_keys}; defaults only: {defaults_keys - ssot_keys}"
    )


def test_all_roles_have_nonempty_keywords_in_ssot() -> None:
    for role, kws in ROLE_KEYWORDS.items():
        assert isinstance(kws, list), f"role={role} keywords must be list"
        assert len(kws) > 0, f"role={role} keywords must be nonempty (SSOT)"


def test_all_roles_have_nonempty_keywords_in_defaults() -> None:
    for role, kws in DEFAULT_RULES_CONFIG["doc_role_keywords"].items():
        assert isinstance(kws, list), f"role={role} keywords must be list"
        assert len(kws) > 0, f"role={role} keywords must be nonempty (defaults)"


def test_authorization_contains_full_word_in_defaults() -> None:
    """honest-detection-results: rules_defaults.py 的 authorization 之前只有"授权"和"委托",
    本次补了"授权委托书"一词。"""
    assert (
        "授权委托书" in DEFAULT_RULES_CONFIG["doc_role_keywords"]["authorization"]
    )


def test_short_substring_strategy_allowed() -> None:
    """spec 允许 rules_defaults.py 用短子串、role_keywords.py 用复合词的不对等策略。
    验证两者都合法:defaults 含短"报价",SSOT 含复合"投标报价"。"""
    assert "报价" in DEFAULT_RULES_CONFIG["doc_role_keywords"]["pricing"]
    assert "投标报价" in ROLE_KEYWORDS["pricing"]


def test_new_industry_terms_in_ssot() -> None:
    """honest-detection-results N2: 10 个强烈建议词加入 SSOT。"""
    assert "价格标" in ROLE_KEYWORDS["pricing"]
    assert "开标一览表" in ROLE_KEYWORDS["pricing"]
    assert "资信标" in ROLE_KEYWORDS["qualification"]
    assert "资信" in ROLE_KEYWORDS["qualification"]
    assert "业绩" in ROLE_KEYWORDS["qualification"]
    assert "类似业绩" in ROLE_KEYWORDS["qualification"]
    assert "企业简介" in ROLE_KEYWORDS["company_intro"]
    assert "施工进度" in ROLE_KEYWORDS["construction"]
    assert "进度计划" in ROLE_KEYWORDS["construction"]


def test_defaults_are_substring_of_some_ssot_keyword() -> None:
    """honest-detection-results: 弱一致性约束 — rules_defaults.py 的每个关键词
    MUST 是 role_keywords.py 对应 role 里某个 keyword 的子串(或相等)。

    设计意图:defaults 使用 "短子串覆盖更广" 的策略(见 design D7),但**必须**
    对应 SSOT 里真有的业务概念;反方向不要求(SSOT 里新的复合词如"开标一览表"
    可以在 defaults 里无对应短子串)。

    这个约束防止"defaults 加了 SSOT 没有的词"的漂移 — 只允许严格的子集关系。
    """
    defaults = DEFAULT_RULES_CONFIG["doc_role_keywords"]
    violations: list[str] = []
    for role, default_kws in defaults.items():
        ssot_kws = ROLE_KEYWORDS.get(role, [])
        for d in default_kws:
            if not any(d in s for s in ssot_kws):
                violations.append(
                    f"role={role}: defaults 的 '{d}' 不是任何 SSOT keyword 的子串 "
                    f"(SSOT {ssot_kws})"
                )
    assert not violations, "\n".join(violations)
