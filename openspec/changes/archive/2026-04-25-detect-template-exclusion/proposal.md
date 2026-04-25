## Why

3 家供应商在同一工程监理项目中使用招标方下发的同一 docx 模板(元数据 `author=LP` + `doc_created_at=2023-10-09 07:16:00` 跨三家一致)投标,当前检测引擎触发 `structure_similarity=100 + is_ironclad=true(scorer.py 阈值:max_sub≥0.9 且 score≥85)` / `text_similarity≈57~91` / `style=76.5` / `metadata_author=100 + is_ironclad=true(METADATA_IRONCLAD_THRESHOLD=85)` / `metadata_time=sub_score 高 + is_ironclad=true` → `formula_total ≥ 85(铁证升级)→ risk_level=high` 的**假阳围标判定**(CH-1 prod 版分数体感 62.5 是 metadata_author 早期版本未含 last_saved_by/company 维度,CH-1 已修;现版 100 + iron=true)。工程监理等行业中,使用招标方下发的模板投标是合法合规行为,系统必须识别"同模板"并对受模板污染的维度做**分数剔除/降权 + 铁证抑制**,否则误伤所有合规投标人。

Q1 产品决策 = **A 方案**(metadata 簇识别 + 维度剔除/降权);Q2 产品决策 = **删掉 D 兜底**(在现有 DIMENSION_WEIGHTS 下 D5 数学不可达,且 A 已覆盖核心场景;若未来 A 漏识别出现假阳 → follow-up 再开新 change 加兜底)。

## What Changes

- 新增**模板簇识别(template cluster detection)**预处理步骤,在 `judge.judge_and_create_report` 内、PC/OA 加载完成后、第一次 `_compute_dims_and_iron` / DEF-OA 写入完成后、`_apply_template_adjustments` 调用前,基于 bidder 的 `document_metadata.author` + `doc_created_at` 同值跨 bidder 匹配 → 判定"模板簇"成员
- 扫描粒度:每个 bidder 取其 `file_role in {"technical", "construction", "bid_letter", "company_intro", "authorization", "pricing", "unit_price"}` 的 BidDocument 对应的 DocumentMetadata 集合(覆盖 docx + xlsx 两类承载模板的文件,排除 `qualification` PDF 噪音 + `other` 无效分类);跨 bidder 用**集合相交非空**判簇(非单一 key 相等,避免一 bidder N 份文档时语义模糊)。`file_role` 枚举值与 `parser/llm/role_classifier.py::VALID_ROLES` 对齐
- 命中模板簇的 bidder 对:**剔除** `structure_similarity` / `style(global)` / `metadata_author` / `metadata_time` 四维的分数贡献(PC.score→0 / OA.score→0);**同步清除** 这些维度 PC 的 `is_ironclad=false` + OA `evidence_json.has_iron_evidence=false`(铁证源是模板本身不是围标行为),evidence_json 保留 `raw_is_ironclad` 作审计
- 命中模板簇的 bidder 对:`text_similarity` 保留但 **降权 ×0.5**;**豁免条款**:若 text_similarity PC `is_ironclad=true`(LLM 段级判定 ≥3 段或 ≥50% 段为 `plagiarism` 类,详见 `text_sim_impl/aggregator.py::compute_is_ironclad`,说明模板之外仍有大量真抄袭)→ 不降权保留原分
- style(global)分支:**所有** bidder 都在同一簇 → OA.score=0 + is_ironclad 抑制;**部分** bidder 在簇 → 保留原分(先期简化,N-gram 精细化留 follow-up)
- `_compute_dims_and_iron` / `_has_sufficient_evidence` / `summarize` (LLM 路径,经 `_run_l9` 透传)**各自扩 1 个 keyword-only 可选参数** `adjusted_pcs / adjusted_oas`(均默认 None 向后兼容);本 change 调用点显式传入两 dict,各 helper 优先读 adjusted 再回落 ORM raw。`_compute_formula_total` **不扩 kwarg**(其签名仅消费 `per_dim_max + has_ironclad`,不读 PC/OA 字段,由调用方决定喂 raw 还是 adjusted)。**`compute_report` 签名保持不变**(主 spec L268 + L2843 既有契约 + 2 条 L1 signature_unchanged 测试不破);adjusted dict 消费下沉到底层 helper(production path `judge.py:235` 直调 helper,`compute_report` 仅作纯函数测试入口)。`_has_sufficient_evidence` 内部:(a) 铁证短路读 dict 中调整后的 is_ironclad/has_iron_evidence;(b) 信号判定分母从 `AgentTask.score` 切到 `OverallAnalysis.score`
- `AnalysisReport` 新增 `template_cluster_detected: bool` + `template_cluster_adjusted_scores: JSONB`(clusters + adjustments 原始 vs 调整对照,可观测性)
- spec delta:`detect-framework` **ADD 2 Req**(模板簇识别 / 模板簇维度剔除/降权与铁证抑制)+ **MOD 1 Req**("证据不足判定规则",新增 adjusted_scores 可选参数 + 分母切换条件)
- **纯后端 change**:不改前端 UI、不加 badge 标注。**对比页(api/routes/compare.py)继续展示原始 PC 分数**(审计原始信号优先,前端不消费 `template_cluster_adjusted_scores` JSONB);report 页 total_score 与对比页 PC 原始分**短期内会自相显示矛盾**(report total 偏低 vs PC 原始 100),用户可从 `template_cluster_detected=true` 自查;follow-up 加对比页 badge 标注模板簇命中维度

## Capabilities

### Modified Capabilities
- `detect-framework`: 新增模板簇识别预处理 + 维度剔除/降权规则 + 铁证抑制 + 证据充分判定分母切换

## Impact

**代码**:
- `backend/app/services/detect/template_cluster.py`(新建)— `_detect_template_cluster` + `_apply_template_adjustments` 纯函数
- `backend/app/services/detect/judge.py` — 在 PC/OA 加载后、`_compute_dims_and_iron` 之前(实际 6 步顺序见 design D5)接入 template cluster 预处理
- `backend/app/services/detect/judge_llm.py::_has_sufficient_evidence` — 签名扩 `overall_analyses` 参数,分母从 `AgentTask.score` 切到相应维度的 `OverallAnalysis.score`
- `backend/app/models/analysis_report.py` — 新增 `template_cluster_detected` BOOLEAN NOT NULL DEFAULT FALSE + `template_cluster_adjusted_scores` JSONB NULL
- `backend/app/schemas/analysis_report.py` — `AnalysisReportResponse` 同步加 optional 字段
- alembic 0012 migration — 加两字段

**spec**:
- `openspec/specs/detect-framework/spec.md` — ADD 2 Req(模板簇识别 / 模板簇维度剔除/降权与铁证抑制)+ MOD 1 Req("证据不足判定规则",扩 adjusted_scores 可选参数 + 分母切换条件)

**测试**:
- L1:模板簇识别纯函数(metadata 集合相交判簇 / file_role 过滤 / metadata 缺失兜底 / tz 归一化)+ adjustment 纯函数(四维剔除 / is_ironclad 抑制 / text_sim 降权 + 铁证豁免 / style 部分覆盖保留)+ `_has_sufficient_evidence` 新签名
- L2:3 供应商 golden zip(mock agent 高分 + 同 metadata)跑完 → `template_cluster_detected=true` / adjustments 含四维 + text 降权 / `risk_level in ("low", "indeterminate")`
- L3:**跑全套 L3 e2e 作回归网保护**(report 页 total 与对比页 PC 原始分自相矛盾的 UX 缝隙需 L3 兜底);若 L3 历史有 flaky 按 CLAUDE.md flaky 条款降级凭证

**兜底**:
- metadata 查询异常/缺失 → `_detect_template_cluster` 返空 + ERROR 日志,走原打分路径(不阻塞)
- 模板簇识别失败(metadata 全 NULL)→ 无 adjustment,与本 change 不存在时等价

**依赖**:CH-1 归档已提供干净 identity_info + 完整 document_metadata author/created_at 落库。无前端改动、无新 LLM 调用、无新第三方依赖。
