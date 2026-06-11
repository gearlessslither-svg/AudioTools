---
name: audio-report-trend-monitor
description: Periodically inspect the latest audio/Wwise/Unity audit reports, aggregate issue trends, explain the current project health, and propose safe tool or workflow improvements. Use when the user asks to monitor reports every few hours, compare recent reports, summarize runtime audio findings, or iterate the audio QA tools from accumulated data.
---

# Audio Report Trend Monitor

Use this skill to turn many generated audio reports into one rolling diagnosis and tool-improvement backlog.

## Boundary

- A Skill is not a background process. For automatic checks, pair this skill with Codex automation, Windows Task Scheduler, or a local watcher script.
- Default behavior is read-only: inspect reports, write summary reports, and suggest fixes/tool changes. Do not modify Wwise/Unity unless the user explicitly approves a separate change.

## Inputs

Recommended:

- Report root, usually `G:\AI\Material\Wwise`.
- Number of latest reports to inspect, usually 5-12.
- Project names/paths if known: Unity root and Wwise root.

Relevant report types:

- Unity/Wwise runtime log reports: GUI monitor JSON/MD, reparse JSON/MD, JSONL summaries.
- Wwise audits and modification reports.
- Unity static integration audits.
- Resource budget/readiness/production reports.

## Workflow

1. Collect the latest X report files, prioritizing `.json` over `.md` and excluding `.jsonl` unless explicitly requested.
2. Parse structured fields: summary, severity counts, category counts, event counts, issue groups, findings, QA failures, modified objects.
3. Normalize issue types:
   - `EventBankLoadFailed`
   - `StopEventBankLoadFailed`
   - `VoiceStarvation`
   - `SourceStarvation`
   - `MonitorQueueFull`
   - `SetStateFail`
   - `MissingBankOrMedia`
   - `LicenseOrPackaging`
   - `FalsePositiveOrParserNoise`
4. Produce a concise trend report:
   - reports inspected
   - top recurring issues
   - what is likely happening now
   - whether the newest reports improved or regressed
   - source quality and freshness of the inspected reports
   - recommended next engineering/audio actions
5. Propose tool/workflow iterations:
   - new parser rules
   - GUI panels or filters
   - bilingual suggestions
   - source-code correlation
   - scheduled report generation
   - report retention and noise suppression
6. If recurring monitoring is requested, use Codex automation or a local scheduled script. State clearly which mechanism is responsible for the periodic run.

## Script

Prefer the bundled script for deterministic parsing:

```powershell
python "$env:USERPROFILE\.codex\skills\audio-report-trend-monitor\scripts\audio_report_trend_monitor.py" `
  --report-root "G:\AI\Material\Wwise" `
  --latest 8 `
  --out "G:\AI\Material\Wwise\ProjectEF_AudioReport_TrendSummary.md" `
  --json-out "G:\AI\Material\Wwise\ProjectEF_AudioReport_TrendSummary.json"
```

For a local polling loop:

```powershell
python "$env:USERPROFILE\.codex\skills\audio-report-trend-monitor\scripts\audio_report_trend_monitor.py" `
  --report-root "G:\AI\Material\Wwise" `
  --latest 8 `
  --out "G:\AI\Material\Wwise\ProjectEF_AudioReport_TrendSummary.md" `
  --json-out "G:\AI\Material\Wwise\ProjectEF_AudioReport_TrendSummary.json" `
  --watch `
  --interval-hours 3
```

## Output Rules

- Separate real runtime problems from parser/tool false positives.
- Do not overclaim causality. Use confidence wording and cite evidence.
- Report data quality: latest report time, missing source types, stale reports, narrow runtime coverage, and evidence gaps that limit confidence.
- Keep tool improvement suggestions actionable and scoped.
- If the same issue repeats across reports, recommend fixing the source issue before adding more Wwise-side mitigation.
