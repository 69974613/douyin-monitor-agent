from __future__ import annotations

import copy
import os


DEFAULT_CONFIG = {
    "mode": "demo",  # demo | live
    "monitor": {
        "accounts": [
            "卡带森林", "卡带森林（发小）", "卡带森林的小马甲",
            "卡带森林（兄弟）", "佳佳超有才",   # 题目"测试账号表格"原文账号
        ],
        "within_days": 3,
        "schedule_times": ["12:00", "18:00", "22:00"],
        "demo_interval_seconds": 180,      # 题目规定演示间隔：3 分钟
        "demo_time_scale": 900,            # 快速演示时 1s 真实时间 ≈ 15min 模拟时间
        "demo_fast": True,
        "demo_fast_iterations": 4,
        "demo_fast_interval_seconds": 2,
        "demo_max_scans": 0,               # 3 分钟演示模式最大扫描次数（0=不限；防现场忘停）
    },
    "alert": {
        "like_threshold": 300,             # 题目规定阈值
        "demo_like_threshold": 300,        # 快速演示阈值（时间加速 900 倍，增量可达 300）
        "demo_slow_like_threshold": 20,    # 3 分钟真实间隔演示阈值（增量仅约 17~40，题目备注允许下调）
        "warned_person": "测试者",
    },
    # 强意图：直接自动回复；弱意图：仅记录、转人工（避免单字"歌"误伤）
    "keywords": {
        "strong": ["BGM", "求歌名", "什么歌", "什么歌曲", "这首歌叫什么歌", "背景音乐"],
        "weak": ["好听", "歌"],
    },
    "song": {"name": "你是我的仰望", "singer": "爆火音乐"},
    "reply_templates": [
        "歌曲是{singer}的《{song}》~",
        "好听的歌是{singer}的{song}",
        "完整版可听 {singer}的{song}",
        "{singer}的{song}",
        "{song}-{singer}",
        "是{singer}的《{song}》",
    ],
    "sink": {
        "type": "local",  # local | feishu
        "output_dir": "output",
        "feishu": {
            "app_id": "",
            "app_secret": "",
            "spreadsheet_token": "",
            "webhook_url": "",
        },
    },
    # 题目2 Sub-Agent 的 LLM 兜底解析（OpenAI 兼容接口；api_key 留空或解析全成功时不调用）
    "agent2": {
        "enabled": True,
        "summary_time": "23:00",
        "messages_file": "",
        # 《推广账号表》报价列（题目物料截图）：报价 ≠ 垫付金额，独立维护
        "quotes": {
            "初秋": 400, "艳红": 700, "唐山第一女泵工": 700, "戎大姨": 800,
            "高高": 1000, "葵花夫妇": 1000, "张栋梁": 100, "@@陈三": 700,
        },
        "llm": {
            "base_url": "https://api.deepseek.com",
            "api_key": "",            # 也可用环境变量 DEEPSEEK_API_KEY
            "model": "deepseek-chat",
        },
    },
    "douyin_cookie": "",
    "sec_uids": {},
    "notify": {
        "use_card": True,
        "reply_confirm": False,    # 半自动模式：回复需飞书卡片人工批准后才真实发送
        "card_callback": {"host": "0.0.0.0", "port": 7788},
    },
}


def load_config(path: str | None = None) -> dict:
    cfg = copy.deepcopy(DEFAULT_CONFIG)   # 深拷贝避免篡改默认值
    if path and os.path.exists(path):
        try:
            import yaml  # type: ignore

            with open(path, "r", encoding="utf-8") as f:
                user = yaml.safe_load(f) or {}
            _deep_update(cfg, user)
        except Exception as e:
            # 配置读取失败绝不能静默——否则飞书凭证/阈值悄悄失效，排查极难
            import logging
            logging.getLogger("douyin_agent").warning(
                "配置文件 %s 读取失败，使用内置默认配置：%s", path, e)
    return cfg


def _deep_update(base: dict, override: dict):
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_update(base[k], v)
        else:
            base[k] = v
