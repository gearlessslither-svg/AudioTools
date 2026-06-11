#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any

from waapi import WaapiClient


TARGETS = [
    r"\Actor-Mixer Hierarchy\UI\UI\UI_CoinLayer",
    r"\Actor-Mixer Hierarchy\UI\UI\UI_GetFish",
]

PROPERTIES = {
    "UseMaxSoundPerInstance": True,
    "MaxSoundPerInstance": 5,
    "OverLimitBehavior": 1,
}


def call(client: WaapiClient, uri: str, args: dict[str, Any]) -> dict[str, Any]:
    result = client.call(uri, args)
    if result is None:
        raise RuntimeError(f"WAAPI call returned None: {uri}")
    return result


def get_object(client: WaapiClient, path: str) -> dict[str, Any]:
    result = call(
        client,
        "ak.wwise.core.object.get",
        {
            "from": {"path": [path]},
            "options": {
                "return": [
                    "id",
                    "name",
                    "type",
                    "path",
                    "@UseMaxSoundPerInstance",
                    "@MaxSoundPerInstance",
                    "@OverLimitBehavior",
                ]
            },
        },
    )
    rows = result.get("return") or []
    if len(rows) != 1:
        raise RuntimeError(f"Expected exactly one object for {path}, got {len(rows)}")
    return rows[0]


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply conservative playback limits to ProjectEF UI burst containers.")
    parser.add_argument("--waapi", default="ws://127.0.0.1:8080/waapi")
    parser.add_argument("--out", required=True)
    parser.add_argument("--json-out", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    report: dict[str, Any] = {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "dry_run": bool(args.dry_run),
        "saved": False,
        "properties": PROPERTIES,
        "items": [],
    }
    with WaapiClient(url=args.waapi) as client:
        for path in TARGETS:
            before = get_object(client, path)
            if not args.dry_run:
                for prop, value in PROPERTIES.items():
                    call(client, "ak.wwise.core.object.setProperty", {"object": before["id"], "property": prop, "value": value})
            after = get_object(client, path)
            report["items"].append(
                {
                    "path": path,
                    "status": "dry-run" if args.dry_run else "updated",
                    "before": {
                        "UseMaxSoundPerInstance": before.get("@UseMaxSoundPerInstance"),
                        "MaxSoundPerInstance": before.get("@MaxSoundPerInstance"),
                        "OverLimitBehavior": before.get("@OverLimitBehavior"),
                    },
                    "after": {
                        "UseMaxSoundPerInstance": after.get("@UseMaxSoundPerInstance"),
                        "MaxSoundPerInstance": after.get("@MaxSoundPerInstance"),
                        "OverLimitBehavior": after.get("@OverLimitBehavior"),
                    },
                }
            )
        if not args.dry_run:
            call(client, "ak.wwise.core.project.save", {})
            report["saved"] = True

    md = [
        "# ProjectEF UI Playback Limit Apply Report",
        "",
        f"- Generated: {report['generated_at']}",
        f"- Dry run: {report['dry_run']}",
        f"- Saved Wwise project: {report['saved']}",
        "",
        "| Path | Status | Before | After |",
        "|---|---|---|---|",
    ]
    for item in report["items"]:
        md.append(
            f"| `{item['path']}` | {item['status']} | "
            f"`{json.dumps(item['before'], ensure_ascii=False)}` | "
            f"`{json.dumps(item['after'], ensure_ascii=False)}` |"
        )
    out = Path(args.out)
    json_out = Path(args.json_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    json_out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(md) + "\n", encoding="utf-8")
    json_out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out)
    print(json_out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
