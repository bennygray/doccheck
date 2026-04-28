# Tasks

> 三层防线(A 行 / B sheet / F 数值)实施 + 下游 SUM 过滤 + alembic 迁移。
> 验收顺序:impl(1-7) → 测试(8-10) → manual(11) → 全量绿(12)。

## 1. A:汇总行 deterministic skip(fill_price.py)

- [x] 1.1 [impl] `fill_price.py` 加常量 `PRICE_SUMMARY_KEYWORDS = ("合计", "汇总", "小计", "总计", "总额", "总价")`
- [x] 1.2 [impl] `_extract_row` 加规则:`item_name`(strip 后)以任一关键字**开头或完全等于**关键字 + 数值字段(qty/up/tp)≤ 1 个非空 → return None;紧跟备注 skip 之后,价值字段解析之前
- [x] 1.3 [impl] 不影响真分项(数值字段 ≥ 2 非空时不杀,如"合计费用 数量=10 单价=N 合价=N")

## 2. B:LLM sheet_role enum + prompt + 解析

- [x] 2.1 [impl] `prompts.py::PRICE_RULE_SYSTEM_PROMPT` 加 sheet_role 字段说明(三值枚举)+ 判定原则 + 监理标/工程量清单 2 个示例
- [x] 2.2 [impl] `prompts.py::PRICE_RULE_USER_TEMPLATE` 输出格式说明加 sheet_role 字段
- [x] 2.3 [impl] `price_rule_detector.py::detect_price_rule`:解析每 sheets_config 项的 `sheet_role` 字段;enum 校验({"main","breakdown","summary"});invalid → 默认 main + log warning
- [x] 2.4 [impl] LLM 漏字段时的默认值规则:单 sheet → main;多 sheet → 第一个 main,后续 breakdown
- [x] 2.5 [impl] `price_rule_detector.py::REQUIRED_MAPPING_KEYS` 不变(sheet_role 不算 column_mapping 的 key,在外层 sheets_config item 字段)

## 3. F:数值关系兜底校验 validator

- [x] 3.1 [impl] 新建 `app/services/parser/pipeline/sheet_role_validator.py`
- [x] 3.2 [impl] `compute_sheet_sums(price_items)` helper:按 sheet_name group sum
- [x] 3.3 [impl] `find_suspect_pairs(sheet_sums, epsilon=0.01)`:返回所有 SUM 1% 容差内相等的 (sheet_a, sheet_b) 对;skip SUM=0 的 sheet
- [x] 3.4 [impl] `validate_and_fix_roles(sheets_config, suspect_pairs, sheet_row_counts)`:
  - LLM 已分清(main+breakdown / main+summary)→ 不动
  - LLM 都 main 或都缺 → 行数少的为 main,多的为 breakdown
  - 行数相等(罕见)→ 保留 LLM 第一个为 main + log warning
- [x] 3.5 [impl] 入口函数 `validate_sheet_roles(rule, price_items_list) -> updated_sheets_config`,**纯函数**(不直接写 DB,返修正后的 sheets_config)
- [x] 3.6 [impl] 触发时机:`run_pipeline.py` 报价回填后 / aggregate 前调用;若有修正 → UPDATE rule.sheets_config + 写一条 audit_logs(action="sheet_role_validator_fix")
- [x] 3.7 [impl] log warning 格式:`"sheet_role validator: {sheet_a}/{sheet_b} SUM≈ ({sum_a}≈{sum_b}); LLM both main → fix to main/breakdown"`

## 4. 下游 SUM 过滤(aggregate_bidder_totals + compare_price)

- [x] 4.1 [impl] 抽 helper `app/services/detect/agents/anomaly_impl/sheet_role_filter.py::is_main_sheet_clause()` — 返回 SQLAlchemy 表达式给 query 用;**单一真相源**避免两处 drift
- [x] 4.2 [impl] `aggregate_bidder_totals` SQL 改:JOIN PriceParsingRule + EXISTS subquery 过滤 sheet_role='main' 的 sheet
- [x] 4.3 [impl] `compare.py::compare_price` 底部"总报价"行同样过滤(用 4.1 的 helper)
- [x] 4.4 [impl] backward compat:JSONB COALESCE(sheet_role, 'main') 默认 main(老数据无字段时不破坏行为)

## 5. price_parsing_rule 模型 + alembic

- [x] 5.1 [impl] `models/price_parsing_rule.py` 注释 sheets_config 字段更新(JSONB array 模式说明加 sheet_role)
- [x] 5.2 [impl] 新 alembic version `00XX_sheet_role.py`:upgrade 把每 sheets_config[*] 加 `sheet_role: 'main'`(若缺);downgrade 移除 sheet_role 字段
- [x] 5.3 [impl] alembic 测试:subprocess 跑 upgrade + downgrade 不抛错 + 数据保留

## 6. admin/rules API 扩字段(只读)

- [x] 6.1 [impl] `app/schemas/price_parsing_rule.py` SheetConfig schema 加 `sheet_role: Literal["main","breakdown","summary"] = "main"` 默认 main
- [x] 6.2 [impl] PUT `/api/projects/{pid}/price-rules/{id}` body 不强制 sheet_role,缺则保留旧值(部分更新)
- [x] 6.3 [impl] GET 返回 sheets_config 含 sheet_role 字段(给 future UI 编辑用)

## 7. run_pipeline 接入 validator

- [x] 7.1 [impl] `run_pipeline.py` 报价回填(`fill_price_from_rule` 之后)调 `validate_sheet_roles(rule, all_inserted_price_items)`
- [x] 7.2 [impl] 若 validator 修正 → 调用 helper 持久化 sheets_config(UPDATE price_parsing_rules)+ 写 audit_logs

## 8. L1 测试

- [x] 8.1 [L1] `test_fill_price_summary_row.py` 6 case(A 汇总行 skip)
- [x] 8.2 [L1] `test_price_rule_detector_sheet_role.py` 5 case(B sheet_role parse + 默认值)
- [x] 8.3 [L1] `test_sheet_role_validator.py` 8 case(F 数值兜底)
- [x] 8.4 [L1] `test_aggregate_filter_main_sheet.py` 4 case(SQL 过滤行为)
- [x] 8.5 [L1] `test_compare_price_main_sheet_filter.py` 2 case(底部"总报价"过滤 + UI 主体仍展示所有 sheets)
- [x] 8.6 [L1] `test_pipeline_invariant.py` 2 case(aggregate vs compare_price SUM 一致 + 监理标 fixture SUM=456000)
- [x] 8.7 [L1] `test_alembic_sheet_role_migration.py` subprocess upgrade/downgrade

## 9. L2 e2e 测试

- [x] 9.1 [L2] `test_e2e_monitoring_template_scenario`:模拟监理标 fixture(报价表 1 行 + 管理人员明细 5+1 行;LLM mock 标 main+breakdown);验 SUM=456000 + price_overshoot 在 max_price=500000 时不触发;在 max_price=400000 时只算 main 触发
- [x] 9.2 [L2] `test_e2e_boq_scenario`:模拟工程量清单(3 个独立分项 sheet,LLM mock 全 main);验 SUM = 三 sheet sum 之和(各自 SUM 不等所以 F 不触发)
- [x] 9.3 [L2] `test_e2e_llm_misclassify_fallback`:LLM mock 返全 main(误判),F validator 兜底将明细分解 sheet 改 breakdown;验最终 SUM 正确

## 10. L2 task_count 不变(回归)

- [x] 10.1 [L2] 既有 e2e fixture 跑过(286 passed 或顺延);agent_task_count=27 不变;无 detector 算法改动

## 11. L3 manual 凭证

- [x] 11.1 [L3] Claude_in_Chrome 重跑 walkthrough:3 真实供应商 zip + max_price=2,000,000(原 walkthrough 配置)
- [x] 11.2 [L3] 截图:报价对比页"总报价"行,验值 = (供 A 真价 / 供 B 真价 / 供 C 真价),不再 3x 虚高
- [x] 11.3 [L3] 截图:维度明细页,price_overshoot 不再误触发(供 C 真价 < max_price)
- [x] 11.4 [L3] 截图:维度明细页 price_total_match 行为(若两家真价相同则触发,不同则不触发)
- [x] 11.5 [L3] 凭证归档 `e2e/artifacts/fix-multi-sheet-price-double-count-<YYYY-MM-DD>/`(README + 4 截图 + agent_tasks_after.json + report.json)

## 12. 全量测试总汇

- [x] 12.1 跑 [L1][L2][L3] 全部测试,全绿
