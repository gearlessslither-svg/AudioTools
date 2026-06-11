#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(r"G:\AI\Material\Wwise")
OUT = ROOT / "\u62a5\u544a" / "ProjectEF_AudioRequirement_Jira_EdgeFlow.png"
FONT_PATH = r"C:\Windows\Fonts\simhei.ttf"

W, H = 1800, 1220
BG = "#101820"
PANEL = "#172331"
DARK = "#0e151d"
TEXT = "#eef5ff"
MUTED = "#aebdcc"
LINE = "#4c6278"
BLUE = "#5ba7ff"
GREEN = "#45c0a5"
ORANGE = "#f2b15f"
PURPLE = "#9d87ff"
YELLOW = "#f2d16b"
RED = "#ff7e79"


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    ft = ImageFont.truetype(FONT_PATH, 50)
    fs = ImageFont.truetype(FONT_PATH, 26)
    fh = ImageFont.truetype(FONT_PATH, 32)
    fb = ImageFont.truetype(FONT_PATH, 23)
    fsmall = ImageFont.truetype(FONT_PATH, 20)

    def rr(xy, r, fill, outline=None, width=2):
        draw.rounded_rectangle(xy, radius=r, fill=fill, outline=outline, width=width)

    def text(x, y, s, font, fill=TEXT, anchor=None):
        draw.text((x, y), s, font=font, fill=fill, anchor=anchor)

    def lines(x, y, s, font=fb, fill=MUTED, gap=8):
        yy = y
        for line in s.split("\n"):
            draw.text((x, yy), line, font=font, fill=fill)
            yy += font.size + gap

    def card(x, y, w, h, n, title, body, color, tag=""):
        rr((x, y, x + w, y + h), 18, PANEL, color, 3)
        draw.rectangle((x, y, x + 10, y + h), fill=color)
        text(x + 28, y + 24, f"{n}. {title}", fh)
        lines(x + 28, y + 78, body)
        if tag:
            rr((x + 24, y + h - 50, x + w - 24, y + h - 18), 9, DARK)
            text(x + 40, y + h - 44, tag, fsmall, color)

    def arrow(x1, y1, x2, y2):
        draw.line((x1, y1, x2, y2), fill=LINE, width=5)
        draw.polygon([(x2, y2), (x2 - 18, y2 - 10), (x2 - 18, y2 + 10)], fill=LINE)

    text(70, 48, "Edge 登录态同步 Jira：实际使用流程", ft)
    text(72, 114, "你已经在 Edge 登录 Jira 时，用这个流程把 yupeng 的 Jira 单同步到音频需求筛选工具", fs, MUTED)
    rr((1390, 52, 1725, 112), 16, DARK, GREEN, 2)
    text(1558, 68, "Cookie 不保存，只当前窗口使用", fsmall, GREEN, "ma")

    card(
        70,
        190,
        480,
        230,
        "1",
        "先确认 Edge 已登录",
        "在 Edge 打开 Jira\n确认能看到问题导航器和你的单子\n这一步只是确认登录有效",
        BLUE,
    )
    card(
        660,
        190,
        480,
        230,
        "2",
        "完全关闭 Edge",
        "关闭所有 Edge 窗口\n如果后台还有 msedge.exe\n在任务管理器里结束它",
        ORANGE,
        "原因：Edge 会锁住 Cookie 数据库",
    )
    card(
        1250,
        190,
        480,
        230,
        "3",
        "点 Use Browser Login",
        "重新打开 Jira 工具\n点击 Use Browser Login\n成功后 Test Jira 不再显示登录页",
        GREEN,
        "读到后可重新打开 Edge",
    )
    arrow(560, 305, 650, 305)
    arrow(1150, 305, 1240, 305)

    rr((70, 485, 1730, 785), 24, "#1f2e3f", "#37516a", 2)
    text(100, 518, "同步和分类", fh)
    card(
        110,
        590,
        360,
        175,
        "4",
        "Sync JQL",
        "默认筛 yupeng：\nassignee = yupeng\nLimit 控制数量",
        PURPLE,
    )
    card(
        525,
        590,
        360,
        175,
        "5",
        "Match All Issues",
        "匹配策划证据\n判断是否需要音频\n生成证据位置",
        GREEN,
    )
    card(
        940,
        590,
        360,
        175,
        "6",
        "筛选查看",
        "按 System / Version / Start 筛\nReady = 可开始\nDesignOnly = 先看设计",
        BLUE,
    )
    card(
        1355,
        590,
        330,
        175,
        "7",
        "导出或回复",
        "Open Evidence File\nCopy Jira Reply Draft\nExport Report",
        YELLOW,
    )
    arrow(480, 666, 515, 666)
    arrow(895, 666, 930, 666)
    arrow(1310, 666, 1345, 666)

    rr((70, 840, 1730, 1100), 24, "#121e29", LINE, 2)
    text(100, 873, "结果字段怎么看", fh)
    items = [
        ("Audio?", "Yes / Maybe / No\n是否真的像音频需求", BLUE),
        ("Start?", "Ready 可开始\nRisky/Blocked 先问清楚", GREEN),
        ("System", "UI / Fishing / Environment\n来自最匹配的策划证据", PURPLE),
        ("Version", "优先读 Jira Fix Version\n没有就从标题/描述推断", ORANGE),
        ("Best Evidence", "策划路径 + Sheet/Row/Line/Page\n用来快速回查", YELLOW),
    ]
    for i, (name, body, color) in enumerate(items):
        x = 105 + i * 330
        rr((x, 948, x + 285, 1068), 16, DARK, color, 3)
        text(x + 22, 970, name, fb)
        lines(x + 22, 1012, body, fsmall, MUTED, 5)

    rr((70, 1148, 1730, 1198), 12, DARK, RED, 2)
    text(95, 1160, "注意：如果不想关闭 Edge，可用 Import Jira CSV 作为旁路；工具不会修改 Jira、Unity、Wwise 或 P4。", fsmall, MUTED)

    img.save(OUT)
    print(OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
