---
name: game-audio-project-profile
description: Build and maintain a reusable audio project profile from design docs, Wwise, Unity, source-control rules, naming conventions, platform constraints, and known production pitfalls.
---

# Game Audio Project Profile

Use this skill when a project needs a durable audio context packet before requirement mining, Wwise edits, Unity integration, or QA. The output should let future agents understand the project without rediscovering basics.

## Purpose

Create a project-specific profile that captures verified facts, inferred rules, open questions, and known risks. Treat it as the audio onboarding document for humans and agents.

## Inputs

- Design-doc roots and important feature documents.
- Wwise project path, Authoring version, WAAPI endpoint, SoundBank output path.
- Unity project path, Wwise Integration version, relevant audio scripts/config tables/prefabs.
- Jira/project-management conventions, upstream dependency links, status meanings.
- Version-control rules for Unity `.meta`, Wwise `.wwu`, Originals, GeneratedSoundBanks, plugins, profiling/cache output.
- Existing audio reports, resource totals, QA reports, naming rules, and user decisions.

## Workflow

1. **Inventory sources**: list exact paths, tools, versions, and scan dates.
2. **Grade source quality**: mark completeness, freshness, precision, traceability, and coverage for each major source.
3. **Project summary**: identify genre, camera/perspective model, multiplayer model, core loops, platforms, and build constraints.
4. **Audio architecture**: summarize Wwise hierarchy, Events, Bus layout, Switch/State/RTPC model, perspective/gender/material ordering, SoundBank strategy, and Unity trigger style.
5. **Production rules**: record naming rules, source-control policy, asset ownership, review/approval gates, and submit/get-latest safety rules.
6. **Known pitfalls**: record previous mistakes and guardrails, such as duplicated dimensions, stale `_Self`, Actor objects named `Play_*`, missing override flags, and Unity `.meta` handling.
7. **Open questions**: list only questions that change design, estimates, or implementation safety.
8. **Refresh plan**: define when to update the profile after version upgrades, major design changes, Wwise edits, Unity integration changes, or Jira workflow changes.

## Output

Produce a concise profile with these sections:

- **Verified Facts**
- **Source Inventory And Quality**
- **Inferred Rules**
- **Audio Architecture**
- **Pipeline And Ownership**
- **Version-Control Rules**
- **Known Risks And Guardrails**
- **Open Questions**
- **Refresh Triggers**

## Rules

- Do not invent final project rules from one example; mark uncertain patterns as inferred.
- Do not hide stale or incomplete sources. The profile must state when facts were last scanned and which source areas are missing.
- If a user-corrected mistake exists, preserve it as a guardrail.
- Prefer links to current reports rather than duplicating large tables.
- When profiles are project-specific, keep them outside the generic skill body, for example in a project report or `references/project-profile.md`.
