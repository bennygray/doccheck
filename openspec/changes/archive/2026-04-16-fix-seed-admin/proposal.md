## Why

全新数据库启动后 users 表为空，无法登录系统（E2E 验收缺陷 DEF-003）。`config.py` 中已定义 `auth_seed_admin_username` / `auth_seed_admin_password`，但 `main.py` lifespan 中从未调用 seed 逻辑。

## What Changes

- 在 `main.py` lifespan 启动阶段增加 admin seed：检测 users 表是否为空，若空则自动创建管理员账号（`must_change_password=True`，首次登录强制改密）
- seed 逻辑提取为独立函数，可被测试和 `INFRA_DISABLE_SEED=1` 环境变量跳过

## Capabilities

### New Capabilities

- `admin-seed`: 系统启动时自动创建种子管理员账号

### Modified Capabilities

（无修改，仅新增启动逻辑）

## Impact

- **后端代码**: `main.py`（lifespan 增加 seed 调用）、新建 `services/auth/seed.py`
- **数据库**: 无 schema 变更，仅首次启动时 INSERT 一行 users
- **前端**: 无
- **API**: 无
