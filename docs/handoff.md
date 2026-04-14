# 项目 Handoff

> **跨会话/跨人接手的现场视角快照。** 计划视角见 `docs/execution-plan.md` §5。
>
> 本文档职责:记录"现在人在哪、下一步干什么、有什么没说清"。
> 最近变更历史只保留 5 条,更早历史去 `git log` 查。

---

## 1. 当前状态快照

| 项 | 值 |
|---|---|
| 当前里程碑 | **M3 进行中(4/9)**,C9 `detect-agent-structure-similarity` 已 archive,待 commit |
| 当前 change | C9 已 archive,即将随本次 commit 一起提交 |
| 当前任务行 | N/A |
| 最新 commit | C8 归档 `dae65ac` — C9 archive commit 即将产生 |
| 工作区 | C9 全量改动:**数据层(C5 延伸)**:新增 `backend/app/models/document_sheet.py`(DocumentSheet 模型,表名 `document_sheets` 复数,JSONB rows + merged_cells)+ alembic `0006_add_document_sheets`(JSONB PG/JSON SQLite 双变体)+ 扩 `parser/content/__init__.py` xlsx 分支双写 DocumentText + DocumentSheet + `MAX_ROWS_PER_SHEET` 截断 + `_clean_prior_extraction` 同步清 DocumentSheet + 扩 `parser/content/xlsx_parser.py::SheetData` 加 `merged_cells_ranges` 字段 + 新建 `backend/scripts/backfill_document_sheets.py`(幂等 + 错误隔离 + `--dry-run` + 退出码)+ `tests/fixtures/auth_fixtures._delete_all` 加 DocumentSheet 清理。**检测层(C9 主体)**:**新增 `backend/app/services/detect/agents/structure_sim_impl/` 子包 8 文件**(__init__/config/models/title_lcs/field_sig/fill_pattern/scorer/loaders)+ **重写 `agents/structure_similarity.py::run()`** 为三维度纯程序化算法(目录:LCS on docx 章节标题归一化序列,走 CPU executor / 字段:xlsx 列头 hash + 非空 bitmask + 合并单元格 Jaccard / 填充:xlsx cell type pattern multiset Jaccard;按 sheet_name 配对,sheet 维度 score=max,三维度按原始权重重归一化加权)+ preflight 加 `bidders_share_role_with_ext` 检查 docx/xlsx 至少一存在(新增 `_preflight_helpers.bidders_share_role_with_ext` helper)+ 维度级 None 不影响其他维度 / Agent 级 skip 用 `score=0.0` + `participating_dimensions=[]` 哨兵(不做 C8 式降级,严格按 execution-plan §3 C9 兜底原文)+ **L1 7 test 文件 99 用例** + **L2 1 test 文件 4 scenario** + 既有 `test_parser_content_api.py` 扩 2 用例(C5 延伸验证)+ `backend/README.md` "C9 依赖"段(5 env + 回填脚本用法)+ `.gitignore` 加 c9-* 白名单 + `e2e/artifacts/c9-2026-04-15/README.md` L3 手工凭证占位 + `openspec/specs/detect-framework/spec.md` sync(+5 Req,从 29 Req → 34 Req)+ `openspec/specs/parser-pipeline/spec.md` sync(MODIFIED 文档内容提取 + 3 ADDED Req)。**测试合计 550 全绿**(C9 新增 103 用例,C8 基线 448 → 550 = +102 含 E2E 新 2 用例) |

---

## 2. 本次 session 关键决策(2026-04-15,C9 propose+apply+archive)

### propose 阶段已敲定(4 决策)

- **C 选项:跨层延伸 C5 持久化**(用户拍板):新增 `document_sheets` 表 JSONB 持久化 xlsx cell 矩阵 + 合并单元格,不走 "Agent 运行时 re-extract" 路径;明确接受 "C9 跨 2 层"和 "alembic 0006 迁移" 的代价,换长期最干净的数据契约
- **三维度权重 0.4/0.3/0.3**(目录/字段/填充):用户接受 design 默认值,不改均权;run 期 env `STRUCTURE_SIM_WEIGHTS` 可覆盖
- **回填策略:回填**(用户决定):新增 `backend/scripts/backfill_document_sheets.py` 手工触发幂等脚本(NOT EXISTS 过滤 + 单 doc 错误隔离 + `--dry-run`)
- **不引 LLM**(用户接受):三维度纯程序化(LCS / Jaccard / hash);C14 综合研判时再 LLM 串所有维度

### apply 阶段就地敲定

- **`AgentRunResult.score: float` 不放 Optional**(C6 契约锁定):Agent 级"结构缺失"用 `score=0.0` 哨兵 + `evidence.participating_dimensions=[]` 标记;spec 同步从 `score=None` 调到 `score=0.0` 哨兵,2 处 Scenario 已修(spec sync 后已落到 main spec)
- **表名 `document_sheets`(复数)**:design 原写单数 `document_sheet`,apply 期发现既有 `document_texts/document_images` 全复数 → 改齐;同时 FK 不加 CASCADE(对齐既有,虽 design.D1 原写了 ondelete="CASCADE")
- **`_preflight_helpers.bidders_share_role_with_ext` 新增**:preflight 第二步要 "至少一侧有 docx 或 xlsx",独立 helper 比内联查询干净
- **目录 + xlsx 维度可能落不同 file_role**(structure_similarity 内决策):evidence.doc_role 用 `"role_a+role_b"` 合并表达;doc_id_a / doc_id_b 用 `int[]`(可能 1 或 2 个)而非单 int
- **维度级 skip 下放到 run 内**(spec D8 已写,落到代码):preflight 不做真章节切分 / cell 矩阵读取(成本高),只做轻量 COUNT 检查
- **测试目录约定灵活**:tasks.md 原写部分 L1 测试在 `tests/unit/services/parser/...`,apply 时改放到 `tests/unit/test_*.py` 平级(与既有 `test_parser_content_xlsx.py` 等对齐);xlsx 持久化测试合并到既有 `tests/e2e/test_parser_content_api.py`(L2)而非新建 L1 文件,匹配既有 extract_content 测试位置
- **`fixtures/auth_fixtures._delete_all` 同步加 DocumentSheet** 清表(否则 C9 后 PairComparison 测试因 BidDocument 删除受 FK 阻塞)
- **回填脚本独立 session per doc**:每个 doc 自己 `async with async_session()` + commit + 失败 rollback 不影响其他;比一个长事务里 `try/except` 干净
- **bool 归 'T' 文本**(fill_pattern 决策):True/False 通常是配置开关而非数值,与 N(数字)区分;改善"模板填充模式"语义
- **`_row_bitmask` 尾部连续 0 截掉**:稀疏 sheet 干扰大,对齐两侧(否则同结构但宽度不同 → bitmask 长度差 → multiset 不匹配)

### 文档联动

- **`backend/README.md`** 新增 "C9 detect-agent-structure-similarity 依赖" 段:5 新 env + DocumentSheet 持久化说明 + 回填脚本两种用法(全量 / dry-run)
- **`openspec/specs/detect-framework/spec.md`** sync:MODIFIED "10 Agent 骨架"(dummy 列表去 `structure_similarity`,加 "已替换" Scenario)+ ADDED 5 Req(三维度算法 / preflight / 维度级与 Agent 级 skip 语义 / evidence_json / 环境变量),+ 17 Scenario;total 34 Req
- **`openspec/specs/parser-pipeline/spec.md`** sync:MODIFIED "文档内容提取"(xlsx 分支加 DocumentSheet 双写 + 裁切)+ ADDED 3 Req(DocumentSheet 数据契约 / 回填脚本 / xlsx_parser merged_cells_ranges)
- **`.gitignore`** 加 `c9-*` L3 artifacts 白名单
- **`docs/handoff.md`** 即本次更新

---

## 2.bak1 上一 session 决策(2026-04-15,C8 apply+archive)

### propose 阶段已敲定(4 决策,本次未变更)

- **A1 独立降级**:章节切分失败 → C8 自己跑整文档 TF-IDF + dimension 仍写 section_similarity;不引用 C7 text_similarity 结果不跨 Agent 耦合
- **B1 纯正则 5 PATTERN 切章**:第X章 / 第X节 / X.Y 数字 / 中文数字+顿号 / 纯数字+顿号;不引 LLM 切章
- **C2 title TF-IDF + 序号回退对齐**:title sim ≥ 0.40 贪心配对;未配对按 idx 序号回退
- **D1 复用 C7 `text_sim_impl/`**:C7 子包只读 import,零改动;章节级评分只新增对齐层 + 跨章节合并层

### apply 阶段就地敲定

- **`_title_tokenizer` 独立**(aligner.py):C7 jieba_tokenizer 把 STOPWORDS 过滤狠,短 title 全归零;C8 加专用宽松 tokenizer,不动 C7
- **`raw_loader.py` 绕 segmenter 短段合并**:保章节标题独立边界;fallback 路径仍用 segmenter 合并产物
- **pair 级公式 = max×0.6 + mean×0.4**(C7 是 max×0.7+mean×0.3):章节粒度 max 更易虚高,mean 权重上调对冲
- **章节对合并跨 LLM 调用**:所有章节 para_pairs 合并按 title_sim × avg_sim 粗排,仅前 30 段对送 LLM(与 C7 共享 MAX_PAIRS_TO_LLM,不叠加)

---

## 2.bak2 上上 session 决策(2026-04-15,C7 apply+archive)

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

## 2.bak3 上上上 session 决策(2026-04-14,C6 apply 阶段)

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

- 无硬阻塞,**M3 进度 4/9**,C9 已 archive,本次 commit 后继续 C10
- **Follow-up(C9 新增)**:**L3 手工凭证待补**(延续 C5~C8):Docker kernel-lock 解除后,按 `e2e/artifacts/c9-2026-04-15/README.md` 步骤跑 3 张截图(启动检测 / 报告页 structure_similarity 三维度展开 / 回填脚本日志);同期手工跑 `uv run python -m scripts.backfill_document_sheets` 验证幂等
- **Follow-up(C9 新增)**:**合并单元格细粒度比对**:目前只比 `merged_cells_ranges` 位置集合 Jaccard,未考虑合并后的填充内容;C17 或更后改进
- **Follow-up(C9 新增)**:**sheet 名 fuzzy 匹配**:目前 `field_sig` / `fill_pattern` 配对按 `sheet_name` 完全相等;两家改名("报价表" vs "报价清单") → 无法配对 → 维度 0 分;留 follow-up
- **Follow-up(C9 新增)**:**`document_sheets.rows_json` JSONB 巨型表存储**:`MAX_ROWS_PER_SHEET=5000` 截断兜底;若生产环境平均 JSONB > 1MB 考虑分行表 `document_sheet_rows`
- **Follow-up(C9 新增)**:**`STRUCTURE_SIM_WEIGHTS` 调优**:实战观察 Scenario 2 命中率,若 field 维度敏感可调 `(0.3, 0.4, 0.3)`;`backend/README.md` 已记
- **Follow-up(C8 留下,C9 继承)**:**L3 手工凭证待补 c8-2026-04-15**(同上 kernel-lock 依赖)
- **Follow-up(C7 留下,C8/C9 继承)**:`ProcessPoolExecutor` executor cancel 无法真中断子进程任务(C6 Risk-1);用 `max_features + MAX_PAIRS + MAX_ROWS` 限时缓解
- **Follow-up(C7 留下,C8/C9 继承)**:容器 `cpu_count` 验证(C6 Q3);kernel-lock 解除后跑 `docker exec backend python -c "import os; print(os.cpu_count())"`
- **Follow-up(C6 留下,C9 消化 3/10)**:10 Agent 真实 `run()` 替换 — 已完成 text_similarity(C7)+ section_similarity(C8)+ structure_similarity(C9),剩 7 个(metadata_author/time/machine / price_consistency / error_consistency / style / image_reuse)待 C10~C13
- **Follow-up(C6 留下)**:`judge.py` `DIMENSION_WEIGHTS` 占位权重,C14 LLM 综合研判时可调
- **Follow-up(C4 留下)**:加密包 3 次密码错冻结(推 C17);`encrypted-sample.7z`(L3 fixture)未入库
- **Follow-up**:Docker Desktop kernel-lock — C3~C9 L3 都跑不起来
- **Follow-up**:生产部署前必须 env 覆盖 `SECRET_KEY` / `AUTH_SEED_ADMIN_PASSWORD` / `LLM_API_KEY`;C6 调优 `AGENT_TIMEOUT_S` 等;C7 `TEXT_SIM_*` 3 env;C8 `SECTION_SIM_*` 3 env;C9 `STRUCTURE_SIM_*` 5 env
- **Follow-up(C5 留下)**:`role_keywords.py` Python 常量;C17 admin 后台迁 DB + UI
- **Follow-up(C9 pre-existing 暴露)**:`backend/app/services/parser/content/__init__.py` 有 2 条 ruff 错(F401 unused `select` + 一行 E501)pre-existing,不属 C9 scope,留 cleanup change

---

## 4. 下次开工建议

**一句话交接**:
> **C9 `detect-agent-structure-similarity` 已归档,M3 进度 4/9**。L1+L2 = **550 全绿**,C9 新增 103 用例;L3 延续手工凭证。下一步 `git push`(本次 archive commit 已产生),然后进 M3 下一个 change `/opsx:propose` 开 **C10 `detect-agents-metadata`**(合并 3 个 metadata Agent:作者/时间/机器指纹;共用元数据提取器,跨投标人字段聚类碰撞)。

**可直接粘贴给 AI 作为新会话起点**:
```
继续 documentcheck 项目。M3 进度 4/9,C9 detect-agent-structure-similarity 已 archive + commit。
下一步进 C10 /opsx:propose detect-agents-metadata(合并 3 个 metadata Agent):
  - 替换 app/services/detect/agents/metadata_{author,time,machine}.py 的 dummy run()
  - 共用元数据提取器(C5 已写到 DocumentMetadata 表,直接消费)
  - 子检测算法:author 跨投标人聚类碰撞 / time 5 分钟内修改时间聚集 / machine appVersion+template 碰撞
  - 元数据缺失 → 标"数据不足"skip,不假阳(execution-plan §3 C10 兜底)
  - 子检测可通过 flag 单独关闭(L1 验)
  - 覆盖 execution-plan §3 C10 的 5 scenario
对应 docs/execution-plan.md §3 C10 小节。
请先读 docs/handoff.md 确认现状,然后 openspec-propose 为 C10 生成 artifacts。
注意:C10 是 3 Agent 合并提案,scope 比 C7~C9 大,propose 阶段需用户敲定"是否真合并 vs 拆 3 个独立 change"。
```

**C10 前的预备条件(已就绪)**:

- **C5 `DocumentMetadata` 表已就绪**:`author / last_saved_by / company / doc_created_at / doc_modified_at / app_name / app_version` 字段全;C10 直接 query
- **C6 `_preflight_helpers.bidder_has_metadata`** 已就绪(可指定 `require_field='author' / 'modified' / 'machine'`)
- **`_dummy.py` 给剩 7 Agent 用**;C10 后剩 4 Agent dummy(price_consistency / error_consistency / style / image_reuse)
- **registry / engine / judge / context** 全锁定不变;C10 只改 3 Agent 文件
- **C10 是合并提案**:propose 阶段需用户敲定"是否真合并到一个 change vs 拆 3 个 mini change";若合并,3 Agent 共享 `metadata_extractor.py` 公共子模块

---

## 5. 最近变更历史(仅保留最近 5 条)

| 日期 | 变更 |
|---|---|
| 2026-04-15 | **C9 `detect-agent-structure-similarity` 归档(M3 进度 4/9)**:**数据层延伸**:新增 `document_sheets` 表 + alembic 0006(JSONB rows + merged_cells)+ `parser/content/__init__.py` xlsx 双写 + `xlsx_parser.SheetData.merged_cells_ranges` 字段 + 回填脚本 `backfill_document_sheets.py`(幂等 + 错误隔离 + dry-run);**检测层**:新增 `structure_sim_impl/` 8 文件(config/models/title_lcs/field_sig/fill_pattern/scorer/loaders)+ 重写 `structure_similarity.py::run()` 三维度纯程序化(目录 LCS / 字段 Jaccard / 填充 Jaccard,按 sheet_name 配对 max,三维度按原始权重重归一化)+ `_preflight_helpers.bidders_share_role_with_ext`;**测试 550 全绿**(C9 新增 103 用例);零 LLM 引入;关键决策:C 选项跨层延伸持久化 / 维度级 None 不影响其他 / Agent 级 skip 用 score=0.0 哨兵不走 C8 式降级;apply 意外:表名复数对齐 / FK 不加 CASCADE / bool 归 T / `_row_bitmask` 截尾;spec sync +5 Req(detect-framework)+ 3 Req(parser-pipeline);L3 延续手工凭证 |
| 2026-04-15 | **C8 `detect-agent-section-similarity` 归档(M3 进度 3/9,commit dae65ac)**:新增 `section_sim_impl/` 8 文件 + 重写 `section_similarity.py::run()` 章节级双轨算法(5 PATTERN 切章 → title TF-IDF 贪心对齐 + 序号回退 → 复用 C7 text_sim_impl 评分 → max×0.6+mean×0.4);L1 266 / L2 182 = 448 pass;C8 新增 38 用例;零新增第三方依赖;关键决策:A1 独立降级 / B1 纯正则 / C2 TF-IDF+index 回退 / D1 复用 C7 |
| 2026-04-15 | **C7 `detect-agent-text-similarity` 归档(M3 进度 2/9,commit ad7c779)**:新增 `text_sim_impl/` 7 文件 + 重写 `text_similarity.py::run()` 双轨算法(本地 TF-IDF+cosine 筛 → LLM 定性 → is_ironclad)+ `engine._build_ctx` 注入 LLM provider;L1 232 / L2 178 = 410 pass;C7 新增 49 用例;关键决策:A1 双轨分工 / B1 零新增依赖 / `max_df=1.0` 抗短样本 |
| 2026-04-14 | **C6 `detect-framework` 归档(M3 启动,commit 999c0d6)**:5 模型 + 0005 迁移 + services/detect/{registry,context,engine,judge}.py + 10 Agent 骨架(dummy run)+ services/async_tasks/{tracker,scanner}.py + 4 端点 + 4 前端组件;L1 188 / L2 173 = 361 pass;C6 新增 62 用例 |
| 2026-04-14 | **C5 `parser-pipeline` 归档(M2 完成 3/3,commit e3fda28)**:4 模型 + 0004 迁移 + parser/{content,llm,pipeline} 12 模块 + 4 端点 + 4 前端组件;L1 153 / L2 143 = 296 pass;C5 新增 53 用例;E3 DB 原子占位 / SSE 内存 broker |
