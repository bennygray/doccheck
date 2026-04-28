# fix-multi-sheet-price-double-count — Manual 凭证

## 时间 + 关联
- 时间: 2026-04-28
- 关联调查:本 change 解决的是 fix-bug-triple-and-direction-high → walkthrough 暴露的"报价 SUM 3x 虚高"根因 bug
- 历经 6 次相关 patch 未解决(parser-pipeline / parser-accuracy-fixes / detect-template-exclusion / fix-llm-timeout-default-followup / fix-section-similarity-spawn-loop / fix-bug-triple-and-direction-high / fix-unit-price-orphan-fallback)
- 5 阶段深度调查后定位**架构层抽象错误**(PriceItem 扁平模型对"多视角同钱"场景概念盲区)

## 根因

招标方下发的监理标 xlsx 模板含 3 sheet:报价表 / 管理人员单价表 / 人员进场计划。
- 报价表 1 行 = 委托监理总价 X(456,000)
- 管理人员单价表 5 行 = X 的人月明细分解(SUM=X)
- Sheet 2 row 9「合计」= 明细的汇总行(value=X)

**3 视角描述同一笔钱**,但 sheets_config 把所有 sheet 都当独立报价 SUM,加上汇总行也入库 →
SUM = X + X + X = **3X** 虚高 → price_overshoot 铁证级 detector 假阳性高风险。

## 修复(三层防线)

| 层 | 类型 | 文件 |
|---|---|---|
| **A** 汇总行 deterministic skip | row 级 / 始终生效 | `fill_price.py` 关键字+unit_price 为空 → skip |
| **B** LLM sheet_role 显式分类 | sheet 级 / LLM | `prompts.py` 加 sheet_role 字段 + `price_rule_detector.py` 解析 |
| **F** 数值关系兜底校验 | sheet 级 / deterministic | 新建 `sheet_role_validator.py` |
| **下游 SUM 过滤** | SQL 级 | `aggregate_bidder_totals` + `compare_price` 共用 `is_main_sheet_clause` |
| **alembic** | 数据迁移 | 0013 backfill `sheet_role='main'` |

## 测试结果

| 套件 | 结果 |
|---|---|
| L1 backend pytest unit | ✅ **1223 passed / 8 skipped**(原 1182 + 新 41) |
| L1 frontend tsc + Vitest | (本 change 零前端改动,跳过) |
| L2 backend e2e | ✅ **291 passed / 2 skipped**(原 286 + 新 5)|
| L3 manual walkthrough | ✅ 见下文 |

## L3 实测(项目 id=3295,3 真实供应商 zip)

### 修前(2026-04-28 早上 walkthrough)
| 投标人 | sheet1 主表 | sheet2 明细+合计 | flat SUM | 报告底部"总报价" |
|---|---|---|---|---|
| 供 A | 1 行 / 456k | 6 行 / 912k | **1,368,000** ❌ | 1,368,000 ❌ |
| 供 B | 1 行 / 486k | 6 行 / 972k | **1,458,000** ❌ | 1,458,000 ❌ |
| 供 C | 1 行 / 674.8k | 6 行 / 1,349.6k | **2,024,400** ❌ | 2,024,400 ❌ |
- price_overshoot(max_price=2,000,000)假阳性触发铁证(供 C 2,024k > 2,000k)

### 修后(本 change)
| 投标人 | sheet1 主表 (main) | sheet2 明细 (breakdown) | aggregate SUM 仅 main |
|---|---|---|---|
| 供 A | 1 行 / 456k | 5 行 / 456k | **456,000** ✅ |
| 供 B | 1 行 / 486k | 5 行 / 486k | **486,000** ✅ |
| 供 C | 1 行 / 674.8k | 5 行 / 674.8k | **674,800** ✅ |

- A 汇总行被 skip:管理人员单价表 6 行 → 5 行(合计行不入库,sum 由 912k 削到 456k)
- B LLM 正确分类:报价表=main / 管理人员单价表=breakdown(看 [agent_tasks.json](agent_tasks.json) `price_parsing_rules.sheets_config`)
- 下游过滤:`aggregate_bidder_totals` 仅 SUM main sheet → 真实价 456k/486k/674.8k
- price_overshoot=0 score(674.8k < 2M),price_total_match=0 score(三家不同),**不再误触发**

## 截图

| 截图 | 验证点 |
|---|---|
| [01-project-detail-completed.png](01-project-detail-completed.png) | 项目详情页 Tag=已完成,3 投标人 priced |
| [02-report-overview.png](02-report-overview.png) | 报告总览(总分变化反映真实价) |
| [03-dimensions-detail.png](03-dimensions-detail.png) | 维度明细 — price_overshoot **不在铁证区**(score=0) |
| [04-compare-price-real-totals.png](04-compare-price-real-totals.png) | **报价对比页底部"总报价" = 456,000 / 486,000 / 674,800**(核心证据)|
| [05-compare-overview.png](05-compare-overview.png) | 对比总览 pair-level 维度 |

## 数据 dump
- [agent_tasks.json](agent_tasks.json):27 task 完整状态(13 unique agents);price_overshoot/price_total_match 都 score=0
- [report.json](report.json):报告 v1 完整 dimensions

## 关键发现 / 副作用

1. **prompt 加长导致 LLM 超时** — 第一次 walkthrough 失败(LLM 300s 超时),把 sheet_role 说明 + 2 长示例去掉后正常;现 prompt 简短(规则 3 行 + 字段说明 3 行)
2. **L1/L2 fixture 都需补 sheets_config[].sheet_role='main'** — 非破坏性,backward compat 默认 main 兜底,现存数据 alembic upgrade 自动回填

## ⚠️ Follow-up(本次未做,登记 backlog)

- Admin UI sheet_role 编辑器(LLM+F 错时人工纠正)
- D 方案 BidderTotalPrice 独立模型层(若 b' 还有边缘漏)
- 工程量清单场景的 e2e 真实 fixture(本 change 用 mock 数据;监理标用 3 真实供应商 zip 验证)
- AI 综合研判 LLM 文本英文 key 本地化(已在 backlog)

## 凭证文件
- README.md(本文件)
- 5 张截图
- agent_tasks.json + report.json

## 相关
- proposal: `openspec/changes/fix-multi-sheet-price-double-count/proposal.md`
- design: `openspec/changes/fix-multi-sheet-price-double-count/design.md`
- tasks: `openspec/changes/fix-multi-sheet-price-double-count/tasks.md`
- spec delta: `openspec/changes/fix-multi-sheet-price-double-count/specs/parser-pipeline/spec.md`
