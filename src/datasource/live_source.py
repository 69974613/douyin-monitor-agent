from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from src.datasource.base import DouyinDataSource
from src.models import Comment, Video
from src.utils import get_logger, net_retry

log = get_logger()


class LiveDouyinSource(DouyinDataSource):
    """真实抖音数据源：Playwright 接管浏览器，拦截页面网络请求的接口返回包。

    思路（对标 JD 浏览器自动化要求）：
      1. 启动 Chromium（可注入登录 Cookie），打开博主主页 / 视频页；
      2. 注册 response 监听，匹配抖音前端调用的官方接口：
         - 用户作品：  /aweme/v1/web/aweme/post/
         - 视频详情：  /aweme/v1/web/aweme/detail/
         - 评论列表：  /aweme/v1/web/comment/list/
      3. 滚动触发分页加载，被动收割返回 JSON——无需逆向 X-Bogus 签名
        （签名由抖音前端 JS 自己完成），稳定性远高于纯 requests 逆向。

    资源开销控制（生产要点）：
      - 整个数据源生命周期只开 **1 个 context + 1 个常驻 page**，
        每次采集复用同一 page 导航，杜绝频繁开关 Page 的内存抖动；
      - 同一视频的详情与评论在一次页面访问中同时收割
        （get_video_with_comments），避免对同一 URL goto 两次；
      - 备选方案：context.request 直接发 API 请求（免开页面），
        但需自行处理签名，故仅作为注释保留思路。

    安装：pip install playwright && playwright install chromium
    可选登录：将浏览器导出的 Cookie 字符串传入 cookie 参数。
    """

    POST_API_RE = re.compile(r"/aweme/v1/web/aweme/post/")
    DETAIL_API_RE = re.compile(r"/aweme/v1/web/aweme/detail/")
    COMMENT_API_RE = re.compile(r"/aweme/v1/web/comment/list/")

    def __init__(self, cookie: str = "", sec_uids: Optional[Dict[str, str]] = None,
                 headless: bool = True):
        self.cookie = cookie
        self.sec_uids = sec_uids or {}
        self.headless = headless
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None   # 常驻单页面：全生命周期复用
        # 风控状态（reply_comment 写操作保护）
        self._reply_date = ""      # 当日日期（跨天自动重置计数）
        self._reply_count = 0      # 今日已回复条数
        self.risk_halt = False     # 验证码/风控页熔断：触发后拒绝一切写操作，转人工

    def _reply_risk_ok(self) -> bool:
        """回复前风控自检：熔断标志 + 每日上限。通过返回 True。"""
        import datetime as _dt

        today = _dt.date.today().isoformat()
        if self._reply_date != today:
            self._reply_date, self._reply_count = today, 0
        if self.risk_halt:
            log.error("[live] 风控熔断中（此前检测到验证码/风控页），回复转人工")
            return False
        if self._reply_count >= self.DAILY_REPLY_LIMIT:
            log.error("[live] 今日回复已达上限 %d 条，剩余转人工（防刷量封号）",
                      self.DAILY_REPLY_LIMIT)
            return False
        return True

    @staticmethod
    def _looks_like_risk_page(page) -> bool:
        """检测验证码 / 风控页特征（TODO(校准)：选择器随版本可能变动）。"""
        for sel in ("[class*='captcha']", "[id*='captcha']",
                    "[class*='verify-wrap']", "[class*='nc_']"):
            try:
                if page.locator(sel).count() > 0:
                    return True
            except Exception:
                pass
        return False

    def _ensure_browser(self):
        if self._page is not None:
            return
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as e:
            raise RuntimeError(
                "live 模式需要 Playwright：pip install playwright && playwright install chromium"
            ) from e
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self.headless)
        self._context = self._browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
            viewport={"width": 1440, "height": 900})
        if self.cookie:
            self._context.add_cookies(self._parse_cookie(self.cookie))
        self._page = self._context.new_page()

    @staticmethod
    def _parse_cookie(cookie_str: str) -> List[dict]:
        cookies = []
        for kv in cookie_str.split(";"):
            if "=" in kv:
                k, v = kv.strip().split("=", 1)
                cookies.append({"name": k, "value": v,
                                "domain": ".douyin.com", "path": "/"})
        return cookies

    def _collect_api(self, url: str,
                     api_res: List[Tuple[re.Pattern, str]],
                     wait_ms: int = 8000) -> Dict[str, List[dict]]:
        """在常驻 page 上导航到 url，拦截匹配各 api_re 的接口返回包，滚动触发加载。

        api_res: [(编译正则, 通道名), ...]；返回 {通道名: [payload, ...]}。
        每次调用结束移除监听器，避免监听器跨采集累积泄漏。
        """
        self._ensure_browser()
        payloads: Dict[str, List[dict]] = {name: [] for _, name in api_res}

        def on_response(resp):
            for pat, name in api_res:
                if pat.search(resp.url):
                    try:
                        payloads[name].append(resp.json())
                    except Exception:
                        pass

        page = self._page
        page.on("response", on_response)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(wait_ms)
            for _ in range(3):   # 滚动触发分页
                page.mouse.wheel(0, 2000)
                page.wait_for_timeout(1500)
        finally:
            page.remove_listener("response", on_response)
        return payloads

    def get_recent_videos(self, account: str, within_days: int) -> List[Video]:
        sec_uid = self.sec_uids.get(account)
        if not sec_uid:
            log.warning("账号 %s 未配置 sec_uid，跳过", account)
            return []
        url = f"https://www.douyin.com/user/{sec_uid}?showTab=post"
        payloads = self._collect_api(url, [(self.POST_API_RE, "post")])["post"]
        out: List[Video] = []
        cutoff = datetime.now() - timedelta(days=within_days)
        for data in payloads:
            for aw in data.get("aweme_list", []):
                create_ts = int(aw.get("create_time", 0))
                pub = datetime.fromtimestamp(create_ts) if create_ts else None
                if pub and pub < cutoff:
                    continue
                stat = aw.get("statistics", {})
                out.append(Video(
                    aweme_id=str(aw.get("aweme_id")),
                    account=account,
                    title=aw.get("desc", ""),
                    publish_time=pub.strftime("%Y-%m-%d %H:%M:%S") if pub else "",
                    likes=int(stat.get("digg_count", 0)),
                    play_count=int(stat.get("play_count", 0)),
                    comments_count=int(stat.get("comment_count", 0))))
        log.info("[live] %s 拦截到 %d 个作品（近 %d 天）", account, len(out), within_days)
        return out

    def get_video_with_comments(self, account: str, aweme_id: str
                                ) -> Tuple[Video, List[Comment]]:
        """一次页面访问同时收割视频详情与评论（生产优化：同一 URL 只 goto 一次）。"""
        url = f"https://www.douyin.com/video/{aweme_id}"
        payloads = self._collect_api(url, [
            (self.DETAIL_API_RE, "detail"), (self.COMMENT_API_RE, "comment")])

        video: Optional[Video] = None
        for data in payloads["detail"]:
            aw = data.get("aweme_detail") or {}
            if aw.get("aweme_id"):
                stat = aw.get("statistics", {})
                video = Video(
                    aweme_id=str(aw.get("aweme_id")), account=account,
                    title=aw.get("desc", ""), publish_time="",
                    likes=int(stat.get("digg_count", 0)),
                    play_count=int(stat.get("play_count", 0)),
                    comments_count=int(stat.get("comment_count", 0)))
                break
        if video is None:
            raise RuntimeError(f"[live] 未能拦截到视频 {aweme_id} 的详情接口返回")

        comments: List[Comment] = []
        for data in payloads["comment"]:
            for c in data.get("comments") or []:
                comments.append(Comment(
                    comment_id=str(c.get("cid")),
                    aweme_id=aweme_id, account=account,
                    text=c.get("text", ""),
                    user=c.get("user", {}).get("nickname", "匿名")))
        log.info("[live] 视频 %s 单次访问收割：详情 1 + 评论 %d 条", aweme_id, len(comments))
        return video, comments

    # ---- 单项接口（兼容 base 抽象；内部委托 get_video_with_comments）----
    def get_video_stats(self, account: str, aweme_id: str) -> Video:
        return self.get_video_with_comments(account, aweme_id)[0]

    def get_comments(self, account: str, aweme_id: str) -> List[Comment]:
        return self.get_video_with_comments(account, aweme_id)[1]

    # ---- 真实自动评论回复（生产骨架 + 风控加固）----
    REPLY_COOLDOWN_S = 3      # 风控限速下限：两次回复最小间隔
    REPLY_DELAY_MAX_S = 8     # 随机延迟上限：模拟真人节奏，实际延迟 = U(cooldown, max)
    DAILY_REPLY_LIMIT = 50    # 每日回复上限：超过即熔断转人工，防刷量封号

    def reply_comment(self, aweme_id: str, comment_id: str, text: str,
                      comment_text: str = "") -> bool:
        """真实回复评论：Playwright 打开视频页 → 定位目标评论 → 点回复 → 填写 → 提交。

        ⚠️ 风控加固：
        - 回复前自检：熔断标志 + 每日上限（DAILY_REPLY_LIMIT）；
        - 定位策略：按原评论文本（comment_text）filter(has_text=...) 锁定目标评论，
          找不到直接返回 False 转人工——绝不 fallback 点第一条（会回复错人）；
        - 提交后检测验证码/风控页，命中则置位 risk_halt 熔断（后续回复全部转人工）；
        - 强制随机延迟 U(REPLY_COOLDOWN_S, REPLY_DELAY_MAX_S) 模拟真人节奏；
        - 失败返回 False，由调用方决定转人工（绝不静默丢弃）。
        """
        import random
        import time as _time

        if not self._reply_risk_ok():
            return False
        self._ensure_browser()
        page = self._page
        try:
            page.goto(f"https://www.douyin.com/video/{aweme_id}",
                      wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(5000)
            if self._looks_like_risk_page(page):
                self.risk_halt = True
                log.error("[live] 检测到验证码/风控页，熔断一切自动回复，请人工处理")
                return False
            # 按原评论文本定位目标评论条目（TODO(校准)：data-e2e 随版本可能变动）
            target = comment_text or comment_id   # 无文本时退化为 cid 精确匹配
            item = page.locator('div[data-e2e="comment-item"]').filter(
                has_text=target).first
            if item.count() == 0:
                log.error("[live] 未找到目标评论 %s（已删除或选择器需校准），转人工", comment_id)
                return False
            # TODO(校准)：点击"回复" → 填入文本 → 提交
            reply_btn = item.locator('div[data-e2e="comment-reply"]').first
            reply_btn.click()
            box = page.locator('div[data-e2e="comment-input"] textarea, '
                               'div[data-e2e="comment-input"] [contenteditable="true"]').first
            box.fill(text)
            box.press("Enter")
            page.wait_for_timeout(2000)
            if self._looks_like_risk_page(page):   # 提交后二次确认
                self.risk_halt = True
                log.error("[live] 提交后出现验证码/风控页，熔断并转人工")
                return False
            self._reply_count += 1
            log.info("[live] 回复已提交（今日第 %d/%d 条）：%s ← %s",
                     self._reply_count, self.DAILY_REPLY_LIMIT, comment_id, text)
            _time.sleep(random.uniform(self.REPLY_COOLDOWN_S, self.REPLY_DELAY_MAX_S))
            return True
        except Exception as e:
            log.error("[live] 回复评论 %s 失败（转人工）：%s", comment_id, e)
            return False

    def close(self):
        if self._page:
            try:
                self._page.close()
            except Exception:
                pass
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()
