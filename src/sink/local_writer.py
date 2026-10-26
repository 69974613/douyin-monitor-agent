from __future__ import annotations

import csv
import os
from typing import List

from src.models import CommentHit, LikeAlert, PlayRecord, Video
from src.sink.base import SheetWriter


class LocalSheetWriter(SheetWriter):
    """本地 CSV 写入器：用 4 张表镜像飞书电子表格结构，可直接用 Excel / 飞书导入查看。

    表清单（对应题目1 写入飞书的要求）：
      视频数据监控.csv      —— 每次扫描的视频点赞 / 播放 / 评论数
      点赞预警.csv          —— 点赞增量 > 阈值的预警记录
      评论关键词命中.csv    —— 强意图自动回复 + 弱意图仅记录（含处理方式列）
      播放量.csv            —— 播放量采集记录
    """

    def __init__(self, output_dir: str = "output"):
        self.dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
        self.files = {
            "video": os.path.join(output_dir, "视频数据监控.csv"),
            "alert": os.path.join(output_dir, "点赞预警.csv"),
            "comment": os.path.join(output_dir, "评论关键词命中.csv"),
            "play": os.path.join(output_dir, "播放量.csv"),
        }
        self._ensure_headers()

    def _ensure_headers(self):
        headers = {
            "video": ["扫描时间", "数据源", "账号", "视频ID", "标题", "发布时间", "点赞", "播放", "评论数"],
            "alert": ["扫描时间", "账号", "视频ID", "标题", "上次点赞", "本次点赞", "增量", "阈值", "预警人"],
            "comment": ["扫描时间", "账号", "视频ID", "标题", "评论内容", "命中关键词", "自动回复话术", "处理方式"],
            "play": ["扫描时间", "账号", "视频ID", "标题", "播放量"],
        }
        for k, path in self.files.items():
            if not os.path.exists(path):
                with open(path, "w", newline="", encoding="utf-8-sig") as f:
                    csv.writer(f).writerow(headers[k])

    def _append(self, key: str, row: list):
        with open(self.files[key], "a", newline="", encoding="utf-8-sig") as f:
            csv.writer(f).writerow(row)

    def write_video_stats(self, videos: List[Video], scan_time: str,
                          data_source: str = "live"):
        for v in videos:
            self._append(
                "video",
                [scan_time, data_source, v.account, v.aweme_id, v.title,
                 v.publish_time, v.likes, v.play_count, v.comments_count],
            )

    def write_like_alerts(self, alerts: List[LikeAlert]):
        for a in alerts:
            self._append(
                "alert",
                [a.scan_time, a.account, a.aweme_id, a.title, a.prev_likes,
                 a.cur_likes, a.delta, a.threshold, a.warned_person],
            )

    def write_comment_hits(self, hits: List[CommentHit]):
        for h in hits:
            self._append(
                "comment",
                [h.scan_time, h.account, h.aweme_id, h.title, h.comment_text,
                 h.matched_keyword, h.reply_text, h.action],
            )

    def write_play_records(self, plays: List[PlayRecord]):
        for p in plays:
            self._append(
                "play",
                [p.scan_time, p.account, p.aweme_id, p.title, p.play_count],
            )
