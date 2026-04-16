# 项目 Handoff

> **跨会话/跨人接手的现场视角快照。** 计划视角见 `docs/execution-plan.md` §5。
>
> 本文档职责:记录"现在人在哪、下一步干什么、有什么没说清"。
> 最近变更历史只保留 5 条,更早历史去 `git log` 查。

---

## 1. 当前状态快照

| 项 | 值 |
|---|---|
| 当前里程碑 | **M4 完成 + V1 全量验收 + DEF-OA 修复** |
| 当前 change | DEF-OA `fix-dimension-review-oa` 归档完成。judge 补写 pair 维度 OA 行,维度级复核 API 全 11 维度可用 |
| 最新 commit | DEF-OA 归档 |
| 工作区 | C17 全量改动:**后端**:新增 `models/system_config.py`(SystemConfig 单行 JSON)+ `services/admin/`(rules_defaults + rules_mapper + rules_reader 3 文件)+ `schemas/admin.py`(用户+规则 Pydantic)+ `routes/admin.py`(5 endpoint: GET/POST/PATCH users + GET/PUT rules)+ `main.py` 注册 admin router + Alembic 0009 migration;**引擎集成**:`engine.py` 检测前读 SystemConfig + `judge.py` 支持自定义 weights/risk_levels;**前端**:`AdminUsersPage.tsx`(用户表格+创建+启用禁用)+ `AdminRulesPage.tsx`(10 维度+全局配置+保存+恢复默认)+ `App.tsx` 新增 2 admin 路由 + `api.ts` 新增 5 API 函数 + `types/index.ts` 新增 admin 类型 + `ProjectListPage.tsx` admin 导航入口;**测试**:L1 后端 16 + L1 前端 8 + L2 3 = 27 新增用例;**spec sync**:新增 `admin-users` spec(4 Req/12 Scenario)+ `admin-rules` spec(6 Req/15 Scenario);**L3 手工凭证**:`e2e/artifacts/c17-2026-04-16/README.md` |

---

## 2. 本次 session 关键决策(2026-04-16,C17 `admin-users` propose+apply)

### propose 阶段已敲定(4 产品级决策)

- **Q1 A 仅全局级**:单行 SystemConfig，GET/PUT 读写；不做项目级覆盖
- **Q2 A 仅最新值 + 恢复默认**:PUT 覆盖写入，不做版本号/回滚
- **Q3 A 仅 admin 手动创建**:POST /api/admin/users 由 admin 调用，无公开注册
- **Q4 A requirements.md §8 最小集**:10 维度 enabled/weight/llm_enabled + 特有阈值 + 全局参数，不暴露全部 ~50 个 agent env var

### 文档联动

- **`openspec/specs/admin-users/spec.md`** 新建:4 Req / 12 Scenario
- **`openspec/specs/admin-rules/spec.md`** 新建:6 Req / 15 Scenario
- **`docs/execution-plan.md §6`** 追加 1 行 C17 归档记录
- **`e2e/artifacts/c17-2026-04-16/README.md`** L3 手工凭证占位
- **`docs/handoff.md`** 即本次更新

---

## 2.bak_C15 上一 session 关键决策(2026-04-16,C15 `report-export` propose+apply)

### propose 阶段已敲定(4 产品级决策)

- **Q1 C Word 模板两者结合**:内置默认 + 用户上传可覆盖 + 上传坏掉回退内置
- **Q2 D 复核粒度组合**:整报告级(必须)+ 维度级(可选)
- **Q3 A 独立 `audit_log` 表全字段**
- **Q4 D 异步 + 预览链接 + 三兜底**

### apply 阶段就地敲定(重要现场决策 B2)

- **design D4 改 B2**:原 design 假设复用 `async_tasks`,apply 发现侵入大;就地改独立 `export_jobs` 表(14 字段)

---

## 2.bak_C14 上一 session 关键决策(2026-04-16,C14 propose+apply+archive)

- Q1 B 预聚合结构化摘要 / Q2 A 公式兜底 / Q3 B 可升不可降+铁证 85 守护 / Q4 C 不做跨项目共现 / Q5 C 降级模板+前缀哨兵
- apply:AgentRunResult 字段名修正 / e2e autouse fixture / fallback 前缀约束 / summarize 铁证无条件入 top_k

---

## 2.bak_C13 上一 session 关键决策(2026-04-15,C13 propose+apply+archive)

- Q1 合并 / Q2 (A) L-5 铁证 / Q3 (C) MD5+pHash 双路 / Q4 (C) L-8 全 LLM / Q5 零新增依赖
- apply:不扩 AgentRunResult 改走 OA evidence 顶层 / DocumentText 行级 SQL / imagehash int64 cast

---

## 3. 待确认 / 阻塞

- 无硬阻塞,**M4 完成(3/3),全部 17 个 change 已归档**
- **Follow-up(C16)**:字符级 diff / price evidence 对齐 / 对比页面导出
- **Follow-up(C17)**:元数据白名单已通过 admin 规则配置可编辑（✅ 已解决）；按维度分 Tab 的完整配置 UI（第二期）
- **Follow-up(C15)**:用户模板上传 UI / PDF 导出 / 批量导出 / audit 过滤器 / 导出历史页
- **Follow-up(C14)**:跨项目历史共现 / DIMENSION_WEIGHTS 实战调参 / L-9 prompt N-shot 精调
- **Follow-up(持续)**:Docker kernel-lock 未解(C3~C17 L3 全延续手工凭证)
- **Follow-up(持续)**:生产部署前 env 覆盖全清单

---

## 4. 下次开工建议

**一句话交接**:
> **M4 完成,全部 17 个 change 已归档。** C15 报告导出 + C16 对比视图 + C17 用户管理/规则配置 = M4 可交付。系统具备完整的上传→解析→检测→报告→导出→对比→管理能力。下一步：M4 演示级交付凭证 + follow-up 规划（第二期 backlog 整理）。

**可直接粘贴给 AI 作为新会话起点**:
```
继续 documentcheck 项目。M4 已完成(3/3),C17 admin-users 已 archive + push。
全部 17 个 change（C1~C17）已归档,系统达到可交付状态。
下一步:
  1. M4 演示级交付凭证(execution-plan §4 要求:Word 报告示例 + 管理操作截图)
  2. follow-up backlog 整理(C14~C17 累积的 follow-up 项)
  3. 第二期规划(US-9.2 按维度分 Tab / US-10 LLM 配置 / 跨项目历史共现 等)
请先读 docs/handoff.md 和 docs/execution-plan.md §4~§6 确认现状。
也检查 memory 和 claude.md。
```

---

## 5. 最近变更历史(仅保留最近 5 条)

| 日期 | 变更 |
|---|---|
| 2026-04-16 | **DEF-OA `fix-dimension-review-oa` 归档**:judge.py 补写 7 pair 维度 OA 聚合行;error_consistency/image_reuse early-return 补 OA;维度级复核 API 全 11 维度可用;L1 801 + L2 250 全绿 |
| 2026-04-16 | **V1 全量验收测试**:`docs/v1-acceptance-test-report.md` 55/66 通过(96.5% 可执行通过率);2 失败(AT-7.7 LLM 降级 UI / AT-9.2 维度复核);9 阻塞(fixture 不足) |
| 2026-04-16 | **DEF-007 `fix-l3-acceptance-bugs` 归档**:BUG-2 TEXT_SIM_MIN_DOC_CHARS 500→300;BUG-3 get_current_user 支持 query param token + ExportButton/useDetectProgress SSE URL 追加 token;WARN-1 AdminRulesPage input null→"";L3 11/11 全绿 |
| 2026-04-16 | **DEF-006 `fix-silent-project-transition-failure` 归档**:run_pipeline 6 处 try_transition_project_ready 加异常保护;trigger.py task 引用持有+done callback 异常日志;4 新增 L1 用例 |
| 2026-04-16 | **DEF-004 `increase-samples-limit` 归档**:text_similarity samples 10→30, section_similarity 5→15 |
