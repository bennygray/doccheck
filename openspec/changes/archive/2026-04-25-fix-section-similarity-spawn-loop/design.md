## Context

- `harden-async-infra F1`(archive 2026-04-21)引入 `run_isolated` per-task 子进程隔离,初衷是"坏 docx 触发段错误不再把共享 pool 拉坏"
- `section_similarity` 在迁移到 `run_isolated` 时,scorer.py 把原本 `loop.run_in_executor(get_cpu_executor(), ...)` 的 N 次循环**机械替换**为 N 次 `run_isolated`,等于让原本"共享 pool 复用进程"的隐式优化失效
- 2026-04-26 e2e 实测暴露:per-pair spawn 在 Windows 平台 jieba 冷启动主导耗时,N>50 章节对必超时

## Goals / Non-Goals

**Goals:**
- 把 N 次 spawn 变 1 次 spawn,固定开销(spawn ~230ms + jieba ~600ms + IPC + import)从 O(N) 降到 O(1)
- 保持 `run_isolated` 现有 isolation 契约(per-task 隔离防 broken pool)
- 保持 evidence_json / PairComparison / 既有降级路径**所有产品行为不变**
- spec 锁住"section_similarity 必须批量化"的契约,防未来回归到 per-pair spawn

**Non-Goals:**
- 不引入 long-lived shared pool(破坏 F1 isolation 契约,需要更大 design)
- 不动 `text_similarity` / `structure_similarity`(只调 1 次 spawn,无热点)
- 不调整 `agent_subprocess_timeout` / `AGENT_TIMEOUT_S` 配置(实测单 spawn 路径 N=300 也只 ~70s,120s subprocess timeout 充裕)
- 不引入子进程内并发(N 次纯 TF-IDF 串行总和也只是几百毫秒,不需要)

## Decisions

### D1 helper 函数位置 = `section_sim_impl/scorer.py` 同文件 module-level 函数

理由:
- 必须 module-level(spawn 走 pickle by name,nested 函数不可 pickle)— 这是 Python multiprocessing 硬约束
- 与 scorer 主逻辑紧密耦合,不需要独立文件;scorer.py 里加 ~15 行新函数对可读性影响最小
- 不引入新 module(避免 import 路径震荡)

**备选**:独立 `batch_compute.py` — 排除,过度抽象,只一处用

### D2 helper 接受**纯数据**(段落字符串列表),不接受 ChapterBlock 对象

理由:
- ChapterBlock 含 `paragraphs: tuple[str, ...]`,把整个对象 pickle 过去开销不必要(还要带 title 等无关字段)
- 直接传 `list[tuple[list[str], list[str]]]` 章节对段落数据,IPC 量最小
- 子进程内只调 `c7_tfidf.compute_pair_similarity(a, b, threshold, max_pairs)` 这一纯函数

签名:
```python
def compute_all_pair_sims_batch(
    chapter_pair_data: list[tuple[list[str], list[str]]],
    threshold: float,
    max_pairs: int,
) -> list[list[ParaPair]]:
    return [
        c7_tfidf.compute_pair_similarity(a_paras, b_paras, threshold, max_pairs)
        for a_paras, b_paras in chapter_pair_data
    ]
```

### D3 `run_isolated` timeout 仍用 `settings.agent_subprocess_timeout`(120s)

理由:
- 实测 N=80 章节对单 spawn 内总耗时 ~55s,120s 阈值有 2x 余量
- 极端 N=200 估算 ~140s,会触发 timeout → 走既有 `AgentSkippedError(SUBPROC_TIMEOUT)` → engine 标 skipped(契约不变)
- 不在本 change 调高 timeout,避免改动扩散到 harden-async-infra 的 F1 spec

### D4 失败兜底走既有 fallback 路径

如果 `run_isolated` 抛 `AgentSkippedError`:
- engine 既有契约 `_mark_skipped` 标 task `status=skipped`,summary 含中文降级文案
- 不走章节级 → 整文档级 fallback,因为"批量子进程崩"和"per-pair 子进程崩"信号意义不同(批量崩通常是真异常,不是数据局部问题)
- 这与 archive `agent-skipped-error-guard` 的 except 顺序契约一致(`AgentSkippedError` 在 `Exception` 之前 raise)

### D5 L1 测试 2 case

```python
# tests/unit/test_section_scorer_batch.py

def test_batch_helper_results_equivalent_to_per_pair():
    """compute_all_pair_sims_batch 结果与 N 次单调一致"""
    # 用合成段落构造 3 个章节对
    # 分别跑 batch helper 和 N 次单调
    # 断言 ParaPair 列表逐项相等

@pytest.mark.asyncio
async def test_scorer_calls_run_isolated_exactly_once(monkeypatch):
    """scorer.score_all_chapter_pairs 内 run_isolated 调用次数 = 1(防回归)"""
    call_counter = {"count": 0}
    async def fake_run_isolated(func, *args, timeout):
        call_counter["count"] += 1
        return func(*args)
    monkeypatch.setattr(
        "app.services.detect.agents.section_sim_impl.scorer.run_isolated",
        fake_run_isolated,
    )
    # 构造 5 个章节对的 fixture
    await scorer.score_all_chapter_pairs(...)
    assert call_counter["count"] == 1, f"调用 {call_counter['count']} 次,应为 1"
```

第 2 个 case 是**核心防回归契约** — 钉死"批量化"的代码路径,未来任何把循环改回 per-pair 的 PR 都会红测。

### D6 L2 不新增 case,沿用既有

L2 既有的 `test_section_similarity_*.py`(若有)走的是 mock LLM,且不依赖真 jieba 计算,本 change 不改 schema / API,L2 行为不变。

### D7 manual e2e 验证步骤

1. 重启后端(本 session 已在跑,新代码 import 后即生效;若没 reload 则 kill + 重起)
2. 重新上传 3 供应商 zip(项目 2486 已删,要新建项目)
3. 等解析完成 + 启动检测
4. 检测 status 应显示 25 succeeded(或 24 succeeded + 1 其他 agent 的独立 timeout),`section_similarity` 三个 pair 全部 succeeded
5. 凭证 `e2e/artifacts/fix-section-similarity-spawn-loop-2026-04-26/`:
   - `README.md`:执行步骤 + 期望 / 实际 + before/after section_similarity 状态对比
   - `agent_tasks_after.json`:新一轮检测的 25 个 agent_task 状态 dump

## Risks / Trade-offs

| 风险 | 缓解 |
|---|---|
| 单 spawn 内 N 个章节对总耗时 > 120s subprocess timeout | 实测 N=80 时 ~55s,N=300 时 ~70s,远低于 120s;真有 N>500 的极端场景走 SUBPROC_TIMEOUT → skipped(契约不变) |
| 子进程内 OOM | 章节段落数有 s_config 既有约束,实测 20×20 段落计算内存 < 100MB,N=300 累加 < 30GB(numpy/sklearn 释放及时,不累计) |
| 改动破坏既有 fallback 路径 | scorer.score_all_chapter_pairs 是 run() 的子调用,run() 既有的"切章失败 → 整文档级 fallback" 路径不受影响 |
| L1 mock fixture 与新 helper 签名不匹配 | 新 helper 签名最小化(纯函数 + 纯数据),mock 友好;test case 2 用 monkeypatch 替换 run_isolated 不依赖真 spawn |

## Migration Plan

1. 改 scorer.py(新加 helper + for 循环替换)+ 新 L1 测试文件(1 commit)
2. 部署无需迁移步骤(纯实现优化)
3. Manual:重新上传 zip + 跑检测验证 section_similarity 不再 timeout
4. Rollback:回滚 commit;不改配置 / schema,无遗留状态

## Open Questions

无。Why / What / Decisions 均已与 user 在 propose 阶段对齐(2026-04-26 简略版 review + 实测微基准数据论证)。
