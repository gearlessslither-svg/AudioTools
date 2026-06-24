from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .db import ROOT_DIR, PlanCategory
from .recipe import build_recipe_for_category


HANDOFF_DIR = ROOT_DIR / "handoff"
CURRENT_PLAN_PATH = HANDOFF_DIR / "current_plan.json"
CODEX_REQUEST_DIR = HANDOFF_DIR / "codex_requests"
LATEST_CODEX_REQUEST_PATH = HANDOFF_DIR / "codex_request_latest.md"


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


def write_codex_request_file(
    path: Path,
    *,
    requirement: str,
    current_plan_path: Path = CURRENT_PLAN_PATH,
    library_root: str = "",
    result_limit: int = 200,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    title_hint = requirement.strip().splitlines()[0][:80] if requirement.strip() else "Sound Finder request"
    content = f"""# Sound Finder Codex Request

Status: waiting_for_codex

## Task

Read this request, analyze the sound requirement, and write a Sound Finder plan JSON to:

```text
{current_plan_path}
```

After the JSON file is written, the Sound Finder GUI will import it and run search automatically.

## Requirement

```text
{requirement.strip()}
```

## Context

- Title hint: {title_hint}
- Sound library root: {library_root or "(use the Sound Finder active library)"}
- Result limit per category: {result_limit}

## Output Schema

Write exactly this JSON structure to `current_plan.json`:

```json
{{
  "title": "short Chinese title",
  "requirement": "original requirement text",
  "categories": [
    {{
      "name": "Chinese category or sound need name",
      "direction": "brief Chinese direction for sound design",
      "keywords": ["english search keyword", "another keyword"],
      "include": true,
      "recipe_style": "realistic_tactile",
      "recipe": [
        {{
          "name": "layer name",
          "role": "layer role",
          "keywords": ["english keyword"],
          "weight": 1.0
        }}
      ]
    }}
  ]
}}
```

## Rules

- Use English keywords because the local SFX library is indexed mostly by English filenames.
- Split the requirement into practical searchable categories, not too many tiny fragments.
- Prefer reusable game-audio layers over one-off over-specific assets.
- Keep `include` true for categories that should be searched immediately.
- Use `realistic_tactile` unless the requirement clearly needs another existing recipe style.
"""
    path.write_text(content, encoding="utf-8")
    LATEST_CODEX_REQUEST_PATH.write_text(content, encoding="utf-8")
