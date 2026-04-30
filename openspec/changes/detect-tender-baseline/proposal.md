## Why

`detect-template-exclusion`(2026-04-25 归档) 的"模板簇剔除"机制只覆盖 5/12 维度,且基于元数据指纹 (author + doc_created_at) 识别,**元数据失效时完全不工作**。`text-sim-exact-match-bypass`(2026-04-29 归档) 引入段级 hash 旁路,让 ≥50 字 exact_match 段直接顶到 ironclad —— 但招标方下发的 docx 模板段(本次客户提供模板实测:资信标 34 段 ≥50 字)会让所有应标方在文本/章节/报价多个维度同时触发铁证,业务上线即误报海啸。

第一性原理:招标方下发模板这件事在业务上是**确定性输入**,不是统计推断问题。本次 change 用招标文件作为**白名单基线**做精准剔除,并以"跨投标人共识 ≥3 distinct bidders"作为无招标文件场景的兜底,把 `detect-template-exclusion` 主题闭环。

## What Changes

- **数据模型**:新建 `TenderDocument` 独立表(项目级 1..N,不污染 BidDocument 18 个消费方);`DocumentText` 加 `segment_hash` SHA256 字段
- **基线识别**:新建 `baseline_resolver.py` 模块,封装三级降级
  - L1 有招标文件 → 段 hash 命中 tender 集合 → `template_from_tender`,从 ironclad 触发集剔除
  - L2 无招标文件 + 投标方 ≥3 → 段在 ≥3 distinct bidders 中完全相同 → `template_by_consensus`,从 ironclad 触发集剔除
  - L3 无招标文件 + 投标方 ≤2 → 加 `warnings='baseline_unavailable_low_bidder_count'` 标记 + UI 警示条;**ironclad 触发逻辑保留原行为**(text/section 单维度仍可独自顶铁证 —— 用户产品立场:基线缺失 ≠ 信号无效)
- **template_cluster 扩展**:`_apply_template_adjustments` 新增 `reason="tender_match"` / `"consensus_match"` 分支;evidence_extras 加 `baseline_source ∈ {tender, consensus, metadata_cluster, none}`
- **4 高优 detector 接入**:`text_similarity` / `section_similarity` / `price_consistency` / `price_anomaly` 各自接入 baseline_resolver,粒度分别为段级/章节级/BOQ 项级/bidder 级
  - BOQ 项级 hash key = `(项目名 + 描述 + 计量单位 + 工程量)`,**不含单价/合价/总价**(单价是应标方差异化输入)
  - **BOQ 项级 baseline 仅支持 L1 tender 路径,L2 共识不适用** —— 4 家应标方填同一份招标方下发工程量清单是合法行为,共识阈值会把它们全部误剔成"模板"变零分
  - 多份 BOQ xlsx 不区分文件归属,所有 tender xlsx 行 hash 进项目级同一集合
- **上传 API**:新增 `POST/DELETE/GET /api/projects/{pid}/tender`,复用现有 `_persist_archive` + `trigger_extract`;固定 `file_role="tender"`
- **重跑机制**:复用 `analysis.py:140 PairComparison.version+1` 入口,不另造;补传 tender 后前端弹 dialog 询问"立即重新检测?是/否";不自动触发
- **前端**:`ProjectDetailPage` 加招标文件上传卡 + 基线状态 Badge;`StartDetectButton` 加未传 tender 预检查 dialog;`ReportPage` + `DimensionRow` 模板段 Tag 渲染;`TextComparePage` + `ComparePage` 模板段灰底渲染(复用 `tokens.ts` 既有色板,不新增色值)
- **灰度兜底**:前端加 feature flag `VITE_TENDER_BASELINE_ENABLED`(默认 false),客户验收后再打开

**用户产品立场保留(非 BREAKING)**:text 单维度可独自铁证 —— baseline 只把模板段从铁证分子里精准剔除,不削弱单维度铁证权力。

**不在本次范围(留 follow-up)**:
- `image_reuse` / `error_consistency` 2 个低优 detector 接入 baseline → 后续小 change
- 招标文件 PDF 扫描件解析(本次仅支持 docx + xlsx 干净路径)
- 改 1 字近似抄袭(留 v2 ngram/MinHash/shingle 路径,见 docs/handoff.md §1.1)

**Score 数值口径变化(历史不可比)**:tender 启用后 text_sim / section_sim / price_consistency 维度 score 普遍下降(模板段被剔除);用 `PairComparison.version` 自然递增,URL 可访问历史 v1,向前兼容,**非 BREAKING**。

## Capabilities

### New Capabilities

(无)

### Modified Capabilities

- `detect-framework`:模板基线识别从单维元数据指纹扩展到三级降级(tender hash + 共识 + 警示);4 高优 detector 各自接入 baseline_resolver;evidence_extras 加 baseline_source;ironclad 触发集 MUST 排除 `baseline_source ∈ {tender, consensus}` 的段对(L3 仅加 warnings,不动 ironclad);`_apply_template_adjustments` 函数职责语义扩展(从"metadata 簇专属"扩到"通用 adjustments 执行器",由 baseline_resolver 当生产者喂入 Adjustment list)
- `file-upload`:新增项目级招标文件 (tender) 上传/删除/列表接口;file_role="tender" 走 BidDocument 还是 TenderDocument 独立表 —— design 阶段确认独立表
- `project-mgmt`:项目详情页新增"招标文件"区块(上传卡 + 列表);启动检测前预检查 dialog(未传 tender 警示);补传 tender 后弹"立即重新检测?"dialog
- `report-view`:报告页头部新增基线状态 Badge(L1 蓝/L2 琥珀/L3 中性);维度行模板段标识 Tag
- `compare-view`:双栏对比模板段灰底渲染规则(`rgba(138,145,157,0.08)`,复用 textTertiary token);模板段 Tag 文案"模板段(来自招标文件)"或"模板段(共识识别)"

## Impact

- **后端代码**:新建 `services/detect/baseline_resolver.py` (~150 行) + `api/routes/tender.py` (~50 行) + `models/tender_document.py` (~35 行);改 `services/detect/template_cluster.py` (~40 行) + `services/detect/judge.py` (~20 行) + `services/parser/run_pipeline.py` (~20 行) + 4 detector 各 ~30 行 (~120 行) + 模型加字段 ~10 行 + schemas/api 序列化 ~20 行 = **后端 ~465 行**
- **前端代码**:新建 `components/projects/TenderUploadCard.tsx` + `BaselineStatusBadge.tsx` + `StartDetectPreCheckDialog.tsx` + `RerunAfterTenderDialog.tsx` (~150 行);改 `ProjectDetailPage` / `ProjectCreatePage` / `StartDetectButton` / `ReportPage` / `DimensionRow` / `TextComparePage` / `ComparePage` (~80 行) + `types/index.ts` + `services/api.ts` (~30 行) = **前端 ~260 行**
- **DB 迁移**:alembic 0014_add_tender_document_table + 0015_add_segment_hash_and_boq_baseline_hash 共 ~50 行;零数据迁移;老 `PairComparison.version` 数据保留只读;`DocumentImage.source_type` 字段属 image_reuse follow-up,不在本次范围
- **测试**:L1 ~80 case (baseline_resolver 单测 + 4 detector 接入测 + segment_hash 测 + 三级降级边界);L2 ~15 e2e (tender 上传完整流程 + 三级降级 + 重跑 version 递增 + 历史项目兼容);L3 客户演示 zip + 模板 zip 双套 walkthrough + UI 截图凭证(最小集 → 完整集分级跑)
- **测试 fixture**:`backend/tests/fixtures/llm_mock.py` 加 tender 解析 LLM mock 入口(避免触发真 LLM 收费);新增 `tender_zip_fixture` 复用本次客户提供的真实模板 zip
- **现有归档兼容**:`detect-template-exclusion` 元数据指纹路径保留并继续工作;`text-sim-exact-match-bypass` hash 旁路保留但 ≥50 字 exact_match 升 ironclad 多一层 baseline 检查;`text_sim_impl` / `section_sim_impl` / `price_impl` 内部算法不动
- **现有架构复用率约 70%**:`PairComparison.version` 重跑机制 + `template_cluster.py` adjustments 管道 + 上传/解析管道 + judge 6 步流程 + Ant Design + tokens.ts 色板 全部不动
- **回滚预案**:单 commit revert 即可恢复;前端 feature flag 关闭立即回退 UI;老 PairComparison.version 数据未删,自动恢复;详细回滚命令在 design.md
