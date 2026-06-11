#!/usr/bin/env python3
import argparse
import json
import re
import time
from collections import Counter
from datetime import datetime
from pathlib import Path


DEFAULT_PATTERNS = ["*.json"]
DEFAULT_EXCLUDE = [".jsonl", "TrendSummary.json"]


def read_json(path: Path, max_mb: float):
    try:
        if path.stat().st_size > max_mb * 1024 * 1024:
            return None, f"skipped_large>{max_mb}MB"
        return json.loads(path.read_text(encoding="utf-8-sig", errors="replace")), ""
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def collect_reports(root: Path, latest: int, patterns: list[str], max_mb: float):
    files = []
    for pattern in patterns:
        files.extend(root.glob(pattern))
    unique = []
    seen = set()
    for path in files:
        if not path.is_file():
            continue
        lower = path.name.lower()
        if any(token.lower() in lower for token in DEFAULT_EXCLUDE):
            continue
        if path.resolve() in seen:
            continue
        seen.add(path.resolve())
        unique.append(path)
    unique.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    return unique[:latest]


def text_of_finding(item: dict) -> str:
    for key in ("latest_evidence", "evidence", "text", "message"):
        value = item.get(key)
        if value:
            return str(value)
    return ""


def events_of(item: dict) -> list[str]:
    events = item.get("events") or []
    if isinstance(events, str):
        return [events]
    return [str(e) for e in events if e]


def classify_issue(item: dict):
    issue_type = item.get("type") or item.get("category") or "Unknown"
    text = text_of_finding(item)
    lower = text.lower()
    events = events_of(item)
    event_name = ""
    match = re.search(r"加载Event:([A-Za-z0-9_]+)", text)
    if match:
        event_name = match.group(1)
    elif events:
        event_name = events[0]

    if "加载event:" in lower and ("失败" in text or "退出播放" in text):
        if event_name.lower().startswith("stop_"):
            return "StopEventBankLoadFailed", event_name
        return "EventBankLoadFailed", event_name or "<event>"
    if "voice starvation" in lower:
        return "VoiceStarvation", event_name or "<wwise>"
    if "source starvation" in lower:
        source = re.search(r"source starvation(?: name:)?\s*([0-9]+)", text, re.IGNORECASE)
        return "SourceStarvation", source.group(1) if source else "<source>"
    if "monitor queue full" in lower:
        return "MonitorQueueFull", "<monitor>"
    if "setstate fail" in lower:
        state = re.search(r'StateGroup "([^"]+)", StateName "([^"]+)"', text)
        return "SetStateFail", "/".join(state.groups()) if state else "<state>"
    if "file with file id: 0" in lower or "0.bnk" in lower:
        return "InvalidBankId0", "0.bnk"
    if "bank load failed" in lower:
        return "BankLoadFailed", event_name or "<bank>"
    if "license" in lower or "no license key" in lower:
        return "LicenseOrPackaging", "<license>"
    if item.get("confidence") == "High" and "not found" in lower:
        return "MissingBankOrMedia", event_name or "<media>"
    if item.get("severity") in {"Error", "Warn"}:
        return issue_type, event_name or "<none>"
    return "InfoOrNoise", event_name or "<none>"


def extract_report_items(data: dict):
    if data.get("issue_groups"):
        for item in data["issue_groups"]:
            yield {
                "source": "issue_group",
                "severity": item.get("severity"),
                "type": item.get("type"),
                "count": int(item.get("count") or 1),
                "events": item.get("events") or ([item.get("event_hint")] if item.get("event_hint") else []),
                "latest_evidence": item.get("latest_evidence", ""),
                "confidence": item.get("confidence"),
                "likely_cause": item.get("likely_cause"),
                "recommendation": item.get("recommendation"),
            }
        return
    for item in data.get("findings") or []:
        yield {
            "source": "finding",
            "severity": item.get("severity"),
            "type": item.get("category") or item.get("type"),
            "count": 1,
            "events": item.get("events") or [],
            "latest_evidence": text_of_finding(item),
            "confidence": item.get("confidence"),
            "likely_cause": item.get("likely_cause"),
            "recommendation": item.get("recommendation"),
        }


def analyze_once(root: Path, latest: int, patterns: list[str], max_mb: float):
    report_files = collect_reports(root, latest, patterns, max_mb)
    reports = []
    issue_counts = Counter()
    issue_event_counts = Counter()
    issue_examples = {}
    severity_counts = Counter()
    category_counts = Counter()
    event_counts = Counter()
    qa_failures = []

    for path in report_files:
        data, error = read_json(path, max_mb)
        report = {
            "path": str(path),
            "name": path.name,
            "modified": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
            "size": path.stat().st_size,
            "load_error": error,
            "summary": {},
            "finding_count": 0,
        }
        if data is None:
            reports.append(report)
            continue
        summary = data.get("summary") or data.get("qa") or {}
        report["summary"] = summary
        report["finding_count"] = len(data.get("findings") or []) + len(data.get("issue_groups") or [])
        reports.append(report)

        severity_counts.update(data.get("severity_counts") or {})
        category_counts.update(data.get("category_counts") or {})
        event_counts.update(data.get("event_counts") or {})

        qa = data.get("qa") or {}
        failures = qa.get("failures") or []
        if failures:
            qa_failures.append({"report": path.name, "failures": failures[:20]})

        for item in extract_report_items(data):
            issue_type, subject = classify_issue(item)
            count = int(item.get("count") or 1)
            issue_counts[issue_type] += count
            issue_event_counts[(issue_type, subject)] += count
            issue_examples.setdefault((issue_type, subject), item)

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "report_root": str(root),
        "latest_requested": latest,
        "reports": reports,
        "aggregate": {
            "severity_counts": dict(severity_counts),
            "category_counts": dict(category_counts),
            "event_counts_top": event_counts.most_common(30),
            "issue_counts": dict(issue_counts),
            "issue_event_counts_top": [
                {"type": k[0], "subject": k[1], "count": v}
                for k, v in issue_event_counts.most_common(40)
            ],
            "qa_failures": qa_failures,
        },
        "examples": {
            f"{k[0]}::{k[1]}": v for k, v in list(issue_examples.items())[:80]
        },
        "interpretation": build_interpretation(issue_counts, qa_failures),
        "tool_backlog": build_tool_backlog(issue_counts),
    }


def build_interpretation(issue_counts: Counter, qa_failures):
    lines = []
    event_bank = issue_counts.get("EventBankLoadFailed", 0)
    stop_bank = issue_counts.get("StopEventBankLoadFailed", 0)
    if event_bank + stop_bank > 20:
        lines.append({
            "confidence": "High",
            "title": "Systemic Event bank load failures",
            "detail": "Many Events fail before reaching Wwise because their Event banks cannot be loaded. This is more likely a Unity/WwiseProvider bank lifecycle or packaging issue than individual Wwise Event design errors.",
            "next_step": "Fix the bank-load path/return semantics first, then retest audio design changes.",
        })
    if issue_counts.get("VoiceStarvation", 0) or issue_counts.get("SourceStarvation", 0):
        lines.append({
            "confidence": "Medium",
            "title": "Runtime voice/source starvation is present",
            "detail": "Starvation may be a symptom of leaked loops, excessive PostEvent frequency, or bank/source instability.",
            "next_step": "Correlate timestamps with failed Stop/Event bank loads and Wwise Profiler active voices.",
        })
    if issue_counts.get("MonitorQueueFull", 0):
        lines.append({
            "confidence": "Medium",
            "title": "Wwise monitor queue overflow",
            "detail": "Profiler/monitor messages are overflowing, so diagnostic data can be incomplete during heavy sessions.",
            "next_step": "Increase uMonitorQueuePoolSize for debug builds or reduce monitor spam while testing.",
        })
    if issue_counts.get("SetStateFail", 0):
        lines.append({
            "confidence": "Medium",
            "title": "State set failure appears in runtime logs",
            "detail": "If the State exists in Wwise, this is likely timing/lifecycle related, often during shutdown or before Wwise init.",
            "next_step": "Guard SetState calls by Wwise init/shutdown state and log caller context.",
        })
    if qa_failures:
        lines.append({
            "confidence": "High",
            "title": "QA failures exist in recent reports",
            "detail": "At least one report contains explicit QA failures.",
            "next_step": "Resolve QA failures before broadening the change set.",
        })
    if not lines:
        lines.append({
            "confidence": "Low",
            "title": "No dominant issue detected",
            "detail": "The latest reports do not show a strong repeated failure pattern.",
            "next_step": "Keep monitoring and compare after the next playtest.",
        })
    return lines


def build_tool_backlog(issue_counts: Counter):
    backlog = []
    if issue_counts.get("EventBankLoadFailed", 0) or issue_counts.get("StopEventBankLoadFailed", 0):
        backlog.append({
            "priority": "S",
            "item": "Source-code correlation for bank-load failures",
            "reason": "Repeated Event bank load failures need direct links to WwiseProvider, AkBankManager, bank asset paths, and affected Events.",
            "proposal": "Add an analyzer panel that groups failed Event bank loads by Event, points to likely code paths, and checks generated bank assets.",
        })
    if issue_counts.get("VoiceStarvation", 0) or issue_counts.get("SourceStarvation", 0):
        backlog.append({
            "priority": "A",
            "item": "Profiler-friendly starvation timeline",
            "reason": "Starvation needs timestamp correlation with failed Stop Events, active loops, and high-frequency PostEvent bursts.",
            "proposal": "Add timeline grouping by timestamp window and show nearest Event failures before starvation.",
        })
    if issue_counts.get("MonitorQueueFull", 0):
        backlog.append({
            "priority": "A",
            "item": "Monitor queue health warning",
            "reason": "When the monitor queue is full, downstream diagnosis may be incomplete.",
            "proposal": "Show a visible GUI warning and suggest debug config changes such as uMonitorQueuePoolSize.",
        })
    backlog.append({
        "priority": "A",
        "item": "Recurring report trend summary",
        "reason": "Manual review is expensive and easy to miss after long play sessions.",
        "proposal": "Run this trend monitor every few hours against the latest reports and produce one rolling summary.",
    })
    backlog.append({
        "priority": "B",
        "item": "False-positive suppression registry",
        "reason": "Manifest lines and asset names can contain words such as Fail that are not runtime failures.",
        "proposal": "Keep a local ignore/classification table for known benign patterns.",
    })
    backlog.append({
        "priority": "B",
        "item": "Bilingual executive summary",
        "reason": "Audio, programming, and management readers need different levels of detail.",
        "proposal": "Generate CN/EN cause and recommendation blocks by default for high-confidence issues.",
    })
    return backlog


def render_markdown(result: dict):
    lines = []
    lines.append("# Audio Report Trend Summary")
    lines.append("")
    lines.append(f"- Generated: {result['generated_at']}")
    lines.append(f"- Report root: `{result['report_root']}`")
    lines.append(f"- Latest requested: {result['latest_requested']}")
    lines.append("")
    lines.append("## Reports Inspected")
    lines.append("")
    lines.append("| # | Report | Modified | Findings | Load |")
    lines.append("|---:|---|---|---:|---|")
    for idx, report in enumerate(result["reports"], 1):
        load = report["load_error"] or "OK"
        lines.append(f"| {idx} | `{report['name']}` | {report['modified']} | {report['finding_count']} | {load} |")
    lines.append("")
    aggregate = result["aggregate"]
    lines.append("## Top Issues")
    lines.append("")
    lines.append("| Type | Subject | Count |")
    lines.append("|---|---|---:|")
    for item in aggregate["issue_event_counts_top"][:20]:
        lines.append(f"| {item['type']} | `{item['subject']}` | {item['count']} |")
    if not aggregate["issue_event_counts_top"]:
        lines.append("| - | - | 0 |")
    lines.append("")
    lines.append("## Interpretation")
    lines.append("")
    for item in result["interpretation"]:
        lines.append(f"### {item['title']}")
        lines.append("")
        lines.append(f"- Confidence: {item['confidence']}")
        lines.append(f"- Analysis: {item['detail']}")
        lines.append(f"- Next step: {item['next_step']}")
        lines.append("")
    lines.append("## Tool / Workflow Backlog")
    lines.append("")
    lines.append("| Priority | Item | Reason | Proposal |")
    lines.append("|---|---|---|---|")
    for item in result["tool_backlog"]:
        lines.append(f"| {item['priority']} | {item['item']} | {item['reason']} | {item['proposal']} |")
    lines.append("")
    lines.append("## Aggregate Counters")
    lines.append("")
    lines.append("### Severity")
    lines.append("")
    for key, value in sorted(aggregate["severity_counts"].items(), key=lambda kv: str(kv[0])):
        lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("### Category")
    lines.append("")
    for key, value in sorted(aggregate["category_counts"].items(), key=lambda kv: str(kv[0])):
        lines.append(f"- {key}: {value}")
    lines.append("")
    return "\n".join(lines)


def write_outputs(result: dict, out: Path, json_out: Path | None):
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_markdown(result), encoding="utf-8")
    if json_out:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8-sig")


def main():
    parser = argparse.ArgumentParser(description="Aggregate recent audio/Wwise/Unity reports and propose workflow/tool iterations.")
    parser.add_argument("--report-root", required=True)
    parser.add_argument("--latest", type=int, default=8)
    parser.add_argument("--patterns", nargs="*", default=DEFAULT_PATTERNS)
    parser.add_argument("--max-file-mb", type=float, default=120.0)
    parser.add_argument("--out", required=True)
    parser.add_argument("--json-out")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--interval-hours", type=float, default=3.0)
    args = parser.parse_args()
    root = Path(args.report_root)
    out = Path(args.out)
    json_out = Path(args.json_out) if args.json_out else None

    def run_once():
        result = analyze_once(root, args.latest, args.patterns, args.max_file_mb)
        write_outputs(result, out, json_out)
        print(f"[{result['generated_at']}] wrote {out}")

    if not args.watch:
        run_once()
        return 0
    interval = max(args.interval_hours, 0.05) * 3600
    while True:
        run_once()
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
