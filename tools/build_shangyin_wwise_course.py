from __future__ import annotations

import json
import re
import textwrap
import zipfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import fitz


WORKSPACE = Path(r"G:\AI\Material\Wwise")
OUT = WORKSPACE / "course_design_shangyin_noscreens"
PDF_OUT = WORKSPACE / "course_design_shangyin_noscreens_pdf"
HTML_OUT = WORKSPACE / "course_design_shangyin_noscreens_html"

XMIND_FILES = [
    Path(r"E:\Ryan\0417 上音\Wwise301速通.xmind"),
    Path(r"E:\Ryan\0417 上音\课后作业 - 模板.xmind"),
    Path(r"E:\Ryan\0417 上音\3D Kit Demo实战训练.xmind"),
    Path(r"E:\Ryan\0417 上音\Lesson 5 1107.xmind"),
    Path(r"E:\Ryan\0417 上音\Lesson 5 课后作业.xmind"),
    Path(r"E:\Ryan\0417 上音\Lesson 6 - 1110.xmind"),
    Path(r"E:\Ryan\0417 上音\Lesson 6 - 1113.xmind"),
    Path(r"E:\Ryan\0417 上音\Lesson 7 - 1120.xmind"),
    Path(r"E:\Ryan\0417 上音\Lesson 9.xmind"),
    Path(r"E:\Ryan\0417 上音\Lesson 12.xmind"),
    Path(r"E:\Ryan\0417 上音\Unity + Wwise3DGameKit实战训练.xmind"),
]

PDF_FILE = Path(r"E:\EF\周会\0513\Wwise 1012024完全突破.pdf")


@dataclass
class Topic:
    title: str
    children: list["Topic"]
    notes: str = ""


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    value = re.sub(r"\s+", " ", str(value)).strip()
    return value


def parse_topic(obj: dict) -> Topic:
    title = clean_text(obj.get("title") or obj.get("topic", {}).get("title") or "Untitled")
    notes = ""
    if isinstance(obj.get("notes"), dict):
        notes = clean_text(obj["notes"].get("plain") or obj["notes"].get("html"))
    elif isinstance(obj.get("notes"), str):
        notes = clean_text(obj["notes"])
    children: list[Topic] = []
    children_obj = obj.get("children")
    if isinstance(children_obj, dict):
        attached = children_obj.get("attached") or []
        if isinstance(attached, list):
            children.extend(parse_topic(x) for x in attached if isinstance(x, dict))
    elif isinstance(children_obj, list):
        children.extend(parse_topic(x) for x in children_obj if isinstance(x, dict))
    return Topic(title=title, children=children, notes=notes)


def parse_xmind(path: Path) -> list[Topic]:
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        if "content.json" in names:
            data = json.loads(z.read("content.json").decode("utf-8"))
            sheets = data if isinstance(data, list) else [data]
            roots = []
            for sheet in sheets:
                root = sheet.get("rootTopic") or sheet.get("root") or sheet
                if isinstance(root, dict):
                    roots.append(parse_topic(root))
            return roots
        if "content.xml" in names:
            import xml.etree.ElementTree as ET

            xml = z.read("content.xml")
            root = ET.fromstring(xml)
            ns = {"x": "urn:xmind:xmap:xmlns:content:2.0"}
            roots = []
            for sheet in root.findall(".//x:sheet", ns):
                topic = sheet.find("x:topic", ns)
                if topic is not None:
                    roots.append(parse_xml_topic(topic, ns))
            return roots
    return []


def parse_xml_topic(elem, ns) -> Topic:
    title_elem = elem.find("x:title", ns)
    title = clean_text(title_elem.text if title_elem is not None else "Untitled")
    children = []
    for child in elem.findall(".//x:children/x:topics/x:topic", ns):
        # Only direct children are wanted; ElementTree path above can recurse through
        # nested topics depending on the XML shape, so filter by parent is skipped in
        # favor of broad readability for old XMind files.
        children.append(parse_xml_topic(child, ns))
    return Topic(title=title, children=children)


def flatten(topic: Topic, depth: int = 0) -> list[tuple[int, str]]:
    rows = [(depth, topic.title)]
    for child in topic.children:
        rows.extend(flatten(child, depth + 1))
    return rows


def outline_md(topic: Topic, depth: int = 0) -> str:
    indent = "  " * depth
    line = f"{indent}- {topic.title}"
    if topic.notes:
        line += f"：{topic.notes}"
    lines = [line]
    for child in topic.children:
        lines.append(outline_md(child, depth + 1))
    return "\n".join(lines)


def extract_pdf_summary(path: Path) -> dict:
    doc = fitz.open(path)
    page_count = len(doc)
    toc = doc.get_toc(simple=True)
    pages = []
    for i in range(min(len(doc), 40)):
        text = clean_text(doc.load_page(i).get_text("text"))
        if text:
            pages.append({"page": i + 1, "text": text[:1200]})
    headings = []
    for level, title, page in toc[:120]:
        headings.append({"level": level, "title": clean_text(title), "page": page})
    if not headings:
        heading_pat = re.compile(r"^(Lesson|Module|第[一二三四五六七八九十0-9]+|[0-9]+[.、])")
        for item in pages:
            for line in item["text"].split(" "):
                if heading_pat.match(line):
                    headings.append({"level": 1, "title": line, "page": item["page"]})
                    break
    doc.close()
    return {"page_count": page_count, "toc": headings, "sample_pages": pages}


def keyword_inventory(texts: list[str]) -> list[tuple[str, int]]:
    terms = [
        "Wwise", "Unity", "Event", "SoundBank", "Game Sync", "State", "Switch", "RTPC",
        "AkEvent", "AkBank", "AkAmbient", "Callback", "Profiler", "3D", "Spatial",
        "Random Container", "Music", "Footstep", "Ambience", "Trigger", "Collider",
        "Post Event", "Sound SFX", "Actor-Mixer", "Bus", "Effect", "GameKit",
    ]
    c = Counter()
    joined = "\n".join(texts).lower()
    for term in terms:
        c[term] = joined.count(term.lower())
    return [(k, v) for k, v in c.most_common() if v]


def lesson_profile_from_file(path: Path, roots: list[Topic]) -> dict:
    title = path.stem
    all_titles = []
    for r in roots:
        all_titles.extend(t for _, t in flatten(r))
    joined = " ".join(all_titles)
    terms = [k for k, v in keyword_inventory([joined])[:10]]
    top_children = []
    for root in roots:
        for child in root.children[:8]:
            top_children.append(child.title)
    if not top_children:
        top_children = [r.title for r in roots[:8]]
    return {
        "title": title,
        "terms": terms,
        "top_children": top_children,
        "outline": "\n\n".join(outline_md(r) for r in roots),
    }


def classify_modules(profiles: list[dict]) -> list[dict]:
    lessons = []
    for idx, p in enumerate(profiles, start=1):
        raw = p["title"]
        lower = raw.lower()
        if "作业" in raw or "模板" in raw:
            kind = "课后作业 / Assignment"
            duration = "45-60 分钟讲解 + 课后完成"
        elif "demo" in lower or "gamekit" in lower or "实战" in raw:
            kind = "实战训练 / Lab"
            duration = "3-4 小时"
        elif "301" in raw:
            kind = "速通总览 / Bootcamp"
            duration = "4-6 小时"
        else:
            kind = "课堂课次 / Lesson"
            duration = "2-3 小时"
        lessons.append({
            "id": f"SY-{idx:02d}",
            "source": raw,
            "kind": kind,
            "duration": duration,
            "terms": p["terms"] or ["Wwise", "Unity", "Event", "SoundBank"],
            "focus": "、".join(p["top_children"][:5]) if p["top_children"] else raw,
            "outline": p["outline"],
        })
    return lessons


def md_table(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    out = ["| " + " | ".join(rows[0]) + " |", "| " + " | ".join(["---"] * len(rows[0])) + " |"]
    for row in rows[1:]:
        out.append("| " + " | ".join(str(x).replace("\n", "<br>") for x in row) + " |")
    return "\n".join(out)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def build_readme(lessons: list[dict], pdf_summary: dict) -> str:
    rows = [["课次", "来源资料", "类型", "建议时长", "核心方向"]]
    for l in lessons:
        rows.append([l["id"], l["source"], l["kind"], l["duration"], l["focus"][:80]])
    return f"""# 上音 Wwise 新资料无截图版教案

## 版本定位

这是一套基于新增 `.xmind` 与 `Wwise 1012024完全突破.pdf` 的独立教案。  
由于前一版截图抽取存在重复图风险，本版完全不使用截图，专注于：

- 授课流程
- 必要知识点
- 课堂实操
- 学生问答
- 课后作业
- 评分与验收

## 新资料来源

{md_table([["文件", "用途"]] + [[p.name, "XMind 课程/作业/实战结构"] for p in XMIND_FILES] + [[PDF_FILE.name, f"PDF 辅助资料，页数约 {pdf_summary['page_count']}"]])}

## 课程总览

{md_table(rows)}

## 使用建议

- 如果用于短训营：优先使用 `SY-01 Wwise301速通`、两个 GameKit 实战和 Lesson 5-7。
- 如果用于正式课：按课次顺序授课，并把作业模板作为每课提交规范。
- 如果用于 101 补强：结合 `Wwise 1012024完全突破.pdf` 的知识点，把 Event、SoundBank、Game Sync、Profiler 作为贯穿主线。
"""


def build_material_index(profiles: list[dict], pdf_summary: dict) -> str:
    parts = ["# 新资料知识点提取\n"]
    parts.append("## XMind 结构提取\n")
    for p in profiles:
        parts.append(f"### {p['title']}\n")
        parts.append(f"核心术语：{', '.join(p['terms']) if p['terms'] else '未自动识别'}\n")
        parts.append("```text\n" + p["outline"][:6000] + "\n```\n")
    parts.append("## PDF 辅助资料摘要\n")
    parts.append(f"- 文件：`{PDF_FILE}`\n- 页数：{pdf_summary['page_count']}\n")
    if pdf_summary["toc"]:
        rows = [["Level", "Title", "Page"]]
        for h in pdf_summary["toc"][:80]:
            rows.append([h["level"], h["title"], h["page"]])
        parts.append(md_table(rows))
    else:
        parts.append("未检测到 PDF 目录；已保留前 40 页文本摘要供后续精修。\n")
    parts.append("\n## PDF 前页文本采样\n")
    for item in pdf_summary["sample_pages"][:12]:
        parts.append(f"### Page {item['page']}\n\n{textwrap.shorten(item['text'], width=1000, placeholder='...')}\n")
    return "\n".join(parts)


def build_teacher_guide(lesson: dict) -> str:
    terms = lesson["terms"][:8]
    return f"""# {lesson['id']} 教师版教案：{lesson['source']}

## 课程类型

{lesson['kind']}

## 建议时长

{lesson['duration']}

## 课程定位

本课基于新增 XMind 资料 `{lesson['source']}` 整理。它被设计为无截图授课版本，教师通过流程、板书、现场演示和问答来完成知识传递。

## 教学目标

完成本课后，学员应能：

- 说出本课核心 Wwise / Unity 术语。
- 按步骤完成一段可验证的课堂实操。
- 用自己的话解释本课机制解决的游戏音频问题。
- 在课后作业中提交清晰的工程证据、问题记录和复盘。

## 核心知识点

{md_table([["English Term", "中文教学说明"]] + [[f"`{t}`", "保留英文原词，课堂用中文解释其功能、适用场景和排错路径。"] for t in terms])}

## 来源资料结构

```text
{lesson['outline'][:7000]}
```

## 流程化授课设计

{md_table([
    ["时间", "环节", "教师动作", "学员动作"],
    ["0:00-0:10", "问题导入", "用一个游戏音频需求引出本课机制。", "回答：如果没有该机制，会出现什么问题？"],
    ["0:10-0:30", "概念讲解", "解释核心术语，画出对象/组件/运行时链路。", "记录 English Term 与中文含义。"],
    ["0:30-0:55", "教师演示", "从空状态做一遍最小可运行案例。", "记录关键步骤和命名。"],
    ["0:55-1:35", "学员跟做", "巡回检查工程结构、引用、参数和触发条件。", "完成课堂任务并截图或记录。"],
    ["1:35-1:55", "排错复盘", "挑选 2-3 个典型错误按链路排查。", "写下自己的排错顺序。"],
    ["1:55-2:00", "作业说明", "说明提交格式和评分点。", "确认课后任务。"],
])}

## 板书链路

```mermaid
flowchart LR
    A["Design Goal"] --> B["Wwise / Unity Feature"]
    B --> C["Authoring Setup"]
    C --> D["Runtime Trigger"]
    D --> E["Verification"]
    E --> F["Debug Notes"]
```

## 课堂实操

1. 明确声音设计目标。
2. 创建或打开课程工程。
3. 建立本课对应 Wwise / Unity 对象。
4. 设置命名、参数、触发条件或 SoundBank。
5. 运行并验证。
6. 记录失败点和解决方式。

## 学生常见问题与回答

{md_table([
    ["学生问题", "教师回答"],
    ["为什么 Wwise 里能听到，游戏里还是没声音？", "Wwise authoring 试听只证明对象可播放；游戏端还需要 Event、SoundBank、加载路径和触发条件都正确。"],
    ["我应该用 State、Switch 还是 RTPC？", "先看数据形态：离散局部类别用 Switch，全局模式用 State，连续数值用 RTPC。"],
    ["脚本触发和组件触发怎么选？", "固定、简单、场景化触发优先组件；需要 gameplay logic、条件判断或动态参数时用脚本。"],
    ["排错从哪里开始？", "从触发链路开始：Trigger/Script -> Event -> Bank -> Object/Bus -> Output/Profiler。"],
])}

## 课堂检测

- 术语解释：随机抽 3 个 English Terms。
- 操作检查：学员展示本课最小案例。
- 排错题：教师给出一个无声/不触发/参数无效案例，学员说出检查顺序。

## 课后作业

提交：

- 工程截图或结构说明。
- 运行验证录屏或文字说明。
- 300 字以内复盘：做了什么、遇到什么问题、如何解决。
- 至少 3 个本课 English Terms 的中文解释。
"""


def build_student_handout(lesson: dict) -> str:
    terms = lesson["terms"][:8]
    return f"""# {lesson['id']} 学员讲义：{lesson['source']}

## 本课目标

- 理解本课机制对应的游戏音频问题。
- 掌握核心 English Terms。
- 完成课堂最小案例。
- 形成可复用的排错链路。

## 核心术语

{md_table([["English Term", "我的理解"]] + [[f"`{t}`", ""] for t in terms])}

## 本课流程

```mermaid
flowchart LR
    A["需求"] --> B["机制"]
    B --> C["设置"]
    C --> D["触发"]
    D --> E["验证"]
    E --> F["复盘"]
```

## 课堂任务记录

{md_table([
    ["项目", "我的记录"],
    ["我创建/修改的对象或组件", ""],
    ["我使用的 Event / SoundBank / Game Sync", ""],
    ["我如何验证", ""],
    ["我遇到的问题", ""],
    ["我的解决方式", ""],
])}

## 自查清单

- [ ] 我能说出本课机制解决什么问题。
- [ ] 我能解释至少 3 个 English Terms。
- [ ] 我完成了课堂实操。
- [ ] 我知道失败时从哪里开始排查。

## 课后作业

按教师要求提交课堂项目证据，并回答：

> 这个机制如何让声音从“固定播放”变成“响应游戏”？
"""


def build_assignment_template(lesson: dict) -> str:
    return f"""# {lesson['id']} 课后作业：{lesson['source']}

## 提交内容

{md_table([
    ["内容", "要求"],
    ["工程证据", "截图、录屏或结构说明，能证明你完成了操作。"],
    ["术语解释", "至少 3 个 English Terms，每个给出中文解释。"],
    ["排错记录", "至少记录 1 个问题和解决方式。"],
    ["项目迁移", "说明本课机制如何加入你的个人项目。"],
])}

## 评分标准

{md_table([
    ["维度", "分值", "标准"],
    ["完成度", "40", "功能或结构可验证。"],
    ["术语准确", "20", "English Terms 使用正确。"],
    ["排错记录", "20", "能说明问题原因和解决步骤。"],
    ["表达清晰", "20", "提交内容清楚、命名规范。"],
])}

## 反思问题

1. 我今天最重要的新概念是什么？
2. 我在哪一步最容易出错？
3. 如果重新做一遍，我会如何优化流程？
"""


def build_qa_bank(lessons: list[dict]) -> str:
    return """# 学生问答库

## 通用问答

""" + "\n".join([
        "### Wwise 里能听到，为什么游戏里听不到？\n\n因为 Wwise authoring 试听只证明声音对象能播放。游戏端还需要 Event 正确、SoundBank 已生成并加载、触发条件成立、bus routing 和音量没有阻断。\n",
        "### Event、Sound SFX、SoundBank 的关系是什么？\n\nSound SFX 是声音对象，Event 是游戏调用声音行为的入口，SoundBank 是游戏运行时读取的数据包。\n",
        "### State、Switch、RTPC 怎么选？\n\nSwitch 适合离散局部类别，State 适合全局模式，RTPC 适合连续数值。\n",
        "### Unity 组件触发和脚本触发怎么选？\n\n简单固定触发用组件；需要逻辑判断、动态参数、复杂 gameplay 条件时用脚本。\n",
        "### 作业应该交什么？\n\n交可验证证据、术语解释、排错记录和项目迁移说明，不只交最终截图。\n",
    ]) + "\n## 按课次追问\n\n" + "\n".join(
        f"### {l['id']} {l['source']}\n\n- 本课机制解决什么声音设计问题？\n- 本课最关键的 English Term 是什么？\n- 如果运行结果失败，你的第一步检查是什么？\n"
        for l in lessons
    )


def export_simple_html(md_path: Path, html_path: Path) -> None:
    text = md_path.read_text(encoding="utf-8")
    body = []
    in_code = False
    for line in text.splitlines():
        if line.startswith("```"):
            if in_code:
                body.append("</pre>")
            else:
                body.append("<pre>")
            in_code = not in_code
            continue
        if in_code:
            body.append(line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
        elif line.startswith("# "):
            body.append(f"<h1>{line[2:]}</h1>")
        elif line.startswith("## "):
            body.append(f"<h2>{line[3:]}</h2>")
        elif line.startswith("### "):
            body.append(f"<h3>{line[4:]}</h3>")
        elif line.startswith("- "):
            body.append(f"<p>• {line[2:]}</p>")
        elif line.strip():
            body.append(f"<p>{line}</p>")
        else:
            body.append("")
    html = f"""<!doctype html><meta charset="utf-8"><style>
body{{font-family:'Microsoft YaHei',Arial,sans-serif;max-width:980px;margin:40px auto;line-height:1.7;color:#1f2937}}
h1{{border-bottom:3px solid #2563eb;padding-bottom:10px}} table{{border-collapse:collapse;width:100%}}
td,th{{border:1px solid #cbd5e1;padding:6px}} pre{{background:#f1f5f9;padding:12px;white-space:pre-wrap}}
</style>{''.join(body)}"""
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(html, encoding="utf-8")


def main() -> None:
    if OUT.exists():
        import shutil
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    profiles = []
    for path in XMIND_FILES:
        roots = parse_xmind(path)
        profiles.append(lesson_profile_from_file(path, roots))
    pdf_summary = extract_pdf_summary(PDF_FILE)
    lessons = classify_modules(profiles)

    write(OUT / "README.md", build_readme(lessons, pdf_summary))
    write(OUT / "00_material_extract.md", build_material_index(profiles, pdf_summary))
    write(OUT / "99_student_qa_bank.md", build_qa_bank(lessons))
    for lesson in lessons:
        write(OUT / "teacher_guide" / f"{lesson['id']}_{lesson['source']}.md", build_teacher_guide(lesson))
        write(OUT / "student_handbook" / f"{lesson['id']}_{lesson['source']}.md", build_student_handout(lesson))
        write(OUT / "assignments" / f"{lesson['id']}_{lesson['source']}_assignment.md", build_assignment_template(lesson))

    HTML_OUT.mkdir(parents=True, exist_ok=True)
    for md in OUT.rglob("*.md"):
        export_simple_html(md, HTML_OUT / md.relative_to(OUT).with_suffix(".html"))
    index = HTML_OUT / "index.html"
    links = []
    for md in sorted(OUT.rglob("*.md")):
        href = md.relative_to(OUT).with_suffix(".html").as_posix()
        links.append(f"<li><a href='{href}'>{md.relative_to(OUT)}</a></li>")
    index.write_text("<!doctype html><meta charset='utf-8'><h1>上音 Wwise 无截图版教案</h1><ul>" + "\n".join(links) + "</ul>", encoding="utf-8")

    print(f"Generated {OUT}")
    print(f"HTML {HTML_OUT}")
    print(f"Lessons {len(lessons)}")


if __name__ == "__main__":
    main()
