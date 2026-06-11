from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from .db import PlanCategory
from .planner import generate_plan as generate_rule_plan
from .planner import suggest_title
from .recipe import STYLE_LABELS, build_recipe_for_category


DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_OPENAI_URL = "http://127.0.0.1:1234/v1"
DEFAULT_REMOTE_URL = "https://api.openai.com/v1"
DEFAULT_REMOTE_MODEL = "gpt-5-mini"
DEFAULT_MODEL = "qwen2.5:7b-instruct"
DEFAULT_REMOTE_SLOW_MS = 6000
# Output token budget for local models. Must comfortably exceed a full plan: ~10
# categories with directions + keyword arrays runs ~800+ tokens, and 700 truncated
# the JSON ~1/3 of the time -> parse failure -> bad rule fallback. 2048 gives headroom.
DEFAULT_LOCAL_NUM_PREDICT = 2048
# Exact placeholder tokens the model might echo from a schema/example.
# Matched by whole-string equality (see _is_placeholder_text), NOT substring,
# so real keywords like "drum sample" or "category select" are not stripped.
PLACEHOLDER_MARKERS = {
    "category",
    "example",
    "example requirement",
    "english keyword",
    "schema",
    "sound library",
    "sfx search",
    "\u793a\u4f8b\u9700\u6c42",
    "\u6574\u7406\u540e\u7684\u9700\u6c42",
    "\u5206\u7c7b",
    "\u58f0\u97f3\u65b9\u5411",
}


class LocalModelError(RuntimeError):
    pass


@dataclass
class LocalModelConfig:
    mode: str = "auto"
    provider: str = "ollama"
    base_url: str = DEFAULT_OLLAMA_URL
    model: str = DEFAULT_MODEL
    api_key: str = ""
    remote_base_url: str = DEFAULT_REMOTE_URL
    remote_model: str = DEFAULT_REMOTE_MODEL
    remote_api_key: str = ""
    remote_slow_ms: int = DEFAULT_REMOTE_SLOW_MS
    temperature: float = 0.2
    timeout: int = 90
    max_categories: int = 10
    allow_rule_fallback: bool = False


@dataclass
class GeneratedPlan:
    title: str
    requirement: str
    categories: list[PlanCategory]
    source: str
    route: str
    route_reason: str
    latency_ms: int = 0
    raw_response: str = ""
    warning: str = ""


@dataclass
class RouteDecision:
    route: str
    reason: str
    latency_ms: int = 0


def default_config(provider: str | None = None) -> LocalModelConfig:
    selected_provider = (provider or os.environ.get("SOUND_FINDER_LLM_PROVIDER") or "ollama").strip()
    if selected_provider == "openai_compatible":
        base_url = os.environ.get("SOUND_FINDER_LLM_BASE_URL", DEFAULT_OPENAI_URL)
    else:
        base_url = os.environ.get("SOUND_FINDER_LLM_BASE_URL", DEFAULT_OLLAMA_URL)
    return LocalModelConfig(
        mode=os.environ.get("SOUND_FINDER_LLM_MODE", "auto").strip() or "auto",
        provider=selected_provider,
        base_url=base_url,
        model=os.environ.get("SOUND_FINDER_LLM_MODEL", DEFAULT_MODEL),
        api_key=os.environ.get("SOUND_FINDER_LLM_API_KEY", ""),
        remote_base_url=os.environ.get("SOUND_FINDER_REMOTE_BASE_URL", DEFAULT_REMOTE_URL),
        remote_model=os.environ.get("SOUND_FINDER_REMOTE_MODEL", DEFAULT_REMOTE_MODEL),
        remote_api_key=os.environ.get("SOUND_FINDER_REMOTE_API_KEY", os.environ.get("OPENAI_API_KEY", "")),
        remote_slow_ms=_int_from_text(
            os.environ.get("SOUND_FINDER_REMOTE_SLOW_MS", str(DEFAULT_REMOTE_SLOW_MS)),
            DEFAULT_REMOTE_SLOW_MS,
        ),
        temperature=_float_from_text(os.environ.get("SOUND_FINDER_LLM_TEMPERATURE", "0.2"), 0.2),
        timeout=_int_from_text(os.environ.get("SOUND_FINDER_LLM_TIMEOUT", "90"), 90),
        max_categories=_int_from_text(os.environ.get("SOUND_FINDER_LLM_MAX_CATEGORIES", "10"), 10),
        allow_rule_fallback=os.environ.get("SOUND_FINDER_LLM_RULE_FALLBACK", "").lower()
        in {"1", "true", "yes", "on"},
    )


def config_from_mapping(values: dict[str, str]) -> LocalModelConfig:
    provider = values.get("provider") or values.get("local_llm_provider") or ""
    config = default_config(provider or None)
    config.mode = (values.get("mode") or values.get("local_llm_mode") or config.mode).strip() or "auto"
    config.provider = (provider or config.provider).strip() or "ollama"
    config.base_url = (values.get("base_url") or values.get("local_llm_base_url") or config.base_url).strip()
    config.model = (values.get("model") or values.get("local_llm_model") or config.model).strip()
    config.api_key = (values.get("api_key") or values.get("local_llm_api_key") or config.api_key).strip()
    config.remote_base_url = (
        values.get("remote_base_url") or values.get("local_llm_remote_base_url") or config.remote_base_url
    ).strip()
    config.remote_model = (
        values.get("remote_model") or values.get("local_llm_remote_model") or config.remote_model
    ).strip()
    config.remote_api_key = (
        values.get("remote_api_key") or values.get("local_llm_remote_api_key") or config.remote_api_key
    ).strip()
    config.remote_slow_ms = _int_from_text(
        values.get("remote_slow_ms") or values.get("local_llm_remote_slow_ms") or str(config.remote_slow_ms),
        config.remote_slow_ms,
    )
    config.temperature = _float_from_text(
        values.get("temperature") or values.get("local_llm_temperature") or str(config.temperature),
        config.temperature,
    )
    config.timeout = _int_from_text(
        values.get("timeout") or values.get("local_llm_timeout") or str(config.timeout),
        config.timeout,
    )
    config.max_categories = _int_from_text(
        values.get("max_categories") or values.get("local_llm_max_categories") or str(config.max_categories),
        config.max_categories,
    )
    fallback = values.get("allow_rule_fallback") or values.get("local_llm_allow_rule_fallback") or ""
    if fallback:
        config.allow_rule_fallback = fallback.lower() in {"1", "true", "yes", "on"}
    return config


def settings_from_config(config: LocalModelConfig) -> dict[str, str]:
    return {
        "local_llm_mode": config.mode,
        "local_llm_provider": config.provider,
        "local_llm_base_url": config.base_url,
        "local_llm_model": config.model,
        "local_llm_api_key": config.api_key,
        "local_llm_remote_base_url": config.remote_base_url,
        "local_llm_remote_model": config.remote_model,
        "local_llm_remote_api_key": config.remote_api_key,
        "local_llm_remote_slow_ms": str(config.remote_slow_ms),
        "local_llm_temperature": str(config.temperature),
        "local_llm_timeout": str(config.timeout),
        "local_llm_max_categories": str(config.max_categories),
        "local_llm_allow_rule_fallback": "1" if config.allow_rule_fallback else "0",
    }


def generate_requirement_plan(requirement: str, config: LocalModelConfig) -> GeneratedPlan:
    clean_requirement = requirement.strip()
    if not clean_requirement:
        raise LocalModelError("请先输入本次音效需求。")

    decision = choose_generation_route(config)
    route_errors: list[str] = []
    try:
        return _generate_with_route(clean_requirement, config, decision)
    except Exception as exc:
        route_errors.append(f"{decision.route}: {exc}")
        if config.mode == "auto" and decision.route == "remote":
            local_decision = RouteDecision("local", f"远程失败，自动切到本地：{exc}", decision.latency_ms)
            try:
                return _generate_with_route(clean_requirement, config, local_decision)
            except Exception as local_exc:
                route_errors.append(f"local: {local_exc}")
        if not config.allow_rule_fallback:
            if isinstance(exc, LocalModelError):
                raise LocalModelError("; ".join(route_errors)) from exc
            raise LocalModelError("; ".join(route_errors)) from exc
        categories = generate_rule_plan(clean_requirement)
        if not categories:
            raise LocalModelError(f"模型路由失败，规则回退也没有生成可用方案：{'; '.join(route_errors)}") from exc
        return GeneratedPlan(
            title=suggest_title(clean_requirement),
            requirement=clean_requirement,
            categories=categories,
            source="rule-fallback",
            route="rule",
            route_reason="; ".join(route_errors),
            latency_ms=decision.latency_ms,
            warning=f"模型路由失败，已使用规则拆解继续：{'; '.join(route_errors)}",
        )


def _generate_with_route(requirement: str, config: LocalModelConfig, decision: RouteDecision) -> GeneratedPlan:
    if decision.route == "remote":
        raw_text = call_remote_model(requirement, config)
        source = f"remote:{config.remote_model}"
    else:
        raw_text = call_local_model(requirement, config)
        source = f"local:{config.provider}:{config.model}"
    payload = extract_json_payload(raw_text)
    title = str(payload.get("title") or suggest_title(requirement)).strip()
    normalized_requirement = str(payload.get("requirement") or requirement).strip()
    if _is_placeholder_text(title):
        title = suggest_title(requirement)
    if _is_placeholder_text(normalized_requirement):
        normalized_requirement = requirement
    categories = categories_from_payload(payload, config.max_categories)
    if not categories:
        raise LocalModelError(f"{source} 返回了 JSON，但没有可用分类。")
    return GeneratedPlan(
        title=title or suggest_title(requirement),
        requirement=normalized_requirement or requirement,
        categories=categories,
        source=source,
        route=decision.route,
        route_reason=decision.reason,
        latency_ms=decision.latency_ms,
        raw_response=raw_text,
    )


def choose_generation_route(config: LocalModelConfig) -> RouteDecision:
    mode = (config.mode or "auto").strip().lower()
    if mode == "local":
        return RouteDecision("local", "用户强制本地模式。")
    if mode == "remote":
        return RouteDecision("remote", "用户强制联网 GPT 模式。")
    remote_key = config.remote_api_key or os.environ.get("OPENAI_API_KEY", "")
    if not remote_key:
        return RouteDecision("local", "未配置 OPENAI_API_KEY，使用本地模式。")
    ok, elapsed_ms, reason = check_remote_health(config)
    if ok and elapsed_ms <= max(1, config.remote_slow_ms):
        return RouteDecision("remote", f"远程 GPT 可达，探测耗时 {elapsed_ms}ms。", elapsed_ms)
    if ok:
        return RouteDecision(
            "local",
            f"远程 GPT 可达但较慢：{elapsed_ms}ms > {config.remote_slow_ms}ms，使用本地模式。",
            elapsed_ms,
        )
    return RouteDecision("local", f"远程 GPT 不可用，使用本地模式：{reason}", elapsed_ms)


def check_remote_health(config: LocalModelConfig) -> tuple[bool, int, str]:
    url = _openai_api_url(config.remote_base_url, "/models")
    headers = _remote_headers(config)
    started = time.perf_counter()
    try:
        _get_json(url, headers, min(max(1, config.timeout), 10))
    except Exception as exc:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return False, elapsed_ms, str(exc)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return True, elapsed_ms, "ok"


def call_remote_model(requirement: str, config: LocalModelConfig) -> str:
    if not config.remote_model:
        raise LocalModelError("请填写远程 GPT 模型名。")
    if not (config.remote_api_key or os.environ.get("OPENAI_API_KEY", "")):
        raise LocalModelError("未配置远程 GPT API Key。请设置 OPENAI_API_KEY 或在对话框填写。")
    url = _openai_api_url(config.remote_base_url, "/chat/completions")
    payload = {
        "model": config.remote_model,
        "temperature": config.temperature,
        "messages": _messages(requirement, config.max_categories),
        "response_format": {"type": "json_object"},
    }
    response = _post_json(url, payload, _remote_headers(config), config.timeout)
    choices = response.get("choices") or []
    if not choices:
        raise LocalModelError(f"远程 GPT 没有返回 choices：{response}")
    message = choices[0].get("message") or {}
    content = message.get("content", "")
    if not content:
        raise LocalModelError(f"远程 GPT 没有返回 message.content：{response}")
    return str(content)


def call_local_model(requirement: str, config: LocalModelConfig) -> str:
    if config.provider == "openai_compatible":
        return _call_openai_compatible(requirement, config)
    if config.provider == "ollama":
        return _call_ollama(requirement, config)
    raise LocalModelError(f"不支持的本地模型 provider：{config.provider}")


def _call_ollama(requirement: str, config: LocalModelConfig) -> str:
    if not config.model:
        raise LocalModelError("请填写 Ollama 模型名，例如 qwen2.5:7b。")
    url = config.base_url.rstrip("/") + "/api/chat"
    payload = {
        "model": config.model,
        "stream": False,
        "format": "json",
        "options": {"temperature": config.temperature, "num_predict": DEFAULT_LOCAL_NUM_PREDICT},
        "messages": _messages(requirement, config.max_categories),
    }
    response = _post_json(url, payload, {}, config.timeout)
    message = response.get("message") or {}
    content = message.get("content", "")
    if not content:
        raise LocalModelError(f"Ollama 没有返回 message.content：{response}")
    return str(content)


def _call_openai_compatible(requirement: str, config: LocalModelConfig) -> str:
    if not config.model:
        raise LocalModelError("请填写 OpenAI-compatible 本地模型名。")
    url = _openai_chat_url(config.base_url)
    headers = {}
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"
    payload = {
        "model": config.model,
        "temperature": config.temperature,
        "max_tokens": DEFAULT_LOCAL_NUM_PREDICT,
        "messages": _messages(requirement, config.max_categories),
        "response_format": {"type": "json_object"},
    }
    response = _post_json(url, payload, headers, config.timeout)
    choices = response.get("choices") or []
    if not choices:
        raise LocalModelError(f"本地 OpenAI-compatible 服务没有返回 choices：{response}")
    message = choices[0].get("message") or {}
    content = message.get("content", "")
    if not content:
        raise LocalModelError(f"本地 OpenAI-compatible 服务没有返回 message.content：{response}")
    return str(content)


def _remote_headers(config: LocalModelConfig) -> dict[str, str]:
    key = config.remote_api_key or os.environ.get("OPENAI_API_KEY", "")
    return {"Authorization": f"Bearer {key}"} if key else {}


def _compact_messages(requirement: str, max_categories: int, styles: str) -> list[dict[str, str]]:
    system = (
        "You are a senior game-audio SFX search planner. You convert a sound requirement "
        "into search categories for a LOCAL sound-effects library that is searched by matching "
        "words found in real SFX FILE NAMES. Return one valid JSON object only. Do not copy "
        "schemas or examples."
    )
    user = f"""
Sound requirement:
{requirement}

Break the requirement into up to {max_categories} categories that cover its real ACOUSTIC
dimensions (the things that actually change how the sound is recorded/searched).

CRITICAL — keywords must be CONCRETE sound words that really appear in SFX file names,
such as: whoosh, swoosh, swish, swing, air, rod, cane, stick, bamboo, wood, metal, cast,
reel, line, splash, water, drip, creak, impact, hit, snap, thud, rustle, click, tap, coin,
footstep, cloth, fast, slow, heavy, light, short, long.
DO NOT use abstract concept words that never appear in file names
(avoid: force, length, level, tier, grade, brand, season, reaction, premium, generic,
variation, environment, interaction, effect).

Rules:
- Use real, descriptive category names taken from the requirement; never "Category"/"Example".
- 4-7 concrete keywords per category. include = true for every category.
- recipe_style: exactly one of {styles}.
- recipe: 2-3 layers, each with name, role (short), keywords (concrete sound words), weight (number).
  Build the recipe from sounds that fit THIS category, not generic UI clicks.
- Do not put title, requirement, or categories inside recipe.

Return JSON with exactly these top-level keys:
- title: short title string.
- requirement: one short normalized requirement string.
- categories: array of category objects, each with name, direction, keywords, include, recipe_style, recipe.
""".strip()
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _messages(requirement: str, max_categories: int) -> list[dict[str, str]]:
    styles = ", ".join(STYLE_LABELS.keys())
    return _compact_messages(requirement, max_categories, styles)
    system = (
        "You are a senior game-audio requirement planner for a local SFX search tool. "
        "Convert a Chinese or English sound requirement into compact searchable categories. "
        "Return strict JSON only."
    )
    user = f"""
本次需求：
{requirement}

请输出 JSON 对象，不要 Markdown，不要解释。要求：
- title: 简短中文标题。
- requirement: 对原需求的简短整理。
- categories: {max_categories} 个以内，按声音目标拆分类。
- 每个 category:
  - name: 简短中文分类名。
  - direction: 中文声音方向，说明动态、材质、情绪和使用边界。
  - keywords: 4-10 个英文搜索关键词或短语，适合直接搜本地音效库。
  - include: true。
  - recipe_style: 只能是 {styles} 之一。
  - recipe: 2-4 个 layer，每个 layer 有 name, role, keywords, weight。
- layer keywords 必须是英文搜索词。
- 优先拆出可实际制作/搜索的素材层，不要写项目管理建议。

JSON schema:
{{
  "title": "2026-06-05 示例需求",
  "requirement": "整理后的需求",
  "categories": [
    {{
      "name": "分类",
      "direction": "声音方向",
      "keywords": ["english keyword"],
      "include": true,
      "recipe_style": "realistic_tactile",
      "recipe": [
        {{
          "name": "Layer",
          "role": "这一层的声音作用",
          "keywords": ["english keyword"],
          "weight": 1.0
        }}
      ]
    }}
  ]
}}
""".strip()
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _post_json(url: str, payload: dict[str, Any], headers: dict[str, str], timeout: int) -> dict[str, Any]:
    request_headers = {"Content-Type": "application/json", **headers}
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=request_headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=max(1, timeout)) as response:
            text = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise LocalModelError(f"HTTP {exc.code} from {url}: {body}") from exc
    except urllib.error.URLError as exc:
        raise LocalModelError(f"无法连接本地模型服务 {url}: {exc.reason}") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise LocalModelError(f"本地模型服务返回的不是 JSON：{text[:300]}") from exc


def _get_json(url: str, headers: dict[str, str], timeout: int) -> dict[str, Any]:
    request_headers = {"Accept": "application/json", **headers}
    request = urllib.request.Request(url, headers=request_headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=max(1, timeout)) as response:
            text = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise LocalModelError(f"HTTP {exc.code} from {url}: {body[:300]}") from exc
    except urllib.error.URLError as exc:
        raise LocalModelError(f"无法连接 {url}: {exc.reason}") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise LocalModelError(f"服务返回的不是 JSON：{text[:300]}") from exc


def _openai_api_url(base_url: str, suffix: str) -> str:
    base = (base_url or DEFAULT_REMOTE_URL).rstrip("/")
    if base.endswith("/chat/completions") and suffix == "/chat/completions":
        return base
    if base.endswith("/models") and suffix == "/models":
        return base
    if not base.endswith("/v1"):
        base += "/v1"
    return base + suffix


def _openai_chat_url(base_url: str) -> str:
    base = (base_url or DEFAULT_OPENAI_URL).rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    if not base.endswith("/v1"):
        base += "/v1"
    return base + "/chat/completions"


def extract_json_payload(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if not stripped:
        raise LocalModelError("本地模型返回为空。")
    for candidate in _json_candidates(stripped):
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    # Safety net for truncated output (e.g. token limit cut the JSON mid-array):
    # salvage every complete category object and drop the unfinished tail.
    salvaged = _salvage_categories(stripped)
    if salvaged:
        return salvaged
    raise LocalModelError(f"无法从本地模型输出中解析 JSON：{stripped[:500]}")


def _salvage_categories(text: str) -> dict[str, Any] | None:
    key = text.find('"categories"')
    if key < 0:
        return None
    start_bracket = text.find("[", key)
    if start_bracket < 0:
        return None
    objects: list[Any] = []
    i = start_bracket + 1
    n = len(text)
    while i < n:
        while i < n and text[i] not in "{]":
            i += 1
        if i >= n or text[i] == "]":
            break
        depth = 0
        in_str = False
        esc = False
        obj_start = i
        completed = False
        while i < n:
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        objects.append(json.loads(text[obj_start : i + 1]))
                    except json.JSONDecodeError:
                        pass
                    i += 1
                    completed = True
                    break
            i += 1
        if not completed:
            break  # ran out mid-object (the truncated tail) -> stop
    if objects:
        return {"categories": objects}
    return None


def _json_candidates(text: str) -> list[str]:
    candidates = [text]
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S | re.I)
    if fence:
        candidates.append(fence.group(1).strip())
    start = text.find("{")
    if start >= 0:
        decoder = json.JSONDecoder()
        try:
            _, end = decoder.raw_decode(text[start:])
            candidates.append(text[start : start + end])
        except json.JSONDecodeError:
            end = text.rfind("}")
            if end > start:
                candidates.append(text[start : end + 1])
    return candidates


def categories_from_payload(payload: dict[str, Any], max_categories: int) -> list[PlanCategory]:
    categories: list[PlanCategory] = []
    raw_categories = payload.get("categories") or []
    if not isinstance(raw_categories, list):
        return categories
    for raw in raw_categories[: max(1, max_categories)]:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        direction = str(raw.get("direction") or "").strip()
        keywords = _clean_string_list(raw.get("keywords"))
        if _is_placeholder_text(name):
            name = _category_name_from_keywords(keywords)
        if not name or not keywords:
            continue
        style = str(raw.get("recipe_style") or "realistic_tactile").strip()
        if style not in STYLE_LABELS:
            style = "realistic_tactile"
        recipe = _clean_recipe(raw.get("recipe"))
        category_dict = {
            "name": name,
            "direction": direction,
            "keywords": keywords,
            "recipe_style": style,
        }
        if not recipe:
            recipe = build_recipe_for_category(category_dict, style)
        categories.append(
            PlanCategory(
                name=name,
                direction=direction,
                keywords=keywords,
                include=True,
                recipe=recipe,
                recipe_style=style,
            )
        )
    return _dedupe_categories(categories)


def _clean_recipe(raw_recipe: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_recipe, list):
        return []
    recipe: list[dict[str, Any]] = []
    for raw in raw_recipe[:4]:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "Layer").strip()
        role = str(raw.get("role") or "").strip()
        keywords = _clean_string_list(raw.get("keywords"))
        if not keywords:
            continue
        recipe.append(
            {
                "name": name or "Layer",
                "role": role,
                "keywords": keywords,
                "weight": _float_from_text(str(raw.get("weight", "1.0")), 1.0),
            }
        )
    return recipe


def _clean_string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        raw_items = re.split(r"[,;\n]", value)
    elif isinstance(value, list):
        raw_items = value
    else:
        return []
    output: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        text = str(item).strip()
        key = text.lower()
        if not text or key in seen or _is_placeholder_text(text):
            continue
        seen.add(key)
        output.append(text)
    return output


def _is_placeholder_text(text: Any) -> bool:
    value = str(text or "").strip().lower()
    if not value:
        return False
    return value in PLACEHOLDER_MARKERS


def _category_name_from_keywords(keywords: list[str]) -> str:
    for keyword in keywords:
        words = re.findall(r"[A-Za-z0-9]+", keyword)
        if words:
            return " ".join(word.capitalize() for word in words[:4])
    return ""


def _dedupe_categories(categories: list[PlanCategory]) -> list[PlanCategory]:
    output: list[PlanCategory] = []
    seen: set[str] = set()
    for category in categories:
        key = category.name.lower()
        if key in seen:
            continue
        seen.add(key)
        output.append(category)
    return output


def _float_from_text(text: str, default: float) -> float:
    try:
        return float(str(text).strip())
    except (TypeError, ValueError):
        return default


def _int_from_text(text: str, default: int) -> int:
    try:
        return int(float(str(text).strip()))
    except (TypeError, ValueError):
        return default
