#!/usr/bin/env python3
import csv
import html
import re
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "EF音频需求清单_SABC_图表版_2026-05-27.html"

SYSTEM_LABELS = {
    "01": "全局",
    "02": "角色",
    "03": "3C",
    "04": "战斗/钓法/鱼",
    "05": "关卡/世界",
    "06": "物品/经济",
    "07": "目标指引",
    "08": "社交",
    "09": "通用/UI",
    "10": "商业化",
    "全局": "全局",
    "非游戏内": "非游戏内",
}

LEVEL_META = {
    "S": {
        "title": "核心体验",
        "definition": "一定要精细设计，对钓鱼游戏体验有重大影响",
        "reason": "直接影响抛竿、等口、识别咬口、刺鱼、搏鱼、上鱼和关键混音感知。",
        "tone": "red",
    },
    "A": {
        "title": "必不可少",
        "definition": "精细设计，必不可少",
        "reason": "支撑装备差异、鱼种个性、钓场沉浸、重大反馈、多人与主要 UI。",
        "tone": "amber",
    },
    "B": {
        "title": "后置增强",
        "definition": "较为重要，但优先级滞后",
        "reason": "提升完整度、便利性和内容厚度，但不直接决定核心钓鱼判断。",
        "tone": "blue",
    },
    "C": {
        "title": "可砍添头",
        "definition": "可有可无，添头",
        "reason": "多为轻量 UI、低价值提示或装饰性声音，应严格控量避免噪声。",
        "tone": "gray",
    },
}


def esc(value) -> str:
    return html.escape(str(value or ""), quote=True)


def short(value: str, limit: int = 84) -> str:
    value = re.sub(r"\s+", " ", value or "").strip()
    return value if len(value) <= limit else value[: limit - 1] + "…"


def find_sources():
    md = [p for p in ROOT.iterdir() if p.is_file() and p.name.startswith("EF") and "SABC" in p.name and p.suffix == ".md"][0]
    csv_path = [p for p in ROOT.iterdir() if p.is_file() and p.name.startswith("EF") and p.suffix == ".csv"][0]
    budget = [p for p in ROOT.iterdir() if p.is_file() and p.name.startswith("EF") and "资源总量" in p.name and p.suffix == ".md"][0]
    return md, csv_path, budget


def parse_markdown(md_path: Path):
    text = md_path.read_text(encoding="utf-8")
    s_items = []
    s_matches = list(re.finditer(r"^### (S-\d+)\s+(.+)$", text, re.M))
    section4 = text.find("## 4.")
    for index, match in enumerate(s_matches):
        start = match.end()
        end = s_matches[index + 1].start() if index + 1 < len(s_matches) else section4
        block = text[start:end]
        table = {}
        for line in block.splitlines():
            if not line.startswith("|") or line.startswith("|---"):
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) >= 2 and cells[0] != "维度":
                table[cells[0]] = cells[1]
        s_items.append({
            "id": match.group(1),
            "title": match.group(2).strip(),
            "system": table.get("系统", ""),
            "type": table.get("类型", ""),
            "reason": table.get("分级理由", ""),
            "design": table.get("设计方案", ""),
            "wwise": table.get("Wwise 建议", ""),
        })

    a_items = []
    for match in re.finditer(r"^\|\s*(A-\d+)\s*\|(.+)$", text, re.M):
        cells = [c.strip() for c in match.group(0).strip("|").split("|")]
        if len(cells) >= 6:
            a_items.append({
                "id": cells[0],
                "title": cells[1],
                "system": cells[2],
                "type": cells[3],
                "reason": cells[4],
                "design": cells[5],
            })

    def parse_table_between(start_marker: str, end_marker: str, header_first: str):
        start = text.find(start_marker)
        end = text.find(end_marker)
        section = text[start:end] if start != -1 and end != -1 else ""
        rows = []
        for line in section.splitlines():
            if not line.startswith("|") or line.startswith("|---"):
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            if not cells or cells[0] == header_first:
                continue
            rows.append(cells)
        return rows

    b_rows = parse_table_between("## 5.", "## 6.", "分组")
    c_rows = parse_table_between("## 6.", "## 7.", "需求")
    return text, s_items, a_items, b_rows, c_rows


def parse_resources(csv_path: Path):
    rows = list(csv.DictReader(csv_path.open(encoding="utf-8-sig")))
    keys = list(rows[0].keys())
    key = {
        "id": keys[0],
        "level": keys[1],
        "system": keys[2],
        "type": keys[3],
        "scheme": keys[4],
        "resource": keys[5],
        "raw": keys[6],
        "samples": keys[7],
        "wwise": keys[8],
        "unity": keys[9],
        "mix": keys[10],
        "days": keys[11],
        "notes": keys[12],
    }
    return rows, key


def split_field(value: str):
    return [part.strip() for part in (value or "").replace("／", "/").split("/") if part.strip()]


def num(value):
    try:
        return float(value or 0)
    except Exception:
        return 0.0


def build_stats(rows, key):
    by_level = {}
    for level in ["S", "A", "B", "C"]:
        items = [r for r in rows if r[key["level"]] == level]
        by_level[level] = {
            "packages": len(items),
            "raw": sum(num(r[key["raw"]]) for r in items),
            "days": sum(num(r[key["days"]]) for r in items),
            "wwise": sum(num(r[key["wwise"]]) for r in items),
            "unity": sum(num(r[key["unity"]]) for r in items),
        }
    system_counts = Counter()
    type_counts = Counter()
    resource_counts = Counter()
    for row in rows:
        for item in split_field(row[key["system"]]):
            system_counts[item] += 1
        for item in split_field(row[key["type"]]):
            type_counts[item] += 1
        for item in split_field(row[key["resource"]]):
            resource_counts[item] += 1
    return by_level, system_counts, type_counts, resource_counts


def bar_rows(counter, labels=None, limit=12):
    labels = labels or {}
    if not counter:
        return ""
    max_value = max(counter.values())
    rows = []
    for name, value in counter.most_common(limit):
        pct = int(value / max_value * 100) if max_value else 0
        rows.append(
            f'<div class="bar-row"><b>{esc(labels.get(name, name))}</b>'
            f'<div class="bar-track"><span style="width:{pct}%"></span></div>'
            f'<em>{value}</em></div>'
        )
    return "\n".join(rows)


def level_cards(concept_counts, by_level):
    cards = []
    for level in ["S", "A", "B", "C"]:
        meta = LEVEL_META[level]
        stats = by_level[level]
        cards.append(f"""
          <div class="level-card {meta['tone']}">
            <div class="level-mark">{level}</div>
            <h3>{esc(meta['title'])}</h3>
            <p>{esc(meta['definition'])}</p>
            <div class="level-metrics">
              <span><b>{concept_counts[level]}</b>需求项</span>
              <span><b>{int(stats['raw'])}</b>素材</span>
              <span><b>{stats['days']:.1f}</b>人日</span>
            </div>
          </div>
        """)
    return "\n".join(cards)


def budget_bars(by_level, field, suffix=""):
    max_value = max(v[field] for v in by_level.values()) or 1
    rows = []
    for level in ["S", "A", "B", "C"]:
        value = by_level[level][field]
        pct = int(value / max_value * 100)
        rows.append(
            f'<div class="budget-row"><strong>{level}</strong>'
            f'<div class="budget-track {LEVEL_META[level]["tone"]}"><span style="width:{pct}%"></span></div>'
            f'<em>{value:.1f}{suffix}</em></div>'
        )
    return "\n".join(rows)


def s_cards(s_items):
    return "\n".join(f"""
      <details class="s-card">
        <summary><span>{esc(item['id'])}</span>{esc(item['title'])}</summary>
        <dl>
          <dt>系统</dt><dd>{esc(item['system'])}</dd>
          <dt>类型</dt><dd>{esc(item['type'])}</dd>
          <dt>理由</dt><dd>{esc(short(item['reason'], 180))}</dd>
          <dt>Wwise</dt><dd>{esc(short(item['wwise'], 180))}</dd>
        </dl>
      </details>
    """ for item in s_items)


def compact_table(rows, columns, row_mapper, empty="-"):
    body = []
    for row in rows:
        cells = row_mapper(row)
        body.append("<tr>" + "".join(f"<td>{esc(cell)}</td>" for cell in cells) + "</tr>")
    if not body:
        body.append(f"<tr><td colspan='{len(columns)}'>{esc(empty)}</td></tr>")
    return f"""
      <div class="table-wrap">
        <table>
          <thead><tr>{''.join(f'<th>{esc(col)}</th>' for col in columns)}</tr></thead>
          <tbody>{''.join(body)}</tbody>
        </table>
      </div>
    """


def generate():
    md_path, csv_path, budget_path = find_sources()
    _text, s_items, a_items, b_rows, c_rows = parse_markdown(md_path)
    resource_rows, key = parse_resources(csv_path)
    by_level, system_counts, type_counts, resource_counts = build_stats(resource_rows, key)

    concept_counts = {
        "S": len(s_items),
        "A": len(a_items),
        "B": len(b_rows),
        "C": len(c_rows),
    }
    total_concepts = sum(concept_counts.values())
    total_raw = sum(v["raw"] for v in by_level.values())
    total_days = sum(v["days"] for v in by_level.values())
    total_wwise = sum(v["wwise"] for v in by_level.values())
    total_unity = sum(v["unity"] for v in by_level.values())

    a_table = compact_table(
        a_items,
        ["ID", "需求", "系统", "类型", "设计摘要"],
        lambda item: [item["id"], item["title"], item["system"], item["type"], short(item["design"], 80)],
    )
    b_table = compact_table(
        b_rows,
        ["分组", "需求", "系统", "类型", "后置理由"],
        lambda row: [row[0], row[1], row[2], row[3], short(row[4], 84)],
    )
    c_table = compact_table(
        c_rows,
        ["需求", "系统", "类型", "C 级理由"],
        lambda row: [row[0], row[1], row[2], short(row[3], 84)],
    )

    html_text = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>EF 音频需求清单 SABC｜图表版</title>
  <style>
    :root {{
      --bg: #f7f5f0;
      --paper: #fffdf8;
      --ink: #202629;
      --muted: #6c7478;
      --line: #ded7c9;
      --green: #526f67;
      --red: #a85f56;
      --amber: #a67b45;
      --blue: #536f86;
      --gray: #6f7375;
      --soft-red: #efe0dc;
      --soft-amber: #efe7d6;
      --soft-blue: #e5ebef;
      --soft-green: #e4ebe6;
      --soft-gray: #ecebea;
      --shadow: 0 22px 70px rgba(32, 38, 41, .08);
      --radius: 8px;
    }}
    * {{ box-sizing: border-box; }}
    html {{ scroll-behavior: smooth; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: "Microsoft YaHei", "PingFang SC", "Segoe UI", Arial, sans-serif;
      line-height: 1.58;
      letter-spacing: 0;
    }}
    .shell {{ display: grid; grid-template-columns: 260px minmax(0, 1fr); min-height: 100vh; }}
    aside {{
      position: sticky;
      top: 0;
      height: 100vh;
      padding: 34px 26px;
      border-right: 1px solid var(--line);
      background: rgba(255,253,248,.84);
      overflow: auto;
    }}
    .toc-kicker {{ color: var(--green); font-size: 12px; font-weight: 800; text-transform: uppercase; margin-bottom: 12px; }}
    .toc-title {{ font-size: 19px; font-weight: 800; line-height: 1.28; margin-bottom: 26px; }}
    nav a {{
      display: block;
      padding: 9px 0;
      border-bottom: 1px solid rgba(222,215,201,.72);
      color: var(--muted);
      font-size: 13px;
      text-decoration: none;
    }}
    nav a:hover {{ color: var(--ink); }}
    .toc-note {{ margin-top: 24px; padding-top: 18px; border-top: 1px solid var(--line); color: var(--muted); font-size: 12px; }}
    main {{ max-width: 1280px; width: 100%; margin: 0 auto; padding: 42px 48px 74px; }}
    section {{ scroll-margin-top: 22px; }}
    .hero {{
      position: relative;
      overflow: hidden;
      padding: 52px;
      background: var(--paper);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
    }}
    .hero::after {{
      content: "";
      position: absolute;
      right: -120px;
      top: -120px;
      width: 390px;
      height: 390px;
      border: 1px solid rgba(82,111,103,.22);
      border-radius: 50%;
    }}
    .eyebrow {{ color: var(--green); font-size: 13px; font-weight: 800; text-transform: uppercase; margin-bottom: 18px; }}
    h1 {{ max-width: 960px; margin: 0 0 18px; font-size: clamp(36px, 4.8vw, 66px); line-height: 1.06; letter-spacing: 0; }}
    .subtitle {{ max-width: 860px; margin: 0; color: var(--muted); font-size: 18px; }}
    .meta-row {{ display: flex; flex-wrap: wrap; gap: 10px; margin-top: 30px; }}
    .tag {{
      display: inline-flex;
      align-items: center;
      min-height: 32px;
      padding: 7px 11px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: #f0ece3;
      color: #414a4d;
      font-size: 12px;
    }}
    .stats {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; margin: 18px 0 28px; }}
    .stat {{ min-height: 138px; padding: 22px; background: var(--paper); border: 1px solid var(--line); border-radius: var(--radius); }}
    .stat strong {{ display: block; margin-bottom: 10px; color: var(--green); font-size: 34px; line-height: 1; }}
    .stat span {{ color: var(--muted); font-size: 13px; }}
    .panel {{ margin-top: 20px; padding: 38px 0 14px; border-top: 1px solid var(--line); }}
    .section-head {{ display: grid; grid-template-columns: minmax(0,1fr) auto; gap: 24px; align-items: end; margin-bottom: 24px; }}
    h2 {{ margin: 0; font-size: clamp(25px, 2.7vw, 38px); line-height: 1.16; letter-spacing: 0; }}
    .section-head p {{ max-width: 720px; margin: 10px 0 0; color: var(--muted); font-size: 15px; }}
    .label {{ padding: 8px 12px; background: var(--soft-green); border: 1px solid #cbd9d2; border-radius: 999px; color: var(--green); font-size: 12px; font-weight: 800; white-space: nowrap; }}
    .level-grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; }}
    .level-card {{ min-height: 214px; padding: 20px; border: 1px solid var(--line); border-radius: var(--radius); background: #fffefa; }}
    .level-card.red {{ background: var(--soft-red); border-color: #dfc5c0; }}
    .level-card.amber {{ background: var(--soft-amber); border-color: #dfceb1; }}
    .level-card.blue {{ background: var(--soft-blue); border-color: #c9d5dc; }}
    .level-card.gray {{ background: var(--soft-gray); border-color: #d6d3ce; }}
    .level-mark {{ width: 44px; height: 44px; display: grid; place-items: center; margin-bottom: 14px; border-radius: 50%; background: #25302f; color: #fff; font-weight: 900; font-size: 22px; }}
    .level-card h3 {{ margin: 0 0 8px; font-size: 20px; }}
    .level-card p {{ margin: 0 0 16px; color: #4c5658; font-size: 13px; }}
    .level-metrics {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }}
    .level-metrics span {{ padding: 8px; background: rgba(255,255,255,.54); border: 1px solid rgba(222,215,201,.8); border-radius: 6px; color: var(--muted); font-size: 11px; }}
    .level-metrics b {{ display: block; color: var(--ink); font-size: 18px; }}
    .pyramid {{ display: grid; gap: 10px; margin-top: 18px; }}
    .pyramid-row {{ display: grid; grid-template-columns: 88px 1fr 150px; gap: 12px; align-items: center; padding: 14px; border: 1px solid var(--line); background: #fffefa; border-radius: var(--radius); }}
    .pyramid-row b {{ font-size: 22px; }}
    .pyramid-row p {{ margin: 0; color: var(--muted); font-size: 13px; }}
    .bar-track, .budget-track {{ height: 12px; overflow: hidden; border-radius: 99px; background: #ece6dc; }}
    .bar-track span, .budget-track span {{ display: block; height: 100%; border-radius: inherit; background: var(--green); }}
    .budget-track.red span {{ background: var(--red); }}
    .budget-track.amber span {{ background: var(--amber); }}
    .budget-track.blue span {{ background: var(--blue); }}
    .budget-track.gray span {{ background: var(--gray); }}
    .chart-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; }}
    .chart-panel {{ padding: 20px; border: 1px solid var(--line); border-radius: var(--radius); background: #fffefa; }}
    .chart-panel h3 {{ margin: 0 0 14px; font-size: 18px; }}
    .bar-row {{ display: grid; grid-template-columns: 128px 1fr 36px; gap: 10px; align-items: center; margin: 10px 0; }}
    .bar-row b {{ font-size: 13px; }}
    .bar-row em {{ color: var(--muted); font-style: normal; font-size: 12px; text-align: right; }}
    .loop {{
      display: grid;
      grid-template-columns: repeat(9, minmax(112px, 1fr));
      gap: 8px;
      overflow: auto;
      padding-bottom: 8px;
    }}
    .loop-step {{ position: relative; min-height: 134px; padding: 15px 13px; border: 1px solid var(--line); border-radius: var(--radius); background: #fffefa; }}
    .loop-step:not(:last-child)::after {{ content: ""; position: absolute; top: 50%; right: -8px; width: 8px; height: 1px; background: var(--line); }}
    .loop-step b {{ display: block; margin-bottom: 8px; color: var(--green); font-size: 14px; }}
    .loop-step span {{ color: var(--muted); font-size: 12px; }}
    .budget-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; }}
    .budget-row {{ display: grid; grid-template-columns: 42px 1fr 88px; gap: 10px; align-items: center; margin: 12px 0; }}
    .budget-row strong {{ font-size: 18px; }}
    .budget-row em {{ color: var(--muted); font-style: normal; text-align: right; font-size: 12px; }}
    .big-number-grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin-top: 18px; }}
    .big-number {{ padding: 18px; border: 1px solid var(--line); border-radius: var(--radius); background: var(--paper); }}
    .big-number b {{ display: block; color: var(--green); font-size: 30px; line-height: 1; margin-bottom: 8px; }}
    .big-number span {{ color: var(--muted); font-size: 12px; }}
    .s-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }}
    details.s-card {{ border: 1px solid var(--line); border-radius: var(--radius); background: #fffefa; }}
    details.s-card summary {{ cursor: pointer; padding: 14px 16px; font-weight: 800; }}
    details.s-card summary span {{ display: inline-flex; min-width: 48px; color: var(--red); }}
    details.s-card dl {{ display: grid; grid-template-columns: 70px 1fr; gap: 8px 12px; margin: 0; padding: 0 16px 16px; }}
    details.s-card dt {{ color: var(--muted); font-size: 12px; }}
    details.s-card dd {{ margin: 0; font-size: 13px; }}
    .table-wrap {{ overflow: auto; border: 1px solid var(--line); border-radius: var(--radius); background: #fffefa; }}
    table {{ width: 100%; min-width: 940px; border-collapse: collapse; }}
    th, td {{ padding: 11px 12px; border-right: 1px solid var(--line); border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; font-size: 13px; }}
    th {{ background: #ebe5d9; color: #3c4548; font-size: 12px; }}
    tr:last-child td {{ border-bottom: 0; }}
    th:last-child, td:last-child {{ border-right: 0; }}
    .cutline {{ display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }}
    .note {{ margin-top: 16px; padding: 18px; border-radius: var(--radius); background: #25302f; color: #f8f3e9; font-size: 16px; line-height: 1.55; font-weight: 800; }}
    footer {{ margin-top: 26px; color: var(--muted); font-size: 12px; text-align: center; }}
    @media (max-width: 1080px) {{
      .shell {{ grid-template-columns: 1fr; }}
      aside {{ position: static; height: auto; border-right: 0; border-bottom: 1px solid var(--line); }}
      nav {{ display: flex; flex-wrap: wrap; gap: 8px; }}
      nav a {{ border: 1px solid var(--line); border-radius: 999px; padding: 7px 10px; background: var(--paper); }}
      main {{ padding: 28px 20px 52px; }}
      .stats, .level-grid, .chart-grid, .budget-grid, .s-grid, .cutline, .big-number-grid {{ grid-template-columns: 1fr 1fr; }}
      .loop {{ grid-template-columns: repeat(5, minmax(120px, 1fr)); }}
    }}
    @media (max-width: 680px) {{
      .hero {{ padding: 24px; }}
      .panel {{ padding: 30px 0 10px; }}
      .stats, .level-grid, .chart-grid, .budget-grid, .s-grid, .cutline, .big-number-grid {{ grid-template-columns: 1fr; }}
      .section-head {{ grid-template-columns: 1fr; }}
      .pyramid-row {{ grid-template-columns: 1fr; }}
      .loop {{ grid-template-columns: repeat(9, 132px); }}
      .bar-row {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <div class="shell">
    <aside>
      <div class="toc-kicker">SABC Visual</div>
      <div class="toc-title">EF 钓鱼项目音频需求清单</div>
      <nav>
        <a href="#overview">总览</a>
        <a href="#principle">SABC 分级</a>
        <a href="#dimensions">双维度分类</a>
        <a href="#core-loop">核心闭环</a>
        <a href="#budget">资源与工时</a>
        <a href="#s-level">S 级方案</a>
        <a href="#a-level">A 级清单</a>
        <a href="#bc-line">B/C 砍线</a>
        <a href="#source">资料口径</a>
      </nav>
      <div class="toc-note">
        版本：{date.today().isoformat()}<br />
        数据源：2026-05-21 SABC 清单、资源总量表、资源明细 CSV。
      </div>
    </aside>
    <main>
      <section class="hero" id="overview">
        <div class="eyebrow">Project EF Fishing Audio Requirement Map</div>
        <h1>SABC 音频需求分析图表版</h1>
        <p class="subtitle">
          这份图表把原始 SABC 需求清单转换成可汇报、可预算、可制作排期的结构化视图：
          一眼看清核心钓鱼闭环、系统覆盖、音效类型、资源量、人日和 B/C 可砍范围。
        </p>
        <div class="meta-row">
          <span class="tag">S=核心体验</span>
          <span class="tag">A=必不可少</span>
          <span class="tag">B=后置增强</span>
          <span class="tag">C=可砍添头</span>
          <span class="tag">Wwise / Unity / Mix</span>
        </div>
      </section>

      <div class="stats">
        <div class="stat"><strong>{total_concepts}</strong><span>概念需求项：S/A 为逐项方案，B/C 为后置与可砍池。</span></div>
        <div class="stat"><strong>{int(total_raw)}</strong><span>推荐原始素材量，覆盖音乐、音效、环境、UI、语音和混音资产。</span></div>
        <div class="stat"><strong>{total_days:.1f}</strong><span>标准音频小队估算人日，含素材、Wwise、Unity、混音和验收。</span></div>
        <div class="stat"><strong>{int(total_wwise + total_unity)}</strong><span>Wwise 对象与 Unity 配置触点总量估算。</span></div>
      </div>

      <section class="panel" id="principle">
        <div class="section-head">
          <div>
            <h2>SABC 分级原则</h2>
            <p>S/A 的边界不是声音数量，而是是否影响玩家判断、核心循环可信度和长期系统差异。</p>
          </div>
          <div class="label">Priority Logic</div>
        </div>
        <div class="level-grid">
          {level_cards(concept_counts, by_level)}
        </div>
        <div class="pyramid">
          <div class="pyramid-row"><b>S</b><p>{esc(LEVEL_META['S']['reason'])}</p><div class="bar-track"><span style="width:100%"></span></div></div>
          <div class="pyramid-row"><b>A</b><p>{esc(LEVEL_META['A']['reason'])}</p><div class="bar-track"><span style="width:82%"></span></div></div>
          <div class="pyramid-row"><b>B</b><p>{esc(LEVEL_META['B']['reason'])}</p><div class="bar-track"><span style="width:52%"></span></div></div>
          <div class="pyramid-row"><b>C</b><p>{esc(LEVEL_META['C']['reason'])}</p><div class="bar-track"><span style="width:28%"></span></div></div>
        </div>
      </section>

      <section class="panel" id="dimensions">
        <div class="section-head">
          <div>
            <h2>系统与音效类型覆盖</h2>
            <p>需求按“系统”和“音效类型”两条轴独立分类，避免只从功能或只从素材角度看问题。</p>
          </div>
          <div class="label">Two-Axis Map</div>
        </div>
        <div class="chart-grid">
          <div class="chart-panel">
            <h3>系统分布</h3>
            {bar_rows(system_counts, SYSTEM_LABELS)}
          </div>
          <div class="chart-panel">
            <h3>音效类型分布</h3>
            {bar_rows(type_counts)}
          </div>
        </div>
      </section>

      <section class="panel" id="core-loop">
        <div class="section-head">
          <div>
            <h2>S 级核心钓鱼闭环</h2>
            <p>S 级围绕玩家每一轮作钓的关键判断建立：动作要可信、状态要可听、风险要提前、奖励要成立。</p>
          </div>
          <div class="label">Core Loop</div>
        </div>
        <div class="loop">
          <div class="loop-step"><b>抛竿</b><span>S-1 力量、钓组、风向、入水可信度。</span></div>
          <div class="loop-step"><b>收线</b><span>S-2 速度、阻力、控饵节奏。</span></div>
          <div class="loop-step"><b>等口</b><span>S-6 漂相强弱、水流和鱼口信号。</span></div>
          <div class="loop-step"><b>咬口</b><span>S-3 真口、假口、截口、水面攻击。</span></div>
          <div class="loop-step"><b>刺鱼</b><span>S-14 拉力条、泄力、张力判断。</span></div>
          <div class="loop-step"><b>搏鱼</b><span>S-4 鱼状态机、鱼技能、疲劳。</span></div>
          <div class="loop-step"><b>风险</b><span>S-7 过载、断线、挂底、损坏预警。</span></div>
          <div class="loop-step"><b>上鱼</b><span>S-5/S-13 抄网、出水、奖励闭环。</span></div>
          <div class="loop-step"><b>环境/空间</b><span>S-10/S-15/S-16/S-17 水域、天气、混音、1P/3P/多人。</span></div>
        </div>
      </section>

      <section class="panel" id="budget">
        <div class="section-head">
          <div>
            <h2>资源总量与落地压力</h2>
            <p>资源预算以推荐制作量为主，B/C 已按生产包聚合，C 级作为可砍池单列。</p>
          </div>
          <div class="label">Budget</div>
        </div>
        <div class="budget-grid">
          <div class="chart-panel">
            <h3>原始素材量</h3>
            {budget_bars(by_level, 'raw', '')}
          </div>
          <div class="chart-panel">
            <h3>人日估算</h3>
            {budget_bars(by_level, 'days', 'd')}
          </div>
        </div>
        <div class="big-number-grid">
          <div class="big-number"><b>{int(total_wwise)}</b><span>Wwise 对象估算，含 Event、Container、Switch/State/RTPC、Bus 与 SoundBank 组织。</span></div>
          <div class="big-number"><b>{int(total_unity)}</b><span>Unity 配置触点估算，含触发点、配置字段、动画 Notify、状态机或表驱动映射。</span></div>
          <div class="big-number"><b>{by_level['C']['days']:.1f}d</b><span>C 级可砍人日池，适合在版本压力或噪声风险过高时整体压缩。</span></div>
        </div>
      </section>

      <section class="panel" id="s-level">
        <div class="section-head">
          <div>
            <h2>S 级完整方案索引</h2>
            <p>S 级必须精细设计，并且每项都应具备 Wwise、Unity、混音和验收路径。</p>
          </div>
          <div class="label">{len(s_items)} Items</div>
        </div>
        <div class="s-grid">
          {s_cards(s_items)}
        </div>
      </section>

      <section class="panel" id="a-level">
        <div class="section-head">
          <div>
            <h2>A 级必不可少清单</h2>
            <p>A 级决定长期可玩性和系统差异。它们可以排在 S 级之后，但不能从正式制作口径中消失。</p>
          </div>
          <div class="label">{len(a_items)} Items</div>
        </div>
        {a_table}
      </section>

      <section class="panel" id="bc-line">
        <div class="section-head">
          <div>
            <h2>B/C 后置与砍线</h2>
            <p>B 级是增强完整度的后置包，C 级是可砍池。它们的核心价值是帮助版本管理，而不是给音频无限扩量。</p>
          </div>
          <div class="label">Cut Line</div>
        </div>
        <div class="cutline">
          <div>
            <h3>B 级后置增强</h3>
            {b_table}
          </div>
          <div>
            <h3>C 级可砍添头</h3>
            {c_table}
          </div>
        </div>
        <div class="note">
          生产策略：S/A 建立体验骨架，B 作为版本后续增强，C 只在不干扰咬口、张力、环境和 UI 优先级时少量制作。
        </div>
      </section>

      <section class="panel" id="source">
        <div class="section-head">
          <div>
            <h2>资料口径</h2>
            <p>本图表是对已有 SABC 文档和资源明细的可视化，不重新改写需求结论。</p>
          </div>
          <div class="label">SourceGrade B</div>
        </div>
        <div class="chart-grid">
          <div class="chart-panel">
            <h3>使用文件</h3>
            <p>需求清单：{esc(md_path.name)}</p>
            <p>资源明细：{esc(csv_path.name)}</p>
            <p>资源总量：{esc(budget_path.name)}</p>
          </div>
          <div class="chart-panel">
            <h3>注意边界</h3>
            <p>这是需求与预算视图，不代表 Unity/Wwise 已全部实现，也不代表运行测试已覆盖全部场景。</p>
            <p>后续应与项目画像、Wwise 审计、Unity 静态审计和运行覆盖矩阵联动。</p>
          </div>
        </div>
      </section>

      <footer>
        Generated locally from SABC Markdown and resource CSV. No Wwise, Unity, or P4 files were modified.
      </footer>
    </main>
  </div>
</body>
</html>"""
    OUT.write_text(html_text, encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    generate()
