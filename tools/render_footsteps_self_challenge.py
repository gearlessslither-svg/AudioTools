# -*- coding: utf-8 -*-
from pathlib import Path
import math

from PIL import Image, ImageDraw, ImageFont


OUT = Path(r"G:\AI\Material\Wwise\ProjectEF_FootstepsSelf_Challenge_Conclusion_2026-05-22.png")

FONT_PATHS = [
    r"C:\Windows\Fonts\NotoSansSC-VF.ttf",
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\Deng.ttf",
]
BOLD_PATHS = [
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\Dengb.ttf",
    r"C:\Windows\Fonts\NotoSansSC-VF.ttf",
]


def pick(paths):
    for p in paths:
        if Path(p).exists():
            return p
    raise SystemExit("No font found")


FONT = pick(FONT_PATHS)
BOLD = pick(BOLD_PATHS)


def f(size, bold=False):
    return ImageFont.truetype(BOLD if bold else FONT, size)


F_TITLE = f(56, True)
F_SUB = f(27)
F_H = f(34, True)
F_BODY = f(24)
F_SMALL = f(21)
F_TINY = f(18)

COL = {
    "bg": "#f6f8fb",
    "ink": "#17212b",
    "muted": "#5e6a75",
    "white": "#ffffff",
    "red": "#ffe7e2",
    "red_b": "#c95345",
    "amber": "#fff0d6",
    "amber_b": "#c47c20",
    "green": "#e4f6e8",
    "green_b": "#438d55",
    "blue": "#dceeff",
    "blue_b": "#347fbd",
    "violet": "#efe8ff",
    "violet_b": "#7f63c6",
    "gray_b": "#99a5af",
    "line": "#8b98a7",
}


def wh(d, text, font):
    box = d.textbbox((0, 0), text, font=font)
    return box[2] - box[0], box[3] - box[1]


def wrap(d, text, font, width):
    out = []
    for para in str(text).split("\n"):
        if not para:
            out.append("")
            continue
        cur = ""
        for ch in para:
            cand = cur + ch
            if cur and wh(d, cand, font)[0] > width:
                out.append(cur.rstrip())
                cur = ch.lstrip()
            else:
                cur = cand
        if cur:
            out.append(cur.rstrip())
    return out


def text(d, x, y, body, font, fill, width, gap=7):
    for line in wrap(d, body, font, width):
        d.text((x, y), line, font=font, fill=fill)
        y += wh(d, line or " ", font)[1] + gap
    return y


def box(d, x, y, w, h, title, body, fill, border, body_font=None):
    d.rounded_rectangle([x, y, x + w, y + h], radius=18, fill=fill, outline=border, width=3)
    yy = y + 20
    yy = text(d, x + 22, yy, title, F_H, COL["ink"], w - 44, 8) + 2
    if body:
        text(d, x + 22, yy, body, body_font or F_BODY, COL["ink"], w - 44, 8)


def bullet(items):
    return "\n".join("- " + item for item in items)


def arrow(d, start, end, color=None, width=5):
    color = color or COL["line"]
    d.line([start, end], fill=color, width=width)
    x1, y1 = start
    x2, y2 = end
    ang = math.atan2(y2 - y1, x2 - x1)
    size = 18
    p1 = (x2 - size * math.cos(ang - math.pi / 6), y2 - size * math.sin(ang - math.pi / 6))
    p2 = (x2 - size * math.cos(ang + math.pi / 6), y2 - size * math.sin(ang + math.pi / 6))
    d.polygon([end, p1, p2], fill=color)


def tree(d, x, y, lines, font=F_SMALL, gap=7):
    yy = y
    for level, label, color in lines:
        d.text((x + level * 34, yy), label, font=font, fill=color)
        yy += wh(d, label, font)[1] + gap
    return yy


def render():
    W, H = 2600, 3000
    img = Image.new("RGB", (W, H), COL["bg"])
    d = ImageDraw.Draw(img)

    d.text((90, 60), "Footsteps_Self 命名与结构 Challenge 结论", font=F_TITLE, fill=COL["ink"])
    text(
        d,
        94,
        138,
        "只读结论图：这次不修改 Wwise。核心问题不是路由能不能工作，而是命名和维度建模已经互相矛盾，后续维护会越来越难。",
        F_SUB,
        COL["muted"],
        2350,
        8,
    )

    box(
        d,
        90,
        235,
        760,
        560,
        "我应该先质疑的点",
        bullet(
            [
                "`Footsteps_Self` 还带旧的 Self/Perspective 语义。",
                "`Female/Sneakers` 路径下面又放了 Gender Switch。",
                "Gender Switch 里有 Male 分支，实际 Male 内容被塞在 Female 路径里。",
                "真正的 `Male/Sneakers` 是空镜像分支。",
                "Actor-Mixer 容器大量以 `Play_` 开头，这是 Event/API 命名，不是内容命名。",
            ]
        ),
        COL["red"],
        COL["red_b"],
        F_SMALL,
    )

    box(
        d,
        920,
        235,
        760,
        560,
        "只读证据",
        bullet(
            [
                "顶层：`Footsteps_Self/Female` 有内容，`Footsteps_Self/Male/Sneakers` 为空。",
                "4 个运动容器是 Gender Switch。",
                "8 个 Gender 子分支下面再分 Perspective。",
                "12 个 Male/Perspective 关键容器出现在 Female 路径下。",
                "28 个 Actor/Container 名称以 `Play_` 开头。",
            ]
        ),
        COL["amber"],
        COL["amber_b"],
        F_SMALL,
    )

    box(
        d,
        1750,
        235,
        760,
        560,
        "为什么这是设计错误",
        bullet(
            [
                "Gender 被同时编码在路径、对象名和 Switch 中，三套来源会互相打架。",
                "以后补 Male 真实素材时，不知道该放进 Male 文件夹，还是 Female 下的 Male 分支。",
                "Event 名带 Female，会让 Unity 和策划误以为这是女性专属事件。",
                "路由 QA 可能全绿，但语义 QA 已经红了。",
                "这类问题应该在改之前被 challenge，而不是改完才发现。",
            ]
        ),
        COL["violet"],
        COL["violet_b"],
        F_SMALL,
    )

    d.text((90, 890), "当前结构的问题形态", font=F_H, fill=COL["ink"])
    box(d, 90, 950, 1120, 740, "当前：维度重复", "", COL["white"], COL["gray_b"])
    tree(
        d,
        130,
        1035,
        [
            (0, "Player", COL["ink"]),
            (1, "Footsteps_Self  ← 旧 Self 语义", COL["red_b"]),
            (2, "Female", COL["red_b"]),
            (3, "Sneakers", COL["ink"]),
            (4, "New Footsteps", COL["muted"]),
            (5, "Play_Footsteps_Female_Run_Backward_Sneakers", COL["red_b"]),
            (6, "SwitchGroup = Gender", COL["blue_b"]),
            (6, "Play_..._Female", COL["green_b"]),
            (7, "SwitchGroup = Perspective", COL["blue_b"]),
            (7, "Play_..._Female_Player / Others", COL["green_b"]),
            (6, "Play_..._Male  ← Male 在 Female 路径下", COL["red_b"]),
            (7, "Play_..._Male_Player / Others", COL["red_b"]),
            (2, "Male", COL["red_b"]),
            (3, "Sneakers  ← 空", COL["red_b"]),
        ],
        F_SMALL,
        8,
    )

    arrow(d, (1250, 1315), (1370, 1315), COL["line"])

    box(d, 1390, 950, 1120, 740, "建议：一个维度只放一处", "", COL["white"], COL["gray_b"])
    tree(
        d,
        1430,
        1035,
        [
            (0, "Player", COL["ink"]),
            (1, "Footsteps  ← 去掉 Self", COL["green_b"]),
            (2, "Sneakers", COL["ink"]),
            (3, "Run_Backward  ← 内容名，不叫 Play_", COL["green_b"]),
            (4, "SwitchGroup = Gender", COL["blue_b"]),
            (5, "Female", COL["green_b"]),
            (6, "SwitchGroup = Perspective", COL["blue_b"]),
            (7, "Player / Others", COL["green_b"]),
            (8, "SwitchGroup = Surface_Type", COL["blue_b"]),
            (5, "Male", COL["green_b"]),
            (6, "SwitchGroup = Perspective", COL["blue_b"]),
            (7, "Player / Others", COL["green_b"]),
            (8, "SwitchGroup = Surface_Type", COL["blue_b"]),
            (1, "Bus 仍可按 Footsteps/Gender/Perspective/ShoeType", COL["muted"]),
        ],
        F_SMALL,
        8,
    )

    box(
        d,
        90,
        1770,
        760,
        520,
        "命名结论",
        bullet(
            [
                "Actor 侧不建议带 `Play_`。",
                "Event 可以叫 `Play_Footsteps_Run_Backward_Sneakers`。",
                "Actor 可以叫 `Footstep_Run_Backward` 或 `Run_Backward`。",
                "不要在 Event/Actor 名里写 `Female`，除非 Unity 真的发男女专属事件。",
                "`Footsteps_Self` 建议最终改为 `Footsteps`。",
            ]
        ),
        COL["blue"],
        COL["blue_b"],
        F_SMALL,
    )

    box(
        d,
        920,
        1770,
        760,
        520,
        "修复策略",
        bullet(
            [
                "阶段 1：先只改 Actor 命名和层级，Event 暂时保持旧名，避免 Unity 断。",
                "阶段 2：新增或重命名 generic Event，旧 Female Event 做兼容/废弃。",
                "阶段 3：真实 Male 素材到位后，再替换 Male 分支样本，不复制 Female 作为最终资产。",
                "阶段 4：跑 Event target、Switch assignment、Bus/Attenuation QA。",
            ]
        ),
        COL["green"],
        COL["green_b"],
        F_SMALL,
    )

    box(
        d,
        1750,
        1770,
        760,
        520,
        "以后 Skill 要做的事",
        bullet(
            [
                "先 Challenge：维度是否重复、顺序是否合理、命名是否误导。",
                "再执行：用户确认方案后才 WAAPI 修改。",
                "QA 不只看路由，还看语义：空镜像分支、错层 Male/Female、Actor/Event 命名混用。",
                "遇到不确定命名，先问，不顺着错误继续放大。",
            ]
        ),
        COL["amber"],
        COL["amber_b"],
        F_SMALL,
    )

    box(
        d,
        90,
        2370,
        2420,
        390,
        "我的结论",
        "这次我修 Bus/Attenuation 的技术动作是对的，但没有质疑 `Footsteps_Self/Female/.../Gender Switch/Male` 这个语义结构，所以把你的旧命名错误继续固化了。真正正确的模型应该是：Event 触发通用动作，Actor 内部用 Gender Switch 选男女，再用 Perspective 选 Player/Others，最后用 Surface_Type/鞋类/脚步细节选样本。Gender 不应该同时出现在路径、对象名和 Switch 三个层面。",
        COL["red"],
        COL["red_b"],
        F_BODY,
    )

    d.text((94, 2840), "已补入 wwise-project-audit Skill：Challenge Gate 会在以后 Wwise 设计/修改前强制检查这些问题。", font=F_SMALL, fill=COL["muted"])
    img.save(OUT)
    print(str(OUT))


if __name__ == "__main__":
    render()
