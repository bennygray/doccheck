"""L1 单元 - extract.safety 的路径/预算校验 (C4 §10.1)。

对齐 spec.md "压缩包安全解压" Requirement 的 zip-slip 与 zip-bomb 防护场景。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.extract.safety import (
    MAX_ENTRY_COUNT,
    MAX_NESTING_DEPTH,
    MAX_TOTAL_EXTRACTED_BYTES,
    check_count_budget,
    check_nesting_depth,
    check_safe_entry,
    check_size_budget,
)


# ---------------------------------------------------------- check_safe_entry

@pytest.fixture
def root(tmp_path: Path) -> Path:
    extract_root = tmp_path / "extracted"
    extract_root.mkdir()
    return extract_root


class TestSafeEntry:
    def test_normal_relative_path_ok(self, root: Path) -> None:
        ok, _ = check_safe_entry("dir/file.docx", root)
        assert ok

    def test_dotdot_traversal_rejected(self, root: Path) -> None:
        ok, reason = check_safe_entry("../../etc/passwd", root)
        assert not ok
        assert "不安全" in reason

    def test_absolute_unix_rejected(self, root: Path) -> None:
        ok, reason = check_safe_entry("/etc/passwd", root)
        assert not ok
        assert "绝对" in reason

    def test_absolute_windows_rejected(self, root: Path) -> None:
        ok, reason = check_safe_entry("C:\\Windows\\System32\\evil.exe", root)
        assert not ok
        assert "绝对" in reason

    def test_backslash_root_rejected(self, root: Path) -> None:
        ok, reason = check_safe_entry("\\evil", root)
        assert not ok
        assert "绝对" in reason

    def test_empty_rejected(self, root: Path) -> None:
        ok, reason = check_safe_entry("", root)
        assert not ok
        assert "空" in reason

    def test_blank_rejected(self, root: Path) -> None:
        ok, _ = check_safe_entry("   ", root)
        assert not ok

    def test_normalized_inner_traversal_caught(self, root: Path) -> None:
        # a/b/../../../etc/passwd → 实际穿出根
        ok, _ = check_safe_entry("a/b/../../../etc/passwd", root)
        assert not ok

    def test_inner_dotdot_within_root_ok(self, root: Path) -> None:
        # a/../b 经 normpath 后 = b,仍在 root 内
        ok, _ = check_safe_entry("a/../b/file.txt", root)
        assert ok


# ---------------------------------------------------------- 三道预算

class TestBudgets:
    def test_size_budget_ok(self) -> None:
        ok, _ = check_size_budget(MAX_TOTAL_EXTRACTED_BYTES - 1)
        assert ok

    def test_size_budget_exceeded(self) -> None:
        ok, reason = check_size_budget(MAX_TOTAL_EXTRACTED_BYTES + 1)
        assert not ok
        assert "2GB" in reason or "过大" in reason

    def test_count_budget_ok(self) -> None:
        ok, _ = check_count_budget(MAX_ENTRY_COUNT)
        assert ok

    def test_count_budget_exceeded(self) -> None:
        ok, reason = check_count_budget(MAX_ENTRY_COUNT + 1)
        assert not ok
        assert "1000" in reason

    def test_nesting_within_limit(self) -> None:
        for d in range(1, MAX_NESTING_DEPTH + 1):
            ok, _ = check_nesting_depth(d)
            assert ok

    def test_nesting_over_limit(self) -> None:
        ok, reason = check_nesting_depth(MAX_NESTING_DEPTH + 1)
        assert not ok
        assert "嵌套" in reason
