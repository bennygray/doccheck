"""Auth 服务模块 (C2)

- password: bcrypt 哈希与校验
- jwt: JWT 编解码,载荷含 pwd_v 用于改密即时失效
- lockout: 登录失败计数与账户锁定状态机
"""
