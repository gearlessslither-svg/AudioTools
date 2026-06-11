# Audio Production Templates

Use these templates only when the task needs structured output. Keep answers concise when the user asks a narrow question.

## Requirement Candidate Table

| ID | Source | System | Feature | Type | SABC | Reason | Dependency | Ready State | Wwise Need | Unity Need | Asset Estimate | Risk | Next Action |
|---|---|---|---|---|---|---|---|---|---|---|---:|---|---|

Type examples: Music, UI, Gameplay, Foley, VFX, Environment, VO, Mix, System, Debug.

Ready State values:

- `Ready`: enough design/art/program detail exists to produce and integrate.
- `DesignOnly`: final assets are unstable, but audio architecture/spec can be designed.
- `Blocked`: cannot proceed without a specific upstream decision or implementation.
- `Risky`: can proceed, but likely rework must be called out.
- `Cuttable`: optional polish or low-impact content.

## Definition Of Ready

A feature is ready for audio production only when the relevant items are answered:

| Area | Check |
|---|---|
| Design | Gameplay state, success/fail rules, timing, priority, edge cases are known. |
| Art/VFX | Visual/animation reference exists, or placeholder status is explicitly accepted. |
| Program | Trigger owner, Event name, Switch/State/RTPC values, lifecycle, and debug trigger exist. |
| Wwise | Target hierarchy, Bus, attenuation, randomization, voice limit, and SoundBank plan are known. |
| Resource | Asset count, random sample count, naming rule, source/recording plan, and localization need are known. |
| Mix | Priority, ducking, HDR/voice behavior, loudness target, platform constraints are known. |
| QA | Test scene, debug path, expected behavior, and pass/fail criteria are known. |

## Change Impact Report

| Change | Source | Old | New | Audio Impact | Rework Risk | Required Action | Owner |
|---|---|---|---|---|---|---|---|

Always classify impact:

- `NoAudioImpact`
- `ResourceOnly`
- `WwiseOnly`
- `UnityOnly`
- `MixOnly`
- `FullPipeline`
- `UnknownNeedsQuestion`

## Jira Mapping

| Audio Task | Upstream Task | Dependency Type | Blocker? | Ready Signal | Audio Output | QA Evidence |
|---|---|---|---|---|---|---|

Dependency Type examples: DesignRule, VFX, Animation, Prefab, Config, CodeTrigger, Localization, Build, QA.

## Wwise + Unity Design Proposal

For each significant audio feature:

- **Wwise**: Event, Actor-Mixer/Container, Switch/State/RTPC, Bus, Attenuation, SoundBank, voice/performance rule.
- **Unity**: trigger owner, component/prefab/config field, animation notify or state-machine hook, RTPC/Switch timing, debug control.
- **Resources**: source type, count, random sample count, loop/start/stop needs, localization or VO needs.
- **Mix**: loudness role, priority, ducking, spatialization, Player/Others differences, platform notes.
- **QA**: exact test scene, trigger method, expected heard result, log/debug validation, failure cases.

## Post-Change QA Report

| Check | Result | Evidence | Risk | Fix/Question |
|---|---|---|---|---|

Minimum checks:

- Event targets remain stable.
- Switch/State/RTPC groups and assignments match approved design.
- Bus and Attenuation references have the required override flags.
- No accidental `_01`, stale `_Self`, `Play_` Actor names, or duplicated dimensions remain active.
- Source media exists and generated SoundBank coverage is understood.
- Unity contract risks are listed if Event names, paths, or parameters changed.

## Periodic Monitor Summary

- **New audio candidates**:
- **Changed requirements**:
- **Removed/renamed features**:
- **New blockers**:
- **Now ready for audio**:
- **Likely rework**:
- **Suggested Jira updates**:
- **Questions for design/art/program**:
