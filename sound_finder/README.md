# Sound Finder for Reaper

A local sound-library workbench for Reaper. It can still accept a Codex-written plan through `handoff/current_plan.json`, and it now also has an auto-routed model mode that lets you type the requirement inside the GUI, use remote GPT when it is healthy, fall back to a local LLM when it is not, then search, recommend, preview, and drag files into Reaper.

## Start

Run in PowerShell:

```powershell
.\run.ps1
```

The first run creates `.venv` and installs PySide6. Later runs only reinstall
dependencies when `requirements.txt` changes.

## Workflow

1. Use `模型拆解/搜索` in the GUI, or discuss the sound requirement with Codex.
2. Local mode or Codex creates/updates `handoff/current_plan.json`.
3. Click `Import Codex Plan` only when you want to load an external Codex plan.
4. Choose a sound-library root folder.
5. Click `Scan/Update Index`.
6. Click `Confirm And Search`.
7. Browse results by category, preview files, favorite, mark used, or drag files into Reaper.
8. Click `Recommend Combo` to get a layer-based recommendation for the selected category.
9. Click `Change Recipe` to switch the selected category to another analyzed style recipe and re-search it.
10. Click `Random Similar Material` to replace one recommended layer with a close alternative.

Clearing the current work area does not delete saved sessions or search results.

## Local / Remote Model Mode

Click `模型拆解/搜索` in the GUI. The dialog accepts:

- `Auto`: checks remote GPT before each request. If it is reachable and faster than the configured threshold, the request uses the remote model; if it is unavailable or slow, the request uses the local model.
- `Remote`: forces the remote GPT-compatible endpoint.
- `Local`: forces the local model.
- `Ollama`: default `http://127.0.0.1:11434`, model default `qwen3:8b`.
- `OpenAI-compatible / LM Studio`: default `http://127.0.0.1:1234/v1`.

The tool stores the last routing mode, provider, URL, model, timeout, and category limit in the local SQLite settings table. Generated plans are written to `handoff/current_plan.json`, so the old Codex handoff path remains compatible. Status messages include the actual model source, such as `remote:gpt-5-mini` or `local:ollama:qwen3:8b`.

Recommended local setup for this machine:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\setup_local_llm.ps1
```

If strict JSON output is more important than reasoning quality, keep this fallback model available:

```powershell
ollama pull qwen2.5:7b-instruct
```

CLI generation is also available:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 --generate-local-plan "钓鱼游戏背包、购买、奖励、错误反馈 UI 音效" --llm-mode auto --remote-model gpt-5-mini --local-model qwen3:8b
```

If you want a rule-based fallback when the local model is offline:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 --generate-local-plan "需求文本" --local-rule-fallback
```

Codex mode is unchanged: Codex can still write `handoff/current_plan.json`, and the GUI can still load it with `导入 Codex 方案`.

## Current Test

Seed the current fishing-game UI-button requirement with a demo library, search results, and recommendations:

```powershell
.\run.ps1 --seed-current-test
```

Then launch the GUI:

```powershell
.\run.ps1
```

The GUI auto-loads the latest seeded test session.

## Saved Data

Local data is saved at:

```text
data/sound_finder.sqlite
```

The database stores:

- sound-library index
- each requirement session
- category keywords
- layer recipes
- search results
- recommended combos
- favorite and used flags

## REAPER Script Status

Check Codex-managed REAPER scripts and current Action List bindings:

```powershell
.\.venv\Scripts\python.exe tools\reaper_script_status.py
```

Install or update workspace-managed REAPER scripts into the REAPER resource path:

```powershell
.\.venv\Scripts\python.exe tools\install_reaper_scripts.py
```

Current expected shortcut:

```text
Ctrl+Alt+Shift+S -> Codex_Visual slicer for selected item via source file.lua
Ctrl+Alt+Shift+B -> Wwise Bridge Ver2.0.lua
```

The visual slicer uses a default "Balanced visual blocks" preset. To adjust the
cutting behavior, load and run `Codex_Visual slicer preset settings.lua` from
REAPER's Action List, choose a preset, Undo the previous cut if needed, and run
the main slicer again.

`Wwise Bridge Ver2.0.lua` scans the current project regions, lets you batch
select regions, renders selected regions with the current REAPER render format,
and creates Random or Switch Containers in Wwise through ReaWwise/WAAPI. For
Switch Containers, click `Connect / Refresh Wwise`, choose a Switch/State Group,
then review the per-child assignments before starting the export/import.

## Maintenance

Show database size, row counts, indexes, settings, and current library count:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 --db-status
```

Run the representative search benchmark:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 --benchmark-search
```

Run a custom benchmark set:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 --benchmark-search "water splash;button click"
```

Rebuild the FTS5 search index after large manual database changes:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 --rebuild-fts
```

Current FTS5 benchmark after optimization is roughly `0.14-0.49s/query` on a
1.7M-row audio index. The previous baseline was roughly `1.18-2.41s/query`.
