"""L1 单元 - upload.validator 三道校验 (C4 §10.3)。

覆盖 spec.md "文件上传(创建+追加)" 的扩展名/魔数/大小三道场景。
"""

from __future__ import annotations

import pytest

from app.services.upload.validator import (
    MAX_ARCHIVE_BYTES,
    FileTooLarge,
    UnsupportedMediaType,
    validate_archive_file,
)


# 真实压缩包魔数(各取标准前缀)
_ZIP_HEAD = b"PK\x03\x04" + b"\x00" * 28
_7Z_HEAD = b"\x37\x7a\xbc\xaf\x27\x1c" + b"\x00" * 26
_RAR_HEAD = b"Rar!\x1a\x07\x00" + b"\x00" * 25


class TestExtensionAllowlist:
    def test_zip_ok(self) -> None:
        assert (
            validate_archive_file(filename="a.zip", head_bytes=_ZIP_HEAD, total_size=1024)
            == ".zip"
        )

    def test_7z_ok(self) -> None:
        assert (
            validate_archive_file(filename="b.7z", head_bytes=_7Z_HEAD, total_size=1024)
            == ".7z"
        )

    def test_rar_ok(self) -> None:
        assert (
            validate_archive_file(filename="c.rar", head_bytes=_RAR_HEAD, total_size=1024)
            == ".rar"
        )

    def test_no_extension_rejected(self) -> None:
        with pytest.raises(UnsupportedMediaType, match="无扩展名"):
            validate_archive_file(filename="noext", head_bytes=_ZIP_HEAD, total_size=1024)

    def test_exe_extension_rejected(self) -> None:
        with pytest.raises(UnsupportedMediaType, match="不在白名单"):
            validate_archive_file(
                filename="virus.exe", head_bytes=b"MZ" + b"\x00" * 30, total_size=1024
            )

    def test_uppercase_extension_normalized(self) -> None:
        assert (
            validate_archive_file(filename="A.ZIP", head_bytes=_ZIP_HEAD, total_size=1024)
            == ".zip"
        )


class TestMagicNumberMatch:
    def test_zip_ext_with_exe_bytes_rejected(self) -> None:
        # .zip 改名的 .exe / 文本文件 → 魔数失败
        with pytest.raises(UnsupportedMediaType, match="魔数"):
            validate_archive_file(
                filename="fake.zip",
                head_bytes=b"MZ" + b"\x00" * 30,
                total_size=1024,
            )

    def test_zip_ext_with_text_bytes_rejected(self) -> None:
        with pytest.raises(UnsupportedMediaType, match="魔数"):
            validate_archive_file(
                filename="fake.zip",
                head_bytes=b"hello world\n" + b"\x00" * 20,
                total_size=1024,
            )


class TestSizeBudget:
    def test_just_under_limit_ok(self) -> None:
        assert validate_archive_file(
            filename="ok.zip", head_bytes=_ZIP_HEAD, total_size=MAX_ARCHIVE_BYTES
        ) == ".zip"

    def test_over_limit_rejected(self) -> None:
        with pytest.raises(FileTooLarge):
            validate_archive_file(
                filename="big.zip",
                head_bytes=_ZIP_HEAD,
                total_size=MAX_ARCHIVE_BYTES + 1,
            )
