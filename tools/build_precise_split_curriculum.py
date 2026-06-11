from __future__ import annotations

import json
import re
import shutil
import textwrap
import zipfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


WORKSPACE = Path(r"G:\AI\Material\Wwise")
PDF_TEXT_ROOT = WORKSPACE / "pdf_data"
OUT = WORKSPACE / "course_design_precise_split_v3"
STUDENT_OUT = OUT / "official_student_delivery"
TEACHER_OUT = OUT / "xmind_teacher_experience"
PDF_OUT = OUT / "pdf"

FONT_REGULAR = Path(r"C:\Windows\Fonts\msyh.ttc")
FONT_BOLD = Path(r"C:\Windows\Fonts\msyhbd.ttc")
FONT_MONO = Path(r"C:\Windows\Fonts\consola.ttf")

A4 = (1240, 1754)
MARGIN_X = 82
MARGIN_Y = 74
CONTENT_W = A4[0] - MARGIN_X * 2
TEXT = (31, 41, 55)
MUTED = (88, 103, 124)
BLUE = (29, 78, 216)
LIGHT_BLUE = (231, 240, 255)
LIGHT_GRAY = (248, 250, 252)
LINE = (203, 213, 225)


def font(path: Path, size: int):
    if path.exists():
        return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


FONTS = {
    "h1": font(FONT_BOLD, 34),
    "h2": font(FONT_BOLD, 26),
    "h3": font(FONT_BOLD, 22),
    "body": font(FONT_REGULAR, 19),
    "small": font(FONT_REGULAR, 15),
    "code": font(FONT_MONO if FONT_MONO.exists() else FONT_REGULAR, 16),
}


def normalize_official_text(text: str) -> str:
    text = str(text or "")
    replacements = {
        "\u00a0": " ",
        "鈥?": "-",
        "鈥�": "-",
        "鈥": "-",
        "每": "-",
        "–": "-",
        "—": "-",
        "�": "",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+-\s+", " - ", text)
    return text


def normalize_xmind_text(text: str) -> str:
    text = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


BAD_TOKENS = [
    "\ufffd",
    "鈥",
    "鎴",
    "瀹",
    "鑰",
    "锛",
    "乱码",
]


def is_clean_xmind_text(text: str) -> bool:
    text = normalize_xmind_text(text)
    if not text:
        return False
    if any(token in text for token in BAD_TOKENS):
        return False
    if len(text) > 1200:
        return False
    qmarks = text.count("?")
    if qmarks >= 4 and qmarks / max(len(text), 1) > 0.08:
        return False
    return True


@dataclass
class OfficialRef:
    pdf_key: str
    kind: str
    num: int


@dataclass
class OfficialEntry:
    pdf_key: str
    kind: str
    num: int
    title: str
    pages: list[int]
    toc: list[str]

    @property
    def source_label(self) -> str:
        return f"{self.pdf_key}.pdf {self.kind} {self.num}: {self.title}"

    @property
    def page_range(self) -> str:
        if not self.pages:
            return "页码未定位"
        return f"p{min(self.pages)}-p{max(self.pages)}"


STAGE_INFO = {
    "101": {
        "name": "Wwise 101 Foundation",
        "cn": "基础工作流与 Wwise Authoring",
        "hours": "24 小时 / 12 课",
        "outcome": "学生能够从零建立 Wwise 到 Cube 的基础声音链路，并解释 Event、SoundBank、Game Sync、3D 声音、Bus Routing 与基础优化的关系。",
        "audience": "有音乐或音效制作经验，但没有游戏音频和 Wwise 基础的初学者。",
    },
    "201": {
        "name": "Wwise 201 Interactive Music",
        "cn": "互动音乐系统",
        "hours": "24 小时 / 12 课",
        "outcome": "学生能够用 Music Segment、Playlist、Layer、MIDI、Game Sync 与 Transition 规则搭建可交互的音乐系统。",
        "audience": "已经完成 101 或具备基础 Wwise 操作能力的作曲、声音设计或技术音频学习者。",
    },
    "251": {
        "name": "Wwise 251 Optimization",
        "cn": "性能、资源与运行时优化",
        "hours": "20 小时 / 10 课",
        "outcome": "学生能够用 Profiler、Conversion、Voice、SoundBank 与 Runtime 管理方法完成一份可解释的优化审计报告。",
        "audience": "需要把声音设计交付到真实运行环境，并开始关注内存、CPU、流媒体和平台差异的学习者。",
    },
    "301": {
        "name": "Wwise 301 Unity Integration",
        "cn": "Unity 集成与脚本调用",
        "hours": "28 小时 / 14 课",
        "outcome": "学生能够在 Unity 中加载 SoundBank、触发 Event、控制 Game Sync、使用区域效果、处理 Callback，并完成一个小型 Unity + Wwise 集成项目。",
        "audience": "已经理解 Wwise Authoring 基础，希望把声音系统接入 Unity 运行时的声音设计师、技术音频或游戏开发学习者。",
    },
}


STAGE_TERMS = {
    "101": [
        "Wwise Authoring",
        "Cube",
        "Event",
        "Sound SFX",
        "SoundBank",
        "Actor-Mixer Hierarchy",
        "Random Container",
        "Switch",
        "State",
        "Game Parameter",
        "RTPC",
        "Attenuation",
        "3D Spatialization",
        "Master Audio Bus",
        "Soundcaster",
        "Mixing Desk",
    ],
    "201": [
        "Interactive Music",
        "Music Segment",
        "Music Track",
        "Music Playlist Container",
        "Entry Cue",
        "Exit Cue",
        "Tempo",
        "Time Signature",
        "Re-sequencing",
        "Re-orchestration",
        "MIDI",
        "Transition Rule",
        "Stinger",
        "Music Switch Container",
    ],
    "251": [
        "Profiler",
        "Resource Usage",
        "SoundBank",
        "Streaming",
        "Conversion",
        "Compression",
        "Voice",
        "Virtual Voice",
        "Effect",
        "Platform",
        "Granularity",
        "Runtime Management",
    ],
    "301": [
        "Unity",
        "Wwise Adventure Game",
        "AkEvent",
        "AkAmbient",
        "AkBank",
        "GameObject",
        "Listener",
        "PostEvent",
        "LoadBank",
        "SetSwitch",
        "SetState",
        "SetRTPCValue",
        "Callback",
        "Region",
        "Script",
    ],
}


LESSON_MAPS = {
    "101": [
        ("101-01", "Wwise、Cube 与最小发声链路", [1], "建立从导入素材到在 Cube 中听见声音的完整心智模型。", "完成第一个可验证的 Event + SoundBank 链路。"),
        ("101-02", "一个 WAV 的多种用途", [2], "理解 Audio Source 与 Sound SFX Object 的区别，以及对象属性如何创造不同用途。", "用同一素材制作多个声音对象并说明差异。"),
        ("101-03", "少量资源创造声音变化", [3], "用 Random / Sequence Container 减少重复感，并理解随机权重与属性随机化。", "完成一组可重复触发但不机械重复的声音变化。"),
        ("101-04", "Switches 与离散游戏状态", [4], "用 Switch Group / Switch / Switch Container 处理材质、武器类型等离散选择。", "完成一个材质驱动的脚步或碰撞系统。"),
        ("101-05", "Game Parameters 与 RTPC", [5], "用连续数值驱动音量、音高、滤波或其他属性变化。", "设计一条可解释的 RTPC 曲线。"),
        ("101-06", "States 与 Game Sync Profiling", [6, 7], "区分 State / Switch / RTPC，并用 Profiler 验证 Game Sync 是否生效。", "提交一份 Game Sync 选择与验证记录。"),
        ("101-07", "3D Spatialization 与 Position Automation", [8, 9], "理解 Emitter、Listener、Attenuation 和 Position Automation 对空间听感的影响。", "制作一个可听辨距离或位置变化的声音案例。"),
        ("101-08", "Speaker Panning 与 Actor-Mixers", [10, 11], "理解 2D 声像与 Actor-Mixer 组织结构，建立可维护工程层级。", "整理一组符合命名和层级规则的声音对象。"),
        ("101-09", "Master Audio Bus、Submix 与 Effects", [12, 13, 14], "理解从对象到总线的信号流，以及效果器应放在对象层还是 Bus 层。", "画出一条 Sound SFX 到 Master Audio Bus 的信号路径。"),
        ("101-10", "Soundcaster、Mixing Desk 与课堂展示", [15, 16], "用 Soundcaster 和 Mixing Desk 做场景化试听、对比和混音演示。", "建立一个可用于课堂展示的试听 Session。"),
        ("101-11", "Control Surfaces 与 Multiple SoundBanks", [17, 18], "理解控制表面和多 SoundBank 工作流，开始从运行时角度看资源组织。", "说明一个多 Bank 切分方案。"),
        ("101-12", "SoundBank Size 与基础优化", [19, 20], "理解 Bank Size、Media Inclusion 与基础优化策略。", "完成 101 阶段项目展示和排错答辩。"),
    ],
    "201": [
        ("201-01", "互动音乐全局图景与 Re-sequencing 入门", [1], "从线性配乐转向可重排音乐，建立 Segment、Cue、Playlist 的基本关系。", "完成一段可顺序播放的音乐结构。"),
        ("201-02", "Playlist、随机与连续变化", [1], "深入 Music Playlist Container、多组 Playlist、随机循环与 Profiler 观察。", "完成可变化但结构可控的 Playlist。"),
        ("201-03", "Re-orchestration 与 Layered Approach", [2], "用分层思路构建可增减密度的音乐结构。", "完成一组基础 Layer，并设置 Tempo 与 Cue。"),
        ("201-04", "Clips、Fades、Sub-Tracks 与 Layer 实验", [2], "编辑 Clip、Loop、Fade、Filter Curve 与 Sub-Track，扩展音乐系统表现力。", "完成一段可 A/B 比较的分层音乐片段。"),
        ("201-05", "Mixed Method Playlists", [3], "组合重排与分层方法，建立更复杂的互动音乐组织。", "提交一个混合方法 Playlist 结构图。"),
        ("201-06", "Working with MIDI", [4], "理解 Wwise 中 MIDI 的导入、路由和互动控制可能性。", "完成一个 MIDI 驱动的音乐或乐器触发案例。"),
        ("201-07", "Creating Interaction", [5], "把游戏状态、玩家行为和音乐系统连接起来。", "设计一个由 Game Sync 控制的音乐变化。"),
        ("201-08", "Transitions Part I", [6], "掌握基础 Transition 规则、过渡时机和音乐连续性。", "完成两个音乐状态之间的基础过渡。"),
        ("201-09", "Transitions Part II", [7], "处理更复杂的过渡条件、同步点和音乐逻辑。", "完成一个带条件判断的过渡系统。"),
        ("201-10", "Interactive Music Mixing", [8], "在互动音乐结构中处理音量、层级、Bus 与混音可控性。", "提交一份互动音乐混音检查表。"),
        ("201-11", "Adaptive Music System 综合设计", [1, 2, 3, 4, 5, 6, 7, 8], "把重排、分层、MIDI、交互和过渡组合成完整系统。", "完成一个 Adaptive Music System 设计文档。"),
        ("201-12", "201 阶段项目展示与答辩", [1, 2, 3, 4, 5, 6, 7, 8], "通过展示和口头解释验证互动音乐系统的结构、触发和过渡。", "完成项目演示、排错说明和术语答辩。"),
    ],
    "251": [
        ("251-01", "Resource Usage 与 SoundBank 原则", [1], "建立内存、流媒体、SoundBank 与资源加载的基本优化视角。", "完成资源使用观察记录。"),
        ("251-02", "Profiler、Voice Inspector 与 Resource Monitoring", [1], "用 Profiler 观察声音系统运行时的资源与 Voice 情况。", "提交一次 Profiling Session 观察表。"),
        ("251-03", "Conversion and Compression", [2], "理解格式转换、压缩质量、平台差异与资源体积的权衡。", "完成一组 Conversion Settings 对比。"),
        ("251-04", "Voice Management I", [3], "理解 Voice 数量、优先级、限制和播放行为。", "找出并解释一个 Voice 管理问题。"),
        ("251-05", "Voice Management II 与虚拟化策略", [3], "进一步处理 Virtual Voice、Playback Limit 和距离相关的 Voice 策略。", "完成一个 Voice 优化方案。"),
        ("251-06", "Effects 成本与优化", [4], "理解效果器对 CPU、内存和总线路由的影响。", "比较对象层与 Bus 层 Effects 的成本。"),
        ("251-07", "Platform Management", [5], "为不同平台建立差异化资源、压缩和性能策略。", "完成一份平台差异检查表。"),
        ("251-08", "SoundBank Granularity", [6], "理解 Bank 粒度、加载时机、冗余和运行时管理关系。", "提出一个可执行的 Bank 切分方案。"),
        ("251-09", "Runtime Management", [7], "理解运行时加载、卸载、资源释放和项目生命周期管理。", "说明一个运行时资源管理流程。"),
        ("251-10", "Optimization Audit 项目", [1, 2, 3, 4, 5, 6, 7], "用数据和排查链路总结优化问题、证据和建议。", "提交完整 Optimization Audit Report。"),
    ],
    "301": [
        ("301-01", "Unity + Wwise 工程结构与 Adding Sound", [1], "理解 Wwise Adventure Game、Unity 工程和 Wwise 工程之间的对应关系。", "在 Unity 中播放第一个 Wwise Event。"),
        ("301-02", "Trigger Conditions 与组件化触发", [1], "使用组件和触发条件控制声音何时播放。", "完成一个带条件限制的 AkEvent 触发。"),
        ("301-03", "Ambiences 与 AkAmbient", [2], "理解 Ambience 的位置、范围、衰减与触发方式。", "完成一个区域环境声案例。"),
        ("301-04", "SoundBank Management I", [3], "理解 Unity 侧加载 SoundBank 的必要性和常见失败点。", "完成 Bank 加载和事件播放验证。"),
        ("301-05", "SoundBank Management II", [3], "处理多 Bank、场景加载和资源组织问题。", "说明一个场景级 Bank 管理方案。"),
        ("301-06", "Posting Events from Script I", [4], "理解脚本中 PostEvent 的调用对象、时机和参数。", "用脚本触发一个 Event。"),
        ("301-07", "Posting Events from Script II", [4], "把触发与 gameplay logic、动画事件或对象生命周期结合。", "完成一个带逻辑条件的脚本触发。"),
        ("301-08", "Controlling Game Syncs from Script", [5], "用脚本设置 Switch、State 或 RTPC，并验证 Wwise 响应。", "完成一个 Game Sync 脚本控制案例。"),
        ("301-09", "Using Effects on Regions", [6], "理解区域、效果、Aux 或环境变化如何影响声音。", "完成一个区域效果切换案例。"),
        ("301-10", "Callbacks", [7], "理解 Wwise Callback 如何把音频时间点或事件状态传回游戏逻辑。", "完成一个 Callback 触发 Unity 行为的案例。"),
        ("301-11", "Advanced Music System I", [8], "在 Unity 集成中应用高级音乐系统结构。", "完成一个音乐系统触发与状态控制。"),
        ("301-12", "Advanced Music System II", [8], "处理音乐系统、回调、过渡和 gameplay 之间的协同。", "完成一个可演示的高级音乐片段。"),
        ("301-13", "Making Your Own Adventure Game", [9], "从官方 Adventure Game 扩展到自己的场景或玩法设计。", "提出并实现一个小型音频集成功能。"),
        ("301-14", "301 阶段项目展示与答辩", [1, 2, 3, 4, 5, 6, 7, 8, 9], "完整演示 Unity + Wwise 运行时链路和排错能力。", "提交集成项目、排错说明和术语答辩。"),
    ],
}


XMIND_PATHS = [
    Path("E:/Ryan/0417 \u4e0a\u97f3/Wwise301\u901f\u901a.xmind"),
    Path("E:/Ryan/0417 \u4e0a\u97f3/\u8bfe\u540e\u4f5c\u4e1a - \u6a21\u677f.xmind"),
    Path("E:/Ryan/0417 \u4e0a\u97f3/3D Kit Demo\u5b9e\u6218\u8bad\u7ec3.xmind"),
    Path("E:/Ryan/0417 \u4e0a\u97f3/Lesson 5 1107.xmind"),
    Path("E:/Ryan/0417 \u4e0a\u97f3/Lesson 5 \u8bfe\u540e\u4f5c\u4e1a.xmind"),
    Path("E:/Ryan/0417 \u4e0a\u97f3/Lesson 6 - 1110.xmind"),
    Path("E:/Ryan/0417 \u4e0a\u97f3/Lesson 6 - 1113.xmind"),
    Path("E:/Ryan/0417 \u4e0a\u97f3/Lesson 7 - 1120.xmind"),
    Path("E:/Ryan/0417 \u4e0a\u97f3/Lesson 9.xmind"),
    Path("E:/Ryan/0417 \u4e0a\u97f3/Lesson 12.xmind"),
    Path("E:/Ryan/0417 \u4e0a\u97f3/Unity + Wwise3DGameKit\u5b9e\u6218\u8bad\u7ec3.xmind"),
    Path("E:/EF/\u5468\u4f1a/0513/Wwise 1012024\u5b8c\u5168\u7a81\u7834.xmind"),
]


XMIND_ASSIGNMENTS = {
    "Wwise 1012024完全突破.xmind": ["101"],
    "Lesson 5 1107.xmind": ["101"],
    "Lesson 5 课后作业.xmind": ["101"],
    "Lesson 6 - 1110.xmind": ["101", "301"],
    "Lesson 6 - 1113.xmind": ["101", "301"],
    "课后作业 - 模板.xmind": ["101"],
    "Lesson 7 - 1120.xmind": ["251"],
    "Wwise301速通.xmind": ["301"],
    "3D Kit Demo实战训练.xmind": ["301"],
    "Unity + Wwise3DGameKit实战训练.xmind": ["301"],
    "Lesson 9.xmind": ["301"],
    "Lesson 12.xmind": ["301"],
}


COMMON_QA = [
    ("Wwise 里可以听到，为什么游戏里没有声音？", "Authoring 试听只说明声音对象能播放；游戏里还需要 Event 名称正确、SoundBank 已生成并加载、触发条件成立、GameObject/Listener 有效、Bus Routing 与音量没有阻断。"),
    ("Event、Sound SFX、SoundBank 的关系是什么？", "Sound SFX 是声音对象，Event 是游戏调用声音行为的入口，SoundBank 是运行时加载的数据包。"),
    ("Switch、State、RTPC 怎么选？", "Switch 适合离散且局部的分类；State 适合全局状态；RTPC 适合连续数值驱动。"),
    ("为什么一定要保留英文术语？", "Wwise、Unity、官方文档、错误信息和团队沟通都以英文术语为准，中文解释用于理解，英文原词用于执行和排错。"),
    ("排错从哪里开始？", "从触发链路开始：Trigger 或 Script -> Event -> SoundBank -> GameObject / Listener -> Game Sync -> Bus / Output -> Profiler。"),
]


def page_num(path: Path) -> int:
    match = re.search(r"_p(\d+)\.txt$", path.name)
    return int(match.group(1)) if match else 0


def detect_official_entries(pdf_key: str, kind: str) -> dict[int, OfficialEntry]:
    pat = re.compile(rf"^{kind}\s+(\d+):\s+(.+)$")
    grouped: dict[int, dict[str, object]] = {}
    for txt in sorted(PDF_TEXT_ROOT.glob(f"{pdf_key}.pdf_p*.txt"), key=page_num):
        page = page_num(txt)
        lines = txt.read_text(encoding="utf-8", errors="ignore").splitlines()[:18]
        for raw in lines:
            line = normalize_official_text(raw)
            match = pat.match(line)
            if not match:
                continue
            title = match.group(2)
            if "...." in raw or "." * 5 in raw or len(title) > 120:
                continue
            num = int(match.group(1))
            item = grouped.setdefault(num, {"pages": set(), "titles": []})
            item["pages"].add(page)
            item["titles"].append(title)
            break
    toc = extract_toc(pdf_key, kind)
    entries: dict[int, OfficialEntry] = {}
    for num, item in grouped.items():
        titles = item["titles"]
        title = max(titles, key=len)
        entries[num] = OfficialEntry(
            pdf_key=pdf_key,
            kind=kind,
            num=num,
            title=title,
            pages=sorted(item["pages"]),
            toc=toc.get(num, []),
        )
    return entries


def extract_toc(pdf_key: str, kind: str) -> dict[int, list[str]]:
    files = sorted(PDF_TEXT_ROOT.glob(f"{pdf_key}.pdf_p*.txt"), key=page_num)
    toc_files = [f for f in files if page_num(f) <= 8]
    if pdf_key == "wwise101_en":
        toc_files += [f for f in files if page_num(f) in (23, 24)]
    topic_re = re.compile(r"^(.+?)\s+\.{3,}\s+(\d+)\s*$")
    lesson_re = re.compile(rf"^{kind}\s+(\d+):\s+(.+)$")
    current: int | None = None
    toc: dict[int, list[str]] = {}
    for txt in toc_files:
        for raw in txt.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = normalize_official_text(raw)
            if not line or line.startswith(("Source:", "Page:", "Images:")):
                continue
            match = topic_re.match(raw.strip())
            if not match:
                continue
            title = normalize_official_text(match.group(1))
            if not title or title in {"Table of Contents", "Lessons", "Modules"}:
                continue
            lesson_match = lesson_re.match(title)
            if lesson_match:
                current = int(lesson_match.group(1))
                title = lesson_match.group(2).strip()
                toc.setdefault(current, [])
                continue
            if current is not None:
                if title.lower() == "related video":
                    continue
                if not re.search(r"[A-Za-z]", title):
                    continue
                entries = toc.setdefault(current, [])
                if title not in entries and len(entries) < 18:
                    entries.append(title)
    return toc


def build_official_index() -> dict[str, dict[int, OfficialEntry]]:
    return {
        "101": detect_official_entries("wwise101_en", "Module"),
        "201": detect_official_entries("wwise201_en", "Lesson"),
        "251": detect_official_entries("wwise251_en", "Lesson"),
        "301": detect_official_entries("wwise301_en", "Lesson"),
    }


def refs_for(stage: str, nums: list[int], official: dict[str, dict[int, OfficialEntry]]) -> list[OfficialEntry]:
    entries = []
    for num in nums:
        if num in official[stage]:
            entries.append(official[stage][num])
    return entries


def md_table(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    out = ["| " + " | ".join(rows[0]) + " |"]
    out.append("| " + " | ".join(["---"] * len(rows[0])) + " |")
    for row in rows[1:]:
        cleaned = [str(cell).replace("\n", "<br>") for cell in row]
        out.append("| " + " | ".join(cleaned) + " |")
    return "\n".join(out)


def official_ref_table(entries: list[OfficialEntry]) -> str:
    rows = [["官方资料", "章节", "页码", "截图/界面处理"]]
    for entry in entries:
        rows.append([
            f"{entry.pdf_key}.pdf",
            f"{entry.kind} {entry.num}: {entry.title}",
            entry.page_range,
            "本版不嵌入截图；需要界面时打开官方 PDF 对应页码。",
        ])
    return md_table(rows)


def stage_source_manifest(stage: str, official: dict[str, dict[int, OfficialEntry]]) -> str:
    rows = [["官方章节", "标题", "页码范围", "可用目录项示例"]]
    for num, entry in sorted(official[stage].items()):
        rows.append([
            f"{entry.kind} {num}",
            entry.title,
            entry.page_range,
            "；".join(entry.toc[:4]) if entry.toc else "以 PDF 页眉定位为准",
        ])
    return md_table(rows)


def lesson_terms(stage: str, title: str, refs: list[OfficialEntry]) -> list[str]:
    terms = list(STAGE_TERMS[stage])
    ref_text = " ".join([title] + [r.title for r in refs] + [topic for r in refs for topic in r.toc])
    picked = []
    for term in terms:
        key = term.lower().replace("-", " ")
        if any(part in ref_text.lower().replace("-", " ") for part in key.split()[:1]):
            picked.append(term)
    for term in terms:
        if term not in picked:
            picked.append(term)
        if len(picked) >= 8:
            break
    return picked[:8]


def student_lesson_md(stage: str, lesson: tuple[str, str, list[int], str, str], official: dict[str, dict[int, OfficialEntry]]) -> str:
    lesson_id, title, nums, focus, output = lesson
    refs = refs_for(stage, nums, official)
    terms = lesson_terms(stage, title, refs)
    toc_items = []
    for ref in refs:
        if ref.toc:
            toc_items.append(f"{ref.kind} {ref.num} 官方目录项：")
            toc_items.extend([f"- {item}" for item in ref.toc[:10]])
    if not toc_items:
        toc_items.append("- 以官方 PDF 对应章节页码为准进行课堂演示。")

    return f"""## {lesson_id} {title}

### 官方依据

{official_ref_table(refs)}

### 本课定位

{focus}

### 学习目标

- 能用英文术语说明本课机制解决的游戏音频问题。
- 能说出 Authoring、SoundBank、游戏运行时或 Unity 之间的职责边界。
- 能完成本课最小可验证任务，并说明验证方法。
- 能按触发链路进行基础排错。

### 官方目录要点

{chr(10).join(toc_items)}

### English Terms

{md_table([["Term", "中文解释要求"]] + [[f"`{term}`", "保留英文原词，课堂中用中文解释功能、适用场景和常见错误。"] for term in terms])}

### 课堂流程建议

{md_table([
    ["时间", "环节", "学生产出"],
    ["0:00-0:10", "问题导入：把本课机制放入一个具体游戏音频需求。", "说出需求和声音问题。"],
    ["0:10-0:30", "概念讲解：解释官方术语、对象关系和运行时边界。", "完成术语记录。"],
    ["0:30-0:55", "教师演示：使用官方工程或官方 PDF 页码对应步骤。", "记录关键步骤。"],
    ["0:55-1:35", "学生实操：完成最小可验证任务。", output],
    ["1:35-1:50", "排错复盘：用触发链路找 1-2 个常见错误。", "写出排错顺序。"],
    ["1:50-2:00", "Checkpoint：术语、流程、验证三项短测。", "提交课堂检查结果。"],
])}

### 学生任务

- 操作任务：{output}
- 说明任务：用 5-8 句话写清楚本课的声音目标、Wwise 功能、运行时验证方式。
- 排错任务：假设“游戏里没有声音”，按 Trigger / Event / SoundBank / GameObject / Bus / Profiler 的顺序列出检查项。

### 学生问答

{md_table([["问题", "回答"]] + COMMON_QA[:4])}

### 水准测试

- 术语：随机解释 3 个 English Terms。
- 流程：画出本课功能从设计到运行时验证的链路。
- 实操：在课堂工程中复现本课最小功能。
- 反思：写出一个最可能出错的位置和定位方法。
"""


def student_stage_doc(stage: str, official: dict[str, dict[int, OfficialEntry]]) -> str:
    info = STAGE_INFO[stage]
    rows = [["课次", "主题", "官方依据", "建议时长", "课堂产出"]]
    for lesson_id, title, nums, _, output in LESSON_MAPS[stage]:
        refs = refs_for(stage, nums, official)
        source = "；".join([f"{r.kind} {r.num} {r.page_range}" for r in refs])
        rows.append([lesson_id, title, source, "2h", output])

    parts = [
        f"# {info['name']} 学生交付版教材",
        "",
        f"## 阶段定位：{info['cn']}",
        "",
        f"- 适用对象：{info['audience']}",
        f"- 建议时长：{info['hours']}",
        f"- 阶段成果：{info['outcome']}",
        "- 资料边界：本教材以官方 PDF 的课程结构、章节标题、目录项和页码定位为主；不嵌入截图，不使用未经确认的 PDF 正文抽取。",
        "- 截图处理：如课堂必须展示界面，请教师打开对应官方 PDF 页码。本教材只给出页码范围。",
        "",
        "## 官方来源索引",
        "",
        stage_source_manifest(stage, official),
        "",
        "## 课程总览",
        "",
        md_table(rows),
        "",
        "## 阶段核心术语",
        "",
        md_table([["English Term", "课堂解释方向"]] + [[f"`{term}`", "要求学生保留英文原词，并能用中文解释含义、用途和常见误区。"] for term in STAGE_TERMS[stage]]),
        "",
        "## 分课教材",
        "",
    ]
    for lesson in LESSON_MAPS[stage]:
        parts.append(student_lesson_md(stage, lesson, official))
    parts.extend([
        "## 阶段结课测试",
        "",
        md_table([
            ["维度", "分值", "要求"],
            ["概念准确", "25", "能正确解释本阶段核心 English Terms。"],
            ["流程完整", "25", "能说明从设计、生成、加载、触发到验证的完整链路。"],
            ["实操可验证", "30", "能在官方工程或课堂工程中完成可运行结果。"],
            ["排错表达", "20", "能按证据链定位无声、触发失败、参数无效或资源异常。"],
        ]),
        "",
    ])
    return "\n".join(parts)


@dataclass
class XMindSource:
    path: Path
    all_count: int
    clean_count: int
    image_count: int
    nodes: list[tuple[int, str]]


def parse_xmind(path: Path) -> XMindSource:
    nodes: list[tuple[int, str]] = []
    all_count = 0
    image_count = 0

    def walk(topic: dict, depth: int = 0) -> None:
        nonlocal all_count
        all_count += 1
        title = normalize_xmind_text(topic.get("title", ""))
        if is_clean_xmind_text(title):
            nodes.append((depth, title))
        children = topic.get("children") or {}
        if isinstance(children, dict):
            for key in ("attached", "detached"):
                for child in children.get(key) or []:
                    if isinstance(child, dict):
                        walk(child, depth + 1)

    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            image_count = len([n for n in names if n.lower().startswith("resources/") and n.lower().endswith((".png", ".jpg", ".jpeg"))])
            if "content.json" not in names:
                return XMindSource(path, 0, 0, image_count, [])
            data = json.loads(zf.read("content.json").decode("utf-8"))
        for sheet in data if isinstance(data, list) else [data]:
            root = sheet.get("rootTopic", {})
            if isinstance(root, dict):
                walk(root, 0)
    except Exception:
        return XMindSource(path, 0, 0, image_count, [])
    return XMindSource(path, all_count, len(nodes), image_count, nodes)


def collect_xmind_sources() -> list[XMindSource]:
    return [parse_xmind(path) for path in XMIND_PATHS if path.exists()]


def xmind_stage_sources(stage: str, sources: list[XMindSource]) -> list[XMindSource]:
    selected = []
    for source in sources:
        stages = XMIND_ASSIGNMENTS.get(source.path.name, [])
        if stage in stages:
            selected.append(source)
    return selected


def extract_theme_cards(stage: str, sources: list[XMindSource]) -> list[tuple[str, list[str]]]:
    terms = STAGE_TERMS[stage]
    cards: list[tuple[str, list[str]]] = []
    seen: set[str] = set()
    for term in terms:
        hits = []
        key = term.lower().replace("-", " ")
        for source in sources:
            for _, text in source.nodes:
                flat = text.replace("\n", " ")
                if key in flat.lower().replace("-", " ") or any(part and part in flat.lower() for part in key.split()):
                    if flat not in seen:
                        hits.append(f"{flat}（来源：{source.path.name}）")
                        seen.add(flat)
                if len(hits) >= 4:
                    break
            if len(hits) >= 4:
                break
        if hits:
            cards.append((term, hits))
    return cards


def xmind_outline_md(source: XMindSource, limit: int | None = None) -> str:
    lines = [
        f"### {source.path.name}",
        "",
        f"- 节点总数：{source.all_count}",
        f"- 通过可信过滤节点：{source.clean_count}",
        f"- 内嵌图片资源数量：{source.image_count}（本版不嵌入图片；需要时回到原 XMind 打开）",
        "",
    ]
    items = source.nodes if limit is None else source.nodes[:limit]
    for depth, text in items:
        text = text.replace("\n", " / ")
        indent = "  " * min(depth, 5)
        lines.append(f"{indent}- {text}")
    if limit is not None and len(source.nodes) > limit:
        lines.append(f"- 其余 {len(source.nodes) - limit} 个可信节点保留在原 XMind 中，本版仅做精简梳理。")
    return "\n".join(lines)


def teacher_stage_doc(stage: str, sources: list[XMindSource]) -> str:
    info = STAGE_INFO[stage]
    selected = xmind_stage_sources(stage, sources)
    rows = [["XMind 文件", "阶段归属", "可信节点", "图片资源", "处理方式"]]
    for source in selected:
        rows.append([
            source.path.name,
            ", ".join(XMIND_ASSIGNMENTS.get(source.path.name, [])),
            f"{source.clean_count}/{source.all_count}",
            str(source.image_count),
            "只作为教师经验补充；不混入学生官方教材。",
        ])
    if not selected:
        rows.append(["无", stage, "0", "0", "本阶段仅使用官方学生教材。"])

    cards = extract_theme_cards(stage, selected)
    card_parts = []
    for term, hits in cards:
        card_parts.append(f"### {term}")
        card_parts.extend([f"- {hit}" for hit in hits])
        card_parts.append("")
    if not card_parts:
        card_parts.append("本阶段未从 XMind 中提取到足够明确的经验卡片。")

    parts = [
        f"# {info['name']} 教师经验补充",
        "",
        f"## 使用原则：{info['cn']}",
        "",
        "- 本文件只供教师备课、课堂讲法、补充案例和作业设计使用。",
        "- 本文件不作为官方学生教材交付；学生教材请使用 `official_student_delivery` 下的 PDF。",
        "- XMind 节点按 UTF-8 结构化内容读取；疑似乱码、损坏编码、过长异常文本已经过滤。",
        "- XMind 内嵌图片不进入本版 PDF；如需使用，回到原 XMind 文件打开并人工确认来源。",
        "",
        "## 来源覆盖清单",
        "",
        md_table(rows),
        "",
        "## 可转化为课堂经验的主题卡",
        "",
        "\n".join(card_parts),
        "",
        "## 建议用法",
        "",
        "- 课前：先用学生交付版确定本课官方目标，再从本文件挑选 1-2 条经验补充。",
        "- 课中：经验补充只能服务于官方任务，不替代官方流程。",
        "- 课后：把经验补充转化为问答、作业提示或排错提示，不放入学生主教材的权威知识点区域。",
        "",
        "## 教师问答素材",
        "",
        md_table([["问题", "建议回答"]] + COMMON_QA),
        "",
        "## 可信 XMind 轮廓附录",
        "",
    ]
    for source in selected:
        parts.append(xmind_outline_md(source, limit=None))
        parts.append("")
    return "\n".join(parts)


def clean_inline(text: str) -> str:
    text = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", r"[图片：\1]", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    return text.replace("<br>", " / ").replace("<br/>", " / ")


def text_width(draw: ImageDraw.ImageDraw, text: str, fnt) -> int:
    if not text:
        return 0
    box = draw.textbbox((0, 0), text, font=fnt)
    return box[2] - box[0]


def wrap_text(draw: ImageDraw.ImageDraw, text: str, fnt, width: int) -> list[str]:
    text = clean_inline(str(text)).strip()
    if not text:
        return [""]
    lines: list[str] = []
    current = ""
    for ch in text:
        trial = current + ch
        if text_width(draw, trial, fnt) <= width or not current:
            current = trial
        else:
            lines.append(current.rstrip())
            current = ch
    if current:
        lines.append(current.rstrip())
    return lines


class PdfRenderer:
    def __init__(self, title: str):
        self.title = title
        self.pages: list[Image.Image] = []
        self.page_no = 1
        self.image = Image.new("RGB", A4, "white")
        self.draw = ImageDraw.Draw(self.image)
        self.y = MARGIN_Y
        self.footer()

    def footer(self) -> None:
        self.draw.text((MARGIN_X, A4[1] - 44), f"{self.title} - {self.page_no}", font=FONTS["small"], fill=MUTED)

    def new_page(self) -> None:
        self.pages.append(self.image)
        self.page_no += 1
        self.image = Image.new("RGB", A4, "white")
        self.draw = ImageDraw.Draw(self.image)
        self.y = MARGIN_Y
        self.footer()

    def ensure(self, height: int) -> None:
        if self.y + height > A4[1] - 72:
            self.new_page()

    def line(self, text: str, fnt=None, fill=TEXT, indent=0, gap=8) -> None:
        fnt = fnt or FONTS["body"]
        lines = wrap_text(self.draw, text, fnt, CONTENT_W - indent)
        line_h = fnt.size + 8
        self.ensure(line_h * len(lines) + gap)
        for ln in lines:
            self.draw.text((MARGIN_X + indent, self.y), ln, font=fnt, fill=fill)
            self.y += line_h
        self.y += gap

    def heading(self, level: int, text: str) -> None:
        if level == 1:
            self.ensure(82)
            self.draw.text((MARGIN_X, self.y), clean_inline(text), font=FONTS["h1"], fill=(15, 23, 42))
            self.y += 52
            self.draw.line((MARGIN_X, self.y, A4[0] - MARGIN_X, self.y), fill=BLUE, width=3)
            self.y += 18
        elif level == 2:
            self.line(text, FONTS["h2"], fill=(15, 23, 42), gap=12)
        else:
            self.line(text, FONTS["h3"], fill=(15, 23, 42), gap=8)

    def bullet(self, text: str, ordered: str | None = None, indent: int = 0) -> None:
        prefix = f"{ordered}. " if ordered else "- "
        fnt = FONTS["body"]
        lines = wrap_text(self.draw, text, fnt, CONTENT_W - indent - 34)
        line_h = fnt.size + 7
        self.ensure(line_h * len(lines) + 6)
        self.draw.text((MARGIN_X + indent, self.y), prefix, font=fnt, fill=TEXT)
        for line in lines:
            self.draw.text((MARGIN_X + indent + 34, self.y), line, font=fnt, fill=TEXT)
            self.y += line_h
        self.y += 5

    def table(self, rows: list[list[str]]) -> None:
        if not rows:
            return
        max_cols = max(len(row) for row in rows)
        col_w = CONTENT_W // max_cols
        fnt = FONTS["small"]
        line_h = fnt.size + 6
        for idx, row in enumerate(rows):
            cells = []
            max_lines = 1
            for cell in row + [""] * (max_cols - len(row)):
                lines = wrap_text(self.draw, cell, fnt, col_w - 12)
                cells.append(lines)
                max_lines = max(max_lines, len(lines))
            row_h = max(32, max_lines * line_h + 14)
            self.ensure(row_h)
            fill = LIGHT_BLUE if idx == 0 else ("white" if idx % 2 else LIGHT_GRAY)
            x = MARGIN_X
            for lines in cells:
                self.draw.rectangle((x, self.y, x + col_w, self.y + row_h), fill=fill, outline=LINE)
                yy = self.y + 7
                for line in lines:
                    self.draw.text((x + 6, yy), line, font=fnt, fill=TEXT)
                    yy += line_h
                x += col_w
            self.y += row_h
        self.y += 12

    def code_block(self, lines: list[str]) -> None:
        fnt = FONTS["code"]
        wrapped: list[str] = []
        for raw in lines:
            wrapped.extend(wrap_text(self.draw, raw, fnt, CONTENT_W - 28))
        line_h = fnt.size + 6
        h = max(44, len(wrapped) * line_h + 22)
        self.ensure(h + 10)
        self.draw.rectangle((MARGIN_X, self.y, A4[0] - MARGIN_X, self.y + h), fill=LIGHT_GRAY, outline=LINE)
        yy = self.y + 10
        for line in wrapped:
            self.draw.text((MARGIN_X + 14, yy), line, font=fnt, fill=(51, 65, 85))
            yy += line_h
        self.y += h + 10

    def finish(self, path: Path) -> None:
        self.pages.append(self.image)
        path.parent.mkdir(parents=True, exist_ok=True)
        first, rest = self.pages[0], self.pages[1:]
        first.save(path, save_all=True, append_images=rest, resolution=150.0)


def parse_table(lines: list[str], start: int) -> tuple[list[list[str]], int]:
    rows = []
    i = start
    while i < len(lines):
        stripped = lines[i].strip()
        if not (stripped.startswith("|") and stripped.endswith("|")):
            break
        cells = [clean_inline(cell.strip()) for cell in stripped.strip("|").split("|")]
        if not all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
            rows.append(cells)
        i += 1
    return rows, i


def render_markdown_to_pdf(md_path: Path, pdf_path: Path) -> None:
    renderer = PdfRenderer(md_path.stem)
    lines = md_path.read_text(encoding="utf-8").splitlines()
    in_code = False
    code_lines: list[str] = []
    i = 0
    while i < len(lines):
        raw = lines[i]
        stripped = raw.strip()
        if stripped.startswith("```"):
            if not in_code:
                in_code = True
                code_lines = []
            else:
                renderer.code_block(code_lines)
                in_code = False
            i += 1
            continue
        if in_code:
            code_lines.append(raw)
            i += 1
            continue
        if not stripped:
            renderer.y += 5
            i += 1
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading:
            renderer.heading(len(heading.group(1)), heading.group(2))
            i += 1
            continue
        if stripped.startswith("|") and stripped.endswith("|"):
            table, i = parse_table(lines, i)
            renderer.table(table)
            continue
        ordered = re.match(r"^(\d+)\.\s+(.*)$", stripped)
        bullet = re.match(r"^(\s*)[-*]\s+(.*)$", raw)
        if ordered:
            renderer.bullet(ordered.group(2), ordered.group(1))
            i += 1
            continue
        if bullet:
            indent = min(len(bullet.group(1)) * 10, 90)
            renderer.bullet(bullet.group(2), indent=indent)
            i += 1
            continue
        renderer.line(stripped)
        i += 1
    renderer.finish(pdf_path)


def write_outputs() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    STUDENT_OUT.mkdir(parents=True, exist_ok=True)
    TEACHER_OUT.mkdir(parents=True, exist_ok=True)
    PDF_OUT.mkdir(parents=True, exist_ok=True)

    official = build_official_index()
    xmind_sources = collect_xmind_sources()

    readme = [
        "# Wwise 精准拆分版课程资料",
        "",
        "本版本严格拆分两套资料：",
        "",
        "- `official_student_delivery`：基于官方 101/201/251/301 PDF 的学生交付版教材。",
        "- `xmind_teacher_experience`：基于用户提供 XMind 的教师经验补充。",
        "",
        "处理原则：官方教材不混入 XMind 经验；XMind 经验不冒充官方知识点。所有截图均不嵌入，必要界面只标注官方 PDF 页码范围。",
        "",
    ]
    (OUT / "README.md").write_text("\n".join(readme), encoding="utf-8")

    source_rows = [["来源", "类型", "状态"]]
    for stage, entries in official.items():
        for _, entry in sorted(entries.items()):
            source_rows.append([f"{entry.pdf_key}.pdf {entry.kind} {entry.num}", "官方 PDF", f"{entry.title} / {entry.page_range}"])
    for source in xmind_sources:
        source_rows.append([str(source.path), "XMind 经验补充", f"可信节点 {source.clean_count}/{source.all_count}，图片 {source.image_count}"])
    (OUT / "SOURCE_AUDIT.md").write_text("# 来源审计\n\n" + md_table(source_rows) + "\n", encoding="utf-8")

    for stage in ["101", "201", "251", "301"]:
        student_md = STUDENT_OUT / f"Wwise_{stage}_Official_Student_Delivery.md"
        teacher_md = TEACHER_OUT / f"Wwise_{stage}_XMind_Teacher_Experience.md"
        student_md.write_text(student_stage_doc(stage, official), encoding="utf-8")
        teacher_md.write_text(teacher_stage_doc(stage, xmind_sources), encoding="utf-8")

    pdf_files = []
    for md_path in sorted(STUDENT_OUT.glob("*.md")) + sorted(TEACHER_OUT.glob("*.md")) + [OUT / "SOURCE_AUDIT.md"]:
        pdf_path = PDF_OUT / md_path.relative_to(OUT).with_suffix(".pdf")
        render_markdown_to_pdf(md_path, pdf_path)
        pdf_files.append(pdf_path)

    manifest = {
        "student_markdown": [str(p) for p in sorted(STUDENT_OUT.glob("*.md"))],
        "teacher_markdown": [str(p) for p in sorted(TEACHER_OUT.glob("*.md"))],
        "pdf": [str(p) for p in pdf_files],
        "xmind_sources": [
            {
                "path": str(source.path),
                "all_nodes": source.all_count,
                "clean_nodes": source.clean_count,
                "image_resources": source.image_count,
                "assigned_stages": XMIND_ASSIGNMENTS.get(source.path.name, []),
            }
            for source in xmind_sources
        ],
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Generated {len(pdf_files)} PDFs")
    for pdf in pdf_files:
        print(pdf)


if __name__ == "__main__":
    write_outputs()
