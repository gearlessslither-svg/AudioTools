# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk


APP_NAME = "Daily Work Notes"
DATA_VERSION = 1
PRIORITIES = ("High", "Normal", "Low")
PRIORITY_ORDER = {"High": 0, "Normal": 1, "Low": 2}

BG = "#F4F6F8"
PANEL = "#FFFFFF"
INK = "#20252D"
MUTED = "#68717D"
LINE = "#DDE3EA"
ACCENT = "#2563EB"
ACCENT_DARK = "#1D4ED8"
GOOD = "#16845B"
GOOD_BG = "#EAF7F0"
WARN = "#B7791F"
WARN_BG = "#FFF6DF"
BAD = "#C2410C"
BAD_BG = "#FFF1ED"
CHIP = "#EAF1FF"
CHIP_ALT = "#EEF7F1"
CARD = "#FBFCFE"

PROJECT_COLORS = (
    ("#EAF1FF", "#1D4ED8"),
    ("#EAF7F0", "#15803D"),
    ("#FFF6DF", "#B7791F"),
    ("#FFF1ED", "#C2410C"),
    ("#F4ECFF", "#7C3AED"),
    ("#E8FAF7", "#0F766E"),
)


def today_str() -> str:
    return date.today().isoformat()


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def default_data_dir() -> Path:
    override = os.environ.get("EF_WORK_NOTES_DATA")
    if override:
        return Path(override)
    base = os.environ.get("APPDATA")
    if base:
        return Path(base) / "EF_Work_Notes"
    return Path.home() / ".ef_work_notes"


def normalize_project(value: str) -> str:
    value = (value or "").strip()
    return value if value else "General"


def normalize_description(value: str) -> str:
    return " ".join((value or "").strip().split())


def normalize_priority(value: str) -> str:
    return value if value in PRIORITIES else "Normal"


def parse_date_prefix(value: str) -> str:
    if isinstance(value, str) and len(value) >= 10:
        return value[:10]
    return ""


class WorkNotesStore:
    def __init__(self, data_dir: Path | None = None):
        self.data_dir = Path(data_dir) if data_dir else default_data_dir()
        self.path = self.data_dir / "work_notes.json"
        self.backup_dir = self.data_dir / "backups"
        self.data = self._load()
        self._migrate()

    def _blank_data(self) -> dict:
        return {
            "version": DATA_VERSION,
            "created_at": now_iso(),
            "last_synced_date": "",
            "tasks": [],
        }

    def _load(self) -> dict:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            return self._blank_data()
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                loaded = json.load(handle)
            if isinstance(loaded, dict):
                return loaded
        except Exception:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            corrupt = self.data_dir / f"work_notes_corrupt_{stamp}.json"
            try:
                shutil.copy2(self.path, corrupt)
            except Exception:
                pass
        return self._blank_data()

    def _migrate(self) -> None:
        changed = False
        if self.data.get("version") != DATA_VERSION:
            self.data["version"] = DATA_VERSION
            changed = True
        if not isinstance(self.data.get("tasks"), list):
            self.data["tasks"] = []
            changed = True
        for task in self.data["tasks"]:
            if "id" not in task:
                task["id"] = uuid.uuid4().hex[:12]
                changed = True
            if "project" not in task:
                task["project"] = "General"
                changed = True
            if "description" not in task:
                task["description"] = ""
                changed = True
            if task.get("priority") not in PRIORITIES:
                task["priority"] = "Normal"
                changed = True
            if task.get("status") not in ("todo", "done"):
                task["status"] = "todo"
                changed = True
            if "due_date" not in task:
                task["due_date"] = today_str()
                changed = True
            if "origin_date" not in task:
                task["origin_date"] = task.get("due_date", today_str())
                changed = True
            if "rollover_count" not in task:
                task["rollover_count"] = 0
                changed = True
        if changed:
            self.save()

    def _backup_if_needed(self) -> None:
        if not self.path.exists():
            return
        stamp = today_str()
        backup = self.backup_dir / f"work_notes_{stamp}.json"
        if backup.exists():
            return
        try:
            shutil.copy2(self.path, backup)
        except Exception:
            pass

    def save(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self._backup_if_needed()
        tmp_path = self.path.with_suffix(".json.tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(self.data, handle, ensure_ascii=False, indent=2)
        tmp_path.replace(self.path)

    def sync_today(self) -> int:
        today = today_str()
        moved = 0
        for task in self.data["tasks"]:
            if task.get("status") != "todo":
                continue
            due_date = task.get("due_date") or today
            if due_date < today:
                history = task.setdefault("rollover_history", [])
                if isinstance(history, list):
                    history.append({"from": due_date, "to": today, "at": now_iso()})
                task["due_date"] = today
                task["rollover_count"] = int(task.get("rollover_count") or 0) + 1
                task["updated_at"] = now_iso()
                moved += 1
        if self.data.get("last_synced_date") != today or moved:
            self.data["last_synced_date"] = today
            self.save()
        return moved

    def task_by_id(self, task_id: str) -> dict | None:
        for task in self.data["tasks"]:
            if task.get("id") == task_id:
                return task
        return None

    def add_task(self, project: str, description: str, priority: str = "Normal", due_date: str | None = None) -> str:
        description = normalize_description(description)
        if not description:
            raise ValueError("Description is required.")
        due = due_date or today_str()
        task = {
            "id": uuid.uuid4().hex[:12],
            "project": normalize_project(project),
            "description": description,
            "priority": normalize_priority(priority),
            "status": "todo",
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "due_date": due,
            "origin_date": due,
            "rollover_count": 0,
            "completed_at": "",
        }
        self.data["tasks"].append(task)
        self.save()
        return task["id"]

    def update_task(self, task_id: str, project: str, description: str, priority: str) -> None:
        task = self.task_by_id(task_id)
        if not task:
            raise KeyError(task_id)
        description = normalize_description(description)
        if not description:
            raise ValueError("Description is required.")
        task["project"] = normalize_project(project)
        task["description"] = description
        task["priority"] = normalize_priority(priority)
        task["updated_at"] = now_iso()
        self.save()

    def complete_task(self, task_id: str) -> None:
        task = self.task_by_id(task_id)
        if not task:
            raise KeyError(task_id)
        task["status"] = "done"
        task["completed_at"] = now_iso()
        task["updated_at"] = now_iso()
        self.save()

    def reopen_task(self, task_id: str) -> None:
        task = self.task_by_id(task_id)
        if not task:
            raise KeyError(task_id)
        task["status"] = "todo"
        task["completed_at"] = ""
        task["due_date"] = today_str()
        task["updated_at"] = now_iso()
        self.save()

    def delete_task(self, task_id: str) -> None:
        original_count = len(self.data["tasks"])
        self.data["tasks"] = [task for task in self.data["tasks"] if task.get("id") != task_id]
        if len(self.data["tasks"]) != original_count:
            self.save()

    def projects(self) -> list[str]:
        projects = {normalize_project(task.get("project", "")) for task in self.data["tasks"]}
        return sorted(projects, key=str.casefold)

    def active_tasks(self, search: str = "", project: str = "All") -> list[dict]:
        query = search.strip().casefold()
        project_filter = "" if project in ("", "All") else project
        tasks = []
        for task in self.data["tasks"]:
            if task.get("status") != "todo":
                continue
            if task.get("due_date") != today_str():
                continue
            if project_filter and normalize_project(task.get("project", "")) != project_filter:
                continue
            haystack = f"{task.get('project', '')} {task.get('description', '')}".casefold()
            if query and query not in haystack:
                continue
            tasks.append(task)
        return sorted(
            tasks,
            key=lambda task: (
                PRIORITY_ORDER.get(task.get("priority"), 1),
                normalize_project(task.get("project", "")).casefold(),
                task.get("created_at", ""),
            ),
        )

    def completed_tasks(self, search: str = "", project: str = "All") -> list[dict]:
        query = search.strip().casefold()
        project_filter = "" if project in ("", "All") else project
        tasks = []
        for task in self.data["tasks"]:
            if task.get("status") != "done":
                continue
            if project_filter and normalize_project(task.get("project", "")) != project_filter:
                continue
            haystack = f"{task.get('project', '')} {task.get('description', '')}".casefold()
            if query and query not in haystack:
                continue
            tasks.append(task)
        return sorted(tasks, key=lambda task: task.get("completed_at", ""), reverse=True)

    def stats(self) -> dict:
        today = today_str()
        active = [task for task in self.data["tasks"] if task.get("status") == "todo" and task.get("due_date") == today]
        done_today = [
            task
            for task in self.data["tasks"]
            if task.get("status") == "done" and parse_date_prefix(task.get("completed_at", "")) == today
        ]
        rolled = [task for task in active if int(task.get("rollover_count") or 0) > 0]
        return {
            "active": len(active),
            "done_today": len(done_today),
            "rolled": len(rolled),
            "projects": len({normalize_project(task.get("project", "")) for task in active}),
            "completed_total": len([task for task in self.data["tasks"] if task.get("status") == "done"]),
        }

    def completed_by_project(self, search: str = "", project: str = "All") -> dict[str, list[dict]]:
        grouped = defaultdict(list)
        for task in self.completed_tasks(search, project):
            grouped[normalize_project(task.get("project", ""))].append(task)
        return dict(sorted(grouped.items(), key=lambda item: item[0].casefold()))

    def export_markdown(self, destination: Path, report_date: str | None = None) -> Path:
        report_date = report_date or today_str()
        active = self.active_tasks()
        completed_today = [
            task
            for task in self.completed_tasks()
            if parse_date_prefix(task.get("completed_at", "")) == report_date
        ]
        grouped = self.completed_by_project()
        lines = [
            f"# Work Notes - {report_date}",
            "",
            "## Today",
            "",
        ]
        if active:
            for task in active:
                roll = int(task.get("rollover_count") or 0)
                roll_text = f" · rolled {roll}x" if roll else ""
                lines.append(
                    f"- [ ] **{normalize_project(task.get('project', ''))}** "
                    f"[{task.get('priority', 'Normal')}] {task.get('description', '')}{roll_text}"
                )
        else:
            lines.append("- No open items.")
        lines.extend(["", "## Completed Today", ""])
        if completed_today:
            for task in completed_today:
                lines.append(
                    f"- [x] **{normalize_project(task.get('project', ''))}** "
                    f"{task.get('description', '')}"
                )
        else:
            lines.append("- No completed items yet.")
        lines.extend(["", "## Completed Pool By Project", ""])
        if grouped:
            for project, tasks in grouped.items():
                lines.append(f"### {project}")
                for task in tasks:
                    completed = parse_date_prefix(task.get("completed_at", "")) or "unknown"
                    lines.append(f"- {completed} · {task.get('description', '')}")
                lines.append("")
        else:
            lines.append("- Empty.")
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        return destination

    def export_json(self, destination: Path) -> Path:
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        source = os.path.normcase(os.path.abspath(str(self.path)))
        target = os.path.normcase(os.path.abspath(str(destination)))
        if source != target:
            shutil.copy2(self.path, destination)
        return destination


class ScrollableFrame(tk.Frame):
    def __init__(self, parent, bg=PANEL):
        super().__init__(parent, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, borderwidth=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg=bg)
        self.window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.inner.bind("<Configure>", self._sync_scroll_region)
        self.canvas.bind("<Configure>", self._sync_width)
        self.inner.bind("<Enter>", self._bind_mousewheel)
        self.inner.bind("<Leave>", self._unbind_mousewheel)

    def _sync_scroll_region(self, _event=None) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _sync_width(self, event) -> None:
        self.canvas.itemconfigure(self.window, width=event.width)

    def _bind_mousewheel(self, _event=None) -> None:
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _unbind_mousewheel(self, _event=None) -> None:
        self.canvas.unbind_all("<MouseWheel>")

    def _on_mousewheel(self, event) -> None:
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def clear(self) -> None:
        for child in self.inner.winfo_children():
            child.destroy()


class WorkNotesApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.store = WorkNotesStore()
        self.current_date = today_str()
        self.project_var = tk.StringVar(value="")
        self.description_var = tk.StringVar(value="")
        self.priority_var = tk.StringVar(value="Normal")
        self.search_var = tk.StringVar(value="")
        self.filter_project_var = tk.StringVar(value="All")
        self.status_var = tk.StringVar(value="Ready")
        self.stats_var = tk.StringVar(value="")
        self.date_var = tk.StringVar(value=self._date_label())

        self.root.title(APP_NAME)
        self.root.geometry("1180x760")
        self.root.minsize(1000, 650)
        self.root.configure(bg=BG)
        self._setup_style()
        self._build_menu()
        self._build_layout()

        moved = self.store.sync_today()
        if moved:
            self.set_status(f"Rolled {moved} unfinished item(s) into today.")
        self.refresh_all()
        self.root.after(60000, self.check_date_tick)

    def _setup_style(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TScrollbar", troughcolor=BG, background=LINE, bordercolor=BG, arrowcolor=MUTED)
        style.configure("TCombobox", padding=6)

    def _build_menu(self) -> None:
        menu = tk.Menu(self.root)
        file_menu = tk.Menu(menu, tearoff=False)
        file_menu.add_command(label="Export Today Markdown", command=self.export_markdown)
        file_menu.add_command(label="Export JSON Backup", command=self.export_json)
        file_menu.add_separator()
        file_menu.add_command(label="Open Data Folder", command=self.open_data_folder)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.destroy)
        menu.add_cascade(label="File", menu=file_menu)

        view_menu = tk.Menu(menu, tearoff=False)
        view_menu.add_command(label="Sync Date Now", command=self.sync_date_now)
        view_menu.add_command(label="Refresh", command=self.refresh_all)
        menu.add_cascade(label="View", menu=view_menu)
        self.root.configure(menu=menu)

    def _build_layout(self) -> None:
        self._build_header()
        self._build_body()
        self._build_status_bar()
        self.root.bind("<Control-f>", lambda _event: self.search_entry.focus_set())
        self.root.bind("<Control-e>", lambda _event: self.export_markdown())
        self.root.bind("<Control-n>", lambda _event: self.description_entry.focus_set())

    def _build_header(self) -> None:
        header = tk.Frame(self.root, bg=BG)
        header.pack(fill=tk.X, padx=22, pady=(18, 12))

        title_area = tk.Frame(header, bg=BG)
        title_area.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Label(
            title_area,
            text=APP_NAME,
            bg=BG,
            fg=INK,
            font=("Segoe UI", 22, "bold"),
        ).pack(anchor="w")
        tk.Label(
            title_area,
            textvariable=self.date_var,
            bg=BG,
            fg=MUTED,
            font=("Segoe UI", 10),
        ).pack(anchor="w", pady=(3, 0))

        stats = tk.Frame(header, bg=BG)
        stats.pack(side=tk.RIGHT)
        tk.Label(stats, textvariable=self.stats_var, bg=BG, fg=INK, font=("Segoe UI", 10, "bold")).pack(anchor="e")
        tk.Button(
            stats,
            text="Export",
            command=self.export_markdown,
            bg=ACCENT,
            fg="white",
            activebackground=ACCENT_DARK,
            activeforeground="white",
            relief=tk.FLAT,
            padx=18,
            pady=8,
            cursor="hand2",
        ).pack(anchor="e", pady=(8, 0))

    def _build_body(self) -> None:
        body = tk.Frame(self.root, bg=BG)
        body.pack(fill=tk.BOTH, expand=True, padx=22, pady=(0, 14))
        body.grid_columnconfigure(0, weight=3, uniform="body")
        body.grid_columnconfigure(1, weight=2, uniform="body")
        body.grid_rowconfigure(0, weight=1)

        left = tk.Frame(body, bg=PANEL, highlightbackground=LINE, highlightthickness=1)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        left.grid_rowconfigure(3, weight=1)
        left.grid_columnconfigure(0, weight=1)

        right = tk.Frame(body, bg=PANEL, highlightbackground=LINE, highlightthickness=1)
        right.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        right.grid_rowconfigure(1, weight=1)
        right.grid_columnconfigure(0, weight=1)

        self._build_today_panel(left)
        self._build_completed_panel(right)

    def _build_today_panel(self, parent) -> None:
        top = tk.Frame(parent, bg=PANEL)
        top.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 10))
        top.grid_columnconfigure(0, weight=1)
        tk.Label(top, text="Today", bg=PANEL, fg=INK, font=("Segoe UI", 15, "bold")).grid(row=0, column=0, sticky="w")
        tk.Button(
            top,
            text="Sync",
            command=self.sync_date_now,
            bg=CHIP,
            fg=ACCENT_DARK,
            relief=tk.FLAT,
            padx=12,
            pady=5,
            cursor="hand2",
        ).grid(row=0, column=1, sticky="e")

        form = tk.Frame(parent, bg=CARD, highlightbackground=LINE, highlightthickness=1)
        form.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 12))
        form.grid_columnconfigure(1, weight=1)

        tk.Label(form, text="Project", bg=CARD, fg=MUTED, font=("Segoe UI", 9)).grid(row=0, column=0, sticky="w", padx=12, pady=(10, 2))
        tk.Label(form, text="Description", bg=CARD, fg=MUTED, font=("Segoe UI", 9)).grid(row=0, column=1, sticky="w", padx=8, pady=(10, 2))
        tk.Label(form, text="Priority", bg=CARD, fg=MUTED, font=("Segoe UI", 9)).grid(row=0, column=2, sticky="w", padx=8, pady=(10, 2))

        self.project_combo = ttk.Combobox(form, textvariable=self.project_var, values=[], width=18)
        self.project_combo.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 12))
        self.description_entry = ttk.Entry(form, textvariable=self.description_var)
        self.description_entry.grid(row=1, column=1, sticky="ew", padx=8, pady=(0, 12))
        self.description_entry.bind("<Return>", lambda _event: self.add_task())
        self.priority_combo = ttk.Combobox(form, textvariable=self.priority_var, values=PRIORITIES, state="readonly", width=10)
        self.priority_combo.grid(row=1, column=2, sticky="ew", padx=8, pady=(0, 12))
        tk.Button(
            form,
            text="Add",
            command=self.add_task,
            bg=ACCENT,
            fg="white",
            activebackground=ACCENT_DARK,
            activeforeground="white",
            relief=tk.FLAT,
            padx=16,
            pady=7,
            cursor="hand2",
        ).grid(row=1, column=3, sticky="ew", padx=(8, 12), pady=(0, 12))

        filters = tk.Frame(parent, bg=PANEL)
        filters.grid(row=2, column=0, sticky="ew", padx=18, pady=(0, 8))
        filters.grid_columnconfigure(0, weight=1)
        self.search_entry = ttk.Entry(filters, textvariable=self.search_var)
        self.search_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.search_entry.insert(0, "")
        self.search_var.trace_add("write", lambda *_args: self.refresh_lists())
        self.filter_project_combo = ttk.Combobox(filters, textvariable=self.filter_project_var, state="readonly", width=20)
        self.filter_project_combo.grid(row=0, column=1, sticky="e", padx=(0, 8))
        self.filter_project_combo.bind("<<ComboboxSelected>>", lambda _event: self.refresh_lists())
        tk.Button(
            filters,
            text="Clear",
            command=self.clear_filters,
            bg=BG,
            fg=INK,
            relief=tk.FLAT,
            padx=12,
            pady=4,
            cursor="hand2",
        ).grid(row=0, column=2, sticky="e")

        self.today_scroll = ScrollableFrame(parent, bg=PANEL)
        self.today_scroll.grid(row=3, column=0, sticky="nsew", padx=14, pady=(0, 14))

    def _build_completed_panel(self, parent) -> None:
        top = tk.Frame(parent, bg=PANEL)
        top.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 10))
        top.grid_columnconfigure(0, weight=1)
        tk.Label(top, text="Completed Pool", bg=PANEL, fg=INK, font=("Segoe UI", 15, "bold")).grid(row=0, column=0, sticky="w")
        tk.Button(
            top,
            text="Data",
            command=self.open_data_folder,
            bg=CHIP_ALT,
            fg=GOOD,
            relief=tk.FLAT,
            padx=12,
            pady=5,
            cursor="hand2",
        ).grid(row=0, column=1, sticky="e")
        self.completed_scroll = ScrollableFrame(parent, bg=PANEL)
        self.completed_scroll.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 14))

    def _build_status_bar(self) -> None:
        status = tk.Frame(self.root, bg=BG)
        status.pack(fill=tk.X, padx=22, pady=(0, 12))
        tk.Label(status, textvariable=self.status_var, bg=BG, fg=MUTED, font=("Segoe UI", 9)).pack(side=tk.LEFT)
        tk.Label(status, text=str(self.store.path), bg=BG, fg=MUTED, font=("Segoe UI", 9)).pack(side=tk.RIGHT)

    def _date_label(self) -> str:
        return datetime.now().strftime("%A, %Y-%m-%d")

    def set_status(self, text: str) -> None:
        self.status_var.set(text)

    def refresh_all(self) -> None:
        self.date_var.set(self._date_label())
        self.refresh_projects()
        self.refresh_stats()
        self.refresh_lists()

    def refresh_projects(self) -> None:
        projects = self.store.projects()
        self.project_combo.configure(values=projects)
        filter_values = ["All"] + projects
        self.filter_project_combo.configure(values=filter_values)
        if self.filter_project_var.get() not in filter_values:
            self.filter_project_var.set("All")

    def refresh_stats(self) -> None:
        stats = self.store.stats()
        self.stats_var.set(
            f"Open {stats['active']}  ·  Done today {stats['done_today']}  ·  Rolled {stats['rolled']}  ·  Projects {stats['projects']}"
        )

    def refresh_lists(self) -> None:
        search = self.search_var.get()
        project = self.filter_project_var.get()
        self._render_today(self.store.active_tasks(search=search, project=project))
        self._render_completed(self.store.completed_by_project(search=search, project=project))
        self.refresh_stats()

    def clear_filters(self) -> None:
        self.search_var.set("")
        self.filter_project_var.set("All")
        self.refresh_lists()

    def _render_today(self, tasks: list[dict]) -> None:
        self.today_scroll.clear()
        if not tasks:
            self._empty_state(self.today_scroll.inner, "No open work for today.")
            return
        for task in tasks:
            self._task_row(self.today_scroll.inner, task)

    def _render_completed(self, grouped: dict[str, list[dict]]) -> None:
        self.completed_scroll.clear()
        if not grouped:
            self._empty_state(self.completed_scroll.inner, "Completed items will collect here by project.")
            return
        for project, tasks in grouped.items():
            header = tk.Frame(self.completed_scroll.inner, bg=PANEL)
            header.pack(fill=tk.X, padx=4, pady=(8, 4))
            tk.Label(header, text=project, bg=PANEL, fg=INK, font=("Segoe UI", 11, "bold")).pack(side=tk.LEFT)
            tk.Label(header, text=str(len(tasks)), bg=CHIP, fg=ACCENT_DARK, font=("Segoe UI", 9, "bold"), padx=8, pady=2).pack(side=tk.RIGHT)
            for task in tasks[:40]:
                self._completed_row(self.completed_scroll.inner, task)
            if len(tasks) > 40:
                tk.Label(
                    self.completed_scroll.inner,
                    text=f"{len(tasks) - 40} more item(s) hidden in this group.",
                    bg=PANEL,
                    fg=MUTED,
                    font=("Segoe UI", 9),
                ).pack(anchor="w", padx=10, pady=(0, 8))

    def _empty_state(self, parent, text: str) -> None:
        frame = tk.Frame(parent, bg=PANEL)
        frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=30)
        tk.Label(frame, text=text, bg=PANEL, fg=MUTED, font=("Segoe UI", 12)).pack(anchor="center", pady=22)

    def _project_badge(self, parent, project: str) -> tk.Label:
        bg, fg = self._project_colors(project)
        return tk.Label(parent, text=project, bg=bg, fg=fg, font=("Segoe UI", 9, "bold"), padx=8, pady=2)

    def _project_colors(self, project: str) -> tuple[str, str]:
        index = sum(ord(ch) for ch in project) % len(PROJECT_COLORS)
        return PROJECT_COLORS[index]

    def _priority_colors(self, priority: str) -> tuple[str, str]:
        if priority == "High":
            return BAD_BG, BAD
        if priority == "Low":
            return CHIP_ALT, GOOD
        return WARN_BG, WARN

    def _task_row(self, parent, task: dict) -> None:
        row = tk.Frame(parent, bg=CARD, highlightbackground=LINE, highlightthickness=1)
        row.pack(fill=tk.X, padx=4, pady=5)
        row.grid_columnconfigure(1, weight=1)

        check_var = tk.BooleanVar(value=False)
        check = tk.Checkbutton(
            row,
            variable=check_var,
            command=lambda task_id=task["id"]: self.complete_task(task_id),
            bg=CARD,
            activebackground=CARD,
            selectcolor=PANEL,
            cursor="hand2",
        )
        check.grid(row=0, column=0, rowspan=2, sticky="nw", padx=(10, 6), pady=12)

        meta = tk.Frame(row, bg=CARD)
        meta.grid(row=0, column=1, sticky="ew", padx=(0, 8), pady=(9, 2))
        self._project_badge(meta, normalize_project(task.get("project", ""))).pack(side=tk.LEFT)
        priority_bg, priority_fg = self._priority_colors(task.get("priority", "Normal"))
        tk.Label(
            meta,
            text=task.get("priority", "Normal"),
            bg=priority_bg,
            fg=priority_fg,
            font=("Segoe UI", 9, "bold"),
            padx=7,
            pady=2,
        ).pack(side=tk.LEFT, padx=(6, 0))
        roll = int(task.get("rollover_count") or 0)
        if roll:
            tk.Label(
                meta,
                text=f"Rolled {roll}x",
                bg=BG,
                fg=MUTED,
                font=("Segoe UI", 9),
                padx=7,
                pady=2,
            ).pack(side=tk.LEFT, padx=(6, 0))

        tk.Label(
            row,
            text=task.get("description", ""),
            bg=CARD,
            fg=INK,
            font=("Segoe UI", 11),
            justify=tk.LEFT,
            wraplength=560,
        ).grid(row=1, column=1, sticky="ew", padx=(0, 8), pady=(0, 11))

        actions = tk.Frame(row, bg=CARD)
        actions.grid(row=0, column=2, rowspan=2, sticky="ne", padx=(0, 10), pady=10)
        tk.Button(
            actions,
            text="Edit",
            command=lambda t=task: self.open_edit_dialog(t),
            bg=BG,
            fg=INK,
            relief=tk.FLAT,
            padx=10,
            pady=4,
            cursor="hand2",
        ).pack(side=tk.LEFT, padx=(0, 6))
        tk.Button(
            actions,
            text="Delete",
            command=lambda task_id=task["id"]: self.delete_task(task_id),
            bg=BAD_BG,
            fg=BAD,
            relief=tk.FLAT,
            padx=10,
            pady=4,
            cursor="hand2",
        ).pack(side=tk.LEFT)

    def _completed_row(self, parent, task: dict) -> None:
        row = tk.Frame(parent, bg=CARD, highlightbackground=LINE, highlightthickness=1)
        row.pack(fill=tk.X, padx=4, pady=3)
        row.grid_columnconfigure(0, weight=1)
        completed = parse_date_prefix(task.get("completed_at", "")) or "Done"
        tk.Label(
            row,
            text=task.get("description", ""),
            bg=CARD,
            fg=INK,
            font=("Segoe UI", 10),
            justify=tk.LEFT,
            wraplength=380,
        ).grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 2))
        tk.Label(row, text=completed, bg=CARD, fg=MUTED, font=("Segoe UI", 9)).grid(row=1, column=0, sticky="w", padx=10, pady=(0, 8))
        tk.Button(
            row,
            text="Reopen",
            command=lambda task_id=task["id"]: self.reopen_task(task_id),
            bg=CHIP,
            fg=ACCENT_DARK,
            relief=tk.FLAT,
            padx=10,
            pady=4,
            cursor="hand2",
        ).grid(row=0, column=1, rowspan=2, sticky="e", padx=10, pady=8)

    def add_task(self) -> None:
        try:
            self.store.add_task(self.project_var.get(), self.description_var.get(), self.priority_var.get())
        except ValueError as exc:
            messagebox.showwarning(APP_NAME, str(exc))
            return
        self.description_var.set("")
        if not self.project_var.get().strip():
            self.project_var.set("")
        self.refresh_all()
        self.description_entry.focus_set()
        self.set_status("Added to today's list.")

    def complete_task(self, task_id: str) -> None:
        try:
            self.store.complete_task(task_id)
        except KeyError:
            self.set_status("That item no longer exists.")
            return
        self.refresh_all()
        self.set_status("Moved to the completed pool.")

    def reopen_task(self, task_id: str) -> None:
        try:
            self.store.reopen_task(task_id)
        except KeyError:
            self.set_status("That item no longer exists.")
            return
        self.refresh_all()
        self.set_status("Reopened for today.")

    def delete_task(self, task_id: str) -> None:
        task = self.store.task_by_id(task_id)
        if not task:
            return
        if not messagebox.askyesno(APP_NAME, "Delete this item?"):
            return
        self.store.delete_task(task_id)
        self.refresh_all()
        self.set_status("Deleted item.")

    def open_edit_dialog(self, task: dict) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("Edit Item")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.configure(bg=PANEL)
        dialog.resizable(False, False)

        project_var = tk.StringVar(value=normalize_project(task.get("project", "")))
        description_var = tk.StringVar(value=task.get("description", ""))
        priority_var = tk.StringVar(value=task.get("priority", "Normal"))

        frame = tk.Frame(dialog, bg=PANEL)
        frame.pack(fill=tk.BOTH, expand=True, padx=18, pady=18)
        frame.grid_columnconfigure(1, weight=1)
        tk.Label(frame, text="Project", bg=PANEL, fg=MUTED, font=("Segoe UI", 9)).grid(row=0, column=0, sticky="w", pady=(0, 6))
        project_entry = ttk.Combobox(frame, textvariable=project_var, values=self.store.projects(), width=30)
        project_entry.grid(row=0, column=1, sticky="ew", pady=(0, 6), padx=(12, 0))

        tk.Label(frame, text="Description", bg=PANEL, fg=MUTED, font=("Segoe UI", 9)).grid(row=1, column=0, sticky="w", pady=(0, 6))
        desc_entry = ttk.Entry(frame, textvariable=description_var, width=58)
        desc_entry.grid(row=1, column=1, sticky="ew", pady=(0, 6), padx=(12, 0))

        tk.Label(frame, text="Priority", bg=PANEL, fg=MUTED, font=("Segoe UI", 9)).grid(row=2, column=0, sticky="w", pady=(0, 12))
        priority_combo = ttk.Combobox(frame, textvariable=priority_var, values=PRIORITIES, state="readonly", width=14)
        priority_combo.grid(row=2, column=1, sticky="w", pady=(0, 12), padx=(12, 0))

        buttons = tk.Frame(frame, bg=PANEL)
        buttons.grid(row=3, column=0, columnspan=2, sticky="e")

        def save_edit() -> None:
            try:
                self.store.update_task(task["id"], project_var.get(), description_var.get(), priority_var.get())
            except ValueError as exc:
                messagebox.showwarning(APP_NAME, str(exc), parent=dialog)
                return
            dialog.destroy()
            self.refresh_all()
            self.set_status("Updated item.")

        tk.Button(
            buttons,
            text="Cancel",
            command=dialog.destroy,
            bg=BG,
            fg=INK,
            relief=tk.FLAT,
            padx=14,
            pady=6,
            cursor="hand2",
        ).pack(side=tk.LEFT, padx=(0, 8))
        tk.Button(
            buttons,
            text="Save",
            command=save_edit,
            bg=ACCENT,
            fg="white",
            activebackground=ACCENT_DARK,
            activeforeground="white",
            relief=tk.FLAT,
            padx=16,
            pady=6,
            cursor="hand2",
        ).pack(side=tk.LEFT)
        desc_entry.bind("<Return>", lambda _event: save_edit())
        desc_entry.focus_set()
        dialog.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() // 2) - (dialog.winfo_width() // 2)
        y = self.root.winfo_rooty() + (self.root.winfo_height() // 2) - (dialog.winfo_height() // 2)
        dialog.geometry(f"+{max(0, x)}+{max(0, y)}")

    def sync_date_now(self) -> None:
        moved = self.store.sync_today()
        self.current_date = today_str()
        self.refresh_all()
        if moved:
            self.set_status(f"Rolled {moved} unfinished item(s) into today.")
        else:
            self.set_status("Date is synced.")

    def check_date_tick(self) -> None:
        if today_str() != self.current_date:
            self.sync_date_now()
        self.root.after(60000, self.check_date_tick)

    def export_markdown(self) -> None:
        default_name = f"WorkNotes_{today_str()}.md"
        desktop = Path.home() / "Desktop"
        initial_dir = desktop if desktop.exists() else Path.home()
        path = filedialog.asksaveasfilename(
            title="Export Today Markdown",
            initialdir=str(initial_dir),
            initialfile=default_name,
            defaultextension=".md",
            filetypes=[("Markdown", "*.md"), ("Text", "*.txt"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            self.store.export_markdown(Path(path))
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Export failed:\n{exc}")
            return
        self.set_status(f"Exported Markdown: {path}")

    def export_json(self) -> None:
        default_name = f"WorkNotes_Backup_{today_str()}.json"
        desktop = Path.home() / "Desktop"
        initial_dir = desktop if desktop.exists() else Path.home()
        path = filedialog.asksaveasfilename(
            title="Export JSON Backup",
            initialdir=str(initial_dir),
            initialfile=default_name,
            defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            self.store.export_json(Path(path))
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Export failed:\n{exc}")
            return
        self.set_status(f"Exported JSON: {path}")

    def open_data_folder(self) -> None:
        self.store.data_dir.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["explorer.exe", str(self.store.data_dir)])


def run_self_test() -> int:
    data_dir = Path(tempfile.mkdtemp(prefix="ef_work_notes_test_"))
    store = WorkNotesStore(data_dir)
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    old_id = store.add_task("Project A", "Carry this forward", "High", due_date=yesterday)
    new_id = store.add_task("Project B", "Finish today", "Normal")
    moved = store.sync_today()
    assert moved == 1, moved
    assert store.task_by_id(old_id)["due_date"] == today_str()
    assert store.task_by_id(old_id)["rollover_count"] == 1
    store.complete_task(new_id)
    assert len(store.active_tasks()) == 1
    assert len(store.completed_tasks()) == 1
    store.reopen_task(new_id)
    assert len(store.active_tasks()) == 2
    md_path = data_dir / "export.md"
    store.export_markdown(md_path)
    assert md_path.exists()
    shutil.rmtree(data_dir, ignore_errors=True)
    print("Self-test passed.")
    return 0


def main() -> int:
    if "--self-test" in sys.argv:
        return run_self_test()
    root = tk.Tk()
    app = WorkNotesApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
