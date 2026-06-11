# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from waapi import WaapiClient


RET = [
    "id",
    "name",
    "type",
    "path",
    "parent",
    "childrenCount",
    "@SwitchGroupOrStateGroup",
    "@DefaultSwitchOrState",
    "@OutputBus",
    "@Attenuation",
    "@OverrideOutput",
    "@OverridePositioning",
    "@Target",
    "@ActionType",
]


ROOT_OLD = r"\Actor-Mixer Hierarchy\Player\Footsteps_Self"
ROOT_NEW = r"\Actor-Mixer Hierarchy\Player\Footsteps"
PLAYER_ROOT = r"\Actor-Mixer Hierarchy\Player"

MOVEMENTS = {
    "Play_Footsteps_Female_Run_Backward_Sneakers": "Run_Backward",
    "Play_Footsteps_Female_Run_Forward_Sneakers": "Run_Forward",
    "Play_Footsteps_Female_Walk_Backward_Sneakers": "Walk_Backward",
    "Play_Footsteps_Female_Walk_Forward_Sneakers": "Walk_Forward",
}

BUS_PATHS = {
    ("Female", "Player"): r"\Master-Mixer Hierarchy\Default Work Unit\Master Audio Bus\MainMix\SFX\Locomotion\Footsteps\Female\Female_Player\Female_Player_Sneakers",
    ("Female", "Others"): r"\Master-Mixer Hierarchy\Default Work Unit\Master Audio Bus\MainMix\SFX\Locomotion\Footsteps\Female\Female_Others\Female_Others_Sneakers",
    ("Male", "Player"): r"\Master-Mixer Hierarchy\Default Work Unit\Master Audio Bus\MainMix\SFX\Locomotion\Footsteps\Male\Male_Player\Male_Player_Sneakers",
    ("Male", "Others"): r"\Master-Mixer Hierarchy\Default Work Unit\Master Audio Bus\MainMix\SFX\Locomotion\Footsteps\Male\Male_Others\Male_Others_Sneakers",
}


@dataclass
class Log:
    renamed: list[str] = field(default_factory=list)
    moved: list[str] = field(default_factory=list)
    created: list[str] = field(default_factory=list)
    routed: list[str] = field(default_factory=list)
    props: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class Wwise:
    def __init__(self, client: WaapiClient):
        self.client = client
        self.log = Log()

    def call(self, uri: str, args: dict[str, Any]) -> Any:
        return self.client.call(uri, args)

    def get_path(self, path: str) -> dict[str, Any] | None:
        try:
            r = self.call("ak.wwise.core.object.get", {"from": {"path": [path]}, "options": {"return": RET}})
            items = (r or {}).get("return", [])
            return items[0] if items else None
        except Exception:
            return None

    def get_id(self, oid: str) -> dict[str, Any] | None:
        try:
            r = self.call("ak.wwise.core.object.get", {"from": {"id": [oid]}, "options": {"return": RET}})
            items = (r or {}).get("return", [])
            return items[0] if items else None
        except Exception:
            return None

    def children(self, oid: str) -> list[dict[str, Any]]:
        r = self.call(
            "ak.wwise.core.object.get",
            {"from": {"id": [oid]}, "transform": [{"select": ["children"]}], "options": {"return": RET}},
        )
        return (r or {}).get("return", [])

    def descendants(self, path: str) -> list[dict[str, Any]]:
        r = self.call(
            "ak.wwise.core.object.get",
            {"from": {"path": [path]}, "transform": [{"select": ["descendants"]}], "options": {"return": RET}},
        )
        return (r or {}).get("return", [])

    def child(self, parent: dict[str, Any], name: str) -> dict[str, Any] | None:
        for item in self.children(parent["id"]):
            if item.get("name") == name:
                return item
        return None

    def set_name(self, obj: dict[str, Any], new_name: str) -> dict[str, Any]:
        fresh = self.get_id(obj["id"]) or obj
        if fresh.get("name") == new_name:
            return fresh
        before = fresh.get("path", fresh.get("name", ""))
        self.call("ak.wwise.core.object.setName", {"object": fresh["id"], "value": new_name})
        after = self.get_id(fresh["id"]) or fresh
        self.log.renamed.append(f"{before} -> {after.get('path')}")
        return after

    def create_folder(self, parent: dict[str, Any], name: str) -> dict[str, Any]:
        existing = self.child(parent, name)
        if existing:
            return existing
        r = self.call(
            "ak.wwise.core.object.create",
            {
                "parent": parent["id"],
                "type": "Folder",
                "name": name,
                "onNameConflict": "merge",
                "autoAddToSourceControl": False,
            },
        )
        obj = self.get_id(r["id"]) or r
        self.log.created.append(obj.get("path", name))
        return obj

    def move(self, obj: dict[str, Any], parent: dict[str, Any], conflict: str = "fail") -> dict[str, Any]:
        fresh = self.get_id(obj["id"]) or obj
        before = fresh.get("path", fresh.get("name", ""))
        r = self.call(
            "ak.wwise.core.object.move",
            {
                "object": fresh["id"],
                "parent": parent["id"],
                "onNameConflict": conflict,
                "autoCheckOutToSourceControl": False,
            },
        )
        after = self.get_id((r or {}).get("id", fresh["id"])) or fresh
        self.log.moved.append(f"{before} -> {after.get('path')}")
        return after

    def set_ref(self, obj: dict[str, Any], reference: str, target: dict[str, Any]) -> None:
        self.call("ak.wwise.core.object.setReference", {"object": obj["id"], "reference": reference, "value": target["id"]})

    def set_prop(self, obj: dict[str, Any], prop: str, value: Any) -> None:
        fresh = self.get_id(obj["id"]) or obj
        if fresh.get("@" + prop) == value:
            return
        self.call("ak.wwise.core.object.setProperty", {"object": fresh["id"], "property": prop, "value": value})
        self.log.props.append(f"{fresh.get('path')} {prop}={value}")

    def route_leaf(self, obj: dict[str, Any], bus: dict[str, Any]) -> None:
        fresh = self.get_id(obj["id"]) or obj
        current = fresh.get("@OutputBus") or {}
        if current.get("id") != bus["id"]:
            self.set_ref(fresh, "OutputBus", bus)
        self.set_prop(fresh, "OverrideOutput", True)
        self.set_prop(fresh, "OverridePositioning", True)
        after = self.get_id(fresh["id"]) or fresh
        self.log.routed.append(f"{after.get('path')} -> {bus.get('path')}")

    def save(self) -> None:
        self.call("ak.wwise.core.project.save", {})


def ensure_root(w: Wwise) -> dict[str, Any]:
    root = w.get_path(ROOT_NEW)
    old = w.get_path(ROOT_OLD)
    if root and old:
        raise RuntimeError("Both Footsteps and Footsteps_Self exist; manual decision needed.")
    if root:
        return root
    if not old:
        raise RuntimeError("Missing Footsteps root.")
    return w.set_name(old, "Footsteps")


def cleanup_old_wrappers(w: Wwise, root: dict[str, Any], obsolete: dict[str, Any]) -> None:
    for old_name, new_name in [
        ("Female", "Footsteps_Old_Female_Wrapper"),
        ("Male", "Footsteps_Old_Male_Wrapper"),
    ]:
        obj = w.child(root, old_name)
        if not obj:
            continue
        obj = w.set_name(obj, new_name)
        w.move(obj, obsolete, conflict="rename")


def normalize_hierarchy(w: Wwise) -> dict[str, Any]:
    player = w.get_path(PLAYER_ROOT)
    if not player:
        raise RuntimeError("Missing Player root.")
    obsolete = w.create_folder(player, "Obsolete")
    root = ensure_root(w)

    female = w.child(root, "Female")
    if female:
        legacy_sneakers = w.child(female, "Sneakers")
        if legacy_sneakers and not w.child(root, "Sneakers"):
            w.move(legacy_sneakers, root)
    sneakers = w.child(root, "Sneakers")
    if not sneakers:
        raise RuntimeError("Missing or failed to create Footsteps/Sneakers.")
    sneakers = w.get_id(sneakers["id"]) or sneakers

    # The old shoe container inherited Female_Player routing from the old path. It is now generic.
    w.set_prop(sneakers, "OverrideOutput", False)

    new_folder = w.child(sneakers, "New Footsteps")
    if new_folder:
        for child in list(w.children(new_folder["id"])):
            w.move(child, sneakers, conflict="fail")
        new_folder = w.get_id(new_folder["id"]) or new_folder
        new_folder = w.set_name(new_folder, "Footsteps_Old_NewFootsteps_Folder")
        w.move(new_folder, obsolete, conflict="rename")

    cleanup_old_wrappers(w, root, obsolete)
    return w.get_id(sneakers["id"]) or sneakers


def rename_content(w: Wwise, sneakers: dict[str, Any]) -> None:
    for old_name, new_name in MOVEMENTS.items():
        obj = w.child(sneakers, old_name)
        if obj:
            w.set_name(obj, new_name)

    for movement_name in MOVEMENTS.values():
        movement = w.child(sneakers, movement_name)
        if not movement:
            w.log.warnings.append(f"Missing movement container: {movement_name}")
            continue

        for child in list(w.children(movement["id"])):
            name = child.get("name", "")
            if name.endswith("_Female"):
                w.set_name(child, "Female")
            elif name.endswith("_Male"):
                w.set_name(child, "Male")

        movement = w.get_id(movement["id"]) or movement
        for gender_name in ["Female", "Male"]:
            gender = w.child(movement, gender_name)
            if not gender:
                w.log.warnings.append(f"Missing gender branch: {movement_name}/{gender_name}")
                continue
            for child in list(w.children(gender["id"])):
                name = child.get("name", "")
                if name.endswith("_Player"):
                    w.set_name(child, "Player")
                elif name.endswith("_Others"):
                    w.set_name(child, "Others")


def reroute_leaves(w: Wwise, sneakers: dict[str, Any]) -> None:
    buses: dict[tuple[str, str], dict[str, Any]] = {}
    for key, path in BUS_PATHS.items():
        bus = w.get_path(path)
        if not bus:
            raise RuntimeError(f"Missing bus: {path}")
        buses[key] = bus

    for movement_name in MOVEMENTS.values():
        movement = w.child(sneakers, movement_name)
        if not movement:
            continue
        for gender_name in ["Female", "Male"]:
            gender = w.child(movement, gender_name)
            if not gender:
                continue
            for perspective_name in ["Player", "Others"]:
                leaf = w.child(gender, perspective_name)
                if not leaf:
                    w.log.warnings.append(f"Missing perspective branch: {movement_name}/{gender_name}/{perspective_name}")
                    continue
                w.route_leaf(leaf, buses[(gender_name, perspective_name)])


def qa(w: Wwise, sneakers: dict[str, Any]) -> dict[str, Any]:
    root = w.get_path(ROOT_NEW)
    old_root = w.get_path(ROOT_OLD)
    descendants = w.descendants(ROOT_NEW)
    bad_play_names = [
        x["path"]
        for x in descendants
        if x.get("type") in {"ActorMixer", "Folder", "SwitchContainer", "RandomSequenceContainer"}
        and x.get("name", "").startswith("Play_")
    ]
    male_under_female = [x["path"] for x in descendants if "\\Female\\" in x["path"] and re.search(r"_Male($|_)", x.get("name", ""))]

    expected_routes = {
        ("Female", "Player"): "Female_Player_Sneakers",
        ("Female", "Others"): "Female_Others_Sneakers",
        ("Male", "Player"): "Male_Player_Sneakers",
        ("Male", "Others"): "Male_Others_Sneakers",
    }
    route_errors = []
    switch_errors = []
    movement_count = 0
    leaf_count = 0

    for movement_name in MOVEMENTS.values():
        movement = w.child(sneakers, movement_name)
        if not movement:
            switch_errors.append(f"Missing movement: {movement_name}")
            continue
        movement_count += 1
        if ((movement.get("@SwitchGroupOrStateGroup") or {}).get("name") != "Gender"):
            switch_errors.append(f"{movement.get('path')} should use Gender")
        for gender_name in ["Female", "Male"]:
            gender = w.child(movement, gender_name)
            if not gender:
                switch_errors.append(f"Missing {movement_name}/{gender_name}")
                continue
            if ((gender.get("@SwitchGroupOrStateGroup") or {}).get("name") != "Perspective"):
                switch_errors.append(f"{gender.get('path')} should use Perspective")
            for perspective_name in ["Player", "Others"]:
                leaf = w.child(gender, perspective_name)
                if not leaf:
                    switch_errors.append(f"Missing {movement_name}/{gender_name}/{perspective_name}")
                    continue
                leaf_count += 1
                fresh = w.get_id(leaf["id"]) or leaf
                out = fresh.get("@OutputBus") or {}
                expected_bus = expected_routes[(gender_name, perspective_name)]
                if out.get("name") != expected_bus or fresh.get("@OverrideOutput") is not True:
                    route_errors.append(
                        {
                            "path": fresh.get("path"),
                            "bus": out.get("name"),
                            "expected": expected_bus,
                            "override": fresh.get("@OverrideOutput"),
                        }
                    )
                if ((fresh.get("@SwitchGroupOrStateGroup") or {}).get("name") != "Surface_Type"):
                    switch_errors.append(f"{fresh.get('path')} should use Surface_Type")

    # Event actions should still target the four movement containers by object ID.
    actions = w.descendants(r"\Events\Player")
    footstep_targets = []
    for action in actions:
        target = action.get("@Target") or {}
        target_name = target.get("name", "")
        if target_name in MOVEMENTS.values() or target_name in MOVEMENTS.keys():
            footstep_targets.append({"action": action.get("path"), "target": target_name})

    return {
        "root": root.get("path") if root else None,
        "old_root_exists": bool(old_root),
        "sneakers": (w.get_id(sneakers["id"]) or sneakers).get("path"),
        "movement_count": movement_count,
        "leaf_count": leaf_count,
        "bad_play_names": bad_play_names,
        "male_under_female": male_under_female,
        "route_errors": route_errors,
        "switch_errors": switch_errors,
        "footstep_event_target_count": len(footstep_targets),
        "footstep_event_targets": footstep_targets,
        "warnings": w.log.warnings,
    }


def main() -> None:
    client = WaapiClient(url="ws://127.0.0.1:8080/waapi")
    try:
        w = Wwise(client)
        sneakers = normalize_hierarchy(w)
        sneakers = w.get_id(sneakers["id"]) or sneakers
        rename_content(w, sneakers)
        sneakers = w.get_id(sneakers["id"]) or sneakers
        reroute_leaves(w, sneakers)
        w.save()
        report = {
            "changed": {
                "renamed": w.log.renamed,
                "moved": w.log.moved,
                "created": w.log.created,
                "props": w.log.props,
                "routed_count": len(w.log.routed),
            },
            "qa": qa(w, sneakers),
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        client.disconnect()


if __name__ == "__main__":
    main()
