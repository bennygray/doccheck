## MODIFIED Requirements

### Requirement: 10 Agent 骨架文件与 dummy run

后端 MUST 在 `app/services/detect/agents/` 下提供 10 个文件,每个文件定义一个 Agent 骨架,通过 `@register_agent` 装饰器注册到 AGENT_REGISTRY。

C9 归档后,Agent `text_similarity`(C7)、`section_similarity`(C8)、`structure_similarity`(C9)的 `run()` 已替换为真实算法,不再走 dummy;其余 7 个 Agent(`metadata_author / metadata_time / metadata_machine / price_consistency / error_consistency / style / image_reuse`)`run()` 继续走 dummy,直至 C10~C13 各自替换。

每个尚未替换为真实实现的骨架文件 MUST 含:
- `preflight` 函数(按 "Agent preflight 前置条件自检" Requirement 规则)
- `run(ctx: AgentContext) -> AgentRunResult` 函数,dummy 实现:
  - `await asyncio.sleep(random.uniform(0.2, 1.0))`
  - `score = random.uniform(0, 100)`
  - `summary = f"dummy {name} result"`
  - pair 型:INSERT PairComparison 行(随机 is_ironclad 但权重 < 10%)
  - global 型:INSERT OverallAnalysis 行
  - 返 `AgentRunResult(score=score, summary=summary)`

`AgentRunResult` 是 namedtuple,字段:`score: float, summary: str, evidence_json: dict = {}`。当整 Agent 因结构缺失 run 级 skip 时 `score=0.0` 作为哨兵值,evidence 层通过 `participating_dimensions=[]` 标记(详见 "structure_similarity 维度级与 Agent 级 skip 语义" Requirement)。

C10~C13 各 change 替换对应 `run()` 实现,不改 preflight、不改文件名、不改注册 key。

#### Scenario: 10 Agent 模块加载后注册表完整

- **WHEN** `from app.services.detect import agents` 触发所有 agents 模块加载
- **THEN** `AGENT_REGISTRY` 含 10 条目;每条 `run` 可调

#### Scenario: dummy run 产生 PairComparison 行

- **WHEN** 调 metadata_author dummy run(pair 型,C9 后 dummy 列表的一员)
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

#### Scenario: structure_similarity 已替换为真实实现

- **WHEN** 调 `AGENT_REGISTRY["structure_similarity"].run(ctx)` 且至少一个维度可提取
- **THEN** `evidence_json["algorithm"] == "structure_sim_v1"`(非 dummy 标记),summary 非 "dummy" 前缀

## ADDED Requirements

### Requirement: structure_similarity 三维度算法

Agent `structure_similarity` 的 `run()` MUST 执行三个独立维度的结构相似度计算,纯程序化(不调用 LLM):

1. **目录结构维度**(仅作用于 docx 文档):
   - 复用 C8 `section_sim_impl.chapter_parser.extract_chapters` 切出两侧章节 ChapterBlock
   - 取每章 `title`,归一化(剥离 `第X章 / X.Y / 一、` 等序号前缀 + 去空白全角 + 统一标点)
   - 计算 LCS 长度,相似度 = `2 × LCS_len / (len_a + len_b)`
   - 任一侧归一化后章节数 < `STRUCTURE_SIM_MIN_CHAPTERS`(默认 3)→ 该维度不参与聚合(None)

2. **字段结构维度**(仅作用于 xlsx 文档):
   - 读两侧 `DocumentSheet.rows_json` 与 `merged_cells_json`
   - 按 `sheet_name` 配对两侧 sheet(相同名称为一对);未配对 sheet 不贡献分数
   - 对每对 sheet:列头 hash Jaccard(首个非空行归一化后字段集合)+ 每行非空列 bitmask 的 multiset Jaccard + merged_cells ranges 集合 Jaccard,按子权重(`STRUCTURE_SIM_FIELD_JACCARD_SUB_WEIGHTS`,默认 `0.4 / 0.3 / 0.3`)加权
   - 字段维度总分 = `max(per_sheet_sub_score)`(单 sheet 雷同即触发)
   - 两侧任一方 xlsx DocumentSheet 不存在 → 该维度不参与聚合(None)

3. **表单填充模式维度**(仅作用于 xlsx 文档):
   - 对每个 cell 归为 4 类 pattern:`N`(数字)/`D`(日期)/`T`(文本)/`_`(空)
   - 每行 pattern 串接为字符串(如 `"TN_N_D"`),两侧作为 multiset 计算 Jaccard
   - 按 sheet 配对同字段维度;填充维度总分 = `max(per_sheet_jaccard)`
   - 两侧任一方 xlsx DocumentSheet 不存在 → 该维度不参与聚合(None)

**维度聚合**:`STRUCTURE_SIM_WEIGHTS`(默认 `"0.4,0.3,0.3"`)三维度权重;参与维度按其原始权重重新归一化求加权平均,结果 × 100 得 Agent score。仅目录+填充参与时等效 `(dir × 0.4 + fill × 0.3) / 0.7 × 100`。

**is_ironclad**:任一维度 sub_score ≥ 0.90 且 Agent 总 score ≥ 85 → is_ironclad=True。

CPU 密集步骤(目录 LCS)MUST 走 `get_cpu_executor()`(与 C7/C8 共享 ProcessPoolExecutor)。字段/填充维度 Jaccard 运算较轻,不强制走 executor。

#### Scenario: 目录完全一致命中

- **WHEN** pair(A, B)两份 docx 章节标题序列完全相同(含规范化后),共 12 章节
- **THEN** PairComparison.score ≥ 60.0,evidence_json.algorithm = "structure_sim_v1",evidence_json.dimensions.directory.score ≥ 0.9,evidence_json.dimensions.directory.lcs_length ≥ 10

#### Scenario: 报价表填充结构一致命中

- **WHEN** pair(A, B)两份 xlsx 首个 sheet(名为"报价汇总")列头完全相同、空值位置完全相同、合并单元格 ranges 完全相同
- **THEN** PairComparison.score ≥ 60.0,evidence_json.dimensions.field_structure.score ≥ 0.8,evidence_json.dimensions.field_structure.per_sheet 含一条 sub_score ≥ 0.9 的条目

#### Scenario: 独立结构不误报

- **WHEN** pair(A, B)两份 docx 章节标题序列完全不同(LCS 占比 < 0.2)且两份 xlsx 列头、bitmask、merged_cells 均不重合
- **THEN** PairComparison.score < 30.0,is_ironclad = false

#### Scenario: 目录维度走 CPU executor

- **WHEN** 目录结构维度的 LCS 计算(章节数 m × n)
- **THEN** 通过 `get_cpu_executor()` 异步提交(loop.run_in_executor),不在主 asyncio 事件循环内阻塞 CPU

### Requirement: structure_similarity preflight

Agent `structure_similarity` preflight MUST 执行:

1. 双方均有同 file_role 的 BidDocument(复用 `_preflight_helpers.choose_shared_role`)
2. 双方选中角色下至少一侧有 docx 文档 **或** 至少一侧有 xlsx 文档(轻量 COUNT 查询,不做完整结构提取)

维度级提取失败不在 preflight 阶段触发 skip,下放到 `run()` 内部各维度单独判定。

#### Scenario: 同角色文档缺失 skip

- **WHEN** 任一侧无同 file_role 的 BidDocument
- **THEN** 返 `PreflightResult(status='skip', reason='缺少可对比文档')`

#### Scenario: 双方都无 docx 也无 xlsx 时 skip

- **WHEN** 双方共享角色下只有图片或 PDF,无任何 docx/xlsx 文件
- **THEN** 返 `PreflightResult(status='skip', reason='结构缺失')`

#### Scenario: 仅一侧有 docx 时 preflight 放行

- **WHEN** bidder_a 有 docx,bidder_b 仅有 xlsx(角色相同,但类型互补)
- **THEN** preflight 返 `ok`;run 内部目录维度因单侧 docx 缺失而 None,字段/填充维度同理单侧 xlsx 缺失而 None,可能 3 维度全 None → Agent succeeded + score=None + summary="结构缺失"

### Requirement: structure_similarity 维度级与 Agent 级 skip 语义

Agent `structure_similarity` MUST 区分两级 skip:

- **维度级 skip**:单维度提取/计算失败(如 docx 章节数不足、xlsx DocumentSheet 不存在)→ 该维度 `dimensions.<dim>.score = null` 并标注 `reason` 字段;**不影响其他维度**;最终 Agent score 按参与维度的原始权重重新归一化计算
- **Agent 级 skip 两条路径**:
  - preflight 阶段双方无 docx/xlsx → `PreflightResult(status='skip', reason='结构缺失')`,engine 标 AgentTask.status=skipped,**不写 PairComparison**
  - run 阶段 3 维度全部 None(preflight 通过但 docx 章节数不足 + xlsx 无有效 sheet)→ run 仍正常完成,`AgentRunResult(score=0.0, summary="结构缺失:...")`,PairComparison.score=0.0 + `evidence.participating_dimensions=[]`(前端按 participating_dimensions 为空识别为"Agent 级 skip")

**与 C8 section_similarity 不同**:C9 **不做**"章节切分失败 → 降级到整文档粒度"这种降级,execution-plan §3 C9 兜底原文要求"跳过该维度,不假阳"。

#### Scenario: 仅字段维度失败

- **WHEN** 目录维度正常(LCS sim=0.8),字段维度 xlsx DocumentSheet 缺失(bidder_b 未回填),填充维度同理缺失
- **THEN** score = 0.8 × 100 = 80.0(仅目录参与,重归一化权重 1.0);evidence.participating_dimensions = ["directory"];evidence.dimensions.field_structure.score = null + reason = "xlsx_sheet_missing"

#### Scenario: 3 维度全 None 触发 run 级 skip

- **WHEN** preflight 通过(至少一侧有 docx/xlsx),但 run 阶段所有维度提取失败(如 docx 章节数不足 + xlsx 无有效 sheet)
- **THEN** run 返 `AgentRunResult(score=0.0, summary="结构缺失:...")`;PairComparison 写一行 score=0.0、`evidence.participating_dimensions=[]`;AgentTask.status=succeeded

#### Scenario: 不走 C8 式降级

- **WHEN** docx 章节数 < MIN_CHAPTERS=3
- **THEN** 目录维度 None,不走"整文档 TF-IDF 降级"分支;Agent 不 import 任何 text_sim_impl 模块

### Requirement: structure_similarity evidence_json 结构

`PairComparison.evidence_json` 对 `dimension = 'structure_similarity'` 的行 MUST 包含以下字段:

| 字段 | 类型 | 说明 |
|---|---|---|
| `algorithm` | string | `"structure_sim_v1"` |
| `doc_role` | string | 参与检测的共享角色 |
| `doc_id_a` / `doc_id_b` | int[] | 参与检测的文档 id(可能多个,因三维度作用于不同 ext);docx 维度的 doc_id 和 xlsx 维度的 doc_id 可能不同 |
| `participating_dimensions` | string[] | 参与加权的维度名,子集 of `["directory", "field_structure", "fill_pattern"]` |
| `weights_used` | object | 实际使用的权重 `{"directory": 0.4, "field_structure": 0.3, "fill_pattern": 0.3}`(仅列参与维度) |
| `dimensions.directory.score` | float/null | 0~1 或 null(未参与) |
| `dimensions.directory.reason` | string/null | score=null 时的原因 |
| `dimensions.directory.titles_a_count` / `titles_b_count` | int | 两侧章节数 |
| `dimensions.directory.lcs_length` | int | LCS 长度 |
| `dimensions.directory.sample_titles_matched` | string[] | 前 10 条被 LCS 命中的章节标题(归一化前原文) |
| `dimensions.field_structure.score` | float/null | 0~1 或 null |
| `dimensions.field_structure.reason` | string/null | — |
| `dimensions.field_structure.per_sheet` | array | 每个配对 sheet 一条,`{sheet_name, header_sim, bitmask_sim, merged_cells_sim, sub_score}`,上限 5 sheet |
| `dimensions.fill_pattern.score` | float/null | 0~1 或 null |
| `dimensions.fill_pattern.reason` | string/null | — |
| `dimensions.fill_pattern.per_sheet` | array | 每个配对 sheet 一条,`{sheet_name, score, matched_pattern_lines, sample_patterns}`,上限 5 sheet;sample_patterns 上限 10 条 |

#### Scenario: 3 维度正常 evidence_json

- **WHEN** 双方均有 docx(章节提取成功)且均有 xlsx(sheet 成功配对)
- **THEN** participating_dimensions = ["directory", "field_structure", "fill_pattern"],dimensions 三个子对象 score 均非 null

#### Scenario: 单维度失败 evidence_json

- **WHEN** 仅目录参与(bidder_b xlsx DocumentSheet 缺失)
- **THEN** participating_dimensions = ["directory"];dimensions.field_structure.score = null + dimensions.field_structure.reason 非 null

#### Scenario: run 级 skip evidence_json

- **WHEN** run 阶段 3 维度全 None
- **THEN** PairComparison 行 score=0.0,evidence_json.participating_dimensions = [],evidence_json.dimensions 三维度 score 均 null

### Requirement: structure_similarity 环境变量

后端 MUST 支持以下环境变量动态读取:

- `STRUCTURE_SIM_MIN_CHAPTERS`(默认 3)— 目录维度:章节数 < 此值 → 该维度 None
- `STRUCTURE_SIM_MIN_SHEET_ROWS`(默认 2)— 字段/填充维度:每 sheet 非空行 < 此值 → 该 sheet 不参与配对
- `STRUCTURE_SIM_WEIGHTS`(默认 `"0.4,0.3,0.3"`)— 三维度权重(目录/字段/填充),逗号分隔 float
- `STRUCTURE_SIM_FIELD_JACCARD_SUB_WEIGHTS`(默认 `"0.4,0.3,0.3"`)— 字段维度三子信号权重(列头/bitmask/合并单元格)
- `STRUCTURE_SIM_MAX_ROWS_PER_SHEET`(默认 5000)— xlsx 持久化/消费时每 sheet 行数上限

**复用 C8 既有 env**:`SECTION_SIM_MIN_CHAPTER_CHARS=100`(通过 C8 `chapter_parser` 内部读取)。

#### Scenario: WEIGHTS 默认值

- **WHEN** 未设置 `STRUCTURE_SIM_WEIGHTS`
- **THEN** run() 使用 `(0.4, 0.3, 0.3)` 作为 (目录, 字段, 填充) 权重

#### Scenario: 运行期 monkeypatch 生效

- **WHEN** L1/L2 测试 `monkeypatch.setenv("STRUCTURE_SIM_MIN_CHAPTERS", "5")`
- **THEN** run() 读取 5,章节数 < 5 的那一侧 → 目录维度 None

#### Scenario: WEIGHTS 归一化失败时用默认

- **WHEN** 设置 `STRUCTURE_SIM_WEIGHTS="abc,xyz"`(无法 parse)
- **THEN** 代码 fallback 到默认 `(0.4, 0.3, 0.3)` 并打 warning 日志
