# EF Audio Tools Final

This folder contains final user-facing launchers only. Source tools stay in their original folders to avoid duplicated versions.

Recommended entry:

- GUI: `Start_EF_Audio_Tools_GUI.cmd`
- Root shortcut: `G:\AI\Material\Wwise\Start_EF_Audio_Tools_GUI.cmd`

The GUI intentionally shows only the main manual tools. Report generators, background/watch tools, scheduled-task maintenance, legacy helpers, and one-off checks are hidden from the GUI but kept in this folder.

## Main GUI Tools

1. `01_Sound_Finder_for_Reaper.cmd`
   - SFX search, preview, recommendation, and Reaper handoff.

2. `02_UnityWwise_Log_Monitor_GUI.cmd`
   - Main realtime Unity/Wwise log monitor GUI.

3. `06_Open_Report_Dashboard.cmd`
   - Opens the local ProjectEF report dashboard.

4. `08_Wwise_Template_Generator.cmd`
   - Opens the Wwise template generator GUI.

5. `17_Wwise_Profiler_Voice_Capture.cmd`
   - Captures active Wwise Profiler voices, Unity starvation/underrun log findings, and machine metrics.
   - When launched from the GUI, duration and sampling interval can be changed before launch.
   - The report separates audio-content evidence from engine, thread scheduling, streaming IO, and machine budget evidence.

6. `19_P4V_Changelist_Organizer_GUI.cmd`
   - Filters, labels, learns from marked examples, and sorts ProjectEF audio-related pending files into P4 changelist groups.
   - Supports a task-goal memory file and optional Ollama local AI review for selected rows.
   - Supports selected-only moves and creating one fresh pending changelist for selected rows.
   - Uses only `p4 opened`, `p4 diff`, `p4 change -i`, and confirmed `p4 reopen`; it does not revert, add, delete, submit, or modify file contents.

7. `20_UIAudio_StaticInspector_GUI.cmd`
   - Read-only static UI audio scan for Unity Prefab/Scene coverage.
   - Checks `ButtonEx`, `ToggleEx`, `ButtonAudioComp`, `UIStateOnClickSoundController`, prefab instance audio overrides, default fallback events, duplicate UI names, and Wwise Event validity.
   - Generates Markdown, HTML, JSON, and CSV reports under `G:\AI\Material\Wwise\报告`.

8. `21_Animation_Wwise_Event_AutoConfig.cmd`
   - Opens the Animation Wwise Event AutoConfig GUI.
   - Locates source `.fbx` or editable `.anim` clips, maps source clips to editable runtime `.anim` files, validates the requested Wwise Event, previews analyzed keyframe times on a motion timeline, and writes Animation Events after confirmation.
   - Reads the Wwise Event target and source WAV durations. For one-shot `RandomSequenceContainer` targets, it raises the effective event spacing to at least the longest source duration to avoid repeated overlap.
   - Can write a Unity preview request to `D:\EF New\Client\TargetProject\Temp\ProjectEF_AnimationWwiseEventPreviewRequest.json` and open the Unity EditorWindow `ProjectEF/Audio/Animation Wwise Event Preview` for actual prefab animation playback with event markers.
   - The GUI can open the edited `.anim` directly in a text editor for manual inspection or edits.
   - Uses the existing `WwiseAudioHelper` public playback API; it does not modify the helper.
   - The old prompt-style launcher is still available as `G:\AI\Material\Wwise\Tools\Start_ProjectEF_AnimationWwiseEvent_AutoConfig_CLI.cmd`.

9. `22_AudioRequirement_Jira_Triage_GUI.cmd`
   - Read-only GUI for scanning `D:\EF New\Design` into a versioned audio requirement evidence index.
   - Supports common design-source formats including `.docx`, `.xlsx`, `.md`, `.txt`, and `.pdf`.
   - Matches Jira issues or pasted Jira text to exact design document paths and locators.
   - Classifies whether audio work is needed and whether it is `Ready`, `DesignOnly`, `Risky`, `Blocked`, or `Cuttable`.
   - Supports optional Ollama local AI review for selected issues.
   - Supports `Scan + Diff Changes` to compare the current design tree against the previous snapshot and report possible newly added audio needs.
   - Does not modify Jira, Unity, Wwise, P4, or source documents.

## Advanced Hidden Tools

These launchers are still available directly or through `Start_EF_Audio_Tools_Menu.cmd` > `Advanced`.

- `03_AI_Work_Impact_Week.cmd`
- `04_AI_Work_Impact_Month.cmd`
- `05_Audio_Report_Trend_Once.cmd`
- `07_Daily_Log_Intelligence.cmd`
- `09_Audio_Report_Trend_Watch_3h.cmd`
- `10_Runtime_Audio_Follow_Visible.cmd`
- `11_Runtime_Audio_Follow_Minimized.cmd`
- `12_Runtime_Audio_Follow_Stop.cmd`
- `13_Register_Audio_Trend_Task.cmd`
- `14_Unregister_Audio_Trend_Task.cmd`
- `15_Register_Daily_Log_Task.cmd`
- `16_Unregister_Daily_Log_Task.cmd`
- `18_P4V_Audio_Changelist_Check.cmd`
- `23_AudioRequirement_ScanDiff_Once.cmd`
  - Runs one read-only design-doc scan, saves a versioned snapshot, compares it with the previous index, and writes audio requirement diff reports.
  - Intended for automation or scheduled-task wrapping; the GUI remains the preferred manual entry.
- `24_Register_AudioRequirement_Task.cmd`
  - Registers a daily Windows scheduled task for `23_AudioRequirement_ScanDiff_Once.cmd`.
  - The task is not active until this launcher is run deliberately.
- `25_Unregister_AudioRequirement_Task.cmd`
  - Removes the daily audio requirement scan/diff scheduled task.

## Visibility Rule

`tool_paths.json` owns the GUI visibility rule:

- `visible: true` means the tool appears in the GUI.
- `visible: false` means the launcher is hidden from the GUI but remains available as an advanced tool.

Use `visible: true` only for tools that are safe, distinct, and useful as daily manual entry points.

## SoundBank Generation Rule

Generate SoundBanks is a protected action.

- No GUI tool, report tool, QA tool, or template tool should generate SoundBanks unless the user explicitly asks for that exact action in the current task.
- Recommending regeneration is not permission to perform regeneration.
- Before any future tool is allowed to generate banks, it must show the planned output scope and wait for explicit approval.
- Changelist/provenance tools should classify `GeneratedSoundBanks`, `GeneratedSoundBanks_Backup_*`, `.cache`, `.prof`, `.wsettings`, and validation caches separately from authored Wwise source.
