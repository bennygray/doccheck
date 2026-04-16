# 项目 Handoff

> **跨会话/跨人接手的现场视角快照。** 计划视角见 `docs/execution-plan.md` §5。
>
> 本文档职责:记录"现在人在哪、下一步干什么、有什么没说清"。
> 最近变更历史只保留 5 条,更早历史去 `git log` 查。

---

## 1. 当前状态快照

| 项 | 值 |
|---|---|
| 当前里程碑 | **M4 进行中(2/3)— C16 归档完成** |
| 当前 change | C16 `compare-view` 归档完成,下一步 C17 `admin-users` |
| 最新 commit | C15 归档 `6ca9390` — C16 archive commit 即将产生 |
| 工作区 | C16 全量改动:**后端**:新增 `schemas/compare.py`(3 组响应模型)+ `routes/compare.py`(3 个 GET 只读聚合 endpoint)+ `main.py` 注册 compare router;**前端**:`types/index.ts` 新增 10 接口(TextCompare/PriceCompare/MetaCompare 全套)+ `services/api.ts` 新增 3 API 函数 + `App.tsx` 新增 3 路由 + 改造 `ComparePage.tsx` 增加 Tab 栏+文本对比入口链接 + 新建 3 页(`TextComparePage` 双栏同步滚动+段落高亮+角色切换 / `PriceComparePage` 矩阵表格+标红+toggle+排序 / `MetaComparePage` 矩阵表格+着色+标灰+tooltip);**测试**:L1 后端 15 + L2 3 + L1 前端 11 = 29 新增用例;**spec sync**:新增 `compare-view` spec(7 Req)+ 更新 `report-view` spec(1 MODIFIED Req);**L3 手工凭证**:`e2e/artifacts/c16-2026-04-16/README.md` |

---

## 2. 本次 session 关键决策(2026-04-16,C16 `compare-view` propose+apply)

### propose 阶段已敲定(4 产品级决策)

- **Q1 A 贴 US 原文不扩**(用户拍板):文本=pair 级(bidder_a+bidder_b+doc_role),报价/元数据=全项目级(所有投标人矩阵);拒绝 B(scope 翻倍)/ C(仅多一层 filter 但价值有限)
- **Q2 C 全量展开 + "只看异常项" toggle**(用户拍板):默认全量显示所有报价项 + toggle 过滤;拒绝 A(缺聚焦能力)/ B(折叠默认隐藏违背审查全貌需求)
- **Q3 A 前端虚拟滚动 + 后端分页兜底**(用户拍板):90% 场景一次拿完,极端边界 >5000 段落分页;拒绝 B(文本对比同步滚动+跳转在分页下体验差)/ C(截断违背对比本义)
- **Q4 A 复用检测层 evidence**(用户拍板):文本高亮数据来自 PairComparison.evidence_json.samples,不重算 diff;拒绝 B(实时计算慢+与检测结果不一致)/ C(段内字符级 diff 增加复杂度,留 follow-up)

### propose 阶段我自己定(实施细节,design D1~D12)

- **D1 text evidence samples 最多 10 对**:a_idx/b_idx 对应 DocumentText.paragraph_index
- **D2 doc_role 未指定取 score 最高**:一对 (bidder_a, bidder_b) 可能多条 PC(每个 doc_role 一条)
- **D3 报价矩阵 item_name NFKC 对齐**:无 item_name 时退化为 (sheet_name, row_index) 位置对齐
- **D4 evidence 对齐优先简化**:apply 期简化为直接 item_name NFKC 退化(evidence 结构复杂,留 follow-up)
- **D5 元数据主文档 role 优先级**:commercial > technical > bid_letter > company_intro > other,同级取 id 最小
- **D6 METADATA_COMMON_VALUES 常量**:author/last_saved_by 白名单(administrator/admin/user/author/空)+ 80% 高频判定
- **D7 三条新路由**:`compare/text` / `compare/price` / `compare/metadata`
- **D8 三个 GET endpoint 统一前缀**:`/api/projects/{pid}/compare/`
- **D9 未引入 @tanstack/react-virtual**(YAGNI,段落量可控,原生 scroll 足够)
- **D10 段落 >5000 后端 limit/offset 分页兜底**
- **D11 测试:L1 26 + L2 3 + L3 手工**(实际落地 L1 后端 15 + L1 前端 11 + L2 3 = 29)
- **D12 follow-ups**:字符级 diff / LLM 语义对齐 item_name / 白名单管理 UI / 对比导出

### 文档联动

- **`openspec/specs/compare-view/spec.md`** 新建:7 Req(text API + price API + meta API + text FE + price FE + meta FE + Tab 导航)
- **`openspec/specs/report-view/spec.md`** 更新:1 MODIFIED Req(ComparePage Tab 导航 + 文本对比入口)
- **`docs/execution-plan.md §6`** 追加 1 行 C16 归档记录
- **`e2e/artifacts/c16-2026-04-16/README.md`** L3 手工凭证占位
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

- 无硬阻塞,**M4 进度 2/3**
- **Follow-up(C16 新增)**:**字符级 diff(段内高亮)**:当前只有段落级匹配(evidence samples),段内字符级 diff 需引入 diff-match-patch 或类似库
- **Follow-up(C16 新增)**:**price_consistency evidence 对齐优先路径**:当前报价对比用 item_name NFKC 退化对齐;完整路径需读 evidence_json 的 alignment 结构
- **Follow-up(C16 新增)**:**元数据通用值管理 UI**:当前白名单是后端常量;C17 admin 可扩展为可编辑
- **Follow-up(C16 新增)**:**对比页面导出为图片/PDF**
- **Follow-up(C15 留下)**:用户模板上传 UI / PDF 导出 / 批量导出 / audit 过滤器 / 导出历史页
- **Follow-up(C14 留下)**:跨项目历史共现 / L-5/L-8/L-9 retry+parse 共享抽取 / DIMENSION_WEIGHTS 实战调参 / L-9 prompt N-shot 精调
- **Follow-up(持续)**:Docker kernel-lock 未解(C3~C16 L3 全延续手工凭证)
- **Follow-up(持续)**:生产部署前 env 覆盖全清单(SECRET_KEY / AUTH_SEED_ADMIN_PASSWORD / LLM_API_KEY / 各 Agent env)

---

## 4. 下次开工建议

**一句话交接**:
> **C16 `compare-view` 已归档,M4 进度 2/3**。三类对比视图(文本双栏/报价矩阵/元数据矩阵)全部就绪,29 新增测试全绿。下一步 **C17 `admin-users`**(用户管理 + 规则配置),是 M4 最后一个 change。

**可直接粘贴给 AI 作为新会话起点**:
```
继续 documentcheck 项目。M4 进度 2/3,C16 compare-view 已 archive + push。
下一步进 M4 C17 /opsx:propose admin-users(M4 第三个也是最后一个 change)
  - 职责:US-8.1~8.4 + US-9.1 — 用户列表/创建/启用禁用 + 规则配置(报价/权重/阈值)
  - 输入:已就绪的 User 模型 + auth 系统(C2)
  - 输出:前端 admin 页面 + 后端 admin CRUD API + 规则配置 API
  - 不动:C6~C16 检测层/导出层/对比层(只读)
  - 参考:docs/execution-plan.md §3 C17 / §4 M4 判据
对应 docs/execution-plan.md §3 C17 小节。
请先读 docs/handoff.md 确认现状。
propose 阶段需用户敲定(产品/范围级):
  - 规则粒度:项目级 vs 全局级 vs 两者兼有
  - 规则版本:有版本号可回滚 vs 仅最新值
  - 用户创建:admin 手动创建 vs 支持自注册
也检查 memory 和 claude.md。
```

---

## 5. 最近变更历史(仅保留最近 5 条)

| 日期 | 变更 |
|---|---|
| 2026-04-16 | **C16 `compare-view` 归档(M4 进度 2/3)**:**后端** 3 只读 compare endpoint(text pair 级复用 evidence_json.samples / price 全项目 item_name NFKC 矩阵+偏差+总报价 / metadata 全项目 8 字段矩阵+通用值标记+color_group);**前端** 3 新页(TextComparePage 双栏同步滚动+sim 深浅高亮+点击跳转+角色切换 / PriceComparePage 矩阵+<1%标红+toggle+排序+总报价行 / MetaComparePage 矩阵+着色+标灰tooltip+模板红标+时间格式化)+ ComparePage Tab 栏改造;**29 新增用例全绿**(L1 后端 15 + L2 3 + L1 前端 11);4 决策(A/C/A/A);apply 现场:未引入 react-virtual(YAGNI)/ evidence 对齐简化为 item_name NFKC;spec sync:新建 compare-view 7 Req + 更新 report-view 1 MODIFIED Req |
| 2026-04-16 | **C15 `report-export` 归档(M4 进度 1/3,M4 起步)**:新增 4 capability(report-view / report-export / manual-review / audit-log)+ export_jobs 独立表 + Word 导出 + 人工复核(报告级+维度级)+ 操作日志;54 新增用例全绿;4 决策(C/D/A/D) |
| 2026-04-16 | **C14 `detect-llm-judge` 归档(M3 进度 9/9,M3 收官)**:judge 升级为公式+LLM+clamp 4 步+降级模板;55 新增用例;5 决策 |
| 2026-04-15 | **C13 `detect-agents-global` 归档(M3 进度 8/9)**:11 Agent 真实算法全就位,dummy 清空;140 新增用例 |
| 2026-04-15 | **C12 `detect-agent-price-anomaly` 归档(M3 进度 7/9)**:注册表扩至 11 Agent;49 新增用例 |
