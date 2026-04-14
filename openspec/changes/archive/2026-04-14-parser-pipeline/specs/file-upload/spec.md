## MODIFIED Requirements

### Requirement: 文件列表与解析状态

系统 SHALL 提供 `GET /api/projects/{pid}/bidders/{bid}/documents` 端点返回该投标人的文件列表,包含树形结构(保留原压缩包内目录层级)、文件类型、解析状态与错误原因(若有)。C5 起 `bid_documents.parse_status` 取值扩展为 9 种:

- **C4 原有 6 种**:`pending` / `extracting` / `extracted` / `skipped` / `failed` / `needs_password`
- **C5 新增 3 种**:`identifying` / `identified` / `identify_failed`

文档级不进入 `priced` 态(报价仅对 bidder 级有意义)。`bid_documents.file_role` 字段由 C5 LLM 调用填充,取值为 9 种角色枚举之一或 NULL(仍在 `identifying` 前)。新增 `role_confidence` 字段(`high` / `low` / `user` / NULL),用于前端标注"待确认"徽章(`low`)或"用户已修正"(`user`)。

#### Scenario: 返回文件列表

- **WHEN** reviewer 请求自己项目投标人的 documents
- **THEN** 响应 200,body 为数组,每条含 `id / file_name / file_path / file_size / file_type / parse_status / parse_error / file_role / role_confidence / md5 / created_at`

#### Scenario: C5 扩展态 identifying 可查

- **WHEN** pipeline 内容提取中,查 documents
- **THEN** 返回条目 `parse_status='identifying'`

#### Scenario: C5 扩展态 identified 可查

- **WHEN** LLM 成功分类后,查 documents
- **THEN** 条目 `parse_status='identified'`;`file_role` 非 NULL

#### Scenario: 解析中状态可查

- **WHEN** 上传后立即查 documents(bidder 仍在 extracting)
- **THEN** 返回可能为空数组或部分已解压条目,取决于协程进度;至少 bidder 详情 `parse_status=extracting`

#### Scenario: 跨权限访问被拒

- **WHEN** reviewer A 查 reviewer B 项目的文件列表
- **THEN** 响应 404

---

### Requirement: 报价列映射规则骨架

系统 SHALL 为每个项目提供 `GET` 与 `PUT /api/projects/{pid}/price-rules` 端点管理 sheet 级的列映射规则(`PriceParsingRule` 表)。C5 起:

- **规则由 C5 pipeline 的 LLM 调用 INSERT**;用户可通过 `PUT /api/projects/{pid}/price-rules/{id}` 修改 column_mapping
- **新增 `status` 字段**:`identifying | confirmed | failed`(C4 仅有 `confirmed` boolean,C5 保留此字段同时新增 `status` 以覆盖识别中/失败态)
- **新增唯一约束**:`UNIQUE(project_id) WHERE status IN ('identifying','confirmed')`(postgres partial unique index);保证项目内同时只有一条"识别中或已确认"的规则,支撑 C5 rule_coordinator 的 DB 原子占位
- **created_by_llm / confirmed 语义延续 C4**:LLM 首次 INSERT `created_by_llm=true, confirmed=true(C5 D4 决策 = 自动确认)`;用户 PUT 修改 column_mapping 后 `created_by_llm=false`

规则完整形态:

```json
{
  "id": 1,
  "project_id": 10,
  "status": "confirmed",
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
  "confirmed": true,
  "created_at": "...",
  "updated_at": "..."
}
```

#### Scenario: GET 空列表

- **WHEN** 项目尚无规则,`GET /price-rules`
- **THEN** 响应 200,body = `[]`

#### Scenario: GET 返 LLM 识别规则

- **WHEN** C5 pipeline 已完成规则识别,`GET /price-rules`
- **THEN** 响应 200,body 含 1 条 `status='confirmed', created_by_llm=true, confirmed=true`

#### Scenario: PUT 写入列映射规则(C4 兼容 round-trip)

- **WHEN** 提交合法 rule 结构(L2 fixture 场景)
- **THEN** 响应 200,规则写入 DB;再次 GET 可回读

#### Scenario: PUT 修改 column_mapping 触发重回填(C5 新增语义)

- **WHEN** 已有 rule 被修改 column_mapping 并提交 PUT
- **THEN** 响应 200;project 内所有 price_items DELETE → 重新回填(详见 parser-pipeline spec "报价列映射修正")

#### Scenario: column_mapping 非法 JSON 结构

- **WHEN** PUT 提交的 `column_mapping` 缺必需键(如无 `code_col`)
- **THEN** 响应 422

#### Scenario: 跨权限访问

- **WHEN** reviewer A 对 reviewer B 的项目 `GET/PUT /price-rules`
- **THEN** 响应 404

#### Scenario: 唯一约束保证项目级仅一条活跃规则

- **WHEN** 并发两次 INSERT `(project_id, status='identifying', ...)` 到 price_parsing_rules
- **THEN** 第二次触发唯一约束冲突(`UNIQUE(project_id) WHERE status IN ('identifying','confirmed')`)

---

### Requirement: 数据模型字段

C4 MUST 通过 alembic `0003_files` 迁移新增 4 张表,字段与索引如下。C5 通过 alembic `0004_parser_pipeline` 迁移:

**C4 `0003_files` 原定义保留**,以下字段 C5 新增约束:

**`bidders.parse_status`**:VARCHAR(32) NOT NULL DEFAULT 'pending';C5 扩展可取值为 13 种(应用层枚举校验,不加 DB CHECK):
`pending / extracting / needs_password / extracted / partial / failed`(C4 6 种)
`identifying / identified / identify_failed / pricing / priced / price_partial / price_failed`(C5 新增 7 种)

**`bid_documents.parse_status`**:VARCHAR(32) NOT NULL DEFAULT 'pending';C5 扩展 3 种:`identifying / identified / identify_failed`。

**`bid_documents.role_confidence`**:C5 通过 0004 迁移新增字段,`VARCHAR(16) NULL`,取值 `high / low / user / NULL`。

**`price_parsing_rules.status`**:C5 通过 0004 迁移新增字段,`VARCHAR(16) NOT NULL DEFAULT 'identifying'`,取值 `identifying / confirmed / failed`。

**`price_parsing_rules` 唯一约束**:C5 通过 0004 迁移新增 `UNIQUE(project_id) WHERE status IN ('identifying','confirmed')`(postgres partial unique index,由 alembic `op.create_index(..., postgresql_where=...)` 生成)。

#### Scenario: alembic upgrade head 建表(C4 baseline)

- **WHEN** 在已 upgrade 到 `0002_projects` 的 DB 执行 `alembic upgrade head`
- **THEN** 4 张 C4 表存在;继续 upgrade 至 `0004_parser_pipeline` 后,C5 扩展字段与约束到位

#### Scenario: alembic downgrade 0003_files 回滚 C5 扩展

- **WHEN** 在 `0004_parser_pipeline` 上执行 `alembic downgrade 0003_files`
- **THEN** `price_parsing_rules.status` 字段 DROP;唯一约束 DROP;`bid_documents.role_confidence` 字段 DROP;C4 行为恢复

#### Scenario: 同项目活跃投标人 name 唯一(C4 原约束)

- **WHEN** 两次以相同 `(project_id, name)` 插入且都未软删
- **THEN** 第二次触发唯一约束冲突

#### Scenario: parse_status 应用层枚举校验

- **WHEN** 尝试 UPDATE `bidder.parse_status = 'unknown_state'`
- **THEN** ORM schema 层面拒绝(Pydantic/SQLAlchemy 枚举校验抛错);DB 层允许任意 VARCHAR(32) 字符串(无 DB CHECK,应用保证)
