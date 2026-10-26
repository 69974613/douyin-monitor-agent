from __future__ import annotations

import csv
import os
from collections import OrderedDict
from datetime import datetime


def _read_csv(path: str) -> list:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


_CHART_JS = """
<script>
// 图例多选过滤：点一下隐藏该曲线，再点恢复；「全部显示」一键复位
(function () {
  document.querySelectorAll('.chart-box').forEach(function (box) {
    if (box.dataset.bound) return;
    box.dataset.bound = '1';
    box.querySelectorAll('.lg[data-sid]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var sid = btn.getAttribute('data-sid');
        var off = btn.classList.toggle('off');
        box.querySelectorAll('.ser[data-sid="' + sid + '"]').forEach(function (g) {
          g.style.display = off ? 'none' : '';
        });
      });
    });
    var reset = box.querySelector('.lg-reset');
    if (reset) {
      reset.addEventListener('click', function () {
        box.querySelectorAll('.lg.off').forEach(function (b) { b.classList.remove('off'); });
        box.querySelectorAll('.ser').forEach(function (g) { g.style.display = ''; });
      });
    }
  });
})();
</script>
"""


def _short_label(label: str) -> str:
    """账号·视频ID → 账号·…末4位，图例里不至于一长串拥挤。"""
    if "·" in label:
        acc, vid = label.split("·", 1)
        return f"{acc} ·…{vid[-4:]}" if len(vid) > 4 else label
    return label


def _line_chart(series, width=920, height=330):
    if not series:
        return "<p class='muted'>暂无数据</p>"
    maxv = max((v for _, vals in series for _, v in vals), default=1) or 1
    n = max((len(vals) for _, vals in series), default=1)
    colors = ["#e23b3b", "#2f6fed", "#19a979", "#f5a623", "#8e44ad", "#16a2b8", "#e84393"]
    pad_l, pad_r, pad_t, pad_b = 58, 24, 24, 34
    plot_w, plot_h = width - pad_l - pad_r, height - pad_t - pad_b
    x = lambda i: pad_l + plot_w * (i / max(n - 1, 1))
    y = lambda v: pad_t + plot_h * (1 - v / maxv)

    # 图例放在 SVG 外，用 HTML flex-wrap 排布：条目再多也不会互相压字；点击可切换显示
    legend = "".join(
        f'<button type="button" class="lg" data-sid="{i}">'
        f'<i style="background:{colors[i % len(colors)]}"></i>{_short_label(label)}</button>'
        for i, (label, _) in enumerate(series))
    legend += '<button type="button" class="lg lg-reset">全部显示</button>'

    svg = [f'<svg viewBox="0 0 {width} {height}" width="100%" style="max-width:{width}px">']
    # y 轴网格线 + 刻度值
    for k in range(5):
        val = maxv * k / 4
        yy = y(val)
        svg.append(f'<line x1="{pad_l}" y1="{yy:.1f}" x2="{width - pad_r}" y2="{yy:.1f}" '
                   f'stroke="{"#d8dce3" if k == 0 else "#eef0f3"}"/>')
        svg.append(f'<text x="{pad_l - 8}" y="{yy + 4:.1f}" font-size="10" fill="#9aa0a6" '
                   f'text-anchor="end">{int(val)}</text>')
    svg.append(f'<line x1="{pad_l}" y1="{pad_t}" x2="{pad_l}" y2="{height - pad_b}" stroke="#d8dce3"/>')
    # x 轴刻度（扫描序号，太多时抽稀）
    step = max(n // 8, 1)
    for i in sorted(set(list(range(0, n, step)) + [n - 1])):
        svg.append(f'<text x="{x(i):.1f}" y="{height - pad_b + 16}" font-size="10" '
                   f'fill="#9aa0a6" text-anchor="middle">#{i + 1}</text>')

    for si, (label, vals) in enumerate(series):
        if not vals:
            continue
        c = colors[si % len(colors)]
        # SVG points 只认 "x,y" / "x y"，用冒号会导致整条折线被浏览器丢弃
        pts = " ".join(f"{x(idx):.1f},{y(v):.1f}" for idx, v in vals)
        svg.append(f'<g class="ser" data-sid="{si}">')
        svg.append(f'<polyline points="{pts}" fill="none" stroke="{c}" '
                   f'stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>')
        for idx, v in vals:
            svg.append(f'<circle cx="{x(idx):.1f}" cy="{y(v):.1f}" r="3" fill="{c}" '
                       f'stroke="#fff" stroke-width="1">'
                       f'<title>{label} 第{idx + 1}次扫描 点赞 {v}</title></circle>')
        svg.append("</g>")
    svg.append("</svg>")

    hint = ('<p class="muted" style="margin:0 0 8px;font-size:12px">'
            '数据点不足（仅 1 次扫描），趋势线待下轮扫描生成</p>') if n <= 1 else ""
    tip = ('<p class="muted" style="margin:8px 0 0;font-size:12px">'
           '点击上方图例可切换该曲线显示，可多选叠加对比</p>')
    return (f'<div class="chart-box"><div class="legend">{legend}</div>{hint}'
            + "\n".join(svg) + tip + _CHART_JS + "</div>")


CSS = """
* { box-sizing: border-box; }
body { margin:0; font-family:-apple-system,"Microsoft YaHei",sans-serif; background:#f5f6f8; color:#1f2329; }
.header { background:linear-gradient(90deg,#2f6fed,#19a979); color:#fff; padding:24px 32px; }
.header h1 { margin:0; font-size:22px; }
.header p { margin:6px 0 0; opacity:.9; font-size:13px; }
.wrap { padding:24px 32px; max-width:1080px; margin:0 auto; }
.cards { display:flex; gap:14px; flex-wrap:wrap; margin-bottom:24px; }
.card { background:#fff; border-radius:12px; padding:16px 20px; flex:1; min-width:140px; box-shadow:0 1px 3px rgba(0,0,0,.06); }
.card .n { font-size:26px; font-weight:700; color:#2f6fed; }
.card .l { font-size:13px; color:#646a73; margin-top:4px; }
.section { background:#fff; border-radius:12px; padding:18px 22px; margin-bottom:20px; box-shadow:0 1px 3px rgba(0,0,0,.06); }
.section h2 { font-size:16px; margin:0 0 12px; border-left:4px solid #2f6fed; padding-left:10px; }
table { width:100%; border-collapse:collapse; font-size:13px; }
th,td { border:1px solid #eef0f3; padding:7px 10px; text-align:left; }
th { background:#f5f6f8; color:#646a73; font-weight:600; }
tr:nth-child(even) td { background:#fafbfc; }
.alert td { color:#e23b3b; font-weight:600; }
.chart-box .legend { display:flex; flex-wrap:wrap; gap:8px; margin:0 0 10px; }
.chart-box .lg { display:inline-flex; align-items:center; gap:6px; font-family:inherit; font-size:12px;
  line-height:1.7; color:#4e5969; background:#f5f6f8; border:1px solid #e5e8ee; border-radius:14px;
  padding:2px 11px; cursor:pointer; transition:all .15s; }
.chart-box .lg:hover { background:#eaf0fa; border-color:#cfd9e8; }
.chart-box .lg.off { color:#b6bcc7; background:#fff; border-style:dashed; text-decoration:line-through; }
.chart-box .lg.off i { opacity:.3; }
.chart-box .lg i { display:inline-block; width:9px; height:9px; border-radius:50%; flex:none; }
.chart-box .lg-reset { margin-left:auto; background:#fff; border-color:#dfe3ea; color:#2f6fed; }
.muted { color:#9aa0a6; }
pre { background:#0f172a; color:#e2e8f0; padding:14px 16px; border-radius:10px; font-size:13px; white-space:pre-wrap; }
"""


def build_dashboard(cfg: dict, agent2_summary: dict, out_dir: str = "output") -> str:
    video_path = os.path.join(out_dir, "视频数据监控.csv")
    alert_path = os.path.join(out_dir, "点赞预警.csv")
    comment_path = os.path.join(out_dir, "评论关键词命中.csv")
    play_path = os.path.join(out_dir, "播放量.csv")
    promo_path = os.path.join(out_dir, "推广账号表.csv")
    mgmt_path = os.path.join(out_dir, "综合管理表.csv")

    videos = _read_csv(video_path)
    alerts = _read_csv(alert_path)
    comments = _read_csv(comment_path)
    plays = _read_csv(play_path)

    # 点赞增长时间序列（按视频ID；x 坐标 0 起，与 _line_chart 的 i/(n-1) 对齐）
    series_map = OrderedDict()
    meta = {}
    for row in videos:
        aid = row["视频ID"]
        if aid not in series_map:
            series_map[aid] = []
            meta[aid] = row["账号"]
        series_map[aid].append((len(series_map[aid]), int(row["点赞"] or 0)))
    # 多视频可能同账号：标签带视频ID区分，避免曲线重叠认不出
    series = [(f"{meta[aid]}·{aid}", series_map[aid]) for aid in series_map]

    # 最新一行/视频
    latest = {}
    for row in videos:
        latest[row["视频ID"]] = row

    # 最新播放
    play_latest = {}
    for row in plays:
        play_latest[row["视频ID"]] = row

    n_scans = max((len(v) for v in series_map.values()), default=0)

    def table(headers, rows, cls=""):
        h = "".join(f"<th>{h}</th>" for h in headers)
        body = ""
        for r in rows:
            tds = "".join(f"<td>{c}</td>" for c in r)
            body += f"<tr class='{cls}'>{tds}</tr>"
        return f"<table><thead><tr>{h}</tr></thead><tbody>{body}</tbody></table>"

    video_rows = [[v["账号"], v["视频ID"], v["标题"], v["点赞"], v["播放"], v["评论数"], v["扫描时间"]]
                  for v in latest.values()]
    alert_rows = [[a["账号"], a["标题"], a["上次点赞"], a["本次点赞"], a["增量"], a["阈值"], a["预警人"]]
                  for a in alerts]
    comment_rows = [[c["账号"], c["标题"], c["评论内容"], c["命中关键词"], c["自动回复话术"], c["处理方式"]]
                   for c in comments]
    play_rows = [[p["账号"], p["标题"], p["播放量"], p["扫描时间"]]
                 for p in play_latest.values()]

    promo = _read_csv(promo_path)
    mgmt = _read_csv(mgmt_path)
    promo_rows = [[p.get(k, "") for k in ["歌曲", "博主", "报价", "抖加", "抖加支付人", "是否打款", "打款人", "打款日期", "是否接单"]]
                  for p in promo]
    mgmt_rows = [[m.get(k, "") for k in ["歌曲", "抖加花费", "垫付花费", "接单达人数", "垫付待打款笔数", "合计花费"]]
                 for m in mgmt]
    report = agent2_summary.get("master", {}).get("report", "")

    # 当前生效阈值（与 Monitor._resolve_threshold 同口径）：
    # 3 分钟真实间隔演示会自动下调到 demo_slow_like_threshold，看板须如实显示
    a = cfg["alert"]
    if cfg.get("mode", "demo") == "demo":
        eff_threshold = int(a.get(
            "demo_like_threshold" if cfg["monitor"].get("demo_fast", True)
            else "demo_slow_like_threshold", a["like_threshold"]))
    else:
        eff_threshold = int(a["like_threshold"])

    html = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>抖音数据监控 Agent · 演示看板</title><style>{CSS}</style></head>
<body>
<div class="header">
  <h1>抖音数据监控 Agent · 面试演示看板</h1>
  <p>题目1（核心）：账号视频数据监控 / 点赞预警 / 评论自动回复 / 播放量采集 → 写入飞书　|　题目2（辅助）：Master/Sub Agent 费用汇总</p>
  <p>生成时间：{datetime.now():%Y-%m-%d %H:%M:%S}　阈值：{eff_threshold}（当前生效） / {cfg['alert']['like_threshold']}（题目规定）　监控账号：{', '.join(cfg['monitor']['accounts'])}</p>
</div>
<div class="wrap">
  <div class="cards">
    <div class="card"><div class="n">{len(latest)}</div><div class="l">监控视频数（近3天）</div></div>
    <div class="card"><div class="n">{n_scans}</div><div class="l">扫描次数</div></div>
    <div class="card"><div class="n">{len(alerts)}</div><div class="l">点赞预警条数</div></div>
    <div class="card"><div class="n">{len(comments)}</div><div class="l">评论命中条数</div></div>
    <div class="card"><div class="n">{len(play_latest)}</div><div class="l">播放量记录</div></div>
  </div>

  <div class="section">
    <h2>① 点赞增长趋势（每次扫描）</h2>
    {_line_chart(series)}
  </div>

  <div class="section">
    <h2>② 视频数据监控（最新一次扫描）</h2>
    {table(["账号","视频ID","标题","点赞","播放","评论数","扫描时间"], video_rows)}
  </div>

  <div class="section">
    <h2>③ 点赞增量预警（相邻扫描 &gt; 阈值 → 抖加加热）</h2>
    {table(["账号","标题","上次点赞","本次点赞","增量","阈值","预警人"], alert_rows, cls="alert") if alert_rows else '<p class="muted">暂无预警（可把 config.yaml 的 demo_like_threshold 调低以触发）</p>'}
  </div>

  <div class="section">
    <h2>④ 评论关键词命中 + 自动回复话术</h2>
    {table(["账号","标题","评论内容","命中关键词","自动回复话术","处理方式"], comment_rows) if comment_rows else '<p class="muted">暂无命中</p>'}
  </div>

  <div class="section">
    <h2>⑤ 播放量采集（最新）</h2>
    {table(["账号","标题","播放量","扫描时间"], play_rows)}
  </div>

  <div class="section">
    <h2>⑥ 题目2：Master / Sub Agent 综合管理报告</h2>
    <pre>{report}</pre>
  </div>

  <div class="section">
    <h2>⑦ 《推广账号表》（Sub-Agent 填写）</h2>
    {table(["歌曲","博主","报价","抖加","抖加支付人","是否打款","打款人","打款日期","是否接单"], promo_rows) if promo_rows else '<p class="muted">未生成</p>'}
  </div>

  <div class="section">
    <h2>⑧ 《综合管理表》（Master-Agent 填写）</h2>
    {table(["歌曲","抖加花费","垫付花费","接单达人数","垫付待打款笔数","合计花费"], mgmt_rows) if mgmt_rows else '<p class="muted">未生成</p>'}
  </div>
</div>
</body></html>"""

    out_path = os.path.join(out_dir, "dashboard.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return out_path
