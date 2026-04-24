## Context

- 2026-04-24 E2E 验证暴露:`ark-code-latest` 模型下 role_classifier / price_rule_detector 单次 LLM 调用实测 35~132s,现有全局 cap 60s → 高概率 timeout → kick 关键词兜底 → 假阳性放大(详 docs/handoff.md 2026-04-24 条)
- 现状:`Settings.llm_call_timeout: float = 60.0`([backend/app/core/config.py:41](backend/app/core/config.py:41));factory `_cap_timeout` 取 `min(admin_timeout, llm_call_timeout)`(harden-async-infra D4)
- 约束:生产部署已有用 `LLM_CALL_TIMEOUT=N` env 覆盖的,不能破坏既有行为

## Goals / Non-Goals

**Goals:**
- 默认值 60 → 300,失败场景全部覆盖(ark-code-latest 实测最坏 132s,3x buffer 留余地)
- Windows 控制台 utf-8 编码 stdout/stderr,中文日志不再 crash

**Non-Goals:**
- 不改 factory `_cap_timeout` 逻辑
- 不引入 per-site timeout(如 role_classifier=180 / style=300 分治):未来需求,本 change 不做
- 不改 admin-llm-config UI 或 DB schema
- 不改 pydantic-settings env 覆盖能力(保持 `LLM_CALL_TIMEOUT=...` env 可覆盖)

## Decisions

### D1 默认值 = 300.0 秒

用户选择 B(discussion 2026-04-24)。理由:
- 实测 ark-code-latest 最坏 ~132s,3x buffer = 396s,向下取整到 300
- 60s(选 A 方案)仅 2x buffer,边缘 case 仍可能踩
- 保守值换真 timeout 时多 4 分钟等待,比误触发兜底更可控

**备选**:180s。已被 user 在 discussion 里否决(B 选)。

### D2 Windows log encoding 用 sys.stdout.reconfigure + errors='replace'

在 `main.py` lifespan **顶部**(tracker 启动前)执行:

```python
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass  # 非 Windows / 已非 TextIO wrapper 的环境不报错
```

- `errors='replace'` 兜底:极端字符(罕见 Unicode)不崩日志,变 `?`
- try/except 防守 lifecycle 已替换 stream 的场景(test client、uvicorn 某些模式)
- **不用** PYTHONIOENCODING env:侵入启动脚本,不适合容器化部署
- **不用** logging formatter errors='replace':formatter 不能控制 underlying stream encoding,fix 不到根因

### D3 L1 测试钉默认值

新增 `backend/tests/unit/test_llm_timeout_default.py`:

```python
def test_llm_call_timeout_default_is_300():
    from app.core.config import Settings
    s = Settings(_env_file=None)  # 显式不读 .env,测默认值
    assert s.llm_call_timeout == 300.0
```

- 防未来誤改回 60 引发 regression
- 显式 `_env_file=None` 规避测试机 .env 污染

**不**加 L2/L3:配置默认值变更不涉及业务流,L1 钉值足够。本 change 属 CLAUDE.md 中"孤立改配置例外"。

### D4 spec delta 只改 Requirement 默认值 + 3 个 scenario 的示例数字

`openspec/specs/pipeline-error-handling/spec.md` Requirement "LLM 调用全局 timeout 安全上限" 的:
- Requirement body 把"默认 60 秒"改"默认 300 秒"
- Scenario "admin 配置过大 timeout 被 cap":举例 timeout=600, LLM_CALL_TIMEOUT=60 → 改 timeout=1200, LLM_CALL_TIMEOUT=300
- Scenario "admin 配置小 timeout 保持不变":举例 timeout=15, LLM_CALL_TIMEOUT=60 → 改 timeout=15, LLM_CALL_TIMEOUT=300(admin 小值保留语义)
- Scenario "LLM_CALL_TIMEOUT 可通过 env 覆盖":举例 env LLM_CALL_TIMEOUT=30 → 保持(测试 env 覆盖语义,数字不重要)

## Risks / Trade-offs

| 风险 | 缓解 |
|---|---|
| 真 timeout 时用户多等 4 分钟(60→300) | 可观测性:factory `_cap_timeout` 的 kind=timeout 日志已有;UI 通过 `report_ready`/轮询告知用户 |
| 已部署环境若 env 未显式设,升级后自动变 300:大部分场景是好事(减少假阳性),但失败响应变慢 | handoff.md 记录,部署文档强调 env 可手工压回较短值 |
| 极端场景 >300s 超时仍然可能(超大 docx 复杂 prompt) | 未来 per-site timeout 做精细化;本 change 不处理 |
| Windows log encoding reconfigure 若在某些测试框架下触发 AttributeError | try/except 兜底吃掉,不影响启动 |

## Migration Plan

1. 改 config.py 默认 + main.py lifespan + spec + L1 测试(1 commit)
2. 部署无需迁移步骤(config 默认值改动,env 覆盖机制不变)
3. Rollback:若发现慢响应影响大,回滚 commit 或临时 env `LLM_CALL_TIMEOUT=60` 覆盖

## Open Questions

无。D1(300 值)、D2(encoding fix 位置)、D3(测试策略)、D4(spec delta 范围)均已在 discussion 对齐,不再征求意见。
