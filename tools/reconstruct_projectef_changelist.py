#!/usr/bin/env python3
from __future__ import annotations

import csv
import datetime as dt
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


WORKSPACE_ROOT = Path(r"D:\EF Wwise")
PROJECT_ROOT = WORKSPACE_ROOT / "ProjectEF"
OLD_PROJECT_ROOT = WORKSPACE_ROOT / "ProjectEF_2021"
REPORT_DIR = Path(r"G:\AI\Material\Wwise\报告")

THIS_TASK_KEEP = {
    r"ProjectEF\Originals\SFX\UI_Fix.wav",
    r"ProjectEF\Originals\SFX\UI_Food.wav",
    r"ProjectEF\Originals\SFX\UI_GoldCoin.wav",
    r"ProjectEF\Originals\SFX\UI_Special_Start.wav",
    r"ProjectEF\Originals\SFX\UI_Store.wav",
    r"ProjectEF\Originals\SFX\UI_Warehouse.wav",
    r"ProjectEF\Actor-Mixer Hierarchy\UI.wwu",
    r"ProjectEF\Events\UI.wwu",
}

SAME_SAVE_REVIEW = {
    r"ProjectEF\Events\Default Work Unit.wwu",
    r"ProjectEF\Interactive Music Hierarchy\Default Work Unit.wwu",
    r"ProjectEF\Soundcaster Sessions\Default Work Unit.wwu",
}

REVIEW_PREVIOUS_AUTHORED = {
    r"ProjectEF\Actor-Mixer Hierarchy\Player.wwu",
    r"ProjectEF\Attenuations\Default Work Unit.wwu",
    r"ProjectEF\Actor-Mixer Hierarchy\Fishing.wwu",
    r"ProjectEF\Events\Fish.wwu",
    r"ProjectEF\Actor-Mixer Hierarchy\Gear.wwu",
    r"ProjectEF\Events\Gear.wwu",
    r"ProjectEF\Events\Player.wwu",
}

GENERATED_EXTENSIONS = {".wem", ".bnk", ".prof", ".wsettings", ".validationcache", ".cache", ".akd", ".dat", ".mdb", ".log"}
AUTHORED_EXTENSIONS = {".wwu", ".wproj", ".wav"}


def iso_from_ts(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts).isoformat(timespec="seconds")


def size_mb(size: int) -> float:
    return round(size / 1024 / 1024, 3)


def rel_workspace(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(WORKSPACE_ROOT.resolve()))
    except Exception:
        return str(path)


def path_has_part(path: Path, name: str) -> bool:
    return any(part.lower() == name.lower() for part in path.parts)


def path_has_prefix_part(path: Path, prefix: str) -> bool:
    return any(part.lower().startswith(prefix.lower()) for part in path.parts)


def is_generated_cache(path: Path) -> bool:
    parts = [part.lower() for part in path.parts]
    name = path.name.lower()
    return (
        ".cache" in parts
        or ".backup" in parts
        or path.suffix.lower() in GENERATED_EXTENSIONS
        or name == "autodetectedsamplerates.cache"
    )


def ui_evidence(path: Path) -> str:
    if not path.exists() or path.suffix.lower() != ".wwu":
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""
    needles = [
        "UI_Fix",
        "UI_Food",
        "UI_GoldCoin",
        "UI_Special_Start",
        "UI_Store",
        "UI_Warehouse",
        "Play_UI_Fix",
        "Play_UI_Food",
        "Play_UI_GoldCoin",
        "Play_UI_Special_Start",
        "Play_UI_Store",
        "Play_UI_Warehouse",
    ]
    found = [needle for needle in needles if needle in text]
    return ", ".join(found[:8]) + (" ..." if len(found) > 8 else "")


def classify(path: Path) -> dict[str, Any]:
    rel = rel_workspace(path)
    stat = path.stat()
    suffix = path.suffix.lower()
    created = dt.datetime.fromtimestamp(stat.st_ctime)
    modified = dt.datetime.fromtimestamp(stat.st_mtime)
    evidence = ui_evidence(path)

    category = "Ignore"
    action = "Ignore"
    confidence = "Low"
    reason = "Not part of the current reconstruction scope."

    if rel.startswith("ProjectEF_2021\\"):
        category = "OLD_PROJECT_EXCLUDE"
        action = "Do not submit. Revert this path from pending; use keep-workspace-copy if you still want the local old project."
        confidence = "High"
        reason = "Old Wwise 2021 project folder. No files here were created or modified in 2026, so this is most likely reconcile scope noise."
    elif path_has_prefix_part(path, "GeneratedSoundBanks_Backup_"):
        category = "SOUNDBANK_BACKUP_EXCLUDE"
        action = "Do not submit. Revert from pending or move backup outside workspace."
        confidence = "High"
        reason = "Timestamped backup of generated SoundBank output, not authored source. SoundbanksInfo points to old ProjectEF_2021 paths."
    elif path_has_part(path, "GeneratedSoundBanks"):
        category = "GENERATED_BANK_POLICY_REVIEW"
        action = "Review project policy. Do not include in this UI source changelist unless generated banks are intentionally versioned."
        confidence = "Medium"
        reason = "Generated SoundBank runtime output. It may be versioned by project policy, but it is not authored source audio."
    elif is_generated_cache(path):
        category = "GENERATED_CACHE_EXCLUDE"
        action = "Do not submit. Revert from pending if opened; keep ignored."
        confidence = "High"
        reason = "Wwise cache, profiling, user settings, validation cache, generated media, or temporary backup."
    elif rel in THIS_TASK_KEEP:
        category = "KEEP_THIS_UI_TASK"
        action = "Move to a clean changelist for the current UI work and submit with related UI WorkUnits."
        confidence = "High"
        reason = "Created/modified at 2026-06-04 16:09-16:10 and directly references the six new UI feature sounds/events."
    elif rel in SAME_SAVE_REVIEW:
        category = "REVIEW_SAME_SAVE_NO_UI_EVIDENCE"
        action = "Inspect diff. If only Wwise save noise, revert; if intentional routing/session change, keep separately."
        confidence = "Medium"
        reason = "Saved at the same time as the UI import, but local text scan found no direct reference to the new UI sounds/events."
    elif rel in REVIEW_PREVIOUS_AUTHORED:
        category = "REVIEW_PREVIOUS_AUTHORED_WORK"
        action = "Inspect diff and decide whether this belongs to another previous task. Do not mix blindly with the UI changelist."
        confidence = "Medium"
        reason = "Authored Wwise file changed before the 16:09 UI import window, likely previous work or unrelated save."
    elif rel.startswith("ProjectEF\\") and suffix in AUTHORED_EXTENSIONS and (created >= dt.datetime(2026, 6, 1) or modified >= dt.datetime(2026, 6, 1)):
        category = "REVIEW_RECENT_AUTHORED_PROJECTEF"
        action = "Review manually. Keep only if it matches a known task."
        confidence = "Medium"
        reason = "Recent authored ProjectEF file not matched to the known UI task list."

    return {
        "category": category,
        "recommended_action": action,
        "confidence": confidence,
        "reason": reason,
        "rel_path": rel,
        "full_path": str(path),
        "extension": suffix or "[none]",
        "size_mb": size_mb(stat.st_size),
        "created": created.isoformat(timespec="seconds"),
        "modified": modified.isoformat(timespec="seconds"),
        "ui_evidence": evidence,
    }


def collect_candidates() -> list[Path]:
    candidates: set[Path] = set()

    if OLD_PROJECT_ROOT.exists():
        candidates.update(path for path in OLD_PROJECT_ROOT.rglob("*") if path.is_file())

    if PROJECT_ROOT.exists():
        for path in PROJECT_ROOT.rglob("*"):
            if not path.is_file():
                continue
            stat = path.stat()
            created = dt.datetime.fromtimestamp(stat.st_ctime)
            modified = dt.datetime.fromtimestamp(stat.st_mtime)
            rel = rel_workspace(path)
            if (
                created >= dt.datetime(2026, 6, 1)
                or modified >= dt.datetime(2026, 6, 1)
                or rel in THIS_TASK_KEEP
                or rel in SAME_SAVE_REVIEW
                or rel in REVIEW_PREVIOUS_AUTHORED
                or path_has_prefix_part(path, "GeneratedSoundBanks_Backup_")
            ):
                candidates.add(path)

    return sorted(candidates, key=lambda item: rel_workspace(item).lower())


def table(rows: list[list[Any]], headers: list[str]) -> str:
    if not rows:
        rows = [["-", *[""] * (len(headers) - 1)]]
    text_rows = [[str(cell) for cell in row] for row in rows]
    all_rows = [headers] + text_rows
    widths = [max(len(row[index]) for row in all_rows) for index in range(len(headers))]
    out = [
        "| " + " | ".join(headers[index].ljust(widths[index]) for index in range(len(headers))) + " |",
        "| " + " | ".join("-" * widths[index] for index in range(len(headers))) + " |",
    ]
    for row in text_rows:
        out.append("| " + " | ".join(row[index].ljust(widths[index]) for index in range(len(headers))) + " |")
    return "\n".join(out)


def render_markdown(rows: list[dict[str, Any]]) -> str:
    counts = Counter(row["category"] for row in rows)
    sizes = defaultdict(float)
    for row in rows:
        sizes[row["category"]] += row["size_mb"]

    keep_rows = [row for row in rows if row["category"] == "KEEP_THIS_UI_TASK"]
    review_rows = [
        row
        for row in rows
        if row["category"]
        in {
            "REVIEW_SAME_SAVE_NO_UI_EVIDENCE",
            "REVIEW_PREVIOUS_AUTHORED_WORK",
            "REVIEW_RECENT_AUTHORED_PROJECTEF",
            "GENERATED_BANK_POLICY_REVIEW",
        }
    ]
    exclude_rows = [
        row
        for row in rows
        if row["category"] in {"OLD_PROJECT_EXCLUDE", "SOUNDBANK_BACKUP_EXCLUDE", "GENERATED_CACHE_EXCLUDE"}
    ]

    old_project_rows = [row for row in rows if row["category"] == "OLD_PROJECT_EXCLUDE"]
    old_mod_2026 = [
        row
        for row in old_project_rows
        if row["created"] >= "2026-01-01" or row["modified"] >= "2026-01-01"
    ]

    return "\n".join(
        [
            "# ProjectEF Changelist Reconstruction",
            "",
            f"- Generated: {dt.datetime.now().isoformat(timespec='seconds')}",
            f"- Workspace: `{WORKSPACE_ROOT}`",
            f"- Current project: `{PROJECT_ROOT}`",
            f"- Old project folder: `{OLD_PROJECT_ROOT}`",
            "",
            "## Executive Read",
            "",
            "- Do not revert the whole pending changelist.",
            "- The known current UI task is a small set: 6 source WAV files plus 2 UI WorkUnits.",
            "- `ProjectEF_2021` has no 2026-created or 2026-modified files, so its pending files are almost certainly reconcile scope noise, not recent work.",
            "- SoundBank backups, `.cache`, `.prof`, `.wsettings`, validation/cache files should be excluded from submit.",
            "",
            "## Category Summary",
            "",
            table(
                [[category, counts[category], round(sizes[category], 3)] for category in sorted(counts)],
                ["Category", "Files", "MB"],
            ),
            "",
            "## Keep For This UI Task",
            "",
            table(
                [
                    [row["rel_path"], row["size_mb"], row["modified"], row["ui_evidence"] or "-"]
                    for row in keep_rows
                ],
                ["Path", "MB", "Modified", "Evidence"],
            ),
            "",
            "## Review Before Keeping",
            "",
            table(
                [
                    [row["category"], row["rel_path"], row["size_mb"], row["modified"], row["reason"]]
                    for row in review_rows[:120]
                ],
                ["Category", "Path", "MB", "Modified", "Reason"],
            ),
            "",
            "## Exclude / Do Not Submit",
            "",
            table(
                [
                    [row["category"], row["rel_path"], row["size_mb"], row["modified"]]
                    for row in exclude_rows[:160]
                ],
                ["Category", "Path", "MB", "Modified"],
            ),
            "",
            f"- Exclude table is capped at 160 rows for readability. Full row list is in the CSV.",
            f"- `ProjectEF_2021` files with 2026 timestamps: {len(old_mod_2026)}.",
            "",
            "## Safe P4V Rebuild Plan",
            "",
            "1. Close Wwise and Unity.",
            "2. Create a new changelist named `KEEP_ProjectEF_UI_Work`.",
            "3. Move only `KEEP_THIS_UI_TASK` rows into that changelist first.",
            "4. Put `REVIEW_*` rows into a separate `REVIEW_Possible_Previous_Work` changelist, or leave them in default until diffed.",
            "5. For `ProjectEF_2021/...`, `GeneratedSoundBanks_Backup_*`, `.cache`, `.prof`, `.wsettings`: revert from pending. If P4V warns that added files will be deleted and you want the local copy, use keep-workspace-copy or copy the folder outside the workspace first.",
            "6. After cleanup, reconcile only `D:\\EF Wwise\\ProjectEF`, not the workspace root `D:\\EF Wwise`.",
            "",
        ]
    )


def main() -> int:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    rows = [classify(path) for path in collect_candidates()]
    rows = [row for row in rows if row["category"] != "Ignore"]

    md_path = REPORT_DIR / f"ProjectEF_Changelist_Reconstruction_{stamp}.md"
    csv_path = REPORT_DIR / f"ProjectEF_Changelist_Reconstruction_{stamp}.csv"
    json_path = REPORT_DIR / f"ProjectEF_Changelist_Reconstruction_{stamp}.json"

    md_path.write_text(render_markdown(rows), encoding="utf-8")
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()) if rows else [])
        writer.writeheader()
        writer.writerows(rows)
    json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    print(md_path)
    print(csv_path)
    print(json_path)
    print(f"Rows: {len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
