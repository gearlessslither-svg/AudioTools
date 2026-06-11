#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any

from waapi import WaapiClient


DEFAULT_TARGETS = [
    r"\Actor-Mixer Hierarchy\Player\Footsteps\Sneakers\Run_Backward",
    r"\Actor-Mixer Hierarchy\Player\Footsteps\Sneakers\Run_Forward",
    r"\Actor-Mixer Hierarchy\Player\Footsteps\Sneakers\Walk_Backward",
    r"\Actor-Mixer Hierarchy\Player\Footsteps\Sneakers\Walk_Forward",
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


def set_property(client: WaapiClient, object_id: str, prop: str, value: Any) -> None:
    call(
        client,
        "ak.wwise.core.object.setProperty",
        {"object": object_id, "property": prop, "value": value},
    )


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# ProjectEF Footstep Playback Limit Apply Report",
        "",
        f"- Generated: {report['generated_at']}",
        f"- Dry run: {report['dry_run']}",
        f"- Saved Wwise project: {report['saved']}",
        "",
        "## Applied Policy",
        "",
        "- Scope: Player footstep movement-level SwitchContainers under Sneakers.",
        "- Rationale: Others branches already use MaxSoundPerInstance=5; Player branches lacked an effective inherited limit.",
        "- Properties: UseMaxSoundPerInstance=True, MaxSoundPerInstance=5, OverLimitBehavior=1.",
        "",
        "## Results",
        "",
        "| Path | Status | Before | After |",
        "|---|---|---|---|",
    ]
    for item in report["items"]:
        before = json.dumps(item.get("before", {}), ensure_ascii=False)
        after = json.dumps(item.get("after", {}), ensure_ascii=False)
        lines.append(f"| `{item['path']}` | {item['status']} | `{before}` | `{after}` |")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply conservative playback limits to ProjectEF Player footsteps.")
    parser.add_argument("--waapi", default="ws://127.0.0.1:8080/waapi")
    parser.add_argument("--out", required=True)
    parser.add_argument("--json-out", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    report: dict[str, Any] = {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "dry_run": bool(args.dry_run),
        "saved": False,
        "targets": DEFAULT_TARGETS,
        "properties": PROPERTIES,
        "items": [],
    }

    with WaapiClient(url=args.waapi) as client:
        for path in DEFAULT_TARGETS:
            before = get_object(client, path)
            item = {
                "path": path,
                "id": before["id"],
                "status": "dry-run" if args.dry_run else "updated",
                "before": {
                    "UseMaxSoundPerInstance": before.get("@UseMaxSoundPerInstance"),
                    "MaxSoundPerInstance": before.get("@MaxSoundPerInstance"),
                    "OverLimitBehavior": before.get("@OverLimitBehavior"),
                },
            }
            if not args.dry_run:
                for prop, value in PROPERTIES.items():
                    set_property(client, before["id"], prop, value)
            after = get_object(client, path)
            item["after"] = {
                "UseMaxSoundPerInstance": after.get("@UseMaxSoundPerInstance"),
                "MaxSoundPerInstance": after.get("@MaxSoundPerInstance"),
                "OverLimitBehavior": after.get("@OverLimitBehavior"),
            }
            report["items"].append(item)
        if not args.dry_run:
            call(client, "ak.wwise.core.project.save", {})
            report["saved"] = True

    out = Path(args.out)
    json_out = Path(args.json_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    json_out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_markdown(report), encoding="utf-8")
    json_out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out)
    print(json_out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
