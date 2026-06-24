# Desktop Downloads Organizer

Lightweight Windows desktop organizer.

## What It Does

- Opens a small GUI with one main button.
- Scans the current user's C-drive Desktop and Downloads folders.
- Moves loose ordinary files and safe ordinary folders into one folder on the Desktop:
  `C:\Users\<user>\Desktop\_Desktop_Downloads_Organized`
- Sorts moved files by category folder, for example `01_Documents`, `04_Images`, `07_Archives`.
- Moves safe ordinary folders into `00_Folders`.
- Writes a CSV operation log under `_Desktop_Downloads_Organized\_logs`.

## Safety Rules

The tool intentionally skips:

- Folders that contain protected executables, scripts, macro-enabled Office files, hidden/system items, or symlinks/reparse points.
- Shortcuts: `.lnk`, `.url`.
- Executables/installers: `.exe`, `.msi`, `.msix`, `.appx`, `.com`, `.scr`.
- Scripts/automation files: `.bat`, `.cmd`, `.ps1`, `.vbs`, `.js`, `.py`, `.jar`, etc.
- Macro-enabled Office files: `.docm`, `.xlsm`, `.pptm`, etc.
- Hidden/system files such as `desktop.ini`.
- Source folders outside the C drive in GUI mode.

Existing files are never overwritten. If a name already exists, the tool creates names like
`file (1).pdf`.

## Run

Double-click:

```bat
Start_Desktop_File_Organizer.cmd
```

Or from PowerShell:

```powershell
python desktop_file_organizer.py
```

## Test

```powershell
python desktop_file_organizer.py --self-test
```
