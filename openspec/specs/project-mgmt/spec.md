# project-mgmt Specification

## Purpose

提供检测项目的完整生命周期管理:创建、查询(列表/详情,含分页/筛选/搜索)、软删除,并施加基于角色的数据隔离(reviewer 仅见自己;admin 见全部)。本 capability 是 M2 核心流程的起点,后续 C4(投标人/文件)、C5(解析)、C6+(检测)均挂在 `Project` 实体上。

## Requirements

### Requirement: 创建项目

系统 SHALL 提供 `POST /api/projects/` 端点,允许已登录用户创建检测项目。请求体必须包含 `name`(必填,≤100 字符);可选 `bid_code`(≤50 字符)、`max_price`(≥0 且最多 2 位小数)、`description`(≤500 字符)。服务器 MUST 将当前登录用户设为 `owner_id`,将 `status` 初始化为 `draft`,并返回完整项目对象(含自动生成的 `id / created_at`)。

#### Scenario: 合法数据创建成功

- **WHEN** reviewer 以有效 JWT 发送 `POST /api/projects/` 且请求体包含合法 `name` 与可选字段
- **THEN** 响应状态码 201,返回体含 `id / name / status="draft" / owner_id=<当前用户> / created_at / deleted_at=null / risk_level=null`

#### Scenario: 缺 name 拒绝

- **WHEN** 请求体不含 `name` 字段或 `name` 为空字符串
- **THEN** 响应 422,body 含字段级校验错误

#### Scenario: name 超长拒绝

- **WHEN** 请求体 `name` 超过 100 字符
- **THEN** 响应 422

#### Scenario: max_price 负数拒绝

- **WHEN** 请求体 `max_price = -1`
- **THEN** 响应 422

#### Scenario: 同用户允许同名

- **WHEN** 同一 reviewer 连续两次提交相同 `name` 的创建请求
- **THEN** 两次均返回 201,DB 中生成两条独立记录(不同 `id`)

#### Scenario: 未登录拒绝

- **WHEN** 未携带 Authorization 头或 token 无效
- **THEN** 响应 401

---

### Requirement: 项目列表(分页/筛选/搜索/权限过滤)

系统 SHALL 提供 `GET /api/projects/` 端点,返回已登录用户**可见**的项目列表。reviewer 仅可见自己的项目(`owner_id == current_user.id`);admin 可见所有项目。响应 MUST 排除 `deleted_at IS NOT NULL` 的软删记录。端点 MUST 支持分页参数 `page`(默认 1)/ `size`(默认 12,上限 100);筛选参数 `status` / `risk_level`;搜索参数 `search`(对 `name` 与 `bid_code` 的模糊匹配,大小写不敏感)。默认排序为 `created_at DESC`。返回体结构为 `{"items": [...], "total": <int>, "page": <int>, "size": <int>}`。

#### Scenario: reviewer 只见自己的项目

- **WHEN** reviewer A 请求 `GET /api/projects/`,数据库中存在 A 的 2 条和 B 的 3 条记录(均未软删)
- **THEN** 响应 200,`items` 长度为 2,`total=2`,均为 A 的项目

#### Scenario: admin 见全部项目

- **WHEN** admin 请求 `GET /api/projects/`,数据库中存在 A 的 2 条和 B 的 3 条记录(均未软删)
- **THEN** 响应 200,`items` 总计 5 条

#### Scenario: 软删记录默认不出现

- **WHEN** reviewer 请求列表,其 3 条项目中 1 条 `deleted_at` 已置值
- **THEN** `items` 长度为 2,`total=2`

#### Scenario: 按 status 筛选

- **WHEN** 请求 `GET /api/projects/?status=draft`
- **THEN** 仅返回 `status='draft'` 的记录

#### Scenario: 按关键词搜索匹配 name

- **WHEN** 请求 `GET /api/projects/?search=高速` 且存在 `name="京沪高速投标"`
- **THEN** 该记录出现在 `items` 中

#### Scenario: 按关键词搜索匹配 bid_code

- **WHEN** 请求 `GET /api/projects/?search=BID-2026` 且存在 `bid_code="BID-2026-001"`
- **THEN** 该记录出现在 `items` 中

#### Scenario: 分页参数生效

- **WHEN** 有 15 条可见记录,请求 `GET /api/projects/?page=2&size=12`
- **THEN** `items` 长度为 3,`total=15`,`page=2`,`size=12`

#### Scenario: size 上限保护(实现锁定为拒绝越界)

- **WHEN** 请求 `GET /api/projects/?size=500`
- **THEN** 响应 422(由 FastAPI Query `le=100` 校验)

#### Scenario: 未登录拒绝

- **WHEN** 未携带 Authorization 头
- **THEN** 响应 401

---

### Requirement: 项目详情

系统 SHALL 提供 `GET /api/projects/{id}` 端点,返回单个项目的完整信息。reviewer 请求非自己的项目 MUST 返回 404(不得返回 403,以防止泄露项目存在性)。已软删项目 MUST 返回 404。admin 可访问任何未软删项目。返回体 MUST 包含项目基础字段以及四个**占位/扩展字段**:`bidders: [] / files: [] / progress / analysis`;`progress` 结构见 "为 C4+ 预留的占位字段" Requirement;`analysis` 结构由 **C6** 扩展(C6 前恒为 null):

```json
"analysis": null  // C6 前
// C6 后:
"analysis": {
  "current_version": int | null,  // 最新 AgentTask.version;未启动过检测为 null
  "project_status": "draft|parsing|ready|analyzing|completed",
  "started_at": iso8601 | null,  // 最新一轮 MIN(started_at) 或 AgentTask.created_at
  "agent_task_count": int,  // 最新 version 下 AgentTask 总数(未启动为 0)
  "latest_report": {                 // 若 AnalysisReport 行存在
    "version": int,
    "total_score": float,
    "risk_level": "high|medium|low",
    "created_at": iso8601
  } | null
}
```

#### Scenario: reviewer 查看自己的项目

- **WHEN** reviewer A 请求 `GET /api/projects/{id}`,该 id 属于 A
- **THEN** 响应 200,返回体含完整基础字段 + `bidders:[] / files:[] / progress / analysis`

#### Scenario: reviewer 查看他人项目返回 404

- **WHEN** reviewer A 请求 `GET /api/projects/{id}`,该 id 属于 B
- **THEN** 响应 404

#### Scenario: admin 查看任意项目

- **WHEN** admin 请求 `GET /api/projects/{id}`,id 属于任意 reviewer
- **THEN** 响应 200

#### Scenario: 已软删项目返回 404

- **WHEN** 请求已软删项目的详情
- **THEN** 响应 404

#### Scenario: 不存在 id 返回 404

- **WHEN** 请求不存在的 id
- **THEN** 响应 404

#### Scenario: C6 前 analysis 字段为 null

- **WHEN** 项目从未启动过检测(agent_tasks 无对应行)
- **THEN** 响应 `analysis: null`

#### Scenario: C6 后 analysis 字段含 current_version 与 latest_report

- **WHEN** 项目已完成一轮检测(AnalysisReport version=1 存在)
- **THEN** 响应 `analysis.current_version=1, analysis.project_status='completed', analysis.latest_report.total_score` 非 null

---

### Requirement: 软删除项目

系统 SHALL 提供 `DELETE /api/projects/{id}` 端点,执行**软删除**(置 `deleted_at = now()`)。reviewer 仅可删自己的项目(删他人返回 404);admin 可删任意项目。`status == 'analyzing'` 的项目 MUST 返回 409 并拒绝删除。已软删项目再次删除 MUST 返回 404。删除成功返回 204(无 body)。

#### Scenario: reviewer 软删自己的项目

- **WHEN** reviewer A 对自己的项目发送 `DELETE /api/projects/{id}`
- **THEN** 响应 204;DB 中该记录 `deleted_at` 已置值;后续 `GET /api/projects/` 中不再出现该记录

#### Scenario: reviewer 删他人项目返回 404

- **WHEN** reviewer A 对 B 的项目发送 DELETE
- **THEN** 响应 404;DB 中该记录 `deleted_at` 保持 NULL

#### Scenario: 检测中项目拒删

- **WHEN** 项目 `status='analyzing'`,对其发送 DELETE
- **THEN** 响应 409,body 含可读错误说明;`deleted_at` 保持 NULL

#### Scenario: admin 可删任意项目

- **WHEN** admin 对任一 reviewer 的项目发送 DELETE
- **THEN** 响应 204

#### Scenario: 重复删除返回 404

- **WHEN** 对已软删项目再次发送 DELETE
- **THEN** 响应 404(已软删即视为不存在)

---

### Requirement: 角色与鉴权

系统 SHALL 使所有 `/api/projects/*` 端点强制 `Depends(get_current_user)`。任何端点 MUST NOT 对未认证请求返回业务数据。角色区分仅影响**可见数据范围**,不影响端点可达性——reviewer 与 admin 均可调用全部四个端点,差别在查询过滤。

#### Scenario: 过期 token 访问任一端点

- **WHEN** 以过期 JWT 调用 `/api/projects/` 任一端点
- **THEN** 响应 401

#### Scenario: 改密后旧 token 访问

- **WHEN** 以改密前签发的 JWT(`pwd_v` 不匹配 DB)调用任一端点
- **THEN** 响应 401(由 C2 pwd_v 中间件保证)

#### Scenario: 正常 reviewer 可调用全部四个端点

- **WHEN** reviewer 以有效 JWT 分别调用 POST / GET list / GET detail(自己的) / DELETE(自己的)
- **THEN** 均不返回 401/403

---

### Requirement: 数据模型字段

`projects` 表 MUST 包含以下字段:`id INTEGER PK`(BIGSERIAL,实现选用 Integer)、`name VARCHAR(100) NOT NULL`、`bid_code VARCHAR(50) NULL`、`max_price NUMERIC(18,2) NULL`、`description VARCHAR(500) NULL`、`status VARCHAR(32) NOT NULL DEFAULT 'draft'`、`risk_level VARCHAR(16) NULL`、`owner_id` FK→ `users.id` NOT NULL、`created_at TIMESTAMPTZ NOT NULL DEFAULT now()`、`updated_at TIMESTAMPTZ NOT NULL DEFAULT now()`、`deleted_at TIMESTAMPTZ NULL`。MUST 建立联合索引 `(owner_id, deleted_at, created_at)` 支持 reviewer 列表主路径。

#### Scenario: alembic upgrade head 建表

- **WHEN** 在干净数据库执行 `alembic upgrade head`
- **THEN** `projects` 表存在,所有列与默认值按上述清单生成

#### Scenario: alembic downgrade 回滚

- **WHEN** 在已 upgrade 到 `0002_projects` 的数据库执行 `alembic downgrade 0001_users`
- **THEN** `projects` 表被 DROP

#### Scenario: 索引存在支持查询

- **WHEN** 查询 `SELECT ... FROM projects WHERE owner_id=? AND deleted_at IS NULL ORDER BY created_at DESC LIMIT 12`
- **THEN** PostgreSQL 执行计划使用 `(owner_id, deleted_at, created_at)` 索引(L2 可选验证,非强制)

---

### Requirement: 为 C4+ 预留的占位字段

项目详情响应 MUST 包含 `bidders / files / progress / analysis` 四个字段。C5 起扩展 `progress` 字段的结构以覆盖解析流水线的阶段计数;**C6 起** `analysis` 字段由 null 扩展为对象(见 "项目详情" Requirement):

- `bidders` 字段返回真实投标人摘要列表(每项含 `id / name / parse_status / file_count`),来自 `bidders` 表的未软删记录(C4 语义保持)
- `files` 字段返回该项目下所有投标人的 `bid_documents` 扁平列表摘要(每项含 `id / bidder_id / file_name / file_type / parse_status / file_role / role_confidence`);**`file_role / role_confidence` 为 C5 新增字段**(C4 阶段恒 NULL,C5 由 LLM 填充)
- `progress` 字段返回项目级汇总,**C5 扩展为**:
  ```json
  {
    "total_bidders": int,
    "pending_count": int,
    "extracting_count": int,
    "extracted_count": int,
    "identifying_count": int,
    "identified_count": int,
    "pricing_count": int,
    "priced_count": int,
    "failed_count": int,
    "needs_password_count": int,
    "partial_count": int
  }
  ```
  `failed_count` 聚合所有失败态(`failed / identify_failed / price_failed`);`partial_count` 聚合 `partial / price_partial`。项目无投标人时所有计数为 0。
- `analysis` 字段返回项目检测汇总,**C6 扩展为** `null | {current_version, project_status, started_at, agent_task_count, latest_report}`(见 "项目详情" Requirement)

**列表响应** `GET /api/projects/`:C6 起 `risk_level` 字段从恒 null → 改为优先取 AnalysisReport.risk_level(最新 version);无 AnalysisReport 行 → 保持 null。

#### Scenario: 详情返回真实 bidders 摘要

- **WHEN** reviewer `GET /api/projects/{id}`,该项目含 2 个 bidder
- **THEN** 响应 200,body 中 `bidders` 为 2 项数组,每项含 `id / name / parse_status / file_count`

#### Scenario: 详情返回扁平 files 列表含 file_role

- **WHEN** reviewer `GET /api/projects/{id}`,该项目含 2 个 bidder 每个有 3 个 bid_document,其中首位 bidder 已 identified
- **THEN** 响应 body 中 `files` 为 6 项数组,每项含 `id / bidder_id / file_name / file_type / parse_status / file_role / role_confidence`;已 identified 的 bidder 的文档 `file_role` 非 NULL,其他文档 `file_role` 为 NULL

#### Scenario: progress 含 C5 新增计数

- **WHEN** 项目含 3 个 bidder(状态分别为 extracted / identifying / priced),1 个 bidder 为 price_partial
- **THEN** `progress` 的相应字段:`extracted_count=1, identifying_count=1, priced_count=1, partial_count=1`;`total_bidders=4`

#### Scenario: 空项目 progress 全零

- **WHEN** 项目尚无投标人
- **THEN** `progress` 各计数字段均为 0;`total_bidders=0`

#### Scenario: C6 analysis 字段扩展(未检测)

- **WHEN** GET 项目详情,该项目在 C6 起但未启动过检测
- **THEN** response.analysis = null

#### Scenario: C6 analysis 字段扩展(已检测)

- **WHEN** GET 项目详情,该项目已完成一轮检测
- **THEN** response.analysis 为对象;analysis.latest_report 非 null

#### Scenario: 列表 risk_level 取自 AnalysisReport

- **WHEN** GET 项目列表,项目 P1 已完成一轮 risk_level=high 的检测
- **THEN** 列表响应中 P1 的 risk_level='high'(非 null)

#### Scenario: 列表 risk_level 未检测仍 null

- **WHEN** GET 项目列表,项目 P2 从未检测
- **THEN** P2 risk_level=null
