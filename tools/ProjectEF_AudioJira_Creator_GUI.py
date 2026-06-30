#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ProjectEF Audio Jira Creator GUI.

Editor-side helper for drafting and safely creating ProjectEF audio Jira issues.

Safety posture:
- Reuses the Jira URL/cookie saved by the Audio Requirement Jira Triage tool.
- Does not ask for, print, or store account passwords.
- Learns Jira create metadata via /rest/api/2/issue/createmeta.
- Never posts to Jira unless "允许真实创建" is checked and the user confirms.
- Batch creation is intentionally sequential so partial failures are visible.
"""

from __future__ import annotations

import csv
import io
import json
import threading
import urllib.error
import urllib.request
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk


APP_DIR = Path(__file__).resolve().parent
TRIAGE_CONFIG = APP_DIR / "audio_requirement_jira_triage_config.json"
RULES_PATH = APP_DIR / "audio_jira_creator_rules.json"
DEFAULT_JIRA_URL = "http://ef.jira.blackjack-local.com:8080"
PROJECT_KEY = "PROEF"

STANDARD_FIELDS = {
    "project",
    "summary",
    "issuetype",
    "description",
    "components",
    "priority",
    "labels",
}

DEFAULT_DISCIPLINES = {
    "音频设计": "Audio",
    "客户端程序": "Client",
    "TA/技术美术": "TA",
    "QA/测试": "QA",
}

DEFAULT_RULES: dict[str, Any] = {
    "project_key": PROJECT_KEY,
    "issue_types": ["Task", "Bug", "Story"],
    "default_issue_type": "Task",
    "priorities": ["P0", "P1", "P2", "P3"],
    "default_priority": "P2",
    "discipline_components": DEFAULT_DISCIPLINES,
    "default_labels": ["audio"],
    "components_available": [],
    "required_fields_by_type": {},
    "field_meta_by_type": {},
    "description_template": (
        "h3. 背景\n"
        "（待补充）\n\n"
        "h3. 需求 / 期望\n"
        "{title}\n\n"
        "h3. 涉及工种\n"
        "{disciplines}\n\n"
        "h3. 验收标准\n"
        "* 在对应场景 / 触发条件下可以正常听到目标音频\n"
        "* Wwise 事件 / RTPC / Switch 配置正确，并已按项目流程生成或确认 SoundBank\n"
        "* 相关 Unity / Wwise / 配置资源已提交到对应 P4 changelist\n\n"
        "h3. 备注\n"
        "由音频设计创建。补充信息请在评论区继续跟进。"
    ),
}


@dataclass
class DraftIssue:
    title: str
    disciplines: list[str] = field(default_factory=list)
    components: list[str] = field(default_factory=list)
    issue_type: str = ""
    priority: str = ""
    labels: list[str] = field(default_factory=list)
    description: str = ""
    missing_required: list[str] = field(default_factory=list)
    status: str = "Draft"
    jira_key: str = ""
    error: str = ""


def load_jira_conn() -> tuple[str, str]:
    url, cookie = DEFAULT_JIRA_URL, ""
    if TRIAGE_CONFIG.exists():
        try:
            data = json.loads(TRIAGE_CONFIG.read_text(encoding="utf-8"))
            url = str(data.get("jira_url") or url).strip()
            cookie = str(data.get("jira_cookie") or "").strip()
        except (OSError, json.JSONDecodeError):
            pass
    return url, cookie


def load_rules() -> dict[str, Any]:
    if RULES_PATH.exists():
        try:
            data = json.loads(RULES_PATH.read_text(encoding="utf-8"))
            merged = dict(DEFAULT_RULES)
            merged.update(data)
            if not isinstance(merged.get("discipline_components"), dict):
                merged["discipline_components"] = dict(DEFAULT_DISCIPLINES)
            return merged
        except (OSError, json.JSONDecodeError):
            pass
    return dict(DEFAULT_RULES)


def save_rules(rules: dict[str, Any]) -> None:
    RULES_PATH.write_text(json.dumps(rules, ensure_ascii=False, indent=2), encoding="utf-8")


def split_list(text: str) -> list[str]:
    if not text:
        return []
    normalized = text.replace("，", ",").replace("；", ",").replace(";", ",").replace("|", ",")
    return [part.strip() for part in normalized.split(",") if part.strip()]


def is_nonempty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict)):
        return bool(value)
    return True


def request_json(url: str, cookie: str, data: bytes | None = None, method: str = "GET", timeout: int = 30) -> tuple[int, str]:
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if cookie:
        headers["Cookie"] = cookie
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.getcode(), response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except urllib.error.URLError as exc:
        raise RuntimeError(f"连接 Jira 失败：{exc.reason}。如果开着 VPN，请确认内网 Jira 可访问。") from exc


def jira_get(base: str, path: str, cookie: str, timeout: int = 30) -> tuple[int, str]:
    return request_json(base.rstrip("/") + path, cookie, None, "GET", timeout)


def jira_post(base: str, path: str, payload: dict[str, Any], cookie: str, timeout: int = 30) -> tuple[int, str]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return request_json(base.rstrip("/") + path, cookie, data, "POST", timeout)


def field_display_name(field_id: str, meta: dict[str, Any]) -> str:
    name = str(meta.get("name") or field_id)
    return f"{name} ({field_id})" if name != field_id else field_id


def extract_field_meta(field: dict[str, Any]) -> dict[str, Any]:
    allowed_values = []
    for value in field.get("allowedValues") or []:
        if isinstance(value, dict):
            allowed_values.append({
                "id": value.get("id"),
                "name": value.get("name") or value.get("value") or value.get("key"),
                "value": value.get("value"),
                "key": value.get("key"),
            })
        else:
            allowed_values.append({"name": str(value)})
    return {
        "required": bool(field.get("required")),
        "name": field.get("name", ""),
        "schema": field.get("schema", {}),
        "allowedValues": allowed_values[:200],
        "hasDefaultValue": bool(field.get("hasDefaultValue")),
    }


def learn_rules(base: str, cookie: str) -> dict[str, Any]:
    rules = load_rules()
    code, body = jira_get(
        base,
        f"/rest/api/2/issue/createmeta?projectKeys={PROJECT_KEY}&expand=projects.issuetypes.fields",
        cookie,
    )
    if code != 200:
        raise RuntimeError(f"createmeta 返回 HTTP {code}，可能未登录、cookie 过期或没有权限。\n{body[:600]}")
    meta = json.loads(body)
    projects = meta.get("projects") or []
    if not projects:
        raise RuntimeError("createmeta 没有返回 PROEF 项目。请检查项目 key 和账号权限。")

    issue_types = projects[0].get("issuetypes") or []
    rules["issue_types"] = [it.get("name") for it in issue_types if it.get("name")] or rules["issue_types"]

    components: set[str] = set()
    priorities: list[str] = []
    required_by_type: dict[str, list[str]] = {}
    field_meta_by_type: dict[str, dict[str, Any]] = {}

    for issue_type in issue_types:
        type_name = str(issue_type.get("name") or "")
        if not type_name:
            continue
        fields = issue_type.get("fields") or {}
        required: list[str] = []
        field_meta: dict[str, Any] = {}
        for field_id, field in fields.items():
            if not isinstance(field, dict):
                continue
            field_meta[field_id] = extract_field_meta(field)
            if field.get("required"):
                required.append(field_id)
            if field_id == "components":
                for value in field.get("allowedValues") or []:
                    name = value.get("name") if isinstance(value, dict) else None
                    if name:
                        components.add(str(name))
            if field_id == "priority":
                for value in field.get("allowedValues") or []:
                    name = value.get("name") if isinstance(value, dict) else None
                    if name and name not in priorities:
                        priorities.append(str(name))
        required_by_type[type_name] = required
        field_meta_by_type[type_name] = field_meta

    if components:
        rules["components_available"] = sorted(components)
    if priorities:
        rules["priorities"] = priorities
        if rules.get("default_priority") not in priorities:
            rules["default_priority"] = priorities[min(len(priorities) // 2, len(priorities) - 1)]
    rules["required_fields_by_type"] = required_by_type
    rules["field_meta_by_type"] = field_meta_by_type
    save_rules(rules)
    return rules


def format_payload(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


class AudioJiraCreator(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("ProjectEF Audio Jira Creator")
        self.geometry("1180x820")
        self.minsize(980, 680)
        self.rules = load_rules()
        self.jira_url, self.jira_cookie = load_jira_conn()
        self.drafts: list[DraftIssue] = []
        self._batch_preview_signature = ""
        self.disc_vars: dict[str, tk.BooleanVar] = {}
        self.allow_real_create_var = tk.BooleanVar(value=False)
        self.stop_on_error_var = tk.BooleanVar(value=True)
        self._build()
        self.refresh_cookie_status()

    def _build(self) -> None:
        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")
        ttk.Label(top, text=f"Jira: {self.jira_url}  Project: {PROJECT_KEY}").pack(side="left")
        ttk.Button(top, text="学习 Jira 必填字段", command=self.do_learn).pack(side="right")
        ttk.Button(top, text="打开 REST Browser", command=self.open_rest_browser).pack(side="right", padx=6)

        single = ttk.LabelFrame(self, text="单条创建", padding=10)
        single.pack(fill="x", padx=10, pady=(0, 8))
        ttk.Label(single, text="标题 *").grid(row=0, column=0, sticky="w")
        self.title_var = tk.StringVar()
        ttk.Entry(single, textvariable=self.title_var, width=90).grid(row=0, column=1, columnspan=5, sticky="we", pady=3)

        ttk.Label(single, text="涉及工种").grid(row=1, column=0, sticky="w")
        disc_frame = ttk.Frame(single)
        disc_frame.grid(row=1, column=1, columnspan=5, sticky="w")
        for name in self.rules.get("discipline_components", DEFAULT_DISCIPLINES):
            var = tk.BooleanVar(value=(name == "音频设计"))
            self.disc_vars[name] = var
            ttk.Checkbutton(disc_frame, text=name, variable=var).pack(side="left", padx=(0, 10))

        ttk.Label(single, text="类型").grid(row=2, column=0, sticky="w")
        self.type_var = tk.StringVar(value=self.rules.get("default_issue_type", "Task"))
        self.type_combo = ttk.Combobox(single, textvariable=self.type_var, values=self.rules.get("issue_types", []), width=20, state="readonly")
        self.type_combo.grid(row=2, column=1, sticky="w", pady=3)

        ttk.Label(single, text="优先级").grid(row=2, column=2, sticky="e")
        self.prio_var = tk.StringVar(value=self.rules.get("default_priority", "P2"))
        self.prio_combo = ttk.Combobox(single, textvariable=self.prio_var, values=self.rules.get("priorities", []), width=14, state="readonly")
        self.prio_combo.grid(row=2, column=3, sticky="w", pady=3)

        ttk.Label(single, text="Components").grid(row=3, column=0, sticky="w")
        self.comp_var = tk.StringVar()
        ttk.Entry(single, textvariable=self.comp_var, width=90).grid(row=3, column=1, columnspan=5, sticky="we", pady=3)

        ttk.Label(single, text="Labels").grid(row=4, column=0, sticky="w")
        self.labels_var = tk.StringVar(value=", ".join(self.rules.get("default_labels") or []))
        ttk.Entry(single, textvariable=self.labels_var, width=90).grid(row=4, column=1, columnspan=5, sticky="we", pady=3)

        single.columnconfigure(1, weight=1)
        single.columnconfigure(5, weight=1)

        batch = ttk.LabelFrame(self, text="批量输入", padding=10)
        batch.pack(fill="x", padx=10, pady=(0, 8))
        ttk.Label(batch, text="每行一个标题；也支持 CSV/TSV 表头：title, disciplines, components, priority, issue_type, labels, description").pack(anchor="w")
        self.batch_text = scrolledtext.ScrolledText(batch, height=5, wrap="word", font=("Consolas", 10))
        self.batch_text.pack(fill="x", expand=False, pady=(4, 0))

        extra = ttk.LabelFrame(self, text="额外字段 JSON（全局应用；用于 customfield 必填项）", padding=10)
        extra.pack(fill="x", padx=10, pady=(0, 8))
        ttk.Label(extra, text='示例：{"customfield_12345": {"value": "Alpha1版本"}}。为空则不追加。').pack(anchor="w")
        self.extra_json = scrolledtext.ScrolledText(extra, height=3, wrap="none", font=("Consolas", 10))
        self.extra_json.pack(fill="x", expand=False, pady=(4, 0))

        actions = ttk.Frame(self, padding=(10, 0))
        actions.pack(fill="x", pady=(0, 8))
        ttk.Button(actions, text="生成单条预览", command=self.do_single_preview).pack(side="left")
        ttk.Button(actions, text="解析批量 / Dry Run", command=self.do_batch_preview).pack(side="left", padx=6)
        ttk.Button(actions, text="查看必填字段报告", command=self.show_required_report).pack(side="left", padx=6)
        ttk.Button(actions, text="创建单条", command=self.do_create_single).pack(side="left", padx=18)
        ttk.Button(actions, text="批量创建预览列表", command=self.do_create_batch).pack(side="left", padx=6)
        ttk.Checkbutton(actions, text="允许真实创建", variable=self.allow_real_create_var).pack(side="left", padx=18)
        ttk.Checkbutton(actions, text="批量出错即停止", variable=self.stop_on_error_var).pack(side="left")

        panes = ttk.PanedWindow(self, orient=tk.VERTICAL)
        panes.pack(fill="both", expand=True, padx=10, pady=(0, 8))

        preview_frame = ttk.LabelFrame(panes, text="预览 / 日志")
        panes.add(preview_frame, weight=1)
        self.preview = scrolledtext.ScrolledText(preview_frame, height=12, wrap="word", font=("Consolas", 10))
        self.preview.pack(fill="both", expand=True, padx=6, pady=6)

        list_frame = ttk.LabelFrame(panes, text="批量预览列表")
        panes.add(list_frame, weight=1)
        columns = ("status", "title", "type", "priority", "components", "missing", "jira")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=9)
        headings = {
            "status": "状态",
            "title": "标题",
            "type": "类型",
            "priority": "优先级",
            "components": "Components",
            "missing": "缺失必填",
            "jira": "Jira",
        }
        widths = {
            "status": 90,
            "title": 360,
            "type": 100,
            "priority": 80,
            "components": 180,
            "missing": 260,
            "jira": 100,
        }
        for column in columns:
            self.tree.heading(column, text=headings[column])
            self.tree.column(column, width=widths[column], anchor="w")
        self.tree.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        yscroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        yscroll.pack(side="right", fill="y", pady=6)
        self.tree.configure(yscrollcommand=yscroll.set)
        self.tree.bind("<Double-1>", self.on_tree_double_click)

        self.status = tk.Label(self, text="", anchor="w", bd=1, relief="sunken")
        self.status.pack(fill="x", side="bottom")

    def refresh_cookie_status(self) -> None:
        status = "有 Jira cookie" if self.jira_cookie else "没有 Jira cookie：可预览，但学习/创建会失败。先用 Jira Triage 工具刷新浏览器登录。"
        self.log(status)

    def log(self, message: str) -> None:
        self.status.configure(text=message)

    def append_preview(self, message: str) -> None:
        self.preview.insert("end", message.rstrip() + "\n")
        self.preview.see("end")

    def open_rest_browser(self) -> None:
        webbrowser.open(self.jira_url.rstrip("/") + "/plugins/servlet/restbrowser#/")

    def selected_disciplines(self) -> list[str]:
        return [name for name, var in self.disc_vars.items() if var.get()]

    def batch_signature(self) -> str:
        parts = [
            self.batch_text.get("1.0", "end").strip(),
            ",".join(self.selected_disciplines()),
            self.type_var.get().strip(),
            self.prio_var.get().strip(),
            self.comp_var.get().strip(),
            self.labels_var.get().strip(),
            self.extra_json.get("1.0", "end").strip(),
        ]
        return "\n".join(parts)

    def components_for(self, disciplines: list[str]) -> list[str]:
        mapping = self.rules.get("discipline_components", DEFAULT_DISCIPLINES)
        result = []
        for discipline in disciplines:
            comp = mapping.get(discipline)
            if comp and comp not in result:
                result.append(comp)
        return result

    def default_description(self, title: str, disciplines: list[str]) -> str:
        template = self.rules.get("description_template", DEFAULT_RULES["description_template"])
        disc_text = "\n".join(f"* {item}" for item in disciplines) or "* （未指定）"
        return template.format(title=title, disciplines=disc_text)

    def extra_fields(self) -> dict[str, Any]:
        text = self.extra_json.get("1.0", "end").strip()
        if not text:
            return {}
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"额外字段 JSON 格式错误：{exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("额外字段 JSON 必须是对象，例如 {\"customfield_12345\": ...}")
        return data

    def build_payload(self, draft: DraftIssue, extra_fields: dict[str, Any] | None = None) -> dict[str, Any]:
        issue_type = draft.issue_type or self.type_var.get() or self.rules.get("default_issue_type", "Task")
        priority = draft.priority or self.prio_var.get()
        components = draft.components or self.components_for(draft.disciplines)
        labels = draft.labels or split_list(self.labels_var.get())
        description = draft.description or self.default_description(draft.title, draft.disciplines)
        fields: dict[str, Any] = {
            "project": {"key": self.rules.get("project_key", PROJECT_KEY)},
            "summary": draft.title,
            "issuetype": {"name": issue_type},
            "description": description,
        }
        if components:
            fields["components"] = [{"name": c} for c in components]
        if priority:
            fields["priority"] = {"name": priority}
        if labels:
            fields["labels"] = labels
        if extra_fields:
            fields.update(extra_fields)
        return {"fields": fields}

    def missing_required_fields(self, payload: dict[str, Any], issue_type: str) -> list[str]:
        fields = payload.get("fields", {})
        required = self.rules.get("required_fields_by_type", {}).get(issue_type, [])
        meta = self.rules.get("field_meta_by_type", {}).get(issue_type, {})
        missing = []
        for field_id in required:
            field_meta = meta.get(field_id, {})
            if field_id in STANDARD_FIELDS:
                if not is_nonempty(fields.get(field_id)):
                    missing.append(field_display_name(field_id, field_meta))
            elif field_meta.get("hasDefaultValue"):
                continue
            elif not is_nonempty(fields.get(field_id)):
                missing.append(field_display_name(field_id, field_meta))
        return missing

    def build_single_draft(self) -> DraftIssue:
        title = self.title_var.get().strip()
        if not title:
            raise ValueError("请先填写标题。")
        disciplines = self.selected_disciplines()
        components = split_list(self.comp_var.get()) or self.components_for(disciplines)
        return DraftIssue(
            title=title,
            disciplines=disciplines,
            components=components,
            issue_type=self.type_var.get(),
            priority=self.prio_var.get(),
            labels=split_list(self.labels_var.get()),
            description=self.preview.get("1.0", "end").strip() or "",
        )

    def parse_batch(self) -> list[DraftIssue]:
        text = self.batch_text.get("1.0", "end").strip()
        if not text:
            return []
        sample = text.splitlines()[0]
        delimiter = "\t" if "\t" in sample else ","
        reader = csv.reader(io.StringIO(text), delimiter=delimiter)
        rows = [row for row in reader if row and any(cell.strip() for cell in row)]
        if not rows:
            return []

        header_alias = {
            "title": "title",
            "summary": "title",
            "标题": "title",
            "jira标题": "title",
            "disciplines": "disciplines",
            "工种": "disciplines",
            "涉及工种": "disciplines",
            "components": "components",
            "component": "components",
            "priority": "priority",
            "优先级": "priority",
            "issue_type": "issue_type",
            "issuetype": "issue_type",
            "类型": "issue_type",
            "labels": "labels",
            "标签": "labels",
            "description": "description",
            "描述": "description",
        }
        first = [cell.strip().lower() for cell in rows[0]]
        has_header = any(cell in header_alias for cell in first)
        drafts: list[DraftIssue] = []

        if has_header:
            headers = [header_alias.get(cell.strip().lower(), cell.strip().lower()) for cell in rows[0]]
            for raw in rows[1:]:
                record = {headers[i]: raw[i].strip() if i < len(raw) else "" for i in range(len(headers))}
                title = record.get("title", "").strip()
                if not title:
                    continue
                drafts.append(DraftIssue(
                    title=title,
                    disciplines=split_list(record.get("disciplines", "")) or self.selected_disciplines(),
                    components=split_list(record.get("components", "")),
                    issue_type=record.get("issue_type", "").strip() or self.type_var.get(),
                    priority=record.get("priority", "").strip() or self.prio_var.get(),
                    labels=split_list(record.get("labels", "")) or split_list(self.labels_var.get()),
                    description=record.get("description", "").strip(),
                ))
        else:
            for raw in rows:
                title = raw[0].strip()
                if not title:
                    continue
                disciplines = split_list(raw[1]) if len(raw) > 1 else self.selected_disciplines()
                drafts.append(DraftIssue(
                    title=title,
                    disciplines=disciplines,
                    components=split_list(raw[2]) if len(raw) > 2 else [],
                    priority=raw[3].strip() if len(raw) > 3 else self.prio_var.get(),
                    issue_type=raw[4].strip() if len(raw) > 4 else self.type_var.get(),
                    labels=split_list(raw[5]) if len(raw) > 5 else split_list(self.labels_var.get()),
                    description=raw[6].strip() if len(raw) > 6 else "",
                ))
        return drafts

    def validate_draft(self, draft: DraftIssue, extra_fields: dict[str, Any]) -> DraftIssue:
        payload = self.build_payload(draft, extra_fields)
        issue_type = payload["fields"]["issuetype"]["name"]
        draft.issue_type = issue_type
        draft.priority = payload["fields"].get("priority", {}).get("name", "")
        draft.components = [c["name"] for c in payload["fields"].get("components", [])]
        draft.missing_required = self.missing_required_fields(payload, issue_type)
        draft.status = "OK" if not draft.missing_required else "Missing required"
        return draft

    def refresh_tree(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for index, draft in enumerate(self.drafts):
            self.tree.insert("", "end", iid=str(index), values=(
                draft.status,
                draft.title,
                draft.issue_type,
                draft.priority,
                ", ".join(draft.components),
                "; ".join(draft.missing_required),
                draft.jira_key,
            ))

    def do_learn(self) -> None:
        self.log("学习 Jira 字段中：读取 createmeta...")

        def worker() -> None:
            try:
                rules = learn_rules(self.jira_url, self.jira_cookie)
                self.after(0, lambda: self.learn_done(rules))
            except Exception as exc:  # noqa: BLE001
                self.after(0, lambda exc=exc: self.fail("学习 Jira 字段失败", exc))

        threading.Thread(target=worker, daemon=True).start()

    def learn_done(self, rules: dict[str, Any]) -> None:
        self.rules = rules
        self.type_combo.configure(values=rules.get("issue_types", []))
        self.prio_combo.configure(values=rules.get("priorities", []))
        self.log(f"学习完成：IssueType {len(rules.get('issue_types', []))} 个，Components {len(rules.get('components_available', []))} 个。")
        self.show_required_report()

    def required_report_text(self) -> str:
        lines = ["Jira 必填字段报告", f"规则文件: {RULES_PATH}", ""]
        required_by_type = self.rules.get("required_fields_by_type") or {}
        meta_by_type = self.rules.get("field_meta_by_type") or {}
        if not required_by_type:
            lines.append("还没有学习到 createmeta。请先点击“学习 Jira 必填字段”。")
            return "\n".join(lines)
        for issue_type in self.rules.get("issue_types", []):
            required = required_by_type.get(issue_type, [])
            meta = meta_by_type.get(issue_type, {})
            lines.append(f"[{issue_type}]")
            if not required:
                lines.append("  无 required 字段或当前账号未返回字段信息")
                lines.append("")
                continue
            for field_id in required:
                info = meta.get(field_id, {})
                auto = "自动填写" if field_id in STANDARD_FIELDS else ("有默认值" if info.get("hasDefaultValue") else "需要在额外字段 JSON 中补")
                lines.append(f"  - {field_display_name(field_id, info)} : {auto}")
            lines.append("")
        return "\n".join(lines)

    def show_required_report(self) -> None:
        text = self.required_report_text()
        self.preview.delete("1.0", "end")
        self.preview.insert("1.0", text)
        self.log("已显示必填字段报告。")

    def do_single_preview(self) -> None:
        try:
            extra = self.extra_fields()
            draft = self.validate_draft(self.build_single_draft(), extra)
            payload = self.build_payload(draft, extra)
        except Exception as exc:  # noqa: BLE001
            self.fail("生成预览失败", exc)
            return
        self.drafts = [draft]
        self.refresh_tree()
        self.preview.delete("1.0", "end")
        self.preview.insert("1.0", "单条 Jira 创建预览\n\n")
        self.preview.insert("end", format_payload(payload))
        if draft.missing_required:
            self.preview.insert("end", "\n\n缺失必填字段：\n- " + "\n- ".join(draft.missing_required))
        self.log("单条预览完成。")

    def do_batch_preview(self) -> None:
        try:
            signature = self.batch_signature()
            extra = self.extra_fields()
            drafts = self.parse_batch()
            if not drafts:
                messagebox.showwarning("没有批量内容", "请在批量输入框中填写至少一行标题。")
                return
            self.drafts = [self.validate_draft(draft, extra) for draft in drafts]
            self._batch_preview_signature = signature
        except Exception as exc:  # noqa: BLE001
            self.fail("解析批量失败", exc)
            return
        self.refresh_tree()
        ok = sum(1 for draft in self.drafts if not draft.missing_required)
        missing = len(self.drafts) - ok
        self.preview.delete("1.0", "end")
        self.preview.insert("1.0", f"批量 Dry Run 完成：{len(self.drafts)} 条，OK {ok} 条，缺字段 {missing} 条。\n\n")
        for index, draft in enumerate(self.drafts, start=1):
            self.preview.insert("end", f"{index}. [{draft.status}] {draft.title}\n")
            if draft.missing_required:
                self.preview.insert("end", f"   缺失: {'; '.join(draft.missing_required)}\n")
        self.log("批量 Dry Run 完成。")

    def do_create_single(self) -> None:
        if not self.allow_real_create_var.get():
            messagebox.showwarning("真实创建未开启", "请先勾选“允许真实创建”。这能防止误点写入生产 Jira。")
            return
        try:
            extra = self.extra_fields()
            draft = self.validate_draft(self.build_single_draft(), extra)
            payload = self.build_payload(draft, extra)
        except Exception as exc:  # noqa: BLE001
            self.fail("创建前校验失败", exc)
            return
        if draft.missing_required:
            messagebox.showerror("缺失必填字段", "\n".join(draft.missing_required))
            return
        if not messagebox.askyesno("确认创建 Jira", f"将创建 1 张生产 Jira：\n\n{draft.title}\n\n确认继续？"):
            self.log("已取消创建。")
            return
        self.create_payload_async(payload, draft)

    def create_payload_async(self, payload: dict[str, Any], draft: DraftIssue) -> None:
        self.log("创建 Jira 中...")

        def worker() -> None:
            try:
                code, body = jira_post(self.jira_url, "/rest/api/2/issue", payload, self.jira_cookie)
                self.after(0, lambda: self.create_done(code, body, draft))
            except Exception as exc:  # noqa: BLE001
                self.after(0, lambda exc=exc: self.fail("创建 Jira 失败", exc))

        threading.Thread(target=worker, daemon=True).start()

    def create_done(self, code: int, body: str, draft: DraftIssue) -> None:
        if code in (200, 201):
            try:
                result = json.loads(body)
                key = result.get("key", "?")
            except json.JSONDecodeError:
                key = "?"
            draft.status = "Created"
            draft.jira_key = key
            self.drafts = [draft]
            self.refresh_tree()
            url = f"{self.jira_url.rstrip('/')}/browse/{key}"
            self.log(f"创建成功：{key}")
            messagebox.showinfo("创建成功", f"已创建 {key}\n{url}")
            webbrowser.open(url)
            return
        draft.status = f"HTTP {code}"
        draft.error = body[:1000]
        self.drafts = [draft]
        self.refresh_tree()
        self.log(f"创建失败：HTTP {code}")
        messagebox.showerror("创建失败", f"HTTP {code}\n\n{body[:1000]}")

    def do_create_batch(self) -> None:
        if not self.drafts:
            self.do_batch_preview()
            if not self.drafts:
                return
        if self.batch_signature() != self._batch_preview_signature:
            self.do_batch_preview()
            messagebox.showinfo(
                "批量内容已变化",
                "批量输入或全局字段已变化，已重新 Dry Run。请检查预览后再次点击批量创建。",
            )
            return
        if not self.allow_real_create_var.get():
            messagebox.showwarning("真实创建未开启", "请先勾选“允许真实创建”。批量写入前必须显式开启。")
            return
        try:
            extra = self.extra_fields()
            self.drafts = [self.validate_draft(draft, extra) for draft in self.drafts]
        except Exception as exc:  # noqa: BLE001
            self.fail("创建前校验失败", exc)
            return
        self.refresh_tree()
        blocked = [draft for draft in self.drafts if draft.missing_required]
        if blocked:
            messagebox.showerror("批量中存在缺失必填字段", f"{len(blocked)} 条缺失必填字段。请先修正或拆分批次。")
            return
        if not messagebox.askyesno("确认批量创建", f"将顺序创建 {len(self.drafts)} 张生产 Jira。\n\n确认继续？"):
            self.log("已取消批量创建。")
            return
        drafts = list(self.drafts)
        self.log(f"批量创建中：0/{len(drafts)}")

        def worker() -> None:
            for index, draft in enumerate(drafts):
                try:
                    payload = self.build_payload(draft, extra)
                    code, body = jira_post(self.jira_url, "/rest/api/2/issue", payload, self.jira_cookie)
                except Exception as exc:  # noqa: BLE001
                    draft.status = "Error"
                    draft.error = str(exc)[:1000]
                    self.after(0, lambda idx=index: self.batch_progress_done(idx + 1, self.stop_on_error_var.get()))
                    if self.stop_on_error_var.get():
                        self.after(0, lambda: self.batch_finished())
                        return
                    continue
                if code in (200, 201):
                    try:
                        draft.jira_key = json.loads(body).get("key", "?")
                    except json.JSONDecodeError:
                        draft.jira_key = "?"
                    draft.status = "Created"
                else:
                    draft.status = f"HTTP {code}"
                    draft.error = body[:1000]
                    if self.stop_on_error_var.get():
                        self.after(0, lambda idx=index: self.batch_progress_done(idx + 1, True))
                        return
                self.after(0, lambda idx=index: self.batch_progress_done(idx + 1, False))
            self.after(0, lambda: self.batch_finished())

        threading.Thread(target=worker, daemon=True).start()

    def batch_progress_done(self, done: int, stopped: bool) -> None:
        self.refresh_tree()
        total = len(self.drafts)
        self.log(f"批量创建进度：{done}/{total}" + ("，已因错误停止" if stopped else ""))
        if stopped:
            messagebox.showerror("批量创建已停止", "遇到创建失败，已按设置停止。请查看列表中的 HTTP 状态。")

    def batch_finished(self) -> None:
        self.refresh_tree()
        created = [draft for draft in self.drafts if draft.status == "Created"]
        failed = [draft for draft in self.drafts if draft.status.startswith("HTTP") or draft.status == "Error"]
        self.preview.delete("1.0", "end")
        self.preview.insert("1.0", f"批量创建完成：成功 {len(created)}，失败 {len(failed)}。\n\n")
        for draft in self.drafts:
            self.preview.insert("end", f"[{draft.status}] {draft.jira_key or '-'} {draft.title}\n")
            if draft.error:
                self.preview.insert("end", f"  {draft.error[:300]}\n")
        self.log("批量创建完成。")
        messagebox.showinfo("批量创建完成", f"成功 {len(created)}，失败 {len(failed)}。")

    def on_tree_double_click(self, _event: tk.Event) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        draft = self.drafts[int(selection[0])]
        try:
            payload = self.build_payload(draft, self.extra_fields())
        except Exception:
            payload = {}
        self.preview.delete("1.0", "end")
        self.preview.insert("1.0", f"{draft.title}\n\n")
        if draft.jira_key:
            self.preview.insert("end", f"{self.jira_url.rstrip('/')}/browse/{draft.jira_key}\n\n")
        if draft.missing_required:
            self.preview.insert("end", "缺失必填字段：\n- " + "\n- ".join(draft.missing_required) + "\n\n")
        if draft.error:
            self.preview.insert("end", "错误：\n" + draft.error + "\n\n")
        if payload:
            self.preview.insert("end", format_payload(payload))

    def fail(self, title: str, exc: Exception) -> None:
        self.log(f"{title}: {exc}")
        messagebox.showerror(title, str(exc))


def main() -> None:
    AudioJiraCreator().mainloop()


if __name__ == "__main__":
    main()
