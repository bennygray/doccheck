# proposal: fix-multi-sheet-price-double-count

## Why

**症状**:`fix-bug-triple-and-direction-high` 引入 `price_overshoot` 后,2026-04-28 walkthrough(供应商A 单家独立 bidder,真实总报价 456,000)实测后端 `price_items` 表入库 7 行 SUM=1,368,000 — **3 倍虚高**。3 家供应商使用招标方下发的同一监理标模板,**3 家全触发**,直接导致 price_overshoot 铁证级 detector 假阳性高风险报告。

**深度调查** [docs/handoff.md backlog 已记录]证实:

1. **架构假设错位**:`parser-pipeline`(M2 初始)+ `parser-accuracy-fixes` P1-5(多 sheet 候选)的设计前提是「多 sheet = 独立分项加和」(工程量清单场景),但监理 / 咨询 / 人月报价场景里**多 sheet 是同一笔钱的多视角**:
   - Sheet1「报价表」1 行 = 委托监理总价 X(456,000)
   - Sheet2「管理人员单价表」5 行 = X 的人月明细分解(SUM=456,000)
   - Sheet2 row 9「合计」= 明细的汇总行(456,000)
   - SUM(7 rows) = X + X + X = **3X** ❌

2. **历次 patch 都打在错的层** — 6 次 parser/price 相关 change(M2 初始 / parser-accuracy-fixes P1-5/6/7 / detect-template-exclusion / fix-unit-price-orphan-fallback / fix-bug-triple-and-direction-high)反复处理边缘症状(备注行 / 序号列 / 跨文件不混合 / 模板簇 metadata),**没人挑战 PriceItem 扁平模型**对"多视角同钱"场景的概念盲区。

3. **fix-unit-price-orphan-fallback 作者已意识到根因但 scope 局限**:proposal 明文写"主表+子表重复求和会触发 price_overshoot 误报",但只覆盖**跨文件 file_role**维度,没把**同 xlsx 多 sheet** 维度纳入。

**为什么不再"再打一个 patch"**:price 相关已经累积 6 次 patch,每次都是边缘清理。再打一次 patch(只杀汇总行)只削 1/3 重复(剩 2x),不解根因。本 change 直接动 sheets_config schema 加 `sheet_role` 语义角色,让 detector 拿到的"总价"语义干净。

## What Changes

**3 个组件 + 1 alembic + 1 下游过滤**(纯后端;前端 UI 仅 PriceComparePage 底部"总报价"展示同步):

### A. 汇总行 deterministic 识别(局部止血)
- `fill_price.py::_extract_row` 加规则:`item_name` 含汇总关键字(`合计 / 汇总 / 小计 / 总计 / 总额 / 总价`)且数值字段(qty/up/tp)≤ 1 个非空 → skip
- 关键字常量化为 `PRICE_SUMMARY_KEYWORDS`,future 可调
- 不依赖 LLM,**deterministic 兜底**

### B. LLM sheet_role 语义分类(根因解)
- `prompts.py::PRICE_RULE_SYSTEM_PROMPT` 加要求:每 `sheets_config` 项必须含 `sheet_role: "main" | "breakdown" | "summary"` 字段
  - **main**:主报价表 / 独立分项(SUM 计入总价)
  - **breakdown**:跟某 main sheet 同钱的明细分解(不计入 SUM,但入库供 UI 展示)
  - **summary**:汇总型 sheet(整 sheet 都是 summary 性质,不计入 SUM)
- `price_rule_detector.py` 解析 + enum 校验;invalid → 默认 `main` + log warning
- `price_parsing_rules.sheets_config` schema 每项加 `sheet_role` 字段;alembic migration 老数据默认 `main`

### F. 数值关系兜底校验(deterministic safety net)
- 新建 `app/services/parser/pipeline/sheet_role_validator.py`
- 算每个 sheet 的 raw SUM(从 fill_price 得出的 price_items 按 sheet_name group)
- 若两个 sheet 的 SUM 在 ε 容差(默认 1%)内相等 → 标"潜在重复表达"
- 取 LLM 标 `main` 优先;若 LLM 都没标 main 或都标 main → 取行数少 + 数值大者(主表特征:行少、值整、大);log warning + 把决策写 evidence
- 若 SUM 不等(真分项场景)→ 不动手,保留 LLM 分类
- 这是 LLM 失败兜底的 deterministic 校验,与 LLM 双保险

### 下游 SUM 过滤
- `agents/anomaly_impl/extractor.py::aggregate_bidder_totals` SQL 改:JOIN `price_parsing_rules` + JSONB filter,仅 SUM `sheet_role='main'` 行的 total_price
- `/compare/price` 底部"总报价"行也用同样过滤(保持 UI / API 同源)
- **detector 算法 0 改动**(price_anomaly / price_overshoot / price_total_match 自动受益)

### Alembic
- New migration 添加 `price_parsing_rules.sheets_config[*].sheet_role` 字段(JSONB array elements 内字段;无需新 column)
- 数据迁移:既有 `sheets_config` 项里没 sheet_role 的全部默认 `"main"`(行为同现状)

## Capabilities

- `parser-pipeline`:
  - **MODIFIED** "XLSX 报价表结构识别":`sheets_config[*]` 加 `sheet_role` 字段 + 容错默认
  - **MODIFIED** "报价表数据抽取规则(fill_price)":汇总行 skip 规则
  - **ADDED** "Sheet 角色数值一致性校验":F 模块 deterministic post-check
- `detect-framework`:**不动**(detector 算法不变,上游数据干净后自动好)

## Impact

### Code
- **新建**:`app/services/parser/pipeline/sheet_role_validator.py`(~80 行)
- **改**:`app/services/parser/llm/prompts.py`(prompt 加 sheet_role 字段说明 + 反例)
- **改**:`app/services/parser/llm/price_rule_detector.py`(解析 + enum 校验,~15 行)
- **改**:`app/services/parser/pipeline/fill_price.py`(汇总行 skip 规则,~20 行)
- **改**:`app/services/parser/pipeline/rule_coordinator.py`(调用 validator,~10 行)
- **改**:`app/services/detect/agents/anomaly_impl/extractor.py`(aggregate_bidder_totals SQL JOIN + JSONB filter,~25 行)
- **改**:`app/api/routes/compare.py`(compare_price 底部"总报价"过滤,~15 行)
- **改**:`app/models/price_parsing_rule.py`(schema 注释 + JSONB 模式说明,无 column 改动)
- **迁移**:新 alembic version `00XX_sheet_role.py`(JSONB 数据迁移)

### Spec
- `parser-pipeline` 2 MOD + 1 ADD Requirement

### 测试
- L1 新增 ~25 case
- L2 新增 3 fixture(监理标 / 工程量清单 / LLM 错兜底)
- L3 manual 重跑 walkthrough,验"总报价 = 真实价"

### 依赖
- 不升级 LLM provider / SDK
- 不新增 PyPI 包

### 部署
- alembic `alembic upgrade head` 自动迁移
- LLM prompt 改动 → 真实 LLM 输出可能略不同,**首次部署后 admin/rules 页面手动 confirm 一次现有项目的 sheet_role**;新项目自动按新 prompt 走

## Non-Goals(本 change 不做)

- Admin UI sheet_role 编辑器(PriceRulesPanel 加下拉选项)— follow-up,等 LLM+F 实测准确率不够再上
- D 方案 BidderTotalPrice 独立模型层 — follow-up,等 (b') 还有边缘漏再上
- AI 综合研判 LLM 文本中英文 key 本地化(已在 backlog)
- 抽 dimensionLabels.ts util(已在 backlog)
