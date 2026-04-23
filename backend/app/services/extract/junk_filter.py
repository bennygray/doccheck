"""压缩包"打包垃圾"静默过滤 (fix-mac-packed-zip-parsing D4)。

判断一个 entry 相对路径是否为系统/编辑器/Office 锁文件等"用户 100% 没意图放进来"
的垃圾;命中即在 extract 阶段静默丢弃,不产生 bid_documents 行,不写盘。

规则分三类:
- 目录名精确匹配(大小写敏感,覆盖 macOS/Unix 习惯)
- basename 全等(大小写无关,覆盖 Windows 文件系统 case-insensitive)
- basename 前缀(大小写敏感,都是 ASCII 约定)

黑名单保守选择:只列"系统百分百知道不是业务文件"的 pattern;非业务扩展名
(.rtf / 空文件 / 不支持格式) 不在此列,仍由 extract 引擎按 `暂不支持 X` 路径标
skipped 给用户看得见。
"""

from __future__ import annotations

from pathlib import PurePosixPath

# 中间任一路径组件命中 → 整个 entry 丢弃(macOS 资源叉 / VCS / 编辑器 / 系统保留目录)
_JUNK_DIR_COMPONENTS: frozenset[str] = frozenset(
    {
        "__MACOSX",
        ".git",
        ".svn",
        ".hg",
        "__pycache__",
        "node_modules",
        ".idea",
        ".vscode",
        "$RECYCLE.BIN",
        "System Volume Information",
    }
)

# basename 全等(不区分大小写;Windows 文件系统 case-insensitive,所以全部 lower)
_JUNK_BASENAMES_CI: frozenset[str] = frozenset(
    {
        ".ds_store",
        "thumbs.db",
        "ehthumbs.db",
        "desktop.ini",
        ".directory",
    }
)

# basename 前缀(大小写敏感;这些前缀都是固定 ASCII 约定)
_JUNK_BASENAME_PREFIXES: tuple[str, ...] = (
    "._",  # macOS AppleDouble 资源叉 stub
    "~$",  # MS Office 打开锁文件
    ".~",  # MS Office / WPS 崩溃残留
)


def is_junk_entry(relative_path: str) -> bool:
    """判定 entry 是否为打包垃圾。

    Args:
        relative_path: 已解码的相对路径,POSIX 或 Windows 分隔符都接受,不以 / 开头

    Returns:
        True 表示命中黑名单,调用方应丢弃;False 表示正常文件
    """
    if not relative_path:
        return False

    # 统一成 POSIX 分隔符,拆分组件
    normalized = relative_path.replace("\\", "/")
    p = PurePosixPath(normalized)
    parts = p.parts
    if not parts:
        return False

    # 1. 目录组件命中(basename 自身目录名也算,覆盖 "__MACOSX/" 单条目录 entry)
    for component in parts:
        if component in _JUNK_DIR_COMPONENTS:
            return True

    # 2. basename 全等(大小写无关)
    name = p.name
    if not name:
        return False
    if name.lower() in _JUNK_BASENAMES_CI:
        return True

    # 3. basename 前缀(大小写敏感)
    for prefix in _JUNK_BASENAME_PREFIXES:
        if name.startswith(prefix):
            return True

    return False


__all__ = ["is_junk_entry"]
