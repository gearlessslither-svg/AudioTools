from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .db import ROOT_DIR, PlanCategory
from .recipe import build_recipe_for_category


HANDOFF_DIR = ROOT_DIR / "handoff"
CURRENT_PLAN_PATH = HANDOFF_DIR / "current_plan.json"


def plan_to_json(title: str, requirement: str, categories: list[PlanCategory]) -> dict[str, Any]:
    def category_payload(category: PlanCategory) -> dict[str, Any]:
        style = category.recipe_style or "realistic_tactile"
        recipe = category.recipe or build_recipe_for_category(
            {
                "name": category.name,
                "direction": category.direction,
                "keywords": category.keywords,
                "recipe_style": style,
            },
            style,
        )
        return {
            "name": category.name,
            "direction": category.direction,
            "keywords": category.keywords,
            "include": category.include,
            "recipe_style": style,
            "recipe": recipe,
        }

    return {
        "title": title,
        "requirement": requirement,
        "categories": [category_payload(category) for category in categories],
    }


def categories_from_json(payload: dict[str, Any]) -> list[PlanCategory]:
    categories: list[PlanCategory] = []
    for raw in payload.get("categories", []):
        keywords = [str(item).strip() for item in raw.get("keywords", []) if str(item).strip()]
        category_dict = {
            "name": raw.get("name", ""),
            "direction": raw.get("direction", ""),
            "keywords": keywords,
            "recipe_style": raw.get("recipe_style", "realistic_tactile"),
        }
        recipe = raw.get("recipe") or build_recipe_for_category(
            category_dict,
            category_dict["recipe_style"],
        )
        categories.append(
            PlanCategory(
                name=str(raw.get("name", "")).strip(),
                direction=str(raw.get("direction", "")).strip(),
                keywords=keywords,
                include=bool(raw.get("include", True)),
                recipe=recipe,
                recipe_style=category_dict["recipe_style"],
            )
        )
    return [category for category in categories if category.name and category.keywords]


def read_plan_file(path: Path) -> tuple[str, str, list[PlanCategory]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    title = str(payload.get("title", path.stem))
    requirement = str(payload.get("requirement", ""))
    return title, requirement, categories_from_json(payload)


def write_plan_file(path: Path, title: str, requirement: str, categories: list[PlanCategory]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = plan_to_json(title, requirement, categories)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
