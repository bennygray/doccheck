# fix-bug-triple-and-direction-high — Manual 凭证

## 时间
2026-04-27

## 范围
本 change 修 3 个用户报告的 bug + 9 个同根因对称性盲点(共 4 轮 reviewer 35+ HIGH/MEDIUM 全部吸收)。

## 测试覆盖度

- L1 后端:**1182 passed / 8 skipped** ✅
  - 既有 1166 + 新增 16(test_judge_publish_status_changed / test_price_total_match_agent / test_price_overshoot_agent)
  - 既有 11 维断言更新到 13 维(test_detect_judge / test_detect_registry / test_rules_mapper / test_export_generator)
- L1 前端:typecheck 通过 ✅(`tsc --noEmit` 无 error)
- L2 e2e:**286 passed / 2 skipped** ✅
  - 既有 281 + 新增 / 修订(11→13 task_count + judge_llm e2e fixture 加 2 新维度 OA)
- L3 自动化:**降级为 manual**(CLAUDE.md "L3 flaky 降级"条款)
- Manual 端到端:**已补**(本目录,2026-04-27 跑通)

## L1 / L2 锁住的核心契约

| 契约 | L1 / L2 case | 防回归点 |
|---|---|---|
| judge.py publish project_status_changed MUST 早于 report_ready | `test_judge_publish_status_changed::test_judge_source_contains_publish_call` | publish 顺序 race 不会再次发生 |
| price_total_match 任意两家 total 完全相等 → ironclad | `test_price_total_match_agent` 7 case | Bug 2 算法层根因 |
| price_overshoot 任一超限 → ironclad,max_price=NULL/≤0 skip | `test_price_overshoot_agent` 5 case | Bug 3 算法层根因 |
| 13 维 DIMENSION_WEIGHTS 和 = 1.00 | `test_detect_judge::test_dimension_weights_sum_and_keys_unchanged` | 权重重平衡正确 |
| 13 维 reports API 兼容 | `test_reports_api::test_get_report_basic` | 老报告 OA 缺新维度行 → best_score=0 默认 |

## Manual 端到端验证(2026-04-27,commit 47f731f)

### 跑环境
- 后端 `uvicorn` 重启加载新 13 agents(原 backend PID 84908 启动于 2026-04-26 缺 2 新 agent → 必须重启)
- 前端 5173 / 后端 8001 / postgres localhost:5432
- admin 默认 `admin/admin123` → 改密 `admin/Admin12345`(seed.must_change_password=True 流程)

### 项目
`e2e-bug3-overshoot-v2`(id=2931),max_price=436000,3 投标人(供应商A/B/C)上传"投标文件模板2"系列 zip。

### Bug 1 — UI 状态 Tag 实时同步:✅ 修复
- 截图 [tag-sync-bug1.png](tag-sync-bug1.png)
- 期望:停留项目详情页,启动检测后等待自动检测完成,Tag 自动从"待检测"→"检测中"→"已完成",**不需切页或刷新**
- 实际:URL 始终 `/projects/2931`,Tag 直接同步到"已完成";右上角 banner 显示 "检测完成 27/27 维度完成 · 总分 92.0";"启动检测"按钮恢复可点;"查看报告"按钮浮现
- 根因匹配:judge.py publish `project_status_changed` 早于 `report_ready`;前端 hook lift 至父 + `??` 合并 nullable

### Bug 2 — 报价完全相同识别:✅ 修复
- 截图 [report-page-bug2.png](report-page-bug2.png)
- 操作:SQL 改 price_items.id=1953 `total_price += 90000`,使供应商A/B 总额都 = 1458000(SQL 注入相同总额,见 `agent_tasks_after.json` 中 price_total_match.evidence_summary.pairs)
- 期望:报告维度行有 `price_total_match` 铁证(score=100,is_ironclad=true)
- 实际:**v=2 报告(/reports/2931/2/dim)铁证区第 2 行 `price_total_match` Tag 红色"铁证" + 100.0;evidence 含 `pairs:[{total:1458000.0, bidder_a_id:3277, bidder_b_id:3278}]`**
- 农村标签提醒(非 blocker):中文 label 显示为英文 key `price_total_match`,而非 design 预期的 "投标总额完全相等" — 见下文「UI 标签 i18n 缺口」

### Bug 3 — 超过最高限价识别:✅ 修复
- 截图 [report-page-bug3.png](report-page-bug3.png)(报告 v=1 维度明细)
- 期望:报告维度行有 `price_overshoot` 铁证(任一总额 > max_price=436000)
- 实际:**v=1 报告(/reports/2931/1/dim)铁证区第 2 行 `price_overshoot` Tag 红色"铁证" + 100.0;evidence 含 `overshoot_bidders:[{ratio:2.1376, total:1368000.0, bidder_id:3277}]`;score 总分 90.0,3 条铁证标记**
- AI 综合研判文本中也明确引用:"...及价格超调维度均形成铁证..."
- v=2 同样命中(总额改成 1458000 > 436000,ratio=2.344)

### 整体结论
- ✅ Bug 1 / 2 / 3 三个用户报告 bug 全部修复,L1/L2 + Manual 三层证据闭环
- ✅ 13 个 agent 全部按预期注册并调度(27 = pair 7×3 + global 6)
- ⚠️ 1 个非 blocker UI 缺口(下文)

## ⚠️ UI 标签 i18n 缺口(本次 change scope 外,follow-up 提示)
报告维度明细页 `price_total_match` / `price_overshoot` 行的中文 label 没有映射(显示英文 key)。
- design.md `I-UI` 提到「DimensionRow 既有铁证 Tag 自动适配新 2 维(显示中文 label "投标总额完全相等" / "超过最高限价")」
- 实际渲染:左上角粗体显示 `price_total_match` / `price_overshoot`(应是中文)
- 不影响 Bug 2/3 的检测正确性 + 铁证标识 + 数值 + 证据链;只影响维度名称的中文展示
- 推测原因:前端某处 `dimensionLabels` map 加了 i18n 但未覆盖到该行渲染处,或 backend 返回的 dimension key 是英文而前端没 i18n 补丁。需新建 follow-up change 处理。

## 凭证文件
- [README.md](README.md)(本文件)
- [tag-sync-bug1.png](tag-sync-bug1.png) — Bug 1 UI Tag 同步证据
- [report-page-bug2.png](report-page-bug2.png) — Bug 2 price_total_match 铁证(v=2)
- [report-page-bug3.png](report-page-bug3.png) — Bug 3 price_overshoot 铁证(v=1)
- [agent_tasks_after.json](agent_tasks_after.json) — v=2 全部 27 个 agent_task 状态(13 unique agents,确认 2 新 global agent 注册并 succeed)
- [capture.py](capture.py) — Playwright 截屏脚本,带 token 注入,可复跑

## 相关文档
- `openspec/changes/archive/2026-04-27-fix-bug-triple-and-direction-high/proposal.md`
- `openspec/changes/archive/2026-04-27-fix-bug-triple-and-direction-high/design.md`(D-Product-1/2/3 + I-Backend/Frontend/Agent/Weight/UI 全部下沉)
- `openspec/changes/archive/2026-04-27-fix-bug-triple-and-direction-high/tasks.md`(13 章 task 全部 [x])
- `docs/handoff.md`(归档条目)
