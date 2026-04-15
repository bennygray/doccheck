## 1. 检测层:price_impl/ 共享子包(11 文件)

- [x] 1.1 [impl] 新建目录 `backend/app/services/detect/agents/price_impl/` + `__init__.py`(含 `write_pair_comparison_row(ctx, *, score, evidence, is_ironclad)` 共享 helper,照搬 C10 模式)
- [x] 1.2 [impl] 新建 `price_impl/config.py`:`PriceConfig` / `TailConfig` / `AmountPatternConfig` / `ItemListConfig` / `SeriesConfig` / `ScorerConfig` dataclass + `load_price_config()` env 读取 + 权重解析失败 fallback 默认值 + `logger.warning`
- [x] 1.3 [impl] 新建 `price_impl/models.py`:`PriceRow` / `SubDimResult` / `TailHit` / `AmountPatternHit` / `ItemListHit` / `SeriesHit` TypedDict 契约
- [x] 1.4 [impl] 新建 `price_impl/normalizer.py`:`normalize_item_name(s)` + `split_price_tail(total, tail_n)` + `decimal_to_float_safe(d)`,None / 空串 / 异常 → None
- [x] 1.5 [impl] 新建 `price_impl/extractor.py`:`extract_bidder_prices(session, bidder_id, cfg) -> dict[str, list[PriceRow]]`(按 sheet_name 分组,预计算 tail_key / item_name_norm / total_price_float;max_rows_per_bidder 限流)
- [x] 1.6 [impl] 新建 `price_impl/tail_detector.py`:`detect_tail_collisions(rows_a, rows_b, cfg) -> SubDimResult`(跨投标人 (tail, int_len) 组合 key 碰撞,hit_strength=`|∩|/min(|A|,|B|)`,异常样本行级 skip)
- [x] 1.7 [impl] 新建 `price_impl/amount_pattern_detector.py`:`detect_amount_pattern(rows_a, rows_b, cfg) -> SubDimResult`((item_name_norm, unit_price) 对精确匹配率 + 阈值判断)
- [x] 1.8 [impl] 新建 `price_impl/item_list_detector.py`:`detect_item_list_similarity(grouped_a, grouped_b, cfg) -> SubDimResult`(两阶段对齐:1a 位置对齐"同项同价" + 1b item_name 归一精确匹配;阈值判断)
- [x] 1.9 [impl] 新建 `price_impl/series_relation_detector.py`:`detect_series_relation(grouped_a, grouped_b, cfg) -> SubDimResult`(仅同模板时跑;`statistics.pvariance` 算 ratios 方差,`statistics.pstdev / abs(mean)` 算 diffs CV;min_pairs 兜底;ratio/diff 双路命中)
- [x] 1.10 [impl] 新建 `price_impl/scorer.py`:`combine_subdims(results, cfg) -> (score_0_100, evidence)`(disabled/score=None 子检测不参与归一化;全 skip → Agent 级 skip 哨兵 score=0.0 + participating_subdims=[])

## 2. 检测层:price_consistency Agent run() 重写

- [x] 2.1 [impl] 重写 `backend/app/services/detect/agents/price_consistency.py::run()`:按 D4~D8 算法链(load_price_config → extract 双 bidder → 4 detector 并行执行 → scorer 合成 → write_pair_comparison_row);注册元组 `("price_consistency", "pair", preflight)` 不变;preflight 代码不动(复用 `bidder_has_priced`)
- [x] 2.2 [impl] run() 异常路径统一 catch + `logger.exception` + `evidence.error` 写入;AgentTask.status 保持 succeeded(对齐 C10 的 evidence.error 风格)
- [x] 2.3 [impl] evidence_json 填写 `algorithm="price_consistency_v1"` + `doc_role="priced"`(占位) + `enabled` + `participating_subdims` + `subdims` 4 子检测详情(按 spec "evidence_json 结构" Req)

## 3. L1 单元测试(price_impl 子模块)

- [x] 3.1 [L1] 新增 `backend/tests/unit/test_price_normalizer.py`:`normalize_item_name` 5 case(None / 空串 / NFKC 全角 / 大小写 casefold / 首尾空格 strip);`split_price_tail` 6 case(组合 key 区分量级 / int truncate / 负值 None / None / zfill 小金额 / tail_n=4 变动);`decimal_to_float_safe` 3 case(None / 正常 / InvalidOperation)
- [x] 3.2 [L1] 新增 `backend/tests/unit/test_price_extractor.py`:bidder 有 PriceItem + 按 sheet_name 分组 / 预计算字段正确(tail_key / item_name_norm / total_price_float) / bidder 无 PriceItem 返 {} / max_rows_per_bidder 截断
- [x] 3.3 [L1] 新增 `backend/tests/unit/test_price_tail_detector.py`:3 家尾 3 位碰撞 strength=0.5 / 不同量级(int_len 不等)不误撞 / 异常样本全 None → score=None / intersect 空 → score=0.0 / max_hits 限流
- [x] 3.4 [L1] 新增 `backend/tests/unit/test_price_amount_pattern_detector.py`:80% 明细单价相同 strength=0.8 / item_name 变体不合并 → 该对不匹配 / item_name NULL 全侧 → score=None / 阈值不达 → score=0.0
- [x] 3.5 [L1] 新增 `backend/tests/unit/test_price_item_list_detector.py`:阶段 1a 同模板全对齐命中 strength=1.0(mode=position)/ 阶段 1a 阈值不达 → score=0.0 / 阶段 1b flatten item_name 交集命中(mode=item_name)/ 阶段 1 两侧 item_name 全空 → score=None / sheet_name 集合相同但某 sheet 条数不等 → 走阶段 1b
- [x] 3.6 [L1] 新增 `backend/tests/unit/test_price_series_relation_detector.py`:等比 k=0.95 方差 0 → score=1.0(mode=ratio)/ 等差 diff=10000 CV=0 → score=1.0(mode=diff)/ 正常独立报价方差远超阈值 → score=0.0 / 对齐样本 < min_pairs → score=None / 非同模板 → score=None / total_price_float=None 行过滤
- [x] 3.7 [L1] 新增 `backend/tests/unit/test_price_scorer.py`:4 子检测部分 skip 部分命中 → 参与归一化正确(权重重归一) / 全 skip → score=0.0 + participating_subdims=[] + enabled=false / 全 disabled → 同前 / enabled 与 score=None 混合 / subdims stub 含 4 子检测
- [x] 3.8 [L1] 新增 `backend/tests/unit/test_price_config.py`:默认值 / monkeypatch env 覆盖 / SUBDIM_WEIGHTS 逗号解析 / SUBDIM_WEIGHTS 解析失败 fallback + logger.warning / 4 ENABLED 布尔解析 / 数值阈值解析失败 fallback

## 4. L1 单元测试(Agent run)

- [x] 4.1 [L1] 新增 `backend/tests/unit/test_price_consistency_agent.py`:evidence.algorithm="price_consistency_v1" + 命中场景 / Agent 级 skip 哨兵(score=0.0 + enabled=false + participating_subdims=[]) / 单 flag 关闭不影响其他子检测 / 异常路径(evidence.error 非空,AgentTask.status=succeeded)

## 5. L2 API 级 E2E 测试(execution-plan §3 C11 4 Scenario + 本 change 新增 1 Scenario)

- [x] 5.1 [L2] 新增 `backend/tests/e2e/test_detect_price_consistency_agent.py`:
  - **Scenario 1(尾数完全一致)**:3 bidder 每家 5 行 total_price,尾 3 位都是 "880" 且整数位长同为 6 → 启动检测 → `AGENT_REGISTRY["price_consistency"].run(ctx)` 返 score > 0 + evidence.subdims.tail.hits 含 `{tail:"880", int_len:6}`
  - **Scenario 2(明细 95%+ 相同)**:2 bidder 各 20 行同清单,19 行 (item_name, unit_price) 完全一致 → score > 0 + evidence.subdims.item_list.hits 非空 + mode="position" 或 strength≥0.95
  - **Scenario 3(口径不读)**:2 bidder 的 price_parsing_rule 一侧含税一侧不含税 → **C11 不读 currency/tax_included** 字段 → 仍按 total_price 原始值跑所有子检测,不 skip、不归一化(Q2 决策落地验证)
  - **Scenario 4(异常样本跳过)**:2 bidder 各 5 行,其中 3 行 total_price=NULL / item_name=NULL → 异常行被各子检测行级 skip;其他 2 行正常参与;不因 NULL 触发命中
  - **Scenario 5(等比关系命中,新增)**:2 bidder 同模板 5 行,B 家每行 total_price = A 对应行 × 0.95(方差 0) → `evidence.subdims.series.hits[0].mode="ratio", k≈0.95`;score ≥ 50

## 6. 文档与运维

- [x] 6.1 [impl] 更新 `backend/README.md` 添加 "C11 detect-agent-price-consistency 依赖" 段:列出 13 env + 4 子检测说明 + 算法 version string `price_consistency_v1`
- [x] 6.2 [impl] 更新 `.gitignore`:加 `e2e/artifacts/c11-*/` 白名单(对齐 C5~C10 既有风格)
- [x] 6.3 [manual] 新建 `e2e/artifacts/c11-2026-04-15/README.md`:L3 手工凭证占位(延续 C5~C10,Docker kernel-lock 未解除);记录待截图清单(启动检测 / 报告页 price_consistency 4 子检测行展开 / 等比关系 evidence 展示)

## 7. 路线图更新(Q5 scope 扩展记录)

- [x] 7.1 [impl] `docs/execution-plan.md` §6 追加一行:`| 2026-04-15 | C11 scope 扩 series_relation 子检测 | 第一性原理审暴露遗漏(水平关系/等比等差),水平关系归 C11,垂直关系归 C12 |`;§3 C11 原文保留不改(保留历史)

## 8. L3 UI E2E(延续手工凭证)

- [x] 8.1 [L3] 尝试运行 `npm run e2e`(Playwright);若 Docker kernel-lock 未解除 → 降级为手工 + 截图凭证,凭证存 `e2e/artifacts/c11-2026-04-15/`;README.md 占位待生产跑出 — 延续 C5~C10 降级,kernel-lock 未解除,凭证占位 `e2e/artifacts/c11-2026-04-15/README.md` 已就绪

## 9. 验证总汇

- [x] 9.1 跑 [L1] 全部测试(`cd backend && uv run pytest tests/unit/`),全绿 — **495 passed**(C10 base 431 + C11 新增 64 = 495 ✓)
- [x] 9.2 跑 [L2] 全部测试(`cd backend && uv run pytest tests/e2e/`),全绿 — **199 passed**(C10 base 194 + C11 新增 5 = 199 ✓)
- [x] 9.3 跑 [L3] 测试或提交降级凭证(`e2e/artifacts/c11-2026-04-15/*.png` 文件存在或 README.md 占位存在) — 延续 C5~C10 降级凭证,README.md 占位已就绪
- [x] 9.4 跑 [L1][L2][L3] 全部测试,全绿 — **L1+L2 = 694 passed**(C10 base 625 → +69 新增);L3 降级手工凭证
