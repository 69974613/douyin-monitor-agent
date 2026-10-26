from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


def _now_iso() -> str:
    from datetime import datetime

    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@dataclass
class Video:
    aweme_id: str
    account: str
    title: str
    publish_time: str
    likes: int = 0
    play_count: int = 0
    comments_count: int = 0


@dataclass
class Comment:
    comment_id: str
    aweme_id: str
    account: str
    text: str
    user: str = "匿名用户"
    create_time: str = field(default_factory=_now_iso)


@dataclass
class LikeAlert:
    account: str
    aweme_id: str
    title: str
    prev_likes: int
    cur_likes: int
    delta: int
    threshold: int
    warned_person: str
    scan_time: str = field(default_factory=_now_iso)


@dataclass
class CommentHit:
    comment_id: str = ""
    account: str = ""
    aweme_id: str = ""
    title: str = ""
    comment_text: str = ""
    matched_keyword: str = ""
    reply_text: str = ""
    action: str = "已自动回复"  # 已自动回复 | 弱意图-仅记录(转人工)
    scan_time: str = field(default_factory=_now_iso)


@dataclass
class PlayRecord:
    account: str
    aweme_id: str
    title: str
    play_count: int
    scan_time: str = field(default_factory=_now_iso)


@dataclass
class ScanContext:
    """一次完整扫描周期采集到的全部数据。"""

    scan_time: str = field(default_factory=_now_iso)
    videos: List[Video] = field(default_factory=list)
    alerts: List[LikeAlert] = field(default_factory=list)
    hits: List[CommentHit] = field(default_factory=list)
    plays: List[PlayRecord] = field(default_factory=list)
