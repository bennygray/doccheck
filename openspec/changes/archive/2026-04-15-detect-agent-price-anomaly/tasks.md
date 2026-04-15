## 1. anomaly_impl 子包搭建

- [x] 1.1 [impl] 建目录 `backend/app/services/detect/agents/anomaly_impl/` + `__init__.py`(空 or 共享 helper)
- [x] 1.2 [impl] 编写 `anomaly_impl/config.py`:`AnomalyConfig` dataclass + 7 env 加载 + `load_anomaly_config()` + 非法值 ValueError 校验 + baseline_enabled=true 的 warn log
- [x] 1.3 [impl] 编写 `anomaly_impl/models.py`:`BidderPriceSummary` / `AnomalyOutlier` / `DetectionResult` 三个 TypedDict
- [x] 1.4 [impl] 编写 `anomaly_impl/extractor.py`:`aggregate_bidder_totals(session, project_id, cfg)` 单次 SQL 聚合查询 + bidder_id 升序 + max_bidders 截断
- [x] 1.5 [impl] 编写 `anomaly_impl/detector.py`:`detect_outliers(summaries, cfg)` 均值计算 + 偏离判定 + mean==0 兜底 + direction 非 low 的 fallback log
- [x] 1.6 [impl] 编写 `anomaly_impl/scorer.py`:Agent 级 score 合成公式(占位 `min(100, len(outliers)*30 + max(abs(dev))*100)`)

## 2. preflight helper 扩展

- [x] 2.1 [impl] `_preflight_helpers.py` 新增 `async def project_has_priced_bidders(session, project_id, min_count=3) -> bool` + 单次 COUNT(DISTINCT) 查询 + 过滤软删 bidder(现场决策:parse_status 过滤改为"仅通过 INNER JOIN price_items 自动过滤",无 price_item 的 bidder 等价于"未 priced")

## 3. price_anomaly Agent 文件

- [x] 3.1 [impl] 新建 `backend/app/services/detect/agents/price_anomaly.py` + `@register_agent(name="price_anomaly", agent_type="global", preflight=...)` 装饰器
- [x] 3.2 [impl] 实现 `preflight(ctx)`:调用 `project_has_priced_bidders(session, ctx.project_id, cfg.min_sample_size)`;返 `PreflightResult(ok)` / `skip "样本数不足,无法判定异常低价"`
- [x] 3.3 [impl] 实现 `run(ctx)`:三层兜底(ENABLED=false 早返 / extractor 边缘 sample < min 的 skip 哨兵 / 正常路径);INSERT OverallAnalysis 行;evidence_json 按 spec schema 填写(含 baseline/llm_explanation=null 占位)
- [x] 3.4 [impl] 异常路径:extractor/detector 抛异常 → catch + evidence.error 写入 + AgentTask 仍 succeeded(贴 C11 异常语义)

## 4. registry 常量更新

- [x] 4.1 [impl] `registry.py` 新增 `EXPECTED_AGENT_COUNT: int = 11` 常量导出;L1 test 断言 `len(AGENT_REGISTRY) == EXPECTED_AGENT_COUNT`(现场决策:不在模块加载期 assert,因装饰器注册顺序不保证全部完成后再检查,测试断言更干净)
- [x] 4.2 [impl] 全项目 grep 扫描硬编码"10":更新 `tests/unit/test_detect_registry.py`(3 处)、`tests/e2e/test_detect_agents_dummy.py`(2 处)、`tests/e2e/test_analysis_start_api.py`(4 处)、`tests/e2e/test_analysis_status_api.py`(1 处)、`tests/e2e/test_detect_engine_orchestration.py`(2 处)、`tests/e2e/test_project_detail_with_analysis.py`(1 处)、`tests/e2e/test_reports_api.py`(1 处)、`tests/unit/test_detect_judge.py`(2 处);`app/api/routes/analysis.py` 注释更新。`DIMENSION_WEIGHTS` 字典调整(新增 price_anomaly=0.07,price_consistency 0.15→0.10,image_reuse 0.07→0.05,总和仍 = 1.00)

## 5. L1 单元测试

- [x] 5.1 [L1] `tests/unit/test_price_anomaly_config.py`:10 用例(默认 / env 覆盖 / 非法阈值 / 非法 sample_size / 非整数 / max_bidders warn fallback / baseline warn / direction 覆盖)
- [x] 5.2 [L1] `tests/unit/test_price_anomaly_extractor.py`:5 用例(5 家聚合 / bidder_id 升序 / 跳过无 price_items / max_bidders 截断 / 软删排除)
- [x] 5.3 [L1] `tests/unit/test_price_anomaly_detector.py`:9 用例(空 / 全 0 不抛 / 35% 触发 / 26% 不触发 / 全正常 / 多 outlier / direction=high fallback / 高阈值过滤 / 低阈值更敏感)
- [x] 5.4 [L1] `tests/unit/test_price_anomaly_scorer.py`:5 用例(空 / 1 outlier / 2 outliers capped / 3 outliers capped / max_abs 取最大)
- [x] 5.5 [L1] `tests/unit/test_price_anomaly_preflight.py`:7 用例(3 家 helper ok / 2 家 helper false / 无 price_items 不计 / min_count 边界 / Agent preflight ok / Agent preflight skip / 无 session skip)
- [x] 5.6 [L1] `tests/unit/test_price_anomaly_run.py`:7 用例(disabled 早返 / 正常命中 1 outlier / sample below min skip 哨兵 / 正常无 outlier / extractor 异常 / detector 异常 / config 回写 evidence)

## 6. L2 API 级 E2E 测试

- [x] 6.1 [L2] `tests/e2e/test_detect_price_anomaly_agent.py` Scenario 1:5 家 priced,1 家偏低 35% → evidence 含 1 outlier,score > 0,OverallAnalysis 落 1 行
- [x] 6.2 [L2] Scenario 2:2 家 priced → preflight skip,summary 含 "样本数不足"
- [x] 6.3 [L2] Scenario 3:5 家全部正常 → outliers=[],score=0
- [x] 6.4 [L2] Scenario 4:env `DEVIATION_THRESHOLD=0.20` → 原不触发场景(偏 26%)变触发
- [x] 6.5 [L2] Scenario 5:env `ENABLED=false` → evidence `enabled=false, outliers=[]`(注:本 L2 测试中 disabled 路径仍会写 OverallAnalysis 行,因为 _ctx 带 session;单元测试验证 extractor 未调用)

## 7. 注册表加载验证

- [x] 7.1 [L1] `tests/unit/test_detect_registry.py`:新增 `test_registry_has_11_agents` + `test_registry_split_7_pair_4_global` + `test_price_anomaly_is_global`;expected names 集合加入 `price_anomaly`
- [x] 7.2 [L1] 既有注册表测试(10 断言)改 11:`test_detect_agents_dummy.py::test_registry_size_11`

## 8. 文档联动

- [x] 8.1 [impl] `backend/README.md` 追加 "C12 detect-agent-price-anomaly 依赖" 段:Q1~Q4 决策注释 + 算法说明 + 7 env + algorithm version `price_anomaly_v1` + DIMENSION_WEIGHTS 调整记录
- [x] 8.2 [impl] `docs/execution-plan.md` §6 追加 1 行记录"2026-04-15 | C12 Agent 注册表扩至 11 Agent"(§5 当前状态的 M3 进度追踪保留给 handoff.md 同步更新)

## 9. L3 手工凭证占位

- [x] 9.1 [manual] 建 `e2e/artifacts/c12-2026-04-15/README.md` 占位:列出 5 张待补截图 + L1/L2 覆盖证明(L3 阻塞期替代凭证);kernel-lock 解除后补
- [x] 9.2 [impl] `.gitignore` 加 `c12-*` L3 artifacts 白名单(复用既有 pattern)

## 10. 总汇测试

- [x] 10.1 跑 [L1][L2][L3] 全部测试,全绿(L3 降级手工凭证)。**结果:743 pass**(C11 694 基线 → C12 743,净增 49 用例:L1 43 新 + L2 5 新 + 注册表 3 新 + judge 0 新/补 1 Scenario;含既有测试断言从 10→11 全部通过)
