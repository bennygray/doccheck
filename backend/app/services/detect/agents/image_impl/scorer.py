"""image_reuse 评分公式 (C13 占位)

公式:min(100, md5_count * 30 + sum(phash_hit_strength) * 10)
- md5 命中权重高(字节级强信号)
- phash 累加 hit_strength(视觉相似 0~1)
- 上限 100
"""

from __future__ import annotations

from app.services.detect.agents.image_impl.models import DetectionResult


def compute_score(result: DetectionResult) -> float:
    md5_count = len(result.get("md5_matches", []))
    phash_sum = sum(
        float(p.get("hit_strength", 0.0))
        for p in result.get("phash_matches", [])
    )
    raw = md5_count * 30.0 + phash_sum * 10.0
    return min(100.0, raw)


__all__ = ["compute_score"]
