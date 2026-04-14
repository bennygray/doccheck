"""压缩包解压安全校验 (D4 决策)。

zip-slip 与 zip-bomb 防护:在调用方"读 entry → 决定写 entry"之间夹一道
``check_safe_entry`` 与三道预算函数(累计字节 / 累计文件数 / 嵌套深度)。

设计原则:
- 纯函数,不碰 IO 不写盘;调用方在 engine 里组装
- 失败返回 ``(False, reason)`` 而非抛异常 → engine 把 reason 写进 ``parse_error``
- 路径校验三道:``normpath`` 去 ``..`` → ``realpath`` 解符号链接 → ``commonpath``
  确认仍在 root 下;任一一道挂掉就是攻击信号
"""

from __future__ import annotations

import os
from pathlib import Path

# zip-bomb 上限(D4)
MAX_TOTAL_EXTRACTED_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB
MAX_ENTRY_COUNT = 1000
MAX_NESTING_DEPTH = 3


def check_safe_entry(
    entry_path: str,
    extract_root: Path,
) -> tuple[bool, str]:
    """三道路径校验,确认 entry 解压后落点不会逃出 ``extract_root``。

    Args:
        entry_path: 压缩包内的相对路径(已经过编码解码)
        extract_root: 解压根目录(必须存在;由 engine 在 mkdir 后传入)

    Returns:
        ``(ok, reason)``:
        - ok=True → reason="" 可以解压
        - ok=False → reason 是给 ``parse_error`` 的人话,例如 "路径不安全,已跳过"
    """
    # 0. 显式拒绝绝对路径(Windows 还要拦盘符)
    if not entry_path or entry_path.strip() == "":
        return False, "路径为空,已跳过"
    if entry_path.startswith(("/", "\\")) or (
        len(entry_path) >= 2 and entry_path[1] == ":"
    ):
        return False, "绝对路径,已跳过"

    # 1. normpath 去掉 ``./`` ``..`` 等;normpath 之后若仍含 ``..`` → 相对穿越
    normalized = os.path.normpath(entry_path)
    if normalized.startswith("..") or os.sep + ".." in normalized:
        return False, "路径不安全,已跳过"

    # 2. 计算出绝对落点;先用 join + normpath(尚未真去解符号链接)
    candidate = (extract_root / normalized).resolve(strict=False)
    root_resolved = extract_root.resolve(strict=False)

    # 3. commonpath 严格确认在 root 内
    try:
        common = Path(os.path.commonpath([str(root_resolved), str(candidate)]))
    except ValueError:
        # 不同盘符 → commonpath 抛 ValueError,Windows 跨盘攻击
        return False, "路径不安全,已跳过"
    if common != root_resolved:
        return False, "路径不安全,已跳过"

    return True, ""


def check_size_budget(cumulative_bytes: int) -> tuple[bool, str]:
    """累计已写字节超 2GB → 中断本次解压。"""
    if cumulative_bytes > MAX_TOTAL_EXTRACTED_BYTES:
        return False, f"解压文件过大,超过 {MAX_TOTAL_EXTRACTED_BYTES // (1024**3)}GB 限制"
    return True, ""


def check_count_budget(cumulative_count: int) -> tuple[bool, str]:
    """累计已处理条目数超 1000 → 中断本次解压。"""
    if cumulative_count > MAX_ENTRY_COUNT:
        return False, f"文件数超过 {MAX_ENTRY_COUNT}"
    return True, ""


def check_nesting_depth(depth: int) -> tuple[bool, str]:
    """嵌套递归深度 > 3 → 跳过该子包但不中断外层。"""
    if depth > MAX_NESTING_DEPTH:
        return False, f"嵌套层数超过 {MAX_NESTING_DEPTH}"
    return True, ""


__all__ = [
    "MAX_ENTRY_COUNT",
    "MAX_NESTING_DEPTH",
    "MAX_TOTAL_EXTRACTED_BYTES",
    "check_count_budget",
    "check_nesting_depth",
    "check_safe_entry",
    "check_size_budget",
]
