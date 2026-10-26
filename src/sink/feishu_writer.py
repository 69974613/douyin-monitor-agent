from __future__ import annotations

import time
from typing import Dict, List

from src.models import CommentHit, LikeAlert, PlayRecord, Video
from src.sink.base import SheetWriter
from src.utils import net_retry


class FeishuWriter(SheetWriter):
    """飞书写入器：用飞书开放 API 把数据写入电子表格，并用机器人 Webhook 推送预警。

    需配置（config.yaml -> sink.feishu）：
      app_id / app_secret       —— 飞书自建应用凭证
      spreadsheet_token         —— 目标电子表格 token
      webhook_url               —— 飞书群机器人 Webhook（推送预警/回复）
    四个逻辑表映射到电子表格的四个子表（range），可在下方 RANGES 调整。
    """

    TOKEN_API = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    APPEND_API = "https://open.feishu.cn/open-apis/sheets/v2/spreadsheets/{token}/values_append"
    READ_API = "https://open.feishu.cn/open-apis/sheets/v2/spreadsheets/{token}/values/{range}"

    RANGES = {
        "video": "视频数据监控!A1",
        "alert": "点赞预警!A1",
        "comment": "评论关键词命中!A1",
        "play": "播放量!A1",
        "promo": "推广账号表!A1",      # 题目2
        "mgmt": "综合管理表!A1",       # 题目2
    }

    HEADERS = {
        "video": ["扫描时间", "数据源", "账号", "视频ID", "标题", "发布时间", "点赞", "播放", "评论数"],
        "alert": ["扫描时间", "账号", "视频ID", "标题", "上次点赞", "本次点赞", "增量", "阈值", "预警人"],
        "comment": ["扫描时间", "账号", "视频ID", "标题", "评论内容", "命中关键词", "回复话术", "处理方式"],
        "play": ["扫描时间", "账号", "视频ID", "标题", "播放量"],
        "promo": ["歌曲", "博主", "报价", "抖加", "抖加支付人", "是否打款", "打款人", "打款日期", "是否接单", "备注"],
        "mgmt": ["歌曲", "抖加花费", "垫付花费", "接单达人数", "垫付待打款笔数", "合计花费"],
    }

    def __init__(self, feishu_cfg: Dict):
        self.cfg = feishu_cfg
        self.token = None
        self._token_at = 0.0   # token 获取时间戳（tenant_access_token 有效期 2h）
        self._headered = set() # 已写表头的子表（进程内一次）
        if not feishu_cfg.get("app_id") or not feishu_cfg.get("spreadsheet_token"):
            raise RuntimeError(
                "FeishuWriter 需要 app_id / spreadsheet_token；"
                "请在 config.yaml 的 sink.feishu 中配置，或改用 sink.type=local。"
            )

    def _get_token(self, force: bool = False) -> str:
        """获取 tenant_access_token 并缓存；临近过期（<5min）自动重取，长跑不挂 401。"""
        import requests

        if (not force and self.token
                and time.time() - self._token_at < 7200 - 300):
            return self.token
        r = requests.post(
            self.TOKEN_API,
            json={"app_id": self.cfg["app_id"], "app_secret": self.cfg["app_secret"]},
            timeout=10,
        )
        data = r.json()
        if data.get("code") != 0:
            raise RuntimeError(f"获取 tenant_access_token 失败：{data}")
        self.token = data["tenant_access_token"]
        self._token_at = time.time()
        return self.token

    @net_retry
    def _append_values(self, key: str, rows: List[list]):
        import requests

        self._ensure_headers(key)
        token = self._get_token()
        url = self.APPEND_API.format(token=self.cfg["spreadsheet_token"])
        r = requests.post(
            url,
            json={"range": self.RANGES[key], "values": rows, "valueRenderOption": "ToRawValue"},
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        if r.status_code == 401:   # token 意外失效：强制刷新后原地重试一次
            token = self._get_token(force=True)
            r = requests.post(
                url,
                json={"range": self.RANGES[key], "values": rows,
                      "valueRenderOption": "ToRawValue"},
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
            )
        r.raise_for_status()
        # 飞书业务错误可能 HTTP 200 但 code != 0，必须显式校验
        data = r.json()
        if data.get("code") not in (0, None):
            raise RuntimeError(f"飞书写入失败（{self.RANGES[key]}）：code={data.get('code')} msg={data.get('msg')}")

    def _ensure_headers(self, key: str):
        """补表头：跨进程安全——先读子表第一行比对，已是表头就跳过，
        避免 setup_feishu 写过一次、新进程又 append 一遍造成双表头。"""
        if key in self._headered:
            return
        import requests
        from urllib.parse import quote

        token = self._get_token()
        title = self.RANGES[key].split("!")[0]
        rng = quote(f"{title}!A1:Z1")
        r = requests.get(
            self.READ_API.format(token=self.cfg["spreadsheet_token"], range=rng),
            headers={"Authorization": f"Bearer {token}"}, timeout=10)
        first: list = []
        if r.ok and r.json().get("code") == 0:
            values = r.json().get("data", {}).get("valueRange", {}).get("values")
            if values and values[0]:
                first = [str(c) if not isinstance(c, (list, dict)) else str(c)
                         for c in values[0]]
        head = self.HEADERS[key]
        if first[:len(head)] == head:
            self._headered.add(key)
            return
        r2 = requests.post(
            self.APPEND_API.format(token=self.cfg["spreadsheet_token"]),
            json={"range": self.RANGES[key], "values": [head],
                  "valueRenderOption": "ToRawValue"},
            headers={"Authorization": f"Bearer {token}"}, timeout=10)
        if r2.ok and r2.json().get("code") == 0:
            self._headered.add(key)

    def write_video_stats(self, videos: List[Video], scan_time: str,
                          data_source: str = "live"):
        rows = [[scan_time, data_source, v.account, v.aweme_id, v.title,
                 v.publish_time, v.likes, v.play_count, v.comments_count]
                for v in videos]
        if rows:
            self._append_values("video", rows)

    def write_like_alerts(self, alerts: List[LikeAlert]):
        rows = [[a.scan_time, a.account, a.aweme_id, a.title, a.prev_likes,
                 a.cur_likes, a.delta, a.threshold, a.warned_person] for a in alerts]
        if rows:
            self._append_values("alert", rows)

    def write_comment_hits(self, hits: List[CommentHit]):
        rows = [[h.scan_time, h.account, h.aweme_id, h.title, h.comment_text,
                 h.matched_keyword, h.reply_text, h.action] for h in hits]
        if rows:
            self._append_values("comment", rows)

    def write_play_records(self, plays: List[PlayRecord]):
        rows = [[p.scan_time, p.account, p.aweme_id, p.title, p.play_count] for p in plays]
        if rows:
            self._append_values("play", rows)

    # ---- 题目2（辅助）：推广账号表 / 综合管理表写入飞书 ----
    def write_promotion_rows(self, rows: List[list]):
        if rows:
            self._append_values("promo", rows)

    def write_management_rows(self, rows: List[list]):
        if rows:
            self._append_values("mgmt", rows)
