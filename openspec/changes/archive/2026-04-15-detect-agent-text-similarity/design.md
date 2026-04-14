## Context

### 现状(C6 归档后)

- `AGENT_REGISTRY["text_similarity"]` 已注册,preflight = "双方在 bidders_share_any_role 上有同角色文档";run 目前走 `dummy_pair_run`(0.2~1.0s sleep + 随机 0~100 分)
- `AgentContext.llm_provider` 字段存在但 C6 建 ctx 时传 `None`(`engine.py::_build_ctx`)
- `get_cpu_executor()` lazy 单例 + `shutdown_cpu_executor()` 在 FastAPI lifespan shutdown 释放 — C6 无真 Agent 消费,C7 是首个真消费者
- `PairComparison` 表字段:`project_id / version / bidder_a_id / bidder_b_id / dimension / score / is_ironclad / evidence_json / created_at`;dummy 写 `evidence_json={"dummy": True}`
- `DocumentText` 表(C5)存每文档全文 + 分段(段落粒度 `para_index`);C7 从这里取段落
- `BidDocument.doc_role` 在 C5 被 role_classifier 填入(技术/商务/报价表/其他/未知)
- LLM 适配层 `app/services/llm/base.py`:`LLMProvider.complete(messages, ...) -> LLMResult(text, error)`;C5 `ScriptedLLMProvider` 测试 mock 模式沉淀
- 测试环境变量:`INFRA_DISABLE_DETECT=1` 跳过自动调度(L2 测试构造 AgentTask 但不触发 run);C7 大部分 L1/L2 测试直接 `AGENT_REGISTRY["text_similarity"].run(ctx)` 不走 engine

### 约束

- **C6 contract 锁定**:AGENT_REGISTRY 注册 key、preflight 签名与现有"同角色文档存在"判断、AgentContext / AgentRunResult / PreflightResult 字段、engine.py / judge.py / registry.py、其余 9 Agent 模块**全不改**;只改 `text_similarity.py::run()` + 新增 `text_sim_impl/` 子包
- **零新增第三方依赖**:jieba / sklearn / numpy C5 已引入;不加 sentence-transformers / torch
- **score ∈ [0, 100]**:DB `Numeric(6, 2)`,超范围 IntegrityError
- **LLM 5min 硬超时**:engine 外层 `asyncio.wait_for(spec.run, timeout=AGENT_TIMEOUT_S)`,run 内部 LLM 重试 ≤ 1 次,单次 LLM 调用 ≤ 60s,确保总时间 < 5min
- **单 pair 最多 30 段送 LLM**:防 token 爆炸(TEXT_SIM_MAX_PAIRS_TO_LLM 默认 30)
- **CPU 密集段必须走 executor**:TF-IDF 向量化 + cosine 矩阵计算,单 pair 可能上万段对,在协程主线程跑会阻塞整个 event loop

### 干系方

- **审查员(用户)**:报告页 text_similarity 行看到真实分数 + 段落对证据(template/generic/plagiarism 标签)
- **后续 Agent 实施者(C8~C13)**:`text_sim_impl/segmenter + tfidf` 骨架在 C8(section_similarity)可复用(章节级换更粗粒度分块)
- **运维**:C7 后容器启动需 `cpu_count()` 正确识别(cgroup),max_workers 合理;jieba 首次加载词典 ~1s 延迟(启动时 warmup 还是 lazy?)

## Goals / Non-Goals

### Goals

1. **双轨分工落地**:本地 TF-IDF 始终跑(切段 + 算分 + 筛超阈值对);对筛出的高相似段落对调 LLM 定性(template/generic/plagiarism);LLM 失败 → 仅程序分数 + "AI 研判暂不可用"
2. **CPU 密集走 executor**:TF-IDF 向量化 + cosine 矩阵在 `get_cpu_executor()` 里跑,主协程不阻塞
3. **PairComparison.score 语义对齐 judge**:整 pair 级 score(0~100,跨所有段落对的最高/加权),judge.py 的 `per_dim_max = max(pc.score)` 直接消费
4. **is_ironclad 判定**:LLM 返 `plagiarism` 的段落对数 ≥ 3 或占比 ≥ 50% → is_ironclad=true;降级模式(LLM 失败)永远 false
5. **evidence_json 结构化**:存段落对明细(A/B 段落索引 / 向量分数 / LLM 标签 / 摘要),前端报告页可渲染证据卡
6. **5 验证场景全绿**(execution-plan §3 C7):抄袭命中 / 独立不误报 / 3选1命中 / 极短跳过 / LLM降级
7. **LLM Mock 统一入口**:`llm_mock.py` 扩 3 fixture(success / bad_json / timeout)+ 1 工厂,L1/L2/L3 复用

### Non-Goals

- **章节级相似度**:C8 `section_similarity` 做,C7 只做整文档(按段落切但不按章节聚合)
- **结构相似度**:C9
- **跨语言 / 翻译围标识别**:中文场景第一期不做
- **embedding / 语义改写识别**:用 TF-IDF 近字面相似,改写抄袭命中率偏低接受
- **LLM 两次以上重试**:engine 外层超时硬卡;只做 1 次重试(失败立刻降级)
- **缓存跨版本 / 跨 pair**:version+1 重检就全量重跑,简单正确
- **PaddleOCR 图片文字再提取**:用 DocumentText 已有文本,不补图片 OCR

## Decisions

### D1 — 分块策略:段落 + 短段合并 + 超短文档 skip

**决策**:
- 段落来源:`DocumentText.content` 按 `\n\n` 和 `\n` 两级分割得到段落列表(C5 已按段落存,直接用 `DocumentText.paragraphs` 字段)
- 短段合并:相邻段落字符数 < 50 合并,直到 ≥ 50 或到末尾
- 超短文档:pair 中任一 bidder 的"同角色文档总字符数 < `TEXT_SIM_MIN_DOC_CHARS`(默认 500)" → preflight 阶段就 skip,reason = "文档过短无法对比"
  - **注意**:这不破坏 C6 preflight contract — preflight 函数签名不变,只是在原"同角色文档存在"之后加一层字数检查;C6 归档的 preflight spec 本身没有描述字数下限,新增算行为增强不冲突(走 ADD 操作而非 MODIFY)
- 同角色文档多份:取"技术方案" role 的第一份(按 `BidDocument.id` 升序);无技术方案再退化到"商务"、"其他"

**替代方案**:
- 按句切(按 `。!?` 中文标点)→ 粒度过细,TF-IDF 每段词数太少,噪声大
- 按固定 500 字窗口切 → 跨越段落边界,语义切裂
- 整文档一次 TF-IDF → 失去段落粒度证据,无法定位哪段抄了哪段

**理由**:docx 原生段落是"作者逻辑单位",jieba 分词 + TF-IDF 在此粒度最稳;短段合并缓解过细问题;超短 skip 对齐 execution-plan 场景 4

### D2 — TF-IDF + cosine 的超参数与算法细节

**决策**:
```python
# text_sim_impl/tfidf.py(同步函数,由调用方 run_in_executor 包)
def compute_pair_similarity(
    paras_a: list[str],
    paras_b: list[str],
    threshold: float = 0.70,  # 来自 TEXT_SIM_PAIR_SCORE_THRESHOLD
) -> list[ParaPair]:
    # 1. jieba.cut 分词,去停用词(短列表 ~30 词)
    # 2. TfidfVectorizer(tokenizer=jieba_cut, ngram_range=(1, 2),
    #                    min_df=1, max_df=0.95, max_features=20000)
    # 3. vectorizer.fit_transform(paras_a + paras_b) — 联合 vocab
    # 4. 切回 a/b 两块稀疏矩阵
    # 5. cosine_similarity(mat_a, mat_b) → (|A|, |B|) 矩阵
    # 6. 枚举 i,j 取 sim >= threshold 的对 → ParaPair(i, j, sim)
    # 7. 按 sim 降序返回,上限 TEXT_SIM_MAX_PAIRS_TO_LLM(30)
    ...
```

- 停用词:`text_sim_impl/stopwords.py`(约 30 个中文虚词 + 投标文档高频无关词如"项目""公司""本")
- `max_features=20000`:单 pair 词表上限,防极端长文档爆内存
- `min_df=1`:保留长尾(围标抄袭常共享低频词)
- `ngram_range=(1, 2)`:unigram + bigram 兼顾词项和短语
- 稀疏矩阵内存:|A|×|B| 段落对矩阵单 pair 典型 200×200 = 40000 float,数 MB,可接受
- jieba 词典 warmup:`text_sim_impl/__init__.py` 模块级 `jieba.initialize()` 触发惰性加载前置;首个 Agent 启动前跑一次

**替代方案**:
- BM25 → 对长文档偏置控制更好但 jieba+sklearn 无现成实现,加实现代价
- SimHash → 快但粒度粗,段落级不适
- 直接 char-ngram → 中文抄袭对词义敏感,char-ngram 会被小改写绕过

### D3 — LLM Prompt 与 JSON 解析(按 requirements §10.8 L-4)

**决策**:Prompt 完全对齐 §10.8 L-4,单次调用发一个 pair 的全部 ≤ 30 个段落对。

```text
[System]
你是围标文本抄袭检测专家。对下列投标人 A / B 的高相似段落对,
判断每对属于 template(模板雷同)/ generic(行业通用表述)/ plagiarism(同源抄袭)。
仅返回 JSON,不要解释文本。

[User]
投标人 A:{bidder_a.name}
投标人 B:{bidder_b.name}
文档角色:{doc_role}

段落对列表:
{json.dumps([{"idx": i, "a": p.text_a, "b": p.text_b, "sim": p.sim} for i, p in enumerate(pairs)])}

请返回:
{
  "pairs": [
    {"idx": 0, "judgment": "plagiarism|template|generic", "note": "简短说明"}
  ],
  "overall": "该 pair 整体结论",
  "confidence": "high|medium|low"
}
```

**JSON 解析**:
1. 先 `json.loads(response.text)`;失败 → 尝试 `json.loads(re.search(r"\{.*\}", text, re.DOTALL).group())` 剥除可能的 markdown code fence
2. 仍失败 → LLM 重试 1 次(重新组 prompt)
3. 仍失败 → 降级:所有段落对 judgment="generic"(保守),整体结论"LLM 返回格式异常"
4. 成功但 `pairs` 数量与输入不匹配 → 按 idx 对齐,漏掉的补 judgment="generic"

**降级保底**:LLM 错误种类任一出现(timeout / rate_limit / network / parse_fail)→ 整 Agent 进"降级模式",走 D5

**单次 LLM 调用超时**:60s(provider 层设,不在 text_sim 内再套)

### D4 — score 汇总(段落对 → pair 级 score 0~100)

**决策**:
```python
def aggregate_pair_score(para_pairs: list[ParaPair], llm_judgments: dict[int, str]) -> float:
    # 权重:plagiarism=1.0, template=0.6, generic=0.2
    WEIGHT = {"plagiarism": 1.0, "template": 0.6, "generic": 0.2, None: 0.3}  # None = LLM 未标
    if not para_pairs:
        return 0.0  # 无超阈值对
    scored = [
        p.sim * 100 * WEIGHT.get(llm_judgments.get(i), 0.3)
        for i, p in enumerate(para_pairs)
    ]
    # 混合 max + mean:max 捕获最尖锐抄袭,mean 防单点误报,取 max*0.7 + mean*0.3
    return round(max(scored) * 0.7 + (sum(scored) / len(scored)) * 0.3, 2)
```

**降级模式**(LLM 失败):`llm_judgments = {}`,全部按 `None` 权重 0.3 → 等效 `0.3 * 100 * sim_avg`,评分保守

**is_ironclad**:
```python
def is_ironclad(llm_judgments: dict[int, str]) -> bool:
    if not llm_judgments:  # 降级模式无铁证
        return False
    plag_count = sum(1 for j in llm_judgments.values() if j == "plagiarism")
    return plag_count >= 3 or (plag_count / len(llm_judgments) >= 0.5)
```

**理由**:
- score 需同时反应"最尖锐"和"平均面",max+mean 加权是工业界常用折衷
- plagiarism 权重 1.0,template 0.6,generic 0.2 — 对齐 requirements 铁证优先
- is_ironclad 降级时为 false 严格对齐 §10.8 L-4 "LLM 失败不做铁证判定"

### D5 — LLM 降级模式(execution-plan 场景 5)

**决策**:进入降级的触发条件:
- provider 返 `LLMResult.error` 非空(kind ∈ timeout / rate_limit / network / other)
- JSON 解析两次(初 + 1 重试)都失败

降级行为:
- `llm_judgments = {}`(空)
- `score` 按 D4 公式算(全部 None 权重 0.3)
- `is_ironclad = False`
- `summary = "AI 研判暂不可用,仅展示程序相似度(降级)"`
- `evidence_json.ai_judgment = null` + `evidence_json.degraded = true`

**替代**:重试 2~3 次 → 用户久等且仍可能失败,5min 硬超时压力大;拒

### D6 — CPU 密集 via ProcessPoolExecutor(C6 Risk-1 首验)

**决策**:
```python
async def run(ctx: AgentContext) -> AgentRunResult:
    # 1. 协程内:加载双方段落(DB 查)
    paras_a, paras_b = await _load_paragraphs(ctx.session, ctx.bidder_a, ctx.bidder_b)
    if len(...) < MIN_DOC_CHARS:
        return _skip_result("文档过短")

    # 2. CPU 密集:切到 executor
    loop = asyncio.get_running_loop()
    pairs = await loop.run_in_executor(
        get_cpu_executor(),
        compute_pair_similarity,
        paras_a, paras_b, THRESHOLD,
    )

    # 3. LLM 调用:回协程
    if pairs:
        llm_judgments = await _call_llm_judge(ctx.llm_provider, ...)
    else:
        llm_judgments = {}  # 无超阈值对,跳 LLM

    # 4. 汇总 + 写 PairComparison
    score = aggregate_pair_score(pairs, llm_judgments)
    is_ironclad = compute_is_ironclad(llm_judgments)
    await _persist_pair_comparison(ctx.session, ..., score, is_ironclad, evidence)
    return AgentRunResult(score=score, summary=..., evidence_json=...)
```

**jieba + sklearn 进进程池的 pickle 问题**:`compute_pair_similarity` 是纯函数,入参是 `list[str]`,返回 list[ParaPair] dataclass;全部可 pickle。`TfidfVectorizer` 在子进程内 new,不跨进程传递。

**executor cancel 风险(C6 Risk-1)**:若 engine 外层 `asyncio.wait_for` 超时,`run_in_executor` 的 future 被 cancel,但子进程任务已 submit,无法真中断 — 子进程继续跑到完。缓解:
- 限制 `max_features=20000 + MAX_PAIRS=30` 确保单次 executor 任务 < 30s
- 5min agent 超时 > 60s LLM 超时 + 30s TF-IDF,有余量
- 不治本,但 C7 场景够用;真正的 Process.kill 留 C17 或更后的 change

**max_workers 验证**(C6 Q3):
- C7 实施期跑 `docker exec backend python -c "import os; print(os.cpu_count())"` 验证 cgroup 是否正确
- 若容器显示 host 全部核,考虑读 `/sys/fs/cgroup/cpu.max`(但这是 cgroup v2,v1 路径不同)
- **C7 不实施 cgroup 解析**,只验证并记录结论(若有问题 → 开独立 follow-up)

### D7 — evidence_json 结构

**决策**:
```json
{
  "algorithm": "tfidf_cosine_v1",
  "doc_role": "技术方案",
  "doc_id_a": 123,
  "doc_id_b": 456,
  "threshold": 0.70,
  "pairs_total": 18,
  "pairs_plagiarism": 5,
  "pairs_template": 8,
  "pairs_generic": 5,
  "degraded": false,
  "ai_judgment": {
    "overall": "技术方案章节存在大面积同源抄袭",
    "confidence": "high"
  },
  "samples": [
    {"a_idx": 3, "b_idx": 5, "a_text": "...", "b_text": "...", "sim": 0.92, "label": "plagiarism", "note": "..."}
  ]
}
```

`samples` 最多存 10 条(按 sim 降序前 10),全部段落对不存(避免 JSONB 过大);前端报告页展开 samples 渲染证据卡。

### D8 — 测试分层策略

- **L1(`backend/tests/unit/`)**:
  - `test_segmenter.py`:超短文档识别 / 短段合并 / 多 role 回退
  - `test_tfidf.py`:空输入 / 单段输入 / threshold 边界 / max_features 截断
  - `test_llm_judge.py`:prompt 组装 / JSON 解析成功路径 / bad_json 解析降级 / 段数不匹配补齐
  - `test_aggregator.py`:plagiarism≥3 → is_ironclad / 全 generic 保守分 / 空 pair 零分
  - `test_text_similarity_run.py`(Agent 主流程):Mock session + Mock llm_provider,串联 preflight + run 主路径 / LLM 降级 / 超短 skip
- **L2(`backend/tests/e2e/`)**:
  - `test_detect_text_similarity.py`:启动检测(2 bidder,预埋技术方案同文本)→ 等检测完成 → 验证 `text_similarity` AgentTask.status=succeeded + PairComparison 行 + is_ironclad / evidence_json 结构
  - mock `ctx.llm_provider` 通过 monkeypatch `engine._build_ctx` 注入 `ScriptedLLMProvider`
  - 覆盖 3 scenario:抄袭命中(高 score + is_ironclad)/ 独立不误报(低 score)/ LLM 失败降级(degraded=true)
- **L3(`e2e/`)**:延续 C5/C6 降级手工凭证(Docker Desktop kernel-lock 未解除);准备 `e2e/artifacts/c7-2026-04-14/README.md` 占位 + 3 张截图计划(启动检测 / 报告页文本相似度行 / 证据卡展开)

### D9 — jieba 词典 warmup

**决策**:`text_sim_impl/__init__.py` 导入时不 warmup(会拖慢 FastAPI 启动 ~1s),改在 `run()` 内首次调用时 `jieba.initialize()`(idempotent,后续调用 no-op)。warmup 开销落在第一个 text_similarity Agent task,后续并发都能复用。

**替代**:FastAPI lifespan startup 里 warmup → 拖慢启动,C7 单测也会被影响;拒

### D10 — 环境变量命名与默认

| env | 默认 | 作用 |
|---|---|---|
| `TEXT_SIM_MIN_DOC_CHARS` | 500 | 单文档总字符数 < 此值 → preflight skip "文档过短" |
| `TEXT_SIM_PAIR_SCORE_THRESHOLD` | 0.70 | 段落对 cosine 相似度 ≥ 此值才进 LLM 候选 |
| `TEXT_SIM_MAX_PAIRS_TO_LLM` | 30 | 单 pair 最多发送的段落对数(防 token 爆炸) |

所有 env 在 `text_sim_impl/config.py` 统一读取(动态,每次 run 读一次,测试 monkeypatch 友好);写入 `backend/README.md` C7 段。

## Risks / Trade-offs

- **[R-1] sklearn 进进程池首次启动慢**:子进程首次 import sklearn + numpy ~500ms;ProcessPoolExecutor lazy 创建 workers 所以只影响第一个 task;不影响正确性,只是首个 pair 检测慢。→ 接受;生产侧 warmup 可在 lifespan 里触发一次空 `run_in_executor(lambda: None)` 强制 workers 启动
- **[R-2] executor task cancel 无法真中断**:C6 Risk-1 的具体化;缓解同 D6 尾;未彻底解,留 follow-up
- **[R-3] LLM 返回非 JSON 或结构畸变**:两次重试无过度成本;降级路径保守分(generic 权重 0.3)兜底
- **[R-4] 段落数极端(单文档 >5000 段)**:`max_features=20000` 限词表,sim 矩阵 5000×5000 × 4 byte = 100MB,极端但内存可承受;若真遇到,限制单文档最多取前 2000 段(再补 `TEXT_SIM_MAX_PARAGRAPHS` env)→ C7 初版不做,留运维监控
- **[R-5] jieba 首 task 延迟 ~1s**:延迟体现在 agent_task.elapsed_ms,用户对单 Agent 感知不强;若介意 → lifespan warmup
- **[R-6] 测试中 ProcessPoolExecutor 不好隔离**:L1 测试直接调 `compute_pair_similarity` 同步函数,不走 executor;L2 测试用真 executor(接受启动开销)
- **[R-7] max_features=20000 + max_df=0.95 在超短文档上 min_df=1 可能全词项只出现 1 次,TF-IDF 退化成词计数**:接受,对围标"近字面抄袭"场景反而有利(低频词区分度高)

## Migration Plan

### 上线步骤

1. `pip install` / `uv sync`(零新增依赖,实际无新装)
2. 后端部署:`text_sim_impl/` 随 C7 commit 一并上线
3. 首次用户启动检测 → 第一个 pair 慢 ~1~2s(jieba + sklearn 子进程冷启动),后续正常
4. 验证:
   - 报告页 text_similarity 行有真实 score(非 dummy 随机分特征 round(random, 2))
   - evidence_json.algorithm == "tfidf_cosine_v1"
   - `_dummy.py` 在 text_similarity 路径上不再被 import(但其他 9 Agent 仍用)
5. 监控项(C17 或更后才做 ops dashboard,C7 只记 log):
   - `agent_task.elapsed_ms` 分布(text_similarity 分位)
   - `evidence_json.degraded=true` 比例(LLM 失败率)

### 回滚策略

- 代码回滚:撤 C7 commit,`text_similarity.py` 恢复 dummy 实现;框架无改动,其他 9 Agent 不受影响
- DB 无 schema 变更,零回滚

## Open Questions

- **Q1**(延后至 C14):evidence_json.samples 是 10 条上限 — 前端报告页未建时先这样;C14 实现证据详情抽屉时视 UX 需求再调(无需改 schema,前端多取几条)
- **Q2**(C7 实施期决):`ctx.llm_provider` 当前在 `engine._build_ctx` 里 hard-code `None`。C7 需要在 `_build_ctx` 内从某处获取真 provider
  - **子决策 Q2a**:走 `app.services.llm.get_default_provider()`(C1 提供的工厂)
  - **子决策 Q2b**:测试 override 通过 `app.dependency_overrides` 或环境变量 `LLM_PROVIDER_FACTORY`
  - **C7 实施期选**:Q2a + monkeypatch `app.services.llm.get_default_provider` 做 L2 测试注入 — **最简改动;engine._build_ctx 改一行**。C7 tasks 列为 `[impl]`
- **Q3**(C7 实施期验证):Docker 容器 cpu_count 是否正确 — 跑 `docker exec ...` 记录数值,不符合预期再开 follow-up
