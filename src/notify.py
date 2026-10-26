from __future__ import annotations

from src.models import CommentHit, LikeAlert
from src.utils import get_logger, net_retry

log = get_logger()


@net_retry
def _post_webhook(url: str, payload: dict):
    """飞书自定义机器人 Webhook 推送（指数退避重试 2s→4s→8s×3）。"""
    import requests  # 延迟导入

    r = requests.post(url, json=payload, timeout=5)
    r.raise_for_status()


def _alert_card(alert: LikeAlert) -> dict:
    """构造抖加加热预警的飞书交互式卡片（带人工确认按钮）。

    注意：自定义机器人 Webhook 只能"发"卡片；按钮点击回调需要
    飞书开放平台应用配置"消息卡片请求网址"指向 card_server.py
    （python main.py --card-server 启动），回调落库 SQLite boost_decisions 表。
    """
    value = {"aweme_id": alert.aweme_id, "account": alert.account, "title": alert.title}
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "red",
            "title": {"tag": "plain_text",
                      "content": f"🔥 抖加加热预警 · {alert.account}"},
        },
        "elements": [
            {"tag": "div",
             "fields": [
                 {"is_short": True, "text": {"tag": "lark_md",
                  "content": f"**视频**\n《{alert.title}》"}},
                 {"is_short": True, "text": {"tag": "lark_md",
                  "content": f"**点赞增量**\n{alert.prev_likes} → {alert.cur_likes}"
                             f"（+{alert.delta} > 阈值 {alert.threshold}）"}},
             ]},
            {"tag": "div",
             "text": {"tag": "lark_md",
                      "content": f"请**{alert.warned_person}**确认是否加热："}},
            {"tag": "hr"},
            {"tag": "action", "actions": [
                {"tag": "button", "type": "primary",
                 "text": {"tag": "plain_text", "content": "✅ 同意加热"},
                 "value": {**value, "action": "approve"}},
                {"tag": "button", "type": "danger",
                 "text": {"tag": "plain_text", "content": "❌ 驳回"},
                 "value": {**value, "action": "reject"}},
            ]},
            {"tag": "note", "elements": [
                {"tag": "plain_text",
                 "content": f"视频ID {alert.aweme_id} · 点击按钮即写入人工确认记录（SQLite）"}]},
        ],
    }


def notify_alert(alert: LikeAlert, webhook_url: str = "",
                 use_card: bool = True):
    log.warning(
        "【抖加加热预警】账号「%s」视频《%s》点赞 %d → %d（增量 %d > 阈值 %d），"
        "请 %s 及时做抖加加热！",
        alert.account, alert.title, alert.prev_likes, alert.cur_likes,
        alert.delta, alert.threshold, alert.warned_person)
    if not webhook_url:
        return
    try:
        if use_card:
            # 交互式卡片：带「✅ 同意加热 / ❌ 驳回」按钮（人工确认机制）
            _post_webhook(webhook_url, {"msg_type": "interactive",
                                        "card": _alert_card(alert)})
        else:
            _post_webhook(webhook_url, {"msg_type": "text", "content": {"text": (
                f"【抖加加热预警】账号「{alert.account}」视频《{alert.title}》\n"
                f"点赞 {alert.prev_likes} → {alert.cur_likes}"
                f"（增量 {alert.delta} > 阈值 {alert.threshold}）\n"
                f"请 {alert.warned_person} 及时做抖加加热！")}})
    except Exception as e:
        log.error("飞书 Webhook 推送预警失败（已重试）：%s", e)


def notify_text(text: str, webhook_url: str = ""):
    """通用纯文本推送（供 Master-Agent 定时报告等复用，同样带重试）。"""
    if not webhook_url:
        log.info("（无 webhook，仅日志）\n%s", text)
        return
    try:
        _post_webhook(webhook_url, {"msg_type": "text", "content": {"text": text}})
    except Exception as e:
        log.error("飞书 Webhook 推送失败（已重试）：%s", e)


def notify_reply(hit: CommentHit, webhook_url: str = ""):
    log.info("【评论自动回复】账号「%s」《%s》| 评论：%s（命中：%s）| 回复：%s",
             hit.account, hit.title, hit.comment_text,
             hit.matched_keyword, hit.reply_text)
    if webhook_url:
        try:
            _post_webhook(webhook_url, {"msg_type": "text", "content": {"text": (
                f"【评论自动回复】账号「{hit.account}」《{hit.title}》\n"
                f"用户评论：{hit.comment_text}（命中：{hit.matched_keyword}）\n"
                f"已回复：{hit.reply_text}")}})
        except Exception as e:
            log.error("飞书 Webhook 推送回复失败（已重试）：%s", e)


def _reply_confirm_card(hit: CommentHit) -> dict:
    """半自动模式：自动生成的回复推卡片，人工点「同意发送」后才真实提交抖音。

    按钮回调由 card_server 落库 reply_approvals 表（send_reply / skip_reply），
    下一轮扫描时 Monitor 统一执行已批准的回复——效率与账号安全的平衡点。
    """
    value = {"comment_id": hit.comment_id, "aweme_id": hit.aweme_id}
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "orange",
            "title": {"tag": "plain_text",
                      "content": f"💬 回复待确认 · {hit.account}"},
        },
        "elements": [
            {"tag": "div", "fields": [
                {"is_short": True, "text": {"tag": "lark_md",
                 "content": f"**视频**\n《{hit.title}》"}},
                {"is_short": True, "text": {"tag": "lark_md",
                 "content": f"**命中关键词**\n{hit.matched_keyword}"}},
            ]},
            {"tag": "div", "text": {"tag": "lark_md",
             "content": f"**用户评论**：{hit.comment_text}\n"
                        f"**拟自动回复**：{hit.reply_text}"}},
            {"tag": "hr"},
            {"tag": "action", "actions": [
                {"tag": "button", "type": "primary",
                 "text": {"tag": "plain_text", "content": "📤 同意发送"},
                 "value": {**value, "action": "send_reply"}},
                {"tag": "button", "type": "danger",
                 "text": {"tag": "plain_text", "content": "✖️ 不发送"},
                 "value": {**value, "action": "skip_reply"}},
            ]},
            {"tag": "note", "elements": [
                {"tag": "plain_text",
                 "content": "半自动模式：批准后由程序下一轮扫描时提交抖音（风控限速内）"}]},
        ],
    }


def notify_reply_confirm(hit: CommentHit, webhook_url: str = ""):
    """半自动模式入口：推送「📤 同意发送 / ✖️ 不发送」确认卡片。"""
    log.info("【回复待人工确认】账号「%s」《%s》| 评论：%s（命中：%s）| 拟回复：%s",
             hit.account, hit.title, hit.comment_text,
             hit.matched_keyword, hit.reply_text)
    if not webhook_url:
        return
    try:
        _post_webhook(webhook_url, {"msg_type": "interactive",
                                    "card": _reply_confirm_card(hit)})
    except Exception as e:
        log.error("飞书 Webhook 推送回复确认卡片失败（已重试）：%s", e)
