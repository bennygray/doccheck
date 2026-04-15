# C11 detect-agent-price-consistency L3 手工凭证占位

> 延续 C5~C10 风格:Docker Desktop kernel-lock 未解除前,L3 Playwright 不能跑;改为人工跑端到端 + 截图存证。

## 待截图清单

按顺序在 Docker kernel-lock 解除后人工跑一遍并截图入库:

1. **`01-start-detect.png`** — 报告页点"启动检测"按钮,SSE 进度行包含 `price_consistency` Agent 状态从 pending → running → succeeded。
2. **`02-report-overview-price-row.png`** — 报告总览 6 张卡中"报价一致性"卡的总分 + 维度 score 显示。
3. **`03-evidence-tail.png`** — 维度明细页 `price_consistency` 行展开,`subdims.tail` 子检测命中明细,evidence 含 `tail / int_len / rows_a / rows_b`。
4. **`04-evidence-amount-pattern.png`** — `subdims.amount_pattern` 子检测命中明细,evidence 含 `(item_name, unit_price)` 对列表。
5. **`05-evidence-item-list.png`** — `subdims.item_list` 子检测,展示 `mode=position` 或 `mode=item_name` 标记 + 命中行清单。
6. **`06-evidence-series-ratio.png`** — `subdims.series` 子检测命中(等比关系),evidence 含 `mode=ratio, k=0.95, variance, pairs`(Q5 第一性原理审新增子检测的可视化证据)。
7. **`07-flag-disabled.png`** — env 设置 `PRICE_CONSISTENCY_SERIES_ENABLED=false` 重启后再跑,前端展示 series 子检测 `enabled=false` 状态(不参与归一化)。

## L2 已通过的 Scenario(对应执行计划 §3 C11 + 本 change Q5 新增)

L2 自动化测试已覆盖以下 5 Scenario(`backend/tests/e2e/test_detect_price_consistency_agent.py`):

1. ✅ Scenario 1:3 行 total_price 尾 3 位都 "880" 且 int_len 同 6 → tail 命中
2. ✅ Scenario 2:A/B 同模板 20 行 / 19 行匹配 → item_list strength ≥ 0.95(mode=position)
3. ✅ Scenario 3:无 ProjectPriceConfig 仍正常跑(C11 不读 currency / tax_inclusive)
4. ✅ Scenario 4:NULL total_price / NULL item_name 行级 skip 不假阳
5. ✅ Scenario 5:B = A × 0.95 等比关系 → series.ratio 命中 k=0.95(Q5 新增)

## 跑 L3 回放(kernel-lock 解除后)

```bash
cd /path/to/documentcheck
docker compose up -d        # backend + db + frontend
cd e2e
npm install                 # 首次
npm run e2e -- --grep "price_consistency"
```

凭证截图放本目录;若全绿则 9.3 任务标 [x]。
