#!/usr/bin/env python3
import argparse
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path


TEXT_EXTS = {
    ".cs",
    ".prefab",
    ".unity",
    ".asset",
    ".anim",
    ".controller",
    ".playable",
    ".timeline",
    ".json",
    ".xml",
    ".txt",
}

UNITY_ASSET_EXTS = {".prefab", ".unity", ".asset", ".anim", ".controller", ".playable", ".timeline"}

DIRECT_AUDIO_API_PATTERNS = {
    "PostEvent": re.compile(r"\bAkSoundEngine\.PostEvent\s*\("),
    "SetRTPC": re.compile(r"\bAkSoundEngine\.SetRTPCValue\s*\("),
    "SetSwitch": re.compile(r"\bAkSoundEngine\.SetSwitch\s*\("),
    "SetState": re.compile(r"\bAkSoundEngine\.SetState\s*\("),
    "LoadBank": re.compile(r"\bAkSoundEngine\.LoadBank\s*\("),
    "UnloadBank": re.compile(r"\bAkSoundEngine\.UnloadBank\s*\("),
    "StopOrAction": re.compile(r"\bAkSoundEngine\.(?:StopAll|ExecuteActionOnEvent|StopPlayingID|RenderAudio)\s*\("),
}

EVENT_LITERAL_RE = re.compile(r'"((?:Play|Stop|Pause|Resume|Set|Reset|Mute|Unmute|Stinger|Music|VO|UI|SFX|Amb|Loop)_[A-Za-z0-9_]+)"')
AK_EVENTS_CONST_RE = re.compile(r"\bAK\.EVENTS\.([A-Z0-9_]+)\b")
AK_GAME_PARAMETERS_RE = re.compile(r"\bAK\.GAME_PARAMETERS\.([A-Z0-9_]+)\b")
AK_SWITCHES_RE = re.compile(r"\bAK\.SWITCHES\.([A-Z0-9_]+(?:\.[A-Z0-9_]+)*)\b")
AK_STATES_RE = re.compile(r"\bAK\.STATES\.([A-Z0-9_]+(?:\.[A-Z0-9_]+)*)\b")
METHOD_RE = re.compile(
    r"\b(?:public|private|protected|internal|static|virtual|override|async|sealed|new|\s)+\s*"
    r"(?:[A-Za-z_][A-Za-z0-9_<>,\[\]\s]*\s+)?"
    r"([A-Za-z_][A-Za-z0-9_]*)\s*\([^;]*\)\s*(?:where\s+[^{]+)?\{?"
)
CLASS_RE = re.compile(r"\bclass\s+([A-Za-z_][A-Za-z0-9_]*)")
CS_WWISE_FIELD_RE = re.compile(r"\bAK\.Wwise\.(Event|RTPC|Switch|State|Bank|Trigger)\s+([A-Za-z_][A-Za-z0-9_]*)")

UNITY_LIFECYCLE = {
    "Awake",
    "Start",
    "OnEnable",
    "OnDisable",
    "OnDestroy",
    "Update",
    "FixedUpdate",
    "LateUpdate",
    "OnTriggerEnter",
    "OnTriggerExit",
    "OnCollisionEnter",
    "OnCollisionExit",
    "OnAnimatorMove",
    "OnApplicationPause",
    "OnApplicationFocus",
}


def read_text(path: Path, max_bytes: int) -> str | None:
    try:
        if path.stat().st_size > max_bytes:
            return None
        return path.read_text(encoding="utf-8-sig", errors="replace")
    except Exception:
        return None


def collect_files(root: Path, max_mb: float):
    max_bytes = int(max_mb * 1024 * 1024)
    skip_dirs = {
        "Library",
        "Temp",
        "Obj",
        "Build",
        "Builds",
        "Logs",
        ".git",
        ".vs",
        ".idea",
        "UserSettings",
        "MemoryCaptures",
    }
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in skip_dirs for part in path.parts):
            continue
        if path.suffix.lower() not in TEXT_EXTS and path.suffix.lower() != ".meta":
            continue
        try:
            if path.stat().st_size > max_bytes:
                continue
        except OSError:
            continue
        yield path


def parse_wwise_events(wwise_root: Path | None) -> set[str]:
    events: set[str] = set()
    if not wwise_root or not wwise_root.exists():
        return events
    for xml_path in list(wwise_root.rglob("*.wwu")) + list(wwise_root.rglob("SoundbanksInfo.xml")):
        text = read_text(xml_path, 10 * 1024 * 1024)
        if not text:
            continue
        # Fast regex covers Wwise WorkUnits and generated info even if XML namespaces vary.
        for match in re.finditer(r"<Event\b[^>]*\bName=\"([^\"]+)\"", text):
            events.add(match.group(1))
        try:
            root = ET.fromstring(text)
            for elem in root.iter():
                if elem.tag.split("}")[-1] == "Event":
                    name = elem.attrib.get("Name") or elem.attrib.get("name")
                    if name:
                        events.add(name)
        except Exception:
            pass
    return events


def parse_script_guids(unity_root: Path, max_bytes: int) -> dict[str, str]:
    guid_to_script = {}
    assets = unity_root / "Assets"
    if not assets.exists():
        return guid_to_script
    for meta in assets.rglob("*.cs.meta"):
        text = read_text(meta, max_bytes)
        if not text:
            continue
        match = re.search(r"^guid:\s*([a-fA-F0-9]+)\s*$", text, re.MULTILINE)
        if match:
            guid_to_script[match.group(1).lower()] = meta.with_suffix("").name
    return guid_to_script


def infer_system(path: Path, unity_root: Path) -> str:
    try:
        rel = path.relative_to(unity_root)
    except ValueError:
        rel = path
    parts = [p for p in rel.parts if p not in {"Assets", "Scripts", "Runtime", "Prefabs", "Scenes"}]
    if not parts:
        return "Unknown"
    candidates = [p for p in parts[:-1] if not p.startswith("_")]
    return candidates[0] if candidates else parts[0]


def classify_method(method: str | None) -> str:
    if not method:
        return "Unknown"
    if method in UNITY_LIFECYCLE:
        return method
    lower = method.lower()
    if "anim" in lower:
        return "AnimationOrAnimator"
    if "trigger" in lower:
        return "Trigger"
    if "click" in lower or "button" in lower:
        return "UI"
    if "enter" in lower or "exit" in lower:
        return "EnterExit"
    return "Custom"


def extract_event_tokens(line: str) -> list[dict]:
    tokens = []
    for value in EVENT_LITERAL_RE.findall(line):
        tokens.append({"kind": "literal", "value": value})
    for value in AK_EVENTS_CONST_RE.findall(line):
        tokens.append({"kind": "AK.EVENTS", "value": value})
    return tokens


def extract_param_tokens(line: str) -> dict[str, list[str]]:
    return {
        "rtpc": AK_GAME_PARAMETERS_RE.findall(line),
        "switch": AK_SWITCHES_RE.findall(line),
        "state": AK_STATES_RE.findall(line),
    }


def normalize_const_event(token: str) -> str:
    # Generated AK.EVENTS constants are usually upper snake case. Keep original plus title-ish candidate.
    return token


def scan_csharp(path: Path, text: str, unity_root: Path, known_events: set[str]):
    lines = text.splitlines()
    calls = []
    risks = []
    fields = []
    wwise_fields = {}
    class_name = None
    method = None
    brace_depth = 0
    method_depth = None

    for idx, line in enumerate(lines, start=1):
        class_match = CLASS_RE.search(line)
        if class_match:
            class_name = class_match.group(1)

        method_match = METHOD_RE.search(line)
        if method_match and not line.strip().startswith(("if", "for", "while", "switch", "catch")):
            method = method_match.group(1)
            method_depth = brace_depth + line.count("{") - line.count("}")

        for field_type, field_name in CS_WWISE_FIELD_RE.findall(line):
            wwise_fields[field_name] = field_type
            fields.append({"file": str(path), "line": idx, "field": field_name, "type": field_type, "class": class_name})

        hit_types = [kind for kind, pattern in DIRECT_AUDIO_API_PATTERNS.items() if pattern.search(line)]
        for field_name, field_type in wwise_fields.items():
            if not re.search(rf"\b{re.escape(field_name)}\s*\.", line):
                continue
            if field_type == "Event" and re.search(rf"\b{re.escape(field_name)}\s*\.\s*Post\s*\(", line):
                hit_types.append("WwiseEventPost")
            elif field_type == "RTPC" and re.search(rf"\b{re.escape(field_name)}\s*\.\s*SetValue\s*\(", line):
                hit_types.append("SetRTPC")
            elif field_type == "Switch" and re.search(rf"\b{re.escape(field_name)}\s*\.\s*SetValue\s*\(", line):
                hit_types.append("SetSwitch")
            elif field_type == "State" and re.search(rf"\b{re.escape(field_name)}\s*\.\s*SetValue\s*\(", line):
                hit_types.append("SetState")
            elif field_type == "Bank" and re.search(rf"\b{re.escape(field_name)}\s*\.\s*(?:Load|Unload)\s*\(", line):
                hit_types.append("BankFieldLoad")
        if hit_types:
            event_tokens = extract_event_tokens(line)
            param_tokens = extract_param_tokens(line)
            context_start = max(1, idx - 5)
            context_end = min(len(lines), idx + 5)
            before = "\n".join(f"{n}: {lines[n-1]}" for n in range(context_start, idx))
            after = "\n".join(f"{n}: {lines[n-1]}" for n in range(idx + 1, context_end + 1))
            nearby = "\n".join(lines[context_start - 1 : context_end])
            nearby_params = {
                "rtpc": sorted(set(AK_GAME_PARAMETERS_RE.findall(nearby))),
                "switch": sorted(set(AK_SWITCHES_RE.findall(nearby))),
                "state": sorted(set(AK_STATES_RE.findall(nearby))),
            }
            known_status = "UnknownOrDynamic"
            if event_tokens:
                statuses = []
                for token in event_tokens:
                    value = token["value"]
                    if token["kind"] == "literal":
                        statuses.append("Known" if value in known_events else "Unknown")
                    else:
                        statuses.append("GeneratedConstant")
                known_status = ",".join(sorted(set(statuses)))
            call = {
                "file": str(path),
                "line": idx,
                "system": infer_system(path, unity_root),
                "class": class_name,
                "method": method,
                "lifecycle": classify_method(method),
                "api": hit_types,
                "line_text": line.strip(),
                "event_tokens": event_tokens,
                "param_tokens": param_tokens,
                "nearby_params": nearby_params,
                "before": before,
                "after": after,
                "known_status": known_status,
            }
            calls.append(call)

            if method in {"Update", "FixedUpdate", "LateUpdate"} and any(t in hit_types for t in ("PostEvent", "WwiseEventPost")):
                risks.append({
                    "severity": "High",
                    "file": str(path),
                    "line": idx,
                    "issue": "Audio Event appears to be posted from a per-frame Unity lifecycle method.",
                    "recommendation": "Check throttling, state-change gating, cooldown, or move to explicit gameplay transitions.",
                })
            for token in event_tokens:
                if token["kind"] == "literal" and known_events and token["value"] not in known_events:
                    risks.append({
                        "severity": "Warn",
                        "file": str(path),
                        "line": idx,
                        "issue": f"String literal Event `{token['value']}` was not found in parsed Wwise Event names.",
                        "recommendation": "Confirm spelling, generated bank coverage, or whether this project uses runtime-created aliases.",
                    })

        brace_depth += line.count("{") - line.count("}")
        if method_depth is not None and brace_depth < method_depth:
            method = None
            method_depth = None

    return calls, fields, risks


def scan_asset(path: Path, text: str, unity_root: Path, guid_to_script: dict[str, str], known_events: set[str]):
    refs = []
    risks = []
    script_hits = []
    for match in re.finditer(r"m_Script:\s*\{fileID:\s*11500000,\s*guid:\s*([a-fA-F0-9]+),", text):
        guid = match.group(1).lower()
        script = guid_to_script.get(guid)
        if script and (script.startswith("Ak") or "Wwise" in script or "Audio" in script):
            line = text[: match.start()].count("\n") + 1
            script_hits.append({"script": script, "line": line})

    event_names = sorted(set(EVENT_LITERAL_RE.findall(text)))
    unknown_events = [evt for evt in event_names if known_events and evt not in known_events]
    if unknown_events:
        risks.append({
            "severity": "Warn",
            "file": str(path),
            "line": None,
            "issue": f"Serialized Event-like names not found in parsed Wwise Events: {', '.join(unknown_events[:8])}",
            "recommendation": "Confirm stale prefab/scene references or generated Event name mapping.",
        })

    if script_hits or event_names:
        refs.append({
            "file": str(path),
            "system": infer_system(path, unity_root),
            "asset_type": path.suffix.lower(),
            "scripts": script_hits,
            "event_names": event_names,
        })
    return refs, risks


def md_escape(value):
    return str(value).replace("|", "\\|").replace("\n", "<br>")


def write_report(out: Path, data: dict):
    lines = []
    summary = data["summary"]
    lines.append("# Unity 音频集成静态审计报告")
    lines.append("")
    lines.append("## 摘要")
    lines.append("")
    for key, value in summary.items():
        lines.append(f"- **{key}**: {value}")
    lines.append("")

    lines.append("## 事件调用地图")
    lines.append("")
    lines.append("| Event/Token | API | File | Line | Class | Method | Lifecycle | System | Wwise Status | Nearby RTPC/Switch/State |")
    lines.append("|---|---|---|---:|---|---|---|---|---|---|")
    for call in data["calls"][:300]:
        tokens = ", ".join(f"{t['kind']}:{t['value']}" for t in call["event_tokens"]) or "(dynamic/field)"
        nearby = []
        for k, vals in call["nearby_params"].items():
            if vals:
                nearby.append(f"{k}: {', '.join(vals[:6])}")
        lines.append(
            "| "
            + " | ".join(
                md_escape(x)
                for x in [
                    tokens,
                    ",".join(call["api"]),
                    call["file"],
                    call["line"],
                    call["class"] or "",
                    call["method"] or "",
                    call["lifecycle"],
                    call["system"],
                    call["known_status"],
                    "; ".join(nearby),
                ]
            )
            + " |"
        )
    if not data["calls"]:
        lines.append("| - | - | - | - | - | - | - | - | - | - |")
    lines.append("")

    lines.append("## 序列化资源引用")
    lines.append("")
    lines.append("| Asset | Type | System | Scripts | Event-like Names |")
    lines.append("|---|---|---|---|---|")
    for ref in data["asset_refs"][:300]:
        scripts = ", ".join(f"{s['script']}:{s['line']}" for s in ref["scripts"][:10])
        events = ", ".join(ref["event_names"][:12])
        lines.append("| " + " | ".join(md_escape(x) for x in [ref["file"], ref["asset_type"], ref["system"], scripts, events]) + " |")
    if not data["asset_refs"]:
        lines.append("| - | - | - | - | - |")
    lines.append("")

    lines.append("## 风险与推测")
    lines.append("")
    lines.append("| Severity | File | Line | Issue | Recommendation |")
    lines.append("|---|---|---:|---|---|")
    for risk in data["risks"][:300]:
        lines.append(
            "| "
            + " | ".join(
                md_escape(x)
                for x in [
                    risk["severity"],
                    risk["file"],
                    risk.get("line") or "",
                    risk["issue"],
                    risk["recommendation"],
                ]
            )
            + " |"
        )
    if not data["risks"]:
        lines.append("| Pass | - | - | No major static-scan risks found. | Run runtime validation for final confidence. |")
    lines.append("")

    lines.append("## API 统计")
    lines.append("")
    lines.append("| API | Count |")
    lines.append("|---|---:|")
    for api, count in data["api_counts"].most_common():
        lines.append(f"| {md_escape(api)} | {count} |")
    lines.append("")

    lines.append("## 方法生命周期统计")
    lines.append("")
    lines.append("| Lifecycle | Count |")
    lines.append("|---|---:|")
    for lifecycle, count in data["lifecycle_counts"].most_common():
        lines.append(f"| {md_escape(lifecycle)} | {count} |")
    lines.append("")

    lines.append("## 说明")
    lines.append("")
    lines.append("- 本报告是静态扫描结果，不能替代 PlayMode/runtime 验证。")
    lines.append("- `GeneratedConstant` 表示代码使用 `AK.EVENTS.*`，需要结合生成文件或 Wwise 工程确认最终 Event。")
    lines.append("- `(dynamic/field)` 表示通过 `AK.Wwise.Event` 字段或变量调用，静态文本扫描无法完全解析序列化引用。")
    lines.append("- 若需要 100% 解析 prefab/scene 中的 Wwise picker 字段，建议下一步使用 Unity batchmode + AssetDatabase 审计。")

    out.write_text("\n".join(lines), encoding="utf-8-sig")


def make_jsonable(data: dict) -> dict:
    result = dict(data)
    result["api_counts"] = dict(data["api_counts"])
    result["lifecycle_counts"] = dict(data["lifecycle_counts"])
    return result


def main():
    parser = argparse.ArgumentParser(description="Static Unity Wwise/audio integration audit.")
    parser.add_argument("--unity-root", required=True)
    parser.add_argument("--wwise-project-root")
    parser.add_argument("--out", required=True)
    parser.add_argument("--json-out")
    parser.add_argument("--max-file-mb", type=float, default=4.0)
    args = parser.parse_args()

    unity_root = Path(args.unity_root)
    if not unity_root.exists():
        print(f"Unity root not found: {unity_root}", file=sys.stderr)
        return 2
    assets = unity_root / "Assets"
    if not assets.exists():
        print(f"Unity root does not contain Assets/: {unity_root}", file=sys.stderr)
        return 2

    wwise_root = Path(args.wwise_project_root) if args.wwise_project_root else None
    known_events = parse_wwise_events(wwise_root)
    max_bytes = int(args.max_file_mb * 1024 * 1024)
    guid_to_script = parse_script_guids(unity_root, max_bytes)

    calls = []
    fields = []
    risks = []
    asset_refs = []
    files_scanned = 0
    cs_files = 0
    asset_files = 0

    for path in collect_files(assets, args.max_file_mb):
        text = read_text(path, max_bytes)
        if text is None:
            continue
        files_scanned += 1
        suffix = path.suffix.lower()
        if suffix == ".cs":
            cs_files += 1
            c, f, r = scan_csharp(path, text, unity_root, known_events)
            calls.extend(c)
            fields.extend(f)
            risks.extend(r)
        elif suffix in UNITY_ASSET_EXTS:
            asset_files += 1
            refs, r = scan_asset(path, text, unity_root, guid_to_script, known_events)
            asset_refs.extend(refs)
            risks.extend(r)

    api_counts = Counter()
    lifecycle_counts = Counter()
    unique_tokens = set()
    for call in calls:
        for api in call["api"]:
            api_counts[api] += 1
        lifecycle_counts[call["lifecycle"]] += 1
        for token in call["event_tokens"]:
            unique_tokens.add((token["kind"], token["value"]))

    summary = {
        "UnityRoot": str(unity_root),
        "WwiseProjectRoot": str(wwise_root) if wwise_root else "",
        "KnownWwiseEvents": len(known_events),
        "FilesScanned": files_scanned,
        "CSharpFilesScanned": cs_files,
        "UnityAssetFilesScanned": asset_files,
        "AudioApiCalls": len(calls),
        "SerializedAssetRefs": len(asset_refs),
        "AKWwiseEventFields": len(fields),
        "UniqueEventTokens": len(unique_tokens),
        "Risks": len(risks),
    }

    data = {
        "summary": summary,
        "known_events_sample": sorted(known_events)[:100],
        "calls": calls,
        "fields": fields,
        "asset_refs": asset_refs,
        "risks": risks,
        "api_counts": api_counts,
        "lifecycle_counts": lifecycle_counts,
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    write_report(out, data)
    if args.json_out:
        json_out = Path(args.json_out)
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps(make_jsonable(data), ensure_ascii=False, indent=2), encoding="utf-8-sig")
    print(out)
    if args.json_out:
        print(args.json_out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
