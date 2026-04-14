## MODIFIED Requirements

### Requirement: 文档内容提取

系统 SHALL 对每个 `parse_status='extracted'` 的 DOCX/XLSX 文件执行内容提取,落库到 `document_texts` / `document_metadata` / `document_images` / `document_sheets` 四张表。提取在 pipeline 的 `identifying` 阶段早段发生(内容提取成功后才进入 LLM 调用)。

- **DOCX**:提取正文段落、页眉页脚、文本框文本、表格每行合并文本,逐条写 `document_texts`,`location` 标注来源(`body` / `header` / `footer` / `textbox` / `table_row`)
- **XLSX**:
  - 提取所有 sheet(含隐藏 sheet)的合并文本,每 sheet 一条写 `document_texts`,`location='sheet'`(供相似度 Agent 消费)
  - **同时** 写 `document_sheets` 表,每 sheet 一行,含 `sheet_index` / `sheet_name` / `hidden` / `rows_json`(整表 cell 矩阵 JSONB)/ `merged_cells_json`(合并单元格 ranges 字符串列表 JSONB)
  - xlsx 持久化裁切:`rows_json` 行数 > `STRUCTURE_SIM_MAX_ROWS_PER_SHEET`(默认 5000)→ 截断前 5000 行 + warning 日志;不阻塞写入
- **元数据**:从 DOCX/XLSX 的 `docProps/core.xml` + `docProps/app.xml` 抽 `author / last_saved_by / company / created_at / modified_at / app_name / app_version / template`,写 `document_metadata`(每文档 1:1)
- **图片**:DOCX 嵌入图片落盘到 `extracted/<pid>/<bid>/<hash>/imgs/`,计算 md5(32hex)+ phash(64bit),写 `document_images`
- 不支持的格式(DOC/XLS/PDF):`bid_documents.parse_status='skipped'` + `parse_error='暂不支持 {ext} 格式'`,**不**写 document_texts/metadata/images/sheet

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

## ADDED Requirements

### Requirement: DocumentMetadata.template 数据契约

`document_metadata` 表 MUST 追加 `template VARCHAR(255) NULL` 列,alembic 迁移版本号 `0007_add_document_metadata_template`,单向 head(回滚 drop 列)。

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
