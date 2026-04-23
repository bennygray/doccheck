## 1. 前置调研

- [x] 1.1 [impl] 扫 `backend/app/services/detect/agents/*.py` 的顶层文件,列出各 agent `run()` 是否含 `except Exception` 块,记录需要前置的文件清单(预期 6 个:metadata_author / metadata_machine / metadata_time / price_consistency / price_anomaly / image_reuse;可能有文件根本没 try/except 跳过)

## 2. 前置 except AgentSkippedError(6 agent)

- [x] 2.1 [impl] `backend/app/services/detect/agents/metadata_author.py` 若有 `except Exception`,前加 `except AgentSkippedError: raise` + 顶部 import `from app.services.detect.errors import AgentSkippedError`
- [x] 2.2 [impl] `backend/app/services/detect/agents/metadata_machine.py` 同上
- [x] 2.3 [impl] `backend/app/services/detect/agents/metadata_time.py` 同上
- [x] 2.4 [impl] `backend/app/services/detect/agents/price_consistency.py` 同上
- [x] 2.5 [impl] `backend/app/services/detect/agents/price_anomaly.py` 同上
- [x] 2.6 [impl] `backend/app/services/detect/agents/image_reuse.py` 同上

## 3. 元测试

- [x] 3.1 [L1] 新增 `backend/tests/unit/test_agent_except_skipped_guard.py`:(a) 用 `ast.parse` 扫 `app/services/detect/agents/*.py` 顶层文件;(b) 对每个 `async def run(...)` 函数,遍历所有 `ast.Try` 节点 + handlers;(c) 若存在 `handler.type` 是 `Exception` / `BaseException` / `None`(bare except),则必须在其前有一个 handler `handler.type.id == "AgentSkippedError"`;(d) 失败时报告具体文件+行号

## 4. 文档 & spec sync

- [x] 4.1 [impl] spec sync 交由 archive 自动流程
- [x] 4.2 [impl] `docs/handoff.md` §2 "遗留 follow-up" 移除该 latent risk 条目(archive 时做)

## 5. 验证

- [x] 5.1 [L1] 跑 `pytest tests/unit/ -q` 全量绿(含新元测试 + 988 既有)
- [x] 5.2 [manual] 反向验证元测试生效:临时把某 agent 的 `except AgentSkippedError: raise` 删除,跑元测试应 assert 失败;恢复后再跑应绿(临时验证,改回去不 commit)

## 6. 总汇

- [x] 6.1 跑本 change 新增 L1 全绿 + 既有 L1/L2 suite 不回归
