## ADDED Requirements

### Requirement: 系统启动时自动创建种子管理员

系统启动时（lifespan），若 users 表为空，SHALL 自动创建一个管理员账号，使用 `config.auth_seed_admin_username` / `config.auth_seed_admin_password`，`must_change_password=True`，`role=admin`。

#### Scenario: 全新数据库首次启动
- **WHEN** users 表行数为 0，系统启动
- **THEN** 自动创建 admin 用户，`must_change_password=True`，`role=admin`

#### Scenario: 已有用户时不重复创建
- **WHEN** users 表已有至少 1 行，系统启动
- **THEN** 不创建任何用户

#### Scenario: 环境变量禁用 seed
- **WHEN** `INFRA_DISABLE_SEED=1`，系统启动
- **THEN** 跳过 seed 逻辑，不检查也不创建
