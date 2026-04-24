## Context

2026-04-24 E2E 验证 project 1728 用 3 家真实供应商 zip 跑完 pipeline,暴露 parser 层 6 项数据质量问题。这些问题共同影响 CH-2 detect-template-exclusion 的判定基础(identity_info 是否跨 bidder 重复、price_items 是否有足够样本),必须先修。

当前代码状态:
- [`role_classifier.py`](backend/app/services/parser/llm/role_classifier.py):一次 LLM 同时判 role + 抽 identity_info,LLM 错则识别错,无规则兜底
- [`fill_price.py::_parse_decimal`](backend/app/services/parser/pipeline/fill_price.py:184):正则 `^-?\d+(\.\d+)?$`,只剥 "￥/千分位/空格"
- [`fill_price.py::fill_price_from_rule`](backend/app/services/parser/pipeline/fill_price.py:33):单 sheet,`rule.sheet_name` 匹配,匹配不到退到"扫所有 sheet 用同一 mapping"(但都用同一 `column_mapping`,即列字母一样)
- [`PriceParsingRule.column_mapping`](backend/app/models/price_parsing_rule.py):JSONB 单 mapping,schema 固化到 spec + admin UI + price_impl 全部下游
- [`docx_parser.py`](backend/app/services/parser/content/docx_parser.py):已 import `lxml.etree`,textbox 抽取用 `element.xpath(expr, namespaces=NS)` 已废

约束:
- 保持 `python-docx` 当前版本(依赖升级风险)
- 保持现有 admin UI / /compare/price API 响应结构尽量稳定(schema 改动要尽量向后兼容)

## Goals / Non-Goals

**Goals:**
- 3 个真实供应商 zip 作 L2 golden,跑完后:
  - identity_info 3/3 正确(攀钢 / 浙江华建 / 江苏省华厦)
  - B 家 xlsx 的 unit_price/total_price 非 NULL
  - price_items 含"监理人员报价单分析表"5 行数据
  - 无备注行污染 price_items
  - item_code 为"序号"列时置空,非污染
  - docx 文本框内容不丢
- schema 改动(column_mapping → sheets_config)做向后兼容 migration,老项目重启后正常

**Non-Goals:**
- 中文大写金额归一("壹万贰仟" → 12000)
- 升级 python-docx
- 改 admin UI(rule PUT 端点 payload 结构适配 sheets_config 由本 change 覆盖,但 UI 组件重新设计留 follow-up)
- identity_info 多轮 LLM 校验(只做 1 次 LLM + 1 次规则)
- 改 /compare/price 响应结构(多 sheet 在后端展开后仍按老结构输出)

## Decisions

### D1 identity_info LLM + 规则双保险(Q1=C 对齐)

**策略**:
```
1. LLM 正常跑(现有路径),得到 identity_info.company_full_name
2. 独立规则扫 docx body:
   for doc in bidder.docs where file_type=='.docx':
     texts = DocumentText where location=='body' order by paragraph_index
     for t in texts:
       match = re.search(r'投标人\s*[（(]?\s*盖章\s*[）)]?\s*[:：]\s*(.+?)(?:\n|\s{2,}|$)', t.text)
       if match:
         rule_result = match.group(1).strip()
         break
3. 比对:
   if rule_result is None:                # 规则没命中
     keep LLM result (may be wrong but nothing better)
   elif LLM result == rule_result:       # 一致
     keep LLM result, role_confidence=high
   else:                                  # 不一致
     override to rule_result, role_confidence=low
     identity_info['_llm_original'] = LLM_value  # 保留审计
```

**新模块** `app/services/parser/identity_validator.py`:
- `extract_bidder_name_by_rule(session, bidder_id) -> str | None`:返回规则扫到的公司名或 None
- `apply_identity_validation(session, bidder_id, llm_identity_info)`:调用上面函数,做比对,UPDATE bidders.identity_info

**规则位置**:在 [`classify_bidder`](backend/app/services/parser/llm/role_classifier.py:80) 的最后 LLM → identity_info 写入后紧跟一步调用。

**bidders 表新列?** 不新增。`identity_info` JSONB 里加 `_llm_original` key(规则覆盖时)作为审计字段。前端现有的 `company_full_name` 读路径不变。

### D2 `_parse_decimal` 扩"元/万元/万"

**实现**(替换 [`fill_price.py:171`](backend/app/services/parser/pipeline/fill_price.py:171) `_parse_decimal`):

```python
_NUMBER_RE = re.compile(r"^-?\d+(?:\.\d+)?$")
_SUFFIX_MULTIPLIERS = [
    ("万元", Decimal("10000")),
    ("万", Decimal("10000")),
    ("元", Decimal("1")),
]

def _parse_decimal(raw, scale):
    if raw is None: return None
    if isinstance(raw, (int, float, Decimal)):
        return Decimal(str(raw))
    s = str(raw).strip()
    if not s: return None
    cleaned = s.replace(",", "").replace("￥", "").replace("¥", "").replace("$", "").replace(" ", "").replace("\u3000", "")
    multiplier = Decimal("1")
    for suffix, mult in _SUFFIX_MULTIPLIERS:  # 按长度降序
        if cleaned.endswith(suffix):
            cleaned = cleaned[: -len(suffix)]
            multiplier = mult
            break
    if not _NUMBER_RE.match(cleaned):
        return None
    try:
        return Decimal(cleaned) * multiplier
    except InvalidOperation:
        return None
```

**顺序重要**:"万元" 必须在 "元" 之前判(长 suffix 优先);"万" 在 "万元" 之后(否则 "万元" 会被拆成数字+"元")。

**测试矩阵** L1 `test_parse_decimal_suffix.py`:
- "486000" → 486000
- "￥486000元" → 486000
- "12.5万" → 125000
- "12.5万元" → 125000
- "1,234.56" → 1234.56
- "1,234.56 元" → 1234.56
- "12万元整" → None(不支持"整"后缀,走 fallback 备注)
- "hello" → None
- None → None
- 真实负数 "-1234" → -1234

### D3 **BREAKING** PriceParsingRule.sheets_config 多 sheet 候选(Q3=B 对齐)

**DB schema**:
```
ALTER TABLE price_parsing_rules
  ADD COLUMN sheets_config JSONB NOT NULL DEFAULT '[]'::jsonb;

-- 迁移老数据
UPDATE price_parsing_rules
SET sheets_config = jsonb_build_array(
  jsonb_build_object(
    'sheet_name', sheet_name,
    'header_row', header_row,
    'column_mapping', column_mapping
  )
)
WHERE sheets_config = '[]'::jsonb
  AND column_mapping IS NOT NULL AND column_mapping != '{}'::jsonb;

-- 保留老列(不 drop)作为 schema 缓冲期,下个 change 真删
```

**Python model**:
- `sheets_config: Mapped[list[dict]]` 新字段(属性)
- `column_mapping`/`sheet_name`/`header_row` 保留但标 `# deprecated: use sheets_config[0] fallback`,读时从 sheets_config 派生

**LLM prompt 改动** `PRICE_RULE_SYSTEM_PROMPT`:
```
输出 JSON 数组 sheets_config,每项一个价格表 sheet 的 mapping:
[
  {"sheet_name": "报价表", "header_row": 3, "column_mapping": {...}},
  {"sheet_name": "监理人员报价单分析表", "header_row": 2, "column_mapping": {...}}
]
规则:只包含 **真实数据行 >= 1 行** 的候选价格表 sheet;skip "人员进场计划/附件说明" 这类非金额表
```

**向后兼容读 + M1 单 sheet 异常隔离 + M3 失败态护栏**:`fill_price_from_rule(rule, xlsx)`:
```python
# M3 护栏:rule.status 不是 confirmed 直接返空,不走兜底
if rule.status != "confirmed":
    logger.warning("fill_price called with non-confirmed rule status=%s", rule.status)
    return FillResult()

# 向后兼容读:优先 sheets_config,老数据兜底到 sheet_name+column_mapping
sheets = rule.sheets_config or []
if not sheets and rule.column_mapping and rule.sheet_name and rule.header_row:
    sheets = [{
        "sheet_name": rule.sheet_name, "header_row": rule.header_row,
        "column_mapping": rule.column_mapping,
    }]
if not sheets:
    logger.warning("fill_price: rule has no sheets_config and no legacy fields, returning empty")
    return FillResult()

# M1 多 sheet 异常隔离:每 sheet 独立 try/except,一个 sheet 抛错不影响其他
result = FillResult()
for cfg in sheets:
    try:
        ...  # 对每个 sheet 跑原单 sheet 逻辑;累加到 result
    except Exception as e:
        logger.exception("fill_price sheet %r failed", cfg.get("sheet_name"))
        result.partial_failed_sheets.append(f"{cfg.get('sheet_name')}:异常")
        continue  # 继续下一 sheet
```

**下游影响**:
- `extract_bidder_prices` 无感(已按 `sheet_name` 分组)
- `is_same_template`(price_impl) 本来就按 sheet_names 集合比,自然兼容
- `/compare/price` 输出按 (item_name NFKC + fallback sheet_row) 聚合,多 sheet 展开天然兼容

### D4 备注行过滤(P1-6 design 级)

**实现** [`_extract_row`](backend/app/services/parser/pipeline/fill_price.py:96) 加前置 skip。**H3 修正:备注长文本可能落在任一 text 字段(不只 code_col),必须扫六字段**:

```python
PRICE_REMARK_SKIP_MIN_LEN = 100  # 常量

def _extract_row(...):
    ...
    # P1-6 备注行特征:六字段中任一 text 类字段长度 ≥ PRICE_REMARK_SKIP_MIN_LEN
    # 且其他 5 个字段全空(None 或空串)→ 判为备注污染行,整行 skip。
    # 扫 text 类字段(code/name/unit),数值类字段(qty/up/tp)不判长只参与"其他全空"判定
    text_fields = {"item_code": item_code, "item_name": item_name, "unit": unit}
    num_fields = {"qty_raw": qty_raw, "up_raw": up_raw, "tp_raw": tp_raw}
    for k, v in text_fields.items():
        if v and len(str(v)) >= PRICE_REMARK_SKIP_MIN_LEN:
            others_text = {tk: tv for tk, tv in text_fields.items() if tk != k}
            others_empty = (
                all(x is None or str(x).strip() == "" for x in others_text.values())
                and all(x is None for x in num_fields.values())
            )
            if others_empty:
                return None
    ...
```

阈值 100 字的合理性:真实 item_code/item_name/unit 一般 ≤50 字;备注长文本通常 ≥300 字。100 足够隔开。覆盖真实案例:
- "备注:1、全费用..." 在 A 列(code_col,item_code)→ 命中
- "本项目使用说明..." 在 B 列(name_col,item_name)→ 命中(原 design 漏)
- "单位说明见附件..." 在 C 列(unit_col,unit)→ 命中(原 design 漏)

### D5 item_code 序号列识别(P1-7 design 级)

**实现** [`_extract_row`](backend/app/services/parser/pipeline/fill_price.py:96) 数据抽出后加后置 heuristic:

```python
# P1-7:item_code 若纯数字整数(1/2/3...) 且本行有价格/名称/单位 → 判为序号列,置空
if item_code and re.fullmatch(r'\d+', str(item_code).strip()):
    # 有业务字段非空才判为污染(否则是真 empty)
    if item_name or unit or qty_raw or up_raw or tp_raw:
        item_code = None
```

**不**去全局扫 sheet 后判定(太复杂);单行级判断,每 rule 都走这里。

代价:真有编码是 "1" "2" 的 case(罕见,工程量清单一般带前缀)会被误清。记录 follow-up:如业务反馈误伤,扩展成"如果整列 code 都是纯数字且递增,才置空"。

### D6 docx textbox lxml xpath 绕过(Q4=B 对齐)

**现状** [`docx_parser.py`](backend/app/services/parser/content/docx_parser.py) 现有代码使用 `element.xpath(expr, namespaces=NS)` — 新版 python-docx 的 `BaseOxmlElement.xpath()` 已废 `namespaces` kwarg。

**新路径**:
```python
from lxml import etree

_TEXTBOX_XPATH_COMPILED = etree.XPath(
    ".//w:txbxContent//w:t",
    namespaces={"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"},
)

def extract_textboxes(doc) -> list[str]:
    root = doc.element  # python-docx Document._element is lxml root
    results = []
    for t_elem in _TEXTBOX_XPATH_COMPILED(root):
        txt = t_elem.text or ""
        if txt.strip():
            results.append(txt)
    return results
```

预编译 `etree.XPath` 提升性能。命名空间映射写死 w:(wordprocessingml),兼容 word 所有版本。

### D7 alembic migration 策略

- 新 migration `00XX_price_rule_sheets_config.py`
- `upgrade()`:
  ```python
  # Step 1: 加 sheets_config 新列
  op.add_column('price_parsing_rules',
                sa.Column('sheets_config', postgresql.JSONB, nullable=False, server_default='[]'))
  # Step 2: 转换老数据 column_mapping → sheets_config[0](排除失败态 rule 的空 mapping)
  op.execute("""
    UPDATE price_parsing_rules
    SET sheets_config = jsonb_build_array(
      jsonb_build_object(
        'sheet_name', sheet_name,
        'header_row', header_row,
        'column_mapping', column_mapping
      )
    )
    WHERE sheets_config = '[]'::jsonb AND column_mapping IS NOT NULL AND column_mapping != '{}'::jsonb;
  """)
  op.execute("ALTER TABLE price_parsing_rules ALTER COLUMN sheets_config DROP DEFAULT;")
  # Step 3(H2):把老列改 NULLABLE,让新写入路径可以不带它们(sheets_config 是新权威)
  #            保留列本身不 drop,老 admin UI GET 仍能读到 sheet_name/header_row/column_mapping
  op.alter_column('price_parsing_rules', 'sheet_name', nullable=True)
  op.alter_column('price_parsing_rules', 'header_row', nullable=True)
  op.alter_column('price_parsing_rules', 'column_mapping', nullable=True)
  ```
- `downgrade()`:
  ```python
  # 回写第一 sheet 到老列(兜底数据不丢)
  op.execute("""
    UPDATE price_parsing_rules
    SET sheet_name = (sheets_config -> 0 ->> 'sheet_name'),
        header_row = (sheets_config -> 0 ->> 'header_row')::int,
        column_mapping = (sheets_config -> 0 -> 'column_mapping')
    WHERE jsonb_array_length(sheets_config) >= 1
      AND (sheet_name IS NULL OR column_mapping IS NULL);
  """)
  op.alter_column('price_parsing_rules', 'sheet_name', nullable=False)
  op.alter_column('price_parsing_rules', 'header_row', nullable=False)
  op.alter_column('price_parsing_rules', 'column_mapping', nullable=False)
  op.drop_column('price_parsing_rules', 'sheets_config')
  ```
- **H2 双保险**:即使 migration 已 alter nullable,rule_coordinator 写新 rule 时 SHALL 同步回写 `sheets_config[0]` 的 3 字段到老列(`sheet_name`/`header_row`/`column_mapping`),作为 schema 缓冲期的 backward compat(老 admin UI GET 仍工作,老代码路径意外触发时有兜底)
- 保留老 `column_mapping/sheet_name/header_row` 列,本期不 drop;下个 parser change 统一清理(drop 列前确认老 UI 已切掉)

### D8 L2 golden fixture 用 3 供应商 zip(预期 ~¥1 以内)

**文件位置**:`backend/tests/fixtures/templates2/供应商{A,B,C}.zip`(git LFS or 直接入库 < 400MB 约束下)

**问题**:3 个 zip 合计 ~378MB,过大不宜入 git。

**解决**:
- L2 fixture 只入 **解压后 docx/xlsx 本身**(单文件 <200KB)+ 伪 zip fixture 模拟 zip 结构(借用现有 `build_zip_bytes` helper)
- 或者 `.gitignore` 放 real zips,L2 `_testdb_schema` 检查 env `DOCUMENTCHECK_L2_GOLDEN_ZIPS=/path/to/...` 存在才跑 golden 测试

**决策**:后者。env 缺失 → L2 `test_pipeline_parser_accuracy_golden.py` 内 `pytest.skip("DOCUMENTCHECK_L2_GOLDEN_ZIPS not set, skip golden 3-supplier e2e")`,防 CI 断。

## Risks / Trade-offs

| 风险 | 缓解 |
|---|---|
| `sheets_config` 改动影响 admin UI rule PUT 端点 | 向后兼容:后端 PUT 接受老 `column_mapping` payload(自动转 `sheets_config=[old]`),也接受新 `sheets_config` payload;UI 重做放 follow-up |
| identity_validator 正则太严(比如公司名含括号"(甲方)")被截断 | 正则 non-greedy `(.+?)` + 尾终止为"换行/段落结束/≥2 空格"。测试矩阵覆盖:"公司A（盖章）"/"XX有限公司 (甲方)"/"跨行的公司名" 三种 |
| item_code 全纯数字识别误伤真"编码=1"的 case | 加了"同行必须有其他字段"的前提;低风险;follow-up 如被反馈再收紧 |
| alembic 迁移老数据时 column_mapping=NULL(rule status=failed) | WHERE 条件过滤 `column_mapping IS NOT NULL AND column_mapping != '{}'`;失败态 rule 保持 sheets_config=[] |
| docx textbox xpath 非标准命名空间(mc:AlternateContent 包裹) | 测试 fixture 加一份 "AlternateContent 包裹的 textbox" docx 验证能取到 |
| L2 golden 测试真 LLM 调用(3 bidder × 2 LLM call)~1 分钟 ~¥1 | 加 `pytest.skip` + env gate;L1 用 mock LLM 覆盖其他 case;用户一次跑确认 golden 绿即归档 |

## Migration Plan

1. 本 change 改 model + alembic 0008(假设) + 所有代码路径
2. **部署步骤**:
   - `alembic upgrade head`(转 sheets_config)
   - 重启 backend(读新 schema)
   - 老项目无感:rule 原 column_mapping 自动映成 sheets_config[0];下次 re-parse 触发 LLM 会重识别
3. **Rollback**:`alembic downgrade -1` drop sheets_config 列 + git revert 代码
4. 历史项目 rule 已 `confirmed` 的:不自动重识别(保持现有 sheets_config=[old_single]);若想扫多 sheet,用户需手动 re-parse

## Open Questions

无。产品级决策 Q1-Q4 已全部对齐,design 级均有明确实现策略。
