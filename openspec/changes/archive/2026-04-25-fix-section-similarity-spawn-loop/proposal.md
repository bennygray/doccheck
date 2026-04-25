## Why

`section_similarity` agent 在 2026-04-25 / 2026-04-26 两次真实 e2e(投标文件模板 2,3 供应商)实测 100% timeout(>300s),三对 pairwise 的 `agent_tasks.elapsed_ms` 精确卡在 300149/302205/301276 — 不是 LLM 慢,是 [`scorer.py:58-70`](backend/app/services/detect/agents/section_sim_impl/scorer.py#L58-L70) 的 for 循环对**每个章节对都新 spawn 一个 ProcessPoolExecutor**:

```python
for cp in chapter_pairs:
    pairs = await run_isolated(c7_tfidf.compute_pair_similarity, ..., timeout=120)
```

[`run_isolated`](backend/app/services/detect/agents/_subprocess.py#L57) 是 harden-async-infra F1 的 per-task 隔离 helper(每次 `ProcessPoolExecutor(max_workers=1)`)。设计意图是"per-call 隔离防 broken pool 拖死共享 singleton",但 scorer 的 N 次循环把 isolation 优势变成性能灾难:

**微基准**(本机 Windows / Python 3.13,2026-04-26):

| 操作 | 实测耗时 |
|---|---|
| `run_isolated(noop)` 纯 spawn 开销 | 230 ms |
| 子进程内 jieba 词典冷启动(每次新子进程必跑) | ~600 ms |
| `run_isolated(c7_tfidf.compute_pair_similarity)` 含 spawn + jieba + 计算 + IPC | **3.0 s/次** |
| TF-IDF 纯计算(主进程,jieba 已热,20×20 段落) | ~7 ms |

**估算**:N=80 章节对 → 240s,撞 300s 阈值;真实数据可能 N>50 就开始 flaky。固定开销 spawn(~230ms) + jieba 冷启动(~600ms) + numpy/sklearn import + IPC 序列化每次都要重做,**真正杀手是 jieba**,不是 spawn 本身。

把 for 循环移进**单个** `run_isolated` 调用,N 次固定开销变 1 次:**N=80 → 55s,5x 加速**;N=300 也只要 ~70s,把 timeout 风险彻底从这条路径上消除。

## What Changes

- 新加内部 helper `compute_all_pair_sims_batch(chapter_pair_data, threshold, max_pairs)`(放 `section_sim_impl/` 下,可在 `scorer.py` 同文件或独立 `batch_compute.py`):接收所有章节对的段落数据,在子进程内单次循环计算 TF-IDF,返回 `list[list[ParaPair]]`
- 改 [`scorer.py:58-70`](backend/app/services/detect/agents/section_sim_impl/scorer.py#L58-L70):把 N 次 `await run_isolated(c7_tfidf.compute_pair_similarity, ...)` 替换成 1 次 `await run_isolated(compute_all_pair_sims_batch, ...)`
- 子进程 timeout 不动(仍 `agent_subprocess_timeout=120s`):单 spawn 内做 N 次纯 TF-IDF 计算,实测 N=80 时 ~50s 完成,余量充裕

**不动**:
- `run_isolated` / `_subprocess.py` 一行不改 — isolation 契约保留
- `text_similarity` / `structure_similarity` agent 不动(只调一次 `run_isolated`,无循环热点)
- `agent_subprocess_timeout` / `AGENT_TIMEOUT_S` 配置不动
- `evidence_json` schema / `PairComparison` 写库 / preflight 逻辑 / fallback 整文档级降级路径全不动 — **零产品行为变化**,纯性能优化

## Capabilities

### New Capabilities
(无)

### Modified Capabilities
- `pipeline-error-handling`: Requirement "ProcessPool per-task 进程隔离" 加 1 个 scenario,锁住"section_similarity 章节对计算 SHALL 在单一子进程内批量完成,不得 per-pair 调 `run_isolated`"的契约,防止未来回归

## Impact

- 代码:scorer.py 改 ~10 行(for 循环替换)+ 新 helper ~15 行,共 1-2 文件
- 测试:+1 L1 文件 2 case(结果一致性 + run_isolated 调用次数 = 1 防回归),+1 [manual] 重跑 e2e 验证 section_similarity 不再 timeout
- Spec:1 delta 修改 pipeline-error-handling 的 1 个 Requirement(+1 scenario)
- 部署:零配置改动
- 行为:`section_similarity` 维度从 100% timeout 变成 succeeded,围标信号回归;之前 v2 已有 22 succeeded 即将变成 24~25 succeeded(剩下 1 timeout 是其他 agent 的独立问题或为 0)
- 凭证:`e2e/artifacts/fix-section-similarity-spawn-loop-2026-04-26/`(README + before/after section_similarity task 状态对比)
