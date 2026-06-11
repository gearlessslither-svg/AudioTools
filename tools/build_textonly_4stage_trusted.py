from __future__ import annotations

import json
import re
import sys
import zipfile
from pathlib import Path


WORKSPACE = Path(r"G:\AI\Material\Wwise")
OUT = WORKSPACE / "course_design_textonly_4stages"
PDF_OUT = WORKSPACE / "course_design_textonly_4stages_pdf"

TOOL_DIR = WORKSPACE / "course_design" / "tools"
sys.path.insert(0, str(TOOL_DIR))

import export_pdfs_pil as pdf_exporter
import generate_official_version as official


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

PDF_AUX = Path(r"E:\EF\周会\0513\Wwise 1012024完全突破.pdf")

BAD_TOKENS = [
    "\ufffd",
    "鈥",
    "鎴",
    "涓",
    "瀹",
    "鑰",
    "锛",
    "乱码",
]


STAGE_META = {
    "101": {
        "name": "Wwise 101 Foundation",
        "position": "面向零游戏音频基础学员，建立 Wwise Authoring 到游戏运行时的完整声音链路。",
        "outcome": "完成一个能解释 Event、SoundBank、Game Sync、Bus Routing 与基础优化的 Mini Interactive Sound Scene。",
        "hours": "24 小时 / 12 课",
    },
    "201": {
        "name": "Wwise 201 Interactive Music",
        "position": "训练学员从线性音乐制作转向互动音乐结构设计。",
        "outcome": "完成包含 re-sequencing、re-orchestration、transition rules 与 Game Sync 控制的 Adaptive Music System。",
        "hours": "24 小时 / 12 课",
    },
    "251": {
        "name": "Wwise 251 Optimization",
        "position": "建立资源预算、Profiler 观察、转换压缩、Voice、SoundBank 与 runtime 管理意识。",
        "outcome": "完成一份 Optimization Audit Report，能用数据说明问题和优化策略。",
        "hours": "20 小时 / 10 课",
    },
    "301": {
        "name": "Wwise 301 Unity Integration",
        "position": "把 Wwise Authoring 中的声音设计落到 Unity 场景、组件与脚本运行时。",
        "outcome": "完成 Unity + Wwise 小型可玩音频集成项目。",
        "hours": "28 小时 / 14 课",
    },
}


COMMON_QA = [
    ("Wwise 里能听到，为什么游戏里听不到？", "Authoring 试听只证明声音对象能播放。游戏端还需要 Event 正确、SoundBank 已生成并加载、触发条件成立、bus routing 和音量没有阻断。"),
    ("Event、Sound SFX、SoundBank 的关系是什么？", "Sound SFX 是声音对象，Event 是游戏调用声音行为的入口，SoundBank 是游戏运行时读取的数据包。"),
    ("State、Switch、RTPC 怎么选？", "Switch 适合离散局部类别，State 适合全局模式，RTPC 适合连续数值。"),
    ("Unity 组件触发和脚本触发怎么选？", "简单固定触发优先组件；需要 gameplay logic、条件判断、动态参数或回调时使用脚本。"),
    ("排错从哪里开始？", "从触发链路开始：Trigger 或 Script -> Event -> SoundBank -> Object 或 Bus -> Output 或 Profiler。"),
]


def is_clean(text: str) -> bool:
    text = str(text or "").strip()
    if not text:
        return False
    if any(token in text for token in BAD_TOKENS):
        return False
    if len(text) > 180:
        return False
    return True


def parse_xmind_titles(path: Path) -> list[tuple[int, str]]:
    titles: list[tuple[int, str]] = []

    def walk(topic: dict, depth: int = 0) -> None:
        title = str(topic.get("title", "")).strip()
        if is_clean(title):
            titles.append((depth, title))
        children = topic.get("children", {})
        if isinstance(children, dict):
            for child in children.get("attached", []) or []:
                if isinstance(child, dict):
                    walk(child, depth + 1)

    try:
        with zipfile.ZipFile(path) as z:
            if "content.json" not in z.namelist():
                return []
            data = json.loads(z.read("content.json").decode("utf-8"))
        for sheet in data if isinstance(data, list) else [data]:
            root = sheet.get("rootTopic", {})
            if isinstance(root, dict):
                walk(root, 0)
    except Exception:
        return []
    return titles


def xmind_supplements() -> dict[str, list[dict]]:
    supplements = {"101": [], "201": [], "251": [], "301": []}
    for path in XMIND_FILES:
        titles = parse_xmind_titles(path)
        if not titles:
            continue
        stem = path.stem
        clean_titles = titles[:120]
        item = {"file": path.name, "titles": clean_titles}
        lower = stem.lower()
        if "作业" in stem or "模板" in stem:
            for stage in supplements:
                supplements[stage].append(item)
        elif "301" in stem or "unity" in lower or "gamekit" in lower or "lesson" in lower or "3d kit" in lower:
            supplements["301"].append(item)
        else:
            supplements["101"].append(item)
    return supplements


def md_table(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    out = ["| " + " | ".join(rows[0]) + " |", "| " + " | ".join(["---"] * len(rows[0])) + " |"]
    for row in rows[1:]:
        out.append("| " + " | ".join(str(x).replace("\n", "<br>") for x in row) + " |")
    return "\n".join(out)


def source_rows(stage: str, lesson: dict) -> str:
    rows = [["官方资料", "章节", "页码范围", "截图说明"]]
    for row in official.source_block(lesson["sources"]):
        rows.append([row["pdf"], row["chapter"], row["pages"], "本版不嵌入截图；如授课必须看界面，请打开原版 PDF 对应页码。"])
    return md_table(rows)


def supplement_md(items: list[dict], limit_files: int = 8) -> str:
    if not items:
        return "本阶段没有使用新增 XMind 正文；仅使用官方课程结构。"
    parts = []
    for item in items[:limit_files]:
        parts.append(f"### {item['file']}")
        lines = []
        for depth, title in item["titles"][:60]:
            indent = "  " * min(depth, 4)
            lines.append(f"{indent}- {title}")
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


def lesson_text(stage: str, lesson: dict, index: int) -> str:
    terms = lesson.get("terms", [])[:8]
    title = lesson["title"]
    return f"""## 第 {index:02d} 课：{title}

### 官方依据

{source_rows(stage, lesson)}

### 教学目标

- 学员能解释本课核心机制解决的游戏音频问题。
- 学员能保留并正确使用本课 English Terms。
- 学员能按流程完成课堂实操或设计说明。
- 学员能说出本课最常见的失败点和排错顺序。

### 核心术语

{md_table([["English Term", "中文教学说明"]] + [[f"`{term}`", "课堂保留英文原词，用中文解释功能、适用场景和边界。"] for term in terms])}

### 授课流程

{md_table([
    ["时间", "环节", "教师动作", "学生产出"],
    ["0:00-0:10", "问题导入", "提出一个游戏音频需求，引导学员判断为什么需要本课机制。", "说出需求与声音问题。"],
    ["0:10-0:30", "概念讲解", "解释核心术语，画出对象、事件、Bank、运行时或脚本链路。", "记录术语与中文含义。"],
    ["0:30-0:55", "教师演示", "完成一个最小可验证案例。", "记录关键步骤。"],
    ["0:55-1:35", "学员跟做", "巡回检查命名、层级、参数、SoundBank 或 Unity 引用。", "完成课堂任务。"],
    ["1:35-1:50", "排错复盘", "用链路排查 2 个典型错误。", "写出自己的排错顺序。"],
    ["1:50-2:00", "Checkpoint", "进行短测和作业说明。", "提交或记录作业要求。"],
])}

### 具体教学内容

{lesson['focus']}

教师需要将官方步骤转化为三个问题：

1. `What is the audio problem?` 本课解决什么游戏音频问题？
2. `Which Wwise feature is responsible?` 哪个 Wwise 或 Unity feature 负责？
3. `How do we verify it?` 如何在 Authoring、Cube、Profiler 或 Unity Runtime 中验证？

### 学生常见问题

{md_table([["问题", "回答"]] + COMMON_QA[:3])}

### 课堂检测

- 术语题：解释 3 个 English Terms。
- 流程题：按顺序说出本课机制从 authoring 到 runtime 的链路。
- 排错题：给出一个无声、未触发或参数无效案例，让学生说出检查顺序。

### 课后作业

提交一份无截图也能读懂的文字说明：

- 本课完成了什么。
- 使用了哪些 English Terms。
- 运行或验证方式是什么。
- 出现问题时如何排查。
"""


def stage_document(stage: str, data: dict, supplements: list[dict]) -> str:
    meta = STAGE_META[stage]
    lessons = data["lessons"]
    overview_rows = [["课次", "主题", "官方来源", "建议时长"]]
    for i, lesson in enumerate(lessons, 1):
        overview_rows.append([i, lesson["title"], lesson["official"], "2h"])

    doc = [f"# {meta['name']} 无截图文字教案\n"]
    doc.append("## 版本原则\n")
    doc.append("- 只使用能稳定确认的官方章节、课程标题、术语和教学结构。")
    doc.append("- 不使用 PDF 抽取出的可疑正文，不使用任何截图。")
    doc.append("- 如果课堂必须看界面，只标注原版官方 PDF 与页码范围，由教师打开原 PDF 对照。")
    doc.append("- 新增 XMind 只保留通过乱码过滤的清晰节点，不保留可疑文本。\n")

    doc.append("## 阶段定位\n")
    doc.append(meta["position"] + "\n")
    doc.append(f"- 建议时长：{meta['hours']}")
    doc.append(f"- 阶段成果：{meta['outcome']}\n")

    doc.append("## 课程总览\n")
    doc.append(md_table(overview_rows) + "\n")

    doc.append("## 新增资料中可确认的结构节点\n")
    doc.append(supplement_md(supplements) + "\n")

    doc.append("## 阶段学生问答库\n")
    doc.append(md_table([["问题", "回答"]] + COMMON_QA) + "\n")

    doc.append("## 分课教案\n")
    for i, lesson in enumerate(lessons, 1):
        doc.append(lesson_text(stage, lesson, i))

    doc.append("## 阶段测评\n")
    doc.append(md_table([
        ["维度", "分值", "说明"],
        ["概念准确", "25", "能解释核心 English Terms。"],
        ["流程完整", "25", "能说明从设计目标到运行验证的链路。"],
        ["课堂实操", "25", "能完成本阶段最小项目或设计说明。"],
        ["排错能力", "15", "能按链路定位问题。"],
        ["表达规范", "10", "文字说明清晰，无截图也能理解。"],
    ]))
    return "\n".join(doc)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def export_pdf(md_path: Path) -> Path:
    pdf_exporter.ROOT = OUT
    pdf_exporter.OUT = PDF_OUT
    pdf_exporter.PDF_DIR = PDF_OUT
    pdf_exporter.COMBINED_DIR = PDF_OUT
    renderer = pdf_exporter.PdfRenderer(md_path.stem)
    pdf_exporter.render_markdown_file(renderer, md_path)
    pdf_path = PDF_OUT / md_path.with_suffix(".pdf").name
    renderer.finish(pdf_path)
    return pdf_path


def main() -> None:
    if OUT.exists():
        import shutil
        shutil.rmtree(OUT)
    if PDF_OUT.exists():
        import shutil
        shutil.rmtree(PDF_OUT)
    OUT.mkdir(parents=True)
    PDF_OUT.mkdir(parents=True)

    stage_data = official.stage_data()
    supplements = xmind_supplements()

    source_note = [
        "# 可信内容筛选说明",
        "",
        "本目录只保留以下内容：",
        "",
        "- 官方 101/201/251/301 课程标题、章节与页码范围。",
        "- Wwise/Unity 常见 English Terms。",
        "- XMind 中未出现乱码标记、长度合理、结构清晰的节点标题。",
        "- PDF `Wwise 1012024完全突破.pdf` 仅登记为 101 辅助资料，不抽取正文进入教材。",
        "",
        f"101 辅助 PDF：`{PDF_AUX}`",
    ]
    write(OUT / "00_trust_filter_note.md", "\n".join(source_note) + "\n")

    for stage in ["101", "201", "251", "301"]:
        md_path = OUT / f"Wwise_{stage}_TextOnly_Framework.md"
        write(md_path, stage_document(stage, stage_data[stage], supplements[stage]))
        export_pdf(md_path)

    write(OUT / "README.md", "# 四阶段无截图文字教案\n\n本目录包含 101、201、251、301 四个阶段的纯文字版教案源文件。PDF 输出在相邻目录 `course_design_textonly_4stages_pdf`。\n")
    print(f"Generated Markdown: {OUT}")
    print(f"Generated PDFs: {PDF_OUT}")


if __name__ == "__main__":
    main()
