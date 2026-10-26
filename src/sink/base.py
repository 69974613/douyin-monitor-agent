from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from src.models import CommentHit, LikeAlert, PlayRecord, Video


class SheetWriter(ABC):
    """表格写入抽象。demo 用 LocalSheetWriter（本地 CSV 镜像飞书），
    生产用 FeishuWriter（飞书多维表格 / 电子表格开放 API）。"""

    @abstractmethod
    def write_video_stats(self, videos: List[Video], scan_time: str,
                          data_source: str = "live"): ...

    @abstractmethod
    def write_like_alerts(self, alerts: List[LikeAlert]): ...

    @abstractmethod
    def write_comment_hits(self, hits: List[CommentHit]): ...

    @abstractmethod
    def write_play_records(self, plays: List[PlayRecord]): ...


class TeeSheetWriter(SheetWriter):
    """双写写入器：主写入器（飞书）+ 本地 CSV 镜像。

    动机：dashboard.html 看板读的是本地 CSV——sink.type=feishu 时若只写飞书，
    看板 ①~⑤ 全部空白。双写同时保住"飞书实际执行"与"本地可看"。
    飞书写入失败只记日志不抛出（本地镜像已保留数据，下轮扫描重试），
    避免网络抖动拖垮整轮扫描。
    """

    def __init__(self, primary: SheetWriter, mirror: SheetWriter):
        self.primary = primary
        self.mirror = mirror

    def _both(self, method: str, *args, **kwargs):
        getattr(self.mirror, method)(*args, **kwargs)   # 本地镜像必先落盘
        try:
            getattr(self.primary, method)(*args, **kwargs)
        except Exception as e:
            from src.utils import get_logger

            get_logger().error("主写入器（飞书）.%s() 失败（本地镜像已保留，下轮重写）：%s",
                               method, e)

    def write_video_stats(self, videos: List[Video], scan_time: str,
                          data_source: str = "live"):
        self._both("write_video_stats", videos, scan_time, data_source=data_source)

    def write_like_alerts(self, alerts: List[LikeAlert]):
        self._both("write_like_alerts", alerts)

    def write_comment_hits(self, hits: List[CommentHit]):
        self._both("write_comment_hits", hits)

    def write_play_records(self, plays: List[PlayRecord]):
        self._both("write_play_records", plays)
