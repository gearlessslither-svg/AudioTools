"""Natural-language to Wwise audio-logic DSL.

Routes:
  local      Ollama, no API key.
  remote     OpenAI-compatible or Anthropic API, API key required.
  cli        claude/codex command line tools, using their own logged-in session
             when those tools are installed and support non-interactive prompts.

Every generated plan carries provenance in ``_generated_by`` so a saved or run
command can be traced back to its model/source.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from typing import Any

OLLAMA_URL = "http://127.0.0.1:11434"
OPENAI_URL = "https://api.openai.com/v1"
ANTHROPIC_URL = "https://api.anthropic.com/v1"
STALE_DEMO_NAMES = {
    "Play_Amb_LCW_3D_Frogs",
    "Play_Buzzbait",
    "Play_Fish_WaterIn",
    "RTPC_Env_Wetness",
}


class PlannerError(RuntimeError):
    pass


@dataclass
class LLMConfig:
    mode: str = "auto"            # auto | local | remote
    provider: str = "ollama"      # ollama | openai | anthropic | claude-cli | codex-cli
    ollama_url: str = OLLAMA_URL
    local_model: str = "qwen2.5:7b-instruct"
    openai_url: str = OPENAI_URL
    openai_model: str = "gpt-5-mini"
    openai_key: str = ""
    anthropic_url: str = ANTHROPIC_URL
    anthropic_model: str = "claude-sonnet-4-5"
    anthropic_key: str = ""
    claude_cmd: str = "claude"
    codex_cmd: str = "codex"
    timeout: int = 120

    def __post_init__(self) -> None:
        self.openai_key = self.openai_key or os.environ.get("OPENAI_API_KEY", "")
        self.anthropic_key = self.anthropic_key or os.environ.get("ANTHROPIC_API_KEY", "")


def resolve_route(cfg: LLMConfig) -> str:
    mode = (cfg.mode or "auto").lower()
    provider = _provider_alias(cfg.provider)
    if provider in {"claude-cli", "codex-cli"}:
        return "cli"
    if mode == "local":
        return "local"
    if mode == "remote":
        return "remote"
    if provider == "anthropic" and cfg.anthropic_key:
        return "remote"
    if provider in {"openai", ""} and cfg.openai_key:
        return "remote"
    return "local"


def route_label(cfg: LLMConfig) -> str:
    provider = _provider_alias(cfg.provider)
    route = resolve_route(cfg)
    if route == "cli":
        return f"cli:{provider}"
    if route == "remote":
        if provider == "anthropic":
            return f"remote:anthropic:{cfg.anthropic_model}"
        return f"remote:openai:{cfg.openai_model}"
    label = f"local:ollama:{cfg.local_model}"
    if (cfg.mode or "auto").lower() == "auto" and provider in {"openai", "anthropic"}:
        label += f" (auto fallback; {provider} API key missing)"
    return label


def _provider_alias(provider: str | None) -> str:
    text = (provider or "ollama").lower().strip()
    aliases = {
        "claude": "claude-cli",
        "codex": "codex-cli",
    }
    return aliases.get(text, text)


SCHEMA_DOC = """
Return ONE JSON object only, no prose. Shape:
{
  "name": "<short scenario name>",
  "game_object": "TestObj",
  "steps": [ <step>, ... ]
}
Step types:
  {"type":"post_event","event":"<Event name>"}
  {"type":"stop_event","event":"<Event name>"}
  {"type":"stop_all"}
  {"type":"set_rtpc","rtpc":"<GameParameter>","value":<number>}
  {"type":"ramp_rtpc","rtpc":"<GameParameter>","waypoints":[<num>,...],"seg_seconds":[<num>,...],
     "on_cross":[{"value":<num>,"direction":"up|down|any","do":<step>}]}
  {"type":"set_state","group":"<StateGroup>","value":"<State>"}
  {"type":"set_switch","group":"<SwitchGroup>","value":"<Switch>"}
  {"type":"post_trigger","trigger":"<Trigger>"}
  {"type":"wait","seconds":<num>}
  {"type":"loop","count":<int>,"steps":[ ... ]}
  {"type":"parallel","branches":[[ ... ],[ ... ]]}
Rules:
- Preserve the exact order and direction of every RTPC change.
- Gradual, slow, smooth, 缓慢, 逐渐, 慢慢 changes MUST use ramp_rtpc.
- Instant jumps use set_rtpc.
- ramp_rtpc.seg_seconds length must equal len(waypoints) - 1.
- Use on_cross for threshold-triggered actions.
- Use post_event for Wwise Events, not post_trigger.
- Use ONLY names that appear in the project object lists.
- Keep RTPC values within the RTPC min/max range.
- For Stamina tests, set Perspective=Player and set Gender before Play_Stamina when available.
""".strip()


def _objects_block(objects: dict[str, Any]) -> str:
    rtpcs = ", ".join(
        f"{item['name']}[{item.get('min')}..{item.get('max')}]" for item in objects.get("rtpcs", [])
    )
    states = "; ".join(
        f"{group['group']}:({'/'.join(group['states'])})" for group in objects.get("state_groups", [])
    )
    switches = "; ".join(
        f"{group['group']}:({'/'.join(group['switches'])})" for group in objects.get("switch_groups", [])
    )
    triggers = ", ".join(objects.get("triggers", []))
    return (
        "Available Events:\n" + ", ".join(objects.get("events", [])) + "\n\n"
        "Available RTPCs (name[min..max]):\n" + rtpcs + "\n\n"
        "Available State groups:\n" + states + "\n\n"
        "Available Switch groups:\n" + switches + "\n\n"
        "Available Triggers:\n" + triggers
    )


def _messages(scenario: str, objects: dict[str, Any]) -> tuple[str, str]:
    system = (
        "You are a Wwise technical sound designer. Convert a natural-language audio "
        "test scenario into a strict JSON test plan that drives Wwise via WAAPI. "
        "Return one valid JSON object only."
    )
    user = (
        f"{SCHEMA_DOC}\n\n=== PROJECT OBJECTS ===\n{_objects_block(objects)}\n\n"
        f"=== SCENARIO ===\n{scenario}\n\nReturn the JSON test plan now."
    )
    return system, user


def generate_plan(scenario: str, objects: dict[str, Any], cfg: LLMConfig) -> dict[str, Any]:
    scenario = (scenario or "").strip()
    if not scenario:
        raise PlannerError("请先描述测试场景。")

    planned_source = route_label(cfg)
    rule_plan = build_rule_plan(scenario, objects)
    system, user = _messages(scenario, objects)
    try:
        if resolve_route(cfg) == "cli":
            raw = _call_cli(system, user, cfg)
        elif resolve_route(cfg) == "remote":
            raw = _call_remote(system, user, cfg)
        else:
            raw = _call_ollama(system, user, cfg)
        plan = _extract_json(raw)
        if "steps" not in plan or not isinstance(plan["steps"], list):
            raise PlannerError(f"模型没有返回有效 steps。原始输出:\n{raw[:500]}")
        _reject_stale_demo_plan(plan, scenario)
        plan.setdefault("name", scenario.splitlines()[0][:40] or "Audio Logic Test")
        plan.setdefault("game_object", "LLM_AudioTest")
        return _attach_metadata(plan, scenario, planned_source)
    except Exception as exc:  # noqa: BLE001
        if rule_plan:
            rule_plan["_generation_warning"] = (
                f"{planned_source} unavailable or invalid, used deterministic Stamina template instead. "
                f"Reason: {exc}"
            )
            return _attach_metadata(rule_plan, scenario, "rules:stamina-flow-template")
        if isinstance(exc, PlannerError):
            raise
        raise PlannerError(str(exc)) from exc


def _attach_metadata(plan: dict[str, Any], scenario: str, source: str) -> dict[str, Any]:
    plan["_generated_by"] = source
    plan["_raw_description"] = scenario
    plan["_generated_at"] = datetime.now().isoformat(timespec="seconds")
    plan["_command_source"] = source
    return plan


def _reject_stale_demo_plan(plan: dict[str, Any], scenario: str) -> None:
    text = scenario.lower()
    allowed = any(token in text for token in ["frog", "frogs", "青蛙", "湿度", "wetness", "buzzbait", "fish_waterin"])
    if allowed:
        return
    used = _used_names(plan.get("steps", [])) & STALE_DEMO_NAMES
    if used:
        names = ", ".join(sorted(used))
        raise PlannerError(
            f"模型返回了旧示例/青蛙测试对象 ({names})，但当前需求没有提到它们；已拒绝该 DSL。"
        )


def _used_names(steps: list[Any]) -> set[str]:
    names: set[str] = set()
    for step in steps or []:
        if not isinstance(step, dict):
            continue
        for key in ("event", "rtpc", "group", "value", "trigger"):
            value = step.get(key)
            if isinstance(value, str):
                names.add(value)
        if step.get("type") == "loop":
            names |= _used_names(step.get("steps", []))
        elif step.get("type") == "parallel":
            for branch in step.get("branches", []) or []:
                names |= _used_names(branch)
        elif step.get("type") == "ramp_rtpc":
            for cross in step.get("on_cross", []) or []:
                if isinstance(cross, dict) and isinstance(cross.get("do"), dict):
                    names |= _used_names([cross["do"]])
    return names


def build_rule_plan(scenario: str, objects: dict[str, Any]) -> dict[str, Any] | None:
    """Deterministic planner for the recurring Stamina debug flow.

    This is intentionally narrow. It gives the tool a useful no-API path for the
    user's current workflow while LLM routes remain available for general cases.
    """
    text = scenario.lower()
    if not any(token in text for token in ["stamina", "体力", "耐力", "喘", "gasp", "recover"]):
        return None

    events = set(objects.get("events", []) or [])
    rtpcs = {item.get("name") for item in objects.get("rtpcs", []) or []}
    switch_groups = {
        group.get("group"): set(group.get("switches", []) or []) for group in objects.get("switch_groups", []) or []
    }
    if "Play_Stamina" not in events or "RTPC_Player_Stamina" not in rtpcs:
        return None

    play_gasp = _pick_event(events, "Play_Gasp", "Gasp")
    play_recover = _pick_event(events, "Play_Recover", "Recover")
    if not play_gasp or not play_recover:
        return None

    down_seconds = _parse_duration_between(scenario, 50, 0, 15.0)
    up_seconds = _parse_duration_between(scenario, 0, 50, 1.0)
    recover_threshold = _parse_recover_threshold(scenario, 40.0)
    genders = _requested_genders(scenario, switch_groups.get("Gender", set()))
    steps: list[dict[str, Any]] = []
    for index, gender in enumerate(genders):
        if index:
            steps.append({"type": "wait", "seconds": 0.4})
        if "Perspective" in switch_groups and "Player" in switch_groups["Perspective"]:
            steps.append({"type": "set_switch", "group": "Perspective", "value": "Player"})
        if gender:
            steps.append({"type": "set_switch", "group": "Gender", "value": gender})
        steps.extend([
            {"type": "set_rtpc", "rtpc": "RTPC_Player_Stamina", "value": 50},
            {"type": "post_event", "event": "Play_Stamina"},
            {
                "type": "ramp_rtpc",
                "rtpc": "RTPC_Player_Stamina",
                "waypoints": [50, 0],
                "seg_seconds": [down_seconds],
                "on_cross": [
                    {"value": 0, "direction": "down", "do": {"type": "post_event", "event": play_gasp}}
                ],
            },
            {
                "type": "ramp_rtpc",
                "rtpc": "RTPC_Player_Stamina",
                "waypoints": [0, 50],
                "seg_seconds": [up_seconds],
                "on_cross": [
                    {
                        "value": recover_threshold,
                        "direction": "up",
                        "do": {"type": "post_event", "event": play_recover},
                    }
                ],
            },
            {"type": "wait", "seconds": 0.3},
            {"type": "stop_all"},
        ])

    return {
        "name": "Stamina full flow debug",
        "game_object": "AudioLogicTester_Stamina",
        "steps": steps,
        "_planner_notes": [
            "Deterministic Stamina template generated without an API key.",
            f"Down ramp: 50 -> 0 over {down_seconds:g}s; up ramp: 0 -> 50 over {up_seconds:g}s.",
            f"Recover threshold: > {recover_threshold:g}. Genders: {', '.join(g for g in genders if g) or 'default'}.",
        ],
    }


def _pick_event(events: set[str], preferred: str, suffix: str) -> str | None:
    if preferred in events:
        return preferred
    for name in (f"Play_Female_{suffix}", f"Play_Male_{suffix}", f"Play_{suffix}"):
        if name in events:
            return name
    return None


def _requested_genders(scenario: str, available: set[str]) -> list[str]:
    text = scenario.lower()
    has_male = "男" in scenario or "male" in text
    has_female = "女" in scenario or "female" in text
    if ("男" in scenario and "女" in scenario) or (has_male and has_female):
        candidates = ["Male", "Female"]
    elif has_male:
        candidates = ["Male"]
    elif has_female:
        candidates = ["Female"]
    else:
        candidates = ["Male"] if "Male" in available else [""]
    return [gender for gender in candidates if not gender or gender in available] or [""]


def _parse_duration_between(scenario: str, start: int, end: int, default: float) -> float:
    patterns = [
        rf"{start}\s*(?:到|->|至)\s*{end}[^\n。；;]*?(\d+(?:\.\d+)?)\s*(?:s|秒|sec|seconds)",
        rf"{start}[^\n。；;]*?{end}[^\n。；;]*?(\d+(?:\.\d+)?)\s*(?:s|秒|sec|seconds)",
    ]
    for pattern in patterns:
        match = re.search(pattern, scenario, re.I)
        if match:
            try:
                return max(0.0, float(match.group(1)))
            except ValueError:
                pass
    return default


def _parse_recover_threshold(scenario: str, default: float) -> float:
    patterns = [
        r"(?:超过|高于)\s*(\d+(?:\.\d+)?)",
        r"\b(?:above|over)\b\s*(\d+(?:\.\d+)?)",
    ]
    for pattern in patterns:
        match = re.search(pattern, scenario, re.I)
        if not match:
            continue
        try:
            return float(match.group(1))
        except ValueError:
            return default
    return default


def _call_cli(system: str, user: str, cfg: LLMConfig) -> str:
    """Use a logged-in Claude Code or Codex CLI when available."""
    import shutil
    import subprocess

    provider = _provider_alias(cfg.provider)
    prompt = system + "\n\n" + user
    if provider == "claude-cli":
        exe = shutil.which(cfg.claude_cmd)
        if not exe:
            raise PlannerError(
                "找不到 claude CLI。Claude Code 登录态不能被 Python 直接复用；"
                "只有安装并登录可非交互调用的 claude 命令后，才能选择 claude-cli。"
            )
        cmd = [exe, "-p", prompt]
    else:
        exe = shutil.which(cfg.codex_cmd)
        if not exe:
            raise PlannerError(
                "找不到 codex CLI。Codex App 登录态不能被 Python 直接复用；"
                "只有安装并登录可非交互调用的 codex 命令后，才能选择 codex-cli。"
            )
        cmd = [exe, "exec", prompt]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=cfg.timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise PlannerError(f"CLI call timed out after {cfg.timeout}s.") from exc
    if proc.returncode != 0:
        raise PlannerError(f"CLI returned an error:\n{(proc.stderr or proc.stdout)[:800]}")
    return proc.stdout or ""


def _post(url: str, payload: dict[str, Any], headers: dict[str, str], timeout: int) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        raise PlannerError(f"HTTP {exc.code} from {url}: {body[:500]}") from exc
    except urllib.error.URLError as exc:
        raise PlannerError(f"Cannot connect {url}: {exc.reason}") from exc


def _call_ollama(system: str, user: str, cfg: LLMConfig) -> str:
    url = cfg.ollama_url.rstrip("/") + "/api/chat"
    payload = {
        "model": cfg.local_model,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.2, "num_predict": 2048},
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }
    response = _post(url, payload, {}, cfg.timeout)
    return (response.get("message") or {}).get("content", "")


def _call_remote(system: str, user: str, cfg: LLMConfig) -> str:
    provider = _provider_alias(cfg.provider)
    if provider == "anthropic":
        if not cfg.anthropic_key:
            raise PlannerError("未配置 ANTHROPIC_API_KEY；请选择 local/Ollama、claude-cli，或配置 API Key。")
        url = cfg.anthropic_url.rstrip("/") + "/messages"
        payload = {
            "model": cfg.anthropic_model,
            "max_tokens": 2048,
            "temperature": 0.2,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        headers = {"x-api-key": cfg.anthropic_key, "anthropic-version": "2023-06-01"}
        response = _post(url, payload, headers, cfg.timeout)
        parts = response.get("content") or []
        return "".join(part.get("text", "") for part in parts if isinstance(part, dict))

    if not cfg.openai_key:
        raise PlannerError("未配置 OPENAI_API_KEY；选择 OpenAI API 不等于复用 Codex App 登录态。")
    url = cfg.openai_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": cfg.openai_model,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }
    response = _post(url, payload, {"Authorization": f"Bearer {cfg.openai_key}"}, cfg.timeout)
    choices = response.get("choices") or []
    return (choices[0].get("message") or {}).get("content", "") if choices else ""


def _extract_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if not text:
        raise PlannerError("模型返回为空。")
    candidates = [text]
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S | re.I)
    if fence:
        candidates.append(fence.group(1).strip())
    start = text.find("{")
    if start >= 0:
        try:
            _obj, end = json.JSONDecoder().raw_decode(text[start:])
            candidates.append(text[start:start + end])
        except json.JSONDecodeError:
            pass
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            continue
    raise PlannerError(f"无法从模型输出解析 JSON:\n{text[:500]}")
