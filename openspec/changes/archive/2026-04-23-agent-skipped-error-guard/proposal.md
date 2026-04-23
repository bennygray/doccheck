## Why

`harden-async-infra` 引入 `AgentSkippedError` 作为 agent→engine 的 skipped 信号通道(agent 在 run() 抛此异常,engine `_execute_agent_task` 走 `_mark_skipped`)。上一 change 的 post-impl reviewer 标记了一条 **latent risk(MEDIUM)**:

agent 内部若有 `try: ... except Exception as e:`,`AgentSkippedError` 会被通用 except **先抢吞** → 走 `_mark_failed`(status="failed"),绕过 skipped 语义。

**当前状态(11 agent 清单)**:
| Agent | 今天是否抛 AgentSkippedError | except 前置保护 |
|---|---|---|
| `text_similarity` / `section_similarity` / `structure_similarity` | ✅ subprocess crash/timeout | N/A(无 try/except) |
| `style` | ✅ LLM 耗尽重试 | ✅ 已加(harden-async-infra H2) |
| `error_consistency` | ❌(call_l5 返 None 不抛) | ✅ 预防性已加(harden-async-infra M1) |
| **`metadata_author` / `metadata_machine` / `metadata_time`** | ❌ | ❌ 未加 |
| **`price_consistency` / `price_anomaly`** | ❌ | ❌ 未加 |
| **`image_reuse`** | ❌ | ❌ 未加 |

**产品侧无感知 bug**(这 6 个 agent 今天不抛 AgentSkippedError)。但**未来任何人**在它们里加 LLM 调用 / subprocess 路径并 raise AgentSkippedError 时,会被通用 except 静默吞成 failed,绕过 skipped 语义,**再一次踩 harden-async-infra H2 同型坑**。

## What Changes

- **6 个 agent 的 `except Exception` 前加 `except AgentSkippedError: raise`** 预防性前置(与 `style.py` / `error_consistency.py` 现有模式一致)。对于**无本地兜底评分且应显式保留降级结果**的 agent(如 LLM 依赖型),同时仿照 style.py / error_consistency.py 的 H2 模式在 re-raise 前写 OA stub(score=0 + skip_reason in evidence);纯算法型(metadata_* / price_* / image_reuse 主体不依赖外部资源)直接 re-raise 即可,现有 except Exception 分支保留写 OA。
- **新增 L1 元测试** `test_agent_except_skipped_guard.py`:扫 `backend/app/services/detect/agents/*.py` 的所有顶层 async `run()` 函数,若包含 `except Exception` 则必须在其之前出现 `except AgentSkippedError`,否则断言失败 — 防止未来新 agent 忘加。
- **文档更新**:`docs/handoff.md` §2 "遗留 follow-up"移除该项;design D2 补注释说明。

**BREAKING**: 无(这 6 个 agent 今天不抛 AgentSkippedError,行为零变化)。

## Capabilities

### New Capabilities
(无)

### Modified Capabilities
- `pipeline-error-handling`: 扩展 "AgentSkippedError 异常契约" Requirement,加一条 "所有 agent 的 try/except 必须前置 except AgentSkippedError" 的规范性 scenario,由元测试强制。

## Impact

- **后端代码**:6 个 agent 文件的 try/except 补前置(若 agent 没有 try/except 顶层,直接跳过 — 实测 metadata_author / metadata_machine / metadata_time / price_consistency / price_anomaly / image_reuse 是否都有 except Exception 需 apply 期逐文件确认)
- **测试**:新增 L1 元测试 1 个(~15 行 AST 或正则扫描)
- **配置 / schema / 依赖**:零
- **文档**:handoff.md 同步;pipeline-error-handling spec 加 1 scenario
