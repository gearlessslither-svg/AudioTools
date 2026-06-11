# -*- coding: utf-8 -*-
from __future__ import annotations

import json
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
    "@Target",
    "@ActionType",
    "@SwitchGroupOrStateGroup",
    "@DefaultSwitchOrState",
    "@Attenuation",
    "@OutputBus",
]


@dataclass
class Refs:
    perspective_group: str
    perspective_player: str
    perspective_others: str
    gender_group: str
    gender_male: str
    gender_female: str
    gear_player_att: str
    gear_others_att: str
    lure_others_att: str
    player_bus: str
    others_bus: str


class WwiseMod:
    def __init__(self, client: WaapiClient):
        self.client = client
        self.log: list[str] = []
        self.created: list[str] = []
        self.moved: list[str] = []
        self.updated_events: list[str] = []

    def call(self, uri: str, args: dict[str, Any], options: dict[str, Any] | None = None) -> Any:
        payload = dict(args)
        if options is not None:
            return self.client.call(uri, payload, options=options)
        return self.client.call(uri, payload)

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

    def descendants(self, path: str, ret: list[str] | None = None) -> list[dict[str, Any]]:
        r = self.call(
            "ak.wwise.core.object.get",
            {
                "from": {"path": [path]},
                "transform": [{"select": ["descendants"]}],
                "options": {"return": ret or RET},
            },
        )
        return (r or {}).get("return", [])

    def children(self, obj: str) -> list[dict[str, Any]]:
        r = self.call(
            "ak.wwise.core.object.get",
            {"from": {"id": [obj]}, "transform": [{"select": ["children"]}], "options": {"return": RET}},
        )
        return (r or {}).get("return", [])

    def child_by_name(self, parent_id: str, name: str) -> dict[str, Any] | None:
        for child in self.children(parent_id):
            if child.get("name") == name:
                return child
        return None

    def create(self, parent: str, type_: str, name: str) -> dict[str, Any]:
        r = self.call(
            "ak.wwise.core.object.create",
            {
                "parent": parent,
                "type": type_,
                "name": name,
                "onNameConflict": "merge" if type_ == "Folder" else "fail",
                "autoAddToSourceControl": False,
            },
        )
        obj = {"id": r["id"], "name": r["name"]}
        full = self.get_id(obj["id"]) or obj
        self.created.append(full.get("path", name))
        return full

    def ensure_folder(self, parent_path: str, name: str) -> dict[str, Any]:
        parent = self.get_path(parent_path)
        if not parent:
            raise RuntimeError(f"Missing parent: {parent_path}")
        existing = self.child_by_name(parent["id"], name)
        if existing:
            return existing
        return self.create(parent["id"], "Folder", name)

    def set_ref(self, obj: str, reference: str, value: str, quiet: bool = False) -> None:
        try:
            self.call("ak.wwise.core.object.setReference", {"object": obj, "reference": reference, "value": value})
        except Exception as exc:
            if not quiet:
                raise
            self.log.append(f"set_ref skipped: {reference} on {obj}: {exc}")

    def set_prop(self, obj: str, prop: str, value: Any, quiet: bool = True) -> None:
        try:
            self.call("ak.wwise.core.object.setProperty", {"object": obj, "property": prop, "value": value})
        except Exception as exc:
            if not quiet:
                raise
            self.log.append(f"set_prop skipped: {prop} on {obj}: {exc}")

    def set_name(self, obj: str, value: str) -> None:
        self.call("ak.wwise.core.object.setName", {"object": obj, "value": value})

    def move(self, obj: str, parent: str, name_conflict: str = "rename") -> dict[str, Any]:
        r = self.call(
            "ak.wwise.core.object.move",
            {
                "object": obj,
                "parent": parent,
                "onNameConflict": name_conflict,
                "autoCheckOutToSourceControl": False,
            },
        )
        moved = self.get_id((r or {}).get("id", obj)) or (r or {"id": obj})
        self.moved.append(moved.get("path", obj))
        return moved

    def copy(self, obj: str, parent: str) -> dict[str, Any]:
        r = self.call(
            "ak.wwise.core.object.copy",
            {
                "object": obj,
                "parent": parent,
                "onNameConflict": "rename",
                "autoCheckOutToSourceControl": False,
                "autoAddToSourceControl": False,
            },
            options={"return": RET},
        )
        self.created.append(r.get("path", obj))
        return r

    def switch_name(self, obj: dict[str, Any]) -> str | None:
        ref = obj.get("@SwitchGroupOrStateGroup") or {}
        return ref.get("name")

    def assign(self, child_id: str, switch_id: str) -> None:
        try:
            self.call("ak.wwise.core.switchContainer.addAssignment", {"child": child_id, "stateOrSwitch": switch_id})
        except Exception as exc:
            self.log.append(f"assignment skipped: {child_id} -> {switch_id}: {exc}")

    def set_branch_routing(self, obj: str, att: str | None, bus: str | None = None) -> None:
        if att:
            self.set_ref(obj, "Attenuation", att, quiet=True)
        if bus:
            self.set_ref(obj, "OutputBus", bus, quiet=True)

    def ensure_perspective_assignments(self, wrapper_id: str, player_id: str, others_id: str, refs: Refs) -> None:
        self.set_ref(wrapper_id, "SwitchGroupOrStateGroup", refs.perspective_group)
        self.set_ref(wrapper_id, "DefaultSwitchOrState", refs.perspective_player)
        self.assign(player_id, refs.perspective_player)
        self.assign(others_id, refs.perspective_others)

    def ensure_gender_assignments(self, wrapper_id: str, female_id: str, male_id: str, refs: Refs) -> None:
        self.set_ref(wrapper_id, "SwitchGroupOrStateGroup", refs.gender_group)
        self.set_ref(wrapper_id, "DefaultSwitchOrState", refs.gender_female)
        self.assign(female_id, refs.gender_female)
        self.assign(male_id, refs.gender_male)

    def wrap_perspective(
        self,
        path: str,
        refs: Refs,
        player_att: str | None,
        others_att: str | None,
        player_bus: str | None = None,
        others_bus: str | None = None,
    ) -> dict[str, Any]:
        obj = self.get_path(path)
        if not obj:
            raise RuntimeError(f"Missing target to wrap: {path}")
        name = obj["name"]
        if obj["type"] == "SwitchContainer" and self.switch_name(obj) == "Perspective":
            player = self.child_by_name(obj["id"], f"{name}_Player")
            others = self.child_by_name(obj["id"], f"{name}_Others")
            if player and others:
                self.ensure_perspective_assignments(obj["id"], player["id"], others["id"], refs)
                self.set_branch_routing(player["id"], player_att, player_bus)
                self.set_branch_routing(others["id"], others_att, others_bus)
                self.log.append(f"skip existing perspective wrapper: {obj['path']}")
                return obj

        parent_id = obj["parent"]["id"]
        old_id = obj["id"]
        player_name = f"{name}_Player"
        others_name = f"{name}_Others"

        self.set_name(old_id, player_name)
        wrapper = self.create(parent_id, "SwitchContainer", name)
        self.set_ref(wrapper["id"], "SwitchGroupOrStateGroup", refs.perspective_group)
        self.set_ref(wrapper["id"], "DefaultSwitchOrState", refs.perspective_player)

        player = self.move(old_id, wrapper["id"])
        self.set_name(player["id"], player_name)
        player = self.get_id(player["id"]) or player

        others = self.copy(player["id"], wrapper["id"])
        self.set_name(others["id"], others_name)
        others = self.get_id(others["id"]) or others

        self.set_branch_routing(player["id"], player_att, player_bus)
        self.set_branch_routing(others["id"], others_att, others_bus)
        self.ensure_perspective_assignments(wrapper["id"], player["id"], others["id"], refs)
        self.log.append(f"wrapped perspective: {path} -> {wrapper.get('path', name)}")
        return self.get_id(wrapper["id"]) or wrapper

    def create_perspective_branch(
        self,
        parent_id: str,
        name: str,
        source_leaf_id: str,
        refs: Refs,
        player_att: str | None,
        others_att: str | None,
    ) -> dict[str, Any]:
        existing = self.child_by_name(parent_id, name)
        if existing:
            return existing
        branch = self.create(parent_id, "SwitchContainer", name)
        self.set_ref(branch["id"], "SwitchGroupOrStateGroup", refs.perspective_group)
        self.set_ref(branch["id"], "DefaultSwitchOrState", refs.perspective_player)

        player = self.copy(source_leaf_id, branch["id"])
        self.set_name(player["id"], f"{name}_Player")
        player = self.get_id(player["id"]) or player
        others = self.copy(player["id"], branch["id"])
        self.set_name(others["id"], f"{name}_Others")
        others = self.get_id(others["id"]) or others
        self.set_branch_routing(player["id"], player_att)
        self.set_branch_routing(others["id"], others_att)
        self.ensure_perspective_assignments(branch["id"], player["id"], others["id"], refs)
        return self.get_id(branch["id"]) or branch

    def wrap_gender_then_perspective(
        self,
        path: str,
        refs: Refs,
        player_att: str | None,
        others_att: str | None,
    ) -> dict[str, Any]:
        obj = self.get_path(path)
        if not obj:
            raise RuntimeError(f"Missing target to wrap Gender/Perspective: {path}")
        name = obj["name"]
        if obj["type"] == "SwitchContainer" and self.switch_name(obj) == "Gender":
            female = self.child_by_name(obj["id"], f"{name}_Female")
            male = self.child_by_name(obj["id"], f"{name}_Male")
            if female and male:
                self.ensure_gender_assignments(obj["id"], female["id"], male["id"], refs)
                self.log.append(f"skip existing gender wrapper: {obj['path']}")
                return obj

        parent_id = obj["parent"]["id"]
        old_id = obj["id"]
        leaf_name = f"{name}_Female_Player"
        female_name = f"{name}_Female"
        male_name = f"{name}_Male"

        self.set_name(old_id, leaf_name)
        wrapper = self.create(parent_id, "SwitchContainer", name)
        self.set_ref(wrapper["id"], "SwitchGroupOrStateGroup", refs.gender_group)
        self.set_ref(wrapper["id"], "DefaultSwitchOrState", refs.gender_female)

        female = self.create(wrapper["id"], "SwitchContainer", female_name)
        self.set_ref(female["id"], "SwitchGroupOrStateGroup", refs.perspective_group)
        self.set_ref(female["id"], "DefaultSwitchOrState", refs.perspective_player)

        female_player = self.move(old_id, female["id"])
        self.set_name(female_player["id"], f"{female_name}_Player")
        female_player = self.get_id(female_player["id"]) or female_player
        female_others = self.copy(female_player["id"], female["id"])
        self.set_name(female_others["id"], f"{female_name}_Others")
        female_others = self.get_id(female_others["id"]) or female_others

        male = self.create(wrapper["id"], "SwitchContainer", male_name)
        self.set_ref(male["id"], "SwitchGroupOrStateGroup", refs.perspective_group)
        self.set_ref(male["id"], "DefaultSwitchOrState", refs.perspective_player)
        male_player = self.copy(female_player["id"], male["id"])
        self.set_name(male_player["id"], f"{male_name}_Player")
        male_player = self.get_id(male_player["id"]) or male_player
        male_others = self.copy(male_player["id"], male["id"])
        self.set_name(male_others["id"], f"{male_name}_Others")
        male_others = self.get_id(male_others["id"]) or male_others

        for player_obj in (female_player, male_player):
            self.set_branch_routing(player_obj["id"], player_att)
        for others_obj in (female_others, male_others):
            self.set_branch_routing(others_obj["id"], others_att)

        self.ensure_perspective_assignments(female["id"], female_player["id"], female_others["id"], refs)
        self.ensure_perspective_assignments(male["id"], male_player["id"], male_others["id"], refs)
        self.ensure_gender_assignments(wrapper["id"], female["id"], male["id"], refs)
        self.log.append(f"wrapped gender/perspective: {path} -> {wrapper.get('path', name)}")
        return self.get_id(wrapper["id"]) or wrapper

    def update_action_target(self, action_id: str, target_id: str, label: str) -> None:
        self.set_ref(action_id, "Target", target_id)
        self.updated_events.append(label)

    def actions_under(self, event_workunit_path: str) -> list[dict[str, Any]]:
        return [
            x
            for x in self.descendants(event_workunit_path, RET)
            if x.get("type") == "Action" and x.get("@Target")
        ]


def resolve_refs(mod: WwiseMod) -> Refs:
    required = {
        "perspective_group": r"\Switches\System\Perspective",
        "perspective_player": r"\Switches\System\Perspective\Player",
        "perspective_others": r"\Switches\System\Perspective\Others",
        "gender_group": r"\Switches\System\Gender",
        "gender_male": r"\Switches\System\Gender\Male",
        "gender_female": r"\Switches\System\Gender\Female",
        "gear_player_att": r"\Attenuations\Default Work Unit\Gear_Player",
        "gear_others_att": r"\Attenuations\Default Work Unit\Gear_Others",
        "lure_others_att": r"\Attenuations\Default Work Unit\Lure_Others",
        "player_bus": r"\Master-Mixer Hierarchy\Default Work Unit\Master Audio Bus\MainMix\SFX\Gear\Player",
        "others_bus": r"\Master-Mixer Hierarchy\Default Work Unit\Master Audio Bus\MainMix\SFX\Gear\Others",
    }
    ids: dict[str, str] = {}
    for key, path in required.items():
        obj = mod.get_path(path)
        if not obj:
            raise RuntimeError(f"Missing reference {key}: {path}")
        ids[key] = obj["id"]
    return Refs(**ids)


def update_fishing(mod: WwiseMod, refs: Refs) -> None:
    mod.ensure_folder(r"\Actor-Mixer Hierarchy\Fishing", "Obsolete")
    lure_others = mod.get_path(r"\Actor-Mixer Hierarchy\Fishing\Lure_Others")
    obsolete = mod.get_path(r"\Actor-Mixer Hierarchy\Fishing\Obsolete")
    if lure_others and obsolete and lure_others.get("childrenCount", 0) == 0:
        mod.move(lure_others["id"], obsolete["id"])
        mod.log.append("Fishing: moved empty Lure_Others to Obsolete")

    # Fishing was already mostly converted; normalize assignments for the known wrappers.
    for path in [
        r"\Actor-Mixer Hierarchy\Fishing\Fish\WaterIn",
        r"\Actor-Mixer Hierarchy\Fishing\Fish\WaterOut",
        r"\Actor-Mixer Hierarchy\Fishing\Lure\Lure_WaterIn",
        r"\Actor-Mixer Hierarchy\Fishing\Lure\Lure_WaterOut",
        r"\Actor-Mixer Hierarchy\Fishing\Lure\Buzzbait",
    ]:
        obj = mod.get_path(path)
        if not obj or mod.switch_name(obj) != "Perspective":
            continue
        player = None
        others = None
        for child in mod.children(obj["id"]):
            if child["name"].endswith("_Player"):
                player = child
            elif child["name"].endswith("_Others"):
                others = child
        if player and others:
            mod.ensure_perspective_assignments(obj["id"], player["id"], others["id"], refs)
            mod.log.append(f"Fishing: normalized {path}")


def update_gear(mod: WwiseMod, refs: Refs) -> None:
    obsolete = mod.ensure_folder(r"\Actor-Mixer Hierarchy\Gear", "Obsolete")

    # Move unused direct Player_Gear children to Obsolete.
    obsolete_names = [
        "Spool_Lock",
        "Spool_Open",
        "Strike_Slow_001",
        "Strike_Slow_002",
        "Strike_Slow_003",
        "Strike_Slow_004",
        "Line_Cast_Whole",
        "Line_Out",
    ]
    for name in obsolete_names:
        obj = mod.get_path(rf"\Actor-Mixer Hierarchy\Gear\Player_Gear\{name}")
        if obj:
            mod.move(obj["id"], obsolete["id"])
            mod.log.append(f"Gear: moved obsolete {name}")

    others_gear = mod.get_path(r"\Actor-Mixer Hierarchy\Gear\Others_Gear")
    if others_gear and others_gear.get("childrenCount", 0) == 0:
        mod.move(others_gear["id"], obsolete["id"])
        mod.log.append("Gear: moved empty Others_Gear")

    # Rod_Cast is currently nested under Reel_LineCast but is also targeted by a separate Event.
    rod_nested = mod.get_path(r"\Actor-Mixer Hierarchy\Gear\Player_Gear\Reel\Reel_LineCast\Rod_Cast")
    rod_direct = mod.get_path(r"\Actor-Mixer Hierarchy\Gear\Player_Gear\Reel\Rod_Cast")
    reel = mod.get_path(r"\Actor-Mixer Hierarchy\Gear\Player_Gear\Reel")
    if rod_nested and not rod_direct and reel:
        mod.move(rod_nested["id"], reel["id"])
        mod.log.append("Gear: moved Rod_Cast out from Reel_LineCast")

    targets = {
        "Reel_Retrieve": r"\Actor-Mixer Hierarchy\Gear\Player_Gear\Reel\Reel_Retrieve",
        "Reel_LineOut": r"\Actor-Mixer Hierarchy\Gear\Player_Gear\Reel\Reel_LineOut",
        "Reel_LineCast": r"\Actor-Mixer Hierarchy\Gear\Player_Gear\Reel\Reel_LineCast",
        "Rod_Cast": r"\Actor-Mixer Hierarchy\Gear\Player_Gear\Reel\Rod_Cast",
        "Reel_Close": r"\Actor-Mixer Hierarchy\Gear\Player_Gear\Reel\Reel_Close",
        "Reel_Open": r"\Actor-Mixer Hierarchy\Gear\Player_Gear\Reel\Reel_Open",
        "Reel_DragAdjust": r"\Actor-Mixer Hierarchy\Gear\Player_Gear\Reel\Reel_DragAdjust",
        "Line_Snap": r"\Actor-Mixer Hierarchy\Gear\Player_Gear\Line_Snap",
        "Line_Snap_High": r"\Actor-Mixer Hierarchy\Gear\Player_Gear\Line_Snap_High",
        "Strike_Fast": r"\Actor-Mixer Hierarchy\Gear\Player_Gear\Strike_Fast",
        "Lure_Rattle": r"\Actor-Mixer Hierarchy\Gear\Player_Gear\Lure_Rattle",
        "Reel_Broke": r"\Actor-Mixer Hierarchy\Gear\Player_Gear\Reel\Reel_Broke",
        "Rod_Broke": r"\Actor-Mixer Hierarchy\Gear\Player_Gear\Rod_Broke",
    }
    wrappers: dict[str, dict[str, Any]] = {}
    for key, path in targets.items():
        wrappers[key] = mod.wrap_perspective(
            path,
            refs,
            player_att=refs.gear_player_att,
            others_att=refs.gear_others_att,
            player_bus=refs.player_bus,
            others_bus=refs.others_bus,
        )

    for action in mod.actions_under(r"\Events\Gear"):
        target_name = (action.get("@Target") or {}).get("name")
        target_id = (action.get("@Target") or {}).get("id")
        target_obj = mod.get_id(target_id) if target_id else None
        if not target_name or not target_obj:
            continue
        for wrapper_name, wrapper in wrappers.items():
            wrapper_path = wrapper.get("path", "")
            target_path = target_obj.get("path", "")
            if target_name == wrapper_name or target_path == wrapper_path or target_path.startswith(wrapper_path + "\\"):
                label = f"Gear:{action['path']} -> {wrapper_name}"
                mod.update_action_target(action["id"], wrapper["id"], label)
                break


def update_player(mod: WwiseMod, refs: Refs) -> None:
    obsolete = mod.ensure_folder(r"\Actor-Mixer Hierarchy\Player", "Obsolete")
    for path in [
        r"\Actor-Mixer Hierarchy\Player\Footsteps_Self\Footsteps_Wet_Sneakers",
        r"\Actor-Mixer Hierarchy\Player\Footsteps_Self\Female\Sneakers\Old Footsteps",
    ]:
        obj = mod.get_path(path)
        if obj:
            mod.move(obj["id"], obsolete["id"])
            mod.log.append(f"Player: moved obsolete {obj['name']}")

    footstep_paths = [
        r"\Actor-Mixer Hierarchy\Player\Footsteps_Self\Female\Sneakers\New Footsteps\Play_Footsteps_Female_Run_Backward_Sneakers",
        r"\Actor-Mixer Hierarchy\Player\Footsteps_Self\Female\Sneakers\New Footsteps\Play_Footsteps_Female_Run_Forward_Sneakers",
        r"\Actor-Mixer Hierarchy\Player\Footsteps_Self\Female\Sneakers\New Footsteps\Play_Footsteps_Female_Walk_Backward_Sneakers",
        r"\Actor-Mixer Hierarchy\Player\Footsteps_Self\Female\Sneakers\New Footsteps\Play_Footsteps_Female_Walk_Forward_Sneakers",
    ]
    wrappers: dict[str, dict[str, Any]] = {}
    for path in footstep_paths:
        w = mod.wrap_gender_then_perspective(
            path,
            refs,
            player_att=refs.gear_player_att,
            others_att=refs.gear_others_att,
        )
        wrappers[w["name"]] = w

    clothes = mod.wrap_gender_then_perspective(
        r"\Actor-Mixer Hierarchy\Player\Clothes_Self",
        refs,
        player_att=refs.gear_player_att,
        others_att=refs.gear_others_att,
    )

    for action in mod.actions_under(r"\Events\Player"):
        target_name = (action.get("@Target") or {}).get("name")
        target_id = (action.get("@Target") or {}).get("id")
        target_obj = mod.get_id(target_id) if target_id else None
        target_path = (target_obj or {}).get("path", "")
        clothes_path = clothes.get("path", "")
        if target_name == "Clothes_Self" or target_path == clothes_path or target_path.startswith(clothes_path + "\\"):
            mod.update_action_target(action["id"], clothes["id"], f"Player:{action['path']} -> Clothes_Self")
            continue
        for wrapper_name, wrapper in wrappers.items():
            wrapper_path = wrapper.get("path", "")
            if target_name == wrapper_name or target_path == wrapper_path or target_path.startswith(wrapper_path + "\\"):
                mod.update_action_target(action["id"], wrapper["id"], f"Player:{action['path']} -> {wrapper_name}")
                break


def validate(mod: WwiseMod) -> dict[str, Any]:
    gear_actions = mod.actions_under(r"\Events\Gear")
    player_actions = mod.actions_under(r"\Events\Player")
    gear_bad = []
    player_bad = []
    for action in gear_actions:
        target = action.get("@Target") or {}
        obj = mod.get_id(target.get("id", "")) if target.get("id") else None
        if obj and obj.get("path", "").startswith(r"\Actor-Mixer Hierarchy\Gear") and mod.switch_name(obj) != "Perspective":
            gear_bad.append({"action": action["path"], "target": obj["path"], "switch": mod.switch_name(obj)})
    for action in player_actions:
        target = action.get("@Target") or {}
        obj = mod.get_id(target.get("id", "")) if target.get("id") else None
        if obj and obj.get("path", "").startswith(r"\Actor-Mixer Hierarchy\Player") and mod.switch_name(obj) != "Gender":
            player_bad.append({"action": action["path"], "target": obj["path"], "switch": mod.switch_name(obj)})
    return {
        "gearActionCount": len(gear_actions),
        "playerActionCount": len(player_actions),
        "gearBadTargets": gear_bad,
        "playerBadTargets": player_bad,
    }


def main() -> None:
    with WaapiClient(url="ws://127.0.0.1:8080/waapi") as client:
        mod = WwiseMod(client)
        refs = resolve_refs(mod)

        client.call("ak.wwise.core.undo.beginGroup", {})
        try:
            update_fishing(mod, refs)
            update_gear(mod, refs)
            update_player(mod, refs)
            validation = validate(mod)
            if validation["gearBadTargets"] or validation["playerBadTargets"]:
                raise RuntimeError("Validation failed: " + json.dumps(validation, ensure_ascii=False, indent=2))
            client.call("ak.wwise.core.undo.endGroup", {"displayName": "ProjectEF Fishing/Gear/Player 1P3P structure"})
        except Exception:
            client.call("ak.wwise.core.undo.cancelGroup", {})
            raise

        client.call("ak.wwise.core.project.save", {"autoCheckOutToSourceControl": False})

    print(
        json.dumps(
            {
                "createdCount": len(mod.created),
                "movedCount": len(mod.moved),
                "updatedEventActions": len(mod.updated_events),
                "validation": validation,
                "log": mod.log,
                "createdSample": mod.created[:40],
                "moved": mod.moved,
                "updatedEvents": mod.updated_events,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
