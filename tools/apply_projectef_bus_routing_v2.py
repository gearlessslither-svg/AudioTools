# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from waapi import WaapiClient


RET = [
    "id",
    "name",
    "type",
    "path",
    "parent",
    "childrenCount",
    "@OutputBus",
    "@Attenuation",
    "@OverrideOutput",
    "@OverridePositioning",
    "@Target",
    "@ActionType",
]


@dataclass
class Result:
    created: list[str]
    renamed: list[str]
    moved: list[str]
    routed: list[str]
    warnings: list[str]


class ProjectEFBusRouting:
    def __init__(self, client: WaapiClient):
        self.client = client
        self.result = Result([], [], [], [], [])

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

    def descendants(self, path: str) -> list[dict[str, Any]]:
        r = self.call(
            "ak.wwise.core.object.get",
            {
                "from": {"path": [path]},
                "transform": [{"select": ["descendants"]}],
                "options": {"return": RET},
            },
        )
        return (r or {}).get("return", [])

    def children(self, parent_id: str) -> list[dict[str, Any]]:
        r = self.call(
            "ak.wwise.core.object.get",
            {
                "from": {"id": [parent_id]},
                "transform": [{"select": ["children"]}],
                "options": {"return": RET},
            },
        )
        return (r or {}).get("return", [])

    def child(self, parent_id: str, name: str) -> dict[str, Any] | None:
        for item in self.children(parent_id):
            if item.get("name") == name:
                return item
        return None

    def set_name(self, obj_id: str, value: str) -> dict[str, Any]:
        before = self.get_id(obj_id)
        self.call("ak.wwise.core.object.setName", {"object": obj_id, "value": value})
        after = self.get_id(obj_id) or before or {"id": obj_id, "name": value}
        old_path = before.get("path") if before else obj_id
        self.result.renamed.append(f"{old_path} -> {after.get('path', value)}")
        return after

    def create_bus(self, parent_id: str, name: str) -> dict[str, Any]:
        existing = self.child(parent_id, name)
        if existing:
            return existing
        r = self.call(
            "ak.wwise.core.object.create",
            {
                "parent": parent_id,
                "type": "Bus",
                "name": name,
                "onNameConflict": "fail",
                "autoAddToSourceControl": False,
            },
        )
        obj = self.get_id(r["id"]) or r
        self.result.created.append(obj.get("path", name))
        return obj

    def ensure_bus_path(self, parent_path: str, names: list[str]) -> dict[str, Any]:
        cur = self.get_path(parent_path)
        if not cur:
            raise RuntimeError(f"Missing bus parent: {parent_path}")
        for name in names:
            cur = self.create_bus(cur["id"], name)
        return cur

    def move_obj(self, obj_id: str, parent_id: str, conflict: str = "fail") -> dict[str, Any]:
        before = self.get_id(obj_id)
        r = self.call(
            "ak.wwise.core.object.move",
            {
                "object": obj_id,
                "parent": parent_id,
                "onNameConflict": conflict,
                "autoCheckOutToSourceControl": False,
            },
        )
        after = self.get_id((r or {}).get("id", obj_id)) or before or {"id": obj_id}
        self.result.moved.append(f"{before.get('path') if before else obj_id} -> {after.get('path', obj_id)}")
        return after

    def set_ref(self, obj_id: str, reference: str, target_id: str) -> None:
        self.call("ak.wwise.core.object.setReference", {"object": obj_id, "reference": reference, "value": target_id})

    def set_prop(self, obj_id: str, prop: str, value: Any) -> None:
        self.call("ak.wwise.core.object.setProperty", {"object": obj_id, "property": prop, "value": value})

    def route(self, obj: dict[str, Any], bus: dict[str, Any], override_positioning: bool | None = None) -> None:
        self.set_ref(obj["id"], "OutputBus", bus["id"])
        self.set_prop(obj["id"], "OverrideOutput", True)
        if override_positioning is not None:
            self.set_prop(obj["id"], "OverridePositioning", override_positioning)
        self.result.routed.append(f"{obj['path']} -> {bus['path']}")

    def save(self) -> None:
        self.call("ak.wwise.core.project.save", {})


def setup_buses(mod: ProjectEFBusRouting) -> dict[str, dict[str, Any]]:
    bus: dict[str, dict[str, Any]] = {}

    fish_root = r"\Master-Mixer Hierarchy\Default Work Unit\Master Audio Bus\AudioObject_Ambient_3D\Fish"
    for name in ["Fish_Player", "Fish_Others", "Lure_Player", "Lure_Others"]:
        bus[name] = mod.ensure_bus_path(fish_root, [name])

    loco = r"\Master-Mixer Hierarchy\Default Work Unit\Master Audio Bus\MainMix\SFX\Locomotion"
    clother = mod.get_path(loco + r"\Clother")
    clothes = mod.get_path(loco + r"\Clothes")
    if clother and not clothes:
        clothes = mod.set_name(clother["id"], "Clothes")
    elif clother and clothes:
        mod.result.warnings.append("Both Clother and Clothes exist; using Clothes and leaving Clother untouched.")
    if not clothes:
        clothes = mod.ensure_bus_path(loco, ["Clothes"])

    footsteps = r"\Master-Mixer Hierarchy\Default Work Unit\Master Audio Bus\MainMix\SFX\Locomotion\Footsteps"
    for gender in ["Female", "Male"]:
        gender_bus = mod.ensure_bus_path(footsteps, [gender])
        player_bus = mod.create_bus(gender_bus["id"], "Player")
        others_bus = mod.create_bus(gender_bus["id"], "Others")

        legacy_sneakers = mod.child(gender_bus["id"], "Sneakers")
        player_sneakers = mod.child(player_bus["id"], "Sneakers")
        if legacy_sneakers and not player_sneakers:
            player_sneakers = mod.move_obj(legacy_sneakers["id"], player_bus["id"])
        else:
            player_sneakers = mod.create_bus(player_bus["id"], "Sneakers")
        others_sneakers = mod.create_bus(others_bus["id"], "Sneakers")

        bus[f"Footsteps_{gender}_Player"] = player_sneakers
        bus[f"Footsteps_{gender}_Others"] = others_sneakers

    for gender in ["Female", "Male"]:
        for perspective in ["Player", "Others"]:
            bus[f"Clothes_{gender}_{perspective}"] = mod.ensure_bus_path(
                clothes["path"], [gender, perspective]
            )

    return bus


def route_fishing(mod: ProjectEFBusRouting, buses: dict[str, dict[str, Any]]) -> None:
    fishing = r"\Actor-Mixer Hierarchy\Fishing"
    targets = {
        "Fish_WaterIn_Player": "Fish_Player",
        "Fish_WaterOut_Player": "Fish_Player",
        "Fish_WaterIn_Others": "Fish_Others",
        "Fish_WaterOut_Others": "Fish_Others",
        "Lure_WaterIn_Player": "Lure_Player",
        "Lure_WaterOut_Player": "Lure_Player",
        "Buzzbait_Player": "Lure_Player",
        "Lure_WaterIn_Others": "Lure_Others",
        "Lure_WaterOut_Others": "Lure_Others",
        "Buzzbait_Others": "Lure_Others",
    }
    for obj in mod.descendants(fishing):
        name = obj.get("name")
        if name in targets:
            mod.route(obj, buses[targets[name]], override_positioning=True)


GENDER_PERSPECTIVE_RE = re.compile(r"_(Female|Male)_(Player|Others)$")


def route_player(mod: ProjectEFBusRouting, buses: dict[str, dict[str, Any]]) -> None:
    player = r"\Actor-Mixer Hierarchy\Player"
    for obj in mod.descendants(player):
        name = obj.get("name", "")
        path = obj.get("path", "")
        match = GENDER_PERSPECTIVE_RE.search(name)
        if not match:
            continue
        gender, perspective = match.groups()
        if r"\Footsteps_Self\\" in path or r"\Footsteps_Self" in path:
            key = f"Footsteps_{gender}_{perspective}"
        elif r"\Clothes_Self\\" in path or r"\Clothes_Self" in path:
            key = f"Clothes_{gender}_{perspective}"
        else:
            continue
        mod.route(obj, buses[key], override_positioning=True)


def qa(mod: ProjectEFBusRouting, buses: dict[str, dict[str, Any]]) -> dict[str, Any]:
    bus_paths = {key: (mod.get_id(value["id"]) or value).get("path") for key, value in buses.items()}
    bad_routes: list[dict[str, Any]] = []

    def expected_for(obj: dict[str, Any]) -> str | None:
        name = obj.get("name", "")
        path = obj.get("path", "")
        if name in ["Fish_WaterIn_Player", "Fish_WaterOut_Player"]:
            return "Fish_Player"
        if name in ["Fish_WaterIn_Others", "Fish_WaterOut_Others"]:
            return "Fish_Others"
        if name in ["Lure_WaterIn_Player", "Lure_WaterOut_Player", "Buzzbait_Player"]:
            return "Lure_Player"
        if name in ["Lure_WaterIn_Others", "Lure_WaterOut_Others", "Buzzbait_Others"]:
            return "Lure_Others"
        match = GENDER_PERSPECTIVE_RE.search(name)
        if match and r"\Footsteps_Self" in path:
            gender, perspective = match.groups()
            return f"Footsteps_{gender}_{perspective}"
        if match and r"\Clothes_Self" in path:
            gender, perspective = match.groups()
            return f"Clothes_{gender}_{perspective}"
        return None

    for root in [r"\Actor-Mixer Hierarchy\Fishing", r"\Actor-Mixer Hierarchy\Player"]:
        for obj in mod.descendants(root):
            key = expected_for(obj)
            if not key:
                continue
            fresh = mod.get_id(obj["id"]) or obj
            output = fresh.get("@OutputBus") or {}
            expected_bus = buses[key]
            if output.get("id") != expected_bus["id"] or fresh.get("@OverrideOutput") is not True:
                bad_routes.append(
                    {
                        "path": fresh.get("path"),
                        "output": output.get("name"),
                        "expected": key,
                        "override": fresh.get("@OverrideOutput"),
                    }
                )

    events = mod.descendants(r"\Events")
    event_actions = []
    for action in events:
        target = action.get("@Target") or {}
        target_path = target.get("path", "")
        if target_path.startswith(r"\Actor-Mixer Hierarchy\Fishing") or target_path.startswith(
            r"\Actor-Mixer Hierarchy\Player"
        ):
            event_actions.append(
                {
                    "action": action.get("path"),
                    "target": target_path or target.get("name"),
                    "type": action.get("@ActionType"),
                }
            )

    return {
        "bus_paths": bus_paths,
        "created": mod.result.created,
        "renamed": mod.result.renamed,
        "moved": mod.result.moved,
        "routed_count": len(mod.result.routed),
        "bad_routes": bad_routes,
        "event_action_count": len(event_actions),
        "event_actions": event_actions,
        "warnings": mod.result.warnings,
    }


def main() -> None:
    client = WaapiClient(url="ws://127.0.0.1:8080/waapi")
    try:
        mod = ProjectEFBusRouting(client)
        buses = setup_buses(mod)
        route_fishing(mod, buses)
        route_player(mod, buses)
        mod.save()
        report = qa(mod, buses)
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        client.disconnect()


if __name__ == "__main__":
    main()
