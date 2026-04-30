"""C4 upload service:multipart 接收 + 校验 + 落盘。

边界:只负责"安全把上传的压缩包写到 uploads/" + 计算 MD5;
不负责解压(那是 extract service 的事)。
"""

from app.services.upload.storage import save_archive, save_tender_archive
from app.services.upload.validator import (
    FileTooLarge,
    UnsupportedMediaType,
    validate_archive_file,
)

__all__ = [
    "FileTooLarge",
    "UnsupportedMediaType",
    "save_archive",
    "save_tender_archive",
    "validate_archive_file",
]
