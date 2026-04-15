"""style Agent 共享子包 (C13 detect-agents-global)

L-8 两阶段全 LLM 算法(贴 spec §F-DA-06 "LLM 独有维度,程序不参与"):
- Stage1: 每 bidder 1 次调用 → 风格特征摘要
- Stage2: 全局比对一次 → 风格高度一致 bidder 组合列表
- >20 bidder 自动分组(每组 ≤20,本期不跨组比)

任一阶段 LLM 失败 → Agent skip 哨兵(score=0.0 + skip_reason)。
不会退化为程序算法(spec 明确"程序不参与")。

`write_overall_analysis_row` helper 复用 anomaly_impl。
"""

from __future__ import annotations

from app.services.detect.agents.anomaly_impl import write_overall_analysis_row

__all__ = ["write_overall_analysis_row"]
