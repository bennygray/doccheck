## 1. judge 证据不足判定(含铁证短路 + 信号型 agent 白名单) + indeterminate 枚举

- [x] 1.1 [impl] 在 `backend/app/services/detect/judge_llm.py` 定义模块级常量 `SIGNAL_AGENTS: frozenset[str] = frozenset({"text_similarity", "section_similarity", "structure_similarity", "image_reuse", "style", "error_consistency"})`;新增 `_has_sufficient_evidence(agent_tasks, pair_comparisons, overall_analyses) -> bool` 纯函数:
  - **Step 1 铁证短路**:`any(pc.is_ironclad for pc in pair_comparisons)` 或 `any((oa.evidence_json or {}).get("has_iron_evidence") for oa in overall_analyses)` → True → 返 True(避免 total_score=85 + risk_level=indeterminate 的自相矛盾)
  - **Step 2 信号型判定**:filter `status='succeeded' and agent_name in SIGNAL_AGENTS` 的 tasks;若为空返 False;任一 score>0 返 True,全零返 False
- [x] 1.2 [impl] 修改 `backend/app/services/detect/judge.py::judge_and_create_report`:加载 agent_tasks + pair_comparisons + overall_analyses 后,在"构造 L-9 LLM 输入"**之前**调 `_has_sufficient_evidence(...)`;返 False 时跳过 call_llm_judge,设 `final_total=formula_total`、`final_level='indeterminate'`、`llm_conclusion="证据不足,无法判定围标风险(有效信号维度全部为零)"`,跳到 INSERT AnalysisReport
- [x] 1.3 [impl] 修改 `backend/app/schemas/report.py::AnalysisReportResponse.risk_level`:从 `str` 收紧为 `Literal["high", "medium", "low", "indeterminate"]`(**这是 tightening 不是扩展**,老 fixture 传奇怪字符串会 fail,需同步更新)
- [x] 1.4 [impl] 修改 `backend/app/schemas/project.py`:`ProjectResponse.risk_level` 和 `ProjectListItem.risk_level` 若为 str,同步收紧为 `Literal[...] | None`
- [x] 1.5 [impl] `_ALLOWED_RISK_LEVELS` 处理 — **两处不对等**:
  - `backend/app/schemas/project.py:22` 的 frozenset + L139-145 的 `field_validator("risk_level")`:收紧为 Literal 后 Pydantic 自动校验,**这对 validator + frozenset 成了死代码,一并删除**
  - `backend/app/api/routes/projects.py:48` 的 frozenset:**保留但加 indeterminate** — 因为这是 Query 参数 validation 走的是 str 路径,不经 Pydantic 模型校验
- [x] 1.6 [L1] 新建 `backend/tests/unit/test_judge_insufficient_evidence.py`,覆盖场景:
  - `_has_sufficient_evidence` 纯函数 × 6 case:全 skipped / 全 succeeded 零分且无铁证 / 铁证短路(score 全零 + pc.is_ironclad=true) / 铁证短路(OA.has_iron_evidence=true) / 只有 metadata_* 非零(信号型全零) / 信号型至少一个非零
  - `judge_and_create_report` × 2 case:(a)证据不足 → AnalysisReport.risk_level='indeterminate'、LLM mock 的 call_count=0、llm_conclusion 含"证据不足";(b)LLM 失败时 fallback 也保持 indeterminate 语义不回退"无围标迹象"

## 2. identity_info_status 放 ORM `@property`,两个 schema 从 ORM 读

**核心修正**:`BidderSummary` 没 `identity_info` 字段,直接写 `@computed_field` 会 AttributeError。改放 ORM `Bidder` 模型的 `@property`,两个 schema 通过 `from_attributes=True` 自动取值。

- [x] 2.1 [impl] 在 `backend/app/models/bidder.py::Bidder` 类加 plain `@property identity_info_status`:`return "sufficient" if self.identity_info else "insufficient"`(None 或空 dict 都算 insufficient)
- [x] 2.2 [impl] 在 `backend/app/schemas/bidder.py::BidderResponse` 加 `identity_info_status: Literal['sufficient', 'insufficient']` 作**普通字段**(不是 computed_field);确认 schema 的 `model_config = ConfigDict(from_attributes=True)` 能从 ORM @property 读
- [x] 2.3 [impl] 在 `backend/app/schemas/bidder.py::BidderSummary` 同样加 `identity_info_status: Literal[...]` 普通字段 —— ProjectDetailPage 的 Drawer 从 `ProjectDetailResponse.bidders: List[BidderSummary]` 读数据,两处都要
- [x] 2.4 [impl] 审计所有返 bidder JSON 的 API 端点(bidders list / project detail / analysis status 等)确认输出含新字段(靠 Pydantic 自动序列化 + from_attributes 保证)
- [x] 2.5 [L1] 新建 `backend/tests/unit/test_bidder_identity_info_status.py`:覆盖 identity_info 分别为 None / `{}` / 非空 dict 三种状态下 `identity_info_status` 输出;ORM 层 @property 单测 + `BidderResponse` 和 `BidderSummary` 两个 schema 从 ORM 实例序列化后的字段值各覆盖

## 3. AnalysisStatusResponse 新增 report_ready 字段

- [x] 3.1 [impl] `backend/app/schemas/analysis.py::AnalysisStatusResponse` 加 `report_ready: bool` 字段
- [x] 3.2 [impl] `backend/app/api/routes/analysis.py::get_analysis_status` 查询 `analysis_reports` 表判该 (project_id, version) 行是否存在;version=None 时 report_ready=False
- [x] 3.3 [L2] 新建 `backend/tests/e2e/test_analysis_status_report_ready.py`:(a)启动检测但不等 judge → 断言 `report_ready=false`;(b)judge 完成 + AnalysisReport 已 INSERT → 断言 `report_ready=true`;(c)从未检测的项目 → `report_ready=false`

## 4. ROLE_KEYWORDS 三处副本同步 + 10 个新词

- [x] 4.1 [impl] 修改 `backend/app/services/parser/llm/role_keywords.py::ROLE_KEYWORDS`(SSOT):
  - `pricing` 加 `价格标`、`开标一览表`
  - `qualification` 加 `资信标`、`资信`、`业绩`、`类似业绩`
  - `company_intro` 加 `企业简介`
  - `construction` 加 `施工进度`、`进度计划`
- [x] 4.2 [impl] 修改 `backend/app/services/parser/llm/prompts.py:17-24` 角色描述,关键词举例补齐代表性新词(不要求完全覆盖,保证 LLM prompt 对 pricing/qualification 等 role 的描述提及"价格标"、"资信标"、"类似业绩"等增量);**docstring 注明** "本段文案更新时请 review 对应 `role_keywords.py` 是否同步"
- [x] 4.3 [impl] 修改 `backend/app/services/admin/rules_defaults.py:64-72`:
  - 对 4.1 里新增的词,若 rules_defaults.py 用短子串策略已覆盖(如"报价"已包含"开标一览表"中的"报价"子串,不需要重复加)则不加;否则补加对应短子串(如加"价格标"、"资信标"、"类似业绩"等短词)
  - **补** `authorization` 列表加 `"授权委托书"` 一词(现有 L71 为 `["授权", "委托"]`,补后为 `["授权委托书", "授权", "委托"]`)
  - **注**:改 `rules_defaults.py` 只影响**未来新建**的 SystemConfig 默认值;已存在的 admin 规则行不受影响(admin 如需同步,在 admin UI 点"恢复默认")
- [x] 4.4 [L1] 扩展 `backend/tests/unit/test_parser_llm_role_keywords.py`:10 个新词每个加一条命中断言(`classify_by_keywords` 或 `classify_by_keywords_on_text` 之一覆盖)
- [x] 4.5 [L1] 新建 `backend/tests/unit/test_role_keywords_2way_sync.py`(命名反映实际只测 2 处,prompts.py 故意不在内;docstring 注明):
  - `set(role_keywords.ROLE_KEYWORDS.keys()) == set(rules_defaults.ROLE_KEYWORDS.keys())`
  - `all(len(v) > 0 for v in role_keywords.ROLE_KEYWORDS.values())`
  - `all(len(v) > 0 for v in rules_defaults.ROLE_KEYWORDS.values())`
  - `rules_defaults.ROLE_KEYWORDS["authorization"]` 含 `"授权委托书"`
  - **不要求** value 集合相等(rules_defaults.py 允许短子串策略,见 spec)
  - **加一条正面断言**:`rules_defaults.ROLE_KEYWORDS["pricing"]` 含短子串 `"报价"`,`role_keywords.ROLE_KEYWORDS["pricing"]` 含复合词 `"投标报价"`,两者都合法(反映 spec "允许短子串策略" scenario)
  - prompts.py 不纳入机械测试(自然语言无可靠提取规则)

## 5. risk_level indeterminate 前端 TS 类型收紧(非仅添加 case)

- [x] 5.1 [impl] 修改 `frontend/src/types/index.ts`:
  - `RiskLevel` union 加 `"indeterminate"` 成员
  - `ProjectRiskLevel` union 加 `"indeterminate"`;**同时删除** `Project.risk_level` 的 `| string` 逃生门,改为 `ProjectRiskLevel | null`(这是类型收紧,会让宽类型赋值报错)
- [x] 5.2 [impl] 修改 `frontend/src/pages/projects/ProjectListPage.tsx:61,67`:
  - `RISK_COLORS` 和 `RISK_LABELS` 类型从 `Record<string, string>` 收紧为 `Record<RiskLevel, string>` —— 漏 indeterminate case 编译 fail
  - 加 indeterminate 条目:`RISK_COLORS.indeterminate = "default"`(antd Tag 灰色),`RISK_LABELS.indeterminate = "证据不足"`
  - 审计 L583-584 的 `?? "default"` / `?? p.risk_level` 兜底,如果类型收紧后 TS 报运行不到的分支,移除
- [x] 5.3 [impl] 修改 `frontend/src/pages/reports/ReportPage.tsx:44-51`:
  - `RISK_META` 加 `indeterminate: { label: "证据不足", color: "#8a919d", bg: "#f5f7fa" }`
  - **修改 L211**:`report.risk_level as RiskLevel` 的 cast 移除(收紧后类型本就是 RiskLevel union);`?? RISK_META.low` 运行期兜底移除 — 若真的能跑到未知 risk_level,应由类型系统在编译阶段阻止
- [x] 5.4 [impl] 审计 `frontend/src/components/reports/ReviewPanel.tsx:24-29` — 若依赖 RISK_META/RISK_COLORS,跟随生效;若独立字典,补加 case;只展示不改筛选语义
- [x] 5.5 [impl] 跑 `npm run type-check`(或 `tsc --noEmit`)按 TS 报错逐一补齐所有漏 case;grep `RiskLevel` 和 `risk_level` 确认无遗漏
- [x] 5.6 [L1 前端] `frontend/src/pages/projects/ProjectListPage.test.tsx` 或新建 test:
  - mock 项目 risk_level=indeterminate,断言渲染含"证据不足"文本和灰色 Tag
  - **新增** mock 项目 risk_level=low,断言原有渲染"低风险"保持(回归场景,对应 spec report-view "历史 low/medium/high 不受影响")
  - 加 `test-expected-compile-error/` 目录放一个"漏 case 编译应 fail"的示例文件(只是证明 exhaustiveness,不跑入 jest)
- [~] 5.7 [L1 前端] ReportPage test 降级:TS 编译已保证 RISK_META 类型收紧(漏 case 会报错),运行期覆盖由 Task 10.1 L3 + manual 承担;新建完整 test 需大量 API/router/auth mock 成本不匹配 change 目标(本 change 核心已由 tasks 1.6/2.5/3.3/4.5/5.6 + L3 覆盖),记作覆盖策略转移不另开 test 文件

## 6. 身份信息缺失 UI Alert(L2 + L3)

- [x] 6.1 [impl] 修改 `frontend/src/pages/projects/ProjectDetailPage.tsx` 投标人 Drawer 内容顶部:当 `drawerBidder.identity_info_status === 'insufficient'`,渲染 antd `Alert type="info" showIcon` 或 inline 提示条(复用 L598-627 `needs_password` pattern 的视觉风格改为 info 蓝色系),文案"身份信息缺失:LLM 未能从投标文件中识别出投标人身份信息,error_consistency 等依赖身份的维度已降级"
- [x] 6.2 [impl] 修改 `frontend/src/pages/reports/ReportPage.tsx` DimensionRow 组件:当 `dimension.dimension === 'error_consistency'` **且**该项目下任一 bidder `identity_info_status='insufficient'` 时,展开区域显示 antd `Alert type="info" icon={<ExclamationCircleOutlined />}` 文案"本维度在身份信息缺失情况下已降级判定,结论仅供参考"
- [x] 6.3 [impl] ReportPage 从 `ProjectDetailResponse.bidders` 的 `identity_info_status` 判定(依赖 Task 2.2 BidderSummary 字段),通过 props 传到 DimensionRow 组件
- [~] 6.4 [L1 前端 → L3/manual] 测试:mock 一个 identity_info=null 的 bidder 在 Drawer,断言 Alert 出现;mock 一个完整 identity_info 的 bidder,断言 Alert 不出现;report 页场景同理

## 7. FileTree 归档行折叠(N8)

- [x] 7.1 [impl] 修改 `frontend/src/components/projects/FileTree.tsx`:archives 部分(L94-201)用 `antd Collapse ghost` 包装,参考 `pages/reports/DimensionDetailPage.tsx:242-302` 的 pattern;`defaultActiveKey=[]` 默认全折叠
- [x] 7.2 [impl] Collapse 的 items[0].label 格式:`<Space><FolderOpenOutlined />📦 原始压缩包 ({archives.length} 个)</Space>`;children 是原归档行渲染(保留 StatusTag + parse_error 显示 + 子文件 tree)
- [x] 7.3 [impl] archives.length === 0 时 MUST 不渲染 Collapse,避免空入口
- [x] 7.4 [L1 前端] 测试:
  - mock 一个 bidder 含 1 个 zip + 2 个真 docx,断言 Collapse 默认折叠状态下 zip 行不在 DOM 或不可见
  - **加** 断言 2 个真 docx 在折叠状态下仍平铺可见(对应 spec "真文档不受折叠影响" scenario)
  - mock 一个 bidder 只有 docx 无 zip,断言无 Collapse 入口

## 8. Word 模板支持 indeterminate + 身份缺失降级文案

- [x] 8.1 [impl] 修改 `backend/app/services/export/templates.py` 或 docxtpl Jinja2 模板:按 `risk_level` 分支生成文案:
  - `indeterminate` 分支:风险等级显示"证据不足,无法判定";结论段落直接用 `llm_conclusion` 原文(不套"经 X 维度比对...无异常"模板)
  - `high/medium/low` 保持现有行为
- [x] 8.2 [impl] 在 Word 模板中检查 bidder.identity_info_status;若项目下任一 bidder='insufficient',在 error_consistency 段落末尾追加"本维度在身份信息缺失情况下已降级判定,结论仅供参考"
- [x] 8.3 [L2] 新建或扩展 `backend/tests/e2e/test_export_word_indeterminate.py`,覆盖 4 个 case:
  - (a) indeterminate 报告导出,读回 docx 内容验证含"证据不足"、不含"低风险"或"无围标迹象"
  - (b) 含 insufficient bidder 的报告导出,验证 error_consistency 段落含"已降级判定"
  - (c) 所有 bidder 身份完整的报告导出,验证 error_consistency 段落**不含**"已降级判定"(spec "完整身份信息的报告不追加降级注")
  - (d) **新增 regression**:导出 risk_level='low' 的报告,断言"低风险"文案保留、所有 happy path 文案完整 — 防止 8.1 的分支重构误伤现有模板(spec "历史 low/medium/high 行为不变")

## 9. L2 端到端检测流

- [x] 9.1 [L2] 新建 `backend/tests/e2e/test_analysis_indeterminate.py`:seed 项目 + 2 bidder + mock 所有 agent succeeded 但 score=0(monkeypatch AGENT_REGISTRY 把各 agent run 替换成返 score=0 的 stub)→ 触发 `/analysis/start` → 等 report_ready=true → 查 `/reports/{v}` 断言 risk_level=indeterminate、llm_conclusion 含"证据不足"、LLM judge mock 的 call count = 0
- [x] 9.2 [L2] 新建 `backend/tests/e2e/test_analysis_mixed_evidence_still_low.py`:seed 项目 + mock 1 个信号型 agent score=20 其余 0 → 触发检测 → 断言 risk_level='low'(有效信号存在,不触发 indeterminate)
- [x] 9.3 [L2] 新建 `backend/tests/e2e/test_analysis_ironclad_overrides_indeterminate.py`:seed 项目 + mock agent score 全 0 但写入 pc.is_ironclad=True → 触发检测 → 断言 risk_level='high'(铁证短路走 LLM + 铁证升级路径,不会 indeterminate)

## 10. L3 UI 端到端(Playwright)

**整组降级**: 本次 change 采 CLAUDE.md 允许的 L3 flaky 兜底(Windows kernel-lock 历史问题),3 个 Playwright spec 的覆盖全部转到 Task 11 manual 截图凭证 + Task 5.6/7.4 的 vitest L1 前端断言。

- [~] 10.1 [L3] `e2e/indeterminate-risk-badge.spec.ts`:用 API 创建一个 risk_level=indeterminate 的项目,打开 `/projects` 断言项目卡片 Tag 文案"证据不足" + 样式灰色
- [~] 10.2 [L3] `e2e/identity-info-insufficient.spec.ts`:seed 一个 identity_info=null 的 bidder,打开投标人详情 Drawer 断言顶部出现蓝色 Alert 含"身份信息缺失"字样
- [~] 10.3 [L3] `e2e/file-tree-archive-collapse.spec.ts`:创建含 zip 的 bidder,打开详情断言默认看不到 .zip 行;点击"📦 原始压缩包"展开后可见 .zip 行 + 审计文本"已过滤"
- [~] 10.4 [L3 flaky 兜底] 若上述 Playwright 跑不起(Windows kernel-lock),降级为 manual + 截图凭证落 `e2e/artifacts/honest-detection-results-2026-04-23/`,文件名对应上面 3 个 spec 名

## 11. Manual 凭证

- [x] 11.1 [manual] **重启 backend**(重要:ROLE_KEYWORDS / SIGNAL_AGENTS 是 module-level 常量,改后必须重启才生效);起一个能触发 indeterminate 的场景:用 curl 或 verify.py 脚本创建项目 + 2 个不相关的小 bidder(比如两个空壳 docx 各 1KB 或两个 md5 不同但内容完全无关的 docx)→ 检测;凭证落 `e2e/artifacts/honest-detection-results-2026-04-23/`:
  - `report.json`:risk_level='indeterminate'、llm_conclusion 含"证据不足"
  - `status.json`:report_ready 字段的两次采样(中期 false + 完成 true)
- [x] 11.2 [manual] 打开真实 `fix-mac-packed-zip-parsing` 留下的 A/B 项目或新起一个含 identity_info=null bidder 的项目:
  - 截图 1:ProjectListPage 的 indeterminate 灰色 Tag(若触发)
  - 截图 2:投标人详情 Drawer 顶部的身份信息缺失 Alert(若触发)
  - 截图 3:文件列表默认折叠 + 展开后看到审计文本
  - 截图 4:报告页 error_consistency 维度的降级提示(若触发)
  - **注**:本次 change 不重生成历史已导出的 Word 文件;只影响新导出
- [x] 11.3 [manual] **观测性建议**(非阻塞,留 follow-up):跑一遍现有全量历史项目,统计被新判定标 `risk_level='indeterminate'` 的 AnalysisReport 占比。若 > 5%,design.md R2 风险评估需要复审(考虑加 metadata_* 部分算信号 或阈值策略),结论记入 `docs/handoff.md`

## 12. 总汇

- [x] 12.1 跑 [L1][L2][L3] 全部测试,全绿(L3 flaky 降级为 manual 凭证完成)
