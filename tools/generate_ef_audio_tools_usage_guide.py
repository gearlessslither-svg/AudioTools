#!/usr/bin/env python3
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(r"G:\AI\Material\Wwise")
FINAL_DIR = ROOT / "Tools" / "EF_Audio_Tools_Final"
CONFIG_PATH = FINAL_DIR / "tool_paths.json"
REPORT_DIR = ROOT / "\u62a5\u544a"
DATE = dt.datetime.now().strftime("%Y-%m-%d")


CATEGORY_COLORS: dict[str, tuple[int, int, int]] = {
    "Production": (46, 134, 171),
    "Runtime": (179, 82, 116),
    "Reports": (72, 150, 106),
    "Wwise": (196, 137, 49),
    "Automation": (123, 104, 184),
    "P4": (196, 87, 66),
    "Advanced": (101, 116, 139),
}


def wrapper_path(item: dict[str, Any]) -> Path:
    return FINAL_DIR / item["launcher"]


def status_for(item: dict[str, Any]) -> str:
    wrapper_ok = wrapper_path(item).exists()
    source_ok = Path(item["source_launcher"]).exists()
    if wrapper_ok and source_ok:
        return "Ready"
    if not wrapper_ok:
        return "Missing wrapper"
    return "Missing source"


def category_for(item: dict[str, Any]) -> str:
    text = " ".join(str(item.get(key, "")) for key in ("name", "purpose", "launcher", "source_launcher")).lower()
    if "reaper" in text or "sound finder" in text:
        return "Production"
    if "p4" in text or "changelist" in text:
        return "P4"
    if "runtime" in text or "monitor" in text or "follow" in text:
        return "Runtime"
    if "register" in text or "unregister" in text or "scheduled" in text or "watch" in text:
        return "Automation"
    if "report" in text or "summary" in text or "dashboard" in text or "daily" in text:
        return "Reports"
    if "template" in text or "profiler" in text or "waapi" in text:
        return "Wwise"
    return "Advanced"


def load_items() -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    items = []
    for item in config["tools"]:
        merged = {
            **item,
            "category": category_for(item),
            "wrapper_path": str(wrapper_path(item)),
            "source_exists": Path(item["source_launcher"]).exists(),
            "wrapper_exists": wrapper_path(item).exists(),
            "status": status_for(item),
        }
        items.append(merged)
    visible = [item for item in items if item.get("visible", True) is not False]
    hidden = [item for item in items if item.get("visible", True) is False]
    return config, visible, hidden


def render_markdown(config: dict[str, Any], visible: list[dict[str, Any]], hidden: list[dict[str, Any]], out: Path) -> None:
    lines = [
        "# EF Audio Tools Usage Guide",
        "",
        f"- Generated at: {dt.datetime.now().isoformat(timespec='seconds')}",
        f"- Tool folder: `{FINAL_DIR}`",
        f"- GUI launcher: `{FINAL_DIR / config['gui_launcher']}`",
        f"- Menu launcher: `{FINAL_DIR / config['menu_launcher']}`",
        f"- Main GUI tools: {len(visible)}",
        f"- Hidden advanced tools: {len(hidden)}",
        "",
        "## Main GUI Tools",
        "",
    ]
    for index, item in enumerate(visible, 1):
        lines.extend(
            [
                f"### {index}. {item['name']}",
                f"- Category: {item['category']}",
                f"- Status: {item['status']}",
                f"- Purpose: {item['purpose']}",
                f"- Wrapper: `{item['wrapper_path']}`",
                f"- Source: `{item['source_launcher']}`",
                "",
            ]
        )

    lines.extend(["## Hidden Advanced Tools", ""])
    for item in hidden:
        reason = item.get("hidden_reason", "Advanced or maintenance tool.")
        lines.extend(
            [
                f"- `{item['launcher']}` - {item['name']}",
                f"  - Reason: {reason}",
                f"  - Status: {item['status']}",
            ]
        )

    lines.extend(
        [
            "",
            "## Visibility Rule",
            "",
            "- `visible: true` appears in the GUI.",
            "- `visible: false` remains callable from the folder or advanced menu but is hidden from the GUI.",
            "- Keep automatic reports, scheduled tasks, legacy helpers, and superseded tools hidden by default.",
            "",
        ]
    )
    out.write_text("\n".join(lines), encoding="utf-8")


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = [
        Path(r"C:\Windows\Fonts\segoeuib.ttf" if bold else r"C:\Windows\Fonts\segoeui.ttf"),
        Path(r"C:\Windows\Fonts\arialbd.ttf" if bold else r"C:\Windows\Fonts\arial.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def text_width(draw: ImageDraw.ImageDraw, text: str, text_font: ImageFont.ImageFont) -> int:
    box = draw.textbbox((0, 0), text, font=text_font)
    return box[2] - box[0]


def wrap_text(draw: ImageDraw.ImageDraw, text: str, text_font: ImageFont.ImageFont, max_width: int) -> list[str]:
    words = str(text).split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if text_width(draw, candidate, text_font) <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [""]


def draw_wrapped(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    text_font: ImageFont.ImageFont,
    fill: tuple[int, int, int],
    max_width: int,
    line_gap: int = 7,
) -> int:
    x, y = xy
    line_height = getattr(text_font, "size", 18) + line_gap
    for line in wrap_text(draw, text, text_font, max_width):
        draw.text((x, y), line, font=text_font, fill=fill)
        y += line_height
    return y


def wrapped_height(draw: ImageDraw.ImageDraw, text: str, text_font: ImageFont.ImageFont, max_width: int, line_gap: int = 7) -> int:
    return len(wrap_text(draw, text, text_font, max_width)) * (getattr(text_font, "size", 18) + line_gap)


def render_image(visible: list[dict[str, Any]], hidden: list[dict[str, Any]], md_out: Path, png_out: Path) -> None:
    width = 1500
    margin = 56
    card_width = width - margin * 2
    bg = (244, 247, 250)
    ink = (24, 34, 48)
    muted = (84, 99, 118)
    line = (214, 224, 234)
    card = (255, 255, 255)
    dark = (18, 31, 46)
    soft = (235, 241, 247)

    title_font = font(44, True)
    sub_font = font(22)
    h_font = font(26, True)
    body_font = font(20)
    small_font = font(17)
    tag_font = font(16, True)

    scratch = Image.new("RGB", (width, 200), bg)
    scratch_draw = ImageDraw.Draw(scratch)

    def card_height(item: dict[str, Any]) -> int:
        content_width = card_width - 68
        purpose_height = wrapped_height(scratch_draw, item["purpose"], body_font, content_width)
        path_height = wrapped_height(scratch_draw, item["launcher"], small_font, content_width)
        return max(168, 94 + purpose_height + path_height + 44)

    total_height = 290 + sum(card_height(item) + 20 for item in visible) + 220
    image = Image.new("RGB", (width, total_height), bg)
    draw = ImageDraw.Draw(image)

    draw.rectangle((0, 0, width, 230), fill=dark)
    draw.text((margin, 42), "EF Audio Tools", font=title_font, fill=(255, 255, 255))
    draw.text(
        (margin, 104),
        f"Main GUI tools: {len(visible)}  |  Hidden advanced tools: {len(hidden)}  |  {DATE}",
        font=sub_font,
        fill=(205, 218, 232),
    )
    draw.text(
        (margin, 148),
        "The GUI now shows only distinct daily manual entry points. Report, automation, legacy, and superseded tools stay hidden.",
        font=sub_font,
        fill=(205, 218, 232),
    )

    y = 270
    for index, item in enumerate(visible, 1):
        height = card_height(item)
        x0, y0, x1, y1 = margin, y, width - margin, y + height
        color = CATEGORY_COLORS.get(item["category"], CATEGORY_COLORS["Advanced"])
        draw.rounded_rectangle((x0, y0, x1, y1), radius=14, fill=card, outline=line, width=1)
        draw.rectangle((x0, y0, x0 + 12, y1), fill=color)

        draw.rounded_rectangle((x0 + 28, y0 + 24, x0 + 86, y0 + 58), radius=8, fill=color)
        draw.text((x0 + 43, y0 + 29), f"{index}", font=tag_font, fill=(255, 255, 255))
        draw.text((x0 + 104, y0 + 21), item["name"], font=h_font, fill=ink)
        draw.text((x0 + 104, y0 + 55), f"{item['category']}  |  {item['status']}", font=small_font, fill=color)

        current_y = y0 + 92
        current_y = draw_wrapped(draw, (x0 + 28, current_y), item["purpose"], body_font, muted, card_width - 68)
        current_y += 14
        draw.rounded_rectangle((x0 + 28, current_y, x1 - 28, current_y + 38), radius=8, fill=soft)
        draw.text((x0 + 42, current_y + 9), item["launcher"], font=small_font, fill=(70, 84, 102))
        y += height + 20

    draw.text((margin, y + 18), "Hidden advanced tools", font=h_font, fill=ink)
    hidden_names = ", ".join(item["launcher"] for item in hidden)
    draw_wrapped(draw, (margin, y + 58), hidden_names, small_font, muted, width - margin * 2)
    draw.text((margin, total_height - 56), f"Markdown: {md_out.name}  |  Image: {png_out.name}", font=small_font, fill=muted)

    image.save(png_out, quality=95)


def main() -> int:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    config, visible, hidden = load_items()
    md_out = REPORT_DIR / f"EF_Audio_Tools_Usage_Guide_{DATE}.md"
    png_out = REPORT_DIR / f"EF_Audio_Tools_Usage_Long_Image_{DATE}.png"
    json_out = REPORT_DIR / f"EF_Audio_Tools_Usage_Guide_{DATE}.json"

    render_markdown(config, visible, hidden, md_out)
    render_image(visible, hidden, md_out, png_out)
    json_out.write_text(
        json.dumps(
            {
                "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
                "visible_tools": visible,
                "hidden_tools": hidden,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(md_out)
    print(png_out)
    print(json_out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
