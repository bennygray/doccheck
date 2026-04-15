# 项目 Handoff

> **跨会话/跨人接手的现场视角快照。** 计划视角见 `docs/execution-plan.md` §5。
>
> 本文档职责:记录"现在人在哪、下一步干什么、有什么没说清"。
> 最近变更历史只保留 5 条,更早历史去 `git log` 查。

---

## 1. 当前状态快照

| 项 | 值 |
|---|---|
| 当前里程碑 | **M3 进行中(6/9)**,C11 `detect-agent-price-consistency` 已 archive,待 commit |
| 当前 change | C11 已 archive,即将随本次 commit 一起提交 |
| 当前任务行 | N/A |
| 最新 commit | C10 归档 `7573deb` — C11 archive commit 即将产生 |
| 工作区 | C11 全量改动:**检测层(C11 主体)**:**新增 `backend/app/services/detect/agents/price_impl/` 子包 11 文件**(`__init__.py` 含 `write_pair_comparison_row` 共享 helper 复用 C10 模式 / `config.py`(13 env + 4 子检测 dataclass + scorer 配置 + load_price_config)/ `models.py` TypedDict(PriceRow / SubDimResult)/ `normalizer.py`(item_name NFKC+casefold+strip + Decimal `split_price_tail` truncate + zfill + decimal_to_float_safe)/ `extractor.py`(从 PriceItem 按 sheet_name 分组 + 预计算 tail_key/item_name_norm/total_price_float + max_rows_per_bidder 限流)/ `tail_detector.py`((tail, int_len) 组合 key 跨投标人碰撞 hit_strength=`\|∩\|/min`)/ `amount_pattern_detector.py`((item_name_norm, unit_price) 对精确匹配率 + 阈值)/ `item_list_detector.py`(两阶段对齐:1a 同模板按 row_index 位置对齐"同项同价" + 1b 非同模板按 item_name 归一精确)/ `series_relation_detector.py`(**Q5 第一性原理审新增**:同模板对齐序列 ratios 方差 < ε → 等比 + diffs CV < ε → 等差;`statistics.pvariance / pstdev` stdlib)/ `scorer.py`(4 子检测加权合成,disabled/score=None 不参与归一化))+ **重写 `agents/price_consistency.py::run()`** 4 子检测真实算法(纯程序化,零 LLM)+ preflight 代码保持不变(C6 契约锁定,复用 `bidder_has_priced`)+ 异常路径统一 catch + `evidence.error` 写入 + AgentTask.status 保持 succeeded + Agent 级 skip 用 `score=0.0` + `participating_subdims=[]` 哨兵(对齐 C10 风格)+ 子检测 flag `PRICE_CONSISTENCY_{TAIL,AMOUNT_PATTERN,ITEM_LIST,SERIES}_ENABLED` 独立开关(全 disabled → 整 Agent 早返不调 extractor)+ **L1 8 test 文件 64 用例** + **L2 1 test 文件 5 scenario**(覆盖 execution-plan §3 C11 原 4 Scenario + Q5 新增 series Scenario)+ `backend/README.md` "C11 依赖"段(13 env + 4 子检测说明 + algorithm version `price_consistency_v1`)+ `.gitignore` 加 c11-* 白名单 + `e2e/artifacts/c11-2026-04-15/README.md` L3 手工凭证占位 + `openspec/specs/detect-framework/spec.md` sync(+10 ADDED + 1 MODIFIED Req,从 42 → 52 Req)+ `docs/execution-plan.md` §6 追加 1 行(C11 scope 扩 series 子检测的路线图记录,§3 C11 原文保留)。**测试合计 694 全绿**(C11 新增 69 用例,C10 基线 625 → 694) |

---

## 2. 本次 session 关键决策(2026-04-15,C11 propose+apply+archive)

### propose 阶段已敲定(5 决策,Q5 是第一性原理审新增)

- **Q1 (B) 尾数 (tail_3, int_len) 组合 key**(用户拍板):`PRICE_CONSISTENCY_TAIL_N=3` + 整数位长组合 key,区分 ¥100/¥1100/¥8100(尾数同但量级不同);拒绝纯尾数(选项 A 跨量级误撞)/ N=4(漏报多)/ N=2(误报极高)
- **Q2 币种 + 含税口径完全忽略**(用户拍板):C11 不读 `currency` / `tax_inclusive` 字段,直接按 `total_price / unit_price` 原始值比较;原 execution-plan §3 C11 "口径不一致 → 归一化" 路径简化为"不做归一化",真口径混用场景留 C14 LLM 综合研判
- **Q3 (C) 两阶段对齐**(用户拍板):同模板(sheet 集合相同 + 同名 sheet 行数相同)→ `(sheet_name, row_index)` 位置对齐"同项同价";否则 → `item_name` NFKC 归一精确匹配;拒绝纯位置(非同模板全漏)/ 纯 item_name(漏共享模板信号)/ LLM 语义对齐(留 C14)
- **Q4 (A) 只走 PriceItem,不消费 DocumentSheet**(用户拍板):分层职责清晰 — C5 报价抽取层 / C9 结构层 / C11 报价数值检测层;DocumentSheet 留 C9 专管,C11 不跨层
- **Q5 (A) 纳入 series_relation 子检测**(**第一性原理审 + 用户拍板**):新增第 4 子检测覆盖等差/等比/比例关系;execution-plan §3 C11 原文未列,本 change scope 扩展;水平关系归 C11 / 垂直关系归 C12 语义分层;拒绝留 C12(语义不贴) / 留 follow-up(知道漏不修消极)

### apply 阶段就地敲定

- **现场事实修正**:`currency / tax_inclusive` 字段实际在 `project_price_configs`(项目级 1:1)而非 `price_parsing_rules`(propose 期 design.md 写偏);C11 不读这些字段的决策不变,字段路径修正写入 `backend/README.md`,留作 follow-up 修 spec/design 文本
- **测试 bug 修复一次**:`test_tail_max_hits_limits` 初版用 `Decimal(f"{i}000")` for i in 100..130 全部尾数 "000" 是同一 key,只 1 个 intersect 而非 30;改用 `Decimal(f"1{i:03d}")` 得 30 个不同尾 3 位组合 key
- **scorer 三态 evidence 区分**:`_shape_subdim` 为 disabled / 数据缺失(score=None) / 未执行三态分别填 `enabled / score / reason`;前端按 `enabled=false` 优先识别(对齐 C10 evidence 哨兵语义)
- **Agent 早返路径**:4 flag 全关 → 整 Agent 早返不调 extractor(L1 验证 `ext_mock.assert_not_called()`),贴 C10 风格
- **series 仅同模板时跑**:row_index 对齐不可靠时方差计算无意义;复用 `item_list_detector.is_same_template` helper 单一判定源;非同模板 → `score=None` 子检测 skip,不影响其他子检测
- **series 公式选择**:ratios 用 `statistics.pvariance`(等比 = 比值近常数,方差对绝对尺度不敏感);diffs 用 CV = `pstdev/abs(mean)`(等差 = 差值近常数,但绝对差额尺度差异大,CV 归一化稳)
- **测试目录约定**:8 个 L1 test 文件平级 `tests/unit/test_price_*.py`(对齐 C10 metadata_* 风格);L2 单文件 5 scenario 全覆盖 execution-plan §3 C11 + Q5 新增

### 文档联动

- **`backend/README.md`** 新增 "C11 detect-agent-price-consistency 依赖" 段:13 env + 4 子检测说明 + Q2/Q4 决策注释 + algorithm version `price_consistency_v1`
- **`openspec/specs/detect-framework/spec.md`** sync:MODIFIED "10 Agent 骨架"(dummy 列表去 price_consistency,加"price_consistency 已替换" Scenario;dummy 列表仅剩 3 个 global Agent)+ ADDED 10 Req(共享 extractor / normalizer 契约 / 4 子检测算法契约 / scorer 合成 / Agent 级与行级兜底语义 / evidence_json 结构 / env),total 52 Req
- **`docs/execution-plan.md`** §6 追加 1 行 scope 变更记录:`2026-04-15 | C11 scope 扩 series_relation 子检测 | 第一性原理审暴露遗漏...`;§3 C11 原文保留不改
- **memory 新增 `feedback_first_principles_review.md`**:第一性原理审作为 review 简略版自审第 3 项常驻 checklist,跳出类比惯性挑战 design 本身;Q5 新增子检测就是该规则首次落地产出
- **`.gitignore`** 加 `c11-*` L3 artifacts 白名单
- **`docs/handoff.md`** 即本次更新

---

## 2.bak1 上一 session 关键决策(2026-04-15,C10 propose+apply+archive)

### propose 阶段已敲定(3 决策)

- **Q1 A 合并到一个 change**(用户拍板):3 子 Agent(author/time/machine)合并到一个 change,共用 `metadata_impl/` 子包;拒绝拆 3 mini change
- **Q2 A 扩 C5 持久化 template + 回填**(用户拍板):alembic 0007 加 `document_metadata.template` 列 + parser 扩写 + 回填脚本三件套
- **Q3 A 纯精确匹配 + 轻量 NFKC**(用户拍板):NFKC + casefold + strip 后精确相等;拒绝 Levenshtein / 变体合并 / LLM

### apply 阶段就地敲定

- **alembic revision 字符串缩写**:`0007_add_doc_meta_template`(26 chars)受 `alembic_version.version_num` VARCHAR(32) 限制
- **`_preflight_helpers.bidder_has_metadata` machine 分支 OR 加 template**:宽松判定避免 preflight 过度拦截
- **hit_strength 公式 `|∩|/min(|A|,|B|)` 而非 Jaccard**:贴"围标信号"语义(一方全部命中即 1.0)
- **author 子权重 0.5/0.3/0.2** + **time 子权重 0.7/0.3**(env 可覆盖)
- **`time_detector._slide_window_clusters` 跳过整簇避免重复**(`i = j`)
- **Agent run guard 放宽 `session is None`**:L1 mock extractor 测试需要
- **machine 的 participating_fields 从 hits 反推**:无 sub_scores 字段
- **evidence.enabled 三态**:flag 禁用 → false;数据缺失 → true + participating_fields=[]

### 文档联动

- **`backend/README.md`** 加 "C10 依赖" 段:6 env + 回填脚本用法
- **`openspec/specs/detect-framework/spec.md`** sync:+8 Req(34→42)
- **`openspec/specs/parser-pipeline/spec.md`** sync:+2 Req(15→17)

---

## 2.bak2 上上 session 关键决策(2026-04-15,C9 propose+apply+archive)

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

## 2.bak3 上上上 session 决策(2026-04-15,C8 apply+archive)

### propose 阶段已敲定(4 决策)

- **A1 独立降级**:章节切分失败 → C8 自己跑整文档 TF-IDF + dimension 仍写 section_similarity
- **B1 纯正则 5 PATTERN 切章**:第X章 / 第X节 / X.Y 数字 / 中文数字+顿号 / 纯数字+顿号
- **C2 title TF-IDF + 序号回退对齐**:title sim ≥ 0.40 贪心配对;未配对按 idx 序号回退
- **D1 复用 C7 `text_sim_impl/`**:C7 子包只读 import,零改动

### apply 阶段就地敲定

- **`_title_tokenizer` 独立**(aligner.py):C7 jieba_tokenizer 短 title 归零;C8 加专用宽松 tokenizer
- **`raw_loader.py` 绕 segmenter 短段合并**:保章节标题独立边界
- **pair 级公式 = max×0.6 + mean×0.4**:章节粒度 max 更易虚高,mean 权重上调对冲
- **章节对合并跨 LLM 调用**:所有章节 para_pairs 合并按 title_sim × avg_sim 粗排,仅前 30 段对送 LLM

---

## 3. 待确认 / 阻塞

- 无硬阻塞,**M3 进度 6/9**,C11 已 archive,本次 commit 后继续 C12
- **Follow-up(C11 新增)**:**L3 手工凭证待补**(延续 C5~C10):Docker kernel-lock 解除后,按 `e2e/artifacts/c11-2026-04-15/README.md` 步骤跑 7 张截图(启动检测 / 4 子检测 evidence 展开 / series.ratio 命中可视化 / flag 单关 evidence)
- **Follow-up(C11 新增)**:**修 spec/design 中字段路径偏差**:propose 期 design.md / spec.md 写"`price_parsing_rule.currency / tax_included`",实际字段在 `project_price_configs.currency / tax_inclusive`(项目级);代码已对(根本不读这些字段),只是文档需 cleanup;留 follow-up cleanup change(可与 C9 ruff 修复合并)
- **Follow-up(C11 新增)**:**series 阈值实战调参**:`PRICE_CONSISTENCY_SERIES_RATIO_VARIANCE_MAX=0.001` / `DIFF_CV_MAX=0.01` 是经验值;实战数据反馈后首 PR 调参;env 覆盖即可,不动代码
- **Follow-up(C11 新增)**:**LLM 语义对齐 item_name**:`钢筋Φ12` vs `Φ12 螺纹钢` 变体不合并漏报;留 C14 LLM 综合研判
- **Follow-up(C11 新增)**:**含税/币种混用真同价漏报**:Q2 决策不读这些字段,真同价不同表述场景留 C14
- **Follow-up(C11 新增)**:**series 分段 / 中位数 robust 法**:初版用 pvariance + CV 标准统计量,实战若有异常值干扰再升级中位数法 + IQR;留 follow-up
- **Follow-up(C10 留下)**:**生产回填 template 字段**:M3 完成后生产部署前必须跑一次 `backfill_document_metadata_template.py` 回填历史文档;未回填的文档 metadata_machine 维度全 skip
- **Follow-up(C10 留下)**:**作者变体合并** + **template 路径归一化** + **时间窗 5 分钟调优**:实战数据反馈后再处理
- **Follow-up(C9 留下,C10/C11 继承)**:**L3 手工凭证待补 c9-2026-04-15**(同上 kernel-lock 依赖);合并单元格细粒度比对 / sheet 名 fuzzy 匹配 / document_sheets.rows_json 巨型存储 / STRUCTURE_SIM_WEIGHTS 调优
- **Follow-up(C8 留下,C9/C10/C11 继承)**:**L3 手工凭证待补 c8-2026-04-15**(同上 kernel-lock 依赖)
- **Follow-up(C7 留下,C8/C9/C10/C11 继承)**:`ProcessPoolExecutor` executor cancel 无法真中断子进程任务(C6 Risk-1);用 `max_features + MAX_PAIRS + MAX_ROWS` 限时缓解
- **Follow-up(C7 留下,C8/C9/C10/C11 继承)**:容器 `cpu_count` 验证(C6 Q3);kernel-lock 解除后跑 `docker exec backend python -c "import os; print(os.cpu_count())"`
- **Follow-up(C6 留下,C11 消化 7/10)**:10 Agent 真实 `run()` 替换 — 已完成 text_similarity(C7)+ section_similarity(C8)+ structure_similarity(C9)+ metadata_author/time/machine(C10)+ price_consistency(C11),剩 3 个(error_consistency / style / image_reuse)待 C12~C13
- **Follow-up(C6 留下)**:`judge.py` `DIMENSION_WEIGHTS` 占位权重,C14 LLM 综合研判时可调
- **Follow-up(C4 留下)**:加密包 3 次密码错冻结(推 C17);`encrypted-sample.7z`(L3 fixture)未入库
- **Follow-up**:Docker Desktop kernel-lock — C3~C11 L3 都跑不起来
- **Follow-up**:生产部署前必须 env 覆盖 `SECRET_KEY` / `AUTH_SEED_ADMIN_PASSWORD` / `LLM_API_KEY`;C6 调优 `AGENT_TIMEOUT_S` 等;C7 `TEXT_SIM_*` 3 env;C8 `SECTION_SIM_*` 3 env;C9 `STRUCTURE_SIM_*` 5 env;C10 `METADATA_*` 6 env;**C11 `PRICE_CONSISTENCY_*` 13 env**
- **Follow-up(C5 留下)**:`role_keywords.py` Python 常量;C17 admin 后台迁 DB + UI
- **Follow-up(C9 pre-existing 暴露,C10/C11 继承未处理)**:`backend/app/services/parser/content/__init__.py` 有 2 条 ruff 错(F401 unused `select` + 一行 E501)pre-existing,留 cleanup change(可与 C11 字段路径偏差修一起)

---

## 4. 下次开工建议

**一句话交接**:
> **C11 `detect-agent-price-consistency` 已归档,M3 进度 6/9**。L1+L2 = **694 全绿**,C11 新增 69 用例;L3 延续手工凭证。下一步 `git push`(本次 archive commit 已产生),然后进 M3 下一个 change `/opsx:propose` 开 **C12 `detect-agent-price-anomaly`**(异常低价 Agent:相对均值/相对标底,垂直关系)。

**可直接粘贴给 AI 作为新会话起点**:
```
继续 documentcheck 项目。M3 进度 6/9,C11 detect-agent-price-consistency 已 archive + commit。
下一步进 C12 /opsx:propose detect-agent-price-anomaly:
  - 替换 app/services/detect/agents/price_anomaly.py 的 dummy run()(若是 global 型则改 global agent 文件)
  - 消费 C5 PriceItem 表(每 bidder 报价明细项)
  - 算法(execution-plan §3 C12 原文):
      相对均值 : 单家相对项目均值偏离 N% 触发
      相对标底 : 单家相对配置标底偏离触发(可选标底)
  - 兜底(execution-plan §3 C12 原文):
      样本 < 3 家 → 保守不触发
      标底未配置 → 仅按均值判断并说明
  - 不动框架:registry / engine / judge / context 全锁定;只改 1 Agent 文件 + 可能新增 anomaly_impl/ 子包
  - 可复用 C11 模式:共享 normalizer / extractor 模式 + flag 开关 + Agent 级 skip 哨兵
  - C12 = 垂直关系(单家 vs 群体);C11 已做完水平关系(bidder 之间)
对应 docs/execution-plan.md §3 C12 小节。
请先读 docs/handoff.md 确认现状,然后 openspec-propose 为 C12 生成 artifacts。
propose 阶段需用户敲定:
  - 偏离阈值(上下浮动 N%);默认值多少;是否区分项目类型(总包/单项)
  - 标底字段位置(目前未在 PriceItem 表;是否扩 PriceParsingRule 加 baseline_total / 走 ProjectPriceConfig 扩字段 / 走独立 baseline 表)
  - sample_size 下限(execution-plan §3 C12 原文 "< 3 家保守不触发",是否调到 5)
  - LLM 是否参与异常解释(如"低 30% 但是合理报价"语义判断)— 默认走 C14
也可以检查一下memory 和 claude.md。
```

**C12 前的预备条件(已就绪)**:

- **C5 `PriceItem` 表已就绪**:`bidder_id / sheet_name / row_index / item_code / item_name / unit / quantity / unit_price / total_price` 字段(注意 currency / tax_inclusive 在 `project_price_configs` 项目级,不在 PriceItem 行级)
- **C6 `_preflight_helpers.bidder_has_priced`** 已就绪;C12 可考虑加 `project_has_priced_bidders(session, project_id, min_count=3)` helper
- **`_dummy.py` 给剩 3 Agent 用**;C12 后剩 2 Agent dummy(error_consistency / style / image_reuse 取决于 C12 选哪个)— 注意 execution-plan §3 C12 = `price_anomaly`,但 C6 注册的 10 Agent 名字里没有 `price_anomaly`(只有 7 pair + 3 global = error_consistency / style / image_reuse),需先核对 execution-plan §3 与 C6 注册名是否对齐;若不对齐需先在 propose 阶段决策注册名扩展或 execution-plan 修正
- **registry / engine / judge / context** 全锁定不变;C12 只改 1 Agent 文件
- **C11 price_impl/ 模式可复用**:共享子包 + NFKC normalizer + scorer 合成 + flag 开关 + evidence.enabled/participating_subdims 哨兵语义

---

## 5. 最近变更历史(仅保留最近 5 条)

| 日期 | 变更 |
|---|---|
| 2026-04-15 | **C11 `detect-agent-price-consistency` 归档(M3 进度 6/9)**:**检测层**:新增 `price_impl/` 11 文件(__init__ 含 write_pair_comparison_row 复用 C10 / config 13 env + 4 子检测 dataclass / models TypedDict / normalizer NFKC + Decimal split_price_tail truncate+zfill / extractor 按 sheet 分组+预计算 / 4 detector(tail (tail_3,int_len) 组合 key 防量级误撞 / amount_pattern (item_name,unit_price) 对精确匹配 / item_list 两阶段对齐"同项同价"+item_name 兜底 / **series_relation Q5 第一性原理审新增** 同模板对齐序列 ratios 方差+diffs CV 双路命中) / scorer 4 子检测加权合成,disabled/None 不参与归一化)+ 重写 `price_consistency.py::run()`(4 flag 全关早返;Agent 级 skip score=0.0+participating_subdims=[] 哨兵);**测试 694 全绿**(C11 新增 69 用例:L1 64 + L2 5);零 LLM 引入;**5 决策**:Q1 (B) 尾数组合 key / Q2 币种含税完全忽略 / Q3 (C) 两阶段对齐 / Q4 (A) 只走 PriceItem / **Q5 (A) 第一性原理审新增 series**;apply 意外:测试构造 bug 修一次 / 现场发现字段实际在 project_price_configs(留 cleanup) / scorer 三态 evidence(disabled/None/未执行)/ Agent 早返路径;spec sync +10 ADDED+1 MODIFIED Req(detect-framework 42→52);execution-plan §6 追加 C11 scope 扩展记录;**memory 新增 `feedback_first_principles_review.md`**(自审常驻第 3 项);L3 延续手工凭证 |
| 2026-04-15 | **C10 `detect-agents-metadata` 归档(M3 进度 5/9,commit 7573deb)**:**数据层延伸**:扩 `DocumentMetadata.template` 字段 + alembic 0007 + parser 扩 + 回填脚本;**检测层**:新增 `metadata_impl/` 9 文件 + 重写 3 Agent run()(author 三字段精确聚类 hit_strength=`|∩|/min` / time modified 5min 滑窗 + created 精确相等 / machine 三字段元组精确碰撞);**测试 625 全绿**(C10 新增 75 用例);零 LLM 引入;关键决策:合并一个 change / 扩 C5 持久化 + 回填 / 纯精确 + NFKC;spec sync +8 Req(detect-framework 34→42)+ 2 Req(parser-pipeline 15→17) |
| 2026-04-15 | **C9 `detect-agent-structure-similarity` 归档(M3 进度 4/9,commit 8bbda15)**:**数据层延伸**:新增 `document_sheets` 表 + alembic 0006 + 回填脚本;**检测层**:新增 `structure_sim_impl/` 8 文件 + 重写 `structure_similarity.py::run()` 三维度纯程序化(目录 LCS / 字段 Jaccard / 填充 Jaccard);**测试 550 全绿**(C9 新增 103 用例);零 LLM 引入;关键决策:C 选项跨层延伸持久化;spec sync +5 Req(detect-framework)+ 3 Req(parser-pipeline) |
| 2026-04-15 | **C8 `detect-agent-section-similarity` 归档(M3 进度 3/9,commit dae65ac)**:新增 `section_sim_impl/` 8 文件 + 重写 `section_similarity.py::run()` 章节级双轨算法(5 PATTERN 切章 → title TF-IDF 贪心对齐 + 序号回退 → 复用 C7 text_sim_impl);L1 266 / L2 182 = 448 pass;C8 新增 38 用例 |
| 2026-04-15 | **C7 `detect-agent-text-similarity` 归档(M3 进度 2/9,commit ad7c779)**:新增 `text_sim_impl/` 7 文件 + 重写 `text_similarity.py::run()` 双轨算法(TF-IDF+cosine + LLM 定性);L1 232 / L2 178 = 410 pass;C7 新增 49 用例 |
