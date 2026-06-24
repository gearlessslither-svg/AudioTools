#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(r"G:\AI\Material\Wwise")
APP_DIR = ROOT / "Tools"
REPORT_DIR = ROOT / "\u62A5\u544A"
UNITY_PROJECT = Path(r"D:\EF New\Client\TargetProject")
LEARNING_PATH = APP_DIR / "p4_changelist_learning.json"
AUDIO_FOOTPRINT_PATH = REPORT_DIR / "ProjectEF_Unity_Audio_Footprint.json"
AUDIO_TOOL_REPORT_GLOB = "ProjectEF_AnimationWwiseEvent_AutoConfig_*.json"
OUTPUT_RELATIVE = Path("Assets/GameProject/Scripts/Editor/AudioIdentityOverlay/ProjectEFAudioIdentityMap.json")

AUDIO_HINT_WORDS = (
    "audio",
    "wwise",
    "ak",
    "sound",
    "sfx",
    "music",
    "bgm",
    "voice",
    "event",
    "amb",
    "bird",
    "fish",
    "water",
    "ui",
)

SKIP_EXTENSIONS = {".cs", ".dll", ".pdb", ".meta", ".tmp", ".log", ".cache"}
RESOURCE_EXTENSIONS = {
    ".prefab",
    ".anim",
    ".controller",
    ".overridecontroller",
    ".playable",
    ".timeline",
    ".asset",
    ".bnk",
    ".wem",
    ".wwu",
    ".wav",
    ".mp3",
}


def normalize_path(value: str | None) -> str:
    if not value:
        return ""
    return str(value).replace("\\", "/").strip()


def normalize_key(value: str | None) -> str:
    return normalize_path(value).lower()


def load_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def name_from_path(path: str) -> str:
    if not path:
        return ""
    return Path(path.replace("\\", "/")).stem


def classify_type(path: str, fallback: str = "") -> str:
    lower = normalize_key(path)
    ext = Path(lower).suffix
    if "wwisebanks/" in lower or ext in {".bnk", ".wem"}:
        return "WwiseBank"
    if "wwisescriptableobjects/" in lower or "wwise" in lower or ext == ".wwu":
        return "Wwise"
    if ext == ".anim":
        return "Animation"
    if ext in {".playable", ".timeline"} or "timeline" in lower:
        return "Timeline"
    if ext == ".prefab":
        if "/ui/" in lower or "ui" in lower:
            return "UI Prefab"
        return "Prefab"
    if ext == ".asset":
        return fallback or "Asset"
    if ext in {".wav", ".mp3"}:
        return "SourceAudio"
    return fallback or "Resource"


def is_audio_like(path: str, text: str = "", category: str = "") -> bool:
    lower = (normalize_key(path) + " " + str(text).lower() + " " + str(category).lower()).strip()
    if not lower:
        return False
    ext = Path(normalize_path(path)).suffix.lower()
    if ext in SKIP_EXTENSIONS:
        return False
    if ext and ext not in RESOURCE_EXTENSIONS:
        return False
    if any(word in lower for word in AUDIO_HINT_WORDS):
        return True
    return ext in {".bnk", ".wem", ".wwu", ".wav", ".mp3"}


class EntryBuilder:
    def __init__(self) -> None:
        self.entries: dict[str, dict[str, Any]] = {}
        self.name_counts: Counter[str] = Counter()

    def add(
        self,
        path: str,
        *,
        name: str | None = None,
        item_type: str | None = None,
        source: str,
        confidence: str,
        evidence: str,
        weight: int = 1,
    ) -> None:
        path = normalize_path(path)
        name = name or name_from_path(path)
        if not path and not name:
            return
        key = normalize_key(path) if path else f"name:{name.lower()}"
        existing = self.entries.get(key)
        if existing is None:
            existing = {
                "path": path,
                "name": name,
                "type": item_type or classify_type(path),
                "source": source,
                "confidence": confidence,
                "evidence": evidence,
                "frequency": 0,
            }
            self.entries[key] = existing
        else:
            if confidence_rank(confidence) > confidence_rank(str(existing.get("confidence", ""))):
                existing["confidence"] = confidence
            if source not in str(existing.get("source", "")):
                existing["source"] = str(existing.get("source", "")) + "; " + source
            if evidence and evidence not in str(existing.get("evidence", "")):
                existing["evidence"] = str(existing.get("evidence", "")) + "; " + evidence
        existing["frequency"] = int(existing.get("frequency") or 0) + max(1, weight)
        if name:
            self.name_counts[name.lower()] += max(1, weight)

    def sorted_entries(self, limit: int) -> list[dict[str, Any]]:
        return sorted(
            self.entries.values(),
            key=lambda item: (
                -confidence_rank(str(item.get("confidence", ""))),
                -int(item.get("frequency") or 0),
                str(item.get("type") or ""),
                str(item.get("path") or ""),
            ),
        )[:limit]


def confidence_rank(value: str) -> int:
    value = value.lower()
    if value == "high":
        return 3
    if value == "medium":
        return 2
    if value == "low":
        return 1
    return 0


def add_learning_entries(builder: EntryBuilder) -> int:
    data = load_json(LEARNING_PATH)
    examples = data.get("examples", []) if isinstance(data, dict) else []
    count = 0
    for item in examples:
        if not isinstance(item, dict):
            continue
        if str(item.get("repo_kind", "")).lower() not in {"unity", ""}:
            continue
        rel_path = normalize_path(item.get("rel_path"))
        category = str(item.get("category") or "")
        reason = str(item.get("reason") or "")
        if not is_audio_like(rel_path, reason, category):
            continue
        confidence = "High" if any(word in normalize_key(rel_path) for word in ("wwise", "audio", "wwisebanks")) else "Medium"
        builder.add(
            rel_path,
            item_type=classify_type(rel_path, category),
            source="p4-history-learning",
            confidence=confidence,
            evidence=f"{item.get('change', '-')}: {category}",
        )
        count += 1
    return count


def add_audio_footprint_entries(builder: EntryBuilder) -> int:
    data = load_json(AUDIO_FOOTPRINT_PATH)
    rows = data.get("rows", []) if isinstance(data, dict) else []
    count = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        path = normalize_path(row.get("path"))
        bucket = str(row.get("bucket") or "")
        confidence = str(row.get("confidence") or "Low")
        score = int(row.get("score") or 0)
        if score < 8 or confidence_rank(confidence) <= 0:
            continue
        if not is_audio_like(path, bucket, confidence):
            continue
        events = row.get("events") or []
        evidence = row.get("evidence") or []
        evidence_kinds = []
        if isinstance(evidence, list):
            evidence_kinds = [str(item.get("kind")) for item in evidence[:4] if isinstance(item, dict) and item.get("kind")]
        builder.add(
            path,
            item_type=classify_type(path, bucket),
            source="unity-audio-footprint",
            confidence=confidence,
            evidence=f"{bucket}; score={score}; {', '.join(evidence_kinds)}",
            weight=max(1, score // 5),
        )
        for event_name in events[:16]:
            if event_name:
                builder.add(
                    "",
                    name=str(event_name),
                    item_type="WwiseEvent",
                    source="unity-audio-footprint-events",
                    confidence=confidence,
                    evidence=f"Referenced by {path}",
                    weight=1,
                )
        count += 1
    return count


def add_audio_tool_report_entries(builder: EntryBuilder, max_reports: int = 180) -> int:
    if not REPORT_DIR.exists():
        return 0
    reports = sorted(REPORT_DIR.glob(AUDIO_TOOL_REPORT_GLOB), key=lambda item: item.stat().st_mtime, reverse=True)[:max_reports]
    count = 0
    for report in reports:
        data = load_json(report)
        if not isinstance(data, dict):
            continue
        event_name = str(data.get("wwise_event") or "")
        for key, label in (("animation", "Animation"), ("prefab", "Prefab")):
            path = normalize_path(data.get(key))
            if not path:
                continue
            builder.add(
                path,
                item_type=label,
                source="animation-wwise-auto-config",
                confidence="High" if data.get("applied") else "Medium",
                evidence=f"{report.name}; event={event_name}",
                weight=8 if data.get("applied") else 3,
            )
            count += 1
        if event_name:
            builder.add(
                "",
                name=event_name,
                item_type="WwiseEvent",
                source="animation-wwise-auto-config",
                confidence="High",
                evidence=report.name,
                weight=3,
            )
    return count


def write_map(output_path: Path, entries: list[dict[str, Any]], source_counts: dict[str, int]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "generatedAt": dt.datetime.now().isoformat(timespec="seconds"),
        "sources": source_counts,
        "entries": entries,
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Export ProjectEF audio-related asset identity map for the Unity Editor overlay.")
    parser.add_argument("--unity-project", default=str(UNITY_PROJECT), help="Unity project root.")
    parser.add_argument("--limit", type=int, default=6000, help="Maximum entries written to the identity map.")
    parser.add_argument("--open", action="store_true", help="Reveal the generated identity map in Explorer.")
    args = parser.parse_args()

    unity_project = Path(args.unity_project)
    output_path = unity_project / OUTPUT_RELATIVE
    builder = EntryBuilder()
    source_counts = {
        "p4_learning": add_learning_entries(builder),
        "unity_audio_footprint": add_audio_footprint_entries(builder),
        "animation_wwise_reports": add_audio_tool_report_entries(builder),
    }
    entries = builder.sorted_entries(args.limit)
    write_map(output_path, entries, source_counts)

    print(f"Generated ProjectEF audio identity map: {output_path}")
    print(f"Entries: {len(entries)}")
    print("Sources:")
    for key, value in source_counts.items():
        print(f"  {key}: {value}")
    if args.open:
        os.startfile(str(output_path.parent))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
