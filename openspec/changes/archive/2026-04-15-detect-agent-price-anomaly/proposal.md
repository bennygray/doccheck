## Why

C11 `price_consistency` 已覆盖 pair 间水平关系(两家之间的价格一致性),但 execution-plan §3 C12 规划的**垂直关系**(单家 vs 群体)仍未落地。围标场景中,单家投标人可能报出显著偏离群体均值的异常低价(恶意压低中标或陪标配合),纯 pair 级检测无法捕捉此信号。

C6 注册表仅预留 "price_consistency" pair 型 Agent,没有 `price_anomaly` 相关命名空间。execution-plan §3 C12 与注册表脱节,需在本 change 显式扩注册表。

M3 进度 6/9,本 change 推进至 7/9。

## What Changes

- **BREAKING**(spec 契约):`detect-framework` spec 的 "10 Agent 注册表" Requirement MODIFIED 为 "**11 Agent 注册表**":pair 7 + **global 4**(新增 `price_anomaly`);registry 常量 `EXPECTED_AGENT_COUNT` 从 10 → 11
- **新增 Agent**:`app/services/detect/agents/price_anomaly.py`(global 型)+ 子包 `app/services/detect/agents/anomaly_impl/`(复用 C11 `price_impl/` 模式:`config.py / models.py / extractor.py / detector.py / scorer.py`)
- **新增 preflight helper**:`_preflight_helpers.project_has_priced_bidders(session, project_id, min_count=3)`,判断项目是否有 ≥ 3 家成功解析报价的 bidder
- **dummy 替换**:`_dummy.py` 不再提供 `price_anomaly` 骨架(新增时直接带真实 run);C12 后剩 3 global dummy(`error_consistency / style / image_reuse`)— 即 C12 后 dummy 数仍为 3(新增 1 + 替换 0 / 原 3 保持),C13 开始继续替换
- **算法**:纯程序化相对均值偏离检测
  - 样本过滤:仅计成功解析报价的 bidder(`parse_status='priced'` 且 price_items 非空)
  - Agent 级 skip:sample_size < 3(env 可覆盖) → `score=0.0 + participating_subdims=[] + skip_reason`
  - 偏离方向:**仅负偏离**(env `PRICE_ANOMALY_DIRECTION=low`,可扩 `both/high`)
  - 偏离阈值:**默认 30%**(env `PRICE_ANOMALY_DEVIATION_THRESHOLD=0.30` 可覆盖)
  - 基准值:群体均值(总价 `total_price` 求和除以 bidder 数);本期**不支持标底**,`baseline: null` 预留 follow-up hook
- **evidence 结构预留 follow-up 字段**:`baseline: null`(标底 follow-up)+ `llm_explanation: null`(LLM 解释 follow-up,留 C14)
- **env 新增**:`PRICE_ANOMALY_*` 7 个(MIN_SAMPLE_SIZE / DEVIATION_THRESHOLD / DIRECTION / BASELINE_ENABLED / MAX_BIDDERS / WEIGHT / ENABLED)
- **不动框架**:registry 装饰器契约 / engine INSERT 语义(global Agent `pair_bidder_a_id=NULL, pair_bidder_b_id=NULL`)/ judge / context 全锁定,只改 registry 的 `EXPECTED_AGENT_COUNT` 常量

## Capabilities

### New Capabilities
<!-- 无新 capability,复用既有 detect-framework -->

### Modified Capabilities
- `detect-framework`: MODIFIED "10 Agent 注册表" → "11 Agent 注册表";ADDED 若干 Req 描述 `price_anomaly` Agent 的 preflight / 算法 / scorer / Agent 级 skip / evidence_json / env

## Impact

- **代码**:
  - 新增 `backend/app/services/detect/agents/price_anomaly.py`(Agent 文件)
  - 新增 `backend/app/services/detect/agents/anomaly_impl/`(子包 5 文件)
  - 修改 `backend/app/services/detect/registry.py`(`EXPECTED_AGENT_COUNT` 10 → 11)
  - 修改 `backend/app/services/detect/agents/_preflight_helpers.py`(新增 `project_has_priced_bidders`)
- **spec**:`openspec/specs/detect-framework/spec.md` MODIFIED 1 + ADDED ~6 Req(总 52 → ~58 Req)
- **测试**:L1(单元:config 加载 / extractor / detector / scorer / preflight)+ L2(API 级 E2E:含样本不足 skip / 偏离触发 / 正常无告警 / env 覆盖阈值 4 Scenario)+ L3(手工截图凭证,kernel-lock 解除后补)
- **env**:新增 7 个 `PRICE_ANOMALY_*` 变量;`backend/README.md` 新增 "C12 依赖" 段
- **数据库**:**无 schema 变更**(消费 C5 PriceItem 表)
- **依赖**:无新第三方库(stdlib `statistics` + `decimal`)
- **execution-plan**:§5 M3 进度 6/9 → 7/9;§6 追加 1 行记录"C12 Agent 注册表扩至 11 Agent"
