# L3 凭证:fix-unit-price-orphan-fallback

**Change**:`fix-unit-price-orphan-fallback`
**Date**:2026-04-28
**HEAD commit at L3 run**:`ea447c29c7d6bd2e216b68c8863344bb76b8afe6`(归档 commit 含本 change 实施代码)
**Project ID**:3066(`e2e-fallback-2026-04-28` / `L3-FALLBACK-001`)
**Backend**:`http://127.0.0.1:8001`
**Frontend**:`http://localhost:5173`
**LLM**:本地火山 ark `ark-code-latest`(主路径模型,**不**复现服务器 DeepSeek 的 unit_price 误判)

---

## L3 范围与限制(必读)

本 change 修复的 bug 在服务器 DeepSeek 模型下 100% 复现,在本地火山 ark 模型下从不复现。本次 L3 用本地 ark 走真实 UI,目的是:

1. ✅ **验证主路径无回归**:fallback 改动不应破坏"LLM 正确判 pricing"的 happy path
2. ❌ **不能直接验证 fallback 触发后的 UI 表现**:本地 ark 不会判 unit_price,fallback 路径在 L3 不会被触发

**fallback 路径本身的正确性已经在 L1+L2 严格覆盖**:
- L1 12/12 passed:`backend/tests/unit/test_pricing_xlsx_fallback.py`(4 Scenario × 2 helper + 对称性 + sheet mismatch)
- L2 2/2 passed:`backend/tests/e2e/test_parser_pipeline_api.py::test_pipeline_unit_price_fallback` + `test_pipeline_mixed_role_no_double_count`(后者集成跑 `price_overshoot.run` 断言 score=0)

L3 此处的"主路径无回归"是 fallback 修复的**必要补充**,与 L1+L2 互补。

---

## 期望 vs 实际

| 维度 | 期望 | 实际 | 通过 |
|---|---|---|---|
| 上传 3 zip 后 pipeline 跑完 | 3 家全部进 `priced` 终态 | 3 家全 `priced`,无 `parse_error` | ✅ |
| LLM 角色识别 | 3 家 xlsx 全部 `file_role='pricing' confidence='high'` | 一致(本地 ark 行为) | ✅ |
| 报价规则识别 | 项目内 1 条 `confirmed` rule,sheet="报价表" header_row=3 | rule#696 confirmed,完全一致 | ✅ |
| 报价回填行数 | 每家 ≥ 1 行 `price_items` | 每家 7 行 | ✅ |
| 跨 bidder 不重复求和 | aggregate_bidder_totals 返 3 条不同 SUM | 1368000 / 1458000 / 2024400(三家不同) | ✅ |
| UI 项目详情显示 | "已识别 3 / 已回填报价 3 / 100%" | 一致(见截图 01) | ✅ |
| UI 投标人卡片 status tag | 3 家全显示绿色 "已报价" | 一致(见截图 01) | ✅ |
| UI 文件列表对话框 | 4 个文件齐(zip + docx ×2 + xlsx) | 一致(见截图 02) | ✅ |
| 报价规则 UI 编辑器 | 列映射 A/B/D/E/F/G + 保存/重新应用按钮可见 | 一致(见截图 01 底部) | ✅ |

---

## 文件清单

- `01-project-detail-3-priced.png` — 项目详情页:3 家全"已报价" + 100% 进度 + 报价规则展示
- `02-bidder-A-file-list.png` — 供应商 A 文件列表对话框:"文件列表 · 4 个" + 已报价 tag
- `db_evidence.json` — 完整 DB 证据快照(project / bidders / documents / rule / price_items 汇总 + 21 行样本)

---

## 关键 SQL 证据(对应 tasks.md 4.6)

```sql
-- 三家 bidder 全 priced,无 parse_error
SELECT id, name, parse_status, parse_error
FROM bidders WHERE project_id=3066 AND deleted_at IS NULL ORDER BY id;
--   3431 供应商A priced (null)
--   3432 供应商B priced (null)
--   3433 供应商C priced (null)

-- 三家 xlsx 全部正确判 pricing(本地 ark 主路径,**fallback 未触发**)
SELECT bidder_id, file_name, file_role, role_confidence, parse_status
FROM bid_documents WHERE bidder_id IN (3431,3432,3433) AND file_type='.xlsx' ORDER BY bidder_id;
--   3431 工程监理报价表.xlsx                              pricing high identified
--   3432 浙江华建--江苏锂源年产24万吨LFP项目工程监理报价表.xlsx   pricing high identified
--   3433 附件5 工程监理报价表.xlsx                       pricing high identified

-- 项目级唯一 rule,confirmed
SELECT id, status, sheet_name, header_row FROM price_parsing_rules WHERE project_id=3066;
--   696 confirmed 报价表 3

-- 各家 price_items 数 + 总价不同(无重复求和)
SELECT bidder_id, count(*) AS cnt, SUM(total_price) AS total
FROM price_items WHERE bidder_id IN (3431,3432,3433) GROUP BY bidder_id ORDER BY bidder_id;
--   3431 7 1368000.00
--   3432 7 1458000.00
--   3433 7 2024400.00
```

---

## 操作变通(透明记录)

L3 任务 4.3 原计划用 Claude_in_Chrome MCP 的 `file_upload` 工具上传 zip。Chrome 安全策略拒绝了 MCP 程序化上传文件输入(`{"code":-32000,"message":"Not allowed"}`)。改用 HTTP API(`POST /api/projects/{pid}/bidders/`)上传——**项目本身仍通过 UI 创建,3 家投标人状态变化、文件列表、报价规则等 UI 端响应均真实可见(见截图)**。等价性论证:upload endpoint 与 UI 表单走相同的路由,差异仅在调用方(浏览器 vs httpx),pipeline 行为完全一致。
