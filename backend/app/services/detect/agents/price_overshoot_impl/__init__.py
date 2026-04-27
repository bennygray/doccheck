"""price_overshoot Agent 共享子包 (fix-bug-triple-and-direction-high)

任一 bidder.total_price > Project.max_price 检测(global 型):
- 复用 anomaly_impl.extractor.aggregate_bidder_totals 产出 BidderPriceSummary
- 命中 → 铁证级(超限即等同合规底线违规)
- preflight:max_price=NULL 或 ≤0 → skip
- 决策 1A:超限一律 ironclad,follow-up 可分级阈值化
"""

from __future__ import annotations
