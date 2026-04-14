## MODIFIED Requirements

### Requirement: 10 Agent 骨架文件与 dummy run

后端 MUST 在 `app/services/detect/agents/` 下提供 10 个文件,每个文件定义一个 Agent 骨架,通过 `@register_agent` 装饰器注册到 AGENT_REGISTRY。

C8 归档后,Agent `text_similarity`(C7)和 `section_similarity`(C8)的 `run()` 已替换为真实算法,不再走 dummy;其余 8 个 Agent(`structure_similarity / metadata_author / metadata_time / metadata_machine / price_consistency / error_consistency / style / image_reuse`)`run()` 继续走 dummy,直至 C9~C13 各自替换。

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

C9~C13 各 change 替换对应 `run()` 实现,不改 preflight、不改文件名、不改注册 key。

#### Scenario: 10 Agent 模块加载后注册表完整

- **WHEN** `from app.services.detect import agents` 触发所有 agents 模块加载
- **THEN** `AGENT_REGISTRY` 含 10 条目;每条 `run` 可调

#### Scenario: dummy run 产生 PairComparison 行

- **WHEN** 调 structure_similarity dummy run(pair 型,仍是 C8 后 dummy 列表的一员)
- **THEN** pair_comparisons 表新增 1 行,score 在 0~100;summary 含 "dummy"

#### Scenario: dummy run 产生 OverallAnalysis 行

- **WHEN** 调 style dummy run(global 型)
- **THEN** overall_analyses 表新增 1 行

#### Scenario: text_similarity 已替换为真实实现

- **WHEN** 调 `AGENT_REGISTRY["text_similarity"].run(ctx)` 且段落对存在
- **THEN** `evidence_json["algorithm"] == "tfidf_cosine_v1"`(非 dummy 标记),summary 非 "dummy" 前缀

#### Scenario: section_similarity 已替换为真实实现

- **WHEN** 调 `AGENT_REGISTRY["section_similarity"].run(ctx)` 且章节切分成功
- **THEN** `evidence_json["algorithm"] == "tfidf_cosine_chapter_v1"`(非 dummy 标记),summary 非 "dummy" 前缀

## ADDED Requirements

### Requirement: section_similarity 章节级双轨算法

Agent `section_similarity` 的 `run()` MUST 采用章节级双轨分工,分 5 步:

1. **段落加载**:复用 C7 `text_sim_impl.segmenter.choose_shared_role` + `load_paragraphs_for_roles`,选两侧共有 file_role(按 `ROLE_PRIORITY`)的 BidDocument,加载 body 段落
2. **正则切章**:按 5 种 PATTERN(`第X章 / 第X节 / X.Y 数字序号 / 一、二、 中文数字 / 纯数字+顿号`)识别标题行,切出 `list[ChapterBlock]`;章节内文本 < `SECTION_SIM_MIN_CHAPTER_CHARS`(默认 100)的合并进前一章节
3. **切分成功性判定**:若任一侧 `len(chapters) < SECTION_SIM_MIN_CHAPTERS`(默认 3)或两侧总段落数 < 10 → 触发降级分支(见 "section_similarity 降级模式" Requirement)
4. **章节对齐**:按 title TF-IDF sim 贪心配对(复用 `text_sim_impl.tfidf.jieba_tokenizer`),sim ≥ `SECTION_SIM_TITLE_ALIGN_THRESHOLD`(默认 0.40)标 `aligned_by='title'`;未达阈值的未配对章节按 `idx` 序号对齐,标 `aligned_by='index'`;配对数 = `min(|chapters_a|, |chapters_b|)`
5. **章节级评分 + pair 级汇总**:对每对章节,复用 C7 `text_sim_impl.tfidf.compute_pair_similarity` 算段落对相似度,然后将所有对齐章节的段落对合并按 `title_sim × avg_para_sim` 粗排后取前 `TEXT_SIM_MAX_PAIRS_TO_LLM`(复用 C7 的 30)送 LLM,复用 `text_sim_impl.llm_judge` + `text_sim_impl.aggregator`;pair 级 score = `max(chapter_scores) * 0.6 + mean(chapter_scores) * 0.4`;pair 级 is_ironclad = `any(chapter.is_chapter_ironclad)`

CPU 密集步骤(段落 TF-IDF + title TF-IDF)MUST 走 `get_cpu_executor()`(与 C7 共享 ProcessPoolExecutor)。

#### Scenario: 章节雷同命中

- **WHEN** pair(A, B)双方技术方案章节存在 ≥ 2 章节逐字相同
- **THEN** PairComparison.score ≥ 60.0,is_ironclad = True,evidence_json.algorithm = "tfidf_cosine_chapter_v1",evidence_json.chapter_pairs 含 ≥ 2 个 is_chapter_ironclad=True 的章节对

#### Scenario: 章节错位对齐

- **WHEN** bidder_a 的"技术方案"在 idx=2,bidder_b 的"技术方案"在 idx=3(整体章节数不同但同主题章节标题相近)
- **THEN** aligner 将 (a_idx=2, b_idx=3) 配对,`aligned_by='title'`,title_sim ≥ 0.40

#### Scenario: 无对齐命中走序号回退

- **WHEN** 双方所有章节标题 TF-IDF 均 < 0.40(如纯数字标题)
- **THEN** 每章节按 idx 回退对齐,`aligned_by='index'`,title_sim 可能为 0 但 chapter_score 仍计算

#### Scenario: 单侧多余章节被丢

- **WHEN** bidder_a 含 10 章节,bidder_b 含 6 章节
- **THEN** 对齐后 chapter_pairs 数 = 6,a 的多余 4 章节不参与比较

### Requirement: section_similarity preflight

Agent `section_similarity` preflight MUST 执行:
1. 双方均有同 file_role 的 BidDocument(复用 `segmenter.choose_shared_role`)
2. 双方选中文档总字符数 ≥ `TEXT_SIM_MIN_DOC_CHARS`(复用 C7 env,默认 500)

**章节数检查不在 preflight 阶段做**(需提前执行完整切章,成本高),下放到 `run()` 内部;切章失败走降级路径,不返回 `skip`。

#### Scenario: 同角色文档缺失 skip

- **WHEN** 任一侧无同 file_role 的 BidDocument
- **THEN** 返 `PreflightResult(status='skip', reason='缺少可对比文档')`

#### Scenario: 文档过短 skip

- **WHEN** 任一侧选中文档 total_chars < 500
- **THEN** 返 `PreflightResult(status='skip', reason='文档过短无法对比')`

#### Scenario: 章节数少不算 skip

- **WHEN** 双方文档均 ≥ 500 字但切章后 chapter_a=1 < MIN_CHAPTERS=3
- **THEN** preflight 仍返 `ok`;run 内部切章发现章节不足后走降级,不返回 skip

### Requirement: section_similarity 降级模式(章节切分失败)

当章节切分失败(任一侧 `len(chapters) < SECTION_SIM_MIN_CHAPTERS`,或双方总段落数 < 10),Agent `section_similarity` MUST 降级到整文档粒度:

1. **不再切章**,直接复用 C7 `text_sim_impl.tfidf.compute_pair_similarity` 对双方整文档段落计算 sim
2. **调 LLM 定性**(复用 C7 `text_sim_impl.llm_judge`);LLM 也失败时走 C7 既有降级(`evidence.degraded=true` 并存 `evidence.degraded_to_doc_level=true`)
3. **写 dimension='section_similarity'**(**不是 text_similarity**),与 C7 并行独立;两维度在 judge.py 按各自权重计入总分,不去重
4. **`evidence_json.algorithm = "tfidf_cosine_fallback_to_doc"`**(区别于 chapter_v1)
5. **`evidence_json.degraded_to_doc_level = true` + `evidence_json.degrade_reason` 填具体原因**(如 "章节切分失败(chapters_a=0, chapters_b=2, < 3)")
6. **AgentTask.status = 'succeeded'**(降级不是失败)
7. **is_ironclad 判定同 C7**(`plagiarism_count >= 3` 或 `>= 50%`)— 章节级证据不存在故不启用章节铁证规则

#### Scenario: 双方章节数都为 0 降级

- **WHEN** bidder_a 无章节标题行可识别(chapters=0),bidder_b 也 0
- **THEN** evidence.algorithm="tfidf_cosine_fallback_to_doc",degraded_to_doc_level=true;score 按 C7 同款算法计,AgentTask.status=succeeded

#### Scenario: 单侧章节数不足降级

- **WHEN** bidder_a 含 4 章节,bidder_b 含 2 章节(< MIN_CHAPTERS=3)
- **THEN** 触发降级;degrade_reason 注明 "chapters_b=2 < 3"

#### Scenario: 章节切分 + LLM 双降级

- **WHEN** 章节切分失败且 LLM 调用 timeout
- **THEN** evidence.degraded=true 且 evidence.degraded_to_doc_level=true;summary 说明两重降级

#### Scenario: 降级与 C7 text_similarity 独立

- **WHEN** 章节切分失败,section_similarity 写降级行;同轮 text_similarity(C7)正常写行
- **THEN** 两行 PairComparison 并存,judge.py 按各自维度权重计入 total_score;不合并证据

### Requirement: section_similarity evidence_json 结构

`PairComparison.evidence_json` 对 `dimension = 'section_similarity'` 的行 MUST 包含以下字段:

| 字段 | 类型 | 说明 |
|---|---|---|
| `algorithm` | string | `"tfidf_cosine_chapter_v1"`(正常) / `"tfidf_cosine_fallback_to_doc"`(降级) |
| `doc_role` / `doc_id_a` / `doc_id_b` / `threshold` | 同 C7 | — |
| `chapters_a_count` | int | a 侧切章数(降级时为实际识别数或 0) |
| `chapters_b_count` | int | b 侧切章数 |
| `aligned_count` | int | `aligned_by='title'` 的章节对数(降级时 0) |
| `index_fallback_count` | int | `aligned_by='index'` 的章节对数(降级时 0) |
| `degraded_to_doc_level` | bool | 章节切分是否失败 |
| `degrade_reason` | string/null | 降级原因文案;正常为 null |
| `chapter_pairs` | array | 章节对明细,最多 20 条;每条 `{a_idx, b_idx, a_title, b_title, title_sim, aligned_by, chapter_score, is_chapter_ironclad, plagiarism_count}` |
| 以下继承 C7 字段 | | |
| `pairs_total` / `pairs_plagiarism` / `pairs_template` / `pairs_generic` | int | 跨全章节的段落对汇总(降级时是整文档级) |
| `degraded` | bool | LLM 是否降级(与 C7 同义) |
| `ai_judgment` | object/null | 同 C7 |
| `samples` | array | 按 sim 降序前 10 条段落对(同 C7 schema) |

#### Scenario: 正常 evidence_json

- **WHEN** section_similarity 章节切分成功并完成 LLM 调用
- **THEN** evidence.algorithm="tfidf_cosine_chapter_v1",degraded_to_doc_level=false,chapter_pairs 非空

#### Scenario: 降级 evidence_json

- **WHEN** section_similarity 章节切分失败
- **THEN** evidence.algorithm="tfidf_cosine_fallback_to_doc",degraded_to_doc_level=true,chapter_pairs=[],aligned_count=0

#### Scenario: chapter_pairs 20 条上限

- **WHEN** 对齐章节对数 > 20
- **THEN** chapter_pairs 按 chapter_score 降序截断到 20 条;aligned_count 记录实际对齐数(可 > 20)

### Requirement: section_similarity 环境变量

后端 MUST 支持以下环境变量动态读取:

- `SECTION_SIM_MIN_CHAPTERS`(默认 3)— 任一侧章节数 < 此值触发降级
- `SECTION_SIM_MIN_CHAPTER_CHARS`(默认 100)— 章节内字符 < 此值合并进前一章节
- `SECTION_SIM_TITLE_ALIGN_THRESHOLD`(默认 0.40)— title TF-IDF sim ≥ 此值算对齐成功(by title)

C7 既有环境变量被复用,C8 不重复定义同义 env:`TEXT_SIM_MIN_DOC_CHARS` / `TEXT_SIM_PAIR_SCORE_THRESHOLD` / `TEXT_SIM_MAX_PAIRS_TO_LLM`。

#### Scenario: MIN_CHAPTERS 默认值

- **WHEN** 未设置 SECTION_SIM_MIN_CHAPTERS
- **THEN** run() 使用 3 作为下界

#### Scenario: 运行期 monkeypatch 生效

- **WHEN** L1/L2 测试 monkeypatch.setenv("SECTION_SIM_MIN_CHAPTERS", "5")
- **THEN** run() 读取 5,章节数 < 5 即触发降级
