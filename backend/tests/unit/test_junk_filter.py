"""junk_filter.is_junk_entry L1 单测 (fix-mac-packed-zip-parsing)。

覆盖 spec `file-upload` 的"打包垃圾静默丢弃"相关 scenario 正负例。
"""

from __future__ import annotations

import pytest

from app.services.extract.junk_filter import is_junk_entry


# --------------------------------- 正例:目录组件命中 ----


@pytest.mark.parametrize(
    "path",
    [
        "__MACOSX/._x.docx",
        "__MACOSX/供应商A/._foo.docx",
        "a/b/__MACOSX/c.docx",  # 中间层命中
        "__MACOSX/",  # 纯目录 entry(endswith "/" 在调用方已被截掉,这里保险)
        ".git/config",
        "a/b/.git/HEAD",
        ".svn/entries",
        ".hg/dirstate",
        "__pycache__/foo.cpython-313.pyc",
        "node_modules/left-pad/index.js",
        ".idea/workspace.xml",
        ".vscode/settings.json",
        "$RECYCLE.BIN/S-1-5-21/foo",
        "System Volume Information/IndexerVolumeGuid",
    ],
)
def test_junk_dir_components_hit(path: str) -> None:
    assert is_junk_entry(path) is True


# --------------------------------- 正例:basename 全等大小写无关 ----


@pytest.mark.parametrize(
    "path",
    [
        ".DS_Store",
        "foo/.DS_Store",
        "A/B/C/.ds_store",  # 全小写
        ".Ds_Store",  # 大小写混杂
        "Thumbs.db",
        "thumbs.db",
        "THUMBS.DB",
        "sub/Thumbs.db",
        "ehthumbs.db",
        "desktop.ini",
        "DESKTOP.INI",
        ".directory",  # KDE
    ],
)
def test_junk_basename_exact_ci_hit(path: str) -> None:
    assert is_junk_entry(path) is True


# --------------------------------- 正例:basename 前缀命中 ----


@pytest.mark.parametrize(
    "path",
    [
        "._anything",
        "foo/._bar.docx",
        "供应商A/._江苏锂源.docx",
        "~$report.docx",
        "dir/~$x.xlsx",
        ".~foo.docx",
        "dir/.~bar.docx",
    ],
)
def test_junk_basename_prefix_hit(path: str) -> None:
    assert is_junk_entry(path) is True


# --------------------------------- 反例:用户真实命名不误伤 ----


@pytest.mark.parametrize(
    "path",
    [
        "normal.docx",
        "供应商A/投标报价.xlsx",
        "my~dollar.docx",  # ~ 在中间
        "my._file.docx",  # ._ 在中间
        "my.~thing.docx",  # .~ 在中间
        ".gitignore",  # 前缀不完全匹配 .git/
        ".gitattributes",  # 同上
        ".github",  # 不等于 .git 目录
        "foo/README.md",
        "sub/Thumbs.xlsx",  # basename != thumbs.db(后缀不同)
        "desktop.txt",  # basename != desktop.ini
        "__MACOSX_not_really/foo.docx",  # 目录名多出后缀,不等
        "not__MACOSX/foo.docx",
        "项目/A 公司.docx",
    ],
)
def test_junk_not_hit(path: str) -> None:
    assert is_junk_entry(path) is False


# --------------------------------- 边界 ----


@pytest.mark.parametrize(
    "path,expected",
    [
        ("", False),
        ("foo/", False),  # 目录(调用方已过滤;保险)
        ("/absolute/path/foo.docx", False),  # 绝对路径(check_safe_entry 会拒;junk 不管)
        ("foo\\bar\\baz.docx", False),  # Windows 分隔符,正常文件
        ("foo\\__MACOSX\\x.docx", True),  # Windows 分隔符下 __MACOSX 仍命中
        ("foo\\.DS_Store", True),  # Windows 分隔符下 basename 仍命中
        ("foo\\~$x.docx", True),
    ],
)
def test_junk_edge_cases(path: str, expected: bool) -> None:
    assert is_junk_entry(path) is expected
