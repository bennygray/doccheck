# 项目 Handoff

> **跨会话/跨人接手的现场视角快照。** 计划视角见 `docs/execution-plan.md` §5。
>
> 本文档职责:记录"现在人在哪、下一步干什么、有什么没说清"。
> 最近变更历史只保留 5 条,更早历史去 `git log` 查。

---

## 1. 当前状态快照

| 项 | 值 |
|---|---|
| 当前里程碑 | **M3 进行中(3/9)**,C8 `detect-agent-section-similarity` 已 archive,待 commit |
| 当前 change | C8 已 archive,即将随本次 commit 一起提交 |
| 当前任务行 | N/A |
| 最新 commit | C7 归档 `ad7c779` — C8 archive commit 即将产生 |
| 工作区 | C8 全量改动:**新增 `backend/app/services/detect/agents/section_sim_impl/` 子包 8 文件**(__init__/config/models/chapter_parser/aligner/scorer/fallback/raw_loader)+ **重写 `agents/section_similarity.py::run()`** 为章节级双轨算法(正则 5 PATTERN 切章 → title TF-IDF 贪心对齐 + 序号回退 → 章节对合并段落对 → 复用 C7 tfidf/llm_judge/aggregator → pair 级 max×0.6+mean×0.4 汇总)+ 章节切分失败降级到整文档粒度(A1 独立降级,dimension 仍 section_similarity 与 C7 text_similarity 并行)+ `tests/fixtures/llm_mock.py` 新增 `make_section_similarity_response()` 工厂 + 2 fixture + **L1 5 test 文件 34 用例**(`tests/unit/services/detect/agents/section_sim_impl/test_{chapter_parser,aligner,scorer,fallback}.py` + `test_section_similarity_run.py` 6 用例)+ **L2 1 test 文件 4 scenario**(`tests/e2e/test_detect_section_similarity.py`)+ `backend/README.md` "C8 依赖"段(3 env)+ `.gitignore` 加 c8-* 白名单 + `e2e/artifacts/c8-2026-04-15/README.md` L3 手工凭证占位 + `openspec/specs/detect-framework/spec.md` sync(+5 Req / +17 Scenario,29 Req / 89 Scenario 总)。**测试合计 448 全绿**(L1 266 / L2 182,L3 延续手工凭证),C8 新增 **38 个用例**(L1 34 + L2 4) |

---

## 2. 本次 session 关键决策(2026-04-15,C8 apply+archive)

### propose 阶段已敲定(4 决策)

- **A1 独立降级**:章节切分失败 → C8 自己跑整文档 TF-IDF(复用 C7 tfidf/llm_judge/aggregator)+ evidence.degraded_to_doc_level=true + dimension 仍写 section_similarity;**不引用** C7 text_similarity 结果也**不跨 Agent 耦合**(保 C6 Agent 并行调度前提);judge.py 按 section_similarity / text_similarity 各自权重独立计入 total_score
- **B1 纯正则 5 PATTERN 切章**:第X章 / 第X节 / X.Y 数字 / 中文数字+顿号 / 纯数字+顿号;不引 LLM 切章(2x token 成本 + 有 A1 兜底);投标文档规整命中率高
- **C2 title TF-IDF + 序号回退对齐**:title sim ≥ 0.40 贪心配对(aligned_by='title');未配对按 idx 序号对齐(aligned_by='index');贪心比匈牙利简单,每侧章节 < 30 无性能问题
- **D1 复用 C7 `text_sim_impl/`**:C7 子包只读 import,零改动;章节级评分只新增对齐层 + 跨章节合并层;验证了 C7 把"文本相似度组件"抽公共的可行性

### apply 阶段就地敲定

- **`_title_tokenizer` 独立**(aligner.py):C7 `jieba_tokenizer` 把 STOPWORDS("投标/项目/公司"等)过滤掉,短 title 如"投标函"→ `[]` token → TF-IDF sim=0 → 全部走 index 回退;加 C8 专用更宽松 tokenizer(仅过滤纯数字/标点,保留短区分词),**C7 text_sim_impl/ 不动一字**
- **`raw_loader.py` 绕过 C7 segmenter 短段合并**(核心架构决策):C7 `segmenter.load_paragraphs_for_roles` 合并 < 50 字相邻段(给整文档 TF-IDF 用),会把"第X章 投标函"(6字标题)和紧随 body 粘成一段 → chapter_parser 把标题和 body 混在 title 里,破坏章节边界;C8 新增 `raw_loader.load_raw_body_paragraphs(session, doc_id)` 直查 DB body 段落不合并,chapter_parser 用这个;fallback 路径仍用 segmenter 合并产物(与 C7 doc-level 语义一致)
- **MIN_CHAPTER_CHARS 默认 100 + MIN_CHAPTERS 默认 3** 设计 D2/D5 实战验证 OK;任一侧章节数 < 3 或双方总段落数 < 10 触发降级
- **chapter_pairs evidence 上限 20 条** + samples 跨章节上限 10 条:防 JSONB 爆;前端展开 20 条已够
- **pair 级公式 = max×0.6 + mean×0.4**(C7 是 max×0.7+mean×0.3):章节粒度 max 更容易虚高(单章全模板也 max 高),mean 权重上调 0.4 对冲
- **章节对合并跨 LLM 调用**:所有章节 para_pairs 合并按 `title_sim × avg_sim` 粗排,仅前 30 段对送 LLM(与 C7 共享 MAX_PAIRS_TO_LLM,不叠加);每章节独立聚合 chapter_score(未进 LLM 的段对按 None 权重 0.3 保守计)
- **Agent run 测试需要 mock raw_loader**:C8 加的 helper 在 L1 测试中绕不开,`_patch_raw_loader` 辅助 mock DB 查询

### 文档联动

- **`backend/README.md`** 新增 "C8 detect-agent-section-similarity 依赖" 段:3 新 env + C7 env 复用 + C8 → C7 text_sim_impl 依赖图 + ProcessPoolExecutor 共享
- **`openspec/specs/detect-framework/spec.md`** sync(sync-specs skill):+5 Req(章节级双轨算法 / preflight / 降级模式 / evidence_json / 环境变量)+ 17 Scenario;MODIFIED "10 Agent 骨架" 的 dummy scenario 改 `structure_similarity`(section_similarity 不再 dummy)
- **`.gitignore`** 加 `c8-*` L3 artifacts 白名单
- **`docs/handoff.md`** 即本次更新

---

## 2.bak1 上一 session 决策(2026-04-15,C7 apply+archive)

### propose 阶段已敲定(本次未变更)

- **A1 双轨分工**:本地 TF-IDF 始终跑 + LLM 定性 template/generic/plagiarism;LLM 失败 → 仅程序分数。对齐 §10.8 L-4
- **B1 零新增依赖**:复用 C5 `jieba + scikit-learn + numpy`
- **C 段落切 + 短段合并 + 超短 skip**:docx 原生段落 body(排除页眉页脚);< 50 字相邻合并;单侧 < MIN_DOC_CHARS(500)preflight skip
- **D 不加缓存**:一轮内 pair 不重复;版本+1 重检全量重跑

### apply 阶段就地敲定

- **`max_df=0.95` → `max_df=1.0`**:短样本全词被过滤 → 空 vocab;STOPWORDS + 单字过滤已处理高频词,无需 max_df 二次过滤
- **role_keywords 英文标识符**(technical/construction/bid_letter/...)不是中文"技术方案",design D1 错写时中文,apply 期对正
- **executor cancel 无法真中断子进程任务**:C6 Risk-1 具体化;C7 用 `max_features + MAX_PAIRS` 限时缓解,留 follow-up
- **`engine._build_ctx` llm_provider 注入走 `get_llm_provider()` + try/except fallback None**:C6 Q2a 落地
- **L2 测试手动构造 ctx 直调 Agent.run()**,不走 engine.run_detection(更快更稳)
- **C7 已消费 ProcessPoolExecutor**(C6 D9 首个真消费者验证)

---

## 2.bak2 上上 session 决策(2026-04-14,C6 apply 阶段)

### propose 阶段已敲定

- **A1 整体做**:不拆 C6a/C6b,13 Req / 53 Scenario
- **B1 409 拒绝**:项目 analyzing 态再次启动检测 → 409,不做 resume
- **C2 10 Agent 注册表 + dummy run**:name + agent_type + preflight 三元组稳定 contract;C7~C13 只改 run()
- **D3 通用 async_tasks 表 + 只扫不自动恢复**:4 subtype,消化 C4/C5 event loop 重启丢任务遗留

### apply 阶段就地敲定

- AGENT_TIMEOUT_S / GLOBAL_TIMEOUT_S 动态读取(L2 monkeypatch 支持)
- agents/__init__.py 在 analysis.py 中 import(触发 @register_agent)
- dummy_pair_run / dummy_global_run 共享 helper(C7/C8 已从 2 Agent 中脱离)
- preflight 共享查询 helper(`_preflight_helpers.py`,C7/C8 部分复用)
- L2 SSE 测试 httpx ASGITransport 流不可靠断开 → 只覆盖 404,流式靠 L1 broker + L3 手工
- clean_users fixture 扩 5 表
- L3 延续 C5 降级手工凭证(Docker kernel-lock)
- judge.py 铁证强制 ≥ 85;llm_conclusion 留空给 C14
- ProcessPoolExecutor 接口预留(C7 已消费)

---

## 3. 待确认 / 阻塞

- 无硬阻塞,**M3 进度 3/9**,C8 已 archive,本次 commit 后继续 C9
- **Follow-up(C8 新增)**:**L3 手工凭证待补**(延续 C5/C6/C7):Docker kernel-lock 解除后,按 `e2e/artifacts/c8-2026-04-15/README.md` 步骤跑 3 张截图(启动检测 / 报告页 chapter_pairs 展开 / 降级 evidence 展示)
- **Follow-up(C7 留下,C8 继承)**:`ProcessPoolExecutor` executor cancel 无法真中断子进程任务(C6 Risk-1);C7/C8 都用 `max_features + MAX_PAIRS` 限时缓解,根本解留更后 change
- **Follow-up(C7 留下,C8 继承)**:容器 `cpu_count` 验证(C6 Q3);kernel-lock 解除后跑 `docker exec backend python -c "import os; print(os.cpu_count())"`
- **Follow-up(C6 留下,C8 消化 2/10)**:10 Agent 真实 `run()` 替换 — 已完成 text_similarity(C7)+ section_similarity(C8),剩 8 个(structure_similarity / metadata_author/time/machine / price_consistency / error_consistency / style / image_reuse)待 C9~C13
- **Follow-up(C6 留下)**:`judge.py` `DIMENSION_WEIGHTS` 占位权重,C14 LLM 综合研判时可调
- **Follow-up(C4 留下)**:加密包 3 次密码错冻结(推 C17);`encrypted-sample.7z`(L3 fixture)未入库
- **Follow-up**:Docker Desktop kernel-lock — C3~C8 L3 都跑不起来
- **Follow-up**:生产部署前必须 env 覆盖 `SECRET_KEY` / `AUTH_SEED_ADMIN_PASSWORD` / `LLM_API_KEY`;C6 调优 `AGENT_TIMEOUT_S` 等;C7 调优 `TEXT_SIM_*` 3 env;C8 调优 `SECTION_SIM_*` 3 env
- **Follow-up(C5 留下)**:`role_keywords.py` Python 常量;C17 admin 后台迁 DB + UI

---

## 4. 下次开工建议

**一句话交接**:
> **C8 `detect-agent-section-similarity` 已归档,M3 进度 3/9**。L1 266 / L2 182 = **448 全绿**,C8 新增 38 用例;L3 延续手工凭证。下一步 `git push`(本次 archive commit 已产生),然后进 M3 下一个 change `/opsx:propose` 开 **C9 `detect-agent-structure-similarity`**(第三个真实 Agent:结构相似度 — 目录结构 / 字段结构 / 表单填充模式;结构提取失败标"结构缺失"不假阳,不做降级到整文档)。

**可直接粘贴给 AI 作为新会话起点**:
```
继续 documentcheck 项目。M3 进度 3/9,C8 detect-agent-section-similarity 已 archive + commit。
下一步进 C9 /opsx:propose detect-agent-structure-similarity:
  - 替换 app/services/detect/agents/structure_similarity.py 的 run() 为真实实现
  - 3 维度:目录结构(章节标题序列对比)/ 字段结构(表单空值模式)/ 表单填充模式
  - 结构提取失败 → 标 "结构缺失" skip,不做 C8 式降级(execution-plan §3 C9 明确)
  - 不动框架:registry / preflight / engine / judge 保持不变
  - 可能复用 C8 chapter_parser 作为目录结构提取
  - 覆盖 execution-plan §3 C9 的 4 scenario
对应 docs/execution-plan.md §3 C9 小节。
请先读 docs/handoff.md 确认现状,然后 openspec-propose 为 C9 生成 artifacts。
```

**C9 前的预备条件(已就绪)**:

- **C7 `text_sim_impl/` + C8 `section_sim_impl/chapter_parser` 可复用**:C9 目录结构维度可 import `section_sim_impl.chapter_parser.extract_chapters` 得章节标题序列,比较两侧章节标题 LCS 或顺序相似度
- **xlsx 报价单结构已有 C5 基础**:report_parser 阶段解析出 sheet 合并单元格、空值位置等;C9 字段结构维度从 `DocumentImage / DocumentMetadata / xlsx 解析产物` 拉数据(具体表 spec 阶段再定)
- **LLM 非必需**:C9 结构维度可以"纯程序化"判断(标题序列 LCS / 空值 hash / 表单填充模式比较),是否调 LLM 由 C9 propose 决策
- **preflight**:延用 C6 contract "双方有同角色文档"+可能追加"结构可提取"检查(返 skip "结构缺失"对齐 execution-plan 兜底)
- **`_preflight_helpers.py`** 仍可用;`_dummy.py` 仍给 7 Agent 用(C8 后)

---

## 5. 最近变更历史(仅保留最近 5 条)

| 日期 | 变更 |
|---|---|
| 2026-04-15 | **C8 `detect-agent-section-similarity` 归档(M3 进度 3/9)**:新增 `section_sim_impl/` 8 文件(chapter_parser/aligner/scorer/fallback/raw_loader/config/models)+ 重写 `section_similarity.py::run()` 章节级双轨算法(5 PATTERN 切章 → title TF-IDF 贪心对齐 + 序号回退 → 复用 C7 text_sim_impl 评分 → max×0.6+mean×0.4);**L1 266 / L2 182 = 448 pass**;C8 新增 38 用例;零新增第三方依赖(复用 C7 子包);关键决策:A1 独立降级 / B1 纯正则 / C2 TF-IDF+index 回退 / D1 复用 C7;apply 意外:`_title_tokenizer` 独立(C7 STOPWORDS 过狠)+ `raw_loader.py` 绕 segmenter 短段合并(保章节边界);spec sync +5 Req+17 Scenario;L3 延续手工凭证 |
| 2026-04-15 | **C7 `detect-agent-text-similarity` 归档(M3 进度 2/9,commit ad7c779)**:新增 `text_sim_impl/` 7 文件 + 重写 `text_similarity.py::run()` 为真实双轨算法(本地 TF-IDF+cosine 筛 → LLM 定性 → is_ironclad)+ `engine._build_ctx` 注入 LLM provider;L1 232 / L2 178 = 410 pass;C7 新增 49 用例;零新增第三方依赖;关键决策:A1 双轨分工 / B1 零新增依赖 / `max_df=1.0` 抗短样本 |
| 2026-04-14 | **C6 `detect-framework` 归档(M3 启动,commit 999c0d6)**:5 模型 + 0005 迁移 + services/detect/{registry,context,engine,judge}.py + 10 Agent 骨架(dummy run)+ services/async_tasks/{tracker,scanner}.py + 4 端点 + 4 前端组件;L1 188 / L2 173 = 361 pass;C6 新增 62 用例 |
| 2026-04-14 | **C5 `parser-pipeline` 归档(M2 完成 3/3,commit e3fda28)**:4 模型 + 0004 迁移 + parser/{content,llm,pipeline} 12 模块 + 4 端点 + 4 前端组件;L1 153 / L2 143 = 296 pass;C5 新增 53 用例;E3 DB 原子占位 / SSE 内存 broker |
| 2026-04-14 | **C4 `file-upload` 归档(M2 进度 2/3)**:4 模型 + 0003 迁移 + upload/extract 服务 + 3 路由 + 6 前端组件;L1 130 / L2 101 / L3 12 = 243 pass;C4 新增 106 用例;文件路径 absolute / GBK cp437 回路 / 加密包两阶段 probe |
