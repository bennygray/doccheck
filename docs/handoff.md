# 项目 Handoff

> **跨会话/跨人接手的现场视角快照。** 计划视角见 `docs/execution-plan.md` §5。
>
> 本文档职责:记录"现在人在哪、下一步干什么、有什么没说清"。
> 最近变更历史只保留 5 条,更早历史去 `git log` 查。

---

## 1. 当前状态快照

| 项 | 值 |
|---|---|
| 当前里程碑 | **M3 进行中(5/9)**,C10 `detect-agents-metadata` 已 archive,待 commit |
| 当前 change | C10 已 archive,即将随本次 commit 一起提交 |
| 当前任务行 | N/A |
| 最新 commit | C9 归档 `8bbda15` — C10 archive commit 即将产生 |
| 工作区 | C10 全量改动:**数据层(C5 延伸)**:扩 `backend/app/models/document_metadata.py` 加 `template: Mapped[str \| None] = mapped_column(String(255), nullable=True)` + alembic `0007_add_document_metadata_template.py`(revision 字符串缩写为 `0007_add_doc_meta_template` 受 alembic_version VARCHAR(32) 限制)+ 扩 `parser/content/metadata_parser.py::DocMetadata` 加 `template` 字段 + 从 `docProps/app.xml::<Template>` 节点提取 + 扩 `parser/content/__init__.py` DocumentMetadata 写入加 `template=meta.template` + 新建 `backend/scripts/backfill_document_metadata_template.py`(幂等 + 错误隔离 + `--dry-run` + 退出码,照搬 C9 模板)。**检测层(C10 主体)**:**新增 `backend/app/services/detect/agents/metadata_impl/` 子包 9 文件**(`__init__.py` 含 `write_pair_comparison_row` 共享 helper / config.py / models.py TypedDict / normalizer.py NFKC+casefold+strip / extractor.py / author_detector.py(三字段跨投标人精确聚类,hit_strength=`\|∩\|/min(\|A\|,\|B\|)`) / time_detector.py(modified_at 5 分钟滑窗 + created_at 精确相等) / machine_detector.py(三字段元组精确碰撞) / scorer.py)+ **重写 `agents/metadata_{author,time,machine}.py::run()`** 为 3 子 Agent 真实算法(纯程序化,零 LLM)+ preflight 代码保持不变(C6 契约锁定)+ 扩 `_preflight_helpers.bidder_has_metadata` 的 `"machine"` 分支 OR 条件加 `DocumentMetadata.template.is_not(None)` + 异常路径统一 catch + `evidence.error` 写入 + AgentTask.status 保持 succeeded + Agent 级 skip 用 `score=0.0` + `participating_fields=[]` 哨兵(对齐 C9 风格)+ 子检测 flag `METADATA_{AUTHOR,TIME,MACHINE}_ENABLED` 独立开关(disabled → `evidence.enabled=false` 不调 extractor)+ **L1 14 test 文件 69 用例** + **L2 1 test 文件 5 scenario**(覆盖 execution-plan §3 C10 全部 5 Scenario)+ 既有 `test_parser_content_api.py` 扩 1 用例(Template 字段验证)+ `backend/README.md` "C10 依赖"段(6 env + 回填脚本用法)+ `.gitignore` 加 c10-* 白名单 + `e2e/artifacts/c10-2026-04-15/README.md` L3 手工凭证占位 + `openspec/specs/detect-framework/spec.md` sync(+8 Req,从 34 Req → 42 Req)+ `openspec/specs/parser-pipeline/spec.md` sync(MODIFIED 文档内容提取 + 2 ADDED Req,从 15 → 17 Req)。**测试合计 625 全绿**(C10 新增 75 用例,C9 基线 550 → 625) |

---

## 2. 本次 session 关键决策(2026-04-15,C10 propose+apply+archive)

### propose 阶段已敲定(3 决策)

- **Q1 A 合并到一个 change**(用户拍板):3 子 Agent(author/time/machine)合并到一个 change,共用 `metadata_impl/` 子包;拒绝拆 3 mini change(archive 开销 3 倍)和 "machine 拆出" 折中方案
- **Q2 A 扩 C5 持久化 template + 回填**(用户拍板):alembic 0007 加 `document_metadata.template` 列 + parser 扩写 + 回填脚本三件套(照搬 C9 模式);拒绝降级为"只用 `appName + appVersion`"(会把 5 Scenario 3 信号从强指纹退化为弱提示)
- **Q3 A 纯精确匹配 + 轻量 NFKC**(用户拍板):NFKC + casefold + strip 归一化后精确相等;拒绝 Levenshtein / 规则化变体合并 / LLM 兜底;理由:元数据维度定位强证据铁证,漏报一单不如误报一单代价高,LLM 额度留 C14

### apply 阶段就地敲定

- **alembic revision 字符串缩写**(apply 期发现):原用 `0007_add_document_metadata_template`(35 chars)超过 `alembic_version.version_num` VARCHAR(32) 限制 → 改为 `0007_add_doc_meta_template`(26 chars);文件名保持 `0007_add_document_metadata_template.py` 全称;spec sync 文本同步修正
- **`_preflight_helpers.bidder_has_metadata` machine 分支改 OR 加 template**:宽松判定 "任一 machine 字段非空即通过",run 内部再做精确三字段 AND 匹配;避免 preflight 过度拦截
- **hit_strength 公式 `|∩|/min(|A|,|B|)` 而非 Jaccard**:Jaccard 对"一方 5 个 author 另一方 1 个相同 author"只得 0.2 信号偏弱;min 版本更贴合"围标信号"语义(一方全部命中即 1.0)
- **author 子权重 0.5/0.3/0.2**(apply 期默认值,`METADATA_AUTHOR_SUBDIM_WEIGHTS` 可覆盖):author 最强信号 / last_saved_by 次之 / company 可能默认填"某公司"权重最低
- **time 子权重 0.7/0.3**(modified/created):modified_at 是编辑时间(围标方批量生成强信号),created_at 是模板 init 时间信号较弱
- **`time_detector._slide_window_clusters` 跳过整簇避免重复**:连续 2+ 跨 side 条目归为一簇后直接 `i = j`,防止一个簇被分解计数多次
- **Agent run guard 放宽 `session is None`**:L1 单元测试以 mock `extract_bidder_metadata` 方式测试 Agent run,不需要真 session;`write_pair_comparison_row` 内部已处理 session=None 静默跳过
- **machine 的 participating_fields 从 hits 反推**:machine_detector 无 `sub_scores` 字段(单维度元组匹配),scorer 从 `hits[*].field` 取 `"machine_fingerprint"` 作为 participating_fields
- **evidence.enabled 语义**:flag 禁用 → `enabled=false`;数据缺失 → `enabled=true + participating_fields=[]`;前端按 `enabled=false` 优先识别
- **测试目录约定**:14 个 L1 test 文件平级 `tests/unit/test_metadata_*.py`(与既有风格对齐),不走 `tests/unit/services/detect/agents/` 深层目录;L2 单文件 5 scenario 覆盖全部 execution-plan §3 C10 验证场景

### 文档联动

- **`backend/README.md`** 新增 "C10 detect-agents-metadata 依赖" 段:6 env + 回填脚本两种用法(全量 / dry-run)+ DocumentMetadata.template 字段说明 + alembic 0007 revision 缩写说明
- **`openspec/specs/detect-framework/spec.md`** sync:MODIFIED "10 Agent 骨架"(dummy 列表去掉 3 metadata,加 3 "已替换" Scenario)+ ADDED 8 Req(共享 extractor / 3 子维度算法契约 / Agent 级 skip 与 flag 语义 / evidence_json 结构 / env / bidder_has_metadata machine 扩 template),total 42 Req
- **`openspec/specs/parser-pipeline/spec.md`** sync:MODIFIED "文档内容提取"(元数据字段列表加 template + 2 Template Scenario)+ ADDED 2 Req(DocumentMetadata.template 数据契约 / 回填脚本),total 17 Req
- **`.gitignore`** 加 `c10-*` L3 artifacts 白名单
- **`docs/handoff.md`** 即本次更新

---

## 2.bak1 上一 session 关键决策(2026-04-15,C9 propose+apply+archive)

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

## 2.bak2 上上 session 决策(2026-04-15,C8 apply+archive)

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

## 2.bak3 上上上 session 决策(2026-04-15,C7 apply+archive)

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

## 3. 待确认 / 阻塞

- 无硬阻塞,**M3 进度 5/9**,C10 已 archive,本次 commit 后继续 C11
- **Follow-up(C10 新增)**:**L3 手工凭证待补**(延续 C5~C9):Docker kernel-lock 解除后,按 `e2e/artifacts/c10-2026-04-15/README.md` 步骤跑 3 张截图(启动检测 / 报告页 metadata_* 3 行展开 / 回填脚本日志);同期手工跑 `uv run python -m scripts.backfill_document_metadata_template` 验证幂等
- **Follow-up(C10 新增)**:**生产回填 template 字段**:M3 完成后生产部署前必须跑一次 `backfill_document_metadata_template.py` 回填历史文档 template;未回填的文档 metadata_machine 维度全 skip
- **Follow-up(C10 新增)**:**作者变体合并**:当前纯精确匹配("张三" vs "张三 (admin)" 不合并);实战漏报多时开 B 路线(规则化变体剥离 + pypinyin 拼音互转);留 C17+
- **Follow-up(C10 新增)**:**template 路径归一化**:`C:\...\Normal.dotm` vs `/Users/.../Normal.dotm` 当前不做路径剥离,只 NFKC;生产中若出现跨 OS 路径差异导致漏报可加 basename 归一化
- **Follow-up(C10 新增)**:**时间窗默认 5 分钟调优**:`METADATA_TIME_CLUSTER_WINDOW_MIN=5` 可能偏严(围标方手工编辑多文档耗时也可能超 5 分钟);实战数据调参,`backend/README.md` 已记
- **Follow-up(C9 留下,C10 继承)**:**L3 手工凭证待补 c9-2026-04-15**(同上 kernel-lock 依赖);合并单元格细粒度比对 / sheet 名 fuzzy 匹配 / document_sheets.rows_json 巨型存储 / STRUCTURE_SIM_WEIGHTS 调优
- **Follow-up(C8 留下,C9/C10 继承)**:**L3 手工凭证待补 c8-2026-04-15**(同上 kernel-lock 依赖)
- **Follow-up(C7 留下,C8/C9/C10 继承)**:`ProcessPoolExecutor` executor cancel 无法真中断子进程任务(C6 Risk-1);用 `max_features + MAX_PAIRS + MAX_ROWS` 限时缓解
- **Follow-up(C7 留下,C8/C9/C10 继承)**:容器 `cpu_count` 验证(C6 Q3);kernel-lock 解除后跑 `docker exec backend python -c "import os; print(os.cpu_count())"`
- **Follow-up(C6 留下,C10 消化 6/10)**:10 Agent 真实 `run()` 替换 — 已完成 text_similarity(C7)+ section_similarity(C8)+ structure_similarity(C9)+ metadata_author/time/machine(C10),剩 4 个(price_consistency / error_consistency / style / image_reuse)待 C11~C13
- **Follow-up(C6 留下)**:`judge.py` `DIMENSION_WEIGHTS` 占位权重,C14 LLM 综合研判时可调
- **Follow-up(C4 留下)**:加密包 3 次密码错冻结(推 C17);`encrypted-sample.7z`(L3 fixture)未入库
- **Follow-up**:Docker Desktop kernel-lock — C3~C10 L3 都跑不起来
- **Follow-up**:生产部署前必须 env 覆盖 `SECRET_KEY` / `AUTH_SEED_ADMIN_PASSWORD` / `LLM_API_KEY`;C6 调优 `AGENT_TIMEOUT_S` 等;C7 `TEXT_SIM_*` 3 env;C8 `SECTION_SIM_*` 3 env;C9 `STRUCTURE_SIM_*` 5 env;C10 `METADATA_*` 6 env
- **Follow-up(C5 留下)**:`role_keywords.py` Python 常量;C17 admin 后台迁 DB + UI
- **Follow-up(C9 pre-existing 暴露,C10 继承未处理)**:`backend/app/services/parser/content/__init__.py` 有 2 条 ruff 错(F401 unused `select` + 一行 E501)pre-existing,不属 C10 scope,留 cleanup change

---

## 4. 下次开工建议

**一句话交接**:
> **C10 `detect-agents-metadata` 已归档,M3 进度 5/9**。L1+L2 = **625 全绿**,C10 新增 75 用例;L3 延续手工凭证。下一步 `git push`(本次 archive commit 已产生),然后进 M3 下一个 change `/opsx:propose` 开 **C11 `detect-agent-price-consistency`**(报价一致性 Agent:尾数/金额模式/报价表项相似度,消费 C5 PriceItem + C9 DocumentSheet)。

**可直接粘贴给 AI 作为新会话起点**:
```
继续 documentcheck 项目。M3 进度 5/9,C10 detect-agents-metadata 已 archive + commit。
下一步进 C11 /opsx:propose detect-agent-price-consistency:
  - 替换 app/services/detect/agents/price_consistency.py 的 dummy run()
  - 消费 C5 PriceItem 表(已持久化每 bidder 的报价明细项)+ C9 DocumentSheet(xlsx cell 矩阵)
  - 3 子检测算法(execution-plan §3 C11):
      尾数一致 : 跨投标人报价尾 N 位数字集合碰撞
      金额模式 : 跨投标人 (item_name, unit_price) 对精确或模糊匹配率
      报价表项 : 跨投标人报价清单整体 95%+ 相似(对齐 DocumentSheet.rows_json)
  - 归一化:币种/含税口径(口径不一致 → 标"无法比对",不假阳)
  - 兜底(execution-plan §3 C11 原文):异常样本(非数值/缺失)→ 跳过不假阳;归一化失败 → 标"口径不一致,无法比对"
  - 不动框架:registry / engine / judge / context 全锁定
对应 docs/execution-plan.md §3 C11 小节。
请先读 docs/handoff.md 确认现状,然后 openspec-propose 为 C11 生成 artifacts。
注意:propose 阶段需用户敲定"尾数比对的 N"+ "子检测是否共享 price_impl/ 子包"+ "跨货币归一化策略"。
```

**C11 前的预备条件(已就绪)**:

- **C5 `PriceItem` 表已就绪**:`bidder_id / doc_id / item_name / unit_price / quantity / total_price / currency / tax_included` 字段(见 C5 归档);C11 直接 query
- **C9 `DocumentSheet` 表已就绪**:xlsx cell 矩阵 + 合并单元格 ranges;C11 可按需消费
- **C6 `_preflight_helpers.bidder_has_priced`** 已就绪
- **`_dummy.py` 给剩 4 Agent 用**;C11 后剩 3 Agent dummy(error_consistency / style / image_reuse)
- **registry / engine / judge / context** 全锁定不变;C11 只改 1 Agent 文件
- **C10 metadata_impl/ 模式可复用**:共享 `price_impl/` 子包 + NFKC normalizer + scorer 合成 + flag 开关 + evidence.enabled/participating_fields 哨兵语义

---

## 5. 最近变更历史(仅保留最近 5 条)

| 日期 | 变更 |
|---|---|
| 2026-04-15 | **C10 `detect-agents-metadata` 归档(M3 进度 5/9)**:**数据层延伸**:扩 `DocumentMetadata.template` 字段 + alembic 0007(revision 缩写 `0007_add_doc_meta_template` 受 VARCHAR(32) 限制)+ `metadata_parser` 从 `docProps/app.xml::<Template>` 提取 + 回填脚本 `backfill_document_metadata_template.py`(幂等 + 错误隔离 + dry-run);**检测层**:新增 `metadata_impl/` 9 文件(__init__ 含 write_pair_comparison_row / config / models TypedDict / normalizer NFKC+casefold+strip / extractor / author/time/machine_detector / scorer)+ 重写 3 Agent run()(author 三字段精确聚类 hit_strength=`|∩|/min` / time modified 5min 滑窗 + created 精确相等 / machine 三字段元组精确碰撞)+ `_preflight_helpers.bidder_has_metadata` machine 分支扩 template + 子检测 flag `METADATA_{AUTHOR,TIME,MACHINE}_ENABLED` + Agent 级 skip 用 score=0.0 + participating_fields=[] 哨兵;**测试 625 全绿**(C10 新增 75 用例);零 LLM 引入;关键决策:合并一个 change / 扩 C5 持久化 + 回填 / 纯精确 + NFKC(拒绝 Levenshtein/LLM);apply 意外:alembic revision 字符串缩写 / hit_strength 用 min 公式胜 Jaccard / session=None 放宽给 L1 mock / time 滑窗跳整簇避免重复;spec sync +8 Req(detect-framework 34→42)+ 2 Req(parser-pipeline 15→17);L3 延续手工凭证 |
| 2026-04-15 | **C9 `detect-agent-structure-similarity` 归档(M3 进度 4/9,commit 8bbda15)**:**数据层延伸**:新增 `document_sheets` 表 + alembic 0006(JSONB rows + merged_cells)+ `parser/content/__init__.py` xlsx 双写 + `xlsx_parser.SheetData.merged_cells_ranges` 字段 + 回填脚本 `backfill_document_sheets.py`(幂等 + 错误隔离 + dry-run);**检测层**:新增 `structure_sim_impl/` 8 文件(config/models/title_lcs/field_sig/fill_pattern/scorer/loaders)+ 重写 `structure_similarity.py::run()` 三维度纯程序化(目录 LCS / 字段 Jaccard / 填充 Jaccard,按 sheet_name 配对 max,三维度按原始权重重归一化)+ `_preflight_helpers.bidders_share_role_with_ext`;**测试 550 全绿**(C9 新增 103 用例);零 LLM 引入;关键决策:C 选项跨层延伸持久化 / 维度级 None 不影响其他 / Agent 级 skip 用 score=0.0 哨兵不走 C8 式降级;apply 意外:表名复数对齐 / FK 不加 CASCADE / bool 归 T / `_row_bitmask` 截尾;spec sync +5 Req(detect-framework)+ 3 Req(parser-pipeline);L3 延续手工凭证 |
| 2026-04-15 | **C8 `detect-agent-section-similarity` 归档(M3 进度 3/9,commit dae65ac)**:新增 `section_sim_impl/` 8 文件 + 重写 `section_similarity.py::run()` 章节级双轨算法(5 PATTERN 切章 → title TF-IDF 贪心对齐 + 序号回退 → 复用 C7 text_sim_impl 评分 → max×0.6+mean×0.4);L1 266 / L2 182 = 448 pass;C8 新增 38 用例;零新增第三方依赖;关键决策:A1 独立降级 / B1 纯正则 / C2 TF-IDF+index 回退 / D1 复用 C7 |
| 2026-04-15 | **C7 `detect-agent-text-similarity` 归档(M3 进度 2/9,commit ad7c779)**:新增 `text_sim_impl/` 7 文件 + 重写 `text_similarity.py::run()` 双轨算法(本地 TF-IDF+cosine 筛 → LLM 定性 → is_ironclad)+ `engine._build_ctx` 注入 LLM provider;L1 232 / L2 178 = 410 pass;C7 新增 49 用例;关键决策:A1 双轨分工 / B1 零新增依赖 / `max_df=1.0` 抗短样本 |
| 2026-04-14 | **C6 `detect-framework` 归档(M3 启动,commit 999c0d6)**:5 模型 + 0005 迁移 + services/detect/{registry,context,engine,judge}.py + 10 Agent 骨架(dummy run)+ services/async_tasks/{tracker,scanner}.py + 4 端点 + 4 前端组件;L1 188 / L2 173 = 361 pass;C6 新增 62 用例 |
