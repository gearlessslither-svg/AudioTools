from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path
from typing import Any

from .db import ROOT_DIR


HANDOFF_DIR = ROOT_DIR / "handoff"
PROJECTS_DIR = ROOT_DIR / "reaper_projects"
TRACK_SCRIPT_PATH = HANDOFF_DIR / "sound_finder_create_reaper_tracks.lua"
TRACK_STATUS_PATH = HANDOFF_DIR / "sound_finder_create_reaper_tracks_status.txt"


KNOWN_TRACK_NAMES = {
    "返回大厅": ("Large_Back_To_Lobby", "Large"),
    "周末补给福利": ("Banner_Weekend_Supply_Benefit", "Banner"),
    "背包": ("Tile_Backpack", "Tile"),
    "仓库": ("Tile_Storage", "Tile"),
    "食品": ("Tile_Food", "Tile"),
    "维修": ("Tile_Repair", "Tile"),
    "渔具店": ("Tile_Fishing_Tackle_Shop", "Tile"),
    "前往钓场": ("Large_Go_To_Fishing_Spot", "Large"),
    "技能": ("Tile_Skills", "Tile"),
    "时装": ("Tile_Outfit", "Tile"),
    "鱼护": ("Tile_Keepnet", "Tile"),
    "任务": ("Tile_Quests", "Tile"),
    "载具": ("Tile_Vehicle", "Tile"),
    "成就": ("Tile_Achievements", "Tile"),
    "图鉴": ("Tile_Collection_Book", "Tile"),
    "地图": ("Tile_Map", "Tile"),
    "百科": ("Tile_Encyclopedia", "Tile"),
    "资讯": ("Tile_News", "Tile"),
    "排行榜": ("Tile_Leaderboard", "Tile"),
    "公会": ("Tile_Guild", "Tile"),
    "好友": ("Tile_Friends", "Tile"),
    "银色资源/代币": ("Resource_Silver_Token", "Resource"),
    "金币": ("Resource_Gold_Coin", "Resource"),
    "信箱/邮件": ("Icon_Mailbox", "Icon"),
    "设置齿轮": ("Icon_Settings_Gear", "Icon"),
    "公告/扬声器": ("Icon_Announcement_Speaker", "Icon"),
    "聊天/客服": ("Icon_Chat_Support", "Icon"),
    "搜索/查看": ("Icon_Search_View", "Icon"),
    "活动/引导牌（待确认）": ("Icon_Event_Guide_Sign_TBC", "Icon"),
}


TYPE_HINTS = [
    ("Large", ["large", "go to", "back to", "travel", "lobby"]),
    ("Banner", ["banner", "benefit", "reward", "supply"]),
    ("Resource", ["coin", "currency", "token", "gold", "silver"]),
    ("Icon", ["icon", "mail", "settings", "gear", "speaker", "chat", "search"]),
]


def reaper_exe_path() -> Path:
    default = Path(r"C:\Program Files\REAPER (x64)\reaper.exe")
    return default if default.exists() else Path("reaper.exe")


def sanitize_track_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", name.strip())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned or "Requirement"


def sanitize_project_name(title: str, requirement: str = "", session_id: int | None = None) -> str:
    source = (title or "").strip()
    if not source:
        source = " ".join((requirement or "").split())[:80]
    if not source and session_id is not None:
        source = f"Sound Finder Session {session_id}"
    source = re.sub(r"^(\d{4})-(\d{2})-(\d{2})(\b|\s)", r"\1 \2 \3\4", source)
    source = re.sub(r"[<>:\"/\\|?*\x00-\x1f]+", " ", source)
    source = re.sub(r"\s+", " ", source).strip(" .")
    if not source:
        source = "Sound Finder Project"
    return source[:120].rstrip(" .")


def project_path_for_session(session_id: int, title: str, requirement: str = "") -> tuple[str, Path]:
    project_name = sanitize_project_name(title, requirement, session_id)
    project_dir = PROJECTS_DIR / project_name
    return project_name, project_dir / f"{project_name}.rpp"


def title_from_keywords(category: dict[str, Any]) -> str:
    for keyword in category.get("keywords", []):
        ascii_keyword = re.sub(r"[^A-Za-z0-9 ]+", " ", str(keyword))
        words = [word for word in ascii_keyword.split() if word]
        if words:
            return "_".join(word.capitalize() for word in words[:5])
    raw_name = re.sub(r"[^A-Za-z0-9 ]+", " ", str(category.get("name", "")))
    words = [word for word in raw_name.split() if word]
    if words:
        return "_".join(word.capitalize() for word in words[:5])
    return "Requirement"


def infer_kind(track_name: str) -> str:
    lower = track_name.lower().replace("_", " ")
    for kind, hints in TYPE_HINTS:
        if any(hint in lower for hint in hints):
            return kind
    return "Tile"


def english_track_for_category(category: dict[str, Any]) -> tuple[str, str]:
    name = str(category.get("name", "")).strip()
    if name in KNOWN_TRACK_NAMES:
        return KNOWN_TRACK_NAMES[name]

    fallback = sanitize_track_name(title_from_keywords(category))
    if not fallback.startswith(("Large_", "Banner_", "Tile_", "Resource_", "Icon_")):
        kind = infer_kind(fallback)
        if kind != "Tile":
            fallback = f"{kind}_{fallback}"
    else:
        kind = fallback.split("_", 1)[0]
    return fallback, kind


def remove_tile_prefix(track_name: str) -> tuple[str, str]:
    if track_name.startswith("Tile_"):
        return track_name[5:], track_name
    return track_name, ""


def unique_track_names(categories: list[dict[str, Any]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    output: list[dict[str, str]] = []
    for category in categories:
        base_name, kind = english_track_for_category(category)
        track_name, legacy_name = remove_tile_prefix(sanitize_track_name(base_name))
        if not legacy_name and kind == "Tile":
            legacy_name = f"Tile_{track_name}"
        candidate = track_name
        suffix = "Alt"
        while candidate in seen:
            candidate = f"{track_name}_{suffix}"
            suffix += "X"
        seen.add(candidate)
        output.append(
            {
                "name": candidate,
                "kind": sanitize_track_name(kind),
                "legacy": legacy_name,
                "original": str(category.get("name", "")),
            }
        )
    return output


def lua_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def write_reaper_track_script(
    session_id: int,
    title: str,
    requirement: str,
    categories: list[dict[str, Any]],
    project_name: str,
    project_path: Path,
    project_was_existing: bool,
    group_name: str = "",
) -> Path:
    HANDOFF_DIR.mkdir(parents=True, exist_ok=True)
    project_path.parent.mkdir(parents=True, exist_ok=True)
    tracks = unique_track_names(categories)
    track_rows = []
    for track in tracks:
        track_rows.append(
            "  { name = %s, kind = %s, legacy = %s, original = %s },"
            % (
                lua_quote(track["name"]),
                lua_quote(track["kind"]),
                lua_quote(track["legacy"]),
                lua_quote(track["original"]),
            )
        )

    status_path_lua = str(TRACK_STATUS_PATH).replace("\\", "/")
    project_path_lua = str(project_path).replace("\\", "/")
    project_exists_lua = "true" if project_was_existing else "false"

    script = f"""-- Generated by Sound Finder. Creates or updates empty REAPER requirement tracks.
-- Session: {session_id} / {title}

local status_path = {lua_quote(status_path_lua)}
local project_path = {lua_quote(project_path_lua)}
local project_name = {lua_quote(project_name)}
local project_was_existing = {project_exists_lua}
local parent_name = {lua_quote(group_name)}
local old_parent_name = "UI"
local session_label = {lua_quote(f"Sound Finder session {session_id}")}
local requirement_text = {lua_quote(requirement)}

local requirements = {{
{chr(10).join(track_rows)}
}}

local colors = {{
  Parent = {{ 72, 132, 214 }},
  Large = {{ 49, 156, 121 }},
  Banner = {{ 49, 156, 121 }},
  Tile = {{ 116, 97, 184 }},
  Resource = {{ 206, 151, 42 }},
  Icon = {{ 88, 142, 173 }},
}}

local function native_color(kind)
  local c = colors[kind] or colors.Tile
  return reaper.ColorToNative(c[1], c[2], c[3]) | 0x1000000
end

local function set_track_name(track, name)
  reaper.GetSetMediaTrackInfo_String(track, "P_NAME", name, true)
end

local function get_track_name(track)
  local ok, name = reaper.GetSetMediaTrackInfo_String(track, "P_NAME", "", false)
  if ok then return name end
  return ""
end

local function set_track_note(track, key, value)
  reaper.GetSetMediaTrackInfo_String(track, "P_EXT:codex_" .. key, value, true)
end

local function set_project_note(key, value)
  if reaper.SetProjExtState then
    reaper.SetProjExtState(0, "SoundFinder", key, value)
  end
end

local function find_track_by_name(name)
  local count = reaper.CountTracks(0)
  for i = 0, count - 1 do
    local track = reaper.GetTrack(0, i)
    if get_track_name(track) == name then
      return track, i
    end
  end
  return nil, nil
end

local function clear_default_tracks()
  while reaper.CountTracks(0) > 0 do
    reaper.DeleteTrack(reaper.GetTrack(0, 0))
  end
end

local function collect_folder_children(parent_index)
  local children = {{}}
  local balance = 1
  local count = reaper.CountTracks(0)
  for i = parent_index + 1, count - 1 do
    local track = reaper.GetTrack(0, i)
    table.insert(children, track)
    balance = balance + math.floor(reaper.GetMediaTrackInfo_Value(track, "I_FOLDERDEPTH"))
    if balance <= 0 then
      break
    end
  end
  return children
end

local function folder_insert_index(parent_index)
  local balance = 1
  local count = reaper.CountTracks(0)
  for i = parent_index + 1, count - 1 do
    local track = reaper.GetTrack(0, i)
    balance = balance + math.floor(reaper.GetMediaTrackInfo_Value(track, "I_FOLDERDEPTH"))
    if balance <= 0 then
      return i + 1
    end
  end
  return count
end

local function ensure_parent()
  local parent, index = find_track_by_name(parent_name)
  if not parent then
    parent, index = find_track_by_name(old_parent_name)
  end
  if parent then
    set_track_name(parent, parent_name)
    return parent, index, collect_folder_children(index)
  end

  index = reaper.CountTracks(0)
  reaper.InsertTrackAtIndex(index, true)
  parent = reaper.GetTrack(0, index)
  set_track_name(parent, parent_name)
  return parent, index, {{}}
end

local function ensure_child(parent_index, name, legacy_name)
  local track = find_track_by_name(name)
  if track then
    return track
  end
  if legacy_name and legacy_name ~= "" then
    track = find_track_by_name(legacy_name)
    if track then
      return track
    end
  end
  local insert_index = folder_insert_index(parent_index)
  reaper.InsertTrackAtIndex(insert_index, true)
  return reaper.GetTrack(0, insert_index)
end

local created_names = {{}}
if not project_was_existing then
  clear_default_tracks()
end

reaper.Undo_BeginBlock()
reaper.PreventUIRefresh(1)

local parent, parent_index, children = ensure_parent()
set_track_name(parent, parent_name)
set_track_note(parent, "purpose", "UI requirement group. Empty tracks are placeholders for manual Sound Finder drag/drop.")
set_track_note(parent, "source_session", session_label)
set_track_note(parent, "project_name", project_name)
set_track_note(parent, "project_path", project_path)
reaper.SetMediaTrackInfo_Value(parent, "I_FOLDERDEPTH", 1)
reaper.SetMediaTrackInfo_Value(parent, "I_CUSTOMCOLOR", native_color("Parent"))
table.insert(created_names, parent_name)

for i, req in ipairs(requirements) do
  local track = ensure_child(parent_index, req.name, req.legacy)
  set_track_name(track, req.name)
  set_track_note(track, "ui_requirement_type", req.kind)
  set_track_note(track, "ui_requirement_original", req.original)
  set_track_note(track, "source_session", session_label)
  set_track_note(track, "project_name", project_name)
  set_track_note(track, "project_path", project_path)
  reaper.SetMediaTrackInfo_Value(track, "I_CUSTOMCOLOR", native_color(req.kind))
  reaper.SetMediaTrackInfo_Value(track, "I_FOLDERDEPTH", 0)
  table.insert(created_names, req.name)
end

for i, req in ipairs(requirements) do
  if req.legacy and req.legacy ~= "" then
    local primary_track = find_track_by_name(req.name)
    local legacy_track = find_track_by_name(req.legacy)
    if primary_track and legacy_track and primary_track ~= legacy_track then
      if reaper.CountTrackMediaItems(legacy_track) == 0 then
        reaper.DeleteTrack(legacy_track)
      end
    end
  end
end

local final_children = collect_folder_children(parent_index)
for i, track in ipairs(final_children) do
  if i == #final_children then
    reaper.SetMediaTrackInfo_Value(track, "I_FOLDERDEPTH", -1)
  else
    reaper.SetMediaTrackInfo_Value(track, "I_FOLDERDEPTH", 0)
  end
end

set_project_note("session_id", tostring({session_id}))
set_project_note("title", project_name)
set_project_note("requirement", requirement_text)
set_project_note("source", "Sound Finder")
reaper.MarkProjectDirty(0)
reaper.PreventUIRefresh(-1)
reaper.TrackList_AdjustWindows(false)
reaper.UpdateArrange()
reaper.Undo_EndBlock("Sound Finder: Create UI requirement tracks", -1)

local function write_status(save_result)
  local f = io.open(status_path, "w")
  if f then
    f:write("project_name=" .. project_name .. "\\n")
    f:write("project_path=" .. project_path .. "\\n")
    f:write("project_exists_before=" .. tostring(project_was_existing) .. "\\n")
    f:write("save_result=" .. save_result .. "\\n")
    f:write("parent=" .. parent_name .. "\\n")
    f:write("session_id=" .. tostring({session_id}) .. "\\n")
    f:write("track_count=" .. tostring(#created_names) .. "\\n")
    for _, name in ipairs(created_names) do
      f:write(name .. "\\n")
    end
    f:close()
  end
end

write_status("pending")
local save_result = "missing"
if reaper.Main_SaveProjectEx then
  -- Main_SaveProjectEx returns no value; calling tostring() on it errors.
  reaper.Main_SaveProjectEx(0, project_path, 0)
  save_result = "saved"
else
  reaper.Main_SaveProject(0, false)
  save_result = "fallback"
end
write_status(save_result)
"""
    TRACK_SCRIPT_PATH.write_text(script, encoding="utf-8")
    return TRACK_SCRIPT_PATH


def run_reaper_script(
    script_path: Path,
    project_path: Path | None = None,
    project_was_existing: bool = False,
    timeout_seconds: int = 20,
) -> tuple[bool, str]:
    if TRACK_STATUS_PATH.exists():
        TRACK_STATUS_PATH.unlink()

    initial_mtime = 0.0
    if project_path is not None and project_path.exists():
        initial_mtime = project_path.stat().st_mtime

    command = [str(reaper_exe_path()), "-newinst"]
    if project_path is not None and project_was_existing and project_path.exists():
        command.append(str(project_path))
    command.append(str(script_path))
    try:
        process = subprocess.Popen(command)
    except OSError as exc:
        return False, str(exc)

    deadline = time.monotonic() + timeout_seconds
    status_message = ""
    while time.monotonic() < deadline:
        if TRACK_STATUS_PATH.exists():
            status_message = TRACK_STATUS_PATH.read_text(encoding="utf-8", errors="replace")
            if project_path is None:
                return True, status_message
            if project_path.exists() and project_path.stat().st_mtime > initial_mtime:
                return True, status_message
        if process.poll() is not None:
            break
        time.sleep(0.25)

    if status_message:
        return False, f"REAPER wrote status but project file was not updated: {project_path}\n\n{status_message}"
    return False, f"REAPER did not write status file: {TRACK_STATUS_PATH}"


def create_or_update_reaper_project(
    session_id: int,
    title: str,
    requirement: str,
    categories: list[dict[str, Any]],
    timeout_seconds: int = 20,
    group_name: str = "",
) -> tuple[bool, str, str, Path]:
    project_name, project_path = project_path_for_session(session_id, title, requirement)
    project_was_existing = project_path.exists()
    script_path = write_reaper_track_script(
        session_id,
        title,
        requirement,
        categories,
        project_name,
        project_path,
        project_was_existing,
        group_name=group_name,
    )
    ok, message = run_reaper_script(
        script_path,
        project_path=project_path,
        project_was_existing=project_was_existing,
        timeout_seconds=timeout_seconds,
    )
    return ok, message, project_name, project_path
