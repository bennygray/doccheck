## Context

`harden-async-infra` 归档后,post-impl reviewer 标记 MEDIUM latent risk:6 个 agent(`metadata_author` / `metadata_machine` / `metadata_time` / `price_consistency` / `price_anomaly` / `image_reuse`)的 `except Exception` 块前没有前置 `except AgentSkippedError: raise`,今天它们不抛 AgentSkippedError 所以无 bug,但未来任何人在它们里加 LLM 调用 / subprocess 路径并 raise AgentSkippedError 时,会被通用 except 静默吞成 failed → 再踩 harden-async-infra H2 同型坑。

本 change 做**纯防御性加固**。

核心约束:
- 零产品行为变化 — 这 6 个 agent 今天不抛 AgentSkippedError
- 不引入新抽象 — 复用 `style.py` / `error_consistency.py` 已有的前置 `except AgentSkippedError: raise` 模式
- 用元测试强制,比"靠 code review 记得加"可靠

## Goals / Non-Goals

**Goals**
1. 6 个 agent 的 `except Exception` 前加 `except AgentSkippedError: raise`(若 agent 根本没 try/except 则跳过,apply 期逐文件确认)
2. 新增 L1 元测试扫 `agents/*.py`,静态强制"有 except Exception 必须前置 except AgentSkippedError"
3. 文档同步:handoff 移除该 follow-up;spec 加 1 scenario 明确元测试约束

**Non-Goals**
- 不改这 6 个 agent 的任何现有行为(不加 AgentSkippedError 抛出路径;今天没需求)
- 不动 3 个 similarity agent(它们内部无 try/except,是直接 raise AgentSkippedError 由 run_isolated)
- 不动 style / error_consistency(已在 harden-async-infra 加过)
- 不做 OA stub 写入(6 个 agent 今天不走 skipped 路径,stub 不发生;如未来 agent 新增 AgentSkippedError 抛出路径,**那时**再按 H2 规范补 stub)

## Decisions

### D1 元测试实现 = AST 而非正则

**选定**:用 Python `ast` 模块解析 `agents/*.py`,遍历 top-level async `run` 函数(identifier="run")的 AST,找 `ast.Try` 节点,检查 `handlers` 列表顺序:若存在 `except Exception`,其前必须有 `except AgentSkippedError` handler。

**理由**:
- harden-async-infra 的 `test_engine_except_order` 用 "去注释 + 正则" 已暴露注释里出现 `except ` 字符串的误伤风险(reviewer L1),AST 方案鲁棒
- 标准库,零依赖
- 支持嵌套 try(虽本项目 agent 一般是顶层单 try)

**备选 A**(已否):正则扫源码
- ❌ 同上 reviewer L1 已指出的问题:注释、docstring 里的 `except` 字符串字面量会误判

**备选 B**(已否):运行时 hook 拦截 `_mark_failed` 调用栈
- ❌ 过度设计,运行期加层不如静态检查早暴露

### D2 元测试范围 = agents 入口文件

**选定**:扫 `backend/app/services/detect/agents/*.py` 的顶层文件(不递归 `_impl` 子包),目标是带 `@register_agent` 装饰器的 `async def run(ctx)` 函数。11 agent 对应 11 个文件(含 `_dummy.py` 跳过,`_preflight_helpers.py` 跳过)。

**不扫 `_impl` 子包**:子包是 helper,exception 逸出到 agent 入口 run() 即按 agent 入口规则约束。

### D3 元测试豁免路径

若某个 agent 的 run() 函数**完全没有** `try/except Exception`,元测试不断言什么(没 try/except 就没吞掉 AgentSkippedError 的可能)。只在"有 `except Exception` 但前面没 `except AgentSkippedError`"时 assert 失败。

### D4 修复策略 = 最小 2 行插入

每个有 `except Exception` 的 agent,在其前加:
```python
except AgentSkippedError:
    raise
except Exception as e:
    ...
```

**不写 OA stub**(non-goal D):今天这 6 个 agent 都不抛 AgentSkippedError,stub 不发生;未来真有 agent 加抛出路径时,按 H2 规范单独改写。

### D5 元测试文件位置

`backend/tests/unit/test_agent_except_skipped_guard.py`,L1 级。

## Risks / Trade-offs

- **[Risk 1]** 若未来有人写不带 `except Exception` 但有 `except ValueError` / `except RuntimeError as e` 等具体异常的 agent,元测试不会强制前置 except AgentSkippedError — 理论上 `except ValueError` 不会吞 AgentSkippedError(继承 Exception 但不继承 ValueError),无害。只有 `except Exception` / `except BaseException` / 裸 `except:` 会吞 → 元测试规则覆盖这三种
  → **Mitigation**:元测试同时检查 `except Exception` / `except BaseException` / bare except `except:`(AST 表现为 handler.type is None)

- **[Risk 2]** AST 解析失败(agent 文件有语法错误)→ 元测试报假阳
  → **Mitigation**:解析异常时给清晰 error message 指出哪个文件,不静默 pass/fail

- **[Risk 3]** 新 agent 加到 `agents/` 目录但不带 run() 函数(比如纯 helper)
  → **Mitigation**:元测试只对含有 top-level `async def run` 的文件生效,不 match 的文件 skip

- **[Risk 4]** agent 的 run() 被包装装饰器(`@register_agent(...)`),AST 看到的是 `FunctionDef` 仍可遍历 body
  → **Mitigation**:元测试不依赖装饰器,直接按 function name == "run" 过滤

## Migration Plan

零迁移:无 schema / 无 config / 无 API。后端镜像更新即生效。

**Rollback**:回滚前一个 commit,6 行 insert 撤销,元测试文件删除。

## Open Questions

无。纯防御性改动,全部技术决策本 design 自决。
