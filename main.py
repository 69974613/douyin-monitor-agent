from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.agent2 import run_agent2_demo
from src.config import load_config
from src.datasource.live_source import LiveDouyinSource
from src.datasource.mock_source import MockDouyinSource
from src.monitor import Monitor
from src.sink.feishu_writer import FeishuWriter
from src.sink.local_writer import LocalSheetWriter
from src.store import StateStore
from src.utils import setup_logging


def main():
    ap = argparse.ArgumentParser(description="抖音数据监控 Agent（题目1为主，题目2辅助）")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--mode", default=None, help="demo|live 覆盖配置")
    ap.add_argument("--once", action="store_true", help="仅扫描一次（适合单次验证）")
    ap.add_argument("--agent2-only", action="store_true",
                    help="仅运行题目2 Master/Sub 演示（不启动监控——长驻模式下 --agent2 会被调度阻塞）")
    ap.add_argument("--agent2", action="store_true",
                    help="启动监控前先运行一次题目2 Master/Sub 演示")
    ap.add_argument("--max-scans", type=int, default=0,
                    help="3 分钟演示模式最大扫描次数（0=不限；现场演示建议 3~5 防忘停）")
    ap.add_argument("--card-server", action="store_true",
                    help="仅启动飞书卡片回调服务（接收「同意加热/驳回」按钮，落库 SQLite）")
    args = ap.parse_args()

    cfg = load_config(args.config)
    if args.mode:
        cfg["mode"] = args.mode
    # 容器/CI 用环境变量覆盖演示节奏：DEMO_FAST=false 关快速模式；=true 强制开启
    env_fast = os.environ.get("DEMO_FAST", "").lower()
    if env_fast in ("0", "false", "no"):
        cfg["monitor"]["demo_fast"] = False
    elif env_fast in ("1", "true", "yes"):
        cfg["monitor"]["demo_fast"] = True
    out_dir = cfg["sink"]["output_dir"]
    setup_logging(out_dir)

    if args.card_server:
        from src.card_server import run_card_server

        cb = cfg.get("notify", {}).get("card_callback", {})
        run_card_server(os.path.join(out_dir, "state.db"),
                        host=cb.get("host", "0.0.0.0"), port=int(cb.get("port", 7788)),
                        encrypt_key=cb.get("encrypt_key", ""))
        return

    if args.agent2_only:
        # 独立分支：不建监控/数据源，run_agent2_demo 自身即退出——长驻模式也可用
        run_agent2_demo(out_dir=out_dir,
                        llm_cfg=cfg["agent2"].get("llm"),
                        quotes=cfg["agent2"].get("quotes"),
                        feishu_cfg=cfg["sink"]["feishu"] if cfg["sink"]["type"] == "feishu" else None)
        return

    if args.max_scans:
        cfg["monitor"]["demo_max_scans"] = args.max_scans

    store = StateStore(os.path.join(out_dir, "state.db"))

    if cfg["mode"] == "live":
        source = LiveDouyinSource(
            cookie=cfg.get("douyin_cookie", ""),
            sec_uids=cfg.get("sec_uids", {}))
    else:
        source = MockDouyinSource(
            cfg["monitor"]["accounts"], cfg["song"],
            time_scale=cfg["monitor"].get("demo_time_scale", 900))

    if cfg["sink"]["type"] == "feishu":
        try:
            from src.sink.base import TeeSheetWriter

            # 双写：飞书为主 + 本地 CSV 镜像（--once 验证与演示看板都读本地文件）
            sink = TeeSheetWriter(FeishuWriter(cfg["sink"]["feishu"]),
                                  LocalSheetWriter(out_dir))
        except Exception as e:
            print(f"⚠️ 飞书写入器初始化失败，降级本地镜像：{e}")
            sink = LocalSheetWriter(out_dir)
    else:
        sink = LocalSheetWriter(out_dir)

    webhook = cfg["sink"]["feishu"].get("webhook_url", "")
    mon = Monitor(cfg, source, sink, store, webhook_url=webhook)

    try:
        if args.agent2:
            # 前置执行一次题目2 演示（mon.run() 在非 fast 模式下会阻塞，放后面永远到不了）
            run_agent2_demo(out_dir=out_dir,
                            llm_cfg=cfg["agent2"].get("llm"),
                            quotes=cfg["agent2"].get("quotes"),
                            feishu_cfg=cfg["sink"]["feishu"] if cfg["sink"]["type"] == "feishu" else None)
        if args.once:
            ctx = mon.scan_once()
            mon._summary(ctx)
        else:
            mon.run()
    finally:
        source.close()   # live 模式释放 Playwright 浏览器资源


if __name__ == "__main__":
    main()
