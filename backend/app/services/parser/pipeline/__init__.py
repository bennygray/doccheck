"""C5 解析流水线编排模块。

子模块:
- progress_broker: 项目级 SSE 事件 broker
- rule_coordinator: 报价规则 DB 原子占位并发控制 (E3 决策)
- run_pipeline: per-bidder 主协程
- fill_price: 按规则回填报价数据
- trigger: 外部触发入口 (asyncio.create_task + INFRA_DISABLE_PIPELINE)
"""
