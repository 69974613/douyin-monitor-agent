from __future__ import annotations

import logging
import logging.handlers
import os

try:
    from tenacity import retry, stop_after_attempt, wait_exponential

    # 网络请求指数退避重试：2s → 4s → 8s，共尝试 4 次（首调 + 3 重试），最终失败向上抛出
    net_retry = retry(
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=2, max=8),
        reraise=True,
    )
except ImportError:
    # tenacity 未安装：退化为直通装饰器——demo 零依赖也能跑，生产装库后自动获得重试
    def net_retry(fn):
        return fn

LOGGER_NAME = "douyin_agent"


def setup_logging(output_dir: str = "output") -> logging.Logger:
    """系统级日志：控制台 + 按天切分文件（保留 30 天），区分 INFO/WARNING/ERROR。"""
    os.makedirs(output_dir, exist_ok=True)
    logger = logging.getLogger(LOGGER_NAME)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    fh = logging.handlers.TimedRotatingFileHandler(
        os.path.join(output_dir, "agent.log"),
        when="midnight", backupCount=30, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)
