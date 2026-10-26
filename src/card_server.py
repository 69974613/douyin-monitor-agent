from __future__ import annotations

"""飞书消息卡片回调服务：接收「✅ 同意加热 / ❌ 驳回」按钮点击事件。

飞书侧配置（开放平台 → 应用 → 事件与回调 → 消息卡片请求网址）填：
    http://<本机公网地址>:7788/feishu/card
协议（飞书卡片回调 v2）：
    1. 首次配置校验：POST {"challenge": "...", "type": "url_verification"}
       → 原样返回 {"challenge": "..."}
    2. 按钮点击：schema 2.0 为 {"event": {"action": {"value": {...}}}}，
       旧版为 {"action": {"value": {...}}} —— 两种都兼容解析。
按钮 value 约定：
    {"action": "approve|reject", "aweme_id": "...", ...}          —— 抖加加热确认
    {"action": "send_reply|skip_reply", "comment_id": "...", ...} —— 半自动回复确认

纯标准库实现（http.server），无新增依赖；决策落 SQLite boost_decisions 表，
主程序可随时读取人工确认状态 —— 这就是 JD 里"人工确认机制"的闭环。
安全说明：
    已支持回调验签（可选）：在飞书后台配置 Encrypt Key 并写入 config.yaml
    notify.card_callback.encrypt_key 后，服务按官方算法校验
    X-Lark-Signature = SHA256(timestamp + nonce + encrypt_key + body)，
    校验失败返回 403。未配置时跳过验签（演示模式）。
    已知限制：开启 Encrypt Key 后飞书会发送 AES-CBC 加密包（{"encrypt": ...}），
    解密需第三方库（pycryptodome），演示版未实现——检测到加密包会明确提示。
    生产部署还应：服务前置 Nginx 限流 / IP 白名单。演示环境仅监听内网使用。
"""

import hashlib
import json
import os
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from src.store import StateStore
from src.utils import get_logger

log = get_logger()


class CardCallbackHandler(BaseHTTPRequestHandler):
    store: StateStore = None  # 启动时注入
    encrypt_key: str = ""     # 启动时注入；为空则不启用验签

    def _verify_signature(self, raw: bytes) -> bool:
        """飞书官方验签算法（纯标准库 hashlib，无需 pycryptodome）：
        将 timestamp、nonce、encrypt_key、body 四段按顺序拼接后取 SHA256 十六进制，
        与请求头 X-Lark-Signature 比对。未配置 encrypt_key 时直接放行（演示模式）。"""
        if not self.encrypt_key:
            return True
        ts = self.headers.get("X-Lark-Request-Timestamp", "")
        nonce = self.headers.get("X-Lark-Request-Nonce", "")
        sig = self.headers.get("X-Lark-Signature", "")
        expected = hashlib.sha256(
            (ts + nonce + self.encrypt_key + raw.decode("utf-8", "replace"))
            .encode("utf-8")).hexdigest()
        ok = bool(sig) and sig == expected
        if not ok:
            log.warning("飞书回调验签失败：X-Lark-Signature=%s（期望 %s…）——拒绝处理",
                        sig, expected[:16])
        return ok

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) or b"{}"

        # 0) 回调验签（配置了 Encrypt Key 才启用；失败直接 403，不解析不落库）
        if not self._verify_signature(raw):
            self.send_response(403)
            self.end_headers()
            return

        try:
            body = json.loads(raw)
        except Exception:
            body = {}

        # 0.5) 加密回调包：开启 Encrypt Key 后飞书发 {"encrypt": "..."}（AES-CBC），
        # 解密需第三方库，演示版未实现——明确提示而非静默忽略
        if "encrypt" in body:
            # TODO: 若需支持加密回调，此处应为（需 pip install pycryptodome）：
            #   from Crypto.Cipher import AES; import base64
            #   key = hashlib.sha256(self.encrypt_key.encode()).digest()
            #   plaintext = unpad(AES.new(key, AES.MODE_CBC, iv=data[:16]).decrypt(base64.b64decode(body["encrypt"]))[16:], 16)
            # 解密后再走 challenge 回显 / 按钮解析
            log.warning("收到加密回调包（encrypt 字段），需 pycryptodome AES 解密；"
                        "请在飞书后台关闭'加密策略'或自行实现 decrypt 后重试")
            self._reply({"code": 0, "msg": "encrypted payload not supported in demo"})
            return

        # 1) 飞书网址配置校验（challenge 回显）
        if body.get("type") == "url_verification" or "challenge" in body:
            self._reply({"challenge": body.get("challenge", "")})
            log.info("卡片回调地址校验通过（challenge 回显）")
            return

        # 2) 按钮点击事件（兼容 v2 / v1 两种 schema）
        action = (body.get("event", {}).get("action")
                  or body.get("action") or {})
        value = action.get("value") or {}
        op = value.get("action", "")
        aweme_id = value.get("aweme_id", "")
        operator = (body.get("event", {}).get("operator", {})
                    .get("open_id", "") or "feishu_user")
        if op in ("approve", "reject") and aweme_id:
            decision = "已同意加热" if op == "approve" else "已驳回"
            self.store.set_boost_decision(
                aweme_id, decision,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"), operator)
            log.warning("【人工确认】视频 %s（%s）→ %s（操作人 %s）",
                        aweme_id, value.get("title", ""), decision, operator)
            self._reply({"code": 0})
        elif op in ("send_reply", "skip_reply") and value.get("comment_id"):
            # 半自动回复确认：批准后由 Monitor 下一轮扫描统一提交抖音
            status = "approved" if op == "send_reply" else "已跳过"
            self.store.set_reply_decision(
                value["comment_id"], status,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"), operator)
            log.warning("【回复人工确认】评论 %s → %s（操作人 %s）",
                        value["comment_id"], status, operator)
            self._reply({"code": 0})
        else:
            self._reply({"code": 0, "msg": "ignored"})

    def _reply(self, obj: dict):
        data = json.dumps(obj).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):  # 静默默认 stderr 访问日志，统一走 logger
        pass


def run_card_server(db_path: str, host: str = "0.0.0.0", port: int = 7788,
                    encrypt_key: str = ""):
    CardCallbackHandler.store = StateStore(db_path)
    CardCallbackHandler.encrypt_key = encrypt_key
    srv = ThreadingHTTPServer((host, port), CardCallbackHandler)
    log.info("飞书卡片回调服务已启动：%s:%d（决策写入 %s，验签：%s）",
             host, port, db_path, "已启用" if encrypt_key else "未启用（未配置 Encrypt Key）")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()
        log.info("卡片回调服务已停止")
