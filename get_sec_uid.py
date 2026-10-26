"""从抖音账号主页链接提取 sec_uid（live 模式 sec_uids 配置的辅助工具）。

用法：
    python get_sec_uid.py "https://v.douyin.com/xxxx/"          # 分享短链
    python get_sec_uid.py "https://www.douyin.com/user/MS4w..." # 完整主页链接
    python get_sec_uid.py 卡带森林 --open                        # 按昵称搜索（Playwright）

原理：
  1. 完整 /user/ 链接：sec_uid 就在路径里，正则直接提取（无需浏览器）；
  2. 短链 v.douyin.com：requests 跟随 302 重定向，Location 即 /user/<sec_uid>；
  3. 仅有昵称：Playwright 打开 douyin.com 搜索页，从搜索结果/跳转中正则提取
     （sec_uid 特征：MS4wLjABAAAA 开头的 Base64-ish 串）。

提取后写入 config.yaml 的 sec_uids 映射即可启用 live 模式。
"""
from __future__ import annotations

import re
import sys

SEC_UID_RE = re.compile(r"MS4wLjABAAAA[\w-]+")


def extract_from_url(url: str) -> str:
    """从完整主页链接或短链重定向中提取 sec_uid。"""
    m = SEC_UID_RE.search(url)
    if m:
        return m.group(0)
    # 短链：跟随重定向拿真实地址（requests 缺失时退化为 urllib）
    try:
        import requests
        resp = requests.head(url, allow_redirects=True, timeout=10,
                             headers={"User-Agent": "Mozilla/5.0"})
        final = resp.url
    except ImportError:
        import urllib.request
        req = urllib.request.Request(url, method="HEAD",
                                     headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            final = resp.geturl()
    m = SEC_UID_RE.search(final)
    return m.group(0) if m else ""


def extract_by_search(nickname: str) -> str:
    """仅有昵称时：Playwright 打开搜索页提取（需 playwright + chromium）。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError("昵称搜索需要 Playwright：pip install playwright "
                           "&& playwright install chromium")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto(f"https://www.douyin.com/search/{nickname}?type=user",
                      wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(6000)
            # 搜索结果卡片链接 / 页面源码中均可正则捞 sec_uid
            m = SEC_UID_RE.search(page.content())
            return m.group(0) if m else ""
        finally:
            browser.close()


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    arg = sys.argv[1]
    if arg.startswith("http"):
        sec = extract_from_url(arg)
    else:
        sec = extract_by_search(arg)
    if sec:
        print(f"sec_uid = {sec}")
        print("写入 config.yaml：")
        print("sec_uids:")
        print(f'  "账号名": "{sec}"')
    else:
        print("未提取到 sec_uid：链接可能已失效，或页面结构变动，"
              "可手动在浏览器打开主页从源码搜 MS4wLjABAAAA")
        sys.exit(2)


if __name__ == "__main__":
    main()
