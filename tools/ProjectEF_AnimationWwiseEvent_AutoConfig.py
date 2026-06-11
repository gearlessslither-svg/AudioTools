#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import uuid
import wave
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable


DEFAULT_UNITY_ROOT = Path(r"D:\EF New\Client\TargetProject")
DEFAULT_WWISE_ROOT = Path(r"D:\EF Wwise\ProjectEF")
REPORT_DIR = Path(__file__).resolve().parents[1] / "\u62a5\u544a"
RECEIVER_RELATIVE_PATH = Path(
    "Assets/GameProject/Scripts/Runtime/GameView/Audio/AnimationWwiseEventReceiver.cs"
)
RECEIVER_GUID = "8e45ad6b91c84730a32488ca6e500d02"
EVENT_FUNCTION = "PlayAnimationWwiseEvent"

RECEIVER_SOURCE = r'''using UnityEngine;
using BlackJack.BJFramework.Runtime;

namespace BlackJack.ProjectEF.Runtime
{
    public sealed class AnimationWwiseEventReceiver : MonoBehaviour
    {
#if USE_WWISE
        private WwiseAudioHelper m_wwiseAudioHelper;
#endif

        public void PlayAnimationWwiseEvent(AnimationEvent animationEvent)
        {
#if USE_WWISE
            string eventName = animationEvent != null ? animationEvent.stringParameter : string.Empty;
            if (string.IsNullOrEmpty(eventName))
            {
                return;
            }

            if (m_wwiseAudioHelper == null)
            {
                m_wwiseAudioHelper = GetComponent<WwiseAudioHelper>();
            }

            if (m_wwiseAudioHelper != null)
            {
                m_wwiseAudioHelper.PlayAudio(
                    eventName,
                    BlackJack.BJFramework.Runtime.AudioType.Sound,
                    callbackAction: null);
                return;
            }

            AkUnitySoundEngine.PostEvent(eventName, gameObject);
#endif
        }
    }
}
'''

RECEIVER_META = f"""fileFormatVersion: 2
guid: {RECEIVER_GUID}
MonoImporter:
  externalObjects: {{}}
  serializedVersion: 2
  defaultReferences: []
  executionOrder: 0
  icon: {{instanceID: 0}}
  userData: 
  assetBundleName: 
  assetBundleVariant: 
"""


class ToolError(RuntimeError):
    pass


@dataclass
class Key:
    t: float
    x: float
    y: float
    z: float
    w: float


@dataclass
class Curve:
    path: str
    keys: list[Key]


@dataclass
class TransformInfo:
    file_id: str
    game_object: str
    father: str
    name: str
    path: str
    pos: tuple[float, float, float]
    rot: tuple[float, float, float, float]
    stripped: bool = False
    source_ref: str | None = None


@dataclass
class AnalysisResult:
    times: list[float]
    mode: str
    metric: str
    threshold: float
    strongest_metric: float
    sample_fps: float
    min_gap: float
    selection_policy: str
    clip_length: float
    endpoint_paths: list[str]
    y_range: tuple[float, float] | None = None


@dataclass
class AudioSourceInfo:
    name: str
    path: str | None
    duration: float | None


@dataclass
class WwiseEventDesign:
    event_name: str
    target_names: list[str]
    target_type: str | None
    audio_sources: list[AudioSourceInfo]
    min_duration: float | None
    max_duration: float | None
    effective_min_gap: float
    audio_aware_spacing_applied: bool
    notes: list[str]


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def write_text_if_changed(path: Path, text: str) -> bool:
    old = path.read_text(encoding="utf-8-sig") if path.exists() else None
    newline = "\r\n" if old and "\r\n" in old else "\n"
    output = text.replace("\r\n", "\n").replace("\n", newline)
    if old == output:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(output, encoding="utf-8", newline="")
    return True


def normalize_path(value: str | Path) -> Path:
    return Path(value).expanduser().resolve()


def guid_from_meta(asset_path: Path) -> str:
    meta_path = asset_path.with_suffix(asset_path.suffix + ".meta")
    if not meta_path.exists():
        raise ToolError(f"Missing meta file: {meta_path}")
    match = re.search(r"^guid:\s*([0-9a-fA-F]{32})\s*$", read_text(meta_path), re.M)
    if not match:
        raise ToolError(f"Cannot read guid from: {meta_path}")
    return match.group(1).lower()


def resolve_asset(root: Path, query: str, suffix: str) -> Path:
    candidate = Path(query)
    if candidate.is_absolute() and candidate.exists():
        return candidate
    if candidate.exists():
        return candidate.resolve()

    asset_root = root / "Assets"
    if not asset_root.exists():
        raise ToolError(f"Unity Assets folder not found: {asset_root}")

    query_name = query.lower()
    matches: list[Path] = []
    for path in asset_root.rglob(f"*{suffix}"):
        if path.name.lower() == query_name or path.stem.lower() == query_name:
            matches.append(path)
    if not matches:
        raise ToolError(f"Could not find {suffix} asset matching: {query}")
    if len(matches) > 1:
        lines = "\n".join(str(p) for p in matches[:20])
        raise ToolError(f"Multiple {suffix} assets match {query}; pass a full path:\n{lines}")
    return matches[0]


def resolve_animation_asset(root: Path, query: str) -> tuple[Path, Path | None]:
    candidate = Path(query)
    if candidate.is_absolute() and candidate.exists():
        if candidate.suffix.lower() == ".anim":
            return candidate, None
        if candidate.suffix.lower() == ".fbx":
            return find_editable_anim_for_source(root, candidate), candidate
        if candidate.is_dir():
            raise ToolError(
                f"Animation query is a folder, not a specific clip. Pass one .fbx/.anim file or animation name: {candidate}"
            )

    if candidate.exists():
        candidate = candidate.resolve()
        if candidate.suffix.lower() == ".anim":
            return candidate, None
        if candidate.suffix.lower() == ".fbx":
            return find_editable_anim_for_source(root, candidate), candidate

    anim_error: ToolError | None = None
    try:
        return resolve_asset(root, query, ".anim"), None
    except ToolError as exc:
        anim_error = exc

    try:
        source_fbx = resolve_asset(root, query, ".fbx")
        return find_editable_anim_for_source(root, source_fbx), source_fbx
    except ToolError as fbx_error:
        raise ToolError(
            f"Could not resolve animation as editable .anim or source .fbx.\n"
            f".anim lookup: {anim_error}\n"
            f".fbx lookup: {fbx_error}"
        ) from fbx_error


def find_editable_anim_for_source(root: Path, source_path: Path) -> Path:
    asset_root = root / "Assets"
    stem = source_path.stem.lower()
    matches = [path for path in asset_root.rglob("*.anim") if path.stem.lower() == stem]
    if not matches:
        raise ToolError(
            f"Found source FBX but no extracted editable .anim with the same name: {source_path}\n"
            "Extract or duplicate the clip to a .anim first, then rerun the tool."
        )

    runtime_matches = [path for path in matches if "runtimeassets" in {part.lower() for part in path.parts}]
    preferred = runtime_matches or matches
    if len(preferred) == 1:
        return preferred[0]

    lines = "\n".join(str(path) for path in preferred[:20])
    raise ToolError(
        f"Multiple editable .anim files match source FBX {source_path.name}; pass a full .anim path:\n{lines}"
    )


def resolve_prefab(unity_root: Path, animation_path: Path, query: str | None) -> Path | None:
    if query:
        return resolve_asset(unity_root, query, ".prefab")

    bundle_root = animation_path.parent.parent
    prefab_dir = bundle_root / "Prefabs"
    if prefab_dir.exists():
        prefabs = sorted(prefab_dir.glob("*.prefab"))
        if len(prefabs) == 1:
            return prefabs[0]

    return None


def validate_wwise_event(wwise_root: Path, event_name: str) -> tuple[bool, str | None]:
    if not wwise_root.exists():
        return False, f"Wwise root not found: {wwise_root}"
    pattern = re.compile(rf'<Event\s+Name="{re.escape(event_name)}"(?=[\s>/])')
    for path in list((wwise_root / "Events").rglob("*.wwu")) if (wwise_root / "Events").exists() else wwise_root.rglob("*.wwu"):
        try:
            if pattern.search(read_text(path)):
                return True, str(path)
        except UnicodeDecodeError:
            continue
    return False, f"Event not found in Wwise .wwu files: {event_name}"


def extract_xml_element(text: str, tag: str, start_index: int) -> str:
    open_index = text.rfind("<", 0, start_index + 1)
    if open_index < 0:
        return text[start_index : start_index + 300000]
    pattern = re.compile(rf"<(/?){re.escape(tag)}(?=[\s>/])[^>]*(/?)>", re.I)
    depth = 0
    for match in pattern.finditer(text, open_index):
        is_close = bool(match.group(1))
        is_self_close = bool(match.group(2)) or match.group(0).endswith("/>")
        if is_close:
            depth -= 1
            if depth <= 0:
                return text[open_index : match.end()]
        elif not is_self_close:
            depth += 1
    return text[open_index : open_index + 300000]


def read_wav_duration(path: Path) -> float | None:
    try:
        with wave.open(str(path), "rb") as wav:
            rate = wav.getframerate()
            if rate <= 0:
                return None
            return wav.getnframes() / rate
    except Exception:
        return None


def locate_original_audio_files(wwise_root: Path, audio_names: Iterable[str]) -> dict[str, Path]:
    originals = wwise_root / "Originals"
    if not originals.exists():
        return {}
    desired = {name.lower(): name for name in audio_names}
    found: dict[str, Path] = {}
    for path in originals.rglob("*.wav"):
        key = path.name.lower()
        if key in desired:
            found[desired[key]] = path
    return found


def analyze_wwise_event_design(
    wwise_root: Path,
    event_name: str,
    requested_min_gap: float,
    audio_aware_spacing: bool,
) -> WwiseEventDesign:
    notes: list[str] = []
    target_names: list[str] = []
    target_type: str | None = None
    target_block = ""

    if not wwise_root.exists():
        notes.append(f"Wwise root not found: {wwise_root}")
        return WwiseEventDesign(event_name, [], None, [], None, None, requested_min_gap, False, notes)

    event_pattern = re.compile(rf'<Event\s+Name="{re.escape(event_name)}"(?=[\s>/]).*?</Event>', re.S)
    event_roots = [wwise_root / "Events"] if (wwise_root / "Events").exists() else [wwise_root]
    for root in event_roots:
        for path in root.rglob("*.wwu"):
            try:
                text = read_text(path)
            except Exception:
                continue
            event_match = event_pattern.search(text)
            if event_match:
                target_names = re.findall(r'<ObjectRef\s+Name="([^"]+)"', event_match.group(0))
                if target_names:
                    notes.append(f"Event targets: {', '.join(target_names)}")
                break
        if target_names:
            break

    for target_name in target_names:
        target_marker = re.compile(rf'<([A-Za-z]+)\s+Name="{re.escape(target_name)}"(?=[\s>/])')
        for path in wwise_root.rglob("*.wwu"):
            try:
                text = read_text(path)
            except Exception:
                continue
            marker_match = target_marker.search(text)
            if marker_match:
                target_type = marker_match.group(1)
                target_block = extract_xml_element(text, target_type, marker_match.start())
                notes.append(f"Target object: {target_type} `{target_name}` in {path}")
                break
        if target_block:
            break

    audio_names = re.findall(r"<AudioFile>([^<]+\.wav)</AudioFile>", target_block, re.I)
    audio_paths = locate_original_audio_files(wwise_root, audio_names)
    audio_sources: list[AudioSourceInfo] = []
    for audio_name in audio_names:
        path = audio_paths.get(audio_name)
        duration = read_wav_duration(path) if path else None
        audio_sources.append(AudioSourceInfo(audio_name, str(path) if path else None, duration))

    durations = [source.duration for source in audio_sources if source.duration is not None]
    min_duration = min(durations) if durations else None
    max_duration = max(durations) if durations else None

    properties = {
        match.group(1): match.group(2)
        for match in re.finditer(r'<Property\s+Name="([^"]+)"[^>]*\sValue="([^"]*)"', target_block)
    }
    is_looping = properties.get("PlayMechanismLoop", "False").lower() == "true"
    looks_like_random_one_shot = (
        target_type == "RandomSequenceContainer"
        and bool(audio_sources)
        and not is_looping
    )

    effective_min_gap = requested_min_gap
    spacing_applied = False
    if audio_aware_spacing and looks_like_random_one_shot and max_duration:
        effective_min_gap = max(requested_min_gap, max_duration)
        spacing_applied = effective_min_gap > requested_min_gap
        notes.append(
            "Audio-aware spacing applied: RandomSequenceContainer one-shot sources should not retrigger faster than longest source duration."
        )
    elif audio_aware_spacing and target_type:
        notes.append("Audio-aware spacing inspected but did not override min gap.")

    if audio_sources:
        notes.append(
            f"Audio sources: {len(audio_sources)}, duration range: "
            f"{min_duration:.3f}s - {max_duration:.3f}s" if min_duration is not None and max_duration is not None else
            f"Audio sources: {len(audio_sources)}, duration unavailable"
        )

    return WwiseEventDesign(
        event_name=event_name,
        target_names=target_names,
        target_type=target_type,
        audio_sources=audio_sources,
        min_duration=min_duration,
        max_duration=max_duration,
        effective_min_gap=effective_min_gap,
        audio_aware_spacing_applied=spacing_applied,
        notes=notes,
    )


def parse_float_vec3(text: str) -> tuple[float, float, float]:
    match = re.search(r"\{x:\s*([^,]+), y:\s*([^,]+), z:\s*([^,}]+)\}", text)
    if not match:
        return (0.0, 0.0, 0.0)
    return (float(match.group(1)), float(match.group(2)), float(match.group(3)))


def parse_float_quat(text: str) -> tuple[float, float, float, float]:
    match = re.search(r"\{x:\s*([^,]+), y:\s*([^,]+), z:\s*([^,]+), w:\s*([^,}]+)\}", text)
    if not match:
        return (0.0, 0.0, 0.0, 1.0)
    return (
        float(match.group(1)),
        float(match.group(2)),
        float(match.group(3)),
        float(match.group(4)),
    )


def parse_animation_clip(path: Path) -> tuple[str, float, list[Curve]]:
    text = read_text(path)
    stop_match = re.search(r"^\s+m_StopTime:\s*([0-9.eE+-]+)\s*$", text, re.M)
    clip_length = float(stop_match.group(1)) if stop_match else 0.0

    start = text.find("  m_RotationCurves:")
    end = text.find("  m_EulerCurves:", start)
    if start < 0 or end < 0:
        raise ToolError(f"Cannot find rotation curves in animation: {path}")

    curves: list[Curve] = []
    rotation_text = text[start:end]
    for raw in re.split(r"\n  - curve:\n", rotation_text)[1:]:
        block = "  - curve:\n" + raw
        path_value = parse_curve_path(block)
        keys = [
            Key(
                t=float(match.group(1)),
                x=float(match.group(2)),
                y=float(match.group(3)),
                z=float(match.group(4)),
                w=float(match.group(5)),
            )
            for match in re.finditer(
                r"\n      - serializedVersion: 3\n"
                r"\s*time:\s*([0-9.eE+-]+)\n"
                r"\s*value:\s*\{x:\s*([^,]+), y:\s*([^,]+), z:\s*([^,]+), w:\s*([^,}]+)\}",
                block,
            )
        ]
        if keys:
            curves.append(Curve(path_value, keys))
            clip_length = max(clip_length, keys[-1].t)

    if not curves:
        raise ToolError(f"No usable rotation curves found in animation: {path}")
    return text, clip_length, curves


def parse_curve_path(block: str) -> str:
    marker = "\n    path: "
    idx = block.find(marker)
    if idx < 0:
        return ""
    lines = block[idx + len(marker) :].splitlines()
    value = lines[0].strip()
    for line in lines[1:]:
        if re.match(r"^      \S", line) and not re.match(r"^      (m_|- )", line):
            value += " " + line.strip()
        else:
            break
    return value


def split_yaml_documents(text: str) -> list[str]:
    docs = re.split(r"\n(?=--- !u!)", text)
    return [doc for doc in docs if doc.startswith("--- !u!")]


def parse_prefab_transforms(prefab_path: Path, animation_root_names: Iterable[str]) -> tuple[dict[str, TransformInfo], str]:
    text = read_text(prefab_path)
    game_object_names: dict[str, str] = {}
    stripped_game_objects: dict[str, str | None] = {}
    transforms_raw: dict[str, dict[str, object]] = {}

    for doc in split_yaml_documents(text):
        header = re.match(r"--- !u!(\d+) &(-?\d+)( stripped)?", doc)
        if not header:
            continue
        type_id, file_id, stripped = header.group(1), header.group(2), bool(header.group(3))
        if type_id == "1":
            name_match = re.search(r"\n  m_Name:\s*(.*)", doc)
            if name_match:
                game_object_names[file_id] = name_match.group(1).strip()
            if stripped:
                stripped_game_objects[file_id] = parse_corresponding_source_ref(doc)
        elif type_id == "4":
            go = re.search(r"\n  m_GameObject:\s*\{fileID:\s*(-?\d+)\}", doc)
            father = re.search(r"\n  m_Father:\s*\{fileID:\s*(-?\d+)\}", doc)
            pos = re.search(r"\n  m_LocalPosition:\s*(\{[^\n]+\})", doc)
            rot = re.search(r"\n  m_LocalRotation:\s*(\{[^\n]+\})", doc)
            if go:
                transforms_raw[file_id] = {
                    "go": go.group(1),
                    "father": father.group(1) if father else "0",
                    "pos": parse_float_vec3(pos.group(1)) if pos else (0.0, 0.0, 0.0),
                    "rot": parse_float_quat(rot.group(1)) if rot else (0.0, 0.0, 0.0, 1.0),
                }

    def build_path(transform_id: str) -> str:
        names: list[str] = []
        seen: set[str] = set()
        current = transform_id
        while current in transforms_raw and current not in seen:
            seen.add(current)
            go_id = str(transforms_raw[current]["go"])
            names.append(game_object_names.get(go_id, "?"))
            current = str(transforms_raw[current]["father"])
        return "/".join(reversed(names))

    roots = list(animation_root_names)
    transforms: dict[str, TransformInfo] = {}
    for file_id, raw in transforms_raw.items():
        full_path = build_path(file_id)
        asset_path = strip_to_animation_root(full_path, roots)
        go_id = str(raw["go"])
        if not asset_path:
            continue
        transforms[asset_path] = TransformInfo(
            file_id=file_id,
            game_object=go_id,
            father=str(raw["father"]),
            name=game_object_names.get(go_id, "?"),
            path=asset_path,
            pos=raw["pos"],  # type: ignore[arg-type]
            rot=raw["rot"],  # type: ignore[arg-type]
            stripped=go_id in stripped_game_objects,
            source_ref=stripped_game_objects.get(go_id),
        )

    if not transforms:
        raise ToolError(f"Could not map prefab transform paths to animation paths: {prefab_path}")
    return transforms, text


def strip_to_animation_root(full_path: str, roots: list[str]) -> str:
    parts = full_path.split("/")
    for i, part in enumerate(parts):
        if part in roots:
            return "/".join(parts[i:])
    return ""


def parse_corresponding_source_ref(doc: str) -> str | None:
    match = re.search(
        r"m_CorrespondingSourceObject:\s*\{fileID:\s*(-?\d+), guid:\s*([0-9a-fA-F]{32}), type:\s*(\d+)\}",
        doc,
    )
    if not match:
        return None
    return f"{{fileID: {match.group(1)}, guid: {match.group(2)}, type: {match.group(3)}}}"


def q_norm(q: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    n = math.sqrt(sum(v * v for v in q)) or 1.0
    return (q[0] / n, q[1] / n, q[2] / n, q[3] / n)


def q_dot(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2] + a[3] * b[3]


def q_slerp(a: tuple[float, float, float, float], b: tuple[float, float, float, float], u: float) -> tuple[float, float, float, float]:
    a = q_norm(a)
    b = q_norm(b)
    dot = q_dot(a, b)
    if dot < 0.0:
        b = (-b[0], -b[1], -b[2], -b[3])
        dot = -dot
    if dot > 0.9995:
        return q_norm(tuple(a[i] + (b[i] - a[i]) * u for i in range(4)))  # type: ignore[return-value]
    theta = math.acos(max(-1.0, min(1.0, dot)))
    sin_theta = math.sin(theta)
    s0 = math.sin((1.0 - u) * theta) / sin_theta
    s1 = math.sin(u * theta) / sin_theta
    return tuple(a[i] * s0 + b[i] * s1 for i in range(4))  # type: ignore[return-value]


def q_mul(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    )


def q_rotate(q: tuple[float, float, float, float], v: tuple[float, float, float]) -> tuple[float, float, float]:
    p = (v[0], v[1], v[2], 0.0)
    qi = (-q[0], -q[1], -q[2], q[3])
    r = q_mul(q_mul(q, p), qi)
    return (r[0], r[1], r[2])


def v_add(a: tuple[float, float, float], b: tuple[float, float, float]) -> tuple[float, float, float]:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def rot_at(curve: Curve | None, t: float) -> tuple[float, float, float, float] | None:
    if not curve or not curve.keys:
        return None
    keys = curve.keys
    if t <= keys[0].t:
        return (keys[0].x, keys[0].y, keys[0].z, keys[0].w)
    if t >= keys[-1].t:
        return (keys[-1].x, keys[-1].y, keys[-1].z, keys[-1].w)
    lo, hi = 0, len(keys) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if keys[mid].t < t:
            lo = mid
        else:
            hi = mid
    a, b = keys[lo], keys[hi]
    u = (t - a.t) / (b.t - a.t)
    return q_slerp((a.x, a.y, a.z, a.w), (b.x, b.y, b.z, b.w), u)


def is_leaf(path: str, paths: set[str]) -> bool:
    prefix = path + "/"
    return not any(other.startswith(prefix) for other in paths)


def choose_endpoint_paths(transforms: dict[str, TransformInfo], include_regex: str) -> list[str]:
    paths = set(transforms)
    leaf_paths = [path for path in paths if is_leaf(path, paths)]
    preferred = [path for path in leaf_paths if re.search(include_regex, path, re.I)]
    if preferred:
        return sorted(preferred)
    fallback = [path for path in leaf_paths if re.search(r"hand|foot|tail|head", path, re.I)]
    return sorted(fallback or leaf_paths)[:24]


def world_pos_at(
    path: str,
    t: float,
    transforms: dict[str, TransformInfo],
    curves: dict[str, Curve],
) -> tuple[float, float, float]:
    parts = path.split("/")
    current_path = ""
    pos = (0.0, 0.0, 0.0)
    rot = (0.0, 0.0, 0.0, 1.0)
    for idx, part in enumerate(parts):
        current_path = part if idx == 0 else current_path + "/" + part
        transform = transforms.get(current_path)
        if not transform:
            raise ToolError(f"Missing transform path in prefab: {current_path}")
        pos = v_add(pos, q_rotate(rot, transform.pos))
        local_rot = rot_at(curves.get(current_path), t) or transform.rot
        rot = q_norm(q_mul(rot, local_rot))
    return pos


def analyze_with_prefab(
    clip_length: float,
    curves: list[Curve],
    transforms: dict[str, TransformInfo],
    include_regex: str,
    mode: str,
    sample_fps: float,
    strength_ratio: float,
    min_gap: float,
    selection_policy: str = "strongest",
) -> AnalysisResult:
    endpoint_paths = choose_endpoint_paths(transforms, include_regex)
    if not endpoint_paths:
        raise ToolError("No endpoint paths found for motion analysis.")

    curve_map = {curve.path: curve for curve in curves}
    dt = 1.0 / sample_fps
    sample_count = int(round(clip_length / dt)) + 1
    samples: list[dict[str, float]] = []
    for index in range(sample_count):
        t = min(clip_length, index * dt)
        ys = [world_pos_at(endpoint, t, transforms, curve_map)[1] for endpoint in endpoint_paths]
        samples.append({"t": t, "y": sum(ys) / len(ys)})

    for index in range(1, len(samples) - 1):
        samples[index]["v"] = (samples[index + 1]["y"] - samples[index - 1]["y"]) / (2.0 * dt)
    if len(samples) > 2:
        samples[0]["v"] = samples[1]["v"]
        samples[-1]["v"] = samples[-2]["v"]

    velocities = [sample.get("v", 0.0) for sample in samples]
    y_values = [sample["y"] for sample in samples]
    if mode == "downstroke":
        strongest = abs(min(velocities))
        threshold = strongest * strength_ratio
        candidates = [
            {"t": samples[i]["t"], "metric": -samples[i]["v"]}
            for i in range(2, len(samples) - 2)
            if samples[i]["v"] < samples[i - 1]["v"]
            and samples[i]["v"] <= samples[i + 1]["v"]
            and -samples[i]["v"] >= threshold
        ]
        metric = "negative_y_velocity"
    else:
        speed = [abs(v) for v in velocities]
        strongest = max(speed)
        threshold = strongest * strength_ratio
        candidates = [
            {"t": samples[i]["t"], "metric": speed[i]}
            for i in range(2, len(samples) - 2)
            if speed[i] > speed[i - 1] and speed[i] >= speed[i + 1] and speed[i] >= threshold
        ]
        metric = "abs_y_velocity"

    times = cluster_candidate_times(candidates, min_gap, clip_length, selection_policy)
    return AnalysisResult(
        times=times,
        mode=mode,
        metric=metric,
        threshold=threshold,
        strongest_metric=strongest,
        sample_fps=sample_fps,
        min_gap=min_gap,
        selection_policy=selection_policy,
        clip_length=clip_length,
        endpoint_paths=endpoint_paths,
        y_range=(min(y_values), max(y_values)),
    )


def analyze_rotation_speed(
    clip_length: float,
    curves: list[Curve],
    sample_fps: float,
    strength_ratio: float,
    min_gap: float,
    selection_policy: str = "strongest",
) -> AnalysisResult:
    moving = [curve for curve in curves if len(curve.keys) > 8]
    if not moving:
        raise ToolError("No moving rotation curves found.")
    moving = sorted(moving, key=lambda curve: len(curve.keys), reverse=True)[:12]
    dt = 1.0 / sample_fps
    samples: list[dict[str, float]] = []
    for index in range(1, int(round(clip_length / dt))):
        t = min(clip_length - dt, index * dt)
        total = 0.0
        for curve in moving:
            a = rot_at(curve, max(0.0, t - dt))
            b = rot_at(curve, min(clip_length, t + dt))
            if a and b:
                dot = abs(q_dot(q_norm(a), q_norm(b)))
                total += math.acos(max(-1.0, min(1.0, dot))) / (2.0 * dt)
        samples.append({"t": t, "speed": total / len(moving)})
    strongest = max(sample["speed"] for sample in samples)
    threshold = strongest * strength_ratio
    candidates = [
        {"t": samples[i]["t"], "metric": samples[i]["speed"]}
        for i in range(2, len(samples) - 2)
        if samples[i]["speed"] > samples[i - 1]["speed"]
        and samples[i]["speed"] >= samples[i + 1]["speed"]
        and samples[i]["speed"] >= threshold
    ]
    return AnalysisResult(
        times=cluster_candidate_times(candidates, min_gap, clip_length, selection_policy),
        mode="speed",
        metric="rotation_speed",
        threshold=threshold,
        strongest_metric=strongest,
        sample_fps=sample_fps,
        min_gap=min_gap,
        selection_policy=selection_policy,
        clip_length=clip_length,
        endpoint_paths=[curve.path for curve in moving],
    )


def cluster_candidate_times(
    candidates: list[dict[str, float]],
    min_gap: float,
    clip_length: float,
    selection_policy: str = "strongest",
) -> list[float]:
    selected: list[dict[str, float]] = []
    if selection_policy == "first_after_gap":
        for candidate in candidates:
            if not selected or candidate["t"] - selected[-1]["t"] > min_gap:
                selected.append(candidate)

        if len(selected) > 1 and selected[0]["t"] + clip_length - selected[-1]["t"] < min_gap:
            selected.pop()
        return [round(item["t"], 6) for item in selected]

    for candidate in candidates:
        if not selected or candidate["t"] - selected[-1]["t"] > min_gap:
            selected.append(candidate)
        elif candidate["metric"] > selected[-1]["metric"]:
            selected[-1] = candidate

    if len(selected) > 1 and selected[0]["t"] + clip_length - selected[-1]["t"] < min_gap:
        if selected[0]["metric"] >= selected[-1]["metric"]:
            selected.pop()
        else:
            selected.pop(0)
    return [round(item["t"], 6) for item in selected]


def parse_event_blocks(lines: list[str], start: int, end: int) -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in lines[start + 1 : end]:
        if line.startswith("  - time:"):
            if current:
                blocks.append(current)
            current = [line]
        elif current:
            current.append(line)
    if current:
        blocks.append(current)
    return blocks


def find_events_section(lines: list[str]) -> tuple[int, int]:
    start = next((i for i, line in enumerate(lines) if line.startswith("  m_Events:")), -1)
    if start < 0:
        raise ToolError("Animation clip has no m_Events section.")
    if lines[start].strip() == "m_Events: []":
        return start, start + 1
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("--- !u!") or (lines[i].startswith("  m_") and not lines[i].startswith("  m_Events")):
            end = i
            break
    return start, end


def event_block_time(block: list[str]) -> float:
    match = re.match(r"\s*-\s*time:\s*([0-9.eE+-]+)", block[0])
    return float(match.group(1)) if match else 0.0


def event_block_is_target(block: list[str], event_name: str) -> bool:
    text = "\n".join(block)
    return f"functionName: {EVENT_FUNCTION}" in text and f"data: {event_name}" in text


def render_event_block(time_value: float, event_name: str) -> list[str]:
    return [
        f"  - time: {time_value:.6f}".rstrip("0").rstrip("."),
        f"    functionName: {EVENT_FUNCTION}",
        f"    data: {event_name}",
        "    objectReferenceParameter: {fileID: 0}",
        "    floatParameter: 0",
        "    intParameter: 0",
        "    messageOptions: 0",
    ]


def update_animation_events(animation_text: str, event_name: str, times: list[float]) -> tuple[str, int, int]:
    lines = animation_text.splitlines()
    start, end = find_events_section(lines)
    existing = parse_event_blocks(lines, start, end)
    preserved = [block for block in existing if not event_block_is_target(block, event_name)]
    generated = [render_event_block(time_value, event_name) for time_value in times]
    combined = sorted(preserved + generated, key=event_block_time)
    replacement = ["  m_Events:"]
    for block in combined:
        replacement.extend(block)
    new_lines = lines[:start] + replacement + lines[end:]
    return "\n".join(new_lines) + "\n", len(generated), len(existing) - len(preserved)


def ensure_receiver_script(unity_root: Path, apply: bool) -> tuple[Path, bool]:
    script_path = unity_root / RECEIVER_RELATIVE_PATH
    meta_path = script_path.with_suffix(script_path.suffix + ".meta")
    changed = False
    if apply:
        changed |= write_text_if_changed(script_path, RECEIVER_SOURCE)
        changed |= write_text_if_changed(meta_path, RECEIVER_META)
    else:
        changed = not script_path.exists() or not meta_path.exists()
    return script_path, changed


def find_script_guid(unity_root: Path, script_name: str) -> str | None:
    for meta_path in (unity_root / "Assets").rglob(f"{script_name}.cs.meta"):
        match = re.search(r"^guid:\s*([0-9a-fA-F]{32})\s*$", read_text(meta_path), re.M)
        if match:
            return match.group(1).lower()
    return None


def find_mono_behaviour_game_object(prefab_text: str, script_guid: str) -> str | None:
    for doc in split_yaml_documents(prefab_text):
        if f"guid: {script_guid}" not in doc:
            continue
        match = re.search(r"\n  m_GameObject:\s*\{fileID:\s*(-?\d+)\}", doc)
        if match:
            return match.group(1)
    return None


def find_game_object_doc(prefab_text: str, game_object_id: str) -> str | None:
    for doc in split_yaml_documents(prefab_text):
        if re.match(rf"--- !u!1 &{re.escape(game_object_id)}(?: stripped)?", doc):
            return doc
    return None


def make_file_id(existing_text: str) -> str:
    while True:
        value = str(uuid.uuid4().int % 9000000000000000000 + 100000000000000000)
        if f"&{value}" not in existing_text and f"fileID: {value}" not in existing_text:
            return value


def ensure_receiver_component(prefab_path: Path, unity_root: Path, apply: bool) -> tuple[bool, str]:
    text = read_text(prefab_path)
    if f"guid: {RECEIVER_GUID}" in text:
        return False, "receiver already present"

    helper_guid = find_script_guid(unity_root, "WwiseAudioHelper")
    target_go = find_mono_behaviour_game_object(text, helper_guid) if helper_guid else None
    if not target_go:
        raise ToolError(
            "Could not find WwiseAudioHelper on prefab. Add --prefab for the right asset or add the receiver manually."
        )

    new_id = make_file_id(text)
    game_object_doc = find_game_object_doc(text, target_go)
    if not game_object_doc:
        raise ToolError(f"Could not find target GameObject in prefab: fileID {target_go}")

    mono = (
        f"--- !u!114 &{new_id}\n"
        "MonoBehaviour:\n"
        "  m_ObjectHideFlags: 0\n"
        "  m_CorrespondingSourceObject: {fileID: 0}\n"
        "  m_PrefabInstance: {fileID: 0}\n"
        "  m_PrefabAsset: {fileID: 0}\n"
        f"  m_GameObject: {{fileID: {target_go}}}\n"
        "  m_Enabled: 1\n"
        "  m_EditorHideFlags: 0\n"
        f"  m_Script: {{fileID: 11500000, guid: {RECEIVER_GUID}, type: 3}}\n"
        "  m_Name: \n"
        "  m_EditorClassIdentifier: \n"
    )

    if "stripped" in game_object_doc.splitlines()[0]:
        source_ref = parse_corresponding_source_ref(game_object_doc)
        if not source_ref:
            raise ToolError("Target stripped GameObject has no source prefab reference.")
        insert = (
            f"    - targetCorrespondingSourceObject: {source_ref}\n"
            "      insertIndex: -1\n"
            f"      addedObject: {{fileID: {new_id}}}\n"
        )
        marker = "  m_SourcePrefab:"
        marker_index = text.find(marker)
        if marker_index < 0 or "    m_AddedComponents:" not in text[:marker_index]:
            raise ToolError("Could not find PrefabInstance m_AddedComponents block.")
        new_text = text[:marker_index] + insert + text[marker_index:]
    else:
        component_line = f"  - component: {{fileID: {new_id}}}\n"
        doc_start = text.find(game_object_doc)
        doc_end = doc_start + len(game_object_doc)
        component_marker = "  m_Component:\n"
        component_index = text.find(component_marker, doc_start, doc_end)
        layer_index = text.find("  m_Layer:", doc_start, doc_end)
        if component_index < 0 or layer_index < 0:
            raise ToolError("Could not find GameObject component list.")
        new_text = text[:layer_index] + component_line + text[layer_index:]

    new_text = new_text.rstrip() + "\n" + mono
    if apply:
        write_text_if_changed(prefab_path, new_text)
    return True, f"receiver added to GameObject fileID {target_go}"


def build_report(
    animation_path: Path,
    prefab_path: Path | None,
    event_name: str,
    wwise_validation: tuple[bool, str | None],
    wwise_design: WwiseEventDesign,
    analysis: AnalysisResult,
    changed_files: list[str],
    apply: bool,
) -> dict[str, object]:
    return {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "applied": apply,
        "animation": str(animation_path),
        "prefab": str(prefab_path) if prefab_path else None,
        "wwise_event": event_name,
        "wwise_event_valid": wwise_validation[0],
        "wwise_event_evidence": wwise_validation[1],
        "wwise_design": {
            "target_names": wwise_design.target_names,
            "target_type": wwise_design.target_type,
            "audio_source_count": len(wwise_design.audio_sources),
            "audio_sources": [
                {
                    "name": source.name,
                    "path": source.path,
                    "duration": source.duration,
                }
                for source in wwise_design.audio_sources
            ],
            "min_duration": wwise_design.min_duration,
            "max_duration": wwise_design.max_duration,
            "effective_min_gap": wwise_design.effective_min_gap,
            "audio_aware_spacing_applied": wwise_design.audio_aware_spacing_applied,
            "notes": wwise_design.notes,
        },
        "analysis": {
            "mode": analysis.mode,
            "metric": analysis.metric,
            "threshold": analysis.threshold,
            "strongest_metric": analysis.strongest_metric,
            "sample_fps": analysis.sample_fps,
            "min_gap": analysis.min_gap,
            "selection_policy": analysis.selection_policy,
            "clip_length": analysis.clip_length,
            "event_count": len(analysis.times),
            "event_times": analysis.times,
            "endpoint_count": len(analysis.endpoint_paths),
            "endpoint_paths": analysis.endpoint_paths,
            "y_range": analysis.y_range,
        },
        "changed_files": changed_files,
    }


def write_report(report: dict[str, object], event_name: str) -> tuple[Path, Path]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    safe_event = re.sub(r"[^A-Za-z0-9_.-]+", "_", event_name)
    json_path = REPORT_DIR / f"ProjectEF_AnimationWwiseEvent_AutoConfig_{safe_event}_{stamp}.json"
    md_path = json_path.with_suffix(".md")
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    analysis = report["analysis"]  # type: ignore[index]
    md = [
        "# ProjectEF Animation Wwise Event AutoConfig",
        "",
        f"- Applied: {report['applied']}",
        f"- Animation: `{report['animation']}`",
        f"- Prefab: `{report['prefab']}`",
        f"- Wwise Event: `{report['wwise_event']}`",
        f"- Wwise Event Valid: {report['wwise_event_valid']} ({report['wwise_event_evidence']})",
        f"- Wwise Target: {report['wwise_design']['target_type']} / {', '.join(report['wwise_design']['target_names'])}",  # type: ignore[index]
        f"- Audio Sources: {report['wwise_design']['audio_source_count']}",  # type: ignore[index]
        f"- Audio Duration Range: {report['wwise_design']['min_duration']}s - {report['wwise_design']['max_duration']}s",  # type: ignore[index]
        f"- Effective Min Gap: {report['wwise_design']['effective_min_gap']}s",  # type: ignore[index]
        f"- Mode: {analysis['mode']} / {analysis['metric']}",  # type: ignore[index]
        f"- Event Count: {analysis['event_count']}",  # type: ignore[index]
        f"- Changed Files: {len(report['changed_files'])}",  # type: ignore[arg-type]
        "",
        "## Event Times",
        "",
        ", ".join(f"{time:.3f}" for time in analysis["event_times"]),  # type: ignore[index]
        "",
        "## Wwise Design Notes",
        "",
    ]
    md.extend(f"- {note}" for note in report["wwise_design"]["notes"])  # type: ignore[index]
    md.extend([
        "",
        "## Endpoint Paths",
        "",
    ])
    md.extend(f"- `{path}`" for path in analysis["endpoint_paths"])  # type: ignore[index]
    md_path.write_text("\n".join(md) + "\n", encoding="utf-8")
    return md_path, json_path


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze Unity animation motion and write Wwise Animation Events.")
    parser.add_argument("--unity-root", default=str(DEFAULT_UNITY_ROOT))
    parser.add_argument("--wwise-root", default=str(DEFAULT_WWISE_ROOT))
    parser.add_argument("--animation", required=True, help="AnimationClip .anim/.fbx path, file name, or stem.")
    parser.add_argument("--wwise-event", required=True, help="Wwise Event name to post from Animation Events.")
    parser.add_argument("--prefab", help="Prefab path, file name, or stem. Defaults to sibling Prefabs/*.prefab.")
    parser.add_argument("--mode", choices=["downstroke", "speed"], default="downstroke")
    parser.add_argument("--endpoint-regex", default=r"wing|hand")
    parser.add_argument("--sample-fps", type=float, default=60.0)
    parser.add_argument("--strength-ratio", type=float, default=0.30)
    parser.add_argument("--min-gap", type=float, default=0.28)
    parser.add_argument(
        "--disable-audio-aware-spacing",
        action="store_true",
        help="Do not raise min gap based on Wwise target audio durations.",
    )
    parser.add_argument("--apply", action="store_true", help="Write Unity assets. Without this, only reports planned changes.")
    parser.add_argument("--skip-prefab-component", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    unity_root = normalize_path(args.unity_root)
    wwise_root = normalize_path(args.wwise_root)
    animation_path, source_animation_path = resolve_animation_asset(unity_root, args.animation)
    prefab_path = resolve_prefab(unity_root, animation_path, args.prefab)

    animation_text, clip_length, curves = parse_animation_clip(animation_path)
    root_names = {curve.path.split("/")[0] for curve in curves if curve.path}
    wwise_validation = validate_wwise_event(wwise_root, args.wwise_event)
    wwise_design = analyze_wwise_event_design(
        wwise_root,
        args.wwise_event,
        args.min_gap,
        not args.disable_audio_aware_spacing,
    )
    effective_min_gap = wwise_design.effective_min_gap
    selection_policy = "first_after_gap" if wwise_design.audio_aware_spacing_applied else "strongest"

    if prefab_path:
        transforms, _prefab_text = parse_prefab_transforms(prefab_path, root_names)
        analysis = analyze_with_prefab(
            clip_length,
            curves,
            transforms,
            args.endpoint_regex,
            args.mode,
            args.sample_fps,
            args.strength_ratio,
            effective_min_gap,
            selection_policy,
        )
    else:
        analysis = analyze_rotation_speed(
            clip_length,
            curves,
            args.sample_fps,
            args.strength_ratio,
            effective_min_gap,
            selection_policy,
        )

    if not analysis.times:
        raise ToolError("No event times selected. Try lowering --strength-ratio or --min-gap.")

    changed_files: list[str] = []

    new_animation_text, generated_count, replaced_count = update_animation_events(
        animation_text,
        args.wwise_event,
        analysis.times,
    )
    if args.apply and new_animation_text != animation_text:
        write_text_if_changed(animation_path, new_animation_text)
        changed_files.append(str(animation_path))
    elif new_animation_text != animation_text:
        changed_files.append(str(animation_path) + " (planned)")

    receiver_path, receiver_changed = ensure_receiver_script(unity_root, args.apply)
    if receiver_changed:
        changed_files.append(str(receiver_path) + ("" if args.apply else " (planned)"))
        changed_files.append(str(receiver_path.with_suffix(receiver_path.suffix + ".meta")) + ("" if args.apply else " (planned)"))

    prefab_message = "no prefab component requested"
    if prefab_path and not args.skip_prefab_component:
        prefab_changed, prefab_message = ensure_receiver_component(prefab_path, unity_root, args.apply)
        if prefab_changed:
            changed_files.append(str(prefab_path) + ("" if args.apply else " (planned)"))

    report = build_report(
        animation_path,
        prefab_path,
        args.wwise_event,
        wwise_validation,
        wwise_design,
        analysis,
        changed_files,
        args.apply,
    )
    if source_animation_path:
        report["source_animation"] = str(source_animation_path)
    md_path, json_path = write_report(report, args.wwise_event)

    print(f"Animation: {animation_path}")
    if source_animation_path:
        print(f"Source animation: {source_animation_path}")
    print(f"Prefab: {prefab_path or 'None'}")
    print(f"Wwise Event: {args.wwise_event}")
    print(f"Wwise validation: {wwise_validation[0]} - {wwise_validation[1]}")
    print(f"Wwise target: {wwise_design.target_type or 'Unknown'} - {', '.join(wwise_design.target_names) or 'None'}")
    print(f"Audio sources: {len(wwise_design.audio_sources)}")
    if wwise_design.min_duration is not None and wwise_design.max_duration is not None:
        print(f"Audio duration range: {wwise_design.min_duration:.3f}s - {wwise_design.max_duration:.3f}s")
    print(
        f"Effective min gap: {wwise_design.effective_min_gap:.3f}s "
        f"(requested {args.min_gap:.3f}s, audio-aware {not args.disable_audio_aware_spacing})"
    )
    print(f"Mode: {analysis.mode}, metric: {analysis.metric}")
    print(f"Selection policy: {analysis.selection_policy}")
    print(f"Generated events: {generated_count}, replaced old target events: {replaced_count}")
    print(f"Event count: {len(analysis.times)}")
    print("Event times:")
    print(", ".join(f"{time:.3f}" for time in analysis.times))
    print(f"Receiver: {receiver_path}")
    print(f"Prefab receiver: {prefab_message}")
    print(f"Applied: {args.apply}")
    print(f"Report: {md_path}")
    print(f"JSON: {json_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except ToolError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
