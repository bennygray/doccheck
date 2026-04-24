# Tasks

6 项 parser 层精度修复 + schema 变更 + migration。按问题域分节;每节内先 impl 再测试;末尾总汇 L1/L2 全绿 + L2 golden(3 供应商 zip)。

## 1. P0-1 identity_info LLM + 规则双保险

- [x] 1.1 [impl] 新建 `backend/app/services/parser/identity_validator.py`:
  - `extract_bidder_name_by_rule(session, bidder_id) -> str | None`:按 docx body 段 non-greedy 正则 `投标人\s*[（(]?\s*盖章\s*[）)]?\s*[:：]\s*(.+?)(?:\n|\s{2,}|$)`,首次命中返回公司名
  - `apply_identity_validation(session, bidder_id)`:对比 LLM 与规则结果,按 "一致保留 / 不一致覆盖 + role_confidence=low + _llm_original 审计 / 未命中保留 LLM" 策略更新 DB
- [x] 1.2 [impl] `classify_bidder`([role_classifier.py:80](backend/app/services/parser/llm/role_classifier.py:80))在 LLM 成功路径末尾、commit 前调用 `apply_identity_validation`;失败路径(LLM 错)保持现有 `identity_info=NULL` 行为不变
- [x] 1.3 [impl] 改 `ROLE_CLASSIFY_SYSTEM_PROMPT`([prompts.py](backend/app/services/parser/llm/prompts.py)):在 `identity_info` 字段说明下加"投标方 = docx body 中'投标人（盖章）：' 后紧跟的公司全名,不是反复出现的招标方/项目名/甲方"
- [x] 1.4 [L1] 新建 `backend/tests/unit/test_identity_validator.py`:覆盖 10+ 正则 case(全角括号/半角括号/无括号/跨行/冒号中英/混排/空 body/未命中/多 docx 首命中)
- [x] 1.5 [L1] 新建 `backend/tests/unit/test_identity_validation_flow.py`:mock LLM 返 identity_info,test 覆盖
  - LLM 与规则一致 → 保留 LLM,**断言**`identity_info` 不含 `_llm_original` key
  - LLM 与规则不一致 → 规则覆盖 company_full_name;**M5 断言**`identity_info._llm_original == <原 LLM 值>`(审计字段确有写入);role_confidence 该 bidder 所有 docx/xlsx 全 low
  - 规则未命中 → 保留 LLM,`_llm_original` 不写入
  - LLM 缺 company_full_name 但规则命中 → rule 值直接写 company_full_name,`_llm_original` 不写入(无原值可留)

## 2. P0-3 `_parse_decimal` 扩 元/万元/万 后缀

- [x] 2.1 [impl] 改 `backend/app/services/parser/pipeline/fill_price.py::_parse_decimal`:
  - 扩 suffix 剥离列表 `[("万元", 10000), ("万", 10000), ("元", 1)]`(按长度降序判 endswith)
  - 扩 char 剥离:"¥"(半角)/ "\u3000"(全角空格)加入
- [x] 2.2 [L1] 新建 `backend/tests/unit/test_parse_decimal_suffix.py`:
  - case: `"486000"/486000`, `"￥486000元"/486000`, `"12.5 万"/125000`, `"12.5万元"/125000`, `"1,234.56"/1234.56`, `"1,234.56 元"/1234.56`, `"-1234"/-1234`, `"12万元整"/None`(不支持"整"), `"hello"/None`, `None/None`
  - case:既有 case 回归(`"1,234"/1234` 等)

## 3. P1-5 多 sheet 候选(BREAKING: PriceParsingRule.sheets_config)

- [x] 3.1 [impl] alembic 新建 `backend/alembic/versions/00XX_price_rule_sheets_config.py`(版本号按 git log 选):
  - Step 1 `add_column sheets_config JSONB NOT NULL DEFAULT '[]'::jsonb`
  - Step 2 `op.execute(UPDATE ...)` 老数据自动转 `[{sheet_name, header_row, column_mapping}]`(WHERE `column_mapping IS NOT NULL AND column_mapping != '{}'::jsonb`,排除失败态 rule)
  - Step 3 `DROP DEFAULT` 防止后续插入不带 sheets_config
  - **Step 4 (H2)** `alter_column` 把 `sheet_name` / `header_row` / `column_mapping` 三列改 `nullable=True`,让新 rule 只写 sheets_config 也能通过 NOT NULL 约束(列本身保留做 backward compat 读)
  - `downgrade()`:先回写 sheets_config[0] 的 3 字段到老列兜底 → `alter_column` 三列改回 `nullable=False` → `drop_column sheets_config`
- [x] 3.2 [impl] `backend/app/models/price_parsing_rule.py`:
  - 加 `sheets_config: Mapped[list[dict]]` JSON 字段(nullable=False,server_default='[]')
  - 老列 `column_mapping`/`sheet_name`/`header_row` 的 `Mapped` 注解改可空:`sheet_name: Mapped[str | None]`,`header_row: Mapped[int | None]`,`column_mapping: Mapped[dict[str, Any] | None]`;加 `# deprecated: use sheets_config` 注释(与 H2 migration alter_column 对齐)
- [x] 3.3 [impl] 改 `PRICE_RULE_SYSTEM_PROMPT` 返 `sheets_config: array`;system 明确"只返候选价格表 sheet(含 1+ 数据行),skip 人员进场计划/附件说明/目录"
- [x] 3.4 [impl] `backend/app/services/parser/llm/price_rule_detector.py`:
  - 改 JSON schema 验证:接受 `sheets_config: list[dict]`,每项有 sheet_name/header_row/column_mapping 3 键
  - 旧 format(单 `sheet_name`/`header_row`/`column_mapping`)向后兼容:包装为 `sheets_config=[{...}]`
- [x] 3.5 [impl] `backend/app/services/parser/pipeline/rule_coordinator.py`:
  - 写入新 rule 时 `sheets_config` 为 LLM 返回数组
  - **H2 同步回写**:为 backward compat 同时回写 `sheets_config[0]` 的 `sheet_name`/`header_row`/`column_mapping` 到老列(schema buffer;若 sheets_config 为空则 3 列保留 NULL)
  - `_try_claim` 占位 INSERT 时 3 老列传 None(依赖 H2 migration 后 nullable=True)
- [x] 3.6 [impl] `backend/app/services/parser/pipeline/fill_price.py::fill_price_from_rule`:
  - **M3 护栏**:rule.status != 'confirmed' 直接返 `FillResult()` + warning 日志
  - 读 `rule.sheets_config`;老 rule(sheets_config=[])fallback 构造 `[{rule.sheet_name, rule.header_row, rule.column_mapping}]`,前提老 3 列均非空
  - **M1 单 sheet 异常隔离**:每 sheet 包 try/except,抛错加入 `partial_failed_sheets=["<sheet>:异常"]` 并 `logger.exception`,**continue 下一 sheet 不中断**
  - 迭代 sheets_config 每项,分别调 `_extract_row` 逻辑
  - 统计每 sheet 的 success/fail,最终 bidder.parse_status 按"全 success=priced / 部分 success=price_partial / 全 fail=price_failed"判定
- [x] 3.7 [impl] `backend/app/api/routes/price.py`(PUT /api/projects/{pid}/price-rules/{id}):
  - 接受新 payload `{sheets_config: [...]}` 和老 payload `{column_mapping, sheet_name?, header_row?}`
  - 老 payload 自动包装成单 sheet sheets_config
  - 混传(两者同时给)返 422
- [x] 3.8 [L1] 新建 `backend/tests/unit/test_fill_price_multi_sheet.py`:
  - 多 sheet config 全 success / 部分 success / 全 fail 3 case
  - 老 rule(sheets_config=[])自动 fallback 单 sheet
  - **M1 单 sheet 抛异常(mock _extract_row raise)**:其他 sheet 仍继续,`partial_failed_sheets` 含该 sheet 名
  - **M3 rule.status=failed/identifying**:直接返 FillResult 空,不写 price_items
- [x] 3.9 [L1] 新建 `backend/tests/unit/test_price_rule_schema_migration.py`:
  - alembic upgrade/downgrade on fresh testdb
  - 老数据(手工 INSERT `column_mapping={...}, sheet_name='X', header_row=2, sheets_config=[]`)upgrade 后自动转 `sheets_config=[{X,2,{...}}]`
- [x] 3.10 [L1] 新建 `backend/tests/unit/test_price_rule_put_backward_compat.py`:
  - PUT 老 payload(column_mapping 无 sheets_config)被包装为单 sheet sheets_config,验证 DB 最终态
  - **M4** PUT 混传 `{sheets_config: [...], column_mapping: {...}}` 返 422

## 4. P1-6 备注行过滤

- [x] 4.1 [impl] `fill_price.py::_extract_row` 加前置 skip 规则(**H3 修正**):扫三个 text 字段(item_code/item_name/unit),任一长度 ≥ PRICE_REMARK_SKIP_MIN_LEN(=100) 且其他 5 个字段全空(text 空串或 None、num 全 None)→ return None;覆盖"备注长文本在任一 text 列"场景
- [x] 4.2 [impl] `PRICE_REMARK_SKIP_MIN_LEN = 100` 常量提到 fill_price.py 模块级
- [x] 4.3 [L1] 在 `test_fill_price_multi_sheet.py` 加 3 种备注行 case + 1 非备注 case:
  - 长 150 字落 A 列(item_code) + 其他全 None → skip
  - 长 150 字落 B 列(item_name) + 其他全 None → skip(**H3 新覆盖**)
  - 长 150 字落 C 列(unit) + 其他全 None → skip(**H3 新覆盖**)
  - 长 150 字落 B 列 + C 列有"项" + 数值列有值 → **不** skip(真实有说明的长 name 不误伤)

## 5. P1-7 item_code 序号列识别

- [x] 5.1 [impl] `fill_price.py::_extract_row` 加后置规则:`item_code 匹配 ^\d+$ 且本行有其他字段非空 → item_code = None`
- [x] 5.2 [L1] 补 `test_fill_price_multi_sheet.py` case:
  - 行 A="1", B=非空, F=非空 → item_code=None(序号列污染)
  - 行 A="DT-001", B=非空 → item_code 保留(真编码)
  - 行 A="1", B/C/D/E/F/G 全空 → 跳过(备注行前置规则先生效)

## 6. P2-8 docx textbox lxml xpath

- [x] 6.1 [impl] 改 `backend/app/services/parser/content/docx_parser.py`:
  - `_TEXTBOX_XPATH_COMPILED = etree.XPath(".//w:txbxContent//w:t", namespaces={"w": "<wordprocessingml URL>"})` 模块级预编译
  - 删除老 `element.xpath(expr, namespaces=NS)` 路径(引发 BaseOxmlElement.xpath 告警的那段)
  - 从 `doc.element`(python-docx Document root)调 `_TEXTBOX_XPATH_COMPILED(root)` 拿 `<w:t>` 列表
- [x] 6.2 [L1] 新建 `backend/tests/unit/test_docx_textbox_extract.py`:
  - Fixture:手工构造最小含 textbox 的 docx(zip 形态) + 不含 textbox 的 docx
  - 验证 `extract_docx` 输出中 textbox TextBlock 非空 + text 包含预期内容
  - 验证不含 textbox 时不报错,输出无 textbox TextBlock
  - 启动测试 + caplog 断言:不再出现 `BaseOxmlElement.xpath() got an unexpected keyword argument 'namespaces'` 警告

## 7. Spec sync

- [x] 7.1 [impl] 本 change delta `specs/parser-pipeline/spec.md`:MOD 5 Req(LLM 角色分类+identity / 报价表结构识别 / 报价数据回填 / 文档内容提取 textbox scenario / 报价列映射修正) + ADD 1 Req(identity_validator 规则模块);archive 时会 merge 进主 spec

## 8. L2 golden:3 供应商 zip 端到端验证

- [x] 8.1 [L2] 新建 `backend/tests/e2e/test_pipeline_parser_accuracy_golden.py`:
  - 前置 env gate:`if not os.environ.get("DOCUMENTCHECK_L2_GOLDEN_ZIPS"): pytest.skip("golden zips not provided")`
  - 从 env 路径读 `供应商A.zip / 供应商B.zip / 供应商C.zip`(用户本机的真实文件)
  - 跑完 pipeline(INFRA_DISABLE_PIPELINE 设 false,真 LLM)
  - 断言:
    - 3 bidder 的 `identity_info.company_full_name` 分别等于 "攀钢集团工科工程咨询有限公司" / "浙江华建" 系列 / "江苏省华厦工程项目管理有限公司" (B 的短名可接受 substring match)
    - 供应商B 的 xlsx 对应 bidder 的 `price_items` 中 total_price 或 unit_price 至少一个非 NULL
    - 每个 bidder 的 price_items 包含"监理人员报价单分析表" sheet_name 至少 5 行(真·报价明细)
    - 任何 price_items 行,item_code 要么为 None 要么不是纯数字整数
    - 任何 price_items 行,item_code 长度 < 100(无备注行污染)
    - 每个 bidder 至少有 1 条 `document_texts where location='textbox'` OR 日志无"BaseOxmlElement.xpath namespaces" 警告
  - 预期耗时:5~10 分钟;预期 LLM 成本:~¥1

## 9. 全量测试 + manual 凭证

- [x] 9.1 [manual] 跑 [L1][L2][L3] 全部测试,全绿
  - L1(backend):`cd backend && uv run pytest tests/unit/`;新增 6 文件 ~40+ case
  - L1(frontend):`cd frontend && npm test -- --run`;本 change 无前端改动,预期 114/114
  - L2:`TEST_DATABASE_URL=... uv run pytest tests/e2e/`;新增 1 golden file(需 env gate 开)
  - L3:**不跑**(本 change 仅后端数据层改动,无 UI 变化)
- [x] 9.2 [manual] 3 供应商 zip 跑 L2 golden + dump 最终 DB 状态(identity_info / price_items)到 `e2e/artifacts/parser-accuracy-fixes-2026-04-25/` README + snapshot.json(与之前 E2E 对照,证明 8 类问题中本 change 覆盖的 6 项全修)

## 10. 归档前 self-check

- [x] 10.1 [manual] openspec validate parser-accuracy-fixes → "is valid"
- [x] 10.2 [manual] `git diff --stat` 确认 scope:
  - 新 `identity_validator.py`
  - 改 `role_classifier.py` / `prompts.py` / `fill_price.py` / `price_rule_detector.py` / `rule_coordinator.py` / `docx_parser.py` / `price_parsing_rule.py` model / `price.py` route
  - 新 alembic 00XX migration
  - 新 L1 file × 6 / L2 file × 1
  - 新 change archive dir
- [x] 10.3 [manual] alembic 升/降级跑通:
  - `alembic upgrade head` → sheets_config 列存在,老数据转换正确,老 3 列 nullable=True
  - `alembic downgrade -1` → sheets_config drop,老 3 列 nullable=False 恢复;downgrade 前 rule 数据未丢失
  - `alembic upgrade head` → 再次升级成功
- [x] 10.4 [manual] handoff.md 追加本次归档条目(最近 5 条保留策略)

## 11. 总汇

- [x] 11.1 [manual] 跑 [L1][L2][L3] 全部测试,全绿(重跑一次确认无回归)
