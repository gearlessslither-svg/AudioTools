#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import itertools
import json
import math
import time
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_PROJECT_ROOT = Path(r"D:\EF Wwise\ProjectEF")
DEFAULT_WAAPI_URL = "ws://127.0.0.1:8080/waapi"
WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT_DIR = WORKSPACE_ROOT / "Reports"

NON_OBJECT_TAGS = {
    "ActiveSource",
    "ActiveSourceList",
    "AudioFile",
    "BlendTrack",
    "BlendTrackAssoc",
    "BlendTrackAssocList",
    "ChildrenList",
    "CrossfadingInfo",
    "Curve",
    "Custom",
    "GameParameterRef",
    "Grouping",
    "GroupingBehavior",
    "GroupingBehaviorList",
    "GroupingInfo",
    "GroupingList",
    "ItemList",
    "ItemRef",
    "Local",
    "MediaID",
    "MediaIDList",
    "ObjectList",
    "ObjectLists",
    "ObjectRef",
    "PluginLib",
    "Point",
    "PointList",
    "Property",
    "PropertyList",
    "Reference",
    "ReferenceList",
    "RTPC",
    "StateRef",
    "SwitchRef",
    "Value",
    "ValueList",
}

WAAPI_RETURN = [
    "id",
    "name",
    "type",
    "path",
    "parent",
    "childrenCount",
    "@ActionType",
    "@Target",
    "@OutputBus",
    "@OverrideOutput",
    "@Attenuation",
    "@OverridePositioning",
    "@SwitchGroupOrStateGroup",
    "@DefaultSwitchOrState",
    "@Volume",
    "@MakeUpGain",
    "@InitialValue",
    "@Min",
    "@Max",
]

PLAYABLE_TARGET_TYPES = {
    "ActorMixer",
    "BlendContainer",
    "RandomSequenceContainer",
    "SequenceContainer",
    "Sound",
    "SwitchContainer",
}


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def normalize_wwise_path(path: str) -> str:
    text = (path or "").strip().replace("/", "\\")
    if not text:
        return ""
    if not text.startswith("\\"):
        text = "\\" + text
    while "\\\\" in text:
        text = text.replace("\\\\", "\\")
    return text.rstrip("\\")


def is_skipped_path(path: Path) -> bool:
    parts = {part.lower() for part in path.parts}
    return bool(parts & {".backup", ".cache", "backup", "cache"})


def safe_ref_id(ref: Any) -> str:
    if isinstance(ref, dict):
        return str(ref.get("id") or ref.get("ID") or "")
    if isinstance(ref, str):
        return ref
    return ""


def number_or_none(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def interp(points: list[tuple[float, float]], x: float) -> float | None:
    if not points:
        return None
    ordered = sorted(points)
    if x <= ordered[0][0]:
        return ordered[0][1]
    if x >= ordered[-1][0]:
        return ordered[-1][1]
    for left, right in zip(ordered, ordered[1:]):
        lx, ly = left
        rx, ry = right
        if lx <= x <= rx:
            if math.isclose(lx, rx):
                return ry
            t = (x - lx) / (rx - lx)
            return ly + (ry - ly) * t
    return None


@dataclass
class RefInfo:
    reference: str
    name: str
    id: str


@dataclass
class RtpcCurve:
    owner_id: str
    owner_name: str
    owner_type: str
    scope: str
    property_name: str
    control_name: str
    control_id: str
    points: list[tuple[float, float]]

    def value_at(self, x: float) -> float | None:
        return interp(self.points, x)


@dataclass
class BlendTrackInfo:
    owner_id: str
    owner_name: str
    control_name: str
    control_id: str
    curves: list[RtpcCurve] = field(default_factory=list)
    associations: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class GroupingInfo:
    owner_id: str
    group_name: str
    group_id: str
    state_name: str
    state_id: str
    item_names: list[str]
    item_ids: list[str]


@dataclass
class WwiseObject:
    id: str
    name: str
    type: str
    path: str
    source_file: Path
    parent_id: str | None = None
    children: list[str] = field(default_factory=list)
    properties: dict[str, Any] = field(default_factory=dict)
    references: list[RefInfo] = field(default_factory=list)
    audio_file: str = ""
    rtpcs: list[RtpcCurve] = field(default_factory=list)
    blend_tracks: list[BlendTrackInfo] = field(default_factory=list)
    groupings: list[GroupingInfo] = field(default_factory=list)


class WwiseIndex:
    def __init__(self, root: Path):
        self.root = root
        self.objects: dict[str, WwiseObject] = {}
        self.path_to_id: dict[str, str] = {}
        self.name_to_ids: dict[str, list[str]] = defaultdict(list)
        self.errors: list[str] = []
        self.file_count = 0
        self.originals_by_name: dict[str, list[Path]] = defaultdict(list)

    def scan(self) -> None:
        if not self.root.exists():
            raise FileNotFoundError(f"Wwise project root not found: {self.root}")
        xml_files = [p for p in self.root.rglob("*.wwu") if not is_skipped_path(p)]
        xml_files += [p for p in self.root.glob("*.wproj") if not is_skipped_path(p)]
        for xml_file in sorted(xml_files, key=lambda p: str(p).lower()):
            self._scan_xml(xml_file)
        self._scan_originals()

    def _scan_originals(self) -> None:
        originals = self.root / "Originals"
        if not originals.exists():
            return
        for path in originals.rglob("*"):
            if path.is_file():
                self.originals_by_name[path.name.lower()].append(path)

    def _category_for(self, xml_file: Path) -> str:
        try:
            rel = xml_file.relative_to(self.root)
        except ValueError:
            return ""
        return rel.parts[0] if len(rel.parts) > 1 else ""

    def _full_path(self, category: str, parts: list[str]) -> str:
        path = "\\" + "\\".join([part for part in parts if part])
        if category:
            path = "\\" + category + path
        return normalize_wwise_path(path)

    def _is_object_element(self, elem: ET.Element) -> bool:
        tag = local_name(elem.tag)
        return tag not in NON_OBJECT_TAGS and bool(elem.attrib.get("ID")) and (
            "Name" in elem.attrib or tag == "Action"
        )

    def _scan_xml(self, xml_file: Path) -> None:
        try:
            root = ET.parse(xml_file).getroot()
        except Exception as exc:
            self.errors.append(f"{xml_file}: {exc}")
            return
        self.file_count += 1
        category = self._category_for(xml_file)

        def walk(elem: ET.Element, parent_id: str | None, parts: list[str]) -> None:
            current_parent = parent_id
            current_parts = parts
            if self._is_object_element(elem):
                tag = local_name(elem.tag)
                obj_id = elem.attrib["ID"]
                name = elem.attrib.get("Name", "")
                current_parts = parts + [name or tag]
                obj = WwiseObject(
                    id=obj_id,
                    name=name,
                    type=tag,
                    path=self._full_path(category, current_parts),
                    source_file=xml_file,
                    parent_id=parent_id,
                    properties=self._properties(elem),
                    references=self._references(elem),
                    audio_file=self._audio_file(elem),
                )
                obj.rtpcs = self._rtpcs(elem, obj)
                obj.blend_tracks = self._blend_tracks(elem, obj)
                obj.groupings = self._groupings(elem, obj)
                self.objects[obj_id] = obj
                self.path_to_id[obj.path] = obj_id
                self.name_to_ids[name.lower()].append(obj_id)
                if parent_id and parent_id in self.objects:
                    self.objects[parent_id].children.append(obj_id)
                current_parent = obj_id

            for child in list(elem):
                walk(child, current_parent, current_parts)

        walk(root, None, [])

    def _properties(self, elem: ET.Element) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for prop in elem.findall("./PropertyList/Property"):
            name = prop.attrib.get("Name", "")
            if not name:
                continue
            if "Value" in prop.attrib:
                result[name] = prop.attrib.get("Value")
                continue
            values = [value.text or "" for value in prop.findall("./ValueList/Value")]
            result[name] = values[0] if len(values) == 1 else values
        return result

    def _references(self, elem: ET.Element) -> list[RefInfo]:
        refs: list[RefInfo] = []
        for ref in elem.findall("./ReferenceList/Reference"):
            obj_ref = ref.find("./ObjectRef")
            if obj_ref is None:
                continue
            refs.append(
                RefInfo(
                    reference=ref.attrib.get("Name", ""),
                    name=obj_ref.attrib.get("Name", ""),
                    id=obj_ref.attrib.get("ID", ""),
                )
            )
        return refs

    def _audio_file(self, elem: ET.Element) -> str:
        audio = elem.find("./AudioFile")
        return audio.text.strip() if audio is not None and audio.text else ""

    def _parse_curve(self, rtpc: ET.Element, owner: WwiseObject, scope: str) -> RtpcCurve:
        prop = rtpc.find("./PropertyList/Property[@Name='PropertyName']")
        control = rtpc.find("./ReferenceList/Reference[@Name='ControlInput']/ObjectRef")
        points: list[tuple[float, float]] = []
        for point in rtpc.findall("./ReferenceList/Reference[@Name='Curve']/Custom/Curve/PointList/Point"):
            x = number_or_none(point.findtext("XPos"))
            y = number_or_none(point.findtext("YPos"))
            if x is not None and y is not None:
                points.append((x, y))
        return RtpcCurve(
            owner_id=owner.id,
            owner_name=owner.name,
            owner_type=owner.type,
            scope=scope,
            property_name=prop.attrib.get("Value", "") if prop is not None else "",
            control_name=control.attrib.get("Name", "") if control is not None else "",
            control_id=control.attrib.get("ID", "") if control is not None else "",
            points=points,
        )

    def _rtpcs(self, elem: ET.Element, owner: WwiseObject) -> list[RtpcCurve]:
        return [
            self._parse_curve(rtpc, owner, "object")
            for rtpc in elem.findall("./ObjectLists/ObjectList[@Name='RTPC']/Reference/Local/RTPC")
        ]

    def _blend_tracks(self, elem: ET.Element, owner: WwiseObject) -> list[BlendTrackInfo]:
        tracks: list[BlendTrackInfo] = []
        for track in elem.findall("./BlendTrackList/BlendTrack"):
            control = track.find("./ReferenceList/Reference[@Name='LayerCrossFadeControlInput']/ObjectRef")
            info = BlendTrackInfo(
                owner_id=owner.id,
                owner_name=owner.name,
                control_name=control.attrib.get("Name", "") if control is not None else "",
                control_id=control.attrib.get("ID", "") if control is not None else "",
            )
            info.curves = [
                self._parse_curve(rtpc, owner, "blendTrack")
                for rtpc in track.findall("./ObjectLists/ObjectList[@Name='RTPC']/Reference/Local/RTPC")
            ]
            for assoc in track.findall("./BlendTrackAssocList/BlendTrackAssoc"):
                item = assoc.find("./ItemRef")
                fade = assoc.find("./CrossfadingInfo")
                info.associations.append(
                    {
                        "item_name": item.attrib.get("Name", "") if item is not None else "",
                        "item_id": item.attrib.get("ID", "") if item is not None else "",
                        "left": number_or_none(fade.findtext("LeftEdgePos") if fade is not None else None),
                        "right": number_or_none(fade.findtext("RightEdgePos") if fade is not None else None),
                    }
                )
            tracks.append(info)
        return tracks

    def _groupings(self, elem: ET.Element, owner: WwiseObject) -> list[GroupingInfo]:
        switch_group = next((ref for ref in owner.references if ref.reference == "SwitchGroupOrStateGroup"), None)
        result: list[GroupingInfo] = []
        for group in elem.findall("./GroupingInfo/GroupingList/Grouping"):
            switch = group.find("./SwitchRef")
            if switch is None:
                continue
            items = group.findall("./ItemList/ItemRef")
            result.append(
                GroupingInfo(
                    owner_id=owner.id,
                    group_name=switch_group.name if switch_group else "",
                    group_id=switch_group.id if switch_group else "",
                    state_name=switch.attrib.get("Name", ""),
                    state_id=switch.attrib.get("ID", ""),
                    item_names=[item.attrib.get("Name", "") for item in items],
                    item_ids=[item.attrib.get("ID", "") for item in items],
                )
            )
        return result

    def descendants(self, obj_id: str) -> list[WwiseObject]:
        result: list[WwiseObject] = []

        def visit(oid: str) -> None:
            for child_id in self.objects.get(oid, WwiseObject("", "", "", "", Path())).children:
                child = self.objects.get(child_id)
                if not child:
                    continue
                result.append(child)
                visit(child_id)

        visit(obj_id)
        return result

    def ancestors(self, obj_id: str) -> list[WwiseObject]:
        result: list[WwiseObject] = []
        current = self.objects.get(obj_id)
        while current and current.parent_id:
            parent = self.objects.get(current.parent_id)
            if not parent:
                break
            result.append(parent)
            current = parent
        return result

    def subtree_ids(self, obj_id: str) -> set[str]:
        return {obj_id} | {obj.id for obj in self.descendants(obj_id)}

    def resolve(self, query: str) -> list[WwiseObject]:
        text = query.strip()
        if not text:
            return []
        if text.startswith("{") and text.endswith("}") and text in self.objects:
            return [self.objects[text]]
        norm = normalize_wwise_path(text) if "\\" in text or "/" in text else ""
        if norm and norm in self.path_to_id:
            return [self.objects[self.path_to_id[norm]]]
        exact = self.name_to_ids.get(text.lower(), [])
        if exact:
            return [self.objects[oid] for oid in exact]
        lower = text.lower()
        return [obj for obj in self.objects.values() if lower in obj.name.lower() or lower in obj.path.lower()]

    def related_events(self, target_ids: set[str]) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for event in self.objects.values():
            if event.type != "Event":
                continue
            actions = [obj for obj in self.descendants(event.id) if obj.type == "Action"]
            hits: list[dict[str, Any]] = []
            for action in actions:
                target = next((ref for ref in action.references if ref.reference == "Target"), None)
                if target and target.id in target_ids:
                    hits.append(
                        {
                            "action_id": action.id,
                            "action_path": action.path,
                            "action_type": int(action.properties.get("ActionType") or 1),
                            "target_id": target.id,
                            "target_name": target.name,
                        }
                    )
            if hits:
                events.append({"event": event, "actions": hits})
        return sorted(events, key=lambda item: item["event"].path.lower())


def waapi_connect(url: str):
    from waapi import WaapiClient

    return WaapiClient(url=url)


def call(client: Any, uri: str, args: dict[str, Any], default: Any = None) -> Any:
    try:
        result = client.call(uri, args)
        return default if result is None else result
    except Exception:
        return default


def live_get(client: Any, obj_ids: list[str]) -> list[dict[str, Any]]:
    result = call(
        client,
        "ak.wwise.core.object.get",
        {"from": {"id": obj_ids}, "options": {"return": WAAPI_RETURN}},
        {"return": []},
    )
    return result.get("return", [])


def resolve_voice_paths(index: WwiseIndex, client: Any, voices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ids = sorted({voice.get("objectGUID") for voice in voices if voice.get("objectGUID")})
    live_by_id = {item.get("id"): item for item in live_get(client, ids)}
    rows = []
    for voice in voices:
        oid = voice.get("objectGUID")
        local = index.objects.get(oid)
        live = live_by_id.get(oid, {})
        rows.append(
            {
                "objectGUID": oid,
                "name": (local.name if local else live.get("name")) or "",
                "type": (local.type if local else live.get("type")) or "",
                "path": (local.path if local else live.get("path")) or "",
                "pipelineID": voice.get("pipelineID"),
                "gameObjectID": voice.get("gameObjectID"),
            }
        )
    return rows


def make_switch_combinations(index: WwiseIndex, target_ids: set[str], max_combinations: int) -> list[dict[str, str]]:
    groups: dict[str, list[str]] = defaultdict(list)
    defaults: dict[str, str] = {}
    for oid in target_ids:
        obj = index.objects.get(oid)
        if not obj:
            continue
        group_ref = next((ref for ref in obj.references if ref.reference == "SwitchGroupOrStateGroup"), None)
        default_ref = next((ref for ref in obj.references if ref.reference == "DefaultSwitchOrState"), None)
        if group_ref and default_ref:
            defaults[group_ref.name] = default_ref.name
        for grouping in obj.groupings:
            if grouping.group_name and grouping.state_name and grouping.state_name not in groups[grouping.group_name]:
                groups[grouping.group_name].append(grouping.state_name)
    if not groups:
        return [{}]
    ordered = sorted(groups.items())
    combos = [dict(zip([name for name, _ in ordered], states)) for states in itertools.product(*[states for _, states in ordered])]
    default_combo = {name: defaults.get(name, states[0]) for name, states in ordered}
    result = [default_combo]
    for combo in combos:
        if combo not in result:
            result.append(combo)
        if len(result) >= max_combinations:
            break
    return result


def rtpc_controls(index: WwiseIndex, target_ids: set[str]) -> dict[str, dict[str, Any]]:
    controls: dict[str, dict[str, Any]] = {}
    for oid in target_ids:
        obj = index.objects.get(oid)
        if not obj:
            continue
        for curve in obj.rtpcs:
            if curve.control_id:
                controls.setdefault(curve.control_id, {"name": curve.control_name, "id": curve.control_id})
        for track in obj.blend_tracks:
            if track.control_id:
                controls.setdefault(track.control_id, {"name": track.control_name, "id": track.control_id})
            for curve in track.curves:
                if curve.control_id:
                    controls.setdefault(curve.control_id, {"name": curve.control_name, "id": curve.control_id})
    for control in controls.values():
        obj = index.objects.get(control["id"])
        initial = number_or_none(obj.properties.get("InitialValue") if obj else None)
        min_v = number_or_none(obj.properties.get("Min") if obj else None)
        max_v = number_or_none(obj.properties.get("Max") if obj else None)
        control["initial"] = 0.0 if initial is None else initial
        control["min"] = 0.0 if min_v is None else min_v
        control["max"] = 100.0 if max_v is None else max_v
    return controls


def transport_test(
    index: WwiseIndex,
    client: Any,
    play_object_id: str,
    target_subtree_ids: set[str],
    controls: dict[str, dict[str, Any]],
    switch_combos: list[dict[str, str]],
    rtpc_values: list[float],
    duration: float,
) -> list[dict[str, Any]]:
    call(client, "ak.wwise.core.profiler.enableProfilerData", {"dataTypes": [{"dataType": "voices"}, {"dataType": "voiceInspector"}]}, {})
    call(client, "ak.wwise.core.profiler.startCapture", {}, {})
    rows: list[dict[str, Any]] = []
    default_switch_combo = switch_combos[0] if switch_combos else {}
    try:
        values = rtpc_values or [0.0]
        for combo in switch_combos:
            for group, state in combo.items():
                call(client, "ak.soundengine.setSwitch", {"switchGroup": group, "switchState": state}, {})
            for value in values:
                for control in controls.values():
                    bounded = max(control.get("min", 0.0), min(control.get("max", 100.0), value))
                    call(client, "ak.soundengine.setRTPCValue", {"rtpc": control["id"], "value": bounded}, {})
                transport = call(client, "ak.wwise.core.transport.create", {"object": play_object_id}, {})
                transport_id = transport.get("transport")
                if transport_id is not None:
                    call(client, "ak.wwise.core.transport.executeAction", {"transport": transport_id, "action": "play"}, {})
                time.sleep(duration)
                voice_result = call(client, "ak.wwise.core.profiler.getVoices", {"time": "capture"}, {"return": []})
                voices = voice_result.get("return", [])
                target_voices = [voice for voice in voices if voice.get("objectGUID") in target_subtree_ids]
                rows.append(
                    {
                        "switches": dict(combo),
                        "rtpc_value": value,
                        "voice_count": len(voices),
                        "target_voice_count": len(target_voices),
                        "voices": resolve_voice_paths(index, client, target_voices),
                    }
                )
                if transport_id is not None:
                    call(client, "ak.wwise.core.transport.executeAction", {"transport": transport_id, "action": "stop"}, {})
                    call(client, "ak.wwise.core.transport.destroy", {"transport": transport_id}, {})
                time.sleep(0.08)
    finally:
        for control in controls.values():
            call(client, "ak.soundengine.setRTPCValue", {"rtpc": control["id"], "value": control.get("initial", 0.0)}, {})
        for group, state in default_switch_combo.items():
            call(client, "ak.soundengine.setSwitch", {"switchGroup": group, "switchState": state}, {})
        call(client, "ak.wwise.core.profiler.stopCapture", {}, {})
    return rows


def static_checks(index: WwiseIndex, root: WwiseObject, target_ids: set[str], controls: dict[str, dict[str, Any]]) -> dict[str, Any]:
    objects = [index.objects[oid] for oid in target_ids if oid in index.objects]
    counts = Counter(obj.type for obj in objects)
    audio_sources = [obj for obj in objects if obj.type == "AudioFileSource" and obj.audio_file]
    missing_sources = []
    for source in audio_sources:
        matches = index.originals_by_name.get(source.audio_file.lower(), [])
        if not matches:
            missing_sources.append({"path": source.path, "audio_file": source.audio_file})

    empty_switch_branches = []
    for obj in objects:
        if obj.type != "SwitchContainer":
            continue
        for grouping in obj.groupings:
            child_ids = grouping.item_ids
            leaf_sources = []
            for child_id in child_ids:
                child_subtree = {child_id} | {desc.id for desc in index.descendants(child_id)}
                leaf_sources.extend(
                    item for item in child_subtree if index.objects.get(item, None) and index.objects[item].type == "AudioFileSource"
                )
            if not leaf_sources:
                empty_switch_branches.append(
                    {
                        "container": obj.path,
                        "group": grouping.group_name,
                        "state": grouping.state_name,
                        "items": grouping.item_names,
                    }
                )

    rtpc_warnings = []
    initial_by_id = {cid: data.get("initial", 0.0) for cid, data in controls.items()}
    for obj in objects:
        for curve in obj.rtpcs + [curve for track in obj.blend_tracks for curve in track.curves]:
            if curve.property_name.lower() != "volume" or not curve.control_id:
                continue
            initial = initial_by_id.get(curve.control_id, 0.0)
            value = curve.value_at(initial)
            if value is not None and value <= -96:
                rtpc_warnings.append(
                    {
                        "owner": obj.path,
                        "scope": curve.scope,
                        "control": curve.control_name,
                        "initial": initial,
                        "volume_db_at_initial": round(value, 3),
                        "points": curve.points,
                    }
                )

    overlap_warnings = []
    sample_points = sorted({0.0, 0.001, 1.0, 10.0, 20.0, 25.0, 30.0, 40.0, 50.0, 75.0, 100.0})
    for obj in objects:
        object_volume_curves = [curve for curve in obj.rtpcs if curve.property_name.lower() == "volume"]
        for track in obj.blend_tracks:
            blend_volume_curves = [curve for curve in track.curves if curve.property_name.lower() == "volume"]
            for object_curve in object_volume_curves:
                for blend_curve in blend_volume_curves:
                    if object_curve.control_id != blend_curve.control_id:
                        continue
                    combined = []
                    for x in sample_points:
                        ov = object_curve.value_at(x)
                        bv = blend_curve.value_at(x)
                        if ov is not None and bv is not None:
                            combined.append((x, ov + bv))
                    if combined and max(v for _, v in combined) <= -96:
                        overlap_warnings.append(
                            {
                                "owner": obj.path,
                                "control": object_curve.control_name,
                                "max_combined_volume_db": round(max(v for _, v in combined), 3),
                                "sampled_curve": [(x, round(v, 3)) for x, v in combined],
                                "associations": track.associations,
                            }
                        )

    return {
        "object_count": len(objects),
        "type_counts": dict(counts),
        "audio_sources": [{"path": obj.path, "audio_file": obj.audio_file} for obj in audio_sources],
        "missing_sources": missing_sources,
        "empty_switch_branches": empty_switch_branches,
        "rtpc_initial_silence_warnings": rtpc_warnings,
        "rtpc_overlap_warnings": overlap_warnings,
    }


def choose_play_object(target: WwiseObject, related_events: list[dict[str, Any]]) -> WwiseObject:
    play_events = []
    for item in related_events:
        actions = item.get("actions", [])
        if any(action.get("action_type", 1) == 1 for action in actions):
            play_events.append(item["event"])
    exact_play = [event for event in play_events if event.name.lower() == f"play_{target.name.lower()}"]
    if exact_play:
        return exact_play[0]
    if play_events:
        return play_events[0]
    return target


def summarize_status(static: dict[str, Any], transport_rows: list[dict[str, Any]]) -> tuple[str, list[str]]:
    reasons: list[str] = []
    status = "PASS"
    if not static["audio_sources"]:
        status = "FAIL"
        reasons.append("No AudioFileSource was found under the tested target.")
    if static["missing_sources"]:
        status = "FAIL"
        reasons.append(f"{len(static['missing_sources'])} AudioFileSource file(s) are missing under Originals.")
    if transport_rows and max((row["target_voice_count"] for row in transport_rows), default=0) == 0:
        status = "FAIL"
        reasons.append("Transport playback produced no target voices in the sampled matrix.")
    if static["rtpc_overlap_warnings"]:
        status = "WARN" if status == "PASS" else status
        reasons.append("One or more RTPC curve combinations have no audible overlap.")
    if static["rtpc_initial_silence_warnings"]:
        status = "WARN" if status == "PASS" else status
        reasons.append("Initial RTPC values put one or more Volume curves at or below -96 dB.")
    if static["empty_switch_branches"]:
        status = "WARN" if status == "PASS" else status
        reasons.append("One or more Switch states route to branches with no AudioFileSource.")
    if not reasons:
        reasons.append("Static checks and transport sampling did not find a blocking issue.")
    return status, reasons


def md_table(headers: list[str], rows: list[list[Any]]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(cell).replace("\n", "<br>") for cell in row) + " |")
    return lines


def write_reports(payload: dict[str, Any], out_dir: Path, stem: str) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"{stem}.json"
    md_path = out_dir / f"{stem}.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# ProjectEF Wwise Node Debug Report",
        "",
        f"- Status: `{payload['status']}`",
        f"- Generated: `{payload['generated']}`",
        f"- Query: `{payload['query']}`",
        f"- Target: `{payload['target']['path']}`",
        f"- Play object: `{payload['play_object']['path']}`",
        f"- WAAPI: `{payload.get('waapi', {}).get('status', 'not used')}`",
        "",
        "## Diagnosis",
        "",
    ]
    lines.extend(f"- {reason}" for reason in payload["status_reasons"])
    lines.extend(["", "## Static Summary", ""])
    static = payload["static"]
    lines.extend(
        [
            f"- Object count: `{static['object_count']}`",
            f"- Type counts: `{static['type_counts']}`",
            f"- Audio sources: `{len(static['audio_sources'])}`",
            f"- Missing sources: `{len(static['missing_sources'])}`",
            f"- Empty switch branches: `{len(static['empty_switch_branches'])}`",
            f"- Initial RTPC silence warnings: `{len(static['rtpc_initial_silence_warnings'])}`",
            f"- RTPC overlap warnings: `{len(static['rtpc_overlap_warnings'])}`",
        ]
    )
    if payload.get("related_events"):
        lines.extend(["", "## Related Events", ""])
        lines.extend(
            md_table(
                ["Event", "Actions"],
                [
                    [
                        item["event"]["path"],
                        ", ".join(f"{a['action_type']}->{a['target_name']}" for a in item["actions"]),
                    ]
                    for item in payload["related_events"]
                ],
            )
        )
    if static["missing_sources"]:
        lines.extend(["", "## Missing Sources", ""])
        lines.extend(md_table(["Path", "Audio file"], [[x["path"], x["audio_file"]] for x in static["missing_sources"]]))
    if static["empty_switch_branches"]:
        lines.extend(["", "## Empty Switch Branches", ""])
        lines.extend(
            md_table(
                ["Container", "Group", "State", "Items"],
                [[x["container"], x["group"], x["state"], ", ".join(x["items"])] for x in static["empty_switch_branches"]],
            )
        )
    if static["rtpc_initial_silence_warnings"]:
        lines.extend(["", "## RTPC Initial Silence", ""])
        lines.extend(
            md_table(
                ["Owner", "Scope", "Control", "Initial", "Volume dB"],
                [
                    [x["owner"], x["scope"], x["control"], x["initial"], x["volume_db_at_initial"]]
                    for x in static["rtpc_initial_silence_warnings"]
                ],
            )
        )
    if static["rtpc_overlap_warnings"]:
        lines.extend(["", "## RTPC Overlap Warnings", ""])
        lines.extend(
            md_table(
                ["Owner", "Control", "Max Combined dB", "Associations"],
                [
                    [
                        x["owner"],
                        x["control"],
                        x["max_combined_volume_db"],
                        ", ".join(a["item_name"] for a in x["associations"]),
                    ]
                    for x in static["rtpc_overlap_warnings"]
                ],
            )
        )
    if payload.get("transport_tests"):
        lines.extend(["", "## Transport Tests", ""])
        lines.extend(
            md_table(
                ["Switches", "RTPC", "Target Voices", "Voices"],
                [
                    [
                        json.dumps(row["switches"], ensure_ascii=False),
                        row["rtpc_value"],
                        row["target_voice_count"],
                        ", ".join(v["path"] for v in row["voices"]),
                    ]
                    for row in payload["transport_tests"]
                ],
            )
        )
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path, json_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only ProjectEF Wwise node/event debugger.")
    parser.add_argument("query", help="Wwise object name, id, or path. Example: Stamina or Play_Stamina")
    parser.add_argument("--project-root", default=str(DEFAULT_PROJECT_ROOT))
    parser.add_argument("--waapi", default=DEFAULT_WAAPI_URL)
    parser.add_argument("--no-transport", action="store_true")
    parser.add_argument("--duration", type=float, default=0.35)
    parser.add_argument("--rtpc-values", default="", help="Comma-separated RTPC test values. Defaults to initial, 1, 30, 50, 100.")
    parser.add_argument("--max-switch-combinations", type=int, default=12)
    parser.add_argument("--out-dir", default=str(DEFAULT_REPORT_DIR))
    args = parser.parse_args()

    started = datetime.now()
    index = WwiseIndex(Path(args.project_root))
    index.scan()
    matches = index.resolve(args.query)
    if not matches:
        raise SystemExit(f"No Wwise object matched query: {args.query}")
    target = sorted(matches, key=lambda obj: (0 if obj.name.lower() == args.query.lower() else 1, obj.path))[0]

    if target.type == "Event":
        actions = [obj for obj in index.descendants(target.id) if obj.type == "Action"]
        target_ids = {ref.id for action in actions for ref in action.references if ref.reference == "Target" and ref.id in index.objects}
        if not target_ids:
            target_ids = {target.id}
        primary_target_id = sorted(target_ids)[0]
        target_for_static = index.objects.get(primary_target_id, target)
        play_object = target
    else:
        target_ids = index.subtree_ids(target.id)
        related = index.related_events(target_ids)
        play_object = choose_play_object(target, related)
        target_for_static = target

    target_subtree_ids = set()
    for oid in target_ids:
        if oid in index.objects:
            target_subtree_ids |= index.subtree_ids(oid)
    if not target_subtree_ids:
        target_subtree_ids = {target.id}

    related_events = index.related_events(target_subtree_ids)
    controls = rtpc_controls(index, target_subtree_ids)
    static = static_checks(index, target_for_static, target_subtree_ids, controls)
    switch_combos = make_switch_combinations(index, target_subtree_ids, args.max_switch_combinations)

    if args.rtpc_values.strip():
        rtpc_values = [float(item.strip()) for item in args.rtpc_values.split(",") if item.strip()]
    else:
        initial_values = [float(data.get("initial", 0.0)) for data in controls.values()] or [0.0]
        rtpc_values = sorted({*initial_values, 1.0, 30.0, 50.0, 100.0})

    waapi_status = {"status": "not used"}
    transport_rows: list[dict[str, Any]] = []
    if not args.no_transport:
        try:
            with waapi_connect(args.waapi) as client:
                info = call(client, "ak.wwise.core.getInfo", {}, {})
                version = (info.get("version") or {}).get("displayName", "")
                build = (info.get("version") or {}).get("build", "")
                waapi_status = {"status": "connected", "version": version, "build": build, "sessionId": info.get("sessionId", "")}
                transport_rows = transport_test(
                    index=index,
                    client=client,
                    play_object_id=play_object.id,
                    target_subtree_ids=target_subtree_ids,
                    controls=controls,
                    switch_combos=switch_combos,
                    rtpc_values=rtpc_values,
                    duration=args.duration,
                )
        except Exception as exc:
            waapi_status = {"status": "failed", "error": str(exc)}

    status, reasons = summarize_status(static, transport_rows)
    payload = {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "elapsed_seconds": round((datetime.now() - started).total_seconds(), 3),
        "query": args.query,
        "status": status,
        "status_reasons": reasons,
        "project_root": str(index.root),
        "target": {"id": target.id, "name": target.name, "type": target.type, "path": target.path},
        "play_object": {"id": play_object.id, "name": play_object.name, "type": play_object.type, "path": play_object.path},
        "primary_static_target": {
            "id": target_for_static.id,
            "name": target_for_static.name,
            "type": target_for_static.type,
            "path": target_for_static.path,
        },
        "waapi": waapi_status,
        "scan": {"files": index.file_count, "objects": len(index.objects), "errors": index.errors[:20]},
        "rtpc_controls": list(controls.values()),
        "switch_combinations": switch_combos,
        "related_events": [
            {
                "event": {"id": item["event"].id, "name": item["event"].name, "path": item["event"].path},
                "actions": item["actions"],
            }
            for item in related_events
        ],
        "static": static,
        "transport_tests": transport_rows,
    }

    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    safe_name = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in args.query.strip())[:48] or "WwiseNode"
    md_path, json_path = write_reports(payload, Path(args.out_dir), f"ProjectEF_WwiseNodeDebug_{safe_name}_{stamp}")
    payload["markdown_report"] = str(md_path)
    payload["json_report"] = str(json_path)
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({"status": status, "markdown_report": str(md_path), "json_report": str(json_path), "reasons": reasons}, ensure_ascii=False, indent=2))
    return 0 if status in {"PASS", "WARN"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
