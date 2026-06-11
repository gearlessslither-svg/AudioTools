---
name: game-audio-production-intelligence
description: Use when building or running an AI-assisted game audio production workflow across design docs, art/program dependencies, Jira/tasks, Wwise, Unity, resource estimation, readiness gates, change monitoring, and post-change QA.
---

# Game Audio Production Intelligence

Use this skill when the user wants AI to act as a game-audio production center: discover audio needs, challenge incomplete requirements, judge readiness, estimate assets and effort, connect Jira/design/Wwise/Unity, monitor changes, and QA implementation.

## Operating Principle

Audio is usually downstream of design, art, and engineering, but audio work should not be completely idle while upstream work is unstable. Separate work into:

- **Exploration**: project understanding, system maps, risk discovery, placeholder design, naming standards, Wwise/Unity scaffolding proposals.
- **Ready production**: asset creation, Wwise authoring, Unity integration, mix tuning, final QA.

Before accepting any task, challenge it against project context, audio-design intent, implementation cost, and dependency readiness. If the rule is unclear, state the risk and ask a specific question or propose a reversible placeholder plan.

Do not confuse runtime observation with whole-project truth. A captured play session only proves what happened in that session. Use design docs to predict required audio coverage, static Unity/Wwise scans to detect implementation presence, and runtime logs/profiler captures to validate exercised scenarios. Anything not exercised must be reported as `Untested` or `NotObserved`, not as correct or missing.

## Source Quality Gate

AI production judgment is only as strong as the material it can inspect. Before broad recommendations, grade the source base:

- **Completeness**: Are design docs, configs, Wwise, Unity, logs, tasks, and user confirmations all available for this question?
- **Freshness**: Are the files and reports current, or could they be stale after a sync, Wwise upgrade, branch change, or design change?
- **Precision**: Do sources name exact triggers, states, owners, resource counts, and expected behavior?
- **Traceability**: Can each claim link to a file, report, object, log line, screenshot, changelist, or explicit confirmation?
- **Coverage**: Does runtime evidence cover the tested scenario, or is it only a narrow play session?

Use grades:

- `SourceGrade A`: enough evidence for high-confidence recommendations.
- `SourceGrade B`: enough for planning, but some details remain inferred.
- `SourceGrade C`: useful for exploration only; do not commit to final production decisions.
- `SourceGrade D`: too incomplete; output data requests and owner questions first.

Reports must say what evidence was available, what was missing, and how that limits confidence.

## Inputs To Inspect

Prefer local project sources over memory:

- Design docs, feature specs, economy/combat/progression docs, config tables, localization sheets.
- Art references, VFX lists, animation lists, prefabs, naming conventions, final/placeholder status.
- Engineering specs, Unity scripts/configs, event trigger tables, debug tools, Jira/task metadata.
- Wwise project state via `wwise-project-audit` or `wwise-project-resource-audit`.
- Existing audio requirement sheets, SABC lists, resource totals, implementation plans, QA reports.

If a source may be stale, mark it as unverified. Do not treat Jira, docs, or Wwise as individually complete; compare them.

## Core Workflow

1. **Project context pass**: identify genre, core loops, player perspective, multiplayer model, platform/performance constraints, major systems, and current audio architecture.
2. **Requirement mining**: convert docs and tasks into candidate audio needs by system and sound type. Include SABC priority, dependency owners, implementation surface, and likely resource count.
3. **Challenge gate**: question unclear names, duplicated dimensions, missing triggers, unstable art/VFX, missing config fields, unrealistic bespoke-resource requests, and features with no acceptance criteria.
4. **Definition of Ready**: classify each candidate as `Ready`, `DesignOnly`, `Blocked`, `Risky`, or `Cuttable`.
5. **Design proposal**: for ready or designable work, propose Wwise objects, Unity trigger/config fields, resource counts, random sample rules, mix/bus logic, and QA method.
6. **Task mapping**: map needs to Jira or task units. Keep audio tasks linked to upstream design/art/program tasks, but maintain an audio-owned queue so audio can forecast workload before upstream completion.
7. **Implementation guardrail**: before edits, produce exact changes and wait for confirmation when the operation touches Wwise hierarchy, Events, Bus routing, RTPC/Switch/State, Unity contracts, or versioned assets.
8. **Post-change QA**: after edits, audit object targets, routes, attenuations, switches/states/RTPCs, generated assets, naming, performance risks, and residual open questions.
9. **Change monitoring**: on each new scan, diff against prior reports and identify added/removed/renamed features, changed priorities, changed dependencies, and audio rework impact.

For broad validation, maintain a coverage matrix:

| Feature/Scenario | Required By | Static Unity | Static Wwise | Runtime Session | Status | Next Test |
|---|---|---|---|---|---|---|

Use statuses such as `Ready`, `DesignOnly`, `Blocked`, `Risky`, `ObservedPass`, `ObservedFail`, `StaticOnly`, `NotObserved`, and `NeedsScenario`.

## Challenge Gate

Always look for these before saying “yes”:

- A design request describes a feeling, but not the gameplay state or trigger that causes it.
- A feature depends on VFX/animation/art that is placeholder or still moving.
- A programmer-facing trigger has no owner, no parameter range, no lifecycle rule, or no debug path.
- A resource request asks for per-item/per-fish/per-weapon bespoke sound where a template plus Switch/RTPC would be cheaper and safer.
- The same dimension appears in multiple layers, such as path name, object name, Switch, and Event all encoding Gender/Perspective/Surface.
- A Jira task says audio is unblocked, but its linked design/art/program tasks are unresolved.
- Generated Wwise/Unity assets appear in source control without a clear rule for whether they are source assets or build/cache output.

## Output Standard

For substantial work, produce these sections:

- **Assumptions**: what is verified, inferred, or unknown.
- **Source Quality**: completeness, freshness, precision, traceability, and coverage limits.
- **Requirement Map**: audio candidates by system and type with SABC priority.
- **Readiness**: Ready/DesignOnly/Blocked/Risky/Cuttable and why.
- **Coverage Scope**: what was actually scanned or played, and what remains untested or unknown.
- **Plan**: Wwise, Unity, resource, mix, QA, and owner/dependency steps.
- **Questions**: only the questions that block a correct decision.
- **Next Actions**: what AI can do now, what humans must decide, what upstream teams must provide.

For reusable table formats, read `references/audio-production-templates.md`.

## Skill Coordination

- Use `game-audio-project-profile` to create or refresh the durable project context before broad planning.
- Use `audio-requirement-mining` to turn design docs, specs, and task lists into SABC audio requirement candidates.
- Use `audio-readiness-and-change-monitor` to judge whether work is ready, blocked, risky, or newly changed.
- Use `audio-resource-budgeting` to produce music/SFX/VO totals, random sample needs, Wwise/Unity/mix steps, and time estimates.
- Use `audio-implementation-qa` for post-change QA across Wwise, Unity, source media, mix, performance, and submit risk.
- Use `unity-audio-integration-audit` to scan Unity-side Wwise/audio calls, serialized audio references, pre/post trigger logic, and implementation risks.
- Use `game-audio-version-control-guard` for Unity/Wwise source-control decisions, Perforce resolve/reconcile/revert, `.meta`, plugin binaries, and SoundBank submit questions.
- Use `wwise-project-audit` for Wwise design reasoning, WAAPI modification plans, and post-edit QA.
- Use `wwise-project-resource-audit` for project/resource health reports, SoundBank/source media checks, version-upgrade checks, and HTML/Markdown audit reports.
- Use `overnight-autonomous-runner` for long scans and recurring handoffs.
- Use `codex-connection-resilience` when long-running work must survive network disconnects.

## Safety Rules

- Do not modify Wwise, Unity, source assets, or Jira unless the user explicitly asks.
- When the user asks for modification, first challenge the design and present the intended change list unless they already approved that exact pattern.
- Keep Event/API names stable unless the user accepts Unity contract changes.
- Prefer templates, Switches, States, RTPCs, and reusable containers over large bespoke resource explosions.
- Treat `.meta`, Wwise WorkUnits, SoundBanks, plugin binaries, and generated media according to project version-control policy; if unclear, ask or report the risk.
