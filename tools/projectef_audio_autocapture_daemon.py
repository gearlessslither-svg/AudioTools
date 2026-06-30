#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ProjectEF Audio Auto-Capture Daemon.

Always-on lightweight watcher. When the game/Unity becomes active (its log starts
growing), it auto-starts a capture SESSION: it tails the Unity Editor.log / game
Player.log, keeps only audio-relevant lines, classifies each (severity / category /
reason / suggested fix) by REUSING the Log Monitor's rules, and on session end writes
a per-session capture (.jsonl raw + .json summary) into the captures folder.

The daily/weekly briefing (projectef_audio_briefing.py) then rolls these session
captures into a "problems + solutions" report. Register it to auto-start at logon via
Register_ProjectEF_AudioAutoCapture_Tasks.ps1.

Usage:
    python projectef_audio_autocapture_daemon.py            # run forever (daemon)
    python projectef_audio_autocapture_daemon.py --once     # single poll (for testing)
    python projectef_audio_autocapture_daemon.py --interval 15 --unity-root "D:\\EF New\\Client\\TargetProject"
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
OUT_DIR = Path(r"G:\AI\Material\Wwise")
CAPTURE_DIR = OUT_DIR / "audio_debug_captures"
DEFAULT_UNITY_ROOT = Path(r"D:\EF New\Client\TargetProject")
DEFAULT_WWISE_ROOT = Path(r"D:\EF Wwise\ProjectEF")

ACTIVE_SEC = 60        # newest log written within this window => game/Unity active
IDLE_TIMEOUT_SEC = 150  # no audio activity + log stale this long => end session
MAX_SESSION_LINES = 20000  # safety cap per session

# --- Reuse the Log Monitor's discovery + classification when available -----------
sys.path.insert(0, str(TOOLS_DIR))
try:
    import ProjectEF_UnityWwise_AudioLogMonitor_GUI as mon  # type: ignore
    _HAVE_MON = True
except Exception:  # noqa: BLE001
    mon = None  # type: ignore
    _HAVE_MON = False
    import re
    _AUDIO_RE = re.compile(r"(wwise|\bak\b|aksoundengine|soundbank|\.bnk\b|\.wem\b|postevent|loadbank|rtpc|setswitch|setstate|audio|声音|音效)", re.IGNORECASE)
    _ERR_RE = re.compile(r"(error|exception|fail|not found|missing|null)", re.IGNORECASE)
    _WARN_RE = re.compile(r"(warn|warning)", re.IGNORECASE)
    _EVENT_RE = re.compile(r"\b(?:Play|Stop|Set|Music|VO|UI|SFX|Amb|Loop)_[A-Za-z0-9_]+\b")


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def discover_logs(unity_root: Path) -> list[Path]:
    if _HAVE_MON:
        try:
            return mon.discover_logs(unity_root)
        except Exception:  # noqa: BLE001
            pass
    cands: list[Path] = []
    import os
    la = os.environ.get("LOCALAPPDATA")
    if la:
        cands.append(Path(la) / "Unity" / "Editor" / "Editor.log")
    up = os.environ.get("USERPROFILE")
    if up:
        low = Path(up) / "AppData" / "LocalLow"
        if low.exists():
            cands.extend(low.rglob("Player.log"))
    return [p for p in cands if p.exists() and p.is_file()]


def is_audio_line(line: str) -> bool:
    return bool((mon.AUDIO_RE if _HAVE_MON else _AUDIO_RE).search(line))


def classify_line(line: str, known_events: set[str]) -> dict:
    if _HAVE_MON:
        sev = mon.severity(line)
        cat = mon.category(line)
        events = mon.EVENT_RE.findall(line)
        try:
            level, desc, suggestion = mon.infer_reason(cat, line, events, known_events)
        except Exception:  # noqa: BLE001
            level, desc, suggestion = sev, "", ""
        return {"severity": sev, "category": cat, "level": level,
                "reason": desc, "suggestion": suggestion, "events": events[:5]}
    sev = "Error" if _ERR_RE.search(line) else ("Warn" if _WARN_RE.search(line) else "Info")
    return {"severity": sev, "category": "Audio", "level": sev,
            "reason": "", "suggestion": "", "events": _EVENT_RE.findall(line)[:5]}


def load_known_events(wwise_root: Path) -> set[str]:
    if _HAVE_MON:
        try:
            return mon.parse_wwise_events(wwise_root)
        except Exception:  # noqa: BLE001
            return set()
    return set()


class Session:
    def __init__(self, unity_root: Path) -> None:
        self.start = datetime.now()
        self.start_iso = now_iso()
        self.unity_root = str(unity_root)
        self.last_activity = time.time()
        self.lines: list[dict] = []
        self.counts: dict[str, int] = {}

    def add(self, entry: dict) -> None:
        if len(self.lines) >= MAX_SESSION_LINES:
            return
        self.lines.append(entry)
        sev = entry.get("severity", "Info")
        self.counts[sev] = self.counts.get(sev, 0) + 1
        self.last_activity = time.time()

    def finalize(self) -> Path | None:
        if not self.lines:
            return None
        CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
        stamp = self.start.strftime("%Y-%m-%d_%H%M%S")
        # raw jsonl
        raw = CAPTURE_DIR / f"session_{stamp}.jsonl"
        with raw.open("w", encoding="utf-8") as f:
            for e in self.lines:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        # grouped problems with suggestions
        groups: dict[tuple, dict] = {}
        for e in self.lines:
            if e.get("severity") == "Info":
                continue
            key = (e.get("category", "?"), (e.get("events") or ["?"])[0] if e.get("events") else e.get("reason", "")[:40])
            g = groups.setdefault(key, {"category": key[0], "subject": key[1], "count": 0,
                                        "severity": e.get("severity"), "suggestion": e.get("suggestion", ""),
                                        "example": e.get("line", "")[:200] if e.get("line") else ""})
            g["count"] += 1
        problems = sorted(groups.values(), key=lambda g: g["count"], reverse=True)[:30]
        summary = {
            "start": self.start_iso, "end": now_iso(),
            "duration_sec": int(time.time() - self.start.timestamp()),
            "unity_root": self.unity_root,
            "total_audio_lines": len(self.lines),
            "counts_by_severity": self.counts,
            "problems": problems,
        }
        out = CAPTURE_DIR / f"session_{stamp}.json"
        out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        return out


def read_new_audio_lines(logs: list[Path], offsets: dict[str, int], known_events: set[str]) -> list[dict]:
    out: list[dict] = []
    for path in logs:
        key = str(path)
        try:
            size = path.stat().st_size
        except OSError:
            continue
        off = offsets.get(key, size)  # first sight: start at end (don't replay history)
        if off > size:  # log rotated/truncated
            off = 0
        if off == size:
            offsets[key] = size
            continue
        try:
            with path.open("r", encoding="utf-8", errors="replace") as f:
                f.seek(off)
                chunk = f.read()
                offsets[key] = f.tell()
        except OSError:
            continue
        for line in chunk.splitlines():
            if not line.strip() or not is_audio_line(line):
                continue
            entry = classify_line(line, known_events)
            entry["line"] = line.strip()[:500]
            entry["t"] = now_iso()
            entry["log"] = path.name
            out.append(entry)
    return out


HEARTBEAT_SEC = 20


def run(unity_root: Path, wwise_root: Path, interval: int, once: bool) -> int:
    known_events = load_known_events(wwise_root)
    offsets: dict[str, int] = {}
    session: Session | None = None
    last_hb = 0.0
    print(f"[autocapture] start; reuse_monitor={_HAVE_MON}; captures -> {CAPTURE_DIR}", flush=True)
    while True:
        # Only the two real RUNTIME logs: Editor.log (editor Play mode) and Player.log
        # (standalone Windows build). Excludes editor housekeeping logs (AssetImport/
        # shadercompiler) so "active" detection means the game is actually running.
        logs = [p for p in discover_logs(unity_root) if p.name in ("Editor.log", "Player.log")]
        newest = max((p.stat().st_mtime for p in logs if p.exists()), default=0.0)
        active_now = bool(newest) and (time.time() - newest) < ACTIVE_SEC
        new_lines = read_new_audio_lines(logs, offsets, known_events)

        if session is None and (active_now or new_lines):
            session = Session(unity_root)
            print(f"[autocapture] session START @ {session.start_iso} (logs={len(logs)})", flush=True)
        if session is not None:
            for e in new_lines:
                session.add(e)
                # live scroll: show each captured audio line so the window isn't dead
                print(f"  [{e.get('severity','?')}/{e.get('category','?')}] {e.get('log','')}: {e.get('line','')[:120]}", flush=True)
            idle = time.time() - session.last_activity
            if not active_now and idle > IDLE_TIMEOUT_SEC:
                out = session.finalize()
                print(f"[autocapture] session END; lines={len(session.lines)} -> {out}", flush=True)
                session = None

        # heartbeat so you can SEE it's alive even when no audio is happening
        if not once and (time.time() - last_hb) >= HEARTBEAT_SEC:
            last_hb = time.time()
            ages = ", ".join(f"{p.name} {int(time.time() - p.stat().st_mtime)}s" for p in logs if p.exists())
            sess = f"on/{len(session.lines)}行" if session else "off"
            print(f"[心跳] 监听中 active={active_now} 会话={sess} | {ages or '无日志'}", flush=True)

        if once:
            if session is not None:
                out = session.finalize()
                print(f"[autocapture] (--once) wrote {out}")
            print(f"[autocapture] once: logs={len(logs)} active={active_now} new_audio_lines={len(new_lines)}")
            return 0
        time.sleep(max(3, interval))


def main() -> int:
    ap = argparse.ArgumentParser(description="ProjectEF audio auto-capture daemon")
    ap.add_argument("--unity-root", default=str(DEFAULT_UNITY_ROOT))
    ap.add_argument("--wwise-root", default=str(DEFAULT_WWISE_ROOT))
    ap.add_argument("--interval", type=int, default=15)
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()
    try:
        return run(Path(a.unity_root), Path(a.wwise_root), a.interval, a.once)
    except KeyboardInterrupt:
        print("[autocapture] stopped")
        return 0


if __name__ == "__main__":
    sys.exit(main())
