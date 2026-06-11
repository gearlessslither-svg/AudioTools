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

DEFAULT_P4PORT = "ef.p4.blackjack-local.com:1666"
DEFAULT_P4USER = "yupeng"
DEFAULT_P4CLIENT = "yupeng_ADMIN-V9BNJMS5N"
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_LOCAL_MODEL = "qwen2.5:7b-instruct"

BG = "#0f1722"
PANEL = "#151f2d"
PANEL_2 = "#1b2636"
CARD = "#202c3d"
INK = "#edf4ff"
MUTED = "#9fb0c6"
LINE = "#334258"
WARN = "#ffcc66"

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
    "include_extensions": [".prefab", ".asset", ".unity", ".cs", ".meta", ".json", ".xml", ".bytes", ".bnk", ".wem"],
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
    if category in {"KEEP_THIS_UI_TASK", "UNITY_RULE_KEYWORD_KEEP", "UNITY_RULE_EXTENSION_KEEP", "UNITY_META_PAIR_KEEP"}:
        return "KEEP"
    if category in {
        "OLD_PROJECT_EXCLUDE",
        "SOUNDBANK_BACKUP_EXCLUDE",
        "GENERATED_CACHE_EXCLUDE",
        "UNITY_EXCLUDE_GENERATED_OR_LOCAL",
        "UNITY_RULE_EXCLUDE",
    }:
        return "EXCLUDE"
    if category == "GENERATED_BANK_POLICY_REVIEW":
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

    def create_changelist(self, description: str) -> tuple[str, str]:
        clean_lines = safe_p4_description_lines(description.splitlines())[:6]
        attempts = [clean_lines, ["Reconciled offline work"], ["<saved by Perforce>"]]
        errors: list[str] = []
        for attempt_lines in attempts:
            form = (
                "Change:\tnew\n\n"
                f"Client:\t{self.client}\n\n"
                f"User:\t{self.user}\n\n"
                "Status:\tnew\n\n"
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
        if asset_keyword_matches or asset_suffix in {".prefab", ".bnk", ".wem"}:
            matched_rules.extend(f"meta pair:{item}" for item in asset_keyword_matches)
            category = "UNITY_META_PAIR_KEEP"
            action = "Keep with its paired Unity asset if that asset is being submitted."
            confidence = "Medium"
            reason = "Unity .meta appears paired with an audio/Wwise/prefab/manifest related asset."
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
        category = "UNITY_RULE_KEYWORD_KEEP"
        action = "Keep if Unity repo policy versions Wwise runtime banks for this change."
        confidence = "Medium"
        reason = "Unity Wwise bank/runtime file matched Wwise-related rules."
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


def collect_unity_local_candidates(root: Path, rules: dict[str, Any]) -> list[Path]:
    if not root.exists():
        return []
    rg_paths = collect_unity_local_candidates_with_rg(root, rules)
    if rg_paths:
        return rg_paths

    since = parse_since(str(rules.get("local_since", DEFAULT_RULES["local_since"])))
    exclude_tokens = [item.lower() for item in rules["exclude_path_tokens"]]
    candidates: list[Path] = []
    targeted_roots = [
        root / "WwiseBanks",
        root / "Assets" / "Wwise",
        root / "Assets" / "Audio",
        root / "Packages",
        root / "ProjectSettings",
    ]
    for scan_root in [item for item in targeted_roots if item.exists()]:
        for dirpath, dirnames, filenames in os.walk(scan_root):
            rel_dir = normalize_path_text(rel_to_root(Path(dirpath), root)).lower()
            dirnames[:] = [
                dirname
                for dirname in dirnames
                if not any(token and token in dirname.lower() for token in exclude_tokens)
                and not any(token and token in f"{rel_dir}/{dirname.lower()}" for token in exclude_tokens)
            ]
            for filename in filenames:
                path = Path(dirpath) / filename
                try:
                    stat = path.stat()
                except OSError:
                    continue
                created = dt.datetime.fromtimestamp(stat.st_ctime)
                modified = dt.datetime.fromtimestamp(stat.st_mtime)
                rel = rel_to_root(path, root)
                rel_norm = normalize_path_text(rel)
                suffix = path.suffix.lower()
                path_matches = bool(contains_any(rel_norm, [str(item) for item in rules["include_keywords"] + rules["review_keywords"]]))
                ext_matches = suffix in {normalize_extension(str(item)) for item in rules["include_extensions"]}
                if created >= since or modified >= since or path_matches or ext_matches:
                    candidates.append(path)
    return sorted(set(candidates), key=lambda item: rel_to_root(item, root).lower())


def collect_unity_local_candidates_with_rg(root: Path, rules: dict[str, Any]) -> list[Path]:
    rg = shutil.which("rg")
    if not rg:
        return []
    since = parse_since(str(rules.get("local_since", DEFAULT_RULES["local_since"])))
    include_keywords = [str(item) for item in rules["include_keywords"]]
    include_ext = {normalize_extension(str(item)) for item in rules["include_extensions"]}
    strong_ext = {".prefab", ".bnk", ".wem", ".wwu", ".wproj", ".wav", ".xml", ".bytes"}

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

    cmd = [rg, "--files", str(root)]
    for glob in globs:
        cmd.extend(["-g", glob])
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=12)
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
        self.button(p4_panel, "Scan Selected Repo", self.scan).pack(side=tk.LEFT, padx=8)
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
        self.button(apply_panel, "Selected -> New CL", self.move_selected_to_new_cl, bg="#2f6f5e").pack(side=tk.LEFT, padx=4)
        self.button(apply_panel, "Apply Move To CLs", self.apply_moves).pack(side=tk.LEFT, padx=(20, 6))
        tk.Label(
            apply_panel,
            text="Selected -> New CL creates one pending CL after confirmation. No revert/add/delete/submit.",
            bg=PANEL,
            fg=WARN,
            font=("Segoe UI", 9, "bold"),
        ).pack(side=tk.LEFT, padx=(12, 8))

        table_frame = tk.Frame(self, bg=BG)
        table_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 8))
        columns = ("decision", "upload", "category", "source", "p4", "modified", "created", "mb", "path", "reason")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="extended")
        headings = {
            "decision": "Decision",
            "upload": "Advice",
            "category": "Type",
            "source": "Source",
            "p4": "P4",
            "modified": "Modified",
            "created": "Created",
            "mb": "MB",
            "path": "Path",
            "reason": "Reason",
        }
        widths = {"decision": 120, "upload": 120, "category": 250, "source": 135, "p4": 100, "modified": 150, "created": 150, "mb": 70, "path": 430, "reason": 560}
        for column in columns:
            self.tree.heading(column, text=headings[column])
            self.tree.column(column, width=widths[column], anchor=tk.W)
        self.tree.tag_configure("keep", background="#10251d")
        self.tree.tag_configure("review", background="#24210f")
        self.tree.tag_configure("exclude", background="#2a1518")
        self.tree.tag_configure("generated", background="#1b2035")
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

    def button(self, parent: tk.Misc, text: str, command, bg: str = CARD) -> tk.Button:
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=bg,
            fg=INK,
            activebackground="#2a3c55",
            activeforeground=INK,
            relief=tk.FLAT,
            padx=12,
            pady=6,
            font=("Segoe UI", 9, "bold"),
        )

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
        self.load_profile_into_vars(self.repo_var.get())
        self.rows = []
        self.refresh_table()
        self.status_var.set("Repo changed. Click Scan Selected Repo to load that repo's P4/local candidate list.")

    def browse_repo_root(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.repo_root_var.get() or str(Path.home()), parent=self)
        if selected:
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
        self.save_rules_from_ui()
        profile = self.profile()
        root = self.profile_root()
        rules = self.rules_from_ui()
        self.status_var.set(f"Scanning {profile.name}: P4 opened list first, local fallback if unavailable...")
        self.update_idletasks()

        rows: list[dict[str, Any]] = []
        ok, message, entries = self.p4().opened_entries(root)
        self.p4_ok = ok
        self.p4_message = message

        if ok and entries:
            rows = self.rows_from_p4_entries(profile, root, entries, rules)
            source_message = "P4 opened"
        else:
            rows = self.rows_from_local_fallback(profile, root, rules)
            source_message = "Local fallback"

        for index, row in enumerate(rows):
            decision = category_to_decision(row["category"])
            row["id"] = str(index)
            row["repo_kind"] = profile.kind
            row["decision"] = decision
            row["upload_advice"] = display_upload(decision)
        self.rows = rows
        learned_count = self.apply_learning_to_rows(self.rows)
        self.refresh_table()
        learned_text = f" Learned applied: {learned_count}." if learned_count else ""
        self.status_var.set(f"{source_message}. {message} Rows: {len(rows)}.{learned_text}")

    def rows_from_p4_entries(
        self,
        profile: RepoProfile,
        root: Path,
        entries: list[dict[str, str]],
        rules: dict[str, Any],
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for entry in entries:
            depot_path = entry["depot"]
            local_path, rel_path = depot_to_local(depot_path, root, profile, self.depot_marker_var.get())
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

    def refresh_table(self) -> None:
        self.tree.delete(*self.tree.get_children())
        query = self.search_var.get().strip().lower()
        decision_filter = self.decision_filter_var.get()
        counts = Counter(row["decision"] for row in self.rows)
        self.summary_var.set(" | ".join(f"{key}:{counts.get(key, 0)}" for key in DECISIONS) + f" | Total:{len(self.rows)}")
        self.visible_iids.clear()
        for row in self.rows:
            if decision_filter != "All" and row["decision"] != decision_filter:
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
                    "learning_source",
                    "local_ai_reason",
                    "program_checks",
                )
            ).lower()
            if query and query not in haystack:
                continue
            tag = DECISION_META[row["decision"]]["tag"]
            iid = row["id"]
            self.visible_iids.append(iid)
            self.tree.insert(
                "",
                tk.END,
                iid=iid,
                tags=(tag,),
                values=(
                    row["decision"],
                    row["upload_advice"],
                    row["category"],
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

    def move_selected_to_new_cl(self) -> None:
        selected = self.selected_rows()
        if not selected:
            messagebox.showinfo("Selected -> New CL", "Select one or more P4-opened rows first.")
            return
        files: list[str] = []
        skipped_local = 0
        for row in selected:
            if row.get("source") != "P4 opened":
                skipped_local += 1
                continue
            target = row.get("reopen_target") or row.get("p4_depot") or row.get("full_path")
            if target:
                files.append(str(target))
        if not files:
            messagebox.showinfo(
                "Selected -> New CL",
                "No selected P4-opened files to move. If the row source says Local fallback, scan with a matching P4 client first.",
            )
            return
        description = self.selected_changelist_description(selected)
        preview = "\n".join(str(row.get("rel_path", "")) for row in selected[:8])
        if len(selected) > 8:
            preview += f"\n... {len(selected) - 8} more"
        if not messagebox.askyesno(
            "Create New Changelist",
            f"Create one new pending changelist and move {len(files)} selected P4-opened files into it?\n\n"
            f"Skipped local fallback rows: {skipped_local}\n\n"
            f"{preview}\n\n"
            "Operations: p4 change -i, then p4 reopen -c. No submit/revert/add/delete/file-content changes.",
        ):
            return
        try:
            p4 = self.p4()
            changelist, create_message = p4.create_changelist(description)
            success, errors = p4.reopen(changelist, files)
        except Exception as exc:
            self.status_var.set(f"Selected -> New CL failed: {exc}")
            messagebox.showerror("Selected -> New CL Failed", str(exc)[:4000])
            return
        text = f"Created CL {changelist}.\n{create_message}\nMoved {success}/{len(files)} selected files."
        if skipped_local:
            text += f"\nSkipped local fallback rows: {skipped_local}"
        if errors:
            text += "\n\nErrors:\n" + "\n".join(errors[:8])
        self.status_var.set(text[:1000])
        messagebox.showinfo("Selected -> New CL", text[:4000])
        self.scan()

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
        if not messagebox.askyesno(
            "Apply P4 Reopen",
            f"Move {total} P4-opened files to the specified changelists using `p4 reopen -c`?\n\n"
            f"Scope: {'selected rows only' if self.selected_only_var.get() else 'all table rows'}\n"
            f"Local fallback rows skipped: {skipped_local}\n\n"
            "This does not create changelists, revert, add, delete, submit, or modify file contents.",
        ):
            return
        p4 = self.p4()
        messages = []
        for decision, (cl, files) in groups.items():
            if not cl or not files:
                continue
            success, errors = p4.reopen(cl, files)
            messages.append(f"{decision}: moved {success}/{len(files)} to CL {cl}")
            messages.extend(errors[:5])
        text = "\n".join(messages)
        self.status_var.set(text[:1000])
        messagebox.showinfo("Apply Result", text[:4000])
        self.scan()


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
