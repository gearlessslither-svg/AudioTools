from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


ROOT = Path(__file__).resolve().parents[1]
APPDATA = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
OBS_CONFIG = APPDATA / "obs-studio" / "plugin_config" / "obs-websocket" / "config.json"
OBS_SCENES = APPDATA / "obs-studio" / "basic" / "scenes"
REAPER_RESOURCE = APPDATA / "REAPER"
REAPER_SCRIPT_NAME = "Codex_OBS ReaStream capture setup.lua"
REAPER_SCRIPT_SOURCE = ROOT / "reaper_scripts" / REAPER_SCRIPT_NAME
REAPER_IDENTIFIER = "Codex_OBS"


def first_existing(paths: list[Path]) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return None


def find_obs_exe() -> Path | None:
    return first_existing(
        [
            Path(r"C:\Program Files\obs-studio\bin\64bit\obs64.exe"),
            Path(r"C:\Program Files (x86)\obs-studio\bin\64bit\obs64.exe"),
        ]
    )


def find_reaper_exe() -> Path | None:
    return first_existing(
        [
            Path(r"C:\Program Files\REAPER (x64)\reaper.exe"),
            Path(r"C:\Program Files\REAPER\reaper.exe"),
            Path(r"C:\Program Files (x86)\REAPER\reaper.exe"),
        ]
    )


def find_reastream_vst() -> Path | None:
    candidates = [
        Path(r"C:\Program Files\VSTPlugins\ReaPlugs\reastream-standalone.dll"),
        Path(r"C:\Program Files\Common Files\VST2\ReaPlugs\reastream-standalone.dll"),
        Path(r"C:\Program Files\REAPER (x64)\Plugins\FX\reastream.dll"),
    ]
    return first_existing(candidates)


def tasklist_contains(image_name: str) -> bool:
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {image_name}"],
            capture_output=True,
            text=True,
            check=False,
            timeout=8,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return image_name.lower() in result.stdout.lower()


def process_count(image_name: str) -> int:
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {image_name}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            check=False,
            timeout=8,
        )
    except (OSError, subprocess.SubprocessError):
        return 0
    return sum(1 for line in result.stdout.splitlines() if line.lower().startswith(f'"{image_name.lower()}"'))


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json_with_backup(path: Path, payload: dict[str, Any]) -> Path | None:
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    if path.exists():
        backup = path.with_suffix(path.suffix + f".bak-{time.strftime('%Y%m%d-%H%M%S')}")
        shutil.copy2(path, backup)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return backup


def obs_websocket_config_summary() -> tuple[dict[str, Any], list[str]]:
    config = read_json(OBS_CONFIG)
    lines = [f"OBS WebSocket config: {OBS_CONFIG}"]
    if not config:
        lines.append("  missing, can create it")
        return config, lines
    lines.append(f"  enabled: {config.get('server_enabled')}")
    lines.append(f"  port: {config.get('server_port', 4455)}")
    lines.append(f"  auth_required: {config.get('auth_required')}")
    lines.append("  password: configured" if config.get("server_password") else "  password: empty")
    return config, lines


def enable_obs_websocket_config() -> tuple[dict[str, Any], Path | None, bool]:
    config = read_json(OBS_CONFIG)
    changed = False
    if not config:
        config = {
            "alerts_enabled": False,
            "auth_required": False,
            "first_load": False,
            "server_enabled": True,
            "server_password": "",
            "server_port": 4455,
        }
        changed = True
    if config.get("server_enabled") is not True:
        config["server_enabled"] = True
        changed = True
    if "server_port" not in config:
        config["server_port"] = 4455
        changed = True
    if "auth_required" not in config:
        config["auth_required"] = bool(config.get("server_password"))
        changed = True
    if "alerts_enabled" not in config:
        config["alerts_enabled"] = False
        changed = True
    backup = write_json_with_backup(OBS_CONFIG, config) if changed else None
    return config, backup, changed


def reaper_audio_driver_summary() -> str:
    ini = REAPER_RESOURCE / "REAPER.ini"
    if not ini.exists():
        return "REAPER.ini not found"
    driver_name = ""
    audio_mode = ""
    for line in ini.read_text(encoding="utf-8", errors="ignore").splitlines():
        lower = line.lower()
        if lower.startswith("asio_driver_name="):
            driver_name = line.split("=", 1)[1].strip().strip('"')
        elif lower.startswith("audiothreadpr="):
            continue
        elif lower.startswith("audio") and "=" in line:
            audio_mode = line.strip()
    if driver_name:
        return f"ASIO driver: {driver_name}"
    return audio_mode or "audio driver not detected"


def reaper_has_reastream() -> bool:
    cache = REAPER_RESOURCE / "reaper-vstplugins64.ini"
    if not cache.exists():
        return False
    return "reastream" in cache.read_text(encoding="utf-8", errors="ignore").lower()


def obs_scene_reastream_filters() -> list[str]:
    filters: list[str] = []
    if not OBS_SCENES.exists():
        return filters
    for path in OBS_SCENES.glob("*.json"):
        try:
            data = read_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        collect_reastream_filters(data, path.name, filters)
    return filters


def collect_reastream_filters(node: Any, scene_name: str, filters: list[str], source_name: str = "") -> None:
    if isinstance(node, dict):
        current_source = source_name
        if "name" in node and "id" in node:
            current_source = str(node.get("name", source_name))
        for filter_data in node.get("filters", []) or []:
            settings = filter_data.get("settings", {})
            plugin_path = str(settings.get("plugin_path", ""))
            if "reastream" in plugin_path.lower():
                filters.append(
                    f"{scene_name}: source `{current_source}` filter `{filter_data.get('name')}` -> {plugin_path}"
                )
        for value in node.values():
            collect_reastream_filters(value, scene_name, filters, current_source)
    elif isinstance(node, list):
        for item in node:
            collect_reastream_filters(item, scene_name, filters, source_name)


@dataclass
class ObsConnectionConfig:
    host: str = "127.0.0.1"
    port: int = 4455
    password: str = ""

    @classmethod
    def from_obs_config(cls, config: dict[str, Any]) -> "ObsConnectionConfig":
        return cls(
            port=int(config.get("server_port") or 4455),
            password=str(config.get("server_password") or ""),
        )


class ObsWebSocketClient:
    def __init__(self, config: ObsConnectionConfig, timeout: float = 4.0) -> None:
        self.config = config
        self.timeout = timeout
        self.ws: Any = None

    def __enter__(self) -> "ObsWebSocketClient":
        self.connect()
        return self

    def __exit__(self, _exc_type: Any, _exc: Any, _tb: Any) -> None:
        self.close()

    def connect(self) -> None:
        try:
            import websocket
        except ImportError as exc:
            raise RuntimeError("Missing dependency: websocket-client. Run .\\run.ps1 once to install requirements.") from exc

        self.ws = websocket.create_connection(
            f"ws://{self.config.host}:{self.config.port}",
            timeout=self.timeout,
        )
        hello = self._recv_json()
        if hello.get("op") != 0:
            raise RuntimeError(f"OBS did not send Hello: {hello}")
        data = hello.get("d", {})
        identify: dict[str, Any] = {"rpcVersion": data.get("rpcVersion", 1)}
        auth = data.get("authentication")
        if auth:
            if not self.config.password:
                raise RuntimeError("OBS WebSocket requires a password, but no password was found in config.json.")
            identify["authentication"] = self._auth_string(
                self.config.password,
                str(auth.get("salt", "")),
                str(auth.get("challenge", "")),
            )
        self._send_json({"op": 1, "d": identify})
        identified = self._recv_json()
        if identified.get("op") != 2:
            raise RuntimeError(f"OBS did not identify the connection: {identified}")

    def close(self) -> None:
        if self.ws is not None:
            try:
                self.ws.close()
            finally:
                self.ws = None

    def request(self, request_type: str, request_data: dict[str, Any] | None = None) -> dict[str, Any]:
        if self.ws is None:
            raise RuntimeError("OBS WebSocket is not connected.")
        request_id = str(uuid.uuid4())
        self._send_json(
            {
                "op": 6,
                "d": {
                    "requestType": request_type,
                    "requestId": request_id,
                    "requestData": request_data or {},
                },
            }
        )
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            response = self._recv_json()
            if response.get("op") != 7:
                continue
            payload = response.get("d", {})
            if payload.get("requestId") != request_id:
                continue
            status = payload.get("requestStatus", {})
            if not status.get("result"):
                code = status.get("code", "?")
                comment = status.get("comment", "unknown error")
                raise RuntimeError(f"{request_type} failed ({code}): {comment}")
            return payload.get("responseData", {})
        raise RuntimeError(f"Timed out waiting for OBS response to {request_type}.")

    def _send_json(self, payload: dict[str, Any]) -> None:
        self.ws.send(json.dumps(payload))

    def _recv_json(self) -> dict[str, Any]:
        return json.loads(self.ws.recv())

    @staticmethod
    def _auth_string(password: str, salt: str, challenge: str) -> str:
        secret = base64.b64encode(hashlib.sha256((password + salt).encode("utf-8")).digest()).decode("ascii")
        return base64.b64encode(hashlib.sha256((secret + challenge).encode("utf-8")).digest()).decode("ascii")


class BridgeController:
    def __init__(self) -> None:
        self.obs_exe = find_obs_exe()
        self.reaper_exe = find_reaper_exe()

    def environment_report(self) -> list[str]:
        lines: list[str] = []
        lines.append(f"Workspace: {ROOT}")
        lines.append(f"OBS exe: {self.obs_exe or 'not found'}")
        lines.append(f"OBS running: {tasklist_contains('obs64.exe')}")
        _, config_lines = obs_websocket_config_summary()
        lines.extend(config_lines)
        lines.append(f"REAPER exe: {self.reaper_exe or 'not found'}")
        lines.append(f"REAPER running instances: {process_count('reaper.exe')}")
        lines.append(f"REAPER audio: {reaper_audio_driver_summary()}")
        lines.append(f"REAPER ReaStream cache: {'found' if reaper_has_reastream() else 'missing'}")
        lines.append(f"Standalone ReaStream VST: {find_reastream_vst() or 'not found'}")
        scene_filters = obs_scene_reastream_filters()
        if scene_filters:
            lines.append("OBS ReaStream VST filters:")
            lines.extend([f"  {entry}" for entry in scene_filters])
        else:
            lines.append("OBS ReaStream VST filters: not found in scene files")
        return lines

    def install_reaper_script(self) -> list[str]:
        if not REAPER_SCRIPT_SOURCE.exists():
            raise RuntimeError(f"Missing source script: {REAPER_SCRIPT_SOURCE}")
        target_dir = REAPER_RESOURCE / "Scripts"
        mirror_dir = target_dir / "Codex"
        target_dir.mkdir(parents=True, exist_ok=True)
        mirror_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / REAPER_SCRIPT_NAME
        mirror = mirror_dir / REAPER_SCRIPT_NAME
        shutil.copy2(REAPER_SCRIPT_SOURCE, target)
        shutil.copy2(REAPER_SCRIPT_SOURCE, mirror)
        return [
            f"Installed REAPER script: {target}",
            f"Mirrored REAPER script: {mirror}",
            "Run it once from REAPER Action List, or open it from the Scripts folder and load it as a ReaScript.",
        ]

    def enable_obs_websocket(self) -> list[str]:
        config, backup, changed = enable_obs_websocket_config()
        lines = [f"OBS WebSocket enabled in config: {OBS_CONFIG}"]
        if backup:
            lines.append(f"Backup: {backup}")
        if not changed:
            lines.append("No config change needed.")
        if tasklist_contains("obs64.exe"):
            lines.append("OBS is already running. If WebSocket was disabled before, restart OBS or enable it in Tools > WebSocket Server Settings.")
        lines.append(f"Port: {config.get('server_port', 4455)}")
        lines.append(f"Auth required: {config.get('auth_required')}")
        return lines

    def launch_obs(self) -> list[str]:
        if tasklist_contains("obs64.exe"):
            return ["OBS is already running."]
        if not self.obs_exe:
            raise RuntimeError("OBS executable was not found.")
        subprocess.Popen([str(self.obs_exe)], cwd=str(self.obs_exe.parent))
        return [f"Launched OBS: {self.obs_exe}"]

    def launch_reaper(self) -> list[str]:
        if tasklist_contains("reaper.exe"):
            return ["REAPER is already running."]
        if not self.reaper_exe:
            raise RuntimeError("REAPER executable was not found.")
        subprocess.Popen([str(self.reaper_exe)], cwd=str(self.reaper_exe.parent))
        return [f"Launched REAPER: {self.reaper_exe}"]

    def wait_for_obs(self, seconds: float = 12.0) -> None:
        deadline = time.time() + seconds
        while time.time() < deadline:
            if tasklist_contains("obs64.exe"):
                return
            time.sleep(0.35)
        raise RuntimeError("OBS did not appear in the process list.")

    def start_recording(self) -> list[str]:
        config = read_json(OBS_CONFIG)
        client_config = ObsConnectionConfig.from_obs_config(config)
        with ObsWebSocketClient(client_config) as obs:
            version = obs.request("GetVersion")
            status = obs.request("GetRecordStatus")
            lines = [f"Connected to OBS {version.get('obsVersion', 'unknown')}."]
            if status.get("outputActive"):
                lines.append("OBS is already recording.")
                return lines
            obs.request("StartRecord")
            lines.append("OBS recording started.")
            return lines

    def stop_recording(self) -> list[str]:
        config = read_json(OBS_CONFIG)
        client_config = ObsConnectionConfig.from_obs_config(config)
        with ObsWebSocketClient(client_config) as obs:
            status = obs.request("GetRecordStatus")
            if not status.get("outputActive"):
                return ["OBS is not recording."]
            response = obs.request("StopRecord")
            output_path = response.get("outputPath")
            lines = ["OBS recording stopped."]
            if output_path:
                lines.append(f"Output: {output_path}")
            return lines

    def one_click_capture(self) -> list[str]:
        lines: list[str] = []
        lines.extend(self.enable_obs_websocket())
        lines.extend(self.install_reaper_script())
        if not tasklist_contains("reaper.exe"):
            lines.extend(self.launch_reaper())
        lines.extend(self.launch_obs())
        self.wait_for_obs()
        lines.append("Waiting for OBS WebSocket...")
        last_error: Exception | None = None
        for _ in range(16):
            try:
                lines.extend(self.start_recording())
                lines.append("Capture path is active if REAPER Master ReaStream Send and OBS ReaStream Receive use the same identifier.")
                return lines
            except Exception as exc:  # noqa: BLE001 - shown to the user as setup guidance.
                last_error = exc
                time.sleep(0.75)
        raise RuntimeError(
            "Could not connect to OBS WebSocket. "
            "If OBS was already open with WebSocket disabled, restart OBS or enable Tools > WebSocket Server Settings, then click again. "
            f"Last error: {last_error}"
        )


class BridgeWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.controller = BridgeController()
        self.setWindowTitle("Codex OBS/Reaper Bridge")
        self.resize(900, 620)

        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        self.status = QLabel("OBS/Reaper audio bridge")
        self.status.setAlignment(Qt.AlignLeft)
        layout.addWidget(self.status)

        button_row = QHBoxLayout()
        buttons = [
            ("检查环境", self.check_environment),
            ("启用 OBS WebSocket", self.enable_obs_websocket),
            ("安装 REAPER 路由脚本", self.install_reaper_script),
            ("打开 OBS", self.launch_obs),
            ("一键抓取", self.one_click_capture),
            ("停止录制", self.stop_recording),
        ]
        for label, handler in buttons:
            button = QPushButton(label)
            button.clicked.connect(handler)
            button_row.addWidget(button)
        layout.addLayout(button_row)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Bridge status and setup notes will appear here.")
        layout.addWidget(self.log, 1)

        hint = QLabel(
            "推荐线路：REAPER Master ReaStream Send -> OBS ReaStream VST Receive -> OBS Record. "
            "第一次需要在 REAPER/OBS 的 ReaStream 窗口确认 Send/Receive 和同一个 Identifier。"
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.setCentralWidget(root)
        self.check_environment()

    def append_lines(self, lines: list[str]) -> None:
        self.log.append("\n".join(lines))
        self.log.append("")

    def run_action(self, label: str, action: Any) -> None:
        self.status.setText(label)
        QApplication.processEvents()
        try:
            lines = action()
        except Exception as exc:  # noqa: BLE001 - GUI boundary.
            self.append_lines([f"ERROR: {exc}"])
            QMessageBox.warning(self, "OBS/Reaper Bridge", str(exc))
        else:
            self.append_lines(lines)
        finally:
            self.status.setText("Ready")

    def check_environment(self) -> None:
        self.run_action("Checking environment...", self.controller.environment_report)

    def enable_obs_websocket(self) -> None:
        self.run_action("Enabling OBS WebSocket...", self.controller.enable_obs_websocket)

    def install_reaper_script(self) -> None:
        self.run_action("Installing REAPER route script...", self.controller.install_reaper_script)

    def launch_obs(self) -> None:
        self.run_action("Launching OBS...", self.controller.launch_obs)

    def one_click_capture(self) -> None:
        self.run_action("Starting one-click capture...", self.controller.one_click_capture)

    def stop_recording(self) -> None:
        self.run_action("Stopping OBS recording...", self.controller.stop_recording)


def main() -> int:
    app = QApplication(sys.argv)
    window = BridgeWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
