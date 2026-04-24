## Context

5 项 follow-up 来自 3 次前序 change,性质同属测试/诊断基础设施可靠性。其中 Item 1 在 llm-classifier-observability apply 期通过手工 recon + 诊断代码注入(临时 print + caplog state dump)完全锁定了根因,无遗留模糊性;Item 2-4 + 6 是 reviewer / handoff 明确标过的 latent risk 或覆盖空白,design 级已有明确方案。本 change 的核心约束:

- **Item 1 是真 bug**,clean testdb 下稳定失败,阻塞未来 L2 change 归档 —— 必须修,且修得有回归网
- **Item 2-4 是 latent risk / 覆盖空白**,单独 open change ceremony 太重;合 1 个 wave2 跟 harden-async-infra 同模式
- **零产品行为变化,零 API / 前端 / DB 契约变更**
- **不新建抽象**:5 项改动都是既有站点的微调 + 测试补强,无新 helper / 新 class

## Goals / Non-Goals

**Goals:**
1. L2 `test_xlsx_truncates_oversized_sheet` 恢复全绿(Item 1 bug fix)
2. `app.*` logger 在 alembic upgrade head 后不再被 disable —— 未来任何 caplog 测试不会再撞同一 bug(Item 1 回归防御)
3. Engine 层 except 顺序断言从正则升级 AST,和 agent-skipped-error-guard 的元测试方案齐(Item 2 现代化)
4. `run_isolated` 对 Py 3.14+ `pool._processes` 消失/重命名 graceful degrade(Item 3 future-proof)
5. uvicorn 启动后 `app.*` logger 树默认 INFO 级(Item 4 诊断可见性)
6. text_sim `_DEGRADED_SUMMARY` UI 文案有端到端真实 evidence_json 回归网(Item 6)
7. handoff stale 项清理(+handoff L97)

**Non-Goals:**
- **不解决** 9 个 spec validate 失败(handoff L58,pre-existing,逐个看,scope 大,单独 change)
- **不新建** logging config 框架 / dictConfig yaml(Item 4 只改 1 行 setLevel,不搞 dictConfig)
- **不扩** 任何 Item 的 scope(例如 Item 1 不顺便整理 alembic.ini logger 白名单,Item 4 不顺便加 log 格式化)
- **不改** 产品行为(DB/API/前端 route / 用户可见文案/降级语义)
- **不改** 既有 spec 的 Requirement 本质(只在 openspec validate 强制时加最小 ADDED,锁稳定点)
- **不跑** 真 LLM 采样(本 change 无 LLM 相关改动)

## Decisions

### D1 Item 1 修复:alembic/env.py 单参数改动

**选定**:
```python
# backend/alembic/env.py:27
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)
```

**理由**:
- 根因已 recon 锁定:`fileConfig` 默认 `disable_existing_loggers=True` → alembic upgrade head 跑完后 `logging.Logger.manager.loggerDict` 里所有非白名单 logger 的 `.disabled = True`
- 改动最小:1 行加一个 keyword arg
- 对 prod migration 严格更宽松(prod 只少丢不多丢日志);alembic 自己的 root/sqlalchemy/alembic 三个 logger 依然按 alembic.ini 配置,不受影响
- 对所有应用 logger(`app.xxx`)统一修复,不只 `app.services.parser.content`

**L1 回归断言**(`test_alembic_preserves_app_loggers.py`):
```python
import logging
from alembic import command
from alembic.config import Config

def test_alembic_upgrade_does_not_disable_app_loggers(tmp_path):
    # 先创建 app 层 logger(模拟应用 import 时的状态)
    before = logging.getLogger("app.services.parser.content")
    before.warning("priming")  # 确保 logger 被创建
    assert before.disabled is False

    # 跑一次 alembic 命令(env.py 会调 fileConfig)
    cfg = Config(<test alembic.ini>)
    command.upgrade(cfg, "head")

    # 确认未被 disable
    after = logging.getLogger("app.services.parser.content")
    assert after.disabled is False
```

**备选 A**(已否):修 alembic.ini 加 `app` logger 到白名单
- ❌ 白名单方式只修复列出的 logger,未来新 logger 又会撞坑
- ❌ alembic.ini 变成**应用 logger 列表的副本**,维护负担 + 易漂移

**备选 B**(已否):把 L2 conftest 的 alembic upgrade 调用替换为 SQL 直接执行
- ❌ 丢掉 alembic 的 migration 路径完整性验证
- ❌ 改动面大,多个 fixture 相关

### D2 Item 2 AST 升级:复用 agent-skipped-error-guard 模式

**选定**:`test_engine_agent_skipped_error.py` 的 engine 层 `_execute_agent_task` except 顺序断言从正则/line scanning 改 AST `ast.AsyncFunctionDef.body` 遍历,复用 `test_agent_except_skipped_guard.py` 里已落地的 AST visitor pattern(哪个 try 块、哪个 handler、顺序索引)。

**理由**:
- harden-async-infra reviewer L1 明确标过:`_extract_code_lines` 粗略去注释不处理字符串字面量里的 `#`。当前 engine 测试用同风格的正则扫描,同漏洞
- agent-skipped-error-guard 已建立 AST pattern,一键复用
- 精确解析 Python 语法,消除文本层误匹配

**复用方式**:把 `test_agent_except_skipped_guard.py` 里的 AST visitor helper 抽到 `backend/tests/unit/_except_order_ast.py` 共享模块?**否** —— 两个测试场景不同(agent 是扫所有 run(),engine 是锁定单一函数 `_execute_agent_task`),抽共享会强行复用 + 参数爆炸。改写 engine 测试时内联 AST 代码,复用 AST 库(`ast` 内置)。10-20 行够。

### D3 Item 3 future-proof:getattr + try/except

**选定**:`run_isolated` finally 块改:
```python
finally:
    pool.shutdown(wait=False, cancel_futures=True)
    try:
        processes = list(getattr(pool, "_processes", {}).values())
    except (AttributeError, TypeError):
        processes = []
    for proc in processes:
        try:
            proc.terminate()
            proc.join(0.3)
            if proc.is_alive():
                proc.kill()
                proc.join(0.3)
        except Exception:  # noqa: BLE001
            pass
```

**理由**:
- `getattr(pool, "_processes", {})` 本身对"字段缺失"已有 fallback({}),但如果 stdlib 把 `_processes` 改成方法 / 属性 / 类型,`getattr + .values()` 会 TypeError
- 加 try/except 兜 `AttributeError`/`TypeError`,fallback 到空列表 → 纯 shutdown 路径,无 terminate/kill
- **注意**:fallback 路径是"harden-async-infra 之前的行为",在 Py 3.14+ 如果 stdlib 的 `shutdown(wait=False, cancel_futures=True)` 真正完备解决了 hang worker 问题(目前 ≤3.13 不够),是合理 degrade

**L1 sanity test**(`test_run_isolated_future_proof.py`):
- mock 一个 `ProcessPoolExecutor` subclass,强制 `_processes` 是 None / 删除 / raise AttributeError
- 跑 run_isolated 小 task,断言不 raise,返回正常值
- 验证行为 = 纯 shutdown(wait=False)

**备选 A**(已否):完全移除 `_processes` 依赖,只用公开 API
- ❌ 当前 Py 3.13 `shutdown(wait=False, cancel_futures=True)` 对 hang worker 不保证清理 —— harden-async-infra apply 期实测证实;必须保留下划线字段兜底逻辑在 3.13 路径

### D4 Item 4 setLevel:最小改动

**选定**:`backend/app/main.py` lifespan 顶部(现有 `startup_logger = logging.getLogger("app.startup")` 之前)插入:
```python
try:
    logging.getLogger("app").setLevel(logging.INFO)
except Exception:  # noqa: BLE001 - logging 失败不阻塞启动
    pass
```

**理由**:
- 只设 level,不改 handler / formatter / dictConfig —— 最小侵入
- `app` 树级 setLevel 级联到所有 `app.*` 子 logger(只要它们没 explicit level)—— 一行覆盖整个应用
- prod 默认 warning 级别仍可由 env `LOG_LEVEL` 或 uvicorn `--log-level` 控制 handler 级:**handler 级** > **logger 级**,所以 prod warning 级 handler 不会让 info 爆出
- 诊断时(如 llm-classifier-observability 采样)调 uvicorn `--log-level info` 让 handler 放行 info → 此时 logger 树级已是 INFO,端到端可见
- try/except 兜底 logging 初始化未就绪的极端场景

**备选 A**(已否):写 `logging.yaml` + uvicorn `--log-config` 启动
- ❌ 新建配置文件,dev/prod 多环境同步负担
- ❌ 1 行 setLevel 等效解决本问题(只是诊断可见性)

**备选 B**(已否):改 uvicorn 启动参数
- ❌ 只影响 uvicorn 自己的 logger,不级联 app logger —— 就是 llm-classifier-observability 已验证的失败路径

### D5 Item 6 前端测试补强

**选定**:`DimensionRow.test.tsx` 补 1 case,用真实 `_DEGRADED_SUMMARY` evidence_json shape:
```tsx
const degradedEvidence = {
  score_breakdown: { total: 0, llm_judgment: null },
  llm_error: { kind: "timeout", message: "LLM 超时" },
  degraded: true,
  // ... 其他 text_sim evidence_json 字段
};
render(<DimensionRow dimension="text_similarity" evidenceJson={degradedEvidence} ... />);
expect(screen.getByText(/降级|已跳过|LLM 失败/i)).toBeInTheDocument();
```

**理由**:
- 现有 `DimensionRow.test.tsx` 覆盖 skip / error 文案的 mock stub,但 text_sim 降级(LLM 失败但保留相似度)的**真实 shape**(含 score_breakdown / llm_error / degraded flag)没断过
- 防未来改 DimensionRow 或 text_sim evidence_json 结构时 UI 降级文案回归

**测试实现细节**(apply 期确定):
- evidence_json 真实 shape 从 `backend/app/services/detect/agents/text_similarity.py` 的 `_DEGRADED_SUMMARY` 常量 + 上下游 dict 结构推导
- 不 mock,直接构造 + render
- 断言用户可见的降级文案,不断内部 state

**备选 A**(已否):端到端 Playwright L3 case
- ❌ L3 kernel-lock 阻塞,整个项目 L3 延续手工凭证;不值得为 1 个文案开 L3 通道
- ❌ React Testing Library 足以覆盖组件层真实 shape → UI 文案的数据流

### D6 Spec 处理:最小 ADDED 一条 Requirement(仅在 validate 强制时)

**选定**:**先不写 spec**。若 `openspec validate test-infra-followup-wave2` 失败(同 llm-classifier-observability 遇到的"No deltas found"),写一条 ADDED Requirement 到 `pipeline-error-handling/spec.md`,标题 "测试基础设施鲁棒性契约",scenarios:

1. alembic migration 不 disable 应用 logger(WHEN alembic upgrade head 跑完,THEN `app.services.*` logger `.disabled is False`)
2. `run_isolated` pool 内部字段消失时 graceful fallback(WHEN pool._processes 缺失或非预期类型,THEN finally 块不 raise)
3. engine 层 except 顺序契约由 AST 元测试强制(WHEN `_execute_agent_task` 的 try 块含 except Exception,THEN 其前必有 except AgentSkippedError)

理由 = **仅锁 3 个稳定契约点**(不锁 heuristic / 参数 / implementation detail)。和 llm-classifier-observability 同风格。

**备选 A**(已否):加到每一项 Item 对应的 spec(`parser-pipeline` Item 1/4/6,`pipeline-error-handling` Item 2/3)
- ❌ 5 项 scope 分散到 2-3 个 spec,ceremony 重
- ❌ Item 4 / Item 6 本质不是 spec 契约(是内部诊断 + 前端测试),强行上 spec 是过度设计

## Risks / Trade-offs

- **[R1]** Item 1 的 alembic fileConfig 改动影响所有 prod/dev migration → **Mitigation**:`disable_existing_loggers=False` 是**严格更宽松**(少丢日志)。零回归风险。L1 回归测试正向验证
- **[R2]** Item 2 AST 改写 engine 测试可能漏检既有 case → **Mitigation**:改写前跑旧正则版本记录 baseline 通过的 assertion 集合,AST 版本至少覆盖相同 case
- **[R3]** Item 3 future-proof fallback 在 3.14+ 真触发时,行为 = 纯 shutdown 无 terminate,可能让未来的 hang worker 再次累积 → **Mitigation**:这是**主动接受的 trade-off**(3.14+ 时 stdlib 应已有 proper 清理);L1 sanity 只验"不崩",不验 hang worker 实际清理效果(3.14 前不会触发 fallback)
- **[R4]** Item 4 `logging.getLogger("app").setLevel(INFO)` 如果生产环境经手操作 env 或某 init hook,可能被覆盖 → **Mitigation**:try/except 兜底;prod handler 默认 warning 级,INFO 日志自然不输出,无额外噪声
- **[R5]** Item 6 真实 evidence_json shape 未来 agent 侧改动可能先破此测试 → **Mitigation**:这正是 regression 网的价值;测试失败时顺道提示维护者更新 DimensionRow 的降级渲染逻辑
- **[R6]** scope 散(跨后端 / 前端 / 测试 / 文档) → **Mitigation**:5 项都走同一主题(前序 hardening 遗留),tasks.md 按 Item 分 section 保持清晰;归档条件 = 全部 [x]

## Migration Plan

零迁移:
- 无 DB schema 变更
- 无 API 契约变更
- 无前端 route / state 变更
- Item 1/3/4 的代码改动对 prod 部署天然兼容(严格更宽松 / 严格更鲁棒 / 严格更可见)
- Rollback:回滚 commit,无残留状态

## Open Questions

(无。5 项均 design 级自决。Item 1 根因已 recon 锁定,Item 2-4+6 方案明确。spec 处理跟 validate 结果走 —— 若强制,写最小 3-scenario ADDED Requirement。)
