## Context

### 现状(C9 归档后)

- **3 个 metadata Agent 骨架已就绪**(C6):`metadata_author` / `metadata_time` / `metadata_machine` 均注册到 `AGENT_REGISTRY`,preflight 通过 `bidder_has_metadata(session, bidder_id, require_field)` 实现(`_preflight_helpers.py` 已支持 `require_field in ["author", "modified", "machine"]`);run 目前都走 `dummy_pair_run`。
- **`DocumentMetadata` 数据层已就绪**(C5):表 `document_metadata` PK=`bid_document_id`,字段 `author / last_saved_by / company / doc_created_at / doc_modified_at / app_name / app_version` 全就绪;**缺 `template` 字段**。
- **`parser/content/__init__.py` 已提取元数据**(C5):docx/xlsx 的 `docProps/core.xml` + `docProps/app.xml` 解析并写入 `DocumentMetadata`,但**未提取 `Template` 字段**。
- **`_preflight_helpers.bidder_has_metadata` 的 `machine` 分支**当前看 `app_version OR app_name`(OR);C10 新增 `template` 字段后,preflight 仍维持"任一 machine 字段非空即通过"的宽松策略,保证 preflight 不过度拦截(run 内部精确判定)。
- **C5 回填成本已验证**(C9 做过 `backfill_document_sheets.py`):单 doc 独立 session + 错误隔离 + `--dry-run` 模板成熟,C10 照搬。
- **其他 4 个 Agent 仍 dummy**:`price_consistency` / `error_consistency` / `style` / `image_reuse`,C10 不触。

### 约束

- **C6 contract 锁定**:`name + agent_type + preflight` 三元组不变;3 Agent 文件保留,只改 `run()`。
- **C7/C8/C9 子包零改动**:C10 不 import 任何 `*_sim_impl/` 模块(元数据与相似度独立)。
- **`AgentRunResult` 契约不变**:`score: float, summary: str, evidence_json: dict = {}`;Agent 级 skip 用 `score=0.0` 哨兵(C9 已验证对齐)。
- **零新增第三方依赖**:`unicodedata`(stdlib)NFKC 归一化 + `collections.Counter` / `datetime` 原生类型,无外部包。
- **零 LLM 引入**:3 子维度纯程序化(字符串归一化聚类 + 时间窗扫描 + 元组碰撞);`ctx.llm_provider` 不消费。
- **execution-plan §3 C10 兜底原文**:
  - 元数据缺失 → 标"数据不足",不假阳
  - 提取器失败 → 整 Agent 标"失败",不影响其他维度
- **score ∈ [0, 100]**:DB `Numeric(6, 2)`,C6 PairComparison 已定。
- **score 规则**:Agent 级 score = 子维度命中"hit_strength"(0~1)× 100。`hit_strength` 定义见 D6。

### 干系方

- **审查员**:报告页可见"作者字段碰撞:3 份文档 author='张三'"/"机器指纹碰撞:Word 16.0000 + Normal.dotm 3 家一致"这类明证。
- **C11~C13 实施者**:C10 验证的"共享提取器 + 精确匹配 + 子检测 flag + Agent 级 skip 哨兵"模式,C11 价格一致性类似可复用"共享 DocumentSheet 提取器"。
- **C17 前端**:3 Agent evidence_json 字段统一结构(`participating_fields` / `cluster_hits` / `doc_ids`),前端按 `metadata_*` 合并 tab 渲染。

## Goals / Non-Goals

### Goals

1. **3 子 Agent 真实算法落地**:author/time/machine 各自检测并写 PairComparison。
2. **`DocumentMetadata` 扩 `template` 字段持久化**:alembic 0007 + parser 扩写 + 回填脚本三件套。
3. **`metadata_impl/` 共享子包 9 文件**:config / models / normalizer / extractor / author_detector / time_detector / machine_detector / scorer / `__init__.py`。
4. **5 Scenario 全绿**(execution-plan §3 C10):author 相同命中 / 时间聚集命中 / 机器指纹碰撞命中 / 元数据被清洗标"缺失" / 子检测 flag 可单独关闭。
5. **子检测 flag 单独开关**:env 级配置不重启生效(L1 monkeypatch 可验证)。
6. **Agent 级 skip 与维度级 skip 语义对齐 C9**:Agent 级用 `score=0.0` 哨兵 + `evidence.participating_fields=[]`;维度级用 `evidence.dimensions.<dim>.reason` 标注。

### Non-Goals

- **模糊匹配 / 变体合并**:"张三" vs "张三 (admin)" 等变体 → 留 follow-up(execution-plan 未要求,Q3 决策锁定纯精确)。
- **LLM 综合研判**:C14 再做。
- **`template` 字段跨平台标准化**:Windows 路径 `C:\...\Normal.dotm` vs macOS `/Users/.../Normal.dotm` 不做路径归一化,只做字符串 NFKC+casefold+strip;Office 自定义模板实际都是相同字符串。
- **前端合并 tab**:C17 做;本 change 保 judge 层能够 `SELECT dimension LIKE 'metadata_%'` 一次捞 3 行。
- **第三字段(last_printed_by / identifier)**:execution-plan 只要求 author/last_saved_by/company 三字段,不扩。
- **时间窗 alignment 到投标截止时间**:"5 分钟内被修改"按自然时间窗(挂墙时钟)而非相对时间计算。
- **DocumentMetadata 多 template 记录**:每文档 1:1,不支持"历史 template 列表"(Word 不暴露该信息)。
- **BidDocument 删除级联**:DocumentMetadata 跟 BidDocument 仍 FK 不 CASCADE(对齐 C5/C9 既有策略)。

## Decisions

### D1 — `DocumentMetadata.template` 字段扩展

**决策**:`document_metadata` 表加 `template VARCHAR(255) NULL`,alembic `0007_add_document_metadata_template`。

```python
# backend/app/models/document_metadata.py
class DocumentMetadata(Base):
    ...
    app_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    template: Mapped[str | None] = mapped_column(String(255), nullable=True)  # C10 新增
```

```python
# alembic 0007_add_document_metadata_template.py
def upgrade():
    op.add_column(
        "document_metadata",
        sa.Column("template", sa.String(length=255), nullable=True),
    )

def downgrade():
    op.drop_column("document_metadata", "template")
```

**理由**:
- `VARCHAR(255)` 足够:Office `Template` 字段实际最长约 100 字符(模板文件全路径)。
- 可空:C5 既有文档回填未完成前为 NULL;machine 维度遇 NULL 走单字段缺失 skip(不算 0,避免假阳)。
- 单向 head(回滚 drop 列)不设索引:machine 维度的聚类在内存中做,SQL 侧只 SELECT 几列,不需要索引。

**替代方案**:
- JSONB `extra_metadata_json` 吸收 → 字段数少(当前只 1 个 template),扁平列更直接;JSONB 留给未来多字段。拒。
- `String(500)` → 路径一般不超 255;255 已够兜底。拒。

### D2 — parser/content Template 字段提取

**决策**:`parser/content/__init__.py` 的 docx/xlsx 分支均扩展从 `docProps/app.xml` 提取 `Template` 字段,写入 `DocumentMetadata.template`。

```python
# parser/content/__init__.py(伪代码)
def _extract_metadata_from_docx(file_path: Path) -> dict:
    core = _parse_core_xml(file_path)     # 既有
    app = _parse_app_xml(file_path)       # 既有
    return {
        "author": core.get("creator"),
        "last_saved_by": core.get("lastModifiedBy"),
        "company": app.get("Company"),
        "doc_created_at": _parse_dt(core.get("created")),
        "doc_modified_at": _parse_dt(core.get("modified")),
        "app_name": app.get("Application"),
        "app_version": app.get("AppVersion"),
        "template": app.get("Template"),  # C10 新增
    }
```

**Template 在 docx/xlsx docProps/app.xml 的位置**:`<Template>Normal.dotm</Template>`(docx)或 `<Template>Normal.dotm</Template>`(xlsx);openpyxl/python-docx 不直接暴露,parser 通过 zipfile + xml.etree 解析(C5 既有代码已这么做)。

**`Template` 缺失时**:写 NULL;不抛错。

**新文档自然经过**:上传触发的新文档走 C5 既有 pipeline,自然带上 template;**历史文档需回填**(见 D3)。

### D3 — 回填脚本 `backfill_document_metadata_template.py`

**决策**:`backend/scripts/backfill_document_metadata_template.py`,照搬 C9 `backfill_document_sheets.py` 模板。

```python
async def backfill():
    async with SessionLocal() as session:
        # 扫 parse_status = identified 且 DocumentMetadata 存在但 template 为 NULL 的文档
        q = (
            select(BidDocument, DocumentMetadata)
            .join(DocumentMetadata, DocumentMetadata.bid_document_id == BidDocument.id)
            .where(BidDocument.parse_status == "identified")
            .where(BidDocument.file_type.in_([".docx", ".xlsx"]))
            .where(DocumentMetadata.template.is_(None))
        )
        rows = (await session.execute(q)).all()
        ok_count, fail_count = 0, 0
        for doc, meta in rows:
            try:
                async with AsyncSessionLocal() as tx:
                    extracted = await asyncio.to_thread(_extract_template, doc.file_path)
                    # 重新 query 避免跨 session 对象
                    m = await tx.get(DocumentMetadata, doc.id)
                    if m is None:
                        continue
                    m.template = extracted  # 可能 None
                    await tx.commit()
                print(f"OK doc={doc.id} template={extracted!r}")
                ok_count += 1
            except Exception as e:
                print(f"FAIL doc={doc.id}: {e}")
                fail_count += 1
        print(f"total={ok_count + fail_count} success={ok_count} failed={fail_count}")
```

- **入口**:`uv run python backend/scripts/backfill_document_metadata_template.py` 或 `python -m scripts.backfill_document_metadata_template`
- **`--dry-run` 支持**:打印待回填 doc 数量,不写入。
- **幂等**:SQL 过滤 `template IS NULL`,已回填的自动 skip。
- **错误隔离**:单 doc 独立 session,失败 rollback 不影响后续。
- **不纳入 alembic**:migration 只动 schema。

### D4 — `metadata_impl/` 子包结构

**决策**:`backend/app/services/detect/agents/metadata_impl/`,9 文件:

```
metadata_impl/
├── __init__.py
├── config.py            # env 读取 + flag + 默认值
├── models.py            # MetadataRecord / ClusterHit / TimeCluster evidence schema (TypedDict)
├── normalizer.py        # nfkc_casefold_strip(s) -> str (共用归一化)
├── extractor.py         # extract_bidder_metadata(session, bidder_id) -> list[MetadataRecord]
├── author_detector.py   # detect_author_collisions(records_a, records_b, cfg) -> AuthorDimResult
├── time_detector.py     # detect_time_collisions(records_a, records_b, cfg) -> TimeDimResult
├── machine_detector.py  # detect_machine_collisions(records_a, records_b, cfg) -> MachineDimResult
└── scorer.py            # combine_dimensions(dims: dict, cfg) -> (score, evidence)
```

**理由**:
- 与 C9 `structure_sim_impl/` 风格一致(9 vs 8 文件,规模相当)。
- 3 detector 分文件:3 子算法独立签名不同(author 聚类 / time 滑窗 / machine 元组),抽 `BaseDetector` 反耦合。
- `normalizer.py` 独立:4 字段(author/last_saved_by/company/template)多处调用,避免内联重复。
- `models.py` 用 `TypedDict`(不引 pydantic):仅内部类型契约,不做序列化。

**替代方案**:
- 3 detector 合并到 1 个 `detectors.py` → 单文件 400+ 行易糊;拒。
- 抽 `BaseDetector` 抽象类 → 过度抽象(3 detector 签名/返回不一致);拒。
- normalizer 内联每个 detector → 修改归一化规则需改 3 处;拒。

### D5 — `MetadataRecord` & `extractor`

**决策**:extractor 批量 query 项目一 bidder 的所有 DocumentMetadata,返 `list[MetadataRecord]`(一 doc 一条)。

```python
# models.py
class MetadataRecord(TypedDict):
    bid_document_id: int
    bidder_id: int
    doc_name: str                 # BidDocument.file_name,evidence 给前端
    author_norm: str | None       # nfkc_casefold_strip(author)
    last_saved_by_norm: str | None
    company_norm: str | None
    template_norm: str | None
    doc_created_at: datetime | None
    doc_modified_at: datetime | None
    app_name: str | None          # 原值(app_name/app_version 已规范化)
    app_version: str | None
    # 归一化后的原值(给 evidence 展示原文用)
    author_raw: str | None
    template_raw: str | None
```

```python
# extractor.py
async def extract_bidder_metadata(
    session: AsyncSession, bidder_id: int
) -> list[MetadataRecord]:
    stmt = (
        select(BidDocument, DocumentMetadata)
        .join(DocumentMetadata, DocumentMetadata.bid_document_id == BidDocument.id)
        .where(BidDocument.bidder_id == bidder_id)
    )
    rows = (await session.execute(stmt)).all()
    out: list[MetadataRecord] = []
    for bid_doc, meta in rows:
        out.append({
            "bid_document_id": bid_doc.id,
            "bidder_id": bidder_id,
            "doc_name": bid_doc.file_name or "",
            "author_norm": _norm(meta.author),
            "last_saved_by_norm": _norm(meta.last_saved_by),
            "company_norm": _norm(meta.company),
            "template_norm": _norm(meta.template),
            "doc_created_at": meta.doc_created_at,
            "doc_modified_at": meta.doc_modified_at,
            "app_name": _norm(meta.app_name),
            "app_version": _norm(meta.app_version),
            "author_raw": meta.author,
            "template_raw": meta.template,
        })
    return out
```

**`_norm(s)`**:`None` → `None`;`""` → `None`(空串当缺失);其余:`unicodedata.normalize("NFKC", s).casefold().strip()`,再判若空串再返 `None`。

**理由**:
- 一次性把文档级元数据拉到内存,3 detector 各自消费,避免每个子检测重复 query。
- evidence 需要原值 display(用户看到的是"张三"不是"张三"),保 `author_raw` / `template_raw`。
- 时间字段不归一化(已是 datetime 类型)。

**pair 型 Agent 的 extractor 调用时机**:每个 Agent `run()` 内独立调用(bidder_a + bidder_b 两次),不在 3 Agent 间共享 cache——3 Agent 可能在 thread pool 内并发,共享 cache 要加锁反而复杂;每次 query 开销小可接受。

### D6 — author_detector 算法

**决策**:对 `author_norm` / `last_saved_by_norm` / `company_norm` 三字段,在 bidder_a 和 bidder_b 的 doc 集合间检查**跨投标人精确碰撞**。

```python
# author_detector.py
class AuthorDimResult(TypedDict):
    score: float | None          # 0~1 或 None (字段全缺失)
    reason: str | None           # score=None 时的原因
    sub_scores: dict[str, float]  # {author: 0.7, last_saved_by: 0.0, company: 1.0}
    hits: list[ClusterHit]        # 命中的具体字段+值

def detect_author_collisions(
    records_a: list[MetadataRecord],
    records_b: list[MetadataRecord],
    cfg: AuthorConfig,
) -> AuthorDimResult:
    sub_scores: dict[str, float] = {}
    hits: list[ClusterHit] = []
    all_missing = True

    for field_name, weight in cfg.subdim_weights.items():
        # field_name in {"author", "last_saved_by", "company"}
        vals_a = {r[f"{field_name}_norm"] for r in records_a if r[f"{field_name}_norm"]}
        vals_b = {r[f"{field_name}_norm"] for r in records_b if r[f"{field_name}_norm"]}
        if not vals_a or not vals_b:
            continue  # 单字段单侧缺失 → 不进子分数(不算 0)
        all_missing = False
        intersect = vals_a & vals_b
        if intersect:
            # hit_strength = |intersect| / min(|A|, |B|)(Jaccard 变体,偏重"共同占比")
            strength = len(intersect) / min(len(vals_a), len(vals_b))
            sub_scores[field_name] = strength
            # evidence:每个共同值一条 hit
            for val in intersect:
                # 取原值给前端展示
                docs_a = [r for r in records_a if r[f"{field_name}_norm"] == val]
                docs_b = [r for r in records_b if r[f"{field_name}_norm"] == val]
                hits.append({
                    "field": field_name,
                    "value": docs_a[0][f"{field_name}_raw"] if field_name in ("author", "last_saved_by") else docs_a[0][f"{field_name}_raw"] if field_name == "company" else val,
                    "normalized": val,
                    "doc_ids_a": [d["bid_document_id"] for d in docs_a],
                    "doc_ids_b": [d["bid_document_id"] for d in docs_b],
                })
        else:
            sub_scores[field_name] = 0.0

    if all_missing:
        return {
            "score": None,
            "reason": "author/last_saved_by/company 三字段均缺失",
            "sub_scores": {},
            "hits": [],
        }
    # 参与子字段的原始权重重归一化
    participating = {k: cfg.subdim_weights[k] for k in sub_scores}
    total_w = sum(participating.values())
    score = sum(sub_scores[k] * participating[k] for k in sub_scores) / total_w
    return {
        "score": score,
        "reason": None,
        "sub_scores": sub_scores,
        "hits": hits[:cfg.max_hits_per_agent],   # 限流,避免 evidence 巨大
    }
```

**hit_strength 公式 `|∩| / min(|A|, |B|)`**:
- Jaccard `|∩| / |∪|` 对"一方 5 个 author 另一方 1 个相同 author"会得 `1/5=0.2`,信号偏弱。
- `min` 版本:两侧只要有一侧的值全部命中,即得 1.0(例如一方 3 个 author 都是"张三",另一方 1 个也是"张三",min=1,strength=1.0)。更贴合"围标信号"语义。
- 单 author 跨 bidder 出现即"铁证",`min=1` 时 strength=1.0 自然触发 is_ironclad。

**单字段子权重(`METADATA_AUTHOR_SUBDIM_WEIGHTS`)**:默认 `author=0.5, last_saved_by=0.3, company=0.2`。理由:
- `author` 最强信号(创建者),权重最高。
- `last_saved_by` 次之(最后编辑人,可能是转手传递)。
- `company` 可能是默认填的"某公司"或空,权重最低。

**替代方案**:
- 纯 Jaccard → 信号弱(上面分析),拒。
- 直接 `score = 1 if len(intersect) >= 1 else 0` → 二值化丢失强度信息,拒。
- 引入 Levenshtein 部分匹配 → Q3 决策拒。

### D7 — time_detector 算法

**决策**:两子信号:
1. **`doc_modified_at` 5 分钟滑窗聚集**:把 bidder_a 和 bidder_b 的所有 `doc_modified_at` 汇总排序,任何一个连续 2+ doc 时间差 ≤ `window_min` 分钟 **且跨投标人**(即窗口内两边各有至少 1 个 doc)→ 命中。
2. **`doc_created_at` 跨文档精确相等**:两侧存在 `doc_created_at` 相等的文档对(秒级精确)→ 命中。

```python
# time_detector.py
class TimeDimResult(TypedDict):
    score: float | None
    reason: str | None
    sub_scores: dict[str, float]
    hits: list[TimeCluster]

def detect_time_collisions(
    records_a: list[MetadataRecord],
    records_b: list[MetadataRecord],
    cfg: TimeConfig,
) -> TimeDimResult:
    # sub 1: modified_at 5 分钟滑窗
    mods_a = [(r["doc_modified_at"], r["bid_document_id"], "a") for r in records_a if r["doc_modified_at"]]
    mods_b = [(r["doc_modified_at"], r["bid_document_id"], "b") for r in records_b if r["doc_modified_at"]]
    modified_score = 0.0
    modified_clusters: list[TimeCluster] = []
    if mods_a and mods_b:
        all_mods = sorted(mods_a + mods_b, key=lambda x: x[0])
        window = timedelta(minutes=cfg.window_min)
        # 两指针扫描,找连续 ≤ window 且跨 side 的簇
        i = 0
        while i < len(all_mods):
            cluster = [all_mods[i]]
            j = i + 1
            while j < len(all_mods) and all_mods[j][0] - all_mods[i][0] <= window:
                cluster.append(all_mods[j])
                j += 1
            sides = {c[2] for c in cluster}
            if len(cluster) >= 2 and sides == {"a", "b"}:
                modified_clusters.append({
                    "dimension": "modified_at_cluster",
                    "window_min": cfg.window_min,
                    "doc_ids_a": [c[1] for c in cluster if c[2] == "a"],
                    "doc_ids_b": [c[1] for c in cluster if c[2] == "b"],
                    "times": [c[0].isoformat() for c in cluster],
                })
            i = j if j > i + 1 else i + 1
        if modified_clusters:
            # hit_strength: 命中文档占比(总)
            hit_doc_count = sum(len(c["doc_ids_a"]) + len(c["doc_ids_b"]) for c in modified_clusters)
            total_doc_count = len(mods_a) + len(mods_b)
            modified_score = min(1.0, hit_doc_count / max(1, total_doc_count))

    # sub 2: created_at 精确相等
    created_a_map: dict[datetime, list[int]] = defaultdict(list)
    for r in records_a:
        if r["doc_created_at"]:
            created_a_map[r["doc_created_at"]].append(r["bid_document_id"])
    created_b_map: dict[datetime, list[int]] = defaultdict(list)
    for r in records_b:
        if r["doc_created_at"]:
            created_b_map[r["doc_created_at"]].append(r["bid_document_id"])
    created_score = 0.0
    created_clusters: list[TimeCluster] = []
    common_times = set(created_a_map.keys()) & set(created_b_map.keys())
    if common_times:
        for t in common_times:
            created_clusters.append({
                "dimension": "created_at_match",
                "doc_ids_a": created_a_map[t],
                "doc_ids_b": created_b_map[t],
                "times": [t.isoformat()],
            })
        # hit_strength: 命中 common times 占比
        common_count = sum(len(created_a_map[t]) + len(created_b_map[t]) for t in common_times)
        total_count = sum(len(v) for v in created_a_map.values()) + sum(len(v) for v in created_b_map.values())
        created_score = min(1.0, common_count / max(1, total_count))

    # 维度级 skip 判定
    modified_available = bool(mods_a and mods_b)
    created_available = bool(created_a_map and created_b_map)
    if not modified_available and not created_available:
        return {
            "score": None,
            "reason": "doc_modified_at / doc_created_at 字段全缺失",
            "sub_scores": {},
            "hits": [],
        }

    sub_scores = {}
    if modified_available:
        sub_scores["modified_at_cluster"] = modified_score
    if created_available:
        sub_scores["created_at_match"] = created_score
    # 两子信号默认等权(`METADATA_TIME_SUBDIM_WEIGHTS` 可覆盖,默认 "0.7,0.3")
    sub_w = {
        "modified_at_cluster": cfg.modified_weight,
        "created_at_match": cfg.created_weight,
    }
    participating = {k: sub_w[k] for k in sub_scores}
    total_w = sum(participating.values())
    score = sum(sub_scores[k] * participating[k] for k in sub_scores) / total_w

    return {
        "score": score,
        "reason": None,
        "sub_scores": sub_scores,
        "hits": (modified_clusters + created_clusters)[:cfg.max_hits_per_agent],
    }
```

**理由**:
- 滑窗用双指针 O(n log n)(排序 + 线性扫描),n 通常 < 30,可忽略。
- **跨 side 约束**(`sides == {"a", "b"}`):同一 bidder 内部时间聚集不算围标,只有跨投标人的聚集才是证据。
- `modified_at` 5 min 窗 + `created_at` 精确相等:modified 是编辑时间(围标方批量生成),created 是创建时间(完全一致 → 可能同一模板同一时刻 init);两信号独立触发。
- 时区统一 UTC(C5 `DateTime(timezone=True)` 已保证),跨时区比对无偏差。

**替代方案**:
- `modified_at` 秒级精确相等 → 太严,Word 保存/复制粘贴时间戳偏几秒就漏,拒。
- `created_at` 按 5 min 窗 → Office 文档 create 时间在初始模板时就固定,不会被围标方精准再复刻;精确相等更直接。拒窗口。

### D8 — machine_detector 算法

**决策**:`(app_name, app_version, template)` 三字段**元组**精确碰撞。

```python
# machine_detector.py
class MachineDimResult(TypedDict):
    score: float | None
    reason: str | None
    hits: list[ClusterHit]

def detect_machine_collisions(
    records_a: list[MetadataRecord],
    records_b: list[MetadataRecord],
    cfg: MachineConfig,
) -> MachineDimResult:
    def _key(r: MetadataRecord) -> tuple[str, str, str] | None:
        if not r["app_name"] and not r["app_version"] and not r["template_norm"]:
            return None
        if not r["app_name"] or not r["app_version"] or not r["template_norm"]:
            return None  # 三字段任一缺失 → 该 doc 不参与元组匹配
        return (r["app_name"], r["app_version"], r["template_norm"])

    tuples_a: dict[tuple, list[int]] = defaultdict(list)
    tuples_b: dict[tuple, list[int]] = defaultdict(list)
    for r in records_a:
        k = _key(r)
        if k is not None:
            tuples_a[k].append(r["bid_document_id"])
    for r in records_b:
        k = _key(r)
        if k is not None:
            tuples_b[k].append(r["bid_document_id"])

    if not tuples_a or not tuples_b:
        return {
            "score": None,
            "reason": "app_name/app_version/template 三字段构成的完整元组在至少一侧缺失",
            "hits": [],
        }

    common = set(tuples_a.keys()) & set(tuples_b.keys())
    if not common:
        return {"score": 0.0, "reason": None, "hits": []}

    hits: list[ClusterHit] = []
    for tup in common:
        hits.append({
            "field": "machine_fingerprint",
            "value": {
                "app_name": tup[0],
                "app_version": tup[1],
                "template": tup[2],
            },
            "doc_ids_a": tuples_a[tup],
            "doc_ids_b": tuples_b[tup],
        })

    # hit_strength:命中元组覆盖的 doc 占比
    hit_doc_count = sum(len(tuples_a[t]) + len(tuples_b[t]) for t in common)
    total_doc_count = sum(len(v) for v in tuples_a.values()) + sum(len(v) for v in tuples_b.values())
    score = min(1.0, hit_doc_count / max(1, total_doc_count))

    return {
        "score": score,
        "reason": None,
        "hits": hits[:cfg.max_hits_per_agent],
    }
```

**理由**:
- 三字段 **AND**:`(Word, 16.0000, Normal.dotm)` 三字段一致才算碰撞;`(Word, 16.0000)` 单碰撞信号弱(同版本 Office 用户极多);加 `template` 区分"自定义模板"vs"默认模板"。
- 三字段任一缺失即不参与:避免"一方三字段全空另一方全空"误命中空元组。
- evidence 结构化存 `{app_name, app_version, template}`,前端渲染可单独高亮。

**替代方案**:
- 拆成 3 子维度(app_name/app_version/template)各自计算 → 单独碰撞信号弱,易误报;三字段 AND 信号强,拒拆。
- 只用 `app_version + template` 不带 `app_name` → `app_name` 不同(Word vs Kingsoft)肯定不是同机,`app_name` 作为"同平台"必要条件,保留。

### D9 — scorer 合成规则

**决策**:Agent 级 score = 对应维度的 `hit_strength × 100`;3 个 metadata Agent 各自只有 1 个维度,scorer 直接返 `dim_result.score × 100`。

```python
# scorer.py
def combine_dimension(dim_result: dict, cfg: SubDimConfig) -> tuple[float, dict]:
    """单维度 Agent 的合成:直接拿 dim_result.score × 100 作为 Agent score。"""
    if dim_result["score"] is None:
        # 维度 skip → Agent 级 skip (run 内部判 cfg.enabled 后再决定是否走哨兵)
        return (0.0, {
            "score": None,
            "reason": dim_result["reason"],
            "participating_fields": [],
            "hits": [],
            "sub_scores": dim_result.get("sub_scores", {}),
        })
    agent_score = round(dim_result["score"] * 100, 2)
    participating = list(dim_result.get("sub_scores", {}).keys())
    if not participating and "hits" in dim_result:
        participating = [h["field"] for h in dim_result["hits"]]
    return (agent_score, {
        "score": dim_result["score"],
        "reason": None,
        "participating_fields": participating,
        "hits": dim_result["hits"],
        "sub_scores": dim_result.get("sub_scores", {}),
    })
```

**3 Agent 间的合并展示**:judge 层(C6 既有)对 3 个 `metadata_*` PairComparison 行不做特殊聚合(每行独立 evidence),C14/C17 再做 UI 合并。C10 不触 judge。

**子检测 flag**:在 Agent `run()` 内判 `cfg.enabled`,disabled → 直接返 `AgentRunResult(score=0.0, summary="子检测已禁用")`,PairComparison 正常写一行 score=0.0 + `evidence.enabled=false`(区别于真正 skip 的"participating_fields=[]")。

**is_ironclad**:Agent score ≥ `METADATA_IRONCLAD_THRESHOLD`(默认 85)→ True;此阈值远高于 judge.py 既有 85 阈值,保守。

### D10 — 3 Agent `run()` 骨架(统一模板)

**决策**:3 Agent 的 `run()` 结构完全一致,只选不同 detector 和 config:

```python
# metadata_author.py(示例,time/machine 类似)
from app.services.detect.agents.metadata_impl.config import load_author_config
from app.services.detect.agents.metadata_impl.extractor import extract_bidder_metadata
from app.services.detect.agents.metadata_impl.author_detector import detect_author_collisions
from app.services.detect.agents.metadata_impl.scorer import combine_dimension

@register_agent("metadata_author", "pair", preflight)
async def run(ctx: AgentContext) -> AgentRunResult:
    cfg = load_author_config()
    if not cfg.enabled:
        await _write_pair_comparison(
            ctx, score=0.0, evidence={"algorithm": "metadata_author_v1", "enabled": False}
        )
        return AgentRunResult(score=0.0, summary="metadata_author 子检测已禁用")

    records_a = await extract_bidder_metadata(ctx.session, ctx.bidder_a.id)
    records_b = await extract_bidder_metadata(ctx.session, ctx.bidder_b.id)

    try:
        dim_result = detect_author_collisions(records_a, records_b, cfg)
    except Exception as e:
        # execution-plan §3 C10 兜底:提取器失败 → 整 Agent 标"失败"
        logger.exception("metadata_author 检测异常")
        await _write_pair_comparison(
            ctx, score=0.0, evidence={"algorithm": "metadata_author_v1", "error": str(e)[:200]}
        )
        return AgentRunResult(score=0.0, summary=f"metadata_author 执行失败:{type(e).__name__}")

    agent_score, evidence = combine_dimension(dim_result, cfg)
    evidence["algorithm"] = "metadata_author_v1"
    evidence["doc_ids_a"] = [r["bid_document_id"] for r in records_a]
    evidence["doc_ids_b"] = [r["bid_document_id"] for r in records_b]

    # dim_result.score = None → Agent 级 skip,但 PairComparison 仍写一行 score=0.0
    if dim_result["score"] is None:
        summary = f"元数据缺失:{dim_result['reason']}"
        await _write_pair_comparison(ctx, score=0.0, evidence=evidence)
        return AgentRunResult(score=0.0, summary=summary)

    is_ironclad = agent_score >= cfg.ironclad_threshold
    summary = _build_summary_author(dim_result, is_ironclad)
    await _write_pair_comparison(
        ctx, score=agent_score, evidence=evidence, is_ironclad=is_ironclad
    )
    return AgentRunResult(score=agent_score, summary=summary, evidence_json=evidence)
```

**`_write_pair_comparison` helper**:抽到 `agents/metadata_impl/__init__.py` 或 `_dummy.py`(后者 C6 已有 dummy 写入逻辑,扩展一个非 dummy 版)。决定放到 `metadata_impl/__init__.py::write_pair_comparison_row(ctx, *, score, evidence, is_ironclad=False)`,供 3 Agent 共享。

**理由**:
- 3 Agent 的 run 结构一致 → extractor/scorer 共享 + detector 独立是自然拆分。
- flag disabled 仍写 PairComparison(score=0.0)而非完全不写:保 "3 Agent 都在 analysis_reports 里可见,前端能显示'已禁用'标识"。执行计划 Scenario 5 的验证语义。
- 异常路径单独 catch + evidence.error:运维可 query `WHERE evidence_json @> '{"error": ...}'` 定位失败。

### D11 — config.py 与 env 变量

**决策**:`METADATA_` 前缀统一,默认值做在代码里,env 覆盖动态读取。

```python
# config.py
@dataclass(frozen=True)
class AuthorConfig:
    enabled: bool = True
    subdim_weights: dict[str, float] = field(default_factory=lambda: {"author": 0.5, "last_saved_by": 0.3, "company": 0.2})
    ironclad_threshold: float = 85.0
    max_hits_per_agent: int = 50

@dataclass(frozen=True)
class TimeConfig:
    enabled: bool = True
    window_min: int = 5
    modified_weight: float = 0.7
    created_weight: float = 0.3
    ironclad_threshold: float = 85.0
    max_hits_per_agent: int = 50

@dataclass(frozen=True)
class MachineConfig:
    enabled: bool = True
    ironclad_threshold: float = 85.0
    max_hits_per_agent: int = 50

def load_author_config() -> AuthorConfig:
    return AuthorConfig(
        enabled=_env_bool("METADATA_AUTHOR_ENABLED", True),
        subdim_weights=_env_weights(
            "METADATA_AUTHOR_SUBDIM_WEIGHTS",
            {"author": 0.5, "last_saved_by": 0.3, "company": 0.2},
        ),
        ironclad_threshold=float(os.getenv("METADATA_IRONCLAD_THRESHOLD", "85")),
    )

# 类似 load_time_config, load_machine_config
```

**env 清单**:
- `METADATA_AUTHOR_ENABLED` / `METADATA_TIME_ENABLED` / `METADATA_MACHINE_ENABLED`(默认 `true`)
- `METADATA_TIME_CLUSTER_WINDOW_MIN`(默认 `5`)
- `METADATA_AUTHOR_SUBDIM_WEIGHTS`(默认 `"0.5,0.3,0.2"`,顺序 author,last_saved_by,company)
- `METADATA_TIME_SUBDIM_WEIGHTS`(默认 `"0.7,0.3"`,顺序 modified,created)
- `METADATA_IRONCLAD_THRESHOLD`(默认 `85`,Agent 级 ≥ 阈值 → is_ironclad)
- `METADATA_MAX_HITS_PER_AGENT`(默认 `50`,evidence hits 截断)

**`_env_bool` / `_env_weights` 解析容错**:解析失败 → fallback 到默认值 + `logger.warning`(对齐 C9 `STRUCTURE_SIM_WEIGHTS` 风格)。

### D12 — evidence_json 统一结构

**决策**:3 Agent 的 `evidence_json` 核心字段对齐,便于前端 C17 合并渲染。

```jsonc
// metadata_author evidence_json 示例
{
  "algorithm": "metadata_author_v1",
  "enabled": true,
  "score": 0.67,                       // 0~1,归一化前
  "reason": null,
  "participating_fields": ["author", "company"],
  "sub_scores": {"author": 1.0, "company": 0.5, "last_saved_by": 0.0},
  "hits": [
    {
      "field": "author",
      "value": "张三",                   // 原值
      "normalized": "张三",
      "doc_ids_a": [12],
      "doc_ids_b": [17]
    }
  ],
  "doc_ids_a": [12, 13, 14],            // bidder_a 参与检测的所有 doc
  "doc_ids_b": [16, 17, 18]
}

// metadata_machine evidence_json 示例
{
  "algorithm": "metadata_machine_v1",
  "enabled": true,
  "score": 1.0,
  "reason": null,
  "participating_fields": ["machine_fingerprint"],
  "hits": [
    {
      "field": "machine_fingerprint",
      "value": {
        "app_name": "microsoft office word",
        "app_version": "16.0000",
        "template": "normal.dotm"
      },
      "doc_ids_a": [12],
      "doc_ids_b": [17]
    }
  ],
  "doc_ids_a": [12, 13, 14],
  "doc_ids_b": [16, 17, 18]
}
```

**`participating_fields=[]`**:在元数据全缺失或 flag 禁用时为空,前端据此识别"Agent 级 skip / 已禁用"。

### D13 — 子检测 flag 单独关闭(Scenario 5)

**决策**:env `METADATA_<DIM>_ENABLED=false` → 对应 Agent `run()` 判 `cfg.enabled=False` 后直接返 `score=0.0, enabled=false` 的 evidence,不调 extractor/detector。

**L1 测试**:`monkeypatch.setenv("METADATA_AUTHOR_ENABLED", "false")` → 调 `metadata_author.run(ctx)` → 返回 `score=0.0, summary="metadata_author 子检测已禁用"`,PairComparison 写入的 evidence.enabled=False。

**与 preflight 的关系**:preflight 不读 `cfg.enabled`(preflight 是"数据是否足够"的通用判断,flag 是"业务是否启用"的独立开关);两者独立。flag 关闭但 preflight=ok → run 仍被调(满足 Scenario 5 要求:"可通过 flag 单独关闭"意味着 flag 生效在 run 层,而不是 preflight 层 skip,避免"数据够但配置上不想要"被误标成"skip 无数据")。

### D14 — `bidder_has_metadata` 扩展 machine 分支

**决策**:`_preflight_helpers.bidder_has_metadata` 的 `machine` 分支扩:

```python
elif require_field == "machine":
    stmt = stmt.where(
        (DocumentMetadata.app_version.is_not(None))
        | (DocumentMetadata.app_name.is_not(None))
        | (DocumentMetadata.template.is_not(None))  # C10 新增
    )
```

**理由**:preflight 仍用 OR 宽松判定,新增 template 后 OR 范围扩大,更不易拦截;run 内部精确元组 AND 判定。

## Risks / Trade-offs

| Risk | Mitigation |
|---|---|
| 历史文档 `template` 字段无值 → machine 维度多数 NULL → 多数 pair machine 维度 skip | 回填脚本 `backfill_document_metadata_template.py` 覆盖;生产部署前 **必须** 跑一次回填(handoff/follow-up 标注) |
| `template` 字段 Office 版本差异 → 同一模板跨系统路径不同(`C:\...\Normal.dotm` vs `/Users/.../Normal.dotm`)| NFKC+casefold+strip 只规一 Unicode/大小写;路径不同的同模板不等于 hit(可接受,Office 实际"默认模板"都是 `Normal.dotm` 无路径)。extreme 场景留 follow-up |
| author 变体("张三" vs "张三 (admin)")导致漏报 | Q3 决策锁定纯精确。follow-up 规则化合并可加;实战漏报多时开 C17+ |
| `modified_at` 时区处理错误 → 跨时区误命中 / 漏命中 | C5 `DateTime(timezone=True)` 已保证 UTC;单测覆盖 UTC vs local 转换 |
| extractor 每次 Agent run 重复 query(3 Agent × 2 bidder × 1 query = 6 次) | 每次 query SELECT 1 bidder 的 DocumentMetadata,O(doc_count) 轻;3 Agent 并行 × 2 bidder = 6 轻 query 可接受;加 cache 反引入锁复杂度 |
| 单 bidder 文档数极大(200+ docs)→ `combinatorial` 聚类爆炸 | `METADATA_MAX_BIDDERS_PER_PROJECT=200` 项目级保护阈值(project 下 bidder 数超阈值直接在 engine 层拦截,但本 change 不改 engine,留 follow-up)。单 bidder 内 doc 数通常 < 20,O(n) 扫描无压力 |
| alembic 0007 在生产 PG 运行时加列锁表 | `add_column` 可空无默认值 → `ALTER TABLE ADD COLUMN` 在 PG 11+ 无需重写元组,快速完成;不加 NOT NULL 避免全表回填锁 |
| 回填脚本并发跑(运维误双开)→ 重复 query 但幂等 SQL 过滤 `template IS NULL` | 单 doc 独立 session + commit;并发两脚本最差 race 成"同一 doc 被两脚本都挑中但第二个 commit 时 template 已非 NULL" → 第二个不会再改值(幂等)|
| 子检测 flag 和 preflight 的语义区别被测试忽略 | L1 专测 "flag=false + 数据足够 → run 返 enabled=false" vs "flag=true + 数据不足 → run 返 score=0.0 + participating_fields=[]" |
| machine_detector 单 doc 三字段齐全但实际是 Office 默认值(`Word, 16.0000, Normal.dotm`)→ 合法投标人也误命中 | `Normal.dotm` 是 Office 默认模板,实战中同版本同默认模板的投标人确实可能非围标——**接受误命中**,`is_ironclad` 判定用 score ≥ 85(AND 三字段全一致 + 多文档全命中才达 85);保守不改算法,留 C14 LLM 综合研判降噪 |

## Migration Plan

### 部署步骤

1. **备份 DB**:`pg_dump -Fc documentcheck > dump_pre_c10.dump`
2. **代码发布**:部署 C10 change(包含 alembic 0007)
3. **运行迁移**:`alembic upgrade head` → 加 `document_metadata.template` 列
4. **回填(关键)**:运维在生产机手工跑
   ```bash
   cd backend
   # 先 dry-run 看数量
   uv run python scripts/backfill_document_metadata_template.py --dry-run
   # 确认 OK 后实跑
   uv run python scripts/backfill_document_metadata_template.py
   ```
5. **验证**:`SELECT COUNT(*) FROM document_metadata WHERE template IS NOT NULL` 应等于未损坏 docx/xlsx 数量;运维抽查一条
6. **启动检测验证**:对一个已有检测历史的项目再跑一次"重检测",确认 3 个 `metadata_*` Agent 走真实路径(evidence.algorithm=`metadata_*_v1`)

### 回滚策略

- 单 change 回滚:回退代码 + `alembic downgrade -1` 删除 template 列
- 回滚不影响已产生的 PairComparison(evidence_json 里的 `metadata_*_v1` 数据保留,前端兼容显示)
- 紧急降级:`METADATA_AUTHOR_ENABLED=false` `METADATA_TIME_ENABLED=false` `METADATA_MACHINE_ENABLED=false` 三 flag 全关,3 Agent 全退化到"已禁用"状态,不影响检测流程

## Open Questions

无。所有产品级决策已在 propose 阶段锁定(Q1 合并 / Q2 扩 C5 持久化 + 回填 / Q3 纯精确匹配)。
