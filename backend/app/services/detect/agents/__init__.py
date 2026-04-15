"""11 Agent 骨架模块集合 (C6 detect-framework + C12 扩展)

import 时触发每个子模块的 @register_agent 装饰器,把 AgentSpec 写入
`app.services.detect.registry.AGENT_REGISTRY`。

C6 阶段所有 run() 均为 dummy(sleep + 随机分);
C7~C13 各 change 替换对应 run() 实现,保持 preflight / 注册 key / 签名不变。
C12 扩注册表至 11(新增 global 型 `price_anomaly`)。
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
