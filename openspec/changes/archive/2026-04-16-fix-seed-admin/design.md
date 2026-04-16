## Context

`config.py` 已定义 `auth_seed_admin_username` / `auth_seed_admin_password`（C2 auth 遗留），但启动时没有调用 seed。全新部署必须手动 SQL 插入用户才能登录。

## Goals / Non-Goals

**Goals:**
- 首次启动自动创建 seed admin（`must_change_password=True`）
- 已有用户时不重复创建（幂等）
- 可通过 `INFRA_DISABLE_SEED=1` 跳过（L2 测试用）

**Non-Goals:**
- 不做批量用户导入
- 不做密码强度校验（seed 密码是临时的，首次登录强制改）

## Decisions

### D1: 提取为 `services/auth/seed.py` 独立函数

不直接在 lifespan 写逻辑，提取为 `ensure_seed_admin()` 方便单元测试。

### D2: 检查 users 表行数而非查特定用户名

`SELECT count(*) FROM users` == 0 时才 seed。这样即使 admin 用户名被改过或删除后重建了其他用户，也不会重复插入。

## Risks / Trade-offs

- **[幂等]** 只在 users 表完全为空时 seed → 安全，不会覆盖已有用户
- **[生产安全]** seed 密码必须通过 env 覆盖，否则是公开默认值 → config 注释已说明
