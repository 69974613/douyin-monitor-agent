from __future__ import annotations

import time
from datetime import datetime
from typing import Dict, List, Optional

from src.agent2 import run_agent2_daily
from src.comments import scan_comments
from src.datasource.base import DouyinDataSource
from src.models import CommentHit, LikeAlert, PlayRecord, ScanContext, Video
from src.notify import notify_alert, notify_reply, notify_reply_confirm
from src.sink.base import SheetWriter
from src.store import StateStore
from src.utils import get_logger


class Monitor:
    """题目1 核心：抖音数据监控 Agent。

    一个扫描周期（scan_once）完成：
      1. 拉取各账号近 3 天视频；
      2. 抓取实时点赞 / 播放量；
      3. 点赞增量 > 阈值 → 抖加加热预警（通知测试者）；
      4. 扫描评论区：强意图关键词自动回复（SQLite 去重，重启不重复回复），
         弱意图仅记录转人工；
      5. 采集播放量；
      6. 全部写入飞书（本地镜像）。
    """

    def __init__(self, cfg: dict, source: DouyinDataSource, sink: SheetWriter,
                 store: StateStore, webhook_url: str = ""):
        self.cfg = cfg
        self.source = source
        self.sink = sink
        self.store = store
        self.webhook_url = webhook_url
        self.use_card = bool(cfg.get("notify", {}).get("use_card", True))
        # 半自动模式：自动生成回复 → 飞书卡片人工批准 → 下轮扫描统一真实发送
        # （live 风控的稳妥生产方案；mock 演示不受影响，仍走自动回复(模拟)）
        self.reply_confirm = bool(cfg.get("notify", {}).get("reply_confirm", False))
        self.log = get_logger()
        self.threshold = self._resolve_threshold()

    def _resolve_threshold(self) -> int:
        a = self.cfg["alert"]
        if self.cfg.get("mode") == "demo":
            if self.cfg["monitor"].get("demo_fast", True):
                # 快速演示：时间加速 900 倍，增量可达阈值 300
                return int(a.get("demo_like_threshold", a["like_threshold"]))
            # 题目原文 3 分钟真实间隔：模拟速率下增量仅约 17~40 赞，
            # 按题目备注"演示可调整阈值"下调，否则永远不预警（面试现场事故点）
            return int(a.get("demo_slow_like_threshold", 20))
        return int(a["like_threshold"])

    @property
    def data_source_label(self) -> str:
        """写入表格的数据源标识：面试展示时飞书表里能一眼分辨 mock / live。"""
        return "mock(模拟)" if getattr(self.source, "is_mock", False) else "live"

    def scan_once(self) -> ScanContext:
        ctx = ScanContext()
        self._process_approved_replies()   # 半自动模式：先执行上轮人工批准的回复
        within = self.cfg["monitor"]["within_days"]
        kw = self.cfg["keywords"]
        strong, weak = kw["strong"], kw["weak"]
        tpls = self.cfg["reply_templates"]
        song = self.cfg["song"]

        for acc in self.cfg["monitor"]["accounts"]:
            # 账号级异常隔离：live 抓取单账号失败不影响其他账号
            try:
                videos = self.source.get_recent_videos(acc, within)
            except Exception as e:
                self.log.error("账号 %s 视频列表拉取失败（隔离，继续下一账号）：%s", acc, e)
                continue
            for v in videos:
                # 视频级异常隔离：live 模式单视频抓取失败中断整轮扫描是不可接受的
                try:
                    self._process_video(acc, v, strong, weak, tpls, song, ctx)
                except Exception as e:
                    self.log.error("视频 %s（%s）处理失败（隔离，继续）：%s",
                                   v.aweme_id, acc, e)

        # 6) 写入飞书（本地镜像）；数据源标识列让飞书表一眼分辨 mock / live
        self.sink.write_video_stats(ctx.videos, ctx.scan_time,
                                    data_source=self.data_source_label)
        self.sink.write_like_alerts(ctx.alerts)
        self.sink.write_comment_hits(ctx.hits)
        self.sink.write_play_records(ctx.plays)

        # 弱意图（好听/歌）：按题目"应进行预警或自动回复"，不自动回复防误伤，
        # 但必须推送飞书转人工预警（每轮汇总一条，避免刷屏）
        weak_hits = [h for h in ctx.hits if not h.action.startswith("已自动回复")]
        if weak_hits:
            from src.notify import notify_text

            lines = [f"【弱意图转人工预警】本轮 {len(weak_hits)} 条评论疑似求歌但不宜自动回复，请人工确认："]
            for h in weak_hits[:5]:
                lines.append(f"· {h.account}《{h.title}》「{h.comment_text}」(命中:{h.matched_keyword})")
            if len(weak_hits) > 5:
                lines.append(f"…等共 {len(weak_hits)} 条")
            notify_text("\n".join(lines), self.webhook_url)
        return ctx

    def _process_video(self, acc: str, v: Video, strong: List[str], weak: List[str],
                       tpls: List[str], song: Dict, ctx: ScanContext):
        """处理单个视频：抓数据 → 增量预警 → 播放采集 → 评论扫描回复。"""
        # live 模式：同一次页面访问同时收割详情+评论（省一半导航开销）；
        # mock 模式无此方法，走两次独立拉取。
        batched = getattr(self.source, "get_video_with_comments", None)
        if batched is not None:
            stats, comments = batched(acc, v.aweme_id)
        else:
            stats = self.source.get_video_stats(acc, v.aweme_id)
            comments = self.source.get_comments(acc, v.aweme_id)
        ctx.videos.append(stats)

        # 3) 点赞增量预警（上次值取自 SQLite，跨重启可靠）
        prev_rec = self.store.get_prev(v.aweme_id)
        prev_likes: Optional[int] = prev_rec["likes"] if prev_rec else None
        if prev_likes is not None and (stats.likes - prev_likes) > self.threshold:
            alert = LikeAlert(
                account=acc, aweme_id=v.aweme_id, title=v.title,
                prev_likes=prev_likes, cur_likes=stats.likes,
                delta=stats.likes - prev_likes, threshold=self.threshold,
                warned_person=self.cfg["alert"]["warned_person"])
            ctx.alerts.append(alert)
            notify_alert(alert, self.webhook_url, use_card=self.use_card)
            # 人工确认预登记：卡片按钮点击后由 card_server 覆盖为最终决策
            self.store.set_boost_decision(v.aweme_id, "待确认", ctx.scan_time,
                                          alert_time=ctx.scan_time)
        # 每轮扫描对同一视频只处理一次（scan_once 内逐视频单次调用，不循环重入），
        # video_state 在轮与轮之间演进，增量 = 上一轮点赞 → 本轮点赞，不存在同轮自比
        self.store.set_video_state(v.aweme_id, stats.likes,
                                   stats.play_count, ctx.scan_time)

        # 5) 播放量采集
        ctx.plays.append(PlayRecord(
            account=acc, aweme_id=v.aweme_id, title=v.title,
            play_count=stats.play_count))

        # 4) 评论关键词扫描（已回复评论经 SQLite 去重）
        comments = [c for c in comments if not self.store.is_replied(c.comment_id)]
        hits: List[CommentHit] = scan_comments(
            comments, strong, weak, tpls, song["name"], song["singer"])
        for h in hits:
            h.title = v.title
            if h.action.startswith("已自动回复"):
                # 半自动模式：live 真实回复前必须经飞书卡片人工批准
                if self.reply_confirm and getattr(self.source, "reply_comment", None):
                    status = self.store.get_reply_status(h.comment_id)
                    if status is None:
                        self.store.stage_reply_approval(
                            h.comment_id, v.aweme_id, h.reply_text, h.scan_time)
                        notify_reply_confirm(h, self.webhook_url)
                        h.action = "待人工确认发送"
                        ctx.hits.append(h)
                    # status 非空 = 已进入人工确认流程（pending/approved/已跳过），不重复推送
                    continue
                # 真实送达：live 调 reply_comment；成功才标记已回复（失败保留，下轮重试），
                # 绝不允许"生成即标记"把评论吞掉造成假回复
                ok, simulated = self._deliver_reply(v, h)
                if not ok:
                    h.action = "回复失败-转人工"
                    ctx.hits.append(h)
                    self.log.error(
                        "强意图回复失败（未标记，下轮重试）：%s | %s | %s",
                        h.account, h.comment_text, h.reply_text)
                    continue
                h.action = "已自动回复(模拟)" if simulated else "已自动回复"
                self.store.mark_replied(h.comment_id, v.aweme_id, h.scan_time)
                notify_reply(h, self.webhook_url)
            else:
                # 弱意图：不自动回复（防误伤），标记已处理防重复记录 + 落库追踪人工处理状态
                self.store.mark_replied(h.comment_id, v.aweme_id, h.scan_time)
                self.store.record_weak_intent(
                    h.comment_id, v.aweme_id, h.comment_text,
                    h.matched_keyword, h.scan_time)
                self.log.warning(
                    "弱意图评论仅记录（不回复，转人工预警已推送）：%s | %s | %s",
                    h.account, h.comment_text, h.matched_keyword)
            ctx.hits.append(h)

    def _process_approved_replies(self):
        """半自动模式：把人工批准（approved）的回复真实提交抖音。

        发送成功 → replied_comments 标记 + 状态置"已发送"（永久去重）；
        发送失败 → 保留 approved 状态，下轮扫描重试；风控熔断由 reply_comment 内部处理。
        """
        if not (self.reply_confirm and getattr(self.source, "reply_comment", None)):
            return
        # 风控熔断：跳过本轮提交，且只推一次飞书告警（防日志/消息风暴）
        if getattr(self.source, "risk_halt", False):
            self.log.warning("数据源风控熔断中，跳过本轮自动回复提交，请人工介入")
            if not getattr(self, "_halt_notified", False):
                self._halt_notified = True
                from src.notify import notify_text

                notify_text("【风控熔断告警】抖音数据源检测到验证码/风控页，"
                            "自动回复已熔断，请人工介入处理后再恢复。", self.webhook_url)
            return
        from datetime import datetime

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for cid, aweme_id, text in self.store.approved_replies():
            try:
                ok = bool(self.source.reply_comment(aweme_id, cid, text))
            except Exception as e:
                self.log.error("已批准回复提交异常（保留批准状态，下轮重试）：%s | %s", cid, e)
                continue
            if ok:
                self.store.set_reply_decision(cid, "已发送", now, "system")
                self.store.mark_replied(cid, aweme_id, now)
                self.log.info("【半自动回复已发送】评论 %s ← %s", cid, text)
            else:
                self.log.error("已批准回复发送失败（保留批准状态，下轮重试）：%s", cid)

    def _deliver_reply(self, v: Video, h: CommentHit) -> tuple:
        """把回复真正送达数据源。返回 (是否成功, 是否模拟)。

        live：调用数据源 reply_comment 真实提交（Playwright 填写并提交）；
        mock：无 reply_comment 能力 → 返回模拟标记，不冒充真实回复；
        其他：既不能真实回复也非 mock → 视为失败转人工。
        """
        reply_fn = getattr(self.source, "reply_comment", None)
        if reply_fn is not None:
            return bool(reply_fn(v.aweme_id, h.comment_id, h.reply_text,
                                 comment_text=h.comment_text)), False
        if getattr(self.source, "is_mock", False):
            return True, True
        return False, False

    def run(self):
        m = self.cfg["monitor"]
        if self.cfg.get("mode") == "demo":
            if m.get("demo_fast"):
                iters = int(m.get("demo_fast_iterations", 4))
                # float 支持 0.2s 级间隔（int 会把 0.2 抹成 0）；倍率与间隔相乘
                # 决定每轮模拟时间跨度：0.2s × 18000 = 1 小时/轮，增量 350~800
                gap = float(m.get("demo_fast_interval_seconds", 2))
                scale = float(m.get("demo_time_scale", 900))
                self.log.info("演示快速模式：共 %d 次扫描，真实间隔 %.1fs（时间加速 %.0f 倍，等价 %d 分钟间隔）",
                              iters, gap, scale, int(gap * scale / 60))
                for i in range(iters):
                    self.log.info("--- 第 %d/%d 次扫描 ---", i + 1, iters)
                    ctx = self.scan_once()
                    self._summary(ctx)
                    if i < iters - 1:
                        time.sleep(gap)
            else:
                # 题目原文："演示的数据抓取时间间隔，可设为3分钟"——按 3 分钟真实执行；
                # demo_max_scans（或 --max-scans）控制演示时长，0 = 不限
                interval = int(m.get("demo_interval_seconds", 180))
                max_scans = int(m.get("demo_max_scans", 0))
                self.log.info("演示模式：每 %d 秒扫描一次（题目规定演示间隔 3 分钟），"
                              "阈值已自动下调至 %d（3 分钟真实间隔下增量约 17~40）",
                              interval, self.threshold)
                n = 0
                while True:
                    n += 1
                    self._summary(self.scan_once())
                    if max_scans and n >= max_scans:
                        self.log.info("已达 demo_max_scans=%d，演示结束", max_scans)
                        return
                    time.sleep(interval)
        else:
            self._schedule(m.get("schedule_times", ["12:00", "18:00", "22:00"]))

    def _schedule(self, times: List[str]):
        """生产调度：优先 APScheduler（cron 触发 12/18/22 + 题目2 的 23:00 汇总），
        缺库则退化为轮询。"""
        a2 = self.cfg.get("agent2", {})
        summary_hm = str(a2.get("summary_time", "23:00"))
        sh, sm = map(int, summary_hm.split(":"))
        try:
            from apscheduler.schedulers.blocking import BlockingScheduler

            sched = BlockingScheduler()
            for t in times:
                hh, mm = map(int, t.split(":"))
                sched.add_job(self.scan_once, "cron", hour=hh, minute=mm, id=f"scan_{t}")
            if a2.get("enabled", True):
                sched.add_job(self.run_agent2_summary, "cron", hour=sh, minute=sm,
                              id="agent2_daily_summary")
                self.log.info("生产调度模式（APScheduler）：每天 %s 扫描 + %s 题目2 汇总报告",
                              times, summary_hm)
            else:
                self.log.info("生产调度模式（APScheduler）：每天 %s 扫描", times)
            sched.start()
        except ImportError:
            self.log.warning("未安装 APScheduler，退化为轮询模式（生产建议 pip install apscheduler 或用 Crontab）")
            fired_agent2 = ""
            fired_scan = ""
            while True:
                now = datetime.now()
                hm = now.strftime("%H:%M")
                for t in times:
                    # 同一分钟只扫一次（扫描耗时漂移可能跨分钟，防重扫/漏扫标记）
                    if hm == t and fired_scan != f"{now:%Y%m%d}{t}":
                        fired_scan = f"{now:%Y%m%d}{t}"
                        self.scan_once()
                if a2.get("enabled", True) and hm == summary_hm and fired_agent2 != hm:
                    fired_agent2 = hm   # 同一分钟只触发一次
                    self.run_agent2_summary()
                time.sleep(60)

    def run_agent2_summary(self):
        """题目2 定时汇总（题目要求：晚上 23 点总结当日抖加+垫付申请）：
        Sub 解析申请 → Master 汇总对账 → 填两张表（本地+飞书） → 报告推送到飞书群。"""
        from src.notify import notify_text

        a2 = self.cfg.get("agent2", {})
        self.log.info("--- 题目2 定时汇总（%s）---", a2.get("summary_time", "23:00"))
        result = run_agent2_daily(
            out_dir=self.cfg["sink"]["output_dir"],
            messages_file=a2.get("messages_file", ""),
            llm_cfg=a2.get("llm"), quotes=a2.get("quotes"),
            feishu_cfg=self.cfg["sink"].get("feishu") if self.cfg["sink"]["type"] == "feishu" else None)
        notify_text(result["report"], self.webhook_url)
        return result

    def _summary(self, ctx: ScanContext):
        self.log.info(
            "视频采集：%d 条 | 点赞预警：%d 条 | 评论命中：%d 条（自动回复 %d / 弱意图 %d）| 播放量记录：%d 条",
            len(ctx.videos), len(ctx.alerts), len(ctx.hits),
            sum(1 for h in ctx.hits if h.action.startswith("已自动回复")),
            sum(1 for h in ctx.hits if not h.action.startswith("已自动回复")),
            len(ctx.plays))
