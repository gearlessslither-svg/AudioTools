# Mullvad Speed Guard Windows Port Notes

## 本地位置

工具已经放在：

```text
G:\AI\Material\Wwise\Tools\mullvad-speed-guard
```

## 可以直接复用的代码

- `mullvad_speed_guard.py` 的核心逻辑可复用：读取 `mullvad` CLI、解析 relay 列表、筛选候选、连接指定 relay、测速、健康检查和 watch 循环。
- `relay_inventory.py` 的 SQLite relay 库存、fast-rank、true-test pool、白名单排序和 auto-guard 恢复策略可复用。
- `guard_panel_server.py` 的本地 Web 控制面板和 API 结构可复用。
- `guard_gui.py` 与 `traffic_float_widget.py` 的 Tk 界面可复用，Windows 自带 Tk 的 Python 通常可以直接跑。
- `config.example.json` 的配置结构可复用。

## macOS 专用或不建议复用的部分

- `launchagents/*.plist`、`install_*.sh`、`uninstall_*.sh` 是 macOS LaunchAgent 体系，不适合 Windows。
- `launcher.applescript` 和 `traffic_float_widget.swift` 是 macOS 专用。
- 原来的 `open`、`launchctl`、`pkill`、`ps`、`netstat -ibn`、`ioreg` 调用都不能直接用于 Windows。

## Windows 改造内容

- 新增 `platform_compat.py`，集中处理 Windows/macOS 差异。
- Windows 运行目录改为 `%LOCALAPPDATA%\MullvadSpeedGuard`。
- Python 入口改为当前解释器 `sys.executable`，不再硬编码 `/usr/bin/python3`。
- Web 面板的 Auto Guard 按钮会注册 Windows Task Scheduler 登录任务，并启动当前 detached 守护进程。
- VPN 流量统计在 Windows 使用 PowerShell `Get-NetAdapterStatistics`，并优先匹配 Mullvad/WireGuard/Wintun 网卡。
- 用户空闲检测在 Windows 使用 `GetLastInputInfo`。
- URL 探针的 curl 输出改为 `os.devnull`，Windows 下会走 `NUL`。
- 进程检测/停止在 Windows 使用 PowerShell CIM 和 `taskkill`。

## 公司环境安全加固

- Web 面板只绑定 `127.0.0.1` 和 `::1`，不会监听公网网卡。
- Web 面板会拒绝非 `localhost`、`127.0.0.1`、`[::1]` 的 Host header，降低 DNS rebinding 风险。
- `/api/state`、`/api/latency` 和所有 POST 管理接口都要求 `X-MSG-Token`。token 自动生成在 `results\panel_api_token.txt`，也可通过环境变量 `MSG_PANEL_API_TOKEN` 指定。
- `/api/ping` 保持无 token，用于本地健康检查，但它只返回版本和 ok 状态。
- POST 请求体限制为 64 KB。
- 手动连接 relay 的 hostname 使用 `[a-z0-9-]` 白名单校验。
- 所有 Mullvad 调用使用 `subprocess` 参数数组，不把浏览器传入的值拼进 shell 命令。
- 不保存 Mullvad 账号、密码、真实 IP、浏览记录或访问内容；流量小窗只读取网卡字节计数。
- Auto Guard 默认启用公司工作安全模式：只要 VPN 仍是 Connected，就不自动断链、不自动切 relay、不做会切换 relay 的真测；只有 VPN 已经 Disconnected/Connecting 超过宽限时间时才立即恢复连接。
- 默认不做主动下载测速：`speed_check_every_seconds=0`，`active_speed_when_passive_idle=false`。自动监控只做状态、URL、延迟和被动流量判断。
- 面板里的 `Allow active switching` 默认不勾。勾上后才允许 Auto Guard 在你正在工作时主动切换、真测 relay，并允许主动下载测速。
- 旧 `watch` 命令也受工作安全模式约束：VPN 仍是 Connected 时不会因为慢速或 URL 抖动直接触发 relay scan/reconnect；需要主动切换时显式加 `--allow-active-switching`。

仍需注意：本机管理员、本机恶意进程、已能读取项目目录的进程，可以读取 token 或直接运行 Python 脚本。这个工具的安全边界是“防外部网页和非本机网络访问本地管理口”，不是防本机已沦陷。

## Windows 使用方式

先确认 Python 3 和 Mullvad VPN 已安装，并且命令行能运行：

```powershell
python --version
mullvad --version
```

启动 Web 面板：

```powershell
.\Start_Mullvad_Speed_Guard_Panel.cmd
```

或者直接：

```powershell
python .\guard_panel_server.py --port 18790
```

打开：

```text
http://127.0.0.1:18790/
```

注册 Auto Guard 登录任务：

```powershell
powershell -ExecutionPolicy Bypass -File .\install_auto_guard_windows.ps1
```

卸载 Auto Guard 登录任务：

```powershell
powershell -ExecutionPolicy Bypass -File .\uninstall_auto_guard_windows.ps1
```

注册面板登录启动：

```powershell
powershell -ExecutionPolicy Bypass -File .\install_panel_windows.ps1
```

基础自检：

```powershell
python .\mullvad_speed_guard.py doctor
```

只预览候选节点，不切换 VPN：

```powershell
python .\mullvad_speed_guard.py scan --dry-run --countries hk,jp,sg,us --max-candidates 20
```

启动浮动流量小窗：

```powershell
.\Start_Mullvad_Speed_Guard_Float_Widget.cmd
```
