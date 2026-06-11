#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import math
import os
import queue
import random
import re
import shutil
import subprocess
import sys
import threading
import tkinter as tk
import traceback
import time
from pathlib import Path
from tkinter import filedialog, messagebox, ttk


APP_DIR = Path(__file__).resolve().parent
CORE_SCRIPT = APP_DIR / "ProjectEF_AnimationWwiseEvent_AutoConfig.py"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import ProjectEF_AnimationWwiseEvent_AutoConfig as core


DEFAULT_ANIMATION = str(
    core.DEFAULT_UNITY_ROOT
    / "Assets/GameProject/ArtAssets/Bird/Clp_Bird_Mallards01_General_Fly_Loop.fbx"
)
DEFAULT_WWISE_EVENT = "Play_Bird_Wing_Flap_Small"

BG = "#12161c"
PANEL = "#1a2028"
PANEL_2 = "#222a34"
CARD = "#28313d"
INK = "#edf3f8"
MUTED = "#a7b3c0"
LINE = "#3a4654"
ACCENT = "#3fb7a4"
ACCENT_HOVER = "#55c8b7"
WARN = "#f0b65a"
BAD = "#f07178"
GOOD = "#65d18f"


class AnimationWwiseEventAutoConfigGui(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("ProjectEF Animation Wwise Event AutoConfig GUI")
        self.geometry("1180x780")
        self.minsize(1040, 660)
        self.configure(bg=BG)

        self.unity_root_var = tk.StringVar(value=str(core.DEFAULT_UNITY_ROOT))
        self.wwise_root_var = tk.StringVar(value=str(core.DEFAULT_WWISE_ROOT))
        self.animation_var = tk.StringVar(value=DEFAULT_ANIMATION)
        self.wwise_event_var = tk.StringVar(value=DEFAULT_WWISE_EVENT)
        self.prefab_var = tk.StringVar(value="")
        self.mode_var = tk.StringVar(value="downstroke")
        self.endpoint_regex_var = tk.StringVar(value=r"wing|hand")
        self.sample_fps_var = tk.StringVar(value="60")
        self.strength_ratio_var = tk.StringVar(value="0.30")
        self.min_gap_var = tk.StringVar(value="0.28")
        self.skip_prefab_component_var = tk.BooleanVar(value=False)
        self.audio_aware_spacing_var = tk.BooleanVar(value=True)
        self.audio_mode_var = tk.StringVar(value="Click")
        self.playback_speed_var = tk.StringVar(value="1.0")
        self.loop_preview_var = tk.BooleanVar(value=True)

        self.resolved_animation_var = tk.StringVar(value="未定位")
        self.source_animation_var = tk.StringVar(value="未定位")
        self.resolved_prefab_var = tk.StringVar(value="自动")
        self.wwise_evidence_var = tk.StringVar(value="未校验")
        self.summary_var = tk.StringVar(value="填写动画和 Wwise Event 后，可先定位资源，再直接预览。")
        self.status_var = tk.StringVar(value="Ready")

        self.messages: queue.Queue[tuple[str, object]] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.command_buttons: list[tk.Button] = []
        self.last_report_md: Path | None = None
        self.last_report_json: Path | None = None
        self.last_command: list[str] | None = None
        self.preview_data: dict[str, object] | None = None
        self.last_report: dict[str, object] | None = None
        self.unity_preview_request_path: Path | None = None
        self.auto_open_unity_preview_var = tk.BooleanVar(value=False)
        self.playing = False
        self.play_start_perf = 0.0
        self.play_base_time = 0.0
        self.next_event_index = 0

        self.configure_style()
        self.build_ui()
        self.after(100, self.pump_messages)

    def configure_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=INK)
        style.configure("Treeview", background="#10151b", fieldbackground="#10151b", foreground=INK, rowheight=24)
        style.configure("Treeview.Heading", background=PANEL_2, foreground=INK, relief="flat")
        style.map("Treeview", background=[("selected", "#315f58")])
        style.configure("TCombobox", fieldbackground=PANEL_2, background=PANEL_2, foreground=INK)

    def build_ui(self) -> None:
        root = tk.Frame(self, bg=BG)
        root.pack(fill=tk.BOTH, expand=True)

        header = tk.Frame(root, bg=BG)
        header.pack(fill=tk.X, padx=18, pady=(16, 10))
        tk.Label(
            header,
            text="Animation Wwise Event AutoConfig",
            bg=BG,
            fg=INK,
            font=("Segoe UI", 22, "bold"),
        ).pack(anchor="w")
        tk.Label(
            header,
            text="定位 .fbx/.anim 和 Wwise Event，预览自动分析出的打点，再一键写入 Animation Event 与接收器配置。",
            bg=BG,
            fg=MUTED,
            font=("Segoe UI", 10),
        ).pack(anchor="w", pady=(2, 0))

        config = tk.Frame(root, bg=PANEL, highlightbackground=LINE, highlightthickness=1)
        config.pack(fill=tk.X, padx=18, pady=(0, 12))
        self.path_row(config, "Unity Root", self.unity_root_var, self.choose_unity_root, self.open_unity_root).pack(
            fill=tk.X, padx=12, pady=(12, 6)
        )
        self.path_row(config, "Wwise Root", self.wwise_root_var, self.choose_wwise_root, self.open_wwise_root).pack(
            fill=tk.X, padx=12, pady=6
        )
        self.path_row(config, "Animation", self.animation_var, self.choose_animation, self.open_animation_location).pack(
            fill=tk.X, padx=12, pady=6
        )
        self.path_row(config, "Prefab", self.prefab_var, self.choose_prefab, self.open_prefab_location, optional=True).pack(
            fill=tk.X, padx=12, pady=6
        )

        event_row = tk.Frame(config, bg=PANEL)
        event_row.pack(fill=tk.X, padx=12, pady=(6, 12))
        tk.Label(event_row, text="Wwise Event", bg=PANEL, fg=MUTED, font=("Segoe UI", 9, "bold"), width=13, anchor="w").pack(
            side=tk.LEFT
        )
        tk.Entry(
            event_row,
            textvariable=self.wwise_event_var,
            bg=PANEL_2,
            fg=INK,
            insertbackground=INK,
            relief=tk.FLAT,
            font=("Consolas", 9),
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=6, padx=(4, 8))
        self.command_button(event_row, "校验 / 定位", self.resolve_assets, CARD, INK).pack(side=tk.LEFT, padx=(0, 8))
        self.command_button(event_row, "打开 WWU", self.open_wwise_event_location, CARD, INK).pack(side=tk.LEFT)

        options = tk.Frame(root, bg=PANEL, highlightbackground=LINE, highlightthickness=1)
        options.pack(fill=tk.X, padx=18, pady=(0, 12))
        self.option_row(options).pack(fill=tk.X, padx=12, pady=10)

        actions = tk.Frame(root, bg=PANEL, highlightbackground=LINE, highlightthickness=1)
        actions.pack(fill=tk.X, padx=18, pady=(0, 12))
        self.command_button(actions, "定位资源", self.resolve_assets, CARD, INK).pack(side=tk.LEFT, padx=(12, 8), pady=10)
        self.command_button(actions, "直接预览", self.preview_config, ACCENT, "#06120f").pack(side=tk.LEFT, padx=(0, 8), pady=10)
        self.command_button(actions, "写入 / 修改配置", self.apply_config, WARN, "#161007").pack(side=tk.LEFT, padx=(0, 8), pady=10)
        self.command_button(actions, "锁定可编辑 .anim", self.use_resolved_animation, CARD, INK).pack(side=tk.LEFT, padx=(0, 8), pady=10)
        self.command_button(actions, "Unity Preview", self.open_unity_preview, CARD, INK).pack(side=tk.LEFT, padx=(0, 8), pady=10)
        self.command_button(actions, "Project Audio", self.open_project_audio_preview, CARD, INK).pack(
            side=tk.LEFT, padx=(0, 8), pady=10
        )
        self.command_button(actions, "Unity Edit Keys", self.open_anim_text_editor, CARD, INK).pack(side=tk.LEFT, padx=(0, 8), pady=10)
        self.command_button(actions, "打开报告", self.open_last_report, CARD, INK).pack(side=tk.LEFT, padx=(0, 8), pady=10)
        self.command_button(actions, "报告目录", self.open_report_folder, CARD, INK).pack(side=tk.LEFT, padx=(0, 8), pady=10)
        self.command_button(actions, "复制命令", self.copy_cli_command, CARD, INK).pack(side=tk.LEFT, padx=(0, 8), pady=10)
        self.command_button(actions, "清空日志", self.clear_log, CARD, INK).pack(side=tk.LEFT, padx=(0, 12), pady=10)

        body = tk.PanedWindow(root, orient=tk.HORIZONTAL, sashrelief=tk.FLAT, bg=BG, bd=0, sashwidth=8)
        body.pack(fill=tk.BOTH, expand=True, padx=18, pady=(0, 12))

        left = tk.Frame(body, bg=PANEL, highlightbackground=LINE, highlightthickness=1)
        right = tk.Frame(body, bg=PANEL, highlightbackground=LINE, highlightthickness=1)
        body.add(left, minsize=430)
        body.add(right, minsize=520)

        self.build_location_panel(left)
        self.build_preview_panel(right)

        footer = tk.Frame(root, bg=BG)
        footer.pack(fill=tk.X, padx=18, pady=(0, 12))
        tk.Label(footer, textvariable=self.status_var, bg=BG, fg=MUTED, font=("Segoe UI", 9)).pack(side=tk.LEFT)
        tk.Label(footer, text=str(CORE_SCRIPT), bg=BG, fg="#6f7b88", font=("Segoe UI", 9)).pack(side=tk.RIGHT)

    def path_row(
        self,
        parent: tk.Frame,
        label: str,
        variable: tk.StringVar,
        browse_command,
        locate_command,
        optional: bool = False,
    ) -> tk.Frame:
        row = tk.Frame(parent, bg=PANEL)
        tk.Label(row, text=label, bg=PANEL, fg=MUTED, font=("Segoe UI", 9, "bold"), width=13, anchor="w").pack(
            side=tk.LEFT
        )
        entry = tk.Entry(
            row,
            textvariable=variable,
            bg=PANEL_2,
            fg=INK,
            insertbackground=INK,
            relief=tk.FLAT,
            font=("Consolas", 9),
        )
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=6, padx=(4, 8))
        if optional:
            self.command_button(row, "自动", lambda: variable.set(""), CARD, INK).pack(side=tk.LEFT, padx=(0, 8))
        self.command_button(row, "浏览", browse_command, CARD, INK).pack(side=tk.LEFT, padx=(0, 8))
        self.command_button(row, "定位", locate_command, CARD, INK).pack(side=tk.LEFT)
        return row

    def option_row(self, parent: tk.Frame) -> tk.Frame:
        row = tk.Frame(parent, bg=PANEL)
        tk.Label(row, text="分析模式", bg=PANEL, fg=MUTED, font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Combobox(
            row,
            textvariable=self.mode_var,
            values=("downstroke", "speed"),
            state="readonly",
            width=12,
        ).pack(side=tk.LEFT, padx=(0, 16))
        self.small_entry(row, "端点匹配", self.endpoint_regex_var, 14)
        self.small_entry(row, "采样 FPS", self.sample_fps_var, 6)
        self.small_entry(row, "强度阈值", self.strength_ratio_var, 6)
        self.small_entry(row, "最小间隔", self.min_gap_var, 6)
        tk.Checkbutton(
            row,
            text="音频感知间隔",
            variable=self.audio_aware_spacing_var,
            bg=PANEL,
            fg=INK,
            activebackground=PANEL,
            activeforeground=INK,
            selectcolor=PANEL_2,
        ).pack(side=tk.LEFT, padx=(0, 12))
        tk.Checkbutton(
            row,
            text="Preview后打开Unity",
            variable=self.auto_open_unity_preview_var,
            bg=PANEL,
            fg=INK,
            activebackground=PANEL,
            activeforeground=INK,
            selectcolor=PANEL_2,
        ).pack(side=tk.LEFT, padx=(0, 12))
        tk.Checkbutton(
            row,
            text="不处理 Prefab 接收器",
            variable=self.skip_prefab_component_var,
            bg=PANEL,
            fg=INK,
            activebackground=PANEL,
            activeforeground=INK,
            selectcolor=PANEL_2,
        ).pack(side=tk.LEFT, padx=(12, 0))
        return row

    def small_entry(self, parent: tk.Frame, label: str, variable: tk.StringVar, width: int) -> None:
        tk.Label(parent, text=label, bg=PANEL, fg=MUTED, font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=(0, 6))
        tk.Entry(
            parent,
            textvariable=variable,
            bg=PANEL_2,
            fg=INK,
            insertbackground=INK,
            relief=tk.FLAT,
            font=("Consolas", 9),
            width=width,
        ).pack(side=tk.LEFT, ipady=5, padx=(0, 16))

    def command_button(self, parent: tk.Frame, text: str, command, bg: str, fg: str) -> tk.Button:
        button = tk.Button(
            parent,
            text=text,
            command=command,
            bg=bg,
            fg=fg,
            activebackground=ACCENT_HOVER if bg == ACCENT else "#344250",
            activeforeground=fg,
            relief=tk.FLAT,
            padx=12,
            pady=7,
            font=("Segoe UI", 9, "bold"),
        )
        self.command_buttons.append(button)
        return button

    def build_location_panel(self, parent: tk.Frame) -> None:
        tk.Label(parent, text="定位结果", bg=PANEL, fg=MUTED, font=("Segoe UI", 10, "bold")).pack(
            anchor="w", padx=12, pady=(10, 8)
        )
        self.info_line(parent, "Editable .anim", self.resolved_animation_var, GOOD).pack(fill=tk.X, padx=12, pady=4)
        self.info_line(parent, "Source .fbx", self.source_animation_var, MUTED).pack(fill=tk.X, padx=12, pady=4)
        self.info_line(parent, "Prefab", self.resolved_prefab_var, MUTED).pack(fill=tk.X, padx=12, pady=4)
        self.info_line(parent, "Wwise evidence", self.wwise_evidence_var, MUTED).pack(fill=tk.X, padx=12, pady=4)

        tk.Label(parent, text="摘要", bg=PANEL, fg=MUTED, font=("Segoe UI", 10, "bold")).pack(
            anchor="w", padx=12, pady=(14, 6)
        )
        tk.Label(
            parent,
            textvariable=self.summary_var,
            bg="#10151b",
            fg=INK,
            justify=tk.LEFT,
            anchor="nw",
            wraplength=390,
            padx=10,
            pady=10,
        ).pack(fill=tk.X, padx=12, pady=(0, 10))

        tk.Label(parent, text="日志", bg=PANEL, fg=MUTED, font=("Segoe UI", 10, "bold")).pack(
            anchor="w", padx=12, pady=(4, 6)
        )
        self.log = tk.Text(
            parent,
            bg="#10151b",
            fg=INK,
            insertbackground=INK,
            relief=tk.FLAT,
            wrap=tk.WORD,
            font=("Consolas", 9),
            padx=10,
            pady=10,
            height=13,
        )
        self.log.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))
        self.log.insert(tk.END, "Ready.\n")
        self.log.configure(state=tk.DISABLED)

    def build_preview_panel(self, parent: tk.Frame) -> None:
        tk.Label(parent, text="预览打点", bg=PANEL, fg=MUTED, font=("Segoe UI", 10, "bold")).pack(
            anchor="w", padx=12, pady=(10, 8)
        )
        self.event_tree = ttk.Treeview(parent, columns=("index", "time"), show="headings", height=12)
        self.event_tree.heading("index", text="#")
        self.event_tree.heading("time", text="Time (s)")
        self.event_tree.column("index", width=70, anchor="center", stretch=False)
        self.event_tree.column("time", width=160, anchor="w")
        self.event_tree.pack(fill=tk.X, padx=12, pady=(0, 10))

        controls = tk.Frame(parent, bg=PANEL)
        controls.pack(fill=tk.X, padx=12, pady=(0, 10))
        self.play_button = self.command_button(controls, "播放/暂停", self.toggle_preview_playback, ACCENT, "#06120f")
        self.play_button.pack(side=tk.LEFT, padx=(0, 8))
        self.command_button(controls, "停止", self.stop_preview_playback, CARD, INK).pack(side=tk.LEFT, padx=(0, 12))
        tk.Label(controls, text="音频", bg=PANEL, fg=MUTED, font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Combobox(
            controls,
            textvariable=self.audio_mode_var,
            values=("Click", "Wwise Source", "Mute"),
            state="readonly",
            width=12,
        ).pack(side=tk.LEFT, padx=(0, 12))
        tk.Label(controls, text="速度", bg=PANEL, fg=MUTED, font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Combobox(
            controls,
            textvariable=self.playback_speed_var,
            values=("0.5", "1.0", "2.0", "4.0"),
            state="readonly",
            width=6,
        ).pack(side=tk.LEFT, padx=(0, 12))
        tk.Checkbutton(
            controls,
            text="Loop",
            variable=self.loop_preview_var,
            bg=PANEL,
            fg=INK,
            activebackground=PANEL,
            activeforeground=INK,
            selectcolor=PANEL_2,
        ).pack(side=tk.LEFT)

        self.preview_canvas = tk.Canvas(parent, bg="#10151b", highlightthickness=0, height=230)
        self.preview_canvas.pack(fill=tk.X, padx=12, pady=(0, 10))
        self.preview_canvas.bind("<Configure>", lambda _event: self.draw_preview(self.current_preview_time()))

        tk.Label(parent, text="分析骨骼 / 端点", bg=PANEL, fg=MUTED, font=("Segoe UI", 10, "bold")).pack(
            anchor="w", padx=12, pady=(2, 6)
        )
        self.endpoint_text = tk.Text(
            parent,
            bg="#10151b",
            fg=INK,
            insertbackground=INK,
            relief=tk.FLAT,
            wrap=tk.NONE,
            font=("Consolas", 9),
            padx=10,
            pady=10,
            height=8,
        )
        self.endpoint_text.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))
        self.endpoint_text.configure(state=tk.DISABLED)

    def info_line(self, parent: tk.Frame, label: str, variable: tk.StringVar, value_color: str) -> tk.Frame:
        row = tk.Frame(parent, bg=PANEL)
        tk.Label(row, text=label, bg=PANEL, fg=MUTED, font=("Segoe UI", 9, "bold"), width=15, anchor="w").pack(side=tk.LEFT)
        tk.Label(
            row,
            textvariable=variable,
            bg="#10151b",
            fg=value_color,
            anchor="w",
            justify=tk.LEFT,
            wraplength=295,
            padx=8,
            pady=6,
        ).pack(side=tk.LEFT, fill=tk.X, expand=True)
        return row

    def choose_unity_root(self) -> None:
        path = filedialog.askdirectory(initialdir=self.unity_root_var.get() or str(core.DEFAULT_UNITY_ROOT))
        if path:
            self.unity_root_var.set(path)

    def choose_wwise_root(self) -> None:
        path = filedialog.askdirectory(initialdir=self.wwise_root_var.get() or str(core.DEFAULT_WWISE_ROOT))
        if path:
            self.wwise_root_var.set(path)

    def choose_animation(self) -> None:
        initial = self.animation_var.get() or str(Path(self.unity_root_var.get()) / "Assets")
        initial_dir = str(Path(initial).parent if Path(initial).suffix else Path(initial))
        path = filedialog.askopenfilename(
            initialdir=initial_dir,
            title="选择 Animation .anim 或源 .fbx",
            filetypes=(("Unity Animation / FBX", "*.anim *.fbx"), ("Unity Animation", "*.anim"), ("FBX", "*.fbx"), ("All files", "*.*")),
        )
        if path:
            self.animation_var.set(path)

    def choose_prefab(self) -> None:
        initial = self.prefab_var.get() or str(Path(self.unity_root_var.get()) / "Assets")
        initial_dir = str(Path(initial).parent if Path(initial).suffix else Path(initial))
        path = filedialog.askopenfilename(
            initialdir=initial_dir,
            title="选择 Prefab，留空则按动画目录自动推断",
            filetypes=(("Unity Prefab", "*.prefab"), ("All files", "*.*")),
        )
        if path:
            self.prefab_var.set(path)

    def resolve_assets(self) -> None:
        self.run_background("正在定位资源...", self.resolve_worker)

    def resolve_worker(self) -> None:
        data = self.resolve_current()
        self.messages.put(("resolved", data))

    def preview_config(self) -> None:
        self.run_background("正在预览，不写入 Unity 文件...", lambda: self.run_tool_worker(apply=False))

    def apply_config(self) -> None:
        if not messagebox.askyesno(
            "确认写入",
            "这会修改目标 .anim，并按需要确保 AnimationWwiseEventReceiver 脚本和 Prefab 接收器配置存在。\n\n继续写入吗？",
        ):
            return
        self.run_background("正在写入 / 修改配置...", lambda: self.run_tool_worker(apply=True))

    def resolve_current(self) -> dict[str, object]:
        unity_root = core.normalize_path(self.required_text(self.unity_root_var, "Unity Root"))
        wwise_root = core.normalize_path(self.required_text(self.wwise_root_var, "Wwise Root"))
        animation_query = self.required_text(self.animation_var, "Animation")
        event_name = self.required_text(self.wwise_event_var, "Wwise Event")
        prefab_query = self.prefab_var.get().strip() or None

        animation_path, source_animation_path = core.resolve_animation_asset(unity_root, animation_query)
        prefab_path = core.resolve_prefab(unity_root, animation_path, prefab_query)
        wwise_validation = core.validate_wwise_event(wwise_root, event_name)

        return {
            "animation": animation_path,
            "source_animation": source_animation_path,
            "prefab": prefab_path,
            "wwise_valid": wwise_validation[0],
            "wwise_evidence": wwise_validation[1],
        }

    def build_tool_argv(self, apply: bool) -> list[str]:
        sample_fps = float(self.required_text(self.sample_fps_var, "采样 FPS"))
        strength_ratio = float(self.required_text(self.strength_ratio_var, "强度阈值"))
        min_gap = float(self.required_text(self.min_gap_var, "最小间隔"))
        argv = [
            "--unity-root",
            self.required_text(self.unity_root_var, "Unity Root"),
            "--wwise-root",
            self.required_text(self.wwise_root_var, "Wwise Root"),
            "--animation",
            self.required_text(self.animation_var, "Animation"),
            "--wwise-event",
            self.required_text(self.wwise_event_var, "Wwise Event"),
            "--mode",
            self.mode_var.get(),
            "--endpoint-regex",
            self.required_text(self.endpoint_regex_var, "端点匹配"),
            "--sample-fps",
            str(sample_fps),
            "--strength-ratio",
            str(strength_ratio),
            "--min-gap",
            str(min_gap),
        ]
        prefab = self.prefab_var.get().strip()
        if prefab:
            argv.extend(["--prefab", prefab])
        if self.skip_prefab_component_var.get():
            argv.append("--skip-prefab-component")
        if not self.audio_aware_spacing_var.get():
            argv.append("--disable-audio-aware-spacing")
        if apply:
            argv.append("--apply")
        return argv

    def run_tool_worker(self, apply: bool) -> None:
        argv = self.build_tool_argv(apply)
        command = [sys.executable, "-B", str(CORE_SCRIPT), *argv]
        self.last_command = command
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        completed = subprocess.run(
            command,
            cwd=str(APP_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creationflags,
            env=env,
        )
        output = completed.stdout
        if completed.stderr:
            output = output.rstrip() + "\n\n[stderr]\n" + completed.stderr
        if completed.returncode != 0:
            raise RuntimeError(output or f"Tool failed with exit code {completed.returncode}")

        paths = self.extract_report_paths(output)
        report = self.load_report(paths.get("json"))
        preview_data = self.build_preview_data(report) if report else None
        self.messages.put(
            (
                "run_done",
                {
                    "apply": apply,
                    "output": output,
                    "report": report,
                    "preview_data": preview_data,
                    "md": paths.get("md"),
                    "json": paths.get("json"),
                    "command": command,
                },
            )
        )

    def required_text(self, variable: tk.StringVar, label: str) -> str:
        value = variable.get().strip()
        if not value:
            raise ValueError(f"{label} 不能为空。")
        return value

    def extract_report_paths(self, output: str) -> dict[str, Path]:
        result: dict[str, Path] = {}
        report_match = re.search(r"^Report:\s*(.+)$", output, re.M)
        json_match = re.search(r"^JSON:\s*(.+)$", output, re.M)
        if report_match:
            result["md"] = Path(report_match.group(1).strip())
        if json_match:
            result["json"] = Path(json_match.group(1).strip())
        return result

    def load_report(self, json_path: Path | None) -> dict[str, object] | None:
        if json_path and json_path.exists():
            return json.loads(json_path.read_text(encoding="utf-8-sig"))
        event_name = self.wwise_event_var.get().strip()
        safe_event = re.sub(r"[^A-Za-z0-9_.-]+", "_", event_name)
        candidates = sorted(
            core.REPORT_DIR.glob(f"ProjectEF_AnimationWwiseEvent_AutoConfig_{safe_event}_*.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if candidates:
            return json.loads(candidates[0].read_text(encoding="utf-8-sig"))
        return None

    def build_preview_data(self, report: dict[str, object] | None) -> dict[str, object] | None:
        if not report:
            return None
        analysis = report.get("analysis") if isinstance(report.get("analysis"), dict) else {}
        animation_path = Path(str(report.get("animation") or ""))
        prefab_value = report.get("prefab")
        prefab_path = Path(str(prefab_value)) if prefab_value else None
        event_times = analysis.get("event_times", []) if isinstance(analysis, dict) else []
        endpoint_paths = analysis.get("endpoint_paths", []) if isinstance(analysis, dict) else []
        audio_files = self.find_wwise_audio_files(Path(self.wwise_root_var.get()), str(report.get("wwise_event") or ""))

        samples: list[tuple[float, float]] = []
        clip_length = float(analysis.get("clip_length") or 0.0) if isinstance(analysis, dict) else 0.0
        try:
            _text, parsed_clip_length, curves = core.parse_animation_clip(animation_path)
            clip_length = parsed_clip_length or clip_length
            if prefab_path and prefab_path.exists() and isinstance(endpoint_paths, list) and endpoint_paths:
                root_names = {curve.path.split("/")[0] for curve in curves if curve.path}
                transforms, _prefab_text = core.parse_prefab_transforms(prefab_path, root_names)
                curve_map = {curve.path: curve for curve in curves}
                max_samples = min(max(int(clip_length * 30), 120), 2400)
                for index in range(max_samples + 1):
                    t = clip_length * index / max_samples
                    values = []
                    for endpoint in endpoint_paths:
                        endpoint_text = str(endpoint)
                        if endpoint_text in transforms:
                            values.append(core.world_pos_at(endpoint_text, t, transforms, curve_map)[1])
                    if values:
                        samples.append((t, sum(values) / len(values)))
        except Exception:
            samples = []

        return {
            "clip_length": clip_length,
            "event_times": [float(value) for value in event_times] if isinstance(event_times, list) else [],
            "samples": samples,
            "audio_files": audio_files,
        }

    def find_wwise_audio_files(self, wwise_root: Path, event_name: str) -> list[Path]:
        if not wwise_root.exists() or not event_name:
            return []

        target_names: set[str] = set()
        event_pattern = re.compile(rf'<Event\s+Name="{re.escape(event_name)}"(?=[\s>/]).*?</Event>', re.S)
        events_root = wwise_root / "Events"
        search_roots = [events_root] if events_root.exists() else [wwise_root]
        for root in search_roots:
            for path in root.rglob("*.wwu"):
                try:
                    text = core.read_text(path)
                except Exception:
                    continue
                for event_match in event_pattern.finditer(text):
                    target_names.update(re.findall(r'<ObjectRef\s+Name="([^"]+)"', event_match.group(0)))

        audio_names: set[str] = set()
        for path in wwise_root.rglob("*.wwu"):
            try:
                text = core.read_text(path)
            except Exception:
                continue
            for target_name in target_names:
                marker = f'Name="{target_name}"'
                index = text.find(marker)
                if index >= 0:
                    block = text[index : index + 300000]
                    audio_names.update(re.findall(r"<AudioFile>([^<]+\.wav)</AudioFile>", block, re.I))

        originals = wwise_root / "Originals"
        if not originals.exists():
            return []

        matches: list[Path] = []
        if audio_names:
            lower_names = {name.lower() for name in audio_names}
            matches = [path for path in originals.rglob("*.wav") if path.name.lower() in lower_names]

        if not matches:
            base = re.sub(r"^Play_", "", event_name, flags=re.I).lower()
            matches = [path for path in originals.rglob("*.wav") if base in path.stem.lower()]

        return sorted(matches)[:32]

    def run_background(self, status: str, target) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("正在执行", "当前任务还没结束，请稍等。")
            return
        self.append_log(status)
        self.set_running(True, status)

        def wrapped() -> None:
            try:
                target()
            except Exception as exc:
                self.messages.put(("error", {"error": exc, "trace": traceback.format_exc()}))
            finally:
                self.messages.put(("idle", None))

        self.worker = threading.Thread(target=wrapped, daemon=True)
        self.worker.start()

    def pump_messages(self) -> None:
        try:
            while True:
                kind, payload = self.messages.get_nowait()
                if kind == "resolved":
                    self.apply_resolved(payload)  # type: ignore[arg-type]
                elif kind == "run_done":
                    self.apply_run_done(payload)  # type: ignore[arg-type]
                elif kind == "error":
                    self.apply_error(payload)  # type: ignore[arg-type]
                elif kind == "idle":
                    self.set_running(False, "Ready")
        except queue.Empty:
            pass
        self.after(100, self.pump_messages)

    def apply_resolved(self, payload: dict[str, object]) -> None:
        animation = payload.get("animation")
        source_animation = payload.get("source_animation")
        prefab = payload.get("prefab")
        evidence = payload.get("wwise_evidence")
        valid = bool(payload.get("wwise_valid"))
        self.resolved_animation_var.set(str(animation) if animation else "未定位")
        self.source_animation_var.set(str(source_animation) if source_animation else "无源 FBX 或直接使用 .anim")
        self.resolved_prefab_var.set(str(prefab) if prefab else "未找到 / 未指定")
        self.wwise_evidence_var.set(str(evidence) if evidence else "未校验")
        self.summary_var.set(
            "资源定位完成。\n"
            f"Wwise Event: {'有效' if valid else '未找到'}\n"
            "下一步可以点“直接预览”查看打点，或调整分析参数后再预览。"
        )
        self.append_log("定位完成。")
        self.append_log(f"Editable .anim: {animation}")
        if source_animation:
            self.append_log(f"Source .fbx: {source_animation}")
        self.append_log(f"Prefab: {prefab or 'None'}")
        self.append_log(f"Wwise: {'OK' if valid else 'Missing'} - {evidence}")

    def apply_run_done(self, payload: dict[str, object]) -> None:
        output = str(payload.get("output") or "")
        report = payload.get("report")
        preview_data = payload.get("preview_data")
        md = payload.get("md")
        json_path = payload.get("json")
        apply = bool(payload.get("apply"))
        if isinstance(md, Path):
            self.last_report_md = md
        if isinstance(json_path, Path):
            self.last_report_json = json_path
        self.append_log(output)

        if isinstance(report, dict):
            self.last_report = report
            self.update_preview_from_report(report, apply, preview_data if isinstance(preview_data, dict) else None)
            self.write_unity_preview_request(report)
            if self.auto_open_unity_preview_var.get() and not apply:
                self.open_unity_preview()
        else:
            self.update_preview_from_stdout(output)
            self.summary_var.set("执行完成，但没有读到 JSON 报告；已从命令输出里提取基础打点。请查看日志。")
        self.status_var.set("写入完成" if apply else "预览完成")
        if apply:
            messagebox.showinfo("完成", "Animation Wwise Event 配置已写入。")

    def update_preview_from_report(
        self,
        report: dict[str, object],
        apply: bool,
        preview_data: dict[str, object] | None,
    ) -> None:
        analysis = report.get("analysis") if isinstance(report.get("analysis"), dict) else {}
        wwise_design = report.get("wwise_design") if isinstance(report.get("wwise_design"), dict) else {}
        animation = str(report.get("animation") or "")
        prefab = str(report.get("prefab") or "")
        evidence = str(report.get("wwise_event_evidence") or "")
        event_name = str(report.get("wwise_event") or "")
        event_times = analysis.get("event_times", []) if isinstance(analysis, dict) else []
        endpoint_paths = analysis.get("endpoint_paths", []) if isinstance(analysis, dict) else []
        changed_files = report.get("changed_files", [])

        self.resolved_animation_var.set(animation or "未定位")
        self.source_animation_var.set(str(report.get("source_animation") or "无源 FBX 或直接使用 .anim"))
        self.resolved_prefab_var.set(prefab or "未找到 / 未指定")
        self.wwise_evidence_var.set(evidence)

        for row in self.event_tree.get_children():
            self.event_tree.delete(row)
        if isinstance(event_times, list):
            for index, time_value in enumerate(event_times, start=1):
                self.event_tree.insert("", tk.END, values=(index, f"{float(time_value):.3f}"))

        endpoint_lines = []
        if isinstance(endpoint_paths, list):
            endpoint_lines.extend(str(path) for path in endpoint_paths)
        if isinstance(changed_files, list):
            endpoint_lines.append("")
            endpoint_lines.append("Changed files:" if apply else "Planned changed files:")
            endpoint_lines.extend(str(path) for path in changed_files)
        if isinstance(wwise_design, dict):
            endpoint_lines.append("")
            endpoint_lines.append("Wwise design:")
            endpoint_lines.append(f"target: {wwise_design.get('target_type')} / {', '.join(wwise_design.get('target_names', []))}")
            endpoint_lines.append(f"audio sources: {wwise_design.get('audio_source_count')}")
            endpoint_lines.append(
                f"duration range: {self.format_seconds(wwise_design.get('min_duration'))} - "
                f"{self.format_seconds(wwise_design.get('max_duration'))}"
            )
            endpoint_lines.append(f"effective min gap: {self.format_seconds(wwise_design.get('effective_min_gap'))}")
            for note in wwise_design.get("notes", []) if isinstance(wwise_design.get("notes"), list) else []:
                endpoint_lines.append(f"- {note}")
        self.set_text(self.endpoint_text, "\n".join(endpoint_lines) or "No endpoint data.")
        self.preview_data = preview_data
        self.stop_preview_playback(redraw=False)
        self.draw_preview(0.0)

        count = len(event_times) if isinstance(event_times, list) else 0
        valid = bool(report.get("wwise_event_valid"))
        action = "已写入" if apply else "预览"
        self.summary_var.set(
            f"{action}: {event_name}\n"
            f"打点数量: {count}\n"
            f"Wwise 校验: {'有效' if valid else '未找到'}\n"
            f"模式: {analysis.get('mode')} / {analysis.get('metric') if isinstance(analysis, dict) else ''}\n"
            f"选择策略: {analysis.get('selection_policy') if isinstance(analysis, dict) else ''}\n"
            f"实际间隔: {self.format_seconds(wwise_design.get('effective_min_gap') if isinstance(wwise_design, dict) else None)}\n"
            f"报告: {self.last_report_md or 'None'}"
        )

    def format_seconds(self, value: object) -> str:
        try:
            if value is None:
                return "unknown"
            return f"{float(value):.3f}s"
        except Exception:
            return str(value)

    def update_preview_from_stdout(self, output: str) -> None:
        event_line = re.search(r"Event times:\s*\n([0-9.,\s]+)", output, re.M)
        if not event_line:
            return
        times = [float(value) for value in re.findall(r"[0-9]+(?:\.[0-9]+)?", event_line.group(1))]
        for row in self.event_tree.get_children():
            self.event_tree.delete(row)
        for index, time_value in enumerate(times, start=1):
            self.event_tree.insert("", tk.END, values=(index, f"{time_value:.3f}"))
        clip_length = max(times) if times else 0.0
        self.preview_data = {"clip_length": clip_length, "event_times": times, "samples": [], "audio_files": []}
        self.draw_preview(0.0)

    def toggle_preview_playback(self) -> None:
        if not self.preview_data:
            messagebox.showinfo("暂无预览", "请先点击“直接预览”。")
            return
        if self.playing:
            self.play_base_time = self.current_preview_time()
            self.playing = False
            self.status_var.set("预览暂停")
            return
        self.playing = True
        self.play_start_perf = time.perf_counter()
        self.next_event_index = self.next_event_index_for_time(self.play_base_time)
        self.status_var.set("正在播放预览")
        self.playback_tick()

    def stop_preview_playback(self, redraw: bool = True) -> None:
        self.playing = False
        self.play_base_time = 0.0
        self.next_event_index = 0
        self.stop_async_audio()
        if redraw:
            self.draw_preview(0.0)
            self.status_var.set("预览停止")

    def current_preview_time(self) -> float:
        if not self.preview_data:
            return 0.0
        if not self.playing:
            return self.play_base_time
        speed = float(self.playback_speed_var.get() or "1.0")
        return self.play_base_time + (time.perf_counter() - self.play_start_perf) * speed

    def next_event_index_for_time(self, current_time: float) -> int:
        if not self.preview_data:
            return 0
        times = self.preview_data.get("event_times", [])
        if not isinstance(times, list):
            return 0
        index = 0
        while index < len(times) and float(times[index]) < current_time:
            index += 1
        return index

    def playback_tick(self) -> None:
        if not self.playing or not self.preview_data:
            return
        clip_length = float(self.preview_data.get("clip_length") or 0.0)
        current_time = self.current_preview_time()
        if clip_length > 0.0 and current_time > clip_length:
            if self.loop_preview_var.get():
                self.play_base_time = 0.0
                self.play_start_perf = time.perf_counter()
                self.next_event_index = 0
                current_time = 0.0
            else:
                self.stop_preview_playback()
                return

        times = self.preview_data.get("event_times", [])
        if isinstance(times, list):
            while self.next_event_index < len(times) and float(times[self.next_event_index]) <= current_time:
                self.play_marker_audio(self.next_event_index)
                self.next_event_index += 1

        self.draw_preview(current_time)
        self.after(33, self.playback_tick)

    def play_marker_audio(self, marker_index: int) -> None:
        mode = self.audio_mode_var.get()
        if mode == "Mute":
            return
        if mode == "Wwise Source" and self.preview_data:
            audio_files = self.preview_data.get("audio_files", [])
            if isinstance(audio_files, list) and audio_files:
                path = Path(random.choice(audio_files))
                try:
                    import winsound

                    winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)
                    return
                except Exception:
                    pass
        self.play_click(marker_index)

    def play_click(self, marker_index: int) -> None:
        def worker() -> None:
            try:
                import winsound

                freq = 950 + (marker_index % 3) * 120
                winsound.Beep(freq, 45)
            except Exception:
                self.bell()

        threading.Thread(target=worker, daemon=True).start()

    def stop_async_audio(self) -> None:
        try:
            import winsound

            winsound.PlaySound(None, winsound.SND_PURGE)
        except Exception:
            pass

    def draw_preview(self, current_time: float) -> None:
        canvas = getattr(self, "preview_canvas", None)
        if not canvas:
            return
        canvas.delete("all")
        width = max(canvas.winfo_width(), 600)
        height = max(canvas.winfo_height(), 220)
        canvas.create_rectangle(0, 0, width, height, fill="#10151b", outline="")

        if not self.preview_data:
            canvas.create_text(
                width / 2,
                height / 2,
                text="点击“直接预览”后，这里会显示运动曲线、打点和播放光标。",
                fill=MUTED,
                font=("Segoe UI", 11, "bold"),
            )
            return

        clip_length = float(self.preview_data.get("clip_length") or 0.0)
        samples = self.preview_data.get("samples", [])
        event_times = self.preview_data.get("event_times", [])
        audio_files = self.preview_data.get("audio_files", [])
        if clip_length <= 0.0:
            clip_length = max([float(value) for value in event_times], default=1.0) if isinstance(event_times, list) else 1.0

        graph_left = 36
        graph_right = width - 18
        graph_top = 88
        graph_bottom = height - 34
        graph_width = graph_right - graph_left
        graph_height = graph_bottom - graph_top

        current_time = max(0.0, min(current_time, clip_length))
        current_y_norm = self.sample_normalized_y(samples, current_time)
        self.draw_bird_preview(canvas, width, current_y_norm)

        canvas.create_rectangle(graph_left, graph_top, graph_right, graph_bottom, outline="#2b3542", fill="#0d1218")
        canvas.create_text(
            graph_left,
            20,
            text=f"t={current_time:.2f}s / {clip_length:.2f}s",
            anchor="w",
            fill=INK,
            font=("Consolas", 10, "bold"),
        )
        audio_count = len(audio_files) if isinstance(audio_files, list) else 0
        canvas.create_text(
            graph_right,
            20,
            text=f"markers: {len(event_times) if isinstance(event_times, list) else 0}   wav: {audio_count}",
            anchor="e",
            fill=MUTED,
            font=("Consolas", 9),
        )

        if isinstance(samples, list) and samples:
            values = [float(item[1]) for item in samples]
            y_min = min(values)
            y_max = max(values)
            if abs(y_max - y_min) < 0.000001:
                y_min -= 1.0
                y_max += 1.0
            points: list[float] = []
            for item in samples:
                t = float(item[0])
                y = float(item[1])
                x = graph_left + (t / clip_length) * graph_width
                py = graph_bottom - ((y - y_min) / (y_max - y_min)) * graph_height
                points.extend([x, py])
            if len(points) >= 4:
                canvas.create_line(*points, fill=ACCENT, width=2, smooth=True)
        else:
            canvas.create_text(
                (graph_left + graph_right) / 2,
                (graph_top + graph_bottom) / 2,
                text="没有可绘制的端点曲线；仍可用时间轴检查打点。",
                fill=MUTED,
                font=("Segoe UI", 10),
            )

        if isinstance(event_times, list):
            for index, time_value in enumerate(event_times):
                x = graph_left + (float(time_value) / clip_length) * graph_width
                color = WARN if abs(float(time_value) - current_time) < 0.06 else "#6d4d28"
                canvas.create_line(x, graph_top, x, graph_bottom, fill=color, width=1)
                if abs(float(time_value) - current_time) < 0.06:
                    canvas.create_oval(x - 5, graph_top - 7, x + 5, graph_top + 3, fill=WARN, outline="")

        cursor_x = graph_left + (current_time / clip_length) * graph_width
        canvas.create_line(cursor_x, graph_top - 10, cursor_x, graph_bottom + 8, fill=BAD, width=2)
        canvas.create_text(graph_left, graph_bottom + 18, text="0", anchor="w", fill=MUTED, font=("Consolas", 8))
        canvas.create_text(
            graph_right,
            graph_bottom + 18,
            text=f"{clip_length:.1f}s",
            anchor="e",
            fill=MUTED,
            font=("Consolas", 8),
        )

    def sample_normalized_y(self, samples: object, current_time: float) -> float:
        if not isinstance(samples, list) or not samples:
            return 0.5
        values = [float(item[1]) for item in samples]
        y_min = min(values)
        y_max = max(values)
        if abs(y_max - y_min) < 0.000001:
            return 0.5
        previous = samples[0]
        for item in samples[1:]:
            if float(item[0]) >= current_time:
                span = float(item[0]) - float(previous[0])
                ratio = 0.0 if span <= 0.0 else (current_time - float(previous[0])) / span
                y = float(previous[1]) + (float(item[1]) - float(previous[1])) * ratio
                return (y - y_min) / (y_max - y_min)
            previous = item
        return (float(samples[-1][1]) - y_min) / (y_max - y_min)

    def draw_bird_preview(self, canvas: tk.Canvas, width: int, y_norm: float) -> None:
        cx = width / 2
        cy = 48
        body_w = 58
        body_h = 24
        wing_len = 92
        wing_drop = (y_norm - 0.5) * 72
        wing_lift = math.sin((y_norm - 0.5) * math.pi) * 10
        canvas.create_oval(cx - body_w / 2, cy - body_h / 2, cx + body_w / 2, cy + body_h / 2, fill="#d7dde4", outline="")
        canvas.create_oval(cx + 20, cy - 12, cx + 42, cy + 4, fill="#d7dde4", outline="")
        canvas.create_polygon(cx + 40, cy - 5, cx + 58, cy - 1, cx + 40, cy + 4, fill="#f0c36a", outline="")
        canvas.create_line(cx - 10, cy, cx - wing_len, cy + wing_drop - wing_lift, fill=ACCENT, width=5, capstyle=tk.ROUND)
        canvas.create_line(cx + 4, cy, cx + wing_len, cy + wing_drop - wing_lift, fill=ACCENT, width=5, capstyle=tk.ROUND)

    def apply_error(self, payload: dict[str, object]) -> None:
        error = payload.get("error")
        trace = str(payload.get("trace") or "")
        self.append_log(f"ERROR: {error}")
        if trace:
            self.append_log(trace)
        self.status_var.set("执行失败")
        messagebox.showerror("执行失败", str(error))

    def set_running(self, running: bool, status: str) -> None:
        self.status_var.set(status)
        state = tk.DISABLED if running else tk.NORMAL
        for button in self.command_buttons:
            button.configure(state=state)

    def append_log(self, text: str) -> None:
        self.log.configure(state=tk.NORMAL)
        self.log.insert(tk.END, text.rstrip() + "\n")
        self.log.see(tk.END)
        self.log.configure(state=tk.DISABLED)

    def clear_log(self) -> None:
        self.log.configure(state=tk.NORMAL)
        self.log.delete("1.0", tk.END)
        self.log.configure(state=tk.DISABLED)

    def set_text(self, widget: tk.Text, text: str) -> None:
        widget.configure(state=tk.NORMAL)
        widget.delete("1.0", tk.END)
        widget.insert(tk.END, text)
        widget.configure(state=tk.DISABLED)

    def use_resolved_animation(self) -> None:
        value = self.resolved_animation_var.get().strip()
        if value and value not in {"未定位"} and Path(value).exists():
            self.animation_var.set(value)
            self.append_log(f"Animation 输入已切换到可编辑 .anim: {value}")
        else:
            messagebox.showinfo("未定位", "请先点击“定位资源”或“直接预览”。")

    def copy_cli_command(self) -> None:
        try:
            argv = self.build_tool_argv(apply=False)
            command = ["python", "-B", str(CORE_SCRIPT), *argv]
            text = subprocess.list2cmdline(command)
            self.clipboard_clear()
            self.clipboard_append(text)
            self.append_log("已复制预览命令。")
        except Exception as exc:
            messagebox.showerror("无法复制命令", str(exc))

    def write_unity_preview_request(self, report: dict[str, object], command: str = "preview") -> Path | None:
        try:
            unity_root = Path(self.unity_root_var.get()).resolve()
            animation = Path(str(report.get("animation") or "")).resolve()
            prefab_value = report.get("prefab")
            prefab = Path(str(prefab_value)).resolve() if prefab_value else None
            analysis = report.get("analysis") if isinstance(report.get("analysis"), dict) else {}
            event_times = analysis.get("event_times", []) if isinstance(analysis, dict) else []
            if not isinstance(event_times, list) or not event_times:
                self.append_log("Unity preview request blocked: no event times. Run Direct Preview or Write Config first.")
                messagebox.showerror(
                    "No event times",
                    "No analyzed event times are available. Run Direct Preview or Write Config first, then open Unity Preview/Edit Keys.",
                )
                return None

            request = {
                "animationAssetPath": self.to_unity_asset_path(unity_root, animation),
                "prefabAssetPath": self.to_unity_asset_path(unity_root, prefab) if prefab else "",
                "wwiseEvent": str(report.get("wwise_event") or ""),
                "reportPath": str(self.last_report_md or self.last_report_json or ""),
                "eventTimes": [float(value) for value in event_times] if isinstance(event_times, list) else [],
                "command": command,
            }

            request_path = unity_root / "Temp" / "ProjectEF_AnimationWwiseEventPreviewRequest.json"
            request_path.parent.mkdir(parents=True, exist_ok=True)
            request_path.write_text(json.dumps(request, ensure_ascii=True, indent=2), encoding="utf-8")
            self.unity_preview_request_path = request_path
            self.append_log(f"Unity preview request: {request_path}")
            return request_path
        except Exception as exc:
            self.append_log(f"Unity preview request failed: {exc}")
            return None

    def to_unity_asset_path(self, unity_root: Path, path: Path | None) -> str:
        if path is None:
            return ""
        relative = path.resolve().relative_to(unity_root.resolve())
        return relative.as_posix()

    def open_unity_preview(self) -> None:
        if self.last_report:
            report = self.last_report
        else:
            try:
                resolved = self.resolve_current()
            except Exception as exc:
                messagebox.showerror("Unity Preview failed", str(exc))
                return
            animation = resolved.get("animation")
            if not isinstance(animation, Path) or not animation.exists():
                messagebox.showerror("Missing .anim", str(animation))
                return
            messagebox.showinfo(
                "No preview data",
                "Run Direct Preview or Write Config first. Unity Preview will not send an empty event request.",
            )
            return

        request_path = self.write_unity_preview_request(report, command="preview")
        if not request_path:
            return

        if self.is_unity_project_open(Path(self.unity_root_var.get()).resolve()):
            self.append_log("Unity project is already open. Sent preview request to the Unity editor window.")
            self.status_var.set("Unity preview request sent")
            return

        self.launch_unity_execute_method("AnimationWwiseEventPreviewWindow.OpenFromExternalRequest")

    def launch_unity_execute_method(self, method_name: str) -> None:
        unity_root = Path(self.unity_root_var.get()).resolve()
        unity_exe = self.find_unity_exe(unity_root)
        if not unity_exe:
            selected = filedialog.askopenfilename(
                title="Select Unity.exe",
                filetypes=(("Unity Editor", "Unity.exe"), ("Executable", "*.exe"), ("All files", "*.*")),
            )
            unity_exe = Path(selected) if selected else None
        if not unity_exe:
            messagebox.showerror(
                "Unity not found",
                "Could not find Unity.exe. Open the project manually, then use menu ProjectEF/Audio/Animation Wwise Event Preview.",
            )
            return

        project_version = self.read_unity_version(unity_root)
        if project_version:
            unity_text = str(unity_exe)
            if project_version not in unity_text:
                messagebox.showerror(
                    "Unity version mismatch",
                    f"Blocked for safety.\n\n"
                    f"Project version is {project_version}, but the selected Unity is:\n{unity_exe}\n\n"
                    f"Please select the exact Unity version for this project.",
                )
                return

        command = [
            str(unity_exe),
            "-projectPath",
            str(unity_root),
            "-executeMethod",
            method_name,
        ]
        try:
            subprocess.Popen(command, cwd=str(unity_root))
            self.append_log("Launched Unity preview command:")
            self.append_log(subprocess.list2cmdline(command))
        except Exception as exc:
            messagebox.showerror("Unity launch failed", str(exc))

    def is_unity_project_open(self, unity_root: Path) -> bool:
        unity_root_text = self.normalize_for_compare(unity_root)
        try:
            command = [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "Get-CimInstance Win32_Process -Filter \"name = 'Unity.exe'\" | "
                "Select-Object -ExpandProperty CommandLine",
            ]
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
            completed = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
                creationflags=creationflags,
            )
        except Exception:
            return False

        for line in completed.stdout.splitlines():
            normalized = self.normalize_for_compare(line)
            if unity_root_text in normalized and "assetimportworker" not in normalized.lower():
                return True
        return False

    def normalize_for_compare(self, value: object) -> str:
        return str(value).replace("\\", "/").replace('"', "").lower()

    def find_unity_exe(self, unity_root: Path) -> Path | None:
        version = self.read_unity_version(unity_root)
        candidates: list[Path] = []
        if version:
            version_without_suffix = re.sub(r"c\d+$", "", version)
            candidates.extend(
                [
                    Path(r"D:\Unity") / version / "Editor" / "Unity.exe",
                    Path(r"C:\Unity") / version / "Editor" / "Unity.exe",
                    Path(r"E:\Unity") / version / "Editor" / "Unity.exe",
                    Path(r"C:\Program Files\Unity\Hub\Editor") / version / "Editor" / "Unity.exe",
                    Path(r"D:\Program Files\Unity\Hub\Editor") / version / "Editor" / "Unity.exe",
                    Path(r"E:\Program Files\Unity\Hub\Editor") / version / "Editor" / "Unity.exe",
                    Path(r"C:\Program Files") / f"Unity {version}" / "Editor" / "Unity.exe",
                    Path(r"C:\Program Files") / f"Unity {version_without_suffix}" / "Editor" / "Unity.exe",
                ]
            )

        for base in [
            Path(r"C:\Program Files\Unity\Hub\Editor"),
            Path(r"D:\Program Files\Unity\Hub\Editor"),
            Path(r"E:\Program Files\Unity\Hub\Editor"),
        ]:
            if base.exists():
                candidates.extend(sorted(base.glob("*/Editor/Unity.exe"), reverse=True))

        for base in [Path(r"C:\Program Files"), Path(r"D:\Program Files"), Path(r"E:\Program Files")]:
            if base.exists():
                candidates.extend(sorted(base.glob("Unity*/Editor/Unity.exe"), reverse=True))

        for base in [Path(r"C:\Unity"), Path(r"D:\Unity"), Path(r"E:\Unity")]:
            if base.exists():
                candidates.extend(sorted(base.glob("*/Editor/Unity.exe"), reverse=True))

        which_unity = shutil.which("Unity") or shutil.which("Unity.exe")
        if which_unity:
            candidates.append(Path(which_unity))

        seen: set[str] = set()
        for candidate in candidates:
            key = str(candidate).lower()
            if key in seen:
                continue
            seen.add(key)
            if candidate.exists():
                return candidate
        return None

    def read_unity_version(self, unity_root: Path) -> str | None:
        path = unity_root / "ProjectSettings" / "ProjectVersion.txt"
        if not path.exists():
            return None
        match = re.search(r"m_EditorVersion:\s*(\S+)", path.read_text(encoding="utf-8", errors="replace"))
        return match.group(1) if match else None

    def current_animation_file(self) -> Path:
        if self.last_report and self.last_report.get("animation"):
            return Path(str(self.last_report["animation"]))

        candidate = self.resolved_animation_var.get().strip()
        if candidate and Path(candidate).exists():
            return Path(candidate)

        resolved = self.resolve_current()
        animation = resolved.get("animation")
        if isinstance(animation, Path):
            return animation
        return Path(str(animation))

    def open_project_audio_preview(self) -> None:
        try:
            if self.last_report:
                report = self.last_report
            else:
                resolved = self.resolve_current()
                animation = resolved.get("animation")
                if not isinstance(animation, Path) or not animation.exists():
                    messagebox.showerror("Missing .anim", str(animation))
                    return
                messagebox.showinfo(
                    "No preview data",
                    "Run Direct Preview or Write Config first. Project Audio will not send an empty event request.",
                )
                return

            request_path = self.write_unity_preview_request(report, command="project_audio_preview")
            if not request_path:
                return

            if self.is_unity_project_open(Path(self.unity_root_var.get()).resolve()):
                self.append_log("Unity project is already open. Sent project-audio preview request to the Unity editor window.")
                self.status_var.set("Project audio preview request sent")
                return

            self.launch_unity_execute_method("AnimationWwiseEventPreviewWindow.OpenFromExternalRequest")
        except Exception as exc:
            messagebox.showerror("Project Audio Preview failed", str(exc))

    def open_anim_text_editor(self) -> None:
        try:
            if self.last_report:
                report = self.last_report
            else:
                resolved = self.resolve_current()
                animation = resolved.get("animation")
                if not isinstance(animation, Path) or not animation.exists():
                    messagebox.showerror("Missing .anim", str(animation))
                    return
                messagebox.showinfo(
                    "No preview data",
                    "Run Direct Preview or Write Config first. Unity Edit Keys will not send an empty event request.",
                )
                return

            request_path = self.write_unity_preview_request(report, command="edit_keys")
            if not request_path:
                return

            if self.is_unity_project_open(Path(self.unity_root_var.get()).resolve()):
                self.append_log("Unity project is already open. Sent edit-key request to the Unity editor window.")
                self.status_var.set("Unity edit-key request sent")
                return

            self.launch_unity_execute_method("AnimationWwiseEventPreviewWindow.OpenFromExternalRequest")
        except Exception as exc:
            messagebox.showerror("Open Animation Event keys failed", str(exc))

    def open_unity_root(self) -> None:
        self.open_path(Path(self.unity_root_var.get()))

    def open_wwise_root(self) -> None:
        self.open_path(Path(self.wwise_root_var.get()))

    def open_animation_location(self) -> None:
        candidate = self.resolved_animation_var.get()
        if not candidate or candidate == "未定位":
            candidate = self.animation_var.get()
        self.open_path(Path(candidate), select_file=True)

    def open_prefab_location(self) -> None:
        candidate = self.resolved_prefab_var.get()
        if not candidate or candidate.startswith("未") or candidate == "自动":
            candidate = self.prefab_var.get()
        if candidate:
            self.open_path(Path(candidate), select_file=True)
        else:
            messagebox.showinfo("未指定", "Prefab 当前是自动推断，请先定位资源。")

    def open_wwise_event_location(self) -> None:
        text = self.wwise_evidence_var.get()
        path = Path(text)
        if path.exists():
            self.open_path(path, select_file=True)
        else:
            messagebox.showinfo("未定位", "请先点击“校验 / 定位”。")

    def open_last_report(self) -> None:
        if self.last_report_md and self.last_report_md.exists():
            self.open_path(self.last_report_md, select_file=False)
        elif self.last_report_json and self.last_report_json.exists():
            self.open_path(self.last_report_json, select_file=False)
        else:
            messagebox.showinfo("暂无报告", "请先点击“直接预览”或“写入 / 修改配置”。")

    def open_report_folder(self) -> None:
        self.open_path(core.REPORT_DIR)

    def open_path(self, path: Path, select_file: bool = False) -> None:
        try:
            path = path.expanduser()
            if select_file and path.is_file() and os.name == "nt":
                subprocess.Popen(["explorer", f"/select,{str(path)}"])
            elif path.exists():
                os.startfile(str(path)) if os.name == "nt" else subprocess.Popen(["xdg-open", str(path)])
            else:
                messagebox.showinfo("路径不存在", str(path))
        except Exception as exc:
            messagebox.showerror("无法打开", str(exc))


def main() -> int:
    if not CORE_SCRIPT.exists():
        messagebox.showerror("Missing script", f"Missing core tool:\n{CORE_SCRIPT}")
        return 1
    app = AnimationWwiseEventAutoConfigGui()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
