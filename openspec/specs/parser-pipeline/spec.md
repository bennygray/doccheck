# parser-pipeline Specification

## Purpose

为投标人文档提供完整解析流水线: DOCX/XLSX 内容提取(段落/页眉脚/文本框/表格/图片/元数据)、LLM 角色分类与投标人身份信息提取、LLM 报价表结构识别(项目级单次)、报价数据批量回填、SSE 完整事件流、人工修正(改文档角色 / 改列映射并重新回填)。本 capability 把 C4 落地的 `bidders` / `bid_documents` 物理文件转为结构化数据,为 C6+ 围标检测各 Agent 提供输入。

## Requirements


### Requirement: 文档内容提取

系统 SHALL 对每个 `parse_status='extracted'` 的 DOCX/XLSX 文件执行内容提取,落库到 `document_texts` / `document_metadata` / `document_images` / `document_sheets` 四张表。提取在 pipeline 的 `identifying` 阶段早段发生(内容提取成功后才进入 LLM 调用)。

- **DOCX**:提取正文段落、页眉页脚、文本框文本、表格每行合并文本,逐条写 `document_texts`,`location` 标注来源(`body` / `header` / `footer` / `textbox` / `table_row`)
  - **文本框抽取**(parser-accuracy-fixes P2-8):SHALL 使用 `lxml.etree.XPath()` 直接编译 xpath + `nsmap={"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}`,绕开 `python-docx.BaseOxmlElement.xpath(namespaces=...)` 已废 kwarg;提取到的 textbox 文本(去空白后非空)MUST 各写一条 `document_texts, location='textbox'`
- **XLSX**:
  - 提取所有 sheet(含隐藏 sheet)的合并文本,每 sheet 一条写 `document_texts`,`location='sheet'`(供相似度 Agent 消费)
  - **同时** 写 `document_sheets` 表,每 sheet 一行,含 `sheet_index` / `sheet_name` / `hidden` / `rows_json`(整表 cell 矩阵 JSONB)/ `merged_cells_json`(合并单元格 ranges 字符串列表 JSONB)
  - xlsx 持久化裁切:`rows_json` 行数 > `STRUCTURE_SIM_MAX_ROWS_PER_SHEET`(默认 5000)→ 截断前 5000 行 + warning 日志;不阻塞写入
- **元数据**:从 DOCX/XLSX 的 `docProps/core.xml` + `docProps/app.xml` 抽 `author / last_saved_by / company / created_at / modified_at / app_name / app_version / template`,写 `document_metadata`(每文档 1:1)
- **图片**:DOCX 嵌入图片落盘到 `extracted/<pid>/<bid>/<hash>/imgs/`,计算 md5(32hex)+ phash(64bit),写 `document_images`
- 不支持的格式(DOC/XLS/PDF):`bid_documents.parse_status='skipped'` + `parse_error='暂不支持 {ext} 格式'`,**不**写 document_texts/metadata/images/sheet

#### Scenario: docx 含文本框 lxml 抽取成功
- **WHEN** 解析一份 docx 含文本框 `<w:txbxContent><w:t>盖章处</w:t></w:txbxContent>`
- **THEN** `document_texts` 新增至少 1 条 `location='textbox' AND text LIKE '%盖章处%'`;**不**触发 `BaseOxmlElement.xpath() got an unexpected keyword argument 'namespaces'` 警告

#### Scenario: docx 无文本框不影响其他抽取
- **WHEN** 解析一份不含文本框的 docx
- **THEN** `document_texts` 无 `location='textbox'` 行;其他 location 行正常;无日志警告

#### Scenario: 标准 DOCX 提取段落

- **WHEN** 解析一个含 20 段正文 + 1 个文本框 + 1 个 3 行表格的 DOCX
- **THEN** `document_texts` 新增 ≥ 24 条(20 段 + 1 文本框 + 3 表行);`paragraph_index` 按源序递增;正文段 `location='body'`,文本框 `location='textbox'`,表行 `location='table_row'`

#### Scenario: DOCX 页眉页脚单独提取

- **WHEN** DOCX 含页眉"某公司"与页脚"第 N 页",调用 extract_content
- **THEN** `document_texts` 中该文档至少两条 `location='header'` / `location='footer'` 的记录;**不进入** `location='body'`(US-4.2 AC-3 "不参与文本相似度")

#### Scenario: XLSX 多 sheet 提取

- **WHEN** 解析含 3 个 sheet(1 个隐藏)的 XLSX
- **THEN** `document_texts` 为该文档生成 3 条 `location='sheet'` 记录(含隐藏 sheet);每条 text 字段为该 sheet 所有单元格按行拼接后的字符串

#### Scenario: XLSX 多 sheet 提取含 DocumentSheet

- **WHEN** 解析一份含 3 sheet 的 xlsx(其中 1 隐藏)
- **THEN** `document_texts` 新增 3 条 `location='sheet'`(保留既有行为);`document_sheets` 新增 3 条,`sheet_index` 为 0/1/2,`hidden` 对隐藏 sheet 为 true,`rows_json` 为 cell 矩阵(list of list),`merged_cells_json` 为字符串列表

#### Scenario: XLSX 巨型 sheet 裁切

- **WHEN** 解析一份单 sheet 含 8000 行的 xlsx
- **THEN** `document_sheets.rows_json` 含 5000 行(前 5000);日志 warning 记录 "sheet 'X' 截断 3000 行";不阻塞文档解析流程

#### Scenario: 元数据正确提取

- **WHEN** 解析一个 `core.xml` 含 `<dc:creator>张三</dc:creator>` 的 DOCX
- **THEN** `document_metadata.author = '张三'`;其他字段按 xml 内容或 NULL

#### Scenario: 元数据缺失字段写 NULL

- **WHEN** DOCX 的 `docProps/core.xml` 不存在某字段(如 company)
- **THEN** `document_metadata.company = NULL`;不抛错,其他字段正常

#### Scenario: Template 字段正确提取

- **WHEN** 解析一份 `docProps/app.xml` 含 `<Template>Normal.dotm</Template>` 的 DOCX
- **THEN** `document_metadata.template = 'Normal.dotm'`

#### Scenario: Template 字段缺失写 NULL

- **WHEN** DOCX 的 `docProps/app.xml` 无 `<Template>` 节点或文件不存在
- **THEN** `document_metadata.template = NULL`;不抛错,其他字段正常

#### Scenario: 嵌入图片提取与 hash 计算

- **WHEN** DOCX 嵌入 1 张 JPG 图片
- **THEN** `document_images` 新增 1 条,`md5` 为 32 位十六进制字符串;`phash` 为 64 字符 hex 或 64 bit 01 字符串(约定长度 64 字符);`file_path` 指向 `extracted/<pid>/<bid>/<hash>/imgs/<img_hash>.jpg`,物理文件存在

#### Scenario: 不支持的格式跳过

- **WHEN** bid_document.file_type = '.pdf'
- **THEN** extract_content 不写 document_texts / metadata / images;`bid_documents.parse_status='skipped'`;`parse_error='暂不支持 .pdf 格式'`

#### Scenario: 单文件解析失败不阻塞其他文件

- **WHEN** 一个 bidder 下 3 个 DOCX,其中 1 个损坏(python-docx 抛异常)
- **THEN** 损坏文档 `parse_status='identify_failed'` + `parse_error='<异常前 500 字>'`;其他 2 个正常 `parse_status='identified'`;bidder 聚合状态 = `identified`(因为 partial failure 不阻断)或 `identify_failed`(若全部失败)
---

### Requirement: LLM 角色分类与身份信息提取

系统 SHALL 对每个 `extracted` 的 bidder 执行 **一次 LLM 调用** 完成两项任务:9 种角色分类 + 投标人身份信息提取。输入为该 bidder 所有 DOCX/XLSX 文件的 `(file_name, first_500_chars_of_body_text)` 列表;输出为 `{roles: [{document_id, role, confidence}], identity_info: {...}}`。

**LLM 之后 SHALL 追加一步 `identity_validator` 规则校验**(parser-accuracy-fixes):
- 扫 `DocumentText where location='body'`(该 bidder 下 `.docx` 文件的正文段),按 paragraph_index 升序遍历
- 用正则 `投标人\s*[（(]?\s*盖章\s*[）)]?\s*[:：]\s*(.+?)(?:\n|\s{2,}|$)` 匹配,捕获第一个命中的公司名作为 `rule_bidder_name`
- 比对 LLM 返回的 `identity_info.company_full_name`(下称 `llm_bidder_name`):
  - **规则未命中**(rule_bidder_name=None):保留 LLM 结果不变
  - **两者一致**(相等或互为子串):保留 LLM 结果,`role_confidence` 维持 LLM 判定
  - **两者不一致**:以规则结果覆盖 `identity_info.company_full_name = rule_bidder_name`;`identity_info._llm_original = llm_bidder_name`(审计字段保留原值);相关 file_role 的 role_confidence 置 `low`(前端显示"待确认")

- **角色枚举**(9 种):`technical / construction / pricing / unit_price / bid_letter / qualification / company_intro / authorization / other`
- **身份信息** JSONB schema:`{company_full_name?, company_short_name?, project_manager?, legal_rep?, qualification_no?, contact_phone?, _llm_original?}`,所有字段可选;`_llm_original` 仅规则覆盖场景写入
- **LLM 失败兜底**(D2 决策 + fix-mac-packed-zip-parsing 补丁):
  - 角色分类:两级兜底链路
    1. 先对 `parse_status=identified` 的 DOCX/XLSX 读取 `document_texts` 首段 ≤1000 字(按 `paragraph_index` 升序取 `location='body'` 最早的段落),调 `classify_by_keywords_on_text` 做子串关键词匹配(复用 `ROLE_KEYWORDS`);命中即返回对应角色,`role_confidence='low'`
    2. 未命中(或该文档正文为空/未 identified)再落到 `classify_by_keywords(doc.file_name)` 文件名兜底;仍未命中则 `role='other', role_confidence='low'`
  - 身份信息:不做规则兜底(与 identity_validator 共用规则但场景分离:LLM 失败 → identity_info=NULL;LLM 成功 → identity_validator 校验覆盖)
- 结果写 `bid_documents.file_role` / `bid_documents.role_confidence` / `bidders.identity_info`

#### Scenario: 规则与 LLM identity 一致保留 LLM
- **WHEN** LLM 返回 `identity_info.company_full_name="攀钢集团工科工程咨询有限公司"`;rule scan 命中同名
- **THEN** `bidders.identity_info.company_full_name == "攀钢集团工科工程咨询有限公司"`;无 `_llm_original` 字段;role_confidence 不被 identity_validator 降级

#### Scenario: 规则与 LLM identity 不一致规则覆盖
- **WHEN** LLM 返回 `identity_info.company_full_name="锂源(江苏)科技有限公司"`(招标方误判);rule scan 命中"攀钢集团工科工程咨询有限公司"
- **THEN** `identity_info.company_full_name = "攀钢集团工科工程咨询有限公司"`(规则覆盖);`identity_info._llm_original = "锂源(江苏)科技有限公司"`;该 bidder 下所有 docx/xlsx 的 role_confidence 置 `low`(前端"待确认"标签)

#### Scenario: 规则未命中保留 LLM identity
- **WHEN** LLM 返回 `identity_info.company_full_name="某公司"`;rule scan 未找到"投标人(盖章)："后的公司名(如模板文字缺失)
- **THEN** `identity_info.company_full_name == "某公司"`(LLM 结果保留);无 `_llm_original`;role_confidence 不被降级

#### Scenario: 规则命中跨行公司名
- **WHEN** docx 正文"投标人(盖章):  江苏省华厦\n工程项目管理有限公司"(公司名跨 2 段)
- **THEN** 规则 non-greedy 匹配首段公司名"江苏省华厦",**不**跨段合并;若 LLM 返回完整名则视为不一致,规则覆盖为"江苏省华厦" — 场景作为已知限制,建议用户填写完整不跨行(follow-up 可扩规则跨段合并)

#### Scenario: 正常 LLM 成功分类

- **WHEN** 一个 bidder 有 5 个 DOCX(含"技术方案.docx"/"投标报价.xlsx"等),LLM 返回有效 JSON,identity_validator 规则或一致或未命中
- **THEN** 5 个文档各得一个 `file_role` 值;`bidders.identity_info` 非 NULL;bidder.parse_status = `identified`;SSE 推 `document_role_classified` × 5 + `bidder_status_changed` 事件

#### Scenario: LLM 超时走规则兜底

- **WHEN** 调用 LLM 返回 `LLMResult.error.kind='timeout'`
- **THEN** 所有文档先走正文关键词兜底、未命中再走文件名关键词兜底;命中任一路径 → 对应角色 + `role_confidence='low'`;全未命中 → `role='other', role_confidence='low'`;`bidders.identity_info = NULL`;bidder 进 `identified`

#### Scenario: LLM 返回非法 JSON 走规则兜底

- **WHEN** LLM 返回 `text='{"roles": [...' 缺右括号
- **THEN** 视同 `bad_response` 错,走两级兜底路径(同 timeout 场景)

#### Scenario: 文件名乱码但正文含关键词

- **WHEN** LLM 失败且文件名为乱码(如 `Σ╛¢σ║öσòåA/...docx`,文件名关键词零命中),但正文首段含"投标报价一览表"字样
- **THEN** 正文关键词匹配命中 `pricing`,`file_role='pricing', role_confidence='low'`;不再走文件名兜底

#### Scenario: 身份信息部分字段缺失

- **WHEN** LLM 返回 `identity_info={"company_full_name": "某某有限公司"}` 其他字段未返回
- **THEN** `bidders.identity_info={"company_full_name": "某某有限公司"}`;缺失字段不写入 NULL key(节省存储)

#### Scenario: 低置信度文档标"待确认"

- **WHEN** LLM 返回 `{document_id: 7, role: "technical", confidence: "low"}`
- **THEN** `bid_documents.role_confidence='low'`;前端 API 响应中 `role_confidence` 字段为 `'low'`(前端用于黄色徽章渲染)

#### Scenario: 规则兜底命中"other"

- **WHEN** 文件名与正文均不含任何关键词,LLM 也失败
- **THEN** `file_role='other', role_confidence='low'`

#### Scenario: 文档未 identified 时跳过正文兜底

- **WHEN** LLM 失败,且某文档 `parse_status != 'identified'`(内容提取失败,`document_texts` 为空)
- **THEN** 跳过正文关键词兜底,直接走文件名关键词兜底
---

### Requirement: LLM 报价表结构识别

系统 SHALL 对每个项目的第一个到达"报价识别"阶段的 bidder 的 XLSX 文件触发 **一次 LLM 调用** 识别报价表结构,返回 `sheets_config` 数组(parser-accuracy-fixes P1-5)。识别成功后规则自动 `confirmed=true`,项目内后续 bidder 跳过 LLM 直接用该规则回填。

- **sheets_config 语义**:一个 xlsx 可能含多个候选价格表 sheet(主报价表 + 明细分析表),LLM 返回数组 `[{sheet_name, header_row, column_mapping}, ...]`,只包含**真实数据行 >= 1 行**的候选 sheet
- **非候选 sheet**:LLM SHALL 跳过 "人员进场计划 / 附件说明 / 联系方式 / 目录" 这类非金额表 sheet,不入 sheets_config
- **并发控制**(D3 决策):`price_parsing_rules` 建 `UNIQUE(project_id) WHERE status IN ('identifying','confirmed')`;多 bidder 并发到达本阶段时,仅第一个 INSERT 成功,其余等待
- **等待机制**:`asyncio.Event` 快路径(超时 10s)+ DB poll 慢路径(3s 间隔,最多 5 分钟)
- **LLM 失败**:`price_parsing_rules.status='failed'`;所有等待中的 bidder 进 `price_failed` 态;`bidders.parse_error` 记"报价规则识别失败,可通过 re-parse 重试或手工配置规则"
- **自动批量回填**(D4 决策):规则 `confirmed=true` 触发所有 `identified` 且未 `priced` bidder 的报价回填

#### Scenario: 首个 bidder 识别成功(多 sheet)
- **WHEN** 项目内第一个 bidder 到达报价识别阶段,其 xlsx 含"报价表"(1 行数据)+"监理人员报价单分析表"(5 行数据)+"人员进场计划"(非金额)3 个 sheet
- **THEN** 调用 LLM 识别;成功 → `price_parsing_rules` INSERT 1 条 `status='confirmed', confirmed=true, sheets_config=[{sheet_name:'报价表',...},{sheet_name:'监理人员报价单分析表',...}]`("人员进场计划"不入 sheets_config);SSE 推 `project_price_rule_ready` 事件

#### Scenario: 首个 bidder 识别成功(单 sheet)
- **WHEN** xlsx 只含 1 个价格 sheet
- **THEN** `sheets_config` 数组长度 == 1;行为等同老版单 sheet,向后兼容

#### Scenario: 第二个 bidder 等待首个规则

- **WHEN** 项目内第二个 bidder 在首个 bidder 仍 `identifying` 时到达报价阶段
- **THEN** 第二个 bidder INSERT 冲突 → 进入 `asyncio.Event.wait` 快路径;首个完成 `event.set()` 后,第二个拿到 `sheets_config` 直接回填(**不调 LLM**)

#### Scenario: 等待超时降级 DB poll

- **WHEN** asyncio.Event.wait 10s 超时(假设 event 被重启/异常 GC 丢失)
- **THEN** bidder 进入 DB poll,每 3s 查 `price_parsing_rules.status`;查到 `confirmed` 走回填路径

#### Scenario: 首个 bidder LLM 识别失败

- **WHEN** LLM 返回 error;rule_coordinator UPDATE `status='failed'` + event.set()
- **THEN** 所有等待中 bidder 收到失败信号,各自进 `price_failed` 态;`bidders.parse_error` 含原因;SSE 推 `error` 事件 `{stage: 'price_rule', bidder_id: <首发>, message: ...}`

#### Scenario: 规则识别失败后重试

- **WHEN** 管理员/审查员对项目调 `POST /api/documents/{id}/re-parse`(任一 XLSX 文件)
- **THEN** re-parse 端点 DELETE 该项目 `price_parsing_rules` 中 `status='failed'` 行 → 重跑 pipeline 到报价识别;新的首发 bidder 再次 INSERT identifying → 调 LLM

#### Scenario: sheets_config 每项结构完整
- **WHEN** LLM 成功返回
- **THEN** `sheets_config` 数组每项 MUST 包含 `{sheet_name: str, header_row: int >= 1, column_mapping: {code_col, name_col, unit_col, qty_col, unit_price_col, total_price_col, skip_cols}}`;column_mapping 中每列值为 Excel 列字母(A/B/C...)或 null

#### Scenario: 向后兼容老 rule(无 sheets_config)
- **WHEN** 数据库存在 parser-accuracy-fixes 之前写入的老 rule(`sheets_config` 为空数组,但 `sheet_name`/`header_row`/`column_mapping` 有值)
- **THEN** `fill_price_from_rule` 读时 fallback 构造 `sheets_config=[{sheet_name,header_row,column_mapping}]` 作为单 sheet 运行;无需用户 re-parse
---

### Requirement: 报价 XLSX 选取 fallback 与单 bidder 单类不变量

系统 SHALL 在"报价规则识别"与"报价数据回填"两个阶段为每个 bidder 独立选取参与的 XLSX 文件,采用以下选取规则(fix-unit-price-orphan-fallback):

- **优先规则**:优先选 `file_role='pricing'` 且 `parse_status='identified'` 的 XLSX
- **Fallback 规则**:若该 bidder 无任何 `file_role='pricing'` 的 XLSX,则 fallback 选 `file_role='unit_price'` 且 `parse_status='identified'` 的 XLSX
- **不变量**:同一 bidder 在单次 pipeline 运行中**永不同时混合** `pricing` 与 `unit_price` 两类 XLSX(三分支互斥:pricing 优先 / unit_price 兜底 / 都无则跳过报价阶段)
- **作用面**:此规则对项目内每个 bidder **独立**判定;允许同一项目内不同 bidder 落到不同类(B 用 pricing 数据、A 用 unit_price 数据);**不**做项目级 role 一致化

**动机**:LLM(尤其 DeepSeek 类)对监理/咨询/服务类报价表(首段含"综合单价"字样)有稳定将 `pricing` 误判为 `unit_price` 的倾向。`unit_price` 角色在下游报价管线 0 消费,导致此类 bidder silent failure。Fallback 解决 silent failure,不变量保护下游 `aggregate_bidder_totals` 不受"主表+子表混算"污染(避免 `price_overshoot` / `price_total_match` 等铁证级 detector 误算)。

#### Scenario: 仅 pricing 类 XLSX(主路径)
- **WHEN** bidder 的 XLSX 文件中至少 1 个被 LLM 判 `file_role='pricing'`,可能同时有/没有 `unit_price` 类 XLSX
- **THEN** 仅选 `pricing` 类 XLSX 进入规则识别 + 回填;`unit_price` 类(若存在)被忽略;行为与本 change 之前一致

#### Scenario: 仅 unit_price 类 XLSX(fallback)
- **WHEN** bidder 的 XLSX 文件全部被 LLM 判 `file_role='unit_price'`(无任何 `pricing` 类)且 `parse_status='identified'`
- **THEN** fallback 选 `unit_price` 类 XLSX 进入规则识别(若该 bidder 是项目内首发)+ 回填;bidder 状态走完整 `pricing → priced/price_partial/price_failed` 路径;**不**卡在 `identified`

#### Scenario: pricing + unit_price 都有(优先 pricing 不混合)
- **WHEN** 同一 bidder 同时有 1 个 `file_role='pricing'` 的 XLSX 和 1 个 `file_role='unit_price'` 的 XLSX
- **THEN** **仅** `pricing` 类 XLSX 进入回填;`unit_price` 类 XLSX 被忽略;**不**触发"两份 XLSX 都回填导致 `price_items` 翻倍"风险;`aggregate_bidder_totals` 累加结果只来自 pricing 类

#### Scenario: 既无 pricing 也无 unit_price 类 XLSX(跳过报价阶段)
- **WHEN** bidder 的所有 XLSX 都不是 `pricing` 也不是 `unit_price` 角色,或没有任何 XLSX
- **THEN** pipeline 不进入 `pricing` 阶段;bidder.parse_status 稳定在 `identified`(终态);`price_items` 为空(行为与本 change 之前一致)

#### Scenario: 项目内 bidder 落到不同 role(每家独立判定)
- **WHEN** 项目内 3 家 bidder,B 的 XLSX 被判 `pricing`,A 与 C 的 XLSX 被判 `unit_price`
- **THEN** B 用 `pricing` 类 XLSX 走规则识别(若 B 是首发)与回填;A 与 C 各自 fallback 用 `unit_price` 类 XLSX 走回填;3 家最终都进入 `priced` 终态;A 与 C 的 `price_items` 与 B 同表(因下游 `aggregate_bidder_totals` 不区分 file_role,仅按 bidder_id 聚合)
---

### Requirement: 报价数据回填

系统 SHALL 根据 `price_parsing_rules.sheets_config` 从 bidder 的 XLSX 文件中按**多 sheet 迭代**读取报价项,写入 `price_items` 表。`bidder.parse_status` 根据回填结果置 `priced` / `price_partial` / `price_failed`。

- **触发时机**:
  1. 规则首次 `confirmed=true` 后自动批量触发
  2. 用户 `PUT /api/projects/{pid}/price-rules/{id}` 修改 sheets_config → 清空该项目所有 `price_items` → 重新回填
  3. 单个 bidder `POST /api/documents/{id}/re-parse` 命中该 bidder 的 XLSX → 仅重跑该 bidder
- **XLSX 选取**(fix-unit-price-orphan-fallback):遵循 "报价 XLSX 选取 fallback 与单 bidder 单类不变量" Requirement 定义的规则(`pricing` 优先 / `unit_price` fallback / 单 bidder 不混合)
- **回填逻辑**(多 sheet):
  - 遍历 `rule.sheets_config` 每项 `{sheet_name, header_row, column_mapping}`
  - 对 xlsx 中同名 sheet(严格匹配)从 header_row+1 开始按列字母抽 6 字段;命中不到的 sheet_name 跳过 (记录到 failed_sheets)
  - 跳过纯空行
  - **备注行过滤**(parser-accuracy-fixes P1-6):扫三个 text 字段(item_code/item_name/unit),任一长度 ≥ `PRICE_REMARK_SKIP_MIN_LEN=100`(常量)且其他 5 个字段全空(text 空串或 None、num 全 None)→ 判定备注行,整行 skip(覆盖"长文本落任一 text 列"场景)
  - **item_code 序号列识别**(parser-accuracy-fixes P1-7):若 `item_code` 匹配 `^\d+$`(纯数字整数)且同行 item_name/unit/qty/up/tp 至少一个非空 → 判定为"序号列污染",item_code 置 None(保留其他字段)
  - qty/单价/总价做"千分位/元/万元/万后缀 + 空格/货币符"归一化(parser-accuracy-fixes P0-3),失败则该字段 NULL
- **终态判定**(β 方案):
  - sheets_config 每个 sheet 都抽到 ≥ 1 行 → `priced`
  - 部分 sheet 成功、部分失败(或未找到同名) → `price_partial`,`parse_error` 列出失败 sheet 名
  - 所有 sheet 失败 → `price_failed`

#### Scenario: 多 sheet 全部回填成功
- **WHEN** rule.sheets_config = [{sheet=报价表,...},{sheet=监理人员报价单分析表,...}],xlsx 含两 sheet 均有数据
- **THEN** price_items 写入"报价表"1 行 + "监理人员报价单分析表"5 行,共 6 条;bidder.parse_status=`priced`

#### Scenario: 多 sheet 部分失败
- **WHEN** rule.sheets_config 2 项,其中 xlsx 有第一个 sheet 但无第二个(sheet_name 不匹配)
- **THEN** bidder.parse_status=`price_partial`;parse_error 含"sheet '监理人员报价单分析表' 未找到";第一个 sheet 数据已入库

#### Scenario: 单 sheet 抛异常不影响后续 sheet
- **WHEN** rule.sheets_config 3 项,第二个 sheet 在 `_extract_row` 内部抛 unexpected exception(mock 测试触发)
- **THEN** 该 sheet 计入 `partial_failed_sheets`;第一、第三 sheet 数据正常写 price_items;不抛出到 pipeline 上层;bidder.parse_status=`price_partial`

#### Scenario: rule 非 confirmed 态不走回填
- **WHEN** rule.status='failed' 或 'identifying' 时(边界场景,通常由上游 coordinator 保证不到此),fill_price_from_rule 被调
- **THEN** 返 FillResult()空结果 + warning 日志;**不**构造 fallback sheets 去读 column_mapping;**不**写 price_items

#### Scenario: "￥486000元" 归一为数值
- **WHEN** xlsx 某 cell 值为字符串 "￥486000元" 映到 total_price_col
- **THEN** `price_items.total_price == Decimal("486000.00")`(剥"￥"+"元")

#### Scenario: "12.5 万" 归一为 125000
- **WHEN** cell 值 "12.5 万" 映到 unit_price_col
- **THEN** `price_items.unit_price == Decimal("125000.00")`(剥"万" + ×10000)

#### Scenario: "12.5万元" 归一为 125000
- **WHEN** cell 值 "12.5万元" 映到 total_price_col
- **THEN** `price_items.total_price == Decimal("125000.00")`(剥"万元" + ×10000,"万元"suffix 长度优先)

#### Scenario: "1,234.56 元" 归一为 1234.56
- **WHEN** cell 值 "1,234.56 元"
- **THEN** `Decimal("1234.56")`(保留千分位剥 + 元后缀剥)

#### Scenario: 备注长文本行被过滤(A 列)
- **WHEN** header_row 之后某行 A 列(item_code)为长度 150 字的备注说明,B-G 列全空
- **THEN** 不生成 price_items 记录(过滤;审计意义上忽略)

#### Scenario: 备注长文本行被过滤(name/unit 列)
- **WHEN** header_row 之后某行 B 列(item_name)或 C 列(unit)为长度 150 字的说明文本,其他 text+num 字段全空
- **THEN** 不生成 price_items 记录(H3:扫 text 字段而不只 code_col)

#### Scenario: 有长 item_name 但有数值的正常行不误伤
- **WHEN** item_name 120 字(长),但 unit="项" 非空 或 total_price 非 None
- **THEN** 仍作为正常行写入 price_items(其他字段非空则不判备注)

#### Scenario: item_code 序号列被识别并置空
- **WHEN** 一行 A 列="1",B="建设工程委托监理",F="456000",G="456000"
- **THEN** `price_items` 写入 `{item_code: None, item_name: "建设工程委托监理", unit_price: 456000, total_price: 456000}`;item_code 保留真实业务编码时(如"DT-001")不置空

#### Scenario: 规则修改后重回填
- **WHEN** 项目内已有 3 个 `priced` bidder,用户 PUT 修改 sheets_config
- **THEN** 项目内所有 bidder 的 `price_items` 先 DELETE 再重回填;bidder.parse_status 重经 `pricing → priced`;SSE 推多条 `bidder_price_filled`

#### Scenario: 所有 sheet 回填失败

- **WHEN** bidder 的 2 个 XLSX sheet 按规则都抽不到有效数据
- **THEN** `bidder.parse_status='price_failed'`;`price_items` 为空

#### Scenario: 空行跳过

- **WHEN** header_row 之后某行所有映射列为空
- **THEN** 不生成 price_items 记录

#### Scenario: 无报价表 bidder 停在 identified

- **WHEN** bidder 的所有 bid_documents 中既无 `file_role='pricing'` 也无 `file_role='unit_price'` 的 XLSX 文件
- **THEN** pipeline 不进入 `pricing` 阶段;bidder.parse_status 稳定在 `identified`(终态);`price_items` 为空;project progress 不把该 bidder 计入 `pricing_total`
---

### Requirement: 解析流水线编排

系统 SHALL 为每个 `extracted` bidder 启动一个 `asyncio.create_task(run_pipeline(bidder_id))` 协程,按阶段顺序推进:`extract_content → llm_classify → (wait_project_rule) → fill_price`。各阶段间状态持久化到 DB,重启后可从当前状态恢复。

- **阶段衔接**:每阶段完成 UPDATE `bidder.parse_status` + publish SSE 事件,下一阶段开始前 re-SELECT 当前状态
- **失败隔离**:任一阶段异常 → bidder 标该阶段失败态(identify_failed / price_failed)+ parse_error;不影响同项目其他 bidder
- **re-parse 重跑**:`POST /api/documents/{id}/re-parse` 端点重置该文档所属 bidder 的相关阶段,重新触发 pipeline(pipeline 内部根据当前 parse_status 决定从哪段继续)
- **报价阶段进入条件**(fix-unit-price-orphan-fallback):bidder 至少有一个 `file_role='pricing'` 或 `file_role='unit_price'`(fallback)的 XLSX(详见 "报价 XLSX 选取 fallback 与单 bidder 单类不变量" Requirement)

#### Scenario: pipeline 完整路径

- **WHEN** bidder 从 `extracted` 进入 pipeline(包含 XLSX 报价表)
- **THEN** 状态依次变:`extracted → identifying → identified → pricing → priced`;每次变更 publish 一次 SSE `bidder_status_changed`

#### Scenario: pipeline 无报价表路径

- **WHEN** bidder 所有 XLSX 文档既非 `pricing` 也非 `unit_price` 角色(或根本无 XLSX)
- **THEN** 状态:`extracted → identifying → identified`(不进 pricing 态)

#### Scenario: pipeline 内容提取失败

- **WHEN** extract_content 阶段所有文档都损坏无法解析
- **THEN** bidder.parse_status = `identify_failed`;parse_error = "内容提取全部失败";pipeline 终止,不继续 LLM

#### Scenario: pipeline LLM 识别失败(非兜底命中)

- **WHEN** LLM 失败 + 关键词规则也全部未命中 → 所有文档 role='other' 但这本身仍是合法分类
- **THEN** bidder.parse_status = `identified`(角色全 other 不视为失败);parse_error = NULL;`bidders.identity_info = NULL`(身份信息走空兜底)

#### Scenario: re-parse 重跑失败文档

- **WHEN** 某文档 `parse_status='identify_failed'`,调 `POST /api/documents/{id}/re-parse`
- **THEN** 响应 202;该文档 parse_status 重置为 pending;bidder 若已 identified/priced 终态则重新进入 identifying 阶段;返回前已存在的 price_items 保持不变直到新 pricing 阶段完成

---

### Requirement: 修改文档角色

系统 SHALL 提供 `PATCH /api/documents/{id}/role` 端点,body 为 `{role: "<9 种枚举之一>"}`。修改后立即更新 `bid_documents.file_role` 与 `role_confidence='user'`,**不触发**重新解析(与 US-4.3 AC-5 对齐),**不自动改变**项目 status。

- 若项目 `status='completed'`,响应 200 附加字段 `{warn: "文档角色已修改,当前报告基于修改前分类,建议重新检测"}`(前端据此显示 banner)
- 权限:reviewer 仅可改自己项目的文档角色;admin 可改任意

#### Scenario: reviewer 修改自己项目的文档角色

- **WHEN** reviewer 对自己项目文档 PATCH `{role: "technical"}`
- **THEN** 响应 200;`file_role='technical', role_confidence='user'`

#### Scenario: 非法 role 值拒绝

- **WHEN** PATCH `{role: "invalid"}`
- **THEN** 响应 422

#### Scenario: 跨权限 PATCH 返 404

- **WHEN** reviewer A 对 B 项目的文档 PATCH
- **THEN** 响应 404

#### Scenario: 已 completed 项目修改附带 warn

- **WHEN** 项目 `status='completed'`,PATCH role
- **THEN** 响应 200 body 含 `warn` 字段;`file_role` 正常更新

#### Scenario: 修改不触发 re-parse

- **WHEN** PATCH role 成功
- **THEN** 该文档 parse_status 保持不变;`document_texts / document_metadata` 等提取结果保留;`price_items` 不受影响

---

### Requirement: 报价列映射修正与批量重回填

系统 SHALL 补齐 C4 `PUT /api/projects/{pid}/price-rules/{id}` 端点的完整语义:修改 `sheets_config`(parser-accuracy-fixes)→ 先 DELETE 项目内所有 `price_items` → 重新触发该项目所有 bidder 的报价回填阶段 → 对应 bidder 状态依次 `priced → pricing → priced/price_partial/price_failed`。`created_by_llm=true` 变为 `false`(标记人工修正)。

- **向后兼容**:接受两种 payload 形态:
  - 新 payload:`{sheets_config: [...]}`
  - 老 payload:`{column_mapping: {...}, sheet_name?, header_row?}` → 后端自动包装为 `sheets_config=[{sheet_name, header_row, column_mapping}]` 单 sheet
  - 老新混传 → 返 422
- **并发保护**:项目级 asyncio.Lock;同时到来的第二个 PUT 返 409 "修正正在进行中,请稍后重试"
- **首次 PUT**(规则仍为 LLM 识别态):仅更新字段,不重回填(回填在首次 confirmed 时已完成;修正场景才重回填)
- **审计字段**:`updated_at` 自动更新

#### Scenario: 修正已应用规则触发重回填(新 payload)
- **WHEN** 项目内 3 个 `priced` bidder,规则已 `confirmed=true, created_by_llm=true`,PUT 修改 `sheets_config[0].column_mapping.unit_price_col` 从 "E" 到 "F"
- **THEN** 响应 200;`price_items` 先 DELETE → 重新回填;bidder.parse_status 重新经 `pricing → priced`;SSE 推 `bidder_price_filled` × 3;`price_parsing_rules.created_by_llm=false`

#### Scenario: 老 payload 向后兼容
- **WHEN** 旧版 admin UI 仍发 `{column_mapping: {...}}`(无 sheets_config)
- **THEN** 后端包装为单 sheet `sheets_config=[{...}]`,保存成功;L2 `test_backward_compat_put_column_mapping` 覆盖

#### Scenario: 非法 sheets_config(缺必要键)
- **WHEN** PUT body 的 `sheets_config[0].column_mapping` 缺 `code_col`
- **THEN** 响应 422

#### Scenario: 老新 payload 混传返 422(M4)
- **WHEN** PUT body 同时含 `sheets_config: [...]` 和 `column_mapping: {...}` 两种字段
- **THEN** 响应 422;错误信息指明"sheets_config 与 column_mapping 只能二选一"

#### Scenario: 并发修正返 409

- **WHEN** 第一次 PUT 正在重回填(项目级 Lock 持有中),第二次 PUT 到达
- **THEN** 第二次响应 409

#### Scenario: 跨权限 PUT 返 404

- **WHEN** reviewer A 对 B 项目的 price-rule PUT
- **THEN** 响应 404
---

### Requirement: 重新解析失败文档

系统 SHALL 提供 `POST /api/documents/{id}/re-parse` 端点,对 `parse_status IN ('identify_failed', 'skipped', ...)` 的文档重置 pipeline。已正常 identified/priced 的文档也可 re-parse(覆盖式重跑)。

- **语义**:
  - DELETE 该文档的 `document_texts / document_metadata / document_images` 记录
  - 若该文档 `file_role='pricing'`:额外 DELETE 该 bidder 的所有 `price_items` 并把 bidder.parse_status 置回 `identified`(以便重跑 pricing 阶段)
  - `bid_documents.parse_status = 'identifying'`;trigger pipeline 从 extract_content 阶段对该文档重跑
- 响应 202 (async,前端轮询)
- 权限:reviewer 仅可对自己项目的文档 re-parse

#### Scenario: re-parse identify_failed 文档

- **WHEN** 文档 `parse_status='identify_failed'`,POST re-parse
- **THEN** 响应 202;`document_texts/metadata/images` 中该文档记录被删;bid_documents.parse_status 置 `identifying`;pipeline 重跑

#### Scenario: re-parse skipped 文档

- **WHEN** 文档 `file_type='.pdf'` 且 `parse_status='skipped'`,POST re-parse
- **THEN** 响应 202;但重跑后仍 skipped(格式仍不支持),`parse_error` 不变

#### Scenario: re-parse pricing 文档触发 bidder 重跑报价

- **WHEN** 文档 `file_role='pricing'`,POST re-parse
- **THEN** 响应 202;该 bidder 的 price_items 被 DELETE;bidder.parse_status 退到 `identified`;pipeline 跑完后 bidder 回到 `priced/price_partial/price_failed`

#### Scenario: 跨权限 re-parse 返 404

- **WHEN** reviewer A 对 B 项目的文档 re-parse
- **THEN** 响应 404

---

### Requirement: 查询投标人报价项

系统 SHALL 提供 `GET /api/projects/{pid}/bidders/{bid}/price-items` 端点返回该投标人的所有 `price_items` 记录,按 `(sheet_name, row_index)` 升序。前端项目详情页 Pricing 面板消费此端点。

- 响应字段:`id / sheet_name / row_index / item_code / item_name / unit / quantity / unit_price / total_price`
- 权限:reviewer 仅可查自己项目
- bidder 处于 `pricing` 或未到报价阶段 → 响应 200,body 为空数组

#### Scenario: 已 priced bidder 查询

- **WHEN** bidder.parse_status='priced',GET price-items
- **THEN** 响应 200,body 为数组 ≥ 1 条记录,按 `(sheet_name, row_index)` 排序

#### Scenario: price_partial bidder 查询

- **WHEN** bidder.parse_status='price_partial',GET price-items
- **THEN** 响应 200,返回成功 sheet 的记录

#### Scenario: 尚未 priced 的 bidder 查询

- **WHEN** bidder.parse_status IN ('extracted', 'identifying', 'identified', 'pricing'),GET
- **THEN** 响应 200,body = `[]`

#### Scenario: 跨权限查询返 404

- **WHEN** reviewer A 查 B 项目 bidder 的 price-items
- **THEN** 响应 404

---

### Requirement: 解析进度 SSE 事件流

系统 SHALL 提供 `GET /api/projects/{pid}/parse-progress` SSE 端点,实时推送项目内解析进度事件。首帧为 DB 当前态 snapshot;之后推送以下事件:

| event | data payload |
|---|---|
| `snapshot` | `{bidders: [{id, parse_status, file_count}], progress: {extracted, identified, priced, failed}}` (仅首帧) |
| `bidder_status_changed` | `{bidder_id, old_status, new_status}` |
| `document_role_classified` | `{document_id, bidder_id, role, confidence}` |
| `project_price_rule_ready` | `{rule_id, confirmed, sheet_name, header_row}` |
| `bidder_price_filled` | `{bidder_id, items_count, partial_failed_sheets?: string[]}` |
| `error` | `{bidder_id?, stage, message}` |
| `heartbeat` | `{ts}` (每 15s) |

- 权限:reviewer 仅可订阅自己项目;admin 任意
- 客户端断开(CancelledError)→ 从 broker 摘除订阅者,正常退出
- 响应头:`Cache-Control: no-cache`, `X-Accel-Buffering: no`(防 nginx 缓冲)

#### Scenario: 订阅首帧返回 snapshot

- **WHEN** reviewer 连接 SSE 端点
- **THEN** 首帧 `event: snapshot` 含当前所有 bidder 状态;后续保持长连接

#### Scenario: bidder 状态变更推事件

- **WHEN** 某 bidder 状态从 `extracted` 变为 `identifying`
- **THEN** 所有订阅该项目的连接收到 `event: bidder_status_changed` `{bidder_id, old_status: 'extracted', new_status: 'identifying'}`

#### Scenario: heartbeat 保活

- **WHEN** 连接无业务事件超过 15s
- **THEN** 服务端推一条 `event: heartbeat`

#### Scenario: 跨权限订阅拒绝

- **WHEN** reviewer A 订阅 B 项目 SSE
- **THEN** 响应 404 且不建立长连接

#### Scenario: 客户端断开清理订阅

- **WHEN** 客户端关闭连接
- **THEN** 服务端日志记录"订阅者摘除";broker 内部 queue 列表不再含该订阅者(L2 可通过查 broker 内部状态验证,或仅查日志)

---

### Requirement: LLM Prompt 维护

系统 SHALL 将两个 LLM 调用的 prompt 存放在 `app/services/parser/llm/prompts.py`,作为 Python 模块级常量。prompt 以 Python 字符串 + f-string 变量插值形式管理,不引入 Jinja/YAML。

- `ROLE_CLASSIFY_SYSTEM_PROMPT`:角色分类任务的 system message
- `ROLE_CLASSIFY_USER_TEMPLATE`:user message 模板,参数 `{files}` 列表
- `PRICE_RULE_SYSTEM_PROMPT`:报价表识别 system message
- `PRICE_RULE_USER_TEMPLATE`:user message 模板,参数 `{sheet_name, header_preview}`
- Prompt 本身**不进入 spec**(实施期可调);spec 仅约束"文件存在 + 含 4 个常量 + 常量为非空字符串"

#### Scenario: Prompt 模块导入

- **WHEN** `from app.services.parser.llm.prompts import ROLE_CLASSIFY_SYSTEM_PROMPT`
- **THEN** 导入成功;常量为非空字符串

#### Scenario: Prompt 常量完整性

- **WHEN** 检查 prompts.py
- **THEN** 包含 4 个模块级常量:`ROLE_CLASSIFY_SYSTEM_PROMPT / ROLE_CLASSIFY_USER_TEMPLATE / PRICE_RULE_SYSTEM_PROMPT / PRICE_RULE_USER_TEMPLATE`

---

### Requirement: 角色关键词兜底规则

系统 SHALL 在 `app/services/parser/llm/role_keywords.py` 维护 `ROLE_KEYWORDS: dict[str, list[str]]` 常量,用于 LLM 失败时的"正文关键词兜底 + 文件名关键词兜底"两级匹配。

- 8 个角色各配一组关键词(pricing / technical / construction / unit_price / bid_letter / qualification / company_intro / authorization);第 9 个角色 `other` 为默认兜底,无需关键词
- 提供两个入口函数:
  - `classify_by_keywords(file_name: str) -> str | None`:对文件名做子串包含匹配(不区分大小写),按字典声明顺序遍历,首次命中即返回,全未命中返回 `None`
  - `classify_by_keywords_on_text(text: str) -> str | None`:对正文首段文本做子串包含匹配(不区分大小写),规则同上
- **[honest-detection-results]** ROLE_KEYWORDS 实际存在 3 处副本,本 change 采取**降级同步约束**(不强求值集合完全相等):
  1. `app/services/parser/llm/role_keywords.py` — runtime 两级兜底匹配入口(**SSOT,关键词加减从这里开始**)
  2. `app/services/parser/llm/prompts.py` — LLM 系统 prompt 中"角色→主要关键词"的说明性描述(**不进机械化测试**,改关键词时需 docstring 标注并人工 review 同步)
  3. `app/services/admin/rules_defaults.py` — admin UI 管理员可配置关键词的默认值(**允许用短子串以扩大覆盖范围**,与 role_keywords.py 的复合词策略不同)
- 同步约束:
  - (a) 三处对 9 种 role 的 key 集合完全一致
  - (b) 每处每个 role 的 keywords list 非空
  - (c) **不要求** value 集合相等(rules_defaults.py 短子串与 role_keywords.py 复合词故意不等是 admin 默认覆盖语义)
  - (d) **弱一致性约束**:rules_defaults.py 每个关键词 MUST 是 role_keywords.py 对应 role 里某个 keyword 的子串(防止 defaults 加了 SSOT 没有的词漂移)
- **[honest-detection-results]** 行业术语补充(10 个新词加到 role_keywords.py,rules_defaults.py 可酌情加对应短子串):
  - `pricing`: 增加 `价格标`、`开标一览表`
  - `qualification`: 增加 `资信标`、`资信`、`业绩`、`类似业绩`
  - `company_intro`: 增加 `企业简介`
  - `construction`: 增加 `施工进度`、`进度计划`
- **[honest-detection-results]** `rules_defaults.py:71` 的 `authorization` keywords 当前为 `["授权", "委托"]`,补一项 `"授权委托书"`(之前提案误称"整条缺失",实为少一词)
- 本期不支持管理员动态维护(D2 决策);C17 升级为 DB + admin UI(admin_rules capability);三副本合并 SSOT 留 follow-up

#### Scenario: 角色关键词常量存在

- **WHEN** 导入 `ROLE_KEYWORDS`
- **THEN** 字典含 8 个角色键,每个值为非空字符串列表

#### Scenario: 文件名命中关键词返回对应角色

- **WHEN** 文件名 "投标报价.xlsx",调用 `classify_by_keywords(name)`
- **THEN** 返回 `"pricing"`(命中关键词 "报价")

#### Scenario: 文件名未命中返回 None

- **WHEN** 文件名 "XYZ.docx" 不含任何关键词
- **THEN** `classify_by_keywords` 返回 `None`(调用方据此决定走下一层兜底或兜底到 "other")

#### Scenario: 正文命中关键词返回对应角色

- **WHEN** 正文首段"本公司针对本次招标项目提交投标报价一览表如下",调用 `classify_by_keywords_on_text(text)`
- **THEN** 返回 `"pricing"`(命中关键词 "报价")

#### Scenario: 正文未命中返回 None

- **WHEN** 正文首段不含任何角色关键词
- **THEN** `classify_by_keywords_on_text` 返回 `None`

#### Scenario: 新增"价格标"术语命中 pricing

- **WHEN** 文件名 "XX 价格标.docx",调用 `classify_by_keywords(name)`
- **THEN** 返回 `"pricing"`

#### Scenario: 新增"资信标"术语命中 qualification

- **WHEN** 文件名 "XX 资信标.docx",调用 `classify_by_keywords(name)`
- **THEN** 返回 `"qualification"`

#### Scenario: 新增"类似业绩"术语命中 qualification

- **WHEN** 文件名 "类似业绩证明.docx" 或正文"公司完成过如下类似业绩",调用对应 classify 函数
- **THEN** 返回 `"qualification"`

#### Scenario: 新增"开标一览表"术语命中 pricing

- **WHEN** 文件名含 "开标一览表"
- **THEN** `classify_by_keywords` 返回 `"pricing"`

#### Scenario: 新增"企业简介"术语命中 company_intro

- **WHEN** 文件名 "企业简介.docx",调用 `classify_by_keywords(name)`
- **THEN** 返回 `"company_intro"`(原有表只有"企业介绍/公司简介/公司概况",不含"企业简介")

#### Scenario: 新增"施工进度"/"进度计划"术语命中 construction

- **WHEN** 文件名 "施工进度表.docx" 或 "进度计划.xlsx"
- **THEN** `classify_by_keywords` 分别返回 `"construction"`

#### Scenario: 两处可机械校验副本保持 key 同步

- **WHEN** L1 测试 `test_role_keywords_2way_sync` 比对 `role_keywords.py::ROLE_KEYWORDS` 和 `rules_defaults.py::ROLE_KEYWORDS`(prompts.py 不进测试,因其为自然语言描述无可靠提取规则)
- **THEN** 两处 key 集合完全相同;两处每个 role 的 keywords list 非空;**不**要求 value 集合相等(rules_defaults.py 可用短子串);defaults 每个关键词 MUST 是 SSOT 对应 role 里某个 keyword 的子串

#### Scenario: rules_defaults.py 的 authorization 含授权委托书

- **WHEN** 读取 `admin/rules_defaults.py::ROLE_KEYWORDS["authorization"]`
- **THEN** 列表含 `授权委托书`、`授权`、`委托` 三项(change 前只有后两项)

#### Scenario: rules_defaults.py 允许短子串策略

- **WHEN** `role_keywords.py::ROLE_KEYWORDS["pricing"]` 含复合词 `投标报价`,而 `rules_defaults.py::ROLE_KEYWORDS["pricing"]` 含短子串 `报价`
- **THEN** 两者**都合法**,测试不 fail;本 change 不改 admin 默认的短子串覆盖策略

---

### Requirement: DocumentSheet 数据契约

后端 MUST 提供 `document_sheets` 表承载 xlsx cell 级数据,schema:

- 表名 `document_sheets`(复数,对齐既有 `document_texts`/`document_images`)
- `id` SERIAL PRIMARY KEY
- `bid_document_id` INT NOT NULL REFERENCES `bid_documents(id)`,INDEX;**不加 CASCADE**(对齐既有 `document_texts` 等表,BidDocument 删除由应用层级联)
- `sheet_index` INT NOT NULL — workbook 中 0-based sheet 顺序
- `sheet_name` VARCHAR(255) NOT NULL — openpyxl `ws.title` 原值
- `hidden` BOOLEAN NOT NULL DEFAULT false — sheet_state != 'visible' 时 true
- `rows_json` JSONB NOT NULL(PG)/ JSON(SQLite)— 二维 list,`rows[r][c]` 为 cell 原值(str/int/float/bool/None);上限 `STRUCTURE_SIM_MAX_ROWS_PER_SHEET` 行;SQLAlchemy 列类型用 `sa.JSON().with_variant(JSONB, "postgresql")`
- `merged_cells_json` JSONB/JSON NOT NULL DEFAULT `[]` — 合并单元格 ranges 字符串列表,每项形如 `"A1:B2"`(openpyxl `ws.merged_cells.ranges.str()`)
- `created_at` TIMESTAMPTZ NOT NULL DEFAULT now()
- UNIQUE CONSTRAINT `(bid_document_id, sheet_index)` — 同文档 sheet_index 唯一

字段名与 Python model 字段名一致(蛇形命名)。alembic 迁移版本号 `0006_add_document_sheets`,单向 head(回滚 drop 表)。

#### Scenario: 建模与 unique 约束

- **WHEN** 尝试对同一 `bid_document_id` 插入两条相同 `sheet_index` 的 DocumentSheet
- **THEN** 数据库抛 UniqueConstraint 违反异常;应用层不尝试 upsert(由回填脚本的幂等逻辑在应用层 skip)

#### Scenario: BidDocument 外键约束

- **WHEN** 尝试删除一条仍被 `document_sheets` 引用的 `BidDocument`
- **THEN** 数据库抛外键约束异常(对齐既有 `document_texts`/`document_images`,不自动级联;应用层需先清 children)

#### Scenario: JSONB 存取基本形态

- **WHEN** 插入 `rows_json=[["姓名","电话"],["张三","123"]]`
- **THEN** 后续读取得到完全相同结构的 Python list(含嵌套 list),类型保持 str/None(openpyxl 读 xlsx 后的 cell 值已成 Python 原生类型)

---

### Requirement: DocumentSheet 回填脚本

后端 MUST 提供一次性回填脚本 `backend/scripts/backfill_document_sheets.py`,供运维手工执行,满足:

1. **扫描目标**:`BidDocument.file_type == ".xlsx" AND parse_status == "identified" AND NOT EXISTS(DocumentSheet for this bid_document_id)`(幂等:已回填的 doc 跳过)
2. **执行**:对每个目标 doc,`extract_xlsx(doc.file_path)` 后写 DocumentSheet 行;写入失败 rollback + 日志输出,继续下一个(错误隔离)
3. **日志**:每 doc 一行 `OK doc={id} sheets={n}` 或 `FAIL doc={id}: {err}`;结束输出 `total={n} success={s} failed={f}`
4. **入口**:`uv run python backend/scripts/backfill_document_sheets.py` 或 `python -m scripts.backfill_document_sheets`;退出码 0(无失败)/ 1(有失败)
5. **--dry-run 选项**:仅扫描目标 doc 列表打印 file_name + 计数,不写入 DB
6. **不纳入 alembic migration**:migration 只动 schema;数据层回填由运维单独触发

#### Scenario: 幂等重跑

- **WHEN** 首次回填完成后立即重跑脚本
- **THEN** 输出 `total=0 success=0 failed=0`;已存在 DocumentSheet 的 doc 全部被 `NOT EXISTS` 过滤,不重复插入

#### Scenario: 单 doc 失败不中断

- **WHEN** 100 个目标 doc 中 1 个文件已损坏(openpyxl 抛异常)
- **THEN** 脚本继续处理剩余 99 个;最终 `total=100 success=99 failed=1`;已 rollback 的 doc 的 DocumentSheet 不写入

#### Scenario: 回填脚本不修改 BidDocument 状态

- **WHEN** 脚本处理某 doc
- **THEN** `BidDocument.parse_status` 保持原值(仍为 `identified`);脚本只写 DocumentSheet 不改其他表

#### Scenario: --dry-run 只扫不写

- **WHEN** 跑 `--dry-run` 模式
- **THEN** 列目标 doc 数 + 每个 file_name;`document_sheets` 表无新增

---

### Requirement: xlsx_parser 合并单元格暴露

`app/services/parser/content/xlsx_parser.py` 的 `SheetData` dataclass MUST 追加 `merged_cells_ranges: list[str]` 字段,由 `extract_xlsx` 填充为 openpyxl `ws.merged_cells.ranges` 的字符串化结果列表。

- 读取模式必须为 `read_only=False`(openpyxl read_only 模式读不到 merged_cells)
- 该字段默认空列表(无合并单元格时);非 None
- 单 sheet extract 异常时 `merged_cells_ranges` 默认 `[]`,不影响其他字段

#### Scenario: 无合并单元格

- **WHEN** 一份 xlsx 无任何合并单元格
- **THEN** `SheetData.merged_cells_ranges == []`

#### Scenario: 有合并单元格

- **WHEN** 一份 xlsx 含合并单元格 A1:B2 和 C3:D5
- **THEN** `SheetData.merged_cells_ranges` 含 `"A1:B2"` 和 `"C3:D5"`(顺序不敏感)

---

### Requirement: DocumentMetadata.template 数据契约

`document_metadata` 表 MUST 追加 `template VARCHAR(255) NULL` 列,alembic 迁移文件名 `0007_add_document_metadata_template.py`,revision 字符串 `0007_add_doc_meta_template`(受 alembic_version.version_num VARCHAR(32) 长度限制,缩写但与文件名语义一致),单向 head(回滚 drop 列)。

- 字段名 `template`
- 类型 `VARCHAR(255)`,可空
- 无默认值(缺失写 NULL)
- 不加索引(machine 检测在内存做精确 AND 匹配,不走 SQL 过滤)
- SQLAlchemy model 字段:`template: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)`
- 新文档自然经 `parser/content/__init__.py` 写入;历史文档需 `backfill_document_metadata_template.py` 回填

#### Scenario: alembic 升级加列

- **WHEN** `alembic upgrade head` 从 0006 到 0007
- **THEN** `document_metadata` 表存在 `template VARCHAR(255) NULL` 列;既有数据行 `template = NULL`

#### Scenario: alembic 降级删列

- **WHEN** `alembic downgrade -1` 从 0007 到 0006
- **THEN** `document_metadata.template` 列被 drop;既有 template 数据丢失(可接受)

#### Scenario: 新文档自动写入 template

- **WHEN** 上传一份 docProps/app.xml 含 Template=Normal.dotm 的 DOCX,触发 C5 parser/content
- **THEN** `document_metadata.template == 'Normal.dotm'`(无需运维介入)

#### Scenario: 老文档 template 默认 NULL

- **WHEN** alembic 0007 升级后,既有 DocumentMetadata 行未被回填
- **THEN** `template IS NULL`;不影响现有 C7/C8/C9 Agent 运行

### Requirement: DocumentMetadata template 回填脚本

后端 MUST 提供一次性回填脚本 `backend/scripts/backfill_document_metadata_template.py`,供运维手工执行,满足:

1. **扫描目标**:`BidDocument.parse_status='identified' AND file_type IN ('.docx', '.xlsx') AND DocumentMetadata.template IS NULL`(幂等)
2. **执行**:对每个目标 doc,从 `doc.file_path` 打开 zip 读 `docProps/app.xml` 提取 `<Template>` 节点文本 → UPDATE `document_metadata.template`(单 doc 独立 session + commit)
3. **异常隔离**:单 doc 失败 rollback + 打日志 `FAIL doc={id}: {err}`,继续下一个
4. **日志格式**:每 doc 一行 `OK doc={id} template={value!r}` 或 `FAIL doc={id}: {err}`;结束输出 `total={n} success={s} failed={f}`
5. **`--dry-run` 支持**:仅打印待回填 doc 数量 + 样例前 5 条,不写入
6. **入口**:`uv run python backend/scripts/backfill_document_metadata_template.py` 或 `python -m scripts.backfill_document_metadata_template`
7. **不纳入 alembic migration**:migration 只动 schema;回填由运维单独触发

#### Scenario: 幂等重跑

- **WHEN** 首次回填完成后立即重跑脚本(所有目标 doc 已 `template` 非 NULL)
- **THEN** 输出 `total=0 success=0 failed=0`;SQL 过滤 `template IS NULL` 跳过全部已回填 doc

#### Scenario: 单 doc 失败不中断

- **WHEN** 100 个目标 doc 中 1 个文件已损坏(zipfile 抛异常)
- **THEN** 脚本继续处理剩余 99 个;最终 `total=100 success=99 failed=1`;已 rollback 的 doc 的 `template` 保持 NULL

#### Scenario: dry-run 不写入

- **WHEN** 运行 `python scripts/backfill_document_metadata_template.py --dry-run`
- **THEN** 打印待回填数量 + 样例;`document_metadata.template` 表内容不变

#### Scenario: template 字段缺失的文档也回填

- **WHEN** 目标 doc 的 `docProps/app.xml` 无 `<Template>` 节点
- **THEN** 脚本 UPDATE `template = NULL`(保持原值 NULL),仍计入 success;不阻塞

### Requirement: identity_validator 规则模块

`backend/app/services/parser/identity_validator.py` MUST 提供:

- `extract_bidder_name_by_rule(session, bidder_id) -> str | None`:从 `DocumentText` 扫 `bid_documents.file_type='.docx'` 且 `document_texts.location='body'` 的段落,用正则 `投标人\s*[（(]?\s*盖章\s*[）)]?\s*[:：]\s*(.+?)(?:\n|\s{2,}|$)` non-greedy 匹配;按 paragraph_index 升序遍历,首次命中返回公司名;全未命中返 None
- `apply_identity_validation(session, bidder_id)`:在 classify_bidder 完成后调用;对比规则结果与 LLM 结果(identity_info.company_full_name),按"一致保留 / 不一致规则覆盖 + 置 low / 未命中保留 LLM"策略更新 `bidders.identity_info` 和 `bid_documents.role_confidence`

- **正则策略**:non-greedy `(.+?)`,尾终止为换行/段落结束/≥2 空格;支持中英括号(全半角)"(盖章)"/"（盖章）"/"盖章"(括号可缺);支持冒号中英(`:`/`：`)
- **LLM 未返 identity_info**:rule 结果作为唯一来源,直接写入 company_full_name,role_confidence 维持 LLM 原判(因为是补齐不是纠正)
- **覆盖时审计**:`identity_info._llm_original` 记录 LLM 原返值,永不删除(除非人工编辑)

#### Scenario: 标准"投标人(盖章):xxx" 命中
- **WHEN** docx body 段含 "投标人(盖章)：  江苏省华厦工程项目管理有限公司"
- **THEN** `extract_bidder_name_by_rule` 返回 "江苏省华厦工程项目管理有限公司"

#### Scenario: 半角括号命中
- **WHEN** docx body 段含 "投标人(盖章): 某公司"
- **THEN** 返回 "某公司"

#### Scenario: 无括号命中
- **WHEN** docx body 段含 "投标人盖章: XYZ 有限公司 (盖章日期:xxx)" (括号内是日期不是公司名)
- **THEN** non-greedy 匹配到 "XYZ 有限公司"(空格 ≥2 前终止)

#### Scenario: 未命中返 None
- **WHEN** bidder 所有 docx body 都无"投标人盖章"字样
- **THEN** `extract_bidder_name_by_rule` 返 None

#### Scenario: 只扫 body,不扫 header/footer/textbox
- **WHEN** 盖章字样只在 textbox(`location='textbox'`)里
- **THEN** 规则不命中(scope 限 `location='body'` 降误判风险)

#### Scenario: 覆盖场景审计字段
- **WHEN** LLM 返 "锂源(招标方)",规则返 "攀钢"
- **THEN** 写入后 `identity_info={company_full_name: "攀钢", _llm_original: "锂源(招标方)"}`

#### Scenario: 补齐场景不降级 role_confidence(review H1 修)
- **WHEN** LLM 返 `identity_info={project_manager: "张三"}` 无 company_full_name;规则命中"XX 公司"
- **THEN** `identity_info.company_full_name="XX 公司"`(补齐);**无** `_llm_original`(无原值可审计);bidder 所有 docx/xlsx 的 `role_confidence` **保持 LLM 原判**(因为是补齐不是纠正,与 mismatch 分支区分)

#### Scenario: 子串匹配加最短长度 guard(review M4 修)
- **WHEN** LLM 返 "华建"(3 字),规则返 "浙江华建工程监理"
- **THEN** 短串 <4 字,不判 match,走 mismatch 分支规则覆盖(防"华建" vs "江苏华建建设" 这类同子串不同公司假阳)

## MODIFIED Requirements

### Requirement: per-bidder 流水线完成后触发项目状态聚合

per-bidder 解析流水线（`run_pipeline`）在 bidder 到达终态后，SHALL 调用项目状态聚合逻辑，检查是否所有同项目 bidder 均已终态，若是则触发 `project.status` 流转。

#### Scenario: bidder 到达 identified 终态
- **WHEN** `run_pipeline()` 将 bidder 状态设为 `identified`（角色分类完成，无报价 XLSX）
- **THEN** 调用项目状态聚合函数，检查同项目其他 bidder 状态

#### Scenario: bidder 到达 priced 终态
- **WHEN** `run_pipeline()` 将 bidder 状态设为 `priced`（报价提取完成）
- **THEN** 调用项目状态聚合函数

#### Scenario: bidder 解析失败
- **WHEN** `run_pipeline()` 将 bidder 状态设为 `identify_failed` 或 `price_failed`
- **THEN** 同样调用项目状态聚合函数（失败也是终态）


### Requirement: role_classifier 诊断日志契约

`backend/app/services/parser/llm/role_classifier.py::_classify_bidder_inner` SHALL 在 LLM 调用前后输出足够诊断 N3(LLM 大文档精度退化)根因归类的结构化日志,覆盖"LLM 成功 + 自返 low" 与 "JSON 解析失败"两条现有 `kind` 日志未覆盖的决策路径。具体内容:

- **input shape**:`logger.info` SHALL 在 `llm.complete()` 调用前记录 `files=<int>`、`snippet_empty=<int>`(文档首段正文为空的份数)、`total_prompt_chars=<int>`(完整 user message 字符数)、`file_name_has_mojibake=<bool>`(文件名是否疑似 cp850→GBK 乱码,启发式判定)
- **output confidence mix**:`logger.info` SHALL 在 LLM 返回解析成功后、roles 写入 DB 前记录 `llm_confidence_high=<int>`、`llm_confidence_low=<int>`、`llm_confidence_missing=<int>`(LLM 漏返而走关键词兜底的文档数);三者之和 MUST 等于该 bidder 该批次文档数
- **raw text head**:既有 "role_classifier LLM returned invalid JSON" `logger.warning` SHALL 追加 `raw_text_head=<前 200 字符>`(按字符数,不是字节),用于诊断 response 截断模式

上述三处日志 MUST 零控制流/返回值变化,失败仅影响日志输出不影响主流水线。LLM 调用失败路径(既有 `kind=X msg=Y` warning)保持不变;日志 level 用 `logger.info`(prod 默认 warning 级不输出,诊断时主动调低)。

#### Scenario: LLM 成功路径记 input shape + output mix
- **WHEN** role_classifier 处理一个 bidder,其 DOCX/XLSX 文档集传入 LLM 并返回有效 JSON(含 high / low / 漏返文档的混合)
- **THEN** caplog 捕获 1 条 input shape info(files/snippet_empty/total_prompt_chars/file_name_has_mojibake 字段齐全)+ 1 条 output mix info(high+low+missing 之和等于输入文档数);**不**触发任何 kind warning 或 invalid JSON warning

#### Scenario: LLM 失败路径仅记 kind,不记 output mix
- **WHEN** role_classifier 处理一个 bidder,LLM 返回 `result.error != None`(kind=timeout / rate_limit / ...)
- **THEN** caplog 捕获既有 `"role_classifier LLM error kind=%s msg=%s; fallback to keywords"` warning(未回归)+ input shape info(调用前已打);**不**捕获 output confidence mix info(因为 LLM 未成功返回,不存在 mix 状态)

#### Scenario: JSON 解析失败路径 warning 带 raw_text_head
- **WHEN** LLM 返回非 None、但 `_parse_llm_json` 返回 None(LLM 输出为非法 JSON,如被截断或 markdown 包裹错位)
- **THEN** caplog 捕获的 warning 消息 MUST 含 `raw_text_head=` 字段 + 前 200 字符原始输出;**不**触发 output confidence mix info(解析未成功)
