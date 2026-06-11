#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(r"G:\AI\Material\Wwise")
OUT = ROOT / "报告" / "ProjectEF_AudioRequirement_Tool_Usage_Flow.png"
FONT_PATH = r"C:\Windows\Fonts\simhei.ttf"

W, H = 1800, 1250
BG = "#101820"
PANEL = "#172331"
PANEL2 = "#1f2e3f"
LINE = "#4c6278"
TEXT = "#eef5ff"
MUTED = "#aebdcc"
GREEN = "#45c0a5"
BLUE = "#5ba7ff"
ORANGE = "#f2b15f"
RED = "#ff7e79"
PURPLE = "#9d87ff"
YELLOW = "#f2d16b"


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    font_title = ImageFont.truetype(FONT_PATH, 52)
    font_sub = ImageFont.truetype(FONT_PATH, 26)
    font_h = ImageFont.truetype(FONT_PATH, 32)
    font_b = ImageFont.truetype(FONT_PATH, 22)
    font_small = ImageFont.truetype(FONT_PATH, 20)
    font_tiny = ImageFont.truetype(FONT_PATH, 18)
    font_tag = ImageFont.truetype(FONT_PATH, 22)

    def round_rect(xy, radius, fill, outline=None, width=2):
        draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)

    def text(x, y, value, font, fill=TEXT, anchor=None):
        draw.text((x, y), value, font=font, fill=fill, anchor=anchor)

    def wrap_lines(value, font, max_width):
        lines = []
        for raw in value.split("\n"):
            if not raw:
                lines.append("")
                continue
            if draw.textlength(raw, font=font) <= max_width:
                lines.append(raw)
                continue
            current = ""
            for char in raw:
                test = current + char
                if current and draw.textlength(test, font=font) > max_width:
                    lines.append(current)
                    current = char
                else:
                    current = test
            if current:
                lines.append(current)
        return lines

    def multiline(x, y, value, font, fill=TEXT, line_gap=8, max_width=320):
        lines = wrap_lines(value, font, max_width)
        yy = y
        for line in lines:
            draw.text((x, yy), line, font=font, fill=fill)
            yy += font.size + line_gap
        return yy

    def box(x, y, w, h, title, body, color, footer=None):
        round_rect((x, y, x + w, y + h), 18, PANEL, color, 3)
        draw.rectangle((x, y, x + 10, y + h), fill=color)
        text(x + 28, y + 22, title, font_h)
        multiline(x + 28, y + 72, body, font_b, MUTED, 7, w - 56)
        if footer:
            round_rect((x + 24, y + h - 48, x + w - 24, y + h - 18), 9, "#0e151d")
            text(x + 40, y + h - 43, footer, font_small, color)

    def arrow(x1, y1, x2, y2, color=LINE):
        draw.line((x1, y1, x2, y2), fill=color, width=5)
        if x2 >= x1:
            points = [(x2, y2), (x2 - 18, y2 - 10), (x2 - 18, y2 + 10)]
        else:
            points = [(x2, y2), (x2 + 18, y2 - 10), (x2 + 18, y2 + 10)]
        draw.polygon(points, fill=color)

    text(70, 48, "ProjectEF 音频需求 / Jira 辅助判断工具", font_title)
    text(72, 116, "只读扫描策划案，匹配 Jira，定位证据，生成变更报告；不修改 Unity / Wwise / Jira / P4", font_sub, MUTED)
    round_rect((1450, 52, 1715, 112), 16, "#0e151d", GREEN, 2)
    text(1582, 68, "定位：初筛 + 证据导航", font_tag, GREEN, "ma")

    box(
        70,
        190,
        440,
        310,
        "1 输入",
        "Design 目录：D:\\EF New\\Design\n支持 .docx / .xlsx / .md / .txt / .pdf\n\nJira 单 / JQL / 粘贴文本\nOllama 本地模型（可选）",
        BLUE,
        "所有输入均只读",
    )
    box(
        680,
        190,
        440,
        310,
        "2 扫描与建库",
        "解析文档并切片\n抽取音频候选\n记录证据位置\n保存 index + snapshots\n\n后续扫描只比较变化",
        GREEN,
        "规则模式 0 token",
    )
    box(
        1290,
        190,
        440,
        310,
        "3 匹配与判断",
        "Jira 内容 ↔ 策划证据\n关键词 + 对象词 + 分数\n输出：Yes / Maybe / No\nReady / DesignOnly / Risky\n\n证据弱时不会硬判",
        ORANGE,
        "可选本地 AI 复核",
    )
    arrow(520, 345, 660, 345)
    arrow(1130, 345, 1270, 345)

    round_rect((70, 550, 1730, 790), 24, "#121e29", LINE, 2)
    text(100, 578, "输出给你的东西", font_h)
    box(110, 635, 360, 190, "证据位置", "策划案路径\nSheet / Row / Line / Page\n可直接打开原文件查看", BLUE)
    box(525, 635, 360, 190, "需求结论", "是否需要音频\nReady 状态\n置信度与原因\n需要问谁", GREEN)
    box(940, 635, 360, 190, "变更报告", "新增 / 修改文档\n可能新增的音频需求\n按风险和类型排序", PURPLE)
    box(1355, 635, 330, 190, "Codex Pack", "把变化压缩成审阅包\n避免反复读取全量策划案", YELLOW)

    round_rect((70, 865, 1730, 1135), 24, PANEL2, "#37516a", 2)
    text(100, 895, "日常怎么用", font_h)
    steps = [
        ("打开工具", "工具库 GUI\n选择 Audio Requirement\nJira Triage GUI", BLUE),
        ("看策划变更", "点击 Scan + Diff Changes\n查看新增候选和报告", PURPLE),
        ("查某个 Jira", "Sync Issue 或粘贴文本\n点击 Match All Issues", ORANGE),
        ("确认证据", "选中结果\n→ Open Evidence File\n→ Copy Jira Reply Draft", GREEN),
        ("需要 AI", "本地 Ollama / Hybrid\n或导出 Codex Pack\n只审阅少量候选", YELLOW),
    ]
    for i, (title, body, color) in enumerate(steps):
        x = 105 + i * 330
        round_rect((x, 955, x + 285, 1088), 16, "#0e151d", color, 3)
        text(x + 22, 974, f"{i + 1}. {title}", font_tag)
        multiline(x + 22, 1010, body, font_tiny, MUTED, 5, 245)
        if i < len(steps) - 1:
            arrow(x + 292, 1020, x + 322, 1020, "#6f8296")

    round_rect((70, 1168, 1730, 1218), 12, "#0e151d", RED, 2)
    text(
        95,
        1180,
        "安全边界：工具只做读取、索引、匹配、报告；不会提交、不改源文档、不改项目音频底层。Jira 若未登录，请粘贴 Cookie 或直接粘贴单子文本。",
        font_small,
        MUTED,
    )

    img.save(OUT)
    print(OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
