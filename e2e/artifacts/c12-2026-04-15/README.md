# C12 detect-agent-price-anomaly L3 手工凭证占位

> Docker Desktop kernel-lock 阻塞(C3~C11 延续),此 change L3 手工截图延后补齐。
> L1+L2 已全绿(L1 48 用例 + L2 5 Scenario),C12 核心算法覆盖由 L1/L2 保证。

## 待补 5 张截图(kernel-lock 解除后执行)

1. **启动检测 → price_anomaly Agent 出现在进度列表**
   - 建项目 ≥ 3 家 bidder,上传含报价的压缩包,待解析完成
   - 点 "启动检测",SSE 进度面板应出现 `price_anomaly` dimension 条目(global 型,显示 1 个 task 而非 pair 展开)
   - 截图:`01-progress-shows-price-anomaly.png`

2. **Outlier 命中 → evidence 面板展开**
   - 准备 5 家 bidder,其中 1 家总报价偏低 35%
   - 检测完成后,/reports/{version} 页面 `price_anomaly` 维度应显示为"异常命中"
   - 点开 evidence,应看到:mean / outliers 数组(含偏离 bidder) / config / baseline=null / llm_explanation=null
   - 截图:`02-outlier-hit-evidence.png`

3. **样本不足 skip → dimension 标 skipped**
   - 准备仅 2 家 bidder(< 3 min_sample_size)
   - 检测完成,price_anomaly 应显示 `skipped`,summary = "样本数不足,无法判定异常低价"
   - 截图:`03-sample-insufficient-skip.png`

4. **env DEVIATION_THRESHOLD=0.20 覆盖**
   - 准备 5 家 bidder,1 家偏低 26%(正常 0.30 阈值不触发)
   - 重启后端时 `PRICE_ANOMALY_DEVIATION_THRESHOLD=0.20`
   - 触发检测,该家应出现为 outlier(验证 env 覆盖生效)
   - 截图:`04-env-threshold-override.png`

5. **ENABLED=false → Agent 全 skip**
   - 重启后端时 `PRICE_ANOMALY_ENABLED=false`
   - 检测完成,price_anomaly 维度 evidence `enabled=false`,outliers=[]
   - 截图:`05-enabled-false-disabled.png`

## 前置条件

- 容器 `docker compose up` 正常启动(现阻塞 Docker Desktop kernel-lock,等解除)
- 后端 .env 设置 `PRICE_ANOMALY_*` 覆盖值(默认值在 backend/README.md)
- 前端 /reports 页面渲染 global Agent evidence(C15 前若 UI 未特化 price_anomaly,可展示 JSON raw)

## L1 + L2 覆盖证明(L3 阻塞期替代凭证)

- `backend/tests/unit/test_price_anomaly_config.py` — 10 用例(env 加载 / 非法值 / baseline warn)
- `backend/tests/unit/test_price_anomaly_detector.py` — 9 用例(5 家 35% 触发 / 26% 不触发 / 全正常 / 多 outlier / direction fallback / 阈值区间)
- `backend/tests/unit/test_price_anomaly_scorer.py` — 5 用例(空 / 1 outlier / 2 outliers capped / max_abs)
- `backend/tests/unit/test_price_anomaly_extractor.py` — 5 用例(5 家聚合 / bidder_id 升序 / 跳过无 price_items / max_bidders 截断 / 软删排除)
- `backend/tests/unit/test_price_anomaly_preflight.py` — 7 用例(3/2 家 helper 边界 + Agent preflight + no session)
- `backend/tests/unit/test_price_anomaly_run.py` — 7 用例(disabled 早返 / 正常命中 / skip 哨兵 / 异常 catch / config 回写)
- `backend/tests/e2e/test_detect_price_anomaly_agent.py` — 5 Scenario(对应 L3 上述 5 张截图的算法路径)
