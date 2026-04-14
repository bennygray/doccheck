"""C4 L2 测试 - 在 tmp 目录构造各类压缩包样本 (§11.1)。

可用 factory:
- ``make_normal_zip``         3 entries:docx + xlsx + jpg
- ``make_zip_slip_zip``       含 ``../../etc/passwd`` entry
- ``make_nested_zip(depth)``  递归嵌套到指定深度
- ``make_gbk_zip``            entry 名用 GBK 编码、不置 UTF-8 flag
- ``make_broken_zip``         头是 PK 但内容截断 → BadZipFile
- ``make_empty_zip``          0 entry
- ``make_encrypted_7z``       py7zr 加密 7z

所有 factory 接受 ``out: Path``,直接写到该路径,返回 ``Path``;调用方拼 MD5。
"""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

# 极小 docx/xlsx 占位字节(不需要是合法 OOXML,只要让 file_type=.docx 即可入 DB)
_DOCX_DUMMY = b"PK\x03\x04dummy-docx-content"
_XLSX_DUMMY = b"PK\x03\x04dummy-xlsx-content"
_JPG_DUMMY = b"\xff\xd8\xff\xe0" + b"jpeg-stub" * 10


def make_normal_zip(out: Path) -> Path:
    """3 entry:1.docx / 2.xlsx / 3.jpg。"""
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("1.docx", _DOCX_DUMMY)
        zf.writestr("dir/2.xlsx", _XLSX_DUMMY)
        zf.writestr("dir/sub/3.jpg", _JPG_DUMMY)
    return out


def make_zip_slip_zip(out: Path) -> Path:
    """1 个正常 entry + 1 个穿越 entry。"""
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("ok.docx", _DOCX_DUMMY)
        zf.writestr("../../etc/passwd", b"malicious")
    return out


def make_nested_zip(out: Path, depth: int = 4) -> Path:
    """递归构造嵌套 ZIP,内层 inner_<depth>.zip 包含 一个 docx。

    最外层 = depth 1;extract 时 depth 起始 1,depth+1 进递归。depth=4 时
    最内层应被 ``check_nesting_depth`` 拦下(MAX=3)。
    """
    inner_data = _DOCX_DUMMY
    name = "deepest.docx"

    for layer in range(depth, 0, -1):
        tmp = out.parent / f"_layer_{layer}.zip"
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(name, inner_data)
        inner_data = tmp.read_bytes()
        name = f"inner_{layer}.zip"
        if tmp != out:
            tmp.unlink()

    out.write_bytes(inner_data)
    return out


def make_gbk_zip(out: Path) -> Path:
    """entry 名用 GBK 编码,不置 UTF-8 flag。"""
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        info = zipfile.ZipInfo(filename="投标文件.docx")
        info.flag_bits = 0  # 不置 0x800
        # zipfile 在写 ZipInfo 时把 filename 视作 str → 内部 encode('utf-8' if flag 0x800 else 'cp437')
        # 我们要 GBK,故先把 filename 设成 cp437 解码视图的 GBK bytes
        gbk_name = "投标文件.docx".encode("gbk")
        # 利用 cp437 是 1:1 字节映射的特性,把 GBK bytes 当 cp437 字符塞进去
        info.filename = gbk_name.decode("cp437")
        zf.writestr(info, _DOCX_DUMMY)
    return out


def make_broken_zip(out: Path) -> Path:
    """PK 头但截断 → zipfile.BadZipFile。"""
    out.write_bytes(b"PK\x03\x04" + b"\x00" * 8)
    return out


def make_empty_zip(out: Path) -> Path:
    with zipfile.ZipFile(out, "w") as _zf:
        pass
    return out


def make_encrypted_7z(out: Path, password: str = "secret") -> Path:
    """py7zr 加密 7z。py7zr 必须装 (C4 已加 dep)。"""
    import py7zr

    payload_dir = out.parent / f"_payload_{out.stem}"
    payload_dir.mkdir(parents=True, exist_ok=True)
    (payload_dir / "secret.docx").write_bytes(_DOCX_DUMMY)
    try:
        with py7zr.SevenZipFile(out, "w", password=password) as sz:
            sz.set_encrypted_header(True)
            sz.writeall(payload_dir, arcname=".")
    finally:
        for p in payload_dir.iterdir():
            p.unlink()
        payload_dir.rmdir()
    return out


def md5_of(path: Path) -> str:
    h = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(64 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


__all__ = [
    "make_broken_zip",
    "make_empty_zip",
    "make_encrypted_7z",
    "make_gbk_zip",
    "make_nested_zip",
    "make_normal_zip",
    "make_zip_slip_zip",
    "md5_of",
]
