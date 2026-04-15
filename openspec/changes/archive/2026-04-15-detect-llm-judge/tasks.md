## 1. 配置与 env

- [x] 1.1 [impl] 新建 `backend/app/services/detect/judge_llm.py` 空文件骨架(docstring + future annotations + `__all__=[]` 内部模块);预声明 3 函数签名(`summarize` / `call_llm_judge` / `fallback_conclusion`)
- [x] 1.2 [impl] 在 `judge_llm.py` 新增 `LLMJudgeConfig` dataclass(5 字段)+ `load_llm_judge_config()` loader,校验贴 C11/C12 宽松风格(非法值 fallback + warn log)
- [x] 1.3 [impl] `backend/README.md` 新增 "C14 detect-llm-judge 依赖" 段:5 env 表格 + algorithm version `llm_judge_v1` + Q1~Q5 决策 + clamp 规则

## 2. 摘要预聚合(summarize)

- [x] 2.1 [impl] 实现 `judge_llm.summarize(pcs, oas, per_dim_max, ironclad_info) -> dict`,产结构化摘要(11 维度全列 + top_k 按 score 倒序 + 铁证无条件入 top_k)
- [x] 2.2 [impl] 实现 `_shape_evidence_brief(evidence_json: dict) -> str` helper,从 evidence_json 抽关键字段拼短字符串(≤200 字)
- [x] 2.3 [impl] `summarize` 覆盖 pair 型(PairComparison.is_ironclad)与 global 型(OA.evidence_json.has_iron_evidence)两种铁证来源,skip 维度仍出现在摘要且 `top_k_examples=[]`

## 3. LLM 调用(call_llm_judge)

- [x] 3.1 [impl] 实现 `judge_llm.call_llm_judge(summary, formula_total) -> (conclusion, suggested_total)`,含 retry + JSON 解析容错
- [x] 3.2 [impl] LLM prompt 构造:system("你是围标/串标综合研判专家,基于 11 维度证据摘要产出结论" + 约束字数 ≤200 + 约束不以'AI 综合研判暂不可用'开头 + 输出 JSON Schema) + user(summary JSON + formula_total + "建议总分区间 [{formula_total}, 100]")
- [x] 3.3 [impl] 失败判据统一走 `(None, None)`:JSON 解析失败 / 缺字段 / suggested 超界 / conclusion 空串 / 超时
- [x] 3.4 [impl] 重试策略:`MAX_RETRY+1` 次上限,重试间隔 0;复用 C13 `call_with_retry_and_parse` 同形态 helper(本文件内部实现,不抽共享)

## 4. 失败兜底模板(fallback_conclusion)

- [x] 4.1 [impl] 实现 `judge_llm.fallback_conclusion(final_total, final_level, per_dim_max, ironclad_dims) -> str`,前缀标语固定 `"AI 综合研判暂不可用"`
- [x] 4.2 [impl] 模板 5 段:标语 / 总分与等级 / 铁证维度(可选) / top 3 高分维度 / 建议关注
- [x] 4.3 [impl] 纯函数;输入为 None / 空 dict 时不抛异常,对应段降级或跳过

## 5. judge.py 集成

- [x] 5.1 [impl] 改 `judge.judge_and_create_report`:保留 `compute_report` 调用;之后加 `summarize → call_llm_judge`(若 ENABLED) → clamp → 失败 fallback 分支
- [x] 5.2 [impl] 实现 clamp 顺序(严格 4 步):`max(formula, llm)` → 铁证 `max(_, 85)` → `min(_, 100)` → `compute_level(final)`
- [x] 5.3 [impl] `has_ironclad` 判定逻辑与 `compute_report` 完全一致(任一 PC.is_ironclad 或任一 OA.evidence_json.has_iron_evidence),抽一个 `_detect_ironclad(pcs, oas)` helper 复用避免双重实现
- [x] 5.4 [impl] 幂等检查保留不变;INSERT AnalysisReport 时 `llm_conclusion` 填 LLM 成功结果或 fallback 模板

## 6. LLM mock 扩展

- [x] 6.1 [impl] 扩 `backend/tests/fixtures/llm_mock.py`:加 `make_l9_response(suggested_total, conclusion, reasoning="")` builder
- [x] 6.2 [impl] 加 6 fixture:`mock_llm_l9_ok` / `mock_llm_l9_upgrade` / `mock_llm_l9_clamped` / `mock_llm_l9_failed` / `mock_llm_l9_bad_json` / `mock_llm_l9_disabled`(等价 `LLM_JUDGE_ENABLED=false`)
- [x] 6.3 [impl] fixture 统一 patch `judge_llm.call_llm_judge`(不 patch 底层 LLM 客户端),简化 test 心智模型

## 7. L1 单元测试

- [x] 7.1 [L1] 新建 `backend/tests/unit/test_judge_llm_config.py` ~5 test:默认配置 / 非法 bool/int fallback / TIMEOUT 超界 fallback / MAX_RETRY 超界 / SUMMARY_TOP_K 超界
- [x] 7.2 [L1] 新建 `backend/tests/unit/test_judge_llm_summarize.py` ~6 test:11 维度全列 / top_k 倒序 / 铁证无条件入 top_k / skip 维度结构 / pair+global 两种铁证来源 / evidence_brief 抽取
- [x] 7.3 [L1] 新建 `backend/tests/unit/test_judge_llm_call.py` ~7 test:首次成功 / bad JSON 消费重试 / 重试耗尽 (None,None) / suggested 超界 / conclusion 空串 / 缺字段 / timeout
- [x] 7.4 [L1] 新建 `backend/tests/unit/test_judge_llm_fallback.py` ~6 test:正常模板 / 无铁证跳过铁证段 / 空 per_dim_max 降级 / 前缀标语固定 / 总分/level 插入 / top 3 高分列出
- [x] 7.5 [L1] 扩 `backend/tests/unit/test_detect_judge.py`:+5 test 覆盖 clamp 5 case(升分跨档 / LLM 低于公式被覆盖 / 铁证 LLM 压分被守护 / LLM 与铁证叠加 / 天花板)
- [x] 7.6 [L1] 扩 `test_detect_judge.py`:+5 test 覆盖 `_detect_ironclad` helper(pair is_ironclad / OA has_iron_evidence / 两者都有 / 两者都无 / OA evidence_json 非 dict 兜底)
- [x] 7.7 [L1] 既有 `test_detect_judge.py` 中 `compute_report` 纯函数 test 不改(契约不变),断言仍通过
- [x] 7.8 [L1] 既有 judge 相关 test(如 `test_judge_stream.py` 若存在)默认 patch `call_llm_judge` 返回 `(None, None)` 走降级,不破原断言
- [x] 7.9 [L1] 运行 `pytest backend/tests/unit/` 全绿

## 8. L2 API E2E 测试

- [x] 8.1 [L2] 新建 `backend/tests/e2e/test_judge_llm_e2e.py`
- [x] 8.2 [L2] Scenario 1 LLM 成功升分跨档:seed 11 维度结果产 formula=65 medium / 无铁证 / mock LLM 返回 75 → 断言 AnalysisReport.total=75 level=high / llm_conclusion=LLM 文本
- [x] 8.3 [L2] Scenario 2 LLM 试图降铁证被守护:seed 产 formula=88 + 铁证 / mock LLM 返回 60 → 断言 total=88 level=high / llm_conclusion=LLM 文本
- [x] 8.4 [L2] Scenario 3 LLM 失败走降级兜底:mock `mock_llm_l9_failed` → 断言 total=formula / llm_conclusion 以"AI 综合研判暂不可用"开头 / 包含 formula 结论模板
- [x] 8.5 [L2] Scenario 4 LLM_JUDGE_ENABLED=false 跳过 LLM:env 覆盖 disabled → 断言走降级模板分支 / llm_conclusion 前缀固定
- [x] 8.6 [L2] 运行 `pytest backend/tests/e2e/` 全绿

## 9. L3 UI E2E 凭证

- [x] 9.1 [L3] 新建 `e2e/artifacts/c14-2026-04-15/README.md` 占位:列出待补 2 张截图(报告页 LLM 成功 conclusion 展示 / 报告页降级 banner + 模板文案);`.gitignore` 加 `c14-*` 白名单
- [x] 9.2 [L3] 如 Docker kernel-lock 解除 → 跑 Playwright 补截图;阻塞时降级为手工凭证占位,凭证文件放 `e2e/artifacts/c14-2026-04-15/`(归档前必须存在)

## 10. 注册表与契约不变性校验

- [x] 10.1 [L1] 扩 `backend/tests/unit/test_detect_registry.py`:断言 11 Agent 注册表无变化 / AgentRunResult 仍 3 字段 / `judge.DIMENSION_WEIGHTS` 键集与权重和不变
- [x] 10.2 [L1] 扩断言 `judge.compute_report` 函数签名不变(参数顺序 + 返回类型)

## 11. 文档联动

- [x] 11.1 [impl] `docs/execution-plan.md §6` 追加 1 行 C14 实施记录
- [x] 11.2 [impl] `docs/handoff.md` 更新:状态快照 / 本次 session 决策 / Q4 跨项目共现作为独立 follow-up 登记 / 最近变更历史追加 C14
- [x] 11.3 [impl] 归档前检查 `git status` 无 `.env` 等敏感文件;openspec validate `openspec/changes/detect-llm-judge/`
- [x] 11.4 [impl] openspec archive `detect-llm-judge`(必须在所有 L1/L2/L3 任务全绿 + 手工凭证文件存在之后)
- [x] 11.5 [impl] 归档 commit(格式 `归档 change: detect-llm-judge(M3)`;不 push,等用户指示)

## 12. 总汇

- [x] 12.1 [L1][L2][L3] 跑 [L1][L2][L3] 全部测试,全绿
