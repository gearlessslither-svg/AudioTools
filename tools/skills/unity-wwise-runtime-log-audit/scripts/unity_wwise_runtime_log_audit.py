#!/usr/bin/env python3
import argparse
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime
from pathlib import Path


AUDIO_RE = re.compile(
    r"(wwise|audiokinetic|aksoundengine|akinitializer|akbank|akevent|akunity|ak\.wwise|"
    r"soundbank|generatedsoundbanks|postevent|loadbank|unloadbank|rtpc|setswitch|setstate|"
    r"\.bnk\b|\.wem\b|audio\s+plugin|audio\s+engine|ak_|ak::)",
    re.IGNORECASE,
)

SEVERITY_RE = re.compile(
    r"(error|exception|failed|fail\b|fatal|cannot|can't|could not|invalid|missing|not found|"
    r"denied|unauthorized|nullreference|argumentexception|indexoutofrange|idnotfound|filenotfound|"
    r"失败|错误|异常|无法|不能|未找到|找不到|缺失|退出播放)",
    re.IGNORECASE,
)

WARNING_RE = re.compile(
    r"(warning|warn\b|deprecated|duplicate|not loaded|timeout|underrun|starvation|too many|overflow)",
    re.IGNORECASE,
)

EVENT_RE = re.compile(r"\b(?:Play|Stop|Pause|Resume|Set|Reset|Mute|Unmute|Stinger|Music|VO|UI|SFX|Amb|Loop)_[A-Za-z0-9_]+\b")

CATEGORY_RULES = [
    ("License", re.compile(r"(license|no license key|trial)", re.IGNORECASE)),
    ("InitOrPlugin", re.compile(r"(initialize|initializer|init\b|plugin|dll|version mismatch|akunitysoundengine)", re.IGNORECASE)),
    ("BankOrMedia", re.compile(r"(bank|soundbank|loadbank|unloadbank|\.bnk\b|\.wem\b|media|file not found|bankread|加载event|加载.*bank)", re.IGNORECASE)),
    ("Event", re.compile(r"(postevent|event id|event not found|idnotfound|akevent|executeactiononevent)", re.IGNORECASE)),
    ("RTPCSwitchState", re.compile(r"(rtpc|switch|state|setrtpc|setswitch|setstate|game parameter)", re.IGNORECASE)),
    ("UnityException", re.compile(r"(exception|nullreference|argumentexception|stack trace|missingreference)", re.IGNORECASE)),
    ("BuildOrPackaging", re.compile(r"(build|package|streamingassets|generatedsoundbanks|deploy|copying)", re.IGNORECASE)),
    ("Performance", re.compile(r"(underrun|starvation|voice|memory|cpu|latency|overflow|too many)", re.IGNORECASE)),
]


def read_text(path: Path, max_bytes: int) -> str | None:
    try:
        if path.stat().st_size > max_bytes:
            return None
        return path.read_text(encoding="utf-8-sig", errors="replace")
    except Exception:
        return None


def parse_project_settings(unity_root: Path):
    settings = unity_root / "ProjectSettings" / "ProjectSettings.asset"
    text = read_text(settings, 2 * 1024 * 1024)
    if not text:
        return {}
    result = {}
    for key in ("companyName", "productName"):
        match = re.search(rf"^\s*{key}:\s*(.+?)\s*$", text, re.MULTILINE)
        if match:
            result[key] = match.group(1).strip().strip('"')
    return result


def discover_logs(unity_root: Path | None, explicit_logs: list[str], explicit_roots: list[str], max_bytes: int):
    candidates: list[Path] = []

    for item in explicit_logs:
        p = Path(item)
        if p.is_file():
            candidates.append(p)
        elif p.is_dir():
            candidates.extend(find_logs_in_dir(p, max_bytes))

    for item in explicit_roots:
        p = Path(item)
        if p.is_dir():
            candidates.extend(find_logs_in_dir(p, max_bytes))

    local_app = os.environ.get("LOCALAPPDATA")
    user_profile = os.environ.get("USERPROFILE")
    if local_app:
        candidates.append(Path(local_app) / "Unity" / "Editor" / "Editor.log")
        candidates.append(Path(local_app) / "Unity" / "Editor" / "Editor-prev.log")

    if unity_root:
        for sub in ("Logs", "BuildLogs", "Build", "Builds"):
            p = unity_root / sub
            if p.exists():
                candidates.extend(find_logs_in_dir(p, max_bytes))
        settings = parse_project_settings(unity_root)
        if user_profile and settings.get("companyName") and settings.get("productName"):
            candidates.append(
                Path(user_profile)
                / "AppData"
                / "LocalLow"
                / settings["companyName"]
                / settings["productName"]
                / "Player.log"
            )

    unique = []
    seen = set()
    for p in candidates:
        try:
            rp = p.resolve()
        except Exception:
            rp = p
        if rp in seen or not p.exists() or not p.is_file():
            continue
        try:
            if p.stat().st_size > max_bytes:
                continue
        except OSError:
            continue
        seen.add(rp)
        unique.append(p)
    return unique


def find_logs_in_dir(root: Path, max_bytes: int):
    logs = []
    for ext in ("*.log", "*.txt"):
        for path in root.rglob(ext):
            if not path.is_file():
                continue
            if any(part in {"Library", "Temp", "Obj", ".git", ".vs"} for part in path.parts):
                continue
            try:
                if path.stat().st_size <= max_bytes:
                    logs.append(path)
            except OSError:
                pass
    return logs


def parse_wwise_events(wwise_root: Path | None) -> set[str]:
    events = set()
    if not wwise_root or not wwise_root.exists():
        return events
    for xml_path in list(wwise_root.rglob("*.wwu")) + list(wwise_root.rglob("SoundbanksInfo.xml")):
        text = read_text(xml_path, 10 * 1024 * 1024)
        if not text:
            continue
        for match in re.finditer(r"<Event\b[^>]*\bName=\"([^\"]+)\"", text):
            events.add(match.group(1))
        try:
            root = ET.fromstring(text)
            for elem in root.iter():
                if elem.tag.split("}")[-1] == "Event":
                    name = elem.attrib.get("Name") or elem.attrib.get("name")
                    if name:
                        events.add(name)
        except Exception:
            pass
    return events


def classify(line: str) -> str:
    for category, pattern in CATEGORY_RULES:
        if pattern.search(line):
            return category
    return "UnknownAudio"


def severity(line: str) -> str:
    if SEVERITY_RE.search(line):
        return "Error"
    if WARNING_RE.search(line):
        return "Warn"
    return "Info"


def infer(category: str, line: str, events: list[str], known_events: set[str]):
    lower = line.lower()
    unknown_events = [e for e in events if known_events and e not in known_events]
    if unknown_events:
        return (
            "High",
            f"日志中出现的 Event 名称未在当前 Wwise 工程解析结果中找到：{', '.join(unknown_events[:5])}",
            "检查 Event 拼写、Wwise 工程是否已保存、SoundBank 是否包含该 Event、Unity 生成的 AK 常量是否更新。",
        )
    if category == "License":
        return (
            "High",
            "Wwise License 状态可能限制 SoundBank 生成或打包。",
            "在 Audiokinetic Launcher/Wwise License Manager 中恢复项目 License，然后重新生成 SoundBank。",
        )
    if category == "InitOrPlugin":
        return (
            "Medium",
            "Wwise Unity Runtime 初始化或插件加载链路可能异常。",
            "检查 Wwise Unity Integration 版本、平台插件 DLL、架构目录、Unity 是否锁文件、Wwise SDK/Authoring 版本是否一致。",
        )
    if category == "BankOrMedia":
        if "加载event:" in lower and "stop_" in lower and ("失败" in lower or "退出播放" in lower):
            return (
                "High",
                "Stop Event 的 Bank 加载失败，Stop Event 很可能没有发到 Wwise，因此循环/持续音可能无法停止。",
                "检查 Stop bank 是否已加载却被代码误判为失败、Bank 资源/Bundle 是否存在，或将停止逻辑改为 StopAudio/StopPlayingID/共享控制 Bank。",
            )
        if "not found" in lower or "filenotfound" in lower or "missing" in lower:
            return (
                "High",
                "SoundBank、WEM 或 GeneratedSoundBanks 路径可能缺失或平台不匹配。",
                "确认已用当前版本生成 SoundBank，Unity StreamingAssets/GeneratedSoundBanks 路径正确，Bank 在 PostEvent 前已加载。",
            )
        return (
            "Medium",
            "运行时 Bank/Media 生命周期需要确认。",
            "检查 Bank 加载、卸载、场景切换、平台目录和 SoundbanksInfo.xml。",
        )
    if category == "Event":
        return (
            "Medium",
            "Event 发送或查找链路需要确认。",
            "检查 Unity 触发条件、GameObject 是否已注册、Event 字段是否为空、Bank 是否加载、Wwise Event 是否在生成的 Bank 中。",
        )
    if category == "RTPCSwitchState":
        return (
            "Medium",
            "RTPC/Switch/State 设置可能存在名称、时序或对象作用域问题。",
            "检查参数是否存在于 Wwise，Unity 是否在 PostEvent 前设置，GameObject/global 作用域是否符合设计。",
        )
    if category == "UnityException":
        return (
            "Medium",
            "Unity 异常可能阻断音频触发链路。",
            "结合堆栈定位脚本、Prefab 引用、AK.Wwise.Event 字段、组件生命周期和空引用。",
        )
    if category == "Performance":
        return (
            "Medium",
            "运行时音频性能或发声密度可能异常。",
            "检查高频 PostEvent、voice limit、virtual voice、循环 Stop、多人声源裁剪和 Profiler 性能曲线。",
        )
    return (
        "Low",
        "该日志与音频相关，但静态规则无法确定异常性质。",
        "结合前后文、Unity 调用扫描和 Wwise Profiler 做定点验证。",
    )


def load_static_events(static_json: Path | None):
    if not static_json or not static_json.exists():
        return set()
    try:
        data = json.loads(static_json.read_text(encoding="utf-8-sig"))
    except Exception:
        return set()
    events = set()
    for call in data.get("calls", []):
        for token in call.get("event_tokens", []):
            value = token.get("value")
            if value:
                events.add(value)
    return events


def analyze_logs(logs: list[Path], known_events: set[str], static_events: set[str]):
    entries = []
    findings = []
    category_counts = Counter()
    severity_counts = Counter()
    event_counts = Counter()

    for log in logs:
        text = read_text(log, 200 * 1024 * 1024)
        if text is None:
            continue
        lines = text.splitlines()
        for idx, line in enumerate(lines, start=1):
            if not AUDIO_RE.search(line):
                continue
            sev = severity(line)
            cat = classify(line)
            events = EVENT_RE.findall(line)
            for event in events:
                event_counts[event] += 1
            entry = {
                "file": str(log),
                "line": idx,
                "severity": sev,
                "category": cat,
                "events": events,
                "text": line.strip()[:2000],
            }
            entries.append(entry)
            category_counts[cat] += 1
            severity_counts[sev] += 1

            abnormal = sev in {"Error", "Warn"}
            if events and known_events:
                abnormal = abnormal or any(event not in known_events for event in events)
            if abnormal:
                confidence, cause, recommendation = infer(cat, line, events, known_events)
                context_start = max(1, idx - 2)
                context_end = min(len(lines), idx + 2)
                context = "\n".join(f"{n}: {lines[n-1]}" for n in range(context_start, context_end + 1))
                findings.append(
                    {
                        "file": str(log),
                        "line": idx,
                        "severity": sev,
                        "category": cat,
                        "events": events,
                        "evidence": line.strip()[:2000],
                        "confidence": confidence,
                        "likely_cause": cause,
                        "recommendation": recommendation,
                        "context": context,
                    }
                )

    static_only = sorted(static_events - set(event_counts))
    log_only = sorted(set(event_counts) - static_events) if static_events else []
    return {
        "entries": entries,
        "findings": findings,
        "category_counts": category_counts,
        "severity_counts": severity_counts,
        "event_counts": event_counts,
        "static_only_events": static_only,
        "log_only_events": log_only,
    }


def process_audio_line(log: Path, line_no: int, line: str, known_events: set[str]):
    if not AUDIO_RE.search(line):
        return None, None
    sev = severity(line)
    cat = classify(line)
    events = EVENT_RE.findall(line)
    entry = {
        "file": str(log),
        "line": line_no,
        "severity": sev,
        "category": cat,
        "events": events,
        "text": line.strip()[:2000],
    }
    abnormal = sev in {"Error", "Warn"}
    if events and known_events:
        abnormal = abnormal or any(event not in known_events for event in events)
    finding = None
    if abnormal:
        confidence, cause, recommendation = infer(cat, line, events, known_events)
        finding = {
            "file": str(log),
            "line": line_no,
            "severity": sev,
            "category": cat,
            "events": events,
            "evidence": line.strip()[:2000],
            "confidence": confidence,
            "likely_cause": cause,
            "recommendation": recommendation,
            "context": line.strip()[:2000],
        }
    return entry, finding


def new_analysis_state(static_events: set[str]):
    return {
        "entries": [],
        "findings": [],
        "category_counts": Counter(),
        "severity_counts": Counter(),
        "event_counts": Counter(),
        "static_only_events": sorted(static_events),
        "log_only_events": [],
    }


def add_entry(analysis: dict, entry: dict, finding: dict | None):
    analysis["entries"].append(entry)
    analysis["category_counts"][entry["category"]] += 1
    analysis["severity_counts"][entry["severity"]] += 1
    for event in entry["events"]:
        analysis["event_counts"][event] += 1
    if finding:
        analysis["findings"].append(finding)


def update_cross_checks(analysis: dict, static_events: set[str]):
    logged = set(analysis["event_counts"])
    analysis["static_only_events"] = sorted(static_events - logged)
    analysis["log_only_events"] = sorted(logged - static_events) if static_events else []


def count_lines(path: Path, max_bytes: int) -> int:
    text = read_text(path, max_bytes)
    if text is None:
        return 0
    return len(text.splitlines())


def follow_logs(
    logs: list[Path],
    known_events: set[str],
    static_events: set[str],
    out: Path,
    json_out: Path | None,
    jsonl_out: Path | None,
    unity_root: Path | None,
    wwise_root: Path | None,
    max_bytes: int,
    interval_sec: float,
    report_interval_sec: float,
    duration_sec: float,
    from_start: bool,
    print_all_audio: bool,
):
    analysis = new_analysis_state(static_events)
    positions = {}
    line_counts = {}
    started = datetime.now().isoformat(timespec="seconds")
    for log in logs:
        try:
            if from_start:
                positions[log] = 0
                line_counts[log] = 0
            else:
                positions[log] = log.stat().st_size
                line_counts[log] = count_lines(log, max_bytes)
        except OSError:
            positions[log] = 0
            line_counts[log] = 0

    if jsonl_out:
        jsonl_out.parent.mkdir(parents=True, exist_ok=True)

    last_report = 0.0
    start = time.time()
    print(f"Following {len(logs)} log file(s). Press Ctrl+C to stop.")
    for log in logs:
        print(f"- {log}")

    try:
        while True:
            if duration_sec and (time.time() - start) >= duration_sec:
                break
            for log in list(logs):
                if not log.exists():
                    continue
                try:
                    size = log.stat().st_size
                    if size < positions.get(log, 0):
                        positions[log] = 0
                        line_counts[log] = 0
                    with log.open("r", encoding="utf-8-sig", errors="replace") as handle:
                        handle.seek(positions.get(log, 0))
                        chunk = handle.read()
                        positions[log] = handle.tell()
                except Exception:
                    continue
                if not chunk:
                    continue
                for raw in chunk.splitlines():
                    line_counts[log] = line_counts.get(log, 0) + 1
                    entry, finding = process_audio_line(log, line_counts[log], raw, known_events)
                    if not entry:
                        continue
                    add_entry(analysis, entry, finding)
                    if jsonl_out:
                        with jsonl_out.open("a", encoding="utf-8-sig") as fp:
                            fp.write(json.dumps(entry, ensure_ascii=False) + "\n")
                    if print_all_audio or finding:
                        marker = "!" if finding else " "
                        print(
                            f"{marker} [{entry['severity']}/{entry['category']}] "
                            f"{Path(entry['file']).name}:{entry['line']} {entry['text'][:240]}"
                        )

            now = time.time()
            if now - last_report >= report_interval_sec:
                update_cross_checks(analysis, static_events)
                summary = {
                    "Mode": "Follow",
                    "StartedAt": started,
                    "LastUpdated": datetime.now().isoformat(timespec="seconds"),
                    "UnityRoot": str(unity_root) if unity_root else "",
                    "WwiseProjectRoot": str(wwise_root) if wwise_root else "",
                    "LogsScanned": len(logs),
                    "KnownWwiseEvents": len(known_events),
                    "StaticAuditEvents": len(static_events),
                    "AudioLogLines": len(analysis["entries"]),
                    "Findings": len(analysis["findings"]),
                    "UniqueEventsInLogs": len(analysis["event_counts"]),
                }
                write_report(out, summary, analysis)
                if json_out:
                    payload = {"summary": summary, **jsonable(analysis), "logs": [str(p) for p in logs]}
                    json_out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8-sig")
                last_report = now
            time.sleep(interval_sec)
    except KeyboardInterrupt:
        print("Stopped.")

    update_cross_checks(analysis, static_events)
    summary = {
        "Mode": "Follow",
        "StartedAt": started,
        "LastUpdated": datetime.now().isoformat(timespec="seconds"),
        "UnityRoot": str(unity_root) if unity_root else "",
        "WwiseProjectRoot": str(wwise_root) if wwise_root else "",
        "LogsScanned": len(logs),
        "KnownWwiseEvents": len(known_events),
        "StaticAuditEvents": len(static_events),
        "AudioLogLines": len(analysis["entries"]),
        "Findings": len(analysis["findings"]),
        "UniqueEventsInLogs": len(analysis["event_counts"]),
    }
    write_report(out, summary, analysis)
    if json_out:
        payload = {"summary": summary, **jsonable(analysis), "logs": [str(p) for p in logs]}
        json_out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8-sig")
    print(out)
    if json_out:
        print(json_out)


def md_escape(value):
    return str(value).replace("|", "\\|").replace("\n", "<br>")


def write_report(out: Path, summary: dict, analysis: dict):
    lines = []
    lines.append("# Unity/Wwise 运行日志音频诊断报告")
    lines.append("")
    lines.append("## 摘要")
    lines.append("")
    for key, value in summary.items():
        lines.append(f"- **{key}**: {value}")
    lines.append("")

    lines.append("## 分类统计")
    lines.append("")
    lines.append("| Category | Count |")
    lines.append("|---|---:|")
    for key, count in analysis["category_counts"].most_common():
        lines.append(f"| {md_escape(key)} | {count} |")
    lines.append("")

    lines.append("## 严重度统计")
    lines.append("")
    lines.append("| Severity | Count |")
    lines.append("|---|---:|")
    for key, count in analysis["severity_counts"].most_common():
        lines.append(f"| {md_escape(key)} | {count} |")
    lines.append("")

    lines.append("## 关键异常与推测")
    lines.append("")
    lines.append("| Severity | Category | File | Line | Event/Name | Confidence | Evidence | Likely Cause | Recommendation |")
    lines.append("|---|---|---|---:|---|---|---|---|---|")
    for finding in analysis["findings"][:300]:
        lines.append(
            "| "
            + " | ".join(
                md_escape(x)
                for x in [
                    finding["severity"],
                    finding["category"],
                    finding["file"],
                    finding["line"],
                    ", ".join(finding["events"]),
                    finding["confidence"],
                    finding["evidence"],
                    finding["likely_cause"],
                    finding["recommendation"],
                ]
            )
            + " |"
        )
    if not analysis["findings"]:
        lines.append("| Pass | - | - | - | - | - | 未发现明显音频异常日志。 | 仍建议结合 Wwise Profiler 和目标场景验证。 | - |")
    lines.append("")

    lines.append("## 音频日志时间线")
    lines.append("")
    lines.append("| Severity | Category | File | Line | Message |")
    lines.append("|---|---|---|---:|---|")
    for entry in analysis["entries"][:500]:
        lines.append(
            "| "
            + " | ".join(
                md_escape(x)
                for x in [
                    entry["severity"],
                    entry["category"],
                    entry["file"],
                    entry["line"],
                    entry["text"],
                ]
            )
            + " |"
        )
    if not analysis["entries"]:
        lines.append("| - | - | - | - | 没有发现 Wwise/音频相关日志行。 |")
    lines.append("")

    lines.append("## Event 交叉检查")
    lines.append("")
    lines.append("| Event | Count In Logs |")
    lines.append("|---|---:|")
    for event, count in analysis["event_counts"].most_common(200):
        lines.append(f"| {md_escape(event)} | {count} |")
    if not analysis["event_counts"]:
        lines.append("| - | 0 |")
    lines.append("")

    if analysis["log_only_events"]:
        lines.append("### 日志中出现但静态调用表未出现的 Event")
        lines.append("")
        for event in analysis["log_only_events"][:100]:
            lines.append(f"- `{event}`")
        lines.append("")

    if analysis["static_only_events"]:
        lines.append("### 静态调用表存在但本次日志未出现的 Event")
        lines.append("")
        for event in analysis["static_only_events"][:100]:
            lines.append(f"- `{event}`")
        lines.append("")

    lines.append("## 下一步建议")
    lines.append("")
    lines.append("- 如果日志没有音频行，先确认 Unity/Wwise 日志级别、测试路径是否触发到目标代码。")
    lines.append("- 如果 Unity 有调用但 Wwise Profiler 没有 Event，优先查 Bank 加载、GameObject 注册、Event 字段/名称、触发条件。")
    lines.append("- 如果 Wwise Profiler 有 Event 但听不到，优先查 Bus、Volume、Mute/Solo、Attenuation、Voice Limit、Virtual Voice、Listener/Emitter。")
    lines.append("- 如果 Bank/Media 缺失，优先重新生成 SoundBank 并确认 Unity 输出路径和平台目录。")
    lines.append("- 如果是 RTPC/Switch/State 问题，确认设置时机、作用域、默认值和 Wwise 参数名称。")
    out.write_text("\n".join(lines), encoding="utf-8-sig")


def jsonable(analysis):
    result = dict(analysis)
    for key in ("category_counts", "severity_counts", "event_counts"):
        result[key] = dict(result[key])
    return result


def main():
    parser = argparse.ArgumentParser(description="Analyze Unity/Wwise runtime logs for audio issues.")
    parser.add_argument("--unity-root")
    parser.add_argument("--wwise-project-root")
    parser.add_argument("--static-audit-json")
    parser.add_argument("--logs", nargs="*", default=[])
    parser.add_argument("--log-roots", nargs="*", default=[])
    parser.add_argument("--out", required=True)
    parser.add_argument("--json-out")
    parser.add_argument("--max-file-mb", type=float, default=200.0)
    parser.add_argument("--follow", action="store_true", help="Follow logs in near real time and keep updating the report.")
    parser.add_argument("--from-start", action="store_true", help="In follow mode, read existing log content instead of only new lines.")
    parser.add_argument("--interval-sec", type=float, default=1.0)
    parser.add_argument("--report-interval-sec", type=float, default=5.0)
    parser.add_argument("--duration-sec", type=float, default=0.0, help="Stop follow mode after this many seconds; 0 means until Ctrl+C.")
    parser.add_argument("--jsonl-out", help="In follow mode, append each audio-related line as JSONL.")
    parser.add_argument("--print-all-audio", action="store_true", help="In follow mode, print all audio lines; default prints abnormal findings only.")
    args = parser.parse_args()

    unity_root = Path(args.unity_root) if args.unity_root else None
    if unity_root and not unity_root.exists():
        print(f"Unity root not found: {unity_root}", file=sys.stderr)
        return 2

    max_bytes = int(args.max_file_mb * 1024 * 1024)
    logs = discover_logs(unity_root, args.logs, args.log_roots, max_bytes)
    wwise_root = Path(args.wwise_project_root) if args.wwise_project_root else None
    known_events = parse_wwise_events(wwise_root)
    static_events = load_static_events(Path(args.static_audit_json) if args.static_audit_json else None)

    if args.follow:
        follow_logs(
            logs=logs,
            known_events=known_events,
            static_events=static_events,
            out=Path(args.out),
            json_out=Path(args.json_out) if args.json_out else None,
            jsonl_out=Path(args.jsonl_out) if args.jsonl_out else None,
            unity_root=unity_root,
            wwise_root=wwise_root,
            max_bytes=max_bytes,
            interval_sec=args.interval_sec,
            report_interval_sec=args.report_interval_sec,
            duration_sec=args.duration_sec,
            from_start=args.from_start,
            print_all_audio=args.print_all_audio,
        )
        return 0

    analysis = analyze_logs(logs, known_events, static_events)

    summary = {
        "UnityRoot": str(unity_root) if unity_root else "",
        "WwiseProjectRoot": str(wwise_root) if wwise_root else "",
        "LogsScanned": len(logs),
        "KnownWwiseEvents": len(known_events),
        "StaticAuditEvents": len(static_events),
        "AudioLogLines": len(analysis["entries"]),
        "Findings": len(analysis["findings"]),
        "UniqueEventsInLogs": len(analysis["event_counts"]),
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    write_report(out, summary, analysis)
    if args.json_out:
        payload = {"summary": summary, **jsonable(analysis), "logs": [str(p) for p in logs]}
        Path(args.json_out).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8-sig")
    print(out)
    if args.json_out:
        print(args.json_out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
