## ADDED Requirements

### Requirement: indeterminate 风险等级渲染

前端 UI SHALL 对 `risk_level='indeterminate'` 的项目/报告显示中性灰色 Tag 标签 + 文案"证据不足",区别于 high(红)/medium(橙)/low(绿)三档。视觉风格参考项目既有 `RISK_COLORS` / `RISK_META` 字典扩展模式(antd Tag color prop),不引入新组件。

- 颜色规范:前景 `#8a919d`(tokens.ts `textTertiary` 同色);背景 `#f5f7fa`(tokens.ts `bgLayout` 同色)
- 文案:`"证据不足"`
- 受影响前端渲染点(MUST 全部支持 indeterminate,缺一个会让用户在不同页面看到不一致状态):
  1. `pages/projects/ProjectListPage.tsx`:项目卡片风险标签(L67-71 `RISK_COLORS` / `RISK_LABELS`)
  2. `pages/reports/ReportPage.tsx`:Hero 仪表板风险标签(L44-51 `RISK_META`)
  3. `pages/reports/ReportPage.tsx`:GaugeCard 子组件(若其依赖 `RISK_META`,跟随自动生效)
  4. `components/reports/ReviewPanel.tsx`:复核面板的 risk_level 显示(仅展示,不改筛选语义)
- TypeScript 类型 `RiskLevel` 和 `ProjectRiskLevel` union MUST 加 `"indeterminate"` 成员;同时 MUST **收紧宽类型逃生门**:
  - `Project.risk_level` 的 `| string` 退化移除,仅保留 `ProjectRiskLevel | null`
  - `RISK_COLORS`、`RISK_LABELS` 的类型从 `Record<string, string>` 改为 `Record<RiskLevel, string>`,漏 case 编译 fail
  - `ReportPage.tsx` 里 `report.risk_level as RiskLevel ?? RISK_META.low` 运行期兜底移除,直接用 `RISK_META[report.risk_level]`(类型收紧后索引保证非 undefined)

#### Scenario: ProjectListPage 显示 indeterminate 标签

- **WHEN** 项目 `risk_level='indeterminate'`,用户打开项目列表
- **THEN** 项目卡片上显示中性灰色 Tag,文案"证据不足",不是绿色"低风险"

#### Scenario: ReportPage Hero 显示 indeterminate

- **WHEN** 检测报告 `risk_level='indeterminate'`,用户打开报告页
- **THEN** Hero 仪表板顶部风险标签显示灰色"证据不足";GaugeCard 视觉同步

#### Scenario: 历史 low/medium/high 报告不受影响

- **WHEN** 检测报告 `risk_level='low'`,打开报告
- **THEN** 渲染与 change 前一致(绿色"低风险"),无回归

#### Scenario: RISK_COLORS/LABELS 漏 case 编译 fail

- **WHEN** 开发者修改 `ProjectListPage.tsx::RISK_COLORS`(`Record<RiskLevel, string>` 收紧后)时漏加 `indeterminate` case
- **THEN** TypeScript 编译报缺 case 错误(TS2420 or TS2322),CI fail

#### Scenario: RISK_META 索引无运行期 fallback

- **WHEN** `ReportPage.tsx` 读取 `RISK_META[report.risk_level]`(类型收紧后 report.risk_level 为 RiskLevel union,无 as cast 无 `?? RISK_META.low` 兜底)
- **THEN** 索引结果保证非 undefined;若未来漏 case 类型系统立即报错,不会静默 fallback 到 low

---

### Requirement: 身份信息缺失降级 UI

前端 UI SHALL 在 2 个位置对 `bidder.identity_info_status='insufficient'` 显式显示降级文案(Word 导出同理,由 `report-export` capability 单独规定):

- **L2 投标人详情 Drawer 顶部**:`pages/projects/ProjectDetailPage.tsx` 投标人 Drawer 打开时,若该 bidder `identity_info_status='insufficient'`,Drawer 内容顶部显示一个 antd `Alert type="info"` 或 inline 提示条(参考 `needs_password` 场景 pattern),文案:"身份信息缺失:LLM 未能从投标文件中识别出投标人身份信息(公司全称/法人/资质编号等),error_consistency 等依赖身份的维度已降级。"
- **L3 报告页 error_consistency 维度**:`pages/reports/ReportPage.tsx` DimensionRow 渲染 error_consistency 维度时,若该项目至少一个 bidder `identity_info_status='insufficient'`,维度详情区域显示 antd `Alert type="info"` + `ExclamationCircleOutlined`,文案:"本维度在身份信息缺失情况下已降级判定,结论仅供参考。"

- 颜色:统一用 info(蓝色系),不用 warning(橙色已被 medium 风险 + needs_password 占用)
- 文案直接中文 hardcode(项目无 i18n 框架)

后端 schema MUST 同时在 `BidderResponse` 和 `BidderSummary` 两处暴露 `identity_info_status` 计算字段 —— 因为 `ProjectDetailPage` 的投标人 Drawer 从 `ProjectDetailResponse.bidders: List[BidderSummary]` 读数据,仅扩 `BidderResponse` 会让 L2 Drawer 读不到该字段。

#### Scenario: 投标人详情 Drawer 显示缺失提示

- **WHEN** bidder `identity_info=NULL`,用户打开该 bidder 的详情 Drawer
- **THEN** Drawer 内容顶部出现蓝色提示条,含"身份信息缺失"字样

#### Scenario: bidder 身份完整不显示提示

- **WHEN** bidder `identity_info={"company_full_name": "某某公司"}`
- **THEN** Drawer 不显示降级提示条,按原布局渲染

#### Scenario: 报告页 error_consistency 维度降级提示

- **WHEN** 项目下至少一个 bidder `identity_info=NULL`,用户打开报告页,展开 `error_consistency` 维度
- **THEN** 维度内显示蓝色 Alert,含"本维度在身份信息缺失情况下已降级判定"

#### Scenario: 项目所有 bidder 身份完整不显示报告提示

- **WHEN** 项目下所有 bidder 都有 identity_info
- **THEN** 报告页 error_consistency 维度不显示降级 Alert

#### Scenario: BidderSummary 含 identity_info_status

- **WHEN** 调 `GET /api/projects/{pid}` 拿 ProjectDetailResponse,读 `bidders: List[BidderSummary]`
- **THEN** 每条 BidderSummary 含 `identity_info_status: 'sufficient' | 'insufficient'` 字段;前端 Drawer 据此决定是否渲染 Alert

---

### Requirement: 归档行默认折叠

前端 `components/projects/FileTree.tsx` SHALL 对 `file_type in (.zip, .7z, .rar)` 的归档行使用 antd `Collapse ghost` 包装,默认折叠(`defaultActiveKey=[]`),复用 `pages/reports/DimensionDetailPage.tsx` 已有的 Collapse pattern。

- Collapse label 文案:`"📦 原始压缩包 ({n} 个)"` 其中 n 为归档行总数
- 展开后显示:每个归档行(保留现有 StatusTag + 子文件 tree 结构)+ 该归档行的 `parse_error` 字段(含审计文本"已过滤 N 个打包垃圾文件"等)
- 若该 bidder 无归档行(n=0),MUST 不渲染 Collapse(避免空入口)
- 真文档(非归档)的平铺渲染 MUST 保持不变,Collapse 只收拢归档部分

#### Scenario: 默认折叠压缩包行

- **WHEN** bidder 有 1 个 `.zip` 归档 + 3 个真 docx,用户打开详情
- **THEN** 文件列表默认只看到 3 个 docx,顶部有"📦 原始压缩包 (1 个)"折叠入口;.zip 行不可见

#### Scenario: 展开后看到审计文本

- **WHEN** 用户点击"📦 原始压缩包"展开
- **THEN** 看到 .zip 归档行 + 它的 parse_error 字段("已过滤 6 个打包垃圾文件"等审计文本)

#### Scenario: 无归档不渲染 Collapse

- **WHEN** bidder 只有直接上传的 docx(无 zip 归档)
- **THEN** 文件列表按原样平铺,不出现"📦 原始压缩包"折叠入口

#### Scenario: 真文档不受折叠影响

- **WHEN** bidder 有多类文件(docx / xlsx / jpg 直接 + zip 归档内文件)
- **THEN** 所有非归档的真文件平铺显示;归档 `.zip` 行折叠,展开后归档内文件也可见
