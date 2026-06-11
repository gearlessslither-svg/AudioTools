# -*- coding: utf-8 -*-
from __future__ import annotations

import html
import re
from pathlib import Path


SRC = Path(r"G:\AI\Material\Wwise\ProjectEF_Wwise工程与资源检测报告_2026-05-25.md")
OUT = Path(r"G:\AI\Material\Wwise\ProjectEF_Wwise工程与资源检测报告_2026-05-25.html")


def inline(text: str) -> str:
    text = html.escape(text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"(https?://[^\s<]+)", r'<a href="\1" target="_blank" rel="noreferrer">\1</a>', text)
    return text


def slug(title: str, used: set[str]) -> str:
    base = re.sub(r"[^\w\u4e00-\u9fff]+", "-", title.strip()).strip("-").lower() or "section"
    cur = base
    n = 2
    while cur in used:
        cur = f"{base}-{n}"
        n += 1
    used.add(cur)
    return cur


def is_table_line(line: str) -> bool:
    return line.startswith("|") and line.endswith("|")


def split_table(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip("|").split("|")]


def render_table(lines: list[str], caption: str = "") -> str:
    rows = [split_table(line) for line in lines if is_table_line(line)]
    if len(rows) < 2:
        return ""
    header = rows[0]
    body = rows[2:] if len(rows) > 2 and all(set(c) <= {"-"} for c in [x.replace(" ", "") for x in rows[1]]) else rows[1:]
    cls = "table-wrap"
    if caption.startswith("不合理点") or "可能原因" in header or "修改意见" in header:
        cls += " risk-table"
    out = [f'<div class="{cls}"><table>']
    out.append("<thead><tr>" + "".join(f"<th>{inline(c)}</th>" for c in header) + "</tr></thead>")
    out.append("<tbody>")
    for row in body:
        padded = row + [""] * (len(header) - len(row))
        out.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in padded[: len(header)]) + "</tr>")
    out.append("</tbody></table></div>")
    return "\n".join(out)


def markdown_to_html(md: str) -> tuple[str, list[tuple[int, str, str]]]:
    lines = md.splitlines()
    used: set[str] = set()
    toc: list[tuple[int, str, str]] = []
    out: list[str] = []
    i = 0
    in_ul = False
    para: list[str] = []
    current_header = ""

    def flush_para() -> None:
        nonlocal para
        if para:
            out.append("<p>" + inline(" ".join(para).strip()) + "</p>")
            para = []

    def close_ul() -> None:
        nonlocal in_ul
        if in_ul:
            out.append("</ul>")
            in_ul = False

    while i < len(lines):
        line = lines[i].rstrip()
        if not line:
            flush_para()
            close_ul()
            i += 1
            continue

        if is_table_line(line):
            flush_para()
            close_ul()
            table_lines = []
            while i < len(lines) and is_table_line(lines[i].rstrip()):
                table_lines.append(lines[i].rstrip())
                i += 1
            out.append(render_table(table_lines, current_header))
            continue

        m = re.match(r"^(#{1,4})\s+(.+)$", line)
        if m:
            flush_para()
            close_ul()
            level = len(m.group(1))
            title = m.group(2).strip()
            sid = slug(title, used)
            current_header = title
            toc.append((level, title, sid))
            out.append(f'<h{level} id="{sid}">{inline(title)}</h{level}>')
            i += 1
            continue

        if line.startswith("- "):
            flush_para()
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            out.append("<li>" + inline(line[2:].strip()) + "</li>")
            i += 1
            continue

        close_ul()
        para.append(line)
        i += 1

    flush_para()
    close_ul()
    return "\n".join(out), toc


def extract_cards(md: str) -> list[tuple[str, str]]:
    pairs = []
    patterns = {
        "WAAPI": r"- WAAPI：(.+)",
        "解析对象": r"- 解析对象数：(.+)",
        "Fail": r"\| Fail\s+\|\s+(.+?)\s+\|",
        "Warn": r"\| Warn\s+\|\s+(.+?)\s+\|",
        "未引用 WAV": r"\| Unreferenced WAV files\s+\|\s+(.+?)\s+\|",
        "风险建议": r"\| Risk/Advice rows\s+\|\s+(.+?)\s+\|",
    }
    for key, pat in patterns.items():
        m = re.search(pat, md)
        if m:
            pairs.append((key, m.group(1).strip()))
    return pairs


def build_html(md: str) -> str:
    body, toc = markdown_to_html(md)
    cards = extract_cards(md)
    card_html = "\n".join(f"<div class='card'><span>{html.escape(k)}</span><strong>{inline(v)}</strong></div>" for k, v in cards)
    toc_html = "\n".join(
        f"<a class='toc-l{level}' href='#{sid}'>{inline(title)}</a>" for level, title, sid in toc if level <= 2
    )
    css = r"""
:root { color-scheme: light; --bg:#f5f7fb; --panel:#ffffff; --ink:#18212b; --muted:#66717f; --line:#d8e0ea; --blue:#2563eb; --red:#b42318; --amber:#9a5b00; --green:#237a45; }
* { box-sizing: border-box; }
body { margin:0; font-family: "Microsoft YaHei", "Noto Sans SC", "Segoe UI", Arial, sans-serif; background:var(--bg); color:var(--ink); }
.layout { display:grid; grid-template-columns: 310px minmax(0,1fr); min-height:100vh; }
aside { position:sticky; top:0; height:100vh; overflow:auto; border-right:1px solid var(--line); background:#eef3f9; padding:24px 18px; }
aside h2 { margin:0 0 14px; font-size:18px; }
aside a { display:block; padding:7px 10px; color:#253141; text-decoration:none; border-radius:8px; font-size:14px; line-height:1.3; }
aside a:hover { background:#dde8f5; color:#0f4ca3; }
.toc-l2 { margin-left:10px; color:#526071; }
main { padding:34px 44px 70px; max-width:1600px; }
.hero { background:linear-gradient(135deg,#102033,#1e3a5f); color:white; border-radius:14px; padding:28px 32px; margin-bottom:22px; box-shadow:0 14px 36px rgba(16,32,51,.16); }
.hero h1 { margin:0 0 10px; font-size:30px; border:0; color:white; }
.hero p { margin:0; color:#cbd8e8; }
.cards { display:grid; grid-template-columns: repeat(auto-fit,minmax(160px,1fr)); gap:12px; margin:20px 0 30px; }
.card { background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:14px 16px; box-shadow:0 4px 18px rgba(20,32,48,.06); }
.card span { display:block; font-size:13px; color:var(--muted); margin-bottom:7px; }
.card strong { font-size:20px; overflow-wrap:anywhere; }
h1, h2, h3, h4 { scroll-margin-top:18px; }
main > h1 { display:none; }
h2 { margin:38px 0 14px; padding-bottom:8px; border-bottom:2px solid var(--line); font-size:24px; }
h3 { margin:28px 0 10px; font-size:19px; }
p { line-height:1.72; color:#283443; }
ul { background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:16px 22px 16px 34px; }
li { margin:7px 0; line-height:1.62; }
code { background:#eef2f7; border:1px solid #dce4ee; padding:1px 5px; border-radius:5px; font-family: Consolas, "SFMono-Regular", monospace; font-size:.92em; }
a { color:var(--blue); }
.table-wrap { overflow:auto; margin:14px 0 26px; border:1px solid var(--line); border-radius:12px; background:white; box-shadow:0 5px 22px rgba(20,32,48,.05); }
table { width:100%; border-collapse:collapse; min-width:720px; }
th, td { padding:10px 12px; border-bottom:1px solid #e5ebf2; vertical-align:top; text-align:left; line-height:1.48; font-size:14px; }
th { position:sticky; top:0; background:#f0f5fb; color:#1f2d3d; z-index:1; }
tr:hover td { background:#fafcff; }
.risk-table table { min-width:1180px; }
.risk-table th { background:#fff0e9; }
.risk-table td:first-child { font-weight:700; color:var(--red); min-width:230px; }
.risk-table td:nth-child(4) { color:#214f36; }
@media (max-width: 900px) { .layout { display:block; } aside { position:relative; height:auto; } main { padding:24px 18px; } }
"""
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ProjectEF Wwise 工程与资源检测报告</title>
<style>{css}</style>
</head>
<body>
<div class="layout">
<aside>
<h2>报告目录</h2>
{toc_html}
</aside>
<main>
<section class="hero">
<h1>ProjectEF Wwise 工程与资源检测报告</h1>
<p>HTML 版由 Markdown 报告生成，方便浏览、检索和横向查看大表格。</p>
</section>
<section class="cards">{card_html}</section>
{body}
</main>
</div>
</body>
</html>"""


def main() -> None:
    md = SRC.read_text(encoding="utf-8")
    OUT.write_text(build_html(md), encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()
