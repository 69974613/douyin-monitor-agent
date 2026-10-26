from __future__ import annotations

import os
from typing import Dict, Optional

from src.agent2.data import ADVANCE_TEXT, DOUJIA_TEXT
from src.agent2.master_agent import master_agent_run
from src.agent2.sub_agent import sub_agent_run
from src.utils import get_logger

log = get_logger()


def run_agent2_daily(out_dir: str = "output", messages_file: str = "",
                     llm_cfg: Optional[Dict] = None,
                     quotes: Optional[Dict[str, float]] = None,
                     feishu_cfg: Optional[Dict] = None) -> Dict:
    """题目2 定时汇总入口（生产形态）：

    - messages_file 非空：从文件读取"推广群"当日消息（真实场景由飞书群消息
      事件回调写入；也可人工导出粘贴），格式 = 抖加段 + 垫付段拼接文本。
    - 为空：使用题目物料内置样例（演示形态）。
    - llm_cfg / quotes：来自 config.yaml 加载结果（LLM 兜底与报价列）。
    - feishu_cfg 非空：两张表同步写入飞书电子表格（题目2 交付"飞书实际执行"）。

    流程：Sub-Agent 解析 → 填《推广账号表》→ 结构化上报 → Master-Agent
    对账汇总 → 填《综合管理表》→ 生成给管理者的报告（含对账警示）。
    """
    doujia_text, advance_text = DOUJIA_TEXT, ADVANCE_TEXT
    if messages_file and os.path.exists(messages_file):
        with open(messages_file, encoding="utf-8") as f:
            raw = f.read()
        # 约定：文件内以"【抖加金额统计】/【垫付统计】"分段；无标记则整段按垫付尝试
        if "【抖加金额统计】" in raw and "【垫付统计】" in raw:
            i = raw.index("【垫付统计】")
            doujia_text, advance_text = raw[:i], raw[i:]
        else:
            advance_text, doujia_text = raw, ""
        log.info("题目2 汇总：读取群消息文件 %s（%d 字）", messages_file, len(raw))

    sub = sub_agent_run(doujia_text, advance_text, out_dir=out_dir,
                        llm_cfg=llm_cfg, quotes=quotes)
    master = master_agent_run(sub, manager="应聘者", out_dir=out_dir)

    # 两张表同步写入飞书（配了凭证才执行，未配置则仅本地 CSV）
    if feishu_cfg and feishu_cfg.get("app_id") and feishu_cfg.get("spreadsheet_token"):
        try:
            from src.sink.feishu_writer import FeishuWriter

            w = FeishuWriter(feishu_cfg)
            promo_rows = [[r["song"], r["blogger"], r["quote"], f"¥{r['douyin_boost']:.0f}",
                           r["boost_payer"], r["paid"], r["payer"], r["pay_date"],
                           r["accepted"], r["note"]] for r in sub["promotion_rows"]]
            mgmt_rows = [[r["song"], f"¥{r['douyin_total']:.0f}", f"¥{r['advance_total']:.0f}",
                          r["bloggers_accepted"], r["paid_count"], f"¥{r['total']:.0f}"]
                         for r in master["management_rows"]]
            w.write_promotion_rows(promo_rows)
            w.write_management_rows(mgmt_rows)
            log.info("题目2 两张表已写入飞书")
        except Exception as e:
            log.error("题目2 飞书写入失败（已重试，本地 CSV 仍可用）：%s", e)

    return {"sub": sub, "master": master, "report": master["report"]}


def run_agent2_demo(out_dir: str = "output", llm_cfg: Optional[Dict] = None,
                    quotes: Optional[Dict[str, float]] = None,
                    feishu_cfg: Optional[Dict] = None) -> Dict:
    """题目2 演示：Sub-Agent 解析申请 → Master-Agent 汇总报告。"""
    result = run_agent2_daily(out_dir=out_dir, llm_cfg=llm_cfg,
                              quotes=quotes, feishu_cfg=feishu_cfg)
    print("\n=== 题目2：Master / Sub Agent 演示 ===")
    print(result["master"]["report"])
    return {"sub": result["sub"], "master": result["master"]}


def get_agent2_summary(out_dir: str = "output",
                       messages_file: Optional[str] = None) -> Dict:
    return run_agent2_daily(out_dir=out_dir,
                            messages_file=messages_file or "")
