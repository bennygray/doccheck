"""L1: 密码哈希与校验 (C2)."""

from __future__ import annotations

from app.services.auth.password import hash_password, verify_password


def test_hash_is_not_plain():
    h = hash_password("admin123")
    assert h != "admin123"
    assert h.startswith("$2") and len(h) >= 50  # bcrypt 格式


def test_hash_is_salted_each_call():
    # 同一明文两次 hash 结果不同(盐不同),但都能被 verify
    h1 = hash_password("admin123")
    h2 = hash_password("admin123")
    assert h1 != h2
    assert verify_password("admin123", h1)
    assert verify_password("admin123", h2)


def test_verify_wrong_password():
    h = hash_password("correct")
    assert not verify_password("wrong", h)


def test_verify_with_malformed_hash_returns_false():
    # 非 bcrypt 格式的哈希不应抛异常,而是返回 False(防御性)
    assert not verify_password("any", "not-a-bcrypt-hash")
