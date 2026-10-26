# 抖音数据监控 Agent · 面试题目交付

> 核心围绕 **题目1（抖音数据监控）** 构建可运行演示；**题目2（Agent 设计 / Master·Sub）** 作为辅助模块，复用同一套工程与数据。

---

## 一、需求 ↔ 实现 对照（题目1）

| 题目要求 | 实现位置 | 说明 |
|---|---|---|
| 最少选 2 个账号监控 | `config.yaml` → `monitor.accounts`（默认配置题目"测试账号表格"全部 5 个：卡带森林系列 + 佳佳超有才） | `MockDouyinSource` / `LiveDouyinSource` |
| 每天 12/18/22 三时段扫描；演示设 3 分钟间隔 | `Monitor.run()`：**APScheduler cron 触发**，缺库退化轮询 | `demo_interval_seconds: 180` |
| 扫描近 3 天新发布视频（基础=点赞量） | `get_recent_videos(within_days=3)` | 过滤发布时间 < 3 天 |
| 数据抓取后填入**飞书表格** | `sink/LocalSheetWriter`（本地 CSV 镜像）+ `FeishuWriter`（飞书 API + tenacity 重试） | 四个逻辑表对应四张飞书子表 |
| 点赞增量 > 300 → 抖加加热预警（可下调阈值） | `Monitor.scan_once()` + `notify_alert` | 增量基线存 **SQLite**，跨重启可靠 |
| 每个扫描点扫描评论区关键词 | `comments.scan_comments()` | 关键词全部覆盖（见下方强/弱意图分层） |
| 命中关键词 → 自动回复话术 | `reply_templates`（6 套）+ **SQLite 已回复去重** | 重启绝不重复回复同一评论（防风控） |
| 同步扫描视频播放量 | `Monitor` 采集 `play_count` → `播放量.csv` | — |

## 二、健壮性与工程化设计

1. **Mock 数据源读操作幂等**：点赞/播放是时间的纯函数 `f(基线, 速率, 模拟经过时间)`，
   同一时刻重复调用（含重试）返回相同值，杜绝"调两次数据翻倍"。
2. **SQLite 状态持久化**（`src/store.py`，标准库零依赖）：
   `replied_comments` 主键唯一约束保证重启后绝不重复回复同一评论（防抖音风控）；
   `video_state` 保存上次点赞基线。实测：连续重启两次进程，重复回复为 0。
3. **强/弱意图分层**：`BGM/求歌名/什么歌/什么歌曲/这首歌叫什么歌/背景音乐` → 自动回复；
   `歌/好听` → 仅记录、转人工，避免"唱了一首歌"被误回复造成打扰。
4. **财务对账**（题目2 Master-Agent）：群消息声明总额 vs 明细合计自动比对，
   差额显式进报告——演示数据实测输出
   `⚠️ 财务对账异常：垫付群消息总额 ¥2595 与明细合计 ¥2250 差额 ¥345，请核查！`
5. **系统级日志**：`logging` 控制台 + 按天切分文件（保留 30 天），INFO/WARNING/ERROR 分级。
6. **指数退避重试**：`tenacity` 包装飞书 Webhook 等网络请求（2s→4s→8s，3 次重试）。
7. **正则 + LLM 双层解析**（题目2 Sub-Agent）：正则放宽分隔符/中英文冒号/"博主名|达人名"；
   仍未解析的行 fallback 到 OpenAI 兼容接口（默认 DeepSeek，`DEEPSEEK_API_KEY` 环境变量或
   `agent2.llm.api_key` 配置，`llm_extract` 已接入加载后的配置），做 JSON 约束提取；
   两者皆失败则显式标记"需人工核对"，不静默丢数据。
   LLM 的 HTTP 调用同样套 `@net_retry`（2s→4s→8s×3，实测断网场景 16s 内重试 4 次），
   重试耗尽才静默降级转人工——保证兜底链路不阻塞主流程。
8. **飞书交互式卡片 + 人工确认闭环**：抖加预警推送带「✅ 同意加热 / ❌ 驳回」按钮的消息卡片；
   `src/card_server.py`（纯标准库）接收飞书卡片回调（challenge 校验 + v1/v2 schema 兼容），
   决策落 SQLite `boost_decisions` 表（预警时预登记"待确认"，回调覆盖）——JD 的"人工确认机制"闭环。
   ⚠️ 已知限制：回调服务未校验飞书签名（生产需配 Encrypt Key + AES 验签 / IP 白名单）。
9. **Playwright 资源开销控制**：live 模式全生命周期只开 1 个 context + 1 个常驻 page 复用导航；
   同一视频的详情与评论在一次页面访问中同时收割（`get_video_with_comments`），导航次数减半。
10. **异常隔离**：`scan_once` 对账号/视频两级 try/except，live 抓取单点失败不拖垮整轮扫描；
    进程退出统一 `source.close()` 释放浏览器。

## 三、题目2（辅助）：Master / Sub Agent

- **Sub-Agent（推广助手）** `src/agent2/sub_agent.py`：读取"推广群"费用申请 → 双层解析结构化
  → 填《推广账号表》→ 连同"声明总额"一起结构化上报 Master。
- **Master-Agent（综合助手）** `src/agent2/master_agent.py`：对账 → 按歌曲汇总抖加/垫付/接单/打款
  → 填《综合管理表》→ 生成给管理者的报告（含异常警示）。
- **23:00 定时汇总**（题目原文要求）：调度器在每天 23:00 自动触发 `run_agent2_summary`——
  读取推广群消息（`agent2.messages_file`，空则用内置物料）→ 两表落盘 → 报告推送飞书群。

## 四、工程结构

```
douyin/
├── config.yaml                 # 阈值 / 账号 / 排程 / 强弱关键词 / 飞书凭证 / LLM
├── main.py                     # CLI 入口（--once / --agent2 / --mode）
├── run_demo.py                 # 一键演示（扫描+题目2+看板）
├── Dockerfile / docker-compose.yml   # 容器化：docker-compose up 一行拉起
├── src/
│   ├── config.py  models.py  comments.py  monitor.py  notify.py  dashboard.py
│   ├── utils.py                # logging 配置 + tenacity 指数退避
│   ├── store.py                # SQLite 状态持久化（防重复回复 / 增量基线 / 人工确认）
│   ├── card_server.py          # 飞书卡片回调服务（同意加热/驳回 → 落库）
│   ├── datasource/             # base / mock_source(幂等模拟) / live_source(Playwright)
│   ├── sink/                   # base / local_writer(本地) / feishu_writer(飞书)
│   └── agent2/                 # 题目2 Sub/Master Agent（含 LLM 兜底与对账）
└── output/                     # 飞书式表格 + dashboard.html + state.db + 日志
```

## 五、快速开始

```bash
cd D:\python_file\douyin
.venv\Scripts\python run_demo.py          # 演示：4 次加速扫描 + 题目2 + 看板
.venv\Scripts\python main.py --once       # 单次扫描验证
.venv\Scripts\python main.py --agent2      # 启动监控前先跑一次题目2
.venv\Scripts\python main.py --agent2-only # 仅跑题目2（长驻模式下的正确姿势）
.venv\Scripts\python main.py --max-scans 4 # 3 分钟模式限定扫描轮数
.venv\Scripts\python main.py --card-server # 飞书卡片回调服务（按钮决策落库）
.venv\Scripts\python setup_feishu.py      # 飞书链路自检（凭证/子表/写入/推送）
docker-compose up -d                      # 容器化生产运行（三时段调度 + 23:00 汇总）
```

## 六、双模式架构

- **demo 模式**（默认）：`MockDouyinSource` 幂等模拟。两种节奏：
  `demo_fast: true` → 2s 间隔×4 轮快速演示（时间加速，稳定触发预警，适合投屏）；
  `demo_fast: false` → 按题目原文**每 3 分钟真实扫描一次**（`demo_interval_seconds: 180`），
  此时阈值**自动切换**为 `demo_slow_like_threshold: 20`（3 分钟真实间隔下增量约 17~40，
  300 永远达不到——按题目备注下调，`--max-scans 4` 可限定演示轮数防忘停）。
  演示诚实性：mock 环境的自动回复在表格/看板中标注**"已自动回复(模拟)"**，不冒充真实回复；
  **live 回复链路**：Monitor 调用 `LiveDouyinSource.reply_comment`（Playwright 按原评论文本
  定位目标评论 → 点回复 → 填写 → 提交），**提交成功才写 replied_comments，失败标注
  "回复失败-转人工"并保留到下轮重试**——绝不允许"生成即标记"造成假回复。
- **live 模式**：`LiveDouyinSource` 用 **Playwright 接管浏览器、拦截抖音前端接口返回包**
  （作品/详情/评论三个官方 API），签名由页面 JS 自行完成，无需逆向 X-Bogus；
  `FeishuWriter` 写电子表格 + 机器人 Webhook 推送（带重试）；表格带**"数据源"列**，
  mock / live 一眼可辨。安装：`pip install playwright && playwright install chromium`。

## 七、飞书实际执行：接入五步（约 10 分钟）

1. **创建自建应用**：[飞书开放平台](https://open.feishu.cn/app) → 企业自建应用；
2. **开通权限**：权限管理中开通 `sheets:spreadsheet`（读写电子表格）与 `drive:drive`（云空间文件）；
3. **加为文档协作者（最关键、最易漏）**：打开目标电子表格 → 分享 → 把自建应用添加为协作者并给"可编辑"——应用默认无权访问个人文档；
4. **填凭证 + 一键自检**：App ID / App Secret / spreadsheet_token / webhook_url 填入 `config.yaml` → `python setup_feishu.py`（自动验证权限、补全 6 张子表表头、试写一行、推送测试）；
5. **切换**：`sink.type: feishu`，之后 `run_demo.py` / `main.py` 直接写飞书（表头跨进程去重、token 自动续期、写入带重试）。

**sec_uid 获取**：题目短链被截断不影响——`python get_sec_uid.py "主页链接或分享短链"`
自动提取（完整链接正则直取 / 短链跟随重定向 / 仅昵称走 Playwright 搜索页），
输出可直接粘贴进 `config.yaml` 的 `sec_uids` 映射。

**live 自动回复的风控分层**（推荐生产姿势 = 半自动）：
- 全自动：`reply_comment` 内置**随机延迟 3~8s、每日上限 50 条、验证码/风控页检测熔断**（熔断后全部转人工）；
- **半自动（`notify.reply_confirm: true`）**：自动生成回复 → 飞书卡片「📤 同意发送 / ✖️ 不发送」→
  `card_server` 落库批准状态（`reply_approvals` 表）→ 下一轮扫描统一提交——效率与账号安全的平衡点。

## 八、已知限制 / 数据备注

- 题目文档"垫付总结"声称 `¥2595`，但列出的 5 笔明细合计 `¥2250`（注明 7 笔只列 5 笔）——
  系统按明细精确汇总并**在报告中显式对账预警**，不虚构金额。
- live 模式的 Playwright 抓取需自备合规账号 Cookie；真实环境请遵守平台条款。
