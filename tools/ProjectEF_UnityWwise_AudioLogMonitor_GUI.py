#!/usr/bin/env python3
import json
import os
import re
import socket
import subprocess
import threading
import time
import tkinter as tk
from collections import Counter
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText
import xml.etree.ElementTree as ET


DEFAULT_UNITY_ROOT = Path(r"D:\EF New\Client\TargetProject")
DEFAULT_WWISE_ROOT = Path(r"D:\EF Wwise\ProjectEF")
DEFAULT_OUT_DIR = Path(r"G:\AI\Material\Wwise")
REPORT_MD = DEFAULT_OUT_DIR / "ProjectEF_UnityWwise_GUI_RuntimeAudioMonitor.md"
REPORT_JSON = DEFAULT_OUT_DIR / "ProjectEF_UnityWwise_GUI_RuntimeAudioMonitor.json"
REPORT_JSONL = DEFAULT_OUT_DIR / "ProjectEF_UnityWwise_GUI_RuntimeAudioMonitor.jsonl"
REPORT_DIR = DEFAULT_OUT_DIR / "报告"
REPORT_MD_COPY = REPORT_DIR / REPORT_MD.name
REPORT_JSON_COPY = REPORT_DIR / REPORT_JSON.name

SCENARIOS = [
    {
        "id": "Fishing.Cast",
        "label": "Fishing / Cast",
        "patterns": [r"\bcast\b", r"\bthrow\b", r"lure.*(out|cast)", r"Play_.*Cast"],
    },
    {
        "id": "Fishing.LureWater",
        "label": "Fishing / Lure water in/out",
        "patterns": [r"Lure_Water(In|Out)", r"\blure\b.*water", r"water.*\blure\b"],
    },
    {
        "id": "Fishing.BiteSignal",
        "label": "Fishing / Bite or fish signal",
        "patterns": [r"\bbite\b", r"fish.*signal", r"Fish.*Bite", r"float", r"bobber"],
    },
    {
        "id": "Fishing.Fight",
        "label": "Fishing / Fight fish",
        "patterns": [r"\bfight\b", r"struggle", r"tension", r"drag", r"Fish.*Fight"],
    },
    {
        "id": "Fishing.ReelRetrieve",
        "label": "Fishing / Reel retrieve",
        "patterns": [r"Reel_Retrieve", r"Wheel_Retrieve", r"retrieve", r"spinningreel"],
    },
    {
        "id": "Fishing.LineOut",
        "label": "Fishing / Line out",
        "patterns": [r"Line_Out", r"line.*out", r"spool"],
    },
    {
        "id": "Fish.Water",
        "label": "Fish / Water movement",
        "patterns": [r"Fish_Water", r"\bfish\b.*water", r"splash"],
    },
    {
        "id": "Player.Footsteps",
        "label": "Player / Footsteps",
        "patterns": [r"Footstep", r"Footsteps", r"walk", r"run"],
    },
    {
        "id": "Player.BodyState",
        "label": "Player / Stamina or body temp",
        "patterns": [r"Stamina", r"BodyTemp", r"temperature", r"body.*temp"],
    },
    {
        "id": "Gear",
        "label": "Gear / Tools and equipment",
        "patterns": [r"\bGear\b", r"Rod", r"Reel", r"Hook", r"Line_", r"Tackle"],
    },
    {
        "id": "UI",
        "label": "UI / Menu and feedback",
        "patterns": [r"\bUI_", r"Button", r"Menu", r"Click", r"Confirm", r"Cancel"],
    },
    {
        "id": "Ambience.Weather",
        "label": "Ambience / Weather",
        "patterns": [r"Amb", r"Weather", r"Rain", r"Wind", r"Thunder", r"Day", r"Night"],
    },
    {
        "id": "Multiplayer",
        "label": "Multiplayer / Others",
        "patterns": [r"Others", r"OtherPlayer", r"Remote", r"Multiplayer", r"Player_Others"],
    },
]

SCENARIO_PATTERNS = {
    item["id"]: [re.compile(pattern, re.IGNORECASE) for pattern in item["patterns"]]
    for item in SCENARIOS
}


AUDIO_RE = re.compile(
    r"(wwise|audiokinetic|aksoundengine|akinitializer|akbank|akevent|akunity|ak\.wwise|"
    r"soundbank|generatedsoundbanks|postevent|loadbank|unloadbank|rtpc|setswitch|setstate|"
    r"\.bnk\b|\.wem\b|audio\s+plugin|audio\s+engine|ak_|ak::)",
    re.IGNORECASE,
)

ERROR_RE = re.compile(
    r"(error|exception|failed|failure\b|fatal|cannot|can't|could not|invalid|missing|not found|"
    r"denied|unauthorized|nullreference|argumentexception|indexoutofrange|idnotfound|filenotfound|"
    r"失败|错误|异常|无法|不能|未找到|找不到|缺失|退出播放)",
    re.IGNORECASE,
)

WARN_RE = re.compile(
    r"(warning|warn\b|deprecated|duplicate|not loaded|timeout|underrun|starvation|too many|overflow)",
    re.IGNORECASE,
)

EVENT_RE = re.compile(r"\b(?:Play|Stop|Pause|Resume|Set|Reset|Mute|Unmute|Stinger|Music|VO|UI|SFX|Amb|Loop)_[A-Za-z0-9_]+\b")

CATEGORY_RULES = [
    ("License", re.compile(r"(license|no license key|trial)", re.IGNORECASE)),
    ("InitOrPlugin", re.compile(r"(initialize|initializer|init\b|plugin|dll|version mismatch|akunitysoundengine)", re.IGNORECASE)),
    ("BankOrMedia", re.compile(r"(bank|soundbank|loadbank|unloadbank|\.bnk\b|\.wem\b|media|file not found|bankread|加载event|加载.*bank)", re.IGNORECASE)),
    ("Event", re.compile(r"(postevent|event id|event not found|idnotfound|akevent|executeactiononevent)", re.IGNORECASE)),
    ("RTPCSwitchState", re.compile(r"(rtpc|switch|state|setrtpc|setswitch|setstate|game parameter)", re.IGNORECASE)),
    ("UnityException", re.compile(r"(exception|nullreference|argumentexception|stack trace|missingreference)", re.IGNORECASE)),
    ("BuildOrPackaging", re.compile(r"(build|package|streamingassets|generatedsoundbanks|deploy|copying)", re.IGNORECASE)),
    ("Performance", re.compile(r"(underrun|starvation|voice|memory|cpu|latency|overflow|too many)", re.IGNORECASE)),
]

SEVERITY_RANK = {"Error": 3, "Warn": 2, "Info": 1}


def read_text(path: Path, max_bytes: int = 20 * 1024 * 1024) -> str | None:
    try:
        if not path.exists() or path.stat().st_size > max_bytes:
            return None
        return path.read_text(encoding="utf-8-sig", errors="replace")
    except Exception:
        return None


def parse_project_settings(unity_root: Path) -> dict:
    text = read_text(unity_root / "ProjectSettings" / "ProjectSettings.asset", 2 * 1024 * 1024)
    if not text:
        return {}
    result = {}
    for key in ("companyName", "productName"):
        match = re.search(rf"^\s*{key}:\s*(.+?)\s*$", text, re.MULTILINE)
        if match:
            result[key] = match.group(1).strip().strip('"')
    return result


def discover_logs(unity_root: Path) -> list[Path]:
    candidates = []
    local_app = os.environ.get("LOCALAPPDATA")
    user_profile = os.environ.get("USERPROFILE")
    if local_app:
        candidates.append(Path(local_app) / "Unity" / "Editor" / "Editor.log")
        candidates.append(Path(local_app) / "Unity" / "Editor" / "Editor-prev.log")
    if unity_root.exists():
        for sub in ("Logs", "BuildLogs"):
            folder = unity_root / sub
            if folder.exists():
                for ext in ("*.log", "*.txt"):
                    candidates.extend(folder.rglob(ext))
        settings = parse_project_settings(unity_root)
        company = settings.get("companyName")
        product = settings.get("productName")
        if user_profile and company and product:
            candidates.append(Path(user_profile) / "AppData" / "LocalLow" / company / product / "Player.log")

    unique = []
    seen = set()
    for path in candidates:
        if not path.exists() or not path.is_file():
            continue
        try:
            resolved = path.resolve()
        except Exception:
            resolved = path
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(path)
    return sorted(unique, key=lambda p: str(p).lower())


def parse_wwise_events(wwise_root: Path) -> set[str]:
    events = set()
    if not wwise_root.exists():
        return events
    for xml_path in list(wwise_root.rglob("*.wwu")) + list(wwise_root.rglob("SoundbanksInfo.xml")):
        text = read_text(xml_path, 15 * 1024 * 1024)
        if not text:
            continue
        for match in re.finditer(r"<Event\b[^>]*\bName=\"([^\"]+)\"", text):
            events.add(match.group(1))
        try:
            root = ET.fromstring(text)
            for elem in root.iter():
                if elem.tag.split("}")[-1] == "Event":
                    name = elem.attrib.get("Name") or elem.attrib.get("name")
                    if name:
                        events.add(name)
        except Exception:
            pass
    return events


def severity(line: str) -> str:
    if is_bank_or_media_manifest_line(line) and not has_explicit_runtime_error(line):
        return "Info"
    if ERROR_RE.search(line):
        return "Error"
    if WARN_RE.search(line):
        return "Warn"
    return "Info"


def category(line: str) -> str:
    for label, pattern in CATEGORY_RULES:
        if pattern.search(line):
            return label
    return "Audio"


def is_bank_or_media_manifest_line(line: str) -> bool:
    return bool(re.match(r"\s*(Bank ID|Media File ID):", line, re.IGNORECASE))


def has_explicit_runtime_error(line: str) -> bool:
    return bool(
        re.search(
            r"(\(ERROR\)|\berror\b|exception|failed|failure\b|fatal|cannot|can't|could not|"
            r"invalid|missing|not found|denied|unauthorized|nullreference|argumentexception|"
            r"indexoutofrange|idnotfound|filenotfound|失败|错误|异常|无法|不能|未找到|找不到|缺失|退出播放)",
            line,
            re.IGNORECASE,
        )
    )


def should_check_unknown_events(cat: str, line: str) -> bool:
    lower = line.lower()
    if is_bank_or_media_manifest_line(line):
        return False
    return (
        cat == "Event"
        or "playaudio:" in lower
        or "postevent" in lower
        or "executeactiononevent" in lower
        or "加载event:" in lower
    )


def infer_reason(cat: str, line: str, events: list[str], known_events: set[str]) -> tuple[str, str, str]:
    lower = line.lower()
    unknown = [event for event in events if known_events and event not in known_events]
    if unknown:
        return (
            "High",
            "Event name appears in the log but was not found in the parsed Wwise project.",
            "Check spelling, generated AK constants, SoundBank contents, and whether the Wwise project was saved/generated.",
        )
    if cat == "License":
        return ("High", "Wwise license state may limit generation or packaging.", "Restore the project license, then regenerate SoundBanks.")
    if cat == "BankOrMedia":
        if "加载event:" in lower and "stop_" in lower and ("失败" in lower or "退出播放" in lower):
            return (
                "High",
                "A Stop Event bank failed to load, so the Stop Event likely never reached Wwise.",
                "Check whether the Stop bank is already loaded but treated as failure, whether the bank asset/bundle is present, and whether Stop can be replaced by StopAudio/StopPlayingID or a preloaded/shared control bank.",
            )
        if "加载event:" in lower and ("失败" in lower or "退出播放" in lower):
            return (
                "High",
                "An Event bank failed to load, so this Event likely did not reach Wwise.",
                "Check whether the bank is missing from the runtime package, whether the wrong platform/path is used, or whether an already-loaded bank is returned as AK_INVALID_UNIQUE_ID and then treated as a fatal failure.",
            )
        if "not found" in lower or "missing" in lower or "filenotfound" in lower:
            return ("High", "Bank/media file is likely missing or the platform path is wrong.", "Regenerate SoundBanks and verify Unity output paths.")
        return ("Medium", "Bank/media lifecycle needs verification.", "Check Bank load order, unload timing, platform folder, and SoundbanksInfo.xml.")
    if cat == "Event":
        return ("Medium", "Event send/lookup path needs verification.", "Check trigger condition, registered GameObject, Event field/name, and Bank load state.")
    if cat == "RTPCSwitchState":
        return ("Medium", "Parameter name, scope, or timing may be wrong.", "Check Wwise parameter existence, Unity set timing, and GameObject/global scope.")
    if cat == "InitOrPlugin":
        return ("Medium", "Wwise initialization or plugin load path may be abnormal.", "Check Integration version, platform DLLs, architecture folder, and SDK/Authoring version.")
    if cat == "UnityException":
        return ("Medium", "Unity exception may block the audio trigger path.", "Use stack trace to find missing references or lifecycle ordering problems.")
    if cat == "Performance":
        return ("Medium", "Audio performance or voice density may be abnormal.", "Check high-frequency posting, voice limit, virtual voice, loop stop logic, and Wwise Profiler.")
    return ("Low", "Audio-related line with no specific rule hit.", "Correlate with Unity action, Wwise Profiler, and nearby log context.")


class AudioMonitorApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("ProjectEF Unity/Wwise Audio Log Monitor")
        self.root.geometry("1180x760")
        self.root.minsize(960, 620)

        self.running = False
        self.logs: list[Path] = []
        self.positions: dict[Path, int] = {}
        self.line_counts: dict[Path, int] = {}
        self.known_events: set[str] = set()
        self.entries = []
        self.findings = []
        self.issue_groups = {}
        self.issue_filter_keys: set[str] = set()
        self._suppress_issue_selection_event = False
        self.category_counts = Counter()
        self.severity_counts = Counter()
        self.event_counts = Counter()
        self.coverage_observed_counts = Counter()
        self.coverage_warn_counts = Counter()
        self.coverage_error_counts = Counter()
        self.last_report_time = 0.0
        self.last_log_activity_at = 0.0
        self.last_audio_line_at = 0.0
        self.lock = threading.Lock()

        self.unity_root_var = tk.StringVar(value=str(DEFAULT_UNITY_ROOT))
        self.wwise_root_var = tk.StringVar(value=str(DEFAULT_WWISE_ROOT))
        self.filter_var = tk.StringVar(value="All audio")
        self.search_var = tk.StringVar(value="")
        self.read_existing_var = tk.BooleanVar(value=False)
        self.autoscroll_var = tk.BooleanVar(value=True)
        self.connection_monitor_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value="Stopped")
        self.log_status_var = tk.StringVar(value="Logs: not scanned")
        self.wwise_status_var = tk.StringVar(value="Wwise: not loaded")
        self.findings_var = tk.StringVar(value="Issues: 0 / Findings: 0")
        self.last_line_var = tk.StringVar(value="Last audio line: -")
        self.log_scope_var = tk.StringVar(value="Runtime audio log - all audio")
        self.connection_status_var = tk.StringVar(value="Connection: not checked")
        self.bank_diag_summary_var = tk.StringVar(value="Bank diagnostics: not checked")
        self.bank_diag_detail_var = tk.StringVar(value="Top failed Events: not checked")
        self.session_name_var = tk.StringVar(value=datetime.now().strftime("Audio QA %Y-%m-%d %H:%M"))
        self.scene_var = tk.StringVar(value="")
        self.perspective_var = tk.StringVar(value="")
        self.mode_var = tk.StringVar(value="")
        self.character_var = tk.StringVar(value="")
        self.gear_var = tk.StringVar(value="")
        self.fish_var = tk.StringVar(value="")
        self.weather_var = tk.StringVar(value="")
        self.coverage_vars = {
            item["id"]: tk.BooleanVar(value=False)
            for item in SCENARIOS
        }

        self.build_ui()
        self.refresh_logs()
        self.load_wwise_events_async()
        self.root.after(500, self.poll_logs)
        self.root.after(1500, self.poll_connection_status)

    def build_ui(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("TButton", padding=6)
        style.configure("TLabel", padding=2)

        top = ttk.Frame(self.root, padding=(10, 8))
        top.pack(fill=tk.X)

        ttk.Label(top, text="Unity").grid(row=0, column=0, sticky="w")
        unity_entry = ttk.Entry(top, textvariable=self.unity_root_var)
        unity_entry.grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(top, text="Browse", command=self.browse_unity).grid(row=0, column=2, padx=(0, 8))

        ttk.Label(top, text="Wwise").grid(row=1, column=0, sticky="w")
        wwise_entry = ttk.Entry(top, textvariable=self.wwise_root_var)
        wwise_entry.grid(row=1, column=1, sticky="ew", padx=6)
        ttk.Button(top, text="Browse", command=self.browse_wwise).grid(row=1, column=2, padx=(0, 8))

        controls = ttk.Frame(top)
        controls.grid(row=0, column=3, rowspan=2, sticky="ns")
        ttk.Button(controls, text="Start", command=self.start).grid(row=0, column=0, padx=3, pady=2)
        ttk.Button(controls, text="Stop", command=self.stop).grid(row=0, column=1, padx=3, pady=2)
        ttk.Button(controls, text="Refresh Logs", command=self.refresh_logs).grid(row=0, column=2, padx=3, pady=2)
        ttk.Button(controls, text="Clear", command=self.clear).grid(row=1, column=0, padx=3, pady=2)
        ttk.Button(controls, text="Open Report", command=lambda: self.open_path(REPORT_MD)).grid(row=1, column=1, padx=3, pady=2)
        ttk.Button(controls, text="Open Folder", command=lambda: self.open_path(DEFAULT_OUT_DIR)).grid(row=1, column=2, padx=3, pady=2)
        top.columnconfigure(1, weight=1)

        options = ttk.Frame(self.root, padding=(10, 0, 10, 8))
        options.pack(fill=tk.X)
        ttk.Checkbutton(options, text="Read existing log content on Start", variable=self.read_existing_var).pack(side=tk.LEFT)
        ttk.Checkbutton(options, text="Auto scroll", variable=self.autoscroll_var).pack(side=tk.LEFT, padx=(16, 0))
        ttk.Checkbutton(options, text="Connection monitor", variable=self.connection_monitor_var).pack(side=tk.LEFT, padx=(16, 0))
        ttk.Label(options, text="Filter").pack(side=tk.LEFT, padx=(20, 4))
        filter_box = ttk.Combobox(options, textvariable=self.filter_var, state="readonly", width=16)
        filter_box["values"] = ("All audio", "Warn + Error", "Error only")
        filter_box.pack(side=tk.LEFT)
        filter_box.bind("<<ComboboxSelected>>", self.on_filter_changed)
        ttk.Label(options, text="Search").pack(side=tk.LEFT, padx=(20, 4))
        search_entry = ttk.Entry(options, textvariable=self.search_var, width=28)
        search_entry.pack(side=tk.LEFT)
        search_entry.bind("<KeyRelease>", self.on_filter_changed)
        ttk.Button(options, text="Reset filters", command=self.reset_filters).pack(side=tk.LEFT, padx=(8, 0))

        status = ttk.Frame(self.root, padding=(10, 0, 10, 8))
        status.pack(fill=tk.X)
        for var in (
            self.status_var,
            self.log_status_var,
            self.wwise_status_var,
            self.findings_var,
            self.last_line_var,
            self.connection_status_var,
        ):
            ttk.Label(status, textvariable=var, relief=tk.GROOVE, anchor="w").pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))

        body = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        body.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        left = ttk.Frame(body)
        right = ttk.Frame(body)
        body.add(left, weight=4)
        body.add(right, weight=1)

        ttk.Label(left, textvariable=self.log_scope_var).pack(anchor="w")
        self.log_text = ScrolledText(left, wrap=tk.WORD, font=("Consolas", 10), undo=False)
        self.log_text.pack(fill=tk.BOTH, expand=True)
        self.log_text.tag_configure("Error", foreground="#b42318")
        self.log_text.tag_configure("Warn", foreground="#9a6700")
        self.log_text.tag_configure("Info", foreground="#344054")

        right_tabs = ttk.Notebook(right)
        right_tabs.pack(fill=tk.BOTH, expand=True)

        issues_tab = ttk.Frame(right_tabs, padding=(0, 4, 0, 0))
        coverage_tab = ttk.Frame(right_tabs, padding=(0, 4, 0, 0))
        right_tabs.add(issues_tab, text="Issues")
        right_tabs.add(coverage_tab, text="Coverage")

        ttk.Label(issues_tab, text="Known log files").pack(anchor="w")
        self.log_list = tk.Listbox(issues_tab, height=7)
        self.log_list.pack(fill=tk.X, pady=(0, 8))

        issue_header = ttk.Frame(issues_tab)
        issue_header.pack(fill=tk.X)
        ttk.Label(issue_header, text="Problem screening").pack(side=tk.LEFT, anchor="w")
        ttk.Button(issue_header, text="Select all", command=self.select_all_issues).pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(issue_header, text="Invert", command=self.invert_issue_selection).pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(issue_header, text="Show all logs", command=self.clear_issue_selection).pack(side=tk.RIGHT, padx=(4, 0))
        self.issue_tree = ttk.Treeview(
            issues_tab,
            columns=("severity", "kind", "count", "last", "event"),
            show="headings",
            height=10,
            selectmode="extended",
        )
        for column, title, width, anchor in (
            ("severity", "Sev", 56, "center"),
            ("kind", "Type", 170, "w"),
            ("count", "Count", 56, "center"),
            ("last", "Last", 72, "center"),
            ("event", "Event", 150, "w"),
        ):
            self.issue_tree.heading(column, text=title)
            self.issue_tree.column(column, width=width, minwidth=40, anchor=anchor, stretch=(column in {"kind", "event"}))
        self.issue_tree.pack(fill=tk.BOTH, expand=True, pady=(0, 8))
        self.issue_tree.bind("<<TreeviewSelect>>", self.show_selected_issue)

        ttk.Label(issues_tab, text="Analysis suggestion").pack(anchor="w")
        self.analysis_text = ScrolledText(issues_tab, height=13, wrap=tk.WORD, font=("Segoe UI", 9))
        self.analysis_text.pack(fill=tk.BOTH, expand=False)

        self.build_coverage_tab(coverage_tab)

    def build_coverage_tab(self, parent: ttk.Frame):
        session = ttk.LabelFrame(parent, text="Test session metadata", padding=8)
        session.pack(fill=tk.X, pady=(0, 8))
        fields = [
            ("Session", self.session_name_var),
            ("Scene/Map", self.scene_var),
            ("Perspective", self.perspective_var),
            ("Mode", self.mode_var),
            ("Character", self.character_var),
            ("Gear", self.gear_var),
            ("Fish", self.fish_var),
            ("Weather", self.weather_var),
        ]
        for index, (label, var) in enumerate(fields):
            row = index // 2
            col = (index % 2) * 2
            ttk.Label(session, text=label).grid(row=row, column=col, sticky="w", padx=(0, 4), pady=2)
            ttk.Entry(session, textvariable=var, width=18).grid(row=row, column=col + 1, sticky="ew", padx=(0, 8), pady=2)
        session.columnconfigure(1, weight=1)
        session.columnconfigure(3, weight=1)

        scenario_box = ttk.LabelFrame(parent, text="Planned scenarios for this run", padding=8)
        scenario_box.pack(fill=tk.X, pady=(0, 8))
        for index, item in enumerate(SCENARIOS):
            cb = ttk.Checkbutton(
                scenario_box,
                text=item["label"],
                variable=self.coverage_vars[item["id"]],
                command=self.coverage_changed,
            )
            cb.grid(row=index // 2, column=index % 2, sticky="w", padx=(0, 8), pady=2)
        scenario_box.columnconfigure(0, weight=1)
        scenario_box.columnconfigure(1, weight=1)

        buttons = ttk.Frame(parent)
        buttons.pack(fill=tk.X, pady=(0, 8))
        ttk.Button(buttons, text="Select all", command=lambda: self.set_all_coverage(True)).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Clear planned", command=lambda: self.set_all_coverage(False)).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(buttons, text="Write report now", command=self.write_report).pack(side=tk.LEFT, padx=(6, 0))

        bank_box = ttk.LabelFrame(parent, text="Bank diagnostics", padding=8)
        bank_box.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(bank_box, textvariable=self.bank_diag_summary_var, wraplength=560).pack(anchor="w", fill=tk.X)
        ttk.Label(bank_box, textvariable=self.bank_diag_detail_var).pack(anchor="w", fill=tk.X)
        bank_buttons = ttk.Frame(bank_box)
        bank_buttons.pack(fill=tk.X, pady=(4, 6))
        ttk.Button(bank_buttons, text="Refresh Bank Diagnostics", command=self.refresh_bank_diagnostics).pack(side=tk.LEFT)
        self.bank_diag_tree = ttk.Treeview(
            bank_box,
            columns=("event", "exists", "modified", "kb"),
            show="headings",
            height=5,
        )
        for column, title, width, anchor in (
            ("event", "Top failed Event", 230, "w"),
            ("exists", "Has .bnk", 70, "center"),
            ("modified", "Modified", 150, "center"),
            ("kb", "KB", 70, "e"),
        ):
            self.bank_diag_tree.heading(column, text=title)
            self.bank_diag_tree.column(column, width=width, minwidth=48, anchor=anchor, stretch=(column == "event"))
        self.bank_diag_tree.pack(fill=tk.X)

        ttk.Label(parent, text="Coverage matrix").pack(anchor="w")
        self.coverage_tree = ttk.Treeview(
            parent,
            columns=("planned", "observed", "issues", "status"),
            show="tree headings",
            height=12,
        )
        self.coverage_tree.heading("#0", text="Scenario")
        self.coverage_tree.column("#0", width=220, minwidth=160, stretch=True)
        for column, title, width, anchor in (
            ("planned", "Planned", 70, "center"),
            ("observed", "Observed", 78, "center"),
            ("issues", "Issues", 62, "center"),
            ("status", "Status", 130, "center"),
        ):
            self.coverage_tree.heading(column, text=title)
            self.coverage_tree.column(column, width=width, minwidth=48, anchor=anchor, stretch=False)
        self.coverage_tree.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

        ttk.Label(parent, text="Tester notes").pack(anchor="w")
        self.session_notes_text = ScrolledText(parent, height=6, wrap=tk.WORD, font=("Segoe UI", 9))
        self.session_notes_text.pack(fill=tk.BOTH, expand=False)
        self.refresh_bank_diagnostics()
        self.refresh_coverage_tree()

    def set_all_coverage(self, value: bool):
        for var in self.coverage_vars.values():
            var.set(value)
        self.coverage_changed()

    def coverage_changed(self):
        self.refresh_coverage_tree()
        self.write_report()

    def browse_unity(self):
        path = filedialog.askdirectory(initialdir=self.unity_root_var.get() or str(DEFAULT_UNITY_ROOT))
        if path:
            self.unity_root_var.set(path)
            self.refresh_logs()

    def browse_wwise(self):
        path = filedialog.askdirectory(initialdir=self.wwise_root_var.get() or str(DEFAULT_WWISE_ROOT))
        if path:
            self.wwise_root_var.set(path)
            self.load_wwise_events_async()

    def refresh_logs(self):
        unity_root = Path(self.unity_root_var.get())
        self.logs = discover_logs(unity_root)
        self.log_list.delete(0, tk.END)
        for path in self.logs:
            self.log_list.insert(tk.END, str(path))
        if self.logs:
            self.log_status_var.set(f"Logs: {len(self.logs)} found")
        else:
            self.log_status_var.set("Logs: none found")

    def load_wwise_events_async(self):
        self.wwise_status_var.set("Wwise: loading events...")

        def worker():
            events = parse_wwise_events(Path(self.wwise_root_var.get()))
            self.root.after(0, lambda: self.set_wwise_events(events))

        threading.Thread(target=worker, daemon=True).start()

    def set_wwise_events(self, events: set[str]):
        self.known_events = events
        self.wwise_status_var.set(f"Wwise: {len(events)} events loaded" if events else "Wwise: no events loaded")

    def start(self):
        if self.running:
            return
        self.refresh_logs()
        if not self.logs:
            messagebox.showwarning("No logs", "No Unity Editor/Player/project logs were found.")
            return
        self.positions.clear()
        self.line_counts.clear()
        for path in self.logs:
            try:
                if self.read_existing_var.get():
                    self.positions[path] = 0
                    self.line_counts[path] = 0
                else:
                    self.positions[path] = path.stat().st_size
                    self.line_counts[path] = self.count_lines(path)
            except Exception:
                self.positions[path] = 0
                self.line_counts[path] = 0
        self.running = True
        self.update_filter_status("Running: waiting for audio log lines.")
        DEFAULT_OUT_DIR.mkdir(parents=True, exist_ok=True)
        self.write_report()

    def stop(self):
        self.running = False
        self.update_filter_status("Stopped.")
        self.write_report()

    def filter_summary(self) -> str:
        query = self.search_var.get().strip()
        search_text = f"search='{query}'" if query else "no search"
        issue_count = len(self.selected_issue_keys()) if hasattr(self, "issue_tree") else 0
        issue_text = f"{issue_count} selected issue group(s)" if issue_count else "all issue groups"
        return f"Filters: {self.filter_var.get()} / {search_text} / {issue_text}"

    def update_filter_status(self, prefix: str | None = None):
        summary = self.filter_summary()
        if prefix:
            self.status_var.set(f"{prefix} {summary}")
        elif self.running:
            self.status_var.set(f"Running: waiting for audio log lines. {summary}")
        else:
            self.status_var.set(f"Stopped. {summary}")

    def on_filter_changed(self, _event=None):
        self.redraw()
        self.update_filter_status("Filter updated.")

    def reset_filters(self):
        self.filter_var.set("All audio")
        self.search_var.set("")
        self.issue_filter_keys.clear()
        if hasattr(self, "issue_tree"):
            keys = list(self.issue_tree.get_children())
            if keys:
                self._suppress_issue_selection_event = True
                try:
                    self.issue_tree.selection_remove(*keys)
                finally:
                    self._suppress_issue_selection_event = False
        if hasattr(self, "analysis_text"):
            self.analysis_text.delete("1.0", tk.END)
            self.analysis_text.insert(
                tk.END,
                "No problem selected.\n\nRuntime audio log is showing all audio lines.\n\nSelect one or more rows above to filter the Runtime audio log to those grouped issues.",
            )
        self.log_scope_var.set("Runtime audio log - all audio")
        self.redraw()
        self.update_filter_status("Filters reset.")

    def clear(self):
        was_running = self.running
        self.entries.clear()
        self.findings.clear()
        self.issue_groups.clear()
        self.issue_filter_keys.clear()
        self.category_counts.clear()
        self.severity_counts.clear()
        self.event_counts.clear()
        self.coverage_observed_counts.clear()
        self.coverage_warn_counts.clear()
        self.coverage_error_counts.clear()
        self.log_text.delete("1.0", tk.END)
        for item in self.issue_tree.get_children():
            self.issue_tree.delete(item)
        self.refresh_coverage_tree()
        self.analysis_text.delete("1.0", tk.END)
        self.findings_var.set("Issues: 0 / Findings: 0")
        self.last_line_var.set("Last audio line: -")
        self.last_audio_line_at = 0.0
        self.log_scope_var.set("Runtime audio log - all audio")
        if not was_running:
            self.reset_tail_positions()
        self.clear_session_files()
        if was_running:
            self.update_filter_status("Cleared display; monitor is still running and waiting for new audio log lines.")
        else:
            self.update_filter_status("Cleared current monitor session.")
        self.write_report()

    def reset_tail_positions(self):
        for path in list(self.logs):
            try:
                self.positions[path] = path.stat().st_size
                self.line_counts[path] = self.count_lines(path)
            except Exception:
                self.positions[path] = 0
                self.line_counts[path] = 0

    def clear_session_files(self):
        try:
            DEFAULT_OUT_DIR.mkdir(parents=True, exist_ok=True)
            REPORT_JSONL.write_text("", encoding="utf-8-sig")
        except Exception as exc:
            self.status_var.set(f"Clear output file failed: {exc}")

    def count_lines(self, path: Path) -> int:
        text = read_text(path, 200 * 1024 * 1024)
        return len(text.splitlines()) if text else 0

    def poll_logs(self):
        if self.running:
            for path in list(self.logs):
                self.read_new_lines(path)
            if time.time() - self.last_report_time > 5:
                self.write_report()
                self.last_report_time = time.time()
        self.root.after(500, self.poll_logs)

    def process_running(self, image_name: str) -> bool:
        try:
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            result = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {image_name}", "/NH"],
                capture_output=True,
                text=True,
                timeout=1.5,
                creationflags=flags,
            )
            return image_name.lower() in result.stdout.lower()
        except Exception:
            return False

    def tcp_port_open(self, host: str, port: int, timeout: float = 0.25) -> bool:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            return False

    def newest_log_age(self) -> str:
        newest = 0.0
        for path in self.logs:
            try:
                newest = max(newest, path.stat().st_mtime)
            except Exception:
                pass
        if newest <= 0:
            return "no log file"
        age = max(0, int(time.time() - newest))
        if age < 60:
            return f"{age}s ago"
        return f"{age // 60}m ago"

    def audio_line_age(self) -> str:
        if self.last_audio_line_at <= 0:
            return "none"
        age = max(0, int(time.time() - self.last_audio_line_at))
        if age < 60:
            return f"{age}s ago"
        return f"{age // 60}m ago"

    def poll_connection_status(self):
        if self.connection_monitor_var.get():
            unity = "Unity OK" if self.process_running("Unity.exe") else "Unity missing"
            wwise = "Wwise OK" if self.process_running("Wwise.exe") else "Wwise missing"
            logs = f"Logs {len(self.logs)} / latest {self.newest_log_age()}"
            audio = f"Audio {self.audio_line_age()}"
            waapi = "WAAPI open" if self.tcp_port_open("127.0.0.1", 8080) else "WAAPI optional closed"
            self.connection_status_var.set(
                f"Connection: {unity} | {wwise} | {logs} | {audio} | {waapi}"
            )
        else:
            self.connection_status_var.set("Connection: monitor off")
        self.root.after(3000, self.poll_connection_status)

    def read_new_lines(self, path: Path):
        if not path.exists():
            return
        try:
            size = path.stat().st_size
            if size < self.positions.get(path, 0):
                self.positions[path] = 0
                self.line_counts[path] = 0
            with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
                handle.seek(self.positions.get(path, 0))
                chunk = handle.read()
                self.positions[path] = handle.tell()
        except Exception as exc:
            self.status_var.set(f"Read error: {exc}")
            return
        if not chunk:
            return
        self.last_log_activity_at = time.time()
        for line in chunk.splitlines():
            self.line_counts[path] = self.line_counts.get(path, 0) + 1
            self.process_line(path, self.line_counts[path], line)

    def process_line(self, path: Path, line_no: int, line: str):
        if not AUDIO_RE.search(line):
            return
        sev = severity(line)
        cat = category(line)
        events = EVENT_RE.findall(line)
        entry = {
            "time": datetime.now().isoformat(timespec="seconds"),
            "file": str(path),
            "line": line_no,
            "severity": sev,
            "category": cat,
            "events": events,
            "text": line.strip(),
        }
        self.entries.append(entry)
        self.last_audio_line_at = time.time()
        self.category_counts[cat] += 1
        self.severity_counts[sev] += 1
        for event in events:
            self.event_counts[event] += 1

        abnormal = sev in {"Error", "Warn"}
        if should_check_unknown_events(cat, line) and events and self.known_events:
            abnormal = abnormal or any(event not in self.known_events for event in events)
        self.update_coverage_from_entry(entry, abnormal)
        if abnormal:
            confidence, cause, rec = infer_reason(cat, line, events, self.known_events)
            finding = {
                **entry,
                "confidence": confidence,
                "likely_cause": cause,
                "recommendation": rec,
            }
            issue_key = self.register_finding(finding)
            entry["issue_key"] = issue_key
            entry["issue_type"] = finding.get("issue_type", "")

        self.last_line_var.set(f"Last audio line: {Path(path).name}:{line_no}")
        self.findings_var.set(f"Issues: {len(self.issue_groups)} / Findings: {len(self.findings)}")
        self.append_entry_if_visible(entry)
        self.append_jsonl(entry)

    def update_coverage_from_entry(self, entry: dict, abnormal: bool):
        text = " ".join(
            [
                entry.get("text", ""),
                entry.get("category", ""),
                " ".join(entry.get("events", [])),
            ]
        )
        matched = []
        for scenario_id, patterns in SCENARIO_PATTERNS.items():
            if any(pattern.search(text) for pattern in patterns):
                matched.append(scenario_id)
        if not matched:
            return
        for scenario_id in matched:
            self.coverage_observed_counts[scenario_id] += 1
            if abnormal:
                if entry.get("severity") == "Error":
                    self.coverage_error_counts[scenario_id] += 1
                else:
                    self.coverage_warn_counts[scenario_id] += 1
        self.refresh_coverage_tree()

    def coverage_status(self, scenario_id: str) -> str:
        planned = self.coverage_vars[scenario_id].get()
        observed = self.coverage_observed_counts.get(scenario_id, 0)
        errors = self.coverage_error_counts.get(scenario_id, 0)
        warns = self.coverage_warn_counts.get(scenario_id, 0)
        if planned and observed and errors:
            return "ObservedFail"
        if planned and observed and warns:
            return "ObservedWarn"
        if planned and observed:
            return "ObservedPass"
        if planned and not observed:
            return "PlannedNotObserved"
        if not planned and observed and errors:
            return "ObservedUnplannedFail"
        if not planned and observed:
            return "ObservedUnplanned"
        return "NotObserved"

    def coverage_matrix(self) -> list[dict]:
        rows = []
        for item in SCENARIOS:
            scenario_id = item["id"]
            rows.append(
                {
                    "id": scenario_id,
                    "label": item["label"],
                    "planned": bool(self.coverage_vars[scenario_id].get()),
                    "observed_audio_lines": int(self.coverage_observed_counts.get(scenario_id, 0)),
                    "warns": int(self.coverage_warn_counts.get(scenario_id, 0)),
                    "errors": int(self.coverage_error_counts.get(scenario_id, 0)),
                    "status": self.coverage_status(scenario_id),
                }
            )
        return rows

    def session_metadata(self) -> dict:
        notes = ""
        if hasattr(self, "session_notes_text"):
            notes = self.session_notes_text.get("1.0", tk.END).strip()
        return {
            "session_name": self.session_name_var.get().strip(),
            "scene_or_map": self.scene_var.get().strip(),
            "perspective": self.perspective_var.get().strip(),
            "mode": self.mode_var.get().strip(),
            "character": self.character_var.get().strip(),
            "gear": self.gear_var.get().strip(),
            "fish": self.fish_var.get().strip(),
            "weather": self.weather_var.get().strip(),
            "tester_notes": notes,
        }

    def latest_report_json(self, pattern: str) -> Path | None:
        candidates = []
        for root in (REPORT_DIR, DEFAULT_OUT_DIR):
            if not root.exists():
                continue
            candidates.extend(path for path in root.glob(pattern) if path.is_file())
        if not candidates:
            return None
        return max(candidates, key=lambda path: path.stat().st_mtime)

    def bank_diagnostics_payload(self) -> dict:
        path = self.latest_report_json("ProjectEF_RuntimeBankOutput_Check_*.json")
        if not path:
            return {
                "status": "Missing",
                "summary": "No Runtime Bank Output Check JSON found.",
                "source_json": "",
                "bank_root": "",
                "event_dir": "",
                "authored_event_count": 0,
                "runtime_event_bank_count": 0,
                "missing_event_banks": [],
                "extra_event_banks": [],
                "top_event_bank_status": [],
                "live_failed_event_bank_status": [],
            }

        try:
            data = json.loads(path.read_text(encoding="utf-8-sig", errors="replace"))
        except Exception as exc:
            return {
                "status": "LoadError",
                "summary": f"Runtime Bank Output Check JSON could not be read: {exc}",
                "source_json": str(path),
                "bank_root": "",
                "event_dir": "",
                "authored_event_count": 0,
                "runtime_event_bank_count": 0,
                "missing_event_banks": [],
                "extra_event_banks": [],
                "top_event_bank_status": [],
                "live_failed_event_bank_status": [],
            }

        missing = list(data.get("missing_event_banks") or [])
        extra = list(data.get("extra_event_banks") or [])
        status = "PASS" if not missing and not extra else "CHECK"
        event_dir_text = str(data.get("event_dir") or "")
        event_dir = Path(event_dir_text) if event_dir_text else None
        top_rows = list(data.get("top_event_bank_status") or [])

        live_events = []
        for group in self.issue_group_payloads():
            if group.get("type") in {"EventBankLoadFailed", "StopEventBankLoadFailed", "BankOrMedia"}:
                for event in group.get("events") or [group.get("event_hint", "")]:
                    if event and event not in live_events:
                        live_events.append(event)
        live_rows = []
        for event in live_events[:20]:
            bank_path = event_dir / f"{event}.bnk" if event_dir else None
            live_rows.append(
                {
                    "event": event,
                    "exists": bank_path.exists() if bank_path else False,
                    "path": str(bank_path) if bank_path else "",
                }
            )

        summary = (
            f"Bank root: {data.get('bank_root', '-')} | "
            f"Events {data.get('runtime_event_bank_count', 0)}/{data.get('authored_event_count', 0)} | "
            f"missing={len(missing)} extra={len(extra)} | status={status}"
        )
        return {
            "status": status,
            "summary": summary,
            "source_json": str(path),
            "generated_at": data.get("generated_at", ""),
            "bank_root": data.get("bank_root", ""),
            "event_dir": data.get("event_dir", ""),
            "authored_event_count": data.get("authored_event_count", 0),
            "runtime_event_bank_count": data.get("runtime_event_bank_count", 0),
            "missing_event_banks": missing,
            "extra_event_banks": extra,
            "soundbanks_info": data.get("soundbanks_info", {}),
            "top_event_bank_status": top_rows,
            "live_failed_event_bank_status": live_rows,
        }

    def refresh_bank_diagnostics(self):
        payload = self.bank_diagnostics_payload()
        self.bank_diag_summary_var.set(f"Bank diagnostics: {payload.get('summary', '-')}")
        top_rows = payload.get("top_event_bank_status") or []
        present = sum(1 for item in top_rows if item.get("exists"))
        self.bank_diag_detail_var.set(f"Top failed Events with .bnk: {present}/{len(top_rows)}")
        if hasattr(self, "bank_diag_tree"):
            for item in self.bank_diag_tree.get_children():
                self.bank_diag_tree.delete(item)
            for row in top_rows:
                self.bank_diag_tree.insert(
                    "",
                    tk.END,
                    values=(
                        row.get("event", "-"),
                        "Yes" if row.get("exists") else "No",
                        row.get("modified", "-"),
                        row.get("size_kb", "-"),
                    ),
                )

    def refresh_coverage_tree(self):
        if not hasattr(self, "coverage_tree"):
            return
        for item in self.coverage_tree.get_children():
            self.coverage_tree.delete(item)
        for row in self.coverage_matrix():
            issues = row["errors"] + row["warns"]
            self.coverage_tree.insert(
                "",
                tk.END,
                iid=row["id"],
                text=row["label"],
                values=(
                    "Yes" if row["planned"] else "No",
                    row["observed_audio_lines"],
                    issues,
                    row["status"],
                ),
            )

    def issue_signature(self, finding: dict) -> tuple[str, str, str, str, str]:
        text = finding["text"].lower()
        cat = finding["category"]
        events = finding.get("events") or []
        event_hint = next((event for event in events if event.lower().startswith(("stop_", "play_"))), "")

        stop_bank_failed = (
            ("加载event:" in text or "load event" in text)
            and "stop_" in text
            and ("失败" in text or "退出播放" in text or "failed" in text or "fail" in text)
        )
        if stop_bank_failed:
            return (
                f"StopEventBankLoadFailed:{event_hint or 'StopEvent'}",
                "StopEventBankLoadFailed",
                event_hint or "Stop_*",
                "Unity requested a Stop Event, but the Stop Event bank failed to load. The stop command may never reach Wwise, so loop/continuous voices can leak.",
                "Check the Stop bank load path first. In this project, also verify whether an already-loaded bank is being returned as AK_INVALID_UNIQUE_ID and then treated as a fatal load failure. For reel loops, consider storing the playing ID and stopping it directly, or using a preloaded/shared control bank.",
            )

        event_bank_failed = (
            ("加载event:" in text or "load event" in text)
            and ("失败" in text or "退出播放" in text or "failed" in text or "fail" in text)
        )
        if event_bank_failed:
            return (
                f"EventBankLoadFailed:{event_hint or (events[0] if events else 'Event')}",
                "EventBankLoadFailed",
                event_hint or (events[0] if events else "Event"),
                "Unity requested an Event, but the Event bank failed to load. The Event likely did not reach Wwise, so the intended sound may be missing.",
                "Check bank packaging/path first. If this happens repeatedly for banks that should already be available, verify whether the bank manager returns AK_INVALID_UNIQUE_ID for already-loaded banks and whether WwiseProvider incorrectly treats that as a fatal load failure.",
            )

        if "voice starvation" in text:
            return (
                "Performance:VoiceStarvation",
                "VoiceStarvation",
                ", ".join(events[:2]) or "-",
                "Wwise ran out of available voices or hit a voice budget/priority limit. This often follows leaked loops, repeated PostEvent spam, or insufficient voice limiting.",
                "Check Wwise Profiler for active voices, owner GameObjects, and virtual voice behavior. Verify loop stop logic, set per-bus/container voice limits, and kill oldest/virtualize low-priority sounds.",
            )

        if "source starvation" in text:
            match = re.search(r"source starvation(?: name:)?\s*([0-9]+)?(?:.*?\bgo:\s*([0-9]+))?", finding["text"], re.IGNORECASE)
            source_hint = f"Source {match.group(1) or '?'}" if match else "Source"
            return (
                "Performance:SourceStarvation",
                "SourceStarvation",
                source_hint,
                "A Wwise source could not provide/render audio in time. This can be a downstream symptom of too many voices, missing/unloaded media, streaming pressure, or a loop that never stops.",
                "Correlate the timestamp with Wwise Profiler active voices. If this appears near failed Stop Events, fix the stop/load path before tuning voice count. Then check streaming/cache and source plugin/media health.",
            )

        if cat == "BankOrMedia":
            key_event = event_hint or (events[0] if events else "Unknown")
            return (
                f"BankOrMedia:{key_event}",
                "BankOrMedia",
                key_event,
                finding.get("likely_cause", "Bank/media lifecycle needs verification."),
                finding.get("recommendation", "Check bank load order, unload timing, generated banks, platform folder, and bundle contents."),
            )

        if cat == "RTPCSwitchState":
            key_event = events[0] if events else "Parameter"
            return (
                f"RTPCSwitchState:{key_event}",
                "RTPC/Switch/State",
                key_event,
                finding.get("likely_cause", "Parameter name, scope, or timing may be wrong."),
                finding.get("recommendation", "Check Wwise parameter existence, Unity set timing, and GameObject/global scope."),
            )

        if cat == "Event":
            key_event = events[0] if events else "UnknownEvent"
            return (
                f"Event:{key_event}",
                "Event",
                key_event,
                finding.get("likely_cause", "Event send/lookup path needs verification."),
                finding.get("recommendation", "Check trigger condition, registered GameObject, Event field/name, and bank load state."),
            )

        return (
            f"{cat}:{finding['severity']}",
            cat,
            ", ".join(events[:2]) or "-",
            finding.get("likely_cause", "Audio-related warning/error needs correlation with nearby gameplay action."),
            finding.get("recommendation", "Check nearby log context, Wwise Profiler timeline, and the Unity trigger path."),
        )

    def register_finding(self, finding: dict) -> str:
        key, issue_type, event_hint, cause, rec = self.issue_signature(finding)
        key = re.sub(r"[^A-Za-z0-9_.:-]", "_", key)
        finding["issue_key"] = key
        finding["issue_type"] = issue_type
        self.findings.append(finding)
        group = self.issue_groups.get(key)
        if group is None:
            group = {
                "key": key,
                "severity": finding["severity"],
                "type": issue_type,
                "count": 0,
                "first_time": finding["time"],
                "last_time": finding["time"],
                "events": [],
                "event_hint": event_hint,
                "confidence": finding.get("confidence", "Low"),
                "likely_cause": cause,
                "recommendation": rec,
                "latest_evidence": "",
                "latest_file": "",
                "latest_line": 0,
            }
            self.issue_groups[key] = group

        group["count"] += 1
        group["last_time"] = finding["time"]
        group["latest_evidence"] = finding["text"]
        group["latest_file"] = finding["file"]
        group["latest_line"] = finding["line"]
        for event in finding.get("events", []):
            if event not in group["events"]:
                group["events"].append(event)
        if SEVERITY_RANK.get(finding["severity"], 0) > SEVERITY_RANK.get(group["severity"], 0):
            group["severity"] = finding["severity"]
        confidence_rank = {"High": 3, "Medium": 2, "Low": 1}
        if confidence_rank.get(finding.get("confidence", "Low"), 0) > confidence_rank.get(group["confidence"], 0):
            group["confidence"] = finding.get("confidence", "Low")
            group["likely_cause"] = finding.get("likely_cause", group["likely_cause"])
            group["recommendation"] = finding.get("recommendation", group["recommendation"])

        self.refresh_issue_tree()
        return key

    def refresh_issue_tree(self, select_key: str | None = None):
        previous_selection = set(self.issue_filter_keys)
        self._suppress_issue_selection_event = True
        try:
            for item in self.issue_tree.get_children():
                self.issue_tree.delete(item)

            sorted_groups = sorted(
                self.issue_groups.values(),
                key=lambda group: (
                    -SEVERITY_RANK.get(group["severity"], 0),
                    -group["count"],
                    group["last_time"],
                ),
                reverse=False,
            )
            for group in sorted_groups:
                last_time = group["last_time"].split("T")[-1]
                event_text = ", ".join(group["events"][:2]) or group.get("event_hint") or "-"
                self.issue_tree.insert(
                    "",
                    tk.END,
                    iid=group["key"],
                    values=(group["severity"], group["type"], group["count"], last_time, event_text),
                )

            next_selection: list[str] = []
            if select_key and select_key in self.issue_groups:
                next_selection = [select_key]
            elif previous_selection:
                next_selection = [
                    key
                    for key in previous_selection
                    if key in self.issue_groups
                ]
            if next_selection:
                self.issue_tree.selection_set(*next_selection)
                self.issue_tree.see(next_selection[0])
        finally:
            self._suppress_issue_selection_event = False
        if next_selection:
            self.issue_filter_keys = set(next_selection)
            self.show_selected_issue()
        elif previous_selection or select_key:
            self.issue_filter_keys.clear()
            self.show_selected_issue()

    def show_selected_issue(self, _event=None):
        if self._suppress_issue_selection_event:
            return
        selection = tuple(
            key
            for key in self.issue_tree.selection()
            if key in self.issue_groups
        )
        self.issue_filter_keys = set(selection)
        if not selection:
            self.analysis_text.delete("1.0", tk.END)
            self.analysis_text.insert(
                tk.END,
                "No problem selected.\n\nRuntime audio log is showing all audio lines that match the top filter/search controls.\n\nSelect one or more rows above to filter the Runtime audio log to those grouped issues.",
            )
            self.log_scope_var.set("Runtime audio log - all audio")
            self.redraw()
            self.update_filter_status()
            return
        groups = [
            self.issue_groups[key]
            for key in selection
            if key in self.issue_groups
        ]
        if not groups:
            self.clear_issue_selection()
            return
        if len(groups) == 1:
            group = groups[0]
            events = ", ".join(group["events"]) or group.get("event_hint") or "-"
            zh_cause, zh_recommendation = self.zh_issue_suggestion(group)
            detail = (
                f"Severity: {group['severity']}\n"
                f"Type: {group['type']}\n"
                f"Count: {group['count']}\n"
                f"First seen: {group['first_time']}\n"
                f"Last seen: {group['last_time']}\n"
                f"Events/Sources: {events}\n"
                f"Confidence: {group['confidence']}\n\n"
                f"可能原因 / Likely cause:\n"
                f"CN: {zh_cause}\n"
                f"EN: {group['likely_cause']}\n\n"
                f"建议 / Recommendation:\n"
                f"CN: {zh_recommendation}\n"
                f"EN: {group['recommendation']}\n\n"
                f"最新证据 / Latest evidence:\n"
                f"{group['latest_file']}:{group['latest_line']}\n"
                f"{group['latest_evidence']}\n"
            )
            self.log_scope_var.set(f"Runtime audio log - issue: {group['type']}")
        else:
            total = sum(group["count"] for group in groups)
            detail_lines = [
                f"Selected issues: {len(groups)}",
                f"Grouped finding count: {total}",
                "",
                "Runtime audio log is filtered to all selected issue groups.",
                "",
            ]
            for group in groups:
                events = ", ".join(group["events"]) or group.get("event_hint") or "-"
                detail_lines.extend(
                    [
                        f"- {group['severity']} / {group['type']} / Count {group['count']} / Events: {events}",
                        f"  Latest: {group['latest_file']}:{group['latest_line']}",
                        f"  {group['latest_evidence']}",
                    ]
                )
            detail = "\n".join(detail_lines)
            self.log_scope_var.set(f"Runtime audio log - {len(groups)} selected issue groups")
        self.analysis_text.delete("1.0", tk.END)
        self.analysis_text.insert(tk.END, detail)
        self.redraw()
        self.log_text.see(tk.END)
        self.update_filter_status("Issue filter updated.")

    def selected_issue_keys(self) -> set[str]:
        return {
            key
            for key in self.issue_filter_keys
            if key in self.issue_groups
        }

    def select_all_issues(self):
        keys = list(self.issue_tree.get_children())
        if keys:
            self.issue_tree.selection_set(*keys)
        self.show_selected_issue()

    def invert_issue_selection(self):
        keys = list(self.issue_tree.get_children())
        selected = self.selected_issue_keys()
        inverted = [key for key in keys if key not in selected]
        if inverted:
            self.issue_tree.selection_set(*inverted)
        else:
            self.issue_tree.selection_remove(*keys)
        self.show_selected_issue()

    def clear_issue_selection(self):
        self.issue_filter_keys.clear()
        keys = list(self.issue_tree.get_children())
        if keys:
            self._suppress_issue_selection_event = True
            try:
                self.issue_tree.selection_remove(*keys)
            finally:
                self._suppress_issue_selection_event = False
        self.show_selected_issue()

    def zh_issue_suggestion(self, group: dict) -> tuple[str, str]:
        issue_type = group.get("type", "")
        if issue_type == "StopEventBankLoadFailed":
            return (
                "Unity 已经请求 Stop Event，但 Stop Event 对应 Bank 加载失败，Stop 很可能没有真正发到 Wwise，持续/循环声音可能因此停不掉。",
                "先查 Stop Bank 的加载路径和加载返回值。如果这是已经加载的 Bank 被返回为 AK_INVALID_UNIQUE_ID，又被业务代码当成失败，需要程序修正判断；循环类声音也建议考虑记录 playingId 后直接 StopPlayingID。",
            )
        if issue_type == "EventBankLoadFailed":
            return (
                "Unity 已经请求某个 Event，但对应 Bank 加载失败，所以这个 Event 很可能没有真正发到 Wwise，目标声音可能直接丢失。",
                "先查 Bank 是否真的在运行包/AssetBundle/平台目录里；如果大量重复发生在同一个 Event 上，再重点查 Bank 已加载时是否返回 AK_INVALID_UNIQUE_ID 并被 WwiseProvider 当成失败退出。",
            )
        if issue_type == "VoiceStarvation":
            return (
                "Wwise 可用声部不够，通常由循环声未停止、PostEvent 过密、或 voice limit/priority 策略不足引起。",
                "先在 Profiler 看同一时间的 Active Voices 和 GameObject，再检查循环停止逻辑；然后补 bus/container voice limit、virtual voice 或 kill-oldest 策略。",
            )
        if issue_type == "SourceStarvation":
            return (
                "某个 Wwise source 来不及供给或渲染音频，可能是声部过多、流式/缓存压力、媒体缺失，或上游循环声堆积造成的连锁反应。",
                "按时间戳和 Profiler 对齐。如果同时有 Stop Event 加载失败，先修 Stop 链路，再看 streaming/cache 和 source/plugin 状态。",
            )
        if issue_type == "BankOrMedia":
            return (
                "Bank 或媒体生命周期需要确认，可能是加载顺序、卸载时机、平台路径、AssetBundle 内容或 SoundbanksInfo 不一致。",
                "检查 Bank 是否在 PostEvent 前可用、Unity 打包路径是否包含对应 bnk/wem、以及当前 Wwise 工程保存并重新生成 SoundBank。",
            )
        if issue_type == "RTPC/Switch/State":
            return (
                "参数名、作用域或设置时机可能不对，例如全局/对象作用域混用、GameObject 未注册、或 Set 时机早于对象生命周期。",
                "检查 Wwise 参数是否存在，Unity 调用传入的 GameObject 是否正确，并用 Debug 日志记录参数名、值、对象和帧号。",
            )
        if issue_type == "Event":
            return (
                "Event 发送或查找链路需要确认，可能是触发条件未满足、Event 名不一致、对象未注册、或 Bank 未加载。",
                "检查 Unity 触发条件、Event 名/AK 常量、GameObject 注册状态和 Bank 加载状态，并和 Wwise Profiler 时间线对齐。",
            )
        return (
            "这是一条音频相关异常，需要和上下文的玩法动作、Wwise Profiler 时间线、以及附近 Unity 日志一起判断。",
            "保留最新证据，复现一次并记录具体操作步骤；如果有重复刷屏，再优先查触发频率和生命周期。",
        )

    def entry_visible(self, entry: dict) -> bool:
        selected_issues = self.selected_issue_keys()
        if selected_issues and entry.get("issue_key") not in selected_issues:
            return False
        filter_value = self.filter_var.get()
        if filter_value == "Warn + Error" and entry["severity"] not in {"Warn", "Error"}:
            return False
        if filter_value == "Error only" and entry["severity"] != "Error":
            return False
        query = self.search_var.get().strip().lower()
        if query and query not in json.dumps(entry, ensure_ascii=False).lower():
            return False
        return True

    def append_entry_if_visible(self, entry: dict):
        if not self.entry_visible(entry):
            return
        self.append_log_entry(entry)

    def append_log_entry(self, entry: dict):
        prefix = f"{entry['time']} [{entry['severity']}/{entry['category']}] {Path(entry['file']).name}:{entry['line']}"
        text = f"{prefix}\n{entry['text']}\n\n"
        self.log_text.insert(tk.END, text, entry["severity"])
        if self.autoscroll_var.get():
            self.log_text.see(tk.END)

    def redraw(self):
        self.log_text.delete("1.0", tk.END)
        for entry in self.entries[-5000:]:
            if self.entry_visible(entry):
                self.append_log_entry(entry)

    def append_jsonl(self, entry: dict):
        try:
            with REPORT_JSONL.open("a", encoding="utf-8-sig") as fp:
                fp.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def issue_group_payloads(self) -> list[dict]:
        return [
            {
                "severity": group["severity"],
                "type": group["type"],
                "count": group["count"],
                "first_time": group["first_time"],
                "last_time": group["last_time"],
                "events": group["events"],
                "event_hint": group.get("event_hint", ""),
                "confidence": group["confidence"],
                "likely_cause": group["likely_cause"],
                "recommendation": group["recommendation"],
                "latest_file": group["latest_file"],
                "latest_line": group["latest_line"],
                "latest_evidence": group["latest_evidence"],
            }
            for group in sorted(
                self.issue_groups.values(),
                key=lambda item: (-SEVERITY_RANK.get(item["severity"], 0), -item["count"], item["type"]),
            )
        ]

    def write_report(self):
        try:
            DEFAULT_OUT_DIR.mkdir(parents=True, exist_ok=True)
            REPORT_DIR.mkdir(parents=True, exist_ok=True)
            payload = {
                "summary": {
                    "mode": "GUI follow",
                    "running": self.running,
                    "unity_root": self.unity_root_var.get(),
                    "wwise_root": self.wwise_root_var.get(),
                    "logs": [str(p) for p in self.logs],
                    "known_wwise_events": len(self.known_events),
                    "audio_lines": len(self.entries),
                    "issues": len(self.issue_groups),
                    "findings": len(self.findings),
                    "last_updated": datetime.now().isoformat(timespec="seconds"),
                    "connection_status": self.connection_status_var.get(),
                },
                "severity_counts": dict(self.severity_counts),
                "category_counts": dict(self.category_counts),
                "event_counts": dict(self.event_counts),
                "session": self.session_metadata(),
                "coverage_matrix": self.coverage_matrix(),
                "bank_diagnostics": self.bank_diagnostics_payload(),
                "issue_groups": self.issue_group_payloads(),
                "findings": self.findings[-300:],
                "entries": self.entries[-500:],
            }
            json_text = json.dumps(payload, ensure_ascii=False, indent=2)
            md_text = self.render_markdown(payload)
            for path in (REPORT_JSON, REPORT_JSON_COPY):
                path.write_text(json_text, encoding="utf-8-sig")
            for path in (REPORT_MD, REPORT_MD_COPY):
                path.write_text(md_text, encoding="utf-8-sig")
        except Exception as exc:
            self.status_var.set(f"Report write error: {exc}")

    def render_markdown(self, payload: dict) -> str:
        lines = ["# ProjectEF Unity/Wwise GUI Runtime Audio Monitor", ""]
        lines.append("## Summary")
        lines.append("")
        for key, value in payload["summary"].items():
            if isinstance(value, list):
                value = "<br>".join(value)
            lines.append(f"- **{key}**: {value}")
        lines.append("")
        lines.append("## Coverage Scope")
        lines.append("")
        session = payload.get("session", {})
        if session:
            for key, value in session.items():
                value = str(value).replace("\n", "<br>") if value else "-"
                lines.append(f"- **{key}**: {value}")
        lines.append("")
        lines.append("> Runtime coverage is session evidence only. `NotObserved` means this monitor did not see matching audio evidence in this captured run; it does not prove the feature is absent or correct.")
        lines.append("")
        lines.append("| Scenario | Planned | Observed Audio Lines | Warns | Errors | Status |")
        lines.append("|---|---|---:|---:|---:|---|")
        for row in payload.get("coverage_matrix", []):
            table_row = [
                row["label"],
                "Yes" if row["planned"] else "No",
                row["observed_audio_lines"],
                row["warns"],
                row["errors"],
                row["status"],
            ]
            lines.append("| " + " | ".join(str(x).replace("|", "\\|").replace("\n", "<br>") for x in table_row) + " |")
        lines.append("")
        bank = payload.get("bank_diagnostics", {})
        lines.append("## Bank Diagnostics")
        lines.append("")
        if bank:
            lines.append(f"- **status**: {bank.get('status', '-')}")
            lines.append(f"- **source_json**: `{bank.get('source_json', '') or '-'}`")
            lines.append(f"- **bank_root**: `{bank.get('bank_root', '') or '-'}`")
            lines.append(f"- **event_dir**: `{bank.get('event_dir', '') or '-'}`")
            lines.append(f"- **authored_event_count**: {bank.get('authored_event_count', 0)}")
            lines.append(f"- **runtime_event_bank_count**: {bank.get('runtime_event_bank_count', 0)}")
            lines.append(f"- **missing_event_banks**: {len(bank.get('missing_event_banks') or [])}")
            lines.append(f"- **extra_event_banks**: {len(bank.get('extra_event_banks') or [])}")
            lines.append("")
            lines.append("| Top Failed Event | Has .bnk | Modified | KB |")
            lines.append("|---|---|---|---:|")
            for item in bank.get("top_event_bank_status") or []:
                row = [
                    item.get("event", "-"),
                    "Yes" if item.get("exists") else "No",
                    item.get("modified", "-"),
                    item.get("size_kb", "-"),
                ]
                lines.append("| " + " | ".join(str(x).replace("|", "\\|").replace("\n", "<br>") for x in row) + " |")
            if not bank.get("top_event_bank_status"):
                lines.append("| - | - | - | - |")
            live_rows = bank.get("live_failed_event_bank_status") or []
            if live_rows:
                lines.append("")
                lines.append("| Current Captured Failed Event | Has .bnk | Bank Path |")
                lines.append("|---|---|---|")
                for item in live_rows:
                    row = [
                        item.get("event", "-"),
                        "Yes" if item.get("exists") else "No",
                        item.get("path", "-"),
                    ]
                    lines.append("| " + " | ".join(str(x).replace("|", "\\|").replace("\n", "<br>") for x in row) + " |")
        else:
            lines.append("- No bank diagnostic payload available.")
        lines.append("")
        lines.append("## Issue Summary")
        lines.append("")
        lines.append("| Severity | Type | Count | Last Seen | Events/Sources | Confidence | Likely Cause | Recommendation | Latest Evidence |")
        lines.append("|---|---|---:|---|---|---|---|---|---|")
        for item in payload.get("issue_groups", []):
            row = [
                item["severity"],
                item["type"],
                item["count"],
                item["last_time"],
                ", ".join(item.get("events") or []) or item.get("event_hint", ""),
                item.get("confidence", ""),
                item.get("likely_cause", ""),
                item.get("recommendation", ""),
                f"{item.get('latest_file', '')}:{item.get('latest_line', '')}<br>{item.get('latest_evidence', '')}",
            ]
            lines.append("| " + " | ".join(str(x).replace("|", "\\|").replace("\n", "<br>") for x in row) + " |")
        if not payload.get("issue_groups"):
            lines.append("| Pass | - | 0 | - | - | - | No grouped issues captured yet. | - | - |")
        lines.append("")
        lines.append("## Findings")
        lines.append("")
        lines.append("| Severity | Category | File | Line | Events | Confidence | Evidence | Likely Cause | Recommendation |")
        lines.append("|---|---|---|---:|---|---|---|---|---|")
        for item in self.findings[-300:]:
            row = [
                item["severity"],
                item["category"],
                item["file"],
                item["line"],
                ", ".join(item["events"]),
                item.get("confidence", ""),
                item["text"],
                item.get("likely_cause", ""),
                item.get("recommendation", ""),
            ]
            lines.append("| " + " | ".join(str(x).replace("|", "\\|").replace("\n", "<br>") for x in row) + " |")
        if not self.findings:
            lines.append("| Pass | - | - | - | - | - | No warnings/errors captured yet. | - | - |")
        lines.append("")
        lines.append("## Recent Audio Lines")
        lines.append("")
        lines.append("| Severity | Category | File | Line | Message |")
        lines.append("|---|---|---|---:|---|")
        for item in self.entries[-500:]:
            row = [item["severity"], item["category"], item["file"], item["line"], item["text"]]
            lines.append("| " + " | ".join(str(x).replace("|", "\\|").replace("\n", "<br>") for x in row) + " |")
        if not self.entries:
            lines.append("| - | - | - | - | No audio-related log lines captured yet. |")
        return "\n".join(lines)

    def open_path(self, path: Path):
        try:
            if path.exists():
                os.startfile(path)
            else:
                messagebox.showinfo("Not found", f"Path does not exist yet:\n{path}")
        except Exception as exc:
            messagebox.showerror("Open failed", str(exc))

    def on_close(self):
        self.stop()
        self.root.destroy()


def main():
    root = tk.Tk()
    app = AudioMonitorApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
