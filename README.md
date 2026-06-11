# AudioTools

Private mirror of EdgeFlow / ProjectEF game-audio tooling. This repo holds the
**source** of the tools only — it is a clean mirror kept in sync from the live
working folders; it does **not** contain Unity/Wwise project assets, P4 content,
sound libraries, generated indexes, databases, reports, or secrets.

## Layout

| Path | Source (live) | What it is |
| --- | --- | --- |
| `tools/` | `G:\AI\Material\Wwise\Tools` | ProjectEF audio tool scripts, launchers, skills, EF_Audio_Tools_Final hub |
| `sound_finder/` | `C:\Users\user1\Documents\Reaper` | Sound Finder for Reaper (Python package + REAPER scripts) |
| `sync_audio_tools.py` | — | The sync engine that mirrors the above into this repo |

## Sync workflow

```powershell
python sync_audio_tools.py sync            # mirror live source -> repo + safety scan
python sync_audio_tools.py commit -m "..." # local commit
python sync_audio_tools.py push            # push to origin (explicit, manual)
```

Policy: **commit is local-only; push is always a separate, manual step.**

## What is excluded

Generated indexes/snapshots (`audio_requirement_snapshots/`, `*_jira_index.json`),
the Sound Finder SQLite index (`data/*.sqlite`, ~1.3 GB), `.venv/`, caches,
screenshots, logs, audio media, installers, and any file holding credentials
(the live `audio_requirement_jira_triage_config.json` is replaced by a sanitized
`*.template.json`). See `.gitignore` and the filters in `sync_audio_tools.py`.
