from __future__ import annotations

import csv
import os
import re
from typing import Dict, List, Optional

from src.agent2.models import FeeApplication, PromotionRow
from src.config import DEFAULT_CONFIG
from src.utils import get_logger, net_retry

log = get_logger()

# 正则放宽：分隔符兼容 - － —，冒号兼容中英文，"博主名/达人名"均可
DOUJIA_RE = re.compile(
    r"歌名[：:]?\s*《(.+?)》\s*[-－—]\s*(?:博主名|达人名?)\s*[：:]\s*(.+?)\s*[-－—]\s*金额[：:]?\s*[¥￥]\s*([\d.]+)")
ADVANCE_RE = re.compile(
    r"申请为【(?:达人|博主)\s*[：:]?\s*(.+?)】\s*垫付\s*[¥￥]\s*([\d.]+)\s*[（(]\s*歌曲《(.+?)》\s*[）)]")
TOTAL_RE = {"抖加": re.compile(r"今日已支付[：:]\s*[¥￥]\s*([\d.]+)"),
            "垫付": re.compile(r"今日已垫付[：:]\s*[¥￥]\s*([\d.]+)")}


def parse_applications(doujia_text: str, advance_text: str,
                       llm_cfg: Optional[Dict] = None) -> tuple:
    """两层解析：正则第一层 → 未匹配行交给 LLM 兜底 → 仍失败标记'需人工核对'。"""
    apps: List[FeeApplication] = []
    unparsed: List[str] = []

    m = re.search(r"抖加支付人[：:]\s*(.+)", doujia_text)
    payer_doujia = m.group(1).strip() if m else ""
    parsed_lines = 0
    for line in doujia_text.splitlines():
        mt = DOUJIA_RE.search(line)
        if mt:
            apps.append(FeeApplication(
                type="抖加", song=mt.group(1), blogger=mt.group(2),
                amount=float(mt.group(3)), payer=payer_doujia, date="2026-09-02"))
            parsed_lines += 1
        elif DOUJIA_RE.pattern and re.search(r"歌名", line):
            unparsed.append(f"[抖加] {line.strip()}")

    m = re.search(r"打款人[：:]\s*(.+?)\s*预计打款日期[：:]\s*(\S+)", advance_text)
    payer_advance = m.group(1).strip() if m else ""
    date_advance = m.group(2).strip() if m else ""
    for line in advance_text.splitlines():
        mt = ADVANCE_RE.search(line)
        if mt:
            apps.append(FeeApplication(
                type="垫付", song=mt.group(3), blogger=mt.group(1),
                amount=float(mt.group(2)), payer=payer_advance, date=date_advance))
            parsed_lines += 1
        elif re.search(r"垫付", line) and re.search(r"[¥￥]", line) \
                and not TOTAL_RE["垫付"].search(line):
            unparsed.append(f"[垫付] {line.strip()}")

    # LLM 兜底：仅当配置了 api_key 且确有正则啃不动的行
    log.info("正则解析完成：%d 行命中，%d 行待 LLM/人工", parsed_lines, len(unparsed))
    if unparsed:
        llm_apps = llm_extract(unparsed, llm_cfg=llm_cfg)
        if llm_apps:
            log.info("LLM 兜底解析成功 %d 条（正则未覆盖）", len(llm_apps))
            apps.extend(llm_apps)
            unparsed = []
    if unparsed:
        log.warning("以下 %d 条申请正则与 LLM 均未解析，需人工核对：%s",
                    len(unparsed), unparsed)

    # 群消息里"声称"的总额（供 Master 对账）
    m1 = TOTAL_RE["抖加"].search(doujia_text)
    m2 = TOTAL_RE["垫付"].search(advance_text)
    stated = {"抖加": float(m1.group(1)) if m1 else None,
              "垫付": float(m2.group(1)) if m2 else None}
    return apps, unparsed, stated


@net_retry
def _llm_request(base_url: str, api_key: str, model: str, prompt: str) -> str:
    """LLM HTTP 调用（网络层指数退避重试：2s→4s→8s×3，失败向上抛出）。"""
    import requests

    r = requests.post(
        f"{base_url}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"model": model, "messages": [{"role": "user", "content": prompt}],
              "temperature": 0},
        timeout=30)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def llm_extract(lines: List[str], llm_cfg: Optional[Dict] = None) -> List[FeeApplication]:
    """LLM 兜底：调用 OpenAI 兼容接口（默认 DeepSeek），Prompt 约束 JSON 输出。

    llm_cfg 优先（来自 config.yaml 加载结果），缺省回落到内置默认。
    网络抖动由 @net_retry 指数退避重试兜住；重试耗尽仍失败才静默降级为
    空列表（由调用方标记"需人工核对"），保证解析兜底不阻塞主流程。
    """
    import json as _json

    cfg = llm_cfg or DEFAULT_CONFIG["agent2"]["llm"]
    api_key = os.environ.get("DEEPSEEK_API_KEY", "") or cfg.get("api_key", "")
    if not api_key:
        return []
    prompt = (
        "从以下群消息行中提取费用申请，严格输出 JSON 数组，"
        '每项形如 {"type":"抖加|垫付","song":"歌名","blogger":"博主/达人名","amount":数字}。'
        "无法解析的行跳过。\n" + "\n".join(lines))
    try:
        content = _llm_request(cfg["base_url"], api_key, cfg["model"], prompt)
        items = _json.loads(re.search(r"\[.*\]", content, re.S).group(0))
        return [FeeApplication(
            type=i.get("type", ""), song=i.get("song", ""), blogger=i.get("blogger", ""),
            amount=float(i.get("amount", 0)), payer="LLM解析", date="") for i in items]
    except Exception as e:
        log.error("LLM 兜底解析失败（已重试，静默降级转人工）：%s", e)
        return []


def build_promotion_table(apps: List[FeeApplication],
                          quotes: Optional[Dict[str, float]] = None) -> List[PromotionRow]:
    """填《推广账号表》。报价列 = 题目物料中博主的合作报价（config agent2.quotes），
    绝不能拿垫付金额冒充报价——两者语义完全不同。"""
    rows: Dict[tuple, PromotionRow] = {}
    for a in apps:
        key = (a.blogger, a.song)
        if key not in rows:
            q = quotes.get(a.blogger) if quotes else None
            rows[key] = PromotionRow(
                song=a.song, blogger=a.blogger, accepted="是", paid="否", payer=a.payer,
                quote=f"¥{q:.0f}" if q else "待确认")
        r = rows[key]
        if a.type == "抖加":
            r.douyin_boost += a.amount
            r.boost_payer = a.payer
        else:
            r.paid = "待打款"
            r.payer = a.payer
            r.pay_date = a.date
    return list(rows.values())


def write_promotion_table(rows: List[PromotionRow], path: str) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["歌曲", "博主", "报价", "抖加", "抖加支付人",
                    "是否打款", "打款人", "打款日期", "是否接单", "备注"])
        for r in rows:
            w.writerow([r.song, r.blogger, r.quote, f"¥{r.douyin_boost:.0f}",
                        r.boost_payer, r.paid, r.payer, r.pay_date,
                        r.accepted, r.note])
    return path


def sub_agent_run(doujia_text: str, advance_text: str, out_dir: str = "output",
                  llm_cfg: Optional[Dict] = None,
                  quotes: Optional[Dict[str, float]] = None) -> Dict:
    """Sub-Agent 主流程：解析 → 填《推广账号表》→ 返回结构化摘要给 Master。"""
    apps, unparsed, stated = parse_applications(doujia_text, advance_text, llm_cfg=llm_cfg)
    rows = build_promotion_table(apps, quotes=quotes)
    path = os.path.join(out_dir, "推广账号表.csv")
    write_promotion_table(rows, path)
    return {
        "applications": [a.__dict__ for a in apps],
        "promotion_rows": [r.__dict__ for r in rows],
        "stated_totals": stated,      # 群消息里"声称"的总额，供 Master 对账
        "unparsed": unparsed,
        "table_path": path,
    }
