## Why

当前 `judge.compute_report` 仅是纯加权公式 + 铁证升级的占位实现,`AnalysisReport.llm_conclusion` 字段恒为空字符串。requirements §L-9 定义的 "LLM 综合研判" 能力未兑现,报告对用户只给出冷冰冰的分数,没有跨维度串讲的自然语言结论,M3 里程碑判据"跑出 10 维度分数+证据"缺最后一块拼图。C14 作为 M3 收官 change,负责在不破坏既有 11 Agent 契约和确定性公式评分的前提下,在 judge 层叠加 LLM 综合研判层。

## What Changes

- **新增 LLM 综合研判入口**:在 `judge.judge_and_create_report` 流程中,`compute_report` 公式先算出 `(formula_total, formula_level)` → 预聚合结构化摘要 → 调 L-9 LLM → 产自然语言结论
- **新增 LLM 可升不可降 clamp 契约**:`final_total = max(formula_total, llm_suggested_total)`,铁证命中时 `final_total ≥ 85` 硬守护,天花板 100;level 按 final_total 重算(可能跨档)
- **新增 LLM 失败模板兜底**:LLM 重试 N 次仍失败 / JSON 解析失败 / 超界 → `llm_conclusion` 填 `fallback_conclusion` 模板(前缀标语 `"AI 综合研判暂不可用"` + 公式结论自然语言化),`total/level` 保持公式值
- **新增预聚合摘要结构**:11 维度 × `{max_score, ironclad_count, top_k_pair_examples, skip_reason}` + 铁证维度列表,token 稳定 3~8k
- **新增 env `LLM_JUDGE_*` 命名空间**(5 个):ENABLED / TIMEOUT_S / MAX_RETRY / SUMMARY_TOP_K / MODEL
- **扩 LLM mock 单一入口**:`llm_mock.py` 加 L-9 builder + 6 fixture(沿用 C13 L-5/L-8 模式)
- **不动**:11 Agent 注册表 / 3 子包中的 8 个 Agent 实现 / AgentRunResult 3 字段契约 / `compute_report` 纯函数(保留作为"基础分"单一事实源)/ `DIMENSION_WEIGHTS` 占位值(留实战反馈调,follow-up)

## Capabilities

### New Capabilities

<!-- 本 change 不新增 capability,L-9 LLM 综合研判职责归属既有 detect-framework capability -->

### Modified Capabilities

- `detect-framework`: 综合研判层从"占位加权公式"升级为"公式 + L-9 LLM 双轨 + 可升不可降 clamp + 失败模板兜底";新增 L-9 摘要预聚合契约、LLM 调用契约、clamp 规则契约、失败兜底模板契约、LLM mock L-9 扩展、env 命名空间

## Impact

- **代码**:
  - 修改 `backend/app/services/detect/judge.py`(`judge_and_create_report` 注入 LLM 调用 + clamp)
  - 新增 `backend/app/services/detect/judge_llm.py`(3 函数:summarize / call_llm_judge / fallback_conclusion)
  - 扩 `backend/tests/fixtures/llm_mock.py`(L-9 builder + 6 fixture)
  - 新增 env 5 个(LLM_JUDGE_*)
- **数据**:无 alembic 迁移;`AnalysisReport.llm_conclusion` 字段从 `""` 占位切到实填(LLM 或降级模板),字段类型不变
- **API**:无新增 endpoint;`POST /api/projects/{id}/detect` 触发链路不变,报告生成阶段内部多调一次 LLM
- **依赖**:无新增 Python 包(复用既有 LLM 客户端基础设施)
- **前端**:轻改 — 报告页加"前缀 match `AI 综合研判暂不可用` → 展示降级 banner"(可在后续 UI change 或手工补,本 change 不强耦合)
- **跨 change 影响**:judge.compute_report 纯函数契约不变,C6~C13 累计 test 全部无需改;既有 `test_detect_judge.py` 需补 LLM mock patch 覆盖 call_llm_judge 旁路
- **测试**:L1 ~28 新增 / L2 4 Scenario / L3 2 手工凭证
- **scope 边界**:不做跨项目历史共现 LLM 上下文(独立 follow-up);不调 DIMENSION_WEIGHTS(实战反馈 follow-up);不做 prompt N-shot examples(首版简版,follow-up)
