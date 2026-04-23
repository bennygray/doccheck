# 项目 Handoff

> **跨会话/跨人接手的现场视角快照。** 计划视角见 `docs/execution-plan.md` §5。
>
> 本文档职责:记录"现在人在哪、下一步干什么、有什么没说清"。
> 最近变更历史只保留 5 条,更早历史去 `git log` 查。

---

## 1. 当前状态快照

| 项 | 值 |
|---|---|
| 当前里程碑 | **M4 完成 + V1 全量验收 + admin-llm-config + fix-mac-packed-zip-parsing + honest-detection-results** |
| 当前 change | `honest-detection-results` 归档完成。修复"检测结果看起来 OK 实则沉默失败"的 5 类产品语义问题:**证据不足判定(F2)** risk_level 新增 `indeterminate` 枚举 + judge 层"非 skipped 信号型 agent 全零且无铁证"前置判定 + 跳过 LLM 直接返"证据不足"结论;**identity_info 缺失显式降级(F3)** ORM `@property` + BidderSummary/BidderResponse 双 schema 暴露 `identity_info_status` + 前端 Drawer / 报告页 error_consistency / Word 模板三处 info 蓝色降级文案;**ROLE_KEYWORDS 三副本同步(N2)** 补 10 个行业术语("价格标/开标一览表/资信标/资信/业绩/类似业绩/企业简介/施工进度/进度计划") + `rules_defaults.py.authorization` 补"授权委托书" + 2way sync 测试(SSOT role_keywords.py 与 admin/rules_defaults.py 的 key 集合一致 + value 非空 + defaults 是 SSOT 的短子串);**report_ready 字段(N4)** `/analysis/status` 新增 bool 字段区分"agent 终态 vs judge 完成";**前端 TS 类型收紧(D5)** 移除 `ProjectRiskLevel \| string` 逃生门 + `Record<RiskLevel, ...>` 强制覆盖 + 删除运行期 `?? RISK_META.low` 静默 fallback;**FileTree 归档行默认折叠(N8)** antd `Collapse ghost` 包装 `.zip/.7z/.rar` 归档行 |
| 最新 commit | honest-detection-results 归档 |
| 工作区 | honest-detection-results 全量改动:**后端代码**:`services/detect/judge_llm.py` 新增 `SIGNAL_AGENTS` 常量 + `_has_sufficient_evidence()` 纯函数(含铁证短路 + 信号型白名单)+ `INSUFFICIENT_EVIDENCE_CONCLUSION` 常量;`services/detect/judge.py` `judge_and_create_report()` 加证据不足前置分支;`models/bidder.py` 加 `identity_info_status @property`;`schemas/{bidder,project,report,analysis}.py` 加 Literal + computed 字段 + report_ready;`api/routes/analysis.py` 填充 report_ready;`api/routes/projects.py::_ALLOWED_RISK_LEVELS` 加 indeterminate;`services/parser/llm/role_keywords.py` 加 10 新词;`services/parser/llm/prompts.py` 同步角色描述;`services/admin/rules_defaults.py` 同步 + 补授权委托书;`services/export/{generator,worker}.py` 支持 risk_level_cn/is_indeterminate/has_insufficient_identity 降级段落。**前端代码**:`types/index.ts` union 扩展 + 删 `\| string` 逃生门 + Bidder/BidderSummary 加 identity_info_status + AnalysisStatusResponse 加 report_ready;`ProjectListPage.tsx` RISK_COLORS/LABELS 收紧为 Record<RiskLevel,...>;`ReportPage.tsx` RISK_META 加 indeterminate 条 + 拉 project detail 判 hasInsufficientIdentity + DimensionRow 降级 Alert + 删 as/fallback 兜底 + 404 retry 改用 /analysis/status 给精确文案;`ProjectDetailPage.tsx` Drawer 顶部 info Alert 条件渲染;`FileTree.tsx` archives 部分用 Collapse ghost 默认折叠;`useDetectProgress.ts` SSE report_ready 事件用 RiskLevel 替换硬编码 union。**测试**:L1 新增 `test_judge_insufficient_evidence.py` (10 case)/`test_bidder_identity_info_status.py`(6 case)/`test_role_keywords_2way_sync.py`(7 case)、扩展 `test_parser_llm_role_keywords.py` + `test_judge_pair_oa.py` fixture;L2 新增 `test_analysis_indeterminate.py`(3 case)/`test_analysis_status_report_ready.py`(3 case)/`test_export_word_indeterminate.py`(6 case);前端新增 `DimensionRow.test.tsx`(4 case)+ 扩展 `FileTree.test.tsx`/`ProjectListPage.test.tsx`;L1 全量 940/940 绿;L2 受影响子集 25/25 绿;前端 vitest 新增 14 case 全绿 + 全量 99/100(1 无关 flaky AdminUsersPage);TS --noEmit clean;**spec sync**:`detect-framework` 加 "证据不足判定规则"/"AnalysisReport risk_level 新增 indeterminate" + 改 "综合研判骨架" 插 step4 + 改 "检测状态快照 API" 加 report_ready + 4 scenario;`parser-pipeline` 改 "角色关键词兜底规则" 加三副本同步约束 + 10 新词 scenario;`report-view` 加 3 Req;`report-export` 加 1 Req;**manual 凭证**:`e2e/artifacts/honest-detection-results-2026-04-23/` JSON — identity_info_status 字段工作 ✓、report_ready 中 false / 完成 true ✓、C3 铁证短路避免 "indeterminate + 85 分" 自相矛盾 ✓(真实 docx metadata 碰撞触发,走 LLM 正确给出 high + 合理结论) |

---

## 2. 本次 session 关键决策(2026-04-23,`honest-detection-results` propose+apply+archive)

### 上游触发
上一 change `fix-mac-packed-zip-parsing` 归档时列出的 10 条 follow-up,其中 5 条(F2/F3/N2/N4/N8)合并成本 change "用户看得到的诚实性"。F1/N5/N6/N7 基础设施鲁棒性下次做;N3 LLM 大文档精度先 explore。

### propose 5 个产品决策(Q1-Q5 已与用户对齐)
- **Q1 B**:"非 skipped 的信号型 agent 全部 score=0 且无铁证" → 证据不足
- **Q2 C**:`risk_level` 新增 `indeterminate` 枚举值(不用标志位,一次到位类型系统强制覆盖)
- **Q3 L2+L3+L5**:身份信息缺失显示位置 = 投标人详情 Drawer 顶部 + 报告 error_consistency 维度 + Word 导出降级文案(不做列表页/对比页)
- **Q4 a**:ROLE_KEYWORDS 10 个强烈建议新词(价格标/开标一览表/资信标/资信/业绩/类似业绩/企业简介/施工进度/进度计划)
- **Q5 B**:归档行用 `antd Collapse ghost` 默认折叠,复用 DimensionDetailPage 已有 pattern

### apply 现场决策(技术层,不问用户)
- **D1 信号型 agent 白名单**:SIGNAL_AGENTS 只含 text/section/structure/image/style/error_consistency,剔除 metadata_* + price_consistency("0 == 没异常" 不算无信号)—— 缓解"干净项目被误判 indeterminate"
- **D1 铁证短路**:PC.is_ironclad / OA.has_iron_evidence 任一为 True → 证据充分 True(避免 `total_score=85 + risk_level=indeterminate` 自相矛盾)
- **D4 identity_info_status 放 ORM @property + from_attributes=True**:而不是 Pydantic computed_field(BidderSummary 没 identity_info 字段,computed_field 会 AttributeError)
- **D5 前端 TS 收紧路径**:`Record<RiskLevel, ...>` + 删 `| string` 逃生门 + 删运行期 `?? RISK_META.low` — 第 1 轮 reviewer 指出原"TS 强制覆盖"承诺是虚假保证,收紧后才真成立
- **D7 ROLE_KEYWORDS 同步约束降级**:SSOT=role_keywords.py;defaults 允许短子串(故意不强求值相等);弱一致性=defaults 每词 MUST 是 SSOT 某词的子串;prompts.py 不进机械测试(自然语言无可靠提取规则),靠 docstring 人工 review
- **D10 report_ready vs project.status 顺序**:INSERT AnalysisReport → UPDATE project.status 之间有 ~几十毫秒窗口,前端 MUST 以 report_ready 为权威拉取判据(spec scenario 明确)
- **I-3 补 DimensionRow 孤立组件测试**:第 3 轮 reviewer 指出 Task 5.7/6.4 降级 manual 后, `<Alert data-testid="dimension-identity-degraded">` 零自动化覆盖 — export DimensionRow + 4 case 孤立 render 测试

### 文档联动
- **`openspec/specs/detect-framework/spec.md`** 改:"综合研判骨架" 插 step4 + 加 scenario;"检测状态快照 API" 加 report_ready + 4 scenario
- **`openspec/specs/detect-framework/spec.md`** 加:"证据不足判定规则" / "AnalysisReport risk_level 新增 indeterminate" 两 Requirement
- **`openspec/specs/parser-pipeline/spec.md`** 改 "角色关键词兜底规则":加三副本同步约束 + 10 新词 scenario + authorization 条说明
- **`openspec/specs/report-view/spec.md`** 加 3 Req
- **`openspec/specs/report-export/spec.md`** 加 1 Req
- **`docs/handoff.md`** 即本次更新

### 3 轮独立 review 均 CONDITIONAL GO → GO(最终)
- 第 1 轮:TS 强制覆盖虚假保证 / BidderSummary 无 identity_info / 铁证 vs indeterminate 冲突 / 三副本 set 相等不可靠 — 全修
- 第 2 轮:BidderSummary computed_field AttributeError / _ALLOWED_RISK_LEVELS 漏改 / Word 模板 low/medium/high 回归 / report_ready vs project_status 顺序 — 全修
- 第 3 轮:useDetectProgress SSE risk_level 漏 indeterminate / report_ready 前端无消费点 / 2way sync 弱一致性缺失 / DimensionRow 零自动化 — 全修

### 遗留到下一 change(`harden-async-infra`)
- F1 ProcessPool per-task 进程隔离
- N5 testdb 容器化
- N6 `make_gbk_zip` fixture 重写
- N7 LLM provider `.complete()` 统一 `asyncio.wait_for`

N3 LLM 大文档精度先 `/openspec-explore` 再决定。11.3 Manual 观测建议:跑全量历史项目统计 indeterminate 占比,>5% 触发 design 复审。

---

## 2.bak_fix-mac-packed-zip-parsing 上一 session 关键决策(2026-04-23,`fix-mac-packed-zip-parsing` propose+apply+archive)

### 案例触发
- 真实 A/B zip(`e2e/artifacts/supplier-ab/supplier_A.zip` 166MB / `supplier_B.zip` 9.8MB,macOS Archive Utility 打包)暴露:parser 流水线**静默降级为无意义结果**(bid_documents.role 全 None、identity_info 全 null、检测报告"全零 + 低风险无围标"误导结论)
- 用户感知:"流程跑不同/卡住了" — 实则流水线跑完但结果全 0

### propose 阶段已敲定(产品/范围级决策)
- **A/B/C 选项分三层**:A 最小(只修 macOS 那批)、B 完整黑名单(+Windows/Office/VCS,**推荐选中**)、C 白名单严打(被否决:扩展名白名单过不掉 `~$x.docx` 这类恰好是 .docx 的临时文件)
- **区分"垃圾丢弃" vs "不支持但告知"**:打包垃圾 → 静默丢弃不产 bid_documents 行;非业务扩展名 → 保留 skipped 反馈用户
- **identity_info 不做规则兜底**:保持 spec 原意("避免精度差导致污染"),follow-up 由 UI/报告侧显示"识别信息缺失"文案

### apply 现场决策
- **保留 engine.py 既有 GBK 启发式 + 后置 UTF-8 校验**(而非整段删改):零回归路径,Windows GBK 包不受影响
- **`classify_by_keywords` 契约变更** None on miss(原返 "other"):便于上层两级兜底区分"命中 other" vs "未命中";同步更新唯一 production 调用点 + 2 个测试文件
- **fixture scope-safe 清理**:共享 dev DB 里有 project 226 的老数据,既有 `test_parser_llm_role_classifier.py` 的 `DELETE WHERE id>0` 会和 FK 冲突;改为按 `User.username` 前缀过滤只删本测试的 seed
- **端到端修 `_phase_extract_content`**(范围外但必要):真实 A/B 验收暴露 pipeline 把 .zip 归档行也扔给 `extract_content`,标成"未知文件类型 .zip" 覆盖我写入的 "已过滤 N 个" 审计文本;加一行 `file_type.in_([".docx",".xlsx"])` 过滤 + 回归测试
- **L2 fixture 手工构造 UTF-8-no-flag ZIP**:Python stdlib `zipfile` 对非 ASCII 文件名会强制置位 bit 11,无法原生模拟 macOS 无 flag 场景;手写本地文件头+中心目录+EOCD 精确控制 flag
- **manual 凭证用 JSON 代截图**:CLI 环境无 GUI,`verify.py` 调真 LLM 跑完整流程把 `bidders_before_detect / documents_A / documents_B / analysis_status / report` JSON 落盘到 `e2e/artifacts/supplier-ab/after-fix/`

### 文档联动
- **`openspec/specs/file-upload/spec.md`** 改 "压缩包安全解压" Requirement,+6 新 Scenario
- **`openspec/specs/parser-pipeline/spec.md`** 改 "LLM 角色分类与身份信息提取" + "角色关键词兜底规则" 两个 Requirement
- **`docs/handoff.md`** 即本次更新

### 发现但 **不在本次 change 范围** 的遗留问题(10 条)
参见 archive 目录 `openspec/changes/archive/2026-04-23-fix-mac-packed-zip-parsing/design.md` §5"Open Questions" 上下文。总览 + 优先级:
- **F2 高**:judge LLM 全零/全 skipped 时仍给"无围标"误导结论 — 应返"证据不足"
- **F1 中**:ProcessPool 崩溃兜底(per-task 进程隔离);A/B 案例靠垃圾过滤"绕过"但根因没修
- **F3 中**:identity_info NULL 时 UI/报告侧文案降级
- **N3 中**:大文档(如 161MB docx)下 LLM role_classifier 精度退化(A 全走兜底 low,B 全 high)— 需先开日志调查
- **N5 中**:共享 dev DB 污染导致 `pytest tests/e2e/` 全量跑不动 — testdb 容器化
- **N7 低-中**:LLM provider `.complete()` 没统一 `asyncio.wait_for`
- **N2 低-中**:`ROLE_KEYWORDS` 补 "价格标"/"资信标"(A 的"价格标/资信标"因此没命中 pricing/qualification)
- **N4 低**:analysis completion 与 report 生成时序不对齐(需加 `report_ready` 字段)
- **N6 低**:`make_gbk_zip` fixture 实际产出不是声称的东西(flag 被强制置位)— 重写
- **N8 低**:归档行(.zip)在 UI 的语义模糊 — 按 file_type 折叠

---

## 2.bak_admin-llm-config 上一 session 关键决策(2026-04-20,`admin-llm-config` propose+apply+archive)

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
- **Follow-up(产品决策搁置,2026-04-22)**:投标包内若报价单为 `.doc/.docx` 而非 `.xlsx`,当前链路**静默 skip**(无报错),导致 price_consistency 维度漏检
  - 现状代码位置:`run_pipeline.py:_find_pricing_xlsx` 硬过滤 `.xlsx` / `fill_price.py` 仅走 `extract_xlsx` / `price_consistency.py` preflight 找不到时 skip
  - 已评估两条路径并**搁置**:
    - 最小止血(1 天):改为显式 failed + UI 提示"报价单非 xlsx 格式,需人工"
    - 完整方案(6-8 天):抽象 tabular region + docx 表抽取 + LLM 兜底 C(详见此 session 讨论记录)
  - 触发重启条件:业务侧反馈 docx 报价单出现频率显著上升,或出现因此漏检的围标 case

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
| 2026-04-23 | **`honest-detection-results` 归档**:F2 证据不足+indeterminate 枚举(铁证短路 + 信号型 agent 白名单)+ F3 identity_info_status ORM property 三处显式降级文案 + N2 ROLE_KEYWORDS 10 新词三副本同步 + N4 report_ready 字段 + 前端 TS 类型收紧(删 \| string 逃生门+Record<RiskLevel,...>)+ N8 FileTree Collapse 折叠;L1 940、L2 25、前端 vitest 14 新增全绿;3 轮独立 reviewer 报告全吸收 |
| 2026-04-23 | **`fix-mac-packed-zip-parsing` 归档**:macOS 打包 zip 的 3 个级联缺陷(打包垃圾 + UTF-8 无 flag 文件名 + role 分类链路断裂)一次修 + bonus 修 phase1 覆盖归档行 parse_error;真 A/B zip 验收 bid_documents 12/14→4/4、identify_failed 12→0、role=None 26→2、检测报告非零信号 |
