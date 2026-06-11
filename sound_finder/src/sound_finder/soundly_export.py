from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any

from .db import ROOT_DIR
from .reaper_tracks import unique_track_names


HANDOFF_DIR = ROOT_DIR / "handoff"


DEFAULT_REJECT = ["-music", "-loop", "-ambience", "-drone", "-song"]


CURATED_QUERIES: dict[str, dict[str, Any]] = {
    "Large_Back_To_Lobby": {
        "queries": ['"interior door" close', '"door handle" click', '"wood door" close'],
        "reject": ["-creak", "-slam"],
        "target": "Short realistic lobby/back action. Door handle or interior door close, 0.4-1.5s.",
    },
    "Banner_Weekend_Supply_Benefit": {
        "queries": ['"supply crate" open', '"loot box" open', '"gift box" open'],
        "reject": ["-magic", "-cinematic"],
        "target": "Reward/supply banner with a real container or package open, 0.5-2s.",
    },
    "Tile_Backpack": {
        "queries": ['"backpack zipper"', '"bag zipper" open', '"duffle bag" zipper'],
        "reject": ["-long", "-cloth loop"],
        "target": "Short bag zipper or gear bag open, tactile and close, 0.2-1.5s.",
    },
    "Tile_Storage": {
        "queries": ['"storage box" latch', '"crate open"', '"case open" click'],
        "reject": ["-break", "-destroy"],
        "target": "Storage box, case, or crate latch/open, 0.3-1.5s.",
    },
    "Tile_Food": {
        "queries": ['"food package" rustle', '"lunch box" open', '"snack bag" crinkle'],
        "reject": ["-eating", "-chew"],
        "target": "Food container or package interaction, not eating, 0.3-1.5s.",
    },
    "Tile_Repair": {
        "queries": ['"wrench click"', '"ratchet click"', '"screwdriver" turn'],
        "reject": ["-impact", "-machine loop"],
        "target": "Small repair tool click or metal adjustment, 0.1-1s.",
    },
    "Tile_Fishing_Tackle_Shop": {
        "queries": ['"shop bell" ding', '"cash register" ding', '"fishing reel" click'],
        "reject": ["-crowd", "-market ambience"],
        "target": "Shop/tackle identity: bell, register, or reel click, 0.2-1.5s.",
    },
    "Large_Go_To_Fishing_Spot": {
        "queries": ['"fishing rod" cast', '"fishing line" cast', '"water splash" small'],
        "reject": ["-ocean ambience", "-river loop"],
        "target": "Travel to fishing spot: cast, reel, water touch, or outdoor transition, 0.5-2s.",
    },
    "Tile_Skills": {
        "queries": ['"card flip"', '"book page" turn', '"skill card"'],
        "reject": ["-spell cast", "-explosion"],
        "target": "Skill card/book motion, realistic paper/card layer, 0.2-1s.",
    },
    "Tile_Outfit": {
        "queries": ['"cloth rustle" short', '"clothing rustle"', '"fabric swish" short'],
        "reject": ["-wind", "-long movement"],
        "target": "Short clothing/fabric movement for outfit UI, 0.2-1.5s.",
    },
    "Tile_Keepnet": {
        "queries": ['"fishing net"', '"fish in net"', '"fish flop" net'],
        "reject": ["-big splash", "-underwater ambience"],
        "target": "Fishing net or fish-in-net detail, close and short if possible.",
    },
    "Tile_Quests": {
        "queries": ['"paper parchment" rustle', '"document stamp"', '"clipboard" paper'],
        "reject": ["-tear", "-fire"],
        "target": "Quest paper, parchment, stamp, or checklist, 0.2-1.5s.",
    },
    "Tile_Vehicle": {
        "queries": ['"boat engine" start', '"RIB engine" start', '"jet ski" start'],
        "reject": ["-truck", "-car", "-long idle"],
        "target": "Fishing-related vehicle, preferably boat/RIB motor start or handle, 0.5-2.5s.",
    },
    "Tile_Achievements": {
        "queries": ['"achievement unlock"', '"medal" clink', '"trophy" ding'],
        "reject": ["-fanfare", "-long music"],
        "target": "Achievement with trophy/medal or short positive unlock, 0.5-2s.",
    },
    "Tile_Collection_Book": {
        "queries": ['"book page turn" short', '"album page" flip', '"collection book" page'],
        "reject": ["-magic", "-spell"],
        "target": "Collection book or album page, short and realistic, 0.2-1s.",
    },
    "Tile_Map": {
        "queries": ['"map unfold"', '"paper map" rustle', '"map fold"'],
        "reject": ["-navigation voice", "-ambience"],
        "target": "Map fold/unfold paper gesture, 0.5-2s.",
    },
    "Tile_Encyclopedia": {
        "queries": ['"book page turn" short', '"thick book" open', '"encyclopedia" page'],
        "reject": ["-magic", "-spell"],
        "target": "Book/encyclopedia page or open, short and readable.",
    },
    "Tile_News": {
        "queries": ['"newspaper" rustle', '"paper sheet" pickup', '"notice paper"'],
        "reject": ["-fire", "-tear"],
        "target": "News or notice paper handling, 0.2-1.5s.",
    },
    "Tile_Leaderboard": {
        "queries": ['"scoreboard" click', '"number board" flip', '"medal" clink'],
        "reject": ["-crowd", "-arena", "-buzzer"],
        "target": "Leaderboard/ranking board, number flip, small medal or board clink, 0.2-1.5s.",
    },
    "Tile_Guild": {
        "queries": ['"banner" cloth', '"flag" unfurl', '"shield" metal'],
        "reject": ["-battle", "-large hit"],
        "target": "Guild identity: banner cloth, flag, crest, or restrained shield metal, 0.5-2s.",
    },
    "Tile_Friends": {
        "queries": ['"message notification"', '"friend request"', '"phone notification"'],
        "reject": ["-sci fi", "-alarm"],
        "target": "Friendly social notification, light and short, 0.2-1.5s.",
    },
    "Resource_Silver_Token": {
        "queries": ['"token coin"', '"silver coin" click', '"poker chip"'],
        "reject": ["-casino ambience", "-slot machine"],
        "target": "Small metal/plastic token or silver coin touch, 0.1-1s.",
    },
    "Resource_Gold_Coin": {
        "queries": ['"gold coin" clink', '"coin pickup"', '"coin drop"'],
        "reject": ["-coin rain", "-slot machine"],
        "target": "Gold coin pickup/drop/clink, short and tactile, 0.1-1.2s.",
    },
    "Icon_Mailbox": {
        "queries": ['"mailbox" open', '"envelope" open', '"letter" paper'],
        "reject": ["-machine", "-long"],
        "target": "Mailbox/envelope/letter action for mail icon, 0.1-1s.",
    },
    "Icon_Settings_Gear": {
        "queries": ['"gear click"', '"knob turn"', '"mechanical switch" click'],
        "reject": ["-engine", "-machine loop"],
        "target": "Small gear/knob/settings mechanism, 0.1-1s.",
    },
    "Icon_Announcement_Speaker": {
        "queries": ['"radio switch"', '"walkie talkie" switch', '"speaker" click'],
        "reject": ["-announcement voice", "-crowd"],
        "target": "Speaker/announcement icon via device switch/click, 0.1-1s.",
    },
    "Icon_Chat_Support": {
        "queries": ['"chat message" pop', '"headset" click', '"walkie talkie" click'],
        "reject": ["-alarm", "-sci fi"],
        "target": "Chat/support icon, short message or headset/radio click, 0.1-1s.",
    },
    "Icon_Search_View": {
        "queries": ['"camera lens" click', '"magnifying glass"', '"aperture ring" click'],
        "reject": ["-shutter burst", "-camera ambience"],
        "target": "Search/view icon via lens, magnifier, or focus click, 0.1-1s.",
    },
    "Icon_Event_Guide_Sign_TBC": {
        "queries": ['"wooden sign" tap', '"notice board"', '"board tap"'],
        "reject": ["-impact", "-break"],
        "target": "Temporary event/guide sign placeholder. Confirm icon meaning before final use.",
    },
}


def fallback_queries(track_name: str, category: dict[str, Any]) -> list[str]:
    stem = track_name.split("_", 1)[-1].replace("_", " ").lower()
    keywords = [str(item).strip() for item in category.get("keywords", []) if str(item).strip()]
    output = [f'"{stem}"']
    output.extend(keywords[:2])
    while len(output) < 3:
        output.append(stem)
    return output[:3]


def soundly_rows(session_id: int, title: str, categories: list[dict[str, Any]]) -> list[dict[str, str]]:
    tracks = unique_track_names(categories)
    rows: list[dict[str, str]] = []
    for category, track in zip(categories, tracks):
        profile = CURATED_QUERIES.get(track["name"], {})
        queries = profile.get("queries") or fallback_queries(track["name"], category)
        reject = DEFAULT_REJECT + list(profile.get("reject", []))
        rows.append(
            {
                "session_id": str(session_id),
                "session_title": title,
                "wwise_name": track["name"],
                "type": track["kind"],
                "original_name": track["original"],
                "soundly_query_1": queries[0] if len(queries) > 0 else "",
                "soundly_query_2": queries[1] if len(queries) > 1 else "",
                "soundly_query_3": queries[2] if len(queries) > 2 else "",
                "reject_terms": " ".join(dict.fromkeys(reject)),
                "target": profile.get("target", "Short, realistic UI feature layer. Prefer 0.1-2s and avoid long beds."),
            }
        )
    return rows


def export_soundly_search_sheet(
    session_id: int,
    title: str,
    categories: list[dict[str, Any]],
) -> tuple[Path, Path]:
    HANDOFF_DIR.mkdir(parents=True, exist_ok=True)
    safe_id = str(session_id)
    csv_path = HANDOFF_DIR / f"soundly_search_sheet_session_{safe_id}.csv"
    md_path = HANDOFF_DIR / f"soundly_search_sheet_session_{safe_id}.md"
    rows = soundly_rows(session_id, title, categories)

    fieldnames = [
        "session_id",
        "session_title",
        "wwise_name",
        "type",
        "original_name",
        "soundly_query_1",
        "soundly_query_2",
        "soundly_query_3",
        "reject_terms",
        "target",
    ]
    with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    lines = [
        f"# Soundly Search Sheet - Session {session_id}",
        "",
        f"- Title: {title}",
        f"- Requirements: {len(rows)}",
        "- Use the queries in Soundly, then filter/reject by the target notes.",
        "",
        "| Wwise Name | Type | Query 1 | Query 2 | Query 3 | Reject | Target |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            "| {wwise_name} | {type} | {soundly_query_1} | {soundly_query_2} | {soundly_query_3} | {reject_terms} | {target} |".format(
                **{key: str(value).replace("|", "/") for key, value in row.items()}
            )
        )
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return csv_path, md_path
