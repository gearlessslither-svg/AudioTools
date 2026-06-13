"""Wwise audio-logic test engine.

Executes a structured test plan (DSL) against a running Wwise Authoring instance
via WAAPI ``ak.soundengine.*``. The engine is intentionally small: post events,
set/ramp RTPCs, set states/switches, move the test emitter/listener, wait, loop,
and run simple branches.
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from datetime import datetime
from typing import Any, Callable

DEFAULT_WAAPI_URL = "ws://127.0.0.1:8080/waapi"
RAMP_TICK_SECONDS = 0.03
SUPPORTED_TYPES = {
    "post_event",
    "stop_event",
    "stop_all",
    "set_rtpc",
    "ramp_rtpc",
    "set_state",
    "set_switch",
    "set_distance",
    "set_position",
    "post_trigger",
    "wait",
    "loop",
    "parallel",
}


class AudioLogicError(RuntimeError):
    pass


def _ensure_event_loop() -> None:
    # WaapiClient.__init__ calls asyncio.get_event_loop(); worker threads on
    # Python 3.12+ need a loop created explicitly.
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _iter_steps(steps: list[Any], path: str = "steps") -> list[tuple[dict[str, Any] | None, str]]:
    found: list[tuple[dict[str, Any] | None, str]] = []
    for index, step in enumerate(steps or []):
        step_path = f"{path}[{index}]"
        if not isinstance(step, dict):
            found.append((None, step_path))
            continue
        found.append((step, step_path))
        if step.get("type") == "loop":
            found.extend(_iter_steps(step.get("steps", []), f"{step_path}.steps"))
        elif step.get("type") == "parallel":
            for branch_index, branch in enumerate(step.get("branches", []) or []):
                found.extend(_iter_steps(branch, f"{step_path}.branches[{branch_index}]"))
        elif step.get("type") == "ramp_rtpc":
            for cross_index, cross in enumerate(step.get("on_cross", []) or []):
                if isinstance(cross, dict) and isinstance(cross.get("do"), dict):
                    found.extend(_iter_steps([cross["do"]], f"{step_path}.on_cross[{cross_index}].do"))
    return found


def _collect_events(steps: list[Any]) -> set[str]:
    names: set[str] = set()
    for step, _path in _iter_steps(steps):
        if not step:
            continue
        if step.get("type") in {"post_event", "stop_event"} and step.get("event"):
            names.add(str(step["event"]))
    return names


def _object_maps(objects: dict[str, Any] | None) -> dict[str, Any]:
    objects = objects or {}
    rtpcs = {}
    for item in objects.get("rtpcs", []) or []:
        name = item.get("name")
        if name:
            rtpcs[str(name)] = {
                "min": _to_float(item.get("min", item.get("@Min", item.get("Min")))),
                "max": _to_float(item.get("max", item.get("@Max", item.get("Max")))),
            }
    states = {
        str(group.get("group")): {str(value) for value in group.get("states", [])}
        for group in objects.get("state_groups", []) or []
        if group.get("group")
    }
    switches = {
        str(group.get("group")): {str(value) for value in group.get("switches", [])}
        for group in objects.get("switch_groups", []) or []
        if group.get("group")
    }
    return {
        "events": {str(name) for name in objects.get("events", []) or []},
        "rtpcs": rtpcs,
        "states": states,
        "switches": switches,
        "triggers": {str(name) for name in objects.get("triggers", []) or []},
    }


def validate_plan(plan: dict[str, Any], objects: dict[str, Any] | None) -> dict[str, Any]:
    """Validate the DSL against real Wwise object names and basic playability risks."""
    maps = _object_maps(objects)
    errors: list[str] = []
    warnings: list[str] = []
    step_count = 0
    event_count = 0

    for step, path in _iter_steps(plan.get("steps", [])):
        if step is None:
            errors.append(f"{path}: step must be a JSON object.")
            continue
        step_count += 1
        step_type = str(step.get("type", "")).strip()
        if step_type not in SUPPORTED_TYPES:
            errors.append(f"{path}: unknown step type '{step_type}'.")
            continue

        if step_type in {"post_event", "stop_event"}:
            event = str(step.get("event", "")).strip()
            event_count += 1
            if not event:
                errors.append(f"{path}: missing event name.")
            elif maps["events"] and event not in maps["events"]:
                errors.append(f"{path}: event '{event}' does not exist in this Wwise project.")

        elif step_type == "post_trigger":
            trigger = str(step.get("trigger", "")).strip()
            if not trigger:
                errors.append(f"{path}: missing trigger name.")
            elif maps["triggers"] and trigger not in maps["triggers"]:
                warnings.append(f"{path}: trigger '{trigger}' was not found in the fetched Trigger list.")

        elif step_type == "set_rtpc":
            _validate_rtpc_value(step, path, maps["rtpcs"], errors, warnings)

        elif step_type == "ramp_rtpc":
            rtpc = str(step.get("rtpc", "")).strip()
            if not rtpc:
                errors.append(f"{path}: missing RTPC name.")
            elif maps["rtpcs"] and rtpc not in maps["rtpcs"]:
                errors.append(f"{path}: RTPC '{rtpc}' does not exist in this Wwise project.")
            waypoints = step.get("waypoints", [])
            if not isinstance(waypoints, list) or len(waypoints) < 2:
                errors.append(f"{path}: ramp_rtpc needs at least two waypoints.")
            else:
                for index, value in enumerate(waypoints):
                    _validate_rtpc_number(rtpc, value, f"{path}.waypoints[{index}]", maps["rtpcs"], errors, warnings)
            segs = step.get("seg_seconds")
            if segs is not None:
                if not isinstance(segs, list) or len(segs) != max(0, len(waypoints) - 1):
                    errors.append(f"{path}: seg_seconds length must equal len(waypoints) - 1.")
                else:
                    for index, value in enumerate(segs):
                        if _to_float(value) is None or float(value) < 0:
                            errors.append(f"{path}.seg_seconds[{index}]: duration must be a non-negative number.")
            for cross_index, cross in enumerate(step.get("on_cross", []) or []):
                cross_path = f"{path}.on_cross[{cross_index}]"
                if not isinstance(cross, dict):
                    errors.append(f"{cross_path}: crossing rule must be a JSON object.")
                    continue
                if _to_float(cross.get("value")) is None:
                    errors.append(f"{cross_path}: crossing value must be numeric.")
                if str(cross.get("direction", "any")).lower() not in {"up", "down", "any"}:
                    errors.append(f"{cross_path}: direction must be up, down, or any.")
                if not isinstance(cross.get("do"), dict):
                    errors.append(f"{cross_path}: missing nested 'do' step.")

        elif step_type == "set_state":
            group = str(step.get("group", "")).strip()
            value = str(step.get("value", "")).strip()
            if not group or not value:
                errors.append(f"{path}: set_state needs group and value.")
            elif maps["states"]:
                if group not in maps["states"]:
                    errors.append(f"{path}: StateGroup '{group}' does not exist.")
                elif value not in maps["states"][group]:
                    errors.append(f"{path}: State '{value}' is not in StateGroup '{group}'.")

        elif step_type == "set_switch":
            group = str(step.get("group", "")).strip()
            value = str(step.get("value", "")).strip()
            if not group or not value:
                errors.append(f"{path}: set_switch needs group and value.")
            elif maps["switches"]:
                if group not in maps["switches"]:
                    errors.append(f"{path}: SwitchGroup '{group}' does not exist.")
                elif value not in maps["switches"][group]:
                    errors.append(f"{path}: Switch '{value}' is not in SwitchGroup '{group}'.")

        elif step_type == "set_distance":
            distance = _to_float(step.get("distance"))
            if distance is None or distance < 0:
                errors.append(f"{path}: set_distance.distance must be a non-negative number.")

        elif step_type == "set_position":
            for axis in ("x", "y", "z"):
                if _to_float(step.get(axis, 0)) is None:
                    errors.append(f"{path}: set_position.{axis} must be numeric.")

        elif step_type == "wait":
            secs = _to_float(step.get("seconds", 0))
            if secs is None or secs < 0:
                errors.append(f"{path}: wait seconds must be a non-negative number.")

    warnings.extend(_stamina_warnings(plan))
    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "step_count": step_count,
        "event_count": event_count,
        "checked_at": datetime.now().isoformat(timespec="seconds"),
    }


def _validate_rtpc_value(
    step: dict[str, Any],
    path: str,
    rtpcs: dict[str, dict[str, float | None]],
    errors: list[str],
    warnings: list[str],
) -> None:
    rtpc = str(step.get("rtpc", "")).strip()
    if not rtpc:
        errors.append(f"{path}: missing RTPC name.")
        return
    if rtpcs and rtpc not in rtpcs:
        errors.append(f"{path}: RTPC '{rtpc}' does not exist in this Wwise project.")
    _validate_rtpc_number(rtpc, step.get("value"), f"{path}.value", rtpcs, errors, warnings)


def _validate_rtpc_number(
    rtpc: str,
    value: Any,
    path: str,
    rtpcs: dict[str, dict[str, float | None]],
    errors: list[str],
    warnings: list[str],
) -> None:
    number = _to_float(value)
    if number is None:
        errors.append(f"{path}: RTPC value must be numeric.")
        return
    limits = rtpcs.get(rtpc, {})
    min_value = limits.get("min")
    max_value = limits.get("max")
    if min_value is not None and number < min_value:
        warnings.append(f"{path}: {number:g} is below {rtpc} minimum {min_value:g}.")
    if max_value is not None and number > max_value:
        warnings.append(f"{path}: {number:g} is above {rtpc} maximum {max_value:g}.")


def _stamina_warnings(plan: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    steps = plan.get("steps", [])
    events = _collect_events(steps)
    uses_stamina = "Play_Stamina" in events or any(
        step and step.get("rtpc") == "RTPC_Player_Stamina" for step, _path in _iter_steps(steps)
    )
    if not uses_stamina:
        return warnings

    switch_pairs = {
        (str(step.get("group")), str(step.get("value")))
        for step, _path in _iter_steps(steps)
        if step and step.get("type") == "set_switch"
    }
    if ("Perspective", "Player") not in switch_pairs:
        warnings.append("Stamina: set Perspective=Player before Play_Stamina; Others may be empty or silent.")
    if not any(group == "Gender" for group, _value in switch_pairs):
        warnings.append("Stamina: set Gender=Male/Female before Play_Stamina to avoid inheriting an old switch state.")
    if ("Perspective", "Others") in switch_pairs:
        warnings.append("Stamina: Perspective=Others is known to be risky for this container; prefer Player for audible tests.")

    for step, path in _iter_steps(steps):
        if not step:
            continue
        if step.get("type") == "ramp_rtpc" and step.get("rtpc") == "RTPC_Player_Stamina":
            waypoints = [_to_float(v) for v in step.get("waypoints", [])]
            if len(waypoints) >= 2 and waypoints[0] is not None and waypoints[1] is not None:
                if waypoints[0] >= 40 and waypoints[1] < waypoints[0]:
                    warnings.append(
                        f"{path}: RTPC_Player_Stamina starts at {waypoints[0]:g}; "
                        "the first part of Play_Stamina may be intentionally quiet until the RTPC enters the audible range."
                    )
        if step.get("type") == "set_switch" and step.get("group") == "Gender" and step.get("value") == "Female":
            warnings.append(
                "Stamina/Female: previous project audit found the Female breathing branch can be near-silent; "
                "if Male works but Female does not, inspect the Female_Breathing volume RTPC/BlendTrack curve."
            )
    return warnings


class AudioLogicEngine:
    def __init__(
        self,
        url: str = DEFAULT_WAAPI_URL,
        log: Callable[[str], None] | None = None,
        stop_flag: threading.Event | None = None,
    ) -> None:
        self.url = url
        self.log = log or (lambda _message: None)
        self.stop_flag = stop_flag or threading.Event()
        self.client = None
        self.gobj = 90909
        self.listener_gobj = 90910
        self._playing: dict[str, int] = {}
        self.messages: list[str] = []
        self.summary: dict[str, Any] = {"posted_events": [], "warnings": [], "bank_warnings": []}
        self._profiler_active = False
        self._step_index = 0
        self._step_total = 0

    # ---------- connection ----------
    def connect(self) -> None:
        _ensure_event_loop()
        try:
            from waapi import WaapiClient
        except Exception as exc:  # noqa: BLE001
            raise AudioLogicError(f"Missing waapi-client package: {exc}. Run: pip install waapi-client") from exc
        try:
            self.client = WaapiClient(url=self.url)
        except Exception as exc:  # noqa: BLE001
            raise AudioLogicError(
                f"Cannot connect WAAPI ({self.url}). Open Wwise and enable Authoring API.\n{exc}"
            ) from exc
        info = self._call("ak.wwise.core.getInfo", {}) or {}
        version = (info.get("version") or {}).get("displayName", "?")
        self._emit(f"Connected Wwise {version}")

    def disconnect(self) -> None:
        if not self.client:
            return
        try:
            self._call("ak.soundengine.unregisterGameObj", {"gameObject": self.gobj})
        except Exception:
            pass
        try:
            self._call("ak.soundengine.unregisterGameObj", {"gameObject": self.listener_gobj})
        except Exception:
            pass
        try:
            self.client.disconnect()
        except Exception:
            pass
        self.client = None

    def _call(self, uri: str, args: dict[str, Any]) -> Any:
        if not self.client:
            raise AudioLogicError("WAAPI is not connected.")
        return self.client.call(uri, args)

    def _emit(self, message: str) -> None:
        text = str(message)
        self.messages.append(text)
        try:
            self.log(text)
        except UnicodeEncodeError:
            safe = text.encode("gbk", errors="replace").decode("gbk", errors="replace")
            try:
                self.log(safe)
            except Exception:
                pass
        except Exception:
            pass

    def fetch_objects(self) -> dict[str, Any]:
        """Fetch project Events/RTPCs/States/Switches to ground plans in real names."""

        def q(waql: str, returns: list[str]) -> list[dict[str, Any]]:
            result = self._call("ak.wwise.core.object.get", {"waql": waql, "options": {"return": returns}}) or {}
            return result.get("return", [])

        events = [o["name"] for o in q("$ from type Event", ["name"]) if o.get("name")]
        triggers = [o["name"] for o in q("$ from type Trigger", ["name"]) if o.get("name")]
        rtpcs = []
        for item in q("$ from type GameParameter", ["name", "@Min", "@Max", "min", "max"]):
            name = item.get("name")
            if not name:
                continue
            rtpcs.append({
                "name": name,
                "min": item.get("@Min", item.get("min")),
                "max": item.get("@Max", item.get("max")),
            })
        state_groups = []
        for group in q("$ from type StateGroup", ["name", "id"]):
            states = [
                state["name"]
                for state in q(f'$ "{group["id"]}" select children where type = "State"', ["name"])
                if state.get("name")
            ]
            state_groups.append({"group": group["name"], "states": states})
        switch_groups = []
        for group in q("$ from type SwitchGroup", ["name", "id"]):
            switches = [
                switch["name"]
                for switch in q(f'$ "{group["id"]}" select children where type = "Switch"', ["name"])
                if switch.get("name")
            ]
            switch_groups.append({"group": group["name"], "switches": switches})
        return {
            "events": events,
            "triggers": triggers,
            "rtpcs": rtpcs,
            "state_groups": state_groups,
            "switch_groups": switch_groups,
        }

    def _stopped(self) -> bool:
        return self.stop_flag.is_set()

    # ---------- run ----------
    def run(self, plan: dict[str, Any]) -> dict[str, Any]:
        name = plan.get("name", "scenario")
        game_object_name = str(plan.get("game_object") or "LLM_AudioTest")
        self.summary = {
            "ok": False,
            "name": name,
            "game_object": game_object_name,
            "generated_by": plan.get("_generated_by", "manual"),
            "posted_events": [],
            "warnings": [],
            "bank_warnings": [],
            "started_at": datetime.now().isoformat(timespec="seconds"),
        }
        self._emit(f"=== Run scenario: {name} (game object: {game_object_name}) ===")
        self._emit(f"Command source: {self.summary['generated_by']}")
        if plan.get("_generation_warning"):
            self._emit(f"Generation warning: {plan['_generation_warning']}")
        if plan.get("_raw_description"):
            first_line = str(plan["_raw_description"]).splitlines()[0][:120]
            self._emit(f"Original description saved: {first_line}")

        self._call("ak.soundengine.registerGameObj", {"gameObject": self.gobj, "name": game_object_name})
        self._register_test_listener(game_object_name)
        self.stop_all()
        self._load_banks(plan)
        self._start_profiler()
        try:
            self._step_index = 0
            self._step_total = len([step for step, _path in _iter_steps(plan.get("steps", [])) if step])
            self._run_steps(plan.get("steps", []))
            if self._stopped():
                self._emit("Run stopped by user.")
                self.summary["stopped"] = True
            else:
                self._emit("=== Scenario finished ===")
                self.summary["ok"] = True
        finally:
            self.stop_all()
            self._stop_profiler()
            self.summary["finished_at"] = datetime.now().isoformat(timespec="seconds")
        return self.summary

    def _register_test_listener(self, game_object_name: str) -> None:
        listener_name = f"{game_object_name}_Listener"
        try:
            self._call("ak.soundengine.registerGameObj", {"gameObject": self.listener_gobj, "name": listener_name})
            self._set_position(self.gobj, 0.0, 0.0, 0.0)
            self._set_position(self.listener_gobj, 0.0, 0.0, 0.0)
            self._call("ak.soundengine.setDefaultListeners", {"listeners": [self.listener_gobj]})
            self._call(
                "ak.soundengine.setListeners",
                {"emitter": self.gobj, "listeners": [self.listener_gobj]},
            )
            self._emit(f"Registered test emitter/listener at origin ({self.gobj} -> {self.listener_gobj})")
        except Exception as exc:  # noqa: BLE001
            warning = f"listener setup warning: {exc}"
            self.summary["warnings"].append(warning)
            self._emit(f"WARNING: {warning}")

    def _set_position(self, game_object: int, x: float, y: float, z: float) -> None:
        self._call(
            "ak.soundengine.setPosition",
            {
                "gameObject": game_object,
                "position": {
                    "position": {"x": x, "y": y, "z": z},
                    "orientationFront": {"x": 0, "y": 0, "z": 1},
                    "orientationTop": {"x": 0, "y": 1, "z": 0},
                },
            },
        )

    def _start_profiler(self) -> None:
        try:
            self._call(
                "ak.wwise.core.profiler.enableProfilerData",
                {"dataTypes": [{"dataType": "voices"}, {"dataType": "voiceInspector"}]},
            )
            self._call("ak.wwise.core.profiler.startCapture", {})
            self._profiler_active = True
            self._emit("Profiler voice capture started.")
        except Exception as exc:  # noqa: BLE001
            warning = f"profiler voice capture unavailable: {exc}"
            self.summary["warnings"].append(warning)
            self._emit(f"WARNING: {warning}")

    def _stop_profiler(self) -> None:
        if not self._profiler_active:
            return
        try:
            self._call("ak.wwise.core.profiler.stopCapture", {})
            self._emit("Profiler voice capture stopped.")
        except Exception as exc:  # noqa: BLE001
            self._emit(f"profiler stop warning: {exc}")
        finally:
            self._profiler_active = False

    def _sample_voices(self, label: str) -> None:
        if not self._profiler_active:
            return
        try:
            result = self._call("ak.wwise.core.profiler.getVoices", {"time": "capture"}) or {}
            voices = result.get("return", []) or []
            target = [voice for voice in voices if str(voice.get("gameObjectID")) == str(self.gobj)]
            names = []
            for voice in target[:4]:
                names.append(str(voice.get("objectName") or voice.get("name") or voice.get("objectGUID") or "?"))
            suffix = f": {', '.join(names)}" if names else ""
            self._emit(f"voices after {label}: testObject={len(target)} total={len(voices)}{suffix}")
        except Exception as exc:  # noqa: BLE001
            self._emit(f"voice sample warning after {label}: {exc}")

    def _load_banks(self, plan: dict[str, Any]) -> None:
        events = _collect_events(plan.get("steps", []))
        try:
            self._call("ak.soundengine.loadBank", {"soundBank": "Init"})
        except Exception as exc:  # noqa: BLE001
            warning = f"loadBank Init warning: {exc}"
            self.summary["bank_warnings"].append(warning)
            self._emit(warning)
        loaded = 0
        for event in sorted(events):
            try:
                self._call("ak.soundengine.loadBank", {"soundBank": event})
                loaded += 1
            except Exception as exc:  # noqa: BLE001
                warning = f"loadBank '{event}' skipped or failed: {exc}"
                self.summary["bank_warnings"].append(warning)
                self._emit(warning)
        self._emit(f"SoundBanks loaded: Init + {loaded}/{len(events)} event banks")

    def _run_steps(self, steps: list[dict[str, Any]]) -> None:
        for step in steps:
            if self._stopped():
                return
            self._run_step(step)

    def _run_step(self, step: dict[str, Any]) -> None:
        step_type = str(step.get("type", "")).strip()
        handler = getattr(self, f"_do_{step_type}", None)
        if handler is None:
            self._emit(f"[skip] Unknown step type: {step_type}")
            return
        self._step_index += 1
        total = f"/{self._step_total}" if self._step_total else ""
        self._emit(f"[step {self._step_index}{total}] {self._describe_step(step)}")
        handler(step)

    def _describe_step(self, step: dict[str, Any]) -> str:
        step_type = str(step.get("type", ""))
        if step_type == "post_event":
            return f"post_event {step.get('event', '')}"
        if step_type == "stop_event":
            return f"stop_event {step.get('event', '')}"
        if step_type == "set_rtpc":
            return f"set_rtpc {step.get('rtpc', '')}={step.get('value', '')}"
        if step_type == "ramp_rtpc":
            return f"ramp_rtpc {step.get('rtpc', '')} {step.get('waypoints', [])}"
        if step_type in {"set_switch", "set_state"}:
            return f"{step_type} {step.get('group', '')}->{step.get('value', '')}"
        if step_type == "set_distance":
            return f"set_distance {step.get('distance', 0)}m"
        if step_type == "set_position":
            return f"set_position ({step.get('x', 0)}, {step.get('y', 0)}, {step.get('z', 0)})"
        if step_type == "wait":
            return f"wait {step.get('seconds', 0)}s"
        if step_type == "loop":
            return f"loop x{step.get('count', 1)}"
        if step_type == "parallel":
            return f"parallel {len(step.get('branches', []) or [])} branches"
        return step_type

    # ---------- step handlers ----------
    def _do_post_event(self, step: dict[str, Any]) -> None:
        event = step["event"]
        result = self._call("ak.soundengine.postEvent", {"event": event, "gameObject": self.gobj}) or {}
        playing_id = result.get("return")
        if playing_id is not None:
            self._playing[event] = int(playing_id)
        self.summary["posted_events"].append({"event": event, "playing_id": playing_id})
        self._emit(f"postEvent {event} (playingId={playing_id})")
        time.sleep(0.08)
        self._sample_voices(event)
        if playing_id in (None, 0):
            warning = f"postEvent {event} returned invalid playingId; event may not have started."
            self.summary["warnings"].append(warning)
            self._emit(f"WARNING: {warning}")

    def _do_stop_event(self, step: dict[str, Any]) -> None:
        event = step["event"]
        playing_id = self._playing.get(event)
        if playing_id is None:
            self._emit(f"stopEvent {event}: no recorded playingId, skipped")
            return
        self._call("ak.soundengine.stopPlayingID", {"playingId": playing_id})
        self._emit(f"stopEvent {event} (playingId={playing_id})")

    def _do_stop_all(self, _step: dict[str, Any]) -> None:
        self.stop_all()

    def stop_all(self) -> None:
        try:
            self._call("ak.soundengine.stopAll", {"gameObject": self.gobj})
            self._emit("stopAll")
        except Exception as exc:  # noqa: BLE001
            self._emit(f"stopAll warning: {exc}")

    def _do_set_rtpc(self, step: dict[str, Any]) -> None:
        rtpc = step["rtpc"]
        value = float(step["value"])
        self._call("ak.soundengine.setRTPCValue", {"rtpc": rtpc, "value": value, "gameObject": self.gobj})
        self._emit(f"setRTPC {rtpc} = {value:g}")
        self._sample_voices(f"{rtpc}={value:g}")

    def _do_set_state(self, step: dict[str, Any]) -> None:
        self._call("ak.soundengine.setState", {"stateGroup": step["group"], "state": step["value"]})
        self._emit(f"setState {step['group']} -> {step['value']}")

    def _do_set_switch(self, step: dict[str, Any]) -> None:
        # WAAPI ak.soundengine.setSwitch uses "switchState" (not "switch").
        self._call(
            "ak.soundengine.setSwitch",
            {"switchGroup": step["group"], "switchState": step["value"], "gameObject": self.gobj},
        )
        self._emit(f"setSwitch {step['group']} -> {step['value']}")

    def _do_set_distance(self, step: dict[str, Any]) -> None:
        distance = float(step.get("distance", 0))
        axis = str(step.get("axis", "z")).lower()
        if axis == "x":
            x, y, z = distance, 0.0, 0.0
        elif axis == "y":
            x, y, z = 0.0, distance, 0.0
        else:
            x, y, z = 0.0, 0.0, distance
        self._set_position(self.listener_gobj, 0.0, 0.0, 0.0)
        self._set_position(self.gobj, x, y, z)
        self._call("ak.soundengine.setListeners", {"emitter": self.gobj, "listeners": [self.listener_gobj]})
        self._emit(f"setDistance emitter->{distance:g}m on {axis}-axis")

    def _do_set_position(self, step: dict[str, Any]) -> None:
        x = float(step.get("x", 0))
        y = float(step.get("y", 0))
        z = float(step.get("z", 0))
        self._set_position(self.gobj, x, y, z)
        self._call("ak.soundengine.setListeners", {"emitter": self.gobj, "listeners": [self.listener_gobj]})
        self._emit(f"setPosition emitter=({x:g}, {y:g}, {z:g})")

    def _do_post_trigger(self, step: dict[str, Any]) -> None:
        self._call("ak.soundengine.postTrigger", {"trigger": step["trigger"], "gameObject": self.gobj})
        self._emit(f"postTrigger {step['trigger']}")

    def _do_wait(self, step: dict[str, Any]) -> None:
        seconds = float(step.get("seconds", 0))
        self._emit(f"wait {seconds:g}s")
        end = time.monotonic() + seconds
        while time.monotonic() < end and not self._stopped():
            time.sleep(min(0.05, max(0.0, end - time.monotonic())))

    def _do_loop(self, step: dict[str, Any]) -> None:
        count = int(step.get("count", 1))
        for index in range(count):
            if self._stopped():
                return
            self._emit(f"loop {index + 1}/{count}")
            self._run_steps(step.get("steps", []))

    def _do_parallel(self, step: dict[str, Any]) -> None:
        branches = step.get("branches", [])
        self._emit(f"parallel branches: {len(branches)}")
        errors: list[BaseException] = []

        def run_branch(branch: list[dict[str, Any]]) -> None:
            try:
                self._run_steps(branch)
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=run_branch, args=(branch,), daemon=True) for branch in branches]
        for thread in threads:
            thread.start()
        for thread in threads:
            while thread.is_alive():
                thread.join(0.1)
                if self._stopped():
                    break
        if errors:
            raise AudioLogicError(f"Parallel branch failed: {errors[0]}") from errors[0]

    def _do_ramp_rtpc(self, step: dict[str, Any]) -> None:
        rtpc = step["rtpc"]
        waypoints = [float(value) for value in step["waypoints"]]
        if len(waypoints) < 2:
            self._emit(f"rampRTPC {rtpc}: skipped, needs at least two waypoints")
            return
        segs = step.get("seg_seconds")
        if not segs:
            total = float(step.get("duration", len(waypoints) - 1))
            segs = [total / (len(waypoints) - 1)] * (len(waypoints) - 1)
        segs = [float(value) for value in segs]
        crosses = step.get("on_cross", [])
        fired: set[int] = set()
        self._emit(f"rampRTPC {rtpc}: {waypoints} over {sum(segs):.2f}s")

        previous = waypoints[0]
        self._call("ak.soundengine.setRTPCValue", {"rtpc": rtpc, "value": previous, "gameObject": self.gobj})
        for index in range(len(waypoints) - 1):
            if self._stopped():
                return
            start_value = waypoints[index]
            end_value = waypoints[index + 1]
            duration = max(0.0, segs[index] if index < len(segs) else segs[-1])
            start_time = time.monotonic()
            while True:
                if self._stopped():
                    return
                elapsed = time.monotonic() - start_time
                fraction = 1.0 if duration <= 0 else min(1.0, elapsed / duration)
                current = start_value + (end_value - start_value) * fraction
                self._call("ak.soundengine.setRTPCValue", {"rtpc": rtpc, "value": current, "gameObject": self.gobj})
                self._check_cross(crosses, fired, previous, current)
                previous = current
                if fraction >= 1.0:
                    break
                time.sleep(RAMP_TICK_SECONDS)
        self._emit(f"rampRTPC {rtpc} finished at {waypoints[-1]:g}")
        self._sample_voices(f"{rtpc} ramp end")

    def _check_cross(
        self,
        crosses: list[dict[str, Any]],
        fired: set[int],
        previous: float,
        current: float,
    ) -> None:
        for index, cross in enumerate(crosses):
            if index in fired:
                continue
            value = float(cross["value"])
            direction = str(cross.get("direction", "any")).lower()
            up = previous < value <= current
            down = previous > value >= current
            hit = (direction == "up" and up) or (direction == "down" and down) or (
                direction == "any" and (up or down)
            )
            if hit:
                fired.add(index)
                self._emit(f"RTPC crossed {value:g} ({direction}); running nested step")
                self._run_step(cross["do"])


def run_plan(
    plan: dict[str, Any],
    url: str = DEFAULT_WAAPI_URL,
    log: Callable[[str], None] | None = None,
    stop_flag: threading.Event | None = None,
    objects: dict[str, Any] | None = None,
    preflight: bool = True,
) -> dict[str, Any]:
    engine = AudioLogicEngine(url=url, log=log, stop_flag=stop_flag)
    engine.connect()
    validation: dict[str, Any] | None = None
    try:
        if preflight:
            live_objects = objects or engine.fetch_objects()
            validation = validate_plan(plan, live_objects)
            engine._emit(
                f"Preflight: steps={validation['step_count']} events={validation['event_count']} "
                f"errors={len(validation['errors'])} warnings={len(validation['warnings'])}"
            )
            for warning in validation["warnings"]:
                engine._emit(f"WARNING: {warning}")
            if validation["errors"]:
                for error in validation["errors"]:
                    engine._emit(f"ERROR: {error}")
                raise AudioLogicError("Preflight failed; fix the DSL before running.")
        summary = engine.run(plan)
        if validation:
            summary["validation"] = validation
        summary["log"] = engine.messages
        return summary
    finally:
        engine.disconnect()


if __name__ == "__main__":
    import sys

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    demo = {
        "name": "engine self-test",
        "game_object": "EngineSelfTest",
        "steps": [
            {"type": "set_switch", "group": "Perspective", "value": "Player"},
            {"type": "set_switch", "group": "Gender", "value": "Male"},
            {"type": "set_rtpc", "rtpc": "RTPC_Player_Stamina", "value": 30},
            {"type": "post_event", "event": "Play_Stamina"},
            {"type": "wait", "seconds": 0.5},
        ],
    }
    if len(sys.argv) > 1:
        demo = json.load(open(sys.argv[1], encoding="utf-8"))
    run_plan(demo, log=print)
