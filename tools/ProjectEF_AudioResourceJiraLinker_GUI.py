#!/usr/bin/env python3
"""
GUI wrapper for ProjectEF audio resource <-> Jira linking.

The GUI is intentionally read-only for Unity/Wwise/P4/Jira source data:
  - scans resource metadata into reports
  - refreshes local Jira cache through the existing dedicated browser flow
  - reads recent P4 metadata
  - writes local Excel/JSON reports
"""

from __future__ import annotations

import importlib.util
import json
import os
import queue
import subprocess
import sys
import threading
import time
import traceback
import urllib.parse
from pathlib import Path
from tkinter import BooleanVar, IntVar, StringVar, filedialog, messagebox
import tkinter as tk
from tkinter import ttk


APP_DIR = Path(__file__).resolve().parent
REPORT_DIR = Path(r"G:\AI\Material\Wwise\Reports\AudioResourceJiraLinks")
ACTION_INDEX_DIR = Path(r"G:\AI\Material\Wwise\Reports\ActionResourceIndex")
THUMBNAIL_DIR = Path(r"G:\AI\Material\Wwise\Reports\ResourceThumbnails")
UNITY_ROOT = Path(r"D:\EF New\Client\TargetProject")
ACTION_INDEX_SCRIPT = APP_DIR / "ProjectEF_ActionResourceIndex.py"
LINKER_SCRIPT = APP_DIR / "ProjectEF_AudioResourceJiraLinker.py"
JIRA_GUI_SCRIPT = APP_DIR / "ProjectEF_AudioRequirementJiraTriage_GUI.py"
JIRA_CACHE_PATH = APP_DIR / "audio_requirement_jira_issue_cache.json"

DEFAULT_JIRA_URL = "http://ef.jira.blackjack-local.com:8080"
DEFAULT_JQL = "assignee = yupeng AND statusCategory != Done ORDER BY updated DESC"

BG = "#101820"
PANEL = "#172331"
PANEL_2 = "#1e2c3d"
INK = "#f3f7fb"
MUTED = "#aab8c6"
ACCENT = "#47b39d"
WARN = "#d19a45"
ERR = "#d15f5f"


def load_jira_module():
    spec = importlib.util.spec_from_file_location("projectef_jira_triage", JIRA_GUI_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load Jira triage module: {JIRA_GUI_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def run_command(args: list[str], cwd: Path, emit) -> str:
    emit("> " + " ".join(f'"{a}"' if " " in a else a for a in args))
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.Popen(
        args,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    output_parts: list[str] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        output_parts.append(line)
        emit(line.rstrip("\n"))
    code = proc.wait()
    output = "".join(output_parts)
    if code != 0:
        raise RuntimeError(f"Command failed with exit code {code}\n{output[-4000:]}")
    return output


def parse_last_json_object(text: str) -> dict:
    start = text.rfind("{")
    if start < 0:
        return {}
    # The scripts print one final JSON object. Try progressively earlier braces if nested braces confuse rfind.
    for idx in [m.start() for m in __import__("re").finditer(r"\{", text)][::-1]:
        chunk = text[idx:].strip()
        try:
            return json.loads(chunk)
        except Exception:
            continue
    return {}


def jira_issue_url(base_url: str, key: str) -> str:
    return base_url.rstrip("/") + "/browse/" + urllib.parse.quote(key)


def refresh_jira_cache_via_dedicated_browser(base_url: str, jql: str, limit: int, emit) -> dict:
    triage = load_jira_module()
    fields = getattr(triage, "JIRA_SEARCH_FIELDS")
    index = {}
    try:
        index = triage.load_index()
        if index:
            triage.ensure_design_index_lookup(index)
            emit("Loaded design index for Jira audio classification.")
    except Exception as exc:
        emit(f"Design index unavailable; Jira cache will still refresh. Detail: {exc}")

    issues: list[dict] = []
    start_at = 0
    total = None
    page_size = min(100, max(1, limit))
    while len(issues) < limit:
        params = urllib.parse.urlencode({
            "jql": jql,
            "startAt": start_at,
            "maxResults": min(page_size, limit - len(issues)),
            "fields": fields,
        }, safe=",")
        emit(f"Fetching Jira page startAt={start_at}...")
        response = triage.cdp_fetch_jira_url(base_url, jql, f"/rest/api/2/search?{params}", timeout=90)
        status = int(response.get("status") or 0)
        ctype = str(response.get("content_type") or "")
        body = str(response.get("body") or "")
        if status != 200 or "json" not in ctype.lower():
            title = ""
            try:
                title = triage.strip_html(__import__("re").search(r"<title>(.*?)</title>", body, __import__("re").I | __import__("re").S).group(1))
            except Exception:
                pass
            raise RuntimeError(
                "Dedicated Jira browser did not return Jira REST JSON.\n"
                f"HTTP {status} {ctype}\nTitle: {title}\n"
                "Open/Login Jira in the dedicated browser first, then retry."
            )
        payload = json.loads(body)
        total = int(payload.get("total") or 0)
        raw_issues = payload.get("issues") or []
        if not raw_issues:
            break
        for raw in raw_issues:
            issue = triage.parse_issue_from_json(raw)
            issue["source"] = "Jira REST via dedicated browser (Audio Resource Linker GUI)"
            issue["url"] = jira_issue_url(base_url, issue.get("key", ""))
            try:
                evidence = triage.rank_evidence(issue, index, limit=12) if index else []
                issue["evidence"] = evidence
                issue.update(triage.classify_issue(issue, evidence))
                triage.assign_issue_dimensions(issue)
            except Exception as exc:
                emit(f"Jira classify warning {issue.get('key','')}: {exc}")
            issues.append(issue)
            if len(issues) >= limit:
                break
        start_at += len(raw_issues)
        if total is not None and start_at >= total:
            break

    metadata = triage.save_jira_issue_cache(
        issues,
        jira_url=base_url,
        jql=jql,
        source="Jira REST via dedicated browser (Audio Resource Linker GUI)",
    )
    emit(f"Saved Jira cache: {len(issues)} issues. Cache: {JIRA_CACHE_PATH}")
    return {"issues": len(issues), "total": total, "metadata": metadata}


class AudioResourceJiraLinkerGui(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("ProjectEF Audio Resource Jira Linker")
        self.geometry("1320x820")
        self.configure(bg=BG)
        self.queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.latest_excel = StringVar(value=self.find_latest_excel())
        self.latest_json = StringVar(value="")

        self.unity_root_var = StringVar(value=str(UNITY_ROOT))
        self.scan_runtime_var = BooleanVar(value=True)
        self.scan_art_var = BooleanVar(value=True)
        self.refresh_resources_var = BooleanVar(value=True)
        self.refresh_jira_var = BooleanVar(value=True)
        self.learn_p4_var = BooleanVar(value=True)
        self.use_action_index_var = BooleanVar(value=True)
        self.jira_url_var = StringVar(value=DEFAULT_JIRA_URL)
        self.jql_var = StringVar(value=DEFAULT_JQL)
        self.jql_limit_var = IntVar(value=500)
        self.p4_since_var = StringVar(value="2026/06/01")
        self.p4_max_var = IntVar(value=500)
        self.p4_describe_var = IntVar(value=500)
        self.min_score_var = IntVar(value=45)

        self.build_ui()
        self.after(100, self.drain_queue)

    def build_ui(self) -> None:
        header = tk.Frame(self, bg=BG)
        header.pack(fill=tk.X, padx=14, pady=(12, 6))
        tk.Label(header, text="ProjectEF Audio Resource Jira Linker", bg=BG, fg=INK, font=("Segoe UI", 19, "bold")).pack(side=tk.LEFT)
        tk.Label(header, text="Read-only resource/Jira/P4 learning report", bg=BG, fg=MUTED, font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=14, pady=(8, 0))

        main = tk.Frame(self, bg=BG)
        main.pack(fill=tk.BOTH, expand=True, padx=12, pady=8)

        self.section(main, "Inputs")
        input_grid = tk.Frame(main, bg=PANEL)
        input_grid.pack(fill=tk.X, pady=(0, 8))
        self.labeled_entry(input_grid, "Unity Root", self.unity_root_var, 78, 0, 0)
        self.button(input_grid, "Browse", self.browse_unity_root).grid(row=0, column=2, padx=6, pady=8)
        self.check(input_grid, "RuntimeAssets", self.scan_runtime_var).grid(row=0, column=3, padx=6)
        self.check(input_grid, "ArtAssets", self.scan_art_var).grid(row=0, column=4, padx=6)

        self.labeled_entry(input_grid, "Jira URL", self.jira_url_var, 38, 1, 0)
        self.labeled_entry(input_grid, "JQL", self.jql_var, 92, 1, 2, columnspan=3)
        self.labeled_entry(input_grid, "Limit", self.jql_limit_var, 8, 1, 5)

        self.section(main, "Run Options")
        opts = tk.Frame(main, bg=PANEL)
        opts.pack(fill=tk.X, pady=(0, 8))
        self.check(opts, "Scan resources", self.refresh_resources_var).pack(side=tk.LEFT, padx=12, pady=8)
        self.check(opts, "Refresh Jira cache", self.refresh_jira_var).pack(side=tk.LEFT, padx=12)
        self.check(opts, "Learn recent P4", self.learn_p4_var).pack(side=tk.LEFT, padx=12)
        self.check(opts, "Use latest action index", self.use_action_index_var).pack(side=tk.LEFT, padx=12)
        self.labeled_pack_entry(opts, "P4 Since", self.p4_since_var, 12)
        self.labeled_pack_entry(opts, "Max CL", self.p4_max_var, 8)
        self.labeled_pack_entry(opts, "Describe", self.p4_describe_var, 8)
        self.labeled_pack_entry(opts, "Min Score", self.min_score_var, 8)

        self.section(main, "Actions")
        actions = tk.Frame(main, bg=PANEL)
        actions.pack(fill=tk.X, pady=(0, 8))
        self.button(actions, "Run Full Refresh", self.run_full_refresh, bg=ACCENT).pack(side=tk.LEFT, padx=8, pady=10)
        self.button(actions, "Build Table Only", self.build_table_only).pack(side=tk.LEFT, padx=6)
        self.button(actions, "Refresh Jira Only", self.refresh_jira_only).pack(side=tk.LEFT, padx=6)
        self.button(actions, "Open/Login Jira Browser", self.open_dedicated_jira_browser, bg="#315577").pack(side=tk.LEFT, padx=6)
        self.button(actions, "Open Existing Jira Tool", self.open_existing_jira_tool).pack(side=tk.LEFT, padx=6)
        self.button(actions, "Open Latest Excel", self.open_latest_excel).pack(side=tk.LEFT, padx=6)
        self.button(actions, "Open Report Folder", self.open_report_folder).pack(side=tk.LEFT, padx=6)
        self.button(actions, "Open Thumbnail Folder", self.open_thumbnail_folder).pack(side=tk.LEFT, padx=6)

        self.progress = ttk.Progressbar(main, mode="indeterminate")
        self.progress.pack(fill=tk.X, pady=(0, 8))

        status = tk.Frame(main, bg=PANEL)
        status.pack(fill=tk.X, pady=(0, 8))
        tk.Label(status, text="Latest Excel", bg=PANEL, fg=MUTED, font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=(10, 6), pady=8)
        tk.Entry(status, textvariable=self.latest_excel, bg=PANEL_2, fg=INK, insertbackground=INK, relief=tk.FLAT, width=150).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10), pady=8, ipady=4)

        self.log = tk.Text(main, bg="#0c131b", fg=INK, insertbackground=INK, relief=tk.FLAT, height=20, wrap=tk.WORD)
        self.log.pack(fill=tk.BOTH, expand=True)
        self.log_insert("Ready. This tool writes only local reports and caches; it does not edit Unity/Wwise assets.\n")

    def section(self, parent: tk.Widget, title: str) -> None:
        tk.Label(parent, text=title, bg=BG, fg=MUTED, font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(8, 2))

    def button(self, parent: tk.Widget, text: str, command, bg: str = PANEL_2) -> tk.Button:
        return tk.Button(parent, text=text, command=command, bg=bg, fg=INK, activebackground=ACCENT, activeforeground=INK, relief=tk.FLAT, padx=12, pady=6, font=("Segoe UI", 9, "bold"))

    def check(self, parent: tk.Widget, text: str, var: BooleanVar) -> tk.Checkbutton:
        return tk.Checkbutton(parent, text=text, variable=var, bg=PANEL, fg=INK, activebackground=PANEL, activeforeground=INK, selectcolor=BG, font=("Segoe UI", 9))

    def labeled_entry(self, parent: tk.Widget, label: str, var, width: int, row: int, col: int, columnspan: int = 1) -> None:
        frame = tk.Frame(parent, bg=PANEL)
        frame.grid(row=row, column=col, columnspan=columnspan, padx=8, pady=8, sticky="we")
        tk.Label(frame, text=label, bg=PANEL, fg=MUTED, font=("Segoe UI", 8, "bold")).pack(anchor="w")
        tk.Entry(frame, textvariable=var, bg=PANEL_2, fg=INK, insertbackground=INK, relief=tk.FLAT, width=width).pack(fill=tk.X, ipady=4)
        parent.grid_columnconfigure(col, weight=1 if width > 20 else 0)

    def labeled_pack_entry(self, parent: tk.Widget, label: str, var, width: int) -> None:
        frame = tk.Frame(parent, bg=PANEL)
        frame.pack(side=tk.LEFT, padx=8, pady=6)
        tk.Label(frame, text=label, bg=PANEL, fg=MUTED, font=("Segoe UI", 8, "bold")).pack(anchor="w")
        tk.Entry(frame, textvariable=var, bg=PANEL_2, fg=INK, insertbackground=INK, relief=tk.FLAT, width=width).pack(ipady=4)

    def browse_unity_root(self) -> None:
        path = filedialog.askdirectory(initialdir=self.unity_root_var.get() or str(UNITY_ROOT))
        if path:
            self.unity_root_var.set(path)

    def log_insert(self, text: str) -> None:
        self.log.insert(tk.END, text)
        if not text.endswith("\n"):
            self.log.insert(tk.END, "\n")
        self.log.see(tk.END)

    def emit(self, text: str) -> None:
        self.queue.put(("log", text))

    def drain_queue(self) -> None:
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "log":
                    self.log_insert(str(payload))
                elif kind == "done":
                    self.progress.stop()
                    self.set_busy(False)
                    data = payload if isinstance(payload, dict) else {}
                    if data.get("xlsx"):
                        self.latest_excel.set(str(data["xlsx"]))
                    if data.get("json"):
                        self.latest_json.set(str(data["json"]))
                    if data.get("summary"):
                        self.log_insert("Summary: " + json.dumps(data["summary"], ensure_ascii=False))
                    messagebox.showinfo("Audio Resource Jira Linker", "Done.\n\n" + str(data.get("xlsx", ""))[:900])
                elif kind == "error":
                    self.progress.stop()
                    self.set_busy(False)
                    messagebox.showerror("Audio Resource Jira Linker", str(payload)[:4000])
        except queue.Empty:
            pass
        self.after(100, self.drain_queue)

    def set_busy(self, busy: bool) -> None:
        # A light guard is enough: avoid launching overlapping workers.
        pass

    def start_worker(self, target) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("Audio Resource Jira Linker", "A refresh is already running.")
            return
        self.progress.start(12)
        self.worker = threading.Thread(target=self.worker_wrapper, args=(target,), daemon=True)
        self.worker.start()

    def worker_wrapper(self, target) -> None:
        try:
            result = target()
            self.queue.put(("done", result or {}))
        except Exception:
            self.queue.put(("error", traceback.format_exc()))

    def scan_roots(self) -> list[str]:
        root = Path(self.unity_root_var.get().strip())
        roots = []
        if self.scan_runtime_var.get():
            roots.append(str(root / "Assets" / "GameProject" / "RuntimeAssets"))
        if self.scan_art_var.get():
            roots.append(str(root / "Assets" / "GameProject" / "ArtAssets"))
        return roots

    def run_action_index(self) -> dict:
        args = [sys.executable, str(ACTION_INDEX_SCRIPT), "--unity-root", self.unity_root_var.get().strip(), "--out-dir", str(ACTION_INDEX_DIR)]
        for scan_root in self.scan_roots():
            args += ["--scan-root", scan_root]
        out = run_command(args, APP_DIR, self.emit)
        return parse_last_json_object(out)

    def run_linker(self) -> dict:
        p4_max = int(self.p4_max_var.get()) if self.learn_p4_var.get() else 0
        args = [
            sys.executable,
            str(LINKER_SCRIPT),
            "--p4-max-changes",
            str(p4_max),
            "--p4-describe-limit",
            str(int(self.p4_describe_var.get())),
            "--p4-since",
            self.p4_since_var.get().strip(),
            "--min-score",
            str(int(self.min_score_var.get())),
            "--max-links-per-resource",
            "5",
            "--thumbnail-dir",
            str(THUMBNAIL_DIR),
        ]
        if self.use_action_index_var.get():
            args.append("--use-action-index")
        out = run_command(args, APP_DIR, self.emit)
        data = parse_last_json_object(out)
        if not data:
            raise RuntimeError("Linker did not print a JSON result.")
        return data

    def full_refresh_job(self) -> dict:
        started = time.time()
        self.emit("Starting full refresh...")
        if self.refresh_resources_var.get():
            self.emit("Step 1/3: scanning action resources...")
            self.run_action_index()
        else:
            self.emit("Step 1/3 skipped: resource scan disabled.")

        if self.refresh_jira_var.get():
            self.emit("Step 2/3: refreshing Jira cache via dedicated browser...")
            refresh_jira_cache_via_dedicated_browser(
                self.jira_url_var.get().strip(),
                self.jql_var.get().strip(),
                int(self.jql_limit_var.get()),
                self.emit,
            )
        else:
            self.emit("Step 2/3 skipped: Jira refresh disabled; using existing cache.")

        self.emit("Step 3/3: learning recent P4 metadata and building Excel report...")
        result = self.run_linker()
        self.emit(f"Finished in {time.time() - started:.1f}s")
        return result

    def run_full_refresh(self) -> None:
        self.start_worker(self.full_refresh_job)

    def build_table_only(self) -> None:
        self.refresh_resources_var.set(False)
        self.refresh_jira_var.set(False)
        self.start_worker(self.run_linker)

    def refresh_jira_only(self) -> None:
        def job() -> dict:
            result = refresh_jira_cache_via_dedicated_browser(
                self.jira_url_var.get().strip(),
                self.jql_var.get().strip(),
                int(self.jql_limit_var.get()),
                self.emit,
            )
            return {"summary": result, "xlsx": self.latest_excel.get()}
        self.start_worker(job)

    def open_dedicated_jira_browser(self) -> None:
        try:
            triage = load_jira_module()
            triage.start_dedicated_jira_browser(self.jira_url_var.get().strip(), self.jql_var.get().strip())
            messagebox.showinfo("Jira Browser", "Dedicated Jira browser opened. Log in there once, then click Refresh Jira Cache or Run Full Refresh.")
        except Exception as exc:
            messagebox.showerror("Jira Browser", str(exc)[:4000])

    def open_existing_jira_tool(self) -> None:
        subprocess.Popen([sys.executable, str(JIRA_GUI_SCRIPT)], cwd=str(APP_DIR))

    def open_latest_excel(self) -> None:
        path = self.latest_excel.get().strip() or self.find_latest_excel()
        if not path or not Path(path).exists():
            messagebox.showinfo("Open Latest Excel", "No report found yet.")
            return
        os.startfile(path)

    def open_report_folder(self) -> None:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        os.startfile(str(REPORT_DIR))

    def open_thumbnail_folder(self) -> None:
        THUMBNAIL_DIR.mkdir(parents=True, exist_ok=True)
        os.startfile(str(THUMBNAIL_DIR))

    def find_latest_excel(self) -> str:
        if not REPORT_DIR.exists():
            return ""
        files = list(REPORT_DIR.glob("ProjectEF_AudioResourceJiraLinks_*.xlsx"))
        if not files:
            return ""
        return str(max(files, key=lambda p: p.stat().st_mtime))


def main() -> int:
    app = AudioResourceJiraLinkerGui()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
