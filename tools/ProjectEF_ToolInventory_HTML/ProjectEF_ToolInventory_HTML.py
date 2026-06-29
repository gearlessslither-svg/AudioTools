#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import ast
import datetime as dt
import html
import json
import os
import re
import subprocess
import sys
import threading
import urllib.parse
import webbrowser
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


APP_DIR = Path(__file__).resolve().parent
TOOLS_DIR = APP_DIR.parent
ROOT = TOOLS_DIR.parent
FINAL_MENU_CONFIG = TOOLS_DIR / "EF_Audio_Tools_Final" / "tool_paths.json"
REPORT_DIR = ROOT / "Reports" / "ToolInventory"
SNAPSHOT_JSON = REPORT_DIR / "projectef_tool_inventory_latest.json"
SNAPSHOT_HTML = REPORT_DIR / "projectef_tool_inventory_latest.html"

DEFAULT_P4_TARGETS = [
    {
        "label": "ProjectEF_Trunk",
        "port": "ef.p4.blackjack-local.com:1666",
        "client": "yupeng_ADMIN-V9BNJMS5N",
    },
    {
        "label": "Command-line default",
        "port": "",
        "client": os.environ.get("P4CLIENT", ""),
    },
]
TEXT_EXTS = {".py", ".cmd", ".bat", ".ps1", ".md", ".json", ".txt", ".cs", ".asset", ".meta"}
LOCAL_CODE_EXTS = {".py", ".cmd", ".bat", ".ps1", ".md", ".json"}
UNITY_CODE_EXTS = {".cs", ".asmdef", ".asset", ".meta"}
MAX_TEXT = 180_000


@dataclass
class FileInfo:
    path: str
    kind: str
    role: str
    submit_rule: str
    exists: bool = True
    size: int = 0
    modified: str = ""
    summary: str = ""
    evidence: list[str] = field(default_factory=list)


@dataclass
class ToolInfo:
    name: str
    purpose: str
    category: str
    visible: bool
    launcher: str
    files: list[FileInfo] = field(default_factory=list)
    source: str = ""


def now_iso() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def read_text(path: Path, limit: int = MAX_TEXT) -> str:
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    if len(data) > limit:
        data = data[:limit]
    for enc in ("utf-8-sig", "utf-8", "gbk", "cp936", "latin1"):
        try:
            return data.decode(enc, errors="replace")
        except Exception:
            continue
    return data.decode(errors="replace")


def path_str(path: Path | str) -> str:
    return str(path).replace("/", "\\")


def file_mtime(path: Path) -> str:
    try:
        return dt.datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    except OSError:
        return ""


def file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def normalize_path(raw: str, base: Path | None = None) -> Path:
    text = raw.strip().strip('"')
    text = text.replace("%~dp0", str(TOOLS_DIR) + os.sep)
    text = os.path.expandvars(text)
    p = Path(text)
    if not p.is_absolute() and base is not None:
        p = base / p
    return p


def classify_local_file(path: Path) -> tuple[str, str, str]:
    lower = path_str(path).lower()
    suffix = path.suffix.lower()

    if suffix in {".cmd", ".bat", ".ps1"}:
        return (
            "local_launcher",
            "本地启动器",
            "本地工具入口，不需要随 Unity prefab 上传；团队共享时走工具目录/Git。",
        )
    if suffix == ".py":
        return (
            "local_python",
            "本地工具主程序/辅助脚本",
            "本地运行工具，不需要上传 Unity 工程；如果团队也要使用，提交到工具仓库或共享工具目录。",
        )
    if suffix == ".md":
        return (
            "local_doc",
            "工具说明文档",
            "本地说明文件，不随 prefab 提交；需要团队说明时可放工具仓库。",
        )
    if suffix == ".json":
        return (
            "local_data",
            "工具配置/缓存/索引",
            "本地配置或缓存，先看用途；缓存和大索引通常不提交，规则配置可随工具共享。",
        )
    if "/assets/audiotools/" in lower and "/editor/" in lower and suffix == ".cs":
        return (
            "unity_editor_script",
            "Unity Editor 工具脚本",
            "如果希望团队在 Unity 内使用这个工具，脚本和 .meta 必须进 Unity/P4。",
        )
    if "/assets/" in lower and suffix == ".cs" and "/editor/" not in lower:
        return (
            "unity_runtime_script",
            "Unity 运行时脚本/组件",
            "如果 prefab/object 挂载或代码引用它，必须和 prefab/object 以及 .meta 一起提交。",
        )
    if suffix == ".meta":
        return (
            "unity_meta",
            "Unity meta 配对文件",
            "跟随同名资产一起提交，避免 GUID 丢失。",
        )
    if suffix == ".asset" and "/assets/audiotools/" in lower:
        return (
            "unity_tool_data",
            "Unity 工具数据资产",
            "如果这是团队共享配置/映射数据，需要随 Unity 工程提交；纯本地实验数据不要提交。",
        )
    return (
        "file",
        "相关文件",
        "按所属工具和项目策略判断；不确定时先保留在 Review。",
    )


def py_summary(path: Path) -> tuple[str, list[str]]:
    text = read_text(path)
    evidence: list[str] = []
    summary = ""
    try:
        tree = ast.parse(text)
        doc = ast.get_docstring(tree)
        if doc:
            summary = " ".join(doc.strip().split())[:260]
        classes = [n.name for n in tree.body if isinstance(n, ast.ClassDef)]
        funcs = [n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        if classes:
            evidence.append("classes: " + ", ".join(classes[:8]))
        if funcs:
            evidence.append("functions: " + ", ".join(funcs[:10]))
    except Exception:
        first_comment = next((line.strip("# ").strip() for line in text.splitlines() if line.strip().startswith("#")), "")
        if first_comment:
            summary = first_comment[:260]
    flags = sorted(set(re.findall(r"--[A-Za-z0-9][A-Za-z0-9_-]+", text)))
    if flags:
        evidence.append("cli: " + ", ".join(flags[:12]))
    return summary, evidence


def cmd_references(path: Path) -> list[Path]:
    text = read_text(path)
    refs: list[Path] = []
    for m in re.finditer(r'set\s+"SCRIPT=([^"]+)"', text, flags=re.IGNORECASE):
        refs.append(normalize_path(m.group(1), path.parent))
    for m in re.finditer(r'(?:python|py)\s+(?:-B\s+)?(?:"([^"]+\.py)"|([^\s"]+\.py))', text, flags=re.IGNORECASE):
        raw = m.group(1) or m.group(2)
        if raw:
            refs.append(normalize_path(raw, path.parent))
    for m in re.finditer(r'(?:powershell|pwsh).*?(?:"([^"]+\.ps1)"|([^\s"]+\.ps1))', text, flags=re.IGNORECASE):
        raw = m.group(1) or m.group(2)
        if raw:
            refs.append(normalize_path(raw, path.parent))
    return unique_paths(refs)


def py_local_imports(path: Path) -> list[Path]:
    text = read_text(path)
    refs: list[Path] = []
    try:
        tree = ast.parse(text)
    except Exception:
        return []
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name.split(".")[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names = [node.module.split(".")[0]]
        for name in names:
            candidate = path.parent / f"{name}.py"
            if candidate.exists() and candidate != path:
                refs.append(candidate)
            candidate2 = TOOLS_DIR / f"{name}.py"
            if candidate2.exists() and candidate2 != path:
                refs.append(candidate2)
    return unique_paths(refs)


def unique_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    out: list[Path] = []
    for p in paths:
        try:
            key = str(p.resolve()).lower()
        except OSError:
            key = str(p).lower()
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def make_file_info(path: Path, role_override: str = "") -> FileInfo:
    kind, role, submit_rule = classify_local_file(path)
    if role_override:
        role = role_override
    exists = path.exists()
    summary = ""
    evidence: list[str] = []
    if exists and path.suffix.lower() == ".py":
        summary, evidence = py_summary(path)
    elif exists and path.suffix.lower() in {".cmd", ".bat", ".ps1"}:
        refs = cmd_references(path)
        if refs:
            evidence.append("launches: " + ", ".join(p.name for p in refs[:5]))
    return FileInfo(
        path=path_str(path),
        kind=kind,
        role=role,
        submit_rule=submit_rule,
        exists=exists,
        size=file_size(path) if exists else 0,
        modified=file_mtime(path) if exists else "",
        summary=summary,
        evidence=evidence,
    )


def tool_name_from_launcher(path: Path) -> str:
    name = path.stem
    name = re.sub(r"^Start_", "", name, flags=re.IGNORECASE)
    name = re.sub(r"[_-]+", " ", name).strip()
    return name or path.name


def load_menu_tools() -> list[dict[str, Any]]:
    if not FINAL_MENU_CONFIG.exists():
        return []
    try:
        data = json.loads(FINAL_MENU_CONFIG.read_text(encoding="utf-8"))
    except Exception:
        return []
    return list(data.get("tools") or [])


def build_tool_from_launcher(name: str, purpose: str, launcher: Path, visible: bool, source: str) -> ToolInfo:
    files: list[FileInfo] = []
    files.append(make_file_info(launcher, "启动器"))
    refs = cmd_references(launcher) if launcher.exists() and launcher.suffix.lower() in {".cmd", ".bat"} else []
    for ref in refs:
        files.append(make_file_info(ref, "主程序" if ref.suffix.lower() == ".py" else "启动引用"))
        if ref.exists() and ref.suffix.lower() == ".py":
            for dep in py_local_imports(ref):
                files.append(make_file_info(dep, "本地依赖模块"))
    return ToolInfo(
        name=name,
        purpose=purpose,
        category="Visible tool" if visible else "Hidden/helper tool",
        visible=visible,
        launcher=path_str(launcher),
        files=dedupe_file_infos(files),
        source=source,
    )


def dedupe_file_infos(files: list[FileInfo]) -> list[FileInfo]:
    seen: set[str] = set()
    out: list[FileInfo] = []
    for f in files:
        key = f.path.lower()
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out


def scan_local_tools() -> list[ToolInfo]:
    tools: list[ToolInfo] = []
    menu_items = load_menu_tools()
    known_launchers: set[str] = set()

    for item in menu_items:
        source_launcher = str(item.get("source_launcher") or "")
        launcher_path = normalize_path(source_launcher, TOOLS_DIR)
        if not launcher_path.exists():
            launcher_path = normalize_path(str(item.get("launcher") or ""), TOOLS_DIR / "EF_Audio_Tools_Final")
        known_launchers.add(path_str(launcher_path).lower())
        tools.append(
            build_tool_from_launcher(
                name=str(item.get("name") or tool_name_from_launcher(launcher_path)),
                purpose=str(item.get("purpose") or ""),
                launcher=launcher_path,
                visible=bool(item.get("visible", True)),
                source="EF_Audio_Tools_Final/tool_paths.json",
            )
        )

    for launcher in sorted(TOOLS_DIR.glob("Start_*.cmd")):
        if path_str(launcher).lower() in known_launchers:
            continue
        tools.append(
            build_tool_from_launcher(
                name=tool_name_from_launcher(launcher),
                purpose="未进入最终菜单的本地启动器，保留为辅助/实验工具。",
                launcher=launcher,
                visible=False,
                source="Tools/Start_*.cmd discovery",
            )
        )

    assigned = {f.path.lower() for t in tools for f in t.files}
    for script in sorted(TOOLS_DIR.glob("ProjectEF_*.py")):
        if path_str(script).lower() in assigned:
            continue
        tools.append(
            ToolInfo(
                name=script.stem,
                purpose="未绑定启动器的本地 Python 工具/模块。",
                category="Unlisted script",
                visible=False,
                launcher="",
                files=[make_file_info(script, "本地脚本")],
                source="Tools/*.py discovery",
            )
        )
    return tools


def run_p4(args: list[str], timeout: int = 20, port: str = "") -> str:
    try:
        cmd = ["p4"]
        if port:
            cmd += ["-p", port]
        cmd += args
        cp = subprocess.run(cmd, capture_output=True, timeout=timeout)
    except Exception as exc:
        return f"ERROR: {exc}"
    raw = cp.stdout + cp.stderr
    for enc in ("utf-8", "cp936", "gbk", "latin1"):
        try:
            return raw.decode(enc, errors="replace")
        except Exception:
            continue
    return raw.decode(errors="replace")


def parse_opened_line(line: str, client: str) -> dict[str, str] | None:
    m = re.match(r"^(//.+?)#(\d+)\s+-\s+(\S+)\s+(.+?)\s+\(([^)]+)\)", line.strip())
    if not m:
        return None
    depot, rev, action, change, filetype = m.groups()
    return {
        "client": client,
        "depot": depot,
        "rev": rev,
        "action": action,
        "change": change,
        "filetype": filetype,
    }


def classify_p4_file(depot: str) -> tuple[str, str, str]:
    low = depot.lower()
    if low.endswith(".meta"):
        asset_low = low[:-5]
        if asset_low.endswith("/assets/audiotools"):
            return ("unity_meta", "AudioTools 工具目录 meta。", "跟随 AudioTools 工具目录一起提交。")
        if any(token in asset_low for token in [
            "projectefaudioresourcethumbnailexporter.cs",
            "runtimeuiprefabclicktracer.cs",
            "projectefaudioruntimesmoke.cs",
            "findselectedprefabsource.cs",
            "timelineprefabpreviewwindow.cs",
            "animationwwiseeventreceiver.cs",
        ]):
            return ("unity_meta", "Unity 工具/运行时脚本 meta 配对文件。", "必须跟随对应 .cs 一起提交，避免 GUID 丢失。")
        if "/assets/gameproject/scripts/editor/audioidentityoverlay" in asset_low:
            return ("unity_meta", "Audio Identity Overlay 工具 meta 配对文件。", "跟随 AudioIdentityOverlay 工具脚本/数据一起提交。")
    if "/packages/com.unity." in low or "/packages/com.coffee." in low:
        return ("exclude", "第三方 Unity package，不是我们写的工具。", "不要放入工具 CL。")
    if "/assets/audiotools/" in low and "/editor/data/" in low:
        return ("tool_data", "Unity 音频工具数据资产，例如动画/SkillAudio 配置保存数据。", "如果这次要共享工具配置，需要放工具 CL；否则 Review。")
    if "/assets/audiotools/" in low and low.endswith(".cs"):
        return ("unity_editor_tool", "Unity AudioTools 目录下的工具脚本。", "团队要使用就必须提交，和 .meta 配对。")
    if "/assets/audiotools/" in low:
        return ("unity_tool_asset", "Unity AudioTools 目录下的工具资源。", "按工具共享需求提交，和 .meta 配对。")
    if "findselectedprefabsource.cs" in low:
        return ("unity_editor_tool", "Unity Editor 辅助工具，用于定位当前选中 prefab/资源来源。", "本身是 Editor 工具；团队要使用就提交，和 .meta 配对。")
    if "projectefaudioruntimesmoke.cs" in low:
        return ("unity_editor_tool", "ProjectEF 音频运行时 Smoke Test Editor 工具。", "本身是 Editor 工具；团队要使用就提交，和 .meta 配对。")
    if "timelineprefabpreviewwindow.cs" in low:
        return ("unity_editor_tool", "Timeline/Prefab 预览 Editor 工具窗口。", "本身是 Editor 工具；团队要使用就提交，和 .meta 配对。")
    if "/assets/gameproject/scripts/editor/audioidentityoverlay.meta" in low:
        return ("unity_meta", "Audio Identity Overlay 工具文件夹 meta。", "跟随 AudioIdentityOverlay 工具脚本/数据一起提交，避免 GUID/目录资产状态丢失。")
    if "/assets/gameproject/scripts/editor/audioidentityoverlay/" in low:
        return ("unity_editor_tool", "Audio Identity Overlay Editor 工具或本地映射数据。", "Overlay 脚本和 .meta 要随工具提交；纯本地生成的 map 需要 Review。")
    if "animationwwiseeventreceiver" in low and low.endswith(".cs"):
        return ("runtime_receiver", "Animation/Wwise runtime receiver 脚本。", "如果 prefab/object 挂载它，必须和 prefab 一起提交。")
    if "/assets/editor/wwise/" in low:
        return ("wwise_project_data", "Wwise Unity 集成 ProjectData。", "音频资源引用候选，不是我们写的工具脚本，单独 Review。")
    if "/wwisescriptobject/" in low:
        return ("wwise_reference_data", "Wwise ScriptObject 资源引用数据。", "音频资源引用候选，不是工具脚本，跟随音频实现任务 Review。")
    if low.endswith((".py", ".cmd", ".ps1")) and "/tools/" in low:
        return ("local_tool", "工具脚本/启动器。", "可放工具 CL。")
    return ("other", "非工具或无法确认。", "不要自动放入工具 CL。")


def scan_p4_opened() -> dict[str, Any]:
    clients: list[dict[str, Any]] = []
    tool_candidates: list[dict[str, str]] = []
    all_count = 0
    seen_targets: set[tuple[str, str]] = set()
    for target in DEFAULT_P4_TARGETS:
        client = str(target.get("client") or "").strip()
        port = str(target.get("port") or "").strip()
        label = str(target.get("label") or client or port or "P4")
        if not client:
            continue
        key = (port, client)
        if key in seen_targets:
            continue
        seen_targets.add(key)
        out = run_p4(["-c", client, "opened"], timeout=30, port=port)
        entries = []
        for line in out.splitlines():
            parsed = parse_opened_line(line, client)
            if not parsed:
                continue
            parsed["port"] = port
            parsed["label"] = label
            all_count += 1
            bucket, reason, submit_rule = classify_p4_file(parsed["depot"])
            parsed.update({"bucket": bucket, "reason": reason, "submit_rule": submit_rule})
            entries.append(parsed)
            if bucket not in {"exclude", "other"}:
                tool_candidates.append(parsed)
        clients.append({"label": label, "port": port, "client": client, "raw_error": "" if entries else out.strip()[:500], "opened_count": len(entries)})
    return {
        "clients": clients,
        "opened_count": all_count,
        "tool_candidates": tool_candidates,
    }


def build_inventory() -> dict[str, Any]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    tools = scan_local_tools()
    p4 = scan_p4_opened()
    payload = {
        "generated_at": now_iso(),
        "root": path_str(ROOT),
        "tools_dir": path_str(TOOLS_DIR),
        "tool_count": len(tools),
        "visible_tool_count": sum(1 for t in tools if t.visible),
        "file_count": sum(len(t.files) for t in tools),
        "tools": [tool_to_dict(t) for t in tools],
        "p4": p4,
    }
    SNAPSHOT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    SNAPSHOT_HTML.write_text(render_html(payload), encoding="utf-8")
    return payload


def tool_to_dict(t: ToolInfo) -> dict[str, Any]:
    return {
        "name": t.name,
        "purpose": t.purpose,
        "category": t.category,
        "visible": t.visible,
        "launcher": t.launcher,
        "source": t.source,
        "files": [f.__dict__ for f in t.files],
    }


def h(text: Any) -> str:
    return html.escape(str(text or ""), quote=True)


def render_html(payload: dict[str, Any]) -> str:
    data_json = json.dumps(payload, ensure_ascii=False)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ProjectEF 工具文件清单</title>
  <style>
    :root {{
      color-scheme: dark;
      --bg:#0e1420; --panel:#151f2d; --panel2:#1d2a3a; --line:#314156;
      --ink:#edf4ff; --muted:#a9b8cc; --accent:#54c7a7; --warn:#f6c85f; --bad:#ff7474; --blue:#6db6ff;
    }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; font-family: "Segoe UI", "Microsoft YaHei", Arial, sans-serif; background:var(--bg); color:var(--ink); }}
    header {{ position:sticky; top:0; z-index:5; background:#101827; border-bottom:1px solid var(--line); padding:14px 18px; display:flex; gap:12px; align-items:center; flex-wrap:wrap; }}
    h1 {{ margin:0; font-size:20px; font-weight:700; }}
    button, input, select {{ border:1px solid var(--line); background:var(--panel2); color:var(--ink); border-radius:6px; padding:8px 10px; }}
    button {{ cursor:pointer; background:var(--accent); color:#061318; border:0; font-weight:700; }}
    button.secondary {{ background:var(--panel2); color:var(--ink); border:1px solid var(--line); }}
    main {{ padding:18px; max-width:1800px; margin:0 auto; }}
    .stats {{ display:grid; grid-template-columns: repeat(5, minmax(140px,1fr)); gap:10px; margin-bottom:14px; }}
    .stat {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:12px; }}
    .stat b {{ display:block; font-size:22px; margin-top:4px; }}
    .bar {{ display:flex; gap:10px; align-items:center; margin:12px 0 16px; flex-wrap:wrap; }}
    .bar input {{ min-width:340px; flex:1; }}
    .section {{ margin-top:18px; }}
    .section h2 {{ font-size:17px; margin:0 0 10px; }}
    details.tool {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; margin:10px 0; overflow:hidden; }}
    details.tool summary {{ cursor:pointer; list-style:none; padding:12px 14px; display:grid; grid-template-columns: 32px minmax(220px, 1.2fr) minmax(320px,2fr) minmax(120px,.4fr); gap:10px; align-items:center; }}
    details.tool summary::-webkit-details-marker {{ display:none; }}
    .badge {{ display:inline-flex; align-items:center; justify-content:center; height:22px; min-width:22px; padding:0 7px; border-radius:999px; background:#2b3b4f; color:var(--muted); font-size:12px; }}
    .badge.good {{ background:#124033; color:#8af0ce; }}
    .badge.warn {{ background:#4a3512; color:#ffd77e; }}
    .purpose {{ color:var(--muted); line-height:1.35; }}
    .files {{ width:100%; border-collapse:collapse; }}
    .files th, .files td {{ border-top:1px solid var(--line); padding:9px 10px; vertical-align:top; font-size:13px; }}
    .files th {{ color:var(--muted); text-align:left; background:#111b2a; position:sticky; top:58px; }}
    code {{ color:#bde5ff; word-break:break-all; }}
    .rule {{ color:#f5db99; }}
    .muted {{ color:var(--muted); }}
    .missing {{ color:var(--bad); }}
    .p4table {{ width:100%; border-collapse:collapse; background:var(--panel); border:1px solid var(--line); border-radius:8px; overflow:hidden; }}
    .p4table th, .p4table td {{ border-top:1px solid var(--line); padding:9px 10px; text-align:left; vertical-align:top; font-size:13px; }}
    .p4table th {{ background:#111b2a; color:var(--muted); }}
    @media (max-width: 900px) {{
      .stats {{ grid-template-columns:1fr 1fr; }}
      details.tool summary {{ grid-template-columns: 28px 1fr; }}
      details.tool summary .purpose, details.tool summary .meta {{ grid-column: 2 / -1; }}
      .bar input {{ min-width:100%; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>ProjectEF 工具文件清单</h1>
    <button onclick="refreshInventory()">刷新</button>
    <button class="secondary" onclick="expandAll(true)">全部展开</button>
    <button class="secondary" onclick="expandAll(false)">全部收起</button>
    <span class="muted" id="status"></span>
  </header>
  <main>
    <div class="stats" id="stats"></div>
    <div class="bar">
      <input id="search" placeholder="搜索工具名 / 文件名 / 作用 / 提交规则" oninput="render()">
      <select id="filter" onchange="render()">
        <option value="all">全部工具</option>
        <option value="visible">最终菜单可见</option>
        <option value="hidden">隐藏/辅助工具</option>
        <option value="unity">Unity/P4 相关文件</option>
        <option value="local">本地工具文件</option>
      </select>
    </div>
    <section class="section">
      <h2>工具和文件对应</h2>
      <div id="tools"></div>
    </section>
    <section class="section">
      <h2>P4 opened 中的工具相关候选</h2>
      <div id="p4"></div>
    </section>
  </main>
  <script>
    let inventory = {data_json};
    const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
    function stat(label, value) {{ return `<div class="stat"><span class="muted">${{esc(label)}}</span><b>${{esc(value)}}</b></div>`; }}
    function textBlob(tool) {{
      return [tool.name, tool.purpose, tool.category, tool.launcher, ...(tool.files||[]).flatMap(f => [f.path, f.role, f.submit_rule, f.summary, ...(f.evidence||[])])].join(' ').toLowerCase();
    }}
    function fileRow(f) {{
      const missing = f.exists ? '' : ' missing';
      const evidence = (f.evidence||[]).map(e => `<div class="muted">${{esc(e)}}</div>`).join('');
      return `<tr>
        <td><code class="${{missing}}">${{esc(f.path)}}</code>${{f.exists ? '' : '<div class="missing">文件不存在</div>'}}</td>
        <td>${{esc(f.role)}}<div class="muted">${{esc(f.kind)}}</div></td>
        <td>${{esc(f.summary)}}${{evidence}}</td>
        <td class="rule">${{esc(f.submit_rule)}}</td>
        <td class="muted">${{esc(f.modified)}}<br>${{f.size ? esc(f.size) + ' bytes' : ''}}</td>
      </tr>`;
    }}
    function renderTools() {{
      const q = document.getElementById('search').value.trim().toLowerCase();
      const filter = document.getElementById('filter').value;
      const tools = (inventory.tools||[]).filter(t => {{
        if (q && !textBlob(t).includes(q)) return false;
        if (filter === 'visible' && !t.visible) return false;
        if (filter === 'hidden' && t.visible) return false;
        if (filter === 'unity' && !(t.files||[]).some(f => (f.kind||'').startsWith('unity'))) return false;
        if (filter === 'local' && !(t.files||[]).some(f => (f.kind||'').startsWith('local'))) return false;
        return true;
      }});
      document.getElementById('tools').innerHTML = tools.map((t, i) => `
        <details class="tool">
          <summary>
            <span class="badge ${{t.visible ? 'good' : 'warn'}}">${{t.visible ? '用' : '辅'}}</span>
            <strong>${{esc(t.name)}}</strong>
            <span class="purpose">${{esc(t.purpose || t.category)}}</span>
            <span class="meta muted">${{(t.files||[]).length}} files</span>
          </summary>
          <table class="files">
            <thead><tr><th>文件</th><th>作用</th><th>识别依据</th><th>提交/上传规则</th><th>修改时间</th></tr></thead>
            <tbody>${{(t.files||[]).map(fileRow).join('')}}</tbody>
          </table>
        </details>`).join('') || '<p class="muted">没有匹配项。</p>';
    }}
    function renderP4() {{
      const rows = (inventory.p4 && inventory.p4.tool_candidates) || [];
      if (!rows.length) {{
        document.getElementById('p4').innerHTML = '<p class="muted">当前 P4 opened 中没有命中强相关工具候选。</p>';
        return;
      }}
      document.getElementById('p4').innerHTML = `<table class="p4table">
        <thead><tr><th>Client</th><th>Depot 文件</th><th>动作</th><th>分类</th><th>建议</th></tr></thead>
        <tbody>${{rows.map(r => `<tr>
          <td>${{esc(r.client)}}</td><td><code>${{esc(r.depot)}}</code></td><td>${{esc(r.action)}} ${{esc(r.change)}}</td>
          <td>${{esc(r.reason)}}</td><td class="rule">${{esc(r.submit_rule)}}</td>
        </tr>`).join('')}}</tbody>
      </table>`;
    }}
    function render() {{
      document.getElementById('stats').innerHTML = [
        stat('生成时间', inventory.generated_at),
        stat('工具数', inventory.tool_count),
        stat('可见工具', inventory.visible_tool_count),
        stat('文件映射', inventory.file_count),
        stat('P4工具候选', ((inventory.p4||{{}}).tool_candidates||[]).length)
      ].join('');
      document.getElementById('status').textContent = `数据源: ${{inventory.tools_dir}}`;
      renderTools();
      renderP4();
    }}
    async function refreshInventory() {{
      const status = document.getElementById('status');
      status.textContent = '正在刷新...';
      try {{
        const res = await fetch('/api/refresh', {{method:'POST'}});
        if (!res.ok) throw new Error(await res.text());
        inventory = await res.json();
        render();
        status.textContent = `刷新完成: ${{inventory.generated_at}}`;
      }} catch (err) {{
        status.textContent = '刷新失败: ' + err;
      }}
    }}
    function expandAll(open) {{ document.querySelectorAll('details.tool').forEach(d => d.open = open); }}
    render();
  </script>
</body>
</html>"""


class AppHandler(BaseHTTPRequestHandler):
    server_version = "ProjectEFToolInventory/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in {"/", "/index.html"}:
            payload = build_inventory()
            self._send(200, render_html(payload).encode("utf-8"), "text/html; charset=utf-8")
            return
        if parsed.path == "/api/inventory":
            payload = build_inventory()
            self._send(200, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
            return
        self._send(404, b"Not found", "text/plain; charset=utf-8")

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/refresh":
            payload = build_inventory()
            self._send(200, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
            return
        self._send(404, b"Not found", "text/plain; charset=utf-8")


def serve(host: str, port: int, open_browser: bool) -> None:
    payload = build_inventory()
    url = f"http://{host}:{port}/"
    print(f"ProjectEF Tool Inventory: {url}")
    print(f"Snapshot HTML: {SNAPSHOT_HTML}")
    print(f"Tools: {payload['tool_count']}, mapped files: {payload['file_count']}, P4 candidates: {len(payload['p4']['tool_candidates'])}")
    httpd = ThreadingHTTPServer((host, port), AppHandler)
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ProjectEF audio tool inventory HTML server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--once", action="store_true", help="Generate snapshot and exit")
    parser.add_argument("--no-open", action="store_true", help="Do not open browser")
    args = parser.parse_args(argv)
    if args.once:
        payload = build_inventory()
        print(json.dumps({
            "html": path_str(SNAPSHOT_HTML),
            "json": path_str(SNAPSHOT_JSON),
            "tool_count": payload["tool_count"],
            "file_count": payload["file_count"],
            "p4_tool_candidates": len(payload["p4"]["tool_candidates"]),
        }, ensure_ascii=False, indent=2))
        return 0
    serve(args.host, args.port, not args.no_open)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
