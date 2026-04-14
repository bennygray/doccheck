## MODIFIED Requirements

### Requirement: 10 Agent 骨架文件与 dummy run

后端 MUST 在 `app/services/detect/agents/` 下提供 10 个文件,每个文件定义一个 Agent 骨架,通过 `@register_agent` 装饰器注册到 AGENT_REGISTRY。

C7 归档后,Agent `text_similarity` 的 `run()` 已替换为真实双轨算法(本地 TF-IDF + cosine 筛 + LLM 定性),不再走 dummy;其余 9 个 Agent(`section_similarity / structure_similarity / metadata_author / metadata_time / metadata_machine / price_consistency / error_consistency / style / image_reuse`)`run()` 继续走 dummy,直至 C8~C13 各自替换。

每个尚未替换为真实实现的骨架文件 MUST 含:
- `preflight` 函数(按 "Agent preflight 前置条件自检" Requirement 规则)
- `run(ctx: AgentContext) -> AgentRunResult` 函数,dummy 实现:
  - `await asyncio.sleep(random.uniform(0.2, 1.0))`
  - `score = random.uniform(0, 100)`
  - `summary = f"dummy {name} result"`
  - pair 型:INSERT PairComparison 行(随机 is_ironclad 但权重 < 10%)
  - global 型:INSERT OverallAnalysis 行
  - 返 `AgentRunResult(score=score, summary=summary)`

`AgentRunResult` 是 namedtuple,字段:`score: float, summary: str, evidence_json: dict = {}`。

C8~C13 各 change 替换对应 `run()` 实现,不改 preflight、不改文件名、不改注册 key。

#### Scenario: 10 Agent 模块加载后注册表完整

- **WHEN** `from app.services.detect import agents` 触发所有 agents 模块加载
- **THEN** `AGENT_REGISTRY` 含 10 条目;每条 `run` 可调

#### Scenario: dummy run 产生 PairComparison 行

- **WHEN** 调 section_similarity dummy run(pair 型,仍是 C7 后 dummy 列表的一员)
- **THEN** pair_comparisons 表新增 1 行,score 在 0~100;summary 含 "dummy"

#### Scenario: dummy run 产生 OverallAnalysis 行

- **WHEN** 调 style dummy run(global 型)
- **THEN** overall_analyses 表新增 1 行

#### Scenario: text_similarity 已替换为真实实现

- **WHEN** 调 `AGENT_REGISTRY["text_similarity"].run(ctx)` 且段落对存在
- **THEN** `evidence_json["algorithm"] == "tfidf_cosine_v1"`(非 dummy 标记),summary 非 "dummy" 前缀

## ADDED Requirements

### Requirement: text_similarity 双轨算法(本地 TF-IDF + LLM 定性)

Agent `text_similarity` 的 `run()` MUST 采用双轨分工:

1. **本地 TF-IDF 筛选**(始终执行):
   - 取双方同角色文档的段落列表(优先 `技术方案`,无则回退 `商务`、`其他`)
   - jieba 分词 + 去停用词 + `TfidfVectorizer(ngram_range=(1, 2), min_df=1, max_df=0.95, max_features=20000)`
   - `cosine_similarity(mat_a, mat_b)` 构造段落对相似度矩阵
   - 取 `sim >= TEXT_SIM_PAIR_SCORE_THRESHOLD`(默认 0.70)的段落对,按 sim 降序截取前 `TEXT_SIM_MAX_PAIRS_TO_LLM`(默认 30)条
2. **LLM 定性判定**(超阈值段落对存在时执行):
   - 按 requirements.md §10.8 L-4 规格组 prompt:输入双方名称、文档角色、段落对列表(含文本和程序相似度)
   - 请求 LLM 返回 JSON:每对段落 `judgment ∈ {template, generic, plagiarism}` + 整体 `overall` + `confidence ∈ {high, medium, low}`
   - 严格 JSON 解析;失败 → 重试 1 次;仍失败 → 降级
3. **score 汇总**:每对 `score_i = sim * 100 * W[judgment]`,其中 `W = {plagiarism: 1.0, template: 0.6, generic: 0.2, None(降级): 0.3}`;pair 级 `score = round(max(scored) * 0.7 + mean(scored) * 0.3, 2)`
4. **is_ironclad 判定**:LLM 非降级模式下,若 `plagiarism` 对数 ≥ 3 或占比 ≥ 50% → `is_ironclad = True`;降级模式下始终 `False`

CPU 密集步骤(TF-IDF 向量化 + cosine 计算)MUST 走 `get_cpu_executor()` + `loop.run_in_executor()`,不阻塞 event loop。

#### Scenario: 抄袭样本高分命中

- **WHEN** pair(A, B)双方技术方案段落包含 ≥ 5 段几乎逐字相同的文本,LLM 返回全部 plagiarism
- **THEN** PairComparison.score ≥ 85.0,is_ironclad = True,evidence_json.pairs_plagiarism ≥ 5

#### Scenario: 独立样本低分不误报

- **WHEN** pair(A, B)双方文档独立撰写,TF-IDF 筛选无段落对 sim ≥ 0.70
- **THEN** PairComparison.score < 20.0,is_ironclad = False,evidence_json.pairs_total = 0,LLM 未被调用

#### Scenario: 三份中一对命中

- **WHEN** 3 家 bidder 中仅 (A, B) 对抄袭,(A, C) 和 (B, C) 独立
- **THEN** pair(A,B).score 高 + is_ironclad=True;pair(A,C) / (B,C) score 低 + is_ironclad=False

#### Scenario: 段落对 sim 超阈值但 LLM 判为 generic

- **WHEN** LLM 返回全部段落对 judgment = generic(行业通用表述)
- **THEN** PairComparison.score 按 generic 权重 0.2 折算;is_ironclad = False

### Requirement: text_similarity preflight 超短文档 skip

Agent `text_similarity` preflight MUST 在"同角色文档存在"基础上追加字数检查:
- 任一 bidder 的待比对文档总字符数 < `TEXT_SIM_MIN_DOC_CHARS`(默认 500)→ 返 `PreflightResult(status='skip', reason='文档过短无法对比')`
- 双方均满足 `>= TEXT_SIM_MIN_DOC_CHARS` → 返 `ok`

此扩展 MUST 保持 C6 定义的 `PreflightResult(status='skip' | 'ok')` 接口不变;不新增 `downgrade` 分支。

#### Scenario: 单边超短文档 preflight skip

- **WHEN** bidder_a 技术方案总字符 300(< 500),bidder_b 2000
- **THEN** 返 `PreflightResult(status='skip', reason='文档过短无法对比')`

#### Scenario: 双方足够字数 preflight ok

- **WHEN** 双方技术方案总字符均 ≥ 500
- **THEN** 返 `PreflightResult(status='ok')`

#### Scenario: 原"同角色文档存在"规则保留

- **WHEN** bidder_a 有技术方案,bidder_b 无技术方案
- **THEN** 返 `PreflightResult(status='skip', reason='缺少可对比文档')`(字数检查不触发,因无可比对文档)

### Requirement: text_similarity LLM 降级模式

当 LLM 调用失败(`LLMResult.error` 非空,kind ∈ timeout / rate_limit / network / other)或 JSON 解析两次(初 + 1 重试)都失败,Agent `text_similarity` MUST 进入降级模式:

1. 不再调用 LLM;本地 TF-IDF 筛选结果仍保留
2. `evidence_json.degraded = true`,`evidence_json.ai_judgment = null`
3. `score` 按所有段落对 `judgment = None` 权重 0.3 计算(D4 公式)
4. `is_ironclad = False`(降级永远不触发铁证)
5. `summary` 固定文案 "AI 研判暂不可用,仅展示程序相似度(降级)"
6. AgentTask `status = succeeded`(降级不是失败,程序相似度仍可用)

#### Scenario: LLM 超时降级

- **WHEN** `ctx.llm_provider.complete()` 返 `LLMResult(error=LLMError(kind='timeout'))`
- **THEN** evidence_json.degraded = True,AgentTask.status = succeeded,summary 含 "降级"

#### Scenario: LLM 返回非 JSON 降级

- **WHEN** LLM 返回 plain text 非 JSON,初次解析失败;重试仍返 plain text
- **THEN** evidence_json.degraded = True,score 按权重 0.3 保守计算

#### Scenario: LLM 返回 JSON 但段数不匹配

- **WHEN** 输入 10 段落对,LLM 只返回 7 段的 judgment
- **THEN** 缺失 3 段按 judgment='generic' 补齐;不触发降级(不算错误)

### Requirement: text_similarity evidence_json 结构

`PairComparison.evidence_json` 对 `dimension = 'text_similarity'` 的行 MUST 包含以下字段:

| 字段 | 类型 | 说明 |
|---|---|---|
| `algorithm` | string | 固定 `"tfidf_cosine_v1"`,区分 dummy |
| `doc_role` | string | 实际比对的文档角色 |
| `doc_id_a` / `doc_id_b` | int | 被比对的 BidDocument id |
| `threshold` | float | 本次 TEXT_SIM_PAIR_SCORE_THRESHOLD 实际值 |
| `pairs_total` | int | 超阈值段落对总数 |
| `pairs_plagiarism` | int | LLM 判 plagiarism 段数(降级模式 = 0) |
| `pairs_template` | int | LLM 判 template 段数(降级模式 = 0) |
| `pairs_generic` | int | LLM 判 generic 段数(降级模式 = pairs_total) |
| `degraded` | bool | LLM 是否降级 |
| `ai_judgment` | object/null | `{overall: string, confidence: string}`,降级时 null |
| `samples` | array | 按 sim 降序前 10 条 `{a_idx, b_idx, a_text, b_text, sim, label, note}` |

`samples` 上限 10 条以控制 JSONB 大小;`a_text` / `b_text` 每条最多截取 200 字符。

#### Scenario: 正常 evidence_json 结构

- **WHEN** text_similarity 正常完成(LLM 成功)
- **THEN** evidence_json 含 algorithm="tfidf_cosine_v1" + ai_judgment 非 null + samples ≤ 10

#### Scenario: 降级 evidence_json 结构

- **WHEN** text_similarity LLM 降级完成
- **THEN** evidence_json.degraded=true + ai_judgment=null + samples 仍有(程序相似度保留)

### Requirement: text_similarity ProcessPoolExecutor 消费

Agent `text_similarity.run()` MUST 通过 `loop.run_in_executor(get_cpu_executor(), compute_pair_similarity, paras_a, paras_b, threshold)` 将 TF-IDF 向量化 + cosine 矩阵计算卸载到 ProcessPoolExecutor,主协程不阻塞。

`compute_pair_similarity` MUST 是无副作用的纯函数(入参 `list[str] × list[str] × float`,出参 `list[ParaPair]`),可序列化,可在子进程独立跑完。

`TfidfVectorizer` 实例在子进程内 new,不跨进程传递。

#### Scenario: executor 被调用

- **WHEN** text_similarity run 执行 CPU 密集段
- **THEN** `get_cpu_executor()` 返回的 ProcessPoolExecutor 被消费(L1 通过 spy 验证;L2 真实运行)

#### Scenario: jieba 首次调用不崩溃

- **WHEN** 后端启动后首个 text_similarity task(worker 子进程首次 import jieba)
- **THEN** Agent 成功完成;elapsed_ms 可能 > 1000ms(首次词典加载) 但 status=succeeded
