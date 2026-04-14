# 项目 Handoff

> **跨会话/跨人接手的现场视角快照。** 计划视角见 `docs/execution-plan.md` §5。
>
> 本文档职责:记录"现在人在哪、下一步干什么、有什么没说清"。
> 最近变更历史只保留 5 条,更早历史去 `git log` 查。

---

## 1. 当前状态快照

| 项 | 值 |
|---|---|
| 当前里程碑 | **M1**(尚未开始) |
| 当前 change | 待 C1 `infra-base` propose |
| 当前任务行 | N/A |
| 最新 commit | `412322f` 新增第一期层级需求清单(MD + Excel) |
| 工作区 | 有未提交改动:CLAUDE.md、新增 docs/execution-plan.md、新增 docs/handoff.md |

---

## 2. 本次 session 关键决策(2026-04-14)

- **OpenSpec 切分粒度** = 方案 B(capability 级,17 个 change)
- **Detection 粒度** = 每个 Agent 独立一个 change,仅元数据 3 Agent 合并(共用提取器+同算法骨架)
- **推进方式** = 严格串行 C1→C17,一人推进
- **测试方案** = 三层分层(L1 Vitest+RTL+pytest / L2 pytest+TestClient / L3 Playwright)
- **Playwright 位置** = 项目根 `e2e/` 独立目录,baseURL 默认 `http://localhost:5173`
- **LLM 在测试里默认 mock**(`backend/tests/fixtures/llm_mock.py` 单一入口)
- **OpenSpec skill 不 fork**,通过 CLAUDE.md 约束覆盖默认行为(策略 B)
- **archive 自动 commit**(不 push),commit message 格式:`归档 change: <change-name>(M<n>)`

---

## 3. 待确认 / 阻塞

- 无阻塞。下次开工可直接进入 C1 propose。

---

## 4. 下次开工建议

**一句话交接**:
> 执行计划和测试标准已落地。下一步:开始 C1 `infra-base` 的 `openspec-propose`,同时在 C1 的 tasks 里落地 Playwright + Vitest + pytest 三层测试脚手架。

**可直接粘贴给 AI 作为新会话起点**:
```
继续 documentcheck 项目。执行计划在 docs/execution-plan.md,
测试标准和 OpenSpec 约定在 CLAUDE.md。
当前在 M1 之前,准备开第一个 change C1 infra-base。
请先读 docs/handoff.md 和 docs/execution-plan.md §3 C1 小节,
然后用 openspec-propose 为 C1 生成 proposal/design/tasks。
tasks 要按 CLAUDE.md 的测试标准打标签([impl]/[L1]/[L2]/[L3]/[manual]),
并把三层测试脚手架(Vitest/pytest/Playwright)的搭建也列为 C1 的任务。
```

---

## 5. 最近变更历史(仅保留最近 5 条)

| 日期 | 变更 |
|---|---|
| 2026-04-14 | 首版 Handoff 落地,配合 execution-plan.md + CLAUDE.md 测试标准一起上线 |
