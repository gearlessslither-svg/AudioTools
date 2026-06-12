#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ProjectEF Wwise Audio Logic Tester — a programmable, LLM-driven Sound Caster.

Describe a complex audio test in natural language; an LLM (local Ollama or remote
GPT/Claude) turns it into a structured DSL grounded in the project's real objects;
a runtime engine executes it against the open Wwise Authoring instance via WAAPI
(post events, ramp RTPCs over time, conditional triggers on RTPC crossings,
states/switches, loops, parallel branches). No game build required.
"""
from __future__ import annotations

import json
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audio_logic_engine import AudioLogicEngine, DEFAULT_WAAPI_URL, run_plan  # noqa: E402
from audio_logic_llm import LLMConfig, generate_plan  # noqa: E402

EXAMPLE = (
    "触发青蛙环境音；\n"
    "把环境湿度 RTPC 从 0 缓慢升到 100、再降回 20，总共 8 秒；\n"
    "湿度升过 60 时触发 buzzbait；\n"
    "湿度回落到 30 时触发鱼入水声。"
)


class AudioLogicTesterGUI(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("ProjectEF Wwise Audio Logic Tester (LLM Sound Caster)")
        self.geometry("1040x760")
        self.q: queue.Queue[tuple[str, object]] = queue.Queue()
        self.objects: dict | None = None
        self.stop_flag = threading.Event()
        self.run_thread: threading.Thread | None = None

        self._build()
        self.after(100, self._drain)

    def _build(self) -> None:
        # --- connection row ---
        conn = ttk.LabelFrame(self, text="1. 连接 Wwise (WAAPI)")
        conn.pack(fill="x", padx=10, pady=6)
        self.url_var = tk.StringVar(value=DEFAULT_WAAPI_URL)
        ttk.Label(conn, text="WAAPI URL:").pack(side="left", padx=6, pady=6)
        ttk.Entry(conn, textvariable=self.url_var, width=34).pack(side="left", padx=4)
        ttk.Button(conn, text="连接 / 刷新对象", command=self.do_connect).pack(side="left", padx=6)
        self.conn_label = ttk.Label(conn, text="未连接")
        self.conn_label.pack(side="left", padx=10)

        # --- model row ---
        model = ttk.LabelFrame(self, text="2. 模型")
        model.pack(fill="x", padx=10, pady=6)
        self.mode_var = tk.StringVar(value="auto")
        self.provider_var = tk.StringVar(value="ollama")
        self.model_var = tk.StringVar(value="qwen2.5:7b-instruct")
        ttk.Label(model, text="模式:").pack(side="left", padx=6, pady=6)
        ttk.Combobox(model, textvariable=self.mode_var, values=["auto", "local", "remote"],
                     width=8, state="readonly").pack(side="left")
        ttk.Label(model, text="provider:").pack(side="left", padx=6)
        ttk.Combobox(model, textvariable=self.provider_var,
                     values=["ollama", "openai", "anthropic"], width=10,
                     state="readonly").pack(side="left")
        ttk.Label(model, text="模型名:").pack(side="left", padx=6)
        ttk.Entry(model, textvariable=self.model_var, width=22).pack(side="left")
        ttk.Label(model, text="(远程 GPT/Claude 需在环境变量配置 API Key)").pack(side="left", padx=8)

        # --- scenario ---
        scen = ttk.LabelFrame(self, text="3. 用自然语言描述测试场景")
        scen.pack(fill="both", expand=False, padx=10, pady=6)
        self.scenario = ScrolledText(scen, height=6, wrap="word", font=("Microsoft YaHei", 10))
        self.scenario.pack(fill="x", padx=6, pady=6)
        self.scenario.insert("1.0", EXAMPLE)
        ttk.Button(scen, text="① 生成测试逻辑 (DSL)", command=self.do_generate).pack(side="left", padx=6, pady=4)
        ttk.Button(scen, text="载入场景", command=self.do_load).pack(side="left")
        ttk.Button(scen, text="保存场景", command=self.do_save).pack(side="left", padx=6)

        # --- DSL editor ---
        dsl = ttk.LabelFrame(self, text="4. 测试逻辑 DSL (可手动编辑后再运行)")
        dsl.pack(fill="both", expand=True, padx=10, pady=6)
        self.dsl_text = ScrolledText(dsl, height=12, wrap="none", font=("Consolas", 10))
        self.dsl_text.pack(fill="both", expand=True, padx=6, pady=6)
        ttk.Button(dsl, text="② ▶ 运行", command=self.do_run).pack(side="left", padx=6, pady=4)
        ttk.Button(dsl, text="■ 停止", command=self.do_stop).pack(side="left")
        self.run_name_var = tk.StringVar(value="当前 DSL 场景: (空)")
        ttk.Label(dsl, textvariable=self.run_name_var, foreground="#2a6").pack(side="left", padx=14)

        # --- log ---
        logf = ttk.LabelFrame(self, text="运行日志")
        logf.pack(fill="both", expand=True, padx=10, pady=6)
        self.log_text = ScrolledText(logf, height=10, wrap="word", state="disabled",
                                     bg="#1e1e1e", fg="#dcdcdc", font=("Consolas", 10))
        self.log_text.pack(fill="both", expand=True, padx=6, pady=6)

    # ---------- helpers ----------
    def _log(self, msg: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", msg + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _sync_name_from_dsl(self) -> None:
        try:
            plan = json.loads(self.dsl_text.get("1.0", "end"))
            self.run_name_var.set(f"当前 DSL 场景: {plan.get('name', '?')} "
                                  f"({len(plan.get('steps', []))} 步)")
        except Exception:  # noqa: BLE001
            self.run_name_var.set("当前 DSL 场景: (DSL 未解析,无法运行)")

    def _cfg(self) -> LLMConfig:
        provider = self.provider_var.get()
        kwargs = {"mode": self.mode_var.get(), "provider": provider}
        if provider == "ollama":
            kwargs["local_model"] = self.model_var.get().strip()
        elif provider == "anthropic":
            kwargs["anthropic_model"] = self.model_var.get().strip()
        else:
            kwargs["openai_model"] = self.model_var.get().strip()
        return LLMConfig(**kwargs)

    def _drain(self) -> None:
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    self._log(str(payload))
                elif kind == "conn":
                    self.conn_label.config(text=str(payload))
                elif kind == "dsl":
                    self.dsl_text.delete("1.0", "end")
                    self.dsl_text.insert("1.0", str(payload))
                    self._sync_name_from_dsl()
                elif kind == "error":
                    messagebox.showerror("错误", str(payload))
        except queue.Empty:
            pass
        self.after(100, self._drain)

    # ---------- actions ----------
    def do_connect(self) -> None:
        def worker() -> None:
            try:
                eng = AudioLogicEngine(url=self.url_var.get().strip(),
                                       log=lambda m: self.q.put(("log", m)))
                eng.connect()
                self.objects = eng.fetch_objects()
                eng.disconnect()
                o = self.objects
                self.q.put(("conn", f"已连接 ✓  events={len(o['events'])} "
                                     f"rtpcs={len(o['rtpcs'])} states={len(o['state_groups'])} "
                                     f"switches={len(o['switch_groups'])}"))
            except Exception as exc:  # noqa: BLE001
                self.q.put(("conn", "连接失败"))
                self.q.put(("error", exc))
        threading.Thread(target=worker, daemon=True).start()

    def do_generate(self) -> None:
        if not self.objects:
            messagebox.showinfo("先连接", "请先点“连接 / 刷新对象”。")
            return
        scenario = self.scenario.get("1.0", "end").strip()
        cfg = self._cfg()
        self._log(f"\n[生成] 用 {cfg.mode}/{cfg.provider} 模型生成 DSL…")

        def worker() -> None:
            try:
                plan = generate_plan(scenario, self.objects, cfg)
                self.q.put(("dsl", json.dumps(plan, ensure_ascii=False, indent=2)))
                self.q.put(("log", "[生成] 完成,请检查/编辑 DSL 后点运行。"))
            except Exception as exc:  # noqa: BLE001
                self.q.put(("error", exc))
        threading.Thread(target=worker, daemon=True).start()

    def do_run(self) -> None:
        if self.run_thread and self.run_thread.is_alive():
            messagebox.showinfo("运行中", "已有场景在运行,先停止。")
            return
        try:
            plan = json.loads(self.dsl_text.get("1.0", "end"))
        except json.JSONDecodeError as exc:
            messagebox.showerror("DSL 无效", f"JSON 解析失败:\n{exc}")
            return
        self.stop_flag.clear()
        self.run_name_var.set(f"▶ 运行中: {plan.get('name', '?')} ({len(plan.get('steps', []))} 步)")
        url = self.url_var.get().strip()

        def worker() -> None:
            try:
                run_plan(plan, url=url, log=lambda m: self.q.put(("log", m)),
                         stop_flag=self.stop_flag)
            except Exception as exc:  # noqa: BLE001
                self.q.put(("error", exc))
        self.run_thread = threading.Thread(target=worker, daemon=True)
        self.run_thread.start()

    def do_stop(self) -> None:
        self.stop_flag.set()
        self._log("[停止] 已请求停止…")

    def do_save(self) -> None:
        path = filedialog.asksaveasfilename(defaultextension=".json",
                                            filetypes=[("JSON", "*.json")])
        if not path:
            return
        dsl_raw = self.dsl_text.get("1.0", "end").strip()
        try:
            dsl_obj: object = json.loads(dsl_raw) if dsl_raw else {}
        except json.JSONDecodeError:
            dsl_obj = dsl_raw  # keep raw text if not valid JSON yet
        bundle = {"scenario": self.scenario.get("1.0", "end").strip(), "dsl": dsl_obj}
        Path(path).write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
        self._log(f"已保存场景(描述+DSL): {path}")

    def do_load(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            messagebox.showerror("载入失败", str(exc))
            return
        if isinstance(data, dict) and "steps" in data:           # raw DSL plan
            scenario, dsl = "(已载入外部 DSL,无原始描述)", data
        elif isinstance(data, dict):                             # bundled {scenario, dsl}
            scenario, dsl = data.get("scenario", ""), data.get("dsl", "")
        else:
            messagebox.showerror("载入失败", "无法识别的文件格式。")
            return
        dsl_str = json.dumps(dsl, ensure_ascii=False, indent=2) if isinstance(dsl, (dict, list)) else str(dsl)
        self.scenario.delete("1.0", "end"); self.scenario.insert("1.0", scenario)
        self.dsl_text.delete("1.0", "end"); self.dsl_text.insert("1.0", dsl_str)
        self._sync_name_from_dsl()
        self._log(f"已载入场景: {path}")


def main() -> None:
    AudioLogicTesterGUI().mainloop()


if __name__ == "__main__":
    main()
