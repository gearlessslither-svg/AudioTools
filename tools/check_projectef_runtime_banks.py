#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


DEFAULT_TOP_EVENTS = [
    "Play_Fish_WaterIn",
    "Play_Footsteps_Walk_Forward_Sneakers",
    "Play_Footsteps_Walk_Backward_Sneakers",
    "Play_Lure_WaterOut",
    "Play_Lure_WaterIn",
    "Stop_Wheel_Retrieve",
    "Stop_Line_Out",
    "Play_Line_Cast",
    "Play_Spool_Open",
    "Play_Spool_Lock",
]


def strip_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def load_audit(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig", errors="replace"))


def authored_events(audit: dict[str, Any]) -> list[str]:
    objects = audit.get("parsed", {}).get("objects", [])
    names = {
        str(item.get("name", "")).strip()
        for item in objects
        if item.get("type") == "Event" and str(item.get("name", "")).strip()
    }
    return sorted(names)


def bank_events(bank_root: Path) -> list[str]:
    event_dir = bank_root / "Event"
    if event_dir.exists():
        names = {path.stem for path in event_dir.glob("*.bnk") if path.is_file()}
    else:
        names = {path.stem for path in bank_root.glob("*.bnk") if path.is_file() and path.stem != "Init"}
    return sorted(names)


def read_soundbanks_info(bank_root: Path) -> dict[str, Any]:
    path = bank_root / "SoundbanksInfo.xml"
    info: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "size_kb": 0.0,
        "modified": "",
        "bank_count": 0,
        "event_count": 0,
        "root_paths": {},
        "events": [],
    }
    if not path.exists():
        return info

    stat = path.stat()
    info["size_kb"] = round(stat.st_size / 1024, 1)
    info["modified"] = dt.datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")

    root = ET.parse(path).getroot()
    events = []
    for elem in root.iter():
        tag = strip_ns(elem.tag)
        if tag == "SoundBank":
            info["bank_count"] += 1
        elif tag == "Event":
            name = elem.attrib.get("Name") or elem.attrib.get("ShortName") or ""
            event_id = elem.attrib.get("Id") or elem.attrib.get("ID") or ""
            events.append({"name": name, "id": event_id})
        elif tag in {"ProjectRoot", "SourceFilesRoot", "SoundBanksRoot", "ExternalSourcesOutputRoot"}:
            if elem.text:
                info["root_paths"][tag] = elem.text.strip()
    info["events"] = events
    info["event_count"] = len(events)
    return info


def file_info(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False}
    stat = path.stat()
    return {
        "exists": True,
        "size_kb": round(stat.st_size / 1024, 1),
        "modified": dt.datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        "path": str(path),
    }


def analyze(audit_json: Path, bank_root: Path, top_events: list[str]) -> dict[str, Any]:
    audit = load_audit(audit_json)
    authored = authored_events(audit)
    banks = bank_events(bank_root)
    authored_set = set(authored)
    bank_set = set(banks)
    event_dir = bank_root / "Event"
    media_dir = bank_root / "Media"
    sbi = read_soundbanks_info(bank_root)

    return {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "audit_json": str(audit_json),
        "bank_root": str(bank_root),
        "event_dir": str(event_dir),
        "authored_event_count": len(authored),
        "runtime_event_bank_count": len(banks),
        "missing_event_banks": sorted(authored_set - bank_set),
        "extra_event_banks": sorted(bank_set - authored_set),
        "soundbanks_info": sbi,
        "media_wem_count": len(list(media_dir.glob("*.wem"))) if media_dir.exists() else 0,
        "top_event_bank_status": [
            {"event": name, **file_info(event_dir / f"{name}.bnk")}
            for name in top_events
        ],
    }


def table(rows: list[list[Any]], headers: list[str]) -> str:
    if not rows:
        rows = [["-", "-", "-"][: len(headers)]]
    all_rows = [headers] + [[str(cell) for cell in row] for row in rows]
    widths = [max(len(row[i]) for row in all_rows) for i in range(len(headers))]
    out = []
    out.append("| " + " | ".join(headers[i].ljust(widths[i]) for i in range(len(headers))) + " |")
    out.append("| " + " | ".join("-" * widths[i] for i in range(len(headers))) + " |")
    for row in all_rows[1:]:
        out.append("| " + " | ".join(row[i].ljust(widths[i]) for i in range(len(headers))) + " |")
    return "\n".join(out)


def render_markdown(result: dict[str, Any]) -> str:
    missing = result["missing_event_banks"]
    extra = result["extra_event_banks"]
    sbi = result["soundbanks_info"]
    status = "PASS" if not missing and not extra else "CHECK"

    lines = [
        "# ProjectEF Runtime Bank Output Check",
        "",
        f"- Generated: {result['generated_at']}",
        f"- Audit JSON: `{result['audit_json']}`",
        f"- Runtime bank root: `{result['bank_root']}`",
        f"- Status: **{status}**",
        "",
        "## Summary",
        "",
        table(
            [
                ["Authored Wwise Events", result["authored_event_count"]],
                ["Runtime Event .bnk files", result["runtime_event_bank_count"]],
                ["Missing Event banks", len(missing)],
                ["Extra Event banks", len(extra)],
                ["SoundbanksInfo Events", sbi["event_count"]],
                ["SoundbanksInfo Banks", sbi["bank_count"]],
                ["Media .wem files", result["media_wem_count"]],
            ],
            ["Metric", "Value"],
        ),
        "",
        "## Top Prior Runtime Failures",
        "",
        table(
            [
                [
                    item["event"],
                    "Yes" if item.get("exists") else "No",
                    item.get("modified", "-"),
                    item.get("size_kb", "-"),
                ]
                for item in result["top_event_bank_status"]
            ],
            ["Event", "Has .bnk", "Modified", "KB"],
        ),
        "",
        "## Differences",
        "",
        "Missing Event banks:",
        "",
        "\n".join(f"- {name}" for name in missing) if missing else "- None",
        "",
        "Extra Event banks:",
        "",
        "\n".join(f"- {name}" for name in extra) if extra else "- None",
        "",
        "## SoundbanksInfo",
        "",
        f"- Exists: {sbi['exists']}",
        f"- Modified: {sbi.get('modified', '') or '-'}",
        f"- Size KB: {sbi.get('size_kb', 0)}",
        "",
        "Root paths:",
        "",
        "\n".join(f"- {key}: `{value}`" for key, value in sbi.get("root_paths", {}).items()) or "- None found",
        "",
        "## Interpretation",
        "",
        "- Runtime Event bank coverage matches authored Wwise Events when `Missing Event banks` and `Extra Event banks` are both zero.",
        "- This check only proves generated file presence and name coverage. Runtime load success still needs Unity play-session evidence.",
        "- If another audit reports missing Event bank coverage from `GeneratedSoundBanks`, verify whether the project is actually outputting banks to this runtime root.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare ProjectEF authored Wwise Events with runtime Event bank output.")
    parser.add_argument("--audit-json", required=True)
    parser.add_argument("--bank-root", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--json-out")
    parser.add_argument("--top-events", nargs="*", default=DEFAULT_TOP_EVENTS)
    args = parser.parse_args()

    result = analyze(Path(args.audit_json), Path(args.bank_root), args.top_events)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_markdown(result), encoding="utf-8")
    if args.json_out:
        json_out = Path(args.json_out)
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out)
    if args.json_out:
        print(args.json_out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
