#!/usr/bin/env python3
import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path


FIELDNAMES = [
    "date",
    "project",
    "work_area",
    "task",
    "problem",
    "ai_role",
    "human_role",
    "output",
    "impact",
    "involvement",
    "source_grade",
    "evidence",
    "next_step",
]

ROLE_WEIGHTS = {
    "none": 0.0,
    "advisory": 0.25,
    "analysis": 0.5,
    "buildassist": 0.75,
    "controlledexecution": 1.0,
}


def read_ledger(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fp:
        return list(csv.DictReader(fp))


def ensure_ledger(path: Path):
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=FIELDNAMES)
        writer.writeheader()


def parse_date(value: str) -> date | None:
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except Exception:
        return None


def period_start(today: date, period: str) -> date:
    if period == "day":
        return today
    if period == "week":
        return today - timedelta(days=today.weekday())
    if period == "month":
        return today.replace(day=1)
    return date.min


def normalized_weight(row: dict) -> float:
    raw = (row.get("involvement") or "").strip()
    try:
        return max(0.0, min(1.0, float(raw)))
    except Exception:
        pass
    role = (row.get("ai_role") or "").replace(" ", "").lower()
    return ROLE_WEIGHTS.get(role, 0.0)


def summarize(rows: list[dict], period: str) -> dict:
    today = date.today()
    start = period_start(today, period)
    filtered = []
    for row in rows:
        row_date = parse_date(row.get("date", ""))
        if row_date and row_date >= start:
            filtered.append(row)

    total = len(filtered)
    assisted = sum(1 for row in filtered if normalized_weight(row) > 0)
    weighted = sum(normalized_weight(row) for row in filtered)
    grades = Counter((row.get("source_grade") or "Unknown").strip().upper() or "Unknown" for row in filtered)
    areas = Counter((row.get("work_area") or "Unknown").strip() or "Unknown" for row in filtered)
    roles = Counter((row.get("ai_role") or "Unknown").strip() or "Unknown" for row in filtered)
    high_evidence = grades.get("A", 0) + grades.get("B", 0)

    created_assets = [
        row for row in filtered
        if any(token in (row.get("work_area", "") + " " + row.get("impact", "")).lower()
               for token in ("tool", "skill", "report", "workflow", "script", "html", "asset"))
    ]
    by_day = defaultdict(list)
    for row in filtered:
        by_day[row.get("date", "Unknown")].append(row)

    return {
        "period": period,
        "start_date": start.isoformat(),
        "end_date": today.isoformat(),
        "total_tasks": total,
        "ai_assisted_tasks": assisted,
        "ai_assisted_coverage": assisted / total if total else 0,
        "weighted_ai_involvement": weighted / total if total else 0,
        "evidence_backed_impacts": high_evidence,
        "source_grades": dict(grades),
        "work_areas": dict(areas),
        "ai_roles": dict(roles),
        "created_assets_count": len(created_assets),
        "created_assets": created_assets,
        "rows": filtered,
        "by_day": {key: value for key, value in sorted(by_day.items())},
    }


def pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def markdown(summary: dict) -> str:
    lines = [
        "# AI Work Impact Summary",
        "",
        f"- **Period**: {summary['period']} ({summary['start_date']} to {summary['end_date']})",
        f"- **Recorded tasks**: {summary['total_tasks']}",
        f"- **AI-assisted tasks**: {summary['ai_assisted_tasks']} ({pct(summary['ai_assisted_coverage'])})",
        f"- **Weighted AI involvement**: {pct(summary['weighted_ai_involvement'])}",
        f"- **Evidence-backed impacts (A/B)**: {summary['evidence_backed_impacts']}",
        f"- **Reusable assets created**: {summary['created_assets_count']}",
        "",
        "## Source Quality",
        "",
        "| Grade | Count |",
        "|---|---:|",
    ]
    for grade, count in sorted(summary["source_grades"].items()):
        lines.append(f"| {grade} | {count} |")
    lines += [
        "",
        "## Work Areas",
        "",
        "| Area | Count |",
        "|---|---:|",
    ]
    for area, count in sorted(summary["work_areas"].items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"| {area} | {count} |")
    lines += [
        "",
        "## AI Roles",
        "",
        "| Role | Count |",
        "|---|---:|",
    ]
    for role, count in sorted(summary["ai_roles"].items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"| {role} | {count} |")
    lines += [
        "",
        "## Entries",
        "",
        "| Date | Area | Task | AI Role | Source | Impact | Evidence |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in summary["rows"]:
        cells = [
            row.get("date", ""),
            row.get("work_area", ""),
            row.get("task", ""),
            row.get("ai_role", ""),
            row.get("source_grade", ""),
            row.get("impact", ""),
            row.get("evidence", ""),
        ]
        lines.append("| " + " | ".join(str(cell).replace("|", "\\|").replace("\n", "<br>") for cell in cells) + " |")
    if not summary["rows"]:
        lines.append("| - | - | - | - | - | No entries in this period. | - |")
    return "\n".join(lines)


def add_entry(path: Path, args):
    ensure_ledger(path)
    row = {field: getattr(args, field.replace("-", "_"), "") or "" for field in FIELDNAMES}
    if not row["date"]:
        row["date"] = date.today().isoformat()
    if not row["involvement"]:
        row["involvement"] = str(ROLE_WEIGHTS.get(row["ai_role"].replace(" ", "").lower(), 0.0))
    with path.open("a", encoding="utf-8-sig", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=FIELDNAMES)
        writer.writerow(row)


def main():
    parser = argparse.ArgumentParser(description="Create and summarize an AI work impact ledger.")
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--period", choices=["day", "week", "month", "all"], default="week")
    parser.add_argument("--out-md")
    parser.add_argument("--out-json")
    parser.add_argument("--init", action="store_true")
    parser.add_argument("--add", action="store_true")
    for field in FIELDNAMES:
        parser.add_argument(f"--{field}")
    args = parser.parse_args()

    ledger = Path(args.ledger)
    if args.init:
        ensure_ledger(ledger)
    if args.add:
        add_entry(ledger, args)

    rows = read_ledger(ledger)
    summary = summarize(rows, args.period)

    if args.out_json:
        out_json = Path(args.out_json)
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8-sig")
    if args.out_md:
        out_md = Path(args.out_md)
        out_md.parent.mkdir(parents=True, exist_ok=True)
        out_md.write_text(markdown(summary), encoding="utf-8-sig")

    print(json.dumps({
        "ledger": str(ledger),
        "period": summary["period"],
        "total_tasks": summary["total_tasks"],
        "ai_assisted_coverage": summary["ai_assisted_coverage"],
        "weighted_ai_involvement": summary["weighted_ai_involvement"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
