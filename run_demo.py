from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.agent2 import run_agent2_demo
from src.config import load_config
from src.dashboard import build_dashboard
from src.datasource.mock_source import MockDouyinSource
from src.monitor import Monitor
from src.sink.local_writer import LocalSheetWriter
from src.store import StateStore
from src.utils import setup_logging


def _make_sink(cfg: dict, out: str):
    """按 sink.type 选择写入器——演示也能真实写飞书，而非永远只写本地镜像。"""
    if cfg["sink"]["type"] == "feishu":
        try:
            from src.sink.feishu_writer import FeishuWriter

            from src.sink.base import TeeSheetWriter

            # 双写：飞书为主 + 本地 CSV 镜像（演示看板 dashboard 读本地文件）
            return TeeSheetWriter(FeishuWriter(cfg["sink"]["feishu"]),
                                  LocalSheetWriter(out))
        except Exception as e:
            print(f"⚠️ 飞书写入器初始化失败，降级本地镜像：{e}")
    return LocalSheetWriter(out)


def main():
    import argparse

    ap = argparse.ArgumentParser(
        description="一键演示：限轮扫描 + 题目2 Master/Sub + HTML 看板（长驻调度请用 main.py）")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--mode", default=None, help="demo|live 覆盖配置（live 需已配 cookie/sec_uids）")
    args = ap.parse_args()

    cfg = load_config(args.config)
    if args.mode:
        cfg["mode"] = args.mode
    out = cfg["sink"]["output_dir"]
    setup_logging(out)
    store = StateStore(os.path.join(out, "state.db"))
    if cfg["mode"] == "live":
        from src.datasource.live_source import LiveDouyinSource

        source = LiveDouyinSource(cookie=cfg.get("douyin_cookie", ""),
                                  sec_uids=cfg.get("sec_uids", {}))
    else:
        source = MockDouyinSource(cfg["monitor"]["accounts"], cfg["song"],
                                  time_scale=cfg["monitor"].get("demo_time_scale", 900))
    sink = _make_sink(cfg, out)
    mon = Monitor(cfg, source, sink, store,
                  webhook_url=cfg["sink"]["feishu"].get("webhook_url", ""))
    # run_demo 是"一次跑完出看板"的入口：3 分钟真实间隔模式下若不限轮数，
    # mon.run() 永久阻塞，agent2 与 dashboard 永远执行不到
    if not cfg["monitor"].get("demo_fast", True) \
            and not int(cfg["monitor"].get("demo_max_scans", 0)):
        cfg["monitor"]["demo_max_scans"] = 3
        print("ℹ️ demo_fast=false 且未设 demo_max_scans：本次演示自动限定 3 轮后生成看板"
              "（生产长驻请用 main.py）")
    try:
        mon.run()
        a2 = run_agent2_demo(out_dir=out,
                             llm_cfg=cfg["agent2"].get("llm"),
                             quotes=cfg["agent2"].get("quotes"),
                             feishu_cfg=cfg["sink"]["feishu"] if cfg["sink"]["type"] == "feishu" else None)
        build_dashboard(cfg, a2, out)
        print(f"\n✅ 演示完成。看板：{out}/dashboard.html  | 表格已写入 {out}/"
              f"（sink.type={cfg['sink']['type']}）")
    finally:
        source.close()   # live 模式释放 Playwright 浏览器资源


if __name__ == "__main__":
    main()
