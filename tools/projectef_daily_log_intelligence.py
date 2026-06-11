#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


AUDIO_RE = re.compile(
    r"(wwise|audiokinetic|aksoundengine|akinitializer|akbank|akevent|akunity|ak\.wwise|"
    r"soundbank|postevent|loadbank|unloadbank|rtpc|setswitch|setstate|\.bnk\b|\.wem\b|"
    r"audio\s+plugin|audio\s+engine|WwiseAudioHelper|AudioManager4Wwise)",
    re.IGNORECASE,
)

ERROR_RE = re.compile(
    r"(error|exception|failed|failure\b|fatal|cannot|could not|invalid|missing|not found|"
    r"nullreference|argumentexception|filenotfound|idnotfound|bank load failed|failed to load)",
    re.IGNORECASE,
)

WARN_RE = re.compile(
    r"(warning|warn\b|starvation|underrun|overflow|monitor queue full|too many|not loaded)",
    re.IGNORECASE,
)

EVENT_RE = re.compile(r"\b(?:Play|Stop|Pause|Resume|Set|Reset|Mute|Unmute)_[A-Za-z0-9_]+\b")


MODULES: dict[str, dict[str, Any]] = {
    "System.BankAndInit": {
        "label": "系统 / Bank 与初始化",
        "patterns": [r"Init", r"Plugin", r"Bank", r"SoundBank", r"\.bnk", r"LoadBank", r"UnloadBank"],
        "scenarios": ["RQA-01", "RQA-11"],
    },
    "Fishing.Cast": {
        "label": "钓鱼 / 抛竿",
        "patterns": [r"Line_Cast", r"\bCast\b"],
        "scenarios": ["Fishing.Cast", "RQA-03"],
    },
    "Fishing.LureWater": {
        "label": "钓鱼 / Lure 入水出水",
        "patterns": [r"Lure_WaterIn", r"Lure_WaterOut", r"Lure water"],
        "scenarios": ["Fishing.LureWater", "RQA-04"],
    },
    "Fishing.FishWater": {
        "label": "鱼 / 水花与入出水",
        "patterns": [r"Fish_WaterIn", r"Fish_WaterOut", r"Fish / Water", r"Water movement"],
        "scenarios": ["Fish.Water", "RQA-05"],
    },
    "Fishing.ReelRetrieve": {
        "label": "钓鱼 / 收线",
        "patterns": [r"Wheel_Retrieve", r"Reel retrieve"],
        "scenarios": ["Fishing.ReelRetrieve", "RQA-06"],
    },
    "Fishing.LineOut": {
        "label": "钓鱼 / 放线",
        "patterns": [r"Line_Out", r"Line out"],
        "scenarios": ["Fishing.LineOut", "RQA-07"],
    },
    "Fishing.Fight": {
        "label": "钓鱼 / Fight Fish",
        "patterns": [r"Fight", r"Bite", r"Strike"],
        "scenarios": ["Fishing.Fight", "Fishing.BiteSignal"],
    },
    "Player.Footsteps": {
        "label": "玩家 / 脚步",
        "patterns": [r"Footsteps", r"Sneakers"],
        "scenarios": ["Player.Footsteps", "RQA-02"],
    },
    "Player.BodyState": {
        "label": "玩家 / 体力与状态",
        "patterns": [r"Stamina", r"Body", r"Temperature", r"BodyState"],
        "scenarios": ["Player.BodyState"],
    },
    "Gear": {
        "label": "渔具 / 装备交互",
        "patterns": [r"Spool", r"ReelDrag", r"Rod", r"Reel", r"Gear", r"Buzzbait"],
        "scenarios": ["Gear.Tools", "RQA-08"],
    },
    "UI": {
        "label": "UI / 菜单反馈",
        "patterns": [r"Play_UI", r"UI_", r"Common_Click", r"Common_Up", r"Common_Down"],
        "scenarios": ["UI.Menu", "RQA-09"],
    },
    "Ambience": {
        "label": "环境 / BGM 与天气",
        "patterns": [r"Amb", r"BGM", r"Weather", r"Rain", r"Wind", r"Day", r"Night"],
        "scenarios": ["Ambience.Weather", "RQA-10"],
    },
    "Multiplayer.Others": {
        "label": "多人 / Others",
        "patterns": [r"Others", r"OtherPlayer", r"Remote", r"Multiplayer", r"Player_Others"],
        "scenarios": ["Multiplayer"],
    },
    "Performance": {
        "label": "性能 / Starvation 与队列",
        "patterns": [r"Starvation", r"MonitorQueueFull", r"Voice", r"Source", r"overflow"],
        "scenarios": [],
    },
}


def load_json(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8-sig", errors="replace"))


def load_module_profile(report_root: Path, explicit_path: str | None = None) -> dict[str, Any]:
    path = Path(explicit_path) if explicit_path else newest(report_root, "ProjectEF_AudioModuleProfile_*.json")
    data = load_json(path)
    if path:
        data["path"] = str(path)
    modules = data.get("modules")
    if isinstance(modules, list):
        data["module_map"] = {
            str(item.get("id")): {
                "label": item.get("label") or item.get("id"),
                "patterns": item.get("patterns") or [],
                "scenarios": item.get("scenarios") or [],
                "sabc": item.get("sabc", ""),
                "expected_events": item.get("expected_events") or [],
                "core_requirements": item.get("core_requirements") or [],
            }
            for item in modules
            if item.get("id")
        }
    return data


def apply_module_profile(profile: dict[str, Any]) -> None:
    module_map = profile.get("module_map") or {}
    if not module_map:
        return
    MODULES.clear()
    MODULES.update(module_map)


def newest(root: Path, pattern: str) -> Path | None:
    roots = [root]
    if root.parent != root:
        roots.append(root.parent)
    files = []
    seen = set()
    for search_root in roots:
        if not search_root.exists():
            continue
        for path in search_root.glob(pattern):
            if not path.is_file():
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            files.append(path)
    if not files:
        return None
    return max(files, key=lambda path: path.stat().st_mtime)


def discover_logs(unity_root: Path) -> list[Path]:
    candidates: list[Path] = []
    local_app = os.environ.get("LOCALAPPDATA")
    user_profile = os.environ.get("USERPROFILE")
    if local_app:
        candidates.extend(
            [
                Path(local_app) / "Unity" / "Editor" / "Editor.log",
                Path(local_app) / "Unity" / "Editor" / "Editor-prev.log",
            ]
        )
    if user_profile:
        candidates.append(Path(user_profile) / "AppData" / "LocalLow" / "DefaultCompany" / "TargetProject" / "Player.log")
    if unity_root.exists():
        for folder_name in ("Logs", "BuildLogs"):
            folder = unity_root / folder_name
            if folder.exists():
                candidates.extend(path for path in folder.rglob("*") if path.is_file() and path.suffix.lower() in {".log", ".txt"})
    unique: dict[str, Path] = {}
    for path in candidates:
        if path.exists() and path.is_file():
            unique[str(path.resolve()).lower()] = path
    return sorted(unique.values(), key=lambda p: p.stat().st_mtime, reverse=True)


def read_tail(path: Path, max_mb: float) -> str:
    limit = int(max_mb * 1024 * 1024)
    with path.open("rb") as handle:
        size = path.stat().st_size
        if size > limit:
            handle.seek(size - limit)
            handle.readline()
        data = handle.read()
    return data.decode("utf-8-sig", errors="replace")


def severity_of(line: str) -> str:
    if ERROR_RE.search(line):
        return "Error"
    if WARN_RE.search(line):
        return "Warn"
    return "Info"


def module_for_text(text: str) -> str:
    for key, meta in MODULES.items():
        if any(re.search(pattern, text, re.IGNORECASE) for pattern in meta["patterns"]):
            return key
    return "Unknown"


def issue_type(line: str) -> str:
    lower = line.lower()
    if "monitor queue full" in lower:
        return "MonitorQueueFull"
    if "source starvation" in lower:
        return "SourceStarvation"
    if "voice starvation" in lower or "starvation" in lower:
        return "VoiceStarvation"
    if "setstate fail" in lower or ("setstate" in lower and ERROR_RE.search(line)):
        return "SetStateFail"
    if "bank" in lower and ERROR_RE.search(line):
        return "BankLoadFailed"
    if "postevent" in lower and ERROR_RE.search(line):
        return "EventPostFailed"
    if "exception" in lower:
        return "UnityException"
    if WARN_RE.search(line):
        return "Warning"
    if ERROR_RE.search(line):
        return "Error"
    return "Info"


def scan_logs(logs: list[Path], day: dt.date, max_log_mb: float) -> dict[str, Any]:
    start = dt.datetime.combine(day, dt.time.min)
    end = dt.datetime.combine(day, dt.time.max)
    scanned = []
    audio_lines = []
    issue_counts = Counter()
    module_counts = Counter()
    module_issue_counts = Counter()
    event_counts = Counter()
    examples: dict[tuple[str, str], str] = {}

    for path in logs:
        mtime = dt.datetime.fromtimestamp(path.stat().st_mtime)
        if mtime.date() != day:
            continue
        scanned.append({"path": str(path), "modified": mtime.isoformat(timespec="seconds"), "size_mb": round(path.stat().st_size / 1024 / 1024, 2)})
        text = read_tail(path, max_log_mb)
        for idx, line in enumerate(text.splitlines(), 1):
            if not AUDIO_RE.search(line):
                continue
            severity = severity_of(line)
            module = module_for_text(line)
            events = EVENT_RE.findall(line)
            audio_lines.append({"file": str(path), "tail_line": idx, "severity": severity, "module": module, "message": line[:500], "events": events[:5]})
            module_counts[module] += 1
            for event in events:
                event_counts[event] += 1
            if severity in {"Error", "Warn"}:
                typ = issue_type(line)
                issue_counts[(typ, module)] += 1
                module_issue_counts[module] += 1
                examples.setdefault((typ, module), line[:500])

    return {
        "day": day.isoformat(),
        "logs_scanned": scanned,
        "audio_line_count": len(audio_lines),
        "recent_audio_lines": audio_lines[-120:],
        "issue_counts": [{"type": k[0], "module": k[1], "count": v, "example": examples.get(k, "")} for k, v in issue_counts.most_common()],
        "module_audio_counts": dict(module_counts),
        "module_issue_counts": dict(module_issue_counts),
        "event_counts": dict(event_counts.most_common(40)),
    }


def scenario_module(row: dict[str, Any]) -> str:
    text = " ".join(str(row.get(key, "")) for key in ("id", "label", "scenario"))
    for key, meta in MODULES.items():
        if str(row.get("id", "")) in meta.get("scenarios", []):
            return key
        if any(re.search(pattern, text, re.IGNORECASE) for pattern in meta["patterns"]):
            return key
    return "Unknown"


def summarize_modules(monitor: dict[str, Any], log_result: dict[str, Any], bank_check: dict[str, Any], wwise_audit: dict[str, Any]) -> list[dict[str, Any]]:
    coverage_by_module: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in monitor.get("coverage_matrix") or []:
        coverage_by_module[scenario_module(row)].append(row)

    module_issue_counts = Counter(log_result.get("module_issue_counts") or {})
    for item in monitor.get("issue_groups") or []:
        text = " ".join(str(item.get(key, "")) for key in ("type", "latest_evidence", "events", "event_hint"))
        module_issue_counts[module_for_text(text)] += int(item.get("count") or 1)

    bank_missing = len(bank_check.get("missing_event_banks") or [])
    no_limit_count = len((wwise_audit.get("analysis") or {}).get("no_limit_candidates") or [])
    unreferenced_wav = int((wwise_audit.get("file_scan") or {}).get("unreferenced_wav_count") or 0)

    rows = []
    for key, meta in MODULES.items():
        coverage = coverage_by_module.get(key, [])
        statuses = Counter(str(row.get("status", "Unknown")) for row in coverage)
        observed = sum(int(row.get("observed_audio_lines") or 0) for row in coverage)
        planned = sum(1 for row in coverage if row.get("planned"))
        issues = int(module_issue_counts.get(key, 0))

        if key == "System.BankAndInit" and bank_missing:
            issues += bank_missing
        if key == "Performance":
            issues += 0

        if issues > 0:
            status = "ObservedFail" if observed else "Risk"
            completion = 25 if observed else 35
        elif statuses.get("ObservedPass") or statuses.get("ObservedUnplanned") or observed:
            status = "ObservedPass" if planned else "ObservedUnplanned"
            completion = 80 if planned else 60
        elif key == "System.BankAndInit" and bank_check and bank_missing == 0:
            status = "StaticPass"
            completion = 75
        elif coverage:
            status = "NotObserved"
            completion = 30
        else:
            status = "StaticOnly"
            completion = 45

        evidence = []
        if coverage:
            evidence.append(f"coverage={dict(statuses)}")
        if observed:
            evidence.append(f"observed_audio_lines={observed}")
        if issues:
            evidence.append(f"issues={issues}")
        if key == "System.BankAndInit" and bank_check:
            evidence.append(f"runtime_event_banks={bank_check.get('runtime_event_bank_count', '-')}/{bank_check.get('authored_event_count', '-')}")
        if key == "Performance" and no_limit_count:
            evidence.append(f"playback_limit_candidates={no_limit_count}")
        if key == "Ambience" and unreferenced_wav:
            evidence.append(f"unreferenced_wav_total={unreferenced_wav}")

        if status in {"ObservedFail", "Risk"}:
            next_action = "先复测并定位对应日志时间窗；若文件存在但加载失败，转程序侧 lifecycle/path 排查。"
        elif status == "NotObserved":
            next_action = "按 Runtime QA checklist 补场景触发，不能把未观察当作通过。"
        elif status == "StaticPass":
            next_action = "进入新 runtime session 验证实际加载与触发。"
        elif status == "ObservedUnplanned":
            next_action = "下次将该模块标为 Planned，确认触发路径和验收标准。"
        else:
            next_action = "维持观察，等待更完整 session 数据。"

        rows.append(
            {
                "module": key,
                "label": meta["label"],
                "sabc": meta.get("sabc", ""),
                "expected_events": meta.get("expected_events", []),
                "core_requirements": meta.get("core_requirements", []),
                "runtime_validation_status": status,
                "runtime_completion_percent": completion,
                "planned_scenarios": planned,
                "observed_audio_lines": observed,
                "issue_count": issues,
                "evidence": "; ".join(evidence) if evidence else "no direct runtime evidence",
                "next_action": next_action,
            }
        )
    return rows


def collect_problems(trend: dict[str, Any], monitor: dict[str, Any], log_result: dict[str, Any]) -> list[dict[str, Any]]:
    problems = []
    for item in (trend.get("aggregate") or {}).get("issue_event_counts_top") or []:
        typ = item.get("type", "Unknown")
        subject = item.get("subject", "")
        count = int(item.get("count") or 0)
        module = module_for_text(f"{typ} {subject}")
        problems.append({"source": "trend", "module": module, "type": typ, "subject": subject, "count": count, "evidence": f"{typ} / {subject}"})
    for item in monitor.get("issue_groups") or []:
        typ = item.get("type", "Unknown")
        text = item.get("latest_evidence") or item.get("recommendation") or ""
        events = item.get("events") or []
        module = module_for_text(f"{typ} {events} {text}")
        problems.append({"source": "monitor", "module": module, "type": typ, "subject": ", ".join(map(str, events)) or item.get("event_hint", ""), "count": int(item.get("count") or 1), "evidence": text[:300]})
    for item in log_result.get("issue_counts") or []:
        problems.append({"source": "raw_log", **item})
    problems.sort(key=lambda item: int(item.get("count") or 0), reverse=True)
    return problems[:30]


def table(rows: list[list[Any]], headers: list[str]) -> str:
    if not rows:
        return "| " + " | ".join(headers) + " |\n| " + " | ".join("---" for _ in headers) + " |\n"
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        out.append("| " + " | ".join(str(cell).replace("\n", "<br>").replace("|", "/") for cell in row) + " |")
    return "\n".join(out)


def render_markdown(result: dict[str, Any]) -> str:
    module_rows = [
        [
            item["label"],
            item.get("sabc", ""),
            item["runtime_validation_status"],
            f"{item['runtime_completion_percent']}%",
            item["observed_audio_lines"],
            item["issue_count"],
            item["evidence"],
            item["next_action"],
        ]
        for item in result["modules"]
    ]
    problem_rows = [
        [p.get("module", ""), p.get("type", ""), p.get("subject", ""), p.get("count", ""), p.get("source", ""), p.get("evidence", "")]
        for p in result["problems"][:20]
    ]
    source = result["source_quality"]
    lines = [
        "# ProjectEF Daily Audio Log Intelligence",
        "",
        f"- Date: {result['date']}",
        f"- Generated: {result['generated_at']}",
        f"- Unity root: `{result['unity_root']}`",
        f"- Wwise root: `{result['wwise_root']}`",
        "",
        "## Executive Summary",
        "",
        f"- Runtime validation average: **{result['runtime_validation_average']}%**",
        f"- Modules with issues: **{result['modules_with_issues']}** / {len(result['modules'])}",
        f"- Logs scanned for this day: **{len(result['log_scan']['logs_scanned'])}**",
        f"- Audio-related log lines in scanned tail windows: **{result['log_scan']['audio_line_count']}**",
        f"- Top risk: {result['top_risk']}",
        "",
        "## Source Quality",
        "",
        table(
            [
                ["Completeness", source["completeness"]],
                ["Freshness", source["freshness"]],
                ["Precision", source["precision"]],
                ["Traceability", source["traceability"]],
                ["Coverage", source["coverage"]],
            ],
            ["Dimension", "Assessment"],
        ),
        "",
        "## Module Completion And Issues",
        "",
        table(module_rows, ["Module", "SABC", "Status", "Runtime Completion", "Observed Lines", "Issues", "Evidence", "Next Action"]),
        "",
        "## Problem Backlog",
        "",
        table(problem_rows, ["Module", "Type", "Subject", "Count", "Source", "Evidence"]),
        "",
        "## Logs Scanned",
        "",
        table(
            [[item["path"], item["modified"], item["size_mb"]] for item in result["log_scan"]["logs_scanned"]],
            ["Log", "Modified", "MB"],
        ),
        "",
        "## Interpretation Rules",
        "",
        "- `Runtime Completion` means evidence coverage from logs/reports, not feature production completion.",
        "- `NotObserved` is not pass or fail. It means the captured session did not exercise the module.",
        "- Historical trend issues are retained as risks until a newer targeted runtime session proves they are gone.",
        "- If Event `.bnk` files exist but logs still show Bank load failure, prioritize Unity/Wwise bank lifecycle and path resolution.",
        "",
    ]
    return "\n".join(lines)


def source_quality(day: dt.date, monitor: dict[str, Any], trend: dict[str, Any], bank_check: dict[str, Any], log_result: dict[str, Any], profile: dict[str, Any]) -> dict[str, str]:
    logs = log_result.get("logs_scanned") or []
    monitor_date = str((monitor.get("summary") or {}).get("last_updated", ""))
    bank_date = str(bank_check.get("generated_at", ""))
    coverage = monitor.get("coverage_matrix") or []
    observed = sum(int(row.get("observed_audio_lines") or 0) for row in coverage)
    not_observed = sum(1 for row in coverage if row.get("status") == "NotObserved")
    return {
        "completeness": f"B+: 已接入 module_profile({len(profile.get('modules') or [])} modules)、runtime monitor、trend、bank check、Wwise audit 和当日 log；未接入 Jira。",
        "freshness": f"B: 当前日报日期 {day.isoformat()}；monitor latest={monitor_date or 'missing'}；bank_check={bank_date or 'missing'}。",
        "precision": "B: 模块映射基于 Event/日志关键词与 QA checklist，能定位问题类型，但需要 tester session metadata 提高精度。",
        "traceability": "A-: 每条问题保留 source、module、type、count、evidence；原始 log 仅扫描 tail window。",
        "coverage": f"C/B: coverage rows={len(coverage)}，observed_audio_lines={observed}，NotObserved={not_observed}；仍需要按 checklist 主动跑场景。",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a daily ProjectEF audio log intelligence report.")
    parser.add_argument("--report-root", default=r"G:\AI\Material\Wwise\报告")
    parser.add_argument("--unity-root", default=r"D:\EF New\Client\TargetProject")
    parser.add_argument("--wwise-root", default=r"D:\EF Wwise\ProjectEF")
    parser.add_argument("--date", help="YYYY-MM-DD. Default: today")
    parser.add_argument("--max-log-mb", type=float, default=80.0)
    parser.add_argument("--module-profile", help="Optional ProjectEF_AudioModuleProfile_*.json path")
    parser.add_argument("--out", required=True)
    parser.add_argument("--json-out")
    args = parser.parse_args()

    report_root = Path(args.report_root)
    day = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    module_profile = load_module_profile(report_root, args.module_profile)
    apply_module_profile(module_profile)

    monitor_json = newest(report_root, "ProjectEF_UnityWwise_GUI_RuntimeAudioMonitor.json")
    trend_json = newest(report_root, "ProjectEF_AudioReport_TrendSummary_*.json") or newest(report_root, "ProjectEF_AudioReport_TrendSummary.json")
    bank_json = newest(report_root, "ProjectEF_RuntimeBankOutput_Check_*.json")
    wwise_json = newest(report_root, "ProjectEF_Wwise工程与资源检测数据_*.json")

    monitor = load_json(monitor_json)
    trend = load_json(trend_json)
    bank_check = load_json(bank_json)
    wwise_audit = load_json(wwise_json)
    logs = discover_logs(Path(args.unity_root))
    log_result = scan_logs(logs, day, args.max_log_mb)
    modules = summarize_modules(monitor, log_result, bank_check, wwise_audit)
    problems = collect_problems(trend, monitor, log_result)
    avg = round(sum(item["runtime_completion_percent"] for item in modules) / max(len(modules), 1), 1)
    issue_modules = sum(1 for item in modules if item["issue_count"])
    top_risk = "No high-confidence new daily log risk captured."
    if problems:
        first = problems[0]
        top_risk = f"{first.get('type')} / {first.get('subject') or first.get('module')} / count={first.get('count')}"

    result = {
        "date": day.isoformat(),
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "unity_root": args.unity_root,
        "wwise_root": args.wwise_root,
        "inputs": {
            "monitor_json": str(monitor_json) if monitor_json else "",
            "trend_json": str(trend_json) if trend_json else "",
            "bank_json": str(bank_json) if bank_json else "",
            "wwise_json": str(wwise_json) if wwise_json else "",
            "module_profile_json": str(module_profile.get("path", "")),
        },
        "source_quality": source_quality(day, monitor, trend, bank_check, log_result, module_profile),
        "runtime_validation_average": avg,
        "modules_with_issues": issue_modules,
        "top_risk": top_risk,
        "modules": modules,
        "problems": problems,
        "log_scan": log_result,
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_markdown(result), encoding="utf-8")
    if args.json_out:
        json_out = Path(args.json_out)
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps(result, ensure_ascii=True, indent=2), encoding="utf-8")
    print(out)
    if args.json_out:
        print(args.json_out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
