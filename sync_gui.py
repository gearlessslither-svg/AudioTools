"""AudioTools Git 同步器 — tkinter GUI.

A thin front-end over sync_audio_tools.py. Flow:
  扫描/同步 -> 查看改动 -> 填提交说明 -> 提交(本地) -> 推送(需确认)

Push is deliberately a separate, confirmed step. Nothing is pushed automatically.
"""
from __future__ import annotations

import queue
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

import tkinter as tk
from tkinter import messagebox, scrolledtext

REPO = Path(__file__).resolve().parent
ENGINE = REPO / "sync_audio_tools.py"
REMOTE = "git@github.com:gearlessslither-svg/AudioTools.git"


class SyncApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.q: queue.Queue[tuple[str, object]] = queue.Queue()
        self.busy = False
        root.title("AudioTools Git 同步器")
        root.geometry("980x640")

        top = tk.Frame(root, padx=10, pady=8)
        top.pack(fill="x")
        tk.Label(top, text=f"仓库: {REPO}", anchor="w").pack(fill="x")
        tk.Label(top, text=f"远程: {REMOTE}", anchor="w", fg="#888").pack(fill="x")

        bar = tk.Frame(root, padx=10, pady=4)
        bar.pack(fill="x")
        self.buttons: list[tk.Button] = []
        for text, fn in [
            ("① 扫描 / 同步", self.do_sync),
            ("② 查看改动", self.do_status),
            ("③ 提交(本地)", self.do_commit),
            ("④ 推送到 GitHub", self.do_push),
            ("历史", self.do_history),
        ]:
            b = tk.Button(bar, text=text, width=15, command=fn)
            b.pack(side="left", padx=3)
            self.buttons.append(b)

        msg = tk.Frame(root, padx=10, pady=4)
        msg.pack(fill="x")
        tk.Label(msg, text="提交说明:").pack(side="left")
        self.commit_msg = tk.Entry(msg)
        self.commit_msg.pack(side="left", fill="x", expand=True, padx=6)
        self.commit_msg.insert(0, self._default_msg())

        self.out = scrolledtext.ScrolledText(root, wrap="word", state="disabled",
                                             bg="#1e1e1e", fg="#dcdcdc", font=("Consolas", 10))
        self.out.pack(fill="both", expand=True, padx=10, pady=6)

        self.status = tk.Label(root, text="就绪。建议顺序:扫描/同步 → 查看改动 → 提交 → 推送。",
                               anchor="w", bd=1, relief="sunken")
        self.status.pack(fill="x", side="bottom")

        self._log("欢迎使用 AudioTools Git 同步器。\n"
                  "流程:① 扫描/同步(把工具源码镜像进仓库 + 安全扫描)→ ② 查看改动 → "
                  "③ 提交(本地)→ ④ 推送(会先二次确认)。\n"
                  "推送绝不会自动发生。\n")
        self.root.after(100, self._drain)

    # ---------- helpers ----------
    def _default_msg(self) -> str:
        return f"Update audio tools {datetime.now():%Y-%m-%d %H:%M}"

    def _log(self, text: str) -> None:
        self.out.configure(state="normal")
        self.out.insert("end", text + "\n")
        self.out.see("end")
        self.out.configure(state="disabled")

    def _set_busy(self, busy: bool, status: str = "") -> None:
        self.busy = busy
        for b in self.buttons:
            b.configure(state="disabled" if busy else "normal")
        if status:
            self.status.configure(text=status)

    def _run(self, args: list[str], title: str, on_done=None) -> None:
        if self.busy:
            return
        self._set_busy(True, f"{title} 运行中…")
        self._log(f"\n$ {' '.join(args)}")

        def worker() -> None:
            try:
                p = subprocess.run(args, cwd=str(REPO), text=True,
                                   capture_output=True, encoding="utf-8", errors="replace")
                self.q.put(("output", (p.stdout or "") + (p.stderr or "")))
                self.q.put(("done", (title, p.returncode, on_done)))
            except Exception as exc:  # noqa: BLE001
                self.q.put(("output", f"[错误] {exc}"))
                self.q.put(("done", (title, 1, None)))

        threading.Thread(target=worker, daemon=True).start()

    def _drain(self) -> None:
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "output":
                    self._log(str(payload).rstrip())
                elif kind == "done":
                    title, code, cb = payload
                    ok = code == 0
                    self._set_busy(False, f"{title} {'完成 ✅' if ok else '失败 ❌ (返回码 %d)' % code}")
                    if cb:
                        cb(ok)
        except queue.Empty:
            pass
        self.root.after(120, self._drain)

    # ---------- actions ----------
    def do_sync(self) -> None:
        self._run([sys.executable, str(ENGINE), "sync"], "扫描/同步")

    def do_status(self) -> None:
        self._run(["git", "-C", str(REPO), "status", "--short"], "查看改动")

    def do_commit(self) -> None:
        msg = self.commit_msg.get().strip() or self._default_msg()
        self._run([sys.executable, str(ENGINE), "commit", "-m", msg], "提交")

    def do_history(self) -> None:
        self._run(["git", "-C", str(REPO), "log", "--oneline", "-15"], "历史")

    def do_push(self) -> None:
        if not messagebox.askyesno(
            "确认推送",
            "确定把本地提交推送到 GitHub 私有仓库吗?\n\n"
            f"{REMOTE}\n\n推送后远端会更新。",
        ):
            self._log("已取消推送。")
            return
        self._run([sys.executable, str(ENGINE), "push"], "推送")


def main() -> None:
    root = tk.Tk()
    SyncApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
