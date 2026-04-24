## Why

上一个 change `fix-mac-packed-zip-parsing` 用真实 A/B zip 验收后暴露出一层**产品语义层**的缺陷 — 即使数据链路修好,"检测结果"仍可能在系统层面"沉默失败",以误导性结论输出给用户:

1. 所有 agent 打分全零时,LLM judge 仍给"低风险,无围标"结论,用户看不到"其实啥信号都没跑出来"
2. 投标人 `identity_info` LLM 抽取失败 = NULL 时,下游 `error_consistency` 维度直接 downgrade 不运行,但 UI 完全沉默,用户不知道这里少了一个维度
3. LLM 角色分类失败进关键词兜底时,"价格标""资信标""业绩"这类行业标准术语未在关键词表里,全部命中 `other`
4. `/analysis/status` 看到所有 agent 进终态就以为检测完成,但 judge 阶段(LLM 调用 + DB 写报告)还在跑,客户端拿到 404 `/reports/{v}` 以为出错
5. 投标人详情页 `.zip` 归档行和真文档平铺,上一个 change 往上挂的"已过滤 N 个打包垃圾文件"审计文本被埋在视觉噪音里

这些都是"用户看得到的诚实性"问题,不是基础设施问题(后者归下一个 change `harden-async-infra`)。

## What Changes

- **BREAKING(前向兼容):** `risk_level` 枚举新增 `indeterminate` 值,DB schema + Pydantic Literal + 前端 Union + Word 模板 + 复核 API 所有读该字段的点**必须**显式处理新值;老数据 `high/medium/low` 零影响
- 新增 judge 层"证据不足"判定:非 skipped 的 agent 全部 score=0 → 跳过 LLM 调用,直接设 `risk_level=indeterminate` + `llm_conclusion="证据不足,无法判定围标风险(有效信号维度全部为零)"`
- 新增 `BidderResponse.identity_info_status: 'sufficient' | 'insufficient'` 计算字段;前端投标人详情 Drawer 顶部 + 报告 `error_consistency` 维度区 + Word 导出报告段落 3 处按状态显示降级文案
- 三处 `ROLE_KEYWORDS` 副本(`parser/llm/role_keywords.py` runtime / `parser/llm/prompts.py` LLM prompt 描述 / `admin/rules_defaults.py` admin 默认值)同步扩充 10 个行业术语;顺手补齐 `rules_defaults.py` 原本缺失的 `authorization` 条
- `AnalysisStatusResponse` 新增 `report_ready: bool` 字段,客户端区分 "agent 跑完但 judge 在跑" vs "完全结束"
- 投标人详情页 `FileTree.tsx` 的 `.zip/.7z/.rar` 归档行用 `antd Collapse ghost`(复用 `DimensionDetailPage` 已有 pattern)默认折叠,展开后展示审计文本

## Capabilities

### New Capabilities

(无;5 个子问题都落在现有 capability 上)

### Modified Capabilities

- `detect-framework`:新增"证据不足判定规则"Requirement;修订"综合研判骨架"插入证据不足前置判定分支;新增"AnalysisReport risk_level 枚举扩展"Requirement;修订"analysis status API"增加 `report_ready` 字段
- `parser-pipeline`:修订"角色关键词兜底规则"加 10 个新词 + 三处副本同步约束(含 `admin/rules_defaults.py` 补 `authorization` 条)
- `report-view`:新增"indeterminate 风险等级渲染"Requirement;新增"身份信息缺失降级 UI"Requirement;新增"归档行默认折叠"Requirement
- `report-export`:新增"Word 模板支持 indeterminate 和 identity_info 缺失降级文案"Requirement

## Impact

- **代码**:
  - Backend:`services/detect/judge_llm.py` / `services/detect/judge.py`(证据不足 + indeterminate);`models/analysis_report.py` + `schemas/reports.py`(枚举扩展);`schemas/bidders.py`(identity_info_status 字段);`schemas/analysis.py` + `api/routes/analysis.py`(report_ready);`services/parser/llm/role_keywords.py` + `services/parser/llm/prompts.py` + `services/admin/rules_defaults.py`(三处关键词同步);`services/export/templates.py` + Word 模板(identity_info 降级文案)
  - Frontend:`types/index.ts`(RiskLevel/ProjectRiskLevel union 加 indeterminate);`pages/projects/ProjectListPage.tsx` + `pages/projects/ProjectDetailPage.tsx` + `pages/reports/ReportPage.tsx` + `components/projects/FileTree.tsx` + `components/reports/ReviewPanel.tsx`(5 处渲染点 + F3 Alert + N8 Collapse)
- **数据库**:`analysis_reports.risk_level` 若当前 PG enum 需 `ALTER TYPE ... ADD VALUE`(Alembic 0011);若 String(20) + check constraint 需改 constraint;现有 high/medium/low 行零影响
- **依赖**:无新增
- **测试**:新增 3 L1 + 2 L2 + 3 L3(flaky → manual 截图兜底);manual 凭证落 `e2e/artifacts/honest-detection-results-2026-04-23/`
- **向后兼容**:schema 扩展是向前兼容的 superset(老客户端读到 indeterminate 会当未知值 fallback);若客户端依赖 `risk_level in ('high','medium','low')` 会走 fallback 分支,需要前端同步发布
