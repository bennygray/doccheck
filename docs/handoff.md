# 项目 Handoff

> **跨会话/跨人接手的现场视角快照。** 计划视角见 `docs/execution-plan.md` §5。
>
> 本文档职责:记录"现在人在哪、下一步干什么、有什么没说清"。
> 最近变更历史只保留 5 条,更早历史去 `git log` 查。

---

## 1. 当前状态快照

| 项 | 值 |
|---|---|
| 当前里程碑 | **M3 进行中(7/9)**,C12 `detect-agent-price-anomaly` 已 archive,待 commit |
| 当前 change | C12 已 archive,即将随本次 commit 一起提交 |
| 当前任务行 | N/A |
| 最新 commit | C11 归档 `94e8f18` — C12 archive commit 即将产生 |
| 工作区 | C12 全量改动:**检测层(C12 主体)**:**新增 `backend/app/services/detect/agents/anomaly_impl/` 子包 6 文件**(`__init__.py` 含 `write_overall_analysis_row` 共享 helper 对齐 C11 的 `write_pair_comparison_row`;`config.py` 7 env + `AnomalyConfig` dataclass + 严格/宽松两类校验(关键参数抛 ValueError / 次要参数 warn fallback);`models.py` 三 TypedDict(BidderPriceSummary / AnomalyOutlier / DetectionResult);`extractor.py` 单次 SQL INNER JOIN bidders×price_items + GROUP BY 聚合 + bidder_id 升序 + max_bidders 截断 + 软删 bidder 排除;`detector.py` mean 计算 + deviation 判定 + mean==0 兜底 + direction 非 low 运行期 fallback + warn;`scorer.py` 占位公式 `min(100, N*30 + max(|dev|)*100)`)+ **新增 `agents/price_anomaly.py`**(global 型,`@register_agent("price_anomaly", "global", preflight)`,三层兜底:ENABLED=false 早返 / preflight skip 样本不足 / run 边缘 skip 哨兵 `score=0.0 + participating_subdims=[] + skip_reason='sample_size_below_min'`;异常路径统一 catch + evidence.error)+ **新增 `_preflight_helpers.project_has_priced_bidders`**(单次 COUNT(DISTINCT) + INNER JOIN 自动过滤无 price_items 的 bidder)+ **注册表扩 10→11**(registry.py 新增 `EXPECTED_AGENT_COUNT: int = 11` 导出 + agents/__init__.py 加 `price_anomaly` import)+ **judge.py DIMENSION_WEIGHTS 调整**(新增 `price_anomaly=0.07`;`price_consistency 0.15→0.10`;`image_reuse 0.07→0.05`;总和仍 = 1.00)+ **L1 6 test 文件 43 新用例**(config 10 / extractor 5 / detector 9 / scorer 5 / preflight 7 / run 7)+ **L2 1 test 文件 5 Scenario**(对应 tasks 6.1~6.5)+ 更新既有测试硬编码 10→11(test_detect_registry.py 3 处 / test_detect_agents_dummy.py 2 处 / test_analysis_start_api.py 4 处 / test_analysis_status_api.py 1 处 / test_detect_engine_orchestration.py 2 处 / test_project_detail_with_analysis.py 1 处 / test_reports_api.py 1 处 / test_detect_judge.py 2 处 — 含 `test_all_dimensions_100_high` 追加 `price_anomaly` OA 项把 total 从 93 修正到 100)+ `app/api/routes/analysis.py` 注释"10→11"更新 + `backend/README.md` 新增 "C12 detect-agent-price-anomaly 依赖" 段(Q1~Q4 决策 + 算法 + 7 env + algorithm version `price_anomaly_v1` + DIMENSION_WEIGHTS 调整说明)+ `.gitignore` 加 `c12-*` 白名单 + `e2e/artifacts/c12-2026-04-15/README.md` L3 手工凭证占位(5 张待补截图 + L1/L2 覆盖证明)+ `openspec/specs/detect-framework/spec.md` sync(+5 ADDED + 3 MODIFIED Req,从 52 → 57 Req)+ `docs/execution-plan.md` §6 追加 1 行(C12 注册表扩至 11 Agent 的第一性原理审记录)。**测试合计 743 全绿**(C12 新增 49 用例,C11 基线 694 → 743) |

---

## 2. 本次 session 关键决策(2026-04-15,C12 propose+apply+archive)

### propose 阶段已敲定(4 决策)

- **Q1 sample_size 下限 = 3 家**(用户拍板):贴 execution-plan §3 C12 原文,覆盖 3~4 家小体量围标高发场景;拒绝 5 家(漏判小体量项目)
- **Q2 (C) 标底本期不支持,预留 hook 留 follow-up**(用户拍板):evidence.baseline=null 占位;本期单路均值,避免 M3 scope 跨 3 层(DB+检测+UI);贴 execution-plan §3 C12 原文兜底"标底未配置 → 仅按均值判断"
- **Q3 偏离方向 = 只抓低 + 30% 中档**(用户拍板,阈值数字自定写 design):低偏离是围标主信号;30% 抓强可疑误报可控;env 可覆盖
- **Q4 (A) 纯程序化,LLM 解释全留 C14**(用户拍板):贴 C11 模式避免 C12/C14 重复;evidence.llm_explanation=null 占位;分层干净

### propose 阶段我自己定(实施细节,写入 design D1~D9)

- **D1 扩注册表至 11 Agent**(新增 global 型 `price_anomaly`):spec "10 Agent 注册表" Requirement MODIFIED;`EXPECTED_AGENT_COUNT: int = 11` 常量新增
- **D2 子包 `anomaly_impl/` 5 文件结构** 贴 C11 `price_impl/`
- **D3 新增 `project_has_priced_bidders` helper**(单次 COUNT(DISTINCT))
- **D4 env 前缀 `PRICE_ANOMALY_*` 7 条**(关键参数抛 ValueError,次要参数 warn fallback)
- **D5 样本过滤**:仅计 INNER JOIN price_items 成功的 bidder
- **D6 项目类型不区分**(统一阈值)
- **D7 evidence 预留 `baseline: null` + `llm_explanation: null` 两 follow-up 占位字段**
- **D8 Agent 级 skip 哨兵** 贴 C10/C11(score=0.0 + participating_subdims=[] + skip_reason)
- **D9 algorithm version `price_anomaly_v1`**

### apply 阶段就地敲定

- **现场事实修正**:spec 原文"parse_status='priced'"在 `bidders.PARSE_STATUSES = {pending, extracting, extracted, skipped, partial, failed, needs_password}` 中不存在 — 此枚举无 `priced` 值;简化为通过 INNER JOIN price_items 自动过滤(有 price_item = 已成功解析报价),语义等价
- **`EXPECTED_AGENT_COUNT` 不在模块加载期 assert**:装饰器注册顺序不保证全部完成再 assert,改由 L1 测试断言(更干净)
- **DIMENSION_WEIGHTS 调整**:需要新增 `price_anomaly=0.07`,从 `price_consistency 0.15→0.10` + `image_reuse 0.07→0.05` 释放,总和仍 = 1.00;既有测试 `test_all_dimensions_100_high` 需追加 `price_anomaly` OA 项(原只写 10 项导致 total=93)
- **`test_medium_threshold` 注释修正**:原 `price_consistency 0.15*100=15`,现 `0.10*100=10`;总分从 49 → 44,仍在 medium 区间
- **测试 seed fixture 修复**:`PriceParsingRule` 是 **project 级**(非 document 级),L1 extractor test 初版用 `bid_document_id` 字段错误,改为 `project_id`
- **L2 Scenario 5 修改**:disabled 路径若 ctx 带 session 仍会写 OverallAnalysis 行(evidence enabled=false);"extractor 未调用"断言移到 L1(用 mock)验证
- **前端前置扫描**:grep `analysis_reports / AGENT_REGISTRY` 前端硬编码 10 未发现,reports.py 用 `ALL_DIMENSIONS = tuple(DIMENSION_WEIGHTS.keys())` 动态取,自动适配 11

### 文档联动

- **`backend/README.md`** 新增 "C12 detect-agent-price-anomaly 依赖" 段:Q1~Q4 决策注释 + 算法说明 + 7 env + `algorithm=price_anomaly_v1` + DIMENSION_WEIGHTS 调整记录
- **`openspec/specs/detect-framework/spec.md`** sync:MODIFIED 3 Requirement(10 Agent 注册表 / preflight 自检 / 10 Agent 骨架文件)+ ADDED 5 Req(preflight+helper / extractor / detector / skip+evidence / env),total 52 → 57 Req
- **`docs/execution-plan.md`** §6 追加 1 行:`2026-04-15 | C12 Agent 注册表扩至 11 Agent | 第一性原理审:price_anomaly 是物理 global 关系...`
- **`.gitignore`** 加 `c12-*` L3 artifacts 白名单
- **`docs/handoff.md`** 即本次更新

---

## 2.bak_C11 上一 session 关键决策(2026-04-15,C11 propose+apply+archive)

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

## 2.bak_C10 上上 session 关键决策(2026-04-15,C9 propose+apply+archive)

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

## 2.bak_C8 上上上 session 决策(2026-04-15,C8 apply+archive)

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

- 无硬阻塞,**M3 进度 7/9**,C12 已 archive,本次 commit 后继续 C13
- **Follow-up(C12 新增)**:**L3 手工凭证待补**(延续 C5~C11):Docker kernel-lock 解除后,按 `e2e/artifacts/c12-2026-04-15/README.md` 步骤跑 5 张截图(启动检测 / outlier 命中 evidence 展开 / 样本不足 skip / threshold env 覆盖 / enabled=false)
- **Follow-up(C12 新增)**:**标底路径实施**(design D7 预留 evidence.baseline=null 占位):独立 change / C17 admin 后台时一起做;数据层加字段(`ProjectPriceConfig.baseline_total` 或独立 baseline 表) + 前端配置 UI + 修改 detector 支持双路
- **Follow-up(C12 新增)**:**direction=high/both 实施**:env 字段已预留,detector 本期 fallback + warn;实战反馈若需要陪标高价信号再开
- **Follow-up(C12 新增)**:**C14 LLM 解释回填 `llm_explanation`**:evidence 结构已预留 null 字段,C14 综合研判时回填"低价是否合理"(如国企自产钢材 / 本地施工无差旅 → 合理低价)
- **Follow-up(C12 新增)**:**项目类型区分阈值**(design D6 决策):本期统一 30%,实战若总包项目误报率偏高,加 `PRICE_ANOMALY_DEVIATION_THRESHOLD_<TYPE>` per-type 覆盖
- **Follow-up(C12 新增)**:**robust 中位数 + IQR 升级**:初版用均值 + 百分比阈值,极端值(1 家报 1 元)会拉偏均值;实战若有类似干扰再升级
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
> **C12 `detect-agent-price-anomaly` 已归档,M3 进度 7/9**。L1+L2 = **743 全绿**,C12 新增 49 用例;L3 延续手工凭证。注册表从 10 → 11(新增 global 型 `price_anomaly`)。下一步 `git push`(本次 archive commit 已产生),然后进 M3 下一个 change `/opsx:propose` 开 **C13 `detect-agents-global`**(3 global 剩余:`error_consistency / style / image_reuse`)。

**可直接粘贴给 AI 作为新会话起点**:
```
继续 documentcheck 项目。M3 进度 7/9,C12 detect-agent-price-anomaly 已 archive + commit + push。
下一步进 C13 /opsx:propose detect-agents-global:
  - 替换 剩余 3 global Agent 的 dummy run():error_consistency / style / image_reuse
  - execution-plan §3 C13 对应 3 小节(可能拆成 3 个 sub-change 或合并成 1 个,propose 期决策)
  - error_consistency:LLM 语义类,消费 identity_info(bidder 级);preflight 返 downgrade 的降级路径已就绪
  - style:格式风格类,可能是纯程序化或双轨
  - image_reuse:图片 MD5 / 感知 hash 碰撞,消费 document_images 表
  - 不动框架:registry / engine / judge / context 全锁定(C12 已扩至 11 Agent);只改 3 Agent 文件
  - 可复用 C12 模式:新增 global 型 Agent 子包 + write_overall_analysis_row helper + Agent 级 skip 哨兵 + evidence.enabled/outliers 语义
  - C13 后 M3 进度 8/9,剩 C14 LLM 综合研判作为 M3 收官
对应 docs/execution-plan.md §3 C13 小节。
请先读 docs/handoff.md 确认现状(M3 状态 / C12 留下的 follow-ups / 11 Agent 注册表契约已锁定),然后 openspec-propose 为 C13 生成 artifacts。
propose 阶段需用户敲定(按"只问产品/范围级决策,一次一个"规则):
  - 3 Agent 是合并 1 个 change 还是拆 3 个(scope 粒度决策)
  - error_consistency 降级路径的语义(当一方 identity_info 空时,run 用哪些字段交叉)
  - style / image_reuse 的算法档位(LLM 介入深度:纯程序 / 双轨 / 全 LLM)
  - image_reuse 的相似度阈值与算法选型(pHash / dHash / MD5 + 二次确认)
也可以检查一下 memory 和 claude.md。
```

**C13 前的预备条件(已就绪)**:

- **C5/C6 底层就绪**:`document_images`(image_reuse 消费)/ `bidder.identity_info` JSONB(error_consistency 消费)/ `document_texts`(style 消费)
- **C12 扩注册表已落地**:11 Agent 契约稳定,C13 不改注册表,只改 3 Agent 文件的 run() 实现
- **anomaly_impl 模式可复用**:global 型子包结构 + write_overall_analysis_row helper + Agent 级 skip 哨兵(score=0.0 + participating_subdims=[] + skip_reason)
- **`_preflight_helpers`** 已积累 7 个 helper(含 C12 新增 `project_has_priced_bidders`),C13 可能需加 `project_has_images` / `project_has_identity_info` 类似 helper

---

## 5. 最近变更历史(仅保留最近 5 条)

| 日期 | 变更 |
|---|---|
| 2026-04-15 | **C12 `detect-agent-price-anomaly` 归档(M3 进度 7/9)**:**注册表扩 10→11**(新增 global 型 `price_anomaly`):registry.py 加 `EXPECTED_AGENT_COUNT=11` 常量 + agents/__init__.py 加 import;**检测层**:新增 `anomaly_impl/` 6 文件(__init__ 含 `write_overall_analysis_row` 对齐 C11 / config 7 env + AnomalyConfig + 严格/宽松两类校验 / models 三 TypedDict / extractor 单次 SQL INNER JOIN 聚合 + bidder_id 升序 + max_bidders 截断 + 软删排除 / detector mean 计算 + deviation 判定 + mean==0 兜底 + direction 非 low fallback+warn / scorer 占位 min(100, N*30+max(|dev|)*100))+ `price_anomaly.py` Agent 三层兜底(ENABLED=false 早返 / preflight skip / run 边缘 skip 哨兵);**`_preflight_helpers.project_has_priced_bidders`** 单次 COUNT(DISTINCT) + INNER JOIN 自动过滤;**judge.py DIMENSION_WEIGHTS** 调整(+price_anomaly=0.07 / price_consistency 0.15→0.10 / image_reuse 0.07→0.05);**测试 743 全绿**(C12 新增 49 用例:L1 43 + L2 5 + 注册表 1);**4 决策**:Q1 sample_size=3 / Q2 (C) 标底留 follow-up / Q3 只抓低+30% / Q4 (A) LLM 留 C14;apply 现场:parse_status='priced' 非 Bidder 枚举值改用 INNER JOIN 语义 / EXPECTED_AGENT_COUNT 不在模块加载期 assert 改测试断言 / test_all_dimensions_100_high 追加 price_anomaly OA 项修 93→100 / PriceParsingRule project 级非 document 级 fixture 修复 / L2 Scenario 5 disabled 路径仍写 OverallAnalysis 断言移 L1;spec sync +5 ADDED+3 MODIFIED Req(detect-framework 52→57);execution-plan §6 追加 C12 注册表扩展记录;L3 延续手工凭证 |
| 2026-04-15 | **C11 `detect-agent-price-consistency` 归档(M3 进度 6/9,commit 94e8f18)**:**检测层**:新增 `price_impl/` 11 文件(__init__ 含 write_pair_comparison_row 复用 C10 / config 13 env + 4 子检测 dataclass / models TypedDict / normalizer NFKC + Decimal split_price_tail truncate+zfill / extractor 按 sheet 分组+预计算 / 4 detector(tail (tail_3,int_len) 组合 key 防量级误撞 / amount_pattern (item_name,unit_price) 对精确匹配 / item_list 两阶段对齐"同项同价"+item_name 兜底 / **series_relation Q5 第一性原理审新增** 同模板对齐序列 ratios 方差+diffs CV 双路命中) / scorer 4 子检测加权合成,disabled/None 不参与归一化)+ 重写 `price_consistency.py::run()`(4 flag 全关早返;Agent 级 skip score=0.0+participating_subdims=[] 哨兵);**测试 694 全绿**(C11 新增 69 用例:L1 64 + L2 5);零 LLM 引入;**5 决策**:Q1 (B) 尾数组合 key / Q2 币种含税完全忽略 / Q3 (C) 两阶段对齐 / Q4 (A) 只走 PriceItem / **Q5 (A) 第一性原理审新增 series**;apply 意外:测试构造 bug 修一次 / 现场发现字段实际在 project_price_configs(留 cleanup) / scorer 三态 evidence(disabled/None/未执行)/ Agent 早返路径;spec sync +10 ADDED+1 MODIFIED Req(detect-framework 42→52);execution-plan §6 追加 C11 scope 扩展记录;**memory 新增 `feedback_first_principles_review.md`**(自审常驻第 3 项);L3 延续手工凭证 |
| 2026-04-15 | **C10 `detect-agents-metadata` 归档(M3 进度 5/9,commit 7573deb)**:**数据层延伸**:扩 `DocumentMetadata.template` 字段 + alembic 0007 + parser 扩 + 回填脚本;**检测层**:新增 `metadata_impl/` 9 文件 + 重写 3 Agent run()(author 三字段精确聚类 hit_strength=`|∩|/min` / time modified 5min 滑窗 + created 精确相等 / machine 三字段元组精确碰撞);**测试 625 全绿**(C10 新增 75 用例);零 LLM 引入;关键决策:合并一个 change / 扩 C5 持久化 + 回填 / 纯精确 + NFKC;spec sync +8 Req(detect-framework 34→42)+ 2 Req(parser-pipeline 15→17) |
| 2026-04-15 | **C9 `detect-agent-structure-similarity` 归档(M3 进度 4/9,commit 8bbda15)**:**数据层延伸**:新增 `document_sheets` 表 + alembic 0006 + 回填脚本;**检测层**:新增 `structure_sim_impl/` 8 文件 + 重写 `structure_similarity.py::run()` 三维度纯程序化(目录 LCS / 字段 Jaccard / 填充 Jaccard);**测试 550 全绿**(C9 新增 103 用例);零 LLM 引入;关键决策:C 选项跨层延伸持久化;spec sync +5 Req(detect-framework)+ 3 Req(parser-pipeline) |
| 2026-04-15 | **C8 `detect-agent-section-similarity` 归档(M3 进度 3/9,commit dae65ac)**:新增 `section_sim_impl/` 8 文件 + 重写 `section_similarity.py::run()` 章节级双轨算法(5 PATTERN 切章 → title TF-IDF 贪心对齐 + 序号回退 → 复用 C7 text_sim_impl);L1 266 / L2 182 = 448 pass;C8 新增 38 用例 |
