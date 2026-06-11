#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


DEFAULT_WORKSPACE_ROOT = Path(r"D:\EF Wwise")
DEFAULT_PROJECT_ROOT = DEFAULT_WORKSPACE_ROOT / "ProjectEF"
DEFAULT_REPORT_DIR = Path(r"G:\AI\Material\Wwise\报告")
DEFAULT_P4PORT = "ef.p4.blackjack-local.com:1666"
DEFAULT_P4USER = "yupeng"
DEFAULT_P4CLIENT = "yupeng_yupeng_ADMIN-V9BNJMS5N_501206"
DEPOT_TRUNK_MARKER = "/ProjectEFAudio_Trunk/"

AUDIO_EXTS = {".wav", ".wem", ".bnk", ".wwu", ".wproj", ".xml", ".txt"}
SOURCE_AUDIO_EXTS = {".wav", ".aif", ".aiff", ".flac", ".ogg", ".mp3"}
GENERATED_EXTS = {".wem", ".bnk", ".txt", ".xml"}
CACHE_EXTS = {".prof", ".wsettings", ".validationcache", ".log", ".akd", ".cache", ".mdb", ".dat"}
MAX_TABLE_ROWS = 80


def now_stamp() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")


def iso_from_ts(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts).isoformat(timespec="seconds")


def safe_rel(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except Exception:
        return str(path)


def size_mb(size: int) -> float:
    return round(size / 1024 / 1024, 2)


def table(rows: list[list[Any]], headers: list[str], max_rows: int | None = None) -> str:
    if max_rows is not None and len(rows) > max_rows:
        rows = rows[:max_rows] + [[f"... {len(rows) - max_rows} more", *[""] * (len(headers) - 1)]]
    if not rows:
        rows = [["-", *[""] * (len(headers) - 1)]]
    text_rows = [[str(cell) for cell in row] for row in rows]
    all_rows = [headers] + text_rows
    widths = [max(len(row[i]) for row in all_rows) for i in range(len(headers))]
    out = [
        "| " + " | ".join(headers[i].ljust(widths[i]) for i in range(len(headers))) + " |",
        "| " + " | ".join("-" * widths[i] for i in range(len(headers))) + " |",
    ]
    for row in text_rows:
        out.append("| " + " | ".join(row[i].ljust(widths[i]) for i in range(len(headers))) + " |")
    return "\n".join(out)


def path_parts_lower(path: Path) -> list[str]:
    return [part.lower() for part in path.parts]


def has_part(path: Path, name: str) -> bool:
    wanted = name.lower()
    return any(part.lower() == wanted for part in path.parts)


def has_part_prefix(path: Path, prefix: str) -> bool:
    wanted = prefix.lower()
    return any(part.lower().startswith(wanted) for part in path.parts)


def is_under_soundbank_backup(path: Path) -> bool:
    return has_part_prefix(path, "GeneratedSoundBanks_Backup_") or has_part_prefix(path, "_backup_soundbanks_")


def is_under_runtime_backup(path: Path) -> bool:
    return has_part_prefix(path, "_backup_runtime_banks_")


def is_generated_bank(path: Path) -> bool:
    return has_part(path, "GeneratedSoundBanks") and not is_under_soundbank_backup(path)


def is_cache_or_diagnostic(path: Path) -> bool:
    parts = path_parts_lower(path)
    if ".cache" in parts or ".backup" in parts:
        return True
    if path.suffix.lower() in CACHE_EXTS:
        return True
    return path.name.lower() == "autodetectedsamplerates.cache"


def p4ignore_bucket(path: Path, workspace_root: Path) -> str:
    rel = safe_rel(path, workspace_root).replace("\\", "/")
    rel_lower = rel.lower()
    name_lower = path.name.lower()
    parts = [part.lower() for part in Path(rel).parts]

    if ".cache" in parts or ".backup" in parts:
        return "ignored-by-local-policy"
    if rel_lower.startswith("queries/"):
        if rel_lower in {"queries/default work unit.wwu", "queries/factory queries.wwu"}:
            return "explicitly-unignored"
        return "ignored-by-local-policy"
    if rel_lower.startswith("projectef/soundcaster sessions/") or rel_lower.startswith("soundcaster sessions/"):
        if name_lower == "default work unit.wwu":
            return "explicitly-unignored"
        return "ignored-by-local-policy"
    if path.suffix.lower() in {".validationcache", ".wsettings", ".log", ".prof", ".akd"}:
        return "ignored-by-local-policy"
    if name_lower in {"incrementalsoundbankdata.xml", "autodetectedsamplerates.cache"}:
        return "ignored-by-local-policy"
    if is_under_soundbank_backup(path):
        return "not-ignored-backup-risk"
    return "not-ignored"


def p4_executable() -> str:
    known = Path(r"C:\Program Files\Perforce\p4.exe")
    if known.exists():
        return str(known)
    found = shutil.which("p4")
    return found or "p4"


def parse_opened_line(line: str) -> dict[str, str] | None:
    # Example: //depot/file.wwu#3 - edit default change (text)
    match = re.match(r"^(?P<depot>//.+?)#(?P<rev>[^ ]+) - (?P<action>\w+) (?P<change>.+?) \((?P<type>.+)\)$", line.strip())
    if not match:
        return None
    return match.groupdict()


def depot_to_local(depot_path: str, workspace_root: Path) -> Path | None:
    normalized = depot_path.replace("\\", "/")
    if DEPOT_TRUNK_MARKER not in normalized:
        return None
    rel = normalized.split(DEPOT_TRUNK_MARKER, 1)[1]
    return workspace_root / Path(rel.replace("/", os.sep))


def run_p4_opened(args: argparse.Namespace) -> dict[str, Any]:
    cmd = [
        p4_executable(),
        "-p",
        args.p4_port,
        "-u",
        args.p4_user,
        "-c",
        args.p4_client,
        "opened",
    ]
    result: dict[str, Any] = {
        "attempted": True,
        "success": False,
        "command": " ".join(cmd),
        "error": "",
        "items": [],
    }
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=args.p4_timeout,
        )
    except subprocess.TimeoutExpired:
        result["error"] = f"p4 opened timed out after {args.p4_timeout}s"
        return result
    except Exception as exc:
        result["error"] = str(exc)
        return result

    if proc.returncode != 0:
        result["error"] = (proc.stderr or proc.stdout).strip()
        return result

    items = []
    for line in proc.stdout.splitlines():
        parsed = parse_opened_line(line)
        if not parsed:
            continue
        local = depot_to_local(parsed["depot"], Path(args.workspace_root))
        parsed["local_path"] = str(local) if local else ""
        items.append(parsed)
    result["success"] = True
    result["items"] = items
    return result


def collect_referenced_audio_names(project_root: Path) -> set[str]:
    names: set[str] = set()
    pattern = re.compile(r"<AudioFile>\s*([^<]+?)\s*</AudioFile>", re.IGNORECASE)
    for path in project_root.rglob("*.wwu"):
        if is_under_soundbank_backup(path) or is_generated_bank(path):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for match in pattern.finditer(text):
            names.add(Path(match.group(1).strip()).name.lower())
    return names


def collect_local_candidates(project_root: Path, workspace_root: Path, since_days: int) -> list[Path]:
    cutoff = dt.datetime.now() - dt.timedelta(days=since_days)
    paths: list[Path] = []
    for path in project_root.rglob("*"):
        if not path.is_file():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        created = dt.datetime.fromtimestamp(stat.st_ctime)
        modified = dt.datetime.fromtimestamp(stat.st_mtime)
        if created >= cutoff or modified >= cutoff or is_under_soundbank_backup(path):
            paths.append(path)

    for backup_root in workspace_root.glob("_backup_*"):
        if not backup_root.is_dir():
            continue
        for path in backup_root.rglob("*"):
            if path.is_file():
                paths.append(path)
    return sorted(set(paths), key=lambda item: str(item).lower())


def classify_path(path: Path, project_root: Path, workspace_root: Path, referenced_audio: set[str], p4_action: str = "") -> dict[str, Any]:
    stat = path.stat() if path.exists() else None
    suffix = path.suffix.lower()
    rel_project = safe_rel(path, project_root)
    rel_workspace = safe_rel(path, workspace_root)
    ignore_bucket = p4ignore_bucket(path, workspace_root)

    item = {
        "path": str(path),
        "rel_project": rel_project,
        "rel_workspace": rel_workspace,
        "name": path.name,
        "extension": suffix or "[none]",
        "exists": path.exists(),
        "size_mb": size_mb(stat.st_size) if stat else 0.0,
        "created": iso_from_ts(stat.st_ctime) if stat else "",
        "modified": iso_from_ts(stat.st_mtime) if stat else "",
        "p4_action": p4_action,
        "p4ignore": ignore_bucket,
        "category": "Other",
        "severity": "INFO",
        "reasonable": "Review",
        "reason": "",
        "recommendation": "",
        "audio_related": suffix in AUDIO_EXTS,
    }

    if is_under_soundbank_backup(path) or is_under_runtime_backup(path):
        item.update(
            category="SoundBank backup",
            severity="BLOCK",
            reasonable="No",
            audio_related=True,
            reason="Timestamped backup copy of generated SoundBank output, not authored Wwise source.",
            recommendation="Do not submit as changelist content; keep outside workspace or add ignore rule such as GeneratedSoundBanks_Backup_*/.",
        )
    elif is_cache_or_diagnostic(path):
        item.update(
            category="Cache/diagnostic",
            severity="BLOCK",
            reasonable="No",
            audio_related=True,
            reason="Wwise cache, profiling, settings, or diagnostic output.",
            recommendation="Do not submit; keep ignored or revert from pending changelist if opened.",
        )
    elif is_generated_bank(path):
        severity = "REVIEW"
        reasonable = "Policy"
        recommendation = "Submit only if the project intentionally versions generated runtime SoundBanks for this change."
        if p4_action.lower() == "add":
            severity = "WARN"
            recommendation = "Large generated add detected; confirm project policy before submit."
        item.update(
            category="Generated SoundBank output",
            severity=severity,
            reasonable=reasonable,
            audio_related=True,
            reason="Generated bank/media/metadata output under GeneratedSoundBanks.",
            recommendation=recommendation,
        )
    elif has_part(path, "Originals") and suffix in SOURCE_AUDIO_EXTS:
        referenced = path.name.lower() in referenced_audio
        item.update(
            category="Source audio",
            severity="OK" if referenced else "WARN",
            reasonable="Yes" if referenced else "Review",
            audio_related=True,
            reason="Source audio in Originals; referenced by Wwise WorkUnits." if referenced else "Source audio in Originals but no AudioFile reference was found in local WWU scan.",
            recommendation="Submit with the matching Wwise WorkUnit/Event edits if this is intended." if referenced else "Check whether it was imported into Wwise or is an accidental loose file.",
        )
    elif suffix in {".wwu", ".wproj"}:
        item.update(
            category="Authored Wwise project file",
            severity="REVIEW",
            reasonable="Intentional?",
            audio_related=True,
            reason="Authored Wwise project/work unit file.",
            recommendation="Submit only if the object/event/bank change matches the task; inspect diff before submit.",
        )
    elif suffix in AUDIO_EXTS:
        item.update(
            category="Audio-adjacent file",
            severity="REVIEW",
            reasonable="Review",
            audio_related=True,
            reason="Audio-related extension or Wwise metadata.",
            recommendation="Confirm whether this file is authored source or generated output.",
        )

    return item


def summarize_backup_dir(path: Path) -> dict[str, Any]:
    files = [item for item in path.rglob("*") if item.is_file()]
    ext_counter = Counter((item.suffix.lower() or "[none]") for item in files)
    stat = path.stat()
    info_path = path / "Windows" / "SoundbanksInfo.xml"
    info: dict[str, Any] = {
        "name": path.name,
        "path": str(path),
        "created": iso_from_ts(stat.st_ctime),
        "modified": iso_from_ts(stat.st_mtime),
        "file_count": len(files),
        "size_mb": size_mb(sum(item.stat().st_size for item in files)),
        "extensions": dict(sorted(ext_counter.items())),
        "name_timestamp": "",
        "soundbanks_info_exists": info_path.exists(),
        "schema_version": "",
        "soundbank_version": "",
        "root_paths": {},
    }
    match = re.search(r"(\d{8})_(\d{4,6})", path.name)
    if match:
        raw_time = match.group(2)
        fmt = "%Y%m%d%H%M" if len(raw_time) == 4 else "%Y%m%d%H%M%S"
        try:
            info["name_timestamp"] = dt.datetime.strptime(match.group(1) + raw_time, fmt).isoformat(timespec="seconds")
        except ValueError:
            pass
    if info_path.exists():
        text = info_path.read_text(encoding="utf-8", errors="ignore")
        schema = re.search(r'SchemaVersion="([^"]+)"', text)
        bank = re.search(r'Sound[Bb]ankVersion="([^"]+)"', text)
        info["schema_version"] = schema.group(1) if schema else ""
        info["soundbank_version"] = bank.group(1) if bank else ""
        for tag in ("ProjectRoot", "SourceFilesRoot", "SoundBanksRoot", "ExternalSourcesOutputRoot"):
            tag_match = re.search(rf"<{tag}>\s*(.*?)\s*</{tag}>", text, re.IGNORECASE | re.DOTALL)
            if tag_match:
                info["root_paths"][tag] = tag_match.group(1).strip()
    return info


def summarize_current_soundbanks(project_root: Path) -> dict[str, Any]:
    bank_root = project_root / "GeneratedSoundBanks" / "Windows"
    files = [item for item in bank_root.rglob("*") if item.is_file()] if bank_root.exists() else []
    ext_counter = Counter((item.suffix.lower() or "[none]") for item in files)
    info_path = bank_root / "SoundbanksInfo.xml"
    result: dict[str, Any] = {
        "path": str(bank_root),
        "exists": bank_root.exists(),
        "file_count": len(files),
        "size_mb": size_mb(sum(item.stat().st_size for item in files)),
        "extensions": dict(sorted(ext_counter.items())),
        "soundbanks_info_exists": info_path.exists(),
        "schema_version": "",
        "soundbank_version": "",
        "root_paths": {},
    }
    if info_path.exists():
        text = info_path.read_text(encoding="utf-8", errors="ignore")
        schema = re.search(r'SchemaVersion="([^"]+)"', text)
        bank = re.search(r'Sound[Bb]ankVersion="([^"]+)"', text)
        result["schema_version"] = schema.group(1) if schema else ""
        result["soundbank_version"] = bank.group(1) if bank else ""
        for tag in ("ProjectRoot", "SourceFilesRoot", "SoundBanksRoot", "ExternalSourcesOutputRoot"):
            tag_match = re.search(rf"<{tag}>\s*(.*?)\s*</{tag}>", text, re.IGNORECASE | re.DOTALL)
            if tag_match:
                result["root_paths"][tag] = tag_match.group(1).strip()
    return result


def summarize_workspace_scope_risk(path: Path) -> dict[str, Any]:
    files = [item for item in path.rglob("*") if item.is_file()]
    ext_counter = Counter((item.suffix.lower() or "[none]") for item in files)
    stat = path.stat()
    return {
        "name": path.name,
        "path": str(path),
        "created": iso_from_ts(stat.st_ctime),
        "modified": iso_from_ts(stat.st_mtime),
        "file_count": len(files),
        "size_mb": size_mb(sum(item.stat().st_size for item in files)),
        "extensions": dict(sorted(ext_counter.items(), key=lambda pair: (-pair[1], pair[0]))),
        "recommendation": "Do not reconcile/submit this old project folder with the upgraded ProjectEF changelist unless the old project is explicitly intended.",
    }


def analyze(args: argparse.Namespace) -> dict[str, Any]:
    workspace_root = Path(args.workspace_root)
    project_root = Path(args.project_root)
    referenced_audio = collect_referenced_audio_names(project_root)
    p4 = run_p4_opened(args)

    paths: list[tuple[Path, str]] = []
    mode = "p4-opened" if p4["success"] and p4["items"] else "local-fallback"
    if mode == "p4-opened":
        for item in p4["items"]:
            local_text = item.get("local_path") or ""
            if not local_text:
                continue
            local = Path(local_text)
            if local.exists():
                paths.append((local, item.get("action", "")))
    else:
        paths = [(path, "") for path in collect_local_candidates(project_root, workspace_root, args.since_days)]

    classified = [
        classify_path(path, project_root, workspace_root, referenced_audio, p4_action=action)
        for path, action in paths
        if path.exists()
    ]
    audio_items = [item for item in classified if item["audio_related"] or item["severity"] in {"BLOCK", "WARN"}]
    backup_dirs = [
        summarize_backup_dir(path)
        for path in sorted(project_root.glob("GeneratedSoundBanks_Backup_*"))
        if path.is_dir()
    ]
    current_soundbanks = summarize_current_soundbanks(project_root)
    workspace_scope_risks = [
        summarize_workspace_scope_risk(path)
        for path in sorted(workspace_root.glob("ProjectEF_*"))
        if path.is_dir() and path.resolve() != project_root.resolve()
    ]
    category_counts = Counter(item["category"] for item in audio_items)
    severity_counts = Counter(item["severity"] for item in audio_items)

    verdict = "PASS"
    if severity_counts.get("BLOCK", 0):
        verdict = "BLOCK"
    elif severity_counts.get("WARN", 0):
        verdict = "WARN"
    elif severity_counts.get("REVIEW", 0):
        verdict = "REVIEW"

    return {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "workspace_root": str(workspace_root),
        "project_root": str(project_root),
        "mode": mode,
        "p4": p4,
        "since_days": args.since_days,
        "verdict": verdict,
        "counts": {
            "all_candidates": len(classified),
            "audio_related": len(audio_items),
            "by_category": dict(sorted(category_counts.items())),
            "by_severity": dict(sorted(severity_counts.items())),
        },
        "current_soundbanks": current_soundbanks,
        "backup_dirs": backup_dirs,
        "workspace_scope_risks": workspace_scope_risks,
        "items": audio_items,
    }


def render_markdown(result: dict[str, Any]) -> str:
    p4 = result["p4"]
    counts = result["counts"]
    mode_note = (
        "Exact P4 opened list was available."
        if result["mode"] == "p4-opened"
        else "P4 opened list was unavailable, so this report used local file timestamps and known Wwise/P4 risk patterns."
    )
    backup_rows = [
        [
            item["name"],
            item["created"],
            item.get("name_timestamp", "-") or "-",
            item["file_count"],
            item["size_mb"],
            ", ".join(f"{key}:{value}" for key, value in item["extensions"].items()),
            f"Schema {item.get('schema_version') or '-'} / Bank {item.get('soundbank_version') or '-'}",
        ]
        for item in result["backup_dirs"]
    ]
    scope_risk_rows = [
        [
            item["name"],
            item["file_count"],
            item["size_mb"],
            item["modified"],
            ", ".join(f"{key}:{value}" for key, value in list(item["extensions"].items())[:8]),
            item["recommendation"],
        ]
        for item in result.get("workspace_scope_risks", [])
    ]
    backup_root_rows = [
        [
            item["name"],
            item.get("root_paths", {}).get("ProjectRoot", "-"),
            item.get("root_paths", {}).get("SourceFilesRoot", "-"),
            item.get("root_paths", {}).get("SoundBanksRoot", "-"),
        ]
        for item in result["backup_dirs"]
    ]
    item_rows = [
        [
            item["severity"],
            item["category"],
            item["reasonable"],
            item["p4_action"] or "-",
            item["p4ignore"],
            item["size_mb"],
            item["modified"],
            item["rel_workspace"],
            item["recommendation"],
        ]
        for item in sorted(result["items"], key=lambda row: ("BLOCK WARN REVIEW OK INFO".split().index(row["severity"]) if row["severity"] in "BLOCK WARN REVIEW OK INFO".split() else 9, row["rel_workspace"]))
    ]
    source_rows = [
        [
            item["name"],
            item["severity"],
            item["size_mb"],
            item["created"],
            item["reason"],
        ]
        for item in result["items"]
        if item["category"] == "Source audio"
    ]
    generated_rows = [
        [
            item["severity"],
            item["extension"],
            item["size_mb"],
            item["rel_workspace"],
        ]
        for item in result["items"]
        if item["category"] == "Generated SoundBank output"
    ]
    authored_rows = [
        [
            item["severity"],
            item["size_mb"],
            item["modified"],
            item["rel_workspace"],
            item["recommendation"],
        ]
        for item in result["items"]
        if item["category"] == "Authored Wwise project file"
    ]
    blocked_rows = [
        [
            item["category"],
            item["size_mb"],
            item["rel_workspace"],
            item["recommendation"],
        ]
        for item in result["items"]
        if item["severity"] == "BLOCK"
    ]

    lines = [
        "# ProjectEF P4V Audio Changelist Check",
        "",
        f"- Generated: {result['generated_at']}",
        f"- Workspace: `{result['workspace_root']}`",
        f"- Project: `{result['project_root']}`",
        f"- Mode: **{result['mode']}**",
        f"- Verdict: **{result['verdict']}**",
        f"- Note: {mode_note}",
        "",
        "## Summary",
        "",
        table(
            [
                ["All local/P4 candidates", counts["all_candidates"]],
                ["Audio-related/risk candidates", counts["audio_related"]],
                ["BLOCK", counts["by_severity"].get("BLOCK", 0)],
                ["WARN", counts["by_severity"].get("WARN", 0)],
                ["REVIEW", counts["by_severity"].get("REVIEW", 0)],
                ["OK", counts["by_severity"].get("OK", 0)],
            ],
            ["Metric", "Value"],
        ),
        "",
        "## P4 Access",
        "",
        f"- Command: `{p4.get('command', '')}`",
        f"- Success: {p4.get('success')}",
        f"- Error: {p4.get('error') or '-'}",
        "",
        "## Workspace Scope Risks",
        "",
        table(scope_risk_rows, ["Folder", "Files", "MB", "Modified", "Top Extensions", "Recommendation"], max_rows=20),
        "",
        "Interpretation:",
        "",
        "- If P4V Reconcile was run from the workspace root, old project folders such as `ProjectEF_2021` can be pulled into the same pending changelist.",
        "- Revert or move these path-scoped entries separately from the current `ProjectEF` work; do not revert the whole changelist.",
        "",
        "## SoundBank Backups",
        "",
        table(backup_rows, ["Backup", "Created", "Name timestamp", "Files", "MB", "Extensions", "Version"], max_rows=20),
        "",
        "Interpretation:",
        "",
        "- `GeneratedSoundBanks_Backup_*` is a timestamped copy of generated SoundBank output.",
        "- The local `.p4ignore` ignores `.cache/` and `.backup/`, but it does not ignore `GeneratedSoundBanks_Backup_*`, so P4 reconcile can treat these folders as new files.",
        "- These backups are not authored source audio. They are useful as rollback/reference snapshots before regenerating banks, but they normally should not be submitted.",
        "",
        "Backup SoundbanksInfo root path evidence:",
        "",
        table(backup_root_rows, ["Backup", "ProjectRoot", "SourceFilesRoot", "SoundBanksRoot"], max_rows=20),
        "",
        "## Source Audio Adds / Changes",
        "",
        table(source_rows, ["File", "Severity", "MB", "Created", "Reason"], max_rows=60),
        "",
        "## Authored Wwise Files To Review",
        "",
        table(authored_rows, ["Severity", "MB", "Modified", "Path", "Recommendation"], max_rows=60),
        "",
        "## Generated SoundBank Output",
        "",
        table(generated_rows, ["Severity", "Ext", "MB", "Path"], max_rows=60),
        "",
        "## Must Exclude Before Submit",
        "",
        table(blocked_rows, ["Category", "MB", "Path", "Recommendation"], max_rows=80),
        "",
        "## All Audio-Related Items",
        "",
        table(item_rows, ["Severity", "Category", "Reasonable", "P4", "Ignore", "MB", "Modified", "Path", "Recommendation"], max_rows=MAX_TABLE_ROWS),
        "",
        "## Category Counts",
        "",
        table([[key, value] for key, value in sorted(counts["by_category"].items())], ["Category", "Count"]),
        "",
        "## Current GeneratedSoundBanks Snapshot",
        "",
        f"- Path: `{result['current_soundbanks']['path']}`",
        f"- Exists: {result['current_soundbanks']['exists']}",
        f"- Files: {result['current_soundbanks']['file_count']}",
        f"- Size MB: {result['current_soundbanks']['size_mb']}",
        f"- Version: Schema {result['current_soundbanks'].get('schema_version') or '-'} / Bank {result['current_soundbanks'].get('soundbank_version') or '-'}",
        "",
        "Root paths:",
        "",
        "\n".join(f"- {key}: `{value}`" for key, value in result["current_soundbanks"].get("root_paths", {}).items()) or "- None",
        "",
        "## Safe Action",
        "",
        "- In P4V, submit authored Wwise files and intended `Originals` source audio together.",
        "- Do not submit SoundBank backup folders, Wwise cache, profiler sessions, or user settings.",
        "- If generated SoundBanks are versioned by project policy, submit only the intended current `GeneratedSoundBanks` output, not timestamped backups.",
        "- If P4 mode failed, use this as a local triage report and confirm exact add/edit actions in P4V before submit.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze ProjectEF P4V changelist audio-related risk.")
    parser.add_argument("--workspace-root", default=str(DEFAULT_WORKSPACE_ROOT))
    parser.add_argument("--project-root", default=str(DEFAULT_PROJECT_ROOT))
    parser.add_argument("--reports-dir", default=str(DEFAULT_REPORT_DIR))
    parser.add_argument("--p4-port", default=DEFAULT_P4PORT)
    parser.add_argument("--p4-user", default=DEFAULT_P4USER)
    parser.add_argument("--p4-client", default=DEFAULT_P4CLIENT)
    parser.add_argument("--p4-timeout", type=int, default=4)
    parser.add_argument("--since-days", type=int, default=1)
    parser.add_argument("--open-report", action="store_true")
    args = parser.parse_args()

    result = analyze(args)
    report_dir = Path(args.reports_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = now_stamp()
    md_path = report_dir / f"ProjectEF_P4V_AudioChangelist_Check_{stamp}.md"
    json_path = report_dir / f"ProjectEF_P4V_AudioChangelist_Check_{stamp}.json"
    md_path.write_text(render_markdown(result), encoding="utf-8")
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(md_path)
    print(json_path)
    print(f"Verdict: {result['verdict']} ({result['mode']})")
    if args.open_report:
        os.startfile(str(md_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
