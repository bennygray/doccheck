"""L1: 生命周期 dry-run — 扫描过期文件但不删(C1 强制 dry_run=true)"""

from __future__ import annotations

import os
import time
from pathlib import Path

from app.services.lifecycle.cleanup import scan_expired


def test_scan_expired_marks_old_files_without_deleting(tmp_path: Path) -> None:
    # 旧文件:mtime 设为 40 天前
    old = tmp_path / "old.txt"
    old.write_text("old")
    old_time = time.time() - 40 * 86400
    os.utime(old, (old_time, old_time))

    # 新文件:应该不被标记
    new = tmp_path / "new.txt"
    new.write_text("new")

    expired = scan_expired(tmp_path, age_days=30)

    # 断言:旧文件在清单里
    assert old in expired
    # 断言:新文件不在清单里
    assert new not in expired
    # 断言:文件全部仍在磁盘(dry-run 不删)
    assert old.exists()
    assert new.exists()


def test_scan_expired_missing_root_returns_empty() -> None:
    """root 不存在时返回空清单,不抛异常"""
    result = scan_expired("/definitely/does/not/exist/__xyz__", age_days=1)
    assert result == []
