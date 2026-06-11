from __future__ import annotations

import os
import re
from pathlib import Path


REQUIRED_SCRIPTS = [
    "Wwise Bridge Ver2.0.lua",
    "Codex_Enable auto-crossfade media items when editing.lua",
    "Codex_Visual slicer for selected item via source file.lua",
    "Codex_Visual slicer preset settings.lua",
    "codex_visual_event_analyzer.py",
]


def workspace_root() -> Path:
    return Path(__file__).resolve().parents[1]


def appdata_reaper_path() -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return Path.home() / "AppData" / "Roaming" / "REAPER"
    return Path(appdata) / "REAPER"


def file_hash(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def script_status(resource_path: Path) -> list[str]:
    scripts_dir = resource_path / "Scripts"
    mirror_dir = scripts_dir / "Codex"
    source_dir = workspace_root() / "reaper_scripts"
    lines = [
        f"Workspace source path: {source_dir}",
        f"REAPER resource path: {resource_path}",
        f"Scripts path: {scripts_dir}",
        "",
    ]
    for name in REQUIRED_SCRIPTS:
        source = source_dir / name
        target = scripts_dir / name
        mirror = mirror_dir / name
        if not source.exists():
            lines.append(f"SOURCE MISSING {name}")
            continue
        if not target.exists():
            lines.append(f"TARGET MISSING {name}")
        elif file_hash(source) == file_hash(target):
            lines.append(f"OK      root\\{name} ({target.stat().st_size} bytes)")
        else:
            lines.append(f"DRIFT   {name} (workspace and REAPER copies differ)")
        if not mirror.exists():
            lines.append(f"MIRROR MISSING Codex\\{name}")
        elif file_hash(source) == file_hash(mirror):
            lines.append(f"OK      Codex\\{name} ({mirror.stat().st_size} bytes)")
        else:
            lines.append(f"DRIFT   Codex\\{name} (workspace and mirror copies differ)")

    stale = scripts_dir / "Codex_Slice selected items by detected sound events.lua"
    if stale.exists():
        lines.append("")
        lines.append(f"STALE   {stale.name} still exists in REAPER Scripts")
    return lines


def keymap_status(resource_path: Path) -> list[str]:
    keymap = resource_path / "reaper-kb.ini"
    lines = ["", f"Keymap: {keymap}"]
    if not keymap.exists():
        return lines + ["MISSING reaper-kb.ini"]

    text = keymap.read_text(encoding="utf-8", errors="replace")
    for name in REQUIRED_SCRIPTS:
        if name.endswith(".py"):
            continue
        registered = name in text
        lines.append(f"{'REGISTERED' if registered else 'NOT REGISTERED'} {name}")

    shortcut_matches = re.findall(r"^KEY .+Codex_Visual slicer.+$", text, flags=re.MULTILINE)
    if shortcut_matches:
        lines.append("")
        lines.append("Visual slicer shortcuts:")
        lines.extend(shortcut_matches)
    else:
        lines.append("")
        lines.append("No visual slicer shortcut found.")

    wwise_matches = re.findall(r"^KEY .+Wwise Bridge Ver2\.0.+$", text, flags=re.MULTILINE)
    if wwise_matches:
        lines.append("")
        lines.append("Wwise Bridge shortcuts:")
        lines.extend(wwise_matches)
    else:
        lines.append("")
        lines.append("No Wwise Bridge shortcut found.")
    return lines


def extstate_status(resource_path: Path) -> list[str]:
    extstate = resource_path / "reaper-extstate.ini"
    lines = ["", f"ExtState: {extstate}"]
    if not extstate.exists():
        return lines + ["MISSING reaper-extstate.ini"]
    text = extstate.read_text(encoding="utf-8", errors="replace")
    for key in ["preset", "delete_gaps"]:
        match = re.search(rf"^{re.escape(key)}=(.*)$", text, flags=re.MULTILINE)
        if match:
            lines.append(f"{key}={match.group(1)}")
    return lines


def main() -> None:
    resource = appdata_reaper_path()
    lines: list[str] = []
    lines.extend(script_status(resource))
    lines.extend(keymap_status(resource))
    lines.extend(extstate_status(resource))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
