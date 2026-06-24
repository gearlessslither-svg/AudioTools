from __future__ import annotations

import argparse
import csv
import os
import shutil
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

try:
    import tkinter as tk
    from tkinter import scrolledtext, ttk
except Exception:  # pragma: no cover - GUI import is checked at runtime.
    tk = None
    ttk = None
    scrolledtext = None


APP_NAME = "Desktop Downloads Organizer"
VERSION = "2026-06-22"
ORGANIZED_FOLDER_NAME = "_Desktop_Downloads_Organized"
LOGS_FOLDER_NAME = "_logs"
FOLDER_CATEGORY = "00_Folders"

KNOWN_DOWNLOADS_GUID = "{374DE290-123F-4565-9164-39C4925E467B}"

SYSTEM_FILENAMES = {
    "desktop.ini",
    "thumbs.db",
    ".ds_store",
}

PROTECTED_FOLDER_NAMES = {
    "$recycle.bin",
    "system volume information",
}

# Files that can launch code, install software, change registry state, or behave
# like shortcuts are intentionally left where they are.
PROTECTED_EXTENSIONS = {
    ".appref-ms",
    ".appx",
    ".appxbundle",
    ".bat",
    ".cmd",
    ".com",
    ".cpl",
    ".dll",
    ".drv",
    ".exe",
    ".gadget",
    ".hta",
    ".inf",
    ".ins",
    ".iso",
    ".jar",
    ".jnlp",
    ".js",
    ".jse",
    ".lnk",
    ".msc",
    ".msi",
    ".msix",
    ".msixbundle",
    ".msp",
    ".pif",
    ".ps1",
    ".ps1xml",
    ".ps2",
    ".psc1",
    ".psc2",
    ".py",
    ".pyc",
    ".pyo",
    ".reg",
    ".scr",
    ".sh",
    ".sys",
    ".url",
    ".vb",
    ".vbe",
    ".vbs",
    ".ws",
    ".wsf",
    ".wsh",
    ".xlsm",
    ".xltm",
    ".docm",
    ".dotm",
    ".pptm",
    ".potm",
    ".ppam",
}

CATEGORY_EXTENSIONS: Sequence[Tuple[str, Sequence[str]]] = (
    (
        "01_Documents",
        (
            ".pdf",
            ".doc",
            ".docx",
            ".dot",
            ".dotx",
            ".rtf",
            ".txt",
            ".md",
            ".markdown",
            ".odt",
            ".pages",
            ".epub",
            ".mobi",
            ".wps",
        ),
    ),
    (
        "02_Spreadsheets",
        (
            ".xls",
            ".xlsx",
            ".xlt",
            ".xltx",
            ".ods",
            ".csv",
            ".tsv",
            ".numbers",
        ),
    ),
    (
        "03_Presentations",
        (
            ".ppt",
            ".pptx",
            ".pot",
            ".potx",
            ".pps",
            ".ppsx",
            ".odp",
            ".key",
        ),
    ),
    (
        "04_Images",
        (
            ".jpg",
            ".jpeg",
            ".png",
            ".gif",
            ".bmp",
            ".tif",
            ".tiff",
            ".webp",
            ".heic",
            ".heif",
            ".raw",
            ".cr2",
            ".nef",
            ".arw",
            ".svg",
            ".ico",
        ),
    ),
    (
        "05_Video",
        (
            ".mp4",
            ".mov",
            ".mkv",
            ".avi",
            ".wmv",
            ".flv",
            ".webm",
            ".m4v",
            ".mpeg",
            ".mpg",
            ".3gp",
        ),
    ),
    (
        "06_Audio",
        (
            ".mp3",
            ".wav",
            ".flac",
            ".aac",
            ".ogg",
            ".m4a",
            ".wma",
            ".aiff",
            ".mid",
            ".midi",
        ),
    ),
    (
        "07_Archives",
        (
            ".zip",
            ".rar",
            ".7z",
            ".tar",
            ".gz",
            ".bz2",
            ".xz",
            ".tgz",
            ".tbz2",
        ),
    ),
    (
        "08_Design",
        (
            ".psd",
            ".ai",
            ".eps",
            ".indd",
            ".xd",
            ".fig",
            ".sketch",
            ".blend",
            ".fbx",
            ".obj",
            ".stl",
        ),
    ),
    (
        "09_Data",
        (
            ".json",
            ".xml",
            ".yaml",
            ".yml",
            ".toml",
            ".ini",
            ".log",
            ".sqlite",
            ".sqlite3",
            ".db",
        ),
    ),
)

CATEGORY_BY_EXTENSION: Dict[str, str] = {
    extension: category
    for category, extensions in CATEGORY_EXTENSIONS
    for extension in extensions
}


@dataclass
class Operation:
    action: str
    source: str
    destination: str = ""
    reason: str = ""


@dataclass
class OrganizeSummary:
    roots: List[Path]
    output_dir: Path
    moved: int = 0
    skipped: int = 0
    failed: int = 0
    log_path: Optional[Path] = None
    operations: List[Operation] = field(default_factory=list)

    def line(self) -> str:
        return (
            f"完成：移动 {self.moved} 个项目，跳过 {self.skipped} 个，失败 {self.failed} 个。"
            f"归档文件夹：{self.output_dir}"
        )


def expand_windows_path(raw: str) -> Path:
    return Path(os.path.expandvars(raw)).expanduser()


def registry_known_folder(name: str) -> Optional[Path]:
    if os.name != "nt":
        return None
    try:
        import winreg

        key_path = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            value, _ = winreg.QueryValueEx(key, name)
        return expand_windows_path(str(value))
    except Exception:
        return None


def current_user_desktop() -> Path:
    return registry_known_folder("Desktop") or Path.home() / "Desktop"


def current_user_downloads() -> Path:
    return registry_known_folder(KNOWN_DOWNLOADS_GUID) or Path.home() / "Downloads"


def is_c_drive(path: Path) -> bool:
    drive = path.drive.rstrip("\\/").lower()
    return drive == "c:"


def default_source_roots() -> List[Path]:
    candidates = [current_user_desktop(), current_user_downloads()]
    roots: List[Path] = []
    seen = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except Exception:
            resolved = candidate
        key = str(resolved).casefold()
        if key not in seen:
            roots.append(resolved)
            seen.add(key)
    return roots


def default_output_dir(desktop: Optional[Path] = None) -> Path:
    base = desktop or current_user_desktop()
    return base / ORGANIZED_FOLDER_NAME


def category_for(path: Path) -> str:
    return CATEGORY_BY_EXTENSION.get(path.suffix.lower(), "99_Others")


def is_inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except Exception:
        return False


def windows_file_attributes(path: Path) -> Optional[int]:
    if os.name != "nt":
        return None
    try:
        import ctypes

        attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
        if attrs == -1:
            return None
        return int(attrs)
    except Exception:
        return None


def is_hidden_or_system(path: Path) -> bool:
    if os.name != "nt":
        return path.name.startswith(".")
    attrs = windows_file_attributes(path)
    if attrs is None:
        return path.name.startswith(".")
    hidden = bool(attrs & 0x2)
    system = bool(attrs & 0x4)
    return hidden or system


def is_reparse_point(path: Path) -> bool:
    if path.is_symlink():
        return True
    attrs = windows_file_attributes(path)
    return bool(attrs is not None and attrs & 0x400)


def unique_destination(dest: Path) -> Path:
    if not dest.exists():
        return dest
    stem = dest.stem
    suffix = dest.suffix
    parent = dest.parent
    for index in range(1, 10000):
        candidate = parent / f"{stem} ({index}){suffix}"
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"too many duplicate filenames for {dest.name}")


def iter_direct_files(root: Path) -> Iterable[Path]:
    try:
        for entry in root.iterdir():
            yield entry
    except PermissionError:
        return


def folder_protection_reason(folder: Path) -> Optional[str]:
    try:
        for child in folder.rglob("*"):
            name_lower = child.name.lower()
            if name_lower in SYSTEM_FILENAMES:
                continue
            if is_reparse_point(child):
                return f"contains symlink/reparse item: {child.name}"
            if is_hidden_or_system(child):
                return f"contains hidden/system item: {child.name}"
            if child.is_file() and child.suffix.lower() in PROTECTED_EXTENSIONS:
                return f"contains protected executable/script/macro file: {child.name}"
    except PermissionError:
        return "folder cannot be fully inspected"
    except OSError as exc:
        return f"folder cannot be fully inspected: {exc}"
    return None


def should_skip(path: Path, root: Path, output_dir: Path) -> Optional[str]:
    name_lower = path.name.lower()
    if name_lower in SYSTEM_FILENAMES:
        return "system desktop/cache file"
    if name_lower in PROTECTED_FOLDER_NAMES:
        return "protected system folder"
    if is_inside(path, output_dir):
        return "already in organized folder"
    if is_reparse_point(path):
        return "symlink/reparse shortcut skipped"
    if is_hidden_or_system(path):
        return "hidden or system file"
    if path.is_dir():
        return folder_protection_reason(path)
    if not path.is_file():
        return "not a regular file"
    if path.suffix.lower() in PROTECTED_EXTENSIONS:
        return "shortcut/executable/script/macro file protected"
    try:
        path.resolve().relative_to(root.resolve())
    except Exception:
        return "file is outside source root"
    return None


def write_log(output_dir: Path, operations: Sequence[Operation]) -> Path:
    logs_dir = output_dir / LOGS_FOLDER_NAME
    logs_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = logs_dir / f"organize_{stamp}.csv"
    with log_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(["time", "action", "source", "destination", "reason"])
        now = datetime.now().isoformat(timespec="seconds")
        for op in operations:
            writer.writerow([now, op.action, op.source, op.destination, op.reason])
    return log_path


def organize_files(
    roots: Optional[Sequence[Path]] = None,
    output_dir: Optional[Path] = None,
    *,
    require_c_drive: bool = True,
    progress: Optional[Callable[[str], None]] = None,
) -> OrganizeSummary:
    source_roots = [Path(root) for root in (roots or default_source_roots())]
    desktop = source_roots[0] if source_roots else current_user_desktop()
    target_dir = Path(output_dir) if output_dir else default_output_dir(desktop)
    target_dir.mkdir(parents=True, exist_ok=True)

    summary = OrganizeSummary(roots=source_roots, output_dir=target_dir)

    def log(action: str, source: Path, destination: Path | str = "", reason: str = "") -> None:
        op = Operation(action, str(source), str(destination) if destination else "", reason)
        summary.operations.append(op)
        if progress:
            if action == "move":
                progress(f"移动：{source.name} -> {Path(str(destination)).parent.name}")
            elif action == "skip":
                progress(f"跳过：{source.name} ({reason})")
            elif action == "fail":
                progress(f"失败：{source.name} ({reason})")

    for root in source_roots:
        if not root.exists():
            summary.skipped += 1
            log("skip", root, reason="source folder does not exist")
            continue
        if require_c_drive and not is_c_drive(root):
            summary.skipped += 1
            log("skip", root, reason="source folder is not on C drive")
            continue
        if progress:
            progress(f"扫描：{root}")
        for path in iter_direct_files(root):
            reason = should_skip(path, root, target_dir)
            if reason:
                summary.skipped += 1
                log("skip", path, reason=reason)
                continue
            try:
                category = FOLDER_CATEGORY if path.is_dir() else category_for(path)
                category_dir = target_dir / category
                category_dir.mkdir(parents=True, exist_ok=True)
                destination = unique_destination(category_dir / path.name)
                shutil.move(str(path), str(destination))
                summary.moved += 1
                log("move", path, destination)
            except Exception as exc:
                summary.failed += 1
                log("fail", path, reason=str(exc))

    summary.log_path = write_log(target_dir, summary.operations)
    if progress:
        progress(summary.line())
        progress(f"日志：{summary.log_path}")
    return summary


class OrganizerGui:
    def __init__(self) -> None:
        if tk is None or ttk is None or scrolledtext is None:
            raise RuntimeError("tkinter is not available in this Python installation")

        self.root = tk.Tk()
        self.root.title(APP_NAME)
        self.root.geometry("640x420")
        self.root.minsize(520, 320)

        self.status = tk.StringVar(value="准备就绪：点击按钮整理当前用户 C 盘桌面和 Downloads。")

        frame = ttk.Frame(self.root, padding=14)
        frame.pack(fill=tk.BOTH, expand=True)

        self.button = ttk.Button(frame, text="开始整理桌面和 Downloads", command=self.start)
        self.button.pack(fill=tk.X, pady=(0, 10))

        status_label = ttk.Label(frame, textvariable=self.status, anchor="w")
        status_label.pack(fill=tk.X, pady=(0, 8))

        self.log_box = scrolledtext.ScrolledText(frame, height=14, wrap=tk.WORD)
        self.log_box.pack(fill=tk.BOTH, expand=True)
        self.log_box.configure(state=tk.DISABLED)

    def append_log(self, text: str) -> None:
        self.log_box.configure(state=tk.NORMAL)
        self.log_box.insert(tk.END, text + "\n")
        self.log_box.see(tk.END)
        self.log_box.configure(state=tk.DISABLED)
        self.status.set(text)

    def post_log(self, text: str) -> None:
        self.root.after(0, lambda: self.append_log(text))

    def start(self) -> None:
        self.button.configure(state=tk.DISABLED)
        self.append_log(f"{APP_NAME} {VERSION}")
        self.append_log("开始整理。安全的普通文件夹会归入 00_Folders；含执行文件/脚本/宏文件的文件夹会被跳过。")

        def worker() -> None:
            try:
                organize_files(progress=self.post_log)
            except Exception as exc:
                self.post_log(f"整理失败：{exc}")
            finally:
                self.root.after(0, lambda: self.button.configure(state=tk.NORMAL))

        threading.Thread(target=worker, daemon=True).start()

    def run(self) -> int:
        self.root.mainloop()
        return 0


def run_self_test() -> int:
    with tempfile.TemporaryDirectory(prefix="desktop_file_organizer_") as tmp:
        base = Path(tmp)
        desktop = base / "Desktop"
        downloads = base / "Downloads"
        output = desktop / ORGANIZED_FOLDER_NAME
        desktop.mkdir()
        downloads.mkdir()
        samples = {
            desktop / "report.pdf": "pdf",
            desktop / "shortcut.lnk": "shortcut",
            desktop / "tool.exe": "exe",
            desktop / "photo.png": "image",
            downloads / "data.csv": "csv",
            downloads / "script.ps1": "script",
            downloads / "archive.zip": "zip",
        }
        for path, text in samples.items():
            path.write_text(text, encoding="utf-8")
        safe_folder = desktop / "ExistingFolder"
        safe_folder.mkdir()
        (safe_folder / "notes.txt").write_text("notes", encoding="utf-8")
        protected_folder = downloads / "InstallerFolder"
        protected_folder.mkdir()
        (protected_folder / "setup.exe").write_text("exe", encoding="utf-8")

        summary = organize_files(
            roots=[desktop, downloads],
            output_dir=output,
            require_c_drive=False,
        )

        expected_moved = [
            output / "01_Documents" / "report.pdf",
            output / "02_Spreadsheets" / "data.csv",
            output / "04_Images" / "photo.png",
            output / "07_Archives" / "archive.zip",
            output / "00_Folders" / "ExistingFolder",
        ]
        expected_kept = [
            desktop / "shortcut.lnk",
            desktop / "tool.exe",
            downloads / "script.ps1",
            downloads / "InstallerFolder",
        ]
        missing = [str(path) for path in expected_moved if not path.exists()]
        moved_protected = [str(path) for path in expected_kept if not path.exists()]
        if missing or moved_protected or summary.moved != 5 or summary.failed:
            print("SELF TEST FAILED")
            print("missing moved:", missing)
            print("protected moved:", moved_protected)
            print(summary)
            return 1
        print("SELF TEST OK")
        print(summary.line())
        print(f"log={summary.log_path}")
        return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--self-test", action="store_true", help="run a temp-folder safety test")
    parser.add_argument("--cli", action="store_true", help="run once without opening the GUI")
    parser.add_argument(
        "--allow-non-c-drive",
        action="store_true",
        help="allow source folders outside C drive; GUI keeps the C-drive guard on",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.self_test:
        return run_self_test()
    if args.cli:
        summary = organize_files(require_c_drive=not args.allow_non_c_drive, progress=print)
        return 1 if summary.failed else 0
    gui = OrganizerGui()
    return gui.run()


if __name__ == "__main__":
    raise SystemExit(main())
