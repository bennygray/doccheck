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

系统 SHALL 提供 `GET /api/projects/{id}` 端点,返回单个项目的完整信息。reviewer 请求非自己的项目 MUST 返回 404(不得返回 403,以防止泄露项目存在性)。已软删项目 MUST 返回 404。admin 可访问任何未软删项目。返回体 MUST 包含项目基础字段以及三个**占位字段** `bidders: [] / files: [] / progress: null`,为 C4+ 的扩展预留。

#### Scenario: reviewer 查看自己的项目

- **WHEN** reviewer A 请求 `GET /api/projects/{id}`,该 id 属于 A
- **THEN** 响应 200,返回体含完整基础字段 + `bidders:[] / files:[] / progress:null`

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

项目详情响应 MUST 包含 `bidders / files / progress` 三个占位字段,C3 范围内分别固定为 `[] / [] / null`。列表响应 MUST 包含 `risk_level` 字段,C3 范围内恒为 null。

#### Scenario: 详情响应含占位字段

- **WHEN** reviewer 请求自己项目的详情
- **THEN** 响应 body 同时含 `bidders: []`、`files: []`、`progress: null`

#### Scenario: 列表响应含 risk_level

- **WHEN** 请求列表
- **THEN** 每条 `items[i]` 均含 `risk_level` 字段(值为 null)
