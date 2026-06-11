---
name: audio-requirement-mining
description: Mine game design documents, specs, config tables, and task lists into audio requirement candidates with SABC priority, system/type classification, dependencies, risks, and questions.
---

# Audio Requirement Mining

Use this skill when design docs or task lists need to become an audio requirement map. It is read-only unless the user explicitly asks to write a report.

## Inputs

- Design docs, feature specs, changelogs, config tables, localization sheets.
- Existing SABC audio lists, resource budgets, and project profile.
- Wwise and Unity context if available, but do not require them for first-pass mining.

## Workflow

1. **Scan sources**: identify systems, mechanics, states, UI flows, rewards, failures, environments, characters, tools, vehicles, weather, and monetization touchpoints.
2. **Extract candidates**: convert each gameplay state or presentation feature into possible audio needs.
3. **Classify two ways**: by game system and by sound type.
4. **Prioritize SABC**:
   - `S`: core feedback that strongly affects playability, tension, readability, or identity.
   - `A`: essential polish or comprehension needed for a complete shipped feature.
   - `B`: useful support, variety, or secondary readability.
   - `C`: optional flavor, luxury variation, or cuttable polish.
5. **Challenge requests**: flag vague feelings, missing triggers, unstable visuals, over-bespoke resource asks, or no clear player value.
6. **Estimate lightly**: provide rough asset classes and random sample needs, but hand detailed budgets to `audio-resource-budgeting`.
7. **Ask only blocking questions**: avoid flooding design with every curiosity.

## Output Table

| ID | Source | System | Feature | Sound Type | SABC | Reason | Dependency | Ready State | Wwise Need | Unity Need | Risk | Question |
|---|---|---|---|---|---|---|---|---|---|---|---|---|

Sound Type examples:

- Music
- UI
- Gameplay
- Foley
- VFX
- Environment
- VO
- Mix/System
- Debug/Tooling

Ready State examples:

- `Ready`
- `DesignOnly`
- `Blocked`
- `Risky`
- `Cuttable`

## Rules

- Treat docs as design intent, not audio truth.
- Do not assume every item needs bespoke audio; propose templates, Switches, RTPCs, and shared material layers where appropriate.
- Mark stale or contradictory sources explicitly.
- Preserve source references so later diffing can identify why a requirement exists.
