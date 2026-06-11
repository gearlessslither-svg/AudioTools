from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


SCRIPT_NAMES = [
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


def reaper_is_running() -> bool:
    if os.name != "nt":
        return False
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq reaper.exe"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return False
    return "reaper.exe" in result.stdout.lower()


def install_scripts() -> int:
    if reaper_is_running():
        print("REAPER is running. Close REAPER before installing scripts.")
        return 2

    root = workspace_root()
    source_dir = root / "reaper_scripts"
    target_dir = appdata_reaper_path() / "Scripts"
    mirror_dir = target_dir / "Codex"
    target_dir.mkdir(parents=True, exist_ok=True)
    mirror_dir.mkdir(parents=True, exist_ok=True)

    missing = [name for name in SCRIPT_NAMES if not (source_dir / name).exists()]
    if missing:
        for name in missing:
            print(f"Missing workspace source: {source_dir / name}")
        return 1

    for name in SCRIPT_NAMES:
        source = source_dir / name
        target = target_dir / name
        mirror = mirror_dir / name
        shutil.copy2(source, target)
        shutil.copy2(source, mirror)
        print(f"Installed {target}")
        print(f"Mirrored  {mirror}")

    stale = target_dir / "Codex_Slice selected items by detected sound events.lua"
    if stale.exists():
        stale_backup = target_dir / "Codex_Slice selected items by detected sound events.lua.disabled"
        if stale_backup.exists():
            stale_backup.unlink()
        stale.rename(stale_backup)
        print(f"Disabled stale script: {stale_backup}")

    print("Done. Open REAPER and load/register any new scripts from the Action List if needed.")
    return 0


if __name__ == "__main__":
    sys.exit(install_scripts())
