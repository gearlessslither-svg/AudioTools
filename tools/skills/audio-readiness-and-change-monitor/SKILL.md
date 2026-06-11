---
name: audio-readiness-and-change-monitor
description: Judge whether audio work is ready to start, monitor design/art/program/Jira changes, diff snapshots, and report audio impact, blockers, and rework risk.
---

# Audio Readiness And Change Monitor

Use this skill when audio needs a gatekeeper between upstream production and downstream implementation.

## Core Idea

Audio should not wait blindly for upstream work, but production work should not start without enough facts. Split decisions into `Ready`, `DesignOnly`, `Blocked`, `Risky`, and `Cuttable`.

## Definition Of Ready

A feature is `Ready` only when the required areas are known:

- **Design**: gameplay state, timing, priority, success/fail logic, and edge cases.
- **Art/VFX/Animation**: final or accepted placeholder visual reference.
- **Program**: trigger owner, Event/Switch/State/RTPC lifecycle, config fields, and debug path.
- **Wwise**: hierarchy location, Bus, attenuation, randomization, voice rules, SoundBank strategy.
- **Resource**: asset count, sample count, naming rule, source plan, localization/VO needs.
- **Mix**: priority, ducking, loudness role, spatialization, platform constraints.
- **QA**: test scene, trigger method, expected result, logs/debug validation.

## Evidence Model

Do not infer readiness from optimism, Jira ownership, or a single ambiguous mention. Each readiness item must be backed by an evidence level:

- `Verified`: directly observed in accessible sources, such as design docs, configs, Jira fields, Unity code/assets, Wwise objects, logs, SoundBank data, or explicit user/team confirmation.
- `Inferred`: likely from surrounding evidence, naming, folder ownership, call sites, similar implemented systems, or repeated project conventions, but not directly proven.
- `MissingEvidence`: not found in the accessible sources.
- `UnknownNeedsOwner`: cannot be known from the current access level and requires design, art, program, QA, or audio owner confirmation.

`Unknown` is a valid production result. Never promote `MissingEvidence` or `UnknownNeedsOwner` to `Ready`.

Also grade the source set before making readiness claims:

- `SourceGrade A`: complete, fresh, precise, traceable, and coverage-aware.
- `SourceGrade B`: enough for planning, but some details remain inferred.
- `SourceGrade C`: exploration only; final production or submit decisions would be risky.
- `SourceGrade D`: not enough to judge; request data or owner confirmation first.

Readiness cannot exceed the source grade. A feature with `SourceGrade C/D` should not be reported as fully `Ready` even if one source looks positive.

## How To Check Readiness Without Being Told

Use an evidence ladder for each area:

| Area | Primary evidence | Secondary evidence | If missing |
|---|---|---|---|
| Design clarity | Current design docs, feature specs, config tables, Jira acceptance criteria, patch notes | Similar systems, old docs, naming conventions | Mark `UnknownNeedsDesign`; ask for state, timing, priority, edge cases, and success/fail logic |
| Art/VFX/Animation stability | Final assets, animation clips/controllers, VFX prefabs, scene references, Jira status, asset change history | Placeholder assets accepted by owner, stable naming, low recent churn | Mark `UnknownNeedsArt`; recommend design-only audio planning or placeholder sync work |
| Program trigger/interface | Unity C# calls, serialized Wwise components, prefabs/scenes, config fields, state machines, logs, telemetry | Wrapper APIs, generated constants, nearby gameplay code | Mark `Blocked` or `DesignOnly`; ask for trigger owner, lifecycle, object scope, and debug route |
| Wwise feasibility | Existing Events, RTPCs, Switches, States, Buses, Attenuations, Containers, SoundBanks, media references | Existing templates or sibling systems | Mark `WwiseDesignNeeded` if designable; mark `Blocked` only if external dependency is required |
| Resource scope | Requirement count, system variants, random sample rules, localization needs, naming rules, source plan | Similar feature estimates and SABC priority | Mark `Risky` if count can explode; ask for production quality target and cut line |
| Debug/QA path | Test scene, debug menu, logs, Wwise Profiler route, reproducible steps, QA checklist | Manual repro notes or temporary debug logs | Mark `NeedsRuntimeVerification`; do not claim runtime certainty |

When access is incomplete, output the best evidence and the missing owner instead of pretending to know another department's state.

## Static, Runtime, And Coverage Logic

Readiness is not proven by one source. Treat the project as three overlapping maps:

- **Requirement map**: what design/docs/tasks/configs imply should exist.
- **Static implementation map**: what can be found in Wwise, Unity code/assets, configs, SoundBanks, and source control.
- **Runtime observation map**: what a specific captured play session actually exercised.

These maps answer different questions:

| Question | Best evidence | Limitation |
|---|---|---|
| Should this audio feature exist? | Requirement map | Docs can be stale or incomplete |
| Does an implementation appear to exist? | Static implementation map | Code/assets can be unused or conditionally triggered |
| Did it run correctly in this test? | Runtime observation map | Only covers the played scenario |

Never use one runtime session to infer full-game coverage. If a feature is absent from logs, classify it as `NotObserved` unless static and requirement evidence also indicate it is missing. For full confidence, maintain a coverage matrix by feature/scenario and mark each item as `Required`, `StaticFound`, `RuntimeObserved`, `RuntimeFailed`, `Untested`, or `OwnerUnknown`.

## Change Monitoring Workflow

1. **Load prior snapshot/report** if available.
2. **Scan current docs/tasks/configs** and extract feature states.
3. **Diff changes**: added, removed, renamed, reprioritized, reworded, unblocked, newly blocked.
4. **Classify audio impact**:
   - `NoAudioImpact`
   - `ResourceOnly`
   - `WwiseOnly`
   - `UnityOnly`
   - `MixOnly`
   - `FullPipeline`
   - `UnknownNeedsQuestion`
5. **Update readiness** and identify what can be done now.
6. **Produce upstream questions** targeted to design, art, or program.

## Output

| Feature | Old State | New State | Ready State | Evidence Level | Audio Impact | Rework Risk | Blocker | Owner | Next Action |
|---|---|---|---|---|---|---|---|---|

Also include:

- **Source Quality**
- **Now Ready For Audio**
- **DesignOnly Work Available**
- **New Blockers**
- **Likely Rework**
- **Evidence Gaps**
- **Coverage Gaps**
- **Questions For Upstream**
- **Suggested Jira Updates**

## Rules

- Do not mark a task Ready just because Jira says it is assigned to audio.
- Do not mark a task Ready when any required area is `MissingEvidence` or `UnknownNeedsOwner`.
- Prefer `DesignOnly`, `Blocked`, `Risky`, or `NeedsRuntimeVerification` over false certainty.
- For every cross-department unknown, name the likely owner and the smallest useful question.
- Do not treat `NotObserved` runtime evidence as `MissingImplementation`; absence from one test run only means the scenario was not covered.
- If linked upstream tasks are unresolved, call that out.
- If production is blocked, propose reversible design/scaffolding work when valuable.
- Keep recurring reports diff-friendly and stable in structure.
