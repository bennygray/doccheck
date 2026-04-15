"""image_reuse Agent 共享子包 (C13 detect-agents-global)

实现 MD5 + pHash 双路图片复用检测:
- MD5 精确命中 → hit_strength=1.0, match_type='byte_match'
- pHash Hamming distance ≤ threshold → hit_strength=1-d/64, match_type='visual_similar'

字节级匹配优先且独占:同对图在 MD5 命中后不进入 pHash 路。
小图(< MIN_WIDTH/HEIGHT)在 SQL 层过滤。
本期不引 L-7 LLM 非通用图判断;is_iron_evidence 强制 False。

`write_overall_analysis_row` helper 复用 `anomaly_impl/__init__.py`。
"""

from __future__ import annotations

from app.services.detect.agents.anomaly_impl import write_overall_analysis_row

__all__ = ["write_overall_analysis_row"]
