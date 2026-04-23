## Context

`honest-detection-results` 归档时遗留 4 条基础设施鲁棒性问题(F1/N5/N6/N7)。P1 代码调研(2026-04-23)发现与原 design 假设存在三处关键偏差,触发 propose 方案 B(就地重写 artifact):

1. **F1 范围**:共享 `get_cpu_executor()` 被 `section_similarity` / `text_similarity` / `structure_similarity` **三个** agent 使用,不是原假设的两个。
2. **N7 现状**:`OpenAICompatProvider.complete()` **已经**有 `asyncio.wait_for` + 超时捕获 + 返 `LLMResult(error=LLMError(kind="timeout"))`,且 `base.py` 设计原则明确"永远不抛异常"。原 design 的"基类加超时壳 + 新 LLMTimeoutError 异常类"是对既有架构的误读。真正的 N7 问题是 6 个调用点对 `result.error` 的降级不一致。
3. **AgentRunResult 没有 skip_reason 字段**:skipped 状态在 DB 的 `AgentTask.status + summary` 字符串列上表达。原 design 的 Literal 收紧 / 前端字典映射都无所附着。

本 design 基于实际代码结构重写。核心约束:
- 产品行为完全沿用 `honest-detection-results` 的 skipped + 证据不足 + indeterminate 语义(Q1=A / Q2=A 不变)
- **不新建重复抽象**:不加 `LLMTimeoutError` 类(沿用现成 `LLMResult.error`);不加 `AgentRunResult.skip_reason` 字段(沿用 `AgentTask.summary` 文本列);不加前端字典映射(DimensionRow 已渲染 summary)
- **新建唯一的小抽象**:`AgentSkippedError` — 这是 agent → engine 的**一条新信号通道**,因为现有 `_mark_failed` / `_mark_timeout` 都不能产出 `status="skipped"`。没有替代

## Goals / Non-Goals

**Goals**
1. 3 个 CPU 密集 agent(section / text / structure similarity)坏 docx 不拉崩整池,单点失败只标 skipped 不污染其他投标人
2. 6 个 LLM 调用点对 `LLMResult.error` 降级路径齐整;agent 侧超时 → skipped,judge 侧 → 证据不足 indeterminate,role_classifier → 关键词兜底
3. admin 层即便配了巨大 timeout,也有 `LLM_CALL_TIMEOUT=60s` 全局 cap 防御挂起
4. `pytest backend/tests/e2e/` 全量可跑,不再因共享 dev DB 污染卡住
5. `make_gbk_zip` fixture 真实产出 "flag=0 + GBK 文件名",macOS 包场景回归测试真生效
6. 所有新增降级路径在 L1/L2 测试中有明确覆盖

**Non-Goals**
- **不做 LLM 重试 / 退避 / 熔断**(Q2=A:单次超时即 skipped)
- **不做全局任务调度器 / worker pool 框架**(per-call `ProcessPoolExecutor(max_workers=1)` 够用)
- **不改 `LLMProvider.complete()` 契约**("永远不抛异常" 原则保留 — 新增 `AgentSkippedError` 是 agent→engine 层的,不进 LLM 层)
- **不动现有 pipeline fire-and-forget 结构**
- **不解决 N3 LLM 大文档精度退化**(本 change 提供 `AgentTask.summary` 的精细原因码后 `/openspec-explore N3` 单独做)
- **不做 `AgentRunResult.skip_reason` 字段扩展**(reason 靠 summary 文本字段承载,保持和既有 preflight skip reason 一致)
- **不做前端 skip_reason 字典映射**(DimensionRow 直接渲染 summary;前端零改动 — 验证即可,不入 tasks)
- **不做 testdb 的 schema migration 自动化框架**(alembic upgrade head 一次拉齐)

## Decisions

### D1 F1:per-call `ProcessPoolExecutor(max_workers=1)` + asyncio.wait_for,共享 executor 保留

**选定**:在 3 个 agent 各自的 `loop.run_in_executor(get_cpu_executor(), ...)` 调用点换成(**不**用 `with` context manager,因为 `ProcessPoolExecutor.__exit__` 默认 `shutdown(wait=True)` 在子进程挂死时会跟着卡;改 `try/finally + shutdown(wait=False, cancel_futures=True)`):
```python
pool = ProcessPoolExecutor(max_workers=1)
try:
    future = pool.submit(func, *args)
    try:
        return await asyncio.wait_for(
            asyncio.wrap_future(future),
            timeout=AGENT_SUBPROCESS_TIMEOUT,
        )
    except asyncio.TimeoutError:
        raise AgentSkippedError(SKIP_REASON_SUBPROC_TIMEOUT) from None
    except BrokenProcessPool:
        raise AgentSkippedError(SKIP_REASON_SUBPROC_CRASH) from None
finally:
    pool.shutdown(wait=False, cancel_futures=True)
```
`wait=False` + `cancel_futures=True` 在 hang 场景立刻返回,worker 进程会被 Python 运行时最终 kill(进程退出时 SIGKILL 级别清理),不阻塞主协程。**保留**全局 `get_cpu_executor()` singleton 接口:它还被 `engine.py` `shutdown_cpu_executor` 引用作为 C6 框架约定;本 change 只改调用点,不拆 singleton(L2 finding 记录)。

**备选 A**(已否):改共享 pool → 可观测化 + 捕获 `BrokenProcessPool` 后重建
- ❌ 坏 docx 反复触发时 pool 反复重建,成本不稳定
- ❌ 3 个 agent 并发提交时,如何区分"谁导致的 broken"要加额外 correlation,复杂度上升

**备选 B**(已否):用 `asyncio.create_subprocess_exec` + JSON IPC
- ❌ numpy sparse matrix / dataclass 需要改序列化方式,工作量 3 倍

**代价**:每次 agent task 起新进程 ~20-50ms fork+import 开销。`section` / `text` / `structure` 各自是秒级任务,相对成本 <5%,可忽略。

### D2 AgentSkippedError 新异常:Agent → Engine 的 skipped 信号

**问题**:`engine._execute_agent_task` 当前:
- `TimeoutError` → `_mark_timeout`(status="timeout")
- 其他 Exception → `_mark_failed`(status="failed")
- 既没有 `_mark_skipped` 路径给 agent 运行期用(只有 preflight skip)

而 judge 的 `SIGNAL_AGENTS` 证据不足逻辑(honest-detection-results 已建立)依赖 `status="skipped"`。要把 crash/timeout 走进证据不足路径,必须让 engine 能产出 `status="skipped"`。

**选定**:`app/services/detect/errors.py` 新建 `class AgentSkippedError(Exception): pass`。在 `engine._execute_agent_task` 的 `except Exception` 之前加:
```python
except AgentSkippedError as exc:
    await _mark_skipped(session, task, str(exc))
    await session.commit()
    await _publish_agent_status(task)
    return
```

**备选 A**(已否):让 engine 把 `TimeoutError` / `BrokenProcessPool` 直接路由到 `_mark_skipped`
- ❌ 这两个异常也可能来自 agent 非 subprocess 代码(如 LLM 超时已用 asyncio.wait_for 吞在 provider 内,但未来可能加新地方),发生混淆;agent 主动抛 `AgentSkippedError` 语义明确

**备选 B**(已否):给 `AgentRunResult` 加 `skipped: bool` 字段,agent 返回对象时标记
- ❌ 改 NamedTuple 签名是 breaking;`AgentSkippedError` 只在异常路径出现,不污染正常返回值

### D3 N7 LLM 降级:call-site 审计 + 归一,不新建异常

**选定**:保留 `OpenAICompatProvider.complete()` "永远不抛"契约;6 个调用点按职责归一降级:

| 调用点 | 现状(recon) | 本 change 动作 |
|---|---|---|
| `parser/llm/role_classifier.py:111` | ✓ 已 fallback `classify_by_keywords`,`role_confidence='low'` | 保留。加精细化 summary log(写入 bidder 日志上下文,区分 timeout / rate_limit / other) |
| `detect/judge_llm.py:438` | 检查 `result.ok`,非 ok 时走既有降级分支 | 确认降级分支返 `indeterminate + INSUFFICIENT_EVIDENCE_CONCLUSION`(honest-detection-results 已有);必要时补 wiring |
| `detect/agents/style_impl/llm_client.py:120` | 检查 `result.ok`,非 ok 时... | 审计:若 agent 无本地兜底 → raise `AgentSkippedError(SKIP_REASON_LLM_<kind>)`;有兜底 → 保留 |
| `detect/agents/error_impl/llm_judge.py:111` | 有 attempts 重试逻辑(历史遗留) | 保留重试(局部快速重试,<=3 次),最终失败 → raise `AgentSkippedError`;**不**把重试提到全局原则层 |
| `detect/agents/text_sim_impl/llm_judge.py:156` | `if result.error.kind not in ("bad_response", "other")` 的分支奇怪 | 审计并归一到统一白名单:所有 timeout / rate_limit / auth / network → skipped;bad_response / other → 保留既有处理 |
| `parser/llm/price_rule_detector.py:82` | 记日志然后... | 审计:parser 内部不抛 AgentSkippedError(parser 不是 agent);按既有兜底路径继续 |

**不在本 change 的 6 调用点范围内**:
- `admin-llm-config` 的 `tester.py`(admin LLM 连通性测试 API):独立降级路径 — UI 直接回显 `LLMResult.error.kind`,给 admin 看;不走 skipped 语义(测试 API 不是业务流水线)
- `image_reuse` agent:**不调 LLM**(image 维度走 pHash + MD5 纯算法);早期设计文档提及 LLM 但实现未落地。spec / task 不覆盖
- `metadata_*` / `price_consistency` / `price_anomaly` / `style` preflight:不走 provider.complete()

**备选 A**(已否):在 provider 基类抛 `LLMTimeoutError`
- ❌ 违反 `complete() 永远不抛` 设计原则;影响面比需要的大

**备选 B**(已否):写一个通用 `handle_llm_error(result, *, agent_name)` 装饰器
- ❌ 6 个调用点降级语义各异(fallback 关键词 vs indeterminate vs skipped),通用化反而扭曲;审计归一后每处写 3-5 行 clear-site 更好读

### D4 LLM_CALL_TIMEOUT 全局 cap = 60s(**两路径统一覆盖 + None/0/负数防御**)

**选定**:`config.py` 加 `LLM_CALL_TIMEOUT`(env 覆盖,默认 60)。`app/services/llm/factory.py` 有两条 provider 构造入口 —— `get_llm_provider()`(env 直读 `settings.llm_timeout_s`) 与 `get_llm_provider_db()`(DB 读 `cfg.timeout_s`)。**两路径都必须过 cap**。在 `_build_provider`(或 `_get_or_create` 缓存 key 归一前)统一 helper:

```python
def _cap_timeout(raw: float | int | None) -> float:
    cap = settings.LLM_CALL_TIMEOUT  # default 60, env overridable
    if raw is None or raw <= 0:
        return cap  # None / 0 / 负数都走默认 cap,不塌陷为 0
    return min(float(raw), cap)
```

两个入口在构造 `OpenAICompatProvider(..., timeout_s=_cap_timeout(raw))` 前都调它。`_get_or_create` 的 cache key 第 4 元素(timeout)也用 capped 值,防止"先小后大"场景绕过。

**理由**:
- dashscope / openai 正常 completion 耗时 2-15s,60s 给 4-30x 余量;超过 60s 基本可认定挂起
- None/0/负数防御:admin-llm-config DB 若 NULL 或误写 0,`min(0, 60)=0` 会让 `asyncio.wait_for(timeout=0)` 立即超时,所有 LLM 无条件失败 —— 必须兜底到默认 cap
- env 路径也过 cap:避免 `export LLM_TIMEOUT_S=600` 直接穿透

**不做**:admin-llm-config 写入端校验 ≥1。理由 = 写端防御脆弱(多入口可绕过),读端(factory)统一 cap 是单一收口。

### D5 AGENT_SUBPROCESS_TIMEOUT = 120s

**选定**:120s。理由:
- `section` / `text` / `structure_similarity` 正常场景 <5s(小文档) ~ 30s(大文档)
- 159MB A/B 场景实测 `text_similarity` 约 45-80s,120s 给 2x 余量
- 超过 120s 基本可认定为死锁 / OOM swap

### D6 skipped 原因文案规范 = `"<具体原因>,已跳过"`(≤50 字)+ **集中常量模块**

**选定**:所有新增 skipped summary 遵循格式 `"<具体原因>,已跳过"`,中文,最长 50 字。**集中写在 `backend/app/services/detect/errors.py`** 暴露为模块级常量(`SKIP_REASON_SUBPROC_CRASH` / `SKIP_REASON_SUBPROC_TIMEOUT` / `SKIP_REASON_LLM_TIMEOUT` / `SKIP_REASON_LLM_RATE_LIMIT` / `SKIP_REASON_LLM_AUTH` / `SKIP_REASON_LLM_NETWORK` / `SKIP_REASON_LLM_BAD_RESPONSE`),所有 `raise AgentSkippedError(...)` 站点引用常量,禁止字符串硬编码。L1 测试 `test_skip_reason_constants.py` assert 常量值 = 下表文字。

已建立的 preflight skip reason(`"无目标文档"` / `"证据不足"` 等旧文案)**保持不动**,不强制加 "已跳过" 后缀。理由:preflight reasons 已在生产路径稳定、前端 / Word 导出层已验证可读;强行统一后缀会引入无价值 churn。**UI 视角两种风格共存可读即可**,新的降级原因带"已跳过"后缀 + 旧的不带,不影响判断。

具体原因词表:

| 触发场景 | summary 文案 |
|---|---|
| `section/text/structure_similarity` subprocess 崩溃 | "解析崩溃,已跳过" |
| 同上 subprocess 超时 | "解析超时,已跳过" |
| agent LLM 分支 timeout | "LLM 超时,已跳过" |
| agent LLM 分支 rate_limit | "LLM 限流,已跳过" |
| agent LLM 分支 auth | "LLM 鉴权失败,已跳过" |
| agent LLM 分支 network | "LLM 网络错误,已跳过" |
| agent LLM 分支 bad_response / other | "LLM 返回异常,已跳过" |

**前端渲染**:DimensionRow 现有就按 summary 渲染(recon 确认,task 1.1 验证),**零新增映射**。

### D7 N5 testdb 容器化设计

**docker-compose.test.yml**:独立 postgres 服务 `postgres-test`,端口 `${TEST_DB_PORT:-55432}` 避免冲突,DB 名 `documentcheck_test`,volume 匿名(`down -v` 清零)。

**conftest.py 切换**:
```python
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
if not TEST_DATABASE_URL:
    pytest.exit("TEST_DATABASE_URL not set. Run docker-compose -f docker-compose.test.yml up -d first.", returncode=2)
```
**失败策略**:显式 exit 2,不默认退回到 dev DB。

**隔离粒度**:session 开始 `alembic upgrade head`;module 开始 `TRUNCATE ... RESTART IDENTITY CASCADE`(比 drop/create 快 10x)。

**已否备选**:`testcontainers-python`(新增依赖 + docker daemon 启动每次 ~20s);SQLite in-memory(PostgreSQL 专属语法漂移)。

### D8 N6 fixture 重写 = 抽 `build_zip_bytes` helper + 复用

**行动**:
1. 从 `backend/tests/unit/test_engine_utf8_no_flag.py` 抽出 ZIP 手写字节代码到 `backend/tests/fixtures/zip_bytes.py::build_zip_bytes(entries: list[tuple[bytes, bytes]], *, flag_bits: int) -> bytes`
2. `archive_fixtures.py::make_gbk_zip` 重写为 `build_zip_bytes([(name.encode("gbk"), content), ...], flag_bits=0)`
3. `test_engine_utf8_no_flag.py` 改用新 helper 去重

**自审**:这是对**已验证可行字节序列**的抽取,不是预测性设计 — `honest-detection-results` 已经在生产路径验证该字节布局正确。

## Risks / Trade-offs

- **[Risk 1]** per-call `ProcessPoolExecutor` 每次起进程 ~20-50ms 开销,3 个 agent 吞吐略降
  → **Mitigation**:这 3 个 agent 本身秒级,相对开销 <5%;非吞吐敏感路径

- **[Risk 2]** `BrokenProcessPool` 异常类在 Python 3.12+ 位于 `concurrent.futures.process.BrokenProcessPool`,3.11 有别的导入路径
  → **Mitigation**:项目 Python 3.12+(CLAUDE.md 已声明),按 3.12 导入;兼容层用 try/except ImportError 兜底

- **[Risk 3]** 6 个 LLM 调用点归一后,`error_impl/llm_judge.py` 的历史 attempts 重试逻辑保留,可能让"LLM 限流"场景等比扩大 3x QPS 成本
  → **Mitigation**:保留既有 attempts=3(不改),记录在 design 供未来 N3 explore 一并评估;**不在本 change 修改**以免 scope 扩散

- **[Risk 4]** `AgentSkippedError` 新异常类可能被 `except Exception` 过早捕获,导致走 failed 路径而非 skipped
  → **Mitigation**:engine `except AgentSkippedError` 放在 `except Exception` 之前;L1 测试专门 assert 捕获顺序

- **[Risk 5]** docker-compose.test.yml 端口 55432 和本地其他服务冲突
  → **Mitigation**:`${TEST_DB_PORT:-55432}` 参数化,README 注明

- **[Risk 6]** 重写 `make_gbk_zip` 后历史 L2 用例(`test_extract_api.py`)可能行为细微变化
  → **Mitigation**:重写前跑一遍现有 `test_extract_api.py` 记 baseline,diff 为空才算对齐

- **[Risk 7]** CI 没 docker daemon → L2 全量失败
  → **Mitigation**:现有 `docker compose up` 命令说明 CI 有 docker;若真缺,L2 启动前 `docker info || skip`(退回到 change 前状态等价)

- **[Risk 8]** 3 个 CPU agent 的 subprocess 超时 (`AGENT_SUBPROCESS_TIMEOUT=120s`) 与 engine 外层 `AGENT_TIMEOUT_S=300s` 形成两层,外层若先触发会抛 `TimeoutError`(引擎 `wait_for`),子进程可能残留
  → **Mitigation**:正常路径内层 120s 先触发,`finally: pool.shutdown(wait=False, cancel_futures=True)` 立刻解除阻塞(不等 worker 优雅退出,避免 hang)。L1 测试构造 `func=while True: pass + timeout=0.1` 连续 5 次,验证 `psutil.Process().children()` 不残留 zombie

- **[Risk 9]** `pool.shutdown(wait=False, cancel_futures=True)` 返回后 worker 进程仍在跑未完成任务(如 `while True`),不被自动清理(apply 期 L1 测试实测暴露 — reviewer H1 的担忧实质成立,非 paper risk)
  → **Mitigation**(已实装):`run_isolated` finally 主动 terminate/kill:`pool._processes` 取所有 worker 引用,`shutdown(wait=False, cancel_futures=True)` 后依次 `proc.terminate() → join(0.3s) → proc.kill() → join(0.3s)`。`pool._processes` 是 Py 3.8~3.13 稳定的 stdlib 属性,per-call pool 无 race 问题。L1 `test_hang_workers_do_not_accumulate` 5 次 hang 跑验证 alive children ≤10(实测 0 秒内释放完毕)

## Migration Plan

**零迁移**:
- 无 DB schema 变更
- 无 API 契约变更(新增 summary 文案仅文字内容变化)
- 新增配置(`AGENT_SUBPROCESS_TIMEOUT` / `LLM_CALL_TIMEOUT` / `TEST_DATABASE_URL`)有默认值,既有部署零改动生效
- 无前端 route / state 变更

部署顺序:后端镜像更新 → 生效;前端零改动。

**Rollback**:直接回滚前一个 commit,无残留状态(AgentTask skipped 原因文案的历史行不影响 judge,已被覆盖或保留均无副作用)。

## Open Questions

(无。Q1/Q2 产品决策已对齐;N5/N6 纯测试基础设施按 D7/D8 自决;reviewer 可能在 apply 期发现细节再加。)
