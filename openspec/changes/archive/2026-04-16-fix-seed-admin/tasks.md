## 1. 核心实现

- [x] 1.1 [impl] 新建 `backend/app/services/auth/seed.py`，实现 `ensure_seed_admin()` 函数：检查 users 表是否为空，若空则创建 seed admin
- [x] 1.2 [impl] 在 `backend/app/main.py` lifespan 中调用 `ensure_seed_admin()`，受 `INFRA_DISABLE_SEED=1` 环境变量控制

## 2. 单元测试

- [x] 2.1 [L1] 测试 `ensure_seed_admin`：users 表为空 → 创建 admin 用户
- [x] 2.2 [L1] 测试 `ensure_seed_admin`：users 表已有用户 → 不创建
- [x] 2.3 [L1] 测试创建的用户属性：must_change_password=True, role=admin

## 3. 全量测试

- [x] 3.1 跑 [L1][L2] 全部测试，全绿 (1037 passed in 107.72s)
