## Context

- archive change `2026-04-24-config-llm-timeout-default` 改了 `llm_call_timeout`(cap)默认值 60→300,自称解决 role_classifier / price_rule_detector 超时问题
- 但 [factory.py:118](backend/app/services/llm/factory.py#L118) 的实际生效路径是 `max(1, int(_cap_timeout(settings.llm_timeout_s)))`,其中 `_cap_timeout(raw) = min(raw, cap)`
- per-call 默认值 `llm_timeout_s = 30.0` 没动,`backend/.env` 用 60,docker-compose 用 30 → 实际生效 60s 或 30s
- 2026-04-25 e2e 实测:price_rule_detector LLM 调用 >60s 超时 → 占位 rule 转 `failed` → 3 bidder 全 price_failed
- 约束:不能破坏已显式 env 覆盖的生产部署;不引入 per-site timeout(留作未来 change)

## Goals / Non-Goals

**Goals:**
- 让 archive change 的"默认 300s"诺言真正落地:per-call 默认 = cap 默认 = 300
- 新部署(没显式 env)立即生效,本机 .env 同步不再覆盖
- 现有显式 env 覆盖**不破坏**(保持 12 因子语义)

**Non-Goals:**
- 不合并 `llm_timeout_s` 与 `llm_call_timeout` 字段(breaking,牵动 admin UI / DB / 11 Agent / migration,与本次问题不匹配)
- 不引入 per-site timeout(role_classifier=180 / style=300 分治)
- 不动各 Agent 独立 LLM_TIMEOUT_S(`ERROR_CONSISTENCY_LLM_TIMEOUT_S` 等,有自己的 spec)
- 不改 admin-llm-config UI / schema / DB

## Decisions

### D1 默认值 = 300.0 秒,与 cap 对齐

理由:
- 与前一个 change 的 cap 决策一致(那个 change 的 design 已经为 300 做过完整论证:ark-code-latest 实测最坏 132s,3x buffer)
- 保持 per-call ≤ cap 的不变量;cap 是天花板,per-call 等于 cap 时 `min` 不会再改变值
- 用户 OK 选项 B(2026-04-26 discussion),不重新征求

### D2 处理本机 `backend/.env` 的旧值

`.env` 不在 git 历史(已 gitignore),只是开发机的本地配置。删 `LLM_TIMEOUT_S=60` 这一行让代码默认 300 生效。

不删 `.env` 文件本身;只删这一行。其他 LLM 配置(API key / model / base_url)保留。

### D3 docker-compose.yml 默认值 30→300

`LLM_TIMEOUT_S: ${LLM_TIMEOUT_S:-300}`;部署方手工设 env 仍优先。test compose(`docker-compose.test.yml`)不涉及 LLM,不动。

### D4 .env.example 注释重写

老注释引用了 `LLM_CALL_TIMEOUT`(cap)这个用户基本不会主动设的字段,且暗示"默认 300 够用",误导。新注释要讲清:

- per-call(`LLM_TIMEOUT_S`)和 cap(`LLM_CALL_TIMEOUT`)两个值
- 实际生效 = `min(per_call, cap)`,两者默认都是 300
- 想压短某次部署 → 设 `LLM_TIMEOUT_S=60`(per-call),不要设 cap

### D5 L1 测试新增 1 case 钉 per-call 默认值

```python
def test_llm_timeout_s_default_is_300():
    s = Settings(_env_file=None)
    assert s.llm_timeout_s == 300.0
```

原有 `test_llm_call_timeout_default_is_300` 保留。两条配套钉住"per-call 与 cap 都默认 300"的不变量。

### D6 Manual e2e 验证

修完 + 重启后端后,对项目 2486 调 re-parse,验证:
- bidder parse_status 从 `price_failed` 变 `priced` 或 `partial`
- `price_parsing_rules.status` 从 `failed` 变 `confirmed`,`sheets_config` 非空
- 重新 start_analysis,看报价相关 3 维度(price_consistency / price_anomaly / price_near_ceiling)从 skipped 变成有得分

凭证落 `e2e/artifacts/fix-llm-timeout-default-followup-2026-04-26/`(README + 关键截图 + bidder/rule 状态 dump)。

### D7 spec delta 范围

只 MODIFY 既有 Requirement "LLM 调用全局 timeout 安全上限":

- 改名为 "LLM 调用全局 timeout 与 per-call 默认值",描述新增"per-call 默认 300,与 cap 对齐"语义
- 新增 1 个 Scenario:"未配 env 时 per-call 与 cap 默认值都是 300"
- 既有 4 个 scenario 保留(admin 大值被 cap、admin 小值保留、env 覆盖 cap、未配置 env 时 cap=300)

不动 Windows UTF-8 / skipped 文案 / except 顺序等其他 Requirement。

## Risks / Trade-offs

| 风险 | 缓解 |
|---|---|
| 真异常 LLM 调用现在 5 分钟才失败(此前 30~60s) | archive change 已接受这个代价,本次只是让"per-call 也这么慢";想快失败的部署可手工 `LLM_TIMEOUT_S=60` |
| 部署文档 / handoff 提到"LLM_TIMEOUT_S 默认 30" 的位置可能过时 | grep `30` 出现的 4 处(README + spec)不是新约束,本次不做大范围 doc 同步;handoff.md 追加本 change 条目 |
| L2 跑测试时若有 fixture 设了 LLM mock 但默认 timeout 改了,可能影响 fixture 表现 | LLM mock 即时返回不走真 timeout 路径;预计无影响。L2 全跑一次确认 |
| 已有 .env 没设 LLM_TIMEOUT_S 的开发机升级后失败响应慢 4 分钟 | 与 archive change 同款代价,符合"减少假阳性 > 快失败"的优先级 |

## Migration Plan

1. 改 5 文件(config.py + .env.example + docker-compose.yml + 本机 .env + L1 测试),1 commit
2. 部署无需迁移步骤(env 覆盖能力不变)
3. Manual:重启后端,对项目 2486 re-parse,跑通后凭证存 e2e/artifacts/
4. Rollback:回滚 commit 或临时 env `LLM_TIMEOUT_S=60` 覆盖

## Open Questions

无。Why / What / Decisions 在 propose 阶段已与 user 对齐(2026-04-26 discussion 选 B)。
