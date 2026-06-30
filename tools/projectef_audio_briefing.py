#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ProjectEF Audio Briefing — daily / weekly roll-up.

Reads the per-session captures produced by projectef_audio_autocapture_daemon.py and
rolls them into a "problems + solutions" briefing for the period (daily = last 24h,
weekly = last 7 days), with severity breakdown, top problems (each with a suggested
fix), and a trend vs the previous period. Writes Markdown + JSON into the 报告 folder
so the existing dashboard/index picks it up.

Usage:
    python projectef_audio_briefing.py --period daily
    python projectef_audio_briefing.py --period weekly
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

OUT_DIR = Path(r"G:\AI\Material\Wwise")
CAPTURE_DIR = OUT_DIR / "audio_debug_captures"
REPORT_DIR = OUT_DIR / "报告"

PERIOD_DAYS = {"daily": 1, "weekly": 7}


def parse_iso(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def load_sessions(since: datetime, until: datetime) -> list[dict]:
    sessions: list[dict] = []
    if not CAPTURE_DIR.exists():
        return sessions
    for path in CAPTURE_DIR.glob("session_*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        start = parse_iso(str(data.get("start", "")))
        if start is None:
            try:
                start = datetime.fromtimestamp(path.stat().st_mtime)
            except OSError:
                continue
        if since <= start < until:
            data["_start_dt"] = start
            sessions.append(data)
    return sessions


def aggregate(sessions: list[dict]) -> dict:
    total_lines = 0
    sev_counts: dict[str, int] = defaultdict(int)
    problems: dict[tuple, dict] = {}
    for s in sessions:
        total_lines += int(s.get("total_audio_lines") or 0)
        for sev, n in (s.get("counts_by_severity") or {}).items():
            sev_counts[sev] += int(n)
        for p in s.get("problems") or []:
            key = (p.get("category", "?"), str(p.get("subject", ""))[:60])
            g = problems.setdefault(key, {"category": key[0], "subject": key[1], "count": 0,
                                          "severity": p.get("severity", ""),
                                          "suggestion": p.get("suggestion", ""),
                                          "example": p.get("example", "")})
            g["count"] += int(p.get("count") or 0)
            if not g["suggestion"] and p.get("suggestion"):
                g["suggestion"] = p["suggestion"]
    ranked = sorted(problems.values(), key=lambda g: g["count"], reverse=True)
    return {"sessions": len(sessions), "total_lines": total_lines,
            "severity": dict(sev_counts), "problems": ranked}


def render_md(period: str, now: datetime, cur: dict, prev: dict) -> str:
    sev = cur["severity"]
    prev_total = prev["total_lines"]
    delta = cur["total_lines"] - prev_total
    trend = "持平"
    if delta > 0:
        trend = f"↑ 比上一{('日' if period=='daily' else '周')}多 {delta}"
    elif delta < 0:
        trend = f"↓ 比上一{('日' if period=='daily' else '周')}少 {-delta}"
    lines = [
        f"# ProjectEF 音频运行时简报 · {('每日' if period=='daily' else '每周')}",
        "",
        f"- 生成时间: `{now.isoformat(timespec='seconds')}`",
        f"- 统计区间: 最近 {PERIOD_DAYS[period]} 天",
        f"- 会话数: **{cur['sessions']}**(上一期 {prev['sessions']})",
        f"- 音频相关日志行: **{cur['total_lines']}**  ({trend})",
        f"- 严重度: Error **{sev.get('Error',0)}** / Warn **{sev.get('Warn',0)}** / Info {sev.get('Info',0)}",
        "",
        "## Top 问题 + 建议解决方案",
        "",
    ]
    if not cur["problems"]:
        lines.append("- (本期没有捕获到音频问题。若游戏确实跑过,检查守护进程是否在运行。)")
    else:
        lines.append("| # | 严重度 | 类别 | 主题/事件 | 次数 | 建议解决方案 |")
        lines.append("|---|---|---|---|---|---|")
        for i, p in enumerate(cur["problems"][:25], 1):
            sug = (p.get("suggestion") or "").replace("\n", " ")[:120] or "对照 Unity 操作 + Wwise Profiler + 邻近日志定位"
            subj = str(p.get("subject", ""))[:40]
            lines.append(f"| {i} | {p.get('severity','')} | {p.get('category','')} | {subj} | {p['count']} | {sug} |")
    lines += ["", "## 说明", "",
              "- 数据来源: 自动捕获守护按「游戏会话」抓取的音频日志切片(audio_debug_captures/)。",
              "- 建议解决方案来自 Log Monitor 的规则推断(infer_reason),仅供定位起点。",
              ""]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="ProjectEF audio daily/weekly briefing")
    ap.add_argument("--period", choices=["daily", "weekly"], default="daily")
    a = ap.parse_args()
    days = PERIOD_DAYS[a.period]
    now = datetime.now()
    cur = aggregate(load_sessions(now - timedelta(days=days), now))
    prev = aggregate(load_sessions(now - timedelta(days=days * 2), now - timedelta(days=days)))

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = now.strftime("%Y-%m-%d")
    base = REPORT_DIR / f"ProjectEF_AudioBriefing_{a.period}_{stamp}"
    md = render_md(a.period, now, cur, prev)
    base.with_suffix(".md").write_text(md, encoding="utf-8")
    base.with_suffix(".json").write_text(
        json.dumps({"period": a.period, "generated": now.isoformat(timespec="seconds"),
                    "current": cur, "previous_total_lines": prev["total_lines"]},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[briefing] {a.period}: sessions={cur['sessions']} lines={cur['total_lines']} "
          f"problems={len(cur['problems'])} -> {base.with_suffix('.md')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
