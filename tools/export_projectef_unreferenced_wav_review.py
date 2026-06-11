#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
from collections import Counter
from pathlib import Path
from typing import Any


REPORT_DIR_NAME = chr(0x62A5) + chr(0x544A)


def newest(root: Path, pattern: str) -> Path | None:
    matches = [path for path in root.glob(pattern) if path.is_file()]
    if not matches:
        return None
    return max(matches, key=lambda path: path.stat().st_mtime)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig", errors="replace"))


def system_guess(rel_path: str) -> str:
    text = rel_path.replace("/", "\\").lower()
    name = Path(rel_path).name.lower()
    if "\\amb" in text or name.startswith("amb_") or "weather" in text or "rain" in text or "wind" in text:
        return "Ambience/Weather"
    if "bgm" in text or "music" in text:
        return "Music"
    if "\\ui" in text or name.startswith("ui_") or "button" in name or "click" in name:
        return "UI"
    if "footstep" in text or "walk" in name or "run" in name:
        return "Player/Footsteps"
    if "fish" in text or name.startswith("fish_"):
        return "Fish"
    if "lure" in text or name.startswith("lure_"):
        return "Fishing/Lure"
    if any(token in text for token in ("gear", "reel", "rod", "hook", "spool", "line_")):
        return "Gear/Fishing"
    if "voice" in text or "\\vo" in text or name.startswith("vo_"):
        return "VO"
    return "SFX/Unclassified"


def suggested_action(rel_path: str, detail: dict[str, Any]) -> tuple[str, str]:
    text = rel_path.lower()
    size_mb = float(detail.get("size_mb") or 0)
    duration = float(detail.get("duration_sec") or 0)
    channels = int(detail.get("channels") or 0)
    if not detail.get("ok", True):
        return "ArchiveReview", "File metadata could not be fully read; inspect before reuse."
    if any(token in text for token in ("test", "temp", "old", "obsolete", "backup", "copy")):
        return "ArchiveCandidate", "Name suggests test, temporary, old, obsolete, backup, or copied material."
    if channels >= 4 or size_mb >= 20 or duration >= 20:
        return "KeepCandidate", "Large, long, or multichannel asset; likely intentional source material."
    if system_guess(rel_path) in {"Ambience/Weather", "Music"}:
        return "KeepCandidate", "Ambient or music material can be intentionally staged before Wwise hookup."
    return "Review", "Unused by current WWU; choose Keep, Archive, or Delete after external dependency check."


def analyze(audit: dict[str, Any]) -> dict[str, Any]:
    project_root = Path(audit.get("project_root") or "")
    objects = audit.get("parsed", {}).get("objects", [])
    details = audit.get("file_scan", {}).get("wav_details", [])
    audit_samples = set(audit.get("file_scan", {}).get("unreferenced_wav_samples") or [])

    referenced_names = Counter(
        Path(str(obj.get("audio_file"))).name.lower()
        for obj in objects
        if obj.get("audio_file")
    )
    rows = []
    for detail in details:
        rel = str(detail.get("file") or "")
        if not rel or Path(rel).suffix.lower() != ".wav":
            continue
        if Path(rel).name.lower() in referenced_names:
            continue
        action, reason = suggested_action(rel, detail)
        abs_path = project_root / rel if project_root else Path(rel)
        review_status = "KeepCandidateConfirmed" if action == "KeepCandidate" else ""
        rows.append(
            {
                "relative_path": rel,
                "absolute_path": str(abs_path),
                "size_mb": detail.get("size_mb", ""),
                "duration_sec": detail.get("duration_sec", ""),
                "duration_min": round(float(detail.get("duration_sec") or 0) / 60, 3),
                "sample_rate": detail.get("sample_rate", ""),
                "channels": detail.get("channels", ""),
                "bits": detail.get("bits", ""),
                "read_ok": detail.get("ok", True),
                "system_guess": system_guess(rel),
                "suggested_action": action,
                "reason": reason,
                "audit_sample": rel in audit_samples,
                "review_status": review_status,
                "reviewer": "Codex" if review_status else "",
                "review_notes": "Kept in Originals after non-destructive archive pass." if review_status else "",
            }
        )
    rows.sort(key=lambda row: (row["system_guess"], row["relative_path"].lower()))
    return {
        "project_root": str(project_root),
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "rows": rows,
        "counts": {
            "total": len(rows),
            "size_mb": round(sum(float(row["size_mb"] or 0) for row in rows), 2),
            "duration_min": round(sum(float(row["duration_sec"] or 0) for row in rows) / 60, 2),
            "by_system": dict(Counter(row["system_guess"] for row in rows).most_common()),
            "by_suggested_action": dict(Counter(row["suggested_action"] for row in rows).most_common()),
        },
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "relative_path",
        "absolute_path",
        "size_mb",
        "duration_sec",
        "duration_min",
        "sample_rate",
        "channels",
        "bits",
        "read_ok",
        "system_guess",
        "suggested_action",
        "reason",
        "audit_sample",
        "review_status",
        "reviewer",
        "review_notes",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def table(rows: list[list[Any]], headers: list[str]) -> str:
    if not rows:
        rows = [["-"] * len(headers)]
    widths = [
        max(len(str(row[index])) for row in [headers] + rows)
        for index in range(len(headers))
    ]
    out = [
        "| " + " | ".join(str(headers[index]).ljust(widths[index]) for index in range(len(headers))) + " |",
        "| " + " | ".join("-" * widths[index] for index in range(len(headers))) + " |",
    ]
    for row in rows:
        out.append("| " + " | ".join(str(row[index]).ljust(widths[index]) for index in range(len(headers))) + " |")
    return "\n".join(out)


def render_markdown(result: dict[str, Any], audit_json: Path, csv_out: Path, json_out: Path) -> str:
    counts = result["counts"]
    largest = sorted(result["rows"], key=lambda row: float(row["size_mb"] or 0), reverse=True)[:15]
    lines = [
        "# ProjectEF Unreferenced WAV Review",
        "",
        f"- Generated: {result['generated_at']}",
        f"- Audit JSON: `{audit_json}`",
        f"- CSV review list: `{csv_out}`",
        f"- JSON data: `{json_out}`",
        f"- Project root: `{result['project_root']}`",
        "",
        "## Summary",
        "",
        table(
            [
                ["Unreferenced WAV files", counts["total"]],
                ["Total size MB", counts["size_mb"]],
                ["Total duration min", counts["duration_min"]],
            ],
            ["Metric", "Value"],
        ),
        "",
        "## Suggested Action Counts",
        "",
        table([[key, value] for key, value in counts["by_suggested_action"].items()], ["Suggested Action", "Count"]),
        "",
        "## System Guess Counts",
        "",
        table([[key, value] for key, value in counts["by_system"].items()], ["System Guess", "Count"]),
        "",
        "## Largest Review Items",
        "",
        table(
            [
                [
                    row["relative_path"],
                    row["size_mb"],
                    row["duration_min"],
                    row["channels"],
                    row["system_guess"],
                    row["suggested_action"],
                ]
                for row in largest
            ],
            ["Relative Path", "MB", "Min", "Ch", "System", "Suggested Action"],
        ),
        "",
        "## Rules",
        "",
        "- This report is a review list only. It does not delete, archive, rename, or modify Wwise objects.",
        "- `KeepCandidate` means the asset looks intentional or expensive enough to review before cleanup.",
        "- `ArchiveCandidate` means the name suggests old/test/temp material; still verify external dependencies before moving.",
        "- `Review` means no safe automatic decision was inferred.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Export full ProjectEF unreferenced WAV review CSV from Wwise audit JSON.")
    parser.add_argument("--report-root", default=str(Path.cwd() / REPORT_DIR_NAME))
    parser.add_argument("--audit-json")
    parser.add_argument("--out-csv")
    parser.add_argument("--out-json")
    parser.add_argument("--out-md")
    args = parser.parse_args()

    report_root = Path(args.report_root)
    audit_json = Path(args.audit_json) if args.audit_json else newest(report_root, "ProjectEF_Wwise工程与资源检测数据_*.json")
    if not audit_json:
        raise SystemExit(f"No Wwise audit JSON found under {report_root}")

    stamp = dt.datetime.now().strftime("%Y-%m-%d")
    out_csv = Path(args.out_csv) if args.out_csv else report_root / f"ProjectEF_UnreferencedWav_Review_{stamp}.csv"
    out_json = Path(args.out_json) if args.out_json else report_root / f"ProjectEF_UnreferencedWav_Review_{stamp}.json"
    out_md = Path(args.out_md) if args.out_md else report_root / f"ProjectEF_UnreferencedWav_Review_{stamp}.md"

    result = analyze(load_json(audit_json))
    write_csv(out_csv, result["rows"])
    out_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    out_md.write_text(render_markdown(result, audit_json, out_csv, out_json), encoding="utf-8")

    print(out_csv)
    print(out_json)
    print(out_md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
