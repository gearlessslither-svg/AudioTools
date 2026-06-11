#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk


APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "tool_paths.json"

BG = "#0f1722"
PANEL = "#151f2d"
PANEL_2 = "#1b2636"
CARD = "#202c3d"
CARD_HOVER = "#26364b"
INK = "#edf4ff"
MUTED = "#9fb0c6"
LINE = "#334258"
ACCENT = "#4db6ff"
GOOD = "#55d68a"
BAD = "#ff6b6b"
WARN = "#ffcc66"
CATEGORY_COLORS = {
    "Production": "#7dd3fc",
    "Runtime": "#f9a8d4",
    "Reports": "#a7f3d0",
    "Wwise": "#fcd34d",
    "P4": "#fca5a5",
    "Automation": "#c4b5fd",
    "Other": "#d1d5db",
}
CATEGORIES = ["All", "Production", "Runtime", "Reports", "Wwise", "P4", "Automation", "Other"]


class ToolCatalog:
    def __init__(self, config_path: Path):
        self.config_path = config_path
        self.data: dict = {}
        self.tools: list[dict] = []
        self.load()

    def load(self) -> None:
        self.data = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.tools = list(self.data.get("tools", []))

    def launcher_path(self, item: dict) -> Path:
        return APP_DIR / item.get("launcher", "")

    def source_path(self, item: dict) -> Path:
        return Path(item.get("source_launcher", ""))

    def status(self, item: dict) -> str:
        if not self.launcher_path(item).exists():
            return "Missing launcher"
        if not self.source_path(item).exists():
            return "Missing source"
        return "Ready"

    def visible_tools(self) -> list[dict]:
        return [item for item in self.tools if item.get("visible", True) is not False]

    def hidden_tools(self) -> list[dict]:
        return [item for item in self.tools if item.get("visible", True) is False]

    def ready_count(self, items: list[dict] | None = None) -> int:
        scope = items if items is not None else self.visible_tools()
        return sum(1 for item in scope if self.status(item) == "Ready")


class EFAudioToolsGui(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("EF Audio Tools")
        self.geometry("1220x760")
        self.minsize(1040, 640)
        self.configure(bg=BG)

        self.catalog = ToolCatalog(CONFIG_PATH)
        self.current_item: dict | None = None
        self.card_widgets: dict[str, tk.Frame] = {}
        self.search_var = tk.StringVar()
        self.category_var = tk.StringVar(value="All")
        self.status_var = tk.StringVar(value="Ready")
        self.voice_duration_var = tk.StringVar(value="300")
        self.voice_interval_var = tk.StringVar(value="1")
        self.category_buttons: dict[str, tk.Button] = {}

        self.configure_style()
        self.build_ui()
        self.populate_tools()
        self.select_first_tool()

    def configure_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=INK)
        style.configure("TButton", padding=(12, 6))
        style.configure("Accent.TButton", padding=(14, 8))
        style.configure("TEntry", fieldbackground=PANEL_2, foreground=INK)

    def build_ui(self) -> None:
        root = tk.Frame(self, bg=BG)
        root.pack(fill=tk.BOTH, expand=True)

        header = tk.Frame(root, bg=BG)
        header.pack(fill=tk.X, padx=18, pady=(16, 10))

        title_block = tk.Frame(header, bg=BG)
        title_block.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Label(title_block, text="EF Audio Tools", bg=BG, fg=INK, font=("Segoe UI", 23, "bold")).pack(anchor="w")
        tk.Label(
            title_block,
            text="ProjectEF audio workflow launch center",
            bg=BG,
            fg=MUTED,
            font=("Segoe UI", 10),
        ).pack(anchor="w", pady=(2, 0))

        stats = tk.Frame(header, bg=BG)
        stats.pack(side=tk.RIGHT)
        self.count_label = self.metric(stats, "Main", "0")
        self.ready_label = self.metric(stats, "Ready", "0")
        ttk.Button(stats, text="Refresh", command=self.refresh).pack(side=tk.LEFT, padx=(10, 0))
        ttk.Button(stats, text="Folder", command=lambda: self.open_path(APP_DIR)).pack(side=tk.LEFT, padx=(8, 0))

        search_bar = tk.Frame(root, bg=PANEL, highlightbackground=LINE, highlightthickness=1)
        search_bar.pack(fill=tk.X, padx=18, pady=(0, 12))
        tk.Label(search_bar, text="Filter", bg=PANEL, fg=MUTED, font=("Segoe UI", 10, "bold")).pack(
            side=tk.LEFT, padx=(12, 8), pady=10
        )
        search = tk.Entry(
            search_bar,
            textvariable=self.search_var,
            bg=PANEL_2,
            fg=INK,
            insertbackground=INK,
            relief=tk.FLAT,
            font=("Segoe UI", 10),
        )
        search.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=7, padx=(0, 8))
        search.bind("<KeyRelease>", lambda _event: self.populate_tools())
        tk.Button(
            search_bar,
            text="Clear",
            command=self.clear_filter,
            bg=CARD,
            fg=INK,
            activebackground=CARD_HOVER,
            activeforeground=INK,
            relief=tk.FLAT,
            padx=14,
        ).pack(side=tk.LEFT, padx=(0, 10), pady=8)

        category_bar = tk.Frame(root, bg=BG)
        category_bar.pack(fill=tk.X, padx=18, pady=(0, 12))
        for category in CATEGORIES:
            button = tk.Button(
                category_bar,
                text=category,
                command=lambda value=category: self.set_category(value),
                bg=PANEL if category != "All" else ACCENT,
                fg=INK if category != "All" else "#06111d",
                activebackground=CARD_HOVER,
                activeforeground=INK,
                relief=tk.FLAT,
                padx=14,
                pady=7,
                font=("Segoe UI", 9, "bold"),
            )
            button.pack(side=tk.LEFT, padx=(0, 8))
            self.category_buttons[category] = button

        body = tk.Frame(root, bg=BG)
        body.pack(fill=tk.BOTH, expand=True, padx=18, pady=(0, 14))

        left = tk.Frame(body, bg=PANEL, highlightbackground=LINE, highlightthickness=1)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=False)
        left.configure(width=455)
        left.pack_propagate(False)

        self.canvas = tk.Canvas(left, bg=PANEL, highlightthickness=0)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(left, orient=tk.VERTICAL, command=self.canvas.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.list_frame = tk.Frame(self.canvas, bg=PANEL)
        self.canvas_window = self.canvas.create_window((0, 0), window=self.list_frame, anchor="nw")
        self.list_frame.bind("<Configure>", self.on_list_configure)
        self.canvas.bind("<Configure>", self.on_canvas_configure)
        self.canvas.bind_all("<MouseWheel>", self.on_mousewheel)

        right = tk.Frame(body, bg=PANEL, highlightbackground=LINE, highlightthickness=1)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(14, 0))

        self.detail_header = tk.Frame(right, bg=PANEL)
        self.detail_header.pack(fill=tk.X, padx=18, pady=(18, 8))
        self.detail_number = tk.Label(
            self.detail_header,
            text="-",
            bg=ACCENT,
            fg="#06111d",
            width=4,
            font=("Segoe UI", 14, "bold"),
        )
        self.detail_number.pack(side=tk.LEFT, ipady=8)
        title_area = tk.Frame(self.detail_header, bg=PANEL)
        title_area.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(12, 0))
        self.detail_name = tk.Label(title_area, text="Select a tool", bg=PANEL, fg=INK, font=("Segoe UI", 17, "bold"))
        self.detail_name.pack(anchor="w")
        self.detail_status = tk.Label(title_area, text="", bg=PANEL, fg=MUTED, font=("Segoe UI", 10))
        self.detail_status.pack(anchor="w", pady=(2, 0))

        action_bar = tk.Frame(right, bg=PANEL)
        action_bar.pack(fill=tk.X, padx=18, pady=(0, 12))
        self.launch_button = tk.Button(
            action_bar,
            text="Launch",
            command=self.launch_selected,
            bg=ACCENT,
            fg="#06111d",
            activebackground="#82ccff",
            activeforeground="#06111d",
            relief=tk.FLAT,
            padx=22,
            pady=10,
            font=("Segoe UI", 10, "bold"),
        )
        self.launch_button.pack(side=tk.LEFT)
        self.open_source_button = self.small_button(action_bar, "Open Source", self.open_source)
        self.open_source_button.pack(side=tk.LEFT, padx=(10, 0))
        self.open_wrapper_button = self.small_button(action_bar, "Open Wrapper", self.open_wrapper)
        self.open_wrapper_button.pack(side=tk.LEFT, padx=(8, 0))
        self.copy_button = self.small_button(action_bar, "Copy Source", self.copy_source_path)
        self.copy_button.pack(side=tk.LEFT, padx=(8, 0))

        self.options_frame = tk.Frame(right, bg=PANEL)
        self.options_frame.pack(fill=tk.X, padx=18, pady=(0, 12))
        self.voice_options = tk.Frame(self.options_frame, bg=PANEL_2, highlightbackground=LINE, highlightthickness=1)
        tk.Label(
            self.voice_options,
            text="Capture Options",
            bg=PANEL_2,
            fg=MUTED,
            font=("Segoe UI", 10, "bold"),
        ).pack(side=tk.LEFT, padx=(12, 10), pady=10)
        self.option_entry(self.voice_options, "Duration s", self.voice_duration_var, 8).pack(side=tk.LEFT, padx=(0, 10))
        self.option_entry(self.voice_options, "Interval s", self.voice_interval_var, 7).pack(side=tk.LEFT, padx=(0, 12))
        tk.Label(
            self.voice_options,
            text="Used by Wwise Profiler Voice Capture only.",
            bg=PANEL_2,
            fg=MUTED,
            font=("Segoe UI", 9),
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 12))

        section = tk.Frame(right, bg=PANEL)
        section.pack(fill=tk.BOTH, expand=True, padx=18, pady=(0, 18))

        tk.Label(section, text="Purpose", bg=PANEL, fg=MUTED, font=("Segoe UI", 10, "bold")).pack(anchor="w")
        self.purpose = tk.Text(
            section,
            height=5,
            wrap=tk.WORD,
            bg="#101720",
            fg=INK,
            insertbackground=INK,
            relief=tk.FLAT,
            font=("Segoe UI", 10),
            padx=12,
            pady=10,
        )
        self.purpose.pack(fill=tk.X, pady=(6, 14))
        self.purpose.configure(state=tk.DISABLED)

        tk.Label(section, text="Paths", bg=PANEL, fg=MUTED, font=("Segoe UI", 10, "bold")).pack(anchor="w")
        self.paths = tk.Text(
            section,
            height=8,
            wrap=tk.WORD,
            bg="#101720",
            fg="#c8d6e8",
            insertbackground=INK,
            relief=tk.FLAT,
            font=("Consolas", 9),
            padx=12,
            pady=10,
        )
        self.paths.pack(fill=tk.BOTH, expand=True, pady=(6, 0))
        self.paths.configure(state=tk.DISABLED)

        footer = tk.Frame(root, bg=BG)
        footer.pack(fill=tk.X, padx=18, pady=(0, 12))
        tk.Label(footer, textvariable=self.status_var, bg=BG, fg=MUTED, font=("Segoe UI", 9)).pack(side=tk.LEFT)
        tk.Label(footer, text=str(CONFIG_PATH), bg=BG, fg="#65748a", font=("Segoe UI", 9)).pack(side=tk.RIGHT)

    def metric(self, parent: tk.Frame, label: str, value: str) -> tk.Label:
        box = tk.Frame(parent, bg=PANEL, highlightbackground=LINE, highlightthickness=1)
        box.pack(side=tk.LEFT, padx=(0, 8))
        tk.Label(box, text=label, bg=PANEL, fg=MUTED, font=("Segoe UI", 8, "bold")).pack(anchor="w", padx=10, pady=(6, 0))
        value_label = tk.Label(box, text=value, bg=PANEL, fg=INK, font=("Segoe UI", 13, "bold"))
        value_label.pack(anchor="w", padx=10, pady=(0, 6))
        return value_label

    def small_button(self, parent: tk.Frame, text: str, command) -> tk.Button:
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=CARD,
            fg=INK,
            activebackground=CARD_HOVER,
            activeforeground=INK,
            relief=tk.FLAT,
            padx=14,
            pady=8,
            font=("Segoe UI", 9),
        )

    def option_entry(self, parent: tk.Frame, label: str, variable: tk.StringVar, width: int) -> tk.Frame:
        box = tk.Frame(parent, bg=PANEL_2)
        tk.Label(box, text=label, bg=PANEL_2, fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w")
        tk.Entry(
            box,
            textvariable=variable,
            width=width,
            bg="#101720",
            fg=INK,
            insertbackground=INK,
            relief=tk.FLAT,
            font=("Segoe UI", 10),
        ).pack(anchor="w", ipady=4, pady=(2, 0))
        return box

    def on_list_configure(self, _event=None) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def on_canvas_configure(self, event) -> None:
        self.canvas.itemconfigure(self.canvas_window, width=event.width)

    def on_mousewheel(self, event) -> None:
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def clear_filter(self) -> None:
        self.search_var.set("")
        self.populate_tools()

    def set_category(self, category: str) -> None:
        self.category_var.set(category)
        self.update_category_buttons()
        self.populate_tools()

    def update_category_buttons(self) -> None:
        current = self.category_var.get()
        for category, button in self.category_buttons.items():
            selected = category == current
            color = ACCENT if selected else PANEL
            fg = "#06111d" if selected else INK
            button.configure(bg=color, fg=fg)

    def refresh(self) -> None:
        try:
            self.catalog.load()
            self.populate_tools()
            if self.current_item not in self.catalog.visible_tools():
                self.select_first_tool()
            self.status_var.set("Catalog refreshed.")
        except Exception as exc:
            messagebox.showerror("Refresh failed", str(exc))

    def populate_tools(self) -> None:
        for child in self.list_frame.winfo_children():
            child.destroy()
        self.card_widgets.clear()

        query = self.search_var.get().strip().lower()
        selected_category = self.category_var.get()
        visible = []
        main_tools = self.catalog.visible_tools()
        for item in main_tools:
            haystack = " ".join(
                str(item.get(key, "")) for key in ("menu", "name", "purpose", "launcher", "source_launcher")
            ).lower()
            if query and query not in haystack:
                continue
            if selected_category != "All" and self.category_for(item) != selected_category:
                continue
            visible.append(item)

        hidden_count = len(self.catalog.hidden_tools())
        self.count_label.configure(text=str(len(main_tools)))
        self.ready_label.configure(text=f"{self.catalog.ready_count(main_tools)}/{len(main_tools)}")

        for category in CATEGORIES[1:]:
            group_items = [item for item in visible if self.category_for(item) == category]
            if group_items or selected_category == category:
                self.add_section(f"{category} tools", group_items)
        if not visible:
            self.add_section("No matching tools", [])
        self.status_var.set(f"Showing {len(visible)} main tools. {hidden_count} advanced/report tools are hidden from this GUI.")
        self.highlight_current()

    def add_section(self, title: str, items: list[dict]) -> None:
        header = tk.Label(self.list_frame, text=title, bg=PANEL, fg=MUTED, font=("Segoe UI", 9, "bold"))
        header.pack(fill=tk.X, padx=12, pady=(14, 6), anchor="w")
        if not items:
            tk.Label(self.list_frame, text="No matching tools", bg=PANEL, fg="#65748a", font=("Segoe UI", 9)).pack(
                fill=tk.X, padx=16, pady=(0, 8), anchor="w"
            )
            return
        for item in items:
            self.add_card(item)

    def add_card(self, item: dict) -> None:
        status = self.catalog.status(item)
        card = tk.Frame(self.list_frame, bg=CARD, highlightbackground=LINE, highlightthickness=1)
        card.pack(fill=tk.X, padx=12, pady=5)
        self.card_widgets[str(item.get("menu", ""))] = card

        top = tk.Frame(card, bg=CARD)
        top.pack(fill=tk.X, padx=12, pady=(10, 2))
        category = self.category_for(item)
        number = tk.Label(
            top,
            text=str(item.get("menu", "")),
            bg=ACCENT if status == "Ready" else BAD,
            fg="#06111d",
            font=("Segoe UI", 10, "bold"),
            width=4,
        )
        number.pack(side=tk.LEFT)
        tk.Label(
            top,
            text=category,
            bg=CATEGORY_COLORS.get(category, CATEGORY_COLORS["Other"]),
            fg="#07111f",
            font=("Segoe UI", 8, "bold"),
            padx=8,
            pady=2,
        ).pack(side=tk.LEFT, padx=(8, 0))
        name = tk.Label(top, text=item.get("name", ""), bg=CARD, fg=INK, font=("Segoe UI", 10, "bold"))
        name.pack(side=tk.LEFT, padx=(10, 0), fill=tk.X, expand=True, anchor="w")
        status_label = tk.Label(
            top,
            text=status,
            bg=CARD,
            fg=GOOD if status == "Ready" else BAD,
            font=("Segoe UI", 9, "bold"),
        )
        status_label.pack(side=tk.RIGHT)

        purpose = item.get("purpose", "")
        if len(purpose) > 105:
            purpose = purpose[:102] + "..."
        tk.Label(card, text=purpose, bg=CARD, fg=MUTED, font=("Segoe UI", 9), justify=tk.LEFT, wraplength=390).pack(
            fill=tk.X, padx=12, pady=(2, 10), anchor="w"
        )

        for widget in card.winfo_children() + top.winfo_children():
            widget.bind("<Button-1>", lambda _event, tool=item: self.select_tool(tool))
            widget.bind("<Double-1>", lambda _event, tool=item: self.launch_tool(tool))
            widget.bind("<Enter>", lambda _event, frame=card: frame.configure(bg=CARD_HOVER))
            widget.bind("<Leave>", lambda _event, frame=card: self.restore_card_bg(frame))
        card.bind("<Button-1>", lambda _event, tool=item: self.select_tool(tool))
        card.bind("<Double-1>", lambda _event, tool=item: self.launch_tool(tool))
        card.bind("<Enter>", lambda _event, frame=card: frame.configure(bg=CARD_HOVER))
        card.bind("<Leave>", lambda _event, frame=card: self.restore_card_bg(frame))

    def restore_card_bg(self, frame: tk.Frame) -> None:
        frame.configure(bg=CARD)
        for child in frame.winfo_children():
            if isinstance(child, tk.Frame):
                child.configure(bg=CARD)
                for nested in child.winfo_children():
                    if nested.cget("bg") in {CARD_HOVER, CARD}:
                        nested.configure(bg=CARD)
            elif child.cget("bg") in {CARD_HOVER, CARD}:
                child.configure(bg=CARD)

    def is_daily(self, item: dict) -> bool:
        try:
            return int(item.get("menu", "999")) <= 8
        except ValueError:
            return True

    def category_for(self, item: dict) -> str:
        text = " ".join(str(item.get(key, "")) for key in ("name", "purpose", "launcher", "source_launcher")).lower()
        if "reaper" in text or "sound finder" in text:
            return "Production"
        if "p4" in text or "changelist" in text:
            return "P4"
        if "runtime" in text or "monitor" in text or "follow" in text:
            return "Runtime"
        if "register" in text or "unregister" in text or "scheduled" in text or "watch" in text:
            return "Automation"
        if "report" in text or "summary" in text or "dashboard" in text or "daily" in text or "log intelligence" in text:
            return "Reports"
        if "template" in text or "profiler" in text or "waapi" in text:
            return "Wwise"
        return "Other"

    def select_first_tool(self) -> None:
        tools = self.catalog.visible_tools()
        if tools:
            self.select_tool(tools[0])

    def select_tool(self, item: dict) -> None:
        self.current_item = item
        self.highlight_current()
        self.update_tool_options(item)
        status = self.catalog.status(item)
        launcher = self.catalog.launcher_path(item)
        source = self.catalog.source_path(item)

        self.detail_number.configure(text=str(item.get("menu", "")), bg=ACCENT if status == "Ready" else BAD)
        self.detail_name.configure(text=item.get("name", ""))
        self.detail_status.configure(text=status, fg=GOOD if status == "Ready" else BAD)

        self.write_text(self.purpose, item.get("purpose", ""))
        path_text = (
            f"Wrapper:\n{launcher}\n\n"
            f"Source:\n{source}\n\n"
            f"Config:\n{CONFIG_PATH}\n"
        )
        if self.is_voice_capture_tool(item):
            path_text += (
                "\nGUI options:\n"
                f"Duration seconds: {self.voice_duration_var.get()}\n"
                f"Interval seconds: {self.voice_interval_var.get()}\n"
            )
        self.write_text(self.paths, path_text)
        self.status_var.set(f"Selected: {item.get('name')}")

    def is_voice_capture_tool(self, item: dict) -> bool:
        return item.get("launcher") == "17_Wwise_Profiler_Voice_Capture.cmd"

    def update_tool_options(self, item: dict) -> None:
        self.voice_options.pack_forget()
        if self.is_voice_capture_tool(item):
            self.voice_options.pack(fill=tk.X)

    def parse_voice_capture_options(self) -> tuple[str, str] | None:
        try:
            duration = float(self.voice_duration_var.get().strip())
            interval = float(self.voice_interval_var.get().strip())
        except ValueError:
            messagebox.showerror("Invalid capture options", "Duration and interval must be numbers.")
            return None
        if duration < 1 or duration > 7200:
            messagebox.showerror("Invalid duration", "Duration must be between 1 and 7200 seconds.")
            return None
        if interval < 0.1 or interval > 60:
            messagebox.showerror("Invalid interval", "Interval must be between 0.1 and 60 seconds.")
            return None
        duration_text = str(int(duration)) if duration.is_integer() else str(duration)
        interval_text = str(int(interval)) if interval.is_integer() else str(interval)
        return duration_text, interval_text

    def highlight_current(self) -> None:
        current = str((self.current_item or {}).get("menu", ""))
        for menu, card in self.card_widgets.items():
            color = "#2a3c55" if menu == current else CARD
            card.configure(bg=color, highlightbackground=ACCENT if menu == current else LINE)
            for child in card.winfo_children():
                if isinstance(child, tk.Frame):
                    child.configure(bg=color)
                    for nested in child.winfo_children():
                        if nested.cget("bg") in {CARD, CARD_HOVER, "#2a3c55"}:
                            nested.configure(bg=color)
                elif child.cget("bg") in {CARD, CARD_HOVER, "#2a3c55"}:
                    child.configure(bg=color)

    def write_text(self, widget: tk.Text, text: str) -> None:
        widget.configure(state=tk.NORMAL)
        widget.delete("1.0", tk.END)
        widget.insert(tk.END, text)
        widget.configure(state=tk.DISABLED)

    def launch_selected(self) -> None:
        if not self.current_item:
            messagebox.showinfo("Launch", "Select a tool first.")
            return
        self.launch_tool(self.current_item)

    def launch_tool(self, item: dict) -> None:
        launcher = self.catalog.launcher_path(item)
        if not launcher.exists():
            messagebox.showerror("Missing launcher", str(launcher))
            return
        try:
            env = os.environ.copy()
            if self.is_voice_capture_tool(item):
                options = self.parse_voice_capture_options()
                if options is None:
                    return
                duration, interval = options
                env["EF_WWISE_PROFILER_DURATION"] = duration
                env["EF_WWISE_PROFILER_INTERVAL"] = interval
                self.status_var.set(f"Launched: {item.get('name')} ({duration}s / {interval}s)")
            else:
                self.status_var.set(f"Launched: {item.get('name')}")
            creationflags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0) if os.name == "nt" else 0
            subprocess.Popen(
                ["cmd.exe", "/d", "/c", str(launcher)],
                cwd=str(APP_DIR),
                env=env,
                close_fds=True,
                creationflags=creationflags,
            )
        except Exception as exc:
            messagebox.showerror("Launch failed", str(exc))

    def open_source(self) -> None:
        if self.current_item:
            self.open_path(self.catalog.source_path(self.current_item))

    def open_wrapper(self) -> None:
        if self.current_item:
            self.open_path(self.catalog.launcher_path(self.current_item))

    def copy_source_path(self) -> None:
        if not self.current_item:
            return
        path = str(self.catalog.source_path(self.current_item))
        self.clipboard_clear()
        self.clipboard_append(path)
        self.status_var.set(f"Copied: {path}")

    def open_path(self, path: Path) -> None:
        try:
            if not path.exists():
                messagebox.showerror("Path not found", str(path))
                return
            os.startfile(str(path if path.is_dir() else path.parent))
        except Exception as exc:
            messagebox.showerror("Open failed", str(exc))


def main() -> None:
    app = EFAudioToolsGui()
    app.mainloop()


if __name__ == "__main__":
    main()
