# C14 detect-llm-judge L3 手工凭证占位(2026-04-16)

Docker Desktop kernel-lock 延续(C3~C13 L3 全部阻塞中),本次 L3 手工凭证同样降级为占位 + 文字说明,待 kernel-lock 解除后补截图。

## 待补截图清单(2 张)

### 1. 报告页 LLM 成功 conclusion 展示

**步骤**
1. `docker compose up -d && npm run dev`
2. 登录 reviewer 账号 → 上传一套样例投标文件压缩包 → 启动检测
3. 等待检测完成 → 进报告页
4. 确认"综合研判"区显示 LLM 生成的自然语言结论(非降级文案)
5. 截图:报告页顶部 + `llm_conclusion` 展示区

**预期**
- `llm_conclusion` 首字不是 "AI 综合研判暂不可用"
- 文字内容描述 11 维度共振识别结论
- total_score / risk_level 可能因 LLM 升分跨档(formula → final)

### 2. 报告页 LLM 降级 banner + 模板文案

**步骤**
1. env `LLM_JUDGE_ENABLED=false` 启动后端
2. 同样跑一遍检测流程
3. 截图:报告页 `llm_conclusion` 展示区 + 降级 banner

**预期**
- `llm_conclusion` 以 "AI 综合研判暂不可用" 开头
- 文案包含:总分、风险等级、铁证维度(若有)、top 3 高分维度、建议关注
- 前端通过前缀 match 展示黄色小 banner(若前端已实施该识别逻辑)

## 当前状态(2026-04-16)

- **Docker kernel-lock 未解除**,Playwright 无法跑(与 C3~C13 同)
- L1(721 全绿) + L2(217 全绿,含 C14 新增 5 scenario)已覆盖:
  - 升分跨档 / 铁证守护 / 失败兜底 / env disabled / 幂等
  - fallback 模板文案结构 + 前缀固定
  - LLM clamp 规则(可升不可降 / 铁证下限 / 天花板)
- L3 UI 级展示本 change **仅涉及现有报告页 `llm_conclusion` 字段的填充方式变化**,不新增 UI 组件;视觉验证可在 kernel-lock 解除后快速补齐

## L1 / L2 覆盖证明

- L1 关键测试文件:
  - `backend/tests/unit/test_judge_llm_config.py`(config env 7 test)
  - `backend/tests/unit/test_judge_llm_summarize.py`(summarize 9 test)
  - `backend/tests/unit/test_judge_llm_call.py`(call_llm_judge retry+parse 9 test)
  - `backend/tests/unit/test_judge_llm_fallback.py`(fallback 模板 7 test)
  - `backend/tests/unit/test_detect_judge.py`(+13 test:clamp 5 / ironclad helper 5 / 契约 3)
  - `backend/tests/unit/test_detect_registry.py`(+4 test:11 Agent 数 / AgentRunResult 字段 / DIMENSION_WEIGHTS / compute_report 签名)
- L2 关键测试文件:`backend/tests/e2e/test_judge_llm_e2e.py`(S1~S5,5 scenario)
- 既有测试(C6~C13 累计 ~870+ 用例)无需改动,全部通过;`backend/tests/e2e/conftest.py` 新增 autouse fixture `_disable_l9_llm_by_default` 让既有 L2 默认走 (None,None) 降级,不触发真实 LLM
