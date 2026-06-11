-- Creates an empty UI requirement track layout for the current REAPER project.
-- No media is inserted; tracks are named for manual drag/drop from Sound Finder.

local status_path = "C:/Users/user1/Documents/Reaper/handoff/ui_requirement_tracks_created_status.txt"

local requirements = {
  { "Large_Back_To_Lobby", "Large" },
  { "Banner_Weekend_Supply_Benefit", "Banner" },
  { "Tile_Backpack", "Tile" },
  { "Tile_Storage", "Tile" },
  { "Tile_Food", "Tile" },
  { "Tile_Repair", "Tile" },
  { "Tile_Fishing_Tackle_Shop", "Tile" },
  { "Large_Go_To_Fishing_Spot", "Large" },
  { "Tile_Skills", "Tile" },
  { "Tile_Outfit", "Tile" },
  { "Tile_Keepnet", "Tile" },
  { "Tile_Quests", "Tile" },
  { "Tile_Vehicle", "Tile" },
  { "Tile_Achievements", "Tile" },
  { "Tile_Collection_Book", "Tile" },
  { "Tile_Map", "Tile" },
  { "Tile_Encyclopedia", "Tile" },
  { "Tile_News", "Tile" },
  { "Tile_Leaderboard", "Tile" },
  { "Tile_Guild", "Tile" },
  { "Tile_Friends", "Tile" },
  { "Resource_Silver_Token", "Resource" },
  { "Resource_Gold_Coin", "Resource" },
  { "Icon_Mailbox", "Icon" },
  { "Icon_Settings_Gear", "Icon" },
  { "Icon_Announcement_Speaker", "Icon" },
  { "Icon_Chat_Support", "Icon" },
  { "Icon_Search_View", "Icon" },
  { "Icon_Event_Guide_Sign_TBC", "Icon" },
}

local colors = {
  Parent = { 72, 132, 214 },
  Large = { 49, 156, 121 },
  Banner = { 49, 156, 121 },
  Tile = { 116, 97, 184 },
  Resource = { 206, 151, 42 },
  Icon = { 88, 142, 173 },
}

local function native_color(kind)
  local c = colors[kind] or colors.Tile
  return reaper.ColorToNative(c[1], c[2], c[3]) | 0x1000000
end

local function track_name_exists(name)
  local count = reaper.CountTracks(0)
  for i = 0, count - 1 do
    local track = reaper.GetTrack(0, i)
    local ok, existing = reaper.GetSetMediaTrackInfo_String(track, "P_NAME", "", false)
    if ok and existing == name then
      return true
    end
  end
  return false
end

local function unique_name(base)
  if not track_name_exists(base) then
    return base
  end
  local suffix = 2
  while track_name_exists(base .. "_" .. tostring(suffix)) do
    suffix = suffix + 1
  end
  return base .. "_" .. tostring(suffix)
end

local function set_track_name(track, name)
  reaper.GetSetMediaTrackInfo_String(track, "P_NAME", name, true)
end

local function set_track_note(track, key, value)
  reaper.GetSetMediaTrackInfo_String(track, "P_EXT:codex_" .. key, value, true)
end

local parent_name = unique_name("UI")
local start_index = reaper.CountTracks(0)
local created_names = {}

reaper.Undo_BeginBlock()
reaper.PreventUIRefresh(1)

reaper.InsertTrackAtIndex(start_index, true)
local parent = reaper.GetTrack(0, start_index)
set_track_name(parent, parent_name)
set_track_note(parent, "purpose", "UI feature requirement group. Empty tracks are placeholders for manual Sound Finder drag/drop.")
reaper.SetMediaTrackInfo_Value(parent, "I_FOLDERDEPTH", 1)
reaper.SetMediaTrackInfo_Value(parent, "I_CUSTOMCOLOR", native_color("Parent"))
table.insert(created_names, parent_name)

for i, req in ipairs(requirements) do
  local track_index = start_index + i
  reaper.InsertTrackAtIndex(track_index, true)
  local track = reaper.GetTrack(0, track_index)
  local name = req[1]
  local kind = req[2]
  set_track_name(track, name)
  set_track_note(track, "ui_requirement_type", kind)
  set_track_note(track, "ui_requirement_order", tostring(i))
  set_track_note(track, "source_session", "Sound Finder session 9")
  reaper.SetMediaTrackInfo_Value(track, "I_CUSTOMCOLOR", native_color(kind))
  if i == #requirements then
    reaper.SetMediaTrackInfo_Value(track, "I_FOLDERDEPTH", -1)
  else
    reaper.SetMediaTrackInfo_Value(track, "I_FOLDERDEPTH", 0)
  end
  table.insert(created_names, name)
end

reaper.PreventUIRefresh(-1)
reaper.TrackList_AdjustWindows(false)
reaper.UpdateArrange()
reaper.Undo_EndBlock("Codex: Create UI feature requirement tracks", -1)

local f = io.open(status_path, "w")
if f then
  f:write("created_parent=" .. parent_name .. "\n")
  f:write("created_count=" .. tostring(#created_names) .. "\n")
  f:write("start_index=" .. tostring(start_index + 1) .. "\n")
  for _, name in ipairs(created_names) do
    f:write(name .. "\n")
  end
  f:close()
end
