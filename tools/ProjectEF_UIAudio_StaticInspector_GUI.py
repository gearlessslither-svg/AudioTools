#!/usr/bin/env python3
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk


APP_DIR = Path(__file__).resolve().parent
SCANNER = APP_DIR / "projectef_ui_audio_static_inspector.py"

DEFAULT_UNITY_ROOT = r"D:\EF New\Client\TargetProject"
DEFAULT_WWISE_ROOT = r"D:\EF Wwise\ProjectEF"
DEFAULT_SCAN_ROOT = "Assets"
DEFAULT_REPORT_DIR = r"G:\AI\Material\Wwise\报告"

BG = "#0f1722"
PANEL = "#151f2d"
PANEL_2 = "#1b2636"
CARD = "#202c3d"
INK = "#edf4ff"
MUTED = "#9fb0c6"
LINE = "#334258"
ACCENT = "#4db6ff"
GOOD = "#55d68a"
BAD = "#ff6b6b"


class UIAudioStaticInspectorGui(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("ProjectEF UI Audio Static Inspector")
        self.geometry("1040x720")
        self.minsize(920, 620)
        self.configure(bg=BG)

        self.unity_root_var = tk.StringVar(value=DEFAULT_UNITY_ROOT)
        self.wwise_root_var = tk.StringVar(value=DEFAULT_WWISE_ROOT)
        self.scan_root_var = tk.StringVar(value=DEFAULT_SCAN_ROOT)
        self.report_dir_var = tk.StringVar(value=DEFAULT_REPORT_DIR)
        self.include_prefabs_var = tk.BooleanVar(value=True)
        self.include_scenes_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value="Ready")
        self.last_html: Path | None = None
        self.last_csv: Path | None = None
        self.last_md: Path | None = None
        self.last_json: Path | None = None
        self.process: subprocess.Popen[str] | None = None
        self.messages: queue.Queue[str] = queue.Queue()

        self.configure_style()
        self.refresh_latest_report_paths()
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
        style.configure("TButton", padding=(10, 6))
        style.configure("TCheckbutton", background=PANEL, foreground=INK)

    def build_ui(self) -> None:
        root = tk.Frame(self, bg=BG)
        root.pack(fill=tk.BOTH, expand=True)

        header = tk.Frame(root, bg=BG)
        header.pack(fill=tk.X, padx=18, pady=(16, 10))
        tk.Label(header, text="ProjectEF UI Audio Static Inspector", bg=BG, fg=INK, font=("Segoe UI", 22, "bold")).pack(anchor="w")
        tk.Label(
            header,
            text="Read-only static scan for ButtonEx, ToggleEx, UIStateOnClickSoundController, ButtonAudioComp, and Wwise Event validity.",
            bg=BG,
            fg=MUTED,
            font=("Segoe UI", 10),
        ).pack(anchor="w", pady=(2, 0))

        config = tk.Frame(root, bg=PANEL, highlightbackground=LINE, highlightthickness=1)
        config.pack(fill=tk.X, padx=18, pady=(0, 12))
        self.path_row(config, "Unity root", self.unity_root_var, self.choose_unity_root).pack(fill=tk.X, padx=12, pady=(12, 6))
        self.path_row(config, "Wwise root", self.wwise_root_var, self.choose_wwise_root).pack(fill=tk.X, padx=12, pady=6)
        self.path_row(config, "Scan root", self.scan_root_var, self.choose_scan_root).pack(fill=tk.X, padx=12, pady=6)
        self.path_row(config, "Report dir", self.report_dir_var, self.choose_report_dir).pack(fill=tk.X, padx=12, pady=(6, 12))

        options = tk.Frame(root, bg=PANEL, highlightbackground=LINE, highlightthickness=1)
        options.pack(fill=tk.X, padx=18, pady=(0, 12))
        tk.Checkbutton(
            options,
            text="Prefabs",
            variable=self.include_prefabs_var,
            bg=PANEL,
            fg=INK,
            activebackground=PANEL,
            activeforeground=INK,
            selectcolor=PANEL_2,
        ).pack(side=tk.LEFT, padx=(12, 14), pady=10)
        tk.Checkbutton(
            options,
            text="Scenes",
            variable=self.include_scenes_var,
            bg=PANEL,
            fg=INK,
            activebackground=PANEL,
            activeforeground=INK,
            selectcolor=PANEL_2,
        ).pack(side=tk.LEFT, padx=(0, 20), pady=10)

        self.run_button = self.action_button(options, "Run Full Scan", self.run_scan, ACCENT, "#06111d")
        self.run_button.pack(side=tk.LEFT, padx=(0, 10), pady=8)
        self.html_button = self.action_button(options, "Open HTML", self.open_last_html, CARD, INK)
        self.html_button.pack(side=tk.LEFT, padx=(0, 8), pady=8)
        self.csv_button = self.action_button(options, "Open CSV", self.open_last_csv, CARD, INK)
        self.csv_button.pack(side=tk.LEFT, padx=(0, 8), pady=8)
        self.md_button = self.action_button(options, "Open MD", self.open_last_md, CARD, INK)
        self.md_button.pack(side=tk.LEFT, padx=(0, 8), pady=8)
        self.folder_button = self.action_button(options, "Report Folder", self.open_report_folder, CARD, INK)
        self.folder_button.pack(side=tk.LEFT, padx=(0, 8), pady=8)

        body = tk.Frame(root, bg=PANEL, highlightbackground=LINE, highlightthickness=1)
        body.pack(fill=tk.BOTH, expand=True, padx=18, pady=(0, 12))
        tk.Label(body, text="Scan Log", bg=PANEL, fg=MUTED, font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=12, pady=(10, 6))
        self.log = tk.Text(
            body,
            bg="#101720",
            fg=INK,
            insertbackground=INK,
            relief=tk.FLAT,
            wrap=tk.WORD,
            font=("Consolas", 9),
            padx=10,
            pady=10,
        )
        self.log.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))

        footer = tk.Frame(root, bg=BG)
        footer.pack(fill=tk.X, padx=18, pady=(0, 12))
        tk.Label(footer, textvariable=self.status_var, bg=BG, fg=MUTED, font=("Segoe UI", 9)).pack(side=tk.LEFT)
        tk.Label(footer, text=str(SCANNER), bg=BG, fg="#65748a", font=("Segoe UI", 9)).pack(side=tk.RIGHT)

    def path_row(self, parent: tk.Frame, label: str, variable: tk.StringVar, browse_command) -> tk.Frame:
        row = tk.Frame(parent, bg=PANEL)
        tk.Label(row, text=label, bg=PANEL, fg=MUTED, font=("Segoe UI", 9, "bold"), width=11, anchor="w").pack(side=tk.LEFT)
        entry = tk.Entry(row, textvariable=variable, bg=PANEL_2, fg=INK, insertbackground=INK, relief=tk.FLAT, font=("Consolas", 9))
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=6, padx=(4, 8))
        tk.Button(
            row,
            text="Browse",
            command=browse_command,
            bg=CARD,
            fg=INK,
            activebackground="#26364b",
            activeforeground=INK,
            relief=tk.FLAT,
            padx=12,
            pady=6,
        ).pack(side=tk.LEFT)
        return row

    def action_button(self, parent: tk.Frame, text: str, command, bg: str, fg: str) -> tk.Button:
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=bg,
            fg=fg,
            activebackground="#82ccff" if bg == ACCENT else "#26364b",
            activeforeground=fg,
            relief=tk.FLAT,
            padx=16,
            pady=8,
            font=("Segoe UI", 9, "bold"),
        )

    def choose_unity_root(self) -> None:
        path = filedialog.askdirectory(initialdir=self.unity_root_var.get() or DEFAULT_UNITY_ROOT)
        if path:
            self.unity_root_var.set(path)

    def choose_wwise_root(self) -> None:
        path = filedialog.askdirectory(initialdir=self.wwise_root_var.get() or DEFAULT_WWISE_ROOT)
        if path:
            self.wwise_root_var.set(path)

    def choose_scan_root(self) -> None:
        initial = self.scan_root_var.get()
        if not Path(initial).is_absolute():
            initial = str(Path(self.unity_root_var.get()) / initial)
        path = filedialog.askdirectory(initialdir=initial)
        if path:
            unity_root = Path(self.unity_root_var.get())
            try:
                self.scan_root_var.set(str(Path(path).resolve().relative_to(unity_root.resolve())))
            except Exception:
                self.scan_root_var.set(path)

    def choose_report_dir(self) -> None:
        path = filedialog.askdirectory(initialdir=self.report_dir_var.get() or DEFAULT_REPORT_DIR)
        if path:
            self.report_dir_var.set(path)

    def append_log(self, text: str) -> None:
        self.log.configure(state=tk.NORMAL)
        self.log.insert(tk.END, text.rstrip() + "\n")
        self.log.see(tk.END)
        self.log.configure(state=tk.DISABLED)

    def latest_report(self, suffix: str) -> Path | None:
        folder = Path(self.report_dir_var.get())
        if not folder.exists():
            return None
        candidates = list(folder.glob(f"ProjectEF_UIAudio_StaticInspector_*{suffix}"))
        if suffix == ".csv":
            candidates = [
                item
                for item in candidates
                if not item.name.endswith("_states.csv") and not item.name.endswith("_overrides.csv")
            ]
        candidates = sorted(candidates, key=lambda item: item.stat().st_mtime, reverse=True)
        return candidates[0] if candidates else None

    def refresh_latest_report_paths(self) -> None:
        self.last_html = self.last_html if self.last_html and self.last_html.exists() else self.latest_report(".html")
        self.last_csv = self.last_csv if self.last_csv and self.last_csv.exists() else self.latest_report(".csv")
        self.last_md = self.last_md if self.last_md and self.last_md.exists() else self.latest_report(".md")
        self.last_json = self.last_json if self.last_json and self.last_json.exists() else self.latest_report(".json")

    def set_running(self, running: bool) -> None:
        state = tk.DISABLED if running else tk.NORMAL
        self.run_button.configure(state=state)

    def run_scan(self) -> None:
        if self.process and self.process.poll() is None:
            messagebox.showinfo("Scan running", "A scan is already running.")
            return
        if not SCANNER.exists():
            messagebox.showerror("Missing scanner", str(SCANNER))
            return
        if not self.include_prefabs_var.get() and not self.include_scenes_var.get():
            messagebox.showerror("Invalid scope", "Enable Prefabs, Scenes, or both.")
            return

        self.last_html = None
        self.last_csv = None
        self.last_md = None
        self.last_json = None
        self.log.configure(state=tk.NORMAL)
        self.log.delete("1.0", tk.END)
        self.log.configure(state=tk.DISABLED)
        self.status_var.set("Scanning...")
        self.set_running(True)

        command = [
            sys.executable,
            "-B",
            str(SCANNER),
            "--unity-root",
            self.unity_root_var.get(),
            "--wwise-project-root",
            self.wwise_root_var.get(),
            "--scan-root",
            self.scan_root_var.get(),
            "--report-dir",
            self.report_dir_var.get(),
        ]
        if not self.include_prefabs_var.get():
            command.append("--no-prefabs")
        if not self.include_scenes_var.get():
            command.append("--no-scenes")
        threading.Thread(target=self.worker, args=(command,), daemon=True).start()

    def worker(self, command: list[str]) -> None:
        try:
            self.process = subprocess.Popen(
                command,
                cwd=str(APP_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
            assert self.process.stdout is not None
            for line in self.process.stdout:
                self.messages.put(line)
            code = self.process.wait()
            self.messages.put(f"__EXIT__{code}")
        except Exception as exc:
            self.messages.put(f"ERROR: {exc}")
            self.messages.put("__EXIT__1")

    def pump_messages(self) -> None:
        try:
            while True:
                message = self.messages.get_nowait()
                if message.startswith("__EXIT__"):
                    code = int(message.replace("__EXIT__", "") or "1")
                    self.set_running(False)
                    if code == 0:
                        self.refresh_latest_report_paths()
                        report_name = self.last_html.name if self.last_html else "report"
                        self.status_var.set(f"Scan complete: {report_name}")
                        self.append_log(f"Scan complete: {report_name}")
                    else:
                        self.status_var.set("Scan failed.")
                        self.append_log(f"Scan failed with exit code {code}.")
                    continue
                stripped = message.strip()
                if stripped.startswith("REPORT_HTML="):
                    self.last_html = Path(stripped.split("=", 1)[1])
                elif stripped.startswith("REPORT_CSV="):
                    self.last_csv = Path(stripped.split("=", 1)[1])
                elif stripped.startswith("REPORT_MD="):
                    self.last_md = Path(stripped.split("=", 1)[1])
                elif stripped.startswith("REPORT_JSON="):
                    self.last_json = Path(stripped.split("=", 1)[1])
                self.append_log(message)
        except queue.Empty:
            pass
        self.after(100, self.pump_messages)

    def open_last_html(self) -> None:
        self.refresh_latest_report_paths()
        if not self.last_html or not self.last_html.exists():
            messagebox.showinfo("No report", "Run a scan first, or open the report folder.")
            return
        os.startfile(str(self.last_html))

    def open_last_csv(self) -> None:
        self.refresh_latest_report_paths()
        if not self.last_csv or not self.last_csv.exists():
            messagebox.showinfo("No CSV", "Run a scan first, or open the report folder.")
            return
        os.startfile(str(self.last_csv))

    def open_last_md(self) -> None:
        self.refresh_latest_report_paths()
        if not self.last_md or not self.last_md.exists():
            messagebox.showinfo("No Markdown", "Run a scan first, or open the report folder.")
            return
        os.startfile(str(self.last_md))

    def open_report_folder(self) -> None:
        path = Path(self.report_dir_var.get())
        if not path.exists():
            messagebox.showerror("Missing folder", str(path))
            return
        os.startfile(str(path))


def main() -> None:
    app = UIAudioStaticInspectorGui()
    app.mainloop()


if __name__ == "__main__":
    main()
