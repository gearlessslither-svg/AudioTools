#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


TOOL_DIR = Path(__file__).resolve().parent
WORKSPACE_ROOT = TOOL_DIR.parent
DEFAULT_WWISE_ROOT = Path(r"D:\EF Wwise\ProjectEF")
DEFAULT_UNITY_ROOT = Path(r"D:\EF New\Client\TargetProject")
DEFAULT_REPORT_DIR = WORKSPACE_ROOT / "Reports"
DEFAULT_WAAPI = "ws://127.0.0.1:8080/waapi"
DEFAULT_LOCAL_LLM_URL = "http://127.0.0.1:11434"
DEFAULT_LOCAL_MODEL = "qwen3:8b"
DEFAULT_REMOTE_URL = "https://api.openai.com/v1"
DEFAULT_REMOTE_MODEL = "gpt-5-mini"

EVENT_TOKEN_RE = re.compile(
    r"\b(?:Play|Stop|Pause|Resume|Set|Reset|Mute|Unmute|Stinger|Music|VO|UI|SFX|Amb|Loop)_[A-Za-z0-9_]+\b"
)
GUID_RE = re.compile(r"\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}")
WORD_TOKEN_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9_]{2,}\b")
WWISE_PATH_RE = re.compile(r"(?:\\(?:Actor-Mixer Hierarchy|Events|Game Parameters|States|Switches|Master-Mixer Hierarchy)\\[^\s\"']+)")
GAME_HINT_RE = re.compile(
    r"(unity|game|runtime|联调|游戏|日志|log|报错|报错|error|warning|player\.log|editor\.log|"
    r"bank|bnk|wem|postevent|loadbank|setswitch|setrtpc|setstate|soundbank)",
    re.IGNORECASE,
)
WWISE_HINT_RE = re.compile(r"(wwise内|wwise 内|authoring|soundcaster|transport|profiler|容器|节点|event)", re.IGNORECASE)

COMMON_WORDS = {
    "why",
    "what",
    "when",
    "where",
    "event",
    "wwise",
    "unity",
    "audio",
    "sound",
    "game",
    "debug",
    "log",
    "error",
    "warn",
    "warning",
    "failed",
    "fail",
    "play",
    "stop",
    "trigger",
    "runtime",
    "local",
    "remote",
    "online",
    "mode",
}


sys.path.insert(0, str(TOOL_DIR))
try:
    import debug_projectef_wwise_node as wwise_node
except Exception as exc:  # noqa: BLE001
    wwise_node = None
    WWISE_NODE_IMPORT_ERROR = str(exc)
else:
    WWISE_NODE_IMPORT_ERROR = ""


@dataclass
class TargetCandidate:
    query: str
    id: str = ""
    name: str = ""
    type: str = ""
    path: str = ""
    source: str = "rules"
    score: int = 0

    def key(self) -> str:
        return self.id or self.path or self.query.lower()

    def display(self) -> str:
        if self.path:
            return self.path
        return self.name or self.query


@dataclass
class RouteResult:
    mode: str
    source: str
    reason: str
    raw: str = ""
    data: dict[str, Any] | None = None


def safe_slug(text: str, fallback: str = "Scenario") -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in text.strip())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return (cleaned or fallback)[:64]


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig", errors="replace"))
    except Exception:
        return None


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def extract_json_object(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    candidates = [text.strip()]
    fenced = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL | re.IGNORECASE)
    candidates.extend(fenced)
    first = text.find("{")
    last = text.rfind("}")
    if first >= 0 and last > first:
        candidates.append(text[first : last + 1])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            continue
    return None


def llm_prompt(description: str) -> str:
    return (
        "You are extracting inputs for a Wwise/Unity audio debug tool. "
        "Return strict JSON only with keys: debug_mode, targets, log_keywords, scenario. "
        "debug_mode must be one of wwise, game, both, auto. targets are Wwise Event/object names, ids, or paths. "
        "Do not diagnose. Description:\n"
        f"{description}"
    )


def post_json(url: str, payload: dict[str, Any], headers: dict[str, str], timeout: int) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def call_local_extractor(description: str, base_url: str, model: str, timeout: int) -> RouteResult:
    base = base_url.rstrip("/")
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Return valid JSON only."},
            {"role": "user", "content": llm_prompt(description)},
        ],
        "stream": False,
        "options": {"temperature": 0.0},
    }
    response = post_json(f"{base}/api/chat", payload, {"Content-Type": "application/json"}, timeout)
    raw = ((response.get("message") or {}).get("content") or "").strip()
    data = extract_json_object(raw)
    if not data:
        raise RuntimeError("local model did not return parseable JSON")
    return RouteResult("local", f"local:ollama:{model}", f"local extractor via {base}", raw, data)


def call_remote_extractor(description: str, base_url: str, model: str, api_key: str, timeout: int) -> RouteResult:
    if not api_key:
        raise RuntimeError("missing OPENAI_API_KEY or --remote-api-key")
    base = base_url.rstrip("/")
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Return valid JSON only."},
            {"role": "user", "content": llm_prompt(description)},
        ],
        "temperature": 0,
    }
    response = post_json(
        f"{base}/chat/completions",
        payload,
        {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        timeout,
    )
    raw = (((response.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
    data = extract_json_object(raw)
    if not data:
        raise RuntimeError("remote model did not return parseable JSON")
    return RouteResult("remote", f"remote:{model}", f"remote extractor via {base}", raw, data)


def route_extraction(description: str, args: argparse.Namespace) -> RouteResult:
    mode = (args.ai_mode or "auto").lower()
    errors: list[str] = []
    if mode in {"remote", "auto"}:
        try:
            key = args.remote_api_key or os.environ.get("OPENAI_API_KEY", "")
            return call_remote_extractor(description, args.remote_base_url, args.remote_model, key, args.ai_timeout)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"remote: {exc}")
            if mode == "remote":
                return RouteResult("rules", "rules", "; ".join(errors))
    if mode in {"local", "auto"}:
        try:
            return call_local_extractor(description, args.local_base_url, args.local_model, args.ai_timeout)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"local: {exc}")
            if mode == "local":
                return RouteResult("rules", "rules", "; ".join(errors))
    return RouteResult("rules", "rules", "rule extractor" if not errors else "fallback to rules; " + "; ".join(errors))


def load_index(wwise_root: Path) -> Any:
    if wwise_node is None:
        raise RuntimeError(f"Could not import debug_projectef_wwise_node.py: {WWISE_NODE_IMPORT_ERROR}")
    index = wwise_node.WwiseIndex(wwise_root)
    index.scan()
    return index


def candidate_from_obj(query: str, obj: Any, source: str, score: int) -> TargetCandidate:
    return TargetCandidate(
        query=query,
        id=getattr(obj, "id", ""),
        name=getattr(obj, "name", ""),
        type=getattr(obj, "type", ""),
        path=getattr(obj, "path", ""),
        source=source,
        score=score,
    )


def add_resolved_candidate(index: Any, candidates: dict[str, TargetCandidate], query: str, source: str, score: int) -> None:
    query = (query or "").strip().strip("`\"'")
    if not query:
        return
    try:
        matches = index.resolve(query)
    except Exception:
        matches = []
    if not matches:
        candidates.setdefault(query.lower(), TargetCandidate(query=query, source=source, score=score))
        return
    matches = sorted(
        matches,
        key=lambda obj: (
            0 if getattr(obj, "name", "").lower() == query.lower() else 1,
            0 if getattr(obj, "type", "") == "Event" and query.lower().startswith(("play_", "stop_")) else 1,
            len(getattr(obj, "path", "")),
        ),
    )
    for obj in matches[:3]:
        item = candidate_from_obj(query, obj, source, score)
        previous = candidates.get(item.key())
        if previous is None or item.score > previous.score:
            candidates[item.key()] = item


def rule_targets(description: str, index: Any, max_targets: int) -> list[TargetCandidate]:
    candidates: dict[str, TargetCandidate] = {}
    for match in GUID_RE.findall(description):
        add_resolved_candidate(index, candidates, match, "guid", 100)
    for match in WWISE_PATH_RE.findall(description):
        add_resolved_candidate(index, candidates, match, "path", 95)
    for match in EVENT_TOKEN_RE.findall(description):
        add_resolved_candidate(index, candidates, match, "event-token", 90)
    for quoted in re.findall(r"[`\"']([^`\"']{3,160})[`\"']", description):
        add_resolved_candidate(index, candidates, quoted, "quoted", 80)
    for token in WORD_TOKEN_RE.findall(description):
        if token.lower() in COMMON_WORDS:
            continue
        if "_" in token or token[:1].isupper():
            add_resolved_candidate(index, candidates, token, "word", 70)

    resolved = [item for item in candidates.values() if item.id or item.path]
    unresolved = [item for item in candidates.values() if not (item.id or item.path)]
    ordered = sorted(
        resolved,
        key=lambda item: (
            -item.score,
            0 if item.type == "Event" and item.name.lower().startswith(("play_", "stop_")) else 1,
            0 if item.name.lower() == item.query.lower() else 1,
            len(item.path),
        ),
    )
    return (ordered + unresolved)[:max_targets]


def merge_model_targets(route: RouteResult, rule_items: list[TargetCandidate], index: Any, max_targets: int) -> list[TargetCandidate]:
    candidates: dict[str, TargetCandidate] = {item.key(): item for item in rule_items}
    data = route.data or {}
    for target in data.get("targets") or []:
        if isinstance(target, dict):
            query = str(target.get("name") or target.get("query") or target.get("path") or target.get("id") or "")
        else:
            query = str(target)
        add_resolved_candidate(index, candidates, query, route.source, 85)
    return sorted(candidates.values(), key=lambda item: (-item.score, item.display().lower()))[:max_targets]


def infer_debug_mode(description: str, route: RouteResult, explicit: str, has_targets: bool) -> str:
    if explicit != "auto":
        return explicit
    data_mode = str((route.data or {}).get("debug_mode") or "").lower()
    if data_mode in {"wwise", "game", "both"}:
        return data_mode
    game = bool(GAME_HINT_RE.search(description))
    wwise = bool(WWISE_HINT_RE.search(description)) or has_targets
    if game and wwise:
        return "both"
    if game:
        return "game"
    return "wwise" if wwise else "game"


def event_names_for_candidate(index: Any, candidate: TargetCandidate) -> list[str]:
    if not candidate.id or candidate.id not in index.objects:
        return [candidate.name] if candidate.name and candidate.type == "Event" else []
    obj = index.objects[candidate.id]
    if obj.type == "Event":
        return [obj.name]
    target_ids = index.subtree_ids(obj.id)
    events = index.related_events(target_ids)
    names = []
    for item in events:
        event = item.get("event")
        if event and event.name not in names:
            names.append(event.name)
    return names


def run_wwise_node_debug(
    query: str,
    wwise_root: Path,
    waapi: str,
    out_dir: Path,
    duration: float,
    no_transport: bool,
) -> dict[str, Any]:
    script = TOOL_DIR / "debug_projectef_wwise_node.py"
    cmd = [
        sys.executable,
        "-B",
        str(script),
        query,
        "--project-root",
        str(wwise_root),
        "--waapi",
        waapi,
        "--duration",
        str(duration),
        "--out-dir",
        str(out_dir),
    ]
    if no_transport:
        cmd.append("--no-transport")
    started = time.perf_counter()
    completed = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    elapsed = round(time.perf_counter() - started, 3)
    stdout = (completed.stdout or "").strip()
    summary = extract_json_object(stdout) or {}
    payload = None
    json_path = Path(summary.get("json_report", "")) if summary.get("json_report") else None
    if json_path and json_path.exists():
        payload = read_json(json_path)
    return {
        "query": query,
        "returncode": completed.returncode,
        "elapsed_seconds": elapsed,
        "summary": summary,
        "payload": payload,
        "stdout": stdout[-4000:],
        "stderr": (completed.stderr or "").strip()[-4000:],
    }


def load_log_module() -> Any | None:
    path = TOOL_DIR / "ProjectEF_UnityWwise_AudioLogMonitor_GUI.py"
    if not path.exists():
        return None
    import importlib.util

    spec = importlib.util.spec_from_file_location("projectef_audio_log_monitor_gui", path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def latest_bank_report() -> dict[str, Any]:
    roots = [WORKSPACE_ROOT, WORKSPACE_ROOT / "Reports", WORKSPACE_ROOT / "报告"]
    candidates: list[Path] = []
    for root in roots:
        if root.exists():
            candidates.extend(path for path in root.glob("ProjectEF_RuntimeBankOutput_Check_*.json") if path.is_file())
    if not candidates:
        return {"status": "missing", "source_json": ""}
    path = max(candidates, key=lambda p: p.stat().st_mtime)
    data = read_json(path) or {}
    data["source_json"] = str(path)
    data.setdefault("status", "loaded")
    return data


def log_focus_keywords(description: str, candidates: list[TargetCandidate], event_names: list[str], route: RouteResult) -> list[str]:
    words = []
    for item in candidates:
        words.extend([item.query, item.name])
    words.extend(event_names)
    data = route.data or {}
    words.extend(str(item) for item in (data.get("log_keywords") or []))
    for token in WORD_TOKEN_RE.findall(description):
        if token.lower() not in COMMON_WORDS and (token.startswith(("Play_", "Stop_")) or "_" in token):
            words.append(token)
    unique = []
    seen = set()
    for word in words:
        text = str(word or "").strip()
        if len(text) < 3:
            continue
        key = text.lower()
        if key not in seen:
            unique.append(text)
            seen.add(key)
    return unique[:80]


def log_issue_signature(entry: dict[str, Any], likely_cause: str, recommendation: str) -> tuple[str, str, str, str]:
    text = entry["text"].lower()
    events = entry.get("events") or []
    event_hint = next((event for event in events if event.lower().startswith(("stop_", "play_"))), events[0] if events else "")
    if "voice starvation" in text:
        return "Performance:VoiceStarvation", "VoiceStarvation", "Wwise voice budget or loop stop logic is suspect.", "Check active voices and loop stop path in Profiler."
    if "source starvation" in text:
        return "Performance:SourceStarvation", "SourceStarvation", "A source could not render/provide audio in time.", "Correlate with voice count, streaming/cache, and missing media."
    if ("load event" in text or "加载event" in text or "鍔犺浇event" in text) and "stop_" in text and ("fail" in text or "failed" in text or "失败" in text or "澶辫触" in text):
        return f"StopEventBankLoadFailed:{event_hint or 'Stop'}", "StopEventBankLoadFailed", "Stop Event bank load failed, so the stop command may not reach Wwise.", "Check Stop bank packaging/load result or stop by playing ID."
    if ("bank" in text or "bnk" in text or "wem" in text or "media" in text) and ("fail" in text or "missing" in text or "not found" in text or "failed" in text):
        return f"BankOrMedia:{event_hint or 'Unknown'}", "BankOrMedia", likely_cause, recommendation
    if entry.get("category") == "RTPCSwitchState":
        return f"RTPCSwitchState:{event_hint or 'Parameter'}", "RTPC/Switch/State", likely_cause, recommendation
    if entry.get("category") == "Event":
        return f"Event:{event_hint or 'Unknown'}", "Event", likely_cause, recommendation
    return f"{entry.get('category')}:{entry.get('severity')}", entry.get("category", "Audio"), likely_cause, recommendation


def group_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    severity_rank = {"Error": 3, "Warn": 2, "Info": 1}
    for finding in findings:
        key, issue_type, cause, rec = log_issue_signature(
            finding,
            finding.get("likely_cause", ""),
            finding.get("recommendation", ""),
        )
        key = re.sub(r"[^A-Za-z0-9_.:-]", "_", key)
        group = groups.setdefault(
            key,
            {
                "key": key,
                "type": issue_type,
                "severity": finding["severity"],
                "count": 0,
                "events": [],
                "first": finding["time"],
                "last": finding["time"],
                "confidence": finding.get("confidence", "Low"),
                "likely_cause": cause,
                "recommendation": rec,
                "latest_file": finding["file"],
                "latest_line": finding["line"],
                "latest_evidence": finding["text"],
            },
        )
        group["count"] += 1
        group["last"] = finding["time"]
        group["latest_file"] = finding["file"]
        group["latest_line"] = finding["line"]
        group["latest_evidence"] = finding["text"]
        for event in finding.get("events") or []:
            if event not in group["events"]:
                group["events"].append(event)
        if severity_rank.get(finding["severity"], 0) > severity_rank.get(group["severity"], 0):
            group["severity"] = finding["severity"]
    return sorted(groups.values(), key=lambda item: (-severity_rank.get(item["severity"], 0), -item["count"], item["type"]))


def read_log_tail(path: Path, max_bytes: int) -> tuple[str, int]:
    size = path.stat().st_size
    if size <= max_bytes:
        return path.read_text(encoding="utf-8-sig", errors="replace"), 1
    with path.open("rb") as handle:
        handle.seek(max(0, size - max_bytes))
        raw = handle.read()
    text = raw.decode("utf-8-sig", errors="replace")
    first_newline = text.find("\n")
    if first_newline >= 0:
        text = text[first_newline + 1 :]
    return text, -1


def analyze_runtime_logs(
    description: str,
    candidates: list[TargetCandidate],
    event_names: list[str],
    route: RouteResult,
    unity_root: Path,
    wwise_root: Path,
    explicit_logs: list[Path],
    max_log_bytes: int,
) -> dict[str, Any]:
    module = load_log_module()
    if module is None:
        return {"status": "unavailable", "error": "ProjectEF_UnityWwise_AudioLogMonitor_GUI.py not found"}

    logs = explicit_logs or module.discover_logs(unity_root)
    known_events = module.parse_wwise_events(wwise_root)
    focus = log_focus_keywords(description, candidates, event_names, route)
    focus_lower = [item.lower() for item in focus]

    entries: list[dict[str, Any]] = []
    relevant_entries: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    event_counts: Counter[str] = Counter()
    severity_counts: Counter[str] = Counter()
    category_counts: Counter[str] = Counter()
    files_scanned = []

    for path in logs:
        if not path.exists() or not path.is_file():
            continue
        files_scanned.append(str(path))
        try:
            text, line_start = read_log_tail(path, max_log_bytes)
        except Exception:
            continue
        for idx, line in enumerate(text.splitlines(), start=1):
            if not module.AUDIO_RE.search(line):
                continue
            line_no = idx if line_start >= 0 else -1
            sev = module.severity(line)
            cat = module.category(line)
            events = module.EVENT_RE.findall(line)
            entry = {
                "time": datetime.now().isoformat(timespec="seconds"),
                "file": str(path),
                "line": line_no,
                "severity": sev,
                "category": cat,
                "events": events,
                "text": line.strip(),
            }
            entries.append(entry)
            severity_counts[sev] += 1
            category_counts[cat] += 1
            for event in events:
                event_counts[event] += 1

            haystack = json.dumps(entry, ensure_ascii=False).lower()
            relevant = not focus_lower or any(keyword in haystack for keyword in focus_lower)
            if relevant:
                relevant_entries.append(entry)

            abnormal = sev in {"Error", "Warn"}
            if module.should_check_unknown_events(cat, line) and events and known_events:
                abnormal = abnormal or any(event not in known_events for event in events)
            if abnormal and (relevant or not focus_lower):
                confidence, cause, rec = module.infer_reason(cat, line, events, known_events)
                findings.append({**entry, "confidence": confidence, "likely_cause": cause, "recommendation": rec})

    observed_events = {event for event in event_names if event_counts.get(event, 0) > 0}
    not_observed_events = [event for event in event_names if event not in observed_events]
    bank = latest_bank_report()
    bank_rows = []
    event_dir = Path(str(bank.get("event_dir") or "")) if bank.get("event_dir") else None
    missing_banks = set(bank.get("missing_event_banks") or [])
    for event in event_names:
        bnk = event_dir / f"{event}.bnk" if event_dir else None
        bank_rows.append(
            {
                "event": event,
                "observed_in_logs": event in observed_events,
                "runtime_bank_missing_reported": event in missing_banks,
                "bank_path": str(bnk) if bnk else "",
                "bank_file_exists": bool(bnk and bnk.exists()),
            }
        )

    issue_groups = group_findings(findings)
    missing_target_banks = [
        row
        for row in bank_rows
        if row.get("bank_path") and not row.get("bank_file_exists")
    ]
    if missing_target_banks:
        issue_groups.append(
            {
                "key": "BankOrMedia:TargetEventBankMissing",
                "type": "BankOrMedia",
                "severity": "Warn",
                "count": len(missing_target_banks),
                "events": [row["event"] for row in missing_target_banks],
                "first": datetime.now().isoformat(timespec="seconds"),
                "last": datetime.now().isoformat(timespec="seconds"),
                "confidence": "Medium",
                "likely_cause": "Target Event bank file was not found under the latest runtime bank output path.",
                "recommendation": "Regenerate/copy SoundBanks and verify the Unity runtime bank output is current before retesting in game.",
                "latest_file": bank.get("source_json", ""),
                "latest_line": 0,
                "latest_evidence": "; ".join(f"{row['event']} -> {row['bank_path']}" for row in missing_target_banks[:8]),
            }
        )
    status = "PASS"
    if issue_groups:
        status = "FAIL" if any(group["severity"] == "Error" for group in issue_groups) else "WARN"
    elif event_names and not observed_events:
        status = "NOT_OBSERVED"
    return {
        "status": status,
        "log_files": files_scanned,
        "focus_keywords": focus,
        "known_wwise_events": len(known_events),
        "audio_lines": len(entries),
        "relevant_audio_lines": len(relevant_entries),
        "severity_counts": dict(severity_counts),
        "category_counts": dict(category_counts),
        "event_counts": dict(event_counts.most_common(40)),
        "observed_target_events": sorted(observed_events),
        "not_observed_target_events": not_observed_events,
        "bank_report": {
            "source_json": bank.get("source_json", ""),
            "status": bank.get("status", ""),
            "authored_event_count": bank.get("authored_event_count", 0),
            "runtime_event_bank_count": bank.get("runtime_event_bank_count", 0),
            "missing_event_banks": len(bank.get("missing_event_banks") or []),
            "extra_event_banks": len(bank.get("extra_event_banks") or []),
        },
        "target_event_bank_status": bank_rows,
        "issue_groups": issue_groups,
        "findings": findings[:200],
        "recent_relevant_entries": relevant_entries[-120:],
    }


def wwise_specific_findings(payload: dict[str, Any] | None) -> list[str]:
    if not payload:
        return []
    lines: list[str] = []
    rows = payload.get("transport_tests") or []
    max_target_voices = max((int(row.get("target_voice_count") or 0) for row in rows), default=0)
    if rows:
        if max_target_voices > 0:
            lines.append(f"WAAPI Transport produced target voices in the sampled matrix (max target voices: {max_target_voices}).")
        else:
            lines.append("WAAPI Transport did not produce target voices in the sampled matrix.")
    static = payload.get("static") or {}
    if static.get("rtpc_overlap_warnings"):
        lines.append("RTPC curve overlap warning: at least one object Volume curve and BlendTrack Volume curve have no sampled audible overlap.")
    if static.get("rtpc_initial_silence_warnings"):
        lines.append("Initial RTPC warning: one or more Volume curves evaluate at or below -96 dB at the initial value.")
    if static.get("empty_switch_branches"):
        lines.append("Switch warning: one or more switch states route to branches with no AudioFileSource.")
    if static.get("missing_sources"):
        lines.append("Source warning: one or more AudioFileSource files are missing under Originals.")
    if not lines:
        lines.append("No specific Wwise blocking pattern was detected by the static/transport checks.")
    return lines


def summarize_overall(wwise_results: list[dict[str, Any]], runtime: dict[str, Any] | None, mode: str, candidates: list[TargetCandidate]) -> tuple[str, list[str]]:
    reasons: list[str] = []
    status = "PASS"
    if not candidates and mode in {"wwise", "both"}:
        status = "NEEDS_TARGET"
        reasons.append("No Wwise Event or object target could be resolved from the description.")
    for result in wwise_results:
        payload = result.get("payload") or {}
        w_status = payload.get("status") or (result.get("summary") or {}).get("status")
        if w_status == "FAIL":
            status = "FAIL"
        elif w_status == "WARN" and status == "PASS":
            status = "WARN"
        for item in wwise_specific_findings(payload):
            reasons.append(f"Wwise {result.get('query')}: {item}")
    if runtime:
        r_status = runtime.get("status")
        if r_status == "FAIL":
            status = "FAIL"
        elif r_status in {"WARN", "NOT_OBSERVED"} and status == "PASS":
            status = "WARN"
        if r_status == "NOT_OBSERVED":
            reasons.append("Runtime logs did not observe the target Event(s) in the scanned session.")
        for group in runtime.get("issue_groups") or []:
            reasons.append(f"Runtime {group['severity']}/{group['type']}: {group['likely_cause']}")
    if not reasons:
        reasons.append("No blocking evidence was found in the selected checks.")
    return status, reasons[:20]


def md_table(headers: list[str], rows: list[list[Any]]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(cell).replace("|", "\\|").replace("\n", "<br>") for cell in row) + " |")
    return lines


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# ProjectEF Audio Debug Assistant Report",
        "",
        "## Summary",
        "",
        f"- Status: `{payload['status']}`",
        f"- Generated: `{payload['generated']}`",
        f"- Debug mode: `{payload['debug_mode']}`",
        f"- AI route: `{payload['ai_route']['source']}`",
        f"- Scenario: {payload['description']}",
        "",
        "## Diagnosis",
        "",
    ]
    lines.extend(f"- {reason}" for reason in payload["status_reasons"])
    lines.extend(
        [
            "",
            "## Target Resolution",
            "",
        ]
    )
    if payload["targets"]:
        lines.extend(
            md_table(
                ["Query", "Type", "Name", "Path", "Source", "Score"],
                [[t["query"], t["type"], t["name"], t["path"], t["source"], t["score"]] for t in payload["targets"]],
            )
        )
    else:
        lines.append("- No Wwise target resolved.")

    if payload.get("wwise_results"):
        lines.extend(["", "## Wwise Local Debug", ""])
        rows = []
        for item in payload["wwise_results"]:
            summary = item.get("summary") or {}
            child = item.get("payload") or {}
            rows.append(
                [
                    item.get("query", ""),
                    child.get("status") or summary.get("status", ""),
                    "; ".join(child.get("status_reasons") or summary.get("reasons") or []),
                    summary.get("markdown_report", ""),
                    item.get("returncode", ""),
                ]
            )
        lines.extend(md_table(["Query", "Status", "Reasons", "Report", "Exit"], rows))
        lines.extend(["", "### Wwise Specific Evidence", ""])
        for item in payload["wwise_results"]:
            for reason in wwise_specific_findings(item.get("payload")):
                lines.append(f"- {item.get('query')}: {reason}")

    runtime = payload.get("runtime_log_debug")
    if runtime:
        lines.extend(["", "## Game Integration Log Debug", ""])
        lines.extend(
            [
                f"- Status: `{runtime.get('status')}`",
                f"- Logs scanned: `{len(runtime.get('log_files') or [])}`",
                f"- Audio lines: `{runtime.get('audio_lines', 0)}`",
                f"- Relevant audio lines: `{runtime.get('relevant_audio_lines', 0)}`",
                f"- Known Wwise Events: `{runtime.get('known_wwise_events', 0)}`",
                f"- Observed target Events: `{', '.join(runtime.get('observed_target_events') or []) or '-'}`",
                f"- Not observed target Events: `{', '.join(runtime.get('not_observed_target_events') or []) or '-'}`",
            ]
        )
        bank = runtime.get("bank_report") or {}
        lines.extend(
            [
                "",
                "### Bank Cross-Check",
                "",
                f"- Source JSON: `{bank.get('source_json') or '-'}`",
                f"- Runtime Event banks: `{bank.get('runtime_event_bank_count', 0)}/{bank.get('authored_event_count', 0)}`",
                f"- Missing Event banks in latest bank report: `{bank.get('missing_event_banks', 0)}`",
            ]
        )
        if runtime.get("target_event_bank_status"):
            lines.extend(
                md_table(
                    ["Event", "Observed In Logs", "Missing In Bank Report", "Bank Exists", "Bank Path"],
                    [
                        [
                            row["event"],
                            row["observed_in_logs"],
                            row["runtime_bank_missing_reported"],
                            row["bank_file_exists"],
                            row["bank_path"],
                        ]
                        for row in runtime["target_event_bank_status"]
                    ],
                )
            )
        if runtime.get("issue_groups"):
            lines.extend(["", "### Runtime Issue Groups", ""])
            lines.extend(
                md_table(
                    ["Severity", "Type", "Count", "Events", "Likely Cause", "Recommendation", "Latest Evidence"],
                    [
                        [
                            group["severity"],
                            group["type"],
                            group["count"],
                            ", ".join(group.get("events") or []),
                            group["likely_cause"],
                            group["recommendation"],
                            f"{group['latest_file']}:{group['latest_line']}<br>{group['latest_evidence']}",
                        ]
                        for group in runtime["issue_groups"]
                    ],
                )
            )
    lines.extend(
        [
            "",
            "## Tool Reuse Decision",
            "",
            "- Wwise local debug uses `Tools/debug_projectef_wwise_node.py` for static WWU checks plus WAAPI Transport/Profiler sampling.",
            "- Game integration debug reuses the classification rules from `Tools/ProjectEF_UnityWwise_AudioLogMonitor_GUI.py` instead of replacing that log monitor.",
            "- The log monitor remains the realtime GUI/follow tool; this assistant is the scenario-level orchestrator and report generator.",
        ]
    )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scenario-level ProjectEF Wwise/Unity audio debugger.")
    parser.add_argument("description", nargs="*", help="Scene/debug description, Event name, or Wwise node name.")
    parser.add_argument("--description", dest="description_text", default="")
    parser.add_argument("--debug-mode", choices=["auto", "wwise", "game", "both"], default="auto")
    parser.add_argument("--ai-mode", choices=["auto", "rules", "local", "remote"], default="auto")
    parser.add_argument("--local-base-url", default=os.environ.get("AUDIO_DEBUG_LOCAL_LLM_URL", DEFAULT_LOCAL_LLM_URL))
    parser.add_argument("--local-model", default=os.environ.get("AUDIO_DEBUG_LOCAL_MODEL", DEFAULT_LOCAL_MODEL))
    parser.add_argument("--remote-base-url", default=os.environ.get("AUDIO_DEBUG_REMOTE_BASE_URL", DEFAULT_REMOTE_URL))
    parser.add_argument("--remote-model", default=os.environ.get("AUDIO_DEBUG_REMOTE_MODEL", DEFAULT_REMOTE_MODEL))
    parser.add_argument("--remote-api-key", default=os.environ.get("AUDIO_DEBUG_REMOTE_API_KEY", ""))
    parser.add_argument("--ai-timeout", type=int, default=5)
    parser.add_argument("--wwise-root", default=str(DEFAULT_WWISE_ROOT))
    parser.add_argument("--unity-root", default=str(DEFAULT_UNITY_ROOT))
    parser.add_argument("--waapi", default=DEFAULT_WAAPI)
    parser.add_argument("--duration", type=float, default=0.35)
    parser.add_argument("--no-transport", action="store_true")
    parser.add_argument("--log", action="append", default=[], help="Explicit Unity/Player/Editor log path. Repeatable.")
    parser.add_argument("--max-log-bytes", type=int, default=20 * 1024 * 1024)
    parser.add_argument("--max-targets", type=int, default=4)
    parser.add_argument("--out-dir", default=str(DEFAULT_REPORT_DIR))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    description = (args.description_text or " ".join(args.description)).strip()
    if not description:
        raise SystemExit("Please provide a scene description, Wwise Event, or node name.")

    started = time.perf_counter()
    wwise_root = Path(args.wwise_root)
    unity_root = Path(args.unity_root)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    index = load_index(wwise_root)
    route = route_extraction(description, args)
    rule_items = rule_targets(description, index, args.max_targets)
    targets = merge_model_targets(route, rule_items, index, args.max_targets)
    debug_mode = infer_debug_mode(description, route, args.debug_mode, bool(targets))

    event_names: list[str] = []
    for target in targets:
        for event in event_names_for_candidate(index, target):
            if event and event not in event_names:
                event_names.append(event)

    wwise_results: list[dict[str, Any]] = []
    if debug_mode in {"wwise", "both"}:
        for target in targets[: args.max_targets]:
            query = target.name or target.query
            if not query:
                continue
            wwise_results.append(
                run_wwise_node_debug(
                    query=query,
                    wwise_root=wwise_root,
                    waapi=args.waapi,
                    out_dir=out_dir,
                    duration=args.duration,
                    no_transport=args.no_transport,
                )
            )

    runtime = None
    if debug_mode in {"game", "both"}:
        runtime = analyze_runtime_logs(
            description=description,
            candidates=targets,
            event_names=event_names,
            route=route,
            unity_root=unity_root,
            wwise_root=wwise_root,
            explicit_logs=[Path(p) for p in args.log],
            max_log_bytes=args.max_log_bytes,
        )

    status, reasons = summarize_overall(wwise_results, runtime, debug_mode, targets)
    payload = {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "description": description,
        "status": status,
        "status_reasons": reasons,
        "debug_mode": debug_mode,
        "ai_route": {
            "requested": args.ai_mode,
            "mode": route.mode,
            "source": route.source,
            "reason": route.reason,
            "data": route.data or {},
        },
        "paths": {
            "workspace_root": str(WORKSPACE_ROOT),
            "wwise_root": str(wwise_root),
            "unity_root": str(unity_root),
        },
        "targets": [target.__dict__ for target in targets],
        "target_events": event_names,
        "wwise_results": wwise_results,
        "runtime_log_debug": runtime,
    }

    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    stem = f"ProjectEF_AudioDebug_{safe_slug(description)}_{stamp}"
    json_path = out_dir / f"{stem}.json"
    md_path = out_dir / f"{stem}.md"
    payload["json_report"] = str(json_path)
    payload["markdown_report"] = str(md_path)
    write_json(json_path, payload)
    md_path.write_text(render_markdown(payload), encoding="utf-8")
    print(
        json.dumps(
            {
                "status": status,
                "debug_mode": debug_mode,
                "markdown_report": str(md_path),
                "json_report": str(json_path),
                "targets": [target.display() for target in targets],
                "reasons": reasons,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if status in {"PASS", "WARN"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
