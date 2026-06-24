from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "Reports" / "ScreenshotCapture"
OUT_PATH = OUT_DIR / "Screenshot_To_Excel_Usage_Guide.png"


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = [
        Path(r"C:\Windows\Fonts\msyhbd.ttc") if bold else Path(r"C:\Windows\Fonts\msyh.ttc"),
        Path(r"C:\Windows\Fonts\simhei.ttf"),
        Path(r"C:\Windows\Fonts\simsun.ttc"),
    ]
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def rounded(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], fill: str, outline: str | None = None, width: int = 1) -> None:
    draw.rounded_rectangle(box, radius=22, fill=fill, outline=outline, width=width)


def wrapped_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    xy: tuple[int, int],
    text_font: ImageFont.FreeTypeFont,
    fill: str,
    max_width: int,
    line_gap: int = 8,
) -> int:
    x, y = xy
    lines: list[str] = []
    for paragraph in text.split("\n"):
        current = ""
        for char in paragraph:
            trial = current + char
            if draw.textbbox((0, 0), trial, font=text_font)[2] <= max_width:
                current = trial
            else:
                if current:
                    lines.append(current)
                current = char
        lines.append(current)

    for line in lines:
        draw.text((x, y), line, font=text_font, fill=fill)
        bbox = draw.textbbox((x, y), line, font=text_font)
        y += (bbox[3] - bbox[1]) + line_gap
    return y


def multiline_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    xy: tuple[int, int],
    text_font: ImageFont.FreeTypeFont,
    fill: str,
    line_gap: int = 10,
) -> int:
    x, y = xy
    for line in text.split("\n"):
        draw.text((x, y), line, font=text_font, fill=fill)
        bbox = draw.textbbox((x, y), line, font=text_font)
        y += (bbox[3] - bbox[1]) + line_gap
    return y


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (1920, 1080), "#F5F7FA")
    draw = ImageDraw.Draw(image)

    title_font = font(60, bold=True)
    subtitle_font = font(28)
    h_font = font(34, bold=True)
    body_font = font(23)
    small_font = font(22)
    tiny_font = font(18)
    number_font = font(30, bold=True)

    # Header
    draw.rectangle((0, 0, 1920, 164), fill="#12324A")
    draw.text((72, 36), "跑测截图 -> Excel 留档工具", font=title_font, fill="#FFFFFF")
    draw.text((76, 112), "打开工具期间，系统截图自动归档；关闭后按开始-结束时间生成最终 Excel", font=subtitle_font, fill="#D8EAF2")

    # Launcher card
    rounded(draw, (72, 206, 1848, 330), "#FFFFFF", "#D9E2EA", 2)
    draw.text((116, 232), "启动入口", font=h_font, fill="#12324A")
    draw.text((280, 238), r"G:\AI\Material\Wwise\Start_Screenshot_To_Excel.cmd", font=body_font, fill="#2C3E50")
    draw.text((280, 278), "双击后保持窗口开着；跑测结束点击“停止并生成 Excel”或直接关闭窗口。", font=small_font, fill="#51606C")

    # Workflow cards
    cards = [
        ("01", "打开工具", "双击启动入口。\n窗口显示“正在采集”后\n就可以开始跑测。"),
        ("02", "测试中截图", "看到一闪而过的内容就截图。\n支持：\nPrintScreen / Win+Shift+S\nWin+PrintScreen\nXbox Game Bar Captures"),
        ("03", "自动留档", "截图会保存原图，\n并持续刷新 running 临时 Excel。\n测试中不建议编辑\nrunning.xlsx。"),
        ("04", "关闭生成", "关闭后生成最终 Excel：\n截图留档_开始-结束.xlsx\n如果没有截图，\n不创建 Excel。"),
    ]
    x_positions = [72, 524, 976, 1428]
    for x, (num, heading, body) in zip(x_positions, cards):
        rounded(draw, (x, 374, x + 420, 690), "#FFFFFF", "#D9E2EA", 2)
        draw.ellipse((x + 28, 408, x + 88, 468), fill="#1F7A8C")
        draw.text((x + 40, 421), num, font=number_font, fill="#FFFFFF")
        draw.text((x + 112, 414), heading, font=h_font, fill="#12324A")
        multiline_text(draw, body, (x + 32, 500), body_font, "#33424F", line_gap=12)

    # Output and Excel content cards
    rounded(draw, (72, 738, 930, 990), "#EAF6F8", "#B5D7DE", 2)
    draw.text((112, 772), "输出位置", font=h_font, fill="#12324A")
    wrapped_text(
        draw,
        r"G:\AI\Material\Wwise\Reports\ScreenshotCapture",
        (112, 830),
        body_font,
        "#21313D",
        740,
        line_gap=8,
    )
    wrapped_text(
        draw,
        "每次打开到关闭是一轮新会话。最终 Excel 和同名 _images 文件夹会一起保留。",
        (112, 900),
        small_font,
        "#51606C",
        740,
        line_gap=8,
    )

    rounded(draw, (990, 738, 1848, 990), "#FFFFFF", "#D9E2EA", 2)
    draw.text((1030, 772), "Excel 里有什么", font=h_font, fill="#12324A")
    columns = ["序号", "捕获时间", "来源", "尺寸", "原图路径", "备注", "缩略图"]
    x = 1030
    y = 836
    for label in columns:
        bbox = draw.textbbox((0, 0), label, font=small_font)
        w = bbox[2] - bbox[0] + 34
        draw.rounded_rectangle((x, y, x + w, y + 44), radius=12, fill="#F1F4F7", outline="#D9E2EA")
        draw.text((x + 17, y + 8), label, font=small_font, fill="#21313D")
        x += w + 14
        if x > 1750:
            x = 1030
            y += 58
    wrapped_text(
        draw,
        "建议：跑测中只负责截图，结束后在最终 Excel 的“备注”列统一整理问题现象、复现步骤和归类。",
        (1030, 936),
        tiny_font,
        "#51606C",
        760,
        line_gap=6,
    )

    image.save(OUT_PATH, format="PNG", optimize=True)
    print(OUT_PATH)


if __name__ == "__main__":
    main()
