## Why

2026-04-24 E2E 验证(project 1728,3 真实供应商 zip)暴露 8 类问题,本 change 覆盖归属 **parser 层的 6 项**,修复围标检测的**数据输入质量**。CH-3(config timeout)已归档,CH-2(detect-template-exclusion)依赖本 change 提供干净的 identity_info / price_items 做"同模板排除"判定;parser 数据失真 → CH-2 无论策略怎么设计都假阳性。

**可视化症状**:
- 3 家投标人 2/3 的 identity_info 被标成招标方"锂源科技"而不是真实投标方(攀钢 / 浙江华建 / 江苏华厦)
- 供应商 B 的 xlsx 金额字段全 NULL(因写"￥486000元"带"元"后缀,`_parse_decimal` 不识别)
- price_items 只抓了"报价表"sheet 1 行数据,丢了"监理人员报价单分析表"5 行真实明细
- 备注长文本被当 PriceItem 写入污染对比
- `item_code` 永远是"1"(A 列是序号,LLM 硬映成 code_col)
- 所有 docx 文本框内容丢(python-docx xpath namespaces API 变更)

## What Changes

### P0-1 identity_info LLM + 规则双保险
- 改 `ROLE_CLASSIFY_SYSTEM_PROMPT`:`identity_info` 字段说明明确"投标方 = '投标人（盖章）：' 后紧跟的公司,不是反复出现的招标方/项目名"
- 新模块 `app/services/parser/identity_validator.py`:正则扫 docx body 找 `投标人[（(]盖章[）)]\s*[:：]` 后的公司名
- `classify_bidder` 调 LLM 后追加一步校验:LLM 与规则一致 → 保留 LLM + high;不一致 → 规则覆盖 + role_confidence='low';规则未命中 → 保留 LLM

### P0-3 `_parse_decimal` 扩后缀归一
- `app/services/parser/pipeline/fill_price.py::_parse_decimal` 扩规则:
  - 剥后缀 "元"/"万元"/"万";"万"/"万元" 数值 × 10000
  - 现有 "￥/千分位/空格" 保留
  - "￥486000元" → Decimal("486000.00");"12.5 万" → Decimal("125000.00")
- **中文大写归一(壹/贰/...)不在本 change**(放 follow-up)

### P1-5 **BREAKING** `PriceParsingRule` schema:单 mapping → 多 sheet 候选
- DB schema:`column_mapping` (JSONB) → `sheets_config` (JSONB array of `{sheet_name, header_row, column_mapping}`)
- alembic 迁移:老数据自动转换 `{sheet_name, header_row, column_mapping}` → `sheets_config=[old_single]`
- LLM prompt `PRICE_RULE_SYSTEM_PROMPT` 返 `sheets_config` 数组(包含 xlsx 中所有**数据量 ≥1 行**的候选价格表);非候选 sheet 跳过
- `fill_price_from_rule` 改按 `sheets_config` 每项迭代扫 sheet
- downstream 适配:
  - `price_impl/extractor.extract_bidder_prices` 多 sheet iter 不变(原本就按 sheet 分组)
  - `price_impl/item_list_detector.is_same_template` 按多 sheet 并集判定
  - `/compare/price` 多 sheet cell 对齐降级 `(sheet_name, row_index)` key 已支持

### P1-6 备注行过滤
- `fill_price.py::_extract_row` 加前置 skip 规则:**A 列 text 长度 >100 且 B-G 列全 None** → 返 None 跳过(典型备注长文本行特征)
- 阈值 100 字常量化 `PRICE_REMARK_SKIP_MIN_LEN`,后期可调

### P1-7 item_code 序号列识别并置空
- `fill_price.py::_extract_row` 加后置规则:若 `item_code` 值是**纯数字整数**(regex `^\d+$`)且该行 qty/up/tp 至少一个非空 → 判定为"序号列污染",item_code 置 None
- 不影响真实含字母+数字编码的 case(如"DT-001")

### P2-8 docx textbox 用 lxml xpath 绕过
- `app/services/parser/content/docx_parser.py` 抽 textbox 路径改用 `lxml.etree.XPath()` + `nsmap=root.nsmap`,绕开 python-docx `BaseOxmlElement.xpath(namespaces=...)` 已废参数
- 保持 `python-docx` 当前版本

## Capabilities

### New Capabilities
(无)

### Modified Capabilities
- `parser-pipeline`:多个 Requirement 改动
  - "LLM 角色分类与身份信息提取" 新增 identity_validator 后置校验契约
  - "XLSX 报价表结构识别" 改 `sheets_config` 数组契约
  - "报价表数据抽取规则(fill_price)" 改多 sheet 迭代 + 备注行 skip + item_code 序号列置空
  - "DOCX 内容提取" textbox 抽取契约(新)

## Impact

### Code
- **新建**:`app/services/parser/identity_validator.py`(~80 行,正则 + 对比函数)
- **改**:`app/services/parser/llm/role_classifier.py`(调 validator 做后置校验,~30 行)
- **改**:`app/services/parser/llm/prompts.py`(identity prompt 文案 + price_rule prompt 改返 sheets_config)
- **改**:`app/services/parser/pipeline/fill_price.py`(多 sheet iter + _parse_decimal 扩 + 备注行 skip + item_code 序号列 heuristic,~40 行增删)
- **改**:`app/services/parser/pipeline/rule_coordinator.py`(写入 sheets_config 而非 column_mapping)
- **改**:`app/services/parser/llm/price_rule_detector.py`(返 sheets_config 结构)
- **改**:`app/models/price_parsing_rule.py`(column_mapping → sheets_config)
- **改**:`app/services/parser/content/docx_parser.py`(textbox 改 lxml xpath)
- **迁移**:新 alembic version `00XX_price_rule_sheets_config.py`

### Spec
- `openspec/specs/parser-pipeline/spec.md` 4 Requirement modified(见 Modified Capabilities)

### 测试
- L1 新增 5 file(见测试策略)
- L2 新增 1 file(用 3 供应商 zip 作 golden 数据)
- L3 不需要

### 依赖
- 不升级 `python-docx`(保持当前版本)
- `lxml` 已是 python-docx 底层依赖,不新增

### 部署
- alembic `alembic upgrade head` 自动转换老数据
- 无 env 变量新增
- 无 breaking UI 变化

### 下游 change
- CH-2 detect-template-exclusion 依赖本 change 的干净 identity_info + 完整 price_items
