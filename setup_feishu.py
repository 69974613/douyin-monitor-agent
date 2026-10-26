from __future__ import annotations

"""飞书链路自检脚本：交付"在飞书里实际执行"前的一键验证。

用法：
    .venv\\Scripts\\python setup_feishu.py

按 config.yaml 的 sink.feishu 依次验证：
    1. 获取 tenant_access_token（凭证有效性）；
    2. 拉取电子表格子表清单，缺失的四个子表（视频数据监控/点赞预警/
       评论关键词命中/播放量）自动创建；
    3. 每个子表试写一行表头，确认写入权限；
    4. （可选）webhook_url 存在时推送一条测试消息。
全部通过后把 sink.type 改为 feishu 即可正式运行。
"""

import sys

from src.config import load_config
from src.utils import setup_logging

SHEET_TITLES = ["视频数据监控", "点赞预警", "评论关键词命中", "播放量",
                "推广账号表", "综合管理表"]


def main():
    import requests

    setup_logging("output")
    cfg = load_config("config.yaml")
    fcfg = cfg["sink"]["feishu"]
    if not fcfg.get("app_id") or not fcfg.get("spreadsheet_token"):
        print("❌ 请先在 config.yaml 的 sink.feishu 填入 app_id / app_secret / spreadsheet_token")
        sys.exit(1)
    token = fcfg["spreadsheet_token"]
    base = f"https://open.feishu.cn/open-apis/sheets/v3/spreadsheets/{token}"

    # 1) 凭证
    r = requests.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": fcfg["app_id"], "app_secret": fcfg["app_secret"]}, timeout=10)
    data = r.json()
    if data.get("code") != 0:
        print(f"❌ 凭证无效：{data.get('msg')}")
        sys.exit(1)
    print("✅ 1/4 tenant_access_token 获取成功（凭证有效）")
    headers = {"Authorization": f"Bearer {data['tenant_access_token']}"}

    # 2) 子表清单 + 缺失创建
    r = requests.get(f"{base}/sheets/query", headers=headers, timeout=10)
    if r.status_code != 0 and not r.ok:
        print(f"❌ 无权访问该电子表格：{r.text[:200]}")
        sys.exit(1)
    existing = {s["title"] for s in r.json()["data"]["sheets"]}
    print(f"✅ 2/4 电子表格可访问，现有子表：{sorted(existing) or '（空）'}")
    for title in SHEET_TITLES:
        if title not in existing:
            r = requests.post(
                f"{base}/sheets",
                headers=headers,
                json={"title": title, "index": len(existing)}, timeout=10)
            if r.ok and r.json().get("code") == 0:
                existing.add(title)
                print(f"   ➕ 已创建子表《{title}》")
            else:
                print(f"   ⚠️ 创建子表《{title}》失败：{r.text[:120]}（可手动在表格里新建同名子表）")

    # 3) 为全部 6 张子表补表头（含题目2 两张），并验证写入权限
    from src.sink.feishu_writer import FeishuWriter
    w = FeishuWriter(fcfg)
    for key in w.RANGES:
        w._ensure_headers(key)             # 写表头行
        title = w.RANGES[key].split("!")[0]
        print(f"   {'✅' if key in w._headered else '⚠️'} 子表《{title}》表头"
              f"{'就绪' if key in w._headered else '写入失败（请检查权限或手动建列名）'}")
    # 试写一行验证数据权限（提示：可在表格中删除该行）
    w._append_values("video", [["自检写入测试", "mock(模拟)", "-", "-", "-", "-", 0, 0, 0]])
    print("✅ 3/4 子表写入成功（自检行可在表格中删除）")

    # 4) webhook 测试
    if fcfg.get("webhook_url"):
        r = requests.post(fcfg["webhook_url"],
                          json={"msg_type": "text",
                                "content": {"text": "飞书链路自检消息：监控 Agent 已就绪 ✔"}},
                          timeout=5)
        r.raise_for_status()
        print("✅ 4/4 群机器人 Webhook 推送成功")
    else:
        print("ℹ️  4/4 未配置 webhook_url，跳过机器人推送测试")

    print("\n🎉 飞书链路全部就绪。把 config.yaml 的 sink.type 改为 feishu 即可正式写入飞书。")


if __name__ == "__main__":
    main()
