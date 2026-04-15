"""11 Agent 骨架模块集合 (C6 detect-framework + C12 + C13)

import 时触发每个子模块的 @register_agent 装饰器,把 AgentSpec 写入
`app.services.detect.registry.AGENT_REGISTRY`。

C13 归档后,**全部 11 Agent 的 run() 均为真实算法,dummy 列表清空**。
C7~C13 各 change 替换对应 run() 实现,保持 preflight / 注册 key / 签名不变。
- C7 text_similarity / C8 section_similarity / C9 structure_similarity
- C10 metadata_author / metadata_time / metadata_machine
- C11 price_consistency
- C12 price_anomaly(新增 global,直接带真实 run)
- C13 error_consistency / image_reuse / style(3 global 替换 dummy)
"""

from app.services.detect.agents import (  # noqa: F401
    error_consistency,
    image_reuse,
    metadata_author,
    metadata_machine,
    metadata_time,
    price_anomaly,
    price_consistency,
    section_similarity,
    structure_similarity,
    style,
    text_similarity,
)
