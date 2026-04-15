"""error_consistency Agent 共享子包 (C13 detect-agents-global)

C13 实现"错误一致性"维度:跨 bidder identity_info 关键词交叉 + L-5 LLM 深度判断。
共享:
- config: 5 env (ERROR_CONSISTENCY_*) + ErrorConsistencyConfig dataclass
- models: SuspiciousSegment / KeywordHit / LLMJudgment / DetectionResult TypedDict
- keyword_extractor: identity_info 4 类字段平铺 + 短词过滤 + NFKC 归一化
- intersect_searcher: 双向跨 bidder 关键词在 paragraphs + header_footer 子串匹配
- llm_judge: L-5 LLM 调用 + JSON 解析 + 重试 + 失败兜底
- scorer: 占位评分公式

铁证机制:L-5 任一 pair 返 direct_evidence=true → evidence.has_iron_evidence=true
(由 judge.py 读 OverallAnalysis.evidence_json["has_iron_evidence"] 升铁证强制评分)。

`write_overall_analysis_row` helper 复用 `anomaly_impl/__init__.py`(C12 建)。
"""

from __future__ import annotations

# 复用 C12 的 write_overall_analysis_row(语义相同,不重复造)
from app.services.detect.agents.anomaly_impl import write_overall_analysis_row

__all__ = ["write_overall_analysis_row"]
