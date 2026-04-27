## Why

用户 2026-04-27 报 3 个 bug,其中 2 个是产品功能盲点 + 1 个 UX 状态不同步。两轮独立 reviewer 揭出 24 个 HIGH(其中 9 个是同根因"半成品契约":input 字段定义但 detect 不消费 / SSE 协议 publish 漏字段 / 算法维度对齐错位)。本 change 一次性补完核心断点,**不再"补丁式"叠加防护层**,严格按 happy-path 数据流第一性倒推。

3 个用户报的 bug:
1. **UI 状态不同步**:启动检测后状态 Tag 卡"检测中",切到管理页再切回项目详情页才显示"已完成"。根因:`backend/app/services/detect/judge.py:489` 设 `project.status="completed"` 后只 publish `report_ready`,**未推 `project_status_changed`**;前端 `useDetectProgress` 实例隔离在 `HeroDetectArea` 子组件,Tag 在父组件 `ProjectDetailPage:346-351` 读 `project.status`(从 `reloadProject()` 拉),**两侧无连接路径**。
2. **报价相同未识别**:两家供应商总价改成完全相同(都 486000),当前 `price_consistency` 4 子检测全是 pair 行级(`(item_name_norm, unit_price_raw)` 比较),**bidder 级 sum(total_price) 跨家比较的 detector 在仓库零实现**;两家行不同 total 相同场景实测 agent_score=50,远低于铁证阈值。
3. **超限价无提示**:max_price=436000 实际报价 486000 超 11.5%,`grep "max_price\|ceiling" backend/app/services/detect/` 零匹配;`anomaly_impl/detector.py:6-7` 注释自承 `direction='high'/'both' 本期未实现`;`rules_mapper.py:23 "price_ceiling": ["price_anomaly"]` 是 admin UI 假装绑定无运行时效果。

附带修复同根因对称性盲点:`scanner.py:174` 回滚 `project.status` 不 publish(同款 SSE 漏推,违 project-status-sync spec §"项目状态变更发送 SSE 事件" Requirement)、`engine.py:135 except` 崩溃路径不 publish 不回滚 status、`useParseProgress` 缺 `project_status_changed` listener。

## What Changes

**A. 后端 SSE 协议补完(消除 happy-path / failure-path / lifespan 三处 dead publish)**
- `judge.py:489` set status="completed" 后 publish `project_status_changed{new_status:"completed"}`,**MUST before** report_ready(避免前端 race)
- `engine.py:135 except Exception` 分支 set status="ready" + publish project_status_changed{ready} + publish error event(对称 parser 侧)
- `scanner.py:174` 回滚 status="ready" 后 publish project_status_changed{ready}(2 行,补 spec 违反)

**B. 前端 SSE 协议消费(lift hook + 监听 + 兜底)**
- `useDetectProgress` 从 `HeroDetectArea` 子组件 lift 到 `ProjectDetailPage` 父组件;HeroDetectArea / StartDetectButton 改 props 接收 detect/refetch
- 加 listener:`project_status_changed` 直接 setProjectStatus / `error` 暴露 detect.lastError
- `report_ready` handler 兜底 setProjectStatus("completed")(任一事件先到都能打 Tag)
- hook `projectStatus` 初值从 `"draft"` → `null`;Tag 用 `detect.projectStatus ?? project.status`(避反向 bug)
- watchdog:`lastBizEventAt` 跟踪(不算 heartbeat),阈值 35s(≥ 2× HEARTBEAT_INTERVAL_S=15s + tolerance);SSE connected=true 但 35s 内无 biz 事件 → polling MUST 启动
- types/index.ts DetectEventType union 加 `project_status_changed` / `error`
- useParseProgress 同款补 listener(对称性盲点修)

**C. Bug 2 新 global Agent `price_total_match`**
- 新建 `agents/price_total_match.py` + `price_total_match_impl/`;消费既有 `anomaly_impl/extractor::aggregate_bidder_totals` 产出的 BidderPriceSummary
- 任意两 bidder.total_price 完全相等 → `evidence["has_iron_evidence"]=True; score=100`(Agent 自己 set,不动 price_consistency 的 scorer)
- preflight:任一 bidder partial / total=NULL → skip;evidence{enabled:false, reason:"数据缺失"}
- DIMENSION_WEIGHTS 加 `price_total_match: 0.03`;`_DIM_TO_ENGINE` 加 UI 维度 `price_total_match` → ["price_total_match"];DEFAULT_RULES_CONFIG 加新行

**D. Bug 3 新 global Agent `price_overshoot`**
- 新建 `agents/price_overshoot.py` + `price_overshoot_impl/`;消费 BidderPriceSummary + Project.max_price
- 任一 bidder.total_price > max_price → `evidence["has_iron_evidence"]=True; score=100`
- preflight:max_price=NULL 或 ≤0 → skip;evidence{enabled:false, reason:"未设限价"}
- DIMENSION_WEIGHTS 加 `price_overshoot: 0.03`;`_DIM_TO_ENGINE` 加 UI 维度 `price_overshoot` → ["price_overshoot"];DEFAULT_RULES_CONFIG 加新行

**E. 权重重平衡(只动 code 默认,不动 SystemConfig admin 默认)**
- `judge.py` DIMENSION_WEIGHTS:`image_reuse 0.05→0.02` / `style 0.10→0.09` / `error_consistency 0.12→0.10` 释放 0.06,给 2 新维度各 0.03。**和=1.00 verified**
- `DEFAULT_RULES_CONFIG` 不动既有维度权重(决策 2A 零迁移);新 2 维入口 weight 留默认 0
- 新 2 维**不依赖权重生效**(Agent 自己 set has_iron_evidence,经 judge 铁证短路升 high)

**F. UI 超限/相同提示 + admin 标签语义修正**
- ProjectDetailPage Hero `Alert type="error"` + ExclamationCircleOutlined,数据来自 price_overshoot evidence;客观陈述文案
- ReportPage 维度行 `Tag color="error"` 文字"超限" / "两家总价完全相同"
- 雷达图 / 维度列表 11→12 维兼容(老报告 OA 无该维度行 → 渲染默认"未检测";evidence{enabled:false} → 渲染对应 reason)
- 既有 admin UI label `price_ceiling` 中文 "报价天花板" → "**异常低价偏离**"(决策 3A,纯 string 改,零 SystemConfig 迁移,修语义错位防新 bug 4)

**G. 11→12 维既有硬编码巡检(8 处)**
- 测试断言:`test_detect_judge.py:210` / `test_detect_registry.py:131` / `test_reports_api.py:84` / `test_rules_mapper.py:39`
- Word 模板:`test_export_generator.py:99` 维度顺序
- 前端文案:`DetectProgressIndicator.tsx:163,205,268,296` / `DimensionDetailPage.tsx:2` / `api.ts:354`
- LLM prompt:`judge_llm.py:292,426,453`(注意:LLM prompt 写死的是 11 维列表,要更新为 13 维)
- 文档注释:`agents/__init__.py:6`
- admin-rules spec L4 "10 个" → "12"(同步)

## Capabilities

### New Capabilities
(无)

### Modified Capabilities
- `project-status-sync`: MODIFY 既有 Requirement "项目状态变更发送 SSE 事件",新增 detect 阶段 / crash 路径 / scanner 回滚 3 个 scenarios(挂既有 generic Requirement,不新增 Requirement;避 detect-template-exclusion 8 轮过度规约陷阱)
- `detect-framework`: ADD Requirement "报价超限识别(price_overshoot)" + ADD Requirement "报价总额完全相等识别(price_total_match)";每个 2 scenarios 封顶
- `admin-rules`: MODIFY 维度数 10→12;新增 price_total_match + price_overshoot 入口;既有 `price_ceiling` UI label 中文修正

## Impact

- 代码:~16 文件(后端 6 + 前端 5 + 新建 Agent 2 套 + 测试 + 配置同步)
- 测试:L1 12 case / L2 4 case / L3 3 case(对应用户 3 bug)+ 既有 5 个测试断言更新
- Spec delta:3 capability(归并后,不再 5 个;watchdog 阈值移 design.md 不锁 spec)
- 部署:零迁移,既有 SystemConfig 行为不变(决策 2A)
- 行为:Bug 1 happy-path / failure-path / lifespan 三路径都 publish status_changed,UI Tag 实时同步;Bug 2 / Bug 3 命中铁证升 high,UI 显式提示
- 凭证:`e2e/artifacts/fix-bug-triple-and-direction-high-2026-04-27/`(README + before/after agent_tasks 状态对比 + 3 截图凭证)

## Trade-offs Accepted(written in design.md)

- 决策 1A:超限一律 ironclad(简单,follow-up 可分级阈值化)
- 决策 2A:零 SystemConfig 迁移(命名拗口可后续 cleanup change)
- 决策 3A:price_ceiling UI label 改中文 string 修语义错位(零行为变更)
- price_total_match 跨币种 false positive → known limitation(单币种场景不影响)
- watchdog 35s 阈值是 hook 实现细节,不锁 spec
- 工作量 4-5 天(诚实估算,前两轮 reviewer 都说 2.5-3 天乐观)
