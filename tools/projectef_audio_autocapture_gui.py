#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ProjectEF Audio AutoCapture + Briefing — control panel (tkinter).

Replaces the old interactive .cmd menu (which flooded when launched non-interactively
by the hub). Buttons: start/stop the capture daemon, run daily/weekly briefing now,
register/unregister the auto-start + scheduled tasks, open the report/capture folders.
"""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
from pathlib import Path

import tkinter as tk
from tkinter import scrolledtext

TOOLS = Path(__file__).resolve().parent
OUT_DIR = Path(r"G:\AI\Material\Wwise")
CAPTURE_DIR = OUT_DIR / "audio_debug_captures"
REPORT_DIR = OUT_DIR / "报告"
DAEMON = TOOLS / "projectef_audio_autocapture_daemon.py"
BRIEFING = TOOLS / "projectef_audio_briefing.py"
REGISTER = TOOLS / "Register_ProjectEF_AudioAutoCapture_Tasks.ps1"
UNREGISTER = TOOLS / "Unregister_ProjectEF_AudioAutoCapture_Tasks.ps1"
NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.q: queue.Queue[str] = queue.Queue()
        self.daemon_proc: subprocess.Popen | None = None
        root.title("ProjectEF 音频自动捕获 + 简报")
        root.geometry("840x560")

        top = tk.Frame(root, padx=10, pady=8)
        top.pack(fill="x")
        tk.Label(top, text="捕获目录: " + str(CAPTURE_DIR), anchor="w", fg="#888").pack(fill="x")
        tk.Label(top, text="报告目录: " + str(REPORT_DIR), anchor="w", fg="#888").pack(fill="x")

        bar = tk.Frame(root, padx=10, pady=4)
        bar.pack(fill="x")
        self.buttons: list[tk.Button] = []
        for text, fn in [
            ("▶ 启动守护(本次)", self.start_daemon),
            ("■ 停止守护", self.stop_daemon),
            ("每日简报", lambda: self.run_briefing("daily")),
            ("每周简报", lambda: self.run_briefing("weekly")),
            ("注册自启+计划", self.do_register),
            ("取消注册", self.do_unregister),
            ("打开报告/捕获目录", self.open_dirs),
        ]:
            b = tk.Button(bar, text=text, command=fn)
            b.pack(side="left", padx=3)
            self.buttons.append(b)

        self.status = tk.Label(root, text="就绪。守护未运行。", anchor="w", bd=1, relief="sunken")
        self.status.pack(fill="x", side="bottom")
        self.out = scrolledtext.ScrolledText(root, wrap="word", state="disabled",
                                             bg="#1e1e1e", fg="#dcdcdc", font=("Consolas", 10))
        self.out.pack(fill="both", expand=True, padx=10, pady=6)

        self._log("说明:① 点「注册自启+计划」让守护开机自启 + 每日/每周自动出简报;\n"
                  "     或 ② 点「启动守护(本次)」临时跑(关闭本窗口会停止本次守护)。\n"
                  "游戏(编辑器 Play 或 Windows 包)一跑,守护就按会话抓音频日志。\n")
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.after(120, self._drain)

    def _log(self, text: str) -> None:
        self.out.configure(state="normal")
        self.out.insert("end", text + "\n")
        self.out.see("end")
        self.out.configure(state="disabled")

    def _drain(self) -> None:
        try:
            while True:
                self._log(self.q.get_nowait().rstrip())
        except queue.Empty:
            pass
        # reflect daemon liveness
        if self.daemon_proc and self.daemon_proc.poll() is not None:
            self.status.configure(text="守护已退出。")
            self.daemon_proc = None
        self.root.after(150, self._drain)

    def _run_async(self, args: list[str], title: str) -> None:
        self._log(f"\n$ {' '.join(str(a) for a in args)}")

        def worker() -> None:
            try:
                p = subprocess.run(args, cwd=str(TOOLS), capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
                self.q.put((p.stdout or "") + (p.stderr or "") + f"\n[{title} 完成 rc={p.returncode}]")
            except Exception as exc:  # noqa: BLE001
                self.q.put(f"[{title} 出错] {exc}")
        threading.Thread(target=worker, daemon=True).start()

    # ---- actions ----
    def start_daemon(self) -> None:
        if self.daemon_proc and self.daemon_proc.poll() is None:
            self._log("守护已在运行。")
            return
        try:
            self.daemon_proc = subprocess.Popen(
                [sys.executable, "-B", str(DAEMON)], cwd=str(TOOLS),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
        except Exception as exc:  # noqa: BLE001
            self._log(f"[启动失败] {exc}")
            return
        self.status.configure(text=f"守护运行中 (pid {self.daemon_proc.pid})。")
        self._log(f"守护已启动 (pid {self.daemon_proc.pid})。游戏跑起来就会自动抓会话。")

        def pump() -> None:
            assert self.daemon_proc and self.daemon_proc.stdout
            for line in self.daemon_proc.stdout:
                self.q.put(line)
        threading.Thread(target=pump, daemon=True).start()

    def stop_daemon(self) -> None:
        if self.daemon_proc and self.daemon_proc.poll() is None:
            self.daemon_proc.terminate()
            self._log("已请求停止守护。")
            self.status.configure(text="守护已停止。")
        else:
            self._log("守护未在运行。")

    def run_briefing(self, period: str) -> None:
        self._run_async([sys.executable, "-B", str(BRIEFING), "--period", period], f"{period}简报")

    def do_register(self) -> None:
        self._run_async(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(REGISTER)], "注册")

    def do_unregister(self) -> None:
        self._run_async(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(UNREGISTER)], "取消注册")

    def open_dirs(self) -> None:
        for d in (CAPTURE_DIR, REPORT_DIR):
            d.mkdir(parents=True, exist_ok=True)
            try:
                os.startfile(str(d))  # noqa: S606
            except Exception:  # noqa: BLE001
                pass

    def on_close(self) -> None:
        if self.daemon_proc and self.daemon_proc.poll() is None:
            self.daemon_proc.terminate()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
