"""C12 Agent 级 score 合成 (anomaly_impl)

占位公式(C14 judge 合成时可按 PRICE_ANOMALY_WEIGHT 调权):
    score = min(100, len(outliers) * 30 + max(abs(deviation)) * 100)

设计意图:
- 1 家偏离 35% → score ≈ 30 + 35 = 65(medium risk)
- 2 家偏离 40% → score ≈ 60 + 40 = 100(capped)
- 空 outliers → score = 0(无风险)
"""

from __future__ import annotations

from app.services.detect.agents.anomaly_impl.models import DetectionResult


def compute_score(result: DetectionResult) -> float:
    """Agent 级 score,0~100 浮点,4 舍 2 位由外层 write_row 统一处理。"""
    outliers = result["outliers"]
    if not outliers:
        return 0.0
    max_abs_dev = max(abs(o["deviation"]) for o in outliers)
    raw = len(outliers) * 30.0 + max_abs_dev * 100.0
    return min(100.0, raw)


__all__ = ["compute_score"]
