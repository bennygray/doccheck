> 严格按 design.md D12 8 步分批节奏执行。每步 L1+L2 全绿才进下一步;任一失败立即修。
> 标签:[impl] = 代码改动 / [L1] = 单元+组件测试 / [L2] = API 级 e2e / [L3] = UI 级 e2e(Claude_in_Chrome)/ [manual] = 人工验证或决策门

## 1. 基础设施(D12 ①):数据模型 + 上传 API + parser hash 索引

- [ ] 1.1 [impl] 新建 `backend/app/models/tender_document.py`:`TenderDocument`(id / project_id FK / file_name / file_path / md5 / parse_status / created_at / deleted_at)
- [ ] 1.2 [impl] 修改 `models/document_text.py` 加 `segment_hash VARCHAR(64) NULL`
- [ ] 1.3 [impl] 修改 `models/price_item.py` 加 `boq_baseline_hash VARCHAR(64) NULL`
- [ ] 1.4 [impl] alembic 0014_add_tender_document_table.py
- [ ] 1.5 [impl] alembic 0015_add_segment_hash_and_boq_baseline_hash.py
- [ ] 1.6 [impl] 新建 `backend/app/api/routes/tender.py`:POST `/api/projects/{pid}/tender` / GET 列表 / DELETE 软删
- [ ] 1.7 [impl] 注册 tender 路由到 main app + 加 `schemas/tender.py` Pydantic models
- [ ] 1.8a [impl] 扩 `extract/engine.py:trigger_extract` 签名为 `trigger_extract(*, bidder_id=None, tender_id=None, password=None)` keyword-only;**内部约束:`bidder_id` 与 `tender_id` 二选一(MUST NOT 同时给值,MUST NOT 同时空)**;内部按非空字段分发到 `_extract_bidder_archive(bidder_id)` / `_extract_tender_archive(tender_id)` 私有 helper
- [ ] 1.8a-i [impl] **breaking change caller 迁移**:全工程 grep `trigger_extract(` 找出所有 positional 调用点,**已知 3 处必改**:① `routes/bidders.py:218 trigger_extract(bidder.id)` ② `routes/bidders.py:248 trigger_extract(bidder.id)` ③ `routes/documents.py:120 trigger_extract(bidder.id, password=password)`;**docstring 同步**:`services/extract/__init__.py:4` docstring 若提到 trigger_extract 签名也改;统一改为 keyword `trigger_extract(bidder_id=bidder.id, password=...)`;L1 单测覆盖"两参数互斥(同时给值/同时空均 raise)"+ 3 处 caller 改后行为不变回归
- [ ] 1.8b [impl] 新写 `_extract_tender_archive(tender_id)`:**仅复用 zip 解压安全骨架**(`_sync_extract / _extract_zip / _extract_7z / _extract_rar / _walk_extracted_dir` 等纯解压逻辑);**MUST 分叉重写**所有"写 BidDocument / 聚合 bidder.parse_status"的写入点 —— 实际命中 **`engine.py` 5 处 BidDocument 构造**(line 592 / 609 / 828 / 844 / 877)+ **2 处状态聚合**(`_aggregate_bidder_status` / `_set_bidder_failed`);tender 路径写 `DocumentText/DocumentSheet` 关联 TenderDocument,**MUST NOT** 调用 `trigger_pipeline`(tender 不进 run_pipeline 流水线)
- [ ] 1.8b-i [impl] 评估 engine.py 内 `_extract_*` callback 是否需要 polymorphic 改造(支持"写 BidDocument 或 TenderDocument"二选一回调);apply 阶段实测决定具体方案(选项:① 加 `on_child` 回调参数 ② 直接两条独立路径分叉)
- [ ] 1.8c [impl] **tender 解析完全跳过 run_pipeline 流水线**(tender 不属 bidder,architecturally 不进 `run_pipeline()`);因此 `parser/llm/role_classifier.py` / `fill_price_from_rule` / `acquire_or_wait_rule` / `detect_price_rule` 等 LLM 调用全部不会触发;L1 单测**断言 tender 解析全程 0 LLM 调用**
- [ ] 1.9a [impl] 修改 `services/parser/pipeline/run_pipeline.py`:切段后批量计算 segment_hash(复用 `text_sim_impl.tfidf._normalize` + sha256 + < 5 字 NULL 守门)
- [ ] 1.9b [impl] 修改 price 回填管线:计算 PriceItem.boq_baseline_hash(`(项目名+描述+单位+Decimal.normalize(工程量))` 联合 sha256)
- [ ] 1.10a [impl] 在 `routes/tender.py` 新写 `_persist_tender_archive(*, session, tender, upload_file)` helper:**仅复用** `bidders._persist_archive` 的 `_peek_head_and_size` + `validate_archive_file` 安全校验段(line 93+ 起前段);**MUST 分叉重写**:① `save_archive(project_id, bidder_id, ...)` 改为 `save_tender_archive(project_id, tender_id, ...)`(tender 落盘到 `<upload_dir>/<pid>/tender/<md5_prefix>_<safe_name>`)② md5 dedupe 表改查 `TenderDocument.md5` 而非 BidDocument ③ insert 改为 `TenderDocument(project_id=..., file_path=..., md5=..., parse_status='pending')`;**`services/storage.py` 不存在**,真实模块名是 `app/services/upload/storage.py`(不要试图修改它,只需 grep 复用其中 helper)
- [ ] 1.10b [impl] 在 `app/services/upload/storage.py` 加 `save_tender_archive(project_id, tender_id, upload_file) -> str`(对照现有 `save_archive(project_id, bidder_id, upload_file)`);保持函数签名一致风格,共享底层流式落盘逻辑
- [ ] 1.11 [impl] **不**给 `backend/tests/fixtures/llm_mock.py` 加 tender 解析 mock(因为 1.8c 已决定 tender 解析跳过 LLM,无需 mock);仅断言 conftest `_disable_l9_llm_by_default` autouse 不与 tender 解析路径冲突
- [ ] 1.12 [L1] `test_tender_document_model.py`:模型字段 + 软删除 + 项目内 md5 unique
- [ ] 1.13 [L1] `test_segment_hash_compute.py`:归一化口径 + sha256 + 短段 NULL 守门 + 历史 NULL 段 lazy 跳过
- [ ] 1.14 [L1] `test_boq_baseline_hash.py`:工程量精度归一化("1"/"1.0"/"1.000" 一致) + 不含价格 + 多 xlsx 合并去重
- [ ] 1.15 [L2] `test_tender_upload_api.py`:docx/xlsx/zip 上传 / 列表 / 软删 / 500MB 限制 / PDF 415 拒绝
- [ ] 1.16 [L2] `test_tender_parse_failsoft.py`:parse_status='failed' 不阻塞 detector,UI 降级提示
- [ ] 1.17 [L2] 验证门 ①:`pytest backend/tests/unit/test_tender_*.py backend/tests/unit/test_segment_hash*.py backend/tests/unit/test_boq_baseline*.py backend/tests/e2e/test_tender_*.py` 全绿

## 2. 基础逻辑(D12 ②):baseline_resolver + judge 注入点

- [x] 2.1 [impl] 新建 `backend/app/services/detect/baseline_resolver.py`:`resolve_baseline(session, project_id, dimension, raw_pairs) -> BaselineResolution(excluded_pair_ids, baseline_source, warnings)`,三级降级 L1/L2/L3;**dimension ∈ {price_consistency, price_anomaly} 时仅走 L1,L2 共识不适用**
- [x] 2.2 [impl] baseline_resolver 内:tender hash 加载 + 跨 bidder 共识计数(distinct bidder set,按 file_role 分组,unknown/other 不计)+ 优先级合并 `tender > consensus > metadata_cluster > none`;**L3 ≤2 投标方时 excluded_pair_ids=空集 + 仅产 warnings**(不产 Adjustment,不抑制 ironclad)
- [x] 2.3a [impl] baseline_resolver 加 `produce_baseline_adjustments(session, project_id, dimension, raw_pairs) -> list[Adjustment]`:**当生产者**直接产 `tender_match`/`consensus_match` Adjustment(score=0 + is_ironclad=False + evidence_extras.baseline_source)
- [x] 2.3b [impl] 修改 `services/detect/template_cluster.py:_apply_template_adjustments` 签名扩 `extra_adjustments: list[Adjustment] = []` 参数(**当纯执行器**);内部把 metadata_cluster 自产的 + 外部喂入的合并,同 PC.id 取最强 source
- [x] 2.3c [impl] 扩 `Adjustment.reason` 枚举加 `tender_match` / `consensus_match` 2 值;**不在 template_cluster 内新增 if/elif baseline 业务分支**(reason 由调用方决定)
- [x] 2.4 [impl] 修改 `services/detect/judge.py` step5:① 调 `_detect_template_cluster()` ② 调 `baseline_resolver.produce_baseline_adjustments()` ③ 调 `_apply_template_adjustments(..., extra_adjustments=baseline_adjustments)` 一次性合并
- [x] 2.5 [impl] 扩 `PairComparison.evidence_json` schema:加顶级 `baseline_source` 字段 + `warnings` 字段(数组,含 baseline_unavailable_low_bidder_count 等);schemas/report.py 加 `BaselineSourceLiteral` + ReportDimensionDetail.baseline_source/warnings + PairComparisonItem.baseline_source;reports API `/dimensions` 端点按维度合并 evidence_json + AnalysisReport.template_cluster_adjusted_scores 推导 baseline_source(detector §3+ 写入 evidence_json 后直接读)
- [x] 2.6 [L1] `test_baseline_resolver_l1.py`:tender hash 命中 / 多 source 优先级(13 测试全绿)
- [x] 2.7 [L1] `test_baseline_resolver_l2.py`:共识 ≥3 / ≤2 边界 / file_role 分组(11 测试全绿)
- [x] 2.8 [L1] `test_baseline_resolver_l3.py`:投标方 ≤2 警示 + warnings 字段(4 测试全绿)
- [x] 2.9 [L1] `test_template_cluster_baseline_integration.py`:2 新 reason 分支 + 老 metadata_cluster 路径不变(10 测试全绿,回归保护)
- [x] 2.10 [L2] `test_judge_baseline_injection_e2e.py`:judge 6 步 + step5 注入 + adjusted dict 透传 + reports API 含 baseline_source(5 测试全绿)
- [x] 2.11 [L2] 验证门 ②:L1 baseline_resolver+integration 38 测试全绿 + L2 judge_baseline_injection 5 测试全绿(全 unit 1302 + 全 e2e 304 全绿,无回归)

## 3. text_similarity 接入(D12 ③) + L3 最小集

- [ ] 3.1 [impl] 修改 `services/detect/agents/text_similarity.py:run()` 调 baseline_resolver,把 excluded_pair_ids 传给 aggregator
- [ ] 3.2 [impl] 修改 `text_sim_impl/aggregator.py:compute_is_ironclad` 签名加 `baseline_excluded_segment_hashes: set[str] | None = None` 入参(段级 hash 集合,而非 PC 级 baseline_source);逐段判断 **`hashlib.sha256(_normalize(p.a_text).encode("utf-8")).hexdigest()`**(算法与 D2 口径统一)∈ 该集合则**跳过该段的 ironclad 触发**(段仍计入 score);text_similarity.py:run() 内调 baseline_resolver 拿到段级 excluded hash set 后传入
- [ ] 3.2b [impl] 修改 `text_sim_impl/aggregator.py:build_evidence_json`:samples[i] 加 `baseline_matched: bool`(该段 hash 是否 ∈ excluded set)+ `baseline_source: str ∈ {tender, consensus, none}`(段级 source);PC 顶级 baseline_source 取所有命中段的最强 source(供 Badge 用);**前端无需复算 hash**,直接读 samples[i].baseline_matched 决定段级灰底/Tag
- [ ] 3.3 [impl] 修改 `text_sim_impl/aggregator.py:build_evidence_json` 写入 baseline_source 字段
- [ ] 3.4 [L1] `test_text_sim_baseline_integration.py`:① tender 命中段不升 ironclad ② consensus 命中段不升 ③ baseline_source='none' 且原触发条件成立时 **MUST 升** ironclad(原行为不变)④ **L3 ≤2 投标方时 MUST 仍升 ironclad(基线缺失 ≠ 信号无效)** ⑤ PC 内部分段命中 baseline 时按未命中段判 ironclad
- [ ] 3.5 [L1] `test_text_sim_legacy_compat.py`:老 evidence 无 baseline_source 字段 fallback
- [ ] 3.6 [L2] `test_text_sim_baseline_e2e.py`:tender 上传 → 检测 → evidence baseline_source='tender' 段被剔除 ironclad
- [ ] 3.7 [L3] **L3 最小集**:此时前端 tender 上传 UI 还未做(7.x 在 ⑦ 才做),因此最小集**仅后端 API + DB 状态截图**:用 curl/httpie 调 `POST /api/projects/{pid}/tender` 上传本次模板 zip(C:\Users\7way\Desktop\测试\模板.zip),启动检测得 v=新,验证 text_similarity 维度不再误报铁证;UI 截图凭证留 8.x 完整集;后端凭证(API 响应 + DB dump + evidence_json)落 `e2e/artifacts/detect-tender-baseline-{date}/text-sim-minimum-set/`
- [ ] 3.8 [L2] 验证门 ③:L1+L2+L3 最小集全绿才进 ④,**最小集发现方向错可早停**

## 4. section_similarity 接入(D12 ④)

- [ ] 4.1 [impl] 修改 `services/detect/agents/section_similarity.py`:章节标题 hash 命中 baseline 时整章不进 ironclad
- [ ] 4.2 [impl] 修改 `section_sim_impl/scorer.py`:章节级 baseline 命中标记 + chapter_pairs 元数据扩展
- [ ] 4.3 [L1] `test_section_sim_baseline.py`:章节级 baseline / 章节内段级联合判定 / file_role 分组生效
- [ ] 4.4 [L2] `test_section_sim_baseline_e2e.py`:完整流程
- [ ] 4.5 [L2] 验证门 ④:L1+L2 全绿

## 5. price_consistency 接入(D12 ⑤)

- [ ] 5.1 [impl] 修改 `services/detect/agents/price_consistency.py`:run() 调 baseline_resolver(BOQ 粒度);excluded 项不进 ironclad
- [ ] 5.2 [impl] 修改 `price_impl/extractor.py`:加载 PriceItem.boq_baseline_hash + 与 tender BOQ hash 集合比对
- [ ] 5.3 [impl] 4 个子检测(tail / amount_pattern / item_list / series_relation)接入 baseline:item_list 最强受影响,其余按需
- [ ] 5.4 [L1] `test_price_consistency_boq_baseline.py`:BOQ 项级命中 / 不含价格 / 多 xlsx 合并 / 工程量精度
- [ ] 5.5 [L2] `test_price_consistency_boq_e2e.py`
- [ ] 5.6 [L2] 验证门 ⑤:L1+L2 全绿

## 6. price_anomaly 接入(D12 ⑥)

- [ ] 6.1 [impl] 按 design D15 决策:扩 `anomaly_impl/extractor.py:aggregate_bidder_totals` 签名加 keyword-only `excluded_price_item_ids: set[int] | None = None` 参数;**默认 None 时三个共用 agent (price_anomaly/price_overshoot/price_total_match) 行为完全不变**(向后兼容);仅 price_anomaly.run() 在调用前先 query 出 tender BOQ hash 命中的 PriceItem.id 集合,作为该参数传入;SQL `SUM(PriceItem.total_price)` WHERE 子句加 `AND PriceItem.id NOT IN excluded` 过滤
- [ ] 6.1-i [L1] `test_aggregate_bidder_totals_excluded_param.py`:回归保护 — 默认 None 时 price_overshoot/price_total_match 调用结果完全不变(用 fixture 跑两次对比)
- [ ] 6.2 [impl] 修改 `services/detect/agents/anomaly_impl/scorer.py`:输出 baseline_source + warnings 到 evidence_json
- [ ] 6.3 [L1] `test_price_anomaly_baseline.py`:baseline 过滤 / 边界 case 全部命中 baseline 时 score 应为 0
- [ ] 6.4 [L2] `test_price_anomaly_baseline_e2e.py`
- [ ] 6.5 [L2] 验证门 ⑥:L1+L2 全绿

## 7. 前端基线 UI(D12 ⑦) + feature flag

- [ ] 7.1 [impl] 修改 `frontend/.env.example` + `frontend/.env`:加 `VITE_TENDER_BASELINE_ENABLED=false`
- [ ] 7.1b [impl] 修改 `frontend/src/theme/tokens.ts`:加 `bgTemplate: 'rgba(138,145,157,0.08)'` 派生 token(不复用既有 textTertiary hex,而是新加 rgba token 给模板段灰底专用)
- [ ] 7.2 [impl] 新建 `frontend/src/utils/featureFlags.ts`:暴露 `isTenderBaselineEnabled()`
- [ ] 7.3 [impl] 新建 `components/projects/TenderUploadCard.tsx`:**copy** AddBidderDialog 的 drag-drop 内联代码(useState(dragActive) + 原生 onDrop)+ 500MB 校验;**本次 change 不抽 useDragDrop hook**(避免范围爆炸);若 TenderUploadCard / AddBidderDialog 重叠代码 > 30 行,在 follow-up change 中再抽公共 hook(本 change 显式不做)
- [ ] 7.4 [impl] 新建 `components/projects/BaselineStatusBadge.tsx`:L1 蓝/L2 琥珀/L3 中性灰,色值复用 `tokens.ts`
- [ ] 7.5 [impl] 新建 `components/projects/StartDetectPreCheckDialog.tsx`:Alert warning + 不再提醒 checkbox(localStorage `tender_baseline_warning_dismissed_<pid>`)
- [ ] 7.6 [impl] 新建 `components/projects/RerunAfterTenderDialog.tsx`:Alert info + "立即重新检测?是/否"
- [ ] 7.7 [impl] 新建 `components/reports/StaleBaselineBadge.tsx`:老版本无 tender 警示 Badge
- [ ] 7.8 [impl] 修改 `pages/ProjectDetailPage.tsx`:加招标文件区块(feature flag 控制 + 整组隐藏/显示)
- [ ] 7.9 [impl] 修改 `components/projects/StartDetectButton.tsx`:加预检查 dialog 调用
- [ ] 7.10 [impl] 修改 `pages/ReportPage.tsx`:头部加 BaselineStatusBadge + 老版本 Stale Badge
- [ ] 7.11 [impl] 修改 `components/reports/DimensionRow.tsx`:模板段 Tag 渲染规则(蓝/橙/灰三色 + 文案)
- [ ] 7.12 [impl] 修改 `pages/TextComparePage.tsx`:模板段灰底**直接 import `colors.bgTemplate`**(7.1b 加的 token,**不**硬编码 rgba)+ 行首 Tag,优先于既有 simBgColor
- [ ] 7.13 [impl] 修改 `pages/ComparePage.tsx` + `MetaComparePage.tsx` + `PriceComparePage.tsx`:模板段灰底
- [ ] 7.14 [impl] 修改 `types/index.ts`:加 `TenderDocument` / `BaselineSource` / `BaselineStatus` 类型
- [ ] 7.15 [impl] 修改 `services/api.ts`:加 `uploadTender` / `listTender` / `deleteTender` API 客户端
- [ ] 7.16 [L1] `__tests__/TenderUploadCard.test.tsx` + `BaselineStatusBadge.test.tsx` + `StartDetectPreCheckDialog.test.tsx` + `RerunAfterTenderDialog.test.tsx` 4 组件单测
- [ ] 7.17 [L1] `__tests__/featureFlags.test.ts`:flag=true/false 各组件渲染分支
- [ ] 7.18 [L1] frontend tsc 0 errors + Vitest 全绿
- [ ] 7.19 [L2] 验证门 ⑦:前端 L1 全绿,且本地 `npm run dev` 启动后 flag=false 时 UI 与 change 前完全一致

## 8. L3 完整集 + 凭证归档(D12 ⑧)

- [ ] 8.1 [manual] 启动前后端服务(对齐 CLAUDE.md "测试阶段进入前重启前后端")
- [ ] 8.2 [L3] **L1 路径**:本地新建 project + 上传本次模板 zip 作 tender + 4 家应标方,启动 v=1,验证 baseline_source='tender' 段被剔除 ironclad,UI Badge 蓝色
- [ ] 8.3 [L3] **L2 路径**:同 project 不传 tender,3 家应标方,启动检测,验证 baseline_source='consensus' 段被剔除,UI Badge 琥珀
- [ ] 8.4 [L3] **L3 路径**:不传 tender,2 家应标方,验证 UI Badge 中性灰 + warnings='baseline_unavailable_low_bidder_count' + 警示条展示;**ironclad 触发逻辑保留原行为**(若样本含 ≥50 字 exact_match,text/section 单维度仍 MUST 顶铁证 —— L3 不抑制 ironclad,基线缺失 ≠ 信号无效)
- [ ] 8.5 [L3] **回归路径**:跑 project_id=3297(text-sim-exact-match-bypass 客户演示 zip),老 v 不变;新检测应识别真抄袭仍铁证(模板段无来源不剔除)
- [ ] 8.6 [L3] 截图归档 5 张:tender 上传卡 / 启动检测预检查 dialog / 报告页基线 Badge / 双栏对比模板段灰底 / 重跑 dialog → `e2e/artifacts/detect-tender-baseline-{date}/`
- [ ] 8.7 [L3] 真 LLM 跑双 zip(预估 ¥3-5 / 15-20 分钟),`agent_tasks_after.json` + `evidence_json_dump.json` 凭证
- [ ] 8.8 [manual] 编写 `e2e/artifacts/detect-tender-baseline-{date}/README.md`:期望 vs 实际 + commit hash + 5 张截图清单 + 真 LLM 实测数据

## 9. 归档准备

- [ ] 9.1 [L1][L2][L3] 全部测试,全绿(对齐 CLAUDE.md "三层分层测试" 标准)
- [ ] 9.2 [manual] 更新 `docs/handoff.md`:当前里程碑 + 当前 change + 先前 change 状态;在"演进路径备忘"补登 tender baseline 已上线
- [ ] 9.3 [manual] git commit(对齐 CLAUDE.md "archive 自动 commit" 约定):commit message `归档 change: detect-tender-baseline(M5)`,**不 push**(用户单独指示)
