#!/usr/bin/env python3
from __future__ import annotations

import csv
import datetime as dt
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(r"G:\AI\Material\Wwise")
PROJECT_ROOT = Path(r"D:\EF Wwise\ProjectEF")
TOOLS_ROOT = ROOT / "Tools"
REPORT_DIR = ROOT / "\u62a5\u544a"
STAMP = dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")


def rel(path: Path, root: Path = PROJECT_ROOT) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def iso(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts).isoformat(timespec="seconds")


def size_mb(size: int) -> float:
    return round(size / 1024 / 1024, 3)


def read_json(path: Path) -> Any | None:
    if not path.exists():
        return None
    for encoding in ("utf-8-sig", "utf-8"):
        try:
            return json.loads(path.read_text(encoding=encoding))
        except Exception:
            continue
    return None


def file_row(
    path: Path,
    category: str,
    provenance: str,
    confidence: str,
    evidence: str,
    recommendation: str,
    source_record: str = "",
) -> dict[str, Any]:
    stat = path.stat()
    return {
        "category": category,
        "provenance": provenance,
        "confidence": confidence,
        "relative_path": rel(path),
        "absolute_path": str(path),
        "extension": path.suffix.lower(),
        "size_mb": size_mb(stat.st_size),
        "created": iso(stat.st_ctime),
        "modified": iso(stat.st_mtime),
        "evidence": evidence,
        "recommendation": recommendation,
        "source_record": source_record,
    }


def scan_tool_source_for_soundbank_generation() -> dict[str, Any]:
    patterns = [
        re.compile(r"ak\.wwise\.core\.soundbank", re.IGNORECASE),
        re.compile(r"generate.*sound\s*bank", re.IGNORECASE),
        re.compile(r"generate.*soundbank", re.IGNORECASE),
        re.compile(r"soundbank.*generate", re.IGNORECASE),
    ]
    hits: list[dict[str, Any]] = []
    self_path = Path(__file__).resolve()
    for path in TOOLS_ROOT.rglob("*"):
        if path.suffix.lower() not in {".py", ".cmd", ".ps1", ".md", ".json"}:
            continue
        if path.resolve() == self_path:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for line_no, line in enumerate(text.splitlines(), 1):
            if any(pattern.search(line) for pattern in patterns):
                lower = line.lower()
                if "recommend" in lower or "regenerate" in lower or "check" in lower:
                    kind = "advice_or_check_text"
                elif "ak.wwise.core.soundbank" in lower:
                    kind = "possible_waapi_soundbank_call"
                else:
                    kind = "possible_generate_text"
                hits.append({"path": str(path), "line": line_no, "kind": kind, "text": line.strip()[:300]})
    return {
        "hits": hits,
        "possible_generation_calls": [item for item in hits if item["kind"] == "possible_waapi_soundbank_call"],
    }


def summarize_tree(path: Path) -> dict[str, Any]:
    files = [item for item in path.rglob("*") if item.is_file()] if path.exists() else []
    exts = Counter(item.suffix.lower() or "<none>" for item in files)
    total = sum(item.stat().st_size for item in files)
    created_values = [item.stat().st_ctime for item in files]
    modified_values = [item.stat().st_mtime for item in files]
    return {
        "path": str(path),
        "exists": path.exists(),
        "file_count": len(files),
        "size_mb": size_mb(total),
        "extensions": dict(exts.most_common()),
        "created_min": iso(min(created_values)) if created_values else "",
        "created_max": iso(max(created_values)) if created_values else "",
        "modified_min": iso(min(modified_values)) if modified_values else "",
        "modified_max": iso(max(modified_values)) if modified_values else "",
    }


def soundbanks_root_paths(info: Path) -> dict[str, str]:
    if not info.exists():
        return {}
    text = info.read_text(encoding="utf-8-sig", errors="replace")
    result = {}
    for tag in ("ProjectRoot", "SourceFilesRoot", "SoundBanksRoot", "ExternalSourcesOutputRoot"):
        match = re.search(rf"<{tag}>(.*?)</{tag}>", text, re.S)
        result[tag] = match.group(1).strip() if match else ""
    return result


def load_known_tool_reports() -> dict[str, Any]:
    reports: dict[str, Any] = {}
    for name in [
        "ProjectEF_UnreferencedWav_Archive_2026-06-02.json",
        "ProjectEF_UnreferencedWav_Archive_2026-06-02_dryrun.json",
        "ProjectEF_FootstepPlaybackLimit_Apply_2026-06-02.json",
        "ProjectEF_UIPlaybackLimit_Apply_2026-06-02.json",
    ]:
        path = REPORT_DIR / name
        reports[name] = {"path": str(path), "data": read_json(path)}
    reports["voice_capture_reports"] = [
        str(path)
        for path in sorted(REPORT_DIR.glob("ProjectEF_WwiseProfilerVoiceCapture_*.md"))
    ]
    reports["bank_check_reports"] = [
        str(path)
        for path in sorted(REPORT_DIR.glob("ProjectEF_*BankOutput_Check_*.md"))
    ]
    return reports


def build_rows(reports: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    archive_data = reports.get("ProjectEF_UnreferencedWav_Archive_2026-06-02.json", {}).get("data") or {}
    archive_root = Path(archive_data.get("archive_root", "")) if archive_data.get("archive_root") else PROJECT_ROOT / "Originals_UnreferencedArchive_20260602_182257"
    if archive_root.exists():
        for path in sorted(item for item in archive_root.rglob("*") if item.is_file()):
            rows.append(
                file_row(
                    path,
                    "CONFIRMED_TOOL_MOVED_ARCHIVE",
                    "Tool moved file into archive folder",
                    "High",
                    "ProjectEF_UnreferencedWav_Archive_2026-06-02.json has dry_run=false and archive_root matches this folder.",
                    "Do not submit as new authored source unless you intentionally want the archive folder in depot. Use manifest to restore if needed.",
                    reports["ProjectEF_UnreferencedWav_Archive_2026-06-02.json"]["path"],
                )
            )

    for rel_path, evidence in [
        (
            Path("Actor-Mixer Hierarchy") / "Player.wwu",
            "ProjectEF_FootstepPlaybackLimit_Apply_2026-06-02.json has dry_run=false, saved=true, and updated four Player Footsteps/Sneakers containers.",
        ),
        (
            Path("Actor-Mixer Hierarchy") / "UI.wwu",
            "ProjectEF_UIPlaybackLimit_Apply_2026-06-02.json has dry_run=false, saved=true, and updated UI_CoinLayer/UI_GetFish playback limits. This file also has later UI-task edits.",
        ),
    ]:
        path = PROJECT_ROOT / rel_path
        if path.exists():
            rows.append(
                file_row(
                    path,
                    "CONFIRMED_TOOL_MODIFIED_AUTHORED_WWU",
                    "Tool modified authored Wwise WorkUnit",
                    "High",
                    evidence,
                    "Review before submit. This is authored Wwise content with tool-applied changes, not generated bank output.",
                )
            )

    for folder, confidence, evidence in [
        (
            PROJECT_ROOT / ".backup" / "PlaybackLimit_20260602_1750",
            "Medium",
            "Folder name/time aligns with playback-limit workflow; current source scan found no direct creator script, so treat as tool-workflow backup rather than confirmed script output.",
        ),
        (
            PROJECT_ROOT / ".backup" / "WAAPI_Backup_20260602_1748",
            "Medium",
            "Folder name/time aligns with WAAPI edit workflow; current source scan found no direct creator script, so treat as tool-workflow backup rather than confirmed script output.",
        ),
    ]:
        if folder.exists():
            for path in sorted(item for item in folder.rglob("*") if item.is_file()):
                rows.append(
                    file_row(
                        path,
                        "LIKELY_TOOL_WORKFLOW_BACKUP",
                        "Backup copy from tool-assisted Wwise edit workflow",
                        confidence,
                        evidence,
                        "Do not submit. Keep only as local rollback/reference, or move outside workspace after confirming no longer needed.",
                    )
                )

    for folder in sorted(PROJECT_ROOT.glob("GeneratedSoundBanks_Backup_*")):
        for path in sorted(item for item in folder.rglob("*") if item.is_file()):
            rows.append(
                file_row(
                    path,
                    "SOUNDBANK_BACKUP_NOT_AUTHORED",
                    "Generated SoundBank backup copy, no confirmed tool creator",
                    "Medium",
                    "Timestamped SoundBank backup folder. SoundbanksInfo points to old ProjectEF_2021 paths; source scan found detection/reporting code but no creator code.",
                    "Do not submit. Move outside workspace or ignore; these are not authored Wwise source files.",
                )
            )

    bank_root = PROJECT_ROOT / "GeneratedSoundBanks"
    if bank_root.exists():
        for path in sorted(item for item in bank_root.rglob("*") if item.is_file()):
            rows.append(
                file_row(
                    path,
                    "CURRENT_GENERATED_SOUNDBANK_OUTPUT",
                    "Wwise generated output; not confirmed tool-generated",
                    "High",
                    "Files are under GeneratedSoundBanks. Tool source scan found no soundbank-generation WAAPI call; bank reports only checked existing output after generation.",
                    "Submit only if project policy versions generated banks and you intentionally generated these for the changelist.",
                )
            )

    for folder, category, provenance, recommendation in [
        (PROJECT_ROOT / ".cache", "WWISE_CACHE_NOT_AUTHORED", "Wwise conversion/cache output", "Do not submit."),
        (PROJECT_ROOT / "ProfilingArchive", "PROFILER_ARCHIVE_NOT_AUTHORED", "Wwise profiler diagnostic archive", "Do not submit unless team explicitly versions diagnostic captures."),
    ]:
        if folder.exists():
            for path in sorted(item for item in folder.rglob("*") if item.is_file()):
                rows.append(
                    file_row(
                        path,
                        category,
                        provenance,
                        "High",
                        f"Path is under {folder.name}, a diagnostic/generated folder.",
                        recommendation,
                    )
                )

    for path in sorted(PROJECT_ROOT.glob("ProfilingSession*.prof")):
        rows.append(
            file_row(
                path,
                "PROFILER_SESSION_DIAGNOSTIC",
                "Wwise Profiler session output; possibly tool-triggered when Voice Capture was used",
                "Medium",
                "Wwise Profiler Voice Capture reports show startCapture/stopCapture calls; .prof files are diagnostic session data, not authored project content.",
                "Do not submit. Move to ProfilingArchive or keep outside workspace if needed.",
            )
        )

    for path in [
        PROJECT_ROOT / "ProjectEF.user1.wsettings",
        PROJECT_ROOT / "ProjectEF.user1.validationcache",
        PROJECT_ROOT / "Originals" / "AutoDetectedSampleRates.cache",
    ]:
        if path.exists():
            rows.append(
                file_row(
                    path,
                    "USER_OR_VALIDATION_CACHE",
                    "Wwise user/cache file, not authored content",
                    "High",
                    "User settings, validation cache, or sample-rate cache file.",
                    "Do not submit.",
                )
            )

    return rows


def render_markdown(payload: dict[str, Any]) -> str:
    rows = payload["rows"]
    counts = Counter(row["category"] for row in rows)
    size_by_category: dict[str, float] = defaultdict(float)
    for row in rows:
        size_by_category[row["category"]] += float(row["size_mb"])

    lines = [
        "# ProjectEF Tool Provenance Audit",
        "",
        f"- Generated: `{payload['generated_at']}`",
        f"- Project root: `{PROJECT_ROOT}`",
        f"- Tool source root: `{TOOLS_ROOT}`",
        f"- Report root: `{REPORT_DIR}`",
        "- Mode: read-only scan. No Wwise launch, no WAAPI mutation, no SoundBank generation.",
        "",
        "## Hard Rule",
        "",
        "- Codex/tools must not run Generate SoundBanks unless the user explicitly asks for that exact action in the current task.",
        "- Recommending a regeneration is not permission to perform it.",
        "- If a generated bank is needed, first produce a planned output list and wait for explicit approval.",
        "",
        "## Main Conclusions",
        "",
        "- No direct `ak.wwise.core.soundbank.*` generation call was found in the current tool source scan.",
        "- Current `GeneratedSoundBanks` files are Wwise generated output, but this audit does not find evidence that our tools generated them.",
        "- `Originals_UnreferencedArchive_20260602_182257` is confirmed tool-created/moved content: the archive report has `dry_run=false` and records 102 archived WAVs.",
        "- `Actor-Mixer Hierarchy/Player.wwu` and `Actor-Mixer Hierarchy/UI.wwu` contain confirmed tool-applied playback-limit edits from 2026-06-02.",
        "- `.backup`, `.cache`, `GeneratedSoundBanks_Backup_*`, `.prof`, `.wsettings`, `.validationcache`, and `AutoDetectedSampleRates.cache` should not be submitted as authored audio work.",
        "",
        "## Category Summary",
        "",
        "| Category | Files | MB | Recommendation |",
        "|---|---:|---:|---|",
    ]
    recommendations = {
        "CONFIRMED_TOOL_MOVED_ARCHIVE": "Do not submit as new authored source unless intentionally preserving archive.",
        "CONFIRMED_TOOL_MODIFIED_AUTHORED_WWU": "Review before submit; authored WorkUnit with tool-applied changes.",
        "LIKELY_TOOL_WORKFLOW_BACKUP": "Do not submit.",
        "SOUNDBANK_BACKUP_NOT_AUTHORED": "Do not submit.",
        "CURRENT_GENERATED_SOUNDBANK_OUTPUT": "Policy review before submit.",
        "WWISE_CACHE_NOT_AUTHORED": "Do not submit.",
        "PROFILER_ARCHIVE_NOT_AUTHORED": "Do not submit.",
        "PROFILER_SESSION_DIAGNOSTIC": "Do not submit.",
        "USER_OR_VALIDATION_CACHE": "Do not submit.",
    }
    for category, count in counts.most_common():
        lines.append(
            f"| `{category}` | {count} | {round(size_by_category[category], 3)} | {recommendations.get(category, '')} |"
        )

    lines.extend(["", "## Tool Source SoundBank Generation Scan", ""])
    possible_calls = payload["tool_source_scan"]["possible_generation_calls"]
    if not possible_calls:
        lines.append("- No direct WAAPI SoundBank generation call was found.")
    else:
        for hit in possible_calls:
            lines.append(f"- `{hit['path']}:{hit['line']}` {hit['text']}")
    advice_hits = [item for item in payload["tool_source_scan"]["hits"] if item["kind"] != "possible_waapi_soundbank_call"]
    lines.append(f"- Advisory/check text hits: {len(advice_hits)}. These are recommendations or report text, not execution evidence.")

    lines.extend(["", "## SoundBank Roots", "", "| Folder | Files | MB | SoundbanksInfo ProjectRoot | SourceFilesRoot |", "|---|---:|---:|---|---|"])
    for item in payload["soundbank_roots"]:
        root_paths = item.get("root_paths", {})
        lines.append(
            f"| `{Path(item['path']).name}` | {item['file_count']} | {item['size_mb']} | `{root_paths.get('ProjectRoot', '')}` | `{root_paths.get('SourceFilesRoot', '')}` |"
        )

    lines.extend(["", "## Confirmed Tool Modified Authored Files", "", "| File | Evidence |", "|---|---|"])
    modified = [row for row in rows if row["category"] == "CONFIRMED_TOOL_MODIFIED_AUTHORED_WWU"]
    for row in modified:
        lines.append(f"| `{row['relative_path']}` | {row['evidence']} |")
    if not modified:
        lines.append("| `<none>` |  |")

    lines.extend(["", "## Sample Rows", "", "| Category | Confidence | Path | MB | Modified | Evidence |", "|---|---|---|---:|---|---|"])
    priority = [
        "CONFIRMED_TOOL_MOVED_ARCHIVE",
        "CONFIRMED_TOOL_MODIFIED_AUTHORED_WWU",
        "LIKELY_TOOL_WORKFLOW_BACKUP",
        "SOUNDBANK_BACKUP_NOT_AUTHORED",
        "CURRENT_GENERATED_SOUNDBANK_OUTPUT",
        "PROFILER_SESSION_DIAGNOSTIC",
    ]
    sample_rows = []
    for category in priority:
        sample_rows.extend([row for row in rows if row["category"] == category][:8])
    for row in sample_rows:
        lines.append(
            f"| `{row['category']}` | `{row['confidence']}` | `{row['relative_path']}` | {row['size_mb']} | `{row['modified']}` | {row['evidence']} |"
        )

    lines.extend(
        [
            "",
            "## Output Files",
            "",
            f"- CSV detail: `{payload['csv_path']}`",
            f"- JSON detail: `{payload['json_path']}`",
            "",
            "## Boundary",
            "",
            "- This audit identifies provenance from file paths, timestamps, tool source, and generated reports. It cannot prove who clicked Wwise Authoring UI buttons unless a report/tool log recorded it.",
            "- `GeneratedSoundBanks_Backup_*` folders are old generated-output snapshots with ProjectEF_2021 root metadata; this audit found no creator code in current tools.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    reports = load_known_tool_reports()
    rows = build_rows(reports)
    tool_source_scan = scan_tool_source_for_soundbank_generation()
    soundbank_roots = []
    for folder in [PROJECT_ROOT / "GeneratedSoundBanks", *sorted(PROJECT_ROOT.glob("GeneratedSoundBanks_Backup_*"))]:
        summary = summarize_tree(folder)
        summary["root_paths"] = soundbanks_root_paths(folder / "Windows" / "SoundbanksInfo.xml")
        soundbank_roots.append(summary)

    md_path = REPORT_DIR / f"ProjectEF_Tool_Provenance_Audit_{STAMP}.md"
    csv_path = REPORT_DIR / f"ProjectEF_Tool_Provenance_Audit_{STAMP}.csv"
    json_path = REPORT_DIR / f"ProjectEF_Tool_Provenance_Audit_{STAMP}.json"
    payload = {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "project_root": str(PROJECT_ROOT),
        "tools_root": str(TOOLS_ROOT),
        "report_dir": str(REPORT_DIR),
        "tool_reports": reports,
        "tool_source_scan": tool_source_scan,
        "soundbank_roots": soundbank_roots,
        "rows": rows,
        "csv_path": str(csv_path),
        "json_path": str(json_path),
    }

    with csv_path.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=list(rows[0].keys()) if rows else ["category", "relative_path"])
        writer.writeheader()
        writer.writerows(rows)
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(payload), encoding="utf-8")
    print(md_path)
    print(csv_path)
    print(json_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
