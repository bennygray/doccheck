"""密码哈希与校验 — passlib + bcrypt (C2 auth)

- hash_password:生成 bcrypt 哈希,每次调用盐值不同,结果不可逆
- verify_password:比对明文与哈希,安全时间常数比较

passlib CryptContext 的 deprecated="auto" 让后续升级算法时可识别旧哈希,
本 change 不启用升级路径,留给生产化阶段。
"""

from __future__ import annotations

from passlib.context import CryptContext

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    """对明文密码生成 bcrypt 哈希。同一明文多次调用得到不同结果(盐不同)。"""
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """校验明文与哈希是否匹配。非 bcrypt 格式的哈希返回 False,不抛异常。"""
    try:
        return _pwd_context.verify(plain, hashed)
    except ValueError:
        # 哈希格式非法(比如测试误传明文过来)
        return False
