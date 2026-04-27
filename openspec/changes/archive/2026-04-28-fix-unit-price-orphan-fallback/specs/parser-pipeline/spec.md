## ADDED Requirements

### Requirement: 报价 XLSX 选取 fallback 与单 bidder 单类不变量

系统 SHALL 在"报价规则识别"与"报价数据回填"两个阶段为每个 bidder 独立选取参与的 XLSX 文件,采用以下选取规则:

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

## MODIFIED Requirements

> **本次扩展说明**:原 spec 隐含"仅 `file_role='pricing'` 类 XLSX 进入报价回填"。本 change 把它扩展为"`pricing` 优先 + `unit_price` fallback,单 bidder 不混合"。下面 MODIFIED 的两个 Requirement 是把这一扩展显式落到相关条款,行为细节见上方 ADDED Requirement"报价 XLSX 选取 fallback 与单 bidder 单类不变量"。语义性质为**扩展**(原行为是新行为的子集),不是 breaking change。

### Requirement: 报价数据回填

系统 SHALL 根据 `price_parsing_rules.sheets_config` 从 bidder 的 XLSX 文件中按**多 sheet 迭代**读取报价项,写入 `price_items` 表。`bidder.parse_status` 根据回填结果置 `priced` / `price_partial` / `price_failed`。

- **触发时机**:
  1. 规则首次 `confirmed=true` 后自动批量触发
  2. 用户 `PUT /api/projects/{pid}/price-rules/{id}` 修改 sheets_config → 清空该项目所有 `price_items` → 重新回填
  3. 单个 bidder `POST /api/documents/{id}/re-parse` 命中该 bidder 的 XLSX → 仅重跑该 bidder
- **XLSX 选取**:遵循"报价 XLSX 选取 fallback 与单 bidder 单类不变量" Requirement 定义的规则(`pricing` 优先 / `unit_price` fallback / 单 bidder 不混合)
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

### Requirement: 解析流水线编排

系统 SHALL 为每个 `extracted` bidder 启动一个 `asyncio.create_task(run_pipeline(bidder_id))` 协程,按阶段顺序推进:`extract_content → llm_classify → (wait_project_rule) → fill_price`。各阶段间状态持久化到 DB,重启后可从当前状态恢复。

- **阶段衔接**:每阶段完成 UPDATE `bidder.parse_status` + publish SSE 事件,下一阶段开始前 re-SELECT 当前状态
- **失败隔离**:任一阶段异常 → bidder 标该阶段失败态(identify_failed / price_failed)+ parse_error;不影响同项目其他 bidder
- **re-parse 重跑**:`POST /api/documents/{id}/re-parse` 端点重置该文档所属 bidder 的相关阶段,重新触发 pipeline(pipeline 内部根据当前 parse_status 决定从哪段继续)
- **报价阶段进入条件**:bidder 至少有一个 `file_role='pricing'` 或 `file_role='unit_price'`(fallback)的 XLSX(详见"报价 XLSX 选取 fallback 与单 bidder 单类不变量" Requirement)

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

- **WHEN** classify_bidder 抛异常(非 LLM error 而是代码异常)
- **THEN** bidder.parse_status = `identify_failed`;parse_error 含异常信息

#### Scenario: re-parse 重跑失败文档

- **WHEN** 用户对 `identify_failed` 文档调 re-parse
- **THEN** 该 bidder 重新走 pipeline;若已 `identified` 跳过 LLM 直接进 pricing
