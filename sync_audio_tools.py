"""AudioTools Git sync engine.

Mirrors curated tool *source* from the live working locations into this repo,
runs a safety scan, and commits. Pushing is a separate, explicit step.

The repo is a clean mirror: the live tools keep running in their original
folders; this script copies only source-like files (size/extension/path
filtered) into `tools/` and `sound_finder/` here.

Usage:
    python sync_audio_tools.py sync      # mirror sources -> repo, run safety scan
    python sync_audio_tools.py scan      # safety scan only
    python sync_audio_tools.py status    # git status (short)
    python sync_audio_tools.py commit -m "msg"
    python sync_audio_tools.py push      # push to origin (explicit)
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent

# (live source root, destination subdir inside the repo)
SOURCES = [
    (Path(r"G:\AI\Material\Wwise\Tools"), "tools"),
    (Path(r"C:\Users\user1\Documents\Reaper"), "sound_finder"),
]

# Only these extensions are mirrored (whitelist keeps generated binaries out).
ALLOWED_EXT = {
    ".py", ".pyw", ".cmd", ".bat", ".ps1", ".psm1", ".sh",
    ".md", ".txt", ".json", ".yaml", ".yml", ".lua",
    ".cfg", ".ini", ".toml", ".csv",
}
# Files always allowed regardless of extension.
ALLOWED_NAMES = {".gitignore", "requirements.txt", "README"}

# Directory names excluded anywhere in the path.
EXCLUDE_DIRS = {
    ".git", ".venv", "venv", "__pycache__", "node_modules", ".cache", ".prof",
    "audio_requirement_snapshots", "data", "handoff", "reaper_projects",
    "demo_library", "GeneratedSoundBanks", ".idea", ".vscode", ".claude",
    # Live browser profile used by the Jira tool — holds login cookies/sessions.
    "jira_browser_profile",
}
# Exact filenames excluded (generated indexes / files holding secrets).
EXCLUDE_NAMES = {
    "audio_requirement_jira_index.json",
    "audio_requirement_design_diff_latest.json",
    "audio_requirement_jira_triage_config.json",  # holds jira_cookie -> template instead
}
# Filename glob patterns excluded.
EXCLUDE_GLOBS = [
    "*.sqlite", "*.sqlite-*", "*.png", "*.jpg", "*.jpeg", "*.gif", "*.log",
    "*.tsv", "*.exe", "*.dll", "*.wav", "*.flac", "*.aif", "*.aiff", "*.mp3",
    "*.ogg", "*.zip", "*.7z", "*.bak", "*.rpp-bak",
]
MAX_BYTES = 2_000_000  # hard size cap: nothing bigger than ~2MB is source

# Secret-ish patterns flagged by the safety scan (value present, not just a key name).
SECRET_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}"),       # GitHub tokens
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"),                  # Slack tokens
    re.compile(r"\bsk-[A-Za-z0-9]{20,}"),                           # OpenAI-style keys
    re.compile(r"(?i)(cookie|token|password|secret|api[_-]?key)\s*[:=]\s*['\"][^'\"]{8,}['\"]"),
]


def _excluded(rel: Path, name: str, size: int) -> bool:
    if any(part in EXCLUDE_DIRS for part in rel.parts):
        return True
    # Defensive: never mirror anything under a browser profile (cookies/sessions).
    if any("browser_profile" in part.lower() for part in rel.parts):
        return True
    if name in EXCLUDE_NAMES:
        return True
    if any(Path(name).match(g) for g in EXCLUDE_GLOBS):
        return True
    if size > MAX_BYTES:
        return True
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED_EXT and name not in ALLOWED_NAMES:
        return True
    return False


def iter_source_files(src: Path):
    for path in src.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(src)
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if _excluded(rel, path.name, size):
            continue
        yield path, rel


def sync_source(src: Path, dest_name: str) -> tuple[int, int]:
    dest = REPO_ROOT / dest_name
    if dest.exists():
        shutil.rmtree(dest)  # mirror: rebuild so deletions upstream propagate
    copied = skipped = 0
    if not src.exists():
        print(f"  !! source missing: {src}")
        return 0, 0
    for path, rel in iter_source_files(src):
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        copied += 1
    return copied, skipped


def write_jira_template() -> None:
    """Commit a sanitized template instead of the live jira config (has cookie)."""
    live = SOURCES[0][0] / "audio_requirement_jira_triage_config.json"
    if not live.exists():
        return
    try:
        data = json.loads(live.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    for sensitive in ("jira_cookie", "jira_url", "jql"):
        if sensitive in data:
            data[sensitive] = ""
    out = REPO_ROOT / "tools" / "audio_requirement_jira_triage_config.template.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"  wrote sanitized template: {out.relative_to(REPO_ROOT)}")


def safety_scan() -> list[str]:
    findings: list[str] = []
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file() or ".git" in path.parts:
            continue
        size = path.stat().st_size
        if size > MAX_BYTES:
            findings.append(f"LARGE  {size/1_000_000:.1f}MB  {path.relative_to(REPO_ROOT)}")
        if path.suffix.lower() in {".py", ".json", ".ps1", ".cmd", ".yaml", ".yml", ".md", ".txt", ".ini", ".cfg"}:
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for pat in SECRET_PATTERNS:
                if pat.search(text):
                    findings.append(f"SECRET? {pat.pattern[:40]}  in  {path.relative_to(REPO_ROOT)}")
                    break
    return findings


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(REPO_ROOT), *args], text=True,
                          capture_output=True, check=check)


def cmd_sync(_args) -> int:
    print("Syncing sources -> repo mirror:")
    total = 0
    for src, dest_name in SOURCES:
        copied, _ = sync_source(src, dest_name)
        total += copied
        print(f"  {dest_name:14} <- {src}   ({copied} files)")
    write_jira_template()
    print(f"Total mirrored: {total} files")
    print("\nSafety scan:")
    findings = safety_scan()
    if findings:
        for f in findings:
            print("  " + f)
        print(f"\n!! {len(findings)} item(s) flagged — review before committing.")
        return 1
    print("  clean — no large files or secret-like values found.")
    return 0


def cmd_scan(_args) -> int:
    findings = safety_scan()
    if findings:
        print("\n".join(findings))
        return 1
    print("clean")
    return 0


def cmd_status(_args) -> int:
    print(git("status", "--short", check=False).stdout or "(clean)")
    return 0


def cmd_commit(args) -> int:
    git("add", "-A")
    res = git("commit", "-m", args.m, check=False)
    print(res.stdout + res.stderr)
    return res.returncode


def cmd_push(args) -> int:
    branch = git("rev-parse", "--abbrev-ref", "HEAD", check=False).stdout.strip() or "main"
    res = git("push", "-u", "origin", branch, check=False)
    print(res.stdout + res.stderr)
    return res.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="AudioTools git sync engine")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sync").set_defaults(func=cmd_sync)
    sub.add_parser("scan").set_defaults(func=cmd_scan)
    sub.add_parser("status").set_defaults(func=cmd_status)
    c = sub.add_parser("commit"); c.add_argument("-m", required=True); c.set_defaults(func=cmd_commit)
    sub.add_parser("push").set_defaults(func=cmd_push)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
