"""L1: JWT 编解码 (C2)."""

from __future__ import annotations

import pytest

from app.services.auth.jwt import TokenInvalid, create_access_token, decode_access_token


def _mk(**kw) -> str:
    defaults = dict(user_id=1, role="admin", pwd_v=1_700_000_000, username="admin")
    defaults.update(kw)
    return create_access_token(**defaults)


def test_roundtrip():
    t = _mk()
    claims = decode_access_token(t)
    assert claims["sub"] == "1"
    assert claims["role"] == "admin"
    assert claims["pwd_v"] == 1_700_000_000
    assert claims["username"] == "admin"
    assert "exp" in claims and "iat" in claims


def test_expired_token_rejected():
    # 负过期时间 → 签发即过期
    t = _mk(expires_minutes=-1)
    with pytest.raises(TokenInvalid):
        decode_access_token(t)


def test_tampered_signature_rejected():
    t = _mk()
    # 改最后一个字符,破坏签名
    tampered = t[:-1] + ("A" if t[-1] != "A" else "B")
    with pytest.raises(TokenInvalid):
        decode_access_token(tampered)


def test_malformed_token_rejected():
    with pytest.raises(TokenInvalid):
        decode_access_token("not.a.jwt")
    with pytest.raises(TokenInvalid):
        decode_access_token("")


def test_pwd_v_carried_correctly():
    t = _mk(pwd_v=9_999_999_999)
    claims = decode_access_token(t)
    assert claims["pwd_v"] == 9_999_999_999
