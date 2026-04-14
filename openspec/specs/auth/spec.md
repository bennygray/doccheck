# auth Specification

## Purpose
TBD - created by archiving change auth. Update Purpose after archive.
## Requirements

### Requirement: 用户登录与 JWT 签发
系统 SHALL 提供 `POST /api/auth/login` 端点,使用用户名+密码验证身份,成功时签发包含 `user_id`、`role`、`pwd_v`(密码版本)、`exp`(过期时间)的 JWT。

#### Scenario: 正确凭证登录成功
- **WHEN** 客户端以 `{username, password}` POST 到 `/api/auth/login`,凭证匹配 DB 中 `is_active=true` 用户
- **THEN** 响应 SHALL 返回 HTTP 200,body 含 `{access_token, token_type: "bearer", user: {id, username, role, must_change_password, is_active}}`,`access_token` 可被 `decode_access_token` 解出上述 claims

#### Scenario: 错误密码返回通用错误不泄露细节
- **WHEN** 用户名存在但密码错误,或用户名不存在
- **THEN** 响应 SHALL 返回 HTTP 401,body 含通用错误文案(如 "用户名或密码错误"),响应体 SHALL NOT 揭示具体是用户名还是密码错误

#### Scenario: 用户名不存在不累计失败计数
- **WHEN** 以不存在的用户名登录任意多次
- **THEN** DB 中不得为任何用户累计 `login_fail_count`,且 SHALL NOT 因此触发任何真实用户的锁定

#### Scenario: 被禁用用户登录被拒
- **WHEN** 正确凭证但 DB 中 `is_active=false`
- **THEN** 响应 SHALL 返回 HTTP 403

#### Scenario: 密码在 DB 中以 bcrypt 哈希存储
- **WHEN** 查询 `users` 表任意记录
- **THEN** `password_hash` 字段 SHALL 以 `$2b$` 或等价 passlib bcrypt 前缀开头,SHALL NOT 包含明文密码

---

### Requirement: 登录失败计数与账户锁定
系统 SHALL 在连续 `AUTH_LOCKOUT_THRESHOLD`(默认 5)次密码错误后,将账户锁定 `AUTH_LOCKOUT_TTL_MINUTES`(默认 15)分钟,锁定期间登录返回 HTTP 429。

#### Scenario: 连续 5 次错密触发锁定
- **WHEN** 对同一存在用户连续 5 次提交错误密码
- **THEN** 第 6 次对该用户的登录请求 SHALL 返回 HTTP 429,响应 body SHALL 含剩余锁定时长字段(单位秒或分钟)

#### Scenario: 成功登录清零失败计数
- **WHEN** 用户在未达阈值前使用正确密码登录成功
- **THEN** DB 中该用户 `login_fail_count` SHALL 被置为 0,`locked_until` SHALL 被置为 NULL

#### Scenario: 锁定 TTL 过后自动解锁
- **WHEN** `locked_until` 时间戳已过去
- **THEN** 用户下一次登录 SHALL 不再被 429 拦截,按正常密码校验流程处理

#### Scenario: 并发请求不破坏计数一致性
- **WHEN** 两个并发请求对同一用户同时提交错误密码
- **THEN** DB 中 `login_fail_count` 最终值 SHALL 等于实际失败次数(通过 `SELECT FOR UPDATE` 原子化,不丢更新)

---

### Requirement: JWT 校验与当前用户依赖
系统 SHALL 提供 FastAPI 依赖 `get_current_user`,从请求 `Authorization: Bearer <token>` 头解析并校验 JWT;校验包括签名、过期时间,以及 `pwd_v` claim 与 DB `password_changed_at` 一致性。

#### Scenario: 无 token 访问受保护端点
- **WHEN** 客户端不带 `Authorization` 头请求挂有 `Depends(get_current_user)` 的端点
- **THEN** 响应 SHALL 返回 HTTP 401

#### Scenario: 过期 token 访问受保护端点
- **WHEN** `Authorization` 头携带 `exp` 已过期的 JWT
- **THEN** 响应 SHALL 返回 HTTP 401

#### Scenario: 签名无效 token 访问受保护端点
- **WHEN** `Authorization` 头携带签名被篡改或使用其它 secret 签发的 JWT
- **THEN** 响应 SHALL 返回 HTTP 401

#### Scenario: 有效 token 访问受保护端点
- **WHEN** `Authorization` 头携带未过期、签名正确、`pwd_v` 与 DB `password_changed_at` 匹配的 JWT
- **THEN** 响应 SHALL 进入业务处理逻辑,不被 auth 层拦截

---

### Requirement: 角色鉴权
系统 SHALL 提供 `require_role(role)` 依赖,在有效 JWT 基础上进一步校验用户 `role` 与 `is_active`;角色不符或用户已禁用时返回 HTTP 403。

#### Scenario: 非管理员访问 admin 端点被拒
- **WHEN** 使用 `role="reviewer"` 用户的有效 JWT 访问挂有 `Depends(require_role("admin"))` 的端点
- **THEN** 响应 SHALL 返回 HTTP 403

#### Scenario: 管理员访问 admin 端点
- **WHEN** 使用 `role="admin"` 用户的有效 JWT 访问挂有 `Depends(require_role("admin"))` 的端点
- **THEN** 响应 SHALL 进入业务逻辑,返回业务定义的响应码(非 401/403)

#### Scenario: 已禁用用户携带历史 token
- **WHEN** 用户在持有未过期 JWT 期间被标记 `is_active=false`,再次以该 token 访问受保护端点
- **THEN** 响应 SHALL 返回 HTTP 403

---

### Requirement: 初始管理员 seed
系统 SHALL 在数据库首次迁移时创建默认管理员用户(用户名默认 `admin`,密码默认 `admin123`,`role=admin`,`must_change_password=true`),并保证多次执行迁移幂等不重复创建。

#### Scenario: 首次迁移创建默认 admin
- **WHEN** 在空数据库执行 `alembic upgrade head`
- **THEN** `users` 表 SHALL 存在一行 `username='admin'`、`role='admin'`、`must_change_password=true`、`password_hash` 非空且可被 `verify_password('admin123', ...)` 验证为 True

#### Scenario: 重复迁移不重复插入
- **WHEN** 数据库已存在 `username='admin'` 的用户,再次执行创建 admin 的迁移逻辑(例如 downgrade 后 upgrade,或并发启动多实例)
- **THEN** `users` 表仍 SHALL 只有一条 `username='admin'` 记录,且已有用户的字段 SHALL NOT 被覆盖

#### Scenario: 配置覆盖默认用户名/密码
- **WHEN** 部署时设置 `AUTH_SEED_ADMIN_USERNAME=root`、`AUTH_SEED_ADMIN_PASSWORD=Abc12345` 后执行首次迁移
- **THEN** 创建出的默认管理员用户名 SHALL 为 `root`,密码可被 `verify_password('Abc12345', ...)` 验证为 True

---

### Requirement: 修改密码与旧 token 立即失效
系统 SHALL 提供 `POST /api/auth/change-password` 端点,校验旧密码正确后写入新密码哈希并更新 `password_changed_at`;更新后使用旧 JWT(旧 `pwd_v`)访问任何受保护端点 SHALL 立即返回 401。

#### Scenario: 改密成功更新 must_change_password 与时间戳
- **WHEN** 已登录用户以正确 `old_password` 与合规 `new_password` 调用 `/api/auth/change-password`
- **THEN** 响应 SHALL 返回 HTTP 200;DB 中该用户 `must_change_password` SHALL 为 false,`password_hash` SHALL 被更新,`password_changed_at` SHALL 被更新为改密时刻

#### Scenario: 改密后旧 token 立即失效
- **WHEN** 用户改密完成后,用改密前获得的 JWT 调用任何 `Depends(get_current_user)` 的端点
- **THEN** 响应 SHALL 返回 HTTP 401,拒绝原因与"过期 token"一致(不暴露 `pwd_v` 机制细节)

#### Scenario: 旧密码错误拒绝改密
- **WHEN** `old_password` 与 DB 当前 `password_hash` 不匹配
- **THEN** 响应 SHALL 返回 HTTP 400,DB SHALL NOT 发生任何变更

#### Scenario: 新密码不满足强度规则
- **WHEN** `new_password` 少于 8 位,或不同时包含字母与数字
- **THEN** 响应 SHALL 返回 HTTP 422,DB SHALL NOT 发生任何变更

#### Scenario: 获取当前用户
- **WHEN** 已登录用户调用 `GET /api/auth/me`
- **THEN** 响应 SHALL 返回 HTTP 200,body 至少含 `{id, username, role, must_change_password, is_active}`

---

### Requirement: 前端路由守卫与强制改密
系统 SHALL 提供前端 `<ProtectedRoute>` 组件保护所有业务路由,并在用户 `must_change_password=true` 时强制跳转到 `/change-password`。

#### Scenario: 未登录访问受保护路由
- **WHEN** 浏览器未在 `localStorage` 持有有效 `auth:token`,访问任意非 `/login` 非 `/change-password` 路由
- **THEN** 页面 SHALL 重定向至 `/login`

#### Scenario: 首次登录强制改密
- **WHEN** 用户登录后 `must_change_password=true`,尝试导航到 `/projects` 或其他受保护路由
- **THEN** 页面 SHALL 被重定向至 `/change-password`,且在改密成功前不允许访问其他业务路由

#### Scenario: 401 响应触发重定向并记录 pendingPath
- **WHEN** 任一 API 调用返回 401
- **THEN** 前端 SHALL 将当前 `location.pathname` 写入 `localStorage['auth:pendingPath']`,清空 auth context,重定向 `/login`

#### Scenario: 登录后恢复 pendingPath
- **WHEN** 用户完成登录,且 `localStorage['auth:pendingPath']` 有值
- **THEN** 前端 SHALL 导航至该 pendingPath(而非默认 `/projects`),并在跳转后清除该 localStorage 项

---

### Requirement: 前端角色守卫
系统 SHALL 提供前端 `<RoleGuard role>` 组件,保护仅特定角色可访问的路由子树。

#### Scenario: 非管理员访问 admin 路由
- **WHEN** `role="reviewer"` 用户尝试访问 `/admin/*` 路由(被 `<RoleGuard role="admin">` 包裹)
- **THEN** 页面 SHALL 重定向至 `/projects`,admin 子树组件 SHALL NOT 被渲染

#### Scenario: 管理员访问 admin 路由
- **WHEN** `role="admin"` 用户访问 `/admin/*` 路由
- **THEN** admin 子树组件 SHALL 正常渲染
