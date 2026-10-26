# -*- coding: utf-8 -*-
"""逐帧绘制「抖音数据监控 Agent」演示视频，输出 mp4 到桌面。
不依赖浏览器：用 Pillow 画每一帧，imageio-ffmpeg(libx264) 编码。
"""
import os
import math
import numpy as np
import imageio.v2 as imageio
from PIL import Image, ImageDraw, ImageFont

# ---------- 基础配置 ----------
W, H = 1280, 720
FPS = 30
TOTAL = 28.0
FONT_DIR = "C:/Windows/Fonts"

def F(size, bold=False):
    path = os.path.join(FONT_DIR, "msyhbd.ttc" if bold else "msyh.ttc")
    return ImageFont.truetype(path, size)

# 颜色
BG       = (15, 19, 32)
PANEL    = (23, 28, 38)
PANEL2   = (10, 14, 21)
BORDER   = (42, 49, 64)
TEXT     = (232, 236, 241)
MUTED    = (139, 148, 163)
RED      = (254, 44, 85)      # 抖音红
CYAN     = (37, 244, 238)
BLUE     = (90, 169, 255)
GREEN    = (46, 204, 113)
AMBER    = (245, 166, 35)
WHITE    = (255, 255, 255)

# ---------- 数据 ----------
ACCOUNTS = ["卡带森林", "佳佳", "小柯", "阿阳"]
ACC_COLORS = [RED, CYAN, AMBER, GREEN]
ACC_LIKES = [
    [1024, 1430, 1880, 2350],
    [820, 1180, 1500, 1950],
    [540, 760, 980, 1230],
    [1300, 1650, 2050, 2500],
]
YMAX = 2600

TERMINAL = [
    ("[配置]", "加载 5 个监控账号：卡带森林/佳佳/小柯/阿阳/夜行人", CYAN),
    ("[扫描]", "第 1 次扫描 · 模拟时间 Day1 12:00", BLUE),
    ("",      "卡带森林   点赞 1024  ↑406", TEXT),
    ("",      "佳佳超有才 点赞 820   ↑360", TEXT),
    ("",      "小柯唱歌   点赞 540   ↑280", TEXT),
    ("",      "阿阳音乐   点赞 1300  ↑420", TEXT),
    ("[预警]", "增量>300 触发「抖加加热」×3 → 推送测试者", RED),
    ("[扫描]", "第 2 次扫描 · 模拟时间 Day1 18:00", BLUE),
    ("",      "卡带森林   点赞 1430  ↑406", TEXT),
    ("",      "佳佳超有才 点赞 1180  ↑360", TEXT),
    ("",      "小柯唱歌   点赞 760   ↑220", TEXT),
    ("",      "阿阳音乐   点赞 1650  ↑350", TEXT),
    ("[预警]", "增量>300 触发「抖加加热」×3 → 推送测试者", RED),
    ("[评论]", "命中关键词 10 类：BGM/bgm/求歌名/什么歌/背景音乐…", CYAN),
    ("[回复]", "强意图 → 自动回复 6 套话术（如「背景音乐已置顶评论」）", GREEN),
    ("[回复]", "弱意图（好听/歌）→ 转人工预警，避免误伤", GREEN),
    ("[采集]", "播放量采集完成：4 账号 × 4 轮", TEXT),
    ("[扫描]", "第 3 / 4 次扫描完成，趋势见右侧看板", BLUE),
    ("[完成]", "题目1 核心链路跑通 √", GREEN),
]
TERM_START = 1.8
TERM_INT = 0.5

# ---------- 工具 ----------
def rounded(draw, box, r, fill=None, outline=None, width=1):
    draw.rounded_rectangle(box, radius=r, fill=fill, outline=outline, width=width)

def t(draw, xy, s, font, fill, anchor=None):
    draw.text(xy, s, font=font, fill=fill, anchor=anchor)

def lerp(a, b, u):
    return a + (b - a) * u

def clamp(v, lo, hi):
    return max(lo, min(hi, v))

# ---------- 场景绘制 ----------
def draw_topbar(draw, alpha):
    t(draw, (40, 6), "抖音数据监控 Agent", F(28, True), TEXT)
    t(draw, (42, 46), "面试演示 · Agent 岗位", F(15), MUTED)
    # DEMO 胶囊（贴右，避免与副标题重叠）
    rounded(draw, (1136, 18, 1244, 48), 15, fill=(20, 40, 46), outline=CYAN, width=1)
    t(draw, (1190, 33), "● DEMO", F(16, True), CYAN, anchor="mm")

def draw_terminal(base, t_, shown):
    x0, y0, w, h = 36, 76, 596, 596
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    rounded(d, (x0, y0, x0 + w, y0 + h), 14, fill=PANEL2 + (255,), outline=BORDER, width=1)
    # 头部 mac 风圆点 + 标题
    for i, c in enumerate([RED, AMBER, GREEN]):
        d.ellipse([x0 + 18 + i * 20, y0 + 18, x0 + 30 + i * 20, y0 + 30], fill=c)
    t(d, (x0 + 96, y0 + 24), "运行日志  ·  run_demo.py", F(16, True), MUTED, anchor="lm")
    # 可见行（末尾若干行）
    inner_x = x0 + 18
    start_y = y0 + 48
    lh = 29
    visible = 17
    start = max(0, shown - visible)
    f_reg = F(17)
    for row, idx in enumerate(range(start, shown)):
        tag, txt, col = TERMINAL[idx]
        yy = start_y + row * lh
        xx = inner_x
        if tag:
            t(d, (xx, yy), tag, f_reg, col, anchor="la")
            tw = d.textlength(tag, font=f_reg)
            xx += tw + 8
        t(d, (xx, yy), txt, f_reg, col if tag else TEXT, anchor="la")
    # 闪烁光标
    if (t_ * 2) % 1 < 0.5 and shown < len(TERMINAL):
        last_row = min(visible - 1, shown - start - 1)
        yy = start_y + last_row * lh
        t(d, (inner_x, yy), "▋", f_reg, GREEN, anchor="la")
    base.paste(layer, (0, 0), layer)

def draw_stats(base, t_, shown):
    scans = clamp(sum(shown >= th for th in [2, 8, 15, 18]), 1, 4)
    alerts = scans * 3
    replies = 9 if shown >= 15 else (3 if shown >= 14 else 0)
    tiles = [("监控账号", "5"), ("扫描轮次", str(scans)),
             ("抖加预警", str(alerts)), ("自动回复", str(replies))]
    x0, y0, w, h = 652, 76, 592, 120
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    rounded(d, (x0, y0, x0 + w, y0 + h), 14, fill=PANEL + (255,), outline=BORDER, width=1)
    tw = w / 4
    for i, (lab, val) in enumerate(tiles):
        cx = x0 + tw * i + tw / 2
        t(d, (cx, y0 + 30), val, F(34, True), WHITE, anchor="mm")
        t(d, (cx, y0 + 78), lab, F(16), MUTED, anchor="mm")
        if i > 0:
            d.line([x0 + tw * i, y0 + 22, x0 + tw * i, y0 + h - 22], fill=BORDER, width=1)
    base.paste(layer, (0, 0), layer)

def draw_stage_loading(base, t_, a):
    x0, y0, w, h = 652, 212, 592, 460
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    rounded(d, (x0, y0, x0 + w, y0 + h), 14, fill=PANEL + (255,), outline=BORDER, width=1)
    t(d, (x0 + 20, y0 + 18), "正在采集 · 近 3 天视频", F(20, True), TEXT, anchor="la")
    accs = [("卡带森林·卡带_0", "12 条视频"), ("佳佳超有才·佳佳_1", "9 条视频"),
            ("小柯唱歌·小柯_2", "15 条视频"), ("阿阳音乐·阿阳_3", "11 条视频"),
            ("夜行人·夜行_4", "8 条视频")]
    idx = clamp(int((t_ - 2.0) / 0.85) + 1, 0, len(accs))
    yy = y0 + 74
    for i, (name, cnt) in enumerate(accs):
        if i >= idx:
            break
        d.ellipse([x0 + 24, yy - 5, x0 + 34, yy + 5], fill=GREEN)
        t(d, (x0 + 46, yy), name, F(16), TEXT, anchor="lm")
        t(d, (x0 + w - 24, yy), cnt, F(15), MUTED, anchor="rm")
        yy += 42
    ph = (t_ * 2.5) % 1
    dots = "." * (1 + int(ph * 3))
    t(d, (x0 + 24, y0 + h - 44), "采集中" + dots, F(16), CYAN, anchor="la")
    # 按图层自身 alpha 淡化（不能用全不透明 L 遮罩，否则透明区会被涂黑）
    if a < 1:
        alpha = layer.getchannel("A").point(lambda v: int(v * a))
        layer.putalpha(alpha)
    base.paste(layer, (0, 0), layer)

def draw_stage_chart(base, t_):
    x0, y0, w, h = 652, 212, 592, 460
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    rounded(d, (x0, y0, x0 + w, y0 + h), 14, fill=PANEL + (255,), outline=BORDER, width=1)
    t(d, (x0 + 20, y0 + 18), "点赞趋势看板（4 轮扫描）", F(20, True), TEXT, anchor="la")
    px0, py0, px1, py1 = x0 + 56, y0 + 60, x0 + w - 24, y0 + h - 70
    # 网格 + Y 轴标签
    for g in range(5):
        v = YMAX * g / 4
        yy = py1 - (py1 - py0) * (g / 4)
        d.line([px0, yy, px1, yy], fill=BORDER, width=1)
        if g > 0:
            t(d, (px0 - 8, yy), str(int(v)), F(12), MUTED, anchor="ra")
    d.line([px0, py0, px0, py1], fill=BORDER, width=1)
    d.line([px0, py1, px1, py1], fill=BORDER, width=1)
    for i in range(4):
        xx = px0 + (px1 - px0) * (i / 3)
        t(d, (xx, py1 + 12), f"#{i + 1}", F(13), MUTED, anchor="ma")
    # 进度
    p = clamp((t_ - 9.0) / 5.5, 0, 1)
    front = p * 3
    for ai, vals in enumerate(ACC_LIKES):
        col = ACC_COLORS[ai]
        def xp(i): return px0 + (px1 - px0) * (i / 3)
        def yp(v): return py1 - (py1 - py0) * (v / YMAX)
        for i in range(3):
            if front <= i:
                break
            endf = min(front, i + 1)
            xa, ya = xp(i), yp(vals[i])
            xb = xp(endf)
            vb = lerp(vals[i], vals[i + 1], endf - i)
            yb = yp(vb)
            d.line([xa, ya, xb, yb], fill=col, width=3)
        for i in range(4):
            if front >= i - 0.001:
                d.ellipse([xp(i) - 4, yp(vals[i]) - 4, xp(i) + 4, yp(vals[i]) + 4], fill=col)
    # 图例
    ly = y0 + h - 34
    lx = px0
    for ai, name in enumerate(ACCOUNTS):
        col = ACC_COLORS[ai]
        d.ellipse([lx, ly - 5, lx + 10, ly + 5], fill=col)
        t(d, (lx + 16, ly), name, F(14), TEXT, anchor="lm")
        lx += 70 + d.textlength(name, font=F(14))
    base.paste(layer, (0, 0), layer)

def draw_stage_cards(base, t_):
    x0, y0, w, h = 652, 212, 592, 460
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    rounded(d, (x0, y0, x0 + w, y0 + h), 14, fill=PANEL + (255,), outline=BORDER, width=1)
    cw = (w - 60) / 2
    # 卡片 A：抖加预警
    ax, ay = x0 + 20, y0 + 24
    rounded(d, (ax, ay, ax + cw, ay + h - 48), 12, fill=PANEL2 + (255,), outline=RED, width=1)
    t(d, (ax + 16, ay + 16), "▲ 抖加加热预警", F(20, True), RED, anchor="la")
    t(d, (ax + 16, ay + 56), "账号 卡带森林", F(16), TEXT, anchor="la")
    t(d, (ax + 16, ay + 82), "近一轮点赞增量 +406", F(16), TEXT, anchor="la")
    t(d, (ax + 16, ay + 108), "已超过阈值 300", F(16), TEXT, anchor="la")
    t(d, (ax + 16, ay + 150), "人工确认后执行（半自动）", F(14), MUTED, anchor="la")
    b1l, b1r = ax + 16, ax + 16 + (cw - 40) / 2
    b2l, b2r = b1r, ax + cw - 16
    by_, bh = ay + h - 110, ay + h - 70
    rounded(d, (b1l, by_, b1r, bh), 8, fill=GREEN, width=0)
    t(d, ((b1l + b1r) / 2, ay + h - 90), "√ 同意加热", F(15, True), WHITE, anchor="mm")
    rounded(d, (b2l, by_, b2r, bh), 8, fill=(60, 66, 78), width=0)
    t(d, ((b2l + b2r) / 2, ay + h - 90), "× 驳回", F(15, True), TEXT, anchor="mm")
    # 卡片 B：评论回复
    bx, by = ax + cw + 20, ay
    rounded(d, (bx, by, bx + cw, by + h - 48), 12, fill=PANEL2 + (255,), outline=CYAN, width=1)
    t(d, (bx + 16, by + 16), "● 评论自动回复", F(20, True), CYAN, anchor="la")
    t(d, (bx + 16, by + 56), "评论：「求歌名！太喜欢了」", F(15), TEXT, anchor="la")
    t(d, (bx + 16, by + 82), "命中【强意图】→ 自动回复：", F(15), GREEN, anchor="la")
    t(d, (bx + 16, by + 108), "「歌名已置顶在评论区～」", F(15), TEXT, anchor="la")
    t(d, (bx + 16, by + 150), "弱意图（好听/歌）→ 转人工", F(14), MUTED, anchor="la")
    t(d, (bx + 16, by + 174), "6 套话术轮换，防误伤", F(14), MUTED, anchor="la")
    base.paste(layer, (0, 0), layer)

def draw_stage_agent2(base, t_):
    x0, y0, w, h = 652, 212, 592, 460
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    rounded(d, (x0, y0, x0 + w, y0 + h), 14, fill=PANEL + (255,), outline=BORDER, width=1)
    t(d, (x0 + 20, y0 + 18), "题目2 · Master / Sub 费用汇总", F(20, True), TEXT, anchor="la")
    steps = ["Sub（推广助手）解析抖加/垫付申请 9 条",
             "→ 填写《推广账号表》",
             "→ 通知 Master（综合助手）",
             "→ 汇总《综合管理表》",
             "→ 23:00 自动报告管理者"]
    yy = y0 + 64
    for s in steps:
        d.ellipse([x0 + 24, yy - 5, x0 + 34, yy + 5], fill=BLUE)
        t(d, (x0 + 46, yy), s, F(16), TEXT, anchor="lm")
        yy += 34
    # 对账高亮
    hy = yy + 8
    rounded(d, (x0 + 20, hy, x0 + w - 20, hy + 78), 10, fill=(46, 30, 18), outline=AMBER, width=1)
    t(d, (x0 + 36, hy + 18), "财务对账：垫付群 ¥2595 vs 明细 ¥2250", F(16, True), AMBER, anchor="la")
    t(d, (x0 + 36, hy + 48), "差额 ¥345 → 触发预警", F(16, True), AMBER, anchor="la")
    base.paste(layer, (0, 0), layer)

def draw_end(base, t_, a):
    layer = Image.new("RGBA", (W, H), (0, 0, 0, int(255 * a)))
    d = ImageDraw.Draw(layer)
    layer2 = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d2 = ImageDraw.Draw(layer2)
    t(d2, (W / 2, 270), "√ 核心功能全链路跑通", F(46, True), WHITE, anchor="mm")
    t(d2, (W / 2, 330), "题目1 抖音数据监控  ＋  题目2 费用汇总", F(22), CYAN, anchor="mm")
    chips = ["增量预警", "关键词自动回复", "飞书交互闭环", "财务对账", "双数据源(mock+live)"]
    cw = 200
    total_w = cw * len(chips)
    sx = W / 2 - total_w / 2 + cw / 2
    for i, c in enumerate(chips):
        cx = sx + i * cw
        rounded(d2, (cx - 92, 390, cx + 92, 430), 16, fill=(30, 36, 48), outline=ACC_COLORS[i % 4], width=1)
        t(d2, (cx, 410), c, F(15, True), TEXT, anchor="mm")
    layer = Image.alpha_composite(layer, layer2)
    base.paste(layer, (0, 0), layer)

def build_frame(t_):
    img = Image.new("RGB", (W, H), BG)
    # 背景辉光
    bg = ImageDraw.Draw(img)
    bg.ellipse([-200, -200, 500, 500], fill=(40, 12, 24))
    bg.ellipse([900, 300, 1500, 900], fill=(8, 30, 34))
    # 标题场景（不画顶栏，避免站名重复）
    if t_ < 1.8:
        a = clamp(t_ / 1.8, 0, 1)
        layer = Image.new("RGBA", (W, H), (0, 0, 0, int(255 * a)))
        d = ImageDraw.Draw(layer)
        t(d, (W / 2, 320), "抖音数据监控 Agent", F(54, True), WHITE, anchor="mm")
        t(d, (W / 2, 388), "面试演示 · 题目1 核心 ＋ 题目2 辅助", F(24), CYAN, anchor="mm")
        img.paste(layer, (0, 0), layer)
        return np.asarray(img)
    draw_topbar(bg, 1.0)
    shown = clamp(int((t_ - TERM_START) / TERM_INT) + 1, 0, len(TERMINAL))
    draw_terminal(img, t_, shown)
    draw_stats(img, t_, shown)
    # stage 场景切换
    if 9.0 <= t_ < 15.0:
        draw_stage_chart(img, t_)
    elif 15.0 <= t_ < 21.0:
        draw_stage_cards(img, t_)
    elif 21.0 <= t_ < 25.0:
        draw_stage_agent2(img, t_)
    else:
        if t_ < 9.0:
            draw_stage_loading(img, t_, clamp((t_ - 1.8) / 1.0, 0, 1))
        elif t_ >= 25.0:
            draw_end(img, t_, clamp((t_ - 25.0) / 0.4, 0, 1))
    # 底部进度条
    pb = ImageDraw.Draw(img)
    pr = clamp(t_ / TOTAL, 0, 1)
    pb.line([36, 706, 1244, 706], fill=BORDER, width=2)
    pb.line([36, 706, 36 + (1244 - 36) * pr, 706], fill=RED, width=2)
    return np.asarray(img)

def main():
    out = "C:/Users/13278/Desktop/抖音监控Agent_演示.mp4"
    writer = imageio.get_writer(out, fps=FPS, codec="libx264", quality=8,
                                macro_block_size=1,
                                ffmpeg_params=["-pix_fmt", "yuv420p"])
    n = int(TOTAL * FPS)
    for i in range(n):
        t_ = i / FPS
        writer.append_data(build_frame(t_))
    writer.close()
    print("✅ 视频已生成：", out, " 帧数:", n, " 时长: %.1fs" % TOTAL)

if __name__ == "__main__":
    main()
