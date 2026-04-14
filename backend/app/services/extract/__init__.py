"""C4 extract service - 异步压缩包解压。

边界:
- 入口 ``trigger_extract(bidder_id, password=None)``:asyncio 后台协程
- 内部 ``extract_archive(bidder_id, password, session_factory)``:核心循环
- ``INFRA_DISABLE_EXTRACT=1`` 跳过自动起协程,L2 测试 fixture 手动 await

详细决策见 ``openspec/changes/file-upload/design.md`` D4 / D5 / D6。
"""

from app.services.extract.engine import extract_archive, trigger_extract

__all__ = ["extract_archive", "trigger_extract"]
