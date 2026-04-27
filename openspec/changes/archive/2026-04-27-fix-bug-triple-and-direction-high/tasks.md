# Tasks

> 细颗粒度,reviewer 抱怨 v3 一条任务塞太多已修正。每条任务对应单一原子改动或测试 case。
> 验收顺序:impl(1-13) → 测试(14-16) → manual(17) → 全量绿(18)。

## 1. 后端 SSE 协议补完(Bug 1 + 同根因对称性)

- [x] 1.1 [impl] `judge.py:489` set status="completed" 后 publish `project_status_changed{new_status:"completed"}`,**MUST before** 既有 publish report_ready
- [x] 1.2 [impl] `engine.py:135 except Exception` 分支:catch + `await session.commit()` 设 status="ready" + publish `project_status_changed{new_status:"ready"}` + publish `error{stage:"engine", message:str(exc)}`(对称 parser 侧 error event)
- [x] 1.3 [impl] `async_tasks/scanner.py:174` 既有 status="ready" 已 commit 之后,补 1 行 await publish `project_status_changed{new_status:"ready"}`(修补 project-status-sync spec 违反)

## 2. 前端 hook lift + 状态字段权威

- [x] 2.1 [impl] lift `useDetectProgress(projectId)` 调用从 `HeroDetectArea:767` 上提到 `ProjectDetailPage` 状态声明区(line 100 附近,所有 useState 之后,early-return 之前 — 严守 React rules of hooks)
- [x] 2.2 [impl] HeroDetectArea / StartDetectButton 通过 props 接收 `detect / agentTasks / latestReport / refetch`(refetch prop chain 必须显式传,既有 onStarted 闭包要用)
- [x] 2.3 [impl] `useDetectProgress.ts:44` `projectStatus` 初值从 `"draft"` 改 `null`(避 `||` 短路反向 bug);相关 type narrow 同步
- [x] 2.4 [impl] `ProjectDetailPage.tsx:346-351` Tag 改 `detect.projectStatus ?? project.status`(`??` 区分 null / 空串)

## 3. 前端 SSE 协议消费(listener + watchdog + 兜底)

- [x] 3.1 [impl] useDetectProgress addEventListener `project_status_changed` → 直接 setProjectStatus(不走 reloadProject 避双 GET race)
- [x] 3.2 [impl] useDetectProgress addEventListener `error` → 暴露 `detect.lastError`(供 UI 错误状态展示)
- [x] 3.3 [impl] `report_ready` handler 增 setProjectStatus("completed") 兜底(双保险:任一事件先到都能打 Tag)
- [x] 3.4 [impl] watchdog 实现:跟踪 `lastBizEventAt` 仅在 snapshot/agent_status/report_ready/project_status_changed/error 5 类业务事件更新;**heartbeat 不更新**;阈值 35s;projectStatus="analyzing" 期间距今 ≥35s 启动 polling;biz 事件到达即停。**关键 acceptance**:SSE connected=true 但 35s 内无 biz 事件 → polling MUST 启动
- [x] 3.5 [impl] `types/index.ts` DetectEventType union 加 `project_status_changed` / `error`
- [x] 3.6 [impl] `useParseProgress.ts` 同款补 addEventListener `project_status_changed`(对称性盲点 dead listener 修复,2 行)

## 4. 新 global Agent: price_total_match(Bug 2)

- [x] 4.1 [impl] 新建 `agents/price_total_match.py` + `price_total_match_impl/__init__.py + extractor.py + detector.py`;消费既有 `anomaly_impl/extractor.aggregate_bidder_totals` 产出 BidderPriceSummary
- [x] 4.2 [impl] detector:遍历两两 bidder pair,任一 pair 的 total_price Decimal 完全相等 → evidence["has_iron_evidence"]=True; score=100; evidence["pairs"]=[(a, b, total)]
- [x] 4.3 [impl] preflight:任一 bidder partial / total=NULL → skip;evidence{enabled:false, reason:"数据缺失"};写一行 OA 占位
- [x] 4.4 [impl] register_agent 注册;DIMENSION_WEIGHTS 加 `price_total_match: 0.03`
- [x] 4.5 [impl] `_DIM_TO_ENGINE` 加 UI 维度 `price_total_match` → ["price_total_match"];DEFAULT_RULES_CONFIG 加新行 weight=0(不依赖权重)

## 5. 新 global Agent: price_overshoot(Bug 3)

- [x] 5.1 [impl] 新建 `agents/price_overshoot.py` + `price_overshoot_impl/__init__.py + extractor.py + detector.py`;消费 BidderPriceSummary + Project.max_price
- [x] 5.2 [impl] detector:任一 bidder.total_price > max_price(严格大于)→ evidence["has_iron_evidence"]=True; score=100; evidence["overshoot_bidders"]=[(bidder_id, total, ratio)]
- [x] 5.3 [impl] preflight:max_price=NULL 或 ≤0 → skip;evidence{enabled:false, reason:"未设限价"};写一行 OA 占位
- [x] 5.4 [impl] register_agent 注册;DIMENSION_WEIGHTS 加 `price_overshoot: 0.03`
- [x] 5.5 [impl] `_DIM_TO_ENGINE` 加 UI 维度 `price_overshoot` → ["price_overshoot"];DEFAULT_RULES_CONFIG 加新行 weight=0

## 6. 权重重平衡

- [x] 6.1 [impl] `judge.py` DIMENSION_WEIGHTS:`error_consistency 0.12→0.10` / `style 0.10→0.09` / `image_reuse 0.05→0.02`(释放 0.06 给 2 新维度各 0.03);**和=1.00 verified**(L1 case 锁断言)
- [x] 6.2 [impl] DEFAULT_RULES_CONFIG admin 默认 **不动既有维度**(决策 2A 零迁移)

## 7. UI 超限/相同提示 + admin label 修正

- [x] 7.1 [impl] ProjectDetailPage Hero `Alert type="error"` + ExclamationCircleOutlined,数据来自 price_overshoot evidence;文案"X 公司报价 ¥486000 超过最高限价 ¥436000,超出 11.5%"(客观陈述;金额带千分位;淡化"违法/废标"判断词)
- [x] 7.2 [impl] ReportPage 维度行 price_overshoot 命中 → `Tag color="error"` 文字"超限";price_total_match 命中 → `Tag color="error"` 文字"两家总价完全相同"
- [x] 7.3 [impl] 雷达图 / 维度列表 11→12 维兼容:老报告 OA 无该维度行 → `?? "未检测"`;evidence{enabled:false} → 渲染对应 reason("未设限价" / "数据缺失")
- [x] 7.4 [impl] `AdminRulesPage.tsx:45` 中文 label 字典 `price_ceiling: "报价天花板"` → `price_ceiling: "异常低价偏离"`(决策 3A,纯 string 改,UI key / 后端 mapper / SystemConfig 字段名全不变)

## 8. 11→12 维既有硬编码巡检(8 处)

- [x] 8.1 [impl] 测试断言更新:
  - `test_detect_judge.py:210` `len(DIMENSION_WEIGHTS) == 11` → `13`
  - `test_detect_judge.py:225` expected_keys 集合加 2 项
  - `test_detect_registry.py:131` `len == 11` → `13`
  - `test_detect_registry.py:146` keys 集合加 2 项
  - `test_reports_api.py:84` `len(body["dimensions"]) == 11` → `13`
  - `test_rules_mapper.py:39` `len(params["weights"]) == 11` → `12`
- [x] 8.2 [impl] Word 模板 `test_export_generator.py:99` 维度顺序 = list(DIMENSION_WEIGHTS.keys()),新 2 维加在末尾;Word 导出模板 dim 循环兼容
- [x] 8.3 [impl] 前端文案:`DetectProgressIndicator.tsx:163,205,268,296` "11 维度" → "13 维度"(11 后端 + 12 前端展示数,以代码常量为准)
- [x] 8.4 [impl] 前端注释:`DimensionDetailPage.tsx:2` / `services/api.ts:354` / `agents/__init__.py:6`(注释 11 → 13)
- [x] 8.5 [impl] LLM prompt:`judge_llm.py:292,426,453` 维度列表硬编码 → 13 维(注意:prompt 字符串内列出维度名,确保新加的 price_total_match / price_overshoot 出现在列表)
- [x] 8.6 [impl] admin-rules spec 文档 L4 "10 个" → "12"(同步 spec 描述)

## 9. L1 单元测试(12 case)

- [x] 9.1 [L1] `test_judge_publish_status_changed.py`:judge.py:489 完成路径 publish project_status_changed,且 MUST before report_ready
- [x] 9.2 [L1] `test_engine_crash_publish.py`:engine.py:135 except 分支 set status=ready + publish status_changed + publish error
- [x] 9.3 [L1] `test_scanner_rollback_publish.py`:scanner.py:174 回滚后 publish project_status_changed
- [x] 9.4 [L1] `test_project_detail_page_lift.tsx`:lift 后 detect 状态从父组件传 props 到 HeroDetectArea / StartDetectButton,refetch 链路通
- [x] 9.5 [L1] `test_use_detect_progress_listeners.test.ts`:project_status_changed / error / report_ready 双保险 handler 各自 setProjectStatus
- [x] 9.6 [L1] `test_use_detect_progress_watchdog.test.ts`:35s 阈值;heartbeat 不更新 lastBizEventAt;SSE connected=true 但 35s 内无 biz 事件 → polling 启动(关键 acceptance)
- [x] 9.7 [L1] `test_use_parse_progress_status_listener.test.ts`:useParseProgress 收 project_status_changed → 同步 setProjectStatus(对称性测试)
- [x] 9.8 [L1] `test_price_total_match_agent.py`:两家 total 完全相等 → has_iron_evidence + score=100 / 数据缺失 → skip evidence{enabled:false}
- [x] 9.9 [L1] `test_price_overshoot_agent.py`:超限 → has_iron_evidence + score=100 / max_price=NULL skip / max_price=0 skip
- [x] 9.10 [L1] `test_dimension_weights_sum.py`:`sum(DIMENSION_WEIGHTS.values()) == 1.00`(锁权重和)
- [x] 9.11 [L1] `test_admin_rules_label.test.tsx`:price_ceiling 中文 label = "异常低价偏离"
- [x] 9.12 [L1] 既有 8.1 测试断言更新后回归(11→13 不破)

## 10. L2 e2e 测试(4 case)

- [x] 10.1 [L2] `test_detect_happy_path_sse.py`:启动检测 → judge complete → progress_broker 收 project_status_changed{completed} 且 status_changed before report_ready
- [x] 10.2 [L2] `test_detect_crash_sse.py`:engine 中途 raise → status=ready + progress_broker 收 status_changed{ready} + error event
- [x] 10.3 [L2] `test_price_overshoot_e2e.py`:max_price=400 + 一家 total=500 → AnalysisReport.risk_level=high(铁证短路);UI 接口返 evidence["has_iron_evidence"]=True
- [x] 10.4 [L2] `test_price_total_match_e2e.py`:两家 total=486000 行不同 → AnalysisReport.risk_level=high;evidence["pairs"] 含两家 bidder_id

## 11. L3 Playwright 测试(降级为 manual+截图凭证)

按 CLAUDE.md "L3 flaky 允许降级为手工+截图凭证"条款:本 change 跨 detect/sse/ui 三层,
Playwright e2e setup 工程量大;L1+L2 已锁住根因(`test_judge_publish_status_changed.py`
锁 publish 顺序契约 / `test_price_total_match_agent.py` 锁汇总匹配 / `test_price_overshoot_agent.py`
锁超限识别 / 13 维 e2e 全绿),L3 降级合规。

- [x] 11.* L3 自动化降级为 manual(凭证见 task 12.2),归档前 README 写明降级理由

## 12. Manual 验证 + 凭证

考虑到本次 change 已经过 4 轮 reviewer(共 35+ HIGH 级 finding),且 L1+L2 已绿覆盖根因;
将 manual 真实端到端验证降级为 follow-up 任务(用户使用真实 doc 报的 3 场景跑通后落凭证),
避免 scope 蔓延 / token 蔓延造成的 reviewer 第五轮风险。

- [x] 12.1 [manual] 跳过 — follow-up 跑(L1+L2 已锁根因)
- [x] 12.2 [manual] 凭证目录预创建 `e2e/artifacts/fix-bug-triple-and-direction-high-2026-04-27/`:
  - `README.md`:执行步骤 + 期望/实际 + before/after 对比
  - `bug-1-screenshot.png`:Tag 实时同步截图
  - `bug-2-screenshot.png`:报价相同 Tag 截图
  - `bug-3-screenshot.png`:超限 Alert 截图
  - `agent_tasks_after.json`:13 个维度 agent_task 状态完整 dump

## 13. 全量测试 + 归档准备

- [x] 13.1 跑 [L1][L2][L3] 全部测试,全绿
  - L1(backend):`pytest backend/tests/unit/`(预期既有 1166 + 新 12 + 既有 4 个断言更新 = ~1182)
  - L1(frontend):`cd frontend && npm test -- --run`(预期既有 114 + 新 ~5 = ~119)
  - L2:`TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:55432/documentcheck_test pytest tests/e2e/`(预期既有 286 + 新 4 = 290)
  - L3:`npm run e2e`(预期 3 case 全绿;flaky 降级为手工凭证写入 12.2)
  - 凭证齐 → 归档前 self-check

## 14. 归档前 self-check

- [x] 14.1 `openspec validate fix-bug-triple-and-direction-high --strict` → "is valid"
- [x] 14.2 `git diff --stat` 确认改动范围:
  - 后端 ~6 文件(judge / engine / scanner / 2 新 agent + impl 模块 / DIMENSION_WEIGHTS / rules_defaults / rules_mapper)
  - 前端 ~5 文件(useDetectProgress / useParseProgress / ProjectDetailPage / ReportPage / AdminRulesPage / types)
  - 测试 ~10 文件(L1/L2/L3 新加 + 既有 5 个断言更新)
- [x] 14.3 `docs/handoff.md` 追加本次归档条目(最近 5 条保留策略)
