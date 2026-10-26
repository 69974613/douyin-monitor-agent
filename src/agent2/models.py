from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FeeApplication:
    type: str          # 抖加 | 垫付
    song: str
    blogger: str
    amount: float
    payer: str
    date: str
    note: str = ""


@dataclass
class PromotionRow:
    song: str
    blogger: str
    quote: str = ""           # 报价
    douyin_boost: float = 0.0  # 抖加费用
    boost_payer: str = ""
    paid: str = "否"           # 是否打款
    payer: str = ""
    pay_date: str = ""
    accepted: str = "否"        # 是否接单
    note: str = ""


@dataclass
class ManagementRow:
    song: str
    douyin_total: float = 0.0
    advance_total: float = 0.0
    bloggers_accepted: int = 0
    paid_count: int = 0
    total: float = 0.0
