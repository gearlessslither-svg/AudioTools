#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import shutil
import subprocess
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


TEXT_SUFFIXES = {
    ".asmdef",
    ".asset",
    ".bytes",
    ".controller",
    ".cs",
    ".json",
    ".mat",
    ".meta",
    ".prefab",
    ".shader",
    ".txt",
    ".unity",
    ".xml",
    ".yaml",
}

SKIP_DIRS = {
    ".git",
    "Library",
    "Temp",
    "Logs",
    "Obj",
    "obj",
    "Build",
    "Builds",
    "UserSettings",
}


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fp:
        return list(csv.DictReader(fp))


def safe_rel_to(path: Path, root: Path) -> Path | None:
    try:
        return path.resolve().relative_to(root.resolve())
    except ValueError:
        return None


def iter_text_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() in TEXT_SUFFIXES:
            yield path


def scan_external_refs(unity_root: Path, basenames: set[str]) -> dict[str, list[str]]:
    refs: dict[str, list[str]] = defaultdict(list)
    if not unity_root.exists():
        return refs
    pattern_file: Path | None = None
    search_roots = [
        path
        for name in ("Assets", "Packages", "ProjectSettings", "ProjectConfigs")
        if (path := unity_root / name).exists()
    ]
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".txt") as fp:
            pattern_file = Path(fp.name)
            for name in sorted(basenames):
                fp.write(name + "\n")
        cmd = [
            "rg",
            "--fixed-strings",
            "--ignore-case",
            "--with-filename",
            "--line-number",
            "--no-heading",
            "--glob",
            "!Library/**",
            "--glob",
            "!Temp/**",
            "--glob",
            "!Logs/**",
            "--glob",
            "!obj/**",
            "--file",
            str(pattern_file),
            *[str(path) for path in search_roots],
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
        if proc.returncode in {0, 1}:
            for line in proc.stdout.splitlines():
                lower = line.lower()
                file_part = line.split(":", 1)[0]
                try:
                    rel = str(Path(file_part).resolve().relative_to(unity_root))
                except ValueError:
                    rel = file_part
                for name in basenames:
                    if name in lower:
                        refs[name].append(rel)
            return refs
    except Exception:
        refs.clear()
    finally:
        try:
            if pattern_file is not None:
                pattern_file.unlink()
        except Exception:
            pass

    for path in iter_text_files(unity_root):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore").lower()
        except Exception:
            continue
        hits = [name for name in basenames if name in text]
        if not hits:
            continue
        rel = str(path.relative_to(unity_root))
        for name in hits:
            refs[name].append(rel)
    return refs


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Archive ProjectEF unreferenced WAVs with a restore manifest.")
    parser.add_argument("--review-csv", required=True)
    parser.add_argument("--project-root", default=r"D:\EF Wwise\ProjectEF")
    parser.add_argument("--unity-root", default=r"D:\EF New\Client\TargetProject")
    parser.add_argument("--archive-root")
    parser.add_argument("--out-csv", required=True)
    parser.add_argument("--out-json", required=True)
    parser.add_argument("--out-md", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    generated_at = dt.datetime.now().isoformat(timespec="seconds")
    project_root = Path(args.project_root).resolve()
    originals_root = project_root / "Originals"
    unity_root = Path(args.unity_root).resolve()
    archive_root = Path(args.archive_root).resolve() if args.archive_root else project_root / f"Originals_UnreferencedArchive_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}"

    rows = read_rows(Path(args.review_csv))
    basenames = {Path(row["absolute_path"]).name.lower() for row in rows}
    external_refs = scan_external_refs(unity_root, basenames)

    decisions: list[dict[str, Any]] = []
    for row in rows:
        src = Path(row["absolute_path"]).resolve()
        src_rel_originals = safe_rel_to(src, originals_root)
        basename = src.name.lower()
        refs = external_refs.get(basename, [])
        suggested = row.get("suggested_action", "")
        status = ""
        dest = ""
        reason = ""

        if src_rel_originals is None:
            status = "SkippedUnsafeSource"
            reason = "Source path is not under the Wwise Originals root."
        elif refs:
            status = "KeepExternalReference"
            reason = "Filename appears in Unity project text assets."
        elif suggested == "KeepCandidate":
            status = "KeepCandidateConfirmed"
            reason = row.get("reason") or "Marked as keep candidate by source audit."
        elif not src.exists():
            status = "MissingSource"
            reason = "Source file was already absent."
        else:
            dst = (archive_root / src_rel_originals).resolve()
            archive_rel = safe_rel_to(dst, archive_root)
            if archive_rel is None:
                status = "SkippedUnsafeDestination"
                reason = "Destination path is not under archive root."
            elif dst.exists():
                status = "SkippedDestinationExists"
                reason = "Archive destination already exists."
            else:
                status = "DryRunArchive" if args.dry_run else "Archived"
                reason = "Unreferenced by current WWU and no Unity text reference found."
                dest = str(dst)
                if not args.dry_run:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(src), str(dst))

        decisions.append(
            {
                **row,
                "final_status": status,
                "final_reason": reason,
                "archive_path": dest,
                "unity_reference_count": len(refs),
                "unity_reference_samples": "; ".join(refs[:10]),
            }
        )

    counts = Counter(item["final_status"] for item in decisions)
    report = {
        "generated_at": generated_at,
        "dry_run": bool(args.dry_run),
        "project_root": str(project_root),
        "originals_root": str(originals_root),
        "unity_root": str(unity_root),
        "archive_root": str(archive_root),
        "counts": dict(counts),
        "items": decisions,
    }

    fieldnames = list(decisions[0].keys()) if decisions else []
    write_csv(Path(args.out_csv), decisions, fieldnames)
    Path(args.out_json).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# ProjectEF Unreferenced WAV Archive Report",
        "",
        f"- Generated: {generated_at}",
        f"- Dry run: {args.dry_run}",
        f"- Project root: `{project_root}`",
        f"- Archive root: `{archive_root}`",
        "",
        "## Status Counts",
        "",
        "| Status | Count |",
        "|---|---:|",
    ]
    for status, count in counts.most_common():
        lines.append(f"| {status} | {count} |")
    lines.extend(
        [
            "",
            "## Restore Note",
            "",
            "- Files were moved, not deleted.",
            "- Restore by moving each `archive_path` back to `absolute_path` from the CSV/JSON manifest.",
            "",
        ]
    )
    Path(args.out_md).write_text("\n".join(lines), encoding="utf-8")

    print(args.out_csv)
    print(args.out_json)
    print(args.out_md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
