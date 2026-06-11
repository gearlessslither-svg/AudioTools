---
name: unity-wwise-runtime-log-audit
description: Analyze Unity Editor/Player logs and Wwise-related runtime/build logs to identify audio-related lines, abnormal behavior, likely causes, and safe fix recommendations without modifying the project.
---

# Unity Wwise Runtime Log Audit

Use this skill when the user wants to diagnose audio behavior from Unity logs, Wwise runtime messages, build logs, Player logs, Editor logs, or QA logs.

## Purpose

Wwise Profiler shows what reaches Wwise. This skill fills the Unity-side gap: why calls were made, why calls did not reach Wwise, whether banks/media/plugins are missing, whether RTPC/Switch/State/Event names are wrong, and what likely caused runtime audio errors.

## Inputs

Minimum:

- One or more log files, or a Unity project root so common logs can be discovered.

Recommended:

- Wwise project root to parse known Event names.
- Static Unity audio audit JSON from `unity-audio-integration-audit`.
- Current Wwise resource audit report or SoundbanksInfo.xml.
- A short description of what the tester heard or did not hear.

Common log locations:

- `%LOCALAPPDATA%\Unity\Editor\Editor.log`
- `%LOCALAPPDATA%\Unity\Editor\Editor-prev.log`
- `%USERPROFILE%\AppData\LocalLow\<CompanyName>\<ProductName>\Player.log`
- Project-local `Logs/`, `BuildLogs/`, or CI build output.

## Workflow

1. **Collect logs**: use explicit paths first; otherwise discover common Unity Editor/Player/project logs.
2. **Filter audio-related lines**: Wwise, AkSoundEngine, AkBank, SoundBank, PostEvent, RTPC, Switch, State, WEM/BNK, audio plugin, generated banks, license, and audio exceptions.
3. **Classify behavior**: Event, Bank/Media, RTPC/Switch/State, Init/Plugin, Build/Packaging, License, Unity Exception, Performance, UnknownAudio.
4. **Detect abnormal lines**: errors, warnings, missing/invalid names, failed loads, bank read errors, plugin mismatch, no license key, null references near audio, repeated spam.
5. **Cross-check**: compare event-like names in logs with parsed Wwise Event names and static Unity call map when available.
6. **Infer cause**: provide confidence-labeled likely causes and non-destructive fix recommendations.
7. **Report next verification**: suggest Wwise Profiler checks, Unity debug logs, bank generation, or targeted scene tests.

## Realtime Follow Mode

For near-real-time diagnosis while the game is running, use `--follow`. This tails Unity Editor/Player logs and writes a rolling report plus optional JSONL entries:

```powershell
python "$env:USERPROFILE\.codex\skills\unity-wwise-runtime-log-audit\scripts\unity_wwise_runtime_log_audit.py" `
  --unity-root "D:\Path\To\UnityProject" `
  --wwise-project-root "D:\Path\To\WwiseProject" `
  --static-audit-json "G:\AI\Material\Wwise\Unity_Audio_Integration_Audit.json" `
  --out "G:\AI\Material\Wwise\Unity_Wwise_Runtime_Audio_Follow.md" `
  --json-out "G:\AI\Material\Wwise\Unity_Wwise_Runtime_Audio_Follow.json" `
  --jsonl-out "G:\AI\Material\Wwise\Unity_Wwise_Runtime_Audio_Follow.jsonl" `
  --follow
```

This mode is still read-only. It observes logs; it does not inject code, call Unity APIs, or modify scenes.

Realtime GUI tools built from this skill should expose two always-updating diagnosis areas in addition to the raw log stream:

- **Problem screening**: group repeated abnormal lines by likely issue, such as Stop Event bank load failure, Voice Starvation, Source Starvation, missing bank/media, unknown Event, or RTPC/Switch/State failure.
- **Analysis suggestion**: when a grouped issue is selected, show latest evidence, affected Event/source, confidence, likely cause, and safe next verification/fix recommendations.
- **Bilingual suggestion**: if the user asks for bilingual output, show the likely cause and recommendation in both Chinese and English so the same report can be used by audio designers and programmers.
- **Test session coverage**: let the tester label the current run with scene/map, perspective, mode, character, gear, fish, weather, and planned scenarios. The report should then compare planned scenarios with observed runtime audio evidence and mark each item as `ObservedPass`, `ObservedFail`, `ObservedWarn`, `PlannedNotObserved`, `ObservedUnplanned`, or `NotObserved`.

If Unity does not log successful audio calls, follow mode can only diagnose warnings/errors and any custom logs already emitted by the project. For full causal traces, add a program-side audio telemetry layer that logs structured records for `PostEvent`, `SetRTPC`, `SetSwitch`, `SetState`, bank load/unload, owner GameObject, scene, frame, position, and gameplay state.

## Runtime Coverage Boundaries

Runtime logs and Wwise Profiler captures are session evidence, not full-game proof. A single play session can prove that observed paths happened and whether those observed paths produced errors. It cannot prove that unplayed systems, unvisited scenes, unused characters, untriggered weather, untested fish, untested gear, or untested UI flows are correct.

Always separate these states:

- `ObservedPass`: the behavior was exercised in this session and no relevant abnormal evidence was found.
- `ObservedFail`: the behavior was exercised and produced clear abnormal evidence.
- `ObservedWarn`: the behavior was exercised and produced suspicious but not conclusive evidence.
- `NotObserved`: the behavior did not appear in this session; do not call it missing or correct.
- `StaticOnly`: the behavior exists in code/Wwise/assets, but no runtime evidence was captured.
- `NeedsScenario`: a specific play path or QA step is required before runtime judgment.

Rules:

- Never infer whole-game correctness from one runtime log.
- Never treat absence from one log as proof that a Unity interface, Wwise Event, or audio feature does not exist.
- Phrase missing runtime evidence as "not observed in this captured session" unless static sources also show it is missing.
- Require session metadata when possible: map/scene, character, perspective, gear, fish, weather, UI flow, multiplayer state, test duration, and tester action notes.
- For broad coverage, build a scenario matrix from design requirements and static Unity/Wwise maps, then mark each feature as `Observed`, `StaticOnly`, `Untested`, or `NeedsManualRepro`.

## Output

- **Summary**: log files scanned, audio lines, abnormal lines, categories, event names, risk level.
- **Key Findings**: severity, category, file, line, event/name, evidence, likely cause, recommendation.
- **Timeline**: ordered audio-related runtime messages.
- **Cross-Checks**: known/unknown Wwise Events, missing banks/media, static-call correlation.
- **Coverage Scope**: what the captured session actually exercised, what was not observed, and which scenarios still need testing.
- **Next Tests**: exact safe checks to run next.

## Rules

- This skill is read-only by default.
- Do not claim a fix was applied unless a separate modification step was approved and executed.
- Label inference confidence as `High`, `Medium`, or `Low`.
- A missing Wwise Profiler event can be caused before Wwise: Unity condition not met, object not registered, bank not loaded, event field empty, generated IDs stale, scene lifecycle ordering, or code path not executed.
- Do not use a single runtime capture as whole-project validation. Runtime reports must state their coverage scope.
- Prefer exact log lines and paths over broad explanations.
