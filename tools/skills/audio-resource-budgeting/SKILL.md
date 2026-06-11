---
name: audio-resource-budgeting
description: Convert audio requirements into resource totals, random sample rules, music/SFX/VO counts, Wwise/Unity/mix implementation steps, and production time estimates.
---

# Audio Resource Budgeting

Use this skill when audio requirements need to become a production budget, full asset list, schedule, or man-day estimate.

## Inputs

- Requirement map with SABC priority.
- Project profile and target platforms.
- Wwise/Unity implementation assumptions.
- Existing asset library or Wwise resource audit when available.

## Counting Principles

- Separate **minimum shippable**, **recommended**, and **deluxe/full** counts.
- Count by asset class: Music, SFX, UI, Environment, VO, Mix Snapshot, Debug/Proxy events.
- Include random samples when repetition affects quality.
- Do not make every fish/item/tool bespoke by default; use core bespoke assets plus parameterized templates.
- Track C-level cut pool separately.
- VO counts must specify language count and pickup/retake margin.

## Random Sample Rules

Use project context first. If none exists, start with:

- High-frequency one-shots: 6-12 variations.
- Medium-frequency gameplay: 3-6 variations.
- Rare rewards/stingers: 2-4 variations.
- Loops: start/loop/stop or an explicitly equivalent loop design.
- Footsteps/material foley: 6-12 per material per perspective/gender layer when audible.
- UI high-frequency clicks: 4-8 variations or pitch/randomization strategy.
- Environment beds: 2-4 layers plus weather/day/night variants as needed.
- VO system lines: base line count by language plus at least 10% pickup margin.

## Output Table

| ID | SABC | System | Type | Feature | Resource Class | Minimum | Recommended | Deluxe | Random Samples | Wwise Objects | Unity Config | Mix Step | QA Step | Person-Days | Cuttable? | Notes |
|---|---|---|---|---|---|---:|---:|---:|---|---|---|---|---|---:|---|---|

## Implementation Estimate

For each major feature, estimate:

- Source design/recording/editing.
- Wwise import, container setup, Switch/State/RTPC, routing, SoundBank assignment.
- Unity trigger/config/debug hookup.
- Mix pass and performance tuning.
- QA pass and fix buffer.

## Rules

- State assumptions and confidence.
- Keep S/A itemized; B/C can be grouped unless the user asks for full detail.
- Separate creation time from implementation time.
- Identify cut lines that reduce time without breaking the core experience.
