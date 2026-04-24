"""L1:identity_validator 正则矩阵 + 辅助函数(parser-accuracy-fixes P0-1)

不跑 async DB 层,仅测纯函数:
- `_BIDDER_NAME_RE.search(text)` 的正则 case 覆盖
- `_match_identity(llm, rule)` 的一致/不一致/未命中决策

apply_identity_validation(带 DB)由 test_identity_validation_flow.py 覆盖。
"""

from __future__ import annotations

import pytest

from app.services.parser.identity_validator import (
    _BIDDER_NAME_RE,
    _match_identity,
)


# ============================================================ 正则矩阵


def _extract(text: str) -> str | None:
    m = _BIDDER_NAME_RE.search(text)
    return m.group(1).strip() if m else None


class TestBidderNameRegex:
    def test_standard_full_width_parens(self):
        """全角括号 + 中文冒号"""
        text = "投标人（盖章）：  江苏省华厦工程项目管理有限公司"
        assert _extract(text) == "江苏省华厦工程项目管理有限公司"

    def test_half_width_parens(self):
        """半角括号 + 中文冒号"""
        text = "投标人(盖章): 某公司"
        assert _extract(text) == "某公司"

    def test_half_width_colon(self):
        """英文冒号"""
        text = "投标人(盖章): 攀钢集团工科工程咨询有限公司"
        assert _extract(text) == "攀钢集团工科工程咨询有限公司"

    def test_no_parens(self):
        """括号可选(省略)"""
        text = "投标人盖章：测试公司"
        assert _extract(text) == "测试公司"

    def test_whitespace_after_company(self):
        """公司名后 ≥2 空格作为尾终止"""
        text = "投标人(盖章): XYZ 有限公司   (盖章日期:2026-01-08)"
        assert _extract(text) == "XYZ 有限公司"

    def test_newline_as_terminator(self):
        """换行作为尾终止"""
        text = "投标人(盖章): 江苏省华厦\n工程项目管理有限公司"
        # non-greedy 停在换行,只抓首段
        assert _extract(text) == "江苏省华厦"

    def test_end_of_string_as_terminator(self):
        """字符串结束作为尾终止(H1 bug 修复验证)"""
        text = "投标人(盖章):攀钢集团工科工程咨询有限公司"
        # H1:原 [\n$] bug 会让公司名一直吃到行尾;修成 (?:\n|\s{2,}|$) 后 $ 作 anchor 生效
        assert _extract(text) == "攀钢集团工科工程咨询有限公司"

    def test_mixed_full_half_parens(self):
        """全角左 + 半角右(用户填写不规范)"""
        text = "投标人（盖章): 公司 A"
        assert _extract(text) == "公司 A"

    def test_with_extra_space_before_colon(self):
        """冒号前有空格"""
        text = "投标人(盖章) : 公司 B"
        assert _extract(text) == "公司 B"

    def test_empty_text_returns_none(self):
        assert _extract("") is None

    def test_irrelevant_text_returns_none(self):
        assert _extract("这是一份技术投标文件") is None

    def test_project_name_not_matched(self):
        """招标项目名的"锂源科技"不会被误抓(因无"投标人盖章"锚点)"""
        text = "项目名称:锂源(江苏)科技有限公司年产24万吨LFP项目"
        assert _extract(text) is None

    def test_placeholder_template_still_matched(self):
        """L1:模板占位符 <请填写> 会命中(已知限制,follow-up 加过滤)"""
        text = "投标人(盖章):<请填写单位名称>"
        # 规则命中,但下游比对可过滤这种占位;本 change 不处理
        assert _extract(text) == "<请填写单位名称>"


# ============================================================ _match_identity


class TestMatchIdentity:
    def test_exact_equal_is_match(self):
        assert _match_identity("攀钢集团", "攀钢集团") == "match"

    def test_substring_is_match(self):
        """子串一致(LLM 简称 + 规则全称)"""
        assert _match_identity("浙江华建", "浙江华建工程监理有限公司") == "match"

    def test_reverse_substring_is_match(self):
        """子串一致(LLM 全称 + 规则简称)"""
        assert _match_identity("浙江华建工程监理有限公司", "浙江华建") == "match"

    def test_whitespace_insensitive(self):
        """归一化去空格"""
        assert _match_identity("某 公 司", "某公司") == "match"

    def test_different_is_mismatch(self):
        """完全不同 → mismatch"""
        assert _match_identity("锂源(江苏)科技", "攀钢集团工科") == "mismatch"

    def test_llm_none_rule_some_is_fill(self):
        """H1 review 修:LLM 空但规则有 → fill(补齐,不降级 role_confidence)"""
        assert _match_identity(None, "某公司") == "fill"
        assert _match_identity("", "某公司") == "fill"

    def test_rule_none_is_unmatched(self):
        """规则未命中 → unmatched(保留 LLM)"""
        assert _match_identity("某公司", None) == "unmatched"
        assert _match_identity(None, None) == "unmatched"

    def test_short_substring_not_match(self):
        """M4 review 修:短子串不判 match,防假阳"""
        # "华建"3 字 < SUBSTRING_MIN_LEN=4,不允许作子串等价
        assert _match_identity("华建", "浙江华建工程监理") == "mismatch"
        # "浙江华建"4 字 >= 4,可以
        assert _match_identity("浙江华建", "浙江华建工程监理") == "match"
