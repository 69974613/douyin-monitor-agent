from __future__ import annotations

import os
import sqlite3
import threading
from typing import Dict, Optional


class StateStore:
    """SQLite 持久化状态存储：替代"内存 set + 裸 JSON 文件"。

    - video_state：视频上次扫描的点赞/播放（用于跨重启的增量预警）；
    - replied_comments：已自动回复的评论，comment_id 主键唯一约束，
      程序重启后绝不会对同一条评论重复回复（避免触发抖音风控）。
    事务写 + 线程锁，单进程并发安全。
    """

    def __init__(self, db_path: str):
        d = os.path.dirname(db_path)
        if d:
            os.makedirs(d, exist_ok=True)
        # 跨进程并发加固：main 与 card_server 是两个进程写同一 db 文件，
        # 默认 timeout=0 遇锁立即抛 "database is locked"（人工决策会丢）；
        # timeout=5 等锁 + WAL 模式读写不互斥，演示/生产双进程都安全
        self.conn = sqlite3.connect(db_path, check_same_thread=False, timeout=5)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.lock = threading.Lock()
        with self.lock, self.conn:
            self.conn.execute(
                "CREATE TABLE IF NOT EXISTS video_state ("
                "aweme_id TEXT PRIMARY KEY, likes INTEGER, play INTEGER, last_scan TEXT)")
            self.conn.execute(
                "CREATE TABLE IF NOT EXISTS replied_comments ("
                "comment_id TEXT PRIMARY KEY, aweme_id TEXT, replied_at TEXT)")
            # 弱意图评论（好听/歌）转人工追踪：pending = 待人工处理
            self.conn.execute(
                "CREATE TABLE IF NOT EXISTS weak_intents ("
                "comment_id TEXT PRIMARY KEY, aweme_id TEXT, comment_text TEXT, "
                "keyword TEXT, first_seen TEXT, status TEXT DEFAULT 'pending')")
            # 半自动模式：自动生成的回复经飞书卡片人工批准后才真实发送
            # status: pending(待确认) / approved(已批准-待发送) / 已发送 / 已跳过
            self.conn.execute(
                "CREATE TABLE IF NOT EXISTS reply_approvals ("
                "comment_id TEXT PRIMARY KEY, aweme_id TEXT, reply_text TEXT, "
                "staged_at TEXT, status TEXT DEFAULT 'pending', "
                "decided_at TEXT, operator TEXT)")
            # 抖加加热人工确认（飞书卡片按钮回调落库）
            self.conn.execute(
                "CREATE TABLE IF NOT EXISTS boost_decisions ("
                "aweme_id TEXT PRIMARY KEY, alert_time TEXT, "
                "decision TEXT, decided_at TEXT, operator TEXT)")

    def get_prev(self, aweme_id: str) -> Optional[Dict]:
        with self.lock:
            row = self.conn.execute(
                "SELECT likes, play, last_scan FROM video_state WHERE aweme_id=?",
                (aweme_id,)).fetchone()
        return {"likes": row[0], "play": row[1], "last_scan": row[2]} if row else None

    def set_video_state(self, aweme_id: str, likes: int, play: int, last_scan: str):
        with self.lock, self.conn:
            self.conn.execute(
                "INSERT INTO video_state (aweme_id, likes, play, last_scan) VALUES (?,?,?,?) "
                "ON CONFLICT(aweme_id) DO UPDATE SET likes=?, play=?, last_scan=?",
                (aweme_id, likes, play, last_scan, likes, play, last_scan))

    def is_replied(self, comment_id: str) -> bool:
        with self.lock:
            row = self.conn.execute(
                "SELECT 1 FROM replied_comments WHERE comment_id=?",
                (comment_id,)).fetchone()
        return row is not None

    def mark_replied(self, comment_id: str, aweme_id: str, replied_at: str):
        with self.lock, self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO replied_comments (comment_id, aweme_id, replied_at) "
                "VALUES (?,?,?)", (comment_id, aweme_id, replied_at))

    # ---- 弱意图转人工追踪 ----
    def record_weak_intent(self, comment_id: str, aweme_id: str,
                           comment_text: str, keyword: str, first_seen: str):
        with self.lock, self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO weak_intents "
                "(comment_id, aweme_id, comment_text, keyword, first_seen, status) "
                "VALUES (?,?,?,?,?,'pending')",
                (comment_id, aweme_id, comment_text, keyword, first_seen))

    def mark_weak_handled(self, comment_id: str):
        """人工确认后调用（可挂到卡片按钮/后台接口），状态 pending → handled。"""
        with self.lock, self.conn:
            self.conn.execute(
                "UPDATE weak_intents SET status='handled' WHERE comment_id=?",
                (comment_id,))

    def pending_weak_intents(self) -> list:
        with self.lock:
            return self.conn.execute(
                "SELECT comment_id, aweme_id, comment_text, keyword, first_seen "
                "FROM weak_intents WHERE status='pending' ORDER BY first_seen").fetchall()

    # ---- 半自动回复审批（自动生成、人工确认后才真实发送）----
    def stage_reply_approval(self, comment_id: str, aweme_id: str,
                             reply_text: str, staged_at: str):
        with self.lock, self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO reply_approvals "
                "(comment_id, aweme_id, reply_text, staged_at, status) "
                "VALUES (?,?,?,?,'pending')", (comment_id, aweme_id, reply_text, staged_at))

    def set_reply_decision(self, comment_id: str, status: str,
                           decided_at: str, operator: str = ""):
        with self.lock, self.conn:
            self.conn.execute(
                "UPDATE reply_approvals SET status=?, decided_at=?, operator=? "
                "WHERE comment_id=?", (status, decided_at, operator, comment_id))

    def get_reply_status(self, comment_id: str):
        with self.lock:
            row = self.conn.execute(
                "SELECT status FROM reply_approvals WHERE comment_id=?",
                (comment_id,)).fetchone()
        return row[0] if row else None

    def approved_replies(self) -> list:
        with self.lock:
            return self.conn.execute(
                "SELECT comment_id, aweme_id, reply_text FROM reply_approvals "
                "WHERE status='approved' ORDER BY decided_at").fetchall()

    # ---- 抖加加热人工确认（飞书交互式卡片按钮回调）----
    def set_boost_decision(self, aweme_id: str, decision: str,
                           decided_at: str, operator: str = "",
                           alert_time: str = ""):
        """预登记（预警时 decision="待确认" 并写入 alert_time）；
        按钮回调更新 decision/decided_at/operator，alert_time 保留首次预警时间。"""
        with self.lock, self.conn:
            self.conn.execute(
                "INSERT INTO boost_decisions (aweme_id, alert_time, decision, decided_at, operator) "
                "VALUES (?,?,?,?,?) "
                "ON CONFLICT(aweme_id) DO UPDATE SET decision=excluded.decision, "
                "decided_at=excluded.decided_at, operator=excluded.operator",
                (aweme_id, alert_time, decision, decided_at, operator))

    def get_boost_decision(self, aweme_id: str) -> Optional[Dict]:
        with self.lock:
            row = self.conn.execute(
                "SELECT decision, decided_at, operator FROM boost_decisions WHERE aweme_id=?",
                (aweme_id,)).fetchone()
        return ({"decision": row[0], "decided_at": row[1], "operator": row[2]}
                if row else None)
