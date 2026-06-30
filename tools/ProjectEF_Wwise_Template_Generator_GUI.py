#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import json
import re
import socket
import sys
import threading
import traceback
import tkinter as tk
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from typing import Any


DEFAULT_WWISE_ROOT = Path(r"D:\EF Wwise\ProjectEF")
DEFAULT_WAAPI_URL = "ws://127.0.0.1:8080/waapi"
REGISTRY_FILE = Path(__file__).with_name("wwise_template_registry.json")
RUN_REPORT_DIR = Path(__file__).resolve().parents[1] / "报告"

NON_OBJECT_TAGS = {
    "ActiveSource",
    "AudioFile",
    "ChildrenList",
    "ItemRef",
    "MediaID",
    "ObjectRef",
    "PluginLib",
    "Property",
    "PropertyList",
    "Reference",
    "ReferenceList",
    "StateRef",
    "SwitchRef",
    "Value",
    "ValueList",
}

LEAF_TEMPLATE_TYPES = {
    "Action",
    "AudioFileSource",
    "CustomMetadata",
    "Effect",
    "EventAction",
    "MediaID",
    "Sound",
}

TEMPLATE_ROOT_TYPES = {
    "ActorMixer",
    "Attenuation",
    "AuxBus",
    "BlendContainer",
    "Bus",
    "Conversion",
    "Event",
    "Folder",
    "GameParameter",
    "MusicPlaylistContainer",
    "MusicSegment",
    "MusicSwitchContainer",
    "MusicTrack",
    "MusicTrackSequence",
    "RandomSequenceContainer",
    "SoundcasterSession",
    "StateGroup",
    "SwitchContainer",
    "SwitchGroup",
}

NON_COPYABLE_CHILD_TYPES = {
    "AudioSourceRef",
    "ConversionPlugin",
    "Curve",
    "DefaultConversion",
    "Effect",
    "EffectSlot",
    "Modifier",
    "MultiSwitchEntry",
    "MusicClip",
    "MusicCue",
    "MusicFade",
    "MusicPlaylistItem",
    "MusicTransition",
    "Panner",
    "Path2D",
    "Position",
    "RTPC",
    "SourcePlugin",
    "StartState",
    "EndState",
}

RESOURCE_REFERENCE_TYPES = {
    # AudioFileSource is the media-file reference. Sound is authored Wwise content
    # and must stay in structure-only copies as an empty placeholder.
    "AudioFileSource",
}

LIVE_SELF_TEST_TEMPLATE_PATH = r"\Actor-Mixer Hierarchy\Gear\Gear\Line_Snap"

WAAPI_RETURN = [
    "id",
    "name",
    "type",
    "path",
    "parent",
    "childrenCount",
    "@ActionType",
    "@Target",
    "@Attenuation",
    "@Conversion",
    "@DefaultSwitchOrState",
    "@OutputBus",
    "@SwitchGroupOrStateGroup",
]


def now_stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def is_skipped_path(path: Path) -> bool:
    lowered = [part.lower() for part in path.parts]
    return any(part in {".backup", ".cache", "backup", "cache"} for part in lowered)


def normalize_wwise_path(path: str) -> str:
    text = (path or "").strip().replace("/", "\\")
    if not text:
        return ""
    if not text.startswith("\\"):
        text = "\\" + text
    while "\\\\" in text:
        text = text.replace("\\\\", "\\")
    return text.rstrip("\\")


def join_wwise_path(parent: str, name: str) -> str:
    return normalize_wwise_path(parent).rstrip("\\") + "\\" + name.strip("\\")


def parent_wwise_path(path: str) -> str:
    norm = normalize_wwise_path(path)
    if "\\" not in norm.strip("\\"):
        return ""
    return norm.rsplit("\\", 1)[0]


def split_wwise_path(path: str) -> list[str]:
    return [part for part in normalize_wwise_path(path).strip("\\").split("\\") if part]


def relative_under(path: str, root: str) -> str:
    norm_path = normalize_wwise_path(path)
    norm_root = normalize_wwise_path(root)
    if norm_path == norm_root:
        return ""
    prefix = norm_root + "\\"
    if norm_path.startswith(prefix):
        return norm_path[len(prefix) :]
    return norm_path


def rename_with_token(name: str, token: str, replacement: str, force_root: bool = False) -> str:
    token = token.strip()
    replacement = replacement.strip()
    if force_root:
        if token and replacement and token in name:
            return name.replace(token, replacement)
        return replacement or name
    if not token or not replacement:
        return name
    return name.replace(token, replacement)


def suggest_replace_token(root_name: str, object_names: list[str]) -> str:
    root_name = root_name.strip()
    if not root_name:
        return ""
    names = [name for name in object_names if name]
    tokens = [part for part in root_name.split("_") if part]
    candidates = [root_name]
    for length in range(len(tokens) - 1, 0, -1):
        for start in range(0, len(tokens) - length + 1):
            candidate = "_".join(tokens[start : start + length])
            if len(candidate) >= 3 and candidate not in candidates:
                candidates.append(candidate)
    best = root_name
    best_score = -1
    for candidate in candidates:
        hits = sum(1 for name in names if candidate in name)
        score = hits * 1000 + len(candidate)
        if hits >= 2 and score > best_score:
            best = candidate
            best_score = score
    return best


def preview_root_name(manifest: "TemplateManifest", replace_token: str, new_name: str) -> str:
    return rename_with_token(manifest.root.name, replace_token, new_name, force_root=True)


def safe_ref_id(ref: Any) -> str:
    if isinstance(ref, dict):
        return str(ref.get("id") or ref.get("ID") or "")
    if isinstance(ref, str):
        return ref
    return ""


def event_name_for_copy(event_name: str, replace_token: str, new_name: str) -> str:
    new_event_name = rename_with_token(event_name, replace_token, new_name)
    if new_event_name == event_name:
        new_event_name = f"{event_name}_{new_name}"
    return new_event_name


def group_template_events(events: list["TemplateEvent"]) -> list[list["TemplateEvent"]]:
    groups: dict[str, list[TemplateEvent]] = {}
    for event_ref in events:
        groups.setdefault(event_ref.event.id, []).append(event_ref)
    return list(groups.values())


def live_created_path_from_log(log: list[str]) -> str:
    for line in reversed(log):
        if line.startswith("LIVE_CREATED_PATH:"):
            return line.split(":", 1)[1].strip()
    return ""


def write_create_report(log: list[str], error: Exception | None, saved: bool, live_path: str) -> Path | None:
    try:
        RUN_REPORT_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        path = RUN_REPORT_DIR / f"ProjectEF_WwiseTemplateGenerator_Create_{stamp}.md"
        status = "FAILED" if error else "PASS"
        lines = [
            "# ProjectEF Wwise Template Generator Create",
            "",
            f"- Status: `{status}`",
            f"- Generated: `{datetime.now().isoformat(timespec='seconds')}`",
            f"- Saved project: `{saved}`",
            f"- Live path: `{live_path}`",
        ]
        if error:
            lines.append(f"- Error: `{error}`")
        lines.extend(["", "## Log", ""])
        lines.extend(f"- {line}" for line in log)
        path.write_text("\n".join(lines), encoding="utf-8")
        return path
    except Exception:
        return None


def latest_project_source_mtime(root: Path) -> float:
    latest = 0.0
    if not root.exists():
        return latest
    files = [path for path in root.rglob("*.wwu") if not is_skipped_path(path)]
    files += [path for path in root.glob("*.wproj") if not is_skipped_path(path)]
    for path in files:
        try:
            latest = max(latest, path.stat().st_mtime)
        except OSError:
            continue
    return latest


@dataclass
class ProjectObject:
    id: str
    name: str
    type: str
    xml_path: str
    full_path: str
    workunit: str
    source_file: Path
    parent_id: str | None = None
    children_ids: list[str] = field(default_factory=list)
    properties: dict[str, str] = field(default_factory=dict)
    references: list[dict[str, str]] = field(default_factory=list)
    audio_file: str = ""


@dataclass
class TemplateEvent:
    event: ProjectObject
    action: ProjectObject
    target_id: str
    target_name: str
    action_type: str = ""


@dataclass
class TemplateManifest:
    root: ProjectObject
    objects: list[ProjectObject]
    events: list[TemplateEvent]
    counts: Counter
    warnings: list[str]
    external_refs: Counter
    audio_files: list[str]

    @property
    def object_ids(self) -> set[str]:
        return {obj.id for obj in self.objects}


class WwiseProjectIndex:
    def __init__(self, root: Path):
        self.root = root
        self.objects_by_id: dict[str, ProjectObject] = {}
        self.objects_by_full_path: dict[str, ProjectObject] = {}
        self.workunits: dict[str, list[str]] = defaultdict(list)
        self.candidates_by_workunit: dict[str, list[ProjectObject]] = defaultdict(list)
        self.errors: list[str] = []
        self.file_count = 0
        self.object_count = 0
        self.latest_source_mtime = 0.0

    def scan(self) -> None:
        self.objects_by_id.clear()
        self.objects_by_full_path.clear()
        self.workunits.clear()
        self.candidates_by_workunit.clear()
        self.errors.clear()
        self.file_count = 0
        self.object_count = 0

        if not self.root.exists():
            raise FileNotFoundError(f"Wwise project folder does not exist: {self.root}")

        xml_files = [path for path in self.root.rglob("*.wwu") if not is_skipped_path(path)]
        xml_files += [path for path in self.root.glob("*.wproj") if not is_skipped_path(path)]
        self.latest_source_mtime = latest_project_source_mtime(self.root)
        for xml_file in sorted(xml_files, key=lambda p: str(p).lower()):
            self._scan_file(xml_file)

        self.object_count = len(self.objects_by_id)
        self._build_candidates()

    def _category_for(self, xml_file: Path) -> str:
        try:
            rel = xml_file.relative_to(self.root)
        except ValueError:
            return ""
        if len(rel.parts) > 1:
            return rel.parts[0]
        return ""

    def _workunit_for(self, xml_file: Path) -> str:
        try:
            return str(xml_file.relative_to(self.root)).replace("/", "\\")
        except ValueError:
            return str(xml_file)

    def _full_path_for(self, category: str, xml_path: str) -> str:
        xml_path = normalize_wwise_path(xml_path)
        if not category:
            return xml_path
        return normalize_wwise_path("\\" + category + xml_path)

    def _is_object_element(self, elem: ET.Element) -> bool:
        tag = local_name(elem.tag)
        if tag in NON_OBJECT_TAGS:
            return False
        if elem.attrib.get("ID") and ("Name" in elem.attrib or tag == "Action"):
            return True
        return False

    def _scan_file(self, xml_file: Path) -> None:
        try:
            tree = ET.parse(xml_file)
        except Exception as exc:
            self.errors.append(f"{xml_file}: XML parse failed: {exc}")
            return

        self.file_count += 1
        category = self._category_for(xml_file)
        workunit = self._workunit_for(xml_file)
        root = tree.getroot()

        def walk(
            elem: ET.Element,
            parent_id: str | None,
            path_parts: list[str],
        ) -> None:
            tag = local_name(elem.tag)
            current_parent = parent_id
            current_parts = path_parts
            if self._is_object_element(elem):
                obj_id = elem.attrib.get("ID", "")
                obj_name = elem.attrib.get("Name", "")
                display_name = obj_name or f"{tag}:{elem.attrib.get('ShortID') or obj_id[:8]}"
                current_parts = path_parts + [display_name]
                xml_path = normalize_wwise_path("\\" + "\\".join(current_parts))
                full_path = self._full_path_for(category, xml_path)
                obj = ProjectObject(
                    id=obj_id,
                    name=obj_name,
                    type=tag,
                    xml_path=xml_path,
                    full_path=full_path,
                    workunit=workunit,
                    source_file=xml_file,
                    parent_id=parent_id,
                    properties=self._direct_properties(elem),
                    references=self._direct_references(elem),
                    audio_file=self._audio_file(elem),
                )
                self.objects_by_id[obj_id] = obj
                self.objects_by_full_path[full_path] = obj
                self.workunits[workunit].append(obj_id)
                if parent_id and parent_id in self.objects_by_id:
                    self.objects_by_id[parent_id].children_ids.append(obj_id)
                current_parent = obj_id

            for child in list(elem):
                walk(child, current_parent, current_parts)

        walk(root, None, [])

    def _direct_properties(self, elem: ET.Element) -> dict[str, str]:
        result: dict[str, str] = {}
        for prop in elem.findall("./PropertyList/Property"):
            name = prop.attrib.get("Name", "")
            if not name:
                continue
            if "Value" in prop.attrib:
                result[name] = prop.attrib.get("Value", "")
                continue
            values = [value.text or "" for value in prop.findall("./ValueList/Value")]
            result[name] = ", ".join(values)
        return result

    def _direct_references(self, elem: ET.Element) -> list[dict[str, str]]:
        refs: list[dict[str, str]] = []
        for ref in elem.findall("./ReferenceList/Reference"):
            ref_name = ref.attrib.get("Name", "")
            obj_ref = ref.find("./ObjectRef")
            if obj_ref is None:
                continue
            refs.append(
                {
                    "reference": ref_name,
                    "name": obj_ref.attrib.get("Name", ""),
                    "id": obj_ref.attrib.get("ID", ""),
                    "workunit_id": obj_ref.attrib.get("WorkUnitID", ""),
                }
            )
        return refs

    def _audio_file(self, elem: ET.Element) -> str:
        audio = elem.find("./AudioFile")
        if audio is not None and audio.text:
            return audio.text.strip()
        return ""

    def _build_candidates(self) -> None:
        for obj in self.objects_by_id.values():
            if obj.type in LEAF_TEMPLATE_TYPES or obj.type == "WorkUnit":
                continue
            if obj.type not in TEMPLATE_ROOT_TYPES:
                continue
            descendant_count = len(self.descendants(obj.id))
            if descendant_count <= 0:
                continue
            self.candidates_by_workunit[obj.workunit].append(obj)

        for workunit, items in self.candidates_by_workunit.items():
            items.sort(key=lambda obj: (obj.full_path.count("\\"), obj.full_path.lower()))

    def descendants(self, obj_id: str) -> list[ProjectObject]:
        result: list[ProjectObject] = []

        def visit(oid: str) -> None:
            obj = self.objects_by_id.get(oid)
            if not obj:
                return
            for child_id in obj.children_ids:
                child = self.objects_by_id.get(child_id)
                if not child:
                    continue
                result.append(child)
                visit(child_id)

        visit(obj_id)
        return result

    def children(self, obj_id: str) -> list[ProjectObject]:
        obj = self.objects_by_id.get(obj_id)
        if not obj:
            return []
        return [self.objects_by_id[cid] for cid in obj.children_ids if cid in self.objects_by_id]

    def manifest_for(self, obj_id: str) -> TemplateManifest:
        root = self.objects_by_id[obj_id]
        all_objects = [root] + self.descendants(obj_id)
        objects = [root] + [
            obj
            for obj in all_objects[1:]
            if obj.type not in NON_COPYABLE_CHILD_TYPES
        ]
        all_object_ids = {obj.id for obj in all_objects}
        object_ids = {obj.id for obj in objects}
        counts = Counter(obj.type for obj in objects)
        audio_files = [obj.audio_file for obj in objects if obj.audio_file]
        events = self._events_for_ids(object_ids)
        external_refs: Counter = Counter()
        warnings: list[str] = []

        for obj in objects:
            for ref in obj.references:
                ref_id = ref.get("id", "")
                if ref_id and ref_id not in all_object_ids:
                    external_refs[ref.get("reference", "Reference")] += 1

        ignored_internal_count = len(all_objects) - len(objects)
        if ignored_internal_count:
            warnings.append(
                f"已忽略 {ignored_internal_count} 个 XML 内部实现节点，用于匹配 WAAPI 实际复制对象数。"
            )
        if audio_files:
            warnings.append(
                f"模板内含 {len(audio_files)} 个资源源文件；默认创建会保留 Sound 内容骨架并删除复制出的 AudioFileSource 源引用，只有勾选“复制资源引用”才会保留可播放源引用。"
            )
        if not events:
            warnings.append("没有找到引用该模板对象的 Event；如果需要 API 触发，需要手动选择或后续补 Event。")
        event_groups = group_template_events(events)
        multi_target_event_count = sum(1 for group in event_groups if len(group) > 1)
        if multi_target_event_count:
            warnings.append(
                f"{multi_target_event_count} 个关联 Event 内有多个 Action 指向模板对象；创建时会每个 Event 只复制一次并重映射全部相关 Action。"
            )
        if external_refs:
            warnings.append(
                "存在外部引用，会保持指向原工程对象："
                + ", ".join(f"{key} x{value}" for key, value in external_refs.most_common())
            )

        names_with_token = sum(1 for obj in objects if root.name and root.name in obj.name)
        if root.name and names_with_token <= 1 and len(objects) > 3:
            warnings.append(f"只有少量对象名包含替换词 `{root.name}`，创建前建议检查命名规则。")

        return TemplateManifest(root, objects, events, counts, warnings, external_refs, audio_files)

    def _events_for_ids(self, object_ids: set[str]) -> list[TemplateEvent]:
        result: list[TemplateEvent] = []
        for event in self.objects_by_id.values():
            if event.type != "Event":
                continue
            for action in self.descendants(event.id):
                if action.type != "Action":
                    continue
                for ref in action.references:
                    if ref.get("reference") == "Target" and ref.get("id") in object_ids:
                        result.append(
                            TemplateEvent(
                                event=event,
                                action=action,
                                target_id=ref.get("id", ""),
                                target_name=ref.get("name", ""),
                                action_type=action.properties.get("ActionType", "1"),
                            )
                        )
        result.sort(key=lambda item: item.event.full_path.lower())
        return result


class Registry:
    def __init__(self, path: Path):
        self.path = path
        self.items: list[dict[str, Any]] = []
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            self.items = []
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8-sig"))
            self.items = list(data.get("templates", []))
        except Exception:
            self.items = []

    def save(self) -> None:
        data = {"templates": self.items, "updated": now_stamp()}
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def mark(self, manifest: TemplateManifest, replace_token: str) -> None:
        item = {
            "name": manifest.root.name,
            "source_path": manifest.root.full_path,
            "source_id": manifest.root.id,
            "workunit": manifest.root.workunit,
            "replace_token": replace_token,
            "object_count": len(manifest.objects),
            "event_count": len(group_template_events(manifest.events)),
            "updated": now_stamp(),
        }
        self.items = [x for x in self.items if x.get("source_path") != manifest.root.full_path]
        self.items.append(item)
        self.items.sort(key=lambda x: (x.get("workunit", ""), x.get("source_path", "")))
        self.save()

    def by_path(self) -> dict[str, dict[str, Any]]:
        return {item.get("source_path", ""): item for item in self.items}


class WaapiTemplateCreateError(RuntimeError):
    def __init__(self, message: str, log: list[str]):
        super().__init__(message)
        self.log = list(log)


class WaapiTemplateExecutor:
    def __init__(self, url: str):
        try:
            from waapi import WaapiClient
        except Exception as exc:  # pragma: no cover - depends on local install
            raise RuntimeError(f"无法导入 waapi Python 包：{exc}") from exc
        self.WaapiClient = WaapiClient
        self.url = url

    def run(
        self,
        manifest: TemplateManifest,
        target_parent_path: str,
        replace_token: str,
        new_name: str,
        create_events: bool,
        event_parent_path: str,
        update_existing_events: bool,
        save_project: bool,
        copy_sources: bool = False,
    ) -> list[str]:
        log: list[str] = []
        target_parent_path = normalize_wwise_path(target_parent_path)
        event_parent_path = normalize_wwise_path(event_parent_path)
        new_name = new_name.strip()
        replace_token = replace_token.strip()
        if not new_name:
            raise ValueError("新名称不能为空。")
        if not target_parent_path:
            raise ValueError("目标父级路径不能为空。")

        # WaapiClient.__init__ calls asyncio.get_event_loop(), which raises
        # "There is no current event loop in thread ..." on Python 3.12+ when run
        # from a worker thread (this method runs off the Tk main thread). Ensure
        # this thread has an event loop before connecting.
        try:
            asyncio.get_event_loop()
        except RuntimeError:
            asyncio.set_event_loop(asyncio.new_event_loop())

        with self.WaapiClient(url=self.url) as client:
            self.client = client
            created_ids: list[str] = []
            info = self.call("ak.wwise.core.getInfo", {})
            version = ((info or {}).get("version") or {}).get("displayName", "")
            session_id = (info or {}).get("sessionId", "")
            log.append(f"WAAPI connected: {version} session={session_id}")
            undo_open = False
            try:
                self._begin_undo()
                undo_open = True
                result = self._copy_and_rename(
                    manifest=manifest,
                    target_parent_path=target_parent_path,
                    replace_token=replace_token,
                    new_name=new_name,
                    log=log,
                    created_ids=created_ids,
                    copy_sources=copy_sources,
                )
                if create_events:
                    self._copy_events(
                        manifest=manifest,
                        source_to_copy=result["source_to_copy"],
                        replace_token=replace_token,
                        new_name=new_name,
                        event_parent_path=event_parent_path,
                        update_existing=update_existing_events,
                        log=log,
                        created_ids=created_ids,
                    )
                live_root = self._validate_created_id(manifest, result["new_root_id"], log, copy_sources=copy_sources)
                log.append(f"LIVE_CREATED_PATH: {live_root.get('path', result['new_root_path'])}")
                if save_project:
                    self.call("ak.wwise.core.project.save", {"autoCheckOutToSourceControl": False})
                    log.append("Saved Wwise project.")
                    saved_root = self.get_id(result["new_root_id"])
                    if not saved_root:
                        raise RuntimeError(f"Post-save validation failed: cannot resolve new object id {result['new_root_id']}")
                    log.append(f"Post-save live validation OK: {saved_root.get('path', result['new_root_path'])}")
                else:
                    log.append("Not saved. Wwise live session was changed, but .wwu files will not update until the project is saved.")
                self._end_undo("Wwise template instantiate")
                undo_open = False
            except Exception as exc:
                try:
                    self._cleanup_created_objects(created_ids, log)
                except Exception as cleanup_exc:
                    log.append(f"WARNING: cleanup after failure did not fully complete: {cleanup_exc}")
                if undo_open:
                    try:
                        self._cancel_undo()
                        log.append("Cancelled Wwise undo group after failure.")
                    except Exception as cancel_exc:
                        log.append(f"WARNING: undo cancel after failure did not complete: {cancel_exc}")
                log.append(f"ERROR: {exc}")
                raise WaapiTemplateCreateError(str(exc), log) from exc
        return log

    def call(self, uri: str, args: dict[str, Any], options: dict[str, Any] | None = None) -> Any:
        if options is None:
            return self.client.call(uri, args)
        return self.client.call(uri, args, options=options)

    def _begin_undo(self) -> None:
        self.call("ak.wwise.core.undo.beginGroup", {})

    def _end_undo(self, name: str) -> None:
        self.call("ak.wwise.core.undo.endGroup", {"displayName": name})

    def _cancel_undo(self) -> None:
        self.call("ak.wwise.core.undo.cancelGroup", {})

    def _copied_object_id(self, copied: Any) -> str:
        if isinstance(copied, dict):
            if copied.get("id"):
                return str(copied["id"])
            for key in ("objects", "return"):
                items = copied.get(key)
                if isinstance(items, list) and items and isinstance(items[0], dict) and items[0].get("id"):
                    return str(items[0]["id"])
        raise RuntimeError(f"WAAPI object.copy returned no object id: {copied!r}")

    def get_path(self, path: str) -> dict[str, Any] | None:
        try:
            result = self.call(
                "ak.wwise.core.object.get",
                {"from": {"path": [normalize_wwise_path(path)]}, "options": {"return": WAAPI_RETURN}},
            )
        except Exception:
            return None
        items = (result or {}).get("return", [])
        return items[0] if items else None

    def get_id(self, obj_id: str) -> dict[str, Any] | None:
        result = self.call(
            "ak.wwise.core.object.get",
            {"from": {"id": [obj_id]}, "options": {"return": WAAPI_RETURN}},
        )
        items = (result or {}).get("return", [])
        return items[0] if items else None

    def children(self, obj_id: str) -> list[dict[str, Any]]:
        result = self.call(
            "ak.wwise.core.object.get",
            {
                "from": {"id": [obj_id]},
                "transform": [{"select": ["children"]}],
                "options": {"return": WAAPI_RETURN},
            },
        )
        return (result or {}).get("return", [])

    def child_named(self, parent_id: str, name: str) -> dict[str, Any] | None:
        for child in self.children(parent_id):
            if child.get("name") == name:
                return child
        return None

    def descendants(self, obj_id: str) -> list[dict[str, Any]]:
        result = self.call(
            "ak.wwise.core.object.get",
            {
                "from": {"id": [obj_id]},
                "transform": [{"select": ["descendants"]}],
                "options": {"return": WAAPI_RETURN},
            },
        )
        return (result or {}).get("return", [])

    def _copy_and_rename(
        self,
        manifest: TemplateManifest,
        target_parent_path: str,
        replace_token: str,
        new_name: str,
        log: list[str],
        created_ids: list[str] | None = None,
        copy_sources: bool = False,
    ) -> dict[str, Any]:
        source = self.get_path(manifest.root.full_path)
        if not source:
            raise RuntimeError(f"Wwise 中找不到模板源对象：{manifest.root.full_path}")
        target_parent = self.get_path(target_parent_path)
        if not target_parent:
            raise RuntimeError(f"Wwise 中找不到目标父级：{target_parent_path}")

        root_name = preview_root_name(manifest, replace_token, new_name)
        new_root_path = join_wwise_path(target_parent_path, root_name)
        existing = self.child_named(target_parent["id"], root_name)
        if existing:
            raise RuntimeError(f"目标对象已存在，停止创建：{new_root_path}")

        copied = self.call(
            "ak.wwise.core.object.copy",
            {
                "object": source["id"],
                "parent": target_parent["id"],
                "onNameConflict": "rename",
                "autoCheckOutToSourceControl": False,
                "autoAddToSourceControl": False,
            },
            options={"return": WAAPI_RETURN},
        )
        copied_root_id = self._copied_object_id(copied)
        log.append(f"object.copy returned root id: {copied_root_id}")
        if created_ids is not None:
            created_ids.append(copied_root_id)
        copied_root = self.get_id(copied_root_id) or copied
        log.append(f"Copied live root before rename: {copied_root.get('path', copied_root_id)}")
        copied_nodes = [copied_root] + self.descendants(copied_root["id"])

        source_by_rel = {
            relative_under(obj.full_path, manifest.root.full_path): obj
            for obj in manifest.objects
        }
        copy_by_rel: dict[str, dict[str, Any]] = {}
        for copied_node in copied_nodes:
            rel = relative_under(copied_node.get("path", ""), copied_root.get("path", ""))
            copy_by_rel[rel] = copied_node

        source_to_copy: dict[str, str] = {}
        for rel, source_obj in source_by_rel.items():
            copied_node = copy_by_rel.get(rel)
            if not copied_node:
                log.append(f"警告：复制后未找到相对路径 `{rel}`，跳过映射。")
                continue
            source_to_copy[source_obj.id] = copied_node["id"]

        renamed = 0
        for rel, source_obj in sorted(source_by_rel.items(), key=lambda item: item[0].count("\\"), reverse=True):
            copied_node = copy_by_rel.get(rel)
            if not copied_node:
                continue
            desired = rename_with_token(source_obj.name, replace_token, new_name, force_root=(rel == ""))
            if desired and copied_node.get("name") != desired:
                self.call("ak.wwise.core.object.setName", {"object": copied_node["id"], "value": desired})
                renamed += 1

        resolved_root = self.child_named(target_parent["id"], root_name)
        if resolved_root:
            copied_root = self.get_id(resolved_root["id"]) or resolved_root
            log.append(f"Live root resolved after rename: {copied_root.get('path', new_root_path)}")
        else:
            copied_root = self.get_id(copied_root["id"]) or copied_root
            raise RuntimeError(
                f"创建后没有在目标父级下找到根对象 `{root_name}`；"
                f"当前 live root 是 `{copied_root.get('path', copied_root.get('id', ''))}`。"
            )
        if copy_sources:
            log.append("Resource references kept: copied AudioFileSource objects still point to template source files.")
        else:
            removed_sources = self._delete_resource_reference_objects(copied_root["id"], log)
            log.append(f"Resource references removed: deleted {removed_sources} copied AudioFileSource object(s); Sound objects were kept.")
        actual_root_path = copied_root.get("path") or new_root_path
        log.append(f"Copied template object: {manifest.root.full_path} -> {actual_root_path}")
        log.append(f"Renamed objects: {renamed}")
        return {"source_to_copy": source_to_copy, "new_root_path": actual_root_path, "new_root_id": copied_root["id"]}

    def _copy_events(
        self,
        manifest: TemplateManifest,
        source_to_copy: dict[str, str],
        replace_token: str,
        new_name: str,
        event_parent_path: str,
        update_existing: bool,
        log: list[str],
        created_ids: list[str] | None = None,
    ) -> None:
        copied_events = 0
        event_groups = group_template_events(manifest.events)
        for event_group in event_groups:
            event_ref = event_group[0]
            event = event_ref.event
            parent_path = event_parent_path or parent_wwise_path(event.full_path)
            if not parent_path:
                log.append(f"跳过 Event `{event.name}`：缺少目标 Event 父级。")
                continue
            parent = self.get_path(parent_path)
            if not parent:
                raise RuntimeError(f"Wwise 中找不到 Event 父级：{parent_path}")

            source_event = self.get_path(event.full_path)
            if not source_event:
                raise RuntimeError(f"Wwise 中找不到源 Event：{event.full_path}")

            new_event_name = event_name_for_copy(event.name, replace_token, new_name)
            new_event_path = join_wwise_path(parent_path, new_event_name)
            existing = self.child_named(parent["id"], new_event_name)

            if existing:
                if not update_existing:
                    raise RuntimeError(f"Event 已存在，停止创建：{new_event_path}")
                event_copy = existing
                log.append(f"使用已有 Event 并更新 Target：{new_event_path}")
            else:
                copied = self.call(
                    "ak.wwise.core.object.copy",
                    {
                        "object": source_event["id"],
                        "parent": parent["id"],
                        "onNameConflict": "rename",
                        "autoCheckOutToSourceControl": False,
                        "autoAddToSourceControl": False,
                    },
                    options={"return": WAAPI_RETURN},
                )
                event_copy_id = self._copied_object_id(copied)
                log.append(f"Event object.copy returned id: {event_copy_id}")
                if created_ids is not None:
                    created_ids.append(event_copy_id)
                event_copy = self.get_id(event_copy_id) or copied
                if event_copy.get("name") != new_event_name:
                    self.call("ak.wwise.core.object.setName", {"object": event_copy["id"], "value": new_event_name})
                    event_copy = self.get_id(event_copy["id"]) or event_copy
                log.append(f"Live Event resolved after rename: {event_copy.get('path', new_event_path)}")
                copied_events += 1

            actions = [item for item in self.descendants(event_copy["id"]) if item.get("type") == "Action"]
            retargeted = 0
            external_targets: list[str] = []
            for action in actions:
                target_id = safe_ref_id(action.get("@Target"))
                if not target_id:
                    continue
                new_target_id = source_to_copy.get(target_id)
                if not new_target_id:
                    target = action.get("@Target")
                    if isinstance(target, dict):
                        external_targets.append(str(target.get("name") or target.get("id") or target_id))
                    else:
                        external_targets.append(target_id)
                    continue
                self.call(
                    "ak.wwise.core.object.setReference",
                    {"object": action["id"], "reference": "Target", "value": new_target_id},
                )
                retargeted += 1
            if len(event_group) > 1:
                log.append(f"Event `{new_event_name}` 源模板含 {len(event_group)} 个内部 Target，已按单个 Event 处理。")
            log.append(f"Event `{new_event_name}` target 重映射：{retargeted} 个 Action")
            if external_targets:
                unique_targets = sorted(set(external_targets))
                preview = ", ".join(unique_targets[:6])
                if len(unique_targets) > 6:
                    preview += ", ..."
                log.append(f"Event `{new_event_name}` 保留 {len(external_targets)} 个模板外部 Target：{preview}")

        if manifest.events:
            log.append(f"已复制 Event：{copied_events} 个")

    def _cleanup_created_objects(self, created_ids: list[str], log: list[str]) -> None:
        seen: set[str] = set()
        for obj_id in reversed(created_ids):
            if obj_id in seen:
                continue
            seen.add(obj_id)
            obj = self.get_id(obj_id)
            if not obj:
                continue
            path = obj.get("path") or obj_id
            self.call("ak.wwise.core.object.delete", {"object": obj_id})
            log.append(f"Cleaned up created object after failure: {path}")

    def _delete_resource_reference_objects(self, root_id: str, log: list[str]) -> int:
        removed = 0
        for _attempt in range(5):
            sources = [item for item in self.descendants(root_id) if item.get("type") in RESOURCE_REFERENCE_TYPES]
            if not sources:
                break
            for source in sorted(sources, key=lambda item: item.get("path", "").count("\\"), reverse=True):
                self.call("ak.wwise.core.object.delete", {"object": source["id"]})
                removed += 1
        return removed

    def _validate_created_id(
        self,
        manifest: TemplateManifest,
        new_root_id: str,
        log: list[str],
        copy_sources: bool = False,
    ) -> dict[str, Any]:
        root = self.get_id(new_root_id)
        if not root:
            raise RuntimeError(f"Post-create validation failed: cannot resolve new object id {new_root_id}")
        log.append(f"Post-create live root resolved: {root.get('path', new_root_id)}")
        desc = self.descendants(root["id"])
        expected = len(manifest.objects) if copy_sources else len([obj for obj in manifest.objects if obj.type not in RESOURCE_REFERENCE_TYPES])
        actual = 1 + len(desc)
        if actual != expected:
            log.append(f"WARNING: object count mismatch. template={expected}, live={actual}.")
        else:
            log.append(f"Post-create validation OK: object count {actual}/{expected}.")
        return root


class WwiseTemplateApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("ProjectEF Wwise Template Generator")
        self.geometry("1500x920")
        self.minsize(1180, 760)
        self.index: WwiseProjectIndex | None = None
        self.registry = Registry(REGISTRY_FILE)
        self.current_manifest: TemplateManifest | None = None
        self._template_item_to_id: dict[str, str] = {}
        self._hierarchy_item_to_id: dict[str, str] = {}
        self._tree_scroll_state: dict[str, dict[str, Any]] = {}
        self._busy = False
        self.waapi_connected = False
        self.waapi_info: dict[str, str] = {}

        self.project_var = tk.StringVar(value=str(DEFAULT_WWISE_ROOT))
        self.waapi_var = tk.StringVar(value=DEFAULT_WAAPI_URL)
        self.filter_var = tk.StringVar()
        self.status_var = tk.StringVar(value="未扫描")
        self.waapi_status_var = tk.StringVar(value="WAAPI：未检查")
        self.source_var = tk.StringVar()
        self.replace_var = tk.StringVar()
        self.new_name_var = tk.StringVar()
        self.target_parent_var = tk.StringVar()
        self.event_parent_var = tk.StringVar()
        self.create_events_var = tk.BooleanVar(value=True)
        self.update_existing_events_var = tk.BooleanVar(value=False)
        self.save_project_var = tk.BooleanVar(value=True)
        self.copy_sources_var = tk.BooleanVar(value=False)

        self._configure_style()
        self._build_ui()
        self.waapi_var.trace_add("write", self.on_waapi_url_changed)
        self.after(200, self.scan_project)
        self.after(700, self.check_waapi)

    def _configure_style(self) -> None:
        self.configure(bg="#111821")
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("TFrame", background="#111821")
        style.configure("TLabelframe", background="#111821", foreground="#e8eef7")
        style.configure("TLabelframe.Label", background="#111821", foreground="#e8eef7")
        style.configure("TLabel", background="#111821", foreground="#e8eef7")
        style.configure("TCheckbutton", background="#111821", foreground="#e8eef7")
        style.configure("TButton", padding=(10, 5))
        style.configure("Treeview", background="#18212d", foreground="#edf4ff", fieldbackground="#18212d", rowheight=24)
        style.configure("Treeview.Heading", background="#243145", foreground="#edf4ff")
        style.map("Treeview", background=[("selected", "#2f6f9f")])

    def _attach_tree_scrollers(self, parent: tk.Widget, tree: ttk.Treeview) -> None:
        parent.rowconfigure(0, weight=1)
        parent.columnconfigure(0, weight=1)

        tree.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(parent, orient=tk.VERTICAL)
        scrollbar.grid(row=0, column=1, sticky="ns", padx=(4, 0))

        quick_slider = tk.Scale(
            parent,
            orient=tk.VERTICAL,
            from_=0,
            to=1000,
            showvalue=False,
            resolution=1,
            width=18,
            sliderlength=46,
            borderwidth=0,
            highlightthickness=0,
            background="#111821",
            troughcolor="#243145",
            activebackground="#5e9ed6",
            command=lambda value, target=tree: self._quick_scroll_tree(target, value),
        )
        quick_slider.grid(row=0, column=2, sticky="ns", padx=(6, 0))

        self._tree_scroll_state[str(tree)] = {
            "scrollbar": scrollbar,
            "quick_slider": quick_slider,
            "updating": False,
        }

        def on_yview(first: str, last: str, target: ttk.Treeview = tree) -> None:
            scrollbar.set(first, last)
            self._sync_quick_scroll_slider(target, first)

        tree.configure(yscrollcommand=on_yview)
        scrollbar.configure(command=lambda *args, target=tree: self._scroll_tree(target, *args))
        tree.bind("<Configure>", lambda _event, target=tree: self.after_idle(lambda: self._sync_quick_scroll_slider(target)), add="+")
        tree.bind("<<TreeviewOpen>>", lambda _event, target=tree: self.after_idle(lambda: self._sync_quick_scroll_slider(target)), add="+")
        tree.bind("<<TreeviewClose>>", lambda _event, target=tree: self.after_idle(lambda: self._sync_quick_scroll_slider(target)), add="+")

    def _scroll_tree(self, tree: ttk.Treeview, *args: str) -> None:
        tree.yview(*args)
        self.after_idle(lambda: self._sync_quick_scroll_slider(tree))

    def _quick_scroll_tree(self, tree: ttk.Treeview, value: str) -> None:
        state = self._tree_scroll_state.get(str(tree))
        if not state or state.get("updating"):
            return
        try:
            fraction = max(0.0, min(1.0, float(value) / 1000.0))
        except ValueError:
            return
        tree.yview_moveto(fraction)

    def _sync_quick_scroll_slider(self, tree: ttk.Treeview, first: str | float | None = None) -> None:
        state = self._tree_scroll_state.get(str(tree))
        if not state:
            return
        if first is None:
            try:
                first = tree.yview()[0]
            except tk.TclError:
                return
        slider = state["quick_slider"]
        state["updating"] = True
        try:
            slider.set(round(float(first) * 1000))
        finally:
            state["updating"] = False

    def _build_ui(self) -> None:
        top = ttk.Frame(self, padding=(10, 8))
        top.pack(fill=tk.X)

        ttk.Label(top, text="Wwise 工程").grid(row=0, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.project_var).grid(row=0, column=1, sticky="ew", padx=(6, 6))
        ttk.Button(top, text="选择", command=self.choose_project).grid(row=0, column=2, padx=(0, 6))
        ttk.Button(top, text="扫描工程", command=self.scan_project).grid(row=0, column=3, padx=(0, 6))
        ttk.Label(top, text="WAAPI").grid(row=0, column=4, sticky="w")
        ttk.Entry(top, textvariable=self.waapi_var, width=30).grid(row=0, column=5, sticky="ew", padx=(6, 6))
        ttk.Button(top, text="强制连接 / 刷新连接", command=self.check_waapi).grid(row=0, column=6, padx=(0, 6))
        ttk.Label(top, textvariable=self.waapi_status_var).grid(row=0, column=7, sticky="e")
        ttk.Label(top, textvariable=self.status_var).grid(row=1, column=0, columnspan=8, sticky="w", pady=(4, 0))
        top.columnconfigure(1, weight=2)
        top.columnconfigure(5, weight=1)
        top.columnconfigure(7, weight=1)

        filter_bar = ttk.Frame(self, padding=(10, 0, 10, 8))
        filter_bar.pack(fill=tk.X)
        ttk.Label(filter_bar, text="过滤模板").pack(side=tk.LEFT)
        filter_entry = ttk.Entry(filter_bar, textvariable=self.filter_var)
        filter_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 8))
        filter_entry.bind("<Return>", lambda _event: self.populate_templates())
        ttk.Button(filter_bar, text="应用过滤", command=self.populate_templates).pack(side=tk.LEFT)
        ttk.Button(filter_bar, text="保存为模板", command=self.mark_template).pack(side=tk.LEFT, padx=(8, 0))

        main = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        main.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 8))

        left = ttk.Labelframe(main, text="WWU / 模板")
        template_tree_area = ttk.Frame(left)
        template_tree_area.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        self.template_tree = ttk.Treeview(template_tree_area, columns=("type", "count", "path"), show="tree headings")
        self.template_tree.heading("#0", text="模板")
        self.template_tree.heading("type", text="类型")
        self.template_tree.heading("count", text="对象")
        self.template_tree.heading("path", text="路径")
        self.template_tree.column("#0", width=250, stretch=True)
        self.template_tree.column("type", width=120, stretch=False)
        self.template_tree.column("count", width=70, stretch=False, anchor="e")
        self.template_tree.column("path", width=430, stretch=True)
        self._attach_tree_scrollers(template_tree_area, self.template_tree)
        self.template_tree.bind("<<TreeviewSelect>>", self.on_template_select)
        main.add(left, weight=4)

        middle = ttk.Labelframe(main, text="层级预览")
        hierarchy_tools = ttk.Frame(middle)
        hierarchy_tools.pack(fill=tk.X, padx=8, pady=(8, 0))
        ttk.Button(hierarchy_tools, text="设为模板根", command=self.promote_hierarchy_selection).pack(side=tk.LEFT)
        ttk.Button(hierarchy_tools, text="父级作为模板", command=self.promote_hierarchy_parent).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Label(hierarchy_tools, text="提示：双击任意节点，也会把它设为新的模板根。").pack(side=tk.LEFT, padx=(12, 0))
        hierarchy_tree_area = ttk.Frame(middle)
        hierarchy_tree_area.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        self.hierarchy_tree = ttk.Treeview(hierarchy_tree_area, columns=("type", "props", "refs"), show="tree headings")
        self.hierarchy_tree.heading("#0", text="对象")
        self.hierarchy_tree.heading("type", text="类型")
        self.hierarchy_tree.heading("props", text="属性")
        self.hierarchy_tree.heading("refs", text="引用")
        self.hierarchy_tree.column("#0", width=280, stretch=True)
        self.hierarchy_tree.column("type", width=130, stretch=False)
        self.hierarchy_tree.column("props", width=70, stretch=False, anchor="e")
        self.hierarchy_tree.column("refs", width=70, stretch=False, anchor="e")
        self._attach_tree_scrollers(hierarchy_tree_area, self.hierarchy_tree)
        self.hierarchy_tree.bind("<<TreeviewSelect>>", self.on_hierarchy_select)
        self.hierarchy_tree.bind("<Double-1>", self.promote_hierarchy_selection)
        main.add(middle, weight=4)

        right = ttk.Labelframe(main, text="模板详情 / 审核")
        self.detail_text = ScrolledText(
            right,
            height=20,
            wrap=tk.WORD,
            bg="#101720",
            fg="#edf4ff",
            insertbackground="#edf4ff",
            relief=tk.FLAT,
        )
        self.detail_text.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        main.add(right, weight=4)

        bottom = ttk.Labelframe(self, text="创建新结构", padding=(10, 8))
        bottom.pack(fill=tk.X, padx=10, pady=(0, 10))

        ttk.Label(bottom, text="模板源").grid(row=0, column=0, sticky="w")
        ttk.Entry(bottom, textvariable=self.source_var, state="readonly").grid(row=0, column=1, columnspan=5, sticky="ew", padx=(6, 12), pady=2)
        ttk.Label(bottom, text="替换词").grid(row=1, column=0, sticky="w")
        ttk.Entry(bottom, textvariable=self.replace_var, width=22).grid(row=1, column=1, sticky="ew", padx=(6, 12), pady=2)
        ttk.Label(bottom, text="新名称").grid(row=1, column=2, sticky="w")
        ttk.Entry(bottom, textvariable=self.new_name_var, width=24).grid(row=1, column=3, sticky="ew", padx=(6, 12), pady=2)
        ttk.Label(bottom, text="目标父级").grid(row=2, column=0, sticky="w")
        ttk.Entry(bottom, textvariable=self.target_parent_var).grid(row=2, column=1, columnspan=5, sticky="ew", padx=(6, 12), pady=2)
        ttk.Label(bottom, text="Event 父级").grid(row=3, column=0, sticky="w")
        ttk.Entry(bottom, textvariable=self.event_parent_var).grid(row=3, column=1, columnspan=5, sticky="ew", padx=(6, 12), pady=2)

        checks = ttk.Frame(bottom)
        checks.grid(row=4, column=1, columnspan=5, sticky="w", pady=(4, 4))
        ttk.Checkbutton(checks, text="复制/重映射 Event", variable=self.create_events_var).pack(side=tk.LEFT, padx=(0, 14))
        ttk.Checkbutton(checks, text="Event 已存在时更新", variable=self.update_existing_events_var).pack(side=tk.LEFT, padx=(0, 14))
        ttk.Checkbutton(checks, text="复制资源引用", variable=self.copy_sources_var).pack(side=tk.LEFT, padx=(0, 14))
        ttk.Checkbutton(checks, text="执行后保存工程", variable=self.save_project_var).pack(side=tk.LEFT, padx=(0, 14))

        buttons = ttk.Frame(bottom)
        buttons.grid(row=5, column=1, columnspan=5, sticky="ew", pady=(6, 0))
        ttk.Button(buttons, text="预演 / Dry Run", command=self.dry_run).pack(side=tk.LEFT)
        self.create_button = ttk.Button(buttons, text="在 Wwise 创建", command=self.execute_create)
        self.create_button.pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(buttons, text="复制目标路径", command=self.copy_target_path).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Label(buttons, text="提示：执行前请打开 Wwise 并启用 WAAPI。").pack(side=tk.LEFT, padx=(16, 0))

        bottom.columnconfigure(1, weight=1)
        bottom.columnconfigure(3, weight=1)
        bottom.columnconfigure(5, weight=2)
        self.update_create_button_state()

    def on_waapi_url_changed(self, *_args: Any) -> None:
        self.waapi_connected = False
        self.waapi_info = {}
        self.waapi_status_var.set("WAAPI：地址已改，请刷新连接")
        self.update_create_button_state()

    def set_waapi_state(self, connected: bool, message: str, info: dict[str, str] | None = None) -> None:
        self.waapi_connected = connected
        self.waapi_info = info or {}
        self.waapi_status_var.set(message)
        self.update_create_button_state()

    def update_create_button_state(self) -> None:
        if not hasattr(self, "create_button"):
            return
        can_create = (not self._busy) and self.waapi_connected and self.current_manifest is not None
        self.create_button.configure(state=tk.NORMAL if can_create else tk.DISABLED)

    def choose_project(self) -> None:
        folder = filedialog.askdirectory(initialdir=self.project_var.get() or str(DEFAULT_WWISE_ROOT))
        if folder:
            self.project_var.set(folder)
            self.scan_project()

    def set_busy(self, busy: bool, status: str | None = None) -> None:
        self._busy = busy
        if status:
            self.status_var.set(status)
        self.config(cursor="watch" if busy else "")
        self.update_create_button_state()
        self.update_idletasks()

    def scan_project(self) -> None:
        if self._busy:
            return
        root = Path(self.project_var.get().strip())
        self.set_busy(True, "扫描中...")

        def worker() -> None:
            try:
                index = WwiseProjectIndex(root)
                index.scan()
                self.after(0, lambda: self._scan_done(index, None))
            except Exception as exc:
                err = exc
                self.after(0, lambda err=err: self._scan_done(None, err))

        threading.Thread(target=worker, daemon=True).start()

    def _scan_done(self, index: WwiseProjectIndex | None, error: Exception | None) -> None:
        self.set_busy(False)
        if error:
            self.status_var.set("扫描失败")
            messagebox.showerror("扫描失败", f"{error}\n\n{traceback.format_exc(limit=4)}", parent=self)
            return
        self.index = index
        self.current_manifest = None
        self.populate_templates()
        assert index is not None
        self.status_var.set(
            f"已扫描 {index.file_count} 个 XML / {index.object_count} 个对象 / "
            f"{sum(len(v) for v in index.candidates_by_workunit.values())} 个候选模板"
        )
        self.update_create_button_state()

    def populate_templates(self) -> None:
        self.template_tree.delete(*self.template_tree.get_children())
        self._template_item_to_id.clear()
        if not self.index:
            return
        query = self.filter_var.get().strip().lower()
        registry_by_path = self.registry.by_path()

        saved_root = self.template_tree.insert("", tk.END, text="已保存模板", open=True, values=("", "", ""))
        saved_count = 0
        for item in self.registry.items:
            source_path = item.get("source_path", "")
            obj = self.index.objects_by_full_path.get(source_path)
            if not obj:
                continue
            if query and query not in obj.full_path.lower() and query not in obj.name.lower():
                continue
            item_id = self.template_tree.insert(
                saved_root,
                tk.END,
                text=obj.name,
                values=(obj.type, len(self.index.descendants(obj.id)) + 1, obj.full_path),
            )
            self._template_item_to_id[item_id] = obj.id
            saved_count += 1
        if saved_count == 0:
            self.template_tree.insert(saved_root, tk.END, text="无已保存模板", values=("", "", ""))

        for workunit in sorted(self.index.candidates_by_workunit):
            items = self.index.candidates_by_workunit[workunit]
            visible: list[ProjectObject] = []
            for obj in items:
                haystack = f"{obj.name} {obj.type} {obj.full_path} {obj.workunit}".lower()
                if query and query not in haystack:
                    continue
                visible.append(obj)
            if not visible:
                continue
            group = self.template_tree.insert("", tk.END, text=workunit, open=("Fishing.wwu" in workunit), values=("", len(visible), ""))
            for obj in visible:
                marker = "★ " if obj.full_path in registry_by_path else ""
                item_id = self.template_tree.insert(
                    group,
                    tk.END,
                    text=marker + obj.name,
                    values=(obj.type, len(self.index.descendants(obj.id)) + 1, obj.full_path),
                )
                self._template_item_to_id[item_id] = obj.id
        self.after_idle(lambda: self._sync_quick_scroll_slider(self.template_tree))

    def on_template_select(self, _event: Any = None) -> None:
        selection = self.template_tree.selection()
        if not selection or not self.index:
            return
        item_id = selection[0]
        obj_id = self._template_item_to_id.get(item_id)
        if not obj_id:
            return
        self.set_current_template(obj_id)

    def set_current_template(self, obj_id: str) -> None:
        if not self.index:
            return
        manifest = self.index.manifest_for(obj_id)
        self.current_manifest = manifest
        self.source_var.set(manifest.root.full_path)
        self.replace_var.set(suggest_replace_token(manifest.root.name, [obj.name for obj in manifest.objects]))
        if not self.new_name_var.get().strip():
            self.new_name_var.set("")
        self.target_parent_var.set(parent_wwise_path(manifest.root.full_path))
        if manifest.events:
            self.event_parent_var.set(parent_wwise_path(manifest.events[0].event.full_path))
        else:
            parts = split_wwise_path(manifest.root.full_path)
            self.event_parent_var.set("\\Events\\" + (parts[1] if len(parts) > 1 else "Default Work Unit"))
        self.populate_hierarchy(manifest)
        self.populate_detail(manifest)
        self.update_create_button_state()

    def on_hierarchy_select(self, _event: Any = None) -> None:
        if not self.index:
            return
        selection = self.hierarchy_tree.selection()
        if not selection:
            return
        obj_id = self._hierarchy_item_to_id.get(selection[0])
        obj = self.index.objects_by_id.get(obj_id or "")
        if obj:
            self.status_var.set(f"已选中层级节点：{obj.full_path}，可点“设为模板根”。")

    def promote_hierarchy_selection(self, _event: Any = None) -> None:
        if not self.index:
            return
        selection = self.hierarchy_tree.selection()
        if not selection:
            messagebox.showinfo("设为模板根", "请先在层级预览里选中一个对象。", parent=self)
            return
        obj_id = self._hierarchy_item_to_id.get(selection[0])
        if not obj_id:
            return
        self.set_current_template(obj_id)
        self.status_var.set(f"模板根已切换：{self.current_manifest.root.full_path if self.current_manifest else ''}")

    def promote_hierarchy_parent(self) -> None:
        if not self.index:
            return
        selection = self.hierarchy_tree.selection()
        if not selection:
            messagebox.showinfo("父级作为模板", "请先在层级预览里选中一个对象。", parent=self)
            return
        obj_id = self._hierarchy_item_to_id.get(selection[0])
        obj = self.index.objects_by_id.get(obj_id or "")
        if not obj or not obj.parent_id:
            messagebox.showinfo("父级作为模板", "当前对象没有可用父级。", parent=self)
            return
        parent = self.index.objects_by_id.get(obj.parent_id)
        if not parent or parent.type == "WorkUnit":
            messagebox.showinfo("父级作为模板", "当前对象的父级不是可用模板对象。", parent=self)
            return
        self.set_current_template(parent.id)
        self.status_var.set(f"模板根已切换到父级：{parent.full_path}")

    def populate_hierarchy(self, manifest: TemplateManifest) -> None:
        self.hierarchy_tree.delete(*self.hierarchy_tree.get_children())
        self._hierarchy_item_to_id.clear()
        if not self.index:
            return
        manifest_ids = manifest.object_ids

        def add(obj: ProjectObject, parent_item: str = "") -> None:
            node = self.hierarchy_tree.insert(
                parent_item,
                tk.END,
                text=obj.name or obj.type,
                values=(obj.type, len(obj.properties), len(obj.references)),
                open=(obj.id == manifest.root.id or obj.full_path.count("\\") <= manifest.root.full_path.count("\\") + 2),
            )
            self._hierarchy_item_to_id[node] = obj.id
            for child in self.index.children(obj.id):
                if child.id in manifest_ids:
                    add(child, node)

        add(manifest.root)
        self.after_idle(lambda: self._sync_quick_scroll_slider(self.hierarchy_tree))

    def populate_detail(self, manifest: TemplateManifest) -> None:
        lines: list[str] = []
        lines.append(f"模板源: {manifest.root.full_path}")
        lines.append(f"WWU: {manifest.root.workunit}")
        lines.append(f"类型: {manifest.root.type}")
        lines.append(f"对象数: {len(manifest.objects)}")
        lines.append("")
        lines.append("对象类型统计:")
        for key, value in manifest.counts.most_common():
            lines.append(f"- {key}: {value}")
        lines.append("")
        lines.append("根对象属性:")
        if manifest.root.properties:
            for key, value in sorted(manifest.root.properties.items()):
                lines.append(f"- {key}: {value}")
        else:
            lines.append("- 无直接属性")
        lines.append("")
        lines.append("根对象引用:")
        if manifest.root.references:
            for ref in manifest.root.references:
                lines.append(f"- {ref.get('reference')}: {ref.get('name')} ({ref.get('id')})")
        else:
            lines.append("- 无直接引用")
        lines.append("")
        lines.append("关联 Event:")
        if manifest.events:
            for event_group in group_template_events(manifest.events):
                event_ref = event_group[0]
                targets: list[str] = []
                seen_targets: set[str] = set()
                for item in event_group:
                    if item.target_id in seen_targets:
                        continue
                    seen_targets.add(item.target_id)
                    targets.append(item.target_name)
                target_text = ", ".join(targets)
                suffix = f" ({len(event_group)} 个内部 Target)" if len(event_group) > 1 else ""
                lines.append(
                    f"- {event_ref.event.full_path} -> {target_text}{suffix} "
                    f"(ActionType={event_ref.action_type or '1'})"
                )
        else:
            lines.append("- 未发现")
        lines.append("")
        lines.append("审核提示:")
        if manifest.warnings:
            for warning in manifest.warnings:
                lines.append(f"- {warning}")
        else:
            lines.append("- 未发现明显风险，可以作为模板候选。")
        lines.append("")
        lines.append("命名预览:")
        replace_token = self.replace_var.get().strip() or manifest.root.name
        new_name = self.new_name_var.get().strip() or "<新名称>"
        for obj in manifest.objects[:18]:
            rel = relative_under(obj.full_path, manifest.root.full_path)
            desired = rename_with_token(obj.name, replace_token, new_name, force_root=(rel == ""))
            if desired != obj.name:
                lines.append(f"- {obj.name} -> {desired}")
        if len(manifest.objects) > 18:
            lines.append(f"- ... 另有 {len(manifest.objects) - 18} 个对象")

        self.detail_text.delete("1.0", tk.END)
        self.detail_text.insert(tk.END, "\n".join(lines))

    def mark_template(self) -> None:
        if not self.current_manifest:
            messagebox.showinfo("保存模板", "请先选择一个模板候选。", parent=self)
            return
        self.registry.mark(self.current_manifest, self.replace_var.get().strip() or self.current_manifest.root.name)
        self.populate_templates()
        self.status_var.set(f"已保存模板：{self.current_manifest.root.full_path}")

    def dry_run(self) -> None:
        manifest = self.current_manifest
        if not manifest:
            messagebox.showinfo("Dry Run", "请先选择模板。", parent=self)
            return
        replace_token = self.replace_var.get().strip()
        new_name = self.new_name_var.get().strip()
        target_parent = normalize_wwise_path(self.target_parent_var.get())
        if not new_name:
            messagebox.showwarning("Dry Run", "请填写新名称。", parent=self)
            return
        if not target_parent:
            messagebox.showwarning("Dry Run", "请填写目标父级。", parent=self)
            return

        lines: list[str] = []
        lines.append("Dry Run / 将执行的创建计划")
        lines.append("=" * 72)
        root_name = preview_root_name(manifest, replace_token, new_name)
        lines.append(f"模板: {manifest.root.full_path}")
        lines.append(f"目标: {join_wwise_path(target_parent, root_name)}")
        lines.append(f"命名: {replace_token or '<空>'} -> {new_name}")
        lines.append(f"对象: {len(manifest.objects)} 个")
        if self.copy_sources_var.get():
            lines.append("资源引用: 保留模板 AudioFileSource 源引用，复制后可直接播放同一批源文件")
        else:
            source_count = sum(1 for obj in manifest.objects if obj.type in RESOURCE_REFERENCE_TYPES)
            lines.append(f"资源引用: 不复制；将删除复制出的 {source_count} 个 AudioFileSource 源引用，但保留 Sound 内容骨架")
        lines.append("")
        lines.append("对象命名预览:")
        for obj in manifest.objects[:60]:
            rel = relative_under(obj.full_path, manifest.root.full_path)
            desired = rename_with_token(obj.name, replace_token, new_name, force_root=(rel == ""))
            if desired != obj.name:
                lines.append(f"- {obj.type}: {obj.name} -> {desired}")
        if len(manifest.objects) > 60:
            lines.append(f"- ... 另有 {len(manifest.objects) - 60} 个对象")
        lines.append("")
        lines.append("Event 预览:")
        if self.create_events_var.get() and manifest.events:
            for event_group in group_template_events(manifest.events):
                event_ref = event_group[0]
                new_event = event_name_for_copy(event_ref.event.name, replace_token, new_name)
                parent_path = normalize_wwise_path(self.event_parent_var.get()) or parent_wwise_path(event_ref.event.full_path)
                targets: list[str] = []
                seen_targets: set[str] = set()
                for item in event_group:
                    if item.target_id in seen_targets:
                        continue
                    seen_targets.add(item.target_id)
                    targets.append(
                        rename_with_token(
                            item.target_name,
                            replace_token,
                            new_name,
                            force_root=(item.target_id == manifest.root.id),
                        )
                    )
                lines.append(f"- {join_wwise_path(parent_path, new_event)} -> {', '.join(targets)}")
        elif not self.create_events_var.get():
            lines.append("- 已关闭 Event 创建")
        else:
            lines.append("- 没有发现关联 Event")
        lines.append("")
        lines.append("外部引用会保持原引用:")
        if manifest.external_refs:
            for key, value in manifest.external_refs.most_common():
                lines.append(f"- {key}: {value}")
        else:
            lines.append("- 无")

        self.detail_text.delete("1.0", tk.END)
        self.detail_text.insert(tk.END, "\n".join(lines))

    def _project_changed_after_scan(self) -> bool:
        if not self.index:
            return False
        current_mtime = latest_project_source_mtime(Path(self.project_var.get().strip()))
        return current_mtime > self.index.latest_source_mtime + 0.5

    def _validate_live_selection_before_create(self, manifest: TemplateManifest) -> bool:
        if self._project_changed_after_scan():
            messagebox.showwarning(
                "模板索引已过期",
                "Wwise 工程文件在上次扫描后发生了变化。\n\n请先点击“扫描工程”，再创建新的模板实例。",
                parent=self,
            )
            self.status_var.set("工程文件已在扫描后变化；创建前需要重新扫描。")
            return False

        url = self.waapi_var.get().strip() or DEFAULT_WAAPI_URL
        try:
            executor = WaapiTemplateExecutor(url)
            with executor.WaapiClient(url=url) as client:
                root_result = client.call(
                    "ak.wwise.core.object.get",
                    {"from": {"id": [manifest.root.id]}, "options": {"return": WAAPI_RETURN}},
                ) or {}
                live_roots = root_result.get("return", [])
                if not live_roots:
                    messagebox.showwarning(
                        "模板源已失效",
                        "当前选择的模板对象在实时 Wwise 工程中已不存在。\n\n请重新扫描工程，并重新选择模板。",
                        parent=self,
                    )
                    self.status_var.set("所选模板源已不存在；需要重新扫描。")
                    return False

                live_path = normalize_wwise_path(live_roots[0].get("path", ""))
                scanned_path = normalize_wwise_path(manifest.root.full_path)
                if live_path != scanned_path:
                    messagebox.showwarning(
                        "模板源已改名或移动",
                        "当前选择的模板对象在扫描后已于 Wwise 中改名或移动。\n\n"
                        f"扫描时路径:\n{scanned_path}\n\n"
                        f"实时路径:\n{live_path}\n\n"
                        "请先重新扫描工程，并重新选择模板后再创建。",
                        parent=self,
                    )
                    self.status_var.set("所选模板源已在 Wwise 中变化；需要重新扫描。")
                    return False

                parent_path = normalize_wwise_path(self.target_parent_var.get())
                if parent_path:
                    parent_result = client.call(
                        "ak.wwise.core.object.get",
                        {"from": {"path": [parent_path]}, "options": {"return": WAAPI_RETURN}},
                    ) or {}
                    if not parent_result.get("return", []):
                        messagebox.showwarning(
                            "目标父级不存在",
                            f"目标父级在实时 Wwise 工程中不存在:\n{parent_path}\n\n请刷新工具，或选择一个有效父级。",
                            parent=self,
                        )
                        self.status_var.set("目标父级在实时 Wwise 工程中不存在。")
                        return False
        except Exception as exc:
            messagebox.showwarning(
                "实时 Wwise 校验失败",
                f"无法通过 WAAPI 校验当前模板选择:\n{exc}",
                parent=self,
            )
            self.status_var.set("创建前 WAAPI 校验失败。")
            return False
        return True

    def execute_create(self) -> None:
        if self._busy:
            return
        manifest = self.current_manifest
        if not manifest:
            messagebox.showinfo("创建", "请先选择模板。", parent=self)
            return
        new_name = self.new_name_var.get().strip()
        if not new_name:
            messagebox.showwarning("创建", "请填写新名称。", parent=self)
            return
        if not self.waapi_connected and not self.check_waapi():
            messagebox.showwarning("WAAPI 未连接", "请先打开 Wwise，并使用“强制连接 / 刷新连接”完成 WAAPI 握手。", parent=self)
            return
        if not self._validate_live_selection_before_create(manifest):
            return
        source_ref_count = sum(1 for obj in manifest.objects if obj.type in RESOURCE_REFERENCE_TYPES)
        if source_ref_count and not self.copy_sources_var.get():
            if not messagebox.askyesno(
                "确认不复制源引用",
                f"当前模板包含 {source_ref_count} 个 AudioFileSource 源引用。\n\n"
                "继续时会保留复制出的 Sound 对象和容器结构，但会移除这些源引用；"
                "如果你希望新内容能直接播放同一批模板 wav，请先勾选“复制资源引用”。\n\n"
                "继续创建结构内容？",
                parent=self,
            ):
                self.status_var.set("已取消创建；可勾选“复制资源引用”后再试。")
                return
        if not messagebox.askyesno(
            "确认创建",
            "即将在当前打开的 Wwise 工程中创建新结构。\n\n"
            f"模板: {manifest.root.full_path}\n"
            f"新名称: {new_name}\n\n"
            "建议先确认 Wwise 当前工程已保存或可撤销。继续？",
            parent=self,
        ):
            return

        self.set_busy(True, "正在通过 WAAPI 创建...")
        args = {
            "manifest": manifest,
            "target_parent_path": self.target_parent_var.get(),
            "replace_token": self.replace_var.get(),
            "new_name": new_name,
            "create_events": self.create_events_var.get(),
            "event_parent_path": self.event_parent_var.get(),
            "update_existing_events": self.update_existing_events_var.get(),
            "save_project": self.save_project_var.get(),
            "copy_sources": self.copy_sources_var.get(),
        }

        def worker() -> None:
            try:
                executor = WaapiTemplateExecutor(self.waapi_var.get().strip() or DEFAULT_WAAPI_URL)
                log = executor.run(**args)
                self.after(0, lambda: self._execute_done(log, None, bool(args["save_project"])))
            except Exception as exc:
                tb = traceback.format_exc()
                # Keep a reference: Python 3 deletes the `exc` name when the except
                # block exits, but self.after runs the lambda later. Bind via default
                # args so the completion callback (and UI unlock) always fires.
                err = exc
                log = list(getattr(exc, "log", []) or [])
                if log:
                    log.extend(["", "Traceback:", tb])
                else:
                    log = [tb]
                self.after(0, lambda log=log, err=err: self._execute_done(log, err, False))

        threading.Thread(target=worker, daemon=True).start()

    def _execute_done(self, log: list[str], error: Exception | None, saved: bool = False) -> None:
        self.set_busy(False)
        self.detail_text.delete("1.0", tk.END)
        live_path = live_created_path_from_log(log)
        report_path = write_create_report(log, error, saved, live_path)
        report_text = f"\nReport: {report_path}" if report_path else ""
        if error:
            self.status_var.set("创建失败")
            self.detail_text.insert(tk.END, "\n".join(log) + report_text)
            error_message = f"{error}\n\nReport: {report_path}" if report_path else str(error)
            messagebox.showerror("创建失败", error_message, parent=self)
            return
        if live_path:
            try:
                self.clipboard_clear()
                self.clipboard_append(live_path)
            except Exception:
                pass
        if saved:
            self.status_var.set(f"创建完成并已保存：{live_path}" if live_path else "创建完成并已保存")
        else:
            self.status_var.set(f"创建完成；未保存：{live_path}" if live_path else "创建完成；未保存工程")
        header = "创建完成"
        if live_path:
            header += f"\n最终路径: {live_path}\n已复制路径到剪贴板"
        if report_path:
            header += f"\nReport: {report_path}"
        self.detail_text.insert(tk.END, header + "\n" + "=" * 72 + "\n" + "\n".join(log))
        if saved:
            self.status_var.set(
                f"创建完成并已保存；正在刷新索引：{live_path}"
                if live_path
                else "创建完成并已保存；正在刷新索引。"
            )
            self.scan_project()
        else:
            self.status_var.set(
                f"创建完成；未保存工程，磁盘索引未刷新：{live_path}"
                if live_path
                else "创建完成；未保存工程，磁盘索引未刷新。"
            )
        self.update_create_button_state()

    def check_waapi(self) -> bool:
        url = self.waapi_var.get().strip() or DEFAULT_WAAPI_URL
        match = re.match(r"ws://([^:/]+):(\d+)/", url)
        host = match.group(1) if match else "127.0.0.1"
        port = int(match.group(2)) if match else 8080
        try:
            executor = WaapiTemplateExecutor(url)
            with executor.WaapiClient(url=url) as client:
                info = client.call("ak.wwise.core.getInfo", {}) or {}
                project = client.call("ak.wwise.core.getProjectInfo", {}) or {}
            version = ((info.get("version") or {}).get("displayName") or "").strip()
            build = str((info.get("version") or {}).get("build") or info.get("build") or "").strip()
            session_id = str(info.get("sessionId") or "").strip()
            project_name = (project.get("name") or "").strip()
            version_text = " ".join(part for part in [version, f"build {build}" if build else ""] if part)
            suffix = " / ".join(part for part in [version_text, f"sessionId={session_id}" if session_id else "", project_name] if part)
            message = f"WAAPI 已连接：{host}:{port}" + (f"（{suffix}）" if suffix else "")
            self.set_waapi_state(
                True,
                message,
                {"host": host, "port": str(port), "version": version, "build": build, "sessionId": session_id, "project": project_name},
            )
            self.status_var.set(message)
            return True
        except Exception as exc:
            try:
                with socket.create_connection((host, port), timeout=1.5):
                    pass
                message = f"WAAPI 未连接：{host}:{port} 端口可达，但握手失败：{exc}"
            except Exception:
                message = f"WAAPI 未连接：{exc}"
            self.set_waapi_state(False, message)
            self.status_var.set(message)
            return False

    def copy_target_path(self) -> None:
        new_name = self.new_name_var.get().strip()
        target_parent = self.target_parent_var.get().strip()
        if not new_name or not target_parent:
            return
        if self.current_manifest:
            root_name = preview_root_name(self.current_manifest, self.replace_var.get(), new_name)
        else:
            root_name = new_name
        path = join_wwise_path(target_parent, root_name)
        self.clipboard_clear()
        self.clipboard_append(path)
        self.status_var.set(f"已复制目标路径：{path}")

def self_check_no_gui() -> int:
    root = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_WWISE_ROOT
    started = datetime.now()
    index = WwiseProjectIndex(root)
    index.scan()
    candidate_count = sum(len(items) for items in index.candidates_by_workunit.values())
    result = {
        "status": "PASS",
        "project_root": str(root),
        "elapsed_seconds": round((datetime.now() - started).total_seconds(), 3),
        "files": index.file_count,
        "objects": index.object_count,
        "template_candidates": candidate_count,
        "scan_latest_source_mtime": index.latest_source_mtime,
        "current_latest_source_mtime": latest_project_source_mtime(root),
    }
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0


def _delete_live_path(client: Any, path: str) -> list[str]:
    result = client.call(
        "ak.wwise.core.object.get",
        {"from": {"path": [normalize_wwise_path(path)]}, "options": {"return": ["id", "path", "type"]}},
    ) or {}
    deleted: list[str] = []
    for obj in result.get("return", []):
        client.call("ak.wwise.core.object.delete", {"object": obj["id"]})
        deleted.append(obj.get("path") or path)
    return deleted


def _live_type_counts(client: Any, root_path: str) -> tuple[Counter, set[str]]:
    root_result = client.call(
        "ak.wwise.core.object.get",
        {"from": {"path": [normalize_wwise_path(root_path)]}, "options": {"return": ["id", "path", "type"]}},
    ) or {}
    roots = root_result.get("return", [])
    if not roots:
        raise RuntimeError(f"Live self-test cannot resolve created root: {root_path}")
    root = roots[0]
    desc_result = client.call(
        "ak.wwise.core.object.get",
        {
            "from": {"id": [root["id"]]},
            "transform": [{"select": ["descendants"]}],
            "options": {"return": ["id", "path", "type"]},
        },
    ) or {}
    objects = [root] + list(desc_result.get("return", []))
    return Counter(item.get("type", "") for item in objects), {item.get("id", "") for item in objects if item.get("id")}


def _event_targets(client: Any, event_path: str) -> list[str]:
    event_result = client.call(
        "ak.wwise.core.object.get",
        {"from": {"path": [normalize_wwise_path(event_path)]}, "options": {"return": ["id", "path", "type"]}},
    ) or {}
    events = event_result.get("return", [])
    if not events:
        raise RuntimeError(f"Live self-test cannot resolve copied Event: {event_path}")
    action_result = client.call(
        "ak.wwise.core.object.get",
        {
            "from": {"id": [events[0]["id"]]},
            "transform": [{"select": ["descendants"]}],
            "options": {"return": ["id", "path", "type", "@Target"]},
        },
    ) or {}
    return [safe_ref_id(item.get("@Target")) for item in action_result.get("return", []) if item.get("type") == "Action"]


def _write_live_self_test_report(result: dict[str, Any]) -> None:
    try:
        RUN_REPORT_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        json_path = RUN_REPORT_DIR / f"ProjectEF_WwiseTemplateGenerator_LiveSelfTest_{stamp}.json"
        md_path = RUN_REPORT_DIR / f"ProjectEF_WwiseTemplateGenerator_LiveSelfTest_{stamp}.md"
        result["json_report"] = str(json_path)
        result["markdown_report"] = str(md_path)
        json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        lines = [
            "# ProjectEF Wwise Template Generator Live Self-Test",
            "",
            f"- Status: `{result.get('status')}`",
            f"- Generated: `{result.get('generated')}`",
            f"- Source: `{result.get('source_path')}`",
            f"- WAAPI: `{result.get('waapi_url')}`",
            "",
            "## Cases",
            "",
        ]
        for case in result.get("cases", []):
            lines.extend(
                [
                    f"### {case.get('name')}",
                    "",
                    f"- Status: `{case.get('status')}`",
                    f"- Created path: `{case.get('live_path')}`",
                    f"- Event path: `{case.get('event_path')}`",
                    f"- Type counts: `{case.get('type_counts')}`",
                    f"- Cleanup: `{case.get('cleanup_deleted')}`",
                    "",
                ]
            )
        if result.get("errors"):
            lines.extend(["## Errors", ""])
            lines.extend(f"- {item}" for item in result["errors"])
        md_path.write_text("\n".join(lines), encoding="utf-8")
    except Exception as exc:
        result.setdefault("errors", []).append(f"Report write failed: {exc}")


def live_self_test_no_gui() -> int:
    root = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_WWISE_ROOT
    source_path = normalize_wwise_path(sys.argv[3]) if len(sys.argv) > 3 else LIVE_SELF_TEST_TEMPLATE_PATH
    started = datetime.now()
    index = WwiseProjectIndex(root)
    index.scan()
    source = index.objects_by_full_path.get(source_path)
    if not source:
        raise RuntimeError(f"Live self-test source not found in scanned project: {source_path}")
    manifest = index.manifest_for(source.id)
    if not manifest.events:
        raise RuntimeError(f"Live self-test source has no related Event: {source_path}")

    replace_token = suggest_replace_token(manifest.root.name, [obj.name for obj in manifest.objects]) or manifest.root.name
    target_parent = parent_wwise_path(manifest.root.full_path)
    event_parent = parent_wwise_path(manifest.events[0].event.full_path)
    expected_counts = Counter(obj.type for obj in manifest.objects)
    result: dict[str, Any] = {
        "status": "PASS",
        "generated": datetime.now().isoformat(timespec="seconds"),
        "project_root": str(root),
        "source_path": source_path,
        "waapi_url": DEFAULT_WAAPI_URL,
        "replace_token": replace_token,
        "cases": [],
        "errors": [],
    }

    for copy_sources, suffix in [(False, "Shell"), (True, "Refs")]:
        case: dict[str, Any] = {"name": suffix, "copy_sources": copy_sources, "status": "RUNNING"}
        name = f"CodexTemplateMediaSelfTest_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{suffix}"
        event_name = event_name_for_copy(manifest.events[0].event.name, replace_token, name)
        event_path = join_wwise_path(event_parent, event_name)
        live_path = ""
        try:
            executor = WaapiTemplateExecutor(DEFAULT_WAAPI_URL)
            log = executor.run(
                manifest=manifest,
                target_parent_path=target_parent,
                replace_token=replace_token,
                new_name=name,
                create_events=True,
                event_parent_path=event_parent,
                update_existing_events=False,
                save_project=False,
                copy_sources=copy_sources,
            )
            live_path = live_created_path_from_log(log)
            case["live_path"] = live_path
            case["event_path"] = event_path
            case["log"] = log
            with executor.WaapiClient(url=DEFAULT_WAAPI_URL) as client:
                type_counts, live_ids = _live_type_counts(client, live_path)
                targets = _event_targets(client, event_path)
                case["type_counts"] = dict(type_counts)
                case["event_target_count"] = len(targets)
                case["event_targets_in_new_tree"] = sum(1 for target in targets if target in live_ids)
                case["event_targets_stale"] = sum(1 for target in targets if target in manifest.object_ids)
                if type_counts.get("Sound", 0) != expected_counts.get("Sound", 0):
                    raise RuntimeError(
                        f"Sound count mismatch for {suffix}: live={type_counts.get('Sound', 0)}, "
                        f"expected={expected_counts.get('Sound', 0)}"
                    )
                expected_sources = expected_counts.get("AudioFileSource", 0) if copy_sources else 0
                if type_counts.get("AudioFileSource", 0) != expected_sources:
                    raise RuntimeError(
                        f"AudioFileSource count mismatch for {suffix}: "
                        f"live={type_counts.get('AudioFileSource', 0)}, expected={expected_sources}"
                    )
                if not targets or case["event_targets_in_new_tree"] < 1 or case["event_targets_stale"]:
                    raise RuntimeError(f"Event retarget validation failed for {suffix}: targets={targets}")
                case["status"] = "PASS"
        except Exception as exc:
            case["status"] = "FAIL"
            case["error"] = str(exc)
            result["status"] = "FAIL"
            result["errors"].append(str(exc))
        finally:
            cleanup_deleted: list[str] = []
            try:
                with WaapiTemplateExecutor(DEFAULT_WAAPI_URL).WaapiClient(url=DEFAULT_WAAPI_URL) as client:
                    cleanup_deleted.extend(_delete_live_path(client, event_path))
                    if live_path:
                        cleanup_deleted.extend(_delete_live_path(client, live_path))
            except Exception as cleanup_exc:
                case.setdefault("cleanup_errors", []).append(str(cleanup_exc))
                result["status"] = "FAIL"
                result["errors"].append(f"Cleanup failed for {suffix}: {cleanup_exc}")
            case["cleanup_deleted"] = cleanup_deleted
            result["cases"].append(case)

    result["elapsed_seconds"] = round((datetime.now() - started).total_seconds(), 3)
    _write_live_self_test_report(result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--self-check":
        raise SystemExit(self_check_no_gui())
    if len(sys.argv) > 1 and sys.argv[1] == "--live-self-test":
        raise SystemExit(live_self_test_no_gui())
    app = WwiseTemplateApp()
    app.mainloop()


if __name__ == "__main__":
    main()
