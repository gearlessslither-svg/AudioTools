#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(r"G:\AI\Material\Wwise")
OUT = ROOT / "报告" / "ProjectEF_AudioRequirement_Jira_NewFlow.png"
FONT_PATH = r"C:\Windows\Fonts\simhei.ttf"

W, H = 1800, 1240
BG = "#101820"
PANEL = "#172331"
PANEL_DARK = "#0e151d"
PANEL_LIGHT = "#1f2e3f"
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

    font_title = ImageFont.truetype(FONT_PATH, 50)
    font_sub = ImageFont.truetype(FONT_PATH, 26)
    font_h = ImageFont.truetype(FONT_PATH, 32)
    font_b = ImageFont.truetype(FONT_PATH, 23)
    font_s = ImageFont.truetype(FONT_PATH, 20)
    font_xs = ImageFont.truetype(FONT_PATH, 18)

    def rr(xy, radius, fill, outline=None, width=2):
        draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)

    def t(x, y, value, font, fill=TEXT, anchor=None):
        draw.text((x, y), value, font=font, fill=fill, anchor=anchor)

    def wrap(value, font, max_width):
        lines = []
        for raw in value.split("\n"):
            if not raw:
                lines.append("")
                continue
            if draw.textlength(raw, font=font) <= max_width:
                lines.append(raw)
                continue
            current = ""
            for ch in raw:
                probe = current + ch
                if current and draw.textlength(probe, font=font) > max_width:
                    lines.append(current)
                    current = ch
                else:
                    current = probe
            if current:
                lines.append(current)
        return lines

    def mt(x, y, value, font, fill=MUTED, max_width=300, gap=7):
        yy = y
        for line in wrap(value, font, max_width):
            draw.text((x, yy), line, font=font, fill=fill)
            yy += font.size + gap
        return yy

    def box(x, y, w, h, number, title, body, color, tag=""):
        rr((x, y, x + w, y + h), 18, PANEL, color, 3)
        draw.rectangle((x, y, x + 10, y + h), fill=color)
        t(x + 28, y + 22, f"{number}. {title}", font_h)
        mt(x + 28, y + 72, body, font_b, MUTED, w - 56, 7)
        if tag:
            rr((x + 24, y + h - 48, x + w - 24, y + h - 18), 9, PANEL_DARK)
            t(x + 40, y + h - 43, tag, font_s, color)

    def arrow(x1, y1, x2, y2, color=LINE):
        draw.line((x1, y1, x2, y2), fill=color, width=5)
        points = [(x2, y2), (x2 - 18, y2 - 10), (x2 - 18, y2 + 10)]
        draw.polygon(points, fill=color)

    t(70, 48, "Jira 音频需求筛选工具：新使用流程", font_title)
    t(72, 114, "目标：直接复用你浏览器里的 Jira 登录态，拉取 yupeng 的 Jira 单，再按策划证据分类", font_sub, MUTED)
    rr((1370, 52, 1725, 112), 16, PANEL_DARK, GREEN, 2)
    t(1548, 68, "安全：不改项目，不保存 Cookie", font_s, GREEN, "ma")

    box(
        70,
        190,
        390,
        250,
        "1",
        "先登录浏览器",
        "Chrome / Edge 打开 Jira\n确认能看到你的单子\n然后回到工具",
        BLUE,
        "",
    )
    box(
        520,
        190,
        390,
        250,
        "2",
        "打开工具",
        "工具库 GUI\nAudio Requirement\nJira Triage GUI",
        PURPLE,
        "",
    )
    box(
        970,
        190,
        390,
        250,
        "3",
        "Use Browser Login",
        "点击按钮\n读取 Jira Cookie\n自动 Test Jira",
        GREEN,
        "成功=不是登录页",
    )
    arrow(470, 315, 510, 315)
    arrow(920, 315, 960, 315)

    rr((1420, 190, 1730, 440), 18, "#241c17", ORANGE, 3)
    t(1448, 218, "如果失败", font_h, TEXT)
    mt(
        1448,
        270,
        "通常是浏览器占用 Cookie 数据库，或你登录的不是 Chrome/Edge。\n\n关掉浏览器，重开工具，再点一次。",
        font_b,
        MUTED,
        250,
    )

    rr((70, 500, 1730, 805), 24, PANEL_LIGHT, "#37516a", 2)
    t(100, 530, "同步和分类", font_h)
    box(
        110,
        600,
        360,
        170,
        "4",
        "Sync JQL",
        "JQL：assignee = yupeng\nLimit：同步数量\n点击 Sync JQL",
        ORANGE,
    )
    box(
        525,
        600,
        360,
        170,
        "5",
        "Match All Issues",
        "匹配策划证据\n判断是否需要音频\n生成证据位置",
        GREEN,
    )
    box(
        940,
        600,
        360,
        170,
        "6",
        "筛选查看",
        "System / Version / Start\n下拉筛选\nReady 表示可开始",
        BLUE,
    )
    box(
        1355,
        600,
        330,
        170,
        "7",
        "导出/回复",
        "Open Evidence File\nCopy Jira Reply Draft\nExport Report",
        YELLOW,
    )
    arrow(480, 685, 515, 685)
    arrow(895, 685, 930, 685)
    arrow(1310, 685, 1345, 685)

    rr((70, 855, 1730, 1115), 24, "#121e29", LINE, 2)
    t(100, 885, "结果怎么看", font_h)

    result_boxes = [
        ("Audio?", "Yes / Maybe / No\n是否真的像音频需求", BLUE),
        ("Start?", "Ready：可开始\nDesignOnly：先看设计\nRisky/Blocked：先问清楚", GREEN),
        ("System", "UI / Fishing / Environment / Gameplay\n来自最匹配的策划证据", PURPLE),
        ("Version", "优先读 Jira Fix Version\n没有就从标题/描述推断", ORANGE),
        ("Best Evidence", "策划案路径 + Sheet/Row/Line/Page\n用来快速回查", YELLOW),
    ]
    for i, (title, body, color) in enumerate(result_boxes):
        x = 105 + i * 330
        rr((x, 955, x + 285, 1078), 16, PANEL_DARK, color, 3)
        t(x + 22, 975, title, font_b)
        mt(x + 22, 1012, body, font_xs, MUTED, 240, 5)

    rr((70, 1160, 1730, 1210), 12, PANEL_DARK, RED, 2)
    t(
        95,
        1172,
        "安全边界：Use Browser Login 只读取本机 Chrome/Edge 中 Jira 域名 Cookie；不打印、不保存到配置、不提交 Git；关闭工具后需要重新读取。",
        font_s,
        MUTED,
    )

    img.save(OUT)
    print(OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
