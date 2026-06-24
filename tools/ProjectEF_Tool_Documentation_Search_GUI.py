from __future__ import annotations

import ast
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import urllib.error
import urllib.request
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import messagebox, ttk
import tkinter as tk


ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = ROOT / "Tools"
FINAL_DIR = TOOLS_DIR / "EF_Audio_Tools_Final"
CONFIG_PATH = FINAL_DIR / "tool_paths.json"
DOC_DIR = ROOT / "Reports" / "ToolDocs"
DOC_INDEX_PATH = DOC_DIR / "tool_docs_index.json"
DOC_SETTINGS_PATH = DOC_DIR / "tool_docs_settings.json"

DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_OLLAMA_MODEL = "qwen2.5:7b-instruct"
DEFAULT_REMOTE_URL = "https://api.openai.com/v1"
DEFAULT_REMOTE_MODEL = "gpt-5-mini"

TEXT_EXTS = {".py", ".ps1", ".cmd", ".bat", ".md", ".txt", ".json", ".lua"}
MAX_SOURCE_CHARS = 240_000

BG = "#0f1722"
PANEL = "#151f2d"
PANEL_2 = "#1b2636"
CARD = "#202c3d"
INK = "#edf4ff"
MUTED = "#9fb0c6"
LINE = "#334258"
ACCENT = "#4db6ff"
GOOD = "#55d68a"
WARN = "#ffcc66"
BAD = "#ff6b6b"


@dataclass
class SourceSummary:
    path: str
    exists: bool
    size: int = 0
    modified: str = ""
    sha1: str = ""
    kind: str = ""
    docstring: str = ""
    classes: list[str] = field(default_factory=list)
    functions: list[str] = field(default_factory=list)
    cli_flags: list[str] = field(default_factory=list)
    buttons: list[str] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)
    safety_notes: list[str] = field(default_factory=list)
    text_excerpt: str = ""


@dataclass
class ToolDoc:
    menu: str
    name: str
    visible: bool
    purpose: str
    launcher: str
    source_launcher: str
    hidden_reason: str = ""
    source_files: list[SourceSummary] = field(default_factory=list)
    launch_steps: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    generated_at: str = ""
    doc_path: str = ""
    searchable_text: str = ""


def now_text() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def read_text(path: Path, limit: int = MAX_SOURCE_CHARS) -> str:
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    if len(data) > limit:
        data = data[:limit]
    for encoding in ("utf-8-sig", "utf-8", "gbk", "cp936"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def safe_slug(text: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "_", text).strip("_")
    return cleaned[:80] or "tool"


def rel(path: str | Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(ROOT))
    except Exception:
        return str(path)


def normalize_path_token(raw: str, base: Path) -> str:
    text = raw.strip().strip('"').strip("'")
    assignment = re.match(r"^[A-Za-z_][A-Za-z0-9_]*=(.+)$", text)
    if assignment:
        text = assignment.group(1).strip()
    if text.lower().startswith("%~dp0"):
        text = str(base / text[5:].lstrip("\\/"))
    text = re.sub(r"^\$PSScriptRoot[\\/]", lambda _m: str(base) + "\\", text, flags=re.I)
    text = re.sub(r"^\$\{PSScriptRoot\}[\\/]", lambda _m: str(base) + "\\", text, flags=re.I)
    return text


def resolve_path(raw: str, base: Path) -> Path:
    text = normalize_path_token(raw, base)
    if not text:
        return Path()
    expanded = os.path.expandvars(text)
    path = Path(expanded)
    if path.is_absolute():
        return path
    return (base / path).resolve()


def unique_paths(paths: list[Path]) -> list[Path]:
    output: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        if not path:
            continue
        try:
            key = str(path.resolve()).lower()
        except OSError:
            key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        output.append(path)
    return output


def extract_quoted_paths(text: str, base: Path) -> list[Path]:
    candidates: list[Path] = []
    for match in re.finditer(r'"([^"]+\.(?:py|ps1|cmd|bat|html|md|json|lua))"', text, re.I):
        token = normalize_path_token(match.group(1), base)
        if not re.match(r"^[a-z]+://", token, re.I):
            candidates.append(resolve_path(token, base))
    for match in re.finditer(r"'([^']+\.(?:py|ps1|cmd|bat|html|md|json|lua))'", text, re.I):
        token = normalize_path_token(match.group(1), base)
        if not re.match(r"^[a-z]+://", token, re.I):
            candidates.append(resolve_path(token, base))
    for match in re.finditer(r"(?<![\w.-])([A-Za-z]:\\[^\r\n\"']+\.(?:py|ps1|cmd|bat|html|md|json|lua))", text, re.I):
        candidates.append(Path(os.path.expandvars(match.group(1).strip())))
    return unique_paths(candidates)


def parse_python_summary(path: Path, text: str) -> tuple[str, list[str], list[str]]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return "", [], []
    doc = ast.get_docstring(tree) or ""
    classes: list[str] = []
    functions: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            classes.append(node.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(node.name)
    return doc, classes[:40], functions[:80]


def extract_buttons(text: str) -> list[str]:
    patterns = [
        r"QPushButton\(\s*['\"]([^'\"]+)['\"]",
        r"QToolButton\(\).*?setText\(\s*['\"]([^'\"]+)['\"]",
        r"tk\.Button\([^)]*text\s*=\s*['\"]([^'\"]+)['\"]",
        r"ttk\.Button\([^)]*text\s*=\s*['\"]([^'\"]+)['\"]",
        r"\.addItem\(\s*['\"]([^'\"]+)['\"]",
    ]
    items: list[str] = []
    for pattern in patterns:
        items.extend(re.findall(pattern, text, re.S))
    return sorted({item.strip() for item in items if item.strip()})[:80]


def extract_flags(text: str) -> list[str]:
    return sorted(set(re.findall(r"--[A-Za-z0-9][A-Za-z0-9_-]+", text)))[:80]


def extract_paths(text: str) -> list[str]:
    matches = re.findall(r"(?<![A-Za-z0-9])([A-Za-z]:[\\/][^\s\"'<>|]+)", text)
    cleaned = []
    for item in matches:
        item = item.rstrip("),.;")
        if len(item) > 3:
            cleaned.append(item)
    return sorted(set(cleaned))[:40]


def infer_safety_notes(text: str, suffix: str) -> list[str]:
    lower = text.lower()
    self_describing_classifier = "def infer_safety_notes" in lower and "safety_notes" in lower
    if self_describing_classifier:
        return [
            "仅生成 Reports\\ToolDocs 下的文档和索引。",
            "只有点击 Explain 时才调用本地或远程模型。",
        ]
    notes: list[str] = []
    if "does not modify" in lower or "read-only" in lower or "readonly" in lower:
        notes.append("标注为只读或不修改项目文件。")
    if "dry-run" in lower or "dry_run" in lower or "dryrun" in lower:
        notes.append("包含 dry-run / 预览机制。")
    if "messagebox.ask" in lower or "confirm" in lower or "confirmation" in lower or "确认" in text:
        notes.append("包含确认/提示流程。")
    if "p4 reopen" in lower:
        notes.append("会在确认后执行 p4 reopen。")
    if "p4 submit" in lower:
        notes.append("包含 p4 submit 字样，使用前需额外确认。")
    if "remove-item" in lower or "delete" in lower or ".unlink(" in lower:
        notes.append("包含删除相关逻辑，使用前检查作用范围。")
    if "waapi" in lower or "ak.wwise" in lower:
        notes.append("涉及 Wwise/WAAPI。")
    if "soundbank" in lower or "generatebank" in lower:
        notes.append("涉及 SoundBank 字样，注意项目规则。")
    if suffix in {".cmd", ".bat", ".ps1"} and "start-process" in lower:
        notes.append("会启动外部进程或 GUI。")
    return notes[:12]


def summarize_source(path: Path) -> SourceSummary:
    exists = path.exists()
    stat = path.stat() if exists else None
    text = read_text(path) if exists and path.suffix.lower() in TEXT_EXTS else ""
    sha1 = hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()[:12] if text else ""
    docstring = ""
    classes: list[str] = []
    functions: list[str] = []
    if exists and path.suffix.lower() == ".py" and text:
        docstring, classes, functions = parse_python_summary(path, text)
    excerpt = ""
    if text:
        excerpt = "\n".join(line.rstrip() for line in text.splitlines()[:80])
    return SourceSummary(
        path=str(path),
        exists=exists,
        size=stat.st_size if stat else 0,
        modified=dt.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S") if stat else "",
        sha1=sha1,
        kind=path.suffix.lower().lstrip(".") or "file",
        docstring=docstring.strip(),
        classes=classes,
        functions=functions,
        cli_flags=extract_flags(text),
        buttons=extract_buttons(text),
        paths=extract_paths(text),
        safety_notes=infer_safety_notes(text, path.suffix.lower()),
        text_excerpt=excerpt,
    )


def launcher_targets(path: Path, depth: int = 2) -> list[Path]:
    if depth <= 0 or not path.exists() or path.suffix.lower() not in TEXT_EXTS:
        return []
    text = read_text(path, 80_000)
    targets = extract_quoted_paths(text, path.parent)
    output: list[Path] = []
    for target in targets:
        output.append(target)
        if target.suffix.lower() in {".cmd", ".bat", ".ps1"}:
            output.extend(launcher_targets(target, depth - 1))
    return unique_paths(output)


def infer_related_source_files(item: dict) -> list[Path]:
    files: list[Path] = []
    launcher = FINAL_DIR / item.get("launcher", "")
    source_launcher = Path(item.get("source_launcher", ""))
    if launcher:
        files.append(launcher)
        files.extend(launcher_targets(launcher))
    if str(source_launcher):
        files.append(source_launcher)
        files.extend(launcher_targets(source_launcher))

    source_text = str(source_launcher)
    if "Documents\\Reaper" in source_text or "Documents/Reaper" in source_text:
        reaper_root = Path("C:/Users/user1/Documents/Reaper")
        files.extend(
            [
                reaper_root / "README.md",
                reaper_root / "run.ps1",
                reaper_root / "src" / "sound_finder" / "app.py",
                reaper_root / "src" / "sound_finder" / "local_llm.py",
                reaper_root / "src" / "sound_finder" / "handoff.py",
            ]
        )

    # Common source convention: Start_ProjectEF_X.cmd -> ProjectEF_X.py
    name_bits = [
        Path(str(source_launcher)).stem,
        Path(str(source_launcher)).stem.replace("Start_", ""),
        Path(str(source_launcher)).stem.replace("Start_", "").replace("_GUI", ""),
    ]
    for stem in name_bits:
        if not stem:
            continue
        for suffix in (".py", ".ps1", ".cmd", ".md"):
            candidate = TOOLS_DIR / f"{stem}{suffix}"
            if candidate.exists():
                files.append(candidate)

    return unique_paths(files)


def capability_tags(item: dict, summaries: list[SourceSummary]) -> list[str]:
    source_texts: list[str] = []
    root_text = str(ROOT)
    for summary in summaries:
        name = Path(summary.path).name.lower()
        if name == "projectef_tool_documentation_search_gui.py":
            source_texts.append(" ".join([summary.docstring, " ".join(summary.classes), " ".join(summary.functions)]))
        else:
            source_texts.append(summary.text_excerpt.replace(root_text, ""))
    text = " ".join([item.get("name", ""), item.get("purpose", "")] + source_texts).lower()
    tags: list[str] = []
    rules = [
        ("P4 / changelist", ["p4", "changelist", "reopen", "perforce"]),
        ("Wwise / WAAPI", ["wwise", "waapi", "soundbank"]),
        ("Unity integration", ["unity", "prefab", "animation", ".anim", "scene"]),
        ("Runtime log / profiler", ["runtime", "profiler", "log", "voice capture"]),
        ("Jira / requirement", ["jira", "requirement", "design doc", "triage"]),
        ("Report / dashboard", ["report", "dashboard", "html", "markdown", "summary"]),
        ("Search / indexing", ["search", "index", "fts", "finder"]),
        ("Local/remote LLM", ["ollama", "openai", "anthropic", "claude", "codex", "llm"]),
        ("Automation / scheduled task", ["scheduled", "register", "watch", "task"]),
        ("REAPER / SFX production", ["reaper", "sfx", "sound finder", "soundly"]),
    ]
    for label, needles in rules:
        if any(needle in text for needle in needles):
            tags.append(label)
    return tags or ["General tool"]


def generate_tool_doc(item: dict) -> ToolDoc:
    files = infer_related_source_files(item)
    summaries = [summarize_source(path) for path in files]
    launch_steps = [
        f"从 EF Audio Tools GUI 选择菜单 {item.get('menu')}：{item.get('name')}",
        f"直接运行最终启动器：{FINAL_DIR / item.get('launcher', '')}",
    ]
    source_launcher = item.get("source_launcher", "")
    if source_launcher:
        launch_steps.append(f"源启动器：{source_launcher}")
    doc = ToolDoc(
        menu=str(item.get("menu", "")),
        name=str(item.get("name", "")),
        visible=bool(item.get("visible", True)),
        purpose=str(item.get("purpose", "")),
        launcher=str(FINAL_DIR / item.get("launcher", "")),
        source_launcher=source_launcher,
        hidden_reason=str(item.get("hidden_reason", "")),
        source_files=summaries,
        launch_steps=launch_steps,
        capabilities=capability_tags(item, summaries),
        generated_at=now_text(),
    )
    return doc


def markdown_for_tool(doc: ToolDoc) -> str:
    lines: list[str] = []
    lines.append(f"# {doc.menu}. {doc.name}")
    lines.append("")
    lines.append(f"- Generated: {doc.generated_at}")
    lines.append(f"- Visible in GUI: {'Yes' if doc.visible else 'No'}")
    if doc.hidden_reason:
        lines.append(f"- Hidden reason: {doc.hidden_reason}")
    lines.append(f"- Purpose: {doc.purpose}")
    lines.append(f"- Capabilities: {', '.join(doc.capabilities)}")
    lines.append("")
    lines.append("## How To Use")
    for step in doc.launch_steps:
        lines.append(f"- {step}")
    lines.append("")
    lines.append("## Source Files")
    lines.append("| File | Exists | Modified | Size | SHA1 |")
    lines.append("|---|---:|---|---:|---|")
    for src in doc.source_files:
        lines.append(
            f"| `{rel(src.path)}` | {'Yes' if src.exists else 'No'} | {src.modified} | {src.size} | {src.sha1} |"
        )
    lines.append("")
    lines.append("## Code Summary")
    for src in doc.source_files:
        lines.append(f"### {rel(src.path)}")
        if not src.exists:
            lines.append("- Missing.")
            lines.append("")
            continue
        if src.docstring:
            lines.append(f"- Module docstring: {src.docstring[:500]}")
        if src.classes:
            lines.append(f"- Classes: {', '.join(src.classes[:30])}")
        if src.functions:
            lines.append(f"- Functions: {', '.join(src.functions[:50])}")
        if src.cli_flags:
            lines.append(f"- CLI flags: {', '.join(src.cli_flags[:50])}")
        if src.buttons:
            lines.append(f"- UI buttons/options: {', '.join(src.buttons[:40])}")
        if src.paths:
            lines.append(f"- Referenced paths: {', '.join(src.paths[:20])}")
        if src.safety_notes:
            lines.append(f"- Safety notes: {'; '.join(src.safety_notes)}")
        lines.append("")
    lines.append("## Search Text Excerpts")
    for src in doc.source_files:
        if src.text_excerpt:
            lines.append(f"### {rel(src.path)} excerpt")
            lines.append("```text")
            lines.append(src.text_excerpt[:5000])
            lines.append("```")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def doc_search_text(doc: ToolDoc, markdown: str) -> str:
    parts = [
        doc.menu,
        doc.name,
        doc.purpose,
        doc.hidden_reason,
        " ".join(doc.capabilities),
        doc.launcher,
        doc.source_launcher,
        markdown,
    ]
    return "\n".join(part for part in parts if part)


def build_docs() -> list[ToolDoc]:
    DOC_DIR.mkdir(parents=True, exist_ok=True)
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    docs: list[ToolDoc] = []
    for item in config.get("tools", []):
        doc = generate_tool_doc(item)
        markdown = markdown_for_tool(doc)
        doc_path = DOC_DIR / f"{int(doc.menu or 0):02d}_{safe_slug(doc.name)}.md"
        doc_path.write_text(markdown, encoding="utf-8")
        doc.doc_path = str(doc_path)
        doc.searchable_text = doc_search_text(doc, markdown)
        docs.append(doc)
    index_payload = {
        "generated_at": now_text(),
        "config": str(CONFIG_PATH),
        "doc_dir": str(DOC_DIR),
        "tools": [tool_doc_to_dict(doc) for doc in docs],
    }
    DOC_INDEX_PATH.write_text(json.dumps(index_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return docs


def tool_doc_to_dict(doc: ToolDoc) -> dict:
    payload = {
        "menu": doc.menu,
        "name": doc.name,
        "visible": doc.visible,
        "purpose": doc.purpose,
        "launcher": doc.launcher,
        "source_launcher": doc.source_launcher,
        "hidden_reason": doc.hidden_reason,
        "source_files": [source.__dict__ for source in doc.source_files],
        "launch_steps": doc.launch_steps,
        "capabilities": doc.capabilities,
        "generated_at": doc.generated_at,
        "doc_path": doc.doc_path,
        "searchable_text": doc.searchable_text,
    }
    return payload


def load_docs() -> list[dict]:
    if not DOC_INDEX_PATH.exists():
        return [tool_doc_to_dict(doc) for doc in build_docs()]
    try:
        payload = json.loads(DOC_INDEX_PATH.read_text(encoding="utf-8"))
        return list(payload.get("tools", []))
    except (OSError, json.JSONDecodeError):
        return [tool_doc_to_dict(doc) for doc in build_docs()]


def search_docs(docs: list[dict], query: str) -> list[tuple[int, dict]]:
    terms = [term.lower() for term in re.findall(r"[\w\u4e00-\u9fff.-]+", query) if term.strip()]
    if not terms:
        return [(0, doc) for doc in docs]
    results: list[tuple[int, dict]] = []
    for doc in docs:
        text = str(doc.get("searchable_text", "")).lower()
        title = str(doc.get("name", "")).lower()
        purpose = str(doc.get("purpose", "")).lower()
        score = 0
        for term in terms:
            score += text.count(term)
            if term in title:
                score += 20
            if term in purpose:
                score += 10
        if score > 0:
            results.append((score, doc))
    results.sort(key=lambda item: (-item[0], int(item[1].get("menu") or 999)))
    return results


def call_json_api(url: str, payload: dict, headers: dict[str, str], timeout: int) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body[:800]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Cannot connect {url}: {exc.reason}") from exc


def explain_with_model(
    query: str,
    docs: list[dict],
    provider: str,
    base_url: str,
    model: str,
    api_key: str,
    timeout: int,
) -> str:
    context_blocks: list[str] = []
    for doc in docs[:5]:
        context = str(doc.get("searchable_text", ""))[:5500]
        context_blocks.append(f"## {doc.get('menu')}. {doc.get('name')}\n{context}")
    prompt = (
        "你是 ProjectEF 音频工具说明助手。请只根据下面的工具文档回答用户问题，"
        "说明应该使用哪个工具、怎么启动、关键注意事项、相关文件在哪里。"
        "如果文档证据不足，请明确说不足。\n\n"
        f"用户问题：{query}\n\n"
        "相关工具文档：\n"
        + "\n\n".join(context_blocks)
    )
    messages = [
        {"role": "system", "content": "Answer in concise Chinese. Cite tool names and paths from the provided context."},
        {"role": "user", "content": prompt},
    ]
    if provider == "local":
        url = base_url.rstrip("/") + "/api/chat"
        payload = {"model": model, "stream": False, "messages": messages, "options": {"temperature": 0.2}}
        response = call_json_api(url, payload, {}, timeout)
        message = response.get("message") or {}
        return str(message.get("content") or "").strip() or "本地模型没有返回内容。"
    if provider == "remote":
        base = base_url.rstrip("/")
        if not base.endswith("/v1"):
            base += "/v1"
        url = base + "/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        payload = {"model": model, "temperature": 0.2, "messages": messages}
        response = call_json_api(url, payload, headers, timeout)
        choices = response.get("choices") or []
        if not choices:
            return "远程模型没有返回 choices。"
        return str(((choices[0] or {}).get("message") or {}).get("content") or "").strip()
    return rule_based_explanation(query, docs)


def rule_based_explanation(query: str, docs: list[dict]) -> str:
    if not docs:
        return "没有找到相关工具。请先点击 Refresh Docs 重新生成文档索引。"
    lines = [f"针对“{query}”，最相关的工具是："]
    for doc in docs[:5]:
        lines.append(f"- {doc.get('menu')}. {doc.get('name')}：{doc.get('purpose')}")
        lines.append(f"  启动器：{doc.get('launcher')}")
        if doc.get("doc_path"):
            lines.append(f"  文档：{doc.get('doc_path')}")
    lines.append("")
    lines.append("当前使用的是本地规则解释；如需模型解释，请选择 Local Ollama 或 Remote OpenAI-compatible。")
    return "\n".join(lines)


class ToolDocsGui(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("ProjectEF Tool Docs Search")
        self.geometry("1380x820")
        self.minsize(1120, 700)
        self.configure(bg=BG)
        self.docs: list[dict] = load_docs()
        self.results: list[tuple[int, dict]] = []
        self.current_doc: dict | None = None
        self.query_var = tk.StringVar()
        self.provider_var = tk.StringVar(value="off")
        self.base_url_var = tk.StringVar(value=DEFAULT_OLLAMA_URL)
        self.model_var = tk.StringVar(value=DEFAULT_OLLAMA_MODEL)
        self.api_key_var = tk.StringVar()
        self.timeout_var = tk.StringVar(value="120")
        self.status_var = tk.StringVar(value=f"Loaded {len(self.docs)} tool docs.")
        self.load_settings()
        self.build_ui()
        self.run_search()

    def load_settings(self) -> None:
        if not DOC_SETTINGS_PATH.exists():
            return
        try:
            data = json.loads(DOC_SETTINGS_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        self.provider_var.set(data.get("provider", self.provider_var.get()))
        self.base_url_var.set(data.get("base_url", self.base_url_var.get()))
        self.model_var.set(data.get("model", self.model_var.get()))
        self.timeout_var.set(str(data.get("timeout", self.timeout_var.get())))

    def save_settings(self) -> None:
        DOC_DIR.mkdir(parents=True, exist_ok=True)
        data = {
            "provider": self.provider_var.get(),
            "base_url": self.base_url_var.get(),
            "model": self.model_var.get(),
            "timeout": self.timeout_var.get(),
        }
        DOC_SETTINGS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def build_ui(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TButton", padding=(10, 6))
        style.configure("TCombobox", fieldbackground=PANEL_2, background=PANEL_2, foreground=INK)

        header = tk.Frame(self, bg=BG)
        header.pack(fill=tk.X, padx=18, pady=(14, 10))
        tk.Label(header, text="ProjectEF Tool Docs Search", bg=BG, fg=INK, font=("Segoe UI", 22, "bold")).pack(
            side=tk.LEFT
        )
        ttk.Button(header, text="Refresh Docs", command=self.refresh_docs).pack(side=tk.RIGHT, padx=(8, 0))
        ttk.Button(header, text="Open Docs Folder", command=lambda: self.open_path(DOC_DIR)).pack(side=tk.RIGHT)

        search_bar = tk.Frame(self, bg=PANEL, highlightbackground=LINE, highlightthickness=1)
        search_bar.pack(fill=tk.X, padx=18, pady=(0, 10))
        tk.Label(search_bar, text="Search", bg=PANEL, fg=MUTED, font=("Segoe UI", 10, "bold")).pack(
            side=tk.LEFT, padx=(10, 8), pady=9
        )
        entry = tk.Entry(search_bar, textvariable=self.query_var, bg=PANEL_2, fg=INK, insertbackground=INK, relief=tk.FLAT)
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=7, padx=(0, 8))
        entry.bind("<Return>", lambda _event: self.run_search())
        entry.bind("<KeyRelease>", lambda _event: self.run_search())
        ttk.Button(search_bar, text="Explain", command=self.explain_current_search).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(search_bar, text="Clear", command=self.clear_query).pack(side=tk.LEFT, padx=(0, 10))

        model_bar = tk.Frame(self, bg=BG)
        model_bar.pack(fill=tk.X, padx=18, pady=(0, 10))
        self.model_field(model_bar, "Provider", self.provider_var, width=12, combo=["off", "local", "remote"])
        self.model_field(model_bar, "Base URL", self.base_url_var, width=32)
        self.model_field(model_bar, "Model", self.model_var, width=24)
        self.model_field(model_bar, "API Key", self.api_key_var, width=24, password=True)
        self.model_field(model_bar, "Timeout", self.timeout_var, width=8)
        ttk.Button(model_bar, text="Save Model Settings", command=self.save_settings).pack(side=tk.LEFT, padx=(8, 0))

        body = tk.Frame(self, bg=BG)
        body.pack(fill=tk.BOTH, expand=True, padx=18, pady=(0, 10))

        left = tk.Frame(body, bg=PANEL, highlightbackground=LINE, highlightthickness=1)
        left.pack(side=tk.LEFT, fill=tk.Y, expand=False)
        left.configure(width=410)
        left.pack_propagate(False)
        tk.Label(left, text="Results", bg=PANEL, fg=INK, font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=12, pady=(10, 4))
        self.result_list = tk.Listbox(left, bg=PANEL_2, fg=INK, selectbackground=ACCENT, relief=tk.FLAT)
        self.result_list.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))
        self.result_list.bind("<<ListboxSelect>>", lambda _event: self.select_result())

        right = tk.PanedWindow(body, orient=tk.VERTICAL, sashwidth=6, bg=BG, bd=0)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(14, 0))
        doc_panel = tk.Frame(right, bg=PANEL, highlightbackground=LINE, highlightthickness=1)
        explain_panel = tk.Frame(right, bg=PANEL, highlightbackground=LINE, highlightthickness=1)
        right.add(doc_panel, minsize=340)
        right.add(explain_panel, minsize=180)

        doc_top = tk.Frame(doc_panel, bg=PANEL)
        doc_top.pack(fill=tk.X, padx=10, pady=(8, 4))
        tk.Label(doc_top, text="Tool Document", bg=PANEL, fg=INK, font=("Segoe UI", 12, "bold")).pack(side=tk.LEFT)
        ttk.Button(doc_top, text="Open Doc", command=self.open_current_doc).pack(side=tk.RIGHT)
        self.doc_text = tk.Text(doc_panel, bg="#101826", fg=INK, insertbackground=INK, wrap=tk.WORD, relief=tk.FLAT)
        self.doc_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        tk.Label(explain_panel, text="Model / Rule Explanation", bg=PANEL, fg=INK, font=("Segoe UI", 12, "bold")).pack(
            anchor="w", padx=10, pady=(8, 4)
        )
        self.explain_text = tk.Text(explain_panel, bg="#101826", fg=INK, insertbackground=INK, wrap=tk.WORD, relief=tk.FLAT)
        self.explain_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        footer = tk.Frame(self, bg=BG)
        footer.pack(fill=tk.X, padx=18, pady=(0, 12))
        tk.Label(footer, textvariable=self.status_var, bg=BG, fg=MUTED).pack(side=tk.LEFT)

    def model_field(
        self,
        parent: tk.Frame,
        label: str,
        var: tk.StringVar,
        width: int,
        combo: list[str] | None = None,
        password: bool = False,
    ) -> None:
        tk.Label(parent, text=label, bg=BG, fg=MUTED).pack(side=tk.LEFT, padx=(0, 4))
        if combo:
            widget = ttk.Combobox(parent, textvariable=var, width=width, values=combo, state="readonly")
        else:
            widget = tk.Entry(
                parent,
                textvariable=var,
                width=width,
                bg=PANEL_2,
                fg=INK,
                insertbackground=INK,
                relief=tk.FLAT,
                show="*" if password else "",
            )
        widget.pack(side=tk.LEFT, padx=(0, 8), ipady=4)

    def clear_query(self) -> None:
        self.query_var.set("")
        self.run_search()

    def refresh_docs(self) -> None:
        self.status_var.set("Generating docs from latest code...")
        self.disable_for_work(True)
        threading.Thread(target=self._refresh_docs_worker, daemon=True).start()

    def _refresh_docs_worker(self) -> None:
        try:
            docs = [tool_doc_to_dict(doc) for doc in build_docs()]
            self.after(0, lambda: self._refresh_docs_done(docs, None))
        except Exception as exc:
            self.after(0, lambda: self._refresh_docs_done([], exc))

    def _refresh_docs_done(self, docs: list[dict], error: Exception | None) -> None:
        self.disable_for_work(False)
        if error:
            messagebox.showerror("Refresh failed", str(error))
            self.status_var.set("Refresh failed.")
            return
        self.docs = docs
        self.status_var.set(f"Generated {len(self.docs)} tool docs into {DOC_DIR}")
        self.run_search()

    def disable_for_work(self, busy: bool) -> None:
        state = tk.DISABLED if busy else tk.NORMAL
        self.result_list.configure(state=state)

    def run_search(self) -> None:
        query = self.query_var.get().strip()
        self.results = search_docs(self.docs, query)
        self.result_list.delete(0, tk.END)
        for score, doc in self.results:
            visible = "G" if doc.get("visible") else "H"
            self.result_list.insert(tk.END, f"{doc.get('menu'):>2} [{visible}] {doc.get('name')}  ({score})")
        if self.results:
            self.result_list.selection_set(0)
            self.select_result()
        else:
            self.current_doc = None
            self.set_text(self.doc_text, "没有找到相关工具。")
        self.status_var.set(f"{len(self.results)} results / {len(self.docs)} docs")

    def select_result(self) -> None:
        selection = self.result_list.curselection()
        if not selection:
            return
        index = int(selection[0])
        if index >= len(self.results):
            return
        self.current_doc = self.results[index][1]
        doc_path = Path(str(self.current_doc.get("doc_path", "")))
        if doc_path.exists():
            content = read_text(doc_path, 500_000)
        else:
            content = self.current_doc.get("searchable_text", "")
        self.set_text(self.doc_text, content)

    def explain_current_search(self) -> None:
        query = self.query_var.get().strip() or (self.current_doc or {}).get("name", "")
        docs = [doc for _score, doc in self.results[:5]]
        if self.current_doc and self.current_doc not in docs:
            docs.insert(0, self.current_doc)
        if not docs:
            self.set_text(self.explain_text, "没有可解释的搜索结果。")
            return
        self.set_text(self.explain_text, "正在生成解释...")
        self.status_var.set("Explaining search results...")
        provider = self.provider_var.get()
        base_url = self.base_url_var.get().strip() or DEFAULT_OLLAMA_URL
        model = self.model_var.get().strip() or DEFAULT_OLLAMA_MODEL
        api_key = self.api_key_var.get().strip()
        try:
            timeout = max(5, int(float(self.timeout_var.get().strip() or "120")))
        except ValueError:
            timeout = 120
        threading.Thread(
            target=self._explain_worker,
            args=(query, docs, provider, base_url, model, api_key, timeout),
            daemon=True,
        ).start()

    def _explain_worker(
        self,
        query: str,
        docs: list[dict],
        provider: str,
        base_url: str,
        model: str,
        api_key: str,
        timeout: int,
    ) -> None:
        try:
            explanation = explain_with_model(query, docs, provider, base_url, model, api_key, timeout)
            self.after(0, lambda: self._explain_done(explanation, None))
        except Exception as exc:
            fallback = rule_based_explanation(query, docs)
            self.after(0, lambda: self._explain_done(f"模型解释失败：{exc}\n\n{fallback}", None))

    def _explain_done(self, text: str, error: Exception | None) -> None:
        if error:
            self.set_text(self.explain_text, str(error))
            self.status_var.set("Explain failed.")
            return
        self.set_text(self.explain_text, text)
        self.status_var.set("Explanation ready.")

    def open_current_doc(self) -> None:
        if not self.current_doc:
            return
        path = Path(str(self.current_doc.get("doc_path", "")))
        self.open_path(path)

    def open_path(self, path: Path) -> None:
        if not path.exists():
            messagebox.showwarning("Missing path", str(path))
            return
        try:
            os.startfile(str(path))  # type: ignore[attr-defined]
        except Exception:
            webbrowser.open(path.as_uri())

    def set_text(self, widget: tk.Text, text: str) -> None:
        widget.configure(state=tk.NORMAL)
        widget.delete("1.0", tk.END)
        widget.insert("1.0", text)
        widget.configure(state=tk.NORMAL)


def main() -> int:
    if "--generate-docs" in sys.argv:
        docs = build_docs()
        print(f"Generated {len(docs)} tool docs: {DOC_DIR}")
        return 0
    if "--search" in sys.argv:
        index = sys.argv.index("--search")
        query = sys.argv[index + 1] if index + 1 < len(sys.argv) else ""
        docs = load_docs()
        for score, doc in search_docs(docs, query)[:20]:
            print(f"{score:>4}  {doc.get('menu')}. {doc.get('name')} - {doc.get('purpose')}")
        return 0
    app = ToolDocsGui()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
