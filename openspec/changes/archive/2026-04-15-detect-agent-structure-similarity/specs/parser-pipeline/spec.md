## MODIFIED Requirements

### Requirement: 文档内容提取

系统 SHALL 对每个 `parse_status='extracted'` 的 DOCX/XLSX 文件执行内容提取,落库到 `document_texts` / `document_metadata` / `document_images` / `document_sheet` 四张表。提取在 pipeline 的 `identifying` 阶段早段发生(内容提取成功后才进入 LLM 调用)。

- **DOCX**:提取正文段落、页眉页脚、文本框文本、表格每行合并文本,逐条写 `document_texts`,`location` 标注来源(`body` / `header` / `footer` / `textbox` / `table_row`)
- **XLSX**:
  - 提取所有 sheet(含隐藏 sheet)的合并文本,每 sheet 一条写 `document_texts`,`location='sheet'`(供相似度 Agent 消费)
  - **同时** 写 `document_sheet` 表,每 sheet 一行,含 `sheet_index` / `sheet_name` / `hidden` / `rows_json`(整表 cell 矩阵 JSONB)/ `merged_cells_json`(合并单元格 ranges 字符串列表 JSONB)
  - xlsx 持久化裁切:`rows_json` 行数 > `STRUCTURE_SIM_MAX_ROWS_PER_SHEET`(默认 5000)→ 截断前 5000 行 + warning 日志;不阻塞写入
- **元数据**:从 DOCX/XLSX 的 `docProps/core.xml` + `docProps/app.xml` 抽 `author / last_saved_by / company / created_at / modified_at / app_name / app_version`,写 `document_metadata`(每文档 1:1)
- **图片**:DOCX 嵌入图片落盘到 `extracted/<pid>/<bid>/<hash>/imgs/`,计算 md5(32hex)+ phash(64bit),写 `document_images`
- 不支持的格式(DOC/XLS/PDF):`bid_documents.parse_status='skipped'` + `parse_error='暂不支持 {ext} 格式'`,**不**写 document_texts/metadata/images/sheet

#### Scenario: 标准 DOCX 提取段落

- **WHEN** 解析一个含 20 段正文 + 1 个文本框 + 1 个 3 行表格的 DOCX
- **THEN** `document_texts` 新增 ≥ 24 条(20 段 + 1 文本框 + 3 表行);`paragraph_index` 按源序递增;正文段 `location='body'`,文本框 `location='textbox'`,表行 `location='table_row'`

#### Scenario: DOCX 页眉页脚单独提取

- **WHEN** DOCX 含页眉"某公司"与页脚"第 N 页",调用 extract_content
- **THEN** `document_texts` 中该文档至少两条 `location='header'` / `location='footer'` 的记录;**不进入** `location='body'`(US-4.2 AC-3 "不参与文本相似度")

#### Scenario: XLSX 多 sheet 提取含 DocumentSheet

- **WHEN** 解析一份含 3 sheet 的 xlsx(其中 1 隐藏)
- **THEN** `document_texts` 新增 3 条 `location='sheet'`(保留既有行为);`document_sheet` 新增 3 条,`sheet_index` 为 0/1/2,`hidden` 对隐藏 sheet 为 true,`rows_json` 为 cell 矩阵(list of list),`merged_cells_json` 为字符串列表

#### Scenario: XLSX 巨型 sheet 裁切

- **WHEN** 解析一份单 sheet 含 8000 行的 xlsx
- **THEN** `document_sheet.rows_json` 含 5000 行(前 5000);日志 warning 记录 "sheet 'X' 截断 3000 行";不阻塞文档解析流程

## ADDED Requirements

### Requirement: DocumentSheet 数据契约

后端 MUST 提供 `document_sheet` 表承载 xlsx cell 级数据,schema:

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

### Requirement: DocumentSheet 回填脚本

后端 MUST 提供一次性回填脚本 `backend/scripts/backfill_document_sheets.py`,供运维手工执行,满足:

1. **扫描目标**:`BidDocument.file_ext == ".xlsx" AND parse_status == "identified" AND NOT EXISTS(DocumentSheet for this bid_document_id)`(幂等:已回填的 doc 跳过)
2. **执行**:对每个目标 doc,`extract_xlsx(doc.file_path)` 后写 DocumentSheet 行;写入失败 rollback + 日志输出,继续下一个(错误隔离)
3. **日志**:每 doc 一行 `OK doc={id} sheets={n}` 或 `FAIL doc={id}: {err}`;结束输出 `total={n} success={s} failed={f}`
4. **入口**:`uv run python backend/scripts/backfill_document_sheets.py` 或 `python -m scripts.backfill_document_sheets`
5. **不纳入 alembic migration**:migration 只动 schema;数据层回填由运维单独触发

#### Scenario: 幂等重跑

- **WHEN** 首次回填完成后立即重跑脚本
- **THEN** 输出 `total=0 success=0 failed=0`;已存在 DocumentSheet 的 doc 全部被 `NOT EXISTS` 过滤,不重复插入

#### Scenario: 单 doc 失败不中断

- **WHEN** 100 个目标 doc 中 1 个文件已损坏(openpyxl 抛异常)
- **THEN** 脚本继续处理剩余 99 个;最终 `total=100 success=99 failed=1`;已 rollback 的 doc 的 DocumentSheet 不写入

#### Scenario: 回填脚本不修改 BidDocument 状态

- **WHEN** 脚本处理某 doc
- **THEN** `BidDocument.parse_status` 保持原值(仍为 `identified`);脚本只写 DocumentSheet 不改其他表

### Requirement: xlsx_parser 合并单元格暴露

`app/services/parser/content/xlsx_parser.py` 的 `SheetData` dataclass MUST 追加 `merged_cells_ranges: list[str]` 字段,由 `extract_xlsx` 填充为 openpyxl `ws.merged_cells.ranges` 的字符串化结果列表。

- 读取模式必须为 `read_only=False`(openpyxl read_only 模式读不到 merged_cells)
- 该字段默认空列表(无合并单元格时);非 None

#### Scenario: 无合并单元格

- **WHEN** 一份 xlsx 无任何合并单元格
- **THEN** `SheetData.merged_cells_ranges == []`

#### Scenario: 有合并单元格

- **WHEN** 一份 xlsx 含合并单元格 A1:B2 和 C3:D5
- **THEN** `SheetData.merged_cells_ranges` 含 `"A1:B2"` 和 `"C3:D5"`(顺序不敏感)
