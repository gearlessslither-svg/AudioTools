# -*- coding: utf-8 -*-
from pathlib import Path
import math

from PIL import Image, ImageDraw, ImageFont


OUT_DIR = Path(r"G:\AI\Material\Wwise")

FONT_PATHS = [
    r"C:\Windows\Fonts\NotoSansSC-VF.ttf",
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\Deng.ttf",
]
FONT_PATH = next((p for p in FONT_PATHS if Path(p).exists()), None)
if not FONT_PATH:
    raise SystemExit("No Chinese font found")


def make_font(size, bold=False):
    if bold and Path(r"C:\Windows\Fonts\Dengb.ttf").exists():
        return ImageFont.truetype(r"C:\Windows\Fonts\Dengb.ttf", size)
    return ImageFont.truetype(FONT_PATH, size)


F_TITLE = make_font(58, True)
F_SUB = make_font(30, True)
F_H = make_font(34, True)
F_BODY = make_font(25)
F_SMALL = make_font(21)
F_TINY = make_font(18)

COLORS = {
    "bg": "#f7f8fb",
    "ink": "#17202a",
    "muted": "#566573",
    "blue": "#dceeff",
    "blue_border": "#4f8dcc",
    "green": "#e4f6e8",
    "green_border": "#4f9d63",
    "orange": "#fff1dc",
    "orange_border": "#d38b2e",
    "red": "#ffe6e3",
    "red_border": "#cf5a4a",
    "purple": "#efe8ff",
    "purple_border": "#8263c6",
    "gray": "#eef1f4",
    "gray_border": "#96a0aa",
    "line": "#8a99a8",
    "white": "#ffffff",
}


def text_size(draw, text, fnt):
    if not text:
        return 0, 0
    box = draw.textbbox((0, 0), text, font=fnt)
    return box[2] - box[0], box[3] - box[1]


def wrap_by_px(draw, text, fnt, max_width):
    lines = []
    for para in str(text).split("\n"):
        para = para.rstrip()
        if not para:
            lines.append("")
            continue
        cur = ""
        for ch in para:
            test = cur + ch
            if cur and text_size(draw, test, fnt)[0] > max_width:
                lines.append(cur.rstrip())
                cur = ch.lstrip()
            else:
                cur = test
        if cur:
            lines.append(cur.rstrip())
    return lines


def draw_wrapped(draw, xy, text, fnt, fill, max_width, line_gap=7):
    x, y = xy
    lines = wrap_by_px(draw, text, fnt, max_width)
    for line in lines:
        draw.text((x, y), line, font=fnt, fill=fill)
        y += text_size(draw, line or " ", fnt)[1] + line_gap
    return y


def box(
    draw,
    xywh,
    title,
    body=None,
    fill="#ffffff",
    outline="#999999",
    title_fill=None,
    radius=18,
    width=3,
    title_font=None,
    body_font=None,
):
    x, y, w, h = xywh
    draw.rounded_rectangle([x, y, x + w, y + h], radius=radius, fill=fill, outline=outline, width=width)
    pad = 22
    if title:
        draw_wrapped(
            draw,
            (x + pad, y + 18),
            title,
            title_font or F_H,
            title_fill or COLORS["ink"],
            w - pad * 2,
            8,
        )
        ty = y + 18
        for line in wrap_by_px(draw, title, title_font or F_H, w - pad * 2):
            ty += text_size(draw, line, title_font or F_H)[1] + 8
        ty += 8
    else:
        ty = y + pad
    if body:
        draw_wrapped(draw, (x + pad, ty), body, body_font or F_BODY, COLORS["ink"], w - pad * 2, 8)


def arrow(draw, start, end, color=None, width=5):
    color = color or COLORS["line"]
    x1, y1 = start
    x2, y2 = end
    draw.line([x1, y1, x2, y2], fill=color, width=width)
    ang = math.atan2(y2 - y1, x2 - x1)
    size = 18
    p1 = (x2 - size * math.cos(ang - math.pi / 6), y2 - size * math.sin(ang - math.pi / 6))
    p2 = (x2 - size * math.cos(ang + math.pi / 6), y2 - size * math.sin(ang + math.pi / 6))
    draw.polygon([end, p1, p2], fill=color)


def bullet_lines(items, prefix="- "):
    return "\n".join(prefix + i for i in items)


def render_gear():
    w, h = 2600, 3300
    img = Image.new("RGB", (w, h), COLORS["bg"])
    d = ImageDraw.Draw(img)

    d.text((90, 70), "Gear.wwu 修改内容大图", font=F_TITLE, fill=COLORS["ink"])
    d.text(
        (92, 145),
        "只读设计方案：先按 Event 引用筛选，只改真实被游戏触发的 Gear 声音；其余进入 Obsolete 池。",
        font=F_SUB,
        fill=COLORS["muted"],
    )
    d.text(
        (92, 192),
        "当前状态：13 个 Gear Event，17 个 Action 引用；所有有效目标都在 Player_Gear 侧，Others_Gear 为空。",
        font=F_BODY,
        fill=COLORS["muted"],
    )

    box(
        d,
        (90, 270, 720, 480),
        "1. Event 引用入口",
        bullet_lines(
            [
                "Stop_Wheel_Retrieve -> Stop Reel_Retrieve",
                "Play_Wheel_Retrieve -> Play Reel_Retrieve",
                "Play_Line_Out / Stop_Line_Out -> Reel_LineOut",
                "Play_Line_Snap -> Line_Snap + Line_Snap_High + Stop Reel_LineOut",
                "Play_Line_Cast -> Reel_LineCast + Rod_Cast",
                "Play_Spool_Open / Lock -> Reel_Open / Reel_Close",
                "Play_ReelDrag_Adjust -> Reel_DragAdjust",
                "Play_Strike -> Strike_Fast",
                "Play_Lure_Rattle -> Lure_Rattle",
                "Play_Reel_Broke / Rod_Broke -> Broke 声音",
            ]
        ),
        fill=COLORS["blue"],
        outline=COLORS["blue_border"],
        body_font=F_SMALL,
    )

    box(
        d,
        (950, 270, 700, 480),
        "2. 只改这些有效目标",
        bullet_lines(
            [
                "Reel_Retrieve, Reel_LineOut, Reel_LineCast",
                "Reel_Open, Reel_Close, Reel_DragAdjust",
                "Rod_Cast 单独处理，不继续埋在 Reel_LineCast 内",
                "Line_Snap, Line_Snap_High",
                "Strike_Fast, Lure_Rattle",
                "Reel_Broke, Rod_Broke",
                "Stop Action 继续指向同名外层 Perspective 容器",
            ]
        ),
        fill=COLORS["green"],
        outline=COLORS["green_border"],
        body_font=F_SMALL,
    )

    box(
        d,
        (1790, 270, 720, 480),
        "3. Obsolete 候选池",
        bullet_lines(
            [
                "Spool_Lock：未被 Play_Spool_Lock 使用",
                "Spool_Open：未被 Play_Spool_Open 使用",
                "Strike_Slow_001-004：无 Event 引用",
                "Line_Cast_Whole：无 Event 引用",
                "Line_Out：空/无 Event 引用",
                "Others_Gear：当前为空，可选移入 Obsolete 或保留占位",
                "移动到 \\Actor-Mixer Hierarchy\\Gear\\Obsolete",
            ]
        ),
        fill=COLORS["orange"],
        outline=COLORS["orange_border"],
        body_font=F_SMALL,
    )
    arrow(d, (810, 510), (950, 510))
    arrow(d, (1650, 510), (1790, 510))

    box(
        d,
        (90, 850, 2420, 1380),
        "目标结构：每个被 Event 打到的声音，外层都变成 Perspective SwitchContainer",
        "",
        fill=COLORS["white"],
        outline=COLORS["gray_border"],
    )
    x0, y0 = 150, 940
    box(
        d,
        (x0, y0, 520, 150),
        "\\Actor-Mixer Hierarchy\\Gear",
        "保留 Gear WorkUnit；不改变总入口。",
        fill=COLORS["gray"],
        outline=COLORS["gray_border"],
        title_font=F_SUB,
        body_font=F_SMALL,
    )
    box(
        d,
        (x0 + 680, y0, 650, 150),
        "Player_Gear（现有容器）",
        "短期继续作为承载位置；外层 Perspective 容器内部再区分 Player/Others。",
        fill=COLORS["gray"],
        outline=COLORS["gray_border"],
        title_font=F_SUB,
        body_font=F_SMALL,
    )
    box(
        d,
        (x0 + 1500, y0, 580, 150),
        "Obsolete（新建 Folder）",
        "只放未被 Event 真实引用的旧素材/旧结构。",
        fill=COLORS["orange"],
        outline=COLORS["orange_border"],
        title_font=F_SUB,
        body_font=F_SMALL,
    )
    arrow(d, (x0 + 520, y0 + 75), (x0 + 680, y0 + 75))
    arrow(d, (x0 + 1330, y0 + 75), (x0 + 1500, y0 + 75), COLORS["orange_border"])

    examples = [
        ("Reel_Retrieve", "原内部 Switch：Reel_ID\n外层改为 Perspective；Player/Others 分支内保留 Reel_ID。"),
        ("Reel_LineOut", "Loop/Stop 目标。Play/Stop/断线 Stop 都指向外层同名容器。"),
        ("Reel_LineCast", "只处理线轮抛线本体；Rod_Cast 从内部提为独立目标。"),
        ("Rod_Cast", "新建/移动为 Reel 下独立 Perspective 目标，保留 Rod_Cast_Speed。"),
        ("Lure_Rattle", "外层 Perspective；内部分支保留 Lure_Material。"),
        ("Line_Snap / Broke / Strike_Fast", "Sound 或 RandomSequence 也包外层 Perspective；复制出 Others 分支。"),
    ]
    for i, (name, desc) in enumerate(examples):
        col = i % 3
        row = i // 3
        x = 150 + col * 780
        y = 1160 + row * 390
        box(d, (x, y, 690, 310), name, desc, fill="#f9fbff", outline=COLORS["blue_border"], title_font=F_SUB, body_font=F_SMALL)
        ty = y + 140
        d.text((x + 34, ty), f"{name}  [SwitchContainer: Perspective]", font=F_TINY, fill=COLORS["ink"])
        d.text((x + 64, ty + 45), f"{name}_Player  -> Switch=Player, Att=Gear_Player", font=F_TINY, fill=COLORS["ink"])
        d.text((x + 64, ty + 85), f"{name}_Others  -> Switch=Others, Att=Gear_Others", font=F_TINY, fill=COLORS["ink"])

    box(
        d,
        (90, 2300, 1180, 720),
        "Event 替换规则",
        bullet_lines(
            [
                "所有 Play/Stop Action 都改到“同名外层 Perspective 容器”。",
                "Play_Wheel_Retrieve / Stop_Wheel_Retrieve -> Reel_Retrieve（新外层）。",
                "Play_Line_Out / Stop_Line_Out / Play_Line_Snap Stop / Play_Reel_Broke Stop -> Reel_LineOut（新外层）。",
                "Play_Line_Cast 第一条 Action -> Reel_LineCast（新外层）。",
                "Play_Line_Cast 第二条 Action -> Rod_Cast（新独立外层），避免嵌套 Perspective 失效。",
                "不改 Unity Event 名，先保证兼容；Unity 只需要设置 Perspective=Player/Others。",
            ]
        ),
        fill=COLORS["purple"],
        outline=COLORS["purple_border"],
        body_font=F_SMALL,
    )

    box(
        d,
        (1330, 2300, 1180, 720),
        "落地检查点",
        bullet_lines(
            [
                "WAAPI 查询：Events\\Gear 下所有 Action Target 不再指向 *_Player 内部对象。",
                "SwitchGroup：所有新外层均为 System/Perspective，Default=Player。",
                "Assignment：*_Player -> Player；*_Others -> Others。",
                "Attenuation：Player 分支 Gear_Player；Others 分支 Gear_Others。",
                "Stop 测试：Reel_LineOut、Reel_Retrieve 的 Stop 必须仍能停掉对应实例。",
                "Obsolete 不删资源，只移动；可 Undo，可回滚检查。",
            ]
        ),
        fill=COLORS["red"],
        outline=COLORS["red_border"],
        body_font=F_SMALL,
    )

    d.text((90, 3155), "备注：本图为修改设计，不包含实际工程改动；待确认后再通过 WAAPI 执行。", font=F_SMALL, fill=COLORS["muted"])
    gear_path = OUT_DIR / "ProjectEF_Gear_wwu_ModPlan_2026-05-22.png"
    img.save(gear_path)
    return gear_path


def render_player():
    w, h = 2600, 3500
    img = Image.new("RGB", (w, h), COLORS["bg"])
    d = ImageDraw.Draw(img)
    d.text((90, 70), "Player.wwu 修改内容大图", font=F_TITLE, fill=COLORS["ink"])
    d.text((92, 145), "只读设计方案：先筛选 Gender，再筛选 Perspective，最后保留 Surface/Clothing 等原有玩法 Switch。", font=F_SUB, fill=COLORS["muted"])
    d.text((92, 192), "当前状态：4 个 Footsteps Event，每个 Event 同时播放脚步与 Clothes_Self；现有 Gender 是物理文件夹，不是统一 Switch 入口。", font=F_BODY, fill=COLORS["muted"])

    box(
        d,
        (90, 270, 760, 520),
        "1. 当前 Event 入口",
        bullet_lines(
            [
                "Play_Footsteps_Female_Run_Backward_Sneakers",
                "Play_Footsteps_Female_Run_Forward_Sneakers",
                "Play_Footsteps_Female_Walk_Backward_Sneakers",
                "Play_Footsteps_Female_Walk_Forward_Sneakers",
                "每个 Event 有 2 个 Action：",
                "脚步目标：Female/Sneakers/New Footsteps 下对应 Surface_Type 容器",
                "衣物目标：Clothes_Self（Clothing_Type）",
            ]
        ),
        fill=COLORS["blue"],
        outline=COLORS["blue_border"],
        body_font=F_SMALL,
    )

    box(
        d,
        (920, 270, 760, 520),
        "2. 必须建立的 Switch 顺序",
        "第一层：System/Gender（Male / Female）\n第二层：System/Perspective（Player / Others，暂当 1P/3P）\n第三层：原有业务 Switch\n- Footsteps：Surface_Type\n- Clothes：Clothing_Type\n\nUnity 设置一次 Gender/Perspective，动画 Notify 仍只发脚步事件。",
        fill=COLORS["green"],
        outline=COLORS["green_border"],
        body_font=F_SMALL,
    )

    box(
        d,
        (1750, 270, 760, 520),
        "3. Obsolete / 保留",
        bullet_lines(
            [
                "Footsteps_Wet_Sneakers：无 Event 引用，建议入 Obsolete。",
                "Female/Sneakers/Old Footsteps：无 Event 引用，建议入 Obsolete。",
                "Male/Sneakers 当前为空：保留为 Gender 分支，或先复制 Female 作占位。",
                "Clothes_Self 当前无男女差异：先复制模板，后续替换男/女衣物拟音。",
            ]
        ),
        fill=COLORS["orange"],
        outline=COLORS["orange_border"],
        body_font=F_SMALL,
    )
    arrow(d, (850, 530), (920, 530))
    arrow(d, (1680, 530), (1750, 530))

    box(d, (90, 880, 2420, 1540), "目标结构：Gender -> Perspective -> 原有 Switch", "", fill=COLORS["white"], outline=COLORS["gray_border"])

    box(d, (150, 970, 1080, 1320), "Footsteps 结构", "", fill="#f9fbff", outline=COLORS["blue_border"], title_font=F_SUB)
    fx, fy = 210, 1060
    box(d, (fx, fy, 940, 105), "Footsteps_Run_Forward_Sneakers", "SwitchContainer: Gender，Default=Female", fill=COLORS["green"], outline=COLORS["green_border"], title_font=F_SMALL, body_font=F_TINY)
    box(d, (fx + 40, fy + 155, 400, 115), "..._Female", "SwitchContainer: Perspective", fill=COLORS["purple"], outline=COLORS["purple_border"], title_font=F_SMALL, body_font=F_TINY)
    box(d, (fx + 500, fy + 155, 400, 115), "..._Male", "SwitchContainer: Perspective", fill=COLORS["purple"], outline=COLORS["purple_border"], title_font=F_SMALL, body_font=F_TINY)
    arrow(d, (fx + 470, fy + 105), (fx + 240, fy + 155))
    arrow(d, (fx + 470, fy + 105), (fx + 700, fy + 155))
    box(d, (fx + 30, fy + 330, 410, 145), "..._Female_Player", "Switch=Player\n保留现有 Surface_Type 容器与素材", fill=COLORS["blue"], outline=COLORS["blue_border"], title_font=F_SMALL, body_font=F_TINY)
    box(d, (fx + 30, fy + 520, 410, 145), "..._Female_Others", "Switch=Others\n复制模板，Att=Gear_Others 或后续 Player_Others", fill=COLORS["blue"], outline=COLORS["blue_border"], title_font=F_SMALL, body_font=F_TINY)
    box(d, (fx + 500, fy + 330, 410, 145), "..._Male_Player", "Switch=Player\n先复制 Female 或接入男脚步素材", fill=COLORS["blue"], outline=COLORS["blue_border"], title_font=F_SMALL, body_font=F_TINY)
    box(d, (fx + 500, fy + 520, 410, 145), "..._Male_Others", "Switch=Others\n先复制 Male_Player，后续替换 3P 混音", fill=COLORS["blue"], outline=COLORS["blue_border"], title_font=F_SMALL, body_font=F_TINY)
    arrow(d, (fx + 240, fy + 270), (fx + 235, fy + 330))
    arrow(d, (fx + 240, fy + 270), (fx + 235, fy + 520))
    arrow(d, (fx + 700, fy + 270), (fx + 705, fy + 330))
    arrow(d, (fx + 700, fy + 270), (fx + 705, fy + 520))
    box(d, (fx + 120, fy + 735, 740, 250), "第三层保留 Surface_Type", "Cement / Mud / Grass / Pebble / Rock / Sand / Water / Wood / Pedal\n内部继续使用当前 BlendContainer、RandomSequence、Heel/Toe、L/R 随机样本。", fill=COLORS["gray"], outline=COLORS["gray_border"], title_font=F_SMALL, body_font=F_TINY)
    arrow(d, (fx + 440, fy + 665), (fx + 490, fy + 735))
    arrow(d, (fx + 705, fy + 665), (fx + 530, fy + 735))
    box(d, (fx + 120, fy + 1045, 740, 180), "四个动作各建一套同型入口", "Walk_Forward / Walk_Backward / Run_Forward / Run_Backward\n事件可先保持旧 Female 名称，Target 改到新的 Gender 外层。", fill=COLORS["orange"], outline=COLORS["orange_border"], title_font=F_SMALL, body_font=F_TINY)

    box(d, (1370, 970, 1080, 1320), "Clothes 结构", "", fill="#fffdf8", outline=COLORS["orange_border"], title_font=F_SUB)
    cx, cy = 1430, 1060
    box(d, (cx, cy, 940, 105), "Clothes", "SwitchContainer: Gender，Default=Female；替代当前 Clothes_Self 直连入口", fill=COLORS["green"], outline=COLORS["green_border"], title_font=F_SMALL, body_font=F_TINY)
    box(d, (cx + 40, cy + 155, 400, 115), "Clothes_Female", "SwitchContainer: Perspective", fill=COLORS["purple"], outline=COLORS["purple_border"], title_font=F_SMALL, body_font=F_TINY)
    box(d, (cx + 500, cy + 155, 400, 115), "Clothes_Male", "SwitchContainer: Perspective", fill=COLORS["purple"], outline=COLORS["purple_border"], title_font=F_SMALL, body_font=F_TINY)
    arrow(d, (cx + 470, cy + 105), (cx + 240, cy + 155))
    arrow(d, (cx + 470, cy + 105), (cx + 700, cy + 155))
    box(d, (cx + 30, cy + 330, 410, 145), "Clothes_Female_Player", "Switch=Player\n保留 Clothing_Type", fill=COLORS["blue"], outline=COLORS["blue_border"], title_font=F_SMALL, body_font=F_TINY)
    box(d, (cx + 30, cy + 520, 410, 145), "Clothes_Female_Others", "Switch=Others\n复制/轻混音为 3P", fill=COLORS["blue"], outline=COLORS["blue_border"], title_font=F_SMALL, body_font=F_TINY)
    box(d, (cx + 500, cy + 330, 410, 145), "Clothes_Male_Player", "Switch=Player\n先复用 Green_Jacket", fill=COLORS["blue"], outline=COLORS["blue_border"], title_font=F_SMALL, body_font=F_TINY)
    box(d, (cx + 500, cy + 520, 410, 145), "Clothes_Male_Others", "Switch=Others\n后续替换男/3P拟音", fill=COLORS["blue"], outline=COLORS["blue_border"], title_font=F_SMALL, body_font=F_TINY)
    arrow(d, (cx + 240, cy + 270), (cx + 235, cy + 330))
    arrow(d, (cx + 240, cy + 270), (cx + 235, cy + 520))
    arrow(d, (cx + 700, cy + 270), (cx + 705, cy + 330))
    arrow(d, (cx + 700, cy + 270), (cx + 705, cy + 520))
    box(d, (cx + 120, cy + 735, 740, 250), "第三层保留 Clothing_Type", "当前只有 Green_Jacket；保留 Switch 入口，后续可扩 Jacket / Waders / Raincoat / Backpack。\n事件仍与脚步 Event 同步触发，保持身体布料细节。", fill=COLORS["gray"], outline=COLORS["gray_border"], title_font=F_SMALL, body_font=F_TINY)
    arrow(d, (cx + 440, cy + 665), (cx + 490, cy + 735))
    arrow(d, (cx + 705, cy + 665), (cx + 530, cy + 735))
    box(d, (cx + 120, cy + 1045, 740, 180), "命名建议", "父级去掉 _Self：Footsteps / Clothes。\n短期兼容：旧 Event 不改名，只替换 Target。\n长期清理：Event 名可去掉 Female。", fill=COLORS["orange"], outline=COLORS["orange_border"], title_font=F_SMALL, body_font=F_TINY)

    box(
        d,
        (90, 2510, 1180, 720),
        "Event 替换规则",
        bullet_lines(
            [
                "4 个现有 Footsteps Event 暂不改名，降低 Unity 断链风险。",
                "每个 Event 的脚步 Action：Target 改为对应动作的 Gender 外层容器。",
                "每个 Event 的 Clothes Action：Target 改为 Clothes Gender 外层容器。",
                "新增中长期可选 Event：Play_Footsteps_Run_Forward_Sneakers 等去 Female 化名称。",
                "Soundcaster 可保留旧 Event；测试时切 Gender/Perspective 验证分支。",
            ]
        ),
        fill=COLORS["purple"],
        outline=COLORS["purple_border"],
        body_font=F_SMALL,
    )

    box(
        d,
        (1330, 2510, 1180, 720),
        "Unity / 混音检查点",
        bullet_lines(
            [
                "玩家对象初始化：SetSwitch Gender=Male/Female。",
                "相机/声源视角：SetSwitch Perspective=Player/Others。",
                "脚下材质：SetSwitch Surface_Type。",
                "衣物配置：SetSwitch Clothing_Type。",
                "1P 分支更近、更细节；3P 分支更短、更窄、带距离衰减。",
                "建议后续新建 Player_Player / Player_Others 或 Footsteps_Player/Others 衰减，避免长期复用 Gear_*。",
            ]
        ),
        fill=COLORS["red"],
        outline=COLORS["red_border"],
        body_font=F_SMALL,
    )

    d.text((90, 3365), "备注：本图为 Player.wwu 修改设计，不包含实际工程改动；待确认后再通过 WAAPI 分阶段执行。", font=F_SMALL, fill=COLORS["muted"])
    player_path = OUT_DIR / "ProjectEF_Player_wwu_ModPlan_2026-05-22.png"
    img.save(player_path)
    return player_path


if __name__ == "__main__":
    print(render_gear())
    print(render_player())
