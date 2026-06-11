from __future__ import annotations

import re
from datetime import datetime

from .db import PlanCategory


BASE_UI_CATEGORIES = [
    PlanCategory(
        "通用点击",
        "短促、干净、有触感的 UI 点击核心层。",
        [
            "realistic UI click",
            "soft button click",
            "plastic button press",
            "tactile click",
            "short foley click",
            "menu select click",
        ],
    ),
    PlanCategory(
        "确认/进入",
        "比普通点击更积极，适合进入页面、确认选择和主按钮。",
        [
            "confirm UI",
            "positive UI click",
            "menu confirm",
            "short success",
            "soft whoosh",
            "button accept",
        ],
    ),
    PlanCategory(
        "返回/关闭",
        "轻微收回感，音高略低，避免抢注意力。",
        [
            "UI back",
            "menu back click",
            "panel close",
            "window close sound",
            "reverse whoosh short",
            "soft UI close",
        ],
    ),
    PlanCategory(
        "错误/不可用",
        "短、闷、低刺激，提示不可点击或资源不足。",
        [
            "UI error",
            "invalid click",
            "disabled button",
            "negative UI beep",
            "soft error thunk",
            "dull click",
        ],
    ),
    PlanCategory(
        "弹窗/页面切换",
        "轻微滑入、展开、切换反馈，可做界面层级变化。",
        [
            "UI transition",
            "menu whoosh",
            "panel slide",
            "popup open",
            "UI reveal",
            "short rise",
        ],
    ),
]


FISHING_UI_CATEGORIES = [
    PlanCategory(
        "仓库",
        "箱扣、装备包、拉链、物品轻碰，表达库存和收纳。",
        [
            "storage box latch",
            "toolbox latch click",
            "case open click",
            "plastic case snap",
            "inventory item pickup",
            "small objects rattle",
            "bag zipper short",
            "gear bag foley",
        ],
    ),
    PlanCategory(
        "维修",
        "工具、金属、机械咔哒，表达修理和装备维护。",
        [
            "wrench click",
            "metal tool tap",
            "ratchet click",
            "screwdriver turn",
            "mechanical click",
            "metal clank short",
            "toolbox foley",
            "repair tool sound",
        ],
    ),
    PlanCategory(
        "食品",
        "包装纸、罐头、餐盒、塑料容器，短而真实。",
        [
            "food package rustle",
            "snack bag crinkle",
            "paper wrapper foley",
            "can tap",
            "plastic container click",
            "lunch box open",
            "foil wrapper rustle",
            "small package pickup",
        ],
    ),
    PlanCategory(
        "钓具商店",
        "商店提示、收银、商品拿起和钓具小机械声。",
        [
            "shop bell ding",
            "cash register ding",
            "retail counter bell",
            "fishing reel click",
            "fishing tackle foley",
            "gear shop ambience",
            "product pickup",
            "coin register short",
        ],
    ),
    PlanCategory(
        "前往钓场",
        "更大的确认感，带鱼竿抛投、线轮、水面或户外空气。",
        [
            "fishing rod cast",
            "fishing line cast",
            "reel spin",
            "water splash small",
            "lake ambience short",
            "outdoor whoosh",
            "transition whoosh",
            "map travel sound",
            "confirm big UI",
        ],
    ),
    PlanCategory(
        "设置",
        "小齿轮、旋钮、精密机械，适合设置按钮。",
        [
            "gear click",
            "cog wheel turn",
            "mechanical gear short",
            "settings UI click",
            "small mechanism click",
            "precision dial click",
            "metal knob turn",
        ],
    ),
    PlanCategory(
        "货币/购买",
        "硬币、收银、交易完成，音色偏亮但别太长。",
        [
            "coin pickup",
            "coin clink",
            "coin drop short",
            "cash register",
            "money UI sound",
            "purchase confirm",
            "digital coin",
            "reward currency",
        ],
    ),
    PlanCategory(
        "签到/奖励",
        "盖章、奖励弹出、闪光和正向小旋律。",
        [
            "reward popup",
            "daily reward sound",
            "stamp sound",
            "bonus collect",
            "prize reveal",
            "sparkle chime",
            "achievement unlock",
            "gift open",
        ],
    ),
]


GENERIC_GAME_CATEGORIES = [
    PlanCategory(
        "奖励/领取",
        "领取、掉落、结算奖励，用轻快正反馈。",
        [
            "collect reward",
            "item collect",
            "loot pickup",
            "positive UI chime",
            "soft success sound",
            "reward sparkle",
            "bonus claim",
        ],
    ),
    PlanCategory(
        "购买/消耗",
        "购买、扣费、交易完成，适合商店和资源消耗。",
        [
            "purchase confirm",
            "cash register ding",
            "coin spend",
            "shop buy sound",
            "transaction complete",
            "money subtract UI",
        ],
    ),
    PlanCategory(
        "装备选择",
        "装备、装配、物品拿起，适合背包和角色装备界面。",
        [
            "gear equip",
            "item equip",
            "equipment select",
            "cloth pickup",
            "weapon equip",
            "inventory pickup",
        ],
    ),
]


def has_any(text: str, words: list[str]) -> bool:
    lowered = text.lower()
    return any(word.lower() in lowered for word in words)


def dedupe_categories(categories: list[PlanCategory]) -> list[PlanCategory]:
    seen: set[str] = set()
    output: list[PlanCategory] = []
    for category in categories:
        if category.name in seen:
            continue
        seen.add(category.name)
        output.append(category)
    return output


def categories_from_lines(requirement: str) -> list[PlanCategory]:
    output: list[PlanCategory] = []
    lines = [line.strip(" -•\t") for line in requirement.splitlines()]
    for line in lines:
        if not line or len(line) > 18:
            continue
        if re.search(r"[，。、,.;；:：/\\]", line):
            continue
        if len(line) >= 2:
            output.append(
                PlanCategory(
                    line,
                    f"围绕“{line}”寻找可作为按钮反馈或材质点缀的短音效。",
                    [
                        f"{line} UI",
                        f"{line} click",
                        f"{line} foley",
                        "short UI click",
                        "menu select",
                    ],
                )
            )
    return output


def generate_plan(requirement: str) -> list[PlanCategory]:
    text = requirement.strip()
    categories: list[PlanCategory] = []

    categories.extend(categories_from_lines(text))
    categories.extend(BASE_UI_CATEGORIES)

    if has_any(text, ["钓", "鱼", "钓具", "钓场", "fishing", "reel", "rod"]):
        categories.extend(FISHING_UI_CATEGORIES)

    if has_any(text, ["商店", "购买", "货币", "奖励", "签到", "背包", "装备", "shop", "reward"]):
        categories.extend(GENERIC_GAME_CATEGORIES)

    if not text:
        categories.extend(GENERIC_GAME_CATEGORIES)

    return dedupe_categories(categories)


def suggest_title(requirement: str) -> str:
    compact = re.sub(r"\s+", " ", requirement.strip())
    if compact:
        title = compact[:24]
    else:
        title = "未命名音效需求"
    return f"{datetime.now().strftime('%Y-%m-%d')} {title}"
