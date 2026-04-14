"""L1: 密码强度 validator (C2)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.auth import ChangePasswordRequest


def _mk(new: str, old: str = "old-pass-123"):
    return ChangePasswordRequest(old_password=old, new_password=new)


def test_valid_password_passes():
    _mk("Abc12345")
    _mk("password1")
    _mk("P4ssw0rd")


def test_too_short_rejected():
    with pytest.raises(ValidationError):
        _mk("Abc123")  # 6 位


def test_no_digit_rejected():
    with pytest.raises(ValidationError):
        _mk("abcdefghi")


def test_no_letter_rejected():
    with pytest.raises(ValidationError):
        _mk("123456789")


def test_empty_old_password_rejected():
    with pytest.raises(ValidationError):
        ChangePasswordRequest(old_password="", new_password="Abc12345")
