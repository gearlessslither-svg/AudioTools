# -*- coding: utf-8 -*-
from pathlib import Path
import math
import textwrap

from PIL import Image, ImageDraw, ImageFont


OUT = Path(r"G:\AI\Material\Wwise\ProjectEF_Bus_Routing_ModPlan_v2_2026-05-22.png")

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\NotoSansSC-VF.ttf",
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\Deng.ttf",
]
BOLD_CANDIDATES = [
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\Dengb.ttf",
    r"C:\Windows\Fonts\NotoSansSC-VF.ttf",
]


def pick_font(paths):
    for item in paths:
        if Path(item).exists():
            return item
    raise SystemExit("No usable Chinese font found")


FONT = pick_font(FONT_CANDIDATES)
BOLD = pick_font(BOLD_CANDIDATES)


def font(size, bold=False):
    return ImageFont.truetype(BOLD if bold else FONT, size)


F_TITLE = font(58, True)
F_SUB = font(28)
F_H = font(32, True)
F_BODY = font(24)
F_SMALL = font(24)
F_TINY = font(21)

COL = {
    "bg": "#f6f8fb",
    "ink": "#16212b",
    "muted": "#5f6b77",
    "line": "#8594a3",
    "white": "#ffffff",
    "blue": "#deefff",
    "blue_b": "#3b82c4",
    "green": "#e3f6e7",
    "green_b": "#4c9b61",
    "amber": "#fff0d7",
    "amber_b": "#c17a22",
    "red": "#ffe7e2",
    "red_b": "#c95d4e",
    "violet": "#efe9ff",
    "violet_b": "#7d63c5",
    "gray": "#eef2f5",
    "gray_b": "#98a4ae",
    "dark": "#263445",
}


def text_wh(draw, text, fnt):
    if not text:
        return 0, 0
    box = draw.textbbox((0, 0), text, font=fnt)
    return box[2] - box[0], box[3] - box[1]


def wrap_px(draw, text, fnt, max_width):
    lines = []
    for para in str(text).split("\n"):
        if para == "":
            lines.append("")
            continue
        cur = ""
        for ch in para:
            candidate = cur + ch
            if cur and text_wh(draw, candidate, fnt)[0] > max_width:
                lines.append(cur.rstrip())
                cur = ch.lstrip()
            else:
                cur = candidate
        if cur:
            lines.append(cur.rstrip())
    return lines


def draw_text(draw, x, y, text, fnt, fill, max_width, gap=7):
    for line in wrap_px(draw, text, fnt, max_width):
        draw.text((x, y), line, font=fnt, fill=fill)
        y += text_wh(draw, line or " ", fnt)[1] + gap
    return y


def panel(draw, x, y, w, h, title, body="", fill=None, border=None, body_font=None):
    fill = fill or COL["white"]
    border = border or COL["gray_b"]
    draw.rounded_rectangle([x, y, x + w, y + h], radius=16, fill=fill, outline=border, width=3)
    pad = 20
    yy = y + 18
    yy = draw_text(draw, x + pad, yy, title, F_H, COL["ink"], w - pad * 2, 7) + 4
    if body:
        draw_text(draw, x + pad, yy, body, body_font or F_BODY, COL["ink"], w - pad * 2, 7)


def bullet(items):
    return "\n".join(f"- {item}" for item in items)


def arrow(draw, start, end, color=None, width=5):
    color = color or COL["line"]
    x1, y1 = start
    x2, y2 = end
    draw.line([x1, y1, x2, y2], fill=color, width=width)
    ang = math.atan2(y2 - y1, x2 - x1)
    size = 18
    p1 = (x2 - size * math.cos(ang - math.pi / 6), y2 - size * math.sin(ang - math.pi / 6))
    p2 = (x2 - size * math.cos(ang + math.pi / 6), y2 - size * math.sin(ang + math.pi / 6))
    draw.polygon([end, p1, p2], fill=color)


def tree(draw, x, y, lines, fnt=F_SMALL, color=COL["ink"], gap=8):
    yy = y
    for level, text, tag in lines:
        xx = x + level * 34
        tag_color = {
            "keep": "#2e7d42",
            "add": "#1f6fb2",
            "risk": "#bd4f43",
            "old": "#485460",
        }.get(tag, color)
        draw.text((xx, yy), text, font=fnt, fill=tag_color)
        yy += text_wh(draw, text, fnt)[1] + gap
    return yy


def render():
    w, h = 2600, 3300
    img = Image.new("RGB", (w, h), COL["bg"])
    d = ImageDraw.Draw(img)

    d.text((86, 64), "ProjectEF Bus / 1P3P 路由改造方案", font=F_TITLE, fill=COL["ink"])
    draw_text(
        d,
        90,
        142,
        "只读分析版 v2：本图仅提出 Bus 与 Output Routing 改法，尚未修改 Wwise。修正重点：Player 系统必须先分 Male/Female，再分 Player/Others；Clother 应改名为 Clothes。",
        F_SUB,
        COL["muted"],
        2360,
        8,
    )

    panel(
        d,
        90,
        245,
        720,
        650,
        "当前 Bus 现状",
        bullet(
            [
                "Gear 已有 MainMix/SFX/Gear/Player 与 Others。",
                "Fish 目前只有 AudioObject_Ambient_3D/Fish 一条 Bus。",
                "Lure / Buzzbait 也输出到 Fish Bus。",
                "Footsteps 下已存在 Male / Female Bus。",
                "Footsteps 目前仍有 Female/Sneakers 旧层级。",
                "衣服 Bus 目前仍叫 Clother，需要改为 Clothes。",
                "刚修过的 Gear / Player 分支已有不同 attenuation，但部分系统还没有独立 Bus。",
            ]
        ),
        COL["blue"],
        COL["blue_b"],
        F_SMALL,
    )

    panel(
        d,
        940,
        245,
        720,
        650,
        "为什么需要分 Bus",
        bullet(
            [
                "Attenuation 只解决空间距离与衰减，不解决混音编组。",
                "Player / Others 在音量、压缩、ducking、优先级上通常不同。",
                "多人/近距离 Others 容易堆叠，最好能单独限声与压低。",
                "Player 的关键反馈需要更稳定、更靠前，不应被环境或多人噪声淹没。",
                "Bus 过细会增加维护成本，所以只给高收益系统加 Perspective 子 Bus。",
            ]
        ),
        COL["amber"],
        COL["amber_b"],
        F_SMALL,
    )

    panel(
        d,
        1790,
        245,
        720,
        650,
        "设计原则",
        bullet(
            [
                "系统分类优先：Fish 仍归 Fish，Gear 仍归 Gear，Player 仍归 Locomotion。",
                "Perspective 作为二级混音维度，不替代系统分类。",
                "已分好的 Gear 不大改，只补 QA。",
                "Fish / Lure 建议新增 Player/Others 子 Bus。",
                "Footsteps / Clothes 必须先 Gender，再 Perspective。",
                "只有目标节点启用 OverrideOutput，Event 继续指向外层 Switch Container。",
            ]
        ),
        COL["green"],
        COL["green_b"],
        F_SMALL,
    )

    d.text((90, 1000), "推荐目标 Bus 树", font=F_H, fill=COL["ink"])
    d.text((90, 1043), "绿色=保留，蓝色=建议新增，灰色=现有但本轮不动", font=F_BODY, fill=COL["muted"])

    panel(d, 90, 1100, 760, 900, "Fishing / Fish / Lure", "", COL["white"], COL["gray_b"])
    tree(
        d,
        125,
        1185,
        [
            (0, "Master Audio Bus", "keep"),
            (1, "AudioObject_Ambient_3D", "keep"),
            (2, "Fish", "keep"),
            (3, "Fish_Player", "add"),
            (3, "Fish_Others", "add"),
            (3, "Lure_Player", "add"),
            (3, "Lure_Others", "add"),
            (0, "", "old"),
            (0, "Actor 路由建议", "keep"),
            (1, "Fish_WaterIn_Player  -> Fish_Player", "add"),
            (1, "Fish_WaterIn_Others  -> Fish_Others", "add"),
            (1, "Fish_WaterOut_Player -> Fish_Player", "add"),
            (1, "Fish_WaterOut_Others -> Fish_Others", "add"),
            (1, "Lure / Buzzbait Player -> Lure_Player", "add"),
            (1, "Lure / Buzzbait Others -> Lure_Others", "add"),
        ],
    )

    panel(d, 920, 1100, 760, 900, "Gear", "", COL["white"], COL["gray_b"])
    tree(
        d,
        955,
        1185,
        [
            (0, "Master Audio Bus", "keep"),
            (1, "MainMix", "keep"),
            (2, "SFX", "keep"),
            (3, "Gear", "keep"),
            (4, "Player", "keep"),
            (4, "Others", "keep"),
            (4, "Reel", "old"),
            (0, "", "old"),
            (0, "Actor 路由现状", "keep"),
            (1, "Gear_*_Player -> Gear/Player", "keep"),
            (1, "Gear_*_Others -> Gear/Others", "keep"),
            (1, "Attenuation: Gear_Player / Gear_Others", "keep"),
            (1, "本轮建议：不新增 Bus，仅确认 Reel 是否废弃或保留作子分类", "old"),
        ],
    )

    panel(d, 1750, 1100, 760, 900, "Player / Locomotion", "", COL["white"], COL["gray_b"])
    tree(
        d,
        1785,
        1185,
        [
            (0, "Master Audio Bus", "keep"),
            (1, "MainMix", "keep"),
            (2, "SFX", "keep"),
            (3, "Locomotion", "keep"),
            (4, "Footsteps", "keep"),
            (5, "Female", "keep"),
            (6, "Player", "add"),
            (7, "Sneakers", "add"),
            (6, "Others", "add"),
            (7, "Sneakers", "add"),
            (5, "Male", "keep"),
            (6, "Player", "add"),
            (7, "Sneakers", "add"),
            (6, "Others", "add"),
            (7, "Sneakers", "add"),
            (4, "Clothes  （由 Clother 改名）", "add"),
            (5, "Female", "add"),
            (6, "Player", "add"),
            (6, "Others", "add"),
            (5, "Male", "add"),
            (6, "Player", "add"),
            (6, "Others", "add"),
            (0, "", "old"),
            (0, "Actor 路由建议", "keep"),
            (1, "Footsteps Female_Player -> Female/Player/Sneakers", "add"),
            (1, "Footsteps Female_Others -> Female/Others/Sneakers", "add"),
            (1, "Footsteps Male_Player -> Male/Player/Sneakers", "add"),
            (1, "Footsteps Male_Others -> Male/Others/Sneakers", "add"),
            (1, "Clothes Female_Player -> Clothes/Female/Player", "add"),
            (1, "Clothes Female_Others -> Clothes/Female/Others", "add"),
            (1, "Clothes Male_Player -> Clothes/Male/Player", "add"),
            (1, "Clothes Male_Others -> Clothes/Male/Others", "add"),
        ],
        fnt=F_TINY,
        gap=6,
    )

    arrow(d, (500, 2035), (500, 2148), COL["line"])
    arrow(d, (1300, 2035), (1300, 2148), COL["line"])
    arrow(d, (2140, 2035), (2140, 2148), COL["line"])

    panel(
        d,
        90,
        2180,
        2420,
        430,
        "确认后实际修改清单",
        bullet(
            [
                "新增 Bus：Fish_Player、Fish_Others、Lure_Player、Lure_Others。",
                "Footsteps：在已有 Male/Female 下新增 Player/Others；鞋类 Bus 放在 Perspective 下面，例如 Female/Player/Sneakers。",
                "Clothes：把错误命名 Clother 改为 Clothes，再建立 Female/Player、Female/Others、Male/Player、Male/Others。",
                "Fishing/Fish：WaterIn/WaterOut 的 Player/Others 叶子节点启用 OverrideOutput，并分别指向 Fish_Player / Fish_Others。",
                "Fishing/Lure：Lure_WaterIn、Lure_WaterOut、Buzzbait 的 Player/Others 分支启用 OverrideOutput，并分别指向 Lure_Player / Lure_Others。",
                "Player：Footsteps 与 Clothes 的叶子节点按 Gender -> Perspective 路由；保留当前 Actor 里的 Gender -> Perspective -> Surface/Clothing Switch 结构。",
                "Gear：保持当前 Gear/Player 与 Gear/Others；只做一次引用 QA，确认没有遗漏仍输出到旧 Bus 的分支。",
                "所有 Event 保持指向外层 Switch Container，不把 Event 直接拆到 Player/Others，避免 Unity 触发层复杂化。",
            ]
        ),
        COL["violet"],
        COL["violet_b"],
        F_SMALL,
    )

    panel(
        d,
        90,
        2670,
        1165,
        420,
        "混音建议",
        bullet(
            [
                "Player Bus：保持清晰、靠前，关键反馈不轻易被 duck。",
                "Others Bus：整体低于 Player，可做距离感更强的 EQ/压缩/限声。",
                "Fish_Player：上鱼、水入水出反馈稍靠前。",
                "Fish_Others：多人环境中控制数量和峰值，避免水花堆叠。",
                "Footsteps/Clothes：先用 Male/Female 做性别材质与体型差异，再用 Player/Others 做混音差异。",
                "Footsteps/Clothes Others：可比 Player 低 3-6 dB，必要时用 Voice Limit。",
            ]
        ),
        COL["green"],
        COL["green_b"],
        F_SMALL,
    )

    panel(
        d,
        1345,
        2670,
        1165,
        420,
        "需要你确认的点",
        bullet(
            [
                "Fish 是否继续留在 AudioObject_Ambient_3D/Fish 下。我的建议：先保留，风险最低。",
                "Lure 是否和 Fish 共用 Fish 大类。我的建议：共用大类，但拆 Lure_Player/Others 子 Bus。",
                "Footsteps 的最终顺序改为 Footsteps/Gender/Perspective/ShoeType。本轮按你确认的 Male/Female 优先执行。",
                "Clother 是否直接 Rename 为 Clothes。我的建议：直接改名并同步所有 OutputBus 引用。",
                "Gear/Reel 这个旧 Bus 是否有未来用途。我的建议：本轮先不动，后续按引用再清理。",
            ]
        ),
        COL["red"],
        COL["red_b"],
        F_SMALL,
    )

    d.text((92, 3165), "备注：本方案只改 Bus 命名与 Output Bus 路由，不改 Event 触发名、不改 SwitchGroup、不改素材容器层级。Attenuation 继续沿用现有 Player/Others 方案。", font=F_SMALL, fill=COL["muted"])
    img.save(OUT)
    print(str(OUT))


if __name__ == "__main__":
    render()
