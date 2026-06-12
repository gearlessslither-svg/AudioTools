"""Wwise audio-logic test engine.

Executes a structured test plan (DSL) against a running Wwise Authoring instance
via WAAPI `ak.soundengine.*`. This is a programmable, scriptable "Sound Caster":
post events, ramp RTPCs over time, set states/switches, with sequencing,
conditional triggers (on RTPC crossing), loops and parallel branches.

The DSL is intentionally small + extensible. Add a step type = add one handler.

DSL shape:
{
  "name": "scenario",
  "game_object": "TestObj",
  "steps": [ <step>, ... ]
}

Step types:
  {"type":"post_event",  "event":"Name"}
  {"type":"stop_event",  "event":"Name"}            # stops the playing id from a prior post_event
  {"type":"stop_all"}
  {"type":"set_rtpc",    "rtpc":"Name", "value": 50}
  {"type":"ramp_rtpc",   "rtpc":"Name", "waypoints":[0,100,30,70],
                          "seg_seconds":[5,3,4],
                          "on_cross":[{"value":30,"direction":"down","do":<step>}]}
  {"type":"set_state",   "group":"G", "value":"S"}
  {"type":"set_switch",  "group":"G", "value":"S"}
  {"type":"post_trigger","trigger":"Name"}
  {"type":"wait",        "seconds": 2}
  {"type":"loop",        "count": 3, "steps":[ ... ]}
  {"type":"parallel",    "branches":[[ ... ],[ ... ]]}
"""
from __future__ import annotations

import asyncio
import threading
import time
from typing import Any, Callable

DEFAULT_WAAPI_URL = "ws://127.0.0.1:8080/waapi"
RAMP_TICK_SECONDS = 0.03  # ~33 Hz RTPC update while ramping


class AudioLogicError(RuntimeError):
    pass


def _ensure_event_loop() -> None:
    # WaapiClient.__init__ calls asyncio.get_event_loop(); raises in worker threads
    # on Python 3.12+. Give this thread a loop first.
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


class AudioLogicEngine:
    def __init__(self, url: str = DEFAULT_WAAPI_URL,
                 log: Callable[[str], None] | None = None,
                 stop_flag: threading.Event | None = None) -> None:
        self.url = url
        self.log = log or (lambda m: None)
        self.stop_flag = stop_flag or threading.Event()
        self.client = None
        self.gobj = 90909
        self._playing: dict[str, int] = {}  # event name -> playing id

    # ---------- connection ----------
    def connect(self) -> None:
        _ensure_event_loop()
        try:
            from waapi import WaapiClient
        except Exception as exc:  # noqa: BLE001
            raise AudioLogicError(f"缺少 waapi 库: {exc}. 运行 pip install waapi-client") from exc
        try:
            self.client = WaapiClient(url=self.url)
        except Exception as exc:  # noqa: BLE001
            raise AudioLogicError(
                f"无法连接 WAAPI ({self.url})。请确认 Wwise 已打开并启用 Authoring API。\n{exc}"
            ) from exc
        info = self._call("ak.wwise.core.getInfo", {}) or {}
        ver = (info.get("version") or {}).get("displayName", "?")
        self.log(f"已连接 Wwise {ver}")

    def disconnect(self) -> None:
        if self.client:
            try:
                self._call("ak.soundengine.unregisterGameObj", {"gameObject": self.gobj})
            except Exception:
                pass
            try:
                self.client.disconnect()
            except Exception:
                pass
            self.client = None

    def _call(self, uri: str, args: dict[str, Any]) -> Any:
        if not self.client:
            raise AudioLogicError("WAAPI 未连接。")
        return self.client.call(uri, args)

    def fetch_objects(self) -> dict[str, Any]:
        """Pull the project's real Events/RTPCs/States/Switches so the LLM can
        only reference names that actually exist (grounding the generated DSL)."""
        def q(waql: str, ret: list[str]) -> list[dict[str, Any]]:
            r = self._call("ak.wwise.core.object.get", {"waql": waql, "options": {"return": ret}}) or {}
            return r.get("return", [])

        events = [o["name"] for o in q("$ from type Event", ["name"])]
        rtpcs = [
            {"name": o["name"], "min": o.get("Min"), "max": o.get("Max")}
            for o in q("$ from type GameParameter", ["name", "Min", "Max"])
        ]
        state_groups = []
        for g in q("$ from type StateGroup", ["name", "id"]):
            states = [s["name"] for s in q(f'$ "{g["id"]}" select children where type = "State"', ["name"])]
            state_groups.append({"group": g["name"], "states": states})
        switch_groups = []
        for g in q("$ from type SwitchGroup", ["name", "id"]):
            switches = [s["name"] for s in q(f'$ "{g["id"]}" select children where type = "Switch"', ["name"])]
            switch_groups.append({"group": g["name"], "switches": switches})
        return {"events": events, "rtpcs": rtpcs,
                "state_groups": state_groups, "switch_groups": switch_groups}

    def _stopped(self) -> bool:
        return self.stop_flag.is_set()

    # ---------- run ----------
    def run(self, plan: dict[str, Any]) -> None:
        name = plan.get("name", "scenario")
        gobj_name = str(plan.get("game_object") or "LLM_AudioTest")
        self.log(f"=== 运行场景: {name} (game object: {gobj_name}) ===")
        self._call("ak.soundengine.registerGameObj", {"gameObject": self.gobj, "name": gobj_name})
        self._load_banks(plan)
        try:
            self._run_steps(plan.get("steps", []))
            if self._stopped():
                self.log("已停止。")
            else:
                self.log("=== 场景执行完成 ===")
        finally:
            self.stop_all()

    def _collect_events(self, steps: list[Any]) -> set[str]:
        names: set[str] = set()
        for s in steps or []:
            if not isinstance(s, dict):
                continue
            t = s.get("type")
            if t in ("post_event", "stop_event") and s.get("event"):
                names.add(s["event"])
            elif t == "ramp_rtpc":
                for c in s.get("on_cross", []):
                    if isinstance(c, dict) and c.get("do"):
                        names |= self._collect_events([c["do"]])
            elif t == "loop":
                names |= self._collect_events(s.get("steps", []))
            elif t == "parallel":
                for b in s.get("branches", []):
                    names |= self._collect_events(b)
        return names

    def _load_banks(self, plan: dict[str, Any]) -> None:
        """Auto-defined SoundBanks are named after the event. ak.soundengine plays
        silence unless the event's bank (+ Init) is loaded, so load them up front."""
        try:
            self._call("ak.soundengine.loadBank", {"soundBank": "Init"})
        except Exception as exc:  # noqa: BLE001
            self.log(f"loadBank Init 警告: {exc}")
        events = self._collect_events(plan.get("steps", []))
        loaded = 0
        for ev in sorted(events):
            try:
                self._call("ak.soundengine.loadBank", {"soundBank": ev})
                loaded += 1
            except Exception as exc:  # noqa: BLE001
                self.log(f"loadBank '{ev}' 跳过(可能不是独立 bank): {exc}")
        self.log(f"已加载 SoundBank: Init + {loaded}/{len(events)} 个事件 bank")

    def _run_steps(self, steps: list[dict[str, Any]]) -> None:
        for step in steps:
            if self._stopped():
                return
            self._run_step(step)

    def _run_step(self, step: dict[str, Any]) -> None:
        t = str(step.get("type", "")).strip()
        handler = getattr(self, f"_do_{t}", None)
        if handler is None:
            self.log(f"[跳过] 未知步骤类型: {t}")
            return
        handler(step)

    # ---------- step handlers ----------
    def _do_post_event(self, step: dict[str, Any]) -> None:
        ev = step["event"]
        res = self._call("ak.soundengine.postEvent", {"event": ev, "gameObject": self.gobj}) or {}
        pid = res.get("return")
        if pid is not None:
            self._playing[ev] = pid
        self.log(f"▶ postEvent  {ev}  (playingId={pid})")

    def _do_stop_event(self, step: dict[str, Any]) -> None:
        ev = step["event"]
        pid = self._playing.get(ev)
        if pid is not None:
            self._call("ak.soundengine.stopPlayingID", {"playingId": pid})
            self.log(f"⏹ stopEvent {ev} (playingId={pid})")
        else:
            self.log(f"⏹ stopEvent {ev}: 没有记录的 playingId,跳过")

    def _do_stop_all(self, step: dict[str, Any]) -> None:
        self.stop_all()

    def stop_all(self) -> None:
        try:
            self._call("ak.soundengine.stopAll", {"gameObject": self.gobj})
            self.log("⏹ stopAll")
        except Exception as exc:  # noqa: BLE001
            self.log(f"stopAll 警告: {exc}")

    def _do_set_rtpc(self, step: dict[str, Any]) -> None:
        rtpc, val = step["rtpc"], float(step["value"])
        self._call("ak.soundengine.setRTPCValue", {"rtpc": rtpc, "value": val, "gameObject": self.gobj})
        self.log(f"• setRTPC  {rtpc} = {val}")

    def _do_set_state(self, step: dict[str, Any]) -> None:
        self._call("ak.soundengine.setState", {"stateGroup": step["group"], "state": step["value"]})
        self.log(f"• setState {step['group']} -> {step['value']}")

    def _do_set_switch(self, step: dict[str, Any]) -> None:
        self._call("ak.soundengine.setSwitch",
                   {"switchGroup": step["group"], "switch": step["value"], "gameObject": self.gobj})
        self.log(f"• setSwitch {step['group']} -> {step['value']}")

    def _do_post_trigger(self, step: dict[str, Any]) -> None:
        self._call("ak.soundengine.postTrigger", {"trigger": step["trigger"], "gameObject": self.gobj})
        self.log(f"• postTrigger {step['trigger']}")

    def _do_wait(self, step: dict[str, Any]) -> None:
        secs = float(step.get("seconds", 0))
        self.log(f"… wait {secs}s")
        end = time.monotonic() + secs
        while time.monotonic() < end and not self._stopped():
            time.sleep(min(0.05, end - time.monotonic()))

    def _do_loop(self, step: dict[str, Any]) -> None:
        count = int(step.get("count", 1))
        for i in range(count):
            if self._stopped():
                return
            self.log(f"↻ loop {i + 1}/{count}")
            self._run_steps(step.get("steps", []))

    def _do_parallel(self, step: dict[str, Any]) -> None:
        branches = step.get("branches", [])
        self.log(f"⇉ parallel: {len(branches)} 个分支")
        threads = [threading.Thread(target=self._run_steps, args=(b,), daemon=True) for b in branches]
        for t in threads:
            t.start()
        for t in threads:
            while t.is_alive():
                t.join(0.1)
                if self._stopped():
                    break

    def _do_ramp_rtpc(self, step: dict[str, Any]) -> None:
        rtpc = step["rtpc"]
        waypoints = [float(v) for v in step["waypoints"]]
        if len(waypoints) < 2:
            self.log(f"ramp_rtpc {rtpc}: 至少需要 2 个 waypoint,跳过")
            return
        segs = step.get("seg_seconds")
        if not segs:
            total = float(step.get("duration", len(waypoints) - 1))
            segs = [total / (len(waypoints) - 1)] * (len(waypoints) - 1)
        segs = [float(s) for s in segs]
        crosses = step.get("on_cross", [])
        fired: set[int] = set()
        self.log(f"〜 ramp {rtpc}: {waypoints} 用时 {sum(segs):.1f}s")

        prev = waypoints[0]
        self._call("ak.soundengine.setRTPCValue", {"rtpc": rtpc, "value": prev, "gameObject": self.gobj})
        for i in range(len(waypoints) - 1):
            if self._stopped():
                return
            a, b = waypoints[i], waypoints[i + 1]
            dur = max(0.0, segs[i] if i < len(segs) else segs[-1])
            start = time.monotonic()
            while True:
                if self._stopped():
                    return
                elapsed = time.monotonic() - start
                frac = 1.0 if dur <= 0 else min(1.0, elapsed / dur)
                cur = a + (b - a) * frac
                self._call("ak.soundengine.setRTPCValue", {"rtpc": rtpc, "value": cur, "gameObject": self.gobj})
                self._check_cross(crosses, fired, prev, cur)
                prev = cur
                if frac >= 1.0:
                    break
                time.sleep(RAMP_TICK_SECONDS)
        self.log(f"〜 ramp {rtpc} 完成 (终值 {waypoints[-1]})")

    def _check_cross(self, crosses: list[dict[str, Any]], fired: set[int],
                     prev: float, cur: float) -> None:
        for idx, c in enumerate(crosses):
            if idx in fired:
                continue
            v = float(c["value"])
            direction = str(c.get("direction", "any")).lower()
            up = prev < v <= cur
            down = prev > v >= cur
            hit = (direction == "up" and up) or (direction == "down" and down) or \
                  (direction == "any" and (up or down))
            if hit:
                fired.add(idx)
                self.log(f"⚡ {c['value']} 触发 ({direction}) 于 RTPC 穿越")
                self._run_step(c["do"])


def run_plan(plan: dict[str, Any], url: str = DEFAULT_WAAPI_URL,
             log: Callable[[str], None] | None = None,
             stop_flag: threading.Event | None = None) -> None:
    engine = AudioLogicEngine(url=url, log=log, stop_flag=stop_flag)
    engine.connect()
    try:
        engine.run(plan)
    finally:
        engine.disconnect()


if __name__ == "__main__":
    # Live self-test against the open Wwise project.
    import json, sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # avoid GBK console crash on log symbols
    except Exception:
        pass
    demo = {
        "name": "engine self-test",
        "game_object": "EngineSelfTest",
        "steps": [
            {"type": "post_event", "event": "Play_Amb_LCW_3D_Frogs"},
            {"type": "ramp_rtpc", "rtpc": "RTPC_Env_Wetness",
             "waypoints": [0, 100, 30], "seg_seconds": [1.5, 1.0],
             "on_cross": [
                 {"value": 50, "direction": "up", "do": {"type": "post_event", "event": "Play_Buzzbait"}},
                 {"value": 40, "direction": "down", "do": {"type": "post_event", "event": "Play_Fish_WaterIn"}},
             ]},
            {"type": "wait", "seconds": 0.5},
        ],
    }
    if len(sys.argv) > 1:
        demo = json.load(open(sys.argv[1], encoding="utf-8"))
    run_plan(demo, log=print)
