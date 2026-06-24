#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ProjectEF Audio Jira Creator GUI.

Fill a title + the involved disciplines (工种); the tool fills the rest from a
template + learned rules, shows a full PREVIEW, and only creates the Jira issue
after explicit confirmation.

- Reuses the Jira connection (url + cookie) saved by the Audio Requirement Jira
  Triage tool (audio_requirement_jira_triage_config.json) — no separate login.
- "学习 Jira 规则" calls /rest/api/2/issue/createmeta + recent PROEF issues to
  derive valid issue types / components / labels into audio_jira_creator_rules.json.
- NOTHING is posted to Jira without you clicking 创建 and confirming the dialog.

NOTE: Jira is internal (ef.jira.blackjack-local.com). With Mullvad VPN on it is
unreachable — disconnect Mullvad for the Learn / Create steps (drafting works offline).
"""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

APP_DIR = Path(__file__).resolve().parent
TRIAGE_CONFIG = APP_DIR / "audio_requirement_jira_triage_config.json"   # reuse url+cookie
RULES_PATH = APP_DIR / "audio_jira_creator_rules.json"
DEFAULT_JIRA_URL = "http://ef.jira.blackjack-local.com:8080"
PROJECT_KEY = "PROEF"

# Disciplines the user picked -> default Jira component name (refined by Learn).
DEFAULT_DISCIPLINES = {
    "音频设计": "Audio",
    "客户端程序": "Client",
    "技术美术/TA": "TA",
    "QA/测试": "QA",
}

DEFAULT_RULES = {
    "project_key": PROJECT_KEY,
    "issue_types": ["Task", "Bug", "Story"],
    "default_issue_type": "Task",
    "priorities": ["P0", "P1", "P2", "P3"],
    "default_priority": "P2",
    "discipline_components": DEFAULT_DISCIPLINES,
    "default_labels": ["audio"],
    "components_available": [],   # filled by Learn (valid PROEF components)
    "description_template": (
        "h3. 背景\n（待补充）\n\n"
        "h3. 需求 / 期望\n{title}\n\n"
        "h3. 涉及工种\n{disciplines}\n\n"
        "h3. 验收标准\n"
        "* 在对应场景/触发条件下能正常听到目标音频\n"
        "* Wwise 事件 / RTPC / Switch 配置正确,并已生成 SoundBank\n"
        "* 相关资源已提交到对应版本库 (P4 CL)\n\n"
        "h3. 备注\n由音频设计创建。补充信息请在评论区跟进。"
    ),
}


# ---------------- config / rules ----------------
def load_jira_conn() -> tuple[str, str]:
    url, cookie = DEFAULT_JIRA_URL, ""
    if TRIAGE_CONFIG.exists():
        try:
            d = json.loads(TRIAGE_CONFIG.read_text(encoding="utf-8"))
            url = (d.get("jira_url") or url).strip()
            cookie = (d.get("jira_cookie") or "").strip()
        except (OSError, json.JSONDecodeError):
            pass
    return url, cookie


def load_rules() -> dict:
    if RULES_PATH.exists():
        try:
            data = json.loads(RULES_PATH.read_text(encoding="utf-8"))
            merged = dict(DEFAULT_RULES)
            merged.update(data)
            return merged
        except (OSError, json.JSONDecodeError):
            pass
    return dict(DEFAULT_RULES)


def save_rules(rules: dict) -> None:
    RULES_PATH.write_text(json.dumps(rules, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------- jira client ----------------
def _req(url: str, cookie: str, data: bytes | None = None, method: str = "GET", timeout: int = 30):
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if cookie:
        headers["Cookie"] = cookie
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            return resp.getcode(), resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except urllib.error.URLError as exc:
        raise RuntimeError(f"连接 Jira 失败({url}): {exc.reason}。如果开着 Mullvad VPN,请先断开。") from exc


def jira_get(base: str, path: str, cookie: str, timeout: int = 30):
    return _req(base.rstrip("/") + path, cookie, None, "GET", timeout)


def jira_post(base: str, path: str, payload: dict, cookie: str, timeout: int = 30):
    return _req(base.rstrip("/") + path, cookie, json.dumps(payload).encode("utf-8"), "POST", timeout)


def learn_rules(base: str, cookie: str) -> dict:
    """Read live createmeta + recent issues to derive valid types/components/labels."""
    rules = load_rules()
    code, body = jira_get(
        base,
        f"/rest/api/2/issue/createmeta?projectKeys={PROJECT_KEY}&expand=projects.issuetypes.fields",
        cookie,
    )
    if code != 200:
        raise RuntimeError(f"createmeta 返回 {code}(可能未登录/cookie 过期或被 VPN 拦)。{body[:200]}")
    meta = json.loads(body)
    projects = meta.get("projects") or []
    if not projects:
        raise RuntimeError("createmeta 没有返回 PROEF 项目;检查项目 key 和权限。")
    issuetypes = projects[0].get("issuetypes") or []
    rules["issue_types"] = [it.get("name") for it in issuetypes if it.get("name")] or rules["issue_types"]
    comps: set[str] = set()
    prios: list[str] = []
    for it in issuetypes:
        fields = it.get("fields") or {}
        for av in (fields.get("components") or {}).get("allowedValues") or []:
            if av.get("name"):
                comps.add(av["name"])
        for av in (fields.get("priority") or {}).get("allowedValues") or []:
            if av.get("name") and av["name"] not in prios:
                prios.append(av["name"])
    if comps:
        rules["components_available"] = sorted(comps)
    if prios:
        rules["priorities"] = prios
        rules["default_priority"] = prios[len(prios) // 2]
    save_rules(rules)
    return rules


# ---------------- GUI ----------------
class AudioJiraCreator(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("ProjectEF 音频 Jira 创建工具")
        self.geometry("960x720")
        self.rules = load_rules()
        self.jira_url, self.jira_cookie = load_jira_conn()
        self.disc_vars: dict[str, tk.BooleanVar] = {}
        self._build()

    def _build(self) -> None:
        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")
        ttk.Label(top, text=f"Jira: {self.jira_url}  (project {PROJECT_KEY})").pack(side="left")
        ttk.Button(top, text="学习 Jira 规则", command=self.do_learn).pack(side="right")

        form = ttk.Frame(self, padding=(10, 0))
        form.pack(fill="x")
        ttk.Label(form, text="Jira 标题 *").grid(row=0, column=0, sticky="w")
        self.title_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.title_var, width=90).grid(row=0, column=1, columnspan=3, sticky="we", pady=4)

        ttk.Label(form, text="涉及工种").grid(row=1, column=0, sticky="w")
        disc_frame = ttk.Frame(form)
        disc_frame.grid(row=1, column=1, columnspan=3, sticky="w")
        for name in self.rules.get("discipline_components", DEFAULT_DISCIPLINES):
            v = tk.BooleanVar(value=(name == "音频设计"))
            self.disc_vars[name] = v
            ttk.Checkbutton(disc_frame, text=name, variable=v).pack(side="left", padx=6)

        ttk.Label(form, text="类型").grid(row=2, column=0, sticky="w")
        self.type_var = tk.StringVar(value=self.rules.get("default_issue_type", "Task"))
        ttk.Combobox(form, textvariable=self.type_var, values=self.rules.get("issue_types", []), width=18,
                     state="readonly").grid(row=2, column=1, sticky="w", pady=4)
        ttk.Label(form, text="优先级").grid(row=2, column=2, sticky="e")
        self.prio_var = tk.StringVar(value=self.rules.get("default_priority", "P2"))
        ttk.Combobox(form, textvariable=self.prio_var, values=self.rules.get("priorities", []), width=12,
                     state="readonly").grid(row=2, column=3, sticky="w")

        ttk.Label(form, text="Components").grid(row=3, column=0, sticky="w")
        self.comp_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.comp_var, width=90).grid(row=3, column=1, columnspan=3, sticky="we", pady=4)
        form.columnconfigure(1, weight=1)

        btns = ttk.Frame(self, padding=10)
        btns.pack(fill="x")
        ttk.Button(btns, text="① 生成预览", command=self.do_preview).pack(side="left")
        ttk.Button(btns, text="② 创建 Jira(需确认)", command=self.do_create).pack(side="left", padx=8)

        ttk.Label(self, text="预览(描述可直接编辑)").pack(anchor="w", padx=10)
        self.preview = scrolledtext.ScrolledText(self, height=20, wrap="word", font=("Consolas", 10))
        self.preview.pack(fill="both", expand=True, padx=10, pady=4)

        self.status = tk.Label(self, text="就绪。Mullvad 开着时无法连 Jira(学习/创建需断开)。", anchor="w",
                               bd=1, relief="sunken")
        self.status.pack(fill="x", side="bottom")

    # ---- helpers ----
    def selected_disciplines(self) -> list[str]:
        return [n for n, v in self.disc_vars.items() if v.get()]

    def components_for(self, disciplines: list[str]) -> list[str]:
        mp = self.rules.get("discipline_components", DEFAULT_DISCIPLINES)
        return [mp[d] for d in disciplines if d in mp]

    def build_description(self, title: str, disciplines: list[str]) -> str:
        tmpl = self.rules.get("description_template", DEFAULT_RULES["description_template"])
        disc_text = "\n".join(f"* {d}" for d in disciplines) or "* (未指定)"
        return tmpl.format(title=title, disciplines=disc_text)

    def _log(self, msg: str) -> None:
        self.status.configure(text=msg)

    # ---- actions ----
    def do_learn(self) -> None:
        self._log("学习中:读取 createmeta + 最近 PROEF 单…")

        def worker():
            try:
                rules = learn_rules(self.jira_url, self.jira_cookie)
                self.after(0, lambda: self._learn_done(rules))
            except Exception as exc:  # noqa: BLE001
                err = exc
                self.after(0, lambda: self._fail("学习失败", err))

        threading.Thread(target=worker, daemon=True).start()

    def _learn_done(self, rules: dict) -> None:
        self.rules = rules
        self._log(f"学习完成:类型 {len(rules.get('issue_types', []))} 个,"
                  f"可用 component {len(rules.get('components_available', []))} 个 → 已存 {RULES_PATH.name}")
        messagebox.showinfo("学习完成",
                            "已从 Jira 学到合法字段并写入规则文件。\n\n"
                            f"Issue types: {', '.join(rules.get('issue_types', []))}\n"
                            f"Components: {', '.join(rules.get('components_available', [])[:20])}")

    def do_preview(self) -> None:
        title = self.title_var.get().strip()
        if not title:
            messagebox.showwarning("缺标题", "请先填写 Jira 标题。")
            return
        disciplines = self.selected_disciplines()
        comps = self.components_for(disciplines)
        self.comp_var.set(", ".join(comps))
        desc = self.build_description(title, disciplines)
        self.preview.delete("1.0", "end")
        self.preview.insert("1.0", desc)
        self._log("已生成预览。可编辑描述,确认无误后点「创建 Jira」。")

    def build_payload(self) -> dict:
        title = self.title_var.get().strip()
        desc = self.preview.get("1.0", "end").strip() or self.build_description(title, self.selected_disciplines())
        comps = [c.strip() for c in self.comp_var.get().split(",") if c.strip()]
        fields = {
            "project": {"key": self.rules.get("project_key", PROJECT_KEY)},
            "summary": title,
            "issuetype": {"name": self.type_var.get()},
            "description": desc,
        }
        if comps:
            fields["components"] = [{"name": c} for c in comps]
        if self.prio_var.get():
            fields["priority"] = {"name": self.prio_var.get()}
        labels = self.rules.get("default_labels") or []
        if labels:
            fields["labels"] = labels
        return {"fields": fields}

    def do_create(self) -> None:
        title = self.title_var.get().strip()
        if not title:
            messagebox.showwarning("缺标题", "请先填写 Jira 标题。")
            return
        if not self.preview.get("1.0", "end").strip():
            self.do_preview()
        payload = self.build_payload()
        f = payload["fields"]
        confirm = (
            "确认创建以下 Jira 单?(会写入生产 Jira)\n\n"
            f"项目: {f['project']['key']}\n"
            f"类型: {f['issuetype']['name']}   优先级: {f.get('priority', {}).get('name', '-')}\n"
            f"标题: {f['summary']}\n"
            f"Components: {', '.join(c['name'] for c in f.get('components', [])) or '-'}\n"
            f"Labels: {', '.join(f.get('labels', [])) or '-'}\n"
        )
        if not messagebox.askyesno("确认创建 Jira", confirm):
            self._log("已取消创建。")
            return
        self._log("创建中…")

        def worker():
            try:
                code, body = jira_post(self.jira_url, "/rest/api/2/issue", payload, self.jira_cookie)
                self.after(0, lambda: self._create_done(code, body))
            except Exception as exc:  # noqa: BLE001
                err = exc
                self.after(0, lambda: self._fail("创建失败", err))

        threading.Thread(target=worker, daemon=True).start()

    def _create_done(self, code: int, body: str) -> None:
        if code in (200, 201):
            try:
                key = json.loads(body).get("key", "?")
            except json.JSONDecodeError:
                key = "?"
            url = f"{self.jira_url.rstrip('/')}/browse/{key}"
            self._log(f"创建成功:{key}")
            messagebox.showinfo("创建成功", f"已创建 {key}\n{url}")
        else:
            self._log(f"创建失败 HTTP {code}")
            messagebox.showerror("创建失败",
                                 f"HTTP {code}\n\n{body[:600]}\n\n"
                                 "常见原因:cookie 过期(去 Jira Triage 工具点 Use Browser Login 刷新)、"
                                 "component/类型名不合法(先点「学习 Jira 规则」)、或 Mullvad 未断开。")

    def _fail(self, title: str, exc: Exception) -> None:
        self._log(f"{title}: {exc}")
        messagebox.showerror(title, str(exc))


def main() -> None:
    AudioJiraCreator().mainloop()


if __name__ == "__main__":
    main()
