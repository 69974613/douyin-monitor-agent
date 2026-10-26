from __future__ import annotations

import csv
import os
from typing import Dict, List

from src.agent2.models import ManagementRow
from src.utils import get_logger

log = get_logger()


def reconcile(stated_totals: Dict, apps: List[dict]) -> List[str]:
    """财务对账：群消息声明总额 vs 明细合计，差额显式抛出。"""
    warnings: List[str] = []
    for fee_type in ("抖加", "垫付"):
        stated = stated_totals.get(fee_type)
        if stated is None:
            continue
        detail = sum(a["amount"] for a in apps if a["type"] == fee_type)
        if abs(stated - detail) > 0.005:
            warnings.append(
                f"⚠️ 财务对账异常：{fee_type}群消息总额 ¥{stated:.0f} 与明细合计 ¥{detail:.0f} "
                f"差额 ¥{stated - detail:.0f}，请核查！"
                f"（可能来源：群消息未列全的明细、金额笔误或重复申报）")
    return warnings


def master_agent_run(sub_summary: Dict, manager: str = "应聘者",
                     out_dir: str = "output") -> Dict:
    """Master-Agent（综合助手）：接收 Sub 的结构化信息 → 对账 → 填《综合管理表》→ 报告管理者。"""
    apps = sub_summary["applications"]

    by_song: Dict[str, dict] = {}
    for a in apps:
        d = by_song.setdefault(a["song"], {"doujia": 0.0, "advance": 0.0,
                                           "bloggers": set(), "paid": 0})
        if a["type"] == "抖加":
            d["doujia"] += a["amount"]
        else:
            d["advance"] += a["amount"]
            d["paid"] += 1
        d["bloggers"].add(a["blogger"])

    mrows: List[ManagementRow] = []
    for song, d in by_song.items():
        mrows.append(ManagementRow(
            song=song, douyin_total=d["doujia"], advance_total=d["advance"],
            bloggers_accepted=len(d["bloggers"]), paid_count=d["paid"],
            total=d["doujia"] + d["advance"]))

    path = os.path.join(out_dir, "综合管理表.csv")
    os.makedirs(out_dir, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["歌曲", "抖加花费", "垫付花费", "接单达人数", "垫付待打款笔数", "合计花费"])
        for r in mrows:
            w.writerow([r.song, f"¥{r.douyin_total:.0f}", f"¥{r.advance_total:.0f}",
                        r.bloggers_accepted, r.paid_count, f"¥{r.total:.0f}"])

    # 财务对账：差额显式进入报告
    recon = reconcile(sub_summary.get("stated_totals", {}), apps)
    if recon:
        for w_ in recon:
            log.warning(w_)

    report = build_report(manager, mrows, apps, recon,
                          sub_summary.get("unparsed", []))
    return {"management_rows": [r.__dict__ for r in mrows],
            "report": report, "table_path": path,
            "reconciliation": recon}


def build_report(manager: str, mrows: List[ManagementRow], apps: List[dict],
                 recon: List[str], unparsed: List[str]) -> str:
    doujia = sum(r.douyin_total for r in mrows)
    advance = sum(r.advance_total for r in mrows)
    bloggers = sorted({a["blogger"] for a in apps})
    lines = [
        f"【综合管理报告 · 管理者：{manager}】",
        f"今日推广总花费：抖加 ¥{doujia:.0f} + 垫付 ¥{advance:.0f} = ¥{doujia + advance:.0f}",
    ]
    for r in mrows:
        lines.append(
            f"· 《{r.song}》：抖加 ¥{r.douyin_total:.0f}，垫付 ¥{r.advance_total:.0f}，"
            f"接单达人 {r.bloggers_accepted} 位，垫付待打款 {r.paid_count} 笔。")
    lines.append(f"接单达人：{', '.join(bloggers)}")
    # 打款情况从结构化数据动态生成（付款人/打款人/日期均来自解析结果，不再硬编码）
    dj_payers = sorted({a["payer"] for a in apps if a["type"] == "抖加" and a.get("payer")})
    adv = [a for a in apps if a["type"] == "垫付"]
    adv_payers = sorted({a["payer"] for a in adv if a.get("payer")})
    adv_dates = sorted({a["date"] for a in adv if a.get("date")})
    pay_line = "打款情况："
    pay_line += f"抖加 ¥{doujia:.0f} 已由「{'、'.join(dj_payers)}」支付；" if dj_payers else ""
    if adv:
        pay_line += (f"垫付 {len(adv)} 笔共 ¥{advance:.0f} 由「{'、'.join(adv_payers)}」打款"
                     + (f"（预计 {adv_dates[0]}）" if adv_dates else "") + "，待执行。")
    if pay_line == "打款情况：":
        pay_line += "今日无打款记录。"
    lines.append(pay_line)
    lines.extend(recon)
    if unparsed:
        lines.append(f"⚠️ 有 {len(unparsed)} 条申请无法自动解析，需人工核对。")
    return "\n".join(lines)
