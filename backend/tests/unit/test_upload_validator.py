"""L1 单元 - upload.validator 三道校验 (C4 §10.3)。

覆盖 spec.md "文件上传(创建+追加)" 的扩展名/魔数/大小三道场景。
"""

from __future__ import annotations

import pytest

from app.services.upload import validator as validator_module
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


class TestMagicLibmagicFallback:
    """libmagic 返回值与字节头 fallback 的协作场景。

    回归 bug:小 zip(全 docx/xlsx)libmagic 返 application/octet-stream 时
    不应直接判错,需 fallback 字节头判定。
    """

    def test_libmagic_octet_stream_with_zip_head_falls_back_and_passes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # libmagic "我不知道" + 头字节是 PK\x03\x04 → fallback 必须通过
        monkeypatch.setattr(
            validator_module,
            "_guess_mime_with_magic",
            lambda head: "application/octet-stream",
        )
        assert (
            validate_archive_file(filename="x.zip", head_bytes=_ZIP_HEAD, total_size=1024)
            == ".zip"
        )

    def test_libmagic_returns_zip_mime_passes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # libmagic 明确返 application/zip → 直接通过
        monkeypatch.setattr(
            validator_module,
            "_guess_mime_with_magic",
            lambda head: "application/zip",
        )
        assert (
            validate_archive_file(filename="x.zip", head_bytes=_ZIP_HEAD, total_size=1024)
            == ".zip"
        )

    def test_libmagic_returns_mismatch_mime_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # libmagic 给出非 octet-stream 但与扩展名不匹配 → 显式 mismatch,直接拒
        monkeypatch.setattr(
            validator_module,
            "_guess_mime_with_magic",
            lambda head: "image/png",
        )
        with pytest.raises(UnsupportedMediaType, match="魔数"):
            validate_archive_file(
                filename="fake.zip",
                head_bytes=b"\x89PNG\r\n\x1a\n" + b"\x00" * 24,
                total_size=1024,
            )

    def test_libmagic_unavailable_and_bad_head_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # libmagic 不可用(None)+ 头字节也错 → fallback 失败,拒
        monkeypatch.setattr(
            validator_module,
            "_guess_mime_with_magic",
            lambda head: None,
        )
        with pytest.raises(UnsupportedMediaType, match="魔数"):
            validate_archive_file(
                filename="fake.zip",
                head_bytes=b"hello world\n" + b"\x00" * 20,
                total_size=1024,
            )

    def test_libmagic_octet_stream_with_bad_head_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # libmagic 返 octet-stream + 头字节也错 → fallback 失败,拒
        monkeypatch.setattr(
            validator_module,
            "_guess_mime_with_magic",
            lambda head: "application/octet-stream",
        )
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
