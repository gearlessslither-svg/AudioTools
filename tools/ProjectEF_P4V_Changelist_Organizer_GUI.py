#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import csv
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import tkinter as tk
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

import reconstruct_projectef_changelist as recon


APP_DIR = Path(__file__).resolve().parent
ROOT = Path(r"G:\AI\Material\Wwise")
REPORT_DIR = ROOT / "\u62A5\u544A"
RULES_PATH = APP_DIR / "p4_changelist_organizer_rules.json"
LEARNING_PATH = APP_DIR / "p4_changelist_learning.json"
OPERATION_LOG_PATH = APP_DIR / "p4_changelist_organizer_operations.log"
AUDIO_TOOL_REPORT_GLOB = "ProjectEF_AnimationWwiseEvent_AutoConfig_*.json"
AUDIO_FOOTPRINT_JSON = REPORT_DIR / "ProjectEF_Unity_Audio_Footprint.json"

DEFAULT_P4PORT = "ef.p4.blackjack-local.com:1666"
DEFAULT_P4USER = "yupeng"
DEFAULT_P4CLIENT = "yupeng_ADMIN-V9BNJMS5N"
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_LOCAL_MODEL = "qwen2.5:7b-instruct"

BG = "#0f1722"
PANEL = "#151f2d"
PANEL_2 = "#1b2636"
CARD = "#202c3d"
PRIMARY = "#43c6a8"
PRIMARY_ACTIVE = "#5ed8bd"
PRIMARY_INK = "#07161f"
INK = "#edf4ff"
MUTED = "#9fb0c6"
LINE = "#334258"
WARN = "#ffcc66"
AUDIO_HIGHLIGHT_BG = "#6e161b"
AUDIO_HIGHLIGHT_FG = "#fff4f4"
AUDIO_FILTER_BG = "#c24132"
AUDIO_FILTER_ACTIVE = "#ef6a5b"

DECISIONS = ["KEEP", "REVIEW", "EXCLUDE", "GENERATED_REVIEW"]
DECISION_META = {
    "KEEP": {"upload": "Upload", "tag": "keep", "label": "Upload"},
    "REVIEW": {"upload": "Review", "tag": "review", "label": "Review"},
    "EXCLUDE": {"upload": "Do not upload", "tag": "exclude", "label": "Do not upload"},
    "GENERATED_REVIEW": {"upload": "Generated policy", "tag": "generated", "label": "Generated policy"},
}
STOP_TOKENS = {
    "assets",
    "gameproject",
    "runtimeassets",
    "scripts",
    "editor",
    "runtime",
    "client",
    "targetproject",
    "projectef",
    "wwise",
    "scriptableobjects",
    "generatedsoundbanks",
    "audio",
    "sound",
    "event",
    "events",
    "meta",
}


@dataclass(frozen=True)
class RepoProfile:
    key: str
    name: str
    root: str
    depot_marker: str
    kind: str
    marker_candidates: tuple[str, ...]


REPO_PROFILES = {
    "wwise": RepoProfile(
        key="wwise",
        name="Wwise Audio Repo",
        root=r"D:\EF Wwise",
        depot_marker="/ProjectEFAudio_Trunk/",
        kind="wwise",
        marker_candidates=("/ProjectEFAudio_Trunk/",),
    ),
    "unity": RepoProfile(
        key="unity",
        name="Unity Repo",
        root=r"D:\EF New\Client\TargetProject",
        depot_marker="",
        kind="unity",
        marker_candidates=("/TargetProject/", "/Client/TargetProject/"),
    ),
}

DEFAULT_RULES = {
    "include_keywords": ["Wwise", "Ak", "Audio", "Prefab", "Manifest"],
    "include_extensions": [".prefab", ".anim", ".asset", ".unity", ".cs", ".meta", ".json", ".xml", ".bytes", ".bnk", ".wem"],
    "review_keywords": ["ProjectSettings", "Packages", "Addressable", "StreamingAssets", "AssetBundle", "Localization"],
    "exclude_path_tokens": ["Library", "Temp", "Logs", "obj", ".vs", ".cursor", "UserSettings", "DerivedDataCache"],
    "exclude_extensions": [".csproj", ".sln", ".user", ".tmp", ".log", ".cache", ".pidb", ".booproj"],
    "local_since": "2026-06-01",
}


def p4_executable() -> str:
    known = Path(r"C:\Program Files\Perforce\p4.exe")
    if known.exists():
        return str(known)
    found = shutil.which("p4")
    return found or "p4"


def split_csv(text: str) -> list[str]:
    values = []
    for item in re.split(r"[,;\n]", text):
        item = item.strip()
        if item:
            values.append(item)
    return values


def normalize_extension(value: str) -> str:
    value = value.strip().lower()
    if not value:
        return value
    return value if value.startswith(".") else "." + value


def normalize_path_text(path_text: str) -> str:
    return path_text.replace("\\", "/")


def contains_any(text: str, needles: list[str]) -> list[str]:
    lowered = text.lower()
    return [needle for needle in needles if needle and needle.lower() in lowered]


def parse_since(value: str) -> dt.datetime:
    try:
        return dt.datetime.fromisoformat(value.strip())
    except Exception:
        return dt.datetime(2026, 6, 1)


def iso_from_ts(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts).isoformat(timespec="seconds")


def size_mb(size: int) -> float:
    return round(size / 1024 / 1024, 3)


def rel_to_root(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except Exception:
        return str(path)


def safe_stat(path: Path | None) -> dict[str, Any]:
    if path and path.exists():
        stat = path.stat()
        return {
            "size_mb": size_mb(stat.st_size),
            "created": iso_from_ts(stat.st_ctime),
            "modified": iso_from_ts(stat.st_mtime),
        }
    return {"size_mb": "", "created": "", "modified": ""}


def normalized_file_key(value: str | Path | None) -> str:
    if not value:
        return ""
    text = str(value).strip().strip('"')
    if not text:
        return ""
    try:
        path = Path(text)
        if path.is_absolute():
            return normalize_path_text(str(path.resolve())).lower()
    except Exception:
        pass
    return normalize_path_text(text).lower()


def parse_datetime_value(value: Any) -> dt.datetime | None:
    if isinstance(value, dt.datetime):
        return value
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return dt.datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def row_modified_timestamp(row: dict[str, Any]) -> float:
    parsed = parse_datetime_value(row.get("modified"))
    if parsed:
        return parsed.timestamp()
    full_path = row.get("full_path")
    if full_path:
        try:
            return Path(full_path).stat().st_mtime
        except OSError:
            pass
    return 0.0


def load_audio_tool_touch_index(max_reports: int = 160) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    if not REPORT_DIR.exists():
        return index
    reports = sorted(REPORT_DIR.glob(AUDIO_TOOL_REPORT_GLOB), key=lambda item: item.stat().st_mtime, reverse=True)[:max_reports]
    for report_path in reports:
        try:
            data = json.loads(report_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        report_time = parse_datetime_value(data.get("timestamp")) or dt.datetime.fromtimestamp(report_path.stat().st_mtime)
        event_name = str(data.get("wwise_event") or "").strip()
        applied = bool(data.get("applied"))

        candidates: list[tuple[str, str, int]] = []
        for value in data.get("changed_files") or []:
            if value:
                candidates.append((str(value), "changed", 100))
        for key, role in (("animation", "animation target"), ("prefab", "prefab target")):
            value = data.get(key)
            if value and applied:
                candidates.append((str(value), role, 82))

        for file_path, role, score in candidates:
            key = normalized_file_key(file_path)
            if not key:
                continue
            existing = index.get(key)
            if existing and (existing.get("score", 0), existing.get("timestamp", "")) >= (score, report_time.isoformat(timespec="seconds")):
                continue
            index[key] = {
                "score": score,
                "role": role,
                "event": event_name,
                "report": report_path.name,
                "timestamp": report_time.isoformat(timespec="seconds"),
                "path": file_path,
            }
    return index


def load_audio_footprint_index(path: Path = AUDIO_FOOTPRINT_JSON) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    index: dict[str, dict[str, Any]] = {}
    for row in data.get("rows", []):
        if not isinstance(row, dict):
            continue
        keys = [
            normalized_file_key(row.get("full_path")),
            normalized_file_key(row.get("path")),
            normalize_path_text(str(row.get("path") or "")).lower(),
        ]
        for key in keys:
            if key:
                index[key] = row
    return index


def parse_opened_line(line: str) -> dict[str, str] | None:
    match = re.match(r"^(?P<depot>//.+?)#(?P<rev>[^ ]+) - (?P<action>\w+) (?P<change>.+?) \((?P<type>.+)\)$", line.strip())
    if not match:
        return None
    data = match.groupdict()
    data["change"] = normalize_p4_change(data["change"])
    return data


def normalize_p4_change(value: str) -> str:
    value = value.strip()
    if value == "default change":
        return "default"
    if value.startswith("change "):
        return value.split(" ", 1)[1].strip()
    return value.replace(" change", "").strip()


def category_to_decision(category: str) -> str:
    if category in {
        "KEEP_THIS_UI_TASK",
        "UNITY_RULE_KEYWORD_KEEP",
        "UNITY_RULE_EXTENSION_KEEP",
        "UNITY_META_PAIR_KEEP",
        "UNITY_AUDIO_TOOL_CHANGED_KEEP",
        "UNITY_AUDIO_TOOL_TARGET_KEEP",
    }:
        return "KEEP"
    if category in {
        "OLD_PROJECT_EXCLUDE",
        "SOUNDBANK_BACKUP_EXCLUDE",
        "GENERATED_CACHE_EXCLUDE",
        "UNITY_EXCLUDE_GENERATED_OR_LOCAL",
        "UNITY_RULE_EXCLUDE",
    }:
        return "EXCLUDE"
    if category in {"GENERATED_BANK_POLICY_REVIEW", "UNITY_GENERATED_BANK_POLICY_REVIEW"}:
        return "GENERATED_REVIEW"
    return "REVIEW"


def display_upload(decision: str) -> str:
    return DECISION_META.get(decision, DECISION_META["REVIEW"])["label"]


def default_config() -> dict[str, Any]:
    return {
        "profiles": {
            key: {"root": profile.root, "depot_marker": profile.depot_marker}
            for key, profile in REPO_PROFILES.items()
        },
        "rules": dict(DEFAULT_RULES),
    }


def load_config() -> dict[str, Any]:
    config = default_config()
    if not RULES_PATH.exists():
        return config
    try:
        loaded = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    except Exception:
        return config
    for key, value in loaded.get("profiles", {}).items():
        if key in config["profiles"] and isinstance(value, dict):
            config["profiles"][key].update({k: str(v) for k, v in value.items() if k in {"root", "depot_marker"}})
    if isinstance(loaded.get("rules"), dict):
        for key in DEFAULT_RULES:
            if key in loaded["rules"]:
                config["rules"][key] = loaded["rules"][key]
    return config


def save_config(config: dict[str, Any]) -> None:
    RULES_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def load_learning() -> dict[str, Any]:
    data = {"version": 1, "examples": []}
    if not LEARNING_PATH.exists():
        return data
    try:
        loaded = json.loads(LEARNING_PATH.read_text(encoding="utf-8"))
    except Exception:
        return data
    examples = loaded.get("examples", [])
    if isinstance(examples, list):
        data["examples"] = [item for item in examples if isinstance(item, dict)]
    return data


def save_learning(data: dict[str, Any]) -> None:
    examples = [item for item in data.get("examples", []) if isinstance(item, dict)]
    data = {"version": 1, "examples": examples[-2000:]}
    LEARNING_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def text_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    normalized = normalize_path_text(text).lower()
    for raw in re.findall(r"[A-Za-z0-9_]+", normalized):
        for item in raw.split("_"):
            if len(item) >= 2 and item not in STOP_TOKENS:
                tokens.add(item)
    for raw in re.findall(r"[\u4e00-\u9fff]{2,}", normalized):
        tokens.add(raw)
        for index in range(0, max(0, len(raw) - 1)):
            tokens.add(raw[index : index + 2])
    return tokens


def append_rule_tag(existing: str, tag: str) -> str:
    if not existing:
        return tag
    if tag in existing:
        return existing
    return f"{existing}; {tag}"


def bounded_text(value: str, limit: int = 4200) -> str:
    value = value or ""
    if len(value) <= limit:
        return value
    return value[: limit - 80] + "\n...[truncated]...\n" + value[-60:]


def extract_json_object(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else {}
    except Exception:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            value = json.loads(text[start : end + 1])
            return value if isinstance(value, dict) else {}
        except Exception:
            return {}
    return {}


def normalized_decision(value: str) -> str:
    upper = (value or "").strip().upper()
    return upper if upper in DECISIONS else "REVIEW"


def safe_p4_description_lines(lines: list[str]) -> list[str]:
    safe: list[str] = []
    for line in lines:
        text = re.sub(r"[^\x20-\x7E]+", " ", str(line)).strip()
        text = re.sub(r"\s+", " ", text)
        if text:
            safe.append(text[:120])
    return safe or ["ProjectEF audio selected changes"]


def append_operation_log(label: str, text: str) -> None:
    try:
        stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with OPERATION_LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(f"\n[{stamp}] {label}\n{text.strip()}\n")
    except Exception:
        pass


def build_new_change_form(template: str, client: str, user: str, description_lines: list[str]) -> str:
    fields: list[str] = []
    for line in template.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        match = re.match(r"^([A-Za-z][A-Za-z0-9]*):", line)
        if not match:
            continue
        field = match.group(1)
        if field in {"Change", "Client", "User", "Status", "Type", "Description"} and field not in fields:
            fields.append(field)
    for field in ("Change", "Client", "User", "Status", "Type", "Description"):
        if field not in fields:
            fields.append(field)

    values = {
        "Change": "new",
        "Client": client,
        "User": user,
        "Status": "new",
        "Type": "public",
    }
    out: list[str] = []
    for field in fields:
        if field == "Description":
            out.append("Description:")
            out.extend(f"\t{line}" for line in description_lines)
        else:
            out.append(f"{field}:\t{values[field]}")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def learning_similarity(example: dict[str, Any], row: dict[str, Any], task_goal: str) -> float:
    score = 0.0
    if example.get("repo_kind") and example.get("repo_kind") == row.get("repo_kind"):
        score += 0.08
    if example.get("repo") and example.get("repo") == row.get("repo"):
        score += 0.08
    if example.get("extension") and example.get("extension") == row.get("extension"):
        score += 0.12
    if example.get("category") and example.get("category") == row.get("category"):
        score += 0.14
    if example.get("p4_action") and example.get("p4_action") == row.get("p4_action"):
        score += 0.06

    row_tokens = text_tokens(str(row.get("rel_path", "")))
    example_tokens = set(example.get("path_tokens") or text_tokens(str(example.get("rel_path", ""))))
    if row_tokens and example_tokens:
        score += 0.28 * (len(row_tokens & example_tokens) / len(row_tokens | example_tokens))

    current_task_tokens = text_tokens(task_goal)
    example_task_tokens = set(example.get("task_tokens") or text_tokens(str(example.get("task_goal", ""))))
    if current_task_tokens and example_task_tokens:
        score += 0.24 * (len(current_task_tokens & example_task_tokens) / len(current_task_tokens | example_task_tokens))

    if normalize_path_text(str(example.get("rel_path", ""))).lower() == normalize_path_text(str(row.get("rel_path", ""))).lower():
        score += 0.35
    return round(min(score, 1.0), 3)


def marker_list(profile: RepoProfile, ui_marker: str) -> list[str]:
    markers: list[str] = []
    for marker in [ui_marker, profile.depot_marker, *profile.marker_candidates]:
        marker = marker.strip()
        if marker and marker not in markers:
            markers.append(marker)
    return markers


def p4_history_scopes(profile: RepoProfile, root: Path, ui_marker: str) -> list[str | Path]:
    scopes: list[str | Path] = [root]
    for marker in marker_list(profile, ui_marker):
        marker_norm = normalize_path_text(marker).strip("/")
        if marker_norm:
            depot_scope = f"//.../{marker_norm}/..."
            if depot_scope not in scopes:
                scopes.append(depot_scope)
    if "//..." not in scopes:
        scopes.append("//...")
    return scopes


def depot_to_local(depot_path: str, root: Path, profile: RepoProfile, ui_marker: str) -> tuple[Path | None, str]:
    normalized = normalize_path_text(depot_path)
    for marker in marker_list(profile, ui_marker):
        marker_norm = normalize_path_text(marker)
        if marker_norm in normalized:
            rel = normalized.split(marker_norm, 1)[1]
            return root / Path(rel.replace("/", os.sep)), rel.replace("/", os.sep)
    return None, normalized


class P4Client:
    def __init__(self, port: str, user: str, client: str, timeout: int = 4) -> None:
        self.port = port.strip()
        self.user = user.strip()
        self.client = client.strip()
        self.timeout = timeout

    def base_cmd(self) -> list[str]:
        return [p4_executable(), "-p", self.port, "-u", self.user, "-c", self.client]

    def run(self, args: list[str], input_text: str | None = None, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            self.base_cmd() + args,
            input=input_text,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout or self.timeout,
        )

    def test(self) -> tuple[bool, str]:
        try:
            proc = self.run(["info"])
        except subprocess.TimeoutExpired:
            return False, f"p4 info timed out after {self.timeout}s"
        except Exception as exc:
            return False, str(exc)
        text = (proc.stdout or proc.stderr).strip()
        return proc.returncode == 0, text

    def opened_entries(self, root: Path) -> tuple[bool, str, list[dict[str, str]]]:
        path_arg = str(root / "...")
        try:
            proc = self.run(["opened", path_arg])
        except subprocess.TimeoutExpired:
            return False, f"p4 opened timed out after {self.timeout}s for {path_arg}", []
        except Exception as exc:
            return False, str(exc), []

        text = (proc.stdout or proc.stderr).strip()
        if proc.returncode != 0:
            lowered = text.lower()
            if "file(s) not opened" in lowered or "not opened" in lowered:
                return True, f"No opened files reported by P4 for {root}.", []
            return False, text, []

        entries: list[dict[str, str]] = []
        for line in proc.stdout.splitlines():
            parsed = parse_opened_line(line)
            if parsed:
                entries.append(parsed)
        return True, f"Loaded {len(entries)} opened files from P4 for {root}.", entries

    def submitted_changes(self, scope: str | Path, max_count: int = 120) -> list[dict[str, str]]:
        path_arg = str(scope / "...") if isinstance(scope, Path) else scope
        proc = self.run(
            ["changes", "-s", "submitted", "-u", self.user, "-m", str(max_count), path_arg],
            timeout=max(self.timeout, 45),
        )
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout or "p4 changes failed").strip())
        changes: list[dict[str, str]] = []
        for line in proc.stdout.splitlines():
            match = re.match(r"^Change\s+(\d+)\s+on\s+(\S+)\s+by\s+(\S+)\s+'(.*)'$", line.strip())
            if not match:
                continue
            changes.append(
                {
                    "change": match.group(1),
                    "date": match.group(2),
                    "owner": match.group(3),
                    "summary": match.group(4),
                }
            )
        return changes

    def describe_change_files(self, changelist: str) -> list[dict[str, str]]:
        proc = self.run(["describe", "-s", changelist], timeout=max(self.timeout, 30))
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout or f"p4 describe {changelist} failed").strip())
        files: list[dict[str, str]] = []
        for line in proc.stdout.splitlines():
            match = re.match(r"^\.\.\.\s+(//.+?)#\d+\s+(\w+)", line.strip())
            if match:
                files.append({"depot": match.group(1), "action": match.group(2)})
        return files

    def reopen(self, changelist: str, files: list[str]) -> tuple[int, list[str]]:
        errors: list[str] = []
        success = 0
        for index in range(0, len(files), 80):
            batch = files[index : index + 80]
            try:
                proc = self.run(["reopen", "-c", changelist] + batch, timeout=max(self.timeout, 10))
            except subprocess.TimeoutExpired:
                errors.append(f"p4 reopen timed out for batch starting at {index}")
                continue
            except Exception as exc:
                errors.append(str(exc))
                continue
            if proc.returncode == 0:
                success += len(batch)
            else:
                errors.append((proc.stderr or proc.stdout).strip())
        return success, errors

    def reconcile(self, files: list[str], changelist: str = "default") -> tuple[int, list[str], list[str]]:
        errors: list[str] = []
        messages: list[str] = []
        opened = 0
        args = ["reconcile", "-e", "-a"]
        if changelist and changelist.lower() != "default":
            args.extend(["-c", changelist])
        for index in range(0, len(files), 40):
            batch = files[index : index + 40]
            try:
                proc = self.run(args + batch, timeout=max(self.timeout, 30))
            except subprocess.TimeoutExpired:
                errors.append(f"p4 reconcile timed out for batch starting at {index}")
                continue
            except Exception as exc:
                errors.append(str(exc))
                continue
            text = "\n".join(part.strip() for part in [proc.stdout, proc.stderr] if part and part.strip())
            if text:
                messages.append(text)
            if proc.returncode != 0:
                lowered = text.lower()
                benign = "file(s) already opened" in lowered or "no file(s) to reconcile" in lowered
                if not benign:
                    errors.append(text or f"p4 reconcile failed with exit code {proc.returncode}")
            opened += len(re.findall(r" - opened for (?:edit|add)\b", text, flags=re.IGNORECASE))
        return opened, messages, errors

    def reconcile_preview(self, paths: list[str]) -> tuple[list[dict[str, str]], list[str]]:
        """`p4 reconcile -n`: list files changed on disk but NOT yet opened in P4
        (offline work Perforce can't currently see). Opens nothing — preview only."""
        found: list[dict[str, str]] = []
        errors: list[str] = []
        for index in range(0, len(paths), 20):
            batch = paths[index : index + 20]
            try:
                proc = self.run(["reconcile", "-n", "-e", "-a", "-d"] + batch, timeout=max(self.timeout, 60))
            except subprocess.TimeoutExpired:
                errors.append(f"reconcile -n timed out for batch starting at {index}")
                continue
            except Exception as exc:
                errors.append(str(exc))
                continue
            text = "\n".join(p.strip() for p in [proc.stdout, proc.stderr] if p and p.strip())
            for line in text.splitlines():
                low = line.lower()
                if " - " not in line:
                    continue
                if "opened for edit" in low or "reconcile to edit" in low:
                    action = "edit"
                elif "delete" in low:
                    action = "delete"
                elif "add" in low:
                    action = "add"
                else:
                    continue
                found.append({"file": line.split(" - ", 1)[0].strip(), "action": action})
            if proc.returncode != 0:
                low = text.lower()
                if "no file(s) to reconcile" not in low and "no such file" not in low:
                    errors.append(text or f"reconcile -n exit {proc.returncode}")
        return found, errors

    def create_changelist(self, description: str) -> tuple[str, str]:
        clean_lines = safe_p4_description_lines(description.splitlines())[:6]
        attempts = [clean_lines, ["Reconciled offline work"], ["ProjectEF pending work"]]
        errors: list[str] = []
        try:
            template_proc = self.run(["change", "-o"], timeout=max(self.timeout, 10))
            template_text = template_proc.stdout if template_proc.returncode == 0 else ""
        except Exception:
            template_text = ""
        for attempt_lines in attempts:
            if template_text:
                form = build_new_change_form(template_text, self.client, self.user, attempt_lines)
            else:
                form = (
                    "Change:\tnew\n\n"
                    f"Client:\t{self.client}\n\n"
                    f"User:\t{self.user}\n\n"
                    "Status:\tnew\n\n"
                    "Type:\tpublic\n\n"
                    "Description:\n"
                )
                form += "".join(f"\t{line}\n" for line in attempt_lines)
            proc = self.run(["change", "-i"], input_text=form, timeout=max(self.timeout, 10))
            text = (proc.stdout or proc.stderr or "").strip()
            if proc.returncode == 0:
                match = re.search(r"Change\s+(\d+)\s+created", text, re.IGNORECASE)
                if not match:
                    raise RuntimeError(f"Could not parse created changelist number from: {text}")
                return match.group(1), text
            errors.append(text or "p4 change -i failed")
        raise RuntimeError("\n\n".join(errors))


def make_generic_row(
    *,
    profile: RepoProfile,
    rel_path: str,
    full_path: Path | None,
    depot_path: str = "",
    source: str,
    category: str,
    action: str,
    confidence: str,
    reason: str,
    evidence: str = "",
) -> dict[str, Any]:
    stat = safe_stat(full_path)
    suffix = Path(rel_path).suffix.lower() or "[none]"
    reopen_target = str(full_path) if full_path and full_path.exists() else depot_path
    return {
        "repo": profile.name,
        "category": category,
        "recommended_action": action,
        "confidence": confidence,
        "reason": reason,
        "rel_path": rel_path,
        "full_path": str(full_path) if full_path else "",
        "extension": suffix,
        "size_mb": stat["size_mb"],
        "created": stat["created"],
        "modified": stat["modified"],
        "ui_evidence": evidence,
        "p4_action": "-",
        "p4_change": "-",
        "p4_depot": depot_path,
        "reopen_target": reopen_target,
        "source": source,
        "matched_rules": "",
    }


def classify_wwise_path(local_path: Path | None, rel_path: str, depot_path: str, source: str) -> dict[str, Any]:
    profile = REPO_PROFILES["wwise"]
    if local_path and local_path.exists():
        row = recon.classify(local_path)
        if row["category"] != "Ignore":
            row["repo"] = profile.name
            row["source"] = source
            row["p4_depot"] = depot_path
            row["reopen_target"] = str(local_path)
            row["matched_rules"] = "Wwise reconstruction rules"
            return row

    text = normalize_path_text(rel_path or depot_path)
    suffix = Path(text).suffix.lower()
    lowered = text.lower()
    if "projectef_2021/" in lowered:
        category = "OLD_PROJECT_EXCLUDE"
        action = "Do not submit. Old Wwise 2021 project content belongs outside this current changelist."
        confidence = "High"
        reason = "Path is under the old ProjectEF_2021 Wwise project."
    elif "generatedsoundbanks_backup_" in lowered:
        category = "SOUNDBANK_BACKUP_EXCLUDE"
        action = "Do not submit. Keep local backup only if you need it outside the pending changelist."
        confidence = "High"
        reason = "Timestamped generated SoundBank backup, not authored source."
    elif "generatedsoundbanks/" in lowered:
        category = "GENERATED_BANK_POLICY_REVIEW"
        action = "Review project policy before upload. Generated banks may be versioned, but they are not authored source."
        confidence = "Medium"
        reason = "Generated SoundBank runtime output."
    elif ".cache/" in lowered or ".backup/" in lowered or suffix in recon.GENERATED_EXTENSIONS:
        category = "GENERATED_CACHE_EXCLUDE"
        action = "Do not submit. Cache/profiling/temp files should usually stay out of P4."
        confidence = "High"
        reason = "Wwise cache, profiling, user settings, generated media, or temporary file."
    elif suffix in {".wwu", ".wproj", ".wav"}:
        category = "REVIEW_OPENED_AUTHORED_WWISE"
        action = "Inspect diff and decide whether it belongs to the current audio task."
        confidence = "Medium"
        reason = "Opened authored Wwise/source-audio file not matched to the known UI task list."
    else:
        category = "REVIEW_OPENED_WWISE_OTHER"
        action = "Inspect manually. Keep only if this file is intentionally part of the audio change."
        confidence = "Low"
        reason = "Opened Wwise repo file outside the specific reconstruction rules."

    return make_generic_row(
        profile=profile,
        rel_path=rel_path,
        full_path=local_path,
        depot_path=depot_path,
        source=source,
        category=category,
        action=action,
        confidence=confidence,
        reason=reason,
    )


def classify_unity_path(
    local_path: Path | None,
    rel_path: str,
    depot_path: str,
    source: str,
    rules: dict[str, Any],
) -> dict[str, Any]:
    profile = REPO_PROFILES["unity"]
    rel_norm = normalize_path_text(rel_path or depot_path)
    lowered = rel_norm.lower()
    suffix = Path(rel_norm).suffix.lower()
    include_keywords = [str(item) for item in rules["include_keywords"]]
    review_keywords = [str(item) for item in rules["review_keywords"]]
    exclude_tokens = [str(item) for item in rules["exclude_path_tokens"]]
    include_ext = [normalize_extension(str(item)) for item in rules["include_extensions"]]
    exclude_ext = [normalize_extension(str(item)) for item in rules["exclude_extensions"]]

    matched_exclude_tokens = contains_any(rel_norm, exclude_tokens)
    matched_include_keywords = contains_any(rel_norm, include_keywords)
    matched_review_keywords = contains_any(rel_norm, review_keywords)
    matched_rules: list[str] = []
    is_bird_runtime_asset = "assets/gameproject/runtimeassets/bird/" in lowered
    is_bird_art_asset = is_bird_runtime_asset and any(token in lowered for token in ("/mesh/", "/texture/", "/material/"))

    if matched_exclude_tokens or suffix in exclude_ext:
        if matched_exclude_tokens:
            matched_rules.extend(f"exclude path:{token}" for token in matched_exclude_tokens)
        if suffix in exclude_ext:
            matched_rules.append(f"exclude ext:{suffix}")
        category = "UNITY_EXCLUDE_GENERATED_OR_LOCAL"
        action = "Do not upload unless you have a specific project policy exception."
        confidence = "High"
        reason = "Unity generated/local/editor file matched exclude rules."
    elif suffix == ".meta":
        asset_rel = rel_norm[:-5]
        asset_keyword_matches = contains_any(asset_rel, include_keywords)
        asset_suffix = Path(asset_rel).suffix.lower()
        asset_name = Path(asset_rel).name
        if not asset_suffix:
            matched_rules.append("folder meta")
            category = "UNITY_META_PAIR_REVIEW"
            action = "Review only if this folder meta was created or intentionally changed for the current task."
            confidence = "Medium"
            reason = "Unity folder .meta is not automatically part of an audio change."
        elif is_bird_runtime_asset and asset_suffix in {".anim", ".prefab"}:
            matched_rules.append(f"bird audio asset meta:{asset_suffix}")
            category = "UNITY_BIRD_AUDIO_META_REVIEW"
            action = "Keep only when the paired bird animation/prefab is part of this audio task."
            confidence = "Medium"
            reason = "Bird animation/prefab .meta should follow its paired asset, not the bird name alone."
        elif is_bird_art_asset:
            matched_rules.append("bird art meta")
            category = "UNITY_BIRD_ART_REVIEW"
            action = "Review with art ownership. Usually do not submit for a bird audio binding task."
            confidence = "Medium"
            reason = "Bird mesh/texture/material .meta is not audio binding by itself."
        elif asset_keyword_matches or asset_suffix in {".prefab", ".bnk", ".wem"}:
            matched_rules.extend(f"meta pair:{item}" for item in asset_keyword_matches)
            category = "UNITY_META_PAIR_REVIEW"
            action = "Review with its paired Unity asset. Keep only if that asset is intentionally being submitted."
            confidence = "Medium"
            reason = f"Unity .meta appears paired with {asset_name}; it should not be judged alone."
        else:
            category = "UNITY_META_PAIR_REVIEW"
            action = "Review with the paired asset. Do not submit orphaned meta files."
            confidence = "Medium"
            reason = "Unity .meta file must be judged together with its corresponding asset."
    elif "packages/manifest.json" in lowered or lowered.endswith("/manifest.json"):
        matched_rules.append("manifest")
        category = "UNITY_RULE_KEYWORD_KEEP"
        action = "Keep if the dependency/package change belongs to the audio/Wwise work; inspect content before submit."
        confidence = "Medium"
        reason = "Manifest file matched the configured audio upload rules."
    elif "wwisebanks/" in lowered or suffix in {".bnk", ".wem"}:
        matched_rules.append("WwiseBanks")
        category = "UNITY_GENERATED_BANK_POLICY_REVIEW"
        action = "Review project policy before upload. Runtime banks are generated output unless the task explicitly regenerated banks."
        confidence = "Medium"
        reason = "Unity Wwise bank/runtime file matched Wwise-related rules, but should not be kept by name alone."
    elif is_bird_runtime_asset and suffix == ".anim":
        matched_rules.append("bird animation")
        category = "UNITY_BIRD_AUDIO_ANIM_REVIEW"
        action = "Keep when this animation received Wwise AnimationEvent keys for the current bird audio task."
        confidence = "Medium"
        reason = "Bird animation can contain wing-flap Wwise event keys, but tool evidence or diff should confirm it."
    elif is_bird_runtime_asset and suffix == ".prefab":
        matched_rules.append("bird prefab")
        category = "UNITY_BIRD_AUDIO_PREFAB_REVIEW"
        action = "Keep when this prefab stores WwiseAudioHelper or AnimationWwiseEventReceiver setup for this task."
        confidence = "Medium"
        reason = "Bird prefab can contain call-loop AudioHelper setup and animation-event receiver binding."
    elif is_bird_art_asset:
        matched_rules.append("bird art asset")
        category = "UNITY_BIRD_ART_REVIEW"
        action = "Review with art ownership. Usually unrelated to bird call/wing-flap audio binding."
        confidence = "Medium"
        reason = "Bird mesh/texture/material file matched the bird name, but not the audio binding pattern."
    elif matched_include_keywords:
        matched_rules.extend(f"include keyword:{token}" for token in matched_include_keywords)
        category = "UNITY_RULE_KEYWORD_KEEP"
        action = "Move to the audio upload changelist if this belongs to the current task."
        confidence = "Medium"
        reason = "Path matched configured include keywords."
    elif suffix == ".prefab":
        matched_rules.append("prefab extension")
        category = "UNITY_RULE_EXTENSION_KEEP"
        action = "Keep if the prefab stores audio/UI configuration for this task."
        confidence = "Medium"
        reason = "Prefab extension is configured as an audio-relevant asset type."
    elif matched_review_keywords:
        matched_rules.extend(f"review keyword:{token}" for token in matched_review_keywords)
        category = "UNITY_RULE_REVIEW"
        action = "Review manually. These areas often affect project/runtime config."
        confidence = "Medium"
        reason = "Path matched configured review keywords."
    elif suffix in include_ext:
        matched_rules.append(f"review ext:{suffix}")
        category = "UNITY_RULE_EXTENSION_REVIEW"
        action = "Review manually. Extension is allowed, but the path does not prove audio ownership."
        confidence = "Low"
        reason = "File extension is configured as potentially relevant, but no stronger path keyword matched."
    elif lowered.startswith(("assets/", "packages/", "projectsettings/")):
        category = "UNITY_AUTHORED_RECENT_REVIEW"
        action = "Review manually. Keep only if it is part of the current audio task."
        confidence = "Low"
        reason = "Recent/opened authored Unity file outside configured audio rules."
    else:
        category = "UNITY_RULE_EXCLUDE"
        action = "Do not upload to the audio changelist unless you manually mark it."
        confidence = "Low"
        reason = "No configured audio, prefab, manifest, Wwise, or review rule matched."

    row = make_generic_row(
        profile=profile,
        rel_path=rel_path,
        full_path=local_path,
        depot_path=depot_path,
        source=source,
        category=category,
        action=action,
        confidence=confidence,
        reason=reason,
    )
    row["matched_rules"] = ", ".join(matched_rules)
    return row


def collect_wwise_local_candidates(root: Path) -> list[Path]:
    paths = recon.collect_candidates()
    out: list[Path] = []
    for path in paths:
        try:
            path.resolve().relative_to(root.resolve())
        except Exception:
            continue
        out.append(path)
    return out


def unity_local_scan_roots(root: Path) -> list[Path]:
    return [
        item
        for item in [
            root / "WwiseBanks",
            root / "Assets" / "Wwise",
            root / "Assets" / "Audio",
            root / "Assets" / "GameProject" / "RuntimeAssets",
            root / "Assets" / "GameProject" / "Scripts",
            root / "Packages",
            root / "ProjectSettings",
        ]
        if item.exists()
    ]


def collect_unity_local_candidates(root: Path, rules: dict[str, Any]) -> list[Path]:
    if not root.exists():
        return []
    rg_paths = collect_unity_local_candidates_with_rg(root, rules)
    if rg_paths:
        return rg_paths

    since = parse_since(str(rules.get("local_since", DEFAULT_RULES["local_since"])))
    exclude_tokens = [item.lower() for item in rules["exclude_path_tokens"]]
    candidates: list[Path] = []
    targeted_roots = unity_local_scan_roots(root)
    for scan_root in [item for item in targeted_roots if item.exists()]:
        for dirpath, dirnames, filenames in os.walk(scan_root):
            rel_dir = normalize_path_text(rel_to_root(Path(dirpath), root)).lower()
            dirnames[:] = [
                dirname
                for dirname in dirnames
                if not any(token and token in dirname.lower() for token in exclude_tokens)
                and not any(token and token in f"{rel_dir}/{dirname.lower()}" for token in exclude_tokens)
            ]
            include_exts = {normalize_extension(str(item)) for item in rules["include_extensions"]}
            kw_terms = [str(item) for item in rules["include_keywords"] + rules["review_keywords"]]
            for filename in filenames:
                path = Path(dirpath) / filename
                rel = rel_to_root(path, root)
                rel_norm = normalize_path_text(rel)
                suffix = path.suffix.lower()
                path_matches = bool(contains_any(rel_norm, kw_terms))
                ext_matches = suffix in include_exts
                # Cheap name/ext check first; only stat() files that might qualify or
                # whose recency we still need to test. Avoids stat()-ing huge code dirs.
                if path_matches or ext_matches:
                    candidates.append(path)
                    continue
                try:
                    stat = path.stat()
                except OSError:
                    continue
                created = dt.datetime.fromtimestamp(stat.st_ctime)
                modified = dt.datetime.fromtimestamp(stat.st_mtime)
                if created >= since or modified >= since:
                    candidates.append(path)
    return sorted(set(candidates), key=lambda item: rel_to_root(item, root).lower())


def collect_unity_local_candidates_with_rg(root: Path, rules: dict[str, Any]) -> list[Path]:
    rg = shutil.which("rg")
    if not rg:
        return []
    since = parse_since(str(rules.get("local_since", DEFAULT_RULES["local_since"])))
    include_keywords = [str(item) for item in rules["include_keywords"]]
    include_ext = {normalize_extension(str(item)) for item in rules["include_extensions"]}
    strong_ext = {".prefab", ".anim", ".bnk", ".wem", ".wwu", ".wproj", ".wav", ".xml", ".bytes"}

    globs: list[str] = []
    for keyword in include_keywords:
        keyword = keyword.strip()
        if keyword:
            globs.append(f"*{keyword}*")
            globs.append(f"*{keyword}*/**")
    for ext in sorted(include_ext & strong_ext):
        globs.append(f"*{ext}")
        globs.append(f"*{ext}.meta")
    globs.extend(["manifest.json", "packages-lock.json", "*.prefab", "*.prefab.meta"])

    for token in rules["exclude_path_tokens"]:
        token = str(token).strip()
        if token:
            globs.append(f"!{token}/**")
            globs.append(f"!**/{token}/**")
    for ext in rules["exclude_extensions"]:
        ext = normalize_extension(str(ext))
        if ext:
            globs.append(f"!*{ext}")

    scan_roots = unity_local_scan_roots(root)
    if not scan_roots:
        return []
    cmd = [rg, "--files"]
    cmd.extend(str(path) for path in scan_roots)
    for glob in globs:
        cmd.extend(["-g", glob])
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=25)
    except Exception:
        return []
    if proc.returncode not in {0, 1}:
        return []
    candidates: list[Path] = []
    for line in proc.stdout.splitlines():
        path = Path(line.strip())
        if not path.exists() or not path.is_file():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        rel_norm = normalize_path_text(rel_to_root(path, root)).lower()
        created = dt.datetime.fromtimestamp(stat.st_ctime)
        modified = dt.datetime.fromtimestamp(stat.st_mtime)
        is_recent = created >= since or modified >= since
        is_manifest = rel_norm in {"packages/manifest.json", "packages/packages-lock.json"} or rel_norm.endswith("/manifest.json")
        if is_recent or is_manifest:
            candidates.append(path)
    return sorted(set(candidates), key=lambda item: rel_to_root(item, root).lower())


def wwisebank_reconcile_paths(profile: RepoProfile, root: Path) -> list[str]:
    if profile.kind == "unity":
        bank_roots = [root / "WwiseBanks"]
    elif profile.kind == "wwise":
        bank_roots = [root / "GeneratedSoundBanks"]
    else:
        bank_roots = []
    return [str(bank_root / "...") for bank_root in bank_roots if bank_root.exists()]


class OrganizerGui(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("ProjectEF P4V Changelist Organizer")
        self.geometry("1580x920")
        self.minsize(1220, 760)
        self.configure(bg=BG)

        self.config_data = load_config()
        self.rows: list[dict[str, Any]] = []
        self.visible_iids: list[str] = []
        self.p4_ok = False
        self.p4_message = ""
        self._scanning = False
        self._scan_token = 0
        self._p4_operation_running = False
        self._skip_next_auto_bank_reconcile = False

        self.port_var = tk.StringVar(value=DEFAULT_P4PORT)
        self.user_var = tk.StringVar(value=DEFAULT_P4USER)
        self.client_var = tk.StringVar(value=DEFAULT_P4CLIENT)
        self.timeout_var = tk.StringVar(value="4")
        self.repo_var = tk.StringVar(value="wwise")
        self.repo_root_var = tk.StringVar()
        self.depot_marker_var = tk.StringVar()
        self.repo_status_var = tk.StringVar()

        rules = self.config_data["rules"]
        self.include_keywords_var = tk.StringVar(value=", ".join(rules["include_keywords"]))
        self.include_extensions_var = tk.StringVar(value=", ".join(rules["include_extensions"]))
        self.review_keywords_var = tk.StringVar(value=", ".join(rules["review_keywords"]))
        self.exclude_paths_var = tk.StringVar(value=", ".join(rules["exclude_path_tokens"]))
        self.exclude_extensions_var = tk.StringVar(value=", ".join(rules["exclude_extensions"]))
        self.local_since_var = tk.StringVar(value=str(rules["local_since"]))

        self.search_var = tk.StringVar()
        self.decision_filter_var = tk.StringVar(value="All")
        self.audio_only_var = tk.BooleanVar(value=False)
        self.include_local_candidates_var = tk.BooleanVar(value=False)
        self.auto_reconcile_banks_var = tk.BooleanVar(value=True)
        self.task_goal_var = tk.StringVar(value="")
        self.ollama_url_var = tk.StringVar(value=DEFAULT_OLLAMA_URL)
        self.local_model_var = tk.StringVar(value=DEFAULT_LOCAL_MODEL)
        self.local_ai_limit_var = tk.StringVar(value="12")
        self.keep_cl_var = tk.StringVar()
        self.review_cl_var = tk.StringVar()
        self.generated_cl_var = tk.StringVar()
        self.exclude_cl_var = tk.StringVar()
        self.selected_only_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value="Ready. Select a repo and click Scan.")
        self.summary_var = tk.StringVar(value="")

        self.configure_style()
        self.build_ui()
        self.load_profile_into_vars("wwise")
        self.refresh_table()

    def configure_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Treeview", rowheight=25, background="#101720", foreground=INK, fieldbackground="#101720")
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))
        style.map("Treeview", background=[("selected", "#315577")], foreground=[("selected", "#ffffff")])
        style.configure("TCombobox", fieldbackground=PANEL_2, foreground=INK)

    def build_ui(self) -> None:
        header = tk.Frame(self, bg=BG)
        header.pack(fill=tk.X, padx=16, pady=(12, 8))
        tk.Label(header, text="ProjectEF P4V Changelist Organizer", bg=BG, fg=INK, font=("Segoe UI", 20, "bold")).pack(side=tk.LEFT)
        tk.Label(header, textvariable=self.summary_var, bg=BG, fg=MUTED, font=("Segoe UI", 10)).pack(side=tk.RIGHT)

        repo_panel = self.panel(self)
        repo_panel.pack(fill=tk.X, padx=16, pady=(0, 8))
        tk.Label(repo_panel, text="Repo", bg=PANEL, fg=MUTED, font=("Segoe UI", 8, "bold")).pack(side=tk.LEFT, padx=(10, 6), pady=10)
        repo_combo = ttk.Combobox(
            repo_panel,
            textvariable=self.repo_var,
            values=list(REPO_PROFILES.keys()),
            width=12,
            state="readonly",
        )
        repo_combo.pack(side=tk.LEFT, padx=(0, 10))
        repo_combo.bind("<<ComboboxSelected>>", lambda _event: self.on_repo_changed())
        self.entry(repo_panel, "Repo Root", self.repo_root_var, 330).pack(side=tk.LEFT, padx=8, pady=10)
        self.button(repo_panel, "Browse", self.browse_repo_root).pack(side=tk.LEFT, padx=4)
        self.entry(repo_panel, "Depot Marker", self.depot_marker_var, 230).pack(side=tk.LEFT, padx=8, pady=10)
        self.button(repo_panel, "Save Repo/Rules", self.save_rules_from_ui).pack(side=tk.LEFT, padx=8)
        tk.Label(repo_panel, textvariable=self.repo_status_var, bg=PANEL, fg=WARN, font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=12)

        p4_panel = self.panel(self)
        p4_panel.pack(fill=tk.X, padx=16, pady=(0, 8))
        self.entry(p4_panel, "P4PORT", self.port_var, 230).pack(side=tk.LEFT, padx=(10, 8), pady=10)
        self.entry(p4_panel, "P4USER", self.user_var, 120).pack(side=tk.LEFT, padx=8, pady=10)
        self.entry(p4_panel, "P4CLIENT", self.client_var, 360).pack(side=tk.LEFT, padx=8, pady=10)
        self.entry(p4_panel, "Timeout", self.timeout_var, 60).pack(side=tk.LEFT, padx=8, pady=10)
        self.button(p4_panel, "Test P4", self.test_p4).pack(side=tk.LEFT, padx=8)
        self.scan_button = self.button(
            p4_panel,
            "SCAN / Refresh List",
            self.scan,
            bg=PRIMARY,
            fg=PRIMARY_INK,
            active_bg=PRIMARY_ACTIVE,
        )
        self.scan_button.configure(font=("Segoe UI", 10, "bold"), padx=18, pady=8)
        self.scan_button.pack(side=tk.LEFT, padx=8)
        self.scan_progress = ttk.Progressbar(p4_panel, mode="indeterminate", length=150)
        self.scan_progress.pack(side=tk.LEFT, padx=(0, 8))
        self.button(p4_panel, "Export CSV", self.export_csv).pack(side=tk.LEFT, padx=8)
        self.button(p4_panel, "Open Reports", lambda: os.startfile(str(REPORT_DIR))).pack(side=tk.LEFT, padx=8)

        rules_panel = self.panel(self)
        rules_panel.pack(fill=tk.X, padx=16, pady=(0, 8))
        top_rules = tk.Frame(rules_panel, bg=PANEL)
        top_rules.pack(fill=tk.X, padx=10, pady=(8, 4))
        self.entry(top_rules, "Include Keywords", self.include_keywords_var, 350).pack(side=tk.LEFT, padx=(0, 8))
        self.entry(top_rules, "Include Extensions", self.include_extensions_var, 330).pack(side=tk.LEFT, padx=8)
        self.entry(top_rules, "Review Keywords", self.review_keywords_var, 330).pack(side=tk.LEFT, padx=8)
        bottom_rules = tk.Frame(rules_panel, bg=PANEL)
        bottom_rules.pack(fill=tk.X, padx=10, pady=(0, 8))
        self.entry(bottom_rules, "Exclude Paths", self.exclude_paths_var, 430).pack(side=tk.LEFT, padx=(0, 8))
        self.entry(bottom_rules, "Exclude Extensions", self.exclude_extensions_var, 330).pack(side=tk.LEFT, padx=8)
        self.entry(bottom_rules, "Local Fallback Since", self.local_since_var, 130).pack(side=tk.LEFT, padx=8)
        self.button(bottom_rules, "Reset Rules", self.reset_rules).pack(side=tk.LEFT, padx=8)

        learning_panel = self.panel(self)
        learning_panel.pack(fill=tk.X, padx=16, pady=(0, 8))
        learning_top = tk.Frame(learning_panel, bg=PANEL)
        learning_top.pack(fill=tk.X, padx=10, pady=(8, 4))
        tk.Label(learning_top, text="Task Goal", bg=PANEL, fg=MUTED, font=("Segoe UI", 8, "bold")).pack(side=tk.LEFT, padx=(0, 6))
        task_goal = tk.Entry(learning_top, textvariable=self.task_goal_var, bg=PANEL_2, fg=INK, insertbackground=INK, relief=tk.FLAT, width=82)
        task_goal.pack(side=tk.LEFT, padx=(0, 10), ipady=4)
        self.button(learning_top, "Apply Learned", self.apply_learned_marks).pack(side=tk.LEFT, padx=4)
        self.button(learning_top, "Learn From Marks", self.learn_from_selected).pack(side=tk.LEFT, padx=4)
        self.history_learn_button = self.button(learning_top, "Learn History", self.learn_from_p4_history, bg="#344966")
        self.history_learn_button.pack(side=tk.LEFT, padx=4)
        self.button(learning_top, "Open Memory", self.open_learning_memory).pack(side=tk.LEFT, padx=4)
        tk.Label(
            learning_top,
            text="Learning only changes table suggestions.",
            bg=PANEL,
            fg=WARN,
            font=("Segoe UI", 9, "bold"),
        ).pack(side=tk.LEFT, padx=(12, 0))

        learning_bottom = tk.Frame(learning_panel, bg=PANEL)
        learning_bottom.pack(fill=tk.X, padx=10, pady=(0, 8))
        self.entry(learning_bottom, "Ollama URL", self.ollama_url_var, 220).pack(side=tk.LEFT, padx=(0, 8))
        self.entry(learning_bottom, "Local Model", self.local_model_var, 210).pack(side=tk.LEFT, padx=8)
        self.entry(learning_bottom, "Max Rows", self.local_ai_limit_var, 80).pack(side=tk.LEFT, padx=8)
        self.button(learning_bottom, "Test Local AI", self.test_local_ai).pack(side=tk.LEFT, padx=8)
        self.button(learning_bottom, "Local AI Selected", self.local_ai_selected).pack(side=tk.LEFT, padx=4)
        tk.Label(
            learning_bottom,
            text="Local AI reads path/diff snippets and returns KEEP/REVIEW/EXCLUDE/GENERATED_REVIEW. No P4 operation.",
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI", 9),
        ).pack(side=tk.LEFT, padx=(12, 0))

        toolbar = self.panel(self)
        toolbar.pack(fill=tk.X, padx=16, pady=(0, 8))
        tk.Label(toolbar, text="Search", bg=PANEL, fg=MUTED, font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=(10, 6))
        search = tk.Entry(toolbar, textvariable=self.search_var, bg=PANEL_2, fg=INK, insertbackground=INK, relief=tk.FLAT, width=38)
        search.pack(side=tk.LEFT, padx=(0, 12), pady=10, ipady=5)
        search.bind("<KeyRelease>", lambda _event: self.refresh_table())
        tk.Label(toolbar, text="Decision", bg=PANEL, fg=MUTED, font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=(0, 6))
        combo = ttk.Combobox(toolbar, textvariable=self.decision_filter_var, values=["All"] + DECISIONS, width=18, state="readonly")
        combo.pack(side=tk.LEFT, padx=(0, 12))
        combo.bind("<<ComboboxSelected>>", lambda _event: self.refresh_table())
        tk.Checkbutton(
            toolbar,
            text="Audio Only (filter)",
            variable=self.audio_only_var,
            command=self.refresh_table,
            bg=PANEL,
            fg=INK,
            selectcolor=PANEL_2,
            activebackground=PANEL,
            activeforeground=INK,
            font=("Segoe UI", 9, "bold"),
        ).pack(side=tk.LEFT, padx=(0, 10))
        self.button(
            toolbar,
            "Only Audio Changes",
            self.show_audio_only,
            bg=AUDIO_FILTER_BG,
            fg="#ffffff",
            active_bg=AUDIO_FILTER_ACTIVE,
        ).pack(side=tk.LEFT, padx=(0, 6))
        self.button(toolbar, "Show All", self.show_all_rows, bg=CARD).pack(side=tk.LEFT, padx=(0, 10))
        tk.Checkbutton(
            toolbar,
            text="Include Local Scan",
            variable=self.include_local_candidates_var,
            bg=PANEL,
            fg=INK,
            selectcolor=PANEL_2,
            activebackground=PANEL,
            activeforeground=INK,
            font=("Segoe UI", 9, "bold"),
        ).pack(side=tk.LEFT, padx=(0, 10))
        tk.Checkbutton(
            toolbar,
            text="Auto Reconcile WwiseBanks",
            variable=self.auto_reconcile_banks_var,
            bg=PANEL,
            fg=INK,
            selectcolor=PANEL_2,
            activebackground=PANEL,
            activeforeground=INK,
            font=("Segoe UI", 9, "bold"),
        ).pack(side=tk.LEFT, padx=(0, 10))
        for decision, label in [("KEEP", "Mark Keep"), ("REVIEW", "Mark Review"), ("EXCLUDE", "Mark Exclude"), ("GENERATED_REVIEW", "Mark Generated")]:
            self.button(toolbar, label, lambda value=decision: self.mark_selected(value)).pack(side=tk.LEFT, padx=4)

        apply_panel = self.panel(self)
        apply_panel.pack(fill=tk.X, padx=16, pady=(0, 8))
        self.entry(apply_panel, "KEEP CL", self.keep_cl_var, 90).pack(side=tk.LEFT, padx=(10, 8), pady=10)
        self.button(apply_panel, "Copy Keep Desc", lambda: self.copy_cl_description("KEEP")).pack(side=tk.LEFT, padx=4)
        self.entry(apply_panel, "REVIEW CL", self.review_cl_var, 90).pack(side=tk.LEFT, padx=(18, 8), pady=10)
        self.button(apply_panel, "Copy Review Desc", lambda: self.copy_cl_description("REVIEW")).pack(side=tk.LEFT, padx=4)
        self.entry(apply_panel, "BANK CL", self.generated_cl_var, 90).pack(side=tk.LEFT, padx=(18, 8), pady=10)
        self.button(apply_panel, "Copy Bank Desc", lambda: self.copy_cl_description("GENERATED_REVIEW")).pack(side=tk.LEFT, padx=4)
        self.entry(apply_panel, "EXCLUDE CL", self.exclude_cl_var, 90).pack(side=tk.LEFT, padx=(18, 8), pady=10)
        self.button(apply_panel, "Copy Exclude Desc", lambda: self.copy_cl_description("EXCLUDE")).pack(side=tk.LEFT, padx=4)
        tk.Checkbutton(
            apply_panel,
            text="Selected Only",
            variable=self.selected_only_var,
            bg=PANEL,
            fg=INK,
            selectcolor=PANEL_2,
            activebackground=PANEL,
            activeforeground=INK,
            font=("Segoe UI", 9, "bold"),
        ).pack(side=tk.LEFT, padx=(18, 4))
        self.reconcile_button = self.button(apply_panel, "Reconcile Selected Local", self.reconcile_selected_local, bg=PRIMARY, fg=PRIMARY_INK, active_bg=PRIMARY_ACTIVE)
        self.reconcile_button.pack(side=tk.LEFT, padx=4)
        self.bank_reconcile_button = self.button(apply_panel, "Reconcile WwiseBanks", self.reconcile_wwisebanks, bg=PRIMARY, fg=PRIMARY_INK, active_bg=PRIMARY_ACTIVE)
        self.bank_reconcile_button.pack(side=tk.LEFT, padx=4)
        self.detect_offline_button = self.button(apply_panel, "检测离线音频改动", self.detect_offline_audio_changes, bg="#7a5c2e")
        self.detect_offline_button.pack(side=tk.LEFT, padx=4)
        self.selected_new_cl_button = self.button(apply_panel, "Selected -> New CL", self.move_selected_to_new_cl, bg="#2f6f5e")
        self.selected_new_cl_button.pack(side=tk.LEFT, padx=4)
        self.visible_audio_new_cl_button = self.button(apply_panel, "Move Visible Audio -> New CL", self.move_visible_audio_to_new_cl, bg="#2f6f5e")
        self.visible_audio_new_cl_button.pack(side=tk.LEFT, padx=4)
        self.apply_moves_button = self.button(apply_panel, "Apply Move To CLs", self.apply_moves)
        self.apply_moves_button.pack(side=tk.LEFT, padx=(20, 6))
        tk.Label(
            apply_panel,
            text="Selected -> New CL creates one pending CL after confirmation. No revert/add/delete/submit.",
            bg=PANEL,
            fg=WARN,
            font=("Segoe UI", 9, "bold"),
        ).pack(side=tk.LEFT, padx=(12, 8))

        table_frame = tk.Frame(self, bg=BG)
        table_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 8))
        columns = ("decision", "upload", "category", "tool", "audio", "source", "p4", "modified", "created", "mb", "path", "reason")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="extended")
        headings = {
            "decision": "Decision",
            "upload": "Advice",
            "category": "Type",
            "tool": "Tool",
            "audio": "Audio",
            "source": "Source",
            "p4": "P4",
            "modified": "Modified",
            "created": "Created",
            "mb": "MB",
            "path": "Path",
            "reason": "Reason",
        }
        widths = {
            "decision": 110,
            "upload": 110,
            "category": 240,
            "tool": 90,
            "audio": 120,
            "source": 130,
            "p4": 100,
            "modified": 150,
            "created": 150,
            "mb": 65,
            "path": 430,
            "reason": 560,
        }
        for column in columns:
            self.tree.heading(column, text=headings[column])
            self.tree.column(column, width=widths[column], anchor=tk.W)
        self.tree.tag_configure("keep", background="#10251d")
        self.tree.tag_configure("review", background="#24210f")
        self.tree.tag_configure("exclude", background="#2a1518")
        self.tree.tag_configure("generated", background="#1b2035")
        for decision_tag in ("keep", "review", "exclude", "generated"):
            self.tree.tag_configure(f"audio_{decision_tag}", background=AUDIO_HIGHLIGHT_BG, foreground=AUDIO_HIGHLIGHT_FG)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        yscroll = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.tree.yview)
        yscroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.configure(yscrollcommand=yscroll.set)
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self.show_details())
        self.tree.bind("<Double-1>", lambda _event: self.open_selected_path())

        details = self.panel(self)
        details.pack(fill=tk.X, padx=16, pady=(0, 8))
        self.details_text = tk.Text(details, height=6, bg="#101720", fg=INK, insertbackground=INK, relief=tk.FLAT, wrap=tk.WORD)
        self.details_text.pack(fill=tk.X, padx=10, pady=10)
        self.details_text.configure(state=tk.DISABLED)

        status = tk.Label(self, textvariable=self.status_var, bg=BG, fg=MUTED, anchor="w")
        status.pack(fill=tk.X, padx=16, pady=(0, 8))

    def panel(self, parent: tk.Misc) -> tk.Frame:
        return tk.Frame(parent, bg=PANEL, highlightbackground=LINE, highlightthickness=1)

    def button(
        self,
        parent: tk.Misc,
        text: str,
        command,
        bg: str = CARD,
        fg: str = INK,
        active_bg: str = "#2a3c55",
    ) -> tk.Button:
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=bg,
            fg=fg,
            activebackground=active_bg,
            activeforeground=fg,
            relief=tk.FLAT,
            padx=12,
            pady=6,
            font=("Segoe UI", 9, "bold"),
        )

    def set_scan_busy(self, busy: bool) -> None:
        if not hasattr(self, "scan_button") or not hasattr(self, "scan_progress"):
            return
        operation_buttons = [
            getattr(self, "reconcile_button", None),
            getattr(self, "bank_reconcile_button", None),
            getattr(self, "selected_new_cl_button", None),
            getattr(self, "visible_audio_new_cl_button", None),
            getattr(self, "apply_moves_button", None),
            getattr(self, "history_learn_button", None),
        ]
        if busy:
            self.scan_button.configure(text="Scanning...", state=tk.DISABLED)
            self.scan_progress.start(12)
            for button in operation_buttons:
                if button:
                    button.configure(state=tk.DISABLED)
        else:
            self.scan_progress.stop()
            self.scan_progress.configure(value=0)
            self.scan_button.configure(text="SCAN / Refresh List", state=tk.NORMAL)
            if not getattr(self, "_p4_operation_running", False):
                for button in operation_buttons:
                    if button:
                        button.configure(state=tk.NORMAL)

    def set_p4_operation_busy(self, busy: bool, label: str = "P4 operation") -> None:
        if not hasattr(self, "scan_progress"):
            return
        buttons = [
            getattr(self, "reconcile_button", None),
            getattr(self, "bank_reconcile_button", None),
            getattr(self, "selected_new_cl_button", None),
            getattr(self, "visible_audio_new_cl_button", None),
            getattr(self, "apply_moves_button", None),
            getattr(self, "history_learn_button", None),
        ]
        if busy:
            self._p4_operation_running = True
            self.status_var.set(f"{label} is running in background. The window should stay responsive.")
            self.scan_progress.start(12)
            if hasattr(self, "scan_button"):
                self.scan_button.configure(state=tk.DISABLED)
            for button in buttons:
                if button:
                    button.configure(state=tk.DISABLED)
        else:
            self._p4_operation_running = False
            if not getattr(self, "_scanning", False):
                self.scan_progress.stop()
                self.scan_progress.configure(value=0)
                if hasattr(self, "scan_button"):
                    self.scan_button.configure(text="SCAN / Refresh List", state=tk.NORMAL)
            for button in buttons:
                if button:
                    button.configure(state=tk.NORMAL)

    def run_p4_operation_async(self, label: str, worker: Any, done: Any) -> None:
        if self._p4_operation_running:
            messagebox.showinfo(label, "Another P4 operation is already running. Please wait for it to finish.")
            return
        self.set_p4_operation_busy(True, label)

        def background() -> None:
            try:
                result = worker()
                self.after(0, lambda: self._p4_operation_done(label, done, result))
            except Exception as exc:  # noqa: BLE001
                err = exc
                self.after(0, lambda: self._p4_operation_failed(label, err))

        threading.Thread(target=background, daemon=True).start()

    def _p4_operation_done(self, label: str, done: Any, result: Any) -> None:
        self.set_p4_operation_busy(False)
        done(result)

    def _p4_operation_failed(self, label: str, exc: Exception) -> None:
        self.set_p4_operation_busy(False)
        self.status_var.set(f"{label} failed: {exc}")
        append_operation_log(label, f"FAILED\n{exc}")
        messagebox.showerror(f"{label} Failed", str(exc)[:4000])

    def entry(self, parent: tk.Misc, label: str, var: tk.StringVar, width_px: int) -> tk.Frame:
        frame = tk.Frame(parent, bg=PANEL)
        tk.Label(frame, text=label, bg=PANEL, fg=MUTED, font=("Segoe UI", 8, "bold")).pack(anchor="w")
        tk.Entry(frame, textvariable=var, bg=PANEL_2, fg=INK, insertbackground=INK, relief=tk.FLAT, width=max(4, width_px // 8)).pack(anchor="w", ipady=4)
        return frame

    def profile(self) -> RepoProfile:
        return REPO_PROFILES[self.repo_var.get()]

    def profile_root(self) -> Path:
        return Path(self.repo_root_var.get().strip())

    def update_repo_status(self) -> None:
        parts = []
        for key, profile in REPO_PROFILES.items():
            root = Path(self.config_data["profiles"].get(key, {}).get("root", profile.root))
            parts.append(f"{profile.name}:{'found' if root.exists() else 'missing'}")
        self.repo_status_var.set(" | ".join(parts))

    def load_profile_into_vars(self, key: str) -> None:
        profile = REPO_PROFILES[key]
        data = self.config_data["profiles"].get(key, {})
        self.repo_root_var.set(str(data.get("root") or profile.root))
        self.depot_marker_var.set(str(data.get("depot_marker") or profile.depot_marker))
        self.update_repo_status()

    def on_repo_changed(self) -> None:
        self._scan_token += 1
        self._scanning = False
        self.set_scan_busy(False)
        self.load_profile_into_vars(self.repo_var.get())
        self.rows = []
        self.refresh_table()
        self.status_var.set("Repo changed. Click Scan Selected Repo to load that repo's P4/local candidate list.")

    def browse_repo_root(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.repo_root_var.get() or str(Path.home()), parent=self)
        if selected:
            self._scan_token += 1
            self._scanning = False
            self.set_scan_busy(False)
            self.repo_root_var.set(selected)
            self.update_repo_status()

    def rules_from_ui(self) -> dict[str, Any]:
        return {
            "include_keywords": split_csv(self.include_keywords_var.get()),
            "include_extensions": [normalize_extension(item) for item in split_csv(self.include_extensions_var.get())],
            "review_keywords": split_csv(self.review_keywords_var.get()),
            "exclude_path_tokens": split_csv(self.exclude_paths_var.get()),
            "exclude_extensions": [normalize_extension(item) for item in split_csv(self.exclude_extensions_var.get())],
            "local_since": self.local_since_var.get().strip() or DEFAULT_RULES["local_since"],
        }

    def save_rules_from_ui(self) -> None:
        key = self.repo_var.get()
        self.config_data["profiles"][key] = {
            "root": self.repo_root_var.get().strip(),
            "depot_marker": self.depot_marker_var.get().strip(),
        }
        self.config_data["rules"] = self.rules_from_ui()
        save_config(self.config_data)
        self.update_repo_status()
        self.status_var.set(f"Saved repo/rules to {RULES_PATH}")

    def reset_rules(self) -> None:
        self.include_keywords_var.set(", ".join(DEFAULT_RULES["include_keywords"]))
        self.include_extensions_var.set(", ".join(DEFAULT_RULES["include_extensions"]))
        self.review_keywords_var.set(", ".join(DEFAULT_RULES["review_keywords"]))
        self.exclude_paths_var.set(", ".join(DEFAULT_RULES["exclude_path_tokens"]))
        self.exclude_extensions_var.set(", ".join(DEFAULT_RULES["exclude_extensions"]))
        self.local_since_var.set(str(DEFAULT_RULES["local_since"]))
        self.status_var.set("Rules reset in the UI. Click Save Repo/Rules to persist.")

    def open_learning_memory(self) -> None:
        LEARNING_PATH.parent.mkdir(parents=True, exist_ok=True)
        if not LEARNING_PATH.exists():
            save_learning({"version": 1, "examples": []})
        os.startfile(str(LEARNING_PATH))

    def row_to_learning_example(self, row: dict[str, Any]) -> dict[str, Any]:
        task_goal = self.task_goal_var.get().strip()
        return {
            "created_at": dt.datetime.now().isoformat(timespec="seconds"),
            "task_goal": task_goal,
            "task_tokens": sorted(text_tokens(task_goal)),
            "repo_kind": self.repo_var.get(),
            "repo": row.get("repo", ""),
            "rel_path": row.get("rel_path", ""),
            "path_tokens": sorted(text_tokens(str(row.get("rel_path", "")))),
            "extension": row.get("extension", ""),
            "category": row.get("category", ""),
            "decision": normalized_decision(str(row.get("decision", "REVIEW"))),
            "p4_action": row.get("p4_action", ""),
            "p4_change": row.get("p4_change", ""),
            "matched_rules": row.get("matched_rules", ""),
            "reason": row.get("reason", ""),
        }

    def learn_from_selected(self) -> None:
        selected = self.selected_rows()
        if not selected:
            messagebox.showinfo("Learn", "Select rows that you have already marked first.")
            return
        learning = load_learning()
        examples: list[dict[str, Any]] = list(learning.get("examples", []))
        index: dict[tuple[str, str, str], int] = {}
        for pos, item in enumerate(examples):
            key = (
                str(item.get("repo_kind", "")),
                normalize_path_text(str(item.get("rel_path", ""))).lower(),
                str(item.get("task_goal", "")).strip().lower(),
            )
            index[key] = pos
        for row in selected:
            example = self.row_to_learning_example(row)
            key = (
                str(example.get("repo_kind", "")),
                normalize_path_text(str(example.get("rel_path", ""))).lower(),
                str(example.get("task_goal", "")).strip().lower(),
            )
            if key in index:
                examples[index[key]] = example
            else:
                index[key] = len(examples)
                examples.append(example)
        save_learning({"version": 1, "examples": examples})
        self.status_var.set(f"Learned {len(selected)} marked rows into {LEARNING_PATH}.")
        messagebox.showinfo(
            "Learned",
            f"Saved {len(selected)} examples.\n\n"
            "This only updates the local organizer memory. It does not touch P4 or project files.",
        )

    def history_row_to_learning_example(
        self,
        row: dict[str, Any],
        profile: RepoProfile,
        change: dict[str, str],
        sibling: bool = False,
    ) -> dict[str, Any]:
        summary = str(change.get("summary") or "")
        task_goal = f"p4-history {change.get('change', '-')}: {summary}"
        decision = category_to_decision(str(row.get("category", "")))
        if "GENERATED_BANK" in str(row.get("category", "")).upper():
            decision = "GENERATED_REVIEW"
        if sibling:
            decision = "REVIEW"
        return {
            "created_at": dt.datetime.now().isoformat(timespec="seconds"),
            "source": "p4-history-audio-sibling" if sibling else "p4-history",
            "change": change.get("change", ""),
            "change_date": change.get("date", ""),
            "change_owner": change.get("owner", ""),
            "task_goal": task_goal,
            "task_tokens": sorted(text_tokens(task_goal)),
            "repo_kind": profile.key,
            "repo": row.get("repo", profile.name),
            "rel_path": row.get("rel_path", ""),
            "path_tokens": sorted(text_tokens(str(row.get("rel_path", "")))),
            "extension": row.get("extension", ""),
            "category": row.get("category", ""),
            "decision": normalized_decision(decision),
            "p4_action": row.get("p4_action", ""),
            "p4_change": row.get("p4_change", change.get("change", "")),
            "matched_rules": append_rule_tag(str(row.get("matched_rules", "")), f"p4-history:{change.get('change', '')}"),
            "reason": (
                f"Co-submitted with direct audio files in yupeng changelist {change.get('change', '-')}: {summary}"
                if sibling
                else f"Learned from submitted yupeng changelist {change.get('change', '-')}: {summary}"
            ),
        }

    def learn_from_p4_history(self) -> None:
        profile_key = self.repo_var.get()
        profile = REPO_PROFILES[profile_key]
        root = Path(self.repo_root_var.get().strip() or profile.root)
        if not root.exists():
            messagebox.showerror("Learn History", f"Repo root does not exist:\n{root}")
            return
        rules = self.rules_from_ui()
        depot_marker = self.depot_marker_var.get().strip()
        p4_client = self.p4()

        def worker() -> dict[str, Any]:
            changes: list[dict[str, str]] = []
            scope_messages: list[str] = []
            active_scope: str | Path = root
            for scope in p4_history_scopes(profile, root, depot_marker):
                try:
                    changes = p4_client.submitted_changes(scope, max_count=120)
                    scope_messages.append(f"{scope}: {len(changes)} changes")
                    if changes:
                        active_scope = scope
                        break
                except Exception as exc:  # noqa: BLE001
                    scope_messages.append(f"{scope}: {exc}")
            if not changes:
                return {
                    "changes": 0,
                    "files_seen": 0,
                    "audio_files": 0,
                    "sibling_files": 0,
                    "skipped_exclude": 0,
                    "examples": [],
                    "scope_messages": scope_messages,
                    "suspects": [],
                }
            examples: list[dict[str, Any]] = []
            files_seen = 0
            audio_files = 0
            sibling_files = 0
            skipped_exclude = 0
            suspects: list[dict[str, Any]] = []
            fallback_all_scope = str(active_scope) == "//..."
            for change in changes:
                rows: list[dict[str, Any]] = []
                for entry in p4_client.describe_change_files(change["change"]):
                    files_seen += 1
                    depot_path = entry["depot"]
                    lowered_depot = normalize_path_text(depot_path).lower()
                    if fallback_all_scope and profile.kind == "wwise" and "projectefaudio" not in lowered_depot and "/wwise/" not in lowered_depot:
                        continue
                    local_path, rel_path = depot_to_local(depot_path, root, profile, depot_marker)
                    if profile.kind == "wwise":
                        row = classify_wwise_path(local_path, rel_path, depot_path, "P4 history")
                    else:
                        row = classify_unity_path(local_path, rel_path, depot_path, "P4 history", rules)
                    row["repo_kind"] = profile.kind
                    row["p4_action"] = entry.get("action", "-")
                    row["p4_change"] = change["change"]
                    rows.append(row)

                self.apply_audio_footprint(rows, root, profile)
                direct_audio_rows = [row for row in rows if self.is_audio_candidate(row)]
                if not direct_audio_rows:
                    continue
                direct_ids = {id(row) for row in direct_audio_rows}
                change_sibling_files = 0
                change_excluded_files: list[str] = []
                for row in rows:
                    is_direct = id(row) in direct_ids
                    if not is_direct and len(direct_audio_rows) < 2:
                        continue
                    decision = category_to_decision(str(row.get("category", "")))
                    if decision == "EXCLUDE":
                        skipped_exclude += 1
                        change_excluded_files.append(str(row.get("rel_path", "")))
                        continue
                    if is_direct:
                        audio_files += 1
                        examples.append(self.history_row_to_learning_example(row, profile, change))
                    else:
                        sibling_files += 1
                        change_sibling_files += 1
                        examples.append(self.history_row_to_learning_example(row, profile, change, sibling=True))
                if change_sibling_files or change_excluded_files:
                    suspects.append(
                        {
                            "change": change.get("change", ""),
                            "date": change.get("date", ""),
                            "summary": change.get("summary", ""),
                            "direct_audio_files": len(direct_audio_rows),
                            "sibling_files": change_sibling_files,
                            "excluded_files": change_excluded_files[:12],
                        }
                    )

            return {
                "changes": len(changes),
                "files_seen": files_seen,
                "audio_files": audio_files,
                "sibling_files": sibling_files,
                "skipped_exclude": skipped_exclude,
                "examples": examples,
                "scope_messages": scope_messages,
                "suspects": suspects[:80],
            }

        def done(result: dict[str, Any]) -> None:
            learning = load_learning()
            examples: list[dict[str, Any]] = list(learning.get("examples", []))
            index: dict[tuple[str, str, str], int] = {}
            for pos, item in enumerate(examples):
                key = (
                    str(item.get("source", "")),
                    str(item.get("change", "")),
                    normalize_path_text(str(item.get("rel_path", ""))).lower(),
                )
                index[key] = pos
            added = 0
            updated = 0
            for example in result["examples"]:
                key = (
                    str(example.get("source", "")),
                    str(example.get("change", "")),
                    normalize_path_text(str(example.get("rel_path", ""))).lower(),
                )
                if key in index:
                    examples[index[key]] = example
                    updated += 1
                else:
                    index[key] = len(examples)
                    examples.append(example)
                    added += 1
            save_learning({"version": 1, "examples": examples})
            applied = self.apply_learning_to_rows(self.rows) if self.rows else 0
            if self.rows:
                self.refresh_table()
            report_path = ROOT / "Reports" / f"ProjectEF_P4_History_Audio_Learning_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
            report_path.parent.mkdir(parents=True, exist_ok=True)
            lines = [
                "# ProjectEF P4 History Audio Learning\n\n",
                f"- Repo: {profile.name}\n",
                f"- Changes scanned: {result['changes']}\n",
                f"- Files scanned: {result['files_seen']}\n",
                f"- Direct audio candidates: {result['audio_files']}\n",
                f"- Audio-changelist sibling files: {result.get('sibling_files', 0)}\n",
                f"- Skipped excluded/generated/cache candidates: {result['skipped_exclude']}\n",
                f"- Learning examples saved: {len(result['examples'])}\n",
                f"- Applied to current table rows: {applied}\n\n",
                "## Scopes Tried\n\n",
            ]
            for item in result.get("scope_messages", []):
                lines.append(f"- {item}\n")
            lines.append("\n## Suspicious / Review Changelists\n\n")
            suspects = result.get("suspects", [])
            if not suspects:
                lines.append("- No obvious mixed/excluded audio-history candidates found in this scan.\n")
            else:
                for item in suspects:
                    lines.append(
                        f"### Change {item.get('change')} ({item.get('date')})\n"
                        f"- Summary: {item.get('summary')}\n"
                        f"- Direct audio files: {item.get('direct_audio_files')}\n"
                        f"- Audio-changelist sibling files: {item.get('sibling_files')}\n"
                    )
                    excluded_files = item.get("excluded_files") or []
                    if excluded_files:
                        lines.append("- Excluded/generated/cache files seen:\n")
                        for path in excluded_files:
                            lines.append(f"  - `{path}`\n")
                    lines.append("\n")
            report_path.write_text("".join(lines), encoding="utf-8")
            text = (
                f"Learned P4 history: {result['changes']} submitted changelists, "
                f"{result['files_seen']} files, {result['audio_files']} direct audio candidates, "
                f"{result.get('sibling_files', 0)} audio-changelist sibling files. "
                f"Added {added}, updated {updated}, applied {applied}, skipped excluded {result['skipped_exclude']}. "
                f"Report: {report_path}"
            )
            self.status_var.set(text)
            scope_note = "\n".join(str(item) for item in result.get("scope_messages", [])[:5])
            messagebox.showinfo(
                "Learn History",
                text
                + (f"\n\nScopes tried:\n{scope_note}" if scope_note else "")
                + "\n\nThis is read-only P4 history mining. It only updates local learning memory and does not move files.",
            )

        self.run_p4_operation_async("Learn History", worker, done)

    def apply_learned_marks(self) -> None:
        if not self.rows:
            messagebox.showinfo("Apply Learned", "Scan a repo first.")
            return
        count = self.apply_learning_to_rows(self.rows)
        self.refresh_table()
        self.status_var.set(f"Applied learned suggestions to {count} rows.")
        messagebox.showinfo(
            "Apply Learned",
            f"Applied learned suggestions to {count} rows.\n\n"
            "Use this as a highlight pass; ambiguous files should remain REVIEW.",
        )

    def apply_learning_to_rows(self, rows: list[dict[str, Any]]) -> int:
        learning = load_learning()
        examples = [item for item in learning.get("examples", []) if isinstance(item, dict) and item.get("decision") in DECISIONS]
        if not examples:
            return 0
        task_goal = self.task_goal_var.get().strip()
        changed = 0
        for row in rows:
            best: tuple[float, dict[str, Any] | None] = (0.0, None)
            for example in examples:
                score = learning_similarity(example, row, task_goal)
                if score > best[0]:
                    best = (score, example)
            score, example = best
            if not example:
                continue
            old_decision = normalized_decision(str(row.get("decision", "REVIEW")))
            learned_decision = normalized_decision(str(example.get("decision", "REVIEW")))
            threshold = 0.72
            if old_decision == "REVIEW":
                threshold = 0.52
            elif old_decision == "EXCLUDE" and learned_decision != "EXCLUDE":
                threshold = 0.86
            if score < threshold:
                continue
            row["learning_score"] = score
            row["learning_source"] = example.get("rel_path", "")
            if str(example.get("source", "")).startswith("p4-history"):
                row["history_audio_score"] = score
                row["history_audio_label"] = str(example.get("source", "p4-history"))
            row["decision"] = learned_decision
            row["upload_advice"] = display_upload(learned_decision)
            row["matched_rules"] = append_rule_tag(str(row.get("matched_rules", "")), f"learned:{score}")
            row["reason"] = (
                f"Learned from similar marked file ({score}): {example.get('rel_path', '-')}. "
                f"Original rule: {row.get('reason', '')}"
            )
            changed += int(old_decision != learned_decision or score >= threshold)
        return changed

    def p4(self) -> P4Client:
        try:
            timeout = int(self.timeout_var.get().strip() or "4")
        except ValueError:
            timeout = 4
        return P4Client(self.port_var.get(), self.user_var.get(), self.client_var.get(), timeout)

    def test_p4(self) -> None:
        ok, message = self.p4().test()
        self.p4_ok = ok
        self.p4_message = message
        self.status_var.set(("P4 OK: " if ok else "P4 unavailable: ") + message[:500])
        messagebox.showinfo("P4 Test" if ok else "P4 Test Failed", message[:3000])

    def ollama_base_url(self) -> str:
        return self.ollama_url_var.get().strip().rstrip("/") or DEFAULT_OLLAMA_URL

    def test_local_ai(self) -> None:
        url = self.ollama_base_url()
        try:
            with urllib.request.urlopen(f"{url}/api/tags", timeout=5) as response:
                data = json.loads(response.read().decode("utf-8", errors="replace"))
        except Exception as exc:
            self.status_var.set(f"Local AI unavailable: {exc}")
            messagebox.showerror("Local AI", f"Ollama is not reachable at {url}.\n\n{exc}")
            return
        models = [str(item.get("name", "")) for item in data.get("models", []) if item.get("name")]
        current = self.local_model_var.get().strip()
        if not current and models:
            current = models[0]
            self.local_model_var.set(current)
        if current and current not in models:
            message = f"Ollama OK, but model '{current}' was not listed.\n\nInstalled models:\n" + "\n".join(models)
            self.status_var.set("Local AI model not found in Ollama tags.")
            messagebox.showwarning("Local AI", message[:4000])
            return
        message = "Ollama OK.\n\nInstalled models:\n" + ("\n".join(models) if models else "(none)")
        self.status_var.set(f"Local AI OK. Models: {', '.join(models[:4])}")
        messagebox.showinfo("Local AI", message[:4000])

    def local_ai_selected(self) -> None:
        selected = self.selected_rows()
        if not selected:
            messagebox.showinfo("Local AI", "Select rows first. I recommend selecting REVIEW rows or suspicious generated files.")
            return
        try:
            limit = max(1, int(self.local_ai_limit_var.get().strip() or "12"))
        except ValueError:
            limit = 12
        rows = selected[:limit]
        if len(selected) > limit and not messagebox.askyesno(
            "Local AI",
            f"{len(selected)} rows selected, but Max Rows is {limit}.\n\nReview the first {limit} selected rows only?",
        ):
            return
        updated = 0
        errors: list[str] = []
        for index, row in enumerate(rows, 1):
            self.status_var.set(f"Local AI reviewing {index}/{len(rows)}: {row.get('rel_path', '')}")
            self.update_idletasks()
            try:
                diff_excerpt = self.diff_excerpt_for_row(row)
                prompt = self.local_ai_prompt(row, diff_excerpt)
                response_text = self.ollama_generate(prompt)
                result = extract_json_object(response_text)
                if not result:
                    raise ValueError("Ollama did not return a JSON object.")
                self.apply_local_ai_result(row, result)
                updated += 1
            except Exception as exc:
                errors.append(f"{row.get('rel_path', '-')}: {exc}")
        self.refresh_table()
        detail = f"Local AI updated {updated}/{len(rows)} selected rows."
        if errors:
            detail += "\n\nErrors:\n" + "\n".join(errors[:8])
        self.status_var.set(detail[:1000])
        messagebox.showinfo("Local AI Result", detail[:4000])

    def ollama_generate(self, prompt: str) -> str:
        url = self.ollama_base_url()
        model = self.local_model_var.get().strip() or DEFAULT_LOCAL_MODEL
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": 600},
        }
        request = urllib.request.Request(
            f"{url}/api/generate",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                data = json.loads(response.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Ollama HTTP {exc.code}: {body[:800]}") from exc
        return str(data.get("response", ""))

    def diff_excerpt_for_row(self, row: dict[str, Any]) -> str:
        target = row.get("reopen_target") or row.get("p4_depot") or row.get("full_path")
        if row.get("source") == "P4 opened" and target:
            try:
                proc = self.p4().run(["diff", "-du", str(target)], timeout=20)
                text = (proc.stdout or proc.stderr or "").strip()
                if text:
                    return bounded_text(text, 5200)
            except Exception:
                pass

        full_path = row.get("full_path")
        if not full_path:
            return ""
        path = Path(full_path)
        if not path.exists() or not path.is_file():
            return ""
        text_ext = {".anim", ".prefab", ".asset", ".meta", ".cs", ".json", ".xml", ".txt", ".wwu", ".wproj", ".bytes"}
        if path.suffix.lower() not in text_ext:
            return ""
        try:
            if path.stat().st_size > 512 * 1024:
                return f"Local file is text-like but large: {path.stat().st_size} bytes. Diff was unavailable."
            return bounded_text(path.read_text(encoding="utf-8", errors="replace"), 5200)
        except Exception:
            return ""

    def local_ai_prompt(self, row: dict[str, Any], diff_excerpt: str) -> str:
        task_goal = self.task_goal_var.get().strip() or "(not provided)"
        return (
            "You are a conservative Perforce changelist organizer for a Unity + Wwise game audio project.\n"
            "Classify whether this opened file likely belongs to the current audio task.\n"
            "Rules:\n"
            "- If unsure, choose REVIEW.\n"
            "- Unity asset files and their .meta files must be considered as pairs.\n"
            "- Do not recommend submitting cache, user settings, logs, temporary files, or accidental generated files unless project policy requires review.\n"
            "- Generated SoundBanks can be project-policy dependent, so use GENERATED_REVIEW if they need policy review.\n"
            "- For bird audio binding tasks: wing flap one-shots are AnimationEvent keys on the bird .anim that call PlayAnimationWwiseEvent; continuous bird calls are WwiseAudioHelper setup on the bird prefab; AnimationWwiseEventReceiver.cs/.meta is the runtime bridge and should be reviewed by programmers if new or changed.\n"
            "- For bird audio binding tasks, KEEP the specific .anim keys and prefab component data touched by the audio tool or proven by diff. AnimationWwiseEventReceiver.cs/.meta is one-time infrastructure: include it only if the script asset itself is newly added or edited; otherwise the prefab's serialized component reference is enough.\n"
            "- AudioTool evidence is stronger than path keywords. If AudioTool says changed or target, treat it as part of the current task unless the diff contradicts it.\n"
            "- Return strict JSON only, no markdown.\n\n"
            'JSON schema: {"decision":"KEEP|REVIEW|EXCLUDE|GENERATED_REVIEW","confidence":"High|Medium|Low","reason":"brief reason in Chinese","program_checks":["short check 1","short check 2"]}\n\n'
            f"Current task goal: {task_goal}\n"
            f"Repo: {row.get('repo','')}\n"
            f"Path: {row.get('rel_path','')}\n"
            f"Extension: {row.get('extension','')}\n"
            f"P4 action/change: {row.get('p4_action','-')}/{row.get('p4_change','-')}\n"
            f"Rule category: {row.get('category','')}\n"
            f"Rule decision: {row.get('decision','')}\n"
            f"Rule reason: {row.get('reason','')}\n"
            f"Matched rules: {row.get('matched_rules','') or '-'}\n"
            f"AudioTool evidence: {row.get('tool_touch_label') or '-'} / {row.get('tool_touch_role') or '-'} / {row.get('tool_touch_event') or '-'} / {row.get('tool_touch_report') or '-'}\n"
            f"Audio footprint evidence: {row.get('audio_footprint_label') or '-'} / {row.get('audio_footprint_bucket') or '-'} / {row.get('audio_footprint_evidence') or '-'} / {row.get('audio_footprint_events') or '-'}\n"
            f"Diff or file excerpt:\n{diff_excerpt or '(no diff excerpt available)'}\n"
        )

    def apply_local_ai_result(self, row: dict[str, Any], result: dict[str, Any]) -> None:
        decision = normalized_decision(str(result.get("decision", "REVIEW")))
        confidence = str(result.get("confidence", "Low"))[:40]
        reason = str(result.get("reason", "")).strip()[:600] or "Local AI returned no reason."
        checks_value = result.get("program_checks", [])
        if isinstance(checks_value, list):
            checks = "; ".join(str(item) for item in checks_value[:6])
        else:
            checks = str(checks_value)
        original_reason = row.get("original_reason") or row.get("reason", "")
        row["original_reason"] = original_reason
        row["decision"] = decision
        row["upload_advice"] = display_upload(decision)
        row["local_ai_confidence"] = confidence
        row["local_ai_reason"] = reason
        row["program_checks"] = checks
        row["matched_rules"] = append_rule_tag(str(row.get("matched_rules", "")), f"local-ai:{self.local_model_var.get().strip() or DEFAULT_LOCAL_MODEL}:{confidence}")
        row["reason"] = f"Local AI: {reason} Original rule: {original_reason}"

    def scan(self) -> None:
        if getattr(self, "_p4_operation_running", False):
            self.status_var.set("A P4 operation is running. Scan will be available after it finishes.")
            return
        # Re-entrancy guard: ignore extra clicks while a scan is running.
        if getattr(self, "_scanning", False):
            self.status_var.set("Scan is already running in background. Please wait.")
            self.set_scan_busy(True)
            return
        self.save_rules_from_ui()
        profile = self.profile()
        root = self.profile_root()
        rules = self.rules_from_ui()
        p4_client = self.p4()
        depot_marker = self.depot_marker_var.get()
        include_local_candidates = self.include_local_candidates_var.get()
        auto_reconcile_banks = self.auto_reconcile_banks_var.get() and not self._skip_next_auto_bank_reconcile
        self._skip_next_auto_bank_reconcile = False
        self._scan_token += 1
        scan_token = self._scan_token
        self._scanning = True
        self.set_scan_busy(True)
        mode_bits = ["P4 opened"]
        if include_local_candidates:
            mode_bits.append("local candidates")
        if auto_reconcile_banks:
            mode_bits.append("WwiseBank reconcile")
        mode = " + ".join(mode_bits)
        self.status_var.set(f"Scanning {profile.name} ({mode}) in background. The window should stay responsive.")

        def worker() -> None:
            try:
                result = self._scan_compute(
                    scan_token,
                    profile,
                    root,
                    rules,
                    p4_client,
                    depot_marker,
                    include_local_candidates,
                    auto_reconcile_banks,
                )
                self.after(0, lambda: self._scan_done(result))
            except Exception as exc:  # noqa: BLE001
                err = exc
                self.after(0, lambda: self._scan_failed(scan_token, err))

        # Heavy work (p4 + filesystem walk) runs OFF the Tk thread so the GUI
        # stays responsive instead of going "Not Responding".
        threading.Thread(target=worker, daemon=True).start()

    def _scan_compute(
        self,
        scan_token: int,
        profile: "RepoProfile",
        root: Path,
        rules: dict[str, Any],
        p4_client: P4Client,
        depot_marker: str,
        include_local_candidates: bool,
        auto_reconcile_banks: bool,
    ) -> dict[str, Any]:
        """Heavy scan work runs in a worker thread. Do not read Tk variables here."""
        bank_reconcile_message = ""
        if auto_reconcile_banks:
            bank_paths = wwisebank_reconcile_paths(profile, root)
            if bank_paths:
                opened, messages, errors = p4_client.reconcile(bank_paths)
                bank_reconcile_message = f"WwiseBanks reconcile: {opened} opened/add lines"
                if errors:
                    bank_reconcile_message += f", {len(errors)} errors"
                elif messages:
                    bank_reconcile_message += f", {len(messages)} output blocks"
            else:
                bank_reconcile_message = "WwiseBanks reconcile skipped: bank folder not found"
        ok, message, entries = p4_client.opened_entries(root)
        if ok and entries:
            rows = self.rows_from_p4_entries(profile, root, entries, rules, depot_marker)
            appended = 0
            if include_local_candidates:
                local_rows = self.rows_from_local_fallback(profile, root, rules)
                existing_keys = {self.row_identity_key(r) for r in rows if self.row_identity_key(r)}
                for row in local_rows:
                    key = self.row_identity_key(row)
                    if key and key in existing_keys:
                        continue
                    rows.append(row)
                    if key:
                        existing_keys.add(key)
                    appended += 1
                source_message = f"P4 opened + local candidates ({appended} local-only)"
            else:
                source_message = "P4 opened only. Enable Include Local Scan to search unreconciled local files."
        else:
            if include_local_candidates:
                rows = self.rows_from_local_fallback(profile, root, rules)
                source_message = "Local candidates"
            else:
                rows = []
                source_message = "No P4 opened rows loaded. Local scan is disabled."

        audio_tool_count = self.apply_audio_tool_priority(rows, root, profile)
        audio_footprint_count = self.apply_audio_footprint(rows, root, profile)
        rows = self.sort_rows_for_task(rows)
        for index, row in enumerate(rows):
            decision = category_to_decision(row["category"])
            row["id"] = str(index)
            row["repo_kind"] = profile.kind
            row["decision"] = decision
            row["upload_advice"] = display_upload(decision)
        return {
            "token": scan_token,
            "profile_key": profile.key,
            "root": str(root),
            "rows": rows,
            "ok": ok,
            "message": message,
            "source_message": source_message,
            "bank_reconcile_message": bank_reconcile_message,
            "audio_tool_count": audio_tool_count,
            "audio_footprint_count": audio_footprint_count,
        }

    def _scan_done(self, result: dict[str, Any]) -> None:
        """Apply scan results on the Tk main thread."""
        if result.get("token") != self._scan_token:
            return
        if result.get("profile_key") != self.repo_var.get() or result.get("root") != str(self.profile_root()):
            self._scanning = False
            self.set_scan_busy(False)
            self.status_var.set("Discarded scan result because repo/root changed during scan.")
            return
        self._scanning = False
        self.set_scan_busy(False)
        self.p4_ok = result["ok"]
        self.p4_message = result["message"]
        self.rows = result["rows"]
        learned_count = self.apply_learning_to_rows(self.rows)
        self.refresh_table()
        learned_text = f" Learned applied: {learned_count}." if learned_count else ""
        tool_text = f" Audio-tool priority: {result['audio_tool_count']}." if result["audio_tool_count"] else ""
        footprint_text = f" Audio footprint: {result['audio_footprint_count']}." if result["audio_footprint_count"] else ""
        bank_text = f" {result.get('bank_reconcile_message')}." if result.get("bank_reconcile_message") else ""
        self.status_var.set(
            f"{result['source_message']}. {result['message']} Rows: {len(self.rows)}.{bank_text}{tool_text}{footprint_text}{learned_text}")

    def _scan_failed(self, scan_token: int, exc: Exception) -> None:
        if scan_token != self._scan_token:
            return
        self._scanning = False
        self.set_scan_busy(False)
        self.status_var.set(f"Scan failed: {exc}")
        messagebox.showerror("Scan failed", str(exc), parent=self)

    def row_identity_key(self, row: dict[str, Any]) -> str:
        full_path = str(row.get("full_path") or "").strip()
        if full_path:
            return normalize_path_text(full_path).lower()
        rel_path = str(row.get("rel_path") or "").strip()
        return normalize_path_text(rel_path).lower()

    def row_file_keys(self, row: dict[str, Any], root: Path) -> list[str]:
        keys: list[str] = []
        for value in (row.get("full_path"), row.get("reopen_target")):
            key = normalized_file_key(value)
            if key:
                keys.append(key)
        rel_path = str(row.get("rel_path") or "").strip()
        if rel_path:
            keys.append(normalized_file_key(root / rel_path))
            keys.append(normalize_path_text(rel_path).lower())
        return list(dict.fromkeys(keys))

    def apply_audio_tool_priority(self, rows: list[dict[str, Any]], root: Path, profile: RepoProfile) -> int:
        if profile.kind != "unity":
            return 0
        touch_index = load_audio_tool_touch_index()
        touched_count = 0
        for row in rows:
            evidence = None
            for key in self.row_file_keys(row, root):
                evidence = touch_index.get(key)
                if evidence:
                    break
            if not evidence:
                row["tool_touch_score"] = 0
                row["tool_touch_label"] = ""
                continue

            touched_count += 1
            score = int(evidence.get("score") or 0)
            role = str(evidence.get("role") or "target")
            event_name = str(evidence.get("event") or "-")
            report_name = str(evidence.get("report") or "-")
            row["tool_touch_score"] = score
            row["tool_touch_label"] = "AudioTool"
            row["tool_touch_role"] = role
            row["tool_touch_event"] = event_name
            row["tool_touch_report"] = report_name
            row["matched_rules"] = append_rule_tag(str(row.get("matched_rules", "")), f"audio-tool:{role}:{event_name}")

            old_reason = row.get("reason", "")
            if score >= 100:
                row["category"] = "UNITY_AUDIO_TOOL_CHANGED_KEEP"
                row["recommended_action"] = "Keep for this task. This file was recorded as changed by the audio auto-config tool."
                row["confidence"] = "High"
                prefix = f"Audio tool changed this file for {event_name} ({role})."
            else:
                row["category"] = "UNITY_AUDIO_TOOL_TARGET_KEEP"
                row["recommended_action"] = "Keep for this task if the current diff still matches the audio auto-config result."
                row["confidence"] = "Medium"
                prefix = f"Audio tool applied to this target for {event_name} ({role})."
            row["reason"] = f"{prefix} Report: {report_name}. Original rule: {old_reason}"
        return touched_count

    def apply_audio_footprint(self, rows: list[dict[str, Any]], root: Path, profile: RepoProfile) -> int:
        if profile.kind != "unity":
            return 0
        footprint_index = load_audio_footprint_index()
        if not footprint_index:
            return 0

        hit_count = 0
        for row in rows:
            footprint = None
            for key in self.row_file_keys(row, root):
                footprint = footprint_index.get(key)
                if footprint:
                    break
            if not footprint:
                row["audio_footprint_score"] = 0
                row["audio_footprint_label"] = ""
                continue

            hit_count += 1
            score = int(footprint.get("score") or 0)
            confidence = str(footprint.get("confidence") or "Low")
            bucket = str(footprint.get("bucket") or "audio_related")
            events = footprint.get("events") or []
            evidence = footprint.get("evidence") or []
            evidence_kinds = []
            if isinstance(evidence, list):
                evidence_kinds = [str(item.get("kind")) for item in evidence[:4] if isinstance(item, dict) and item.get("kind")]

            row["audio_footprint_score"] = score
            row["audio_footprint_label"] = f"{confidence}:{score}"
            row["audio_footprint_bucket"] = bucket
            row["audio_footprint_events"] = ", ".join(str(item) for item in events[:8])
            row["audio_footprint_evidence"] = ", ".join(evidence_kinds)
            row["matched_rules"] = append_rule_tag(str(row.get("matched_rules", "")), f"audio-footprint:{bucket}:{confidence}:{score}")

            if not row.get("tool_touch_score"):
                original_reason = row.get("reason", "")
                if bucket == "generated_bank_review":
                    row["category"] = "UNITY_GENERATED_BANK_POLICY_REVIEW"
                    row["recommended_action"] = "Review generated-bank policy before moving this file to an upload changelist."
                else:
                    row["category"] = "UNITY_AUDIO_FOOTPRINT_REVIEW"
                    row["recommended_action"] = "Review as an audio candidate. The full-project audio footprint matched this file."
                row["confidence"] = confidence
                row["reason"] = (
                    f"Audio footprint matched {bucket} ({confidence}, score {score}). "
                    f"Evidence: {row['audio_footprint_evidence'] or '-'}. "
                    f"Events: {row['audio_footprint_events'] or '-'}. "
                    f"Original rule: {original_reason}"
                )
        return hit_count

    def sort_rows_for_task(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(
            rows,
            key=lambda row: (
                -int(row.get("tool_touch_score") or 0),
                -int(row.get("audio_footprint_score") or 0),
                -row_modified_timestamp(row),
                0 if row.get("source") == "P4 opened" else 1,
                normalize_path_text(str(row.get("rel_path") or "")).lower(),
            ),
        )

    def rows_from_p4_entries(
        self,
        profile: RepoProfile,
        root: Path,
        entries: list[dict[str, str]],
        rules: dict[str, Any],
        depot_marker: str,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for entry in entries:
            depot_path = entry["depot"]
            local_path, rel_path = depot_to_local(depot_path, root, profile, depot_marker)
            if local_path and local_path.exists():
                rel_path = rel_to_root(local_path, root)
            if profile.kind == "wwise":
                row = classify_wwise_path(local_path, rel_path, depot_path, "P4 opened")
            else:
                row = classify_unity_path(local_path, rel_path, depot_path, "P4 opened", rules)
            row["p4_action"] = entry.get("action", "-")
            row["p4_change"] = entry.get("change", "-")
            row["p4_depot"] = depot_path
            if not row.get("reopen_target"):
                row["reopen_target"] = depot_path
            rows.append(row)
        return sorted(rows, key=lambda item: item["rel_path"].lower())

    def rows_from_local_fallback(self, profile: RepoProfile, root: Path, rules: dict[str, Any]) -> list[dict[str, Any]]:
        if profile.kind == "wwise":
            paths = collect_wwise_local_candidates(root)
            rows = [classify_wwise_path(path, rel_to_root(path, root), "", "Local fallback") for path in paths]
        else:
            paths = collect_unity_local_candidates(root, rules)
            rows = [
                classify_unity_path(path, rel_to_root(path, root), "", "Local fallback", rules)
                for path in paths
            ]
        return [row for row in rows if row["category"] != "Ignore"]

    def is_audio_candidate(self, row: dict[str, Any]) -> bool:
        if int(row.get("tool_touch_score") or 0) > 0:
            return True
        if int(row.get("audio_footprint_score") or 0) > 0:
            return True
        if float(row.get("history_audio_score") or 0) > 0:
            return True

        repo_name = str(row.get("repo") or "")
        if repo_name == REPO_PROFILES["wwise"].name:
            return True

        category = str(row.get("category") or "").upper()
        if any(token in category for token in ("AUDIO", "WWISE", "SOUNDBANK", "BANK")):
            return True

        rel_path = normalize_path_text(str(row.get("rel_path") or row.get("p4_depot") or "")).lower()
        suffix = str(row.get("extension") or Path(rel_path).suffix).lower()
        if suffix in {".bnk", ".wem"}:
            return True
        return any(
            token in rel_path
            for token in (
                "wwisebanks/",
                "generatedsoundbanks/",
                "assets/wwise/",
                "runtimeassets/wwise",
                "wwisescriptableobjects/",
            )
        )

    def show_audio_only(self) -> None:
        self.audio_only_var.set(True)
        self.refresh_table()
        self.status_var.set("Audio Only filter is ON. This only filters/highlights rows; it does not move files or create changelists.")

    def show_all_rows(self) -> None:
        self.audio_only_var.set(False)
        self.refresh_table()
        self.status_var.set("Audio Only filter is OFF. Showing all scanned rows.")

    def refresh_table(self) -> None:
        self.tree.delete(*self.tree.get_children())
        query = self.search_var.get().strip().lower()
        decision_filter = self.decision_filter_var.get()
        audio_only = self.audio_only_var.get()
        counts = Counter(row["decision"] for row in self.rows)
        self.summary_var.set(" | ".join(f"{key}:{counts.get(key, 0)}" for key in DECISIONS) + f" | Total:{len(self.rows)}")
        self.visible_iids.clear()
        for row in self.rows:
            is_audio_candidate = self.is_audio_candidate(row)
            if decision_filter != "All" and row["decision"] != decision_filter:
                continue
            if audio_only and not is_audio_candidate:
                continue
            haystack = " ".join(
                str(row.get(key, ""))
                for key in (
                    "rel_path",
                    "category",
                    "reason",
                    "recommended_action",
                    "p4_action",
                    "matched_rules",
                    "source",
                    "tool_touch_label",
                    "tool_touch_role",
                    "tool_touch_event",
                    "tool_touch_report",
                    "audio_footprint_label",
                    "audio_footprint_bucket",
                    "audio_footprint_events",
                    "audio_footprint_evidence",
                    "learning_source",
                    "local_ai_reason",
                    "program_checks",
                )
            ).lower()
            if query and query not in haystack:
                continue
            tag = DECISION_META[row["decision"]]["tag"]
            row_tags = (f"audio_{tag}",) if is_audio_candidate else (tag,)
            iid = row["id"]
            self.visible_iids.append(iid)
            self.tree.insert(
                "",
                tk.END,
                iid=iid,
                tags=row_tags,
                values=(
                    row["decision"],
                    row["upload_advice"],
                    row["category"],
                    row.get("tool_touch_label", ""),
                    row.get("audio_footprint_label", ""),
                    row.get("source", "-"),
                    f"{row.get('p4_action', '-')}/{row.get('p4_change', '-')}",
                    row["modified"],
                    row["created"],
                    row["size_mb"],
                    row["rel_path"],
                    row["reason"],
                ),
            )

    def selected_rows(self) -> list[dict[str, Any]]:
        selected = set(self.tree.selection())
        return [row for row in self.rows if row["id"] in selected]

    def mark_selected(self, decision: str) -> None:
        selected = self.selected_rows()
        if not selected:
            messagebox.showinfo("Mark", "Select rows first.")
            return
        for row in selected:
            row["decision"] = decision
            row["upload_advice"] = display_upload(decision)
        self.refresh_table()
        self.status_var.set(f"Marked {len(selected)} rows as {decision}.")

    def show_details(self) -> None:
        rows = self.selected_rows()
        if not rows:
            return
        row = rows[0]
        text = (
            f"Repo: {row.get('repo', '-')}\n"
            f"Path: {row['rel_path']}\n"
            f"Full path: {row.get('full_path') or '-'}\n"
            f"Depot path: {row.get('p4_depot') or '-'}\n"
            f"Decision: {row['decision']} / {row['upload_advice']}\n"
            f"Type: {row['category']} | Confidence: {row['confidence']} | Source: {row.get('source','-')} | P4: {row.get('p4_action','-')} {row.get('p4_change','-')}\n"
            f"Audio tool: {row.get('tool_touch_label') or '-'} | {row.get('tool_touch_role') or '-'} | {row.get('tool_touch_event') or '-'} | {row.get('tool_touch_report') or '-'}\n"
            f"Audio footprint: {row.get('audio_footprint_label') or '-'} | {row.get('audio_footprint_bucket') or '-'} | {row.get('audio_footprint_evidence') or '-'} | {row.get('audio_footprint_events') or '-'}\n"
            f"Rules: {row.get('matched_rules') or '-'}\n"
            f"Learned: {row.get('learning_score') or '-'} from {row.get('learning_source') or '-'}\n"
            f"Local AI: {row.get('local_ai_confidence') or '-'} | {row.get('local_ai_reason') or '-'}\n"
            f"Program checks: {row.get('program_checks') or '-'}\n"
            f"Reason: {row['reason']}\n"
            f"Recommended action: {row['recommended_action']}\n"
            f"Evidence: {row.get('ui_evidence') or '-'}"
        )
        self.details_text.configure(state=tk.NORMAL)
        self.details_text.delete("1.0", tk.END)
        self.details_text.insert(tk.END, text)
        self.details_text.configure(state=tk.DISABLED)

    def open_selected_path(self) -> None:
        rows = self.selected_rows()
        if not rows:
            return
        full_path = rows[0].get("full_path")
        if full_path:
            path = Path(full_path)
            if path.exists():
                os.startfile(str(path.parent))

    def export_csv(self) -> None:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
        path = REPORT_DIR / f"ProjectEF_P4V_Changelist_Organizer_Plan_{stamp}.csv"
        if not self.rows:
            messagebox.showinfo("Export", "No rows to export.")
            return
        fields = [
            "task_goal",
            "repo",
            "decision",
            "upload_advice",
            "category",
            "recommended_action",
            "confidence",
            "learning_score",
            "learning_source",
            "local_ai_confidence",
            "local_ai_reason",
            "program_checks",
            "tool_touch_label",
            "tool_touch_role",
            "tool_touch_event",
            "tool_touch_report",
            "audio_footprint_label",
            "audio_footprint_score",
            "audio_footprint_bucket",
            "audio_footprint_evidence",
            "audio_footprint_events",
            "reason",
            "original_reason",
            "matched_rules",
            "rel_path",
            "full_path",
            "p4_depot",
            "reopen_target",
            "extension",
            "size_mb",
            "created",
            "modified",
            "ui_evidence",
            "source",
            "p4_action",
            "p4_change",
        ]
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for row in self.rows:
                record = {key: row.get(key, "") for key in fields}
                record["task_goal"] = self.task_goal_var.get().strip()
                writer.writerow(record)
        self.status_var.set(f"Exported plan: {path}")
        messagebox.showinfo("Exported", str(path))

    def copy_cl_description(self, decision: str) -> None:
        descriptions = {
            "KEEP": "ProjectEF audio changes - verified upload set",
            "REVIEW": "ProjectEF audio changes - needs manual review",
            "GENERATED_REVIEW": "ProjectEF generated Wwise/SoundBank outputs - policy review",
            "EXCLUDE": "ProjectEF local/generated/excluded files - do not submit holding CL",
        }
        desc = descriptions[decision]
        self.clipboard_clear()
        self.clipboard_append(desc)
        self.status_var.set(f"Copied suggested {decision} changelist description. Create the CL in P4V, then paste its number here.")
        messagebox.showinfo(
            "Description Copied",
            "For an existing changelist:\n\n"
            "1. Create or choose the changelist in P4V.\n"
            "2. Paste this copied description if useful.\n"
            "3. Put the CL number into the matching field.\n"
            "4. Keep Selected Only checked if you only want selected rows.\n"
            "5. Click Apply Move To CLs.\n\n"
            "For a fresh changelist without entering a number, select rows and click Selected -> New CL.",
        )

    def rows_for_p4_apply(self) -> list[dict[str, Any]]:
        if self.selected_only_var.get():
            return self.selected_rows()
        return list(self.rows)

    def bank_policy_rows(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for row in rows:
            rel_path = normalize_path_text(str(row.get("rel_path", ""))).lower()
            category = str(row.get("category", ""))
            decision = str(row.get("decision", ""))
            if (
                "wwisebanks/" in rel_path
                or rel_path.endswith((".bnk", ".wem", ".bnk.meta", ".wem.meta"))
                or "BANK_POLICY" in category
                or decision == "GENERATED_REVIEW"
            ):
                out.append(row)
        return out

    def confirm_bank_policy_rows(self, title: str, rows: list[dict[str, Any]]) -> bool:
        bank_rows = self.bank_policy_rows(rows)
        if not bank_rows:
            return True
        preview = "\n".join(str(row.get("rel_path", "")) for row in bank_rows[:10])
        if len(bank_rows) > 10:
            preview += f"\n... {len(bank_rows) - 10} more"
        return messagebox.askyesno(
            title,
            f"The selected scope contains {len(bank_rows)} WwiseBank/generated candidate files.\n\n"
            f"{preview}\n\n"
            "These are policy-review files. Continue with the P4 operation?",
        )

    def selected_changelist_description(self, rows: list[dict[str, Any]]) -> str:
        title = "ProjectEF audio selected changes"
        counts = Counter(str(row.get("decision", "REVIEW")) for row in rows)
        lines = [
            title,
            f"Repo: {self.profile().name}",
            f"Selected files: {len(rows)}",
            "Decisions: " + ", ".join(f"{key}:{counts.get(key, 0)}" for key in DECISIONS if counts.get(key, 0)),
        ]
        lines.append("Created by ProjectEF P4V Changelist Organizer GUI.")
        return "\n".join(lines)

    def reconcile_wwisebanks(self) -> None:
        profile = self.profile()
        root = self.profile_root()
        bank_paths = wwisebank_reconcile_paths(profile, root)
        if not bank_paths:
            messagebox.showinfo(
                "Reconcile WwiseBanks",
                f"No WwiseBank folder found for {profile.name}:\n{root}",
            )
            return
        preview = "\n".join(bank_paths)
        if not messagebox.askyesno(
            "Reconcile WwiseBanks",
            f"Run p4 reconcile -e -a on the WwiseBank scope?\n\n"
            f"{preview}\n\n"
            "This opens changed/new bank files for review. It does not submit, revert, delete, or move files.",
        ):
            return

        p4_client = self.p4()

        def worker() -> tuple[int, list[str], list[str]]:
            return p4_client.reconcile(bank_paths)

        def done(result: tuple[int, list[str], list[str]]) -> None:
            opened, messages, errors = result
            text = f"WwiseBanks reconcile requested. Newly opened/add lines detected: {opened}."
            if messages:
                text += "\n\nOutput:\n" + "\n".join(messages[:8])
            if errors:
                text += "\n\nErrors:\n" + "\n".join(errors[:8])
            self.status_var.set(text[:1000])
            messagebox.showinfo("Reconcile WwiseBanks", text[:4000])
            self._skip_next_auto_bank_reconcile = True
            self.scan()

        self.run_p4_operation_async("Reconcile WwiseBanks", worker, done)

    def detect_offline_audio_changes(self) -> None:
        """Fast, SCOPED reconcile -n: only the known audio paths (AutoConfig targets +
        audio scan roots + WwiseBanks), not the whole project. Lists files changed on
        disk but not yet opened in P4, and offers to reconcile them into a changelist."""
        root = self.profile_root()
        profile = self.profile()
        scope: list[str] = []
        for info in load_audio_tool_touch_index().values():
            p = info.get("path")
            if p and os.path.exists(p):
                scope.append(str(p))
        for d in unity_local_scan_roots(root):
            scope.append(str(d))
        try:
            scope.extend(wwisebank_reconcile_paths(profile, root))
        except Exception:  # noqa: BLE001
            pass
        scope = sorted({s for s in scope if os.path.exists(s)})
        if not scope:
            messagebox.showinfo("检测离线音频改动", "没有可检测的音频范围(先跑 AutoConfig,或确认音频目录存在)。")
            return
        paths = [s + ("/..." if os.path.isdir(s) else "") for s in scope]
        p4_client = self.p4()

        def worker() -> tuple[list[dict[str, str]], list[str]]:
            return p4_client.reconcile_preview(paths)

        def done(result: tuple[list[dict[str, str]], list[str]]) -> None:
            found, errors = result
            if not found:
                msg = "该精准范围内没有 P4 未跟踪的离线改动。"
                if errors:
                    msg += "\n\n注意:\n" + "\n".join(errors[:4])
                self.status_var.set(msg[:300])
                messagebox.showinfo("检测离线音频改动", msg[:2000])
                return
            lines = [f"[{f['action']}] {f['file']}" for f in found]
            preview = "\n".join(lines[:40]) + (f"\n... 还有 {len(lines) - 40} 个" if len(lines) > 40 else "")
            self.status_var.set(f"离线音频改动: {len(found)} 个(精准范围)")
            edit_files = [f["file"] for f in found if f["action"] == "edit"]
            text = f"发现 {len(found)} 个需要进 CL 的离线改动:\n\n{preview}"
            if edit_files and messagebox.askyesno("检测离线音频改动", text + f"\n\n是否把其中 {len(edit_files)} 个已改文件 reconcile 进 changelist?"):
                opened, messages, errs = p4_client.reconcile(edit_files)
                out = f"已 reconcile,opened/add: {opened}\n" + "\n".join((messages or errs)[:5])
                messagebox.showinfo("Reconcile", out[:3000])
                self.scan()
            else:
                messagebox.showinfo("检测离线音频改动", text[:3000])

        self.run_p4_operation_async("检测离线音频改动", worker, done)

    def reconcile_selected_local(self) -> None:
        selected = self.selected_rows()
        if not selected:
            messagebox.showinfo("Reconcile Selected Local", "Select one or more local candidate rows first.")
            return

        files: list[str] = []
        skipped_opened = 0
        skipped_missing = 0
        for row in selected:
            if row.get("source") == "P4 opened":
                skipped_opened += 1
                continue
            full_path = row.get("full_path")
            if full_path and Path(str(full_path)).exists():
                files.append(str(full_path))
            else:
                skipped_missing += 1

        if not files:
            messagebox.showinfo(
                "Reconcile Selected Local",
                "No selected local files can be reconciled. P4-opened rows are already in a changelist.",
            )
            return
        if not self.confirm_bank_policy_rows("Reconcile Selected Local", selected):
            return

        preview = "\n".join(str(Path(path).name) for path in files[:10])
        if len(files) > 10:
            preview += f"\n... {len(files) - 10} more"
        if not messagebox.askyesno(
            "Reconcile Selected Local",
            f"Run p4 reconcile -e -a on {len(files)} selected local files?\n\n"
            f"Skipped P4-opened rows: {skipped_opened}\n"
            f"Skipped missing paths: {skipped_missing}\n\n"
            f"{preview}\n\n"
            "This opens changed/new files in the default pending changelist. It does not submit, revert, delete, or move files.",
        ):
            return

        p4_client = self.p4()

        def worker() -> tuple[int, list[str], list[str]]:
            return p4_client.reconcile(files)

        def done(result: tuple[int, list[str], list[str]]) -> None:
            opened, messages, errors = result
            text = f"Reconcile requested for {len(files)} files. Newly opened/add lines detected: {opened}."
            if messages:
                text += "\n\nOutput:\n" + "\n".join(messages[:6])
            if errors:
                text += "\n\nErrors:\n" + "\n".join(errors[:6])
            self.status_var.set(text[:1000])
            messagebox.showinfo("Reconcile Selected Local", text[:4000])
            self.scan()

        self.run_p4_operation_async("Reconcile Selected Local", worker, done)

    def collect_new_cl_targets(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        p4_files: list[str] = []
        local_files: list[str] = []
        touch_rows: list[dict[str, Any]] = []
        skipped_missing = 0
        skipped_empty = 0
        for row in rows:
            if row.get("source") == "P4 opened":
                target = row.get("reopen_target") or row.get("p4_depot") or row.get("full_path")
                if target:
                    p4_files.append(str(target))
                    touch_rows.append(row)
                else:
                    skipped_empty += 1
                continue
            full_path = row.get("full_path")
            if full_path and Path(str(full_path)).exists():
                local_files.append(str(full_path))
                touch_rows.append(row)
            else:
                skipped_missing += 1
        return {
            "p4_files": list(dict.fromkeys(p4_files)),
            "local_files": list(dict.fromkeys(local_files)),
            "touch_rows": touch_rows,
            "skipped_missing": skipped_missing,
            "skipped_empty": skipped_empty,
        }

    def create_new_cl_for_rows(self, label: str, rows: list[dict[str, Any]], preview_limit: int = 10) -> None:
        targets = self.collect_new_cl_targets(rows)
        p4_files: list[str] = targets["p4_files"]
        local_files: list[str] = targets["local_files"]
        if not p4_files and not local_files:
            messagebox.showinfo(
                label,
                "No selected files can be moved or reconciled. P4-opened rows need a depot path, and local fallback rows need an existing local path.",
            )
            return
        if not self.confirm_bank_policy_rows(label, targets["touch_rows"]):
            return

        description = self.selected_changelist_description(rows)
        preview = "\n".join(str(row.get("rel_path", "")) for row in rows[:preview_limit])
        if len(rows) > preview_limit:
            preview += f"\n... {len(rows) - preview_limit} more"
        if not messagebox.askyesno(
            label,
            f"Create one new pending changelist for this selection?\n\n"
            f"P4-opened files to move: {len(p4_files)}\n"
            f"Local fallback files to reconcile into the new CL: {len(local_files)}\n"
            f"Skipped missing local paths: {targets['skipped_missing']}\n"
            f"Skipped rows without a P4/local target: {targets['skipped_empty']}\n\n"
            f"{preview}\n\n"
            "Operations: p4 change -i, p4 reopen -c, and p4 reconcile -e -a -c. No submit/revert/delete/file-content changes.",
        ):
            return

        p4_client = self.p4()

        def worker() -> dict[str, Any]:
            changelist, create_message = p4_client.create_changelist(description)
            reopen_success = 0
            reopen_errors: list[str] = []
            reconcile_opened = 0
            reconcile_messages: list[str] = []
            reconcile_errors: list[str] = []
            if p4_files:
                reopen_success, reopen_errors = p4_client.reopen(changelist, p4_files)
            if local_files:
                reconcile_opened, reconcile_messages, reconcile_errors = p4_client.reconcile(local_files, changelist)
            return {
                "changelist": changelist,
                "create_message": create_message,
                "reopen_success": reopen_success,
                "reopen_errors": reopen_errors,
                "reconcile_opened": reconcile_opened,
                "reconcile_messages": reconcile_messages,
                "reconcile_errors": reconcile_errors,
            }

        def done(result: dict[str, Any]) -> None:
            text = (
                f"Created CL {result['changelist']}.\n"
                f"{result['create_message']}\n"
                f"Moved P4-opened files: {result['reopen_success']}/{len(p4_files)}\n"
                f"Reconciled local fallback files into CL {result['changelist']}: "
                f"{result['reconcile_opened']} opened/add lines from {len(local_files)} files."
            )
            messages = result["reconcile_messages"]
            errors = result["reopen_errors"] + result["reconcile_errors"]
            if messages:
                text += "\n\nReconcile output:\n" + "\n".join(messages[:6])
            if errors:
                text += "\n\nErrors:\n" + "\n".join(errors[:8])
            append_operation_log(label, text)
            self.status_var.set(text[:1000])
            messagebox.showinfo(label, text[:4000])
            self.scan()

        self.run_p4_operation_async(label, worker, done)

    def move_selected_to_new_cl(self) -> None:
        selected = self.selected_rows()
        if not selected:
            messagebox.showinfo("Selected -> New CL", "Select one or more rows first.")
            return
        self.create_new_cl_for_rows("Selected -> New CL", selected, preview_limit=8)

    def move_visible_audio_to_new_cl(self) -> None:
        if not self.visible_iids:
            messagebox.showinfo("Visible Audio -> New CL", "No visible rows. Scan or adjust filters first.")
            return
        visible = [row for row in self.rows if row.get("id") in set(self.visible_iids)]
        audio_rows = [
            row for row in visible
            if int(row.get("tool_touch_score") or 0) > 0 or int(row.get("audio_footprint_score") or 0) > 0
        ]
        if not audio_rows:
            messagebox.showinfo("Visible Audio -> New CL", "No visible audio candidates. Try checking Audio Only or refreshing the Unity repo scan.")
            return
        self.create_new_cl_for_rows("Visible Audio -> New CL", audio_rows, preview_limit=10)

    def apply_moves(self) -> None:
        groups: dict[str, tuple[str, list[str]]] = {
            "KEEP": (self.keep_cl_var.get().strip(), []),
            "REVIEW": (self.review_cl_var.get().strip(), []),
            "GENERATED_REVIEW": (self.generated_cl_var.get().strip() or self.review_cl_var.get().strip(), []),
            "EXCLUDE": (self.exclude_cl_var.get().strip(), []),
        }
        skipped_local = 0
        rows_to_apply = self.rows_for_p4_apply()
        if self.selected_only_var.get() and not rows_to_apply:
            messagebox.showinfo("Apply", "Selected Only is checked. Select rows first, or uncheck Selected Only for full-table apply.")
            return
        for row in rows_to_apply:
            if row.get("source") != "P4 opened":
                skipped_local += 1
                continue
            decision = row["decision"]
            target = row.get("reopen_target") or row.get("p4_depot") or row.get("full_path")
            if decision in groups and target:
                groups[decision][1].append(str(target))
        missing = [decision for decision, (cl, files) in groups.items() if files and not cl]
        if missing:
            messagebox.showerror("Missing Changelist", "Fill changelist number for: " + ", ".join(missing))
            return
        total = sum(len(files) for cl, files in groups.values() if cl)
        if total == 0:
            messagebox.showinfo(
                "Apply",
                "No P4-opened rows to move. If the table says Local fallback, P4 CLI did not return a pending list for this repo.",
            )
            return
        opened_rows = [row for row in rows_to_apply if row.get("source") == "P4 opened"]
        if not self.confirm_bank_policy_rows("Apply Move To CLs", opened_rows):
            return
        if not messagebox.askyesno(
            "Apply P4 Reopen",
            f"Move {total} P4-opened files to the specified changelists using `p4 reopen -c`?\n\n"
            f"Scope: {'selected rows only' if self.selected_only_var.get() else 'all table rows'}\n"
            f"Local fallback rows skipped: {skipped_local}\n\n"
            "This does not create changelists, revert, add, delete, submit, or modify file contents.",
        ):
            return
        p4_client = self.p4()

        def worker() -> list[str]:
            messages: list[str] = []
            for decision, (cl, files) in groups.items():
                if not cl or not files:
                    continue
                success, errors = p4_client.reopen(cl, files)
                messages.append(f"{decision}: moved {success}/{len(files)} to CL {cl}")
                messages.extend(errors[:5])
            return messages

        def done(messages: list[str]) -> None:
            text = "\n".join(messages)
            self.status_var.set(text[:1000])
            messagebox.showinfo("Apply Result", text[:4000])
            self.scan()

        self.run_p4_operation_async("Apply Move To CLs", worker, done)


def self_test() -> int:
    config = load_config()
    results: dict[str, Any] = {}
    for key, profile in REPO_PROFILES.items():
        root = Path(config["profiles"].get(key, {}).get("root", profile.root))
        if profile.kind == "wwise":
            paths = collect_wwise_local_candidates(root)
            rows = [classify_wwise_path(path, rel_to_root(path, root), "", "Local fallback") for path in paths]
        else:
            rows = [
                classify_unity_path(path, rel_to_root(path, root), "", "Local fallback", config["rules"])
                for path in collect_unity_local_candidates(root, config["rules"])
            ]
        rows = [row for row in rows if row["category"] != "Ignore"]
        results[key] = {
            "root": str(root),
            "exists": root.exists(),
            "rows": len(rows),
            "decisions": dict(Counter(category_to_decision(row["category"]) for row in rows)),
        }
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()
    app = OrganizerGui()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
