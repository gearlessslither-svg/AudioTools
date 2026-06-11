---
name: ai-work-impact-ledger
description: Track and summarize daily, weekly, and monthly AI-assisted work impact, including solved problems, created tools, new workflows, evidence quality, AI involvement ratio, reusable assets, and management-ready reports.
---

# AI Work Impact Ledger

Use this skill when the user wants to measure, explain, or report how AI participated in production work across a day, week, month, milestone, project, or team.

## Core Idea

AI value is not measured by usage time alone. Track evidence-backed impact:

- Problems found or solved
- Tools, reports, scripts, or skills created
- New workflows or QA gates discovered
- Risks avoided or made visible
- Human decisions supported
- Reusable assets produced

The most important accuracy rule: AI judgment quality is bounded by source quality. Always evaluate whether the source material is complete, precise, fresh, and verifiable before claiming high-confidence results.

## Source Quality Model

For every impact summary, include a source-quality assessment:

| Dimension | Meaning | Weak Evidence Example | Strong Evidence Example |
|---|---|---|---|
| Completeness | Do we have enough relevant sources? | Only one chat note | Docs + Wwise + Unity + logs + user confirmation |
| Freshness | Are sources current? | Old design doc, stale report | Latest synced files, recent logs, dated confirmation |
| Precision | Are details specific enough? | "needs better audio" | Event, state, owner, trigger, expected result |
| Traceability | Can claims be linked to artifacts? | Memory-only statement | File, report, script, changelist, screenshot, QA log |
| Coverage | Does runtime evidence cover the scenario? | One arbitrary play session | Labeled scenario matrix with observed/unobserved states |

Use source grades:

- `A`: complete, current, precise, traceable, and coverage is explicit.
- `B`: enough to guide work, but some sources are inferred or partially stale.
- `C`: useful for exploration only; important gaps remain.
- `D`: too incomplete for decisions; only questions or data requests should be produced.

Never present an AI intervention ratio without source grade and evidence links.

## AI Involvement Levels

Use weighted levels so reports do not exaggerate AI ownership:

| Level | Weight | Meaning |
|---|---:|---|
| None | 0.00 | No AI assistance |
| Advisory | 0.25 | AI asked questions, challenged assumptions, or gave suggestions |
| Analysis | 0.50 | AI produced diagnosis, reports, requirement maps, QA results, or summaries |
| BuildAssist | 0.75 | AI created tools, scripts, workflow assets, HTML reports, or implementation plans |
| ControlledExecution | 1.00 | AI executed approved changes and produced QA/report evidence; humans retained final decision |

Preferred metrics:

- **AI-assisted task coverage** = AI-assisted tasks / all recorded tasks.
- **Weighted AI involvement** = sum(weights) / task count.
- **Evidence-backed impact count** = tasks with source grade `A` or `B`.
- **Reusable asset output** = count of tools, skills, templates, scripts, reports, and workflows created.

## Ledger Schema

Maintain a ledger in CSV or JSONL with these fields:

| Field | Required | Notes |
|---|---|---|
| date | Yes | `YYYY-MM-DD` |
| project | Yes | Project or team |
| work_area | Yes | Requirement / Wwise / Unity / P4 / Tool / Report / Workflow / QA |
| task | Yes | Short task title |
| problem | Yes | What problem or uncertainty existed |
| ai_role | Yes | Advisory / Analysis / BuildAssist / ControlledExecution |
| human_role | Yes | Decision, confirmation, testing, design judgment, approval |
| output | Yes | File/report/tool/skill/changelist/link |
| impact | Yes | Time saved, risk reduced, visibility improved, reusable asset created |
| involvement | Yes | 0 / 0.25 / 0.5 / 0.75 / 1 |
| source_grade | Yes | A / B / C / D |
| evidence | Yes | Artifact paths, report names, screenshots, logs, user confirmation |
| next_step | No | Follow-up action |

## Workflow

1. **Collect evidence** from reports, scripts, changelists, task logs, chat summaries, Wwise/Unity audit reports, HTML reports, and created skills.
2. **Normalize entries** into the ledger schema. Separate actual work from discussion-only notes.
3. **Grade source quality** before calculating impact. If evidence is weak, mark it `C` or `D`.
4. **Classify AI role** using the involvement levels.
5. **Summarize by period**:
   - Daily: what changed today, what risks were found, what artifacts were created.
   - Weekly: recurring problem categories, reusable tools, process changes, top risks.
   - Monthly: management view, AI-assisted coverage, weighted involvement, evidence-backed impact, next automation opportunities.
6. **Report limits** clearly: where AI lacked data, where human confirmation was decisive, and where results need better source capture.

## Output

For summaries, include:

- **Executive Summary**
- **AI Impact Metrics**
- **Solved Problems**
- **Created Assets**
- **New Workflows**
- **Risk Reduction**
- **Source Quality**
- **Human Decisions Required**
- **Next Iteration**

For management reports, avoid claiming that AI replaced human work. Say AI improved discovery, analysis, production visibility, QA discipline, repeatability, or risk control.

## Script

Use the bundled script to create or summarize a ledger:

```powershell
python "$env:USERPROFILE\.codex\skills\ai-work-impact-ledger\scripts\ai_work_impact_ledger.py" `
  --ledger "G:\AI\Material\Wwise\AI_Work_Impact_Ledger.csv" `
  --out-md "G:\AI\Material\Wwise\AI_Work_Impact_Summary.md" `
  --out-json "G:\AI\Material\Wwise\AI_Work_Impact_Summary.json" `
  --period month
```

## Rules

- Do not count a task as high AI impact without evidence.
- Do not use AI involvement as a replacement metric for human ownership.
- Always distinguish `AI found`, `AI suggested`, `AI built`, `AI executed with approval`, and `human decided`.
- If source quality is low, make the improvement request part of the report.
- Prefer stable, dated reports and file paths over memory-only claims.
