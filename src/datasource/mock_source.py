from __future__ import annotations

import copy
import random
from datetime import datetime, timedelta
from typing import Dict, List

from src.datasource.base import DouyinDataSource
from src.models import Comment, Video


class MockDouyinSource(DouyinDataSource):
    """演示模拟数据源：无需真实账号 / 网络，即可跑出可讲解的完整效果。

    幂等性设计（读操作零副作用）：
      点赞/播放不是"每调一次加一点"，而是纯函数——
          当前值 = f(基线值, 速率, 模拟经过时间)
      其中模拟经过时间 = (当前真实时间 - 锚点) × time_scale。
      同一时刻重复调用（包括重试）返回完全相同的数据，绝不会叠加。
    """

    def __init__(self, accounts: List[str], song: Dict[str, str],
                 seed: int = 42, time_scale: float = 1.0):
        self.is_mock = True   # Monitor 据此把自动回复标注为"(模拟)"，演示不造假
        self.song = song
        self.time_scale = float(time_scale)
        self._state: Dict[str, dict] = {}
        self._comments_pool: Dict[str, List[Comment]] = {}
        self._rng = random.Random(seed)
        self._anchor = datetime.now()   # 模拟时间锚点（实例创建时刻）
        self._build(accounts)

    def _build(self, accounts: List[str]):
        now = datetime.now()
        titles = [
            f"新歌《{self.song['name']}》治愈上线",
            f"{self.song['name']} 副歌部分太好哭了",
            f"深夜单曲循环 {self.song['name']}",
            f"街边随拍·{self.song['name']} BGM",
            f"舞蹈挑战 | {self.song['name']}",
        ]
        kw_comments = [
            "这首歌好好听啊", "求歌名！太喜欢了", "什么歌呀背景音乐",
            "BGM是什么？求链接", "这首歌叫什么歌", "好听的歌循环了一整天",
            "bgm求一下", "背景音乐是谁唱的", "求歌名 谢谢",
            "什么歌曲这么上头", "好听 已收藏", "这首歌叫什么名字",
        ]
        nm_comments = [
            "已点赞支持", "加油博主", "更新好快", "画面好美",
            "前排", "支持原创", "期待下一期", "节奏感绝了",
        ]
        idx = 0
        for acc in accounts:
            for _ in range(2):
                aweme_id = f"{acc[:2]}_{idx}"
                pub = now - timedelta(hours=self._rng.randint(2, 60))
                base_likes = self._rng.randint(120, 400)
                base_play = base_likes * self._rng.randint(8, 20)
                vid = Video(
                    aweme_id=aweme_id,
                    account=acc,
                    title=self._rng.choice(titles),
                    publish_time=pub.strftime("%Y-%m-%d %H:%M:%S"),
                    likes=base_likes,
                    play_count=base_play,
                    comments_count=self._rng.randint(20, 120),
                )
                pool: List[Comment] = []
                kws = self._rng.sample(kw_comments, self._rng.randint(4, 7))
                nms = self._rng.sample(nm_comments, self._rng.randint(3, 6))
                items = kws + nms
                self._rng.shuffle(items)
                for j, txt in enumerate(items):
                    pool.append(Comment(
                        comment_id=f"{aweme_id}_c{j}",
                        aweme_id=aweme_id, account=acc,
                        text=txt, user=f"用户{j}"))
                self._state[aweme_id] = {
                    "video": vid,
                    "likes0": base_likes,
                    "play0": base_play,
                    # 点赞速率：350~800 赞/小时（30 分钟模拟区间 → 175~400 增量，
                    # 对齐 300 阈值：部分扫描触发预警、部分不触发，展示梯度）
                    "rate": self._rng.uniform(350, 800),
                    "comments_count0": vid.comments_count,
                }
                self._comments_pool[aweme_id] = pool
                idx += 1

    def _elapsed_hours(self) -> float:
        """模拟经过的小时数（纯函数，与调用次数无关）。"""
        real_h = (datetime.now() - self._anchor).total_seconds() / 3600.0
        return max(0.0, real_h * self.time_scale)

    def get_recent_videos(self, account: str, within_days: int) -> List[Video]:
        out: List[Video] = []
        now = datetime.now()
        for aid, st in self._state.items():
            v = st["video"]
            if v.account != account:
                continue
            pub = datetime.strptime(v.publish_time, "%Y-%m-%d %H:%M:%S")
            if (now - pub).days < within_days:
                # 返回副本：调用方持有的引用不与内部状态共享，
                # 后续 get_video_stats 更新不会改写已产出的历史快照
                out.append(copy.deepcopy(v))
        return out

    def get_video_stats(self, account: str, aweme_id: str) -> Video:
        st = self._state.get(aweme_id)
        if not st:
            return Video(aweme_id=aweme_id, account=account, title="", publish_time="")
        h = self._elapsed_hours()
        v = copy.deepcopy(st["video"])
        v.likes = st["likes0"] + int(st["rate"] * h)
        v.play_count = st["play0"] + int(st["rate"] * 11 * h)
        v.comments_count = st["comments_count0"] + int(h * 20)
        return v

    def get_comments(self, account: str, aweme_id: str) -> List[Comment]:
        st = self._state.get(aweme_id)
        if not st:
            return []
        pool = self._comments_pool.get(aweme_id, [])
        # 曝光条数同样是时间的纯函数（幂等）
        revealed = min(len(pool), 2 + int(self._elapsed_hours() * 6))
        return pool[:revealed]
