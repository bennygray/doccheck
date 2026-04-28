# design: fix-multi-sheet-price-double-count

## D-1 决策:三层防线(A 确定性 + B 语义 + F 数值兜底)

| 层 | 类型 | 触发 | 兜底 |
|---|---|---|---|
| A 汇总行 skip | deterministic 规则 | row 级 | 始终生效;独立于 LLM |
| B sheet_role | LLM 概率性 | sheet 级 | LLM 提供 primary 分类 |
| F 数值校验 | deterministic post-check | sheet 间 | LLM 错时纠正 |

**为何不只 B?** LLM 错就裸奔 — 监理标 vs 工程量清单两种场景的 sheet 表头特征近,LLM 必然有时分错。F 是 deterministic 兜底,SUM 数学关系不会骗人。

**为何不只 F?** F 只能识别"两 sheet SUM 相等"模式。若三 sheet 之间复杂关系(主 + 两个不同明细),F 无法定夺谁是主;需要 LLM 给出语义优先级。

**为何还要 A?** 单 sheet 内的"合计"行(本案 Sheet2 row 9)既不是新 sheet 也不是 sheet 间关系,是 row 级污染。F 不管 row,B 不管 row,只能 A 处理。**A + B + F 各管一层,不重叠不冲突。**

## D-2 sheet_role 三值枚举

```python
SheetRole = Literal["main", "breakdown", "summary"]
```

- **main**:主报价 sheet;SUM 计入总价
  - 工程量清单:每个独立分项 sheet 都是 main
  - 监理标:只有「报价表」是 main,「管理人员单价表」不是
- **breakdown**:跟某 main sheet 同钱的明细分解;不计入 SUM,**入库**供 UI 展示和审计
  - 监理标的「管理人员单价表」典型 breakdown
- **summary**:整 sheet 都是 summary 性质;不计入 SUM
  - 现实较少;留作 future 扩展占位(避 main/breakdown 二值过紧)

**默认值规则**(LLM 缺失或 enum 错时):
- 单 sheet:默认 main(zero risk)
- 多 sheet:第一个默认 main,后续默认 breakdown(更接近"主表 + 明细"的常见模式;LLM 应该正确给值,默认只是 last-resort 不破坏行为)

## D-3 prompt 改动详细

新增字段说明 + 反例(避 LLM 误判):

```
sheet_role: "main" | "breakdown" | "summary"
- main:主报价表 / 独立分项;参与总价计算
- breakdown:某主表的明细分解(同一笔钱的不同视角);**不参与**总价计算
- summary:整 sheet 都是汇总性质

判定原则:
- 若 sheet A 的 SUM ≈ sheet B 的 SUM,且 A 项目少 / B 项目多 → A 是 main,B 是 breakdown
- 工程量清单(土建 / 安装 / 电气分别一个 sheet,各自独立分项)→ 全部 main
- 监理服务报价(主表 + 人月明细分析)→ 主表 main,明细 breakdown
```

System prompt 末尾加示例:
```
示例:监理服务报价
sheets_config: [
  {"sheet_name": "报价表", "sheet_role": "main", ...},
  {"sheet_name": "管理人员单价表", "sheet_role": "breakdown", ...}
]

示例:工程量清单
sheets_config: [
  {"sheet_name": "土建工程", "sheet_role": "main", ...},
  {"sheet_name": "安装工程", "sheet_role": "main", ...},
  {"sheet_name": "电气工程", "sheet_role": "main", ...}
]
```

## D-4 F 数值校验算法

```python
def validate_sheet_roles(sheets_config, price_items_grouped_by_sheet):
    """
    Inputs:
      - sheets_config: LLM 给的 sheet_role 标注 list
      - price_items_grouped_by_sheet: dict[sheet_name, list[PriceItem]]
    Output: 修正后的 sheets_config(原地或副本)
    """
    sheet_sums = {sn: sum(pi.total_price for pi in items if pi.total_price is not None)
                  for sn, items in price_items_grouped_by_sheet.items()}

    # 找到所有"潜在重复表达"对(SUM 1% 容差内相等)
    epsilon = 0.01
    suspect_pairs = []
    sheet_names = list(sheet_sums.keys())
    for i in range(len(sheet_names)):
        for j in range(i+1, len(sheet_names)):
            a, b = sheet_names[i], sheet_names[j]
            if sheet_sums[a] == 0 or sheet_sums[b] == 0:
                continue
            ratio = abs(sheet_sums[a] - sheet_sums[b]) / max(sheet_sums[a], sheet_sums[b])
            if ratio <= epsilon:
                suspect_pairs.append((a, b))

    for a, b in suspect_pairs:
        roles = {sn: cfg.get("sheet_role", "main") for sn, cfg in sheets_config_by_name(sheets_config).items()}
        a_role, b_role = roles[a], roles[b]
        # LLM 已经分清楚了 → 信任
        if {a_role, b_role} in ({"main", "breakdown"}, {"main", "summary"}):
            continue
        # LLM 都标 main 或都没标 → F 兜底
        a_rows = len(price_items_grouped_by_sheet[a])
        b_rows = len(price_items_grouped_by_sheet[b])
        # 行数少 + 总价相同 → 主表特征(主表通常 1 行 = 总价;明细 N 行 SUM = 总价)
        if a_rows < b_rows:
            set_role(sheets_config, a, "main")
            set_role(sheets_config, b, "breakdown")
            log_warning(f"F 兜底:{a} → main, {b} → breakdown(SUM 重合)")
        elif a_rows > b_rows:
            set_role(sheets_config, a, "breakdown")
            set_role(sheets_config, b, "main")
            log_warning(...)
        else:
            # 行数相等且 SUM 重合 — 极罕见,保留第一个为 main(stable)
            ...

    return sheets_config
```

**触发时机**:`rule_coordinator.acquire_or_wait_rule()` 写 sheets_config 之前(已有 LLM 结果) — 但当时 price_items 还没生成。需要**两阶段**:
1. 先按 LLM 输出 fill_price 一次(只为算 sheet_sum,不写库)
2. 调 validator 修正 sheet_role
3. 再写库 + fill_price 真正入库

或者**更简方案**:fill_price 时不过滤 sheet_role(全部入库);**aggregate_bidder_totals 在用 sheet_role 过滤前先调 validator 校验**。validator 直接读 price_items 表算 sheet_sum,不需两阶段。

**采用更简方案**:validator 在 aggregate 前(or detect 启动前)运行一次,纠正 sheets_config 入库。fill_price 时不需要管 sheet_role。

但有个边界:validator 修正后如何持久化?— 直接 UPDATE price_parsing_rules.sheets_config JSONB,记 audit_logs 一条。下次 detect 直接读修正后的值。

## D-5 aggregate_bidder_totals SQL 改造

```python
# 旧:
stmt = (select(Bidder.id, Bidder.name, func.sum(PriceItem.total_price).label("total"))
        .select_from(Bidder).join(PriceItem, ...)
        .where(...).group_by(...).order_by(...))

# 新:JOIN price_parsing_rules + JSONB jsonb_path_exists 过滤 sheet_role='main' 的 sheet
stmt = (select(Bidder.id, Bidder.name, func.sum(PriceItem.total_price).label("total"))
        .select_from(Bidder).join(PriceItem, ...)
        .join(PriceParsingRule, PriceParsingRule.id == PriceItem.price_parsing_rule_id)
        .where(
            Bidder.project_id == project_id,
            Bidder.deleted_at.is_(None),
            # JSONB 路径存在性查询:sheets_config 数组里有 sheet_role='main' 且 sheet_name = PriceItem.sheet_name 的项
            text("EXISTS (SELECT 1 FROM jsonb_array_elements(price_parsing_rules.sheets_config) AS sc "
                 "WHERE sc->>'sheet_name' = price_items.sheet_name "
                 "AND COALESCE(sc->>'sheet_role', 'main') = 'main')"),
        )
        .group_by(...).order_by(...))
```

**测试**:L1 SQL fixture 验证:
- sheets_config 有 main + breakdown → 仅 main 行被 SUM
- sheets_config 没 sheet_role(老数据)→ 默认 main → 全部 SUM(backward compat)
- bidder 的 price_items 跨多 rule(多版本)→ 各 rule 独立处理

## D-6 /compare/price 底部"总报价"行同步

`compare.py::compare_price` line 421-432 既有逻辑:`for pi in pi_rows: bid_total += pi.total_price`

改:加 sheet_role 过滤(同 aggregate_bidder_totals):

```python
# 预先按 (project, sheet_name) 算 sheet_role
main_sheet_names = await fetch_main_sheet_names(session, project_id)
# main_sheet_names: set[(rule_id, sheet_name)]

bid_total = Decimal(0)
for pi in pi_rows:
    if pi.bidder_id == bid and pi.total_price is not None:
        if (pi.price_parsing_rule_id, pi.sheet_name) in main_sheet_names:
            bid_total += pi.total_price
```

UI 行为:**主体行(单价对比)仍展示所有 sheets**(用户能看到 breakdown 行,有审计价值),**底部"总报价"只算 main**。

## D-7 alembic 迁移

```python
# 00XX_sheet_role.py
def upgrade():
    op.execute("""
        UPDATE price_parsing_rules
        SET sheets_config = (
            SELECT jsonb_agg(
                CASE
                    WHEN elem ? 'sheet_role' THEN elem
                    ELSE elem || jsonb_build_object('sheet_role', 'main')
                END
            )
            FROM jsonb_array_elements(sheets_config) elem
        )
        WHERE jsonb_typeof(sheets_config) = 'array';
    """)

def downgrade():
    # 从 sheets_config 每项移除 sheet_role 字段(若存在)
    op.execute("""
        UPDATE price_parsing_rules
        SET sheets_config = (
            SELECT jsonb_agg(elem - 'sheet_role')
            FROM jsonb_array_elements(sheets_config) elem
        )
        WHERE jsonb_typeof(sheets_config) = 'array';
    """)
```

## D-8 测试矩阵

### L1(~25 case)

**A 汇总行 skip**(`test_fill_price_summary_row.py`,6 case):
- "合计" + total=N + qty/up=null → skip
- "汇总" + total=N + qty/up=null → skip
- "小计" + total=N + qty/up=null → skip
- "总计" → skip; "总额" → skip; "总价" → skip
- "合计费用" + qty=10 + up=N + total=N(数值字段 ≥ 2 个非空)→ **不**skip(避免误杀真分项)

**B sheet_role parse**(`test_price_rule_detector_sheet_role.py`,5 case):
- LLM 返 sheet_role="main" → 解析正确
- LLM 返 sheet_role="breakdown" → 解析正确
- LLM 返 sheet_role="invalid_value" → 默认 main + log warning
- LLM 漏字段(无 sheet_role)→ 默认 main(单 sheet)/ main+breakdown(多 sheet)
- LLM 全标 main → 解析保留(F 才修正)

**F validator**(`test_sheet_role_validator.py`,8 case):
- 两 sheet SUM 1% 内相等 + LLM 都 main → main+breakdown(行数少的为 main)
- 两 sheet SUM 不等 → 不修正(工程量清单)
- 两 sheet SUM 相等 + LLM 一个 main 一个 breakdown → 不修正(LLM 已对)
- 三 sheet 复杂关系(A+B SUM 相等,C 不同)→ A vs B 修正,C 不动
- 单 sheet → 直接返回不动
- 空 sheets_config → 不抛异常
- price_items 全 NULL → SUM=0 → 跳过该 sheet
- 行数相等且 SUM 相等(罕见)→ 保留 LLM 输出 + log

**aggregator + compare_price 过滤**(`test_aggregate_filter_main_sheet.py`,4 case):
- 全 main sheets → SUM 全计入(行为同 fix-bug-triple)
- main+breakdown → 仅 main 计入
- 老数据(sheets_config 缺 sheet_role)→ COALESCE 默认 main → SUM 全计入(backward compat)
- 多 rule(多版本)→ 各 rule 独立处理

**核心契约 invariant**(`test_pipeline_invariant.py`,2 case):
- aggregate_bidder_totals 与 compare_price 总报价 SUM **永相等**(double-source consistency)
- 监理标 fixture(walkthrough 真数据缩版):入库 7 行 + sheet_role 修正后 SUM=456000

### L2(3 fixture)

`test_e2e_multi_sheet_pricing.py`:
1. **monitoring_template_scenario** - 监理标 3-sheet 模板(本 walkthrough):验证 SUM=真实价 + price_overshoot 不误报
2. **boq_scenario** - 工程量清单 3-sheet 独立分项 fixture:验证全 main + SUM = 各 sheet sum
3. **llm_misclassify_scenario** - LLM mock 输出全标 main(误分);验证 F validator 兜底纠正

### L3 manual

Claude_in_Chrome:
- 重跑 walkthrough(供 A/B/C 全 zip)
- 验"总报价"行不再 3x 虚高(预期 A=456k / B=486k / C=674k 而非 1368k/1458k/2024k)
- 维度明细页 price_overshoot 不再误判(若 max_price>674k 则不应触发)
- 凭证落 `e2e/artifacts/fix-multi-sheet-price-double-count-<date>/`

## D-9 边界 / 风险

1. **真实 LLM 老 prompt 兼容**:既有项目的 sheets_config 没 sheet_role 字段;alembic 默认填 main → 行为同现状(继续 3x 虚高)。**用户必须手动 re-confirm rule** 才能让新 prompt 生效。proposal 写明部署后 onboarding 步骤。
2. **F validator 误杀工程量清单**:三个独立分项 sheet 各自 SUM 相同(罕见但可能)→ F 会标其中两个为 breakdown 误删 2/3 真实数据。Mitigation:F 只在两 sheet 间运作,三个相等时只配对前两个;SQL 保留所有原始数据;用户可经 admin UI 反推 main 拨回(future)。
3. **aggregate_bidder_totals SQL JSONB 性能**:每次 detect 都 JOIN + JSONB EXISTS 扫描;3 bidders × 几十 rows 的项目 SQL plan 应该走 hash join 不影响 latency,但**百家级项目 + 复杂 sheets_config**可能需要 GIN 索引(future 性能优化)。本 change 暂不加 GIN 索引,留观察。
4. **/compare/price 与 aggregate_bidder_totals 同源不一致风险**:两个地方独立实现 sheet_role 过滤,有 drift 风险。Mitigation:抽 helper `is_main_sheet(rule, sheet_name) -> bool` 共用;test_pipeline_invariant.py 锁两边 SUM 一致。

## D-10 NOT 做(本 change scope 外)

- Admin UI sheet_role 编辑器(下拉选项)— follow-up
- BidderTotalPrice 独立模型层(D 方案)— follow-up
- LLM JSON 输出 strict mode(JSON Schema enforcement)— LLM 老一点不支持,留 future
- price_items 反向追溯回 xlsx 单元格的 UI(UI 只展示 sheet_name + row_index)— 当前已可用,不动
- 工程量清单场景的 e2e fixture 用真实大文件(只用 mock 数据,够覆盖逻辑)
