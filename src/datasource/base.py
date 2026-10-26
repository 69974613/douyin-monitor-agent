from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from src.models import Comment, Video


class DouyinDataSource(ABC):
    """抖音数据源抽象。demo 用 MockDouyinSource，生产用 LiveDouyinSource。"""

    @abstractmethod
    def get_recent_videos(self, account: str, within_days: int) -> List[Video]:
        """返回账号内近 within_days 天发布的视频（用于锁定监控对象）。"""

    @abstractmethod
    def get_video_stats(self, account: str, aweme_id: str) -> Video:
        """返回某视频当前的实时数据（点赞 / 播放 / 评论数）。"""

    @abstractmethod
    def get_comments(self, account: str, aweme_id: str) -> List[Comment]:
        """返回某视频评论区（用于关键词扫描与自动回复）。"""

    def close(self):
        """释放数据源资源（live 释放 Playwright 浏览器；mock 无需处理）。"""
