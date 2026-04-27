"""price_total_match Agent 共享子包 (fix-bug-triple-and-direction-high)

bidder 级总报价完全相等检测(global 型):
- 复用 anomaly_impl.extractor.aggregate_bidder_totals 产出 BidderPriceSummary
- 两两比较 bidder.total_price,完全相等 → 铁证级
- 与 price_consistency 责任划分:price_consistency 看行级模式;
  price_total_match 看 bidder 汇总值。
- 跨币种为 known limitation(单 currency 项目场景下不影响)
"""

from __future__ import annotations
