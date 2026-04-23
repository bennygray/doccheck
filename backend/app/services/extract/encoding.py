"""压缩包内文件名编码探测 (D4 / Risks 表"GBK 中文文件名"行)。

ZIP 标准:Bit 11 (UTF-8 flag) 置位 → 文件名是 UTF-8;否则 spec 没说,实际
中文场景分两类:
- Windows 7-Zip / WinRAR 默认用 GBK 字节(历史多数)
- macOS Archive Utility 用 UTF-8 字节但不置 bit 11(fix-mac-packed-zip-parsing D2)

本模块封装一个统一 ``decode_filename`` 让 engine 用同一个调用解所有压缩包格式。
"""

from __future__ import annotations

import chardet


def _looks_like_utf8(raw_bytes: bytes) -> bool:
    """严格按 UTF-8 字节模式校验 raw_bytes。

    (fix-mac-packed-zip-parsing D1)

    - 纯 ASCII (所有字节 < 0x80) → True
    - 含高位字节时,按 UTF-8 多字节序列规则校验:
      - 0xC0..0xDF 后接 1 个 0x80..0xBF (2-byte 序列,但 0xC0/0xC1 属 overlong,排除)
      - 0xE0..0xEF 后接 2 个 0x80..0xBF (3-byte 序列)
      - 0xF0..0xF7 后接 3 个 0x80..0xBF (4-byte 序列)
    - 孤立的 trail byte / 截断的多字节序列 / 非法 lead byte → False

    相比 ``raw_bytes.decode("utf-8")`` 的优势:不仅保证语法合法,还排除
    overlong encoding(C0/C1)等边缘有效输入,降低 GBK 字节序列的误判概率。
    """
    if not raw_bytes:
        return False

    i = 0
    n = len(raw_bytes)
    has_high = False
    while i < n:
        b = raw_bytes[i]
        if b < 0x80:
            i += 1
            continue
        has_high = True
        # 判定 lead byte 并确定后续 trail byte 数量
        if 0xC2 <= b <= 0xDF:  # 2-byte(排除 overlong C0/C1)
            need = 1
        elif 0xE0 <= b <= 0xEF:  # 3-byte
            need = 2
        elif 0xF0 <= b <= 0xF4:  # 4-byte(U+10FFFF 封顶,排除 F5-F7)
            need = 3
        else:
            return False
        if i + need >= n:
            return False  # 截断
        for j in range(1, need + 1):
            tb = raw_bytes[i + j]
            if tb < 0x80 or tb > 0xBF:
                return False
        i += need + 1

    # 全 ASCII 也算 UTF-8 合法,但纯 ASCII 场景交给各编码都能 decode,这里返回 True
    # 由 decode_filename 统一交给 UTF-8 解码器(结果一致、无风险)
    return True


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

    # 2. UTF-8 字节模式严格校验(覆盖 macOS Archive Utility 无 flag 场景;
    #    GBK 字节极难凑成合法 UTF-8 多字节序列,误判概率接近 0)
    if _looks_like_utf8(raw_bytes):
        try:
            return raw_bytes.decode("utf-8"), None
        except UnicodeDecodeError:
            # _looks_like_utf8 通过但 decode 失败,理论不会发生;兜底继续
            pass

    # 3. 中文场景默认 GBK 优先尝试(覆盖 90% Windows 7-Zip / WinRAR);
    #    GBK 是 GB2312/GB18030 超集,失败再走 chardet 兜底。短文件名(如
    #    "投标文件.docx" 的 8 字节 GBK)chardet 置信度往往偏低,不能首选。
    try:
        decoded = raw_bytes.decode("gbk")
        # 完全 ASCII 的别走 GBK 路径(避免误把 ASCII 标 GBK)— 实际等价,但保留
        # 一致性
        return decoded, None
    except UnicodeDecodeError:
        pass

    # 4. chardet 探测兜底;阈值 0.7 以上才信
    detected = chardet.detect(raw_bytes)
    encoding = (detected.get("encoding") or "").lower()
    confidence = detected.get("confidence") or 0.0
    if encoding and confidence >= 0.7:
        try:
            return raw_bytes.decode(encoding), None
        except (UnicodeDecodeError, LookupError):
            pass

    # 5. 最后兜底:latin1 永不抛异常,以乱码名落盘 + warning
    return raw_bytes.decode("latin1", errors="replace"), "文件名编码探测失败,可能乱码"


__all__ = ["decode_filename"]
