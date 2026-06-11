#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any


DEFAULT_WAAPI = "ws://127.0.0.1:8080/waapi"
REPORT_DIR = Path(chr(0x62A5) + chr(0x544A))
VOICE_FIELDS = [
    "pipelineID",
    "playingID",
    "soundID",
    "gameObjectID",
    "gameObjectName",
    "objectGUID",
    "objectName",
    "playTargetID",
    "playTargetGUID",
    "playTargetName",
    "baseVolume",
    "priority",
    "isStarted",
    "isVirtual",
    "isForcedVirtual",
]
PERF_COUNTER_KEYWORDS = (
    "cpu",
    "voice",
    "stream",
    "memory",
    "plugin",
    "source",
    "io",
    "audio",
    "starv",
    "bandwidth",
)
LOG_FINDING_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("VoiceStarvation", re.compile(r"\bvoice starvation\b", re.IGNORECASE)),
    ("SourceStarvation", re.compile(r"\bsource starvation\b", re.IGNORECASE)),
    ("Starvation", re.compile(r"\bstarv(?:ation|ed|ing)?\b", re.IGNORECASE)),
    ("AudioUnderrun", re.compile(r"\b(underrun|xrun|buffer underflow|audio glitch|audio dropout)\b", re.IGNORECASE)),
    ("AudioThreadBudget", re.compile(r"\b(audio thread|dsp|mixer|callback).*\b(cpu|late|slow|blocked|timeout|overrun)\b", re.IGNORECASE)),
    ("StreamingIO", re.compile(r"\b(stream|streaming|i/o|io|disk|read).*\b(slow|timeout|starv|bandwidth|buffer)\b", re.IGNORECASE)),
    ("GeneralPerformance", re.compile(r"\b(cpu|performance|frame|fps|gc alloc|garbage|memory|out of memory|too many)\b", re.IGNORECASE)),
]


def now_stamp() -> str:
    return datetime.now().isoformat(timespec="seconds")


def default_unity_logs() -> list[Path]:
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    if not local:
        return []
    root = local / "Unity" / "Editor"
    return [root / "Editor.log", root / "Editor-prev.log"]


def connect(url: str):
    try:
        from waapi import WaapiClient
    except Exception as exc:
        raise RuntimeError(f"Cannot import waapi Python package: {exc}") from exc
    return WaapiClient(url=url)


def read_new_lines(path: Path, offset: int) -> tuple[list[str], int]:
    if not path.exists():
        return [], offset
    size = path.stat().st_size
    if size < offset:
        offset = 0
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        handle.seek(offset)
        text = handle.read()
        return text.splitlines(), handle.tell()


def normalize_counter_key(value: Any) -> str:
    text = str(value or "").strip()
    return text if text else "<empty>"


def safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def classify_log_line(line: str) -> str | None:
    for kind, pattern in LOG_FINDING_PATTERNS:
        if pattern.search(line):
            return kind
    return None


def is_relevant_performance_counter(item: dict[str, Any]) -> bool:
    haystack = " ".join(
        str(item.get(key, ""))
        for key in ("name", "displayName", "path", "objectName", "counter", "counterName", "stat")
    ).lower()
    return any(keyword in haystack for keyword in PERF_COUNTER_KEYWORDS)


def normalize_performance_counter(item: dict[str, Any]) -> dict[str, Any]:
    name = (
        item.get("name")
        or item.get("displayName")
        or item.get("path")
        or item.get("counterName")
        or item.get("counter")
        or item.get("stat")
        or item.get("id")
        or "<unknown>"
    )
    value = (
        item.get("value")
        if "value" in item
        else item.get("y")
        if "y" in item
        else item.get("currentValue")
        if "currentValue" in item
        else item.get("average")
    )
    return {
        "name": str(name),
        "value": value,
        "unit": item.get("unit") or item.get("units") or "",
    }


def sample_performance_monitor(client) -> tuple[list[dict[str, Any]], str | None]:
    try:
        result = client.call("ak.wwise.core.profiler.getPerformanceMonitor", {"time": "capture"}) or {}
    except Exception as exc:
        return [], str(exc)
    raw_items = result.get("return", [])
    if not isinstance(raw_items, list):
        return [], None
    selected = []
    for item in raw_items:
        if isinstance(item, dict) and is_relevant_performance_counter(item):
            selected.append(normalize_performance_counter(item))
    return selected[:80], None


class RuntimeMetricSampler:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self.psutil = None
        self.processes: list[dict[str, Any]] = []
        self.last_disk: Any = None
        self.last_time = time.monotonic()
        if not enabled:
            return
        try:
            import psutil  # type: ignore

            self.psutil = psutil
            psutil.cpu_percent(interval=None)
            self.last_disk = psutil.disk_io_counters()
            self.processes = self.collect_processes()
            for item in self.processes:
                try:
                    item["process"].cpu_percent(interval=None)
                except Exception:
                    pass
        except Exception:
            self.psutil = None

    def collect_processes(self) -> list[dict[str, Any]]:
        if not self.psutil:
            return []
        tracked = []
        current_pid = os.getpid()
        for proc in self.psutil.process_iter(["pid", "name", "exe", "cmdline"]):
            try:
                if proc.info.get("pid") == current_pid:
                    continue
                name = proc.info.get("name") or ""
                cmdline = " ".join(proc.info.get("cmdline") or [])
                haystack = f"{name} {proc.info.get('exe') or ''} {cmdline}".lower()
                if "unity" in haystack:
                    category = "Unity"
                elif "wwise" in haystack:
                    category = "Wwise"
                elif "projectef" in haystack:
                    category = "ProjectEF"
                else:
                    continue
                tracked.append({"pid": proc.info["pid"], "name": name, "category": category, "process": proc})
            except Exception:
                continue
        return tracked

    def sample(self) -> dict[str, Any]:
        if not self.psutil:
            return {"available": False}
        psutil = self.psutil
        now = time.monotonic()
        metrics: dict[str, Any] = {"available": True}
        try:
            metrics["system_cpu_percent"] = psutil.cpu_percent(interval=None)
        except Exception:
            pass
        try:
            vm = psutil.virtual_memory()
            metrics["memory_percent"] = vm.percent
            metrics["memory_available_mb"] = round(vm.available / (1024 * 1024), 1)
        except Exception:
            pass
        try:
            disk = psutil.disk_io_counters()
            if disk and self.last_disk:
                elapsed = max(now - self.last_time, 0.001)
                metrics["disk_read_mb_s"] = round((disk.read_bytes - self.last_disk.read_bytes) / (1024 * 1024) / elapsed, 3)
                metrics["disk_write_mb_s"] = round((disk.write_bytes - self.last_disk.write_bytes) / (1024 * 1024) / elapsed, 3)
            self.last_disk = disk
            self.last_time = now
        except Exception:
            pass
        process_rows = []
        for item in list(self.processes):
            proc = item["process"]
            try:
                cpu = proc.cpu_percent(interval=None)
                mem = proc.memory_info().rss / (1024 * 1024)
                process_rows.append(
                    {
                        "category": item["category"],
                        "pid": item["pid"],
                        "name": item["name"],
                        "cpu_percent": round(cpu, 2),
                        "rss_mb": round(mem, 1),
                    }
                )
            except Exception:
                continue
        metrics["processes"] = sorted(process_rows, key=lambda row: row.get("cpu_percent", 0), reverse=True)[:12]
        for category in ("Unity", "Wwise", "ProjectEF"):
            metrics[f"{category.lower()}_cpu_percent"] = round(
                sum(row["cpu_percent"] for row in process_rows if row["category"] == category),
                2,
            )
        return metrics


def sample_profiler(client, trigger: str, metric_sampler: RuntimeMetricSampler | None = None) -> dict[str, Any]:
    cursor = client.call("ak.wwise.core.profiler.getCursorTime", {"cursor": "capture"}) or {}
    cursor_time = cursor.get("return")
    voices_result = client.call(
        "ak.wwise.core.profiler.getVoices",
        {"time": "capture"},
        options={"return": VOICE_FIELDS},
    ) or {}
    game_objects_result = client.call(
        "ak.wwise.core.profiler.getGameObjects",
        {"time": "capture"},
    ) or {}
    performance_counters, performance_error = sample_performance_monitor(client)
    voices = voices_result.get("return", [])
    game_objects = game_objects_result.get("return", [])
    sample = {
        "sampled_at": now_stamp(),
        "trigger": trigger,
        "cursor_time_ms": cursor_time,
        "voice_count": len(voices),
        "virtual_voice_count": sum(1 for item in voices if item.get("isVirtual")),
        "forced_virtual_voice_count": sum(1 for item in voices if item.get("isForcedVirtual")),
        "game_object_count": len(game_objects),
        "voices": voices,
        "game_objects": game_objects,
        "performance_counters": performance_counters,
    }
    if performance_error:
        sample["performance_monitor_error"] = performance_error
    if metric_sampler is not None:
        sample["runtime_metrics"] = metric_sampler.sample()
    return sample


def top_counts(samples: list[dict[str, Any]], key: str, limit: int = 20) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    for sample in samples:
        for voice in sample.get("voices", []):
            counter[normalize_counter_key(voice.get(key))] += 1
    return [{"value": value, "count": count} for value, count in counter.most_common(limit)]


def numeric_metric_values(samples: list[dict[str, Any]], key: str) -> list[float]:
    values = []
    for sample in samples:
        value = safe_float((sample.get("runtime_metrics") or {}).get(key))
        if value is not None:
            values.append(value)
    return values


def metric_stats(samples: list[dict[str, Any]], key: str) -> dict[str, float | None]:
    values = numeric_metric_values(samples, key)
    if not values:
        return {"avg": None, "max": None}
    return {"avg": round(mean(values), 2), "max": round(max(values), 2)}


def performance_counter_stats(samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, list[float]] = defaultdict(list)
    units: dict[str, str] = {}
    for sample in samples:
        for item in sample.get("performance_counters", []):
            name = normalize_counter_key(item.get("name"))
            value = safe_float(item.get("value"))
            if value is None:
                continue
            buckets[name].append(value)
            units[name] = str(item.get("unit") or "")
    rows = []
    for name, values in buckets.items():
        if not values:
            continue
        rows.append({"name": name, "max": round(max(values), 3), "avg": round(mean(values), 3), "unit": units.get(name, "")})
    return sorted(rows, key=lambda row: row["max"], reverse=True)[:30]


def max_performance_value(stats: list[dict[str, Any]], include: tuple[str, ...]) -> float | None:
    candidates = []
    for item in stats:
        name = item.get("name", "").lower()
        if all(token in name for token in include):
            value = safe_float(item.get("max"))
            if value is not None:
                candidates.append(value)
    return max(candidates) if candidates else None


def summarize(
    samples: list[dict[str, Any]],
    trigger_lines: list[dict[str, Any]],
    runtime_findings: list[dict[str, Any]],
) -> dict[str, Any]:
    finding_counts = Counter(item.get("kind", "Unknown") for item in runtime_findings)
    perf_stats = performance_counter_stats(samples)
    performance_monitor_errors = Counter(
        sample.get("performance_monitor_error") for sample in samples if sample.get("performance_monitor_error")
    )
    if not samples:
        return {
            "status": "NO_SAMPLES",
            "sample_count": 0,
            "max_voice_count": 0,
            "max_virtual_voice_count": 0,
            "trigger_count": len(trigger_lines),
            "runtime_finding_counts": dict(finding_counts),
            "performance_counters": [],
            "performance_monitor_errors": {},
        }
    max_sample = max(samples, key=lambda item: item.get("voice_count", 0))
    trigger_samples = [item for item in samples if item.get("trigger", "").startswith("unity_log")]
    return {
        "status": "VOICES_CAPTURED" if max_sample.get("voice_count", 0) > 0 else "NO_ACTIVE_VOICES_CAPTURED",
        "sample_count": len(samples),
        "trigger_count": len(trigger_lines),
        "trigger_sample_count": len(trigger_samples),
        "runtime_finding_counts": dict(finding_counts),
        "max_voice_count": max_sample.get("voice_count", 0),
        "max_virtual_voice_count": max_sample.get("virtual_voice_count", 0),
        "max_forced_virtual_voice_count": max_sample.get("forced_virtual_voice_count", 0),
        "max_voice_sample_time": max_sample.get("sampled_at"),
        "max_voice_cursor_time_ms": max_sample.get("cursor_time_ms"),
        "system_cpu_percent": metric_stats(samples, "system_cpu_percent"),
        "memory_percent": metric_stats(samples, "memory_percent"),
        "disk_read_mb_s": metric_stats(samples, "disk_read_mb_s"),
        "unity_cpu_percent": metric_stats(samples, "unity_cpu_percent"),
        "wwise_cpu_percent": metric_stats(samples, "wwise_cpu_percent"),
        "projectef_cpu_percent": metric_stats(samples, "projectef_cpu_percent"),
        "performance_counters": perf_stats,
        "performance_monitor_errors": dict(performance_monitor_errors),
        "top_object_names": top_counts(samples, "objectName"),
        "top_play_target_names": top_counts(samples, "playTargetName"),
        "top_game_object_names": top_counts(samples, "gameObjectName"),
    }


def add_hypothesis(items: list[dict[str, Any]], area: str, confidence: str, title: str, evidence: str, next_step: str) -> None:
    items.append(
        {
            "area": area,
            "confidence": confidence,
            "title": title,
            "evidence": evidence,
            "next_step": next_step,
        }
    )


def build_root_cause_hypotheses(summary: dict[str, Any], runtime_findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    counts = Counter(item.get("kind", "Unknown") for item in runtime_findings)
    max_voice = int(summary.get("max_voice_count") or 0)
    max_virtual = int(summary.get("max_virtual_voice_count") or 0)
    system_cpu_max = (summary.get("system_cpu_percent") or {}).get("max")
    unity_cpu_max = (summary.get("unity_cpu_percent") or {}).get("max")
    disk_read_max = (summary.get("disk_read_mb_s") or {}).get("max")
    perf_stats = summary.get("performance_counters", [])
    audio_cpu_max = max_performance_value(perf_stats, ("cpu", "audio"))
    voice_starvation = counts.get("VoiceStarvation", 0)
    source_starvation = counts.get("SourceStarvation", 0)
    any_starvation = sum(count for kind, count in counts.items() if "Starvation" in kind)

    if not any_starvation:
        add_hypothesis(
            items,
            "Session Evidence",
            "High",
            "No starvation was observed during this capture window.",
            f"Runtime starvation findings: {dict(counts) or '<none>'}; max active voices: {max_voice}.",
            "Do not treat this as whole-project proof. Re-run while reproducing the problematic scene or device condition.",
        )

    if voice_starvation:
        if system_cpu_max is not None and system_cpu_max >= 90:
            add_hypothesis(
                items,
                "Engine/Machine Budget",
                "High",
                "Voice starvation coincides with very high system CPU.",
                f"VoiceStarvation lines: {voice_starvation}; max system CPU: {system_cpu_max}%.",
                "Ask engineering/QA to profile frame CPU, thread scheduling, and target-device load before changing Wwise voice limits.",
            )
        if unity_cpu_max is not None and unity_cpu_max >= 80 and max_voice < 50:
            add_hypothesis(
                items,
                "Engine Budget",
                "Medium",
                "Unity-side load is high while Wwise active voice count is moderate.",
                f"Max Unity CPU: {unity_cpu_max}%; max active voices: {max_voice}.",
                "Capture Unity Profiler CPU timeline around the starvation timestamp and check audio-thread scheduling.",
            )
        if max_voice >= 70 or max_virtual >= 20:
            add_hypothesis(
                items,
                "Audio Content/Concurrency",
                "Medium",
                "Audio voice concurrency is high enough to review Wwise voice policy.",
                f"Max active voices: {max_voice}; max virtual voices: {max_virtual}.",
                "Inspect top play targets, voice limits, virtual voice behavior, priorities, and ambience/music concurrency.",
            )
        if audio_cpu_max is not None and audio_cpu_max >= 70:
            add_hypothesis(
                items,
                "Audio Thread Budget",
                "Medium",
                "Wwise performance counters suggest high audio CPU.",
                f"Max audio CPU-like performance counter: {audio_cpu_max}.",
                "Open the Wwise Profiler Performance Monitor at the same timestamp and inspect expensive effects, busses, and voices.",
            )
        if max_voice < 50 and not (system_cpu_max is not None and system_cpu_max >= 90) and audio_cpu_max is None:
            add_hypothesis(
                items,
                "Evidence Gap",
                "Low",
                "Voice starvation was logged, but this capture does not yet prove audio content is the root cause.",
                f"Max active voices: {max_voice}; system CPU max: {system_cpu_max}; Wwise audio CPU counter: <not captured>.",
                "Re-run on the target machine with Wwise Performance Monitor counters visible, Unity Profiler CPU timeline, and the same repro steps.",
            )

    if source_starvation:
        if disk_read_max is not None and disk_read_max > 80:
            add_hypothesis(
                items,
                "Streaming/Storage",
                "Medium",
                "Source starvation coincides with notable disk read throughput.",
                f"SourceStarvation lines: {source_starvation}; max disk read: {disk_read_max} MB/s.",
                "Check streamed media bandwidth, disk contention, media location, and target-device IO limits.",
            )
        else:
            add_hypothesis(
                items,
                "Streaming/Storage",
                "Medium",
                "Source starvation points to streaming bandwidth or IO starvation more than authored voice count.",
                f"SourceStarvation lines: {source_starvation}; max active voices: {max_voice}; max disk read: {disk_read_max}.",
                "Review streamed source settings, prefetching, media residency, and platform IO budget with engineering.",
            )

    if counts.get("AudioUnderrun") or counts.get("AudioThreadBudget"):
        add_hypothesis(
            items,
            "Audio Thread Scheduling",
            "Medium",
            "Runtime logs mention underrun or audio-thread budget symptoms.",
            f"AudioUnderrun: {counts.get('AudioUnderrun', 0)}; AudioThreadBudget: {counts.get('AudioThreadBudget', 0)}.",
            "Profile CPU spikes and thread priorities near the log timestamp; verify buffer settings only after profiling.",
        )

    if counts.get("GeneralPerformance") and not any_starvation:
        add_hypothesis(
            items,
            "Session Context",
            "Low",
            "General performance warnings were seen, but no Wwise starvation was captured.",
            f"GeneralPerformance findings: {counts.get('GeneralPerformance', 0)}.",
            "Keep these as context, not as audio-root-cause evidence.",
        )

    return items


def render_metric(value: Any) -> str:
    if value is None:
        return "<none>"
    return str(value)


def render_markdown(payload: dict[str, Any]) -> str:
    summary = payload.get("summary", {})
    hypotheses = payload.get("root_cause_hypotheses", [])
    lines = [
        "# ProjectEF Wwise Profiler Voice Capture",
        "",
        f"- Generated: `{payload.get('generated_at')}`",
        f"- Status: `{summary.get('status')}`",
        f"- Duration: `{payload.get('duration_seconds')}s`",
        f"- Interval: `{payload.get('interval_seconds')}s`",
        f"- WAAPI: `{payload.get('waapi_url')}`",
        f"- Enable profiler data: `{payload.get('enable_profiler_data')}`",
        f"- Start capture: `{payload.get('start_capture')}`",
        f"- Capture start time ms: `{payload.get('capture_start_time_ms')}`",
        f"- Stop capture at end: `{payload.get('stop_capture_at_end')}`",
        f"- Capture stop time ms: `{payload.get('capture_stop_time_ms')}`",
        f"- System metrics: `{payload.get('system_metrics')}`",
        "",
        "## Summary",
        "",
        f"- Samples: `{summary.get('sample_count', 0)}`",
        f"- Unity log Voice Starvation triggers: `{summary.get('trigger_count', 0)}`",
        f"- Runtime finding counts: `{summary.get('runtime_finding_counts', {})}`",
        f"- Trigger samples: `{summary.get('trigger_sample_count', 0)}`",
        f"- Max active voices: `{summary.get('max_voice_count', 0)}`",
        f"- Max virtual voices: `{summary.get('max_virtual_voice_count', 0)}`",
        f"- Max forced virtual voices: `{summary.get('max_forced_virtual_voice_count', 0)}`",
        f"- Max voice sample time: `{summary.get('max_voice_sample_time', '')}`",
        f"- Max voice cursor time ms: `{summary.get('max_voice_cursor_time_ms', '')}`",
        "",
        "## Root Cause Hypotheses",
        "",
        "| Area | Confidence | Hypothesis | Evidence | Next Step |",
        "|---|---|---|---|---|",
    ]
    for item in hypotheses:
        lines.append(
            f"| `{item.get('area')}` | `{item.get('confidence')}` | {item.get('title')} | {item.get('evidence')} | {item.get('next_step')} |"
        )
    if not hypotheses:
        lines.append("| `<none>` |  | No hypothesis could be built. | No samples or no usable evidence. | Re-run with Wwise and Unity open. |")

    lines.extend(
        [
            "",
            "## Machine / Engine Metrics",
            "",
            "| Metric | Average | Max |",
            "|---|---:|---:|",
        ]
    )
    for title, key in [
        ("System CPU %", "system_cpu_percent"),
        ("Memory %", "memory_percent"),
        ("Disk Read MB/s", "disk_read_mb_s"),
        ("Unity CPU %", "unity_cpu_percent"),
        ("Wwise CPU %", "wwise_cpu_percent"),
        ("ProjectEF CPU %", "projectef_cpu_percent"),
    ]:
        stats = summary.get(key) or {}
        lines.append(f"| {title} | `{render_metric(stats.get('avg'))}` | `{render_metric(stats.get('max'))}` |")

    lines.extend(["", "## Wwise Performance Counters", "", "| Counter | Average | Max | Unit |", "|---|---:|---:|---|"])
    for item in summary.get("performance_counters", [])[:20]:
        lines.append(f"| `{item.get('name')}` | `{item.get('avg')}` | `{item.get('max')}` | `{item.get('unit')}` |")
    if not summary.get("performance_counters"):
        lines.append("| `<none captured>` |  |  |  |")
    if summary.get("performance_monitor_errors"):
        lines.extend(["", "Performance monitor WAAPI errors:", ""])
        for error, count in summary.get("performance_monitor_errors", {}).items():
            lines.append(f"- `{count}` samples: `{error}`")

    for title, key in [
        ("Top Object Names", "top_object_names"),
        ("Top Play Target Names", "top_play_target_names"),
        ("Top Game Object Names", "top_game_object_names"),
    ]:
        lines.extend([f"", f"## {title}", "", "| Value | Count |", "|---|---:|"])
        for item in summary.get(key, [])[:20]:
            lines.append(f"| `{item.get('value')}` | {item.get('count')} |")
        if not summary.get(key):
            lines.append("| `<none>` | 0 |")

    lines.extend(["", "## Runtime Findings", "", "| Time | Kind | Log | Line |", "|---|---|---|---|"])
    for item in payload.get("runtime_findings", [])[:80]:
        line = str(item.get("line", "")).replace("|", "\\|")
        lines.append(f"| `{item.get('detected_at')}` | `{item.get('kind')}` | `{item.get('path')}` | `{line}` |")
    if not payload.get("runtime_findings"):
        lines.append("| `<none>` |  |  |  |")

    lines.extend(["", "## Tool Errors", "", "| Error |", "|---|"])
    for item in payload.get("errors", []):
        lines.append(f"| `{item}` |")
    if not payload.get("errors"):
        lines.append("| `<none>` |")

    lines.extend(
        [
            "",
            "## Interpretation Boundary",
            "",
            "- This report separates audio-content evidence from engine, thread scheduling, streaming IO, and machine budget evidence.",
            "- Voice Starvation is not automatically an audio-design bug. Treat it as a runtime performance symptom until correlated evidence points to a specific owner.",
            "- Source Starvation is often a streaming or IO budget symptom. Check streamed media and platform storage before assuming the source asset itself is wrong.",
            "- A single capture only proves what happened in this session window. Unplayed scenes and systems remain untested.",
        ]
    )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture Wwise Profiler voice owners for ProjectEF runtime starvation diagnosis.")
    parser.add_argument("--waapi", default=DEFAULT_WAAPI)
    parser.add_argument("--duration", type=float, default=60.0)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--enable-profiler-data", action="store_true")
    parser.add_argument("--start-capture", action="store_true")
    parser.add_argument("--stop-capture-at-end", action="store_true")
    parser.add_argument("--watch-unity-log", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--system-metrics", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--log", action="append", default=[], help="Unity log path to watch. Can be provided multiple times.")
    parser.add_argument("--out", default=None)
    parser.add_argument("--json-out", default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    REPORT_DIR.mkdir(exist_ok=True)
    logs = [Path(item) for item in args.log] if args.log else default_unity_logs()
    log_offsets = {path: path.stat().st_size if path.exists() else 0 for path in logs}
    samples: list[dict[str, Any]] = []
    trigger_lines: list[dict[str, Any]] = []
    runtime_findings: list[dict[str, Any]] = []
    errors: list[str] = []
    metric_sampler = RuntimeMetricSampler(args.system_metrics)
    if args.system_metrics and metric_sampler.psutil is None:
        errors.append("system metrics unavailable: psutil could not be imported or initialized")
    start_time = time.monotonic()
    generated_at = now_stamp()
    file_stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_path = Path(args.out) if args.out else REPORT_DIR / f"ProjectEF_WwiseProfilerVoiceCapture_{file_stamp}.md"
    json_out_path = Path(args.json_out) if args.json_out else REPORT_DIR / f"ProjectEF_WwiseProfilerVoiceCapture_{file_stamp}.json"
    capture_start_time_ms: int | None = None
    capture_stop_time_ms: int | None = None
    info: dict[str, Any] = {}

    with connect(args.waapi) as client:
        info = client.call("ak.wwise.core.getInfo", {}) or {}
        if args.enable_profiler_data:
            try:
                client.call(
                    "ak.wwise.core.profiler.enableProfilerData",
                    {
                        "dataTypes": [
                            {"dataType": "voices"},
                            {"dataType": "voiceInspector"},
                            {"dataType": "apiCalls"},
                            {"dataType": "gameSyncs"},
                        ]
                    },
                )
            except Exception as exc:
                errors.append(f"enableProfilerData failed: {exc}")
        if args.start_capture:
            try:
                result = client.call("ak.wwise.core.profiler.startCapture", {}) or {}
                capture_start_time_ms = result.get("return")
            except Exception as exc:
                errors.append(f"startCapture failed: {exc}")
        try:
            while time.monotonic() - start_time <= args.duration:
                try:
                    samples.append(sample_profiler(client, "interval", metric_sampler))
                except Exception as exc:
                    errors.append(f"sample failed: {exc}")
                if args.watch_unity_log:
                    for path in logs:
                        lines, offset = read_new_lines(path, log_offsets.get(path, 0))
                        log_offsets[path] = offset
                        for line in lines:
                            kind = classify_log_line(line)
                            if not kind:
                                continue
                            item = {"detected_at": now_stamp(), "kind": kind, "path": str(path), "line": line}
                            runtime_findings.append(item)
                            if kind == "VoiceStarvation":
                                trigger_lines.append(item)
                            if "Starvation" in kind or kind in {"AudioUnderrun", "AudioThreadBudget"}:
                                try:
                                    samples.append(sample_profiler(client, f"unity_log:{path.name}:{kind}", metric_sampler))
                                except Exception as exc:
                                    errors.append(f"trigger sample failed: {exc}")
                time.sleep(max(args.interval, 0.1))
        finally:
            if args.stop_capture_at_end:
                try:
                    result = client.call("ak.wwise.core.profiler.stopCapture", {}) or {}
                    capture_stop_time_ms = result.get("return")
                except Exception as exc:
                    errors.append(f"stopCapture failed: {exc}")

    summary = summarize(samples, trigger_lines, runtime_findings)
    root_cause_hypotheses = build_root_cause_hypotheses(summary, runtime_findings)
    payload = {
        "generated_at": generated_at,
        "finished_at": now_stamp(),
        "waapi_url": args.waapi,
        "wwise_version": (info.get("version") or {}).get("displayName"),
        "wwise_build": (info.get("version") or {}).get("build") or info.get("build"),
        "session_id": info.get("sessionId"),
        "duration_seconds": args.duration,
        "interval_seconds": args.interval,
        "enable_profiler_data": args.enable_profiler_data,
        "start_capture": args.start_capture,
        "capture_start_time_ms": capture_start_time_ms,
        "stop_capture_at_end": args.stop_capture_at_end,
        "capture_stop_time_ms": capture_stop_time_ms,
        "watch_unity_log": args.watch_unity_log,
        "system_metrics": args.system_metrics,
        "logs": [str(path) for path in logs],
        "summary": summary,
        "root_cause_hypotheses": root_cause_hypotheses,
        "trigger_lines": trigger_lines,
        "runtime_findings": runtime_findings,
        "samples": samples,
        "errors": errors,
    }
    json_out = json_out_path
    md_out = out_path
    json_out.parent.mkdir(parents=True, exist_ok=True)
    md_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_out.write_text(render_markdown(payload), encoding="utf-8")
    print(json_out)
    print(md_out)
    print(json.dumps(payload["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
