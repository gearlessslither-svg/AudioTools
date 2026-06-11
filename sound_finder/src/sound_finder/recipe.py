from __future__ import annotations

import random
from typing import Any

from .indexer import score_file, tokens_for


STYLE_LABELS = {
    "realistic_tactile": "偏写实装备触感",
    "premium_clean": "高级干净 UI",
    "warm_casual": "轻松休闲真实物件",
    "mechanical_gear": "机械工具质感",
}


def _has(text: str, *words: str) -> bool:
    lowered = text.lower()
    return any(word.lower() in lowered for word in words)


def _base_material_keywords(category: dict[str, Any]) -> list[str]:
    keywords = list(category.get("keywords", []))
    text = f"{category.get('name', '')} {category.get('direction', '')}"

    if _has(text, "仓库", "inventory", "storage"):
        return [
            "storage box latch",
            "toolbox latch click",
            "case snap",
            "bag zipper",
            "small objects rattle",
        ] + keywords
    if _has(text, "维修", "repair", "tool"):
        return [
            "ratchet click",
            "wrench click",
            "metal tool tap",
            "screwdriver turn",
            "mechanical click",
        ] + keywords
    if _has(text, "食品", "food"):
        return [
            "snack bag crinkle",
            "paper wrapper",
            "foil rustle",
            "can tap",
            "plastic container click",
        ] + keywords
    if _has(text, "商店", "shop"):
        return [
            "shop bell ding",
            "cash register ding",
            "product pickup",
            "coin register",
            "fishing reel click",
        ] + keywords
    if _has(text, "钓场", "前往", "travel", "map"):
        return [
            "fishing rod cast",
            "fishing line cast",
            "reel spin",
            "water splash small",
            "outdoor whoosh",
        ] + keywords
    if _has(text, "设置", "setting"):
        return [
            "gear click",
            "cog wheel turn",
            "precision dial click",
            "small mechanism click",
            "metal knob turn",
        ] + keywords
    if _has(text, "货币", "购买", "coin", "purchase"):
        return [
            "coin pickup",
            "coin clink",
            "cash register",
            "purchase confirm",
            "money UI sound",
        ] + keywords
    if _has(text, "奖励", "签到", "reward"):
        return [
            "reward popup",
            "sparkle chime",
            "bonus collect",
            "achievement unlock",
            "gift open",
        ] + keywords
    return keywords


def _tail_keywords(category: dict[str, Any], style: str) -> list[str]:
    text = f"{category.get('name', '')} {category.get('direction', '')}"
    if _has(text, "前往", "钓场", "进入", "确认", "奖励", "签到", "购买"):
        if style == "mechanical_gear":
            return ["mechanical confirm", "metal snap", "ratchet finish", "short whoosh"]
        if style == "warm_casual":
            return ["soft success sound", "gentle chime", "paper whoosh", "small water splash"]
        if style == "premium_clean":
            return ["premium UI confirm", "soft digital rise", "clean success chime", "short airy whoosh"]
        return ["confirm big UI", "short success", "transition whoosh", "positive UI chime"]
    return []


def build_recipe_for_category(category: dict[str, Any], style: str = "realistic_tactile") -> list[dict[str, Any]]:
    material = _base_material_keywords(category)

    if style == "premium_clean":
        recipe = [
            {
                "name": "Click Core",
                "role": "干净短点击，负责操作手感。",
                "keywords": ["clean UI click", "soft button click", "premium interface click", "short click"],
                "weight": 1.0,
            },
            {
                "name": "Material Accent",
                "role": "保留按钮语义的真实材质点缀。",
                "keywords": material[:8],
                "weight": 1.2,
            },
            {
                "name": "Polish Sweetener",
                "role": "轻微闪光、玻璃或电子上扬，增加游戏反馈。",
                "keywords": ["soft sparkle", "digital chime", "glass UI", "positive UI blip"],
                "weight": 0.9,
            },
        ]
    elif style == "warm_casual":
        recipe = [
            {
                "name": "Soft Tap",
                "role": "更柔和的触碰层，降低硬 UI 感。",
                "keywords": ["soft tap", "cloth tap", "wood click", "gentle button click"],
                "weight": 1.0,
            },
            {
                "name": "Object Foley",
                "role": "偏生活化的物件声音，增强真实和亲切感。",
                "keywords": material[:8] + ["paper foley", "small bag foley"],
                "weight": 1.25,
            },
            {
                "name": "Friendly Lift",
                "role": "短促正反馈，适合休闲游戏界面。",
                "keywords": ["friendly UI chime", "soft success", "light positive UI", "small sparkle"],
                "weight": 0.8,
            },
        ]
    elif style == "mechanical_gear":
        recipe = [
            {
                "name": "Mechanical Click",
                "role": "机械咔哒，给按钮明确段落感。",
                "keywords": ["mechanical click", "metal switch", "gear click", "ratchet click"],
                "weight": 1.1,
            },
            {
                "name": "Tool Accent",
                "role": "金属、工具或装备结构声，强化硬核装备感。",
                "keywords": material[:8] + ["metal latch", "small metal clank"],
                "weight": 1.25,
            },
            {
                "name": "Short Servo",
                "role": "很短的机械移动或 UI 过渡，不要盖过真实层。",
                "keywords": ["servo short", "mechanical movement", "small motor", "short whoosh"],
                "weight": 0.75,
            },
        ]
    else:
        recipe = [
            {
                "name": "Click Core",
                "role": "统一的短点击核心，保证所有按钮手感一致。",
                "keywords": [
                    "realistic UI click",
                    "soft button click",
                    "plastic button press",
                    "tactile click",
                    "short foley click",
                ],
                "weight": 1.0,
            },
            {
                "name": "Material Accent",
                "role": "按钮含义对应的真实物件或材质声音。",
                "keywords": material[:8],
                "weight": 1.25,
            },
            {
                "name": "UI Sweetener",
                "role": "轻微游戏化甜味层，让反馈更清楚但不浮夸。",
                "keywords": ["positive UI blip", "soft sparkle", "short success", "menu select click"],
                "weight": 0.8,
            },
        ]

    tail = _tail_keywords(category, style)
    if tail:
        recipe.append(
            {
                "name": "Tail / Motion",
                "role": "只给重要操作的短尾音、转场或确认感。",
                "keywords": tail,
                "weight": 0.85,
            }
        )
    return recipe


def ensure_recipe(category: dict[str, Any]) -> list[dict[str, Any]]:
    recipe = category.get("recipe") or []
    if recipe:
        return recipe
    return build_recipe_for_category(category, category.get("recipe_style", "realistic_tactile"))


def recipe_keywords(category: dict[str, Any]) -> list[str]:
    output = list(category.get("keywords", []))
    for layer in ensure_recipe(category):
        output.extend(layer.get("keywords", []))
    seen: set[str] = set()
    clean: list[str] = []
    for item in output:
        key = item.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        clean.append(item.strip())
    return clean


def next_style_for_category(category: dict[str, Any]) -> str:
    current = category.get("recipe_style", "realistic_tactile")
    text = f"{category.get('name', '')} {category.get('direction', '')}"
    if _has(text, "维修", "设置", "工具", "机械"):
        order = ["mechanical_gear", "premium_clean", "realistic_tactile", "warm_casual"]
    elif _has(text, "食品", "仓库", "背包"):
        order = ["warm_casual", "realistic_tactile", "premium_clean", "mechanical_gear"]
    elif _has(text, "前往", "钓场", "奖励", "签到", "购买", "商店"):
        order = ["premium_clean", "realistic_tactile", "warm_casual", "mechanical_gear"]
    else:
        order = ["realistic_tactile", "premium_clean", "warm_casual", "mechanical_gear"]

    if current not in order:
        return order[0]
    return order[(order.index(current) + 1) % len(order)]


def make_recommendations(
    category: dict[str, Any],
    results: list[dict[str, Any]],
    max_layers: int | None = None,
) -> list[dict[str, Any]]:
    recipe = ensure_recipe(category)
    if max_layers is not None:
        recipe = recipe[:max_layers]

    recommendations: list[dict[str, Any]] = []
    used_audio_ids: set[int] = set()

    for layer in recipe:
        best_item: dict[str, Any] | None = None
        best_score = -1.0
        best_terms: list[str] = []
        keywords = layer.get("keywords", [])
        weight = float(layer.get("weight", 1.0))

        for result in results:
            layer_score, matched = score_file(result, keywords)
            if layer_score <= 0:
                continue

            candidate_score = layer_score * weight + float(result["score"]) * 0.18
            audio_file_id = result.get("audio_file_id") or result.get("id")
            if audio_file_id is None:
                continue
            if audio_file_id in used_audio_ids:
                candidate_score *= 0.72

            if candidate_score > best_score:
                best_score = candidate_score
                best_item = result
                best_terms = matched

        if best_item is None:
            continue

        best_audio_id = best_item.get("audio_file_id") or best_item.get("id")
        if best_audio_id is None:
            continue
        used_audio_ids.add(best_audio_id)
        reason_terms = ", ".join(best_terms[:5]) if best_terms else best_item.get("matched_terms", "")
        recommendations.append(
            {
                "layer_name": layer.get("name", "Layer"),
                "layer_role": layer.get("role", ""),
                "audio_file_id": best_audio_id,
                "path": best_item["path"],
                "name": best_item["name"],
                "score": round(best_score, 2),
                "reason": f"匹配 {reason_terms}",
            }
        )

    return recommendations


def recommend_layer(
    layer: dict[str, Any],
    results: list[dict[str, Any]],
    avoid_audio_ids: set[int] | None = None,
) -> dict[str, Any] | None:
    avoid_audio_ids = avoid_audio_ids or set()
    best_item: dict[str, Any] | None = None
    best_score = -1.0
    best_terms: list[str] = []
    keywords = layer.get("keywords", [])
    weight = float(layer.get("weight", 1.0))

    for result in results:
        if result.get("audio_file_id") in avoid_audio_ids or result.get("id") in avoid_audio_ids:
            continue
        layer_score, matched = score_file(result, keywords)
        if layer_score <= 0:
            continue
        candidate_score = layer_score * weight + float(result.get("score", 0.0)) * 0.18
        if candidate_score > best_score:
            best_score = candidate_score
            best_item = result
            best_terms = matched

    if best_item is None:
        return None

    reason_terms = ", ".join(best_terms[:5]) if best_terms else best_item.get("matched_terms", "")
    return {
        "layer_name": layer.get("name", "Layer"),
        "layer_role": layer.get("role", ""),
        "audio_file_id": best_item.get("audio_file_id") or best_item.get("id"),
        "path": best_item.get("path", ""),
        "name": best_item.get("name", ""),
        "score": round(best_score, 2),
        "reason": f"匹配 {reason_terms}",
    }


def similar_replacement(
    layer: dict[str, Any],
    current_file: dict[str, Any],
    results: list[dict[str, Any]],
    avoid_audio_ids: set[int],
) -> dict[str, Any] | None:
    current_tokens = tokens_for(f"{current_file.get('name', '')} {current_file.get('folder', '')}")
    layer_keywords = layer.get("keywords", [])
    candidates: list[tuple[float, dict[str, Any], list[str]]] = []

    for result in results:
        audio_id = result["audio_file_id"]
        if audio_id == current_file.get("audio_file_id") or audio_id in avoid_audio_ids:
            continue

        layer_score, matched = score_file(result, layer_keywords)
        result_tokens = tokens_for(f"{result['name']} {result['folder']}")
        shared = current_tokens & result_tokens
        shared_score = len(shared) * 18.0
        extension_bonus = 5.0 if result.get("extension") == current_file.get("extension") else 0.0
        score = layer_score * 0.95 + shared_score + float(result["score"]) * 0.08 + extension_bonus
        if score > 0:
            candidates.append((score, result, matched))

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0], reverse=True)
    shortlist = candidates[: min(8, len(candidates))]
    score, result, matched = random.choice(shortlist[: min(4, len(shortlist))])
    reason_terms = ", ".join(matched[:5]) if matched else "文件名/路径特征接近"
    return {
        "layer_name": layer.get("name", "Layer"),
        "layer_role": layer.get("role", ""),
        "audio_file_id": result["audio_file_id"],
        "path": result["path"],
        "name": result["name"],
        "score": round(score, 2),
        "reason": f"相似替换：{reason_terms}",
    }
