# -*- coding: utf-8 -*-
from __future__ import annotations

import html
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


TOOL_DIR = Path(__file__).resolve().parent
WORKSPACE_ROOT = TOOL_DIR.parent
REPORT_ROOTS = [WORKSPACE_ROOT / "报告", WORKSPACE_ROOT]
ROOT = REPORT_ROOTS[0]
OUT = WORKSPACE_ROOT / "ProjectEF_reports_html"
REPORTS_OUT = OUT / "reports"


REPORT_PATTERNS = [
    "ProjectEF_*.md",
    "ProjectEF_Wwise工程*.md",
    "ProjectEF_Unity音频集成静态审计_*.md",
    "ProjectEF_UnityWwise运行日志实时诊断_*.md",
    "ProjectEF_Stop_Wheel_Retrieve_Starvation诊断_*.md",
    "ProjectEF_Wwise工程与资源检测报告_*.md",
    "ProjectEF_Wwise工程体检报告_*.md",
    "ProjectEF_Unity音频集成静态审计_*.md",
    "ProjectEF_UnityWwise_RuntimeLog_Reparse_*.md",
    "ProjectEF_UnityWwise运行日志实时诊断_*.md",
    "ProjectEF_UnityWwise_RuntimeAudioFollow.md",
    "ProjectEF_UnityWwise_GUI_RuntimeAudioMonitor.md",
    "ProjectEF_Stop_Wheel_Retrieve_Starvation诊断_*.md",
    "ProjectEF_Others_Limitations_Analysis_*.md",
    "ProjectEF_Others_Limitations_Modification_*.md",
    "ProjectEF_AudioReport_TrendSummary.md",
]


FRIENDLY_TITLES = {
    "ProjectEF_下一步行动建议": "ProjectEF 音频下一步行动建议",
    "ProjectEF_RuntimeQA_Checklist": "ProjectEF Runtime QA Checklist",
    "ProjectEF_RuntimeBankOutput_Check": "ProjectEF Runtime Bank Output Check",
    "ProjectEF_Wwise工程与资源检测报告": "ProjectEF Wwise 工程与资源检测报告",
    "ProjectEF_Wwise工程体检报告": "ProjectEF Wwise 工程体检报告",
    "ProjectEF_Unity音频集成静态审计": "ProjectEF Unity 音频集成静态审计",
    "ProjectEF_UnityWwise运行日志实时诊断": "ProjectEF Unity/Wwise 运行日志实时诊断",
    "ProjectEF_Stop_Wheel_Retrieve_Starvation诊断": "ProjectEF Stop/Starvation 诊断",
    "ProjectEF_AudioReport_TrendSummary": "ProjectEF 音频检测趋势汇总",
    "ProjectEF_Others_Limitations_Analysis": "ProjectEF Others 限制分析报告",
    "ProjectEF_Others_Limitations_Modification": "ProjectEF Others 限制修改报告",
    "ProjectEF_AudioReport_TrendSummary": "ProjectEF 音频检测趋势汇总",
    "ProjectEF_UnityWwise_GUI_RuntimeAudioMonitor": "ProjectEF Unity/Wwise GUI 运行监控报告",
    "ProjectEF_UnityWwise_RuntimeAudioFollow": "ProjectEF Unity/Wwise 运行日志跟踪报告",
}

FRIENDLY_TITLES.update(
    {
        "ProjectEF_下一步行动建议": "ProjectEF 音频下一步行动建议",
        "ProjectEF_RuntimeQA_Checklist": "ProjectEF Runtime QA Checklist",
        "ProjectEF_RuntimeBankOutput_Check": "ProjectEF Runtime Bank Output Check",
        "ProjectEF_Wwise工程与资源检测报告": "ProjectEF Wwise 工程与资源检测报告",
        "ProjectEF_Wwise工程体检报告": "ProjectEF Wwise 工程体检报告",
        "ProjectEF_Unity音频集成静态审计": "ProjectEF Unity 音频集成静态审计",
        "ProjectEF_UnityWwise运行日志实时诊断": "ProjectEF Unity/Wwise 运行日志实时诊断",
        "ProjectEF_Stop_Wheel_Retrieve_Starvation诊断": "ProjectEF Stop/Starvation 诊断",
        "ProjectEF_AudioReport_TrendSummary": "ProjectEF 音频检测趋势汇总",
    }
)


CSS = r"""
:root {
  --bg: #f4f7fb;
  --paper: #ffffff;
  --ink: #162033;
  --muted: #65758b;
  --line: #d7e0ea;
  --blue: #2456d6;
  --blue-soft: #e9efff;
  --green-soft: #e9f8ef;
  --red-soft: #fff0f0;
  --amber-soft: #fff7df;
  --shadow: 0 18px 45px rgba(28, 44, 76, .12);
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0;
  font-family: "Microsoft YaHei", "Segoe UI", Arial, sans-serif;
  color: var(--ink);
  background: var(--bg);
  line-height: 1.62;
}
.page {
  max-width: 1240px;
  margin: 0 auto;
  padding: 34px 28px 56px;
}
.hero {
  background: linear-gradient(135deg, #ffffff, #edf3ff);
  border: 1px solid var(--line);
  border-radius: 16px;
  padding: 30px 34px;
  box-shadow: var(--shadow);
}
.eyebrow {
  margin: 0 0 8px;
  color: var(--blue);
  font-weight: 700;
  letter-spacing: .04em;
  text-transform: uppercase;
  font-size: 13px;
}
h1 {
  margin: 0;
  font-size: 30px;
  line-height: 1.24;
}
.sub {
  margin: 12px 0 0;
  color: var(--muted);
  max-width: 920px;
}
.meta-grid, .cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 14px;
  margin: 22px 0;
}
.meta, .card {
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 16px 18px;
  box-shadow: 0 8px 22px rgba(28, 44, 76, .06);
}
.meta .label, .card .label {
  color: var(--muted);
  font-size: 13px;
}
.meta .value {
  margin-top: 4px;
  font-weight: 700;
  font-size: 18px;
}
.toolbar {
  position: sticky;
  top: 0;
  z-index: 10;
  margin: 18px 0;
  padding: 12px;
  background: rgba(244, 247, 251, .92);
  backdrop-filter: blur(10px);
  border-bottom: 1px solid var(--line);
}
.toolbar a {
  display: inline-block;
  margin: 4px 6px 4px 0;
  padding: 7px 11px;
  border: 1px solid var(--line);
  border-radius: 999px;
  color: var(--blue);
  background: #fff;
  text-decoration: none;
  font-size: 13px;
}
.content {
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: 16px;
  padding: 28px 32px;
  box-shadow: var(--shadow);
}
h2 {
  margin-top: 34px;
  padding-bottom: 8px;
  border-bottom: 2px solid var(--blue-soft);
  font-size: 24px;
}
h3 {
  margin-top: 28px;
  font-size: 19px;
}
p, li { font-size: 15px; }
a { color: var(--blue); }
code {
  padding: 2px 5px;
  border-radius: 5px;
  background: #eef3fa;
  font-family: Consolas, "Courier New", monospace;
  font-size: .92em;
}
pre {
  overflow: auto;
  padding: 14px 16px;
  border-radius: 10px;
  background: #111827;
  color: #e5e7eb;
}
.table-wrap {
  overflow-x: auto;
  margin: 14px 0 22px;
  border: 1px solid var(--line);
  border-radius: 12px;
}
table {
  width: 100%;
  border-collapse: collapse;
  min-width: 760px;
  background: #fff;
}
th, td {
  border-bottom: 1px solid var(--line);
  padding: 9px 11px;
  text-align: left;
  vertical-align: top;
  font-size: 13px;
}
th {
  position: sticky;
  top: 0;
  z-index: 1;
  background: #edf3ff;
  color: #243b64;
  font-weight: 700;
}
tr:nth-child(even) td { background: #fafcff; }
.severity-error, td:has(.severity-error) { background: var(--red-soft); }
.severity-warn, td:has(.severity-warn) { background: var(--amber-soft); }
.severity-pass, td:has(.severity-pass) { background: var(--green-soft); }
.badge {
  display: inline-block;
  padding: 2px 7px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
}
.badge.error { background: #ffe1e1; color: #9d1c1c; }
.badge.warn { background: #fff0ba; color: #805700; }
.badge.pass { background: #ddf7e5; color: #116b35; }
.report-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(310px, 1fr));
  gap: 16px;
  margin-top: 22px;
}
.report-card {
  display: flex;
  flex-direction: column;
  min-height: 220px;
  color: inherit;
  text-decoration: none;
  transition: transform .16s ease, box-shadow .16s ease;
}
.report-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 20px 38px rgba(28, 44, 76, .15);
}
.report-title {
  font-size: 18px;
  font-weight: 800;
  line-height: 1.35;
}
.report-desc {
  margin-top: 10px;
  color: var(--muted);
  font-size: 14px;
}
.report-stats {
  margin-top: auto;
  padding-top: 16px;
  color: var(--muted);
  font-size: 13px;
}
.footer {
  margin-top: 30px;
  color: var(--muted);
  font-size: 13px;
}
@media print {
  body { background: white; }
  .toolbar { display: none; }
  .hero, .content, .meta, .card { box-shadow: none; }
  .page { max-width: none; padding: 14px; }
}
"""


@dataclass
class Report:
    source: Path
    html_name: str
    title: str
    summary: list[str]
    size_kb: float
    modified: str
    headings: list[tuple[int, str, str]]


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig", errors="replace")


def slugify(text: str) -> str:
    text = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", text, flags=re.UNICODE).strip("-")
    return text[:80] or "section"


def safe_filename(path: Path) -> str:
    stem = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", path.stem, flags=re.UNICODE)
    return stem + ".html"


def friendly_title(path: Path) -> str | None:
    for token, title in FRIENDLY_TITLES.items():
        if token in path.stem:
            return title
    return None


def looks_broken(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    if not compact:
        return False
    return text.count("?") / max(len(compact), 1) > 0.08


def clean_cell(value: object) -> str:
    if value is None:
        return ""
    text = str(value)
    return text.replace("|", "/").replace("\n", "<br>")


def others_analysis_from_json(path: Path) -> str | None:
    json_path = path.with_suffix(".json")
    if not json_path.exists():
        return None
    data = json.loads(json_path.read_text(encoding="utf-8-sig"))
    counts = data.get("counts", {})
    version = (data.get("waapi_info") or {}).get("version") or {}
    objects = data.get("objects", [])

    rows = []
    for item in objects:
        target = item.get("target") or {}
        rows.append(
            "| "
            + " | ".join(
                clean_cell(value)
                for value in [
                    item.get("name"),
                    item.get("type"),
                    item.get("status"),
                    item.get("obsolete"),
                    item.get("live_ok"),
                    item.get("saved_ok"),
                    target.get("MaxSoundPerInstance"),
                    item.get("live_path"),
                    item.get("saved_file"),
                ]
            )
            + " |"
        )

    return "\n".join(
        [
            "# ProjectEF Others 限制分析报告",
            "",
            "> 原 Markdown 的中文内容已经损坏为问号；本展示页根据同名 JSON 重新整理，避免把乱码带入汇报版本。",
            "",
            "## Summary",
            "",
            f"- Wwise project: `{clean_cell(data.get('project'))}`",
            f"- WAAPI version: {clean_cell(version.get('displayName'))} build {clean_cell(version.get('build'))}",
            f"- Own Other/Others objects: {clean_cell(counts.get('own_other_total'))}",
            f"- Active objects: {clean_cell(counts.get('active'))}",
            f"- Need fix: {clean_cell(counts.get('needs_fix'))}",
            f"- Matched live but unsaved/file-diff: {clean_cell(counts.get('matched_live'))}",
            f"- Obsolete skipped: {clean_cell(counts.get('obsolete'))}",
            "",
            "## Applied Check Rule",
            "",
            "- Other/Others 对象需要启用全局播放数量限制。",
            "- `UseMaxSoundPerInstance = True`。",
            "- `IgnoreParentMaxSoundInstance = True`。",
            "- Footsteps / WaterIn / WaterOut 类 Others 目标值通常为 `MaxSoundPerInstance = 5`。",
            "- Reel / Line / Rattle / Buzzbait / Clothes / Broke / Strike 类 Others 目标值通常为 `MaxSoundPerInstance = 3`。",
            "",
            "## Object Detail",
            "",
            "| Name | Type | Status | Obsolete | Live OK | Saved OK | Target Max | Live Path | Saved File |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
            *rows,
        ]
    )


def inline_md(text: str) -> str:
    text = html.escape(text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    text = text.replace("&lt;br&gt;", "<br>").replace("&lt;br/&gt;", "<br>")
    for word, cls in [("Error", "error"), ("Fail", "error"), ("Warn", "warn"), ("Pass", "pass")]:
        text = re.sub(rf"\b{word}\b", f'<span class="badge {cls}">{word}</span>', text)
    return text


def parse_table(lines: list[str], start: int) -> tuple[str, int]:
    rows: list[list[str]] = []
    i = start
    while i < len(lines):
        s = lines[i].strip()
        if not (s.startswith("|") and s.endswith("|")):
            break
        cells = [c.strip() for c in s.strip("|").split("|")]
        if not all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
            rows.append(cells)
        i += 1
    if not rows:
        return "", i
    head = rows[0]
    body = rows[1:]
    out = ['<div class="table-wrap"><table>']
    out.append("<thead><tr>" + "".join(f"<th>{inline_md(c)}</th>" for c in head) + "</tr></thead>")
    out.append("<tbody>")
    for row in body:
        padded = row + [""] * (len(head) - len(row))
        out.append("<tr>" + "".join(f"<td>{inline_md(c)}</td>" for c in padded[: len(head)]) + "</tr>")
    out.append("</tbody></table></div>")
    return "\n".join(out), i


def markdown_to_html(text: str) -> tuple[str, list[tuple[int, str, str]]]:
    lines = text.splitlines()
    out: list[str] = []
    headings: list[tuple[int, str, str]] = []
    paragraph: list[str] = []
    in_code = False
    code_lines: list[str] = []
    list_open = False

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            out.append(f"<p>{inline_md(' '.join(paragraph))}</p>")
            paragraph = []

    def close_list() -> None:
        nonlocal list_open
        if list_open:
            out.append("</ul>")
            list_open = False

    i = 0
    while i < len(lines):
        raw = lines[i]
        s = raw.strip()
        if s.startswith("```"):
            flush_paragraph()
            close_list()
            if not in_code:
                in_code = True
                code_lines = []
            else:
                out.append("<pre><code>" + html.escape("\n".join(code_lines)) + "</code></pre>")
                in_code = False
            i += 1
            continue
        if in_code:
            code_lines.append(raw)
            i += 1
            continue
        if not s:
            flush_paragraph()
            close_list()
            i += 1
            continue
        if s.startswith("|") and s.endswith("|"):
            flush_paragraph()
            close_list()
            table_html, i = parse_table(lines, i)
            out.append(table_html)
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", s)
        if heading:
            flush_paragraph()
            close_list()
            level = len(heading.group(1))
            title = heading.group(2).strip()
            slug = slugify(title)
            duplicate = sum(1 for _, _, existing in headings if existing == slug)
            if duplicate:
                slug = f"{slug}-{duplicate + 1}"
            headings.append((level, title, slug))
            out.append(f'<h{level} id="{html.escape(slug)}">{inline_md(title)}</h{level}>')
            i += 1
            continue
        bullet = re.match(r"^[-*]\s+(.*)$", s)
        if bullet:
            flush_paragraph()
            if not list_open:
                out.append("<ul>")
                list_open = True
            out.append(f"<li>{inline_md(bullet.group(1))}</li>")
            i += 1
            continue
        paragraph.append(s)
        i += 1
    flush_paragraph()
    close_list()
    if in_code:
        out.append("<pre><code>" + html.escape("\n".join(code_lines)) + "</code></pre>")
    return "\n".join(out), headings


def extract_title(text: str, path: Path) -> str:
    preferred = friendly_title(path)
    if preferred and looks_broken(text):
        return preferred
    for line in text.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            if "??" not in title:
                return title
    if preferred:
        return preferred
    return path.stem


def extract_summary(text: str) -> list[str]:
    lines = text.splitlines()
    summary: list[str] = []
    capture = False
    for line in lines:
        s = line.strip()
        if re.match(r"^##\s+(摘要|Summary|总体结论)", s, flags=re.I):
            capture = True
            continue
        if capture and s.startswith("## "):
            break
        if capture:
            if s.startswith("- "):
                summary.append(s[2:])
            elif s.startswith("|") and not re.fullmatch(r"\|\s*:?-{3,}:?.*", s):
                cells = [c.strip() for c in s.strip("|").split("|")]
                if len(cells) >= 2 and cells[0] not in {"项目", "Category", "Severity"}:
                    summary.append(f"{cells[0]}：{cells[1]}")
        if len(summary) >= 7:
            break
    if not summary:
        for line in lines[:40]:
            s = line.strip()
            if s.startswith("- "):
                summary.append(s[2:])
            if len(summary) >= 5:
                break
    return summary[:7]


def report_kind(name: str) -> str:
    mapping = [
        ("Unity音频集成静态审计", "Unity 静态审计"),
        ("RuntimeLog_Reparse", "运行日志复盘"),
        ("运行日志实时诊断", "运行日志实时诊断"),
        ("RuntimeAudioFollow", "运行时跟踪"),
        ("GUI_RuntimeAudioMonitor", "GUI 运行监控"),
        ("Stop_Wheel", "Stop/Starvation 诊断"),
        ("Others_Limitations_Modification", "Others 限制修改"),
        ("Others_Limitations_Analysis", "Others 限制分析"),
        ("TrendSummary", "趋势汇总"),
        ("工程体检", "Wwise 工程体检"),
        ("工程与资源检测", "Wwise 工程与资源检测"),
    ]
    for token, label in mapping:
        if token in name:
            return label
    return "ProjectEF 报告"


def render_report(path: Path) -> Report:
    text = read_text(path)
    source_note = f"来源 Markdown：{path.name}"
    if "Others_Limitations_Analysis" in path.stem and looks_broken(text):
        rebuilt = others_analysis_from_json(path)
        if rebuilt:
            text = rebuilt
            source_note = f"来源 JSON 重建：{path.with_suffix('.json').name}；原 Markdown 保留但未用于展示正文"
    body, headings = markdown_to_html(text)
    title = extract_title(text, path)
    summary = extract_summary(text)
    html_name = safe_filename(path)
    mtime = datetime.fromtimestamp(path.stat().st_mtime)
    modified = mtime.strftime("%Y-%m-%d %H:%M:%S")
    nav = "\n".join(
        f'<a href="#{html.escape(slug)}">{html.escape(title)}</a>'
        for level, title, slug in headings
        if level <= 2
    )
    summary_cards = "\n".join(
        f'<div class="meta"><div class="label">摘要</div><div class="value">{inline_md(item)}</div></div>'
        for item in summary[:4]
    )
    doc = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>{CSS}</style>
</head>
<body>
  <main class="page">
    <section class="hero">
      <p class="eyebrow">{html.escape(report_kind(path.name))}</p>
      <h1>{html.escape(title)}</h1>
      <p class="sub">{html.escape(source_note)}。生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}。</p>
      <div class="meta-grid">
        <div class="meta"><div class="label">文件大小</div><div class="value">{path.stat().st_size / 1024:.1f} KB</div></div>
        <div class="meta"><div class="label">最后修改</div><div class="value">{modified}</div></div>
        <div class="meta"><div class="label">章节数</div><div class="value">{len(headings)}</div></div>
        <div class="meta"><div class="label">展示版</div><div class="value">HTML</div></div>
      </div>
      <div class="meta-grid">{summary_cards}</div>
    </section>
    <nav class="toolbar"><a href="../index.html">返回首页</a>{nav}</nav>
    <article class="content">
      {body}
    </article>
    <p class="footer">Generated from local ProjectEF reports. 原始 Markdown 未被修改。</p>
  </main>
</body>
</html>
"""
    (REPORTS_OUT / html_name).write_text(doc, encoding="utf-8")
    return Report(path, html_name, title, summary, path.stat().st_size / 1024, modified, headings)


def collect_reports() -> list[Path]:
    by_name: dict[str, Path] = {}
    for root in REPORT_ROOTS:
        if not root.exists():
            continue
        for pattern in REPORT_PATTERNS:
            for path in sorted(root.glob(pattern)):
                # Skip known duplicate file with mojibake filename; the clean filename exists too.
                if "杩" in path.name:
                    continue
                current = by_name.get(path.name)
                if current is None or path.stat().st_mtime > current.stat().st_mtime:
                    by_name[path.name] = path
    return sorted(by_name.values(), key=lambda p: p.stat().st_mtime, reverse=True)


def render_index(reports: list[Report]) -> None:
    cards = []
    for report in reports:
        bullets = "".join(f"<li>{inline_md(item)}</li>" for item in report.summary[:4])
        cards.append(
            f"""
<a class="card report-card" href="reports/{html.escape(report.html_name)}">
  <div class="label">{html.escape(report_kind(report.source.name))}</div>
  <div class="report-title">{html.escape(report.title)}</div>
  <div class="report-desc"><ul>{bullets}</ul></div>
  <div class="report-stats">{report.size_kb:.1f} KB · {html.escape(report.modified)} · {len(report.headings)} sections</div>
</a>
"""
        )
    doc = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ProjectEF 音频检测报告展示版</title>
  <style>{CSS}</style>
</head>
<body>
  <main class="page">
    <section class="hero">
      <p class="eyebrow">ProjectEF Audio QA</p>
      <h1>ProjectEF 音频检测报告展示版</h1>
      <p class="sub">汇总 Wwise 工程检测、Unity 音频静态审计、运行时日志诊断、Stop/Starvation 诊断与 Others 限制修改报告。所有页面由本地 Markdown 转换，原始报告不变。</p>
      <div class="meta-grid">
        <div class="meta"><div class="label">报告数量</div><div class="value">{len(reports)}</div></div>
        <div class="meta"><div class="label">生成时间</div><div class="value">{datetime.now().strftime('%Y-%m-%d %H:%M')}</div></div>
        <div class="meta"><div class="label">Wwise 工程</div><div class="value">D:\\EF Wwise\\ProjectEF</div></div>
        <div class="meta"><div class="label">Unity 工程</div><div class="value">D:\\EF New\\Client\\TargetProject</div></div>
      </div>
    </section>
    <section class="report-grid">
      {''.join(cards)}
    </section>
    <p class="footer">打开单份报告后，可以用顶部胶囊导航跳转章节。大表格支持横向滚动。</p>
  </main>
</body>
</html>
"""
    (OUT / "index.html").write_text(doc, encoding="utf-8")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    REPORTS_OUT.mkdir(parents=True, exist_ok=True)
    paths = collect_reports()
    if not paths:
        raise SystemExit("No ProjectEF markdown reports found.")
    reports = [render_report(path) for path in paths]
    render_index(reports)
    print(f"Generated {len(reports)} report HTML files")
    print(OUT / "index.html")
    for report in reports:
        print(REPORTS_OUT / report.html_name)


if __name__ == "__main__":
    main()
