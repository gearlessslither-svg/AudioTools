@echo off
setlocal
title ProjectEF Audio Identity Overlay Map Export

set "SCRIPT=G:\AI\Material\Wwise\Tools\export_projectef_audio_identity_map.py"
set "UNITY_PROJECT=D:\EF New\Client\TargetProject"

if not exist "%SCRIPT%" (
  echo Missing script:
  echo %SCRIPT%
  pause
  exit /b 1
)

python "%SCRIPT%" --unity-project "%UNITY_PROJECT%" --open
echo.
echo Done. In Unity, use menu:
echo ProjectEF/Audio/Resource Name Overlay/Settings
echo.
pause
endlocal
