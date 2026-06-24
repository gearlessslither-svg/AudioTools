"""Small platform helpers for Mullvad Speed Guard."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


IS_WINDOWS = os.name == "nt"

WINDOWS_AUTO_GUARD_TASK_NAME = "MullvadSpeedGuardAutoGuard"
WINDOWS_PANEL_TASK_NAME = "MullvadSpeedGuardPanel"


def runtime_dir() -> Path:
    if IS_WINDOWS:
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "MullvadSpeedGuard"
        return Path.home() / "AppData" / "Local" / "MullvadSpeedGuard"
    return Path.home() / "Library" / "Application Support" / "MullvadSpeedGuard"


def supervisor_labels() -> List[str]:
    if IS_WINDOWS:
        return [WINDOWS_AUTO_GUARD_TASK_NAME, WINDOWS_PANEL_TASK_NAME]
    return [
        "com.story.mullvad-speed-guard.auto-guard",
        "com.story.mullvad-speed-guard.panel",
        "com.story.mullvad-speed-guard.float-widget",
    ]


def python_executable() -> str:
    return sys.executable or "python"


def default_path() -> str:
    if IS_WINDOWS:
        return os.environ.get("PATH", "")
    return "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"


def command_env(extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    env = os.environ.copy()
    path = default_path()
    if path:
        env["PATH"] = path
    env["PYTHONUNBUFFERED"] = "1"
    if extra:
        env.update(extra)
    return env


def background_popen_kwargs() -> Dict[str, Any]:
    if IS_WINDOWS:
        flags = 0
        flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        flags |= getattr(subprocess, "DETACHED_PROCESS", 0)
        return {"creationflags": flags}
    return {"start_new_session": True}


def run_powershell(script: str, timeout: float = 5) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=timeout,
    )


def process_alive(pid: Optional[int]) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError):
        return False


def process_command_line(pid: Optional[int]) -> str:
    if not pid:
        return ""
    if IS_WINDOWS:
        try:
            proc = run_powershell(
                "$p = Get-CimInstance Win32_Process -Filter 'ProcessId = "
                + str(int(pid))
                + "' -ErrorAction SilentlyContinue; if ($p) { $p.CommandLine }",
                timeout=1.5,
            )
            return (proc.stdout or "").strip()
        except Exception:
            return ""
    try:
        proc = subprocess.run(
            ["ps", "-p", str(int(pid)), "-o", "stat=", "-o", "command="],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=0.35,
        )
    except Exception:
        return ""
    if proc.returncode != 0:
        return ""
    line = proc.stdout.strip()
    if not line or line.startswith("Z"):
        return ""
    return line


def pid_running(pid: Optional[int], needle: str) -> bool:
    line = process_command_line(pid)
    return bool(line and needle in line)


def terminate_process_tree(pid: Optional[int]) -> bool:
    if not pid:
        return False
    pid = int(pid)
    if IS_WINDOWS:
        try:
            proc = subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
            return proc.returncode == 0
        except Exception:
            return False
    try:
        os.killpg(pid, 15)
        return True
    except OSError:
        try:
            os.kill(pid, 15)
            return True
        except OSError:
            return False


def kill_processes_matching(patterns: Sequence[str]) -> None:
    if IS_WINDOWS:
        for pattern in patterns:
            escaped = str(pattern).replace("`", "``").replace("'", "''")
            script = (
                "$me = $PID; "
                "Get-CimInstance Win32_Process | "
                f"Where-Object {{ $_.ProcessId -ne $me -and $_.CommandLine -like '*{escaped}*' }} | "
                "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
            )
            try:
                run_powershell(script, timeout=3)
            except Exception:
                pass
        return
    for pattern in patterns:
        try:
            subprocess.run(
                ["pkill", "-f", pattern],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=2,
            )
        except Exception:
            pass


def open_path_or_url(target: str) -> None:
    if IS_WINDOWS:
        os.startfile(target)  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["open", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def nudge_mullvad_app() -> Optional[str]:
    if IS_WINDOWS:
        errors: List[str] = []
        try:
            proc = subprocess.run(
                ["sc", "start", "MullvadVPN"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=5,
            )
            output = (proc.stdout or "").strip()
            if proc.returncode == 0 or "already" in output.lower() or "1056" in output:
                return None
            if output:
                errors.append(output)
        except Exception as exc:
            errors.append(str(exc))

        candidates = [
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Mullvad VPN" / "Mullvad VPN.exe",
            Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Mullvad VPN" / "Mullvad VPN.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Mullvad VPN" / "Mullvad VPN.exe",
        ]
        for candidate in candidates:
            if candidate.exists():
                try:
                    subprocess.Popen([str(candidate)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    return None
                except Exception as exc:
                    errors.append(str(exc))
        return "; ".join(errors) or "Mullvad VPN executable not found"

    try:
        proc = subprocess.run(
            ["open", "-gj", "-a", "Mullvad VPN"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )
    except Exception as exc:
        return str(exc)
    if proc.returncode == 0:
        return None
    return (proc.stderr or proc.stdout or "open Mullvad VPN failed").strip()


def interface_counters(interface: str) -> Dict[str, Any]:
    if IS_WINDOWS:
        return windows_interface_counters(interface)
    return posix_interface_counters(interface)


def posix_interface_counters(interface: str) -> Dict[str, Any]:
    try:
        proc = subprocess.run(
            ["netstat", "-ibn"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=2,
        )
    except Exception as exc:
        return {"ok": False, "interface": interface, "download_bytes": None, "upload_bytes": None, "error": str(exc)}

    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) < 9 or parts[0] != interface or not parts[2].startswith("<Link#"):
            continue
        try:
            if len(parts) >= 11:
                download_bytes = int(parts[6])
                upload_bytes = int(parts[9])
            else:
                download_bytes = int(parts[5])
                upload_bytes = int(parts[8])
        except (ValueError, IndexError):
            break
        return {
            "ok": True,
            "interface": interface,
            "download_bytes": download_bytes,
            "upload_bytes": upload_bytes,
        }
    return {"ok": False, "interface": interface, "download_bytes": None, "upload_bytes": None}


def windows_interface_counters(interface: str) -> Dict[str, Any]:
    safe_interface = interface.replace("'", "''")
    script = f"""
$name = '{safe_interface}'
$adapter = Get-NetAdapter -Name $name -ErrorAction SilentlyContinue
if (-not $adapter) {{
  $adapter = Get-NetAdapter -ErrorAction SilentlyContinue |
    Where-Object {{ $_.Name -eq $name -or $_.Name -like '*Mullvad*' -or $_.InterfaceDescription -like '*Mullvad*' -or $_.InterfaceDescription -like '*WireGuard*' -or $_.InterfaceDescription -like '*Wintun*' }} |
    Select-Object -First 1
}}
if (-not $adapter) {{ exit 2 }}
$stats = Get-NetAdapterStatistics -Name $adapter.Name -ErrorAction SilentlyContinue
if (-not $stats) {{ exit 3 }}
[PSCustomObject]@{{
  Name = $adapter.Name
  ReceivedBytes = [Int64]$stats.ReceivedBytes
  SentBytes = [Int64]$stats.SentBytes
}} | ConvertTo-Json -Compress
"""
    try:
        proc = run_powershell(script, timeout=3)
    except Exception as exc:
        return {"ok": False, "interface": interface, "download_bytes": None, "upload_bytes": None, "error": str(exc)}
    if proc.returncode != 0:
        return {
            "ok": False,
            "interface": interface,
            "download_bytes": None,
            "upload_bytes": None,
            "error": (proc.stdout or f"PowerShell exit {proc.returncode}").strip(),
        }
    try:
        payload = json.loads(proc.stdout.strip())
        return {
            "ok": True,
            "interface": str(payload.get("Name") or interface),
            "download_bytes": int(payload.get("ReceivedBytes") or 0),
            "upload_bytes": int(payload.get("SentBytes") or 0),
        }
    except Exception as exc:
        return {
            "ok": False,
            "interface": interface,
            "download_bytes": None,
            "upload_bytes": None,
            "error": f"cannot parse adapter counters: {exc}",
        }


def user_idle_seconds() -> Optional[float]:
    if IS_WINDOWS:
        try:
            import ctypes
            from ctypes import wintypes

            class LASTINPUTINFO(ctypes.Structure):
                _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

            info = LASTINPUTINFO()
            info.cbSize = ctypes.sizeof(info)
            if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
                return None
            tick_count = ctypes.windll.kernel32.GetTickCount()
            elapsed_ms = (int(tick_count) - int(info.dwTime)) & 0xFFFFFFFF
            return elapsed_ms / 1000.0
        except Exception:
            return None

    try:
        proc = subprocess.run(
            ["ioreg", "-c", "IOHIDSystem"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=3,
        )
    except Exception:
        return None
    for line in proc.stdout.splitlines():
        if "HIDIdleTime" in line:
            try:
                return int(line.split("=")[-1].strip()) / 1_000_000_000
            except ValueError:
                return None
    return None


def scheduled_task_status(task_name: str) -> Dict[str, Any]:
    if not IS_WINDOWS:
        return {"loaded": False, "running": False, "pid": None, "state": "unsupported", "error": None}
    safe_name = task_name.replace("'", "''")
    script = f"""
$task = Get-ScheduledTask -TaskName '{safe_name}' -ErrorAction SilentlyContinue
if (-not $task) {{ exit 1 }}
[PSCustomObject]@{{
  TaskName = $task.TaskName
  State = [string]$task.State
}} | ConvertTo-Json -Compress
"""
    try:
        proc = run_powershell(script, timeout=3)
    except Exception as exc:
        return {"loaded": False, "running": False, "pid": None, "state": "unknown", "error": str(exc)}
    if proc.returncode != 0:
        return {"loaded": False, "running": False, "pid": None, "state": "not registered", "error": proc.stdout.strip()}
    try:
        payload = json.loads(proc.stdout.strip())
        state = str(payload.get("State") or "unknown")
    except Exception:
        state = "unknown"
    return {
        "loaded": True,
        "running": state.lower() == "running",
        "pid": None,
        "state": state,
        "error": None,
    }


def create_logon_task(task_name: str, target_cmd: str) -> None:
    """Register a per-user ONLOGON task that runs ``target_cmd`` via cmd.exe.

    ``target_cmd`` is the path to the ``.cmd`` launcher (no ``cmd.exe`` prefix,
    no surrounding quotes).

    schtasks.exe mis-parses ``/TR`` values that contain embedded quotes, which
    is the classic "exit status 1" failure when registering a cmd.exe launcher
    whose path could contain spaces. Register through the Task Scheduler API via
    PowerShell instead, and pass the values through the environment + a base64
    -EncodedCommand so no shell-quoting of the path is involved at any layer.
    """
    script = (
        "$ErrorActionPreference='Stop';"
        "$a=New-ScheduledTaskAction -Execute $env:ComSpec "
        "-Argument ('/c \"' + $env:MSG_TASK_TARGET + '\"');"
        "$t=New-ScheduledTaskTrigger -AtLogOn;"
        "$s=New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries "
        "-DontStopIfGoingOnBatteries -StartWhenAvailable;"
        "$p=New-ScheduledTaskPrincipal -UserId $env:USERNAME "
        "-LogonType Interactive -RunLevel Limited;"
        "Register-ScheduledTask -TaskName $env:MSG_TASK_NAME -Action $a "
        "-Trigger $t -Settings $s -Principal $p -Force | Out-Null"
    )
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    env = command_env({"MSG_TASK_NAME": task_name, "MSG_TASK_TARGET": target_cmd})
    subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-EncodedCommand",
            encoded,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=20,
        check=True,
        env=env,
    )


def run_scheduled_task(task_name: str) -> None:
    subprocess.run(
        ["schtasks", "/Run", "/TN", task_name],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=10,
        check=True,
    )


def delete_scheduled_task(task_name: str) -> None:
    subprocess.run(
        ["schtasks", "/Delete", "/TN", task_name, "/F"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=5,
    )
