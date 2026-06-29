from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import queue
import shlex
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable
import tkinter as tk


ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = ROOT / "Tools"
SETTINGS_PATH = TOOLS_DIR / "reaper_project_manager_settings.json"

APP_TITLE = "REAPER 工程管理器"
REAPER_EXTENSIONS = (".rpp",)
BACKUP_EXTENSIONS = (".rpp-bak",)
SKIP_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".venv",
    "venv",
    "node_modules",
    "$recycle.bin",
    "system volume information",
}

BG = "#101820"
PANEL = "#172330"
PANEL_2 = "#1d2a38"
INK = "#edf5ff"
MUTED = "#9fb0c2"
LINE = "#304356"
ACCENT = "#4fb6ff"
GOOD = "#57d68d"
WARN = "#ffd166"
BAD = "#ff6b6b"


@dataclass
class ScanOptions:
    include_backups: bool = False
    skip_common_dirs: bool = True


@dataclass
class ScanProgress:
    folders: int = 0
    files: int = 0
    found: int = 0
    current_folder: str = ""


@dataclass
class ReaperProject:
    path: Path
    size: int
    modified_ts: float
    created_ts: float
    match_count: int = 0
    match_snippets: list[str] = field(default_factory=list)
    matched_terms: set[str] = field(default_factory=set)

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def stem(self) -> str:
        return self.path.stem

    @property
    def folder(self) -> str:
        return str(self.path.parent)

    @property
    def extension(self) -> str:
        name = self.path.name.lower()
        if name.endswith(".rpp-bak"):
            return ".rpp-bak"
        return self.path.suffix.lower()

    @property
    def modified_text(self) -> str:
        return format_timestamp(self.modified_ts)

    @property
    def created_text(self) -> str:
        return format_timestamp(self.created_ts)

    @property
    def size_text(self) -> str:
        return format_size(self.size)


def format_timestamp(value: float) -> str:
    try:
        return dt.datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M:%S")
    except (OSError, OverflowError, ValueError):
        return ""


def format_size(size: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def load_settings() -> dict:
    try:
        return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_settings(settings: dict) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def parse_keywords(text: str) -> list[str]:
    raw = text.strip()
    if not raw:
        return []
    try:
        parts = shlex.split(raw, posix=False)
    except ValueError:
        parts = raw.split()
    output: list[str] = []
    seen: set[str] = set()
    for part in parts:
        cleaned = part.strip().strip('"').strip("'").lower()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            output.append(cleaned)
    return output


def is_reaper_project(name: str, include_backups: bool) -> bool:
    lower = name.lower()
    if lower.endswith(REAPER_EXTENSIONS):
        return True
    return include_backups and lower.endswith(BACKUP_EXTENSIONS)


def should_skip_dir(name: str, options: ScanOptions) -> bool:
    if not options.skip_common_dirs:
        return False
    return name.lower() in SKIP_DIR_NAMES


def scan_reaper_projects(
    root: Path,
    options: ScanOptions,
    stop_event: threading.Event | None = None,
    progress: Callable[[ScanProgress], None] | None = None,
) -> tuple[list[ReaperProject], list[str]]:
    projects: list[ReaperProject] = []
    errors: list[str] = []
    progress_state = ScanProgress()
    stack = [root]
    last_emit = 0.0

    while stack:
        if stop_event and stop_event.is_set():
            break
        folder = stack.pop()
        progress_state.current_folder = str(folder)
        progress_state.folders += 1

        try:
            with os.scandir(folder) as entries:
                for entry in entries:
                    if stop_event and stop_event.is_set():
                        break
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            if not should_skip_dir(entry.name, options):
                                stack.append(Path(entry.path))
                            continue
                        if not entry.is_file(follow_symlinks=False):
                            continue
                        progress_state.files += 1
                        if not is_reaper_project(entry.name, options.include_backups):
                            continue
                        stat = entry.stat(follow_symlinks=False)
                        projects.append(
                            ReaperProject(
                                path=Path(entry.path),
                                size=stat.st_size,
                                modified_ts=stat.st_mtime,
                                created_ts=stat.st_ctime,
                            )
                        )
                        progress_state.found += 1
                    except OSError as exc:
                        errors.append(f"{entry.path}: {exc}")
        except OSError as exc:
            errors.append(f"{folder}: {exc}")

        now = time.monotonic()
        if progress and now - last_emit > 0.15:
            progress(
                ScanProgress(
                    folders=progress_state.folders,
                    files=progress_state.files,
                    found=progress_state.found,
                    current_folder=progress_state.current_folder,
                )
            )
            last_emit = now

    if progress:
        progress(
            ScanProgress(
                folders=progress_state.folders,
                files=progress_state.files,
                found=progress_state.found,
                current_folder=progress_state.current_folder,
            )
        )

    projects.sort(key=lambda item: item.modified_ts, reverse=True)
    return projects, errors


def project_field_text(project: ReaperProject) -> str:
    return f"{project.name}\n{project.path}\n{project.folder}".lower()


def terms_match(found_terms: set[str], terms: list[str], match_all: bool) -> bool:
    if not terms:
        return True
    if match_all:
        return all(term in found_terms for term in terms)
    return any(term in found_terms for term in terms)


def find_terms_in_text(text: str, terms: list[str]) -> set[str]:
    lower = text.lower()
    return {term for term in terms if term in lower}


def scan_project_content(
    project: ReaperProject,
    terms: list[str],
    max_snippets: int = 6,
) -> tuple[set[str], int, list[str]]:
    found_terms: set[str] = set()
    snippets: list[str] = []
    line_hits = 0

    try:
        data = project.path.read_bytes()
    except OSError as exc:
        snippets.append(f"读取失败: {exc}")
        return found_terms, line_hits, snippets

    text = ""
    for encoding in ("utf-8-sig", "utf-8", "gbk", "cp936"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if not text:
        text = data.decode("utf-8", errors="replace")

    for line_number, line in enumerate(text.splitlines(), start=1):
        line_found = find_terms_in_text(line, terms)
        if not line_found:
            continue
        found_terms.update(line_found)
        line_hits += 1
        if len(snippets) < max_snippets:
            compact = " ".join(line.strip().split())
            if len(compact) > 220:
                compact = compact[:217] + "..."
            snippets.append(f"L{line_number}: {compact}")

    return found_terms, line_hits, snippets


def filter_projects(
    projects: list[ReaperProject],
    keyword: str,
    scan_content: bool = False,
    match_all: bool = True,
    stop_event: threading.Event | None = None,
    progress: callable | None = None,
) -> list[ReaperProject]:
    terms = parse_keywords(keyword)
    if not terms:
        for project in projects:
            project.match_count = 0
            project.match_snippets = []
            project.matched_terms = set()
        return list(projects)

    output: list[ReaperProject] = []
    total = len(projects)
    for index, project in enumerate(projects, start=1):
        if stop_event and stop_event.is_set():
            break

        field_found = find_terms_in_text(project_field_text(project), terms)
        content_found: set[str] = set()
        content_hits = 0
        snippets: list[str] = []

        if scan_content and not terms_match(field_found, terms, match_all):
            content_found, content_hits, snippets = scan_project_content(project, terms)
        elif scan_content:
            content_found, content_hits, snippets = scan_project_content(project, terms)

        combined = field_found | content_found
        project.matched_terms = combined
        project.match_count = len(field_found) + content_hits
        project.match_snippets = snippets

        if terms_match(combined, terms, match_all):
            output.append(project)

        if progress and (index % 10 == 0 or index == total):
            progress(index, total, len(output), str(project.path))

    return output


def sort_projects(projects: list[ReaperProject], sort_key: str) -> list[ReaperProject]:
    key = sort_key.strip()
    if key == "修改时间 最旧优先":
        return sorted(projects, key=lambda item: item.modified_ts)
    if key == "创建时间 最新优先":
        return sorted(projects, key=lambda item: item.created_ts, reverse=True)
    if key == "创建时间 最旧优先":
        return sorted(projects, key=lambda item: item.created_ts)
    if key == "工程名 A-Z":
        return sorted(projects, key=lambda item: item.name.lower())
    if key == "工程名 Z-A":
        return sorted(projects, key=lambda item: item.name.lower(), reverse=True)
    if key == "大小 最大优先":
        return sorted(projects, key=lambda item: item.size, reverse=True)
    if key == "大小 最小优先":
        return sorted(projects, key=lambda item: item.size)
    if key == "匹配数 最大优先":
        return sorted(
            projects,
            key=lambda item: (item.match_count, item.modified_ts),
            reverse=True,
        )
    return sorted(projects, key=lambda item: item.modified_ts, reverse=True)


def open_path(path: Path) -> None:
    if sys.platform.startswith("win"):
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def reveal_path(path: Path) -> None:
    if sys.platform.startswith("win"):
        subprocess.Popen(["explorer", f"/select,{path}"])
    else:
        open_path(path.parent)


class ReaperProjectManager(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1320x780")
        self.minsize(1060, 620)

        self.settings = load_settings()
        self.queue: queue.Queue = queue.Queue()
        self.scan_stop_event: threading.Event | None = None
        self.filter_stop_event: threading.Event | None = None
        self.all_projects: list[ReaperProject] = []
        self.visible_projects: list[ReaperProject] = []
        self.iid_to_project: dict[str, ReaperProject] = {}
        self.keyword_after_id: str | None = None

        self.root_var = tk.StringVar(value=self.settings.get("last_root") or str(ROOT))
        self.keyword_var = tk.StringVar(value=self.settings.get("last_keyword", ""))
        self.include_backups_var = tk.BooleanVar(
            value=bool(self.settings.get("include_backups", False))
        )
        self.skip_common_dirs_var = tk.BooleanVar(
            value=bool(self.settings.get("skip_common_dirs", True))
        )
        self.scan_content_var = tk.BooleanVar(
            value=bool(self.settings.get("scan_content", False))
        )
        self.match_mode_var = tk.StringVar(
            value=self.settings.get("match_mode", "全部关键词")
        )
        self.sort_var = tk.StringVar(
            value=self.settings.get("sort", "修改时间 最新优先")
        )
        self.status_var = tk.StringVar(value="选择根目录后点击“扫描工程”。")
        self.count_var = tk.StringVar(value="0 个工程")

        self._setup_style()
        self._build_ui()
        self._bind_events()
        self.after(120, self._process_queue)

    def _setup_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", font=("Microsoft YaHei UI", 10))
        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("TLabel", background=BG, foreground=INK)
        style.configure("Muted.TLabel", background=BG, foreground=MUTED)
        style.configure("Panel.TLabel", background=PANEL, foreground=INK)
        style.configure("Status.TLabel", background=PANEL, foreground=MUTED)
        style.configure("Accent.TButton", foreground=BG)
        style.configure("TButton", padding=(10, 6))
        style.configure("TCheckbutton", background=BG, foreground=INK)
        style.map("TCheckbutton", background=[("active", BG)], foreground=[("active", INK)])
        style.configure("Treeview", rowheight=28, fieldbackground="#0f1722", background="#0f1722", foreground=INK)
        style.configure("Treeview.Heading", background=PANEL_2, foreground=INK, padding=(8, 7))
        style.map("Treeview", background=[("selected", "#285a7d")], foreground=[("selected", "#ffffff")])

    def _build_ui(self) -> None:
        self.configure(background=BG)

        header = ttk.Frame(self, style="Panel.TFrame", padding=(14, 12))
        header.pack(fill=tk.X)

        ttk.Label(header, text=APP_TITLE, style="Panel.TLabel", font=("Microsoft YaHei UI", 16, "bold")).pack(side=tk.LEFT)
        ttk.Label(header, textvariable=self.count_var, style="Status.TLabel").pack(side=tk.RIGHT)

        controls = ttk.Frame(self, padding=(14, 12))
        controls.pack(fill=tk.X)

        ttk.Label(controls, text="根目录").grid(row=0, column=0, sticky="w", padx=(0, 8))
        recent_roots = self.settings.get("recent_roots") or []
        self.root_combo = ttk.Combobox(
            controls,
            textvariable=self.root_var,
            values=recent_roots,
        )
        self.root_combo.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        ttk.Button(controls, text="选择", command=self.choose_root).grid(row=0, column=2, padx=(0, 8))
        self.scan_button = ttk.Button(controls, text="扫描工程", command=self.start_scan)
        self.scan_button.grid(row=0, column=3, padx=(0, 8))
        self.cancel_button = ttk.Button(controls, text="停止", command=self.cancel_work, state=tk.DISABLED)
        self.cancel_button.grid(row=0, column=4)

        ttk.Label(controls, text="关键词").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(10, 0))
        keyword_entry = ttk.Entry(controls, textvariable=self.keyword_var)
        keyword_entry.grid(row=1, column=1, sticky="ew", padx=(0, 8), pady=(10, 0))
        keyword_entry.bind("<Return>", lambda _event: self.start_filter())
        ttk.Button(controls, text="关键词扫描", command=self.start_filter).grid(row=1, column=2, padx=(0, 8), pady=(10, 0))
        ttk.Button(controls, text="清空", command=self.clear_keyword).grid(row=1, column=3, padx=(0, 8), pady=(10, 0))

        sort_values = [
            "修改时间 最新优先",
            "修改时间 最旧优先",
            "创建时间 最新优先",
            "创建时间 最旧优先",
            "工程名 A-Z",
            "工程名 Z-A",
            "大小 最大优先",
            "大小 最小优先",
            "匹配数 最大优先",
        ]
        ttk.Label(controls, text="排序").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=(10, 0))
        sort_combo = ttk.Combobox(
            controls,
            textvariable=self.sort_var,
            values=sort_values,
            state="readonly",
            width=20,
        )
        sort_combo.grid(row=2, column=1, sticky="w", padx=(0, 8), pady=(10, 0))
        sort_combo.bind("<<ComboboxSelected>>", lambda _event: self.refresh_tree())

        ttk.Checkbutton(
            controls,
            text="包含 .rpp-bak",
            variable=self.include_backups_var,
        ).grid(row=2, column=2, sticky="w", padx=(0, 8), pady=(10, 0))
        ttk.Checkbutton(
            controls,
            text="跳过常见缓存目录",
            variable=self.skip_common_dirs_var,
        ).grid(row=2, column=3, sticky="w", padx=(0, 8), pady=(10, 0))
        ttk.Checkbutton(
            controls,
            text="扫描工程内容",
            variable=self.scan_content_var,
        ).grid(row=2, column=4, sticky="w", padx=(0, 8), pady=(10, 0))
        ttk.Combobox(
            controls,
            textvariable=self.match_mode_var,
            values=["全部关键词", "任意关键词"],
            state="readonly",
            width=12,
        ).grid(row=2, column=5, sticky="w", pady=(10, 0))

        controls.columnconfigure(1, weight=1)

        body = ttk.PanedWindow(self, orient=tk.VERTICAL)
        body.pack(fill=tk.BOTH, expand=True, padx=14, pady=(0, 12))

        table_frame = ttk.Frame(body)
        body.add(table_frame, weight=4)

        columns = ("modified", "created", "size", "type", "matches", "folder")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="tree headings", selectmode="browse")
        self.tree.heading("#0", text="工程名", command=lambda: self.set_sort("工程名 A-Z"))
        self.tree.heading("modified", text="修改时间", command=lambda: self.set_sort("修改时间 最新优先"))
        self.tree.heading("created", text="创建时间", command=lambda: self.set_sort("创建时间 最新优先"))
        self.tree.heading("size", text="大小", command=lambda: self.set_sort("大小 最大优先"))
        self.tree.heading("type", text="类型")
        self.tree.heading("matches", text="匹配", command=lambda: self.set_sort("匹配数 最大优先"))
        self.tree.heading("folder", text="目录")

        self.tree.column("#0", width=260, minwidth=180, stretch=False)
        self.tree.column("modified", width=160, minwidth=140, stretch=False)
        self.tree.column("created", width=160, minwidth=140, stretch=False)
        self.tree.column("size", width=90, minwidth=80, anchor=tk.E, stretch=False)
        self.tree.column("type", width=80, minwidth=70, stretch=False)
        self.tree.column("matches", width=70, minwidth=60, anchor=tk.CENTER, stretch=False)
        self.tree.column("folder", width=520, minwidth=280, stretch=True)

        y_scroll = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.tree.yview)
        x_scroll = ttk.Scrollbar(table_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)

        detail_frame = ttk.Frame(body, padding=(0, 10, 0, 0))
        body.add(detail_frame, weight=1)

        button_row = ttk.Frame(detail_frame)
        button_row.pack(fill=tk.X, pady=(0, 8))
        ttk.Button(button_row, text="打开工程", command=self.open_selected_project).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(button_row, text="打开目录", command=self.reveal_selected_project).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(button_row, text="复制路径", command=self.copy_selected_path).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(button_row, text="导出 CSV", command=self.export_csv).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Label(button_row, textvariable=self.status_var, style="Muted.TLabel").pack(side=tk.LEFT, padx=(12, 0))

        self.progress_bar = ttk.Progressbar(button_row, mode="indeterminate", length=180)
        self.progress_bar.pack(side=tk.RIGHT)

        self.detail_text = tk.Text(
            detail_frame,
            height=8,
            wrap=tk.WORD,
            background="#0f1722",
            foreground=INK,
            insertbackground=INK,
            relief=tk.FLAT,
            padx=10,
            pady=8,
            font=("Consolas", 10),
        )
        self.detail_text.pack(fill=tk.BOTH, expand=True)
        self.detail_text.configure(state=tk.DISABLED)

    def _bind_events(self) -> None:
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self.show_selected_details())
        self.tree.bind("<Double-1>", lambda _event: self.open_selected_project())
        self.keyword_var.trace_add("write", self._on_keyword_changed)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def choose_root(self) -> None:
        current = self.root_var.get().strip() or str(ROOT)
        initial = current if Path(current).exists() else str(ROOT)
        selected = filedialog.askdirectory(title="选择要扫描的根目录", initialdir=initial)
        if selected:
            self.root_var.set(selected)
            self._remember_root(selected)

    def start_scan(self) -> None:
        root = Path(self.root_var.get().strip()).expanduser()
        if not root.exists() or not root.is_dir():
            messagebox.showerror(APP_TITLE, f"根目录不存在或不是文件夹:\n{root}")
            return

        self.cancel_work()
        self.scan_stop_event = threading.Event()
        self.all_projects = []
        self.visible_projects = []
        self.refresh_tree()
        self.set_busy(True, "扫描中...")
        self._remember_root(str(root))

        options = ScanOptions(
            include_backups=self.include_backups_var.get(),
            skip_common_dirs=self.skip_common_dirs_var.get(),
        )

        def worker() -> None:
            started = time.monotonic()

            def emit_progress(state: ScanProgress) -> None:
                self.queue.put(("scan_progress", state))

            projects, errors = scan_reaper_projects(
                root=root,
                options=options,
                stop_event=self.scan_stop_event,
                progress=emit_progress,
            )
            elapsed = time.monotonic() - started
            cancelled = bool(self.scan_stop_event and self.scan_stop_event.is_set())
            self.queue.put(("scan_done", projects, errors, elapsed, cancelled))

        threading.Thread(target=worker, daemon=True).start()

    def start_filter(self) -> None:
        if self.filter_stop_event:
            self.filter_stop_event.set()
        keyword = self.keyword_var.get()
        if not self.all_projects:
            self.refresh_tree()
            return

        scan_content = self.scan_content_var.get() and bool(parse_keywords(keyword))
        if not scan_content:
            self.visible_projects = filter_projects(
                self.all_projects,
                keyword,
                scan_content=False,
                match_all=self.match_mode_var.get() == "全部关键词",
            )
            self.refresh_tree()
            self._save_current_settings()
            return

        self.filter_stop_event = threading.Event()
        self.set_busy(True, "关键词内容扫描中...")

        def worker() -> None:
            started = time.monotonic()

            def emit_progress(index: int, total: int, found: int, path: str) -> None:
                self.queue.put(("filter_progress", index, total, found, path))

            filtered = filter_projects(
                self.all_projects,
                keyword,
                scan_content=True,
                match_all=self.match_mode_var.get() == "全部关键词",
                stop_event=self.filter_stop_event,
                progress=emit_progress,
            )
            elapsed = time.monotonic() - started
            cancelled = bool(self.filter_stop_event and self.filter_stop_event.is_set())
            self.queue.put(("filter_done", filtered, elapsed, cancelled))

        threading.Thread(target=worker, daemon=True).start()

    def clear_keyword(self) -> None:
        self.keyword_var.set("")
        self.start_filter()

    def cancel_work(self) -> None:
        if self.scan_stop_event:
            self.scan_stop_event.set()
        if self.filter_stop_event:
            self.filter_stop_event.set()

    def set_busy(self, busy: bool, text: str | None = None) -> None:
        if text:
            self.status_var.set(text)
        self.scan_button.configure(state=tk.DISABLED if busy else tk.NORMAL)
        self.cancel_button.configure(state=tk.NORMAL if busy else tk.DISABLED)
        if busy:
            self.progress_bar.start(12)
        else:
            self.progress_bar.stop()

    def set_sort(self, sort_key: str) -> None:
        self.sort_var.set(sort_key)
        self.refresh_tree()

    def refresh_tree(self) -> None:
        sorted_projects = sort_projects(self.visible_projects, self.sort_var.get())
        self.visible_projects = sorted_projects
        self.tree.delete(*self.tree.get_children())
        self.iid_to_project.clear()

        for index, project in enumerate(sorted_projects):
            iid = f"project_{index}"
            self.iid_to_project[iid] = project
            self.tree.insert(
                "",
                tk.END,
                iid=iid,
                text=project.name,
                values=(
                    project.modified_text,
                    project.created_text,
                    project.size_text,
                    project.extension,
                    project.match_count if project.match_count else "",
                    project.folder,
                ),
            )

        total = len(self.all_projects)
        visible = len(sorted_projects)
        if total == visible:
            self.count_var.set(f"{total} 个工程")
        else:
            self.count_var.set(f"{visible} / {total} 个工程")

        if not sorted_projects:
            self._write_details("没有可显示的 REAPER 工程。")

    def show_selected_details(self) -> None:
        project = self.get_selected_project()
        if not project:
            return

        lines = [
            f"工程名: {project.name}",
            f"路径: {project.path}",
            f"目录: {project.folder}",
            f"修改时间: {project.modified_text}",
            f"创建时间: {project.created_text}",
            f"大小: {project.size_text}",
            f"类型: {project.extension}",
        ]
        if project.matched_terms:
            lines.append(f"匹配关键词: {', '.join(sorted(project.matched_terms))}")
        if project.match_snippets:
            lines.append("")
            lines.append("内容命中:")
            lines.extend(f"  {snippet}" for snippet in project.match_snippets)
        self._write_details("\n".join(lines))

    def _write_details(self, text: str) -> None:
        self.detail_text.configure(state=tk.NORMAL)
        self.detail_text.delete("1.0", tk.END)
        self.detail_text.insert("1.0", text)
        self.detail_text.configure(state=tk.DISABLED)

    def get_selected_project(self) -> ReaperProject | None:
        selection = self.tree.selection()
        if not selection:
            return None
        return self.iid_to_project.get(selection[0])

    def open_selected_project(self) -> None:
        project = self.get_selected_project()
        if not project:
            messagebox.showinfo(APP_TITLE, "请先选择一个工程。")
            return
        try:
            open_path(project.path)
        except OSError as exc:
            messagebox.showerror(APP_TITLE, f"打开工程失败:\n{exc}")

    def reveal_selected_project(self) -> None:
        project = self.get_selected_project()
        if not project:
            messagebox.showinfo(APP_TITLE, "请先选择一个工程。")
            return
        try:
            reveal_path(project.path)
        except OSError as exc:
            messagebox.showerror(APP_TITLE, f"打开目录失败:\n{exc}")

    def copy_selected_path(self) -> None:
        project = self.get_selected_project()
        if not project:
            messagebox.showinfo(APP_TITLE, "请先选择一个工程。")
            return
        self.clipboard_clear()
        self.clipboard_append(str(project.path))
        self.status_var.set("已复制工程路径。")

    def export_csv(self) -> None:
        if not self.visible_projects:
            messagebox.showinfo(APP_TITLE, "当前没有可导出的工程。")
            return

        default_name = f"reaper_projects_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        path = filedialog.asksaveasfilename(
            title="导出 REAPER 工程列表",
            defaultextension=".csv",
            initialfile=default_name,
            filetypes=[("CSV", "*.csv"), ("All files", "*.*")],
        )
        if not path:
            return

        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow([
                    "name",
                    "path",
                    "folder",
                    "modified",
                    "created",
                    "size_bytes",
                    "type",
                    "match_count",
                    "matched_terms",
                ])
                for project in self.visible_projects:
                    writer.writerow([
                        project.name,
                        str(project.path),
                        project.folder,
                        project.modified_text,
                        project.created_text,
                        project.size,
                        project.extension,
                        project.match_count,
                        "; ".join(sorted(project.matched_terms)),
                    ])
        except OSError as exc:
            messagebox.showerror(APP_TITLE, f"导出失败:\n{exc}")
            return

        self.status_var.set(f"已导出 CSV: {path}")

    def _on_keyword_changed(self, *_args: object) -> None:
        if self.keyword_after_id:
            self.after_cancel(self.keyword_after_id)
        if self.scan_content_var.get():
            self.status_var.set("已修改关键词，按回车或点击“关键词扫描”。")
            return
        self.keyword_after_id = self.after(300, self.start_filter)

    def _process_queue(self) -> None:
        try:
            while True:
                message = self.queue.get_nowait()
                self._handle_queue_message(message)
        except queue.Empty:
            pass
        self.after(120, self._process_queue)

    def _handle_queue_message(self, message: tuple) -> None:
        kind = message[0]
        if kind == "scan_progress":
            state: ScanProgress = message[1]
            self.status_var.set(
                f"扫描中: {state.folders} 个文件夹，{state.files} 个文件，找到 {state.found} 个工程"
            )
        elif kind == "scan_done":
            _kind, projects, errors, elapsed, cancelled = message
            self.all_projects = projects
            self.visible_projects = projects
            self.set_busy(False)
            suffix = "已停止" if cancelled else "扫描完成"
            error_text = f"，{len(errors)} 个目录/文件无法读取" if errors else ""
            self.status_var.set(f"{suffix}: 找到 {len(projects)} 个工程，用时 {elapsed:.1f}s{error_text}")
            self.start_filter()
        elif kind == "filter_progress":
            _kind, index, total, found, _path = message
            self.status_var.set(f"关键词内容扫描中: {index}/{total}，命中 {found} 个工程")
        elif kind == "filter_done":
            _kind, filtered, elapsed, cancelled = message
            self.visible_projects = filtered
            self.set_busy(False)
            suffix = "关键词扫描已停止" if cancelled else "关键词扫描完成"
            self.status_var.set(f"{suffix}: 显示 {len(filtered)} 个工程，用时 {elapsed:.1f}s")
            self.refresh_tree()
            self._save_current_settings()

    def _remember_root(self, root: str) -> None:
        recent = [item for item in self.settings.get("recent_roots", []) if item != root]
        recent.insert(0, root)
        self.settings["recent_roots"] = recent[:12]
        self.settings["last_root"] = root
        self.root_combo.configure(values=self.settings["recent_roots"])
        self._save_current_settings()

    def _save_current_settings(self) -> None:
        self.settings.update(
            {
                "last_root": self.root_var.get().strip(),
                "last_keyword": self.keyword_var.get(),
                "include_backups": self.include_backups_var.get(),
                "skip_common_dirs": self.skip_common_dirs_var.get(),
                "scan_content": self.scan_content_var.get(),
                "match_mode": self.match_mode_var.get(),
                "sort": self.sort_var.get(),
            }
        )
        try:
            save_settings(self.settings)
        except OSError:
            pass

    def on_close(self) -> None:
        self.cancel_work()
        self._save_current_settings()
        self.destroy()


def run_cli_scan(args: argparse.Namespace) -> int:
    root = Path(args.scan).expanduser()
    if not root.exists() or not root.is_dir():
        print(f"Root folder does not exist: {root}", file=sys.stderr)
        return 2

    projects, errors = scan_reaper_projects(
        root,
        ScanOptions(include_backups=args.include_backups, skip_common_dirs=not args.no_skip),
    )
    filtered = filter_projects(
        projects,
        args.keyword or "",
        scan_content=args.content,
        match_all=not args.any,
    )
    for project in sort_projects(filtered, args.sort):
        print(f"{project.modified_text}\t{project.size_text}\t{project.path}")
    if errors:
        print(f"Unreadable paths: {len(errors)}", file=sys.stderr)
    return 0


def run_self_test() -> int:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        song = root / "Song_A.rpp"
        song.write_text(
            '<REAPER_PROJECT 0.1 "7.0" 1710038400\n'
            '  TRACK "Lead Synth"\n'
            '  FILE "Vox_take_01.wav"\n'
            ">\n",
            encoding="utf-8",
        )
        nested = root / "Album"
        nested.mkdir()
        nested_project = nested / "Battle_Theme.rpp"
        nested_project.write_text(
            '<REAPER_PROJECT 0.1 "7.0" 1710038400\n'
            '  TRACK "Drums Heavy"\n'
            ">\n",
            encoding="utf-8",
        )
        backup = nested / "Old_Edit.rpp-bak"
        backup.write_text("backup project", encoding="utf-8")

        projects, errors = scan_reaper_projects(root, ScanOptions(include_backups=False))
        assert not errors
        assert len(projects) == 2, projects

        projects_with_backup, _errors = scan_reaper_projects(root, ScanOptions(include_backups=True))
        assert len(projects_with_backup) == 3, projects_with_backup

        name_filtered = filter_projects(projects_with_backup, "battle", scan_content=False)
        assert [item.name for item in name_filtered] == ["Battle_Theme.rpp"]

        content_filtered = filter_projects(projects_with_backup, "Lead Synth", scan_content=True)
        assert [item.name for item in content_filtered] == ["Song_A.rpp"]

    print("self-test passed")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="REAPER project manager")
    parser.add_argument("--scan", help="scan a folder and print project paths")
    parser.add_argument("--keyword", default="", help="filter keyword")
    parser.add_argument("--content", action="store_true", help="scan inside .rpp text")
    parser.add_argument("--include-backups", action="store_true", help="include .rpp-bak")
    parser.add_argument("--no-skip", action="store_true", help="do not skip cache/version folders")
    parser.add_argument("--any", action="store_true", help="match any keyword instead of all")
    parser.add_argument("--sort", default="修改时间 最新优先", help="sort mode")
    parser.add_argument("--self-test", action="store_true", help="run internal scanner tests")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.self_test:
        return run_self_test()
    if args.scan:
        return run_cli_scan(args)

    app = ReaperProjectManager()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
