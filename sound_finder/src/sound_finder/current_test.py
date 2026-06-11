from __future__ import annotations

import math
import random
import wave
from pathlib import Path

from .db import ROOT_DIR, PlanCategory, SoundFinderDB
from .handoff import CURRENT_PLAN_PATH, write_plan_file
from .indexer import scan_library, search_audio_files
from .recipe import build_recipe_for_category, make_recommendations


REQUIREMENT = (
    "给钓鱼游戏大厅 UI 按钮设计偏写实、带少量游戏反馈感的音效。"
    "按钮包括仓库、维修、食品、钓具商店、前往钓场、设置、货币/购买、签到奖励、返回关闭和错误不可用。"
)


DEMO_FILES = [
    "UI_Clicks/realistic_UI_click_soft_button_click_tactile_01.wav",
    "UI_Clicks/plastic_button_press_short_foley_click_02.wav",
    "UI_Clicks/menu_select_click_clean_interface_03.wav",
    "UI_Clicks/soft_button_click_positive_UI_blip_04.wav",
    "Storage/storage_box_latch_toolbox_latch_click_01.wav",
    "Storage/case_open_click_plastic_case_snap_02.wav",
    "Storage/inventory_item_pickup_small_objects_rattle_03.wav",
    "Storage/bag_zipper_short_gear_bag_foley_04.wav",
    "Repair/wrench_click_metal_tool_tap_01.wav",
    "Repair/ratchet_click_screwdriver_turn_02.wav",
    "Repair/mechanical_click_metal_clank_short_03.wav",
    "Repair/toolbox_foley_repair_tool_sound_04.wav",
    "Food/food_package_rustle_snack_bag_crinkle_01.wav",
    "Food/paper_wrapper_foley_foil_wrapper_rustle_02.wav",
    "Food/can_tap_plastic_container_click_03.wav",
    "Food/lunch_box_open_small_package_pickup_04.wav",
    "Shop/shop_bell_ding_retail_counter_bell_01.wav",
    "Shop/cash_register_ding_coin_register_short_02.wav",
    "Shop/fishing_reel_click_fishing_tackle_foley_03.wav",
    "Shop/product_pickup_gear_shop_ambience_04.wav",
    "Travel/fishing_rod_cast_fishing_line_cast_01.wav",
    "Travel/reel_spin_outdoor_whoosh_02.wav",
    "Travel/water_splash_small_lake_ambience_short_03.wav",
    "Travel/map_travel_sound_confirm_big_UI_04.wav",
    "Settings/gear_click_cog_wheel_turn_01.wav",
    "Settings/mechanical_gear_short_settings_UI_click_02.wav",
    "Settings/precision_dial_click_metal_knob_turn_03.wav",
    "Currency/coin_pickup_coin_clink_01.wav",
    "Currency/coin_drop_short_money_UI_sound_02.wav",
    "Currency/purchase_confirm_cash_register_03.wav",
    "Reward/reward_popup_daily_reward_sound_01.wav",
    "Reward/stamp_sound_bonus_collect_02.wav",
    "Reward/prize_reveal_sparkle_chime_03.wav",
    "Reward/achievement_unlock_gift_open_04.wav",
    "Navigation/UI_back_menu_back_click_01.wav",
    "Navigation/panel_close_window_close_sound_02.wav",
    "Navigation/reverse_whoosh_short_soft_UI_close_03.wav",
    "Error/UI_error_invalid_click_01.wav",
    "Error/disabled_button_negative_UI_beep_02.wav",
    "Error/soft_error_thunk_dull_click_03.wav",
    "Transitions/UI_transition_menu_whoosh_01.wav",
    "Transitions/panel_slide_popup_open_UI_reveal_02.wav",
]


def _write_demo_wave(path: Path, index: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sample_rate = 44100
    duration = 0.18 + (index % 5) * 0.035
    total_samples = int(sample_rate * duration)
    base_frequency = 220 + (index % 12) * 28
    random.seed(path.name)

    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        frames = bytearray()
        for n in range(total_samples):
            t = n / sample_rate
            envelope = max(0.0, 1.0 - n / total_samples)
            click = math.sin(2 * math.pi * base_frequency * t) * 0.26 * envelope
            tick = math.sin(2 * math.pi * (base_frequency * 2.7) * t) * 0.08 * envelope
            noise = (random.random() - 0.5) * 0.05 * envelope
            sample = max(-1.0, min(1.0, click + tick + noise))
            value = int(sample * 32767)
            frames.extend(value.to_bytes(2, "little", signed=True))
        handle.writeframes(bytes(frames))


def create_demo_library() -> Path:
    root = ROOT_DIR / "demo_library"
    for index, relative in enumerate(DEMO_FILES):
        path = root / relative
        if not path.exists():
            _write_demo_wave(path, index)
    return root


def current_ui_plan() -> list[PlanCategory]:
    raw_categories = [
        (
            "通用点击",
            "所有 UI 按钮共享的短点击核心层，干净、有触感。",
            [
                "realistic UI click",
                "soft button click",
                "plastic button press",
                "tactile click",
                "short foley click",
                "menu select click",
            ],
        ),
        (
            "仓库",
            "箱扣、装备包、拉链、物品轻碰，表达收纳和库存。",
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
        (
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
        (
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
        (
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
        (
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
        (
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
        (
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
        (
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
        (
            "返回/关闭",
            "低调的收回和关闭反馈。",
            [
                "UI back",
                "menu back click",
                "panel close",
                "window close sound",
                "reverse whoosh short",
                "soft UI close",
            ],
        ),
        (
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
    ]

    plan: list[PlanCategory] = []
    for name, direction, keywords in raw_categories:
        category = {"name": name, "direction": direction, "keywords": keywords}
        recipe = build_recipe_for_category(category, "realistic_tactile")
        plan.append(PlanCategory(name, direction, keywords, True, recipe, "realistic_tactile"))
    return plan


def seed_current_test() -> int:
    db = SoundFinderDB()
    demo_root = create_demo_library()
    db.set_setting("library_root", str(demo_root))
    scan_library(db, demo_root)

    plan = current_ui_plan()
    title = "当前测试：钓鱼游戏大厅 UI 按钮"
    write_plan_file(CURRENT_PLAN_PATH, title, REQUIREMENT, plan)

    session_id = db.create_session(title, REQUIREMENT)
    category_ids = db.replace_plan(session_id, REQUIREMENT, plan)
    results_by_index = search_audio_files(db, plan)
    for index, results in results_by_index.items():
        db.save_results(session_id, category_ids[index], results)

    for category in db.list_categories(session_id):
        results = db.list_results(session_id, category["id"])
        recommendations = make_recommendations(category, results)
        if recommendations:
            db.save_recommendations(session_id, category["id"], recommendations, "seed_current_test")

    db.set_setting("last_session_id", str(session_id))
    return session_id


if __name__ == "__main__":
    created_session_id = seed_current_test()
    print(f"Seeded current UI-button test session: {created_session_id}")

