---
name: audio-implementation-qa
description: QA audio implementation across Wwise, Unity, source assets, events, RTPC/Switch/State, Bus/Attenuation, SoundBanks, mix, performance, and version-control risk after changes.
---

# Audio Implementation QA

Use this skill after Wwise/Unity/audio-source changes, or before submitting audio-related work.

## Scope

QA implementation, not taste alone. Check whether the system behaves as designed, is shippable, and is safe for other team members.

## Workflow

1. **Collect intended design**: approved plan, changed files, touched systems, expected Event/RTPC/Switch/State behavior.
2. **Inspect Wwise**: use `wwise-project-audit` or `wwise-project-resource-audit` for object targets, routing, attenuation, naming, media, banks, and upgrade risks.
3. **Inspect Unity**: use `unity-audio-integration-audit` when project files are available; check triggers, config fields, animation notifies, prefab references, `.meta` pairs, generated code/constants, and debug controls.
4. **Check source control**: identify source assets vs generated/cache output, asset/meta pairs, plugin binaries, SoundBank policy, and likely accidental files.
5. **Mix/performance pass**: check bus priority, ducking, voice limits, virtual voice behavior, player/others differences, high-frequency spam, and platform budgets.
6. **Report evidence**: include counts, paths, exact risks, likely causes, and suggested fixes.

## QA Checklist

- Event Actions target the intended object and not an accidental leaf or obsolete branch.
- Event/API names remain stable unless Unity changes are approved.
- Switch/State/RTPC groups exist, values are assigned, defaults are sane, and lifecycles are clear.
- Bus and Attenuation references have required override flags.
- Player/Others, 1P/3P, Gender, Surface, Weather, Material, and other dimensions are not duplicated in conflicting layers.
- No accidental `_01`, stale `_Self`, misleading `Play_*` Actor names, or typo names remain active.
- Missing media, unreferenced media, empty active containers, and generated-bank gaps are reported.
- High-frequency sounds have randomization, voice limits, priority, and mix rules.
- Unity `.meta` files are paired with assets and not mixed from different resolve sides.

## Output

| Check | Result | Evidence | Likely Cause | Fix Recommendation | Needs User Decision |
|---|---|---|---|---|---|

Use result values:

- `Pass`
- `Warn`
- `Fail`
- `NeedsDecision`
- `NotChecked`

## Rules

- Do not make fixes during QA unless the user explicitly asks.
- If the user asks to fix, state the intended change list first for risky Wwise/Unity/API changes.
- Prefer exact file/object paths over general statements.
- If a problem came from a user-approved rule that now looks wrong, challenge it respectfully and propose a safer rule.
