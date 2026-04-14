# file-upload Specification

## Purpose

为投标人 / 投标文件 / 报价规则提供完整数据生命周期: 投标人 CRUD、压缩包上传(zip-bomb / zip-slip / GBK 文件名 / 嵌套 / 加密包防护)、解压后文件树、加密包密码重试、报价元配置 + 列映射规则骨架。本 capability 是 M2 数据输入面的核心,C5+ LLM 解析与 C6+ 围标检测均依附其产生的 `bidders` / `bid_documents` / `price_*` 表。

## Requirements

### Requirement: 投标人 CRUD

系统 SHALL 提供投标人 CRUD 端点,所有端点 MUST 挂 `Depends(get_current_user)` 并走项目级权限过滤(复用 C3 `get_visible_projects_stmt` 模式)。投标人属于项目;reviewer 仅可操作自己项目的投标人,admin 可操作任意项目的投标人。名称同项目内唯一。

- `POST /api/projects/{pid}/bidders` 创建投标人(multipart,`name` 必填 + `file` 选填)
- `GET /api/projects/{pid}/bidders` 列表
- `GET /api/projects/{pid}/bidders/{bid}` 详情
- `DELETE /api/projects/{pid}/bidders/{bid}` 软删投标人 + 硬删关联 `bid_documents` + 硬删 `extracted/` 物理目录;`uploads/` 原压缩包保留

#### Scenario: 只传 name 创建投标人成功

- **WHEN** reviewer 对自己的项目 `POST /bidders` 仅传 `name="A 公司"`
- **THEN** 响应 201,返回体含 `id / name / project_id / parse_status="pending" / file_count=0`

#### Scenario: 同项目名称重复返回 409

- **WHEN** 同项目内已存在 `name="A 公司"` 的投标人,再次提交同名
- **THEN** 响应 409

#### Scenario: 跨项目同名允许

- **WHEN** 项目 P1 有"A 公司",对项目 P2 创建"A 公司"
- **THEN** 响应 201

#### Scenario: name 为空拒绝

- **WHEN** 请求体 `name=""`
- **THEN** 响应 422

#### Scenario: name 超长拒绝

- **WHEN** `name` 超过 200 字符
- **THEN** 响应 422

#### Scenario: reviewer 操作他人项目下的投标人返回 404

- **WHEN** reviewer A 对 reviewer B 的项目 `POST /bidders` 或 `GET /bidders`
- **THEN** 响应 404(不返 403,复用 C3 "防存在性泄露"约定)

#### Scenario: admin 可操作任意项目的投标人

- **WHEN** admin 对任一 reviewer 的项目调 4 端点中任一
- **THEN** 均不返 404

#### Scenario: 删除 reviewer 自己的投标人成功

- **WHEN** reviewer 对自己项目内的投标人发 `DELETE`
- **THEN** 响应 204;DB 中 `bidders.deleted_at` 已置值;该投标人的 `bid_documents` 记录已物理删除;`extracted/{pid}/{bid}/` 目录已 rmtree;`uploads/{pid}/{bid}/` 原压缩包保留

#### Scenario: 检测中项目拒绝删除投标人

- **WHEN** 项目 `status="analyzing"`,对其投标人发 DELETE
- **THEN** 响应 409

---

### Requirement: 文件上传(创建 + 追加)

系统 SHALL 提供两个上传入口:创建投标人时同时上传(`POST /bidders` 的 `file` 字段),以及为已有投标人追加上传(`POST /api/projects/{pid}/bidders/{bid}/upload`)。文件大小 MUST ≤500MB;文件类型 MUST 通过魔数 + 扩展名双校验(白名单:`.zip / .7z / .rar`);MD5 去重粒度为投标人内(`UNIQUE(bidder_id, md5)`)。上传成功 MUST 立即返回 201,不等待解压;解压走后台 `asyncio.create_task`。

#### Scenario: 追加上传合法 ZIP 成功

- **WHEN** 对已有投标人 `POST /upload`,文件为合法 ZIP,大小 <500MB
- **THEN** 响应 201,返回体含 `bidder_id / archive_filename / new_files: [...] / skipped_duplicates: []`;bidder `parse_status` 变为 `extracting`

#### Scenario: 上传 .exe 文件被拒

- **WHEN** 上传扩展名为 `.exe` 的文件
- **THEN** 响应 415

#### Scenario: 上传改扩展名的伪 ZIP

- **WHEN** 上传 `.exe` 改名为 `.zip`(魔数不匹配)
- **THEN** 响应 415(魔数校验失败)

#### Scenario: 上传超 500MB 文件

- **WHEN** 上传 >500MB 文件
- **THEN** 响应 413

#### Scenario: 同 bidder 重复上传相同 MD5 文件被跳过

- **WHEN** 为同一 bidder 第二次上传相同内容文件
- **THEN** 响应 201,但 `new_files=[]`,`skipped_duplicates` 含该 MD5

#### Scenario: 不同 bidder 上传相同 MD5 文件不去重

- **WHEN** 向 bidder A 上传文件 X,再向 bidder B 上传同 X
- **THEN** 两次均 201 并正常入库(同一 project 的两个 bidder 各自持有一份记录)

#### Scenario: 上传到不存在的 bidder

- **WHEN** `POST /bidders/{bid}/upload` 但 `bid` 不存在
- **THEN** 响应 404

#### Scenario: 上传成功后文件物理落盘

- **WHEN** 上传合法 ZIP
- **THEN** `backend/uploads/{pid}/{bid}/<hash16>_<name>` 文件存在,大小等于上传大小

---

### Requirement: 压缩包安全解压

系统 SHALL 在上传成功后异步解压压缩包,过程 MUST 防护 zip-bomb(总解压大小 ≤2GB / 文件总数 ≤1000 / 嵌套深度 ≤3)与 zip-slip(拒绝含 `..` / 绝对路径 / 解压后实际位置超出解压根目录的 entry)。GBK 编码中文文件名 MUST 正确还原。损坏/空压缩包 MUST 标 `parse_status=failed` + 可读 `parse_error`。

#### Scenario: 正常 ZIP 解压成功

- **WHEN** 解压一个正常 ZIP,含 docx / xlsx / jpg 混合文件
- **THEN** bidder `parse_status` 变为 `extracted`;`bid_documents` 表生成对应条数记录;`extracted/{pid}/{bid}/<archive>/` 下文件结构与 ZIP 内一致

#### Scenario: zip-slip 恶意 entry 被跳过

- **WHEN** ZIP 含一个 entry 路径为 `../../etc/passwd`
- **THEN** 该 entry 不解压到 `extracted/` 外;`bid_documents` 记录包含一条 `parse_status=skipped` + `parse_error="路径不安全,已跳过"` 的条目;其他正常 entry 照常解压

#### Scenario: 解压总大小超 2GB 中断

- **WHEN** 压缩包声明或实际解压过程中总字节数超过 2GB
- **THEN** 中断解压;bidder `parse_status=failed`;`parse_error` 含"解压文件过大,超过 2GB 限制"

#### Scenario: 文件数超 1000 中断

- **WHEN** 压缩包含 >1000 个文件
- **THEN** 中断;`parse_status=failed`;`parse_error` 含"文件数超过 1000"

#### Scenario: 嵌套压缩包超 3 层

- **WHEN** ZIP 内包含嵌套 ZIP,递归深度达到第 4 层
- **THEN** 第 4 层不解压;`bid_documents` 记录一条 `parse_status=skipped` + `parse_error="嵌套层数超过 3"`;前 3 层正常解压

#### Scenario: GBK 中文文件名还原

- **WHEN** ZIP 中文件名使用 GBK 编码(而非 UTF-8 flag)
- **THEN** 解压后 `bid_documents.file_name` 字段为正确的中文字符串,非乱码

#### Scenario: 损坏的 ZIP

- **WHEN** 上传损坏的 ZIP 文件(CRC 校验失败)
- **THEN** `parse_status=failed`;`parse_error="文件已损坏,无法解压"`

#### Scenario: 空压缩包

- **WHEN** 上传空 ZIP(无 entry)
- **THEN** `parse_status=failed`;`parse_error="压缩包内无有效文件"`

#### Scenario: 不支持的文件类型被标 skipped

- **WHEN** ZIP 内含 `.doc` / `.xls` / `.pdf` 文件
- **THEN** `bid_documents` 对应记录 `parse_status="skipped"` + `parse_error="暂不支持 X 格式"`;不报错,不中断其他文件

---

### Requirement: 加密压缩包密码重试

系统 SHALL 检测加密压缩包,标记为 `parse_status="needs_password"` 并提供 `POST /api/documents/{id}/decrypt` 端点接受密码重试。密码错误返回 400 + 保持 `needs_password` 状态(**D2 决策:不计数、不冻结**,留 C17 顺手处理)。

#### Scenario: 加密 ZIP 上传后被检测

- **WHEN** 上传设置了密码的 ZIP
- **THEN** 解压协程检测到密码保护;bidder `parse_status` 置为 `needs_password`;`bid_documents` 无明文解压产物;`parse_error="需要密码"`

#### Scenario: 正确密码重试解压成功

- **WHEN** 对 `needs_password` 状态的 bidder 调 `POST /api/documents/{id}/decrypt {password: "<correct>"}`,密码正确
- **THEN** 响应 202(接受,重新解压);bidder `parse_status` 先变 `extracting` 后变 `extracted`;`bid_documents` 正常生成

#### Scenario: 错误密码重试

- **WHEN** 密码错误
- **THEN** 响应 400(`"密码错误"`);bidder `parse_status` 回到 `needs_password`(**不计数不冻结**)

#### Scenario: 状态非 needs_password 调 decrypt

- **WHEN** 对已 `extracted` / `failed` 状态调 `POST /decrypt`
- **THEN** 响应 409

---

### Requirement: 文件列表与解析状态

系统 SHALL 提供 `GET /api/projects/{pid}/bidders/{bid}/documents` 端点返回该投标人的文件列表,包含树形结构(保留原压缩包内目录层级)、文件类型、解析状态(`pending` / `extracting` / `extracted` / `skipped` / `failed` / `needs_password`)与错误原因(若有)。`bid_documents.file_role` 字段在 C4 阶段恒为 NULL(LLM 角色分类 C5 填);列表响应 MUST 包含 `file_role` 字段预留给前端。

#### Scenario: 返回文件列表

- **WHEN** reviewer 请求自己项目投标人的 documents
- **THEN** 响应 200,body 为数组,每条含 `id / file_name / file_path / file_size / file_type / parse_status / parse_error / file_role(null) / md5 / created_at`

#### Scenario: 解析中状态可查

- **WHEN** 上传后立即查 documents(bidder 仍在 extracting)
- **THEN** 返回可能为空数组或部分已解压条目,取决于协程进度;至少 bidder 详情 `parse_status=extracting`

#### Scenario: 跨权限访问被拒

- **WHEN** reviewer A 查 reviewer B 项目的文件列表
- **THEN** 响应 404

---

### Requirement: 文件下载与删除

系统 SHALL 提供 `GET /api/documents/{id}/download` 下载原始压缩包(不是解压后的单文件;US-3.3 AC-6 "可下载原始文件用于证据保全")。 `DELETE /api/documents/{id}` 删除单个 `bid_documents` 记录(不物理删压缩包,保留可重建解压产物)。权限过滤沿用 C3 模式。

#### Scenario: 下载原始压缩包

- **WHEN** reviewer 对自己投标人的 document 调 `GET /download`
- **THEN** 响应 200 + 文件流(Content-Type: application/zip 等);文件内容等于上传时的原压缩包

#### Scenario: 原始文件已清理

- **WHEN** `uploads/` 目录下物理文件已被生命周期任务清掉,但 DB 记录仍在
- **THEN** 响应 410 Gone + `"原始文件已清理"` 文案(C4 阶段实际不会发生,但端点 MUST 实现该分支以应对未来生命周期任务)

#### Scenario: 非 owner 下载返 404

- **WHEN** reviewer A 下载 reviewer B 项目的 document
- **THEN** 响应 404

#### Scenario: 删除 document 记录不删物理压缩包

- **WHEN** `DELETE /api/documents/{id}`
- **THEN** 响应 204;DB 中该 `bid_documents` 记录被物理删除;`uploads/` 下原压缩包保留

---

### Requirement: 项目报价元配置

系统 SHALL 为每个项目提供 **1:1** 的报价元配置(币种 / 含税 / 单位),通过 `GET` 与 `PUT /api/projects/{pid}/price-config` 管理。项目创建时**不**自动生成默认配置;首次 `GET` 若未配置返回 `null`,前端引导用户配置。

- `currency ∈ {"CNY", "USD", "EUR", "HKD"}`
- `tax_inclusive ∈ {true, false}`
- `unit_scale ∈ {"yuan", "wan_yuan", "fen"}`(元 / 万元 / 分)

#### Scenario: 首次 GET 返回 null

- **WHEN** 项目未配置过 price-config,首次 `GET /price-config`
- **THEN** 响应 200,body = `null`

#### Scenario: PUT 创建配置

- **WHEN** `PUT /price-config` 提交合法字段
- **THEN** 响应 200,body 为完整配置对象;再次 GET 可回读

#### Scenario: PUT 覆盖配置

- **WHEN** 已有配置,再次 PUT 不同值
- **THEN** 响应 200;DB 单条记录字段被更新(不是 INSERT)

#### Scenario: 非法 currency 拒绝

- **WHEN** PUT 提交 `currency="JPY"`(不在枚举内)
- **THEN** 响应 422

#### Scenario: 跨权限访问

- **WHEN** reviewer A 对 reviewer B 的项目访问 `GET/PUT /price-config`
- **THEN** 响应 404

---

### Requirement: 报价列映射规则骨架

系统 SHALL 为每个项目提供 `GET` 与 `PUT /api/projects/{pid}/price-rules` 端点管理 sheet 级的列映射规则(`PriceParsingRule` 表)。**C4 阶段不实现 LLM 调用**;数据由 C5 LLM 填充。C4 提供端点骨架 + CRUD 能力,使 L2 可用 fixture 直接 INSERT 验证 round-trip。

规则形态:

```json
{
  "id": 1,
  "sheet_name": "报价清单",
  "header_row": 2,
  "column_mapping": {
    "code_col": "A",
    "name_col": "B",
    "unit_col": "C",
    "qty_col": "D",
    "unit_price_col": "E",
    "total_price_col": "F",
    "skip_cols": []
  },
  "created_by_llm": true,
  "confirmed": false
}
```

#### Scenario: GET 空列表

- **WHEN** 项目尚无规则,`GET /price-rules`
- **THEN** 响应 200,body = `[]`

#### Scenario: PUT 写入列映射规则

- **WHEN** 提交合法 rule 结构
- **THEN** 响应 200,规则写入 DB;再次 GET 可回读

#### Scenario: PUT 修改 confirmed 标志

- **WHEN** 已有 rule `created_by_llm=true, confirmed=false`,`PUT` 带 `confirmed=true`
- **THEN** 响应 200;字段更新

#### Scenario: column_mapping 非法 JSON 结构

- **WHEN** PUT 提交的 `column_mapping` 缺必需键(如无 `code_col`)
- **THEN** 响应 422

#### Scenario: 跨权限访问

- **WHEN** reviewer A 对 reviewer B 的项目 `GET/PUT /price-rules`
- **THEN** 响应 404

---

### Requirement: 数据模型字段

C4 MUST 通过 alembic `0003_files` 迁移新增 4 张表,字段与索引如下:

**`bidders`**:`id INTEGER PK` / `name VARCHAR(200) NOT NULL` / `project_id INTEGER FK(projects.id) NOT NULL` / `parse_status VARCHAR(32) NOT NULL DEFAULT 'pending'` / `parse_error VARCHAR(500) NULL` / `file_count INTEGER NOT NULL DEFAULT 0` / `identity_info JSONB NULL`(C5 LLM 填) / `created_at / updated_at / deleted_at TIMESTAMPTZ`。索引 `(project_id, deleted_at)`;`UNIQUE(project_id, name) WHERE deleted_at IS NULL`(同项目内活跃记录唯一)。

**`bid_documents`**:`id INTEGER PK` / `bidder_id INTEGER FK(bidders.id) NOT NULL` / `file_name VARCHAR(500) NOT NULL` / `file_path VARCHAR(1000) NOT NULL` / `file_size BIGINT NOT NULL` / `file_type VARCHAR(32) NOT NULL`(`.docx` / `.xlsx` / `.jpg` / ...) / `md5 CHAR(32) NOT NULL` / `file_role VARCHAR(32) NULL`(C5 LLM 填) / `parse_status VARCHAR(32) NOT NULL DEFAULT 'pending'` / `parse_error VARCHAR(500) NULL` / `source_archive VARCHAR(500) NOT NULL`(原压缩包文件名) / `created_at TIMESTAMPTZ`。`UNIQUE(bidder_id, md5)`。

**`project_price_configs`**:`project_id INTEGER PK/FK(projects.id)` / `currency VARCHAR(8) NOT NULL` / `tax_inclusive BOOLEAN NOT NULL` / `unit_scale VARCHAR(16) NOT NULL` / `updated_at TIMESTAMPTZ`。

**`price_parsing_rules`**:`id INTEGER PK` / `project_id INTEGER FK(projects.id) NOT NULL` / `sheet_name VARCHAR(200) NOT NULL` / `header_row INTEGER NOT NULL` / `column_mapping JSONB NOT NULL` / `created_by_llm BOOLEAN NOT NULL DEFAULT FALSE` / `confirmed BOOLEAN NOT NULL DEFAULT FALSE` / `created_at / updated_at TIMESTAMPTZ`。索引 `(project_id, sheet_name)`。

#### Scenario: alembic upgrade head 建表

- **WHEN** 在已 upgrade 到 `0002_projects` 的 DB 执行 `alembic upgrade head`
- **THEN** 4 张表存在,索引/约束按上述清单生成

#### Scenario: alembic downgrade 0002_projects

- **WHEN** `alembic downgrade 0002_projects`
- **THEN** 4 张表按 FK 依赖顺序 DROP

#### Scenario: 同项目活跃投标人 name 唯一

- **WHEN** 两次以相同 `(project_id, name)` 插入且都未软删
- **THEN** 第二次触发唯一约束冲突

#### Scenario: 软删的投标人不占 name 空间

- **WHEN** 项目 P 中投标人"A"软删后,再次创建"A"
- **THEN** INSERT 成功(WHERE deleted_at IS NULL 约束允许)
