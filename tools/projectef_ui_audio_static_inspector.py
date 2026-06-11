#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import datetime as dt
import html
import json
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable


DEFAULT_UNITY_ROOT = Path(r"D:\EF New\Client\TargetProject")
DEFAULT_WWISE_ROOT = Path(r"D:\EF Wwise\ProjectEF")
DEFAULT_REPORT_DIR = Path(r"G:\AI\Material\Wwise\报告")
DEFAULT_SCAN_ROOT = "Assets"

BUTTON_EX_GUID = "58da109ee91ff01409447b2efc6cfe69"
TOGGLE_EX_GUID = "b88b28360254ded4db6c6b844cae03d7"
UI_STATE_CLICK_GUID = "08138155e783471dba9c2031b3272cbf"
BUTTON_AUDIO_COMP_GUID = "57cb48a8f6b93454b9edff42b6b67f0e"

COMPONENT_GUIDS = {
    BUTTON_EX_GUID: "ButtonEx",
    TOGGLE_EX_GUID: "ToggleEx",
    UI_STATE_CLICK_GUID: "UIStateOnClickSoundController",
    BUTTON_AUDIO_COMP_GUID: "ButtonAudioComp",
}

AUDIO_OVERRIDE_FIELDS = {
    "m_pressedAudioName",
    "PressedAudioName",
    "m_pointerEnterAudioName",
    "PointerEnterAudioName",
    "m_soundEventName",
    "m_prohibitAudio",
}

SEVERITY_RANK = {
    "High": 0,
    "Medium": 1,
    "Low": 2,
    "Info": 3,
    "Pass": 4,
}

HEADER_RE = re.compile(r"^--- !u!(?P<class_id>\d+) &(?P<file_id>-?\d+)")
SCRIPT_GUID_RE = re.compile(r"m_Script:\s*\{[^}]*guid:\s*(?P<guid>[0-9a-fA-F]+)")
FILE_ID_RE = re.compile(r"fileID:\s*(?P<file_id>-?\d+)")
GUID_RE = re.compile(r"guid:\s*(?P<guid>[0-9a-fA-F]+)")
EVENT_RE = re.compile(r"<Event\b[^>]*\bName=\"([^\"]+)\"")
TARGET_TOKEN_BYTES = [
    token.encode("ascii")
    for token in list(COMPONENT_GUIDS.keys()) + sorted(AUDIO_OVERRIDE_FIELDS)
]


@dataclass
class UnityDoc:
    class_id: int
    file_id: str
    line: int
    lines: list[str]


@dataclass
class ComponentInfo:
    component_id: str
    component_type: str
    script_guid: str
    game_object_id: str
    line: int
    fields: dict[str, object] = field(default_factory=dict)


@dataclass
class ScanContext:
    unity_root: Path
    wwise_root: Path | None
    scan_root: Path
    report_dir: Path
    include_prefabs: bool = True
    include_scenes: bool = True
    max_file_mb: float = 64.0


def clean_scalar(value: str | None) -> str:
    if value is None:
        return ""
    value = value.strip()
    if value in {"", '""', "''"}:
        return ""
    if value.startswith('"') and value.endswith('"') and len(value) >= 2:
        value = value[1:-1]
    if value.startswith("'") and value.endswith("'") and len(value) >= 2:
        value = value[1:-1]
    return value.strip()


def parse_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes"}


def parse_int(value: object, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except Exception:
        return default


def field_scalar(lines: list[str], field_name: str, default: str = "") -> str:
    pattern = re.compile(r"^\s+" + re.escape(field_name) + r":\s*(.*)$")
    for line in lines:
        match = pattern.match(line)
        if match:
            return clean_scalar(match.group(1))
    return default


def field_file_id(lines: list[str], field_name: str) -> str:
    pattern = re.compile(r"^\s+" + re.escape(field_name) + r":\s*(.*)$")
    for line in lines:
        match = pattern.match(line)
        if not match:
            continue
        id_match = FILE_ID_RE.search(match.group(1))
        return id_match.group("file_id") if id_match else "0"
    return "0"


def yaml_list_has_items(lines: list[str], field_name: str) -> bool:
    pattern = re.compile(r"^(?P<indent>\s+)" + re.escape(field_name) + r":\s*(?P<value>.*)$")
    for index, line in enumerate(lines):
        match = pattern.match(line)
        if not match:
            continue
        value = match.group("value").strip()
        if value == "[]" or value.startswith("{}"):
            return False
        base_indent = len(match.group("indent"))
        for next_line in lines[index + 1 :]:
            if not next_line.strip():
                continue
            indent = len(next_line) - len(next_line.lstrip(" "))
            if indent <= base_indent:
                return False
            if next_line.strip().startswith("-"):
                return True
        return False
    return False


def parse_state_sound_entries(lines: list[str]) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    for line in lines:
        start = re.match(r"^\s*-\s+m_uiStateName:\s*(.*)$", line)
        if start:
            if current is not None:
                entries.append(current)
            current = {
                "state": clean_scalar(start.group(1)),
                "event": "",
                "enabled": True,
            }
            continue
        if current is None:
            continue
        event_match = re.match(r"^\s*m_soundEventName:\s*(.*)$", line)
        if event_match:
            current["event"] = clean_scalar(event_match.group(1))
            continue
        enabled_match = re.match(r"^\s*m_isEnableSound:\s*(.*)$", line)
        if enabled_match:
            current["enabled"] = parse_bool(enabled_match.group(1))
            continue
        if re.match(r"^\s{2}m_[A-Za-z0-9_]+:", line) and "m_uiStateOnClickSoundList" not in line:
            continue
    if current is not None:
        entries.append(current)
    return entries


def read_text(path: Path, max_bytes: int | None = None) -> str:
    if max_bytes is not None and path.stat().st_size > max_bytes:
        raise ValueError(f"File larger than max size: {path}")
    return path.read_text(encoding="utf-8-sig", errors="replace")


def file_contains_any_token(path: Path, tokens: list[bytes], chunk_size: int = 1024 * 1024) -> bool:
    tail = b""
    max_token_len = max(len(token) for token in tokens)
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                return False
            data = tail + chunk
            if any(token in data for token in tokens):
                return True
            tail = data[-max_token_len:]


def rel_path(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except Exception:
        return str(path).replace("\\", "/")


def split_unity_docs(text: str) -> list[UnityDoc]:
    docs: list[UnityDoc] = []
    current_class: int | None = None
    current_id = ""
    current_line = 1
    current_lines: list[str] = []
    for index, line in enumerate(text.splitlines(), start=1):
        header = HEADER_RE.match(line)
        if header:
            if current_class is not None:
                docs.append(UnityDoc(current_class, current_id, current_line, current_lines))
            current_class = int(header.group("class_id"))
            current_id = header.group("file_id")
            current_line = index
            current_lines = [line]
        elif current_class is not None:
            current_lines.append(line)
    if current_class is not None:
        docs.append(UnityDoc(current_class, current_id, current_line, current_lines))
    return docs


def build_guid_to_asset_map(unity_root: Path, progress: Callable[[str], None] | None = None) -> dict[str, str]:
    result: dict[str, str] = {}
    assets = unity_root / "Assets"
    if not assets.exists():
        return result
    count = 0
    for meta in assets.rglob("*.prefab.meta"):
        count += 1
        try:
            text = read_text(meta, max_bytes=128 * 1024)
        except Exception:
            continue
        match = re.search(r"^guid:\s*([0-9a-fA-F]+)\s*$", text, flags=re.MULTILINE)
        if match:
            prefab_path = meta.with_suffix("")
            result[match.group(1).lower()] = rel_path(prefab_path, unity_root)
    if progress:
        progress(f"Prefab GUID map: {len(result)} entries from {count} meta files")
    return result


def parse_wwise_events(wwise_root: Path | None) -> set[str]:
    events: set[str] = set()
    if not wwise_root or not wwise_root.exists():
        return events
    candidates: list[Path] = []
    candidates.extend(wwise_root.rglob("*.wwu"))
    candidates.extend(wwise_root.rglob("SoundbanksInfo.xml"))
    for path in candidates:
        try:
            text = read_text(path, max_bytes=96 * 1024 * 1024)
        except Exception:
            continue
        for name in EVENT_RE.findall(text):
            if name:
                events.add(name)
    return events


def parse_default_audio_settings(unity_root: Path) -> dict[str, str]:
    defaults = {
        "button": "UI1_NormalClick",
        "close_button": "Play_UI_Common_Exit",
        "button_hover": "Play_UI_Hover",
        "toggle": "Play_UI_Common_Toggle",
    }
    asset = unity_root / "Assets" / "GameProject" / "Resources" / "GameClientSetting.asset"
    if not asset.exists():
        return defaults
    try:
        text = read_text(asset, max_bytes=2 * 1024 * 1024)
    except Exception:
        return defaults
    mapping = {
        "m_defaultButtonClickSoundName": "button",
        "m_defaultCloseButtonClickSoundName": "close_button",
        "m_defaultButtonPointerEnterSoundName": "button_hover",
        "m_defaultToggleClickSoundName": "toggle",
    }
    for source, target in mapping.items():
        match = re.search(r"^\s*" + re.escape(source) + r":\s*(.*)$", text, flags=re.MULTILINE)
        if match:
            defaults[target] = clean_scalar(match.group(1))
    return defaults


def event_status(event_name: str, known_events: set[str]) -> str:
    if not event_name:
        return "Empty"
    if not known_events:
        return "Unverified"
    return "Known" if event_name in known_events else "Unknown"


def max_severity(current: str, candidate: str) -> str:
    return candidate if SEVERITY_RANK[candidate] < SEVERITY_RANK[current] else current


def guess_special_event(object_path: str, asset_path: str, component_type: str, defaults: dict[str, str]) -> str:
    text = f"{object_path} {asset_path}".lower()
    close_keys = ("close", "back", "return", "exit", "cancel")
    if any(key in text for key in close_keys):
        return defaults.get("close_button", "")
    if component_type == "ToggleEx" or "toggle" in text or "tab" in text:
        return defaults.get("toggle", "")
    return ""


def infer_priority(asset_path: str, object_path: str) -> str:
    text = f"{asset_path}/{object_path}".lower()
    if any(key in text for key in ("homemain", "main", "store", "shop", "task", "reward", "friend", "ranking")):
        return "A"
    if any(key in text for key in ("common", "button", "popup", "dialog")):
        return "B"
    return "C"


def parse_prefab_audio_overrides(
    lines: list[str],
    asset_rel: str,
    guid_to_asset: dict[str, str],
    known_events: set[str],
) -> list[dict[str, object]]:
    overrides: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    for line_no, line in enumerate(lines, start=1):
        target_match = re.match(r"^\s*-\s+target:\s*(.*)$", line)
        if target_match:
            current = {
                "asset_path": asset_rel,
                "line": line_no,
                "target_file_id": "",
                "target_guid": "",
                "source_asset": "",
                "property": "",
                "value": "",
                "severity": "Info",
                "status": "PrefabInstanceOverride",
                "issues": [],
            }
            payload = target_match.group(1)
            file_match = FILE_ID_RE.search(payload)
            guid_match = GUID_RE.search(payload)
            if file_match:
                current["target_file_id"] = file_match.group("file_id")
            if guid_match:
                guid = guid_match.group("guid").lower()
                current["target_guid"] = guid
                current["source_asset"] = guid_to_asset.get(guid, "")
            continue
        if current is None:
            continue
        prop_match = re.match(r"^\s*propertyPath:\s*(.*)$", line)
        if prop_match:
            current["property"] = clean_scalar(prop_match.group(1))
            continue
        value_match = re.match(r"^\s*value:\s*(.*)$", line)
        if value_match:
            current["value"] = clean_scalar(value_match.group(1))
            continue
        if re.match(r"^\s*objectReference:", line):
            prop = str(current.get("property", ""))
            if prop in AUDIO_OVERRIDE_FIELDS:
                value = str(current.get("value", ""))
                issues: list[str] = []
                severity = "Info"
                status = "PrefabInstanceAudioOverride"
                if prop in {"m_pressedAudioName", "PressedAudioName", "m_pointerEnterAudioName", "PointerEnterAudioName", "m_soundEventName"}:
                    wwise_status = event_status(value, known_events)
                    current["wwise_status"] = wwise_status
                    if value and wwise_status == "Unknown":
                        severity = "Medium"
                        status = "UnknownWwiseEvent"
                        issues.append(f"Override value `{value}` was not found in parsed Wwise Events.")
                    elif not value:
                        severity = "Low"
                        status = "AudioOverrideEmpty"
                        issues.append(f"Prefab instance override clears `{prop}`.")
                elif prop == "m_prohibitAudio" and parse_bool(value):
                    status = "AudioProhibitedOverride"
                    issues.append("Prefab instance override disables ButtonEx/ToggleEx audio.")
                current["severity"] = severity
                current["status"] = status
                current["issues"] = issues
                overrides.append(dict(current))
            current = None
    return overrides


def scan_unity_asset(
    path: Path,
    ctx: ScanContext,
    known_events: set[str],
    defaults: dict[str, str],
    guid_to_asset: dict[str, str],
) -> dict[str, object]:
    asset_rel = rel_path(path, ctx.unity_root)
    max_bytes = int(ctx.max_file_mb * 1024 * 1024)
    if path.stat().st_size > max_bytes and not file_contains_any_token(path, TARGET_TOKEN_BYTES):
        return {
            "items": [],
            "state_items": [],
            "overrides": [],
            "stats": {
                "files_scanned": 1,
                "files_with_ui_audio": 0,
                "skipped_no_hits": 1,
                "large_file_prefilter_skips": 1,
                "component_type_counts": {},
            },
        }
    text = read_text(path, max_bytes=max_bytes)
    lines = text.splitlines()
    has_target = any(guid in text for guid in COMPONENT_GUIDS) or any(field in text for field in AUDIO_OVERRIDE_FIELDS)
    if not has_target:
        return {
            "items": [],
            "state_items": [],
            "overrides": [],
            "stats": {
                "files_scanned": 1,
                "files_with_ui_audio": 0,
                "skipped_no_hits": 1,
            },
        }

    docs = split_unity_docs(text)
    game_object_names: dict[str, str] = {}
    transform_to_go: dict[str, str] = {}
    go_to_transform: dict[str, str] = {}
    transform_parent: dict[str, str] = {}
    components_by_go: dict[str, list[ComponentInfo]] = defaultdict(list)
    components: list[ComponentInfo] = []

    for doc in docs:
        if doc.class_id == 1:
            name = field_scalar(doc.lines, "m_Name", f"GameObject_{doc.file_id}")
            game_object_names[doc.file_id] = name or f"GameObject_{doc.file_id}"
        elif doc.class_id in {4, 224}:
            go_id = field_file_id(doc.lines, "m_GameObject")
            father_id = field_file_id(doc.lines, "m_Father")
            transform_to_go[doc.file_id] = go_id
            if go_id and go_id != "0":
                go_to_transform[go_id] = doc.file_id
            transform_parent[doc.file_id] = father_id
        elif doc.class_id == 114:
            script_match = SCRIPT_GUID_RE.search("\n".join(doc.lines[:24]))
            if not script_match:
                script_match = SCRIPT_GUID_RE.search("\n".join(doc.lines))
            if not script_match:
                continue
            guid = script_match.group("guid").lower()
            if guid not in COMPONENT_GUIDS:
                continue
            go_id = field_file_id(doc.lines, "m_GameObject")
            component_type = COMPONENT_GUIDS[guid]
            fields: dict[str, object] = {}
            if component_type in {"ButtonEx", "ToggleEx"}:
                fields["pressed_audio"] = field_scalar(doc.lines, "m_pressedAudioName") or field_scalar(doc.lines, "PressedAudioName")
                fields["pointer_enter_audio"] = field_scalar(doc.lines, "m_pointerEnterAudioName") or field_scalar(doc.lines, "PointerEnterAudioName")
                fields["prohibit_audio"] = parse_bool(field_scalar(doc.lines, "m_prohibitAudio", "0"))
                fields["has_pointer_enter_tween"] = yaml_list_has_items(doc.lines, "m_pointerEnterTweenList")
            elif component_type == "UIStateOnClickSoundController":
                fields["ui_state_controller_go"] = field_file_id(doc.lines, "m_uiStateControllerGameObject")
                fields["state_sound_entries"] = parse_state_sound_entries(doc.lines)
            elif component_type == "ButtonAudioComp":
                fields["preset_type"] = parse_int(field_scalar(doc.lines, "m_presetType", "0"))
                fields["pointer_enter_mode"] = parse_int(field_scalar(doc.lines, "m_pointerEnterAudioApplyMode", "0"))
            info = ComponentInfo(
                component_id=doc.file_id,
                component_type=component_type,
                script_guid=guid,
                game_object_id=go_id,
                line=doc.line,
                fields=fields,
            )
            components.append(info)
            components_by_go[go_id].append(info)

    def object_path(go_id: str) -> str:
        if not go_id or go_id == "0":
            return "(unresolved GameObject)"
        transform_id = go_to_transform.get(go_id)
        if not transform_id:
            return game_object_names.get(go_id, f"GameObject_{go_id}")
        names: list[str] = []
        seen: set[str] = set()
        current = transform_id
        while current and current != "0" and current not in seen and len(names) < 80:
            seen.add(current)
            current_go = transform_to_go.get(current, "")
            names.append(game_object_names.get(current_go, f"GameObject_{current_go or current}"))
            current = transform_parent.get(current, "0")
        return "/".join(reversed(names)) if names else game_object_names.get(go_id, f"GameObject_{go_id}")

    name_counter = Counter()
    for comp in components:
        if comp.component_type in {"ButtonEx", "ToggleEx"}:
            name_counter[game_object_names.get(comp.game_object_id, "")] += 1

    items: list[dict[str, object]] = []
    state_items: list[dict[str, object]] = []

    for comp in components:
        if comp.component_type not in {"ButtonEx", "ToggleEx"}:
            continue
        path_text = object_path(comp.game_object_id)
        companion = components_by_go.get(comp.game_object_id, [])
        companion_types = [item.component_type for item in companion if item.component_id != comp.component_id]
        button_audio = next((item for item in companion if item.component_type == "ButtonAudioComp"), None)
        state_controller = next((item for item in companion if item.component_type == "UIStateOnClickSoundController"), None)
        severity = "Pass"
        status = "Configured"
        issues: list[str] = []
        suggestions: list[str] = []
        pressed = str(comp.fields.get("pressed_audio", ""))
        pointer_enter = str(comp.fields.get("pointer_enter_audio", ""))
        has_hover_tween = bool(comp.fields.get("has_pointer_enter_tween", False))
        prohibit = bool(comp.fields.get("prohibit_audio", False))
        default_audio = defaults["button"] if comp.component_type == "ButtonEx" else defaults["toggle"]
        effective_audio = pressed or default_audio
        wwise_status = event_status(pressed, known_events)
        priority = infer_priority(asset_rel, path_text)

        if comp.component_type == "ButtonEx" and state_controller:
            status = "StateControlled"
            severity = "Info"
            entries = list(state_controller.fields.get("state_sound_entries", []))
            state_target = str(state_controller.fields.get("ui_state_controller_go", "0"))
            effective_audio = "(state dependent)"
            if pressed:
                severity = max_severity(severity, "Low")
                issues.append("Serialized ButtonEx pressed audio is likely ignored because UIStateOnClickSoundController sets ProhibitAudio at runtime.")
            if not entries:
                severity = max_severity(severity, "Medium")
                status = "StateControllerNoSound"
                issues.append("UIStateOnClickSoundController has no state sound entries; click audio will return early.")
            if state_target in {"", "0"}:
                severity = max_severity(severity, "Medium")
                status = "StateControllerMissingTarget"
                issues.append("UIStateOnClickSoundController has no UI state controller GameObject target.")
            enabled_count = 0
            for entry in entries:
                enabled = bool(entry.get("enabled", True))
                state_event = str(entry.get("event", ""))
                state_status = "StateDisabled"
                state_severity = "Info"
                state_effective = ""
                state_issues: list[str] = []
                if enabled:
                    enabled_count += 1
                    state_effective = state_event or defaults["button"]
                    state_status = "StateConfigured" if state_event else "StateDefaultFallback"
                    state_wwise = event_status(state_effective, known_events)
                    if state_wwise == "Unknown":
                        state_status = "UnknownWwiseEvent"
                        state_severity = "Medium"
                        state_issues.append(f"State event `{state_effective}` was not found in parsed Wwise Events.")
                    elif not state_event:
                        state_issues.append("Enabled state uses default button click fallback.")
                else:
                    state_wwise = "Disabled"
                    state_issues.append("State click sound is disabled.")
                severity = max_severity(severity, state_severity)
                if state_status == "UnknownWwiseEvent":
                    status = "StateHasUnknownWwiseEvent"
                state_items.append(
                    {
                        "asset_path": asset_rel,
                        "asset_type": path.suffix.lstrip("."),
                        "line": state_controller.line,
                        "component_id": state_controller.component_id,
                        "object_path": path_text,
                        "component_type": "UIStateOnClickSoundController",
                        "state_name": str(entry.get("state", "")),
                        "enabled": enabled,
                        "event": state_event,
                        "effective_event": state_effective,
                        "wwise_status": state_wwise,
                        "severity": state_severity,
                        "status": state_status,
                        "issues": state_issues,
                    }
                )
            if entries and enabled_count == 0:
                severity = max_severity(severity, "Medium")
                status = "StateControllerAllStatesSilent"
                issues.append("All UI state click sound entries are disabled.")
        elif comp.component_type == "ButtonEx" and button_audio:
            preset_type = parse_int(button_audio.fields.get("preset_type", 0))
            pointer_mode = parse_int(button_audio.fields.get("pointer_enter_mode", 0))
            preset_name = defaults["close_button"] if preset_type == 1 else defaults["button"]
            preset_label = "CloseButton" if preset_type == 1 else "Default"
            status = "PresetCovered"
            severity = "Info"
            effective_audio = preset_name
            wwise_status = event_status(preset_name, known_events)
            suggestions.append(f"ButtonAudioComp preset: {preset_label} -> {preset_name}")
            if pressed and pressed != preset_name:
                severity = max_severity(severity, "Low")
                issues.append(f"Serialized pressed audio `{pressed}` is overwritten by ButtonAudioComp preset `{preset_name}` in Awake.")
            if wwise_status == "Unknown":
                severity = max_severity(severity, "Medium")
                status = "PresetUnknownWwiseEvent"
                issues.append(f"Preset event `{preset_name}` was not found in parsed Wwise Events.")
            if pointer_mode == 1 or (pointer_mode == 2 and has_hover_tween):
                if preset_type == 1:
                    severity = max_severity(severity, "Medium")
                    issues.append("ButtonAudioComp requests hover audio for CloseButton, but GetPointerEnterAudioName does not handle CloseButton.")
                    status = "UnsupportedCloseButtonHoverPreset"
                else:
                    hover_event = defaults["button_hover"]
                    hover_status = event_status(hover_event, known_events)
                    if hover_status == "Unknown":
                        severity = max_severity(severity, "Medium")
                        issues.append(f"Hover preset event `{hover_event}` was not found in parsed Wwise Events.")
            elif has_hover_tween and not pointer_enter:
                severity = max_severity(severity, "Low")
                issues.append("Button has pointer-enter tween but no pointer-enter audio is configured or preset-applied.")
        elif prohibit:
            status = "Prohibited"
            severity = "Info"
            effective_audio = "(disabled)"
            issues.append("m_prohibitAudio disables this component audio.")
        elif pressed:
            status = "Configured"
            wwise_status = event_status(pressed, known_events)
            effective_audio = pressed
            if wwise_status == "Unknown":
                severity = max_severity(severity, "Medium")
                status = "UnknownWwiseEvent"
                issues.append(f"Event `{pressed}` was not found in parsed Wwise Events.")
        else:
            status = "DefaultFallback"
            severity = "Info"
            effective_audio = default_audio
            default_status = event_status(default_audio, known_events)
            if default_status == "Unknown":
                severity = max_severity(severity, "High")
                status = "DefaultFallbackUnknownWwiseEvent"
                issues.append(f"Default fallback `{default_audio}` was not found in parsed Wwise Events.")
            special = guess_special_event(path_text, asset_rel, comp.component_type, defaults)
            if special and special != default_audio:
                severity = max_severity(severity, "Low")
                suggestions.append(f"Path/name suggests specialized event: {special}")
                issues.append("Empty explicit audio falls back to generic default; review whether a specialized event is intended.")

        if pointer_enter:
            pointer_status = event_status(pointer_enter, known_events)
            if pointer_status == "Unknown":
                severity = max_severity(severity, "Medium")
                issues.append(f"Pointer-enter event `{pointer_enter}` was not found in parsed Wwise Events.")
        elif has_hover_tween and comp.component_type == "ButtonEx" and not button_audio:
            severity = max_severity(severity, "Low")
            issues.append("Button has pointer-enter tween but m_pointerEnterAudioName is empty.")

        go_name = game_object_names.get(comp.game_object_id, "")
        duplicate_count = name_counter.get(go_name, 0)
        if go_name and duplicate_count > 1:
            severity = max_severity(severity, "Low")
            issues.append(f"Audited UI object name `{go_name}` appears {duplicate_count} times in this asset; runtime name-only lookup is risky.")

        items.append(
            {
                "asset_path": asset_rel,
                "asset_type": path.suffix.lstrip("."),
                "line": comp.line,
                "component_id": comp.component_id,
                "game_object_id": comp.game_object_id,
                "object_name": go_name,
                "object_path": path_text,
                "component_type": comp.component_type,
                "pressed_audio": pressed,
                "pointer_enter_audio": pointer_enter,
                "effective_audio": effective_audio,
                "default_audio": default_audio,
                "wwise_status": event_status(effective_audio, known_events) if not effective_audio.startswith("(") else "Runtime",
                "status": status,
                "severity": severity,
                "priority": priority,
                "has_pointer_enter_tween": has_hover_tween,
                "prohibit_audio": prohibit,
                "companion_components": companion_types,
                "duplicate_name_count": duplicate_count,
                "issues": issues,
                "suggestions": suggestions,
            }
        )

    overrides = parse_prefab_audio_overrides(lines, asset_rel, guid_to_asset, known_events)
    component_type_counts = Counter(comp.component_type for comp in components)
    return {
        "items": items,
        "state_items": state_items,
        "overrides": overrides,
        "stats": {
            "files_scanned": 1,
            "files_with_ui_audio": 1 if items or state_items or overrides else 0,
            "skipped_no_hits": 0,
            "unity_docs": len(docs),
            "target_components": len(components),
            "component_type_counts": dict(component_type_counts),
        },
    }


def iter_scan_files(ctx: ScanContext) -> list[Path]:
    suffixes: set[str] = set()
    if ctx.include_prefabs:
        suffixes.add(".prefab")
    if ctx.include_scenes:
        suffixes.add(".unity")
    if not ctx.scan_root.exists():
        return []
    files = [path for path in ctx.scan_root.rglob("*") if path.is_file() and path.suffix.lower() in suffixes]
    return sorted(files, key=lambda item: str(item).lower())


def summarize_rows(rows: Iterable[dict[str, object]]) -> dict[str, int]:
    counter = Counter(str(row.get("status", "")) for row in rows)
    return dict(sorted(counter.items(), key=lambda item: item[0]))


def row_sort_key(row: dict[str, object]) -> tuple[int, str, str]:
    return (
        SEVERITY_RANK.get(str(row.get("severity", "Info")), 99),
        str(row.get("asset_path", "")),
        str(row.get("object_path", "")),
    )


def flatten_issues(row: dict[str, object]) -> str:
    issues = row.get("issues", [])
    if isinstance(issues, list):
        return "; ".join(str(item) for item in issues)
    return str(issues)


def flatten_suggestions(row: dict[str, object]) -> str:
    suggestions = row.get("suggestions", [])
    if isinstance(suggestions, list):
        return "; ".join(str(item) for item in suggestions)
    return str(suggestions)


def issue_blob(row: dict[str, object]) -> str:
    return " ".join(
        [
            str(row.get("status", "")),
            str(row.get("wwise_status", "")),
            flatten_issues(row),
            flatten_suggestions(row),
        ]
    ).lower()


def issue_rows(rows: Iterable[dict[str, object]]) -> list[dict[str, object]]:
    return [row for row in rows if str(row.get("severity")) in {"High", "Medium", "Low"}]


def build_review_queues(result: dict[str, object]) -> list[dict[str, object]]:
    components = issue_rows(result["items"])
    states = issue_rows(result["state_items"])
    overrides = issue_rows(result["overrides"])
    all_rows = components + states + overrides

    queues = [
        (
            "Unknown Wwise event strings",
            [row for row in all_rows if "unknownwwiseevent" in str(row.get("status", "")).lower() or str(row.get("wwise_status", "")).lower() == "unknown"],
            "Check spelling or confirm runtime-generated Events.",
        ),
        (
            "A/B priority component issues",
            [row for row in components if str(row.get("priority", "")) in {"A", "B"}],
            "Review high-traffic UI first.",
        ),
        (
            "Specialized default fallbacks",
            [row for row in components if str(row.get("status", "")) == "DefaultFallback" and flatten_suggestions(row)],
            "Decide whether the generic click should become a close/toggle-specific Event.",
        ),
        (
            "Duplicate object-name lookup risks",
            [row for row in components if parse_int(row.get("duplicate_name_count", 0)) > 1],
            "Avoid relying on short object names when applying fixes or runtime checks.",
        ),
        (
            "Hover-audio review",
            [row for row in components if "hover" in issue_blob(row) or "pointer-enter" in issue_blob(row)],
            "Verify hover tween and pointer-enter sound intent together.",
        ),
        (
            "Prefab instance audio overrides",
            overrides,
            "Inspect inherited prefab changes before changing source prefabs.",
        ),
        (
            "UI state click sound issues",
            states,
            "Check state controller target, enabled states, and fallback Events.",
        ),
    ]
    return [
        {
            "queue": name,
            "count": len(rows),
            "next_step": next_step,
        }
        for name, rows, next_step in queues
    ]


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            normalized = dict(row)
            normalized["issues"] = flatten_issues(row)
            normalized["suggestions"] = flatten_suggestions(row)
            normalized["companion_components"] = "; ".join(str(item) for item in row.get("companion_components", []))
            writer.writerow(normalized)


def md_table(rows: list[list[object]], headers: list[str], max_rows: int = 80) -> str:
    if not rows:
        return "_None._"
    display = rows[:max_rows]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in display:
        escaped = [str(cell).replace("|", "\\|").replace("\n", " ") for cell in row]
        lines.append("| " + " | ".join(escaped) + " |")
    if len(rows) > max_rows:
        lines.append(f"\n_Showing {max_rows} of {len(rows)} rows. See CSV/JSON for full detail._")
    return "\n".join(lines)


def render_markdown(result: dict[str, object], csv_name: str, json_name: str, html_name: str) -> str:
    summary = result["summary"]
    defaults = result["defaults"]
    items = sorted(result["items"], key=row_sort_key)
    state_items = sorted(result["state_items"], key=row_sort_key)
    overrides = sorted(result["overrides"], key=row_sort_key)
    issue_items = issue_rows(items)
    issue_states = issue_rows(state_items)
    issue_overrides = issue_rows(overrides)
    review_queues = build_review_queues(result)
    lines = [
        "# ProjectEF UI Audio Static Inspector Report",
        "",
        "Read-only scan. This report did not modify Unity prefabs, scenes, Wwise work units, SoundBanks, or the existing UI Audio Inspector.",
        "",
        "## Source Quality",
        "",
        f"- SourceGrade: {summary['source_grade']}",
        f"- Unity root: `{summary['unity_root']}`",
        f"- Scan root: `{summary['scan_root']}`",
        f"- Wwise root: `{summary['wwise_root']}`",
        f"- Generated: `{summary['generated_at']}`",
        f"- Coverage note: static YAML scan only; runtime-only UI creation and inherited prefab instance internals may need Unity AssetDatabase follow-up.",
        "",
        "## Output Files",
        "",
        f"- Markdown: `{html.escape(str(result['paths']['markdown']))}`",
        f"- HTML: `{html_name}`",
        f"- JSON: `{json_name}`",
        f"- CSV: `{csv_name}`",
        "",
        "## Summary",
        "",
        md_table(
            [
                ["Files considered", summary["files_considered"]],
                ["Files scanned", summary["files_scanned"]],
                ["Files with UI audio evidence", summary["files_with_ui_audio"]],
                ["Large files skipped after token prefilter", summary.get("large_file_prefilter_skips", 0)],
                ["ButtonEx", summary["component_counts"].get("ButtonEx", 0)],
                ["ToggleEx", summary["component_counts"].get("ToggleEx", 0)],
                ["UIStateOnClickSoundController", summary["component_counts"].get("UIStateOnClickSoundController", 0)],
                ["ButtonAudioComp", summary["component_counts"].get("ButtonAudioComp", 0)],
                ["Known Wwise Events", summary["known_wwise_events"]],
                ["Read errors", summary["read_errors"]],
            ],
            ["Metric", "Value"],
            max_rows=30,
        ),
        "",
        "## Default Events",
        "",
        md_table(
            [
                ["Button", defaults.get("button", "")],
                ["Close Button", defaults.get("close_button", "")],
                ["Button Hover", defaults.get("button_hover", "")],
                ["Toggle", defaults.get("toggle", "")],
            ],
            ["Default", "Event"],
            max_rows=20,
        ),
        "",
        "## Severity Counts",
        "",
        md_table([[key, value] for key, value in summary["severity_counts"].items()], ["Severity", "Count"], max_rows=20),
        "",
        "## Component Status Counts",
        "",
        md_table([[key, value] for key, value in summary["item_status_counts"].items()], ["Status", "Count"], max_rows=60),
        "",
        "## Review Queues",
        "",
        md_table(
            [[row["queue"], row["count"], row["next_step"]] for row in review_queues],
            ["Queue", "Count", "Next Step"],
            max_rows=20,
        ),
        "",
        "## Highest Priority Component Findings",
        "",
        md_table(
            [
                [
                    row.get("severity", ""),
                    row.get("status", ""),
                    row.get("component_type", ""),
                    row.get("priority", ""),
                    row.get("asset_path", ""),
                    row.get("object_path", ""),
                    row.get("effective_audio", ""),
                    flatten_issues(row),
                    flatten_suggestions(row),
                ]
                for row in issue_items
            ],
            ["Severity", "Status", "Component", "Priority", "Asset", "Object", "Effective Event", "Issues", "Suggestions"],
            max_rows=100,
        ),
        "",
        "## UI State Sound Findings",
        "",
        md_table(
            [
                [
                    row.get("severity", ""),
                    row.get("status", ""),
                    row.get("asset_path", ""),
                    row.get("object_path", ""),
                    row.get("state_name", ""),
                    row.get("effective_event", ""),
                    row.get("wwise_status", ""),
                    flatten_issues(row),
                ]
                for row in issue_states
            ],
            ["Severity", "Status", "Asset", "Object", "State", "Effective Event", "Wwise", "Issues"],
            max_rows=100,
        ),
        "",
        "## Prefab Instance Audio Overrides",
        "",
        md_table(
            [
                [
                    row.get("severity", ""),
                    row.get("status", ""),
                    row.get("asset_path", ""),
                    row.get("property", ""),
                    row.get("value", ""),
                    row.get("source_asset", ""),
                    flatten_issues(row),
                ]
                for row in issue_overrides
            ],
            ["Severity", "Status", "Asset", "Property", "Value", "Source Asset", "Issues"],
            max_rows=100,
        ),
        "",
        "## Interpretation Notes",
        "",
        "- `DefaultFallback` is not automatically a runtime failure. ButtonEx and ToggleEx can play project defaults when the serialized field is empty.",
        "- `PresetCovered` means ButtonAudioComp writes the audio name at runtime. Serialized ButtonEx values on the same object may be overwritten.",
        "- `StateControlled` means UIStateOnClickSoundController takes over click playback and sets ButtonEx.ProhibitAudio at runtime.",
        "- `UnknownWwiseEvent` means the string was not found in parsed Wwise Events. If the event is generated dynamically, verify with Unity/Wwise runtime evidence.",
    ]
    return "\n".join(lines) + "\n"


def render_html(result: dict[str, object], title: str) -> str:
    summary = result["summary"]
    items = sorted(result["items"], key=row_sort_key)
    state_items = sorted(result["state_items"], key=row_sort_key)
    overrides = sorted(result["overrides"], key=row_sort_key)
    paths = result.get("paths", {})

    def severity_class(value: object) -> str:
        return str(value).lower()

    def report_link(key: str, label: str) -> str:
        value = str(paths.get(key, ""))
        if not value:
            return ""
        name = Path(value).name
        return f"<a href=\"{html.escape(name)}\">{html.escape(label)}</a>"

    def option_list(values: Iterable[object]) -> str:
        unique = sorted({str(value) for value in values if str(value)})
        return "".join(f"<option value=\"{html.escape(value)}\">{html.escape(value)}</option>" for value in unique)

    def row_attributes(row: dict[str, object]) -> str:
        values = {
            "severity": str(row.get("severity", "")),
            "status": str(row.get("status", "")),
            "component": str(row.get("component_type", "")),
            "priority": str(row.get("priority", "")),
        }
        return " ".join(f"data-{key}=\"{html.escape(value)}\"" for key, value in values.items())

    def table(headers: list[str], rows: list[dict[str, object]], mapper: Callable[[dict[str, object]], list[object]], limit: int | None = None) -> str:
        display = rows[:limit] if limit else rows
        head = "".join(f"<th>{html.escape(header)}</th>" for header in headers)
        body_rows = []
        for row in display:
            cells = mapper(row)
            cls = severity_class(row.get("severity", "info"))
            body_rows.append(
                "<tr class=\""
                + cls
                + "\" "
                + row_attributes(row)
                + ">"
                + "".join(f"<td>{html.escape(str(cell))}</td>" for cell in cells)
                + "</tr>"
            )
        more = ""
        if limit and len(rows) > limit:
            more = f"<p class=\"muted\">Showing {limit} of {len(rows)} rows. CSV/JSON contains full detail.</p>"
        if not rows:
            return "<p class=\"empty\">No matching issue rows.</p>"
        return (
            "<div class=\"table-meta\" data-table-count>Showing "
            + str(len(display))
            + " of "
            + str(len(display))
            + " loaded rows</div>"
            + f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>{more}"
        )

    severity_cards = "".join(
        f"<div class=\"metric\"><span>{html.escape(str(key))}</span><strong>{value}</strong></div>"
        for key, value in summary["severity_counts"].items()
    )
    status_cards = "".join(
        f"<div class=\"chip\"><span>{html.escape(str(key))}</span><b>{value}</b></div>"
        for key, value in summary["item_status_counts"].items()
    )
    component_rows = issue_rows(items)
    state_rows = issue_rows(state_items)
    override_rows = issue_rows(overrides)
    all_filter_rows = component_rows + state_rows + override_rows
    review_queues = build_review_queues(result)
    review_cards = "".join(
        "<div class=\"queue\">"
        f"<span>{html.escape(str(row['queue']))}</span>"
        f"<strong>{html.escape(str(row['count']))}</strong>"
        f"<p>{html.escape(str(row['next_step']))}</p>"
        "</div>"
        for row in review_queues
    )
    output_links = " ".join(
        link
        for link in [
            report_link("html", "HTML"),
            report_link("markdown", "Markdown"),
            report_link("csv", "Components CSV"),
            report_link("state_csv", "States CSV"),
            report_link("override_csv", "Overrides CSV"),
            report_link("json", "JSON"),
        ]
        if link
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{html.escape(title)}</title>
<style>
body {{ margin: 0; font-family: "Segoe UI", Arial, sans-serif; background: #101720; color: #e9f2ff; }}
header {{ padding: 26px 32px; background: #172233; border-bottom: 1px solid #334258; position: sticky; top: 0; z-index: 2; }}
h1 {{ margin: 0 0 6px 0; font-size: 26px; }}
h2 {{ margin: 28px 0 10px 0; font-size: 18px; }}
main {{ padding: 24px 32px 40px; }}
.muted {{ color: #9fb0c6; }}
.empty {{ color: #9fb0c6; background: #162233; border: 1px solid #334258; padding: 12px; border-radius: 6px; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; margin: 18px 0; }}
.metric, .chip, .queue {{ background: #182436; border: 1px solid #334258; padding: 12px; border-radius: 6px; }}
.metric span, .chip span, .queue span {{ display: block; color: #9fb0c6; font-size: 12px; }}
.metric strong, .chip b, .queue strong {{ display: block; color: #ffffff; font-size: 21px; margin-top: 4px; }}
.queue p {{ color: #b8c9dd; font-size: 12px; margin: 8px 0 0; line-height: 1.35; }}
.toolbar {{ display: grid; grid-template-columns: minmax(260px, 1fr) repeat(4, minmax(130px, 180px)); gap: 10px; margin: 16px 0 20px; align-items: end; }}
.tool-field label {{ display: block; color: #9fb0c6; font-size: 12px; margin: 0 0 5px; }}
input, select {{ width: 100%; box-sizing: border-box; background: #182436; color: #e9f2ff; border: 1px solid #334258; border-radius: 5px; padding: 8px 9px; font: inherit; }}
.table-meta {{ color: #9fb0c6; font-size: 12px; margin: 8px 0; }}
table {{ width: 100%; border-collapse: collapse; margin: 10px 0 22px; table-layout: fixed; }}
th, td {{ border: 1px solid #334258; padding: 8px 9px; vertical-align: top; word-break: break-word; font-size: 12px; }}
th {{ background: #1f2d42; color: #d9e8fb; text-align: left; }}
tr.high td {{ background: #3a1820; }}
tr.medium td {{ background: #352718; }}
tr.low td {{ background: #243047; }}
tr.info td {{ background: #162233; }}
code {{ color: #b7e4ff; }}
a {{ color: #69c7ff; }}
.links a {{ display: inline-block; margin: 0 10px 8px 0; }}
@media (max-width: 920px) {{ .toolbar {{ grid-template-columns: 1fr 1fr; }} header {{ position: static; }} }}
</style>
</head>
<body>
<header>
<h1>{html.escape(title)}</h1>
<div class="muted">Read-only Unity YAML scan. No Unity, Wwise, SoundBank, or existing Inspector files were modified.</div>
</header>
<main>
<h2>Scan Scope</h2>
<p class="muted">Unity root: <code>{html.escape(str(summary['unity_root']))}</code><br>
Scan root: <code>{html.escape(str(summary['scan_root']))}</code><br>
Wwise root: <code>{html.escape(str(summary['wwise_root']))}</code><br>
Generated: <code>{html.escape(str(summary['generated_at']))}</code></p>
<p class="links">{output_links}</p>
<div class="grid">
<div class="metric"><span>Files considered</span><strong>{summary['files_considered']}</strong></div>
<div class="metric"><span>Files with UI audio</span><strong>{summary['files_with_ui_audio']}</strong></div>
<div class="metric"><span>Large prefilter skips</span><strong>{summary.get('large_file_prefilter_skips', 0)}</strong></div>
<div class="metric"><span>ButtonEx</span><strong>{summary['component_counts'].get('ButtonEx', 0)}</strong></div>
<div class="metric"><span>ToggleEx</span><strong>{summary['component_counts'].get('ToggleEx', 0)}</strong></div>
<div class="metric"><span>Wwise Events</span><strong>{summary['known_wwise_events']}</strong></div>
</div>
<h2>Severity Counts</h2>
<div class="grid">{severity_cards}</div>
<h2>Status Counts</h2>
<div class="grid">{status_cards}</div>
<h2>Review Queues</h2>
<div class="grid">{review_cards}</div>
<h2>Filter Findings</h2>
<div class="toolbar">
<div class="tool-field"><label for="filterSearch">Search</label><input id="filterSearch" type="search" placeholder="asset, object, Event, issue..."></div>
<div class="tool-field"><label for="filterSeverity">Severity</label><select id="filterSeverity"><option value="">All</option>{option_list(row.get("severity", "") for row in all_filter_rows)}</select></div>
<div class="tool-field"><label for="filterStatus">Status</label><select id="filterStatus"><option value="">All</option>{option_list(row.get("status", "") for row in all_filter_rows)}</select></div>
<div class="tool-field"><label for="filterComponent">Component</label><select id="filterComponent"><option value="">All</option>{option_list(row.get("component_type", "") for row in all_filter_rows)}</select></div>
<div class="tool-field"><label for="filterPriority">Priority</label><select id="filterPriority"><option value="">All</option>{option_list(row.get("priority", "") for row in all_filter_rows)}</select></div>
</div>
<h2>Component Findings</h2>
{table(
    ["Severity", "Status", "Component", "Priority", "Asset", "Object", "Effective Event", "Issues", "Suggestions"],
    component_rows,
    lambda row: [
        row.get("severity", ""),
        row.get("status", ""),
        row.get("component_type", ""),
        row.get("priority", ""),
        row.get("asset_path", ""),
        row.get("object_path", ""),
        row.get("effective_audio", ""),
        flatten_issues(row),
        flatten_suggestions(row),
    ],
    limit=500,
)}
<h2>UI State Sound Findings</h2>
{table(
    ["Severity", "Status", "Asset", "Object", "State", "Effective Event", "Wwise", "Issues"],
    state_rows,
    lambda row: [
        row.get("severity", ""),
        row.get("status", ""),
        row.get("asset_path", ""),
        row.get("object_path", ""),
        row.get("state_name", ""),
        row.get("effective_event", ""),
        row.get("wwise_status", ""),
        flatten_issues(row),
    ],
    limit=500,
)}
<h2>Prefab Instance Audio Overrides</h2>
{table(
    ["Severity", "Status", "Asset", "Property", "Value", "Source Asset", "Issues"],
    override_rows,
    lambda row: [
        row.get("severity", ""),
        row.get("status", ""),
        row.get("asset_path", ""),
        row.get("property", ""),
        row.get("value", ""),
        row.get("source_asset", ""),
        flatten_issues(row),
    ],
    limit=500,
)}
<h2>Notes</h2>
<p class="muted">DefaultFallback is not automatically a runtime failure. It means runtime code falls back to the project default event. JSON and CSV contain the full component list.</p>
</main>
<script>
const filters = {{
  q: document.getElementById("filterSearch"),
  severity: document.getElementById("filterSeverity"),
  status: document.getElementById("filterStatus"),
  component: document.getElementById("filterComponent"),
  priority: document.getElementById("filterPriority"),
}};
function matches(row) {{
  const q = filters.q.value.trim().toLowerCase();
  if (q && !row.textContent.toLowerCase().includes(q)) return false;
  for (const key of ["severity", "status", "component", "priority"]) {{
    const value = filters[key].value;
    if (value && row.dataset[key] !== value) return false;
  }}
  return true;
}}
function applyFilters() {{
  document.querySelectorAll("table").forEach((table) => {{
    const rows = Array.from(table.querySelectorAll("tbody tr"));
    let visible = 0;
    rows.forEach((row) => {{
      const show = matches(row);
      row.hidden = !show;
      if (show) visible += 1;
    }});
    const meta = table.previousElementSibling;
    if (meta && meta.hasAttribute("data-table-count")) {{
      meta.textContent = `Showing ${{visible}} of ${{rows.length}} loaded rows`;
    }}
  }});
}}
Object.values(filters).forEach((node) => node.addEventListener("input", applyFilters));
applyFilters();
</script>
</body>
</html>
"""


def scan_project(ctx: ScanContext, progress: Callable[[str], None] | None = None) -> dict[str, object]:
    if progress is None:
        progress = lambda _message: None
    start = dt.datetime.now()
    known_events = parse_wwise_events(ctx.wwise_root)
    defaults = parse_default_audio_settings(ctx.unity_root)
    progress(f"Known Wwise Events: {len(known_events)}")
    progress(f"Default UI events: {defaults}")
    guid_to_asset = build_guid_to_asset_map(ctx.unity_root, progress)
    files = iter_scan_files(ctx)
    progress(f"Scan files considered: {len(files)}")

    items: list[dict[str, object]] = []
    state_items: list[dict[str, object]] = []
    overrides: list[dict[str, object]] = []
    stats = Counter()
    component_counts = Counter()
    read_errors: list[dict[str, str]] = []

    for index, path in enumerate(files, start=1):
        if index == 1 or index % 100 == 0 or index == len(files):
            progress(f"Scanning {index}/{len(files)}: {rel_path(path, ctx.unity_root)}")
        try:
            asset_result = scan_unity_asset(path, ctx, known_events, defaults, guid_to_asset)
        except Exception as exc:
            stats["read_errors"] += 1
            read_errors.append({"path": rel_path(path, ctx.unity_root), "error": str(exc)})
            continue
        asset_stats = dict(asset_result["stats"])
        component_counts.update(asset_stats.pop("component_type_counts", {}))
        stats.update(asset_stats)
        asset_items = list(asset_result["items"])
        asset_states = list(asset_result["state_items"])
        asset_overrides = list(asset_result["overrides"])
        items.extend(asset_items)
        state_items.extend(asset_states)
        overrides.extend(asset_overrides)

    all_findings = items + state_items + overrides
    severity_counts = Counter(str(row.get("severity", "Info")) for row in all_findings)
    for key in ["High", "Medium", "Low", "Info", "Pass"]:
        severity_counts.setdefault(key, 0)
    elapsed = (dt.datetime.now() - start).total_seconds()
    source_grade = "B"
    if stats["read_errors"]:
        source_grade = "C"
    if not known_events:
        source_grade = "C"
    summary = {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "elapsed_seconds": round(elapsed, 2),
        "source_grade": source_grade,
        "unity_root": str(ctx.unity_root),
        "wwise_root": str(ctx.wwise_root) if ctx.wwise_root else "",
        "scan_root": str(ctx.scan_root),
        "files_considered": len(files),
        "files_scanned": int(stats["files_scanned"]),
        "files_with_ui_audio": int(stats["files_with_ui_audio"]),
        "skipped_no_hits": int(stats["skipped_no_hits"]),
        "large_file_prefilter_skips": int(stats["large_file_prefilter_skips"]),
        "read_errors": int(stats["read_errors"]),
        "known_wwise_events": len(known_events),
        "component_counts": dict(component_counts),
        "severity_counts": dict(sorted(severity_counts.items(), key=lambda item: SEVERITY_RANK.get(item[0], 99))),
        "item_status_counts": summarize_rows(items),
        "state_status_counts": summarize_rows(state_items),
        "override_status_counts": summarize_rows(overrides),
    }

    return {
        "summary": summary,
        "defaults": defaults,
        "items": sorted(items, key=row_sort_key),
        "state_items": sorted(state_items, key=row_sort_key),
        "overrides": sorted(overrides, key=row_sort_key),
        "read_errors": read_errors,
        "paths": {},
    }


def write_reports(result: dict[str, object], report_dir: Path) -> dict[str, Path]:
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    base = f"ProjectEF_UIAudio_StaticInspector_{stamp}"
    json_path = report_dir / f"{base}.json"
    csv_path = report_dir / f"{base}.csv"
    state_csv_path = report_dir / f"{base}_states.csv"
    override_csv_path = report_dir / f"{base}_overrides.csv"
    md_path = report_dir / f"{base}.md"
    html_path = report_dir / f"{base}.html"
    result["paths"] = {
        "json": str(json_path),
        "csv": str(csv_path),
        "state_csv": str(state_csv_path),
        "override_csv": str(override_csv_path),
        "markdown": str(md_path),
        "html": str(html_path),
    }

    json_path.write_text(json.dumps(result, ensure_ascii=True, indent=2), encoding="utf-8")
    item_fields = [
        "severity",
        "status",
        "priority",
        "component_type",
        "asset_type",
        "asset_path",
        "line",
        "object_path",
        "object_name",
        "pressed_audio",
        "pointer_enter_audio",
        "effective_audio",
        "default_audio",
        "wwise_status",
        "has_pointer_enter_tween",
        "prohibit_audio",
        "duplicate_name_count",
        "companion_components",
        "issues",
        "suggestions",
    ]
    write_csv(csv_path, list(result["items"]), item_fields)
    state_fields = [
        "severity",
        "status",
        "asset_type",
        "asset_path",
        "line",
        "object_path",
        "state_name",
        "enabled",
        "event",
        "effective_event",
        "wwise_status",
        "issues",
    ]
    write_csv(state_csv_path, list(result["state_items"]), state_fields)
    override_fields = [
        "severity",
        "status",
        "asset_path",
        "line",
        "property",
        "value",
        "wwise_status",
        "target_file_id",
        "target_guid",
        "source_asset",
        "issues",
    ]
    write_csv(override_csv_path, list(result["overrides"]), override_fields)
    md_text = render_markdown(result, csv_path.name, json_path.name, html_path.name)
    md_path.write_text(md_text, encoding="utf-8-sig")
    html_text = render_html(result, "ProjectEF UI Audio Static Inspector Report")
    html_path.write_text(html_text, encoding="utf-8-sig")
    return {
        "json": json_path,
        "csv": csv_path,
        "state_csv": state_csv_path,
        "override_csv": override_csv_path,
        "markdown": md_path,
        "html": html_path,
    }


def resolve_scan_root(unity_root: Path, scan_root_arg: str) -> Path:
    scan_root = Path(scan_root_arg)
    if scan_root.is_absolute():
        return scan_root
    return unity_root / scan_root


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only ProjectEF UI audio static inspector.")
    parser.add_argument("--unity-root", default=str(DEFAULT_UNITY_ROOT))
    parser.add_argument("--wwise-project-root", default=str(DEFAULT_WWISE_ROOT))
    parser.add_argument("--scan-root", default=DEFAULT_SCAN_ROOT, help="Absolute path or path relative to Unity root.")
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR))
    parser.add_argument("--no-prefabs", action="store_true")
    parser.add_argument("--no-scenes", action="store_true")
    parser.add_argument("--max-file-mb", type=float, default=64.0)
    parser.add_argument("--open-html", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    unity_root = Path(args.unity_root).resolve()
    wwise_root = Path(args.wwise_project_root).resolve() if args.wwise_project_root else None
    scan_root = resolve_scan_root(unity_root, args.scan_root).resolve()
    report_dir = Path(args.report_dir).resolve()
    if not unity_root.exists():
        print(f"Unity root not found: {unity_root}", file=sys.stderr)
        return 2
    if not (unity_root / "Assets").exists():
        print(f"Unity root does not contain Assets/: {unity_root}", file=sys.stderr)
        return 2
    if not scan_root.exists():
        print(f"Scan root not found: {scan_root}", file=sys.stderr)
        return 2
    ctx = ScanContext(
        unity_root=unity_root,
        wwise_root=wwise_root,
        scan_root=scan_root,
        report_dir=report_dir,
        include_prefabs=not args.no_prefabs,
        include_scenes=not args.no_scenes,
        max_file_mb=args.max_file_mb,
    )
    result = scan_project(ctx, progress=lambda message: print(message, flush=True))
    paths = write_reports(result, report_dir)
    print("REPORT_JSON=" + str(paths["json"]), flush=True)
    print("REPORT_CSV=" + str(paths["csv"]), flush=True)
    print("REPORT_STATE_CSV=" + str(paths["state_csv"]), flush=True)
    print("REPORT_OVERRIDE_CSV=" + str(paths["override_csv"]), flush=True)
    print("REPORT_MD=" + str(paths["markdown"]), flush=True)
    print("REPORT_HTML=" + str(paths["html"]), flush=True)
    if args.open_html:
        try:
            os.startfile(str(paths["html"]))
        except Exception as exc:
            print(f"Could not open HTML report: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
