import html
import re
from pathlib import Path


ROOT = Path(r"G:\AI\Material\Wwise")
SRC = ROOT / "AI音频研发流程与Skill沉淀汇报_2026-05-25.md"
OUT = ROOT / "AI音频研发流程与Skill沉淀汇报_2026-05-25.html"


def slugify(text: str, used: set[str]) -> str:
    base = re.sub(r"[^\w\u4e00-\u9fff]+", "-", text.strip().lower()).strip("-")
    base = base or "section"
    slug = base
    i = 2
    while slug in used:
        slug = f"{base}-{i}"
        i += 1
    used.add(slug)
    return slug


def inline_md(text: str) -> str:
    text = html.escape(text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    return text


def parse_table(lines: list[str], start: int):
    rows = []
    i = start
    while i < len(lines) and "|" in lines[i] and lines[i].strip():
        raw = lines[i].strip()
        if re.fullmatch(r"[\s|:\-]+", raw):
            i += 1
            continue
        cells = [c.strip() for c in raw.strip("|").split("|")]
        rows.append(cells)
        i += 1
    return rows, i


def table_html(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    head, body = rows[0], rows[1:]
    out = ['<div class="table-wrap"><table>']
    out.append("<thead><tr>")
    for cell in head:
        out.append(f"<th>{inline_md(cell)}</th>")
    out.append("</tr></thead>")
    if body:
        out.append("<tbody>")
        for row in body:
            out.append("<tr>")
            for cell in row:
                out.append(f"<td>{inline_md(cell)}</td>")
            out.append("</tr>")
        out.append("</tbody>")
    out.append("</table></div>")
    return "".join(out)


def md_to_html(markdown: str):
    lines = markdown.splitlines()
    out: list[str] = []
    toc: list[tuple[int, str, str]] = []
    used: set[str] = set()
    list_type = None
    in_code = False
    code_lang = ""
    code_lines: list[str] = []
    first_h1_skipped = False

    def close_list():
        nonlocal list_type
        if list_type:
            out.append(f"</{list_type}>")
            list_type = None

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith("```"):
            if not in_code:
                close_list()
                in_code = True
                code_lang = stripped.strip("`").strip()
                code_lines = []
            else:
                out.append(
                    f'<pre><span class="code-lang">{html.escape(code_lang or "text")}</span>'
                    f"<code>{html.escape(chr(10).join(code_lines))}</code></pre>"
                )
                in_code = False
            i += 1
            continue

        if in_code:
            code_lines.append(line)
            i += 1
            continue

        if not stripped:
            close_list()
            i += 1
            continue

        if "|" in line and i + 1 < len(lines) and re.fullmatch(r"[\s|:\-]+", lines[i + 1].strip()):
            close_list()
            rows, next_i = parse_table(lines, i)
            out.append(table_html(rows))
            i = next_i
            continue

        heading = re.match(r"^(#{1,4})\s+(.+)$", stripped)
        if heading:
            close_list()
            level = len(heading.group(1))
            title = heading.group(2).strip()
            if level == 1 and not first_h1_skipped:
                first_h1_skipped = True
                i += 1
                continue
            hid = slugify(title, used)
            if level <= 3:
                toc.append((level, title, hid))
            out.append(f'<h{level} id="{hid}">{inline_md(title)}</h{level}>')
            i += 1
            continue

        ordered = re.match(r"^\d+\.\s+(.+)$", stripped)
        bullet = re.match(r"^[-*]\s+(.+)$", stripped)
        if ordered or bullet:
            desired = "ol" if ordered else "ul"
            if list_type != desired:
                close_list()
                list_type = desired
                out.append(f"<{desired}>")
            item = ordered.group(1) if ordered else bullet.group(1)
            out.append(f"<li>{inline_md(item)}</li>")
            i += 1
            continue

        close_list()
        out.append(f"<p>{inline_md(stripped)}</p>")
        i += 1

    close_list()
    return "\n".join(out), toc


def build_html(content: str, toc: list[tuple[int, str, str]]) -> str:
    toc_html = "\n".join(
        f'<a class="toc-l{level}" href="#{hid}">{html.escape(title)}</a>'
        for level, title, hid in toc
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>AI 音频研发流程与 Skill 沉淀汇报</title>
  <style>
    :root {{
      --bg: #f6f3ee;
      --paper: #fffdf9;
      --ink: #1f2528;
      --muted: #6d7478;
      --line: #ded7cc;
      --soft: #ece7de;
      --accent: #566f68;
      --accent-2: #9a7b4f;
      --shadow: 0 18px 50px rgba(31, 37, 40, 0.08);
    }}
    * {{ box-sizing: border-box; }}
    html {{ scroll-behavior: smooth; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: "Microsoft YaHei", "PingFang SC", "Segoe UI", Arial, sans-serif;
      line-height: 1.76;
      letter-spacing: 0;
    }}
    .page {{
      display: grid;
      grid-template-columns: 280px minmax(0, 1fr);
      min-height: 100vh;
    }}
    aside {{
      position: sticky;
      top: 0;
      height: 100vh;
      padding: 36px 28px;
      border-right: 1px solid var(--line);
      background: rgba(255, 253, 249, 0.72);
      backdrop-filter: blur(10px);
      overflow: auto;
    }}
    .brand {{
      font-size: 13px;
      color: var(--accent);
      text-transform: uppercase;
      letter-spacing: .08em;
      margin-bottom: 14px;
    }}
    .toc-title {{
      font-size: 18px;
      font-weight: 700;
      line-height: 1.35;
      margin-bottom: 28px;
    }}
    nav a {{
      display: block;
      color: var(--muted);
      text-decoration: none;
      font-size: 13px;
      padding: 7px 0;
      border-bottom: 1px solid rgba(222, 215, 204, .5);
    }}
    nav a:hover {{ color: var(--ink); }}
    .toc-l3 {{ padding-left: 14px; font-size: 12px; }}
    main {{
      max-width: 1120px;
      width: 100%;
      margin: 0 auto;
      padding: 52px 56px 80px;
    }}
    .hero {{
      background: var(--paper);
      border: 1px solid var(--line);
      box-shadow: var(--shadow);
      padding: 56px;
      margin-bottom: 28px;
    }}
    .eyebrow {{
      color: var(--accent);
      font-size: 13px;
      font-weight: 700;
      letter-spacing: .08em;
      text-transform: uppercase;
      margin-bottom: 18px;
    }}
    h1 {{
      font-size: clamp(34px, 4vw, 58px);
      line-height: 1.08;
      margin: 0 0 18px;
      letter-spacing: 0;
    }}
    .subtitle {{
      max-width: 760px;
      color: var(--muted);
      font-size: 17px;
      margin: 0;
    }}
    .meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      margin-top: 32px;
    }}
    .pill {{
      border: 1px solid var(--line);
      background: var(--soft);
      color: #3d4548;
      padding: 7px 11px;
      font-size: 12px;
    }}
    .cards {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 14px;
      margin: 28px 0 42px;
    }}
    .card {{
      background: var(--paper);
      border: 1px solid var(--line);
      padding: 22px;
      min-height: 136px;
    }}
    .card b {{
      display: block;
      font-size: 22px;
      margin-bottom: 8px;
      color: var(--accent);
    }}
    .card span {{
      display: block;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.65;
    }}
    article {{
      background: var(--paper);
      border: 1px solid var(--line);
      box-shadow: var(--shadow);
      padding: 48px 56px;
    }}
    h2 {{
      margin: 48px 0 16px;
      padding-top: 16px;
      border-top: 1px solid var(--line);
      font-size: 25px;
      line-height: 1.35;
    }}
    h2:first-child {{ margin-top: 0; border-top: 0; padding-top: 0; }}
    h3 {{
      margin: 30px 0 12px;
      color: var(--accent);
      font-size: 18px;
    }}
    h4 {{
      margin: 24px 0 10px;
      font-size: 15px;
      color: #333b3e;
    }}
    p {{ margin: 0 0 14px; }}
    ul, ol {{ margin: 0 0 18px 22px; padding: 0; }}
    li {{ margin: 7px 0; }}
    strong {{ color: #15191b; }}
    code {{
      font-family: Consolas, "SFMono-Regular", Menlo, monospace;
      font-size: .92em;
      background: #eee8dd;
      border: 1px solid #ddd4c6;
      padding: 1px 5px;
    }}
    pre {{
      position: relative;
      margin: 20px 0;
      background: #222927;
      color: #f5f1e8;
      padding: 38px 20px 18px;
      overflow: auto;
      border: 1px solid #1d2322;
    }}
    pre code {{
      background: transparent;
      border: 0;
      padding: 0;
      color: inherit;
      font-size: 13px;
    }}
    .code-lang {{
      position: absolute;
      top: 10px;
      left: 18px;
      font-size: 11px;
      color: #b9c7c0;
    }}
    .table-wrap {{
      overflow: auto;
      margin: 20px 0 26px;
      border: 1px solid var(--line);
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      min-width: 760px;
      background: #fffefb;
    }}
    th, td {{
      border-bottom: 1px solid var(--line);
      border-right: 1px solid var(--line);
      padding: 11px 12px;
      text-align: left;
      vertical-align: top;
      font-size: 13px;
    }}
    th {{
      background: #ebe5da;
      color: #30383a;
      font-weight: 700;
    }}
    tr:last-child td {{ border-bottom: 0; }}
    td:last-child, th:last-child {{ border-right: 0; }}
    .footer {{
      color: var(--muted);
      font-size: 12px;
      margin-top: 22px;
      text-align: right;
    }}
    @media (max-width: 960px) {{
      .page {{ display: block; }}
      aside {{ position: static; height: auto; border-right: 0; border-bottom: 1px solid var(--line); }}
      nav {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 18px; }}
      main {{ padding: 28px 18px 48px; }}
      .hero, article {{ padding: 30px 24px; }}
      .cards {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    }}
    @media (max-width: 560px) {{
      nav {{ grid-template-columns: 1fr; }}
      .cards {{ grid-template-columns: 1fr; }}
      .hero, article {{ padding: 26px 18px; }}
    }}
    @media print {{
      body {{ background: #fff; }}
      aside {{ display: none; }}
      .page {{ display: block; }}
      main {{ max-width: none; padding: 0; }}
      .hero, article, .card {{ box-shadow: none; }}
      h2 {{ break-after: avoid; }}
      pre, table {{ break-inside: avoid; }}
    }}
  </style>
</head>
<body>
  <div class="page">
    <aside>
      <div class="brand">Audio AI Workflow</div>
      <div class="toc-title">AI 音频研发流程与 Skill 沉淀汇报</div>
      <nav>{toc_html}</nav>
    </aside>
    <main>
      <section class="hero">
        <div class="eyebrow">2026-05-25 / ProjectEF</div>
        <h1>AI 音频研发流程与 Skill 沉淀汇报</h1>
        <p class="subtitle">把音频从被动接收需求的下游环节，升级为由 AI Agent 辅助的主动研发、风险检测和执行 QA 中枢。</p>
        <div class="meta">
          <span class="pill">Wwise / Unity / P4</span>
          <span class="pill">需求挖掘</span>
          <span class="pill">Ready 判断</span>
          <span class="pill">工程 QA</span>
        </div>
      </section>

      <section class="cards" aria-label="关键结论">
        <div class="card"><b>7</b><span>新增并安装的通用音频生产 Skill，覆盖需求、预算、QA、版本控制。</span></div>
        <div class="card"><b>4</b><span>已接入的基础协作 Skill：Wwise 审计、资源审计、断联恢复、长任务续跑。</span></div>
        <div class="card"><b>SABC</b><span>统一音频优先级和资源预算口径，减少需求漏判和临时堆积。</span></div>
        <div class="card"><b>QA</b><span>所有工程修改遵循改前方案、改后检查、风险留痕的安全流程。</span></div>
      </section>

      <article>
        {content}
      </article>
      <div class="footer">Generated locally from Markdown. No Wwise, Unity, or P4 project files were modified.</div>
    </main>
  </div>
</body>
</html>
"""


def main() -> None:
    markdown = SRC.read_text(encoding="utf-8-sig")
    content, toc = md_to_html(markdown)
    OUT.write_text(build_html(content, toc), encoding="utf-8-sig")
    print(OUT)


if __name__ == "__main__":
    main()
