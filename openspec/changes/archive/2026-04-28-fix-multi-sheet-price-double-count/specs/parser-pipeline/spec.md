# spec delta: parser-pipeline (fix-multi-sheet-price-double-count)

## MODIFIED Requirements

### Requirement: XLSX 报价表结构识别

系统 SHALL 通过 LLM 分析 XLSX 文件**所有候选价格表 sheet** 的前 5~8 行预览,输出 `sheets_config` 数组(权威字段)。每个候选 sheet 项 MUST 包含:`sheet_name` / `header_row` / `column_mapping`(6 列字母映射 + skip_cols)/ **`sheet_role`(本 change 新加)**。

**`sheet_role` 三值枚举**:
- `main`:主报价 sheet;参与总价 SUM 计算
  - 工程量清单场景:每个独立分项 sheet 都标 main
  - 监理 / 咨询 / 人月报价:仅"主报价表"标 main
- `breakdown`:跟某 main sheet 同一笔钱的明细分解;**不参与** SUM,但 price_items 仍入库供 UI 展示和审计
  - 监理标"管理人员单价表"(主报价的人月分解)典型 breakdown
- `summary`:整 sheet 都是汇总性质;不参与 SUM(future 扩展占位)

**LLM 输出兜底**(parse 阶段):
- 缺 `sheet_role` 字段:单 sheet 默认 `main`;多 sheet 第一个默认 `main`,后续默认 `breakdown`;log warning
- 非法值(不在三枚举内):默认 `main` + log warning
- 严格 enum 校验由 `price_rule_detector.py` 完成;invalid 入库不可能

**老数据 backward compat**:既有 `sheets_config` 项缺 `sheet_role` 字段时,SQL 层 COALESCE 默认 `main`(行为同改前)。alembic upgrade 会显式回填 `'main'` 到所有现存项。

#### Scenario: 监理标多 sheet 模板 LLM 标 main+breakdown
- **WHEN** xlsx 含 sheet1=「报价表」(1 行总价 X)+ sheet2=「管理人员单价表」(5 行 SUM=X)+ sheet3=「人员进场计划」(无报价数据)
- **THEN** LLM 返 `sheets_config = [{sheet1, sheet_role:"main"}, {sheet2, sheet_role:"breakdown"}]`,sheet3 不在 sheets_config(prompt 已 exclude 非数据 sheet)

#### Scenario: 工程量清单多 sheet 全 main
- **WHEN** xlsx 含 sheet1=「土建」+ sheet2=「安装」+ sheet3=「电气」,各 sheet 独立分项 SUM 不同
- **THEN** LLM 返 `sheets_config = [{sheet1, sheet_role:"main"}, {sheet2, sheet_role:"main"}, {sheet3, sheet_role:"main"}]`

#### Scenario: LLM 漏 sheet_role 字段(老 prompt 输出)
- **WHEN** LLM 返 `sheets_config = [{sheet1}, {sheet2}]`(无 sheet_role)
- **THEN** parser 默认 sheet1=main, sheet2=breakdown(多 sheet 默认规则);写入 DB 后 sheet_role 字段就位

#### Scenario: LLM 返 sheet_role 非法值
- **WHEN** LLM 返 `sheets_config = [{sheet1, sheet_role:"primary"}]`("primary" 不是合法 enum)
- **THEN** parser 默认改 main + log warning;sheets_config 入库为 `{sheet1, sheet_role:"main"}`

---

### Requirement: 报价表数据抽取规则(fill_price)

系统 SHALL 按 `price_parsing_rule.sheets_config` 数组从 XLSX 抽取 `price_items` 行。每个 `sheet_config` 独立处理,异常隔离(单 sheet 异常仅记 partial_failed,不影响其他)。每行抽 6 字段(item_code / item_name / unit / quantity / unit_price / total_price);全空 → skip;长备注 / 序号列污染 / **汇总行(本 change 新加)**有专门 skip 规则。

**汇总行 skip 规则(本 change 新加)**:
- 关键字常量集 `PRICE_SUMMARY_KEYWORDS = ("合计", "汇总", "小计", "总计", "总额", "总价")`
- 触发条件:`item_name`(strip 后)以任一关键字**开头或完全等于**关键字 **AND** `unit_price` 为空(None / 空串)
- 触发 → return None;该行不入 price_items
- **保护真分项**:有 `unit_price`(典型分项行有"单价 × 数量 = 合价")→ 不杀。汇总行通常没单价(只是各分项 sum),用 unit_price IS NULL 是更精确的特征(比"≤ 1 个数值非空"更稳健 — 实测监理标合计行 qty=大杂烩28 + tp=456000 共 2 个非空,但 up=None 仍被正确识别)

**触发顺序**:row_extract → 备注 sentinel → 备注长文本 → **汇总行(新)** → 序号列 item_code 置空 → 数值归一化

#### Scenario: 监理标 Sheet2 row 9 "合计" 行被 skip(qty 大杂烩 case)
- **WHEN** row 抽出 `item_name="合计"`,quantity=28(各分项月数加和大杂烩),unit_price=null,total_price=456000
- **THEN** unit_price 为空 → 触发汇总行 skip → return None,不入库

#### Scenario: "合计费用"真分项保留
- **WHEN** row 抽出 `item_name="合计费用"`,quantity=10,unit_price=1000,total_price=10000
- **THEN** unit_price 非空 → 不杀(真分项 单价×数量=合价)

#### Scenario: "总价" 短词加合价无单价
- **WHEN** row 抽出 `item_name="总价"`,total_price=500000(unit_price 空)
- **THEN** 触发汇总行 skip(关键字命中 + unit_price 为空)→ return None

---

## ADDED Requirements

### Requirement: Sheet 角色数值一致性校验(F 兜底)

系统 SHALL 在报价回填(`fill_price_from_rule`)之后、报价聚合(`aggregate_bidder_totals`)之前,运行 deterministic 数值兜底校验,纠正 LLM `sheet_role` 误判。

**算法**:
1. 按 `sheet_name` group `price_items`,算每 sheet 的 `raw_sum = sum(total_price)`(NULL 忽略)
2. 找所有"潜在重复表达"对:任意两 sheet 的 SUM 在 ε 容差(默认 0.01,即 1%)内相等 + 两 SUM 都 > 0
3. 对每对 (sheet_a, sheet_b):
   - 若 LLM 已明确标 main+breakdown / main+summary → **不动**(LLM 已对)
   - 若 LLM 都标 main 或都缺 → **兜底**:行数少的为 main,行数多的为 breakdown;log warning
   - 若行数相等 + SUM 相等(罕见) → 保留 LLM 第一个为 main;log warning(留人工审计)

**修正后**:UPDATE `price_parsing_rules.sheets_config` 持久化新 sheet_role + 写一条 `audit_logs` 记录(action=`sheet_role_validator_fix`,details 含 before/after 对比)。

**纯函数 invariant**:`validate_sheet_roles(sheets_config, price_items)` 不直接写 DB;返修正后的 sheets_config 副本;调用方负责持久化。便于测试 + 复用(future 可在 admin UI manual save 时也调).

#### Scenario: 监理标场景 LLM 都标 main F 兜底纠正
- **WHEN** sheets_config = [{sheet1, role:main}, {sheet2, role:main}](LLM 误判);sheet1 SUM=456000 (1 行) + sheet2 SUM=456000 (5 行)
- **THEN** F 检测到两 SUM 相等 + 都 main → 行数少 (sheet1=1) 为 main,行数多 (sheet2=5) 为 breakdown;sheets_config 修正为 [{sheet1, role:main}, {sheet2, role:breakdown}];audit_logs 记一条;aggregate_bidder_totals SUM=456000

#### Scenario: 工程量清单 SUM 不等不动手
- **WHEN** sheets_config 三个 main(土建/安装/电气);各 sheet SUM 不等(土建=100k,安装=200k,电气=50k)
- **THEN** F 不触发(无 SUM 相等的 pair);sheets_config 不变;aggregate SUM=350k

#### Scenario: LLM 已明确标 main+breakdown F 信任不动
- **WHEN** sheets_config = [{sheet1, role:main}, {sheet2, role:breakdown}];SUM 相等
- **THEN** F 检测到 SUM 相等但 LLM 已分清 → 不动;sheets_config 保留;aggregate SUM=sheet1.sum

#### Scenario: 行数相等 + SUM 相等罕见 case 保留 LLM
- **WHEN** sheets_config = [{sheet1, role:main}, {sheet2, role:main}];sheet1 与 sheet2 各 3 行 + SUM 都 = 100k
- **THEN** F 不能判定主表,保留 LLM 第一个为 main(stable order)+ log warning;运维需人工审 audit_logs 决定

---

### Requirement: 报价聚合仅 SUM main 角色 sheet

`aggregate_bidder_totals(session, project_id, cfg)` 与 `compare_price` 底部"总报价"行 MUST 共用同一过滤逻辑:仅 SUM `price_items` 中其 sheet 在 `sheets_config` 里 `sheet_role='main'` 的行。COALESCE 兼容缺字段老数据(默认 main,行为同改前)。

**SQL 实现**(共用 helper `is_main_sheet_clause()`):
```sql
EXISTS (
    SELECT 1 FROM jsonb_array_elements(price_parsing_rules.sheets_config) AS sc
    WHERE sc->>'sheet_name' = price_items.sheet_name
      AND COALESCE(sc->>'sheet_role', 'main') = 'main'
)
```

**Detector 算法不变**:`price_anomaly` / `price_overshoot` / `price_total_match` 三 detector 仍消费 `aggregate_bidder_totals(SUM)`,SUM 来源变干净后自动正确;无 detector 代码改动。

#### Scenario: aggregate_bidder_totals 监理标 main+breakdown
- **WHEN** bidder 有 2 sheet:sheet1=main(456k 1 行)+ sheet2=breakdown(456k 5 行 + 合计 1 行 = 6 行 SUM 912k)
- **AND** 汇总行已被 fill_price 阶段 skip(sheet2 实际入库 5 行 SUM=456k)
- **THEN** aggregate_bidder_totals 仅 SUM sheet1 行 → bidder.total_price = 456k

#### Scenario: compare_price 底部总报价同源
- **WHEN** /api/projects/{pid}/compare/price 返回
- **THEN** items[*].cells[bidder].total_price 仍展示**所有 sheet** 的原始 total_price(供 UI 主体展示和审计;含 breakdown 行)
- **AND** items[*].totals[bidder] 底部"总报价"行只 SUM main sheet 的 total_price = 与 aggregate_bidder_totals 数值**完全相等**(L1 invariant 锁)

#### Scenario: 老数据缺 sheet_role 字段 backward compat
- **WHEN** 既有项目 sheets_config 数组项缺 sheet_role 字段
- **THEN** SQL COALESCE 默认 'main' → 全部计入 SUM(行为同 fix 前;不破坏 backward compat);alembic upgrade 后所有项显式填 'main',COALESCE 路径仅作 future safety net
