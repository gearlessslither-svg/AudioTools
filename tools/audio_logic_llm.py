"""Natural-language -> Wwise audio-logic DSL, via local or remote LLM.

Modes:
  local  : Ollama (default qwen2.5:7b-instruct), no API key needed.
  remote : OpenAI-compatible (gpt-*) OR Anthropic (claude-*), needs an API key.
  auto   : remote if an API key is configured, else local.

The generated DSL is grounded in the project's real Events/RTPCs/States/Switches
(passed in via `objects`) so the model never invents names.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

OLLAMA_URL = "http://127.0.0.1:11434"
OPENAI_URL = "https://api.openai.com/v1"
ANTHROPIC_URL = "https://api.anthropic.com/v1"


class PlannerError(RuntimeError):
    pass


@dataclass
class LLMConfig:
    mode: str = "auto"            # auto | local | remote
    provider: str = "ollama"      # ollama | openai | anthropic
    ollama_url: str = OLLAMA_URL
    local_model: str = "qwen2.5:7b-instruct"
    openai_url: str = OPENAI_URL
    openai_model: str = "gpt-5-mini"
    openai_key: str = ""
    anthropic_url: str = ANTHROPIC_URL
    anthropic_model: str = "claude-sonnet-4-6"
    anthropic_key: str = ""
    timeout: int = 120

    def __post_init__(self) -> None:
        self.openai_key = self.openai_key or os.environ.get("OPENAI_API_KEY", "")
        self.anthropic_key = self.anthropic_key or os.environ.get("ANTHROPIC_API_KEY", "")


def resolve_route(cfg: LLMConfig) -> str:
    mode = (cfg.mode or "auto").lower()
    if mode == "local":
        return "local"
    if mode == "remote":
        return "remote"
    # auto: prefer remote if a key exists
    if (cfg.provider == "anthropic" and cfg.anthropic_key) or \
       (cfg.provider in ("openai", "") and cfg.openai_key):
        return "remote"
    return "local"


SCHEMA_DOC = """
Return ONE JSON object only, no prose. Shape:
{
  "name": "<short scenario name>",
  "game_object": "TestObj",
  "steps": [ <step>, ... ]
}
Step types (use ONLY these):
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
Rules (follow EXACTLY):
- PRESERVE the exact ORDER and DIRECTION of RTPC changes the user describes. If they
  say "先降再升 / drop then rise", waypoints MUST go down first then up (e.g. [50,20,80]).
- Any gradual / slow / smooth / "缓慢/逐渐/慢慢" change MUST use `ramp_rtpc`. NEVER use
  `set_rtpc` for a gradual change — `set_rtpc` is only for an instant jump.
- `ramp_rtpc.waypoints` needs >= 2 numbers in the described order; `seg_seconds` MUST have
  exactly (len(waypoints) - 1) numbers. Split the user's total duration across the segments.
- `on_cross` fires a step when the ramping value crosses a threshold in the given direction
  (use "down" for a falling threshold, "up" for a rising one).
- Use `post_event` to trigger an event (NOT `post_trigger`, unless the name is truly a Trigger).
- Use ONLY names from the project lists. Keep RTPC values within each RTPC's min/max.
- Output steps that match the user's described sequence exactly — no extra/missing steps.

EXAMPLE
User: "触发青蛙环境音；把湿度从 0 缓慢升到 100 再降回 20，共 8 秒；升过 60 触发 buzzbait；回落到 30 触发鱼入水"
JSON:
{"name":"湿度测试","game_object":"TestObj","steps":[
  {"type":"post_event","event":"Play_Amb_LCW_3D_Frogs"},
  {"type":"ramp_rtpc","rtpc":"RTPC_Env_Wetness","waypoints":[0,100,20],"seg_seconds":[4,4],
    "on_cross":[
      {"value":60,"direction":"up","do":{"type":"post_event","event":"Play_Buzzbait"}},
      {"value":30,"direction":"down","do":{"type":"post_event","event":"Play_Fish_WaterIn"}}]}
]}
""".strip()


def _objects_block(objects: dict[str, Any]) -> str:
    rtpcs = ", ".join(
        f"{r['name']}[{r.get('min')}..{r.get('max')}]" for r in objects.get("rtpcs", [])
    )
    states = "; ".join(
        f"{g['group']}:({'/'.join(g['states'])})" for g in objects.get("state_groups", [])
    )
    switches = "; ".join(
        f"{g['group']}:({'/'.join(g['switches'])})" for g in objects.get("switch_groups", [])
    )
    return (
        "Available Events:\n" + ", ".join(objects.get("events", [])) + "\n\n"
        "Available RTPCs (name[min..max]):\n" + rtpcs + "\n\n"
        "Available State groups:\n" + states + "\n\n"
        "Available Switch groups:\n" + switches
    )


def _messages(scenario: str, objects: dict[str, Any]) -> tuple[str, str]:
    system = (
        "You are a Wwise technical sound designer. You convert a natural-language audio "
        "test scenario into a strict JSON test plan (DSL) that drives Wwise via WAAPI. "
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
    system, user = _messages(scenario, objects)
    route = resolve_route(cfg)
    if route == "remote":
        raw = _call_remote(system, user, cfg)
    else:
        raw = _call_ollama(system, user, cfg)
    plan = _extract_json(raw)
    if "steps" not in plan or not isinstance(plan["steps"], list):
        raise PlannerError(f"模型没有返回有效的 steps。原始输出:\n{raw[:500]}")
    plan.setdefault("name", scenario[:24])
    plan.setdefault("game_object", "TestObj")
    return plan


# ---------- providers ----------
def _post(url: str, payload: dict[str, Any], headers: dict[str, str], timeout: int) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json", **headers}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        raise PlannerError(f"HTTP {exc.code} from {url}: {exc.read().decode('utf-8', 'replace')[:300]}") from exc
    except urllib.error.URLError as exc:
        raise PlannerError(f"无法连接 {url}: {exc.reason}") from exc


def _call_ollama(system: str, user: str, cfg: LLMConfig) -> str:
    url = cfg.ollama_url.rstrip("/") + "/api/chat"
    payload = {
        "model": cfg.local_model, "stream": False, "format": "json",
        "options": {"temperature": 0.2, "num_predict": 2048},
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }
    resp = _post(url, payload, {}, cfg.timeout)
    return (resp.get("message") or {}).get("content", "")


def _call_remote(system: str, user: str, cfg: LLMConfig) -> str:
    if cfg.provider == "anthropic":
        if not cfg.anthropic_key:
            raise PlannerError("未配置 ANTHROPIC_API_KEY。")
        url = cfg.anthropic_url.rstrip("/") + "/messages"
        payload = {
            "model": cfg.anthropic_model, "max_tokens": 2048, "temperature": 0.2,
            "system": system, "messages": [{"role": "user", "content": user}],
        }
        headers = {"x-api-key": cfg.anthropic_key, "anthropic-version": "2023-06-01"}
        resp = _post(url, payload, headers, cfg.timeout)
        parts = resp.get("content") or []
        return "".join(p.get("text", "") for p in parts if isinstance(p, dict))
    # openai-compatible
    if not cfg.openai_key:
        raise PlannerError("未配置 OPENAI_API_KEY。")
    url = cfg.openai_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": cfg.openai_model, "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }
    resp = _post(url, payload, {"Authorization": f"Bearer {cfg.openai_key}"}, cfg.timeout)
    choices = resp.get("choices") or []
    return (choices[0].get("message") or {}).get("content", "") if choices else ""


# ---------- json ----------
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
            _, end = json.JSONDecoder().raw_decode(text[start:])
            candidates.append(text[start:start + end])
        except json.JSONDecodeError:
            pass
    for c in candidates:
        try:
            obj = json.loads(c)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue
    raise PlannerError(f"无法从模型输出解析 JSON:\n{text[:500]}")
