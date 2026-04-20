# 项目 Handoff

> **跨会话/跨人接手的现场视角快照。** 计划视角见 `docs/execution-plan.md` §5。
>
> 本文档职责:记录"现在人在哪、下一步干什么、有什么没说清"。
> 最近变更历史只保留 5 条,更早历史去 `git log` 查。

---

## 1. 当前状态快照

| 项 | 值 |
|---|---|
| 当前里程碑 | **M4 完成 + V1 全量验收 + admin-llm-config** |
| 当前 change | `admin-llm-config` 归档完成。Admin 可在 Web UI 配置 LLM provider / api_key / model / base_url / timeout,保存即时生效,无需重启 |
| 最新 commit | admin-llm-config 归档 |
| 工作区 | admin-llm-config 全量改动:**后端**:`schemas/admin.py` 扩 `LLMConfigResponse/LLMConfigUpdate/LLMTestRequest/LLMTestResponse` + 新 `services/admin/llm_reader.py`(DB>env>默认 三层 fallback + `mask_api_key` 脱敏末 4 位)+ 新 `services/llm/tester.py`(test_connection 发 ping + max_tokens=1)+ 改 `services/llm/factory.py`(`@lru_cache` → 指纹哈希 dict cache + `invalidate_provider_cache` + 新增 `get_llm_provider_db` 异步 DB 路径)+ `routes/admin.py` 扩 `GET/PUT/POST test` 3 endpoint + Alembic 0010(SystemConfig.config.llm 默认值补写);**前端**:新 `AdminLLMPage.tsx`(provider Select / api_key Password / model / base_url / timeout InputNumber + 测试连接 + 保存 + 恢复默认)+ `App.tsx` 新 `/admin/llm` 路由 + `AppLayout.tsx` 管理子菜单加项 + `api.ts` 新增 3 API 函数 + `types/index.ts` 新增 LLM 类型;**测试**:L1 后端 11 + L1 前端 5 + L2 后端 8 = 24 新增用例,后端全量 1070/1070 绿,前端全量 97/97 绿;**spec sync**:新增 `admin-llm` spec(6 Req/14 Scenario);**L3 手工凭证**:`e2e/artifacts/admin-llm-2026-04-20/README.md` |

---

## 2. 本次 session 关键决策(2026-04-20,`admin-llm-config` propose+apply+archive)

### propose 阶段已敲定(5 产品级决策)

- **Q1 B dashscope + openai + custom**:白名单 3 种,custom = OpenAI 兼容端点
- **Q2 B 末 4 位保留**:`sk-****abc1`;短于 8 位固定 `sk-****` 占位
- **Q3 B 做测试连接按钮**:发 `"ping"` + max_tokens=1,最省 token
- **Q4 B 三层优先级**:DB > env > 代码默认;保持旧部署兼容
- **Q5 B 指纹哈希 cache + PUT 失效**:(provider, key, model, base, timeout) 作 key,PUT 后清空

### apply 现场决策

- **audit_log 暂不写 admin-llm 更新**:`AuditLog.project_id` 非空,系统级配置不挂项目;Follow-up 改 project_id nullable 或新建 SystemAuditLog
- **factory `get_llm_provider()` 保持同步签名 + env 路径**:11 个 Agent / judge / pipeline 现有调用零改动;新增 `get_llm_provider_db(session)` 异步路径供后续逐步切换
- **`@lru_cache` 换成 dict 指纹缓存**:上限 3,FIFO 淘汰,防病态输入撑爆
- **Tester `max_tokens=1` + timeout 强制 ≤10s**:防 UI 卡死
- **前端 api_key 空白不传**:占位符显示脱敏值,空白提交 → 后端保持旧值

### 文档联动

- **`openspec/specs/admin-llm/spec.md`** 新建:6 Req / 14 Scenario
- **`e2e/artifacts/admin-llm-2026-04-20/README.md`** L3 手工凭证
- **`docs/handoff.md`** 即本次更新

---

## 2.bak_C17 上一 session 关键决策(2026-04-16,C17 `admin-users` propose+apply)

- Q1 A 仅全局级 SystemConfig / Q2 A 覆盖写 + 恢复默认 / Q3 A admin 手动创建 / Q4 A §8 最小集
- L3 手工凭证:`e2e/artifacts/c17-2026-04-16/README.md`

---

## 2.bak_C15 上上一 session 关键决策(2026-04-16,C15 `report-export` propose+apply)

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
