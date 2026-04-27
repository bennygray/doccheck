"""13 Agent 骨架模块集合 (C6 detect-framework + C12 + C13 + fix-bug-triple-and-direction-high)

import 时触发每个子模块的 @register_agent 装饰器,把 AgentSpec 写入
`app.services.detect.registry.AGENT_REGISTRY`。

C13 归档后,**全部 11 Agent 的 run() 均为真实算法**。
fix-bug-triple-and-direction-high 增 2 个 global Agent(price_total_match / price_overshoot)→ 13 个。
- C7 text_similarity / C8 section_similarity / C9 structure_similarity
- C10 metadata_author / metadata_time / metadata_machine
- C11 price_consistency
- C12 price_anomaly(新增 global,直接带真实 run)
- C13 error_consistency / image_reuse / style(3 global 替换 dummy)
- fix-bug-triple-and-direction-high price_total_match / price_overshoot(2 新 global)
"""

from app.services.detect.agents import (  # noqa: F401
    error_consistency,
    image_reuse,
    metadata_author,
    metadata_machine,
    metadata_time,
    price_anomaly,
    price_consistency,
    price_overshoot,
    price_total_match,
    section_similarity,
    structure_similarity,
    style,
    text_similarity,
)
