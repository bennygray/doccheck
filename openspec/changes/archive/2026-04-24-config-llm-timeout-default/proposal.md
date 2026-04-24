## Why

生产环境实测 LLM 默认 timeout 60s 根本不够用:

- **role_classifier**(4 文档批量分类)实测 35~132s,方差大;ark-code-latest 模型对中文长 prompt 推理慢
- **price_rule_detector**(1 xlsx 表结构识别)实测 ~113s
- 现有 60s cap → 上述两处**高概率超时** → 回到关键词兜底 → **放大假阳性面**

2026-04-24 用 3 个真实供应商 zip 做 E2E 验证暴露此问题:LLM_CALL_TIMEOUT 必须临时调到 300s 才跑通全流程(详 `docs/handoff.md`)。

次要伴随修复:Windows 控制台默认 GBK 编码,某些中文日志(招标文件名含 U+00BA 等字符)触发 `UnicodeEncodeError` 日志崩溃,lifespan 一行设 `sys.stdout.reconfigure(encoding='utf-8', errors='replace')` 兜底。

本 change 属于 **CLAUDE.md 约定的"孤立改配置"例外**(仅改默认值 + lifespan 1 行),无 `[L1]/[L2]/[L3]` 业务层测试,但保留 1 个 L1 元测试钉住"config 默认值=300"防未来误改回。

## What Changes

- `backend/app/core/config.py::Settings.llm_call_timeout` 默认值从 60.0 改为 300.0
- `backend/app/main.py` lifespan 顶部调 `sys.stdout.reconfigure(encoding='utf-8', errors='replace')` + `sys.stderr.reconfigure(...)`,Windows 控制台中文日志不再崩
- 新增 L1 `test_llm_timeout_default.py` 钉 default=300(防 regression)
- `openspec/specs/pipeline-error-handling/spec.md` 同步改 Requirement "LLM 调用全局 timeout 安全上限" 的默认值为 300;3 个 scenario 的数字示例按情况调整

**不改**:admin-llm-config 已有 timeout 字段的 UI / 数据库行为、factory 层 `min(admin_timeout, LLM_CALL_TIMEOUT)` 逻辑、各 LLM 调用点 per-site 超时覆盖能力(未来做)

## Capabilities

### New Capabilities
(无)

### Modified Capabilities
- `pipeline-error-handling`: Requirement "LLM 调用全局 timeout 安全上限" 的默认值 60→300,对应 3 个 scenario 中涉及 60 的示例数值同步更新

## Impact

- 代码:2 行代码级改动(`config.py` 默认值 + `main.py` lifespan stdout/stderr reconfigure)
- 测试:+1 L1 file(钉默认值)
- Spec:1 delta file 修改 pipeline-error-handling 的 1 个 requirement + 3 scenario
- 部署:现有 `LLM_CALL_TIMEOUT` env 覆盖**零影响**——已设 env 的部署不受默认值改动影响
- 行为:**真超时时长从 60s 变 300s**,失败响应慢 4 分钟——在 ark-code-latest 这种慢模型场景下是必要代价;可观测性上 factory._cap_timeout 的 kind=timeout 日志仍可用
