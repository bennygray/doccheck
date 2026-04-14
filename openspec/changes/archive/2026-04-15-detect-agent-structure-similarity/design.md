## Context

### 现状(C8 归档后)

- `AGENT_REGISTRY["structure_similarity"]` 已注册(C6),preflight = "双方在 `bidders_share_any_role` 上有同角色文档",run 目前走 `dummy_pair_run`
- **C8 `section_sim_impl/chapter_parser` 可复用**:C8 归档带来 `extract_chapters(paragraphs) -> list[ChapterBlock]`(5 PATTERN 正则切章 + 碎章节合并),C9 目录结构维度直接 import 复用
- **C5 xlsx 持久化不足**:`parser/content/__init__.py` xlsx 分支只写 `DocumentText`(按 sheet 合并为文本),**cell 矩阵和合并单元格信息未入库**;C9 需要 cell 级数据,须先延伸 C5
- `BidDocument.file_ext` 区分 `.docx` / `.xlsx`(C4 已有),preflight/run 可按 ext 分流维度
- `get_cpu_executor()` C7/C8 已消费,C9 目录维度的 LCS 算法纯 CPU 密集(段落数 × 段落数),也走同一 executor;字段/填充维度 JSONB 已按 sheet 切分,不上 executor
- 其他 7 个 Agent(price/metadata/image/style)仍 dummy,C9 不触它们

### 约束

- **C6 contract 锁定 + C7/C8 子包只读**:AGENT_REGISTRY key / preflight 签名 / AgentContext / AgentRunResult 全零改动;C8 `chapter_parser` 一字不改(import only)
- **零新增第三方依赖**:openpyxl(C5 已)+ SQLAlchemy JSONB(C3 已);LCS/Jaccard 手写
- **score ∈ [0, 100]**:DB `Numeric(6, 2)`,C6 PairComparison 已定
- **LLM 不引入**:结构维度纯程序化,ctx.llm_provider 不消费
- **execution-plan §3 C9 兜底原文**:结构提取失败 → 该维度 skip(**不做 C8 式降级到整文档粒度**);3 维度全失败 → Agent 整体 skip,状态 `succeeded` 但 `score=None`、`summary="结构缺失"`
- **score 规则**:任一维度 skip 时,该维度不进加权;最终 score 按"实际参与维度的原始权重归一化再求和",例:仅目录+填充参与 → score = dir_score × (0.4/0.7) + fill_score × (0.3/0.7)

### 干系方

- **审查员**:报告页能看到"目录结构 92% 雷同 + 报价表字段结构 85% 雷同"这类证据锚点
- **C10~C14 实施者**:C9 建立的"复用 C8 chapter_parser + 新增 cell 级数据层"模式是 C10(metadata 3 Agent 合并)的基础;C11 price-consistency 也会消费 DocumentSheet
- **C17 前端**:三维度各自 sub_score + pattern 级 evidence 需要独立渲染格子

## Goals / Non-Goals

### Goals

1. **三维度结构相似度计算**:目录结构(docx 章节标题 LCS)/ 字段结构(xlsx 列头 + 非空 bitmask + 合并单元格 Jaccard)/ 表单填充模式(xlsx value type pattern Jaccard)
2. **数据层延伸打通 cell 级**:新增 `DocumentSheet` 模型 + alembic 0006 + `parser/content/__init__.py` xlsx 分支扩展(保留 DocumentText 写入,追加 DocumentSheet 写入)
3. **回填脚本幂等**:`backend/scripts/backfill_document_sheets.py` 扫 xlsx BidDocument,skip 已有 DocumentSheet 的 doc,错误隔离(单 doc 失败不中断)
4. **4 验证场景全绿**(execution-plan §3 C9):目录完全一致命中 / 报价表填充结构一致命中 / 独立结构不误报 / 结构提取失败标"结构缺失"
5. **Agent 整体或维度 skip 路径完备**:3 维度任何一个提取失败 → 该维度不进 score;3 全失败 → Agent succeeded 但 score=None
6. **复用 C8 chapter_parser 零改动**,不搬代码不拷贝

### Non-Goals

- **合并单元格内部填充内容的语义比对**:只比 ranges 位置集合,不比单元格值相似度(留 follow-up)
- **xlsx sheet 间目录/章节识别**:xlsx 无"章节"语义,目录结构维度只对 docx 生效;xlsx 只提字段/填充两个维度
- **docx 表格(如投标函签字栏)的字段结构识别**:execution-plan §3 C9 Scenario 2 明确是"报价表"(xlsx),C9 不做 docx 表格解析
- **前端 C17**:字段/填充维度 evidence 的表格渲染、合并单元格高亮全留 C17
- **LLM 语义解释**:C14 综合研判再 LLM 串所有维度,C9 只出程序化分数+结构化 evidence
- **巨型 xlsx(> 10k 行)性能调优**:裁到 `MAX_ROWS_PER_SHEET=5000` 给出告警,根本解留更后
- **DocumentSheet 版本化 / 变更追踪**:BidDocument 有 version 字段(C4),重新 upload 时直接删旧 DocumentSheet 再建新的,不做 soft delete

## Decisions

### D1 — `DocumentSheet` 数据模型

**决策**:独立文件 `backend/app/models/document_sheet.py`,与 `DocumentImage`/`DocumentText` 并列

```python
class DocumentSheet(Base):
    __tablename__ = "document_sheets"  # 复数,对齐 document_texts/document_images
    id: Mapped[int] = mapped_column(primary_key=True)
    bid_document_id: Mapped[int] = mapped_column(
        ForeignKey("bid_documents.id"), nullable=False, index=True
    )  # 不加 CASCADE(对齐既有 DocumentText/DocumentImage)
    sheet_index: Mapped[int] = mapped_column()  # 0-based,在 workbook 中顺序
    sheet_name: Mapped[str] = mapped_column(String(255))
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    # JSONB(PG)/ JSON(SQLite) 双写用 `sa.JSON().with_variant(JSONB, "postgresql")`
    rows_json: Mapped[list] = mapped_column(JSON_VARIANT, nullable=False)
    # [[cell, cell, ...], ...] cell = str | float | int | bool | None
    # 裁切规则:rows 数 > MAX_ROWS_PER_SHEET=5000 → 截断 + warning
    merged_cells_json: Mapped[list[str]] = mapped_column(JSON_VARIANT, default=list)
    # ["A1:B2", "C3:D4", ...] openpyxl ws.merged_cells.ranges str
    created_at: Mapped[datetime] = mapped_column(...)

    # 联合唯一 (bid_document_id, sheet_index) 避免重复
    __table_args__ = (UniqueConstraint("bid_document_id", "sheet_index"),)
```

**理由**:
- 独立文件对齐 `DocumentImage`/`DocumentText`,避免 `document.py` 膨胀
- rows 存整表 JSONB 而非 cell 逐行表:C9 用法是整 sheet 读取 Jaccard,不做 cell 级 SQL 查询;整表 JSONB 最简单,读写 O(1) sheet
- `merged_cells_json` 存字符串 list(openpyxl 原生 `ranges` 的 `str(r)` 即 `"A1:B2"`)比起 `(r1,c1,r2,c2)` 元组更小、可读

**替代方案**:
- cell 逐行表(`document_cell` 每行一 row) → 每 sheet 千行,数据库行数膨胀,拒
- 扩 `DocumentText.content_json` → DocumentText 语义是"可喂相似度的文本",混职责,拒
- parquet/外部文件 → 跨网关复杂度,拒

### D2 — C5 xlsx 持久化扩展

**决策**:`parser/content/__init__.py` xlsx 分支保留 DocumentText,追加 DocumentSheet 写入

```python
elif ext == ".xlsx":
    result = await asyncio.to_thread(extract_xlsx, file_path)
    for i, sheet in enumerate(result.sheets):
        # 原路径(保留):DocumentText 合并文本,供相似度 Agent
        session.add(DocumentText(
            bid_document_id=bid_document_id,
            paragraph_index=i,
            text=sheet.merged_text,
            location="sheet",
        ))
        # 新路径:DocumentSheet 整表 rows + merged_cells
        rows = sheet.rows
        if len(rows) > MAX_ROWS_PER_SHEET:
            rows = rows[:MAX_ROWS_PER_SHEET]
            # warning 记日志,不进 DB
        session.add(DocumentSheet(
            bid_document_id=bid_document_id,
            sheet_index=i,
            sheet_name=sheet.sheet_name,
            hidden=sheet.hidden,
            rows_json=rows,
            merged_cells_json=sheet.merged_cells_ranges,
        ))
```

**xlsx_parser.py 扩展**:`SheetData` 追加 `merged_cells_ranges: list[str]` 字段,`extract_xlsx` 读 `ws.merged_cells.ranges` 转字符串

**理由**:双写 DocumentText + DocumentSheet,现有 C7/C8 相似度 Agent 继续消费 DocumentText.merged_text,C9 消费 DocumentSheet.rows_json,不冲突;openpyxl `read_only=False` 已能读 merged_cells(read_only 模式读不到)

**替代方案**:
- 废弃 DocumentText 的 sheet 合并 → 会坏 C7/C8 对 xlsx 相似度的兼容路径,拒
- 只在需要时运行时 extract(Agent 内 re-extract)→ Agent 层 I/O 依赖文件路径,跨 ProcessPool worker 风险,**用户已 review 拒**

### D3 — 回填脚本

**决策**:`backend/scripts/backfill_document_sheets.py` 手工触发,幂等,错误隔离

```python
async def backfill():
    async with SessionLocal() as session:
        # 1. 扫 xlsx + identified 且无 DocumentSheet 的 BidDocument
        q = (
            select(BidDocument)
            .where(BidDocument.file_ext == ".xlsx")
            .where(BidDocument.parse_status == "identified")
            .where(~exists().where(DocumentSheet.bid_document_id == BidDocument.id))
        )
        docs = (await session.execute(q)).scalars().all()
        for doc in docs:
            try:
                result = await asyncio.to_thread(extract_xlsx, doc.file_path)
                for i, sheet in enumerate(result.sheets):
                    rows = sheet.rows[:MAX_ROWS_PER_SHEET]
                    session.add(DocumentSheet(
                        bid_document_id=doc.id,
                        sheet_index=i,
                        sheet_name=sheet.sheet_name,
                        hidden=sheet.hidden,
                        rows_json=rows,
                        merged_cells_json=sheet.merged_cells_ranges,
                    ))
                await session.commit()
                print(f"OK doc={doc.id} sheets={len(result.sheets)}")
            except Exception as e:
                await session.rollback()
                print(f"FAIL doc={doc.id}: {e}")  # 不中断
```

- 入口:`python -m scripts.backfill_document_sheets`(或 `uv run python backend/scripts/backfill_document_sheets.py`)
- 幂等:DocumentSheet 已存在的 doc 跳过(用 `NOT EXISTS` 子查询)
- 错误隔离:单 doc 失败 rollback + 打日志,继续下一个
- 运行位置:运维手工,不嵌 alembic 迁移(migration 只动 schema)

**理由**:幂等 + 错误隔离是运维脚本标配;写进 tasks.md 末尾的 `[manual]` 任务记录"在哪台机器跑过+处理失败条数"

### D4 — 目录结构维度算法(LCS)

**决策**:`title_lcs.compute_directory_similarity(titles_a, titles_b) -> float`

```python
def compute_directory_similarity(titles_a: list[str], titles_b: list[str]) -> float:
    """LCS-based 目录序列相似度 → 0~1"""
    if not titles_a or not titles_b:
        return 0.0
    # 标题归一化:去前后空白、去 Unicode 全角空格、统一序号前缀
    norm_a = [_normalize_title(t) for t in titles_a]
    norm_b = [_normalize_title(t) for t in titles_b]
    lcs_len = _lcs_length(norm_a, norm_b)  # 经典 DP O(m*n)
    return 2 * lcs_len / (len(norm_a) + len(norm_b))
```

**章节提取**:`extract_chapters(paragraphs)` 直接复用 C8 `section_sim_impl.chapter_parser`(零改动),取 `ChapterBlock.title` list

**归一化函数**:
- 去 `第X章 / 第X节 / X.Y / 一、` 等序号前缀(正则替换),**只保留标题实质内容**(避免"第1章 投标函" vs "1 投标函" 因序号不同被判不同)
- 去所有空白、全角空格、顿号;统一中文全半角

**理由**:
- LCS 同时处理"标题顺序相同但部分章节缺失"和"章节插入/删除",比纯 Jaccard(忽略顺序)更贴合"目录序列"语义
- execution-plan Scenario 1 "两份投标书目录完全一致(含错别字)" → 归一化+LCS 足够;错别字级差异本 change 不做(留 C14 LLM 研判)
- 算法复杂度 O(m × n),实际 m/n < 30 可忽略

**替代方案**:
- 序列编辑距离(Levenshtein) → 和 LCS 等价程度够,但归一化成"相似度"需多一步除法,拒
- Jaccard(把章节标题视为无序集合)→ 漏掉顺序信息,Scenario 1"完全一致"能命中但"错乱一致"误命中,拒
- 直接引 `difflib.SequenceMatcher` → stdlib 可用,但其 ratio 含字符级匹配会把"第1章 投标函"和"第2章 投标须知"算出 ~0.7(前缀"第"+"章"共享),误报偏高;自写 LCS 干净,拒

### D5 — 字段结构维度算法(xlsx)

**决策**:`field_sig.compute_field_similarity(sheet_a, sheet_b) -> FieldSimResult`

三子信号加权,默认子权重 `0.4 / 0.3 / 0.3`(列头/bitmask/合并单元格),走 env `STRUCTURE_SIM_FIELD_JACCARD_SUB_WEIGHTS`

```python
@dataclass
class FieldSimResult:
    score: float  # 0~1
    header_sim: float
    bitmask_sim: float
    merged_cells_sim: float
    evidence: dict  # 各子信号的匹配项,前 N 条

def compute_field_similarity(rows_a, merged_a, rows_b, merged_b) -> FieldSimResult:
    # 1. 列头 hash:取首个非空 row,归一化后 sha256 截 16 字符 → 集合 Jaccard
    header_a = _extract_header(rows_a)   # list[str] 归一化后
    header_b = _extract_header(rows_b)
    header_sim = _jaccard(set(header_a), set(header_b))  # 列头词集合
    # 2. 非空 bitmask 序列:每行一个 bitmask(0/1 表示列是否非空),
    #    两侧各算所有行 bitmask 的 multiset,Jaccard
    bits_a = [_row_bitmask(r) for r in rows_a]
    bits_b = [_row_bitmask(r) for r in rows_b]
    bitmask_sim = _jaccard_multiset(bits_a, bits_b)
    # 3. 合并单元格 ranges:两侧 ranges 集合 Jaccard
    merged_sim = _jaccard(set(merged_a), set(merged_b))
    score = (header_sim * W_H + bitmask_sim * W_B + merged_sim * W_M)
    return FieldSimResult(score, header_sim, bitmask_sim, merged_sim, evidence=...)
```

**跨 sheet 配对**:两侧 xlsx 可能 sheet 数不等;按 sheet_name 相同配对,未配对的 sheet 贡献 0 分;最终 xlsx 字段相似度 = `max(sheet_sims)`(一表雷同即可触发)

**理由**:
- 列头 hash Jaccard 捕"用同一模板填报"(Scenario 2 典型信号)
- bitmask 序列 multiset 捕"同样的空值分布"(模板中留白区域一致)
- 合并单元格 ranges Jaccard 捕"用同一格式复制的报价表"
- 三子信号独立失败隔离:列头行不存在 → header_sim=0 但不 skip 整维度;全部失败 → 维度 skip

**替代方案**:
- sheet 间全对全配对 → sheet 少的时候退化成 max;sheet 多时 O(N×M) 爆且"用户 intent"不是全对全,拒
- 列头用全文 TF-IDF cosine → 列头短(< 20 字符),TF-IDF 无意义,拒
- bitmask 用顺序比对(LCS) → bitmask 数量通常 > 100 行,LCS O(m×n) 过大;multiset Jaccard 快,拒

### D6 — 表单填充模式维度算法(xlsx)

**决策**:`fill_pattern.compute_fill_similarity(sheet_a, sheet_b) -> FillSimResult`

```python
def _cell_type_pattern(cell) -> str:
    """cell → 'N'(数字) / 'D'(日期) / 'T'(文本) / '_'(空)"""
    if cell is None or (isinstance(cell, str) and not cell.strip()):
        return "_"
    if isinstance(cell, (int, float)):
        return "N"
    if isinstance(cell, datetime):
        return "D"
    # 字符串 → 尝试转数字/日期
    s = str(cell).strip()
    if _looks_like_number(s): return "N"
    if _looks_like_date(s): return "D"
    return "T"

def compute_fill_similarity(rows_a, rows_b) -> FillSimResult:
    pat_a = [[_cell_type_pattern(c) for c in r] for r in rows_a]
    pat_b = [[_cell_type_pattern(c) for c in r] for r in rows_b]
    # 每行的 type pattern 串成字符串如 "TN_N_D" → 作为 multiset 元素
    lines_a = ["".join(row) for row in pat_a]
    lines_b = ["".join(row) for row in pat_b]
    sim = _jaccard_multiset(lines_a, lines_b)
    return FillSimResult(score=sim, matched_lines=..., evidence=...)
```

**跨 sheet 配对**:同 D5(sheet_name 匹配取 max)

**理由**:
- "表单填充模式"的典型围标信号是"所有投标人的报价表按同一种类型结构填写"(数字列和文本列位置完全一致)
- 按行 pattern 字符串 + multiset Jaccard 能抓到"重复出现的同 pattern 行"
- 与 D5 bitmask 的区别:bitmask 只管"空/非空",本维度进一步区分"数字/日期/文本",粒度更细

**替代方案**:
- 用 cell 原值 hash 做 Jaccard → 数字内容不同但结构相同会被判不同(假阴),拒
- 用 regex 做更细粒度(电话/金额/日期 pattern) → 维度空间爆炸,且 regex 未必准;粗分 4 类够用,拒

### D7 — 三维度聚合

**决策**:`scorer.aggregate_structure_score(dir_sim, field_sim, fill_sim, weights) -> tuple[float, list[str]]`

```python
DEFAULT_WEIGHTS = (0.4, 0.3, 0.3)  # 目录 / 字段 / 填充, env 可覆盖

def aggregate_structure_score(
    dir_result: DirResult | None,  # None 表示该维度 skip
    field_result: FieldResult | None,
    fill_result: FillResult | None,
    weights: tuple[float, float, float],
) -> tuple[float | None, list[str], dict]:
    participating = []
    total_weight = 0.0
    weighted_sum = 0.0
    if dir_result is not None:
        participating.append("directory")
        total_weight += weights[0]
        weighted_sum += dir_result.score * weights[0]
    if field_result is not None:
        participating.append("field_structure")
        total_weight += weights[1]
        weighted_sum += field_result.score * weights[1]
    if fill_result is not None:
        participating.append("fill_pattern")
        total_weight += weights[2]
        weighted_sum += fill_result.score * weights[2]
    if not participating:
        return None, [], {"reason": "all_dimensions_missing"}
    # 归一化到原始权重:参与维度 re-normalize
    normalized = (weighted_sum / total_weight) * 100  # × 100 → 0~100
    return round(min(100.0, max(0.0, normalized)), 2), participating, {...}
```

**归一化语义**:
- 全 3 维度参与:`(dir×0.4 + field×0.3 + fill×0.3) × 100`
- 仅目录+填充:`(dir×0.4 + fill×0.3) / 0.7 × 100`(等效按 0.57 : 0.43 重新分配)
- 全 skip:`score=None`,Agent summary="结构缺失"

**is_ironclad**:任一维度 sub_score ≥ 0.90 且 Agent 总 score ≥ 85 → is_ironclad=True(延续 judge.py 铁证阈值)

**理由**:
- 权重归一化避免"仅一个维度参与"时 score 被稀释(否则 score 上限只到 0.4×100=40,极不直观)
- 维度级 skip 语义清晰:evidence.participating_dimensions 列明哪几个维度参与了
- 不引 LLM → 不需要 C7/C8 的"段落对 → LLM 判断"双轨,简化

### D8 — preflight 与 run 分工

**决策**:preflight 轻量 + run 内部分维度判定

```python
async def preflight(ctx):
    # 1. C6 原约束:同角色文档存在
    shared = await _preflight_helpers.choose_shared_role(session, a.id, b.id)
    if not shared:
        return PreflightResult("skip", "缺少可对比文档")
    # 2. 先判"是否至少有一个可提取维度"——这步要查 DB 轻量 count,不做完整提取
    has_docx = await _has_docx_in_shared_role(session, a.id, b.id, shared)
    has_xlsx = await _has_xlsx_in_shared_role(session, a.id, b.id, shared)
    if not has_docx and not has_xlsx:
        return PreflightResult("skip", "结构缺失")  # docx/xlsx 都没有
    return PreflightResult("ok")

async def run(ctx):
    # 1. 目录结构维度:仅 docx 有效
    dir_result = await _run_directory_dim(ctx) if has_docx else None
    # 2. 字段结构维度:仅 xlsx 有效
    field_result = await _run_field_dim(ctx) if has_xlsx else None
    # 3. 填充模式维度:仅 xlsx 有效
    fill_result = await _run_fill_dim(ctx) if has_xlsx else None
    # 4. 聚合
    score, participating, meta = aggregate_structure_score(dir_result, field_result, fill_result, W)
    if score is None:
        # run 级 skip:score=0.0 哨兵 + evidence.participating_dimensions=[]
        await _persist_pair_comparison(ctx, Decimal("0.00"), False, evidence_skip)
        return AgentRunResult(score=0.0, summary="结构缺失:...")
    return AgentRunResult(score=score, summary=..., evidence_json=evidence)
```

**理由**:
- preflight 不做真正的结构提取(章节切分 / cell 矩阵读取),那些在 run 内走 executor
- "结构缺失"判定分两级:preflight 级(根本没 docx/xlsx)→ skip 整 Agent;run 级(维度内部提取失败)→ 维度 None

### D9 — evidence_json 结构

**决策**:
```json
{
  "algorithm": "structure_sim_v1",
  "doc_role": "tech_scheme",
  "doc_id_a": 123, "doc_id_b": 456,
  "participating_dimensions": ["directory", "field_structure", "fill_pattern"],
  "weights_used": {"directory": 0.4, "field_structure": 0.3, "fill_pattern": 0.3},
  "dimensions": {
    "directory": {
      "score": 0.92,
      "titles_a_count": 12,
      "titles_b_count": 11,
      "lcs_length": 10,
      "sample_titles_matched": ["第1章 投标函", "第2章 投标人须知", ...]
    },
    "field_structure": {
      "score": 0.85,
      "per_sheet": [
        {"sheet_name": "报价汇总", "header_sim": 0.95, "bitmask_sim": 0.80, "merged_cells_sim": 0.88, "sub_score": 0.88}
      ]
    },
    "fill_pattern": {
      "score": 0.78,
      "per_sheet": [
        {"sheet_name": "报价汇总", "score": 0.78, "matched_pattern_lines": 45, "sample_patterns": ["TN_N_D", ...]}
      ]
    }
  }
}
```

- `participating_dimensions` 列明哪些进了加权(供前端判断哪些维度展开)
- 维度内提取失败时 `dimensions.<dim>.score = null` + `dimensions.<dim>.reason = "..."`
- `sample_titles_matched` 上限 10 条;`per_sheet` 上限 5 sheet;`sample_patterns` 上限 10 条

### D10 — 测试分层

- **L1**(子包纯函数):
  - `test_title_lcs.py`:归一化函数 / LCS DP 正确性 / 序号前缀剥离 / 空输入边界
  - `test_field_sig.py`:header Jaccard / bitmask multiset Jaccard / merged_cells Jaccard / sheet_name 配对 / 子权重加权
  - `test_fill_pattern.py`:cell_type_pattern 4 类识别 / 数字日期字符串探测 / Jaccard
  - `test_scorer.py`:3 维度全参与 / 仅 2 维度 / 仅 1 维度 / 全 skip / is_ironclad 触发
  - `test_structure_similarity_run.py`:preflight 各路径 / run 正常三维度 / xlsx-only / docx-only / 全 skip
  - `test_document_sheet_model.py`:建模 + unique 约束
  - `test_backfill_document_sheets.py`:幂等(重跑不重复插入)/ 错误隔离(单 doc 失败不中断)
- **L2**(API E2E,`tests/e2e/test_detect_structure_similarity.py`):
  - Scenario 1:目录完全一致(两个 docx 章节标题序列相同)→ score ≥ 60 + evidence.dimensions.directory.score ≥ 0.9
  - Scenario 2:报价表填充结构一致(两个 xlsx 列头相同 + bitmask 相同)→ score ≥ 60 + evidence.dimensions.field_structure.score ≥ 0.8
  - Scenario 3:结构差异明显(不同目录 + 不同列头)→ score < 30,不误报
  - Scenario 4:结构提取失败(无 docx 无 xlsx,仅图片)→ Agent succeeded 但 score=None,summary="结构缺失"
- **L3**:延续 C5~C8 降级手工凭证,`e2e/artifacts/c9-YYYY-MM-DD/README.md` 占位 + 3 张截图计划(启动检测 / 报告页 structure_similarity 三维度展开 / 回填脚本执行日志截图)

### D11 — 环境变量

| env | 默认 | 作用 |
|---|---|---|
| `STRUCTURE_SIM_MIN_CHAPTERS` | 3 | 目录结构维度:章节数 < 此值 → 该维度 skip |
| `STRUCTURE_SIM_MIN_SHEET_ROWS` | 2 | 字段/填充维度:每 sheet 非空行 < 此值 → 该 sheet 不参与 |
| `STRUCTURE_SIM_WEIGHTS` | `"0.4,0.3,0.3"` | 三维度权重(目录/字段/填充),逗号分隔 float |
| `STRUCTURE_SIM_FIELD_JACCARD_SUB_WEIGHTS` | `"0.4,0.3,0.3"` | 字段维度三子信号权重(列头/bitmask/合并单元格) |
| `STRUCTURE_SIM_MAX_ROWS_PER_SHEET` | 5000 | 持久化层裁切:xlsx 单 sheet 行数上限(C5 延伸同用) |

**复用 C8 既有 env**:`SECTION_SIM_MIN_CHAPTER_CHARS=100`(chapter_parser 内部)——通过 C8 子包 import 生效,不复制

### D12 — ProcessPoolExecutor 消费点

- 目录结构维度:LCS O(m×n) CPU 密集 → `get_cpu_executor()` 异步跑
- 字段/填充维度:每 sheet 独立 Jaccard,数据结构本身是 multiset(set/Counter),CPU 压力低 → 默认不上 executor(单 Agent 运行时间可控);若后续压测发现瓶颈再改
- 与 C7/C8 共享同一 executor lazy 单例(C6 Risk-1 "executor cancel 无法真中断子进程任务"风险继承,mitigation 靠 `MAX_ROWS_PER_SHEET` 和 LCS 内部无限长度检查)

## Risks / Trade-offs

- **[R-1] DocumentSheet JSONB 膨胀**:大 xlsx(5000 行 × 20 列)整表 JSONB 存进 DB,单 doc ~2MB;mitigation:`MAX_ROWS_PER_SHEET=5000` 硬顶 + warning 日志 + follow-up 记录"巨型表分页存储"
- **[R-2] 回填脚本对生产数据的一次性动作**:M3 pre-prod,风险低;生产上线后每次重跑 C5 都会带 DocumentSheet(无需再回填);若未来 DocumentSheet schema 演进再写 0007+ 迁移处理
- **[R-3] 目录标题归一化过度**:剥离"第X章"前缀后"技术方案"和"技术方案"变同字符串,错别字"技木方案"仍不同;归一化不解错别字问题,留 C14 LLM;初期可能漏 Scenario 1 "含错别字" 子场景,但 execution-plan 原文 "含错别字" 未强制定义相似度阈值,按 L2 测试验收标准 ≥ 0.9 仅要求大部分章节相同即可
- **[R-4] sheet 配对按 sheet_name**:两家改了 sheet 名("报价表" vs "报价清单")→ 无法配对 → field/fill 维度 0 分;mitigation:follow-up 做 sheet 名 fuzzy 匹配;本期接受
- **[R-5] cell_type_pattern 过粗**:金额和数量同归 'N',漏精细区分;mitigation:execution-plan Scenario 2 是模板填充一致性,粗粒度足够;C11 price-consistency 会做精细金额分析
- **[R-6] xlsx_parser 扩展与现有 fill_price 路径共用**:SheetData 增字段 merged_cells_ranges,需 fill_price 兼容(只读原有 rows);已是 frozen dataclass 加字段对下游只加不减,兼容
- **[R-7] Agent 维度 skip 前端渲染**:`score=None` 和 `participating_dimensions` 前端需识别,C17 层实现;本 change L2 验证后端字段正确即可

## Migration Plan

### 上线步骤

1. **DB 迁移**:`alembic upgrade head` 跑 0006 加 `document_sheet` 表
2. **代码部署**:xlsx_parser 扩 merged_cells_ranges + content/__init__.py 双写 + structure_similarity.py 真实 run + scripts/backfill_document_sheets.py
3. **手工回填**:`uv run python -m scripts.backfill_document_sheets`(记录输出到 handoff)
4. **验证**:
   - 新 xlsx 上传 → DocumentSheet 行数 = sheet 数
   - 回填完成后已有 xlsx BidDocument 全部有 DocumentSheet 行
   - 首次用户启动检测 → structure_similarity 有真实 score(非 dummy 随机分特征,evidence.algorithm = "structure_sim_v1")

### 回滚策略

- 撤 C9 commit:`structure_similarity.py` 恢复 dummy、content/__init__.py 去掉 DocumentSheet 写入分支
- `alembic downgrade -1` drop document_sheet 表(0006 downgrade 处理)
- 已回填的 DocumentSheet 数据随表 drop 丢失(可接受,回填脚本可重跑)

## Open Questions

- **Q1**(延后至 C14):报告页如何把 structure_similarity 三维度展开渲染?本期 evidence_json 结构设计已留好 `dimensions.<dim>` 子对象,C17 UI 层负责
- **Q2**(C9 实施期验证):`STRUCTURE_SIM_WEIGHTS=0.4,0.3,0.3` 是否合理?L2 Scenario 2 "报价表结构一致" 对 field_structure 的权重敏感;实施期若 Scenario 2 score 不足 60 触发 is_ironclad,调 field weight 为 0.4(0.3,0.4,0.3)
- **Q3**(延后):sheet 名 fuzzy 匹配策略(若 Scenario 2 出现 sheet 名不一致的测试数据),放 handoff follow-up
- **Q4**(延后):巨型 xlsx 分页存储(`document_sheet_row` 逐行表),若生产环境 JSONB 平均大小超 1MB 再做
