## Context

### 现状(C7 归档后)

- `AGENT_REGISTRY["section_similarity"]` 已注册(C6),preflight = "双方在 `bidders_share_any_role` 上有同角色文档",run 目前走 `dummy_pair_run`
- **C7 `text_sim_impl/` 子包就绪**(2026-04-15 归档):`tfidf.compute_pair_similarity` / `llm_judge.call_llm_judge` / `aggregator.aggregate_pair_score + compute_is_ironclad + build_evidence_json` / `stopwords.STOPWORDS` / `models.ParaPair` / `segmenter.load_paragraphs_for_roles + choose_shared_role + ROLE_PRIORITY` 全部可 import 复用
- `PairComparison.dimension='section_similarity'` 已被 C6 dummy 写过(随机分),C8 真实实现写同一 dimension
- `get_cpu_executor()` C7 已消费,C8 是第二个消费者 — worker pool 复用(不新建 executor)
- `DocumentText` 按 `paragraph_index` 有顺序,但无 `style/heading_level` 字段 → 切章只能靠文本正则识别标题行
- `BidDocument.file_role` 用英文标识符(technical / construction / bid_letter / ...),C7 的 `ROLE_PRIORITY` 直接复用

### 约束

- **C6 contract 锁定 + C7 `text_sim_impl/` 只读**:AGENT_REGISTRY key / preflight 签名 / AgentContext / AgentRunResult 全零改动;C7 代码一字不改(import only)
- **零新增第三方依赖**:纯正则 + 复用 C7 算法模块
- **score ∈ [0, 100]**:DB `Numeric(6, 2)`
- **LLM 5min 硬超时 + 重试 1 次**:继承 C7 规则;章节对齐后只发 top-N 章节对给 LLM,不为每对章节各发一次(token 控制)
- **A1 独立降级(用户决策)**:章节切分失败 → C8 自己跑整文档 TF-IDF(复用 C7 tfidf),写 section_similarity 维度;C7 text_similarity 独立并行,不互相依赖
- **单 pair 最多 30 章节对送 LLM**:同 C7 MAX_PAIRS_TO_LLM,防 token 爆

### 干系方

- **审查员**:报告页能看到 "技术方案 第3章 全段抄袭" 这种章节级证据锚点
- **C9~C13 实施者**:C8 建立的"复用 C7 模块 + 新增粒度层"模式是 C9 section/structure 的参照
- **C14 综合研判**:section_similarity + text_similarity 两行 PairComparison 是独立维度,C14 LLM 自己判断是否降重

## Goals / Non-Goals

### Goals

1. **章节级相似度计算**:切章 → 对齐 → 对齐章节对内部段落相似度 → 汇总章节级 score → 累积 pair 级 score
2. **降级路径完备**(A1 独立降级):章节切分失败(章节数 < MIN_CHAPTERS 或任一侧识别为 0)→ 整文档 TF-IDF 兜底,evidence.degraded_to_doc_level=true
3. **复用 C7 算法模块**:TF-IDF / LLM Judge / Aggregator 零改 C7 代码,只 import
4. **4 验证场景全绿**(execution-plan §3 C8):章节雷同命中 / 章节错位对齐 / 识别失败降级 / 极少章节 skip
5. **LLM 成本可控**:章节对齐后 top-N 章节对(按 title_sim × chapter_body_sim 粗排)送 LLM,上限与 C7 共享配置逻辑
6. **preflight 延用 C6 "同角色文档存在"**,再追加章节数检查(章节切分后 < MIN_CHAPTERS → skip "章节过少")

### Non-Goals

- **更换章节识别算法为 LLM / 深度学习**:纯正则足够(投标文档规整 + 有 A1 兜底);C17 或更后可升级
- **跨投标人的章节归一化(同义词映射)**:"技术方案"↔"技术措施"完全 by title TF-IDF 对齐,不建词典
- **章节内子章节递归**:仅一级切章,子章节作为段落处理
- **C14 综合研判的去重优化**:留 C14
- **前端证据渲染的章节维度展开**:C17 UI 层做

## Decisions

### D1 — 章节识别:纯正则 + 5 种模式组合

**决策**:`chapter_parser.extract_chapters(paragraphs: list[str]) -> list[ChapterBlock]`

```python
# 5 种模式(按优先级匹配,命中即确定该段是"章节标题")
PATTERNS = [
    # 1. 第 X 章
    re.compile(r"^\s*第\s*[一二三四五六七八九十百千\d]+\s*章\s*"),
    # 2. 第 X 节
    re.compile(r"^\s*第\s*[一二三四五六七八九十百千\d]+\s*节\s*"),
    # 3. X.Y 数字序号(如 "3.1 技术措施")
    re.compile(r"^\s*\d+(\.\d+)*\s+\S"),
    # 4. 中文数字 + 顿号(如 "一、技术方案")
    re.compile(r"^\s*[一二三四五六七八九十]+\s*[、\.]\s*\S"),
    # 5. 纯数字 + 顿号/空格(如 "1. 投标函" / "1 技术方案")
    re.compile(r"^\s*\d+\s*[、\.]?\s+\S"),
]

@dataclass
class ChapterBlock:
    idx: int           # 章节序号(0-based)
    title: str         # 章节标题原文(截 100 字)
    paragraphs: list[str]  # 章节内段落(不含标题行本身)
    total_chars: int   # 章节内字符总数
```

**切章流程**:
1. 遍历 paragraphs,每段判是否匹配任一 PATTERN
2. 命中 → 开启新 ChapterBlock,之前 buffer 的段落归入上一章节
3. 章节过短(`total_chars < SECTION_SIM_MIN_CHAPTER_CHARS=100`)→ 合并进前一章节(常见:孤立标题行后内容被下一次命中截断导致的碎章节)
4. 返 `list[ChapterBlock]`;若列表 < `SECTION_SIM_MIN_CHAPTERS=3` → 视为"章节切分失败",切到降级分支

**替代方案**:
- docx heading style 识别 → `DocumentText` 表无 heading_level 字段,C5 提取时未保留(不扩表 → 拒)
- LLM 切章 → 每 pair 2 次 LLM 调用成本翻倍,且有 A1 兜底,无必要
- 章节目录 toc 解析 → 许多投标文档无 toc 或 toc 标题与正文不一致,拒

### D2 — 章节对齐:title TF-IDF + 序号回退

**决策**:`aligner.align_chapters(chapters_a, chapters_b) -> list[ChapterPair]`

```python
@dataclass
class ChapterPair:
    a_idx: int
    b_idx: int
    title_sim: float   # 0~1
    aligned_by: Literal["title", "index"]  # title 对齐 / 序号回退
```

**对齐流程**:
1. 对所有 `(a_title, b_title)` 组合算 title-level TF-IDF cosine sim(复用 `text_sim_impl.tfidf.jieba_tokenizer`,但不发 LLM 判定)
2. 贪心匹配:按 sim 降序取 `(a_i, b_j)` 配对,每个章节只能配对一次;sim ≥ `SECTION_SIM_TITLE_ALIGN_THRESHOLD=0.40` 算对齐成功 `aligned_by='title'`
3. 未对齐成功的:按章节 `idx` 对齐序号(`a_i` 配 `b_i`),`aligned_by='index'`,`title_sim` 置当前两者 title sim(可能为 0)
4. 返回 pair 列表 = `min(|chapters_a|, |chapters_b|)`(多余章节丢弃,避免 N×M 爆炸)

**理由**:
- "技术方案" vs "技术措施" title sim ≥ 0.40 能对齐(jieba 分词后 "技术" 共享)
- 完全错位(如投标函 vs 商务部分)title sim < 0.40 走序号回退,保证每章节都有 pair
- 贪心匹配比匈牙利算法简单,sim 矩阵中等规模(10~50 章节)无性能问题

**替代方案**:
- 匈牙利算法最优匹配 → 收益微小(实际每侧章节数 < 30),增加复杂度,拒
- 只按序号对齐 → 处理不了章节错位,场景 2 不过,拒
- 只按 title 对齐不回退 → 有章节标题 TF-IDF 失败的场景(纯数字标题等),拒

### D3 — 章节级相似度计算(复用 C7)

**决策**:`scorer.score_chapter_pair(pair, ctx.llm_provider) -> ChapterScoreResult`

```python
@dataclass
class ChapterScoreResult:
    chapter_pair_idx: int
    a_idx: int
    b_idx: int
    a_title: str
    b_title: str
    title_sim: float
    chapter_score: float  # 0~100
    is_chapter_ironclad: bool
    plagiarism_count: int
    samples: list[dict]  # 前 5 条段落对证据

async def score_chapter_pair(pair, chapter_a, chapter_b, llm_provider, cfg) -> ChapterScoreResult:
    # 1. 复用 C7: compute_pair_similarity 算章节内段落对相似度
    para_pairs = await loop.run_in_executor(
        get_cpu_executor(),
        text_sim_impl.tfidf.compute_pair_similarity,
        chapter_a.paragraphs, chapter_b.paragraphs,
        cfg.para_threshold,  # 0.70(复用 C7 env TEXT_SIM_PAIR_SCORE_THRESHOLD)
        cfg.max_pairs,       # 按章节分摊:C7 的 30 除以对齐章节数,向上取整,min 3
    )
    # 2. 复用 C7 llm_judge(可能无 LLM 调用 if para_pairs=[])
    if para_pairs:
        judgments, ai_meta = await text_sim_impl.llm_judge.call_llm_judge(
            llm_provider, a_name, b_name, "section", para_pairs,
        )
    else:
        judgments, ai_meta = {}, {"overall": "", "confidence": "high"}
    # 3. 复用 C7 aggregator
    chapter_score = text_sim_impl.aggregator.aggregate_pair_score(para_pairs, judgments)
    is_chapter_ironclad = text_sim_impl.aggregator.compute_is_ironclad(judgments)
    return ChapterScoreResult(...)
```

**LLM token 控制**:
- 所有对齐章节的 para_pairs 合并后按 `title_sim × avg_para_sim` 粗排,仅前 `SECTION_SIM_MAX_PAIRS_TO_LLM=30` 个发 LLM(复用 C7 的 30 上限,不叠加)
- 发送时构造"带章节上下文"的 prompt:段落对附带 `chapter_a_title` / `chapter_b_title`,便于 LLM 判断模板性

**替代方案**:
- 每章节单独调 LLM → N 次调用,超时更难控制,拒
- 章节粒度 embedding → 加 sentence-transformers 依赖,拒(B 决策一致)

### D4 — pair 级 score 汇总

**决策**:
```python
def aggregate_pair_level(chapter_results: list[ChapterScoreResult]) -> tuple[float, bool]:
    if not chapter_results:
        return 0.0, False
    scores = [r.chapter_score for r in chapter_results]
    # 章节级取 max*0.6 + mean*0.4(权重略偏 mean,因章节多时某章高分可能仅模板)
    pair_score = max(scores) * 0.6 + (sum(scores) / len(scores)) * 0.4
    # is_ironclad:任一章节 is_chapter_ironclad → 整 pair 铁证(章节级证据足够集中)
    is_ironclad = any(r.is_chapter_ironclad for r in chapter_results)
    return round(min(100.0, max(0.0, pair_score)), 2), is_ironclad
```

**理由**:
- C7 用 max*0.7+mean*0.3,C8 章节粒度 max 更容易虚高(一个章节全模板化也 max 高),mean 权重上调到 0.4
- 铁证继承:章节级铁证 → pair 铁证(单章抄袭已足够严重)

### D5 — 降级路径(A1 独立降级落地)

**决策**:`fallback.run_doc_level_fallback(ctx, shared_roles) -> AgentRunResult`

触发条件(任一):
- 单侧切章结果 `< SECTION_SIM_MIN_CHAPTERS=3`(包括识别 0 章节)
- 双侧切章但总段落数 < 10(章节太碎)

降级行为:
- 直接调 C7 的 text_similarity 运行路径(**不是 import text_similarity.run,而是 import `text_sim_impl` 模块内各函数重新走一遍**,避免跨 Agent 耦合)
- dimension 仍写 `section_similarity`(**不是 text_similarity,两维度独立**)
- evidence:
  ```json
  {
    "algorithm": "tfidf_cosine_fallback_to_doc",
    "degraded_to_doc_level": true,
    "degrade_reason": "章节切分失败(chapters_a=0, chapters_b=2,< 3)",
    "aligned_count": 0,
    "chapter_pairs": [],
    ...C7 同款字段(doc_role / doc_id_a/b / threshold / pairs_total/plagiarism/template/generic / samples / ai_judgment)...
  }
  ```
- summary:"章节切分失败,已降级整文档粒度(chapters_a=0 chapters_b=2)"
- `AgentTask.status = 'succeeded'`(降级不是失败)

**LLM 降级的双重嵌套**:`fallback` 内部调 `text_sim_impl.llm_judge`,若 LLM 也失败 → evidence 兼具 `degraded=true` + `degraded_to_doc_level=true`,两者并存(summary 说明"章节切分失败 + AI 研判暂不可用")

### D6 — preflight 扩展

**决策**:preflight 扩"章节数"检查,但这步需要先切章 — 为避免在 preflight 阶段做完整切章(DB 查询 + 正则 × 多段),把章节数检查**下放到 run() 内部**,preflight 只做 C6 原约束 + 追加字数检查(复用 C7 `TEXT_SIM_MIN_DOC_CHARS=500` 作为"文档够不够切章"的下界,别加新 env)。

```python
async def preflight(ctx):
    # 1. C6 原约束:同角色文档存在
    shared = await segmenter.choose_shared_role(session, a.id, b.id)
    if not shared:
        return PreflightResult("skip", "缺少可对比文档")
    # 2. 文档总字数 ≥ MIN_DOC_CHARS(复用 C7 的 500)
    seg_a = await segmenter.load_paragraphs_for_roles(session, a.id, shared)
    seg_b = await segmenter.load_paragraphs_for_roles(session, b.id, shared)
    if seg_a.total_chars < 500 or seg_b.total_chars < 500:
        return PreflightResult("skip", "文档过短无法对比")
    # 3. 章节数检查在 run() 内做(切章后判)—— 切章失败走 D5 降级,不进 skip
    return PreflightResult("ok")
```

**理由**:preflight 再做一次切章等于 run() 做 2 次,浪费;skip 语义保留给"根本无法比"(无文档 / 过短),"章节太少"归降级不归 skip(降级仍产出 section_similarity.score,比 skip 更有信息量)

### D7 — evidence_json 结构(扩 C7 schema)

**决策**:
```json
{
  "algorithm": "tfidf_cosine_chapter_v1"  // 或 "tfidf_cosine_fallback_to_doc"(降级)
  "doc_role": "technical",
  "doc_id_a": 123, "doc_id_b": 456,
  "threshold": 0.70,
  // 章节级专属字段
  "chapters_a_count": 12, "chapters_b_count": 11,
  "aligned_count": 10,          // 对齐成功的章节对数(by title)
  "index_fallback_count": 1,    // 由序号回退对齐的章节对数
  "degraded_to_doc_level": false,
  "degrade_reason": null,
  // 章节级证据:每个对齐章节对的顶层信息
  "chapter_pairs": [
    {
      "a_idx": 3, "b_idx": 3,
      "a_title": "3 技术方案", "b_title": "3 技术措施",
      "title_sim": 0.52,
      "aligned_by": "title",
      "chapter_score": 78.5,
      "is_chapter_ironclad": true,
      "plagiarism_count": 5
    }
  ],
  // 兼容 C7 的字段(便于前端统一渲染)
  "pairs_total": 18,
  "pairs_plagiarism": 5,
  "pairs_template": 8,
  "pairs_generic": 5,
  "degraded": false,
  "ai_judgment": {"overall": "...", "confidence": "high"},
  "samples": [ ...C7 同款,前 10 条段落对... ]
}
```

`chapter_pairs` 上限 20 条(多了前端看不清);`samples` 保留 C7 的 10 条上限(跨所有章节)。

### D8 — 测试分层

- **L1**:
  - `test_chapter_parser.py`:5 种 PATTERN 分别命中 / 混合文档 / 无章节 / 过短章节合并
  - `test_aligner.py`:完美 title 对齐 / 部分 title + 部分 index 回退 / 全序号回退 / 单侧章节数多多余章节被丢
  - `test_scorer.py`:章节内无段落对 → chapter_score=0 / 多章节粗排截断 / 复用 C7 路径(断言调用了 C7 模块)
  - `test_fallback.py`:触发条件 × 2(章节数不足 / 段落过少)/ 降级后 evidence 字段齐全
  - `test_section_similarity_run.py`:preflight 正常 ok / run 主路径 / 降级路径 / LLM timeout 双降级
- **L2**:
  - `test_detect_section_similarity.py` 4 scenario 对齐 execution-plan §3 C8:
    1. 技术方案章节雷同 → section_similarity.score ≥ 60 + is_ironclad + chapter_pairs 含高分章节
    2. 章节错位(A 5 章节 / B 4 章节,技术方案在不同 idx)→ 对齐后仍命中,`aligned_by='title'`
    3. 识别失败(纯数字标题无法切)→ evidence.degraded_to_doc_level=true + score 走整文档
    4. 极少章节(B 只有 1 章节)→ 章节切分失败(触发 MIN_CHAPTERS=3 下界)→ 走降级;**不返回 skip**(A1 决策保留 section_similarity 行)
- **L3**:延续 C5/C6/C7 手工凭证,`e2e/artifacts/c8-2026-04-15/README.md` 占位 + 3 张截图计划

### D9 — jieba / ProcessPoolExecutor 复用

- jieba warmup:C7 已处理,C8 第一次 run 时若 C7 已跑过则 no-op;否则 C8 内 `text_sim_impl.tfidf.compute_pair_similarity` 内部的 `_ensure_jieba_initialized` 兜底
- ProcessPoolExecutor:`get_cpu_executor()` lazy 单例,C7 和 C8 共享;章节对齐的 title TF-IDF 也走 executor(title 级虽数据量小,但代码保持一致,便于后续 C9/C10 复用同模式)

### D10 — 环境变量

| env | 默认 | 作用 |
|---|---|---|
| `SECTION_SIM_MIN_CHAPTERS` | 3 | 任一侧章节数 < 此值 → 触发降级(整文档兜底) |
| `SECTION_SIM_MIN_CHAPTER_CHARS` | 100 | 章节内文本 < 此值 → 合并进前一章节 |
| `SECTION_SIM_TITLE_ALIGN_THRESHOLD` | 0.40 | title TF-IDF sim ≥ 此值算对齐成功(by title);否则走 index 回退 |

复用 C7 既有 env:`TEXT_SIM_MIN_DOC_CHARS`(preflight 字数下限)/`TEXT_SIM_PAIR_SCORE_THRESHOLD`(段落对 sim 阈值)/`TEXT_SIM_MAX_PAIRS_TO_LLM`(LLM 上限)— C8 不重复加同义 env,通过 import `text_sim_impl.config` 读取

## Risks / Trade-offs

- **[R-1] 正则切章漏命中**:投标文档模板多样,5 种 PATTERN 覆盖不全可能切出奇怪章节 → mitigation:D5 降级路径已兜底,即使切错(切出不合理章节)用户至少还能看到整文档粒度的分数
- **[R-2] title 对齐把"技术方案"和"技术保障"错配**:TF-IDF 分词后这两者共享"技术"高权重,sim 可能 > 0.40 → 带来假阳;mitigation:threshold=0.40 偏保守,实际观察需要调优;C17 可引入章节模板词典
- **[R-3] 章节对齐贪心策略 suboptimal**:多个 a 章节都能和某个 b 章节对齐时,可能吃掉更好的匹配 → mitigation:实际每侧章节数 < 30,假阳的边际成本低,不做匈牙利算法
- **[R-4] 双重 LLM 降级嵌套**:章节切分失败 + LLM 失败 — summary 需说清两个降级;evidence 同时含 `degraded_to_doc_level` 和 `degraded`,前端渲染需识别
- **[R-5] C7 模块 import 链**:`section_similarity.py` import `text_sim_impl`,但 `text_sim_impl` 不反向 import section_similarity;C7 子包 API 稳定性由 C7 spec 保证(目前 C7 spec 未显式声明 API 稳定性 → C8 propose 默认约定:C7 `text_sim_impl` 公开 API 在 C8 归档前不变,后续 change 若改需 bump schema 版本或走 MODIFIED requirement)
- **[R-6] chapter_pairs 20 条上限可能切掉中分章节**:20 条够显示;全量写入 JSONB 在极端长文档下内存/性能堪忧,不改

## Migration Plan

### 上线步骤

1. 代码部署(C7 已有 `text_sim_impl/` 供 C8 import)
2. 首次用户启动检测 → text_similarity(C7) + section_similarity(C8)两个维度同时跑
3. 验证:
   - 报告页 section_similarity 行有真实 score(非 dummy 随机分特征)
   - evidence_json.algorithm 为 `tfidf_cosine_chapter_v1` 或 `tfidf_cosine_fallback_to_doc`
   - 降级路径下 degraded_to_doc_level=true 能被前端识别

### 回滚策略

- 撤 C8 commit,`section_similarity.py` 恢复 dummy;C7 不受影响

## Open Questions

- **Q1**(延后至 C14):报告渲染层如何处理 text_similarity + section_similarity 可能重复的证据?C8 后端层保持独立,C14 LLM 综合研判 + C17 前端 UI 合计负责
- **Q2**(C8 实施期验证):SECTION_SIM_TITLE_ALIGN_THRESHOLD=0.40 是否偏低?实施期 L2 测试"章节错位对齐"场景会验证,若漏报再调 0.30;若假阳再调 0.50
- **Q3**(延后):C17 引入"章节模板词典"后,title 对齐可换成 "词典匹配 + TF-IDF 回退" 两层,但本期不做
