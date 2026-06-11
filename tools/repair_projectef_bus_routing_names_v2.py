# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from typing import Any

from waapi import WaapiClient


RET = ["id", "name", "type", "path", "parent", "childrenCount", "@OutputBus", "@OverrideOutput"]


class Wwise:
    def __init__(self, client: WaapiClient):
        self.client = client
        self.renamed: list[str] = []
        self.moved: list[str] = []
        self.created: list[str] = []
        self.deleted: list[str] = []
        self.warnings: list[str] = []

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

    def child(self, parent_id: str, name: str) -> dict[str, Any] | None:
        for item in self.children(parent_id):
            if item.get("name") == name:
                return item
        return None

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
        self.created.append(obj.get("path", name))
        return obj

    def rename(self, path: str, new_name: str) -> dict[str, Any] | None:
        obj = self.get_path(path)
        if not obj:
            return None
        if obj.get("name") == new_name:
            return obj
        before = obj.get("path", path)
        self.call("ak.wwise.core.object.setName", {"object": obj["id"], "value": new_name})
        after = self.get_id(obj["id"]) or obj
        self.renamed.append(f"{before} -> {after.get('path')}")
        return after

    def move(self, path: str, parent_id: str) -> dict[str, Any] | None:
        obj = self.get_path(path)
        if not obj:
            return None
        before = obj.get("path", path)
        r = self.call(
            "ak.wwise.core.object.move",
            {
                "object": obj["id"],
                "parent": parent_id,
                "onNameConflict": "fail",
                "autoCheckOutToSourceControl": False,
            },
        )
        after = self.get_id((r or {}).get("id", obj["id"])) or obj
        self.moved.append(f"{before} -> {after.get('path')}")
        return after

    def delete_if_empty(self, path: str) -> None:
        obj = self.get_path(path)
        if not obj:
            return
        fresh = self.get_id(obj["id"]) or obj
        if (fresh.get("childrenCount") or 0) > 0:
            self.warnings.append(f"skip delete, not empty: {fresh.get('path')}")
            return
        self.call("ak.wwise.core.object.delete", {"object": fresh["id"]})
        self.deleted.append(fresh.get("path", path))

    def save(self) -> None:
        self.call("ak.wwise.core.project.save", {})


def main() -> None:
    client = WaapiClient(url="ws://127.0.0.1:8080/waapi")
    try:
        w = Wwise(client)

        footsteps = r"\Master-Mixer Hierarchy\Default Work Unit\Master Audio Bus\MainMix\SFX\Locomotion\Footsteps"
        female = w.get_path(footsteps + r"\Female")
        male = w.get_path(footsteps + r"\Male")
        if not female or not male:
            raise RuntimeError("Missing Footsteps Female/Male bus.")

        # Repair Wwise auto-suffixed generic names into stable semantic names.
        w.rename(footsteps + r"\Female\Player_01", "Female_Player")
        w.rename(footsteps + r"\Female\Others_01", "Female_Others")
        w.rename(footsteps + r"\Female\Female_Player\Sneakers", "Female_Player_Sneakers")
        w.rename(footsteps + r"\Female\Female_Others\Sneakers_01", "Female_Others_Sneakers")
        w.rename(footsteps + r"\Male\Player_02", "Male_Player")
        w.rename(footsteps + r"\Male\Others_02", "Male_Others")
        w.rename(footsteps + r"\Male\Male_Player\Sneakers_02", "Male_Player_Sneakers")
        w.rename(footsteps + r"\Male\Male_Others\Sneakers_03", "Male_Others_Sneakers")

        clothes = r"\Master-Mixer Hierarchy\Default Work Unit\Master Audio Bus\MainMix\SFX\Locomotion\Clothes"
        clothes_obj = w.get_path(clothes)
        if not clothes_obj:
            raise RuntimeError("Missing Clothes bus after Clother rename.")
        clothes_female = w.create_bus(clothes_obj["id"], "Clothes_Female")
        clothes_male = w.create_bus(clothes_obj["id"], "Clothes_Male")

        for old_parent, old_child, new_parent, new_name in [
            ("Female_01", "Player_03", clothes_female, "Clothes_Female_Player"),
            ("Female_02", "Others_03", clothes_female, "Clothes_Female_Others"),
            ("Male_01", "Player_04", clothes_male, "Clothes_Male_Player"),
            ("Male_02", "Others_04", clothes_male, "Clothes_Male_Others"),
        ]:
            moved = w.move(clothes + "\\" + old_parent + "\\" + old_child, new_parent["id"])
            if moved:
                w.call("ak.wwise.core.object.setName", {"object": moved["id"], "value": new_name})
                after = w.get_id(moved["id"]) or moved
                w.renamed.append(f"{moved.get('path')} -> {after.get('path')}")

        for old_parent in ["Female_01", "Female_02", "Male_01", "Male_02"]:
            w.delete_if_empty(clothes + "\\" + old_parent)

        w.save()
        print(
            json.dumps(
                {
                    "created": w.created,
                    "renamed": w.renamed,
                    "moved": w.moved,
                    "deleted": w.deleted,
                    "warnings": w.warnings,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        client.disconnect()


if __name__ == "__main__":
    main()
