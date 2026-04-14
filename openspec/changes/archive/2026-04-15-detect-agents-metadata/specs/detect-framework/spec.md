## MODIFIED Requirements

### Requirement: 10 Agent 骨架文件与 dummy run

后端 MUST 在 `app/services/detect/agents/` 下提供 10 个文件,每个文件定义一个 Agent 骨架,通过 `@register_agent` 装饰器注册到 AGENT_REGISTRY。

C10 归档后,Agent `text_similarity`(C7)、`section_similarity`(C8)、`structure_similarity`(C9)、`metadata_author` / `metadata_time` / `metadata_machine`(C10)的 `run()` 已替换为真实算法,不再走 dummy;其余 4 个 Agent(`price_consistency / error_consistency / style / image_reuse`)`run()` 继续走 dummy,直至 C11~C13 各自替换。

每个尚未替换为真实实现的骨架文件 MUST 含:
- `preflight` 函数(按 "Agent preflight 前置条件自检" Requirement 规则)
- `run(ctx: AgentContext) -> AgentRunResult` 函数,dummy 实现:
  - `await asyncio.sleep(random.uniform(0.2, 1.0))`
  - `score = random.uniform(0, 100)`
  - `summary = f"dummy {name} result"`
  - pair 型:INSERT PairComparison 行(随机 is_ironclad 但权重 < 10%)
  - global 型:INSERT OverallAnalysis 行
  - 返 `AgentRunResult(score=score, summary=summary)`

`AgentRunResult` 是 namedtuple,字段:`score: float, summary: str, evidence_json: dict = {}`。当整 Agent 因数据缺失 run 级 skip 时 `score=0.0` 作为哨兵值,evidence 层通过 `participating_fields=[]`(或 `participating_dimensions=[]`,按 Agent 定义)标记。

C11~C13 各 change 替换对应 `run()` 实现,不改 preflight、不改文件名、不改注册 key。

#### Scenario: 10 Agent 模块加载后注册表完整

- **WHEN** `from app.services.detect import agents` 触发所有 agents 模块加载
- **THEN** `AGENT_REGISTRY` 含 10 条目;每条 `run` 可调

#### Scenario: dummy run 产生 PairComparison 行

- **WHEN** 调 price_consistency dummy run(pair 型,C10 后 dummy 列表的一员)
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

#### Scenario: metadata_author 已替换为真实实现

- **WHEN** 调 `AGENT_REGISTRY["metadata_author"].run(ctx)` 且元数据足够
- **THEN** `evidence_json["algorithm"] == "metadata_author_v1"`(非 dummy 标记),summary 非 "dummy" 前缀

#### Scenario: metadata_time 已替换为真实实现

- **WHEN** 调 `AGENT_REGISTRY["metadata_time"].run(ctx)` 且元数据时间字段足够
- **THEN** `evidence_json["algorithm"] == "metadata_time_v1"`(非 dummy 标记),summary 非 "dummy" 前缀

#### Scenario: metadata_machine 已替换为真实实现

- **WHEN** 调 `AGENT_REGISTRY["metadata_machine"].run(ctx)` 且元数据机器指纹字段足够
- **THEN** `evidence_json["algorithm"] == "metadata_machine_v1"`(非 dummy 标记),summary 非 "dummy" 前缀

## ADDED Requirements

### Requirement: metadata Agents 共享元数据提取器

后端 MUST 在 `app/services/detect/agents/metadata_impl/extractor.py` 提供 `extract_bidder_metadata(session, bidder_id) -> list[MetadataRecord]`,由 `metadata_author / metadata_time / metadata_machine` 三个 Agent 共同消费,不重复 query。

- 数据源:`DocumentMetadata` 表(C5 已持久化)+ C10 扩的 `template` 列
- 每条 `MetadataRecord` 对应 bidder 名下一个 BidDocument 的元数据
- 归一化字段(`author_norm` / `last_saved_by_norm` / `company_norm` / `template_norm` / `app_name` / `app_version`)通过 `metadata_impl.normalizer.nfkc_casefold_strip(s)` 计算:先 `unicodedata.normalize("NFKC", s)`,再 `.casefold()`,再 `.strip()`;空串视同 None
- 原值字段(`author_raw` / `template_raw`)保留供 evidence 给前端展示原文
- 时间字段 (`doc_created_at` / `doc_modified_at`) 不归一化,保持 timezone-aware datetime

**不缓存**:每个 Agent 各自调用 extractor;3 Agent 并发执行时不共享 cache(避免锁复杂度)。

#### Scenario: 正常提取

- **WHEN** bidder_id=5 名下有 3 份 BidDocument,每份 DocumentMetadata 存在
- **THEN** 返 `list[MetadataRecord]` 含 3 条,每条字段齐全(`bid_document_id` / `bidder_id` / `doc_name` / 6 个 `*_norm` + 2 个时间 + 2 个 raw)

#### Scenario: bidder 无 DocumentMetadata

- **WHEN** bidder_id=6 名下 BidDocument 均未 C5 解析完成(无 DocumentMetadata 行)
- **THEN** 返 `[]`;不抛错

#### Scenario: 字段为空串走 None

- **WHEN** DocumentMetadata.author = `""`(空串)
- **THEN** `MetadataRecord.author_norm is None`;`author_raw` 保留 `""` 或 None(按 DB 原值)

#### Scenario: NFKC 归一化

- **WHEN** DocumentMetadata.author = `"ＺＨＡＮＧ Ｓａｎ"`(全角)
- **THEN** `MetadataRecord.author_norm == "zhang san"`(NFKC 转半角 + casefold)

### Requirement: metadata_author 跨投标人字段聚类算法

Agent `metadata_author` 的 `run()` MUST 对 bidder_a / bidder_b 双方 `MetadataRecord` 列表执行三子字段碰撞:`author` / `last_saved_by` / `company`。

算法:
1. 对每个子字段,收集双方非空归一化值的集合 `set_a` / `set_b`;单侧空 → 该子字段不进 sub_scores(不算 0)
2. 共同值 `intersect = set_a ∩ set_b`;非空即命中,`hit_strength = |intersect| / min(|set_a|, |set_b|)`(∈ [0, 1])
3. 无命中 → `sub_score = 0.0`;有命中 → `sub_score = hit_strength`
4. 参与子字段按 `METADATA_AUTHOR_SUBDIM_WEIGHTS`(默认 `author=0.5, last_saved_by=0.3, company=0.2`)重归一化加权
5. 全三子字段均单侧缺失 → Agent 级 skip(`score=None` + reason=`"author/last_saved_by/company 三字段均缺失"`)

Agent `score = dim_score × 100`;`is_ironclad` 当 Agent `score >= METADATA_IRONCLAD_THRESHOLD`(默认 85)时 True。

evidence `hits` 数组每个共同值一条(`field` / `value`(原值)/ `normalized` / `doc_ids_a` / `doc_ids_b`);`hits` 上限 `METADATA_MAX_HITS_PER_AGENT`(默认 50)。

#### Scenario: 两 bidder 共享 author 命中

- **WHEN** bidder_a 3 文档 author 均 "张三";bidder_b 2 文档 author 均 "张三",其余字段不同
- **THEN** Agent score ≥ 50.0(author 子 strength=1.0 × 0.5/0.5 归一化 = 1.0 → ×100 = 100.0,但若 last_saved_by/company 两侧有值但无命中则 sub=0 拉低总分);evidence.hits 含一条 `field="author", value="张三"`,`doc_ids_a` 含 3 个 bidder_a 文档 id

#### Scenario: author 跨 bidder 精确一致 → is_ironclad

- **WHEN** bidder_a / bidder_b 三文档 author / last_saved_by / company 全部相同
- **THEN** Agent score = 100.0(三子 strength 均 1.0);is_ironclad=true

#### Scenario: author 均缺失走 Agent 级 skip

- **WHEN** bidder_a/b 所有 DocumentMetadata author=None, last_saved_by=None, company=None
- **THEN** run 返 `AgentRunResult(score=0.0, summary="元数据缺失:...")`;PairComparison 行 score=0.0、evidence.participating_fields=[];不抛错

#### Scenario: 变体不自动合并

- **WHEN** bidder_a author="张三",bidder_b author="张三 (admin)"(精确不等,归一化后仍不同)
- **THEN** sub_scores.author = 0.0(单 intersect 为空);不计命中

### Requirement: metadata_time 时间窗聚集与精确相等算法

Agent `metadata_time` 的 `run()` MUST 对 bidder_a/bidder_b 双方 `doc_modified_at` 与 `doc_created_at` 计算两子信号:

1. **modified_at 滑窗聚集**:
   - 合并双方所有 doc 的 `(modified_at, doc_id, side)` 排序
   - 滑窗宽度 `METADATA_TIME_CLUSTER_WINDOW_MIN`(默认 5 分钟)
   - 任何连续 2+ 条 `modified_at` 差 ≤ 窗口且**跨投标人**(窗口内 side 集合含 a 和 b)→ 记一条 TimeCluster
   - sub_score = `命中文档总数 / 双方总文档数`(clamp to [0, 1])
2. **created_at 精确相等**:
   - 双方 `doc_created_at` 按值分组;共同时间点即命中
   - sub_score = 同上占比

双子信号按 `METADATA_TIME_SUBDIM_WEIGHTS`(默认 modified=0.7, created=0.3)重归一化加权为 dim score。

维度级 skip:双方双字段都无数据 → `score=None, reason="doc_modified_at / doc_created_at 字段全缺失"`。

#### Scenario: 5 分钟内集中修改命中

- **WHEN** bidder_a 3 文档 modified_at 分别为 10:00, 10:02, 10:03;bidder_b 2 文档 modified_at 分别为 10:01, 10:04
- **THEN** 窗口内 5 文档形成一个跨 side 簇;sub_scores.modified_at_cluster > 0;Agent score > 0;evidence.hits 含一条 `dimension="modified_at_cluster"` 条目

#### Scenario: created_at 完全相同命中

- **WHEN** bidder_a doc1.created_at = 2026-03-01T12:00:00Z;bidder_b doc2.created_at = 2026-03-01T12:00:00Z(秒级精确相等)
- **THEN** sub_scores.created_at_match > 0;evidence.hits 含一条 `dimension="created_at_match"` 条目

#### Scenario: 时间窗不跨 bidder 不命中

- **WHEN** bidder_a 3 文档 modified_at 10:00, 10:01, 10:02(同 bidder 集中修改);bidder_b 文档 modified_at 距离 > 5 分钟
- **THEN** 虽 bidder_a 内部窗口内多文档,但无跨 side → sub_scores.modified_at_cluster = 0

#### Scenario: 窗口可 monkeypatch

- **WHEN** `monkeypatch.setenv("METADATA_TIME_CLUSTER_WINDOW_MIN", "30")` 后调 run()
- **THEN** window 读 30 分钟;30 分钟内的跨 bidder 聚集命中

#### Scenario: time 双字段全缺失 → Agent 级 skip

- **WHEN** bidder_a/b 所有 DocumentMetadata `doc_modified_at` 和 `doc_created_at` 均为 None
- **THEN** Agent run 返 `AgentRunResult(score=0.0, summary="元数据缺失:...")`;PairComparison.score=0.0 + evidence.participating_fields=[]

### Requirement: metadata_machine 机器指纹元组碰撞算法

Agent `metadata_machine` 的 `run()` MUST 对 bidder_a/bidder_b 双方 `(app_name, app_version, template_norm)` 三字段**元组精确碰撞**计算:

1. 每份文档构成 key = `(app_name, app_version, template_norm)`;**三字段任一为 None 视为不参与**(整份文档不贡献 machine 匹配)
2. 双方 tuples_a / tuples_b 分别按 key 聚合(同一 key 可能多个 doc)
3. 共同 key `common = keys_a ∩ keys_b`;非空即命中
4. `hit_strength = 命中 key 所覆盖的 doc 数 / 双方总 doc 数`(clamp [0, 1])
5. 双方任一方 tuples 为空(无完整三字段元组)→ 维度级 skip

Agent `score = hit_strength × 100`;evidence hits 每条为:
```
{
  "field": "machine_fingerprint",
  "value": {"app_name": ..., "app_version": ..., "template": ...},
  "doc_ids_a": [...],
  "doc_ids_b": [...]
}
```

#### Scenario: 三字段元组完全一致命中

- **WHEN** bidder_a 2 文档元组均 `("microsoft office word", "16.0000", "normal.dotm")`;bidder_b 1 文档元组相同
- **THEN** Agent score ≥ 85.0(hit_strength=1.0 → ×100 = 100);is_ironclad=true;evidence.hits 含 1 条 machine_fingerprint 元组

#### Scenario: 任一字段不同不命中

- **WHEN** bidder_a (Word, 16.0000, Normal.dotm);bidder_b (Word, 16.0000, CustomBid.dotx)
- **THEN** common = ∅;Agent score = 0.0;evidence.hits = []

#### Scenario: 某字段全缺失走 Agent 级 skip

- **WHEN** bidder_a/b 所有 DocumentMetadata template=None(三字段元组不完整)
- **THEN** tuples_a = tuples_b = {};run 返 score=0.0 + evidence.participating_fields=[]

#### Scenario: 部分文档元组不完整,部分完整

- **WHEN** bidder_a 3 文档,其中 2 个 template=None,1 个 template="normal.dotm";bidder_b 2 文档均 template="normal.dotm"
- **THEN** tuples_a 只含 1 个 doc 的元组(其他 2 doc 跳过);若与 tuples_b 命中,则 evidence.doc_ids_a 含那 1 个 doc id

### Requirement: metadata_* Agent 级 skip 与子检测 flag 语义

3 个 metadata Agent MUST 区分四种路径,按优先级依次判定:

1. **preflight skip**(engine 层处理):`bidder_has_metadata` 返 false → preflight 返 `skip`,engine 标 AgentTask.status=skipped,**不写 PairComparison**
2. **子检测 flag 关闭**:`METADATA_<DIM>_ENABLED=false` → run 不调 extractor/detector,PairComparison 行 `score=0.0` + `evidence.enabled=false`;AgentTask.status=succeeded(用户配置意图,非异常)
3. **维度级 skip(字段全缺失)**:preflight 通过(数据行存在)但实际字段全 None → dim_result.score=None;run 仍写 PairComparison 行 `score=0.0` + `evidence.participating_fields=[]` + `evidence.reason=<原因>`
4. **算法异常**:extractor/detector 抛异常 → run catch,PairComparison 行 `score=0.0` + `evidence.error=<类型:消息前 200 字>`;AgentTask.status=succeeded(不让单 Agent 异常影响整体检测流程)

区分 `participating_fields=[]` 与 `enabled=false`:前端据此可显示"数据不足"vs"已禁用";**前端按 `enabled=false` 优先识别**。

#### Scenario: flag 关闭不调 extractor

- **WHEN** `METADATA_AUTHOR_ENABLED=false` 且双方元数据足够
- **THEN** run 直接返 `AgentRunResult(score=0.0, summary="metadata_author 子检测已禁用")`;PairComparison 行 evidence.enabled=false;extractor 不被调用(L1 可通过 mock 验证)

#### Scenario: flag 关闭不阻塞其他子检测

- **WHEN** `METADATA_AUTHOR_ENABLED=false` 但 METADATA_TIME/MACHINE 仍启用
- **THEN** metadata_author 返 enabled=false;metadata_time / metadata_machine 正常跑各自算法

#### Scenario: 维度级 skip 与 flag 关闭区分

- **WHEN** `METADATA_AUTHOR_ENABLED=true` 但双方 author/last_saved_by/company 全 None
- **THEN** PairComparison 行 score=0.0 + evidence.participating_fields=[] + evidence.enabled=true + evidence.reason 非空;前端据此显示"数据不足"而非"已禁用"

#### Scenario: 异常路径写 error

- **WHEN** extractor 抛异常(模拟 DB 连接失败)
- **THEN** run catch 住,返 AgentRunResult(score=0.0);PairComparison 行 score=0.0 + evidence.error 非空(含类型+消息前 200 字);AgentTask.status=succeeded

### Requirement: metadata_* evidence_json 结构

`PairComparison.evidence_json` 对 `dimension in {'metadata_author', 'metadata_time', 'metadata_machine'}` 的行 MUST 包含以下统一核心字段,供前端合并 tab 渲染:

| 字段 | 类型 | 说明 |
|---|---|---|
| `algorithm` | string | `"metadata_author_v1"` / `"metadata_time_v1"` / `"metadata_machine_v1"` |
| `enabled` | bool | 对应 `METADATA_<DIM>_ENABLED` 配置值,false 时该 Agent 其他字段可为空/默认 |
| `score` | float/null | 0~1 归一化分(×100 即 Agent score);维度级 skip 时 null |
| `reason` | string/null | 维度级 skip 或 flag 禁用或异常时的描述 |
| `participating_fields` | string[] | 参与命中的子字段名,子集 of 各 Agent 自身定义的子字段 |
| `sub_scores` | object | 每子字段/子信号独立 score(0~1) |
| `hits` | array | 命中条目数组;每条结构因 Agent 不同见下 |
| `doc_ids_a` | int[] | bidder_a 参与检测的全部 BidDocument id |
| `doc_ids_b` | int[] | bidder_b 参与检测的全部 BidDocument id |
| `error` | string/null | 算法异常时的错误描述(类型:消息前 200 字);正常路径为 null 或缺省 |

`hits` 条目结构:

- `metadata_author`:`{field: "author"|"last_saved_by"|"company", value: <原值>, normalized: <归一化后>, doc_ids_a, doc_ids_b}`
- `metadata_time`:`{dimension: "modified_at_cluster"|"created_at_match", window_min?: int, doc_ids_a, doc_ids_b, times: string[]}`
- `metadata_machine`:`{field: "machine_fingerprint", value: {app_name, app_version, template}, doc_ids_a, doc_ids_b}`

`hits` 条目上限 `METADATA_MAX_HITS_PER_AGENT`(默认 50)。

#### Scenario: 正常命中 evidence_json

- **WHEN** metadata_author 命中 "张三"
- **THEN** evidence_json.algorithm="metadata_author_v1",enabled=true,score>0,participating_fields 含 "author",hits[0].field="author",hits[0].value="张三",hits[0].doc_ids_a 非空

#### Scenario: flag 关闭 evidence_json

- **WHEN** METADATA_MACHINE_ENABLED=false
- **THEN** evidence_json.algorithm="metadata_machine_v1",enabled=false,score=null 或 0;其他字段可缺省

#### Scenario: 维度级 skip evidence_json

- **WHEN** 三字段全缺失
- **THEN** evidence_json.enabled=true,score=null,reason 非空,participating_fields=[],hits=[]

### Requirement: metadata_* 环境变量

后端 MUST 支持以下环境变量动态读取(env 解析失败时 fallback 到默认值 + `logger.warning`):

- `METADATA_AUTHOR_ENABLED`(默认 `true`)— 布尔:`"false"`/`"0"` 视为 false,其余为 true
- `METADATA_TIME_ENABLED`(默认 `true`)
- `METADATA_MACHINE_ENABLED`(默认 `true`)
- `METADATA_TIME_CLUSTER_WINDOW_MIN`(默认 `5`)— int,单位分钟
- `METADATA_AUTHOR_SUBDIM_WEIGHTS`(默认 `"0.5,0.3,0.2"`)— 逗号分隔 float,顺序 `author,last_saved_by,company`
- `METADATA_TIME_SUBDIM_WEIGHTS`(默认 `"0.7,0.3"`)— 顺序 `modified_at_cluster,created_at_match`
- `METADATA_IRONCLAD_THRESHOLD`(默认 `85.0`)— Agent score ≥ 阈值 → is_ironclad
- `METADATA_MAX_HITS_PER_AGENT`(默认 `50`)— evidence hits 截断上限

#### Scenario: ENABLED 布尔解析

- **WHEN** `METADATA_AUTHOR_ENABLED="false"`(小写字串)
- **THEN** `load_author_config().enabled == False`

#### Scenario: WEIGHTS 解析失败走默认

- **WHEN** `METADATA_AUTHOR_SUBDIM_WEIGHTS="abc,xyz"` 不是合法 float
- **THEN** `load_author_config().subdim_weights == {"author": 0.5, "last_saved_by": 0.3, "company": 0.2}`;日志 warning

#### Scenario: 运行期 monkeypatch 生效

- **WHEN** L1/L2 测试 `monkeypatch.setenv("METADATA_TIME_CLUSTER_WINDOW_MIN", "15")`
- **THEN** 下一次调用 `load_time_config().window_min == 15`

### Requirement: _preflight_helpers.bidder_has_metadata machine 分支扩 template

`_preflight_helpers.bidder_has_metadata(session, bidder_id, require_field="machine")` MUST 在 C10 后扩展条件为 `app_version IS NOT NULL OR app_name IS NOT NULL OR template IS NOT NULL`(逻辑 OR)。

其他 `require_field` 值(`"author"` / `"modified"`)保持 C6 既有逻辑不变。

#### Scenario: template 非空即通过

- **WHEN** bidder 所有 DocumentMetadata app_version=None, app_name=None 但某文档 template="Normal.dotm"
- **THEN** `bidder_has_metadata(session, bidder_id, "machine") == True`

#### Scenario: 三字段全空不通过

- **WHEN** bidder 所有 DocumentMetadata app_version/app_name/template 全 None
- **THEN** `bidder_has_metadata(session, bidder_id, "machine") == False`;metadata_machine preflight 返 skip
