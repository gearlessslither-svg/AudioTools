---
name: unity-audio-integration-audit
description: Scan Unity projects for Wwise/audio integration usage, including PostEvent, RTPC/Switch/State calls, Ak components, scenes/prefabs/assets, surrounding logic, inferred trigger lifecycle, missing Wwise events, and implementation risks.
---

# Unity Audio Integration Audit

Use this skill when the user wants to connect Unity-side gameplay logic with Wwise/audio design, inspect event triggers, understand pre/post call logic, or produce an audio integration report.

## What It Answers

- Which Wwise/audio Events are called from Unity?
- Which scripts, prefabs, scenes, animations, timelines, or assets reference audio?
- What logic appears before and after each audio call?
- Which RTPC/Switch/State values are set near each Event?
- Which calls are risky, such as `PostEvent` in `Update`, string-literal Events, missing stop logic, unknown Wwise Event names, or missing debug paths?
- What can be inferred about gameplay state, owner system, lifecycle, and implementation completeness?

## Required Inputs

Minimum:

- Unity project root, usually the folder containing `Assets/` and `ProjectSettings/`.

Recommended:

- Wwise project root or latest Wwise audit JSON/HTML/Markdown.
- Project profile with naming rules and perspective/gender/material rules.
- P4 changelist or list of changed Unity files when auditing a specific integration.

Optional for deeper validation:

- Unity Editor path for batchmode AssetDatabase scans.
- Runtime logs, QA scene, or debug menu path.
- Permission to add a temporary Editor audit script if static text scanning is insufficient.

## Default Safety

- Static scan is read-only and does not require Unity to be open.
- Prefer scanning with Unity closed, especially around P4 Get Latest/Reconcile/Submit.
- Do not add Editor scripts, modify prefabs, open scenes, or run PlayMode unless the user explicitly asks.
- Treat code/YAML findings as evidence, but label inferred gameplay meaning with confidence.

## Workflow

1. **Confirm roots**: Unity root, Wwise root, report output path, and whether this is full-project or changed-files-only.
2. **Collect Wwise Event vocabulary**: parse Wwise `.wwu` files or a prior Wwise audit JSON if available.
3. **Scan C#**: detect `AkSoundEngine.PostEvent`, `AK.Wwise.Event.Post`, `SetRTPCValue`, `SetSwitch`, `SetState`, bank loads, stops, and action calls.
4. **Scan Unity assets**: inspect scenes, prefabs, assets, controllers, animations, and timelines for Wwise component/script references and serialized Event-like names.
5. **Infer logic**: for each call, capture class, method, lifecycle, nearby conditions, nearby RTPC/Switch/State calls, and likely owner system from file path.
6. **Cross-check Wwise**: mark known Events, unknown names, unresolved constants, and calls that likely depend on generated IDs.
7. **Risk report**: list high-frequency triggers, loop Events without stop, string literals, Update calls, missing perspective/gender setup, missing debug route, and source-control risks.
8. **Recommend next actions**: separate immediate fixes, design questions, program questions, and QA tests.

## Output

For full reports, include:

- **Summary**: counts of scripts/assets scanned, calls, Events, RTPC/Switch/State usage, risks.
- **Event Call Map**: Event/constant, file, line, class, method, lifecycle, owner system, Wwise known/unknown.
- **Pre/Post Logic**: nearby conditions, RTPC/Switch/State setup before calls, stop/action calls after calls.
- **Asset Reference Map**: prefabs/scenes/assets with Ak/Wwise component references.
- **Risk And Inference**: likely problems, confidence, possible causes, suggested fix.
- **Questions**: only questions required to make a safe implementation decision.

## Script

Use the bundled script for a first-pass static scan:

```powershell
python "$env:USERPROFILE\.codex\skills\unity-audio-integration-audit\scripts\unity_audio_integration_audit.py" `
  --unity-root "D:\Path\To\UnityProject" `
  --wwise-project-root "D:\Path\To\WwiseProject" `
  --out "G:\AI\Material\Wwise\Unity_Audio_Integration_Audit.md" `
  --json-out "G:\AI\Material\Wwise\Unity_Audio_Integration_Audit.json"
```

## Rules

- Do not claim runtime certainty from static code alone. Use `Inferred` or `NeedsRuntimeVerification`.
- Prefer exact file and line references.
- Do not treat every unknown Event as wrong; generated constants or serialized `AK.Wwise.Event` fields may need AssetDatabase resolution.
- For loops and persistent states, require lifecycle evidence: start, update, stop/reset, scene unload behavior.
- For player/others, gender, perspective, material, weather, and body-state audio, check that Unity sets the required Switch/State/RTPC at the right owner and timing.
