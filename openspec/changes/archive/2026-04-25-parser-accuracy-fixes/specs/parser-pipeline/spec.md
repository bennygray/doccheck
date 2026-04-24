## MODIFIED Requirements

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


### Requirement: 报价数据回填

系统 SHALL 根据 `price_parsing_rules.sheets_config` 从 bidder 的 XLSX 文件中按**多 sheet 迭代**读取报价项,写入 `price_items` 表。`bidder.parse_status` 根据回填结果置 `priced` / `price_partial` / `price_failed`。

- **触发时机**:
  1. 规则首次 `confirmed=true` 后自动批量触发
  2. 用户 `PUT /api/projects/{pid}/price-rules/{id}` 修改 sheets_config → 清空该项目所有 `price_items` → 重新回填
  3. 单个 bidder `POST /api/documents/{id}/re-parse` 命中该 bidder 的 XLSX → 仅重跑该 bidder
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

- **WHEN** bidder 的所有 bid_documents 中无 `file_role='pricing'` 的 XLSX 文件
- **THEN** pipeline 不进入 `pricing` 阶段;bidder.parse_status 稳定在 `identified`(终态);`price_items` 为空;project progress 不把该 bidder 计入 `pricing_total`


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


## ADDED Requirements

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
