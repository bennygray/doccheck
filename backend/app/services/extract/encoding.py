"""压缩包内文件名编码探测 (D4 / Risks 表"GBK 中文文件名"行)。

ZIP 标准:Bit 11 (UTF-8 flag) 置位 → 文件名是 UTF-8;否则 spec 没说,实际
中文场景多数是 GBK(Windows 7-Zip / WinRAR 默认)。本模块封装一个统一
``decode_filename`` 让 engine 用同一个调用解所有压缩包格式。
"""

from __future__ import annotations

import chardet


def decode_filename(
    raw_bytes: bytes,
    *,
    is_utf8_flagged: bool = False,
) -> tuple[str, str | None]:
    """探测 + 解码 entry 文件名。

    Args:
        raw_bytes: 压缩包内 entry 的原文件名字节(未解码)
        is_utf8_flagged: ZIP 头部 bit 11 是否置位;7z/rar 调用方传 False

    Returns:
        ``(filename, warning)`` —— warning 非 None 时表示用了兜底解码,可写到
        ``bid_documents.parse_error`` 提醒用户该名可能乱码。
    """
    if not raw_bytes:
        return "", None

    # 1. UTF-8 flag 优先(ZIP spec 明确)
    if is_utf8_flagged:
        try:
            return raw_bytes.decode("utf-8"), None
        except UnicodeDecodeError:
            # flag 撒谎 → 继续探测
            pass

    # 2. 中文场景默认 GBK 优先尝试(覆盖 90% Windows 7-Zip / WinRAR);
    #    GBK 是 GB2312/GB18030 超集,失败再走 chardet 兜底。短文件名(如
    #    "投标文件.docx" 的 8 字节 GBK)chardet 置信度往往偏低,不能首选。
    try:
        decoded = raw_bytes.decode("gbk")
        # 完全 ASCII 的别走 GBK 路径(避免误把 ASCII 标 GBK)— 实际等价,但保留
        # 一致性
        return decoded, None
    except UnicodeDecodeError:
        pass

    # 3. chardet 探测兜底;阈值 0.7 以上才信
    detected = chardet.detect(raw_bytes)
    encoding = (detected.get("encoding") or "").lower()
    confidence = detected.get("confidence") or 0.0
    if encoding and confidence >= 0.7:
        try:
            return raw_bytes.decode(encoding), None
        except (UnicodeDecodeError, LookupError):
            pass

    # 4. 最后兜底:latin1 永不抛异常,以乱码名落盘 + warning
    return raw_bytes.decode("latin1", errors="replace"), "文件名编码探测失败,可能乱码"


__all__ = ["decode_filename"]
