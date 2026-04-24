## Why

N3(LLM 大文档精度退化)explore 已完成,发现 `role_classifier.py` 现有诊断能力**只覆盖 1/3 路径** ── `harden-async-infra` 加的 kind 日志只对 LLM provider 报错的路径生效;**LLM 自己返回 confidence=low** 与 **JSON 被截断** 两条路径现在完全隐身。在没有这两条路径的可观测数据之前,任何面向 N3 的 hardening 方案(改 snippet 策略 / 调 max_tokens / 调 timeout / 换 provider)都是盲修。本 change 补齐这两条路径的日志,并附一个 B 方案双采样脚本,为后续 hardening propose 提供数据基础。

## What Changes

- **新增** `role_classifier.py` 3 条 `logger.info` 埋点(零控制流变化,零返回值变化):
  - **input shape**:`llm.complete` 调用前 → `files=N snippet_empty=M total_prompt_chars=K file_name_has_mojibake=bool`
  - **output confidence mix**:LLM 解析成功、写 DB 前 → `llm_confidence_high=X low=Y missing=Z`
  - **raw text head**(扩展 invalid JSON 的 warning):已有 `returned invalid JSON` 日志加一行 `raw_text_head=<前 200 字符>`,用于诊断 H3(response 截断)
- **新增** `e2e/artifacts/supplier-ab-n3-observability/run_sampling.py`:B 方案双采样脚本,复用现有 `run_detection.py` 骨架,清库 → 上传 A+B → 解析 → 抓 `role_classifier` 日志,输出两轮共 4 行对比表到同目录 `README.md`
- **新增** `e2e/artifacts/supplier-ab-n3-observability/README.md`:采样凭证 + 4 行对比表 + explore 产出的 H1/H2/H3 根因定位结论
- 不改 spec(Q1=A 已对齐):纯开发诊断可观测性,日志行为非对外契约,与 `harden-async-infra` 的 kind 日志同风格

## Capabilities

### New Capabilities
(无,本 change 不引入新能力,只增强既有 parser-pipeline 的诊断能力)

### Modified Capabilities
(无。日志行为不是 spec 级 Requirement;未来若数据推出的 hardening change 需要改 `parser-pipeline/spec.md` 的"LLM 角色分类与身份信息提取" Requirement,在那个 change 里改,不在本 change)

## Impact

**后端代码**
- `backend/app/services/parser/llm/role_classifier.py`:+3 `logger.info` + 扩展既有 `warning` 的 message(加 raw_text_head 字段)+ 1 个小 helper `_detect_mojibake(name: str) -> bool`(粗判 heuristic)

**测试**
- L1 新增 `backend/tests/unit/test_role_classifier_observability.py`:caplog 断言 3-5 case
  - input shape 日志字段齐全(files/snippet_empty/total_prompt_chars/file_name_has_mojibake)
  - LLM 成功路径记 output mix(confidence_high/low/missing 正确分布)
  - LLM 失败路径不记 output mix(kind 日志替代)
  - JSON 解析失败时 warning 带 raw_text_head
  - mojibake helper 正反 case

**L3 / L2 不新增**。manual 凭证脚本 + 真 LLM 采样跑 2 轮是本 change 主要的非自动化产出。

**新增 artifacts**
- `e2e/artifacts/supplier-ab-n3-observability/run_sampling.py`
- `e2e/artifacts/supplier-ab-n3-observability/README.md`

**无 DB / API / 前端影响**。info 日志在 prod 默认 warning 级别可不打开,零性能影响;dev/采样时按需调低日志级别。

**无 breaking change**。Rollback 直接回滚 commit。
