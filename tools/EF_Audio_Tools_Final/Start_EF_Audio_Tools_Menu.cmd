@echo off
chcp 65001 >nul
setlocal

:menu
cls
echo ===============================================
echo EF Audio Tools Final
echo ===============================================
echo.
echo Main manual tools
echo 1. Sound Finder for Reaper
echo 2. Unity/Wwise Log Monitor GUI
echo 3. Open Report Dashboard
echo 4. Wwise Template Generator
echo 5. Wwise Profiler Voice Capture
echo 6. P4V Changelist Organizer GUI
echo 7. UI Audio Static Inspector GUI
echo 8. Animation Wwise Event AutoConfig GUI
echo 9. Audio Requirement Jira Triage GUI
echo.
echo A. Advanced / hidden report and maintenance tools
echo Q. Quit
echo.
set /p CHOICE=Choose a tool: 

if /I "%CHOICE%"=="1" call "%~dp0\01_Sound_Finder_for_Reaper.cmd" & goto menu
if /I "%CHOICE%"=="2" call "%~dp0\02_UnityWwise_Log_Monitor_GUI.cmd" & goto menu
if /I "%CHOICE%"=="3" call "%~dp0\06_Open_Report_Dashboard.cmd" & goto menu
if /I "%CHOICE%"=="4" call "%~dp0\08_Wwise_Template_Generator.cmd" & goto menu
if /I "%CHOICE%"=="5" call "%~dp0\17_Wwise_Profiler_Voice_Capture.cmd" & goto menu
if /I "%CHOICE%"=="6" call "%~dp0\19_P4V_Changelist_Organizer_GUI.cmd" & goto menu
if /I "%CHOICE%"=="7" call "%~dp0\20_UIAudio_StaticInspector_GUI.cmd" & goto menu
if /I "%CHOICE%"=="8" call "%~dp0\21_Animation_Wwise_Event_AutoConfig.cmd" & goto menu
if /I "%CHOICE%"=="9" call "%~dp0\22_AudioRequirement_Jira_Triage_GUI.cmd" & goto menu
if /I "%CHOICE%"=="A" goto advanced
if /I "%CHOICE%"=="Q" exit /b 0

echo.
echo Unknown choice.
pause
goto menu

:advanced
cls
echo ===============================================
echo EF Audio Tools Advanced / Hidden
echo ===============================================
echo.
echo Report generators
echo 1. AI Work Impact - Week
echo 2. AI Work Impact - Month
echo 3. Audio Report Trend - Once
echo 4. Daily Log Intelligence
echo 5. Audio Report Trend - Watch 3h
echo.
echo Legacy runtime helpers
echo 6. Runtime Audio Follow - Visible
echo 7. Runtime Audio Follow - Minimized
echo 8. Stop Runtime Audio Follow
echo.
echo Scheduled task maintenance
echo 9. Register Audio Trend Scheduled Task
echo 10. Unregister Audio Trend Scheduled Task
echo 11. Register Daily Log Scheduled Task
echo 12. Unregister Daily Log Scheduled Task
echo.
echo P4 read-only report
echo 13. P4V Audio Changelist Check
echo.
echo Requirement monitoring
echo 14. Audio Requirement Scan Diff - Once
echo 15. Register Audio Requirement Scheduled Task
echo 16. Unregister Audio Requirement Scheduled Task
echo.
echo B. Back
echo Q. Quit
echo.
set /p ADV_CHOICE=Choose an advanced tool: 

if /I "%ADV_CHOICE%"=="1" call "%~dp0\03_AI_Work_Impact_Week.cmd" & goto advanced
if /I "%ADV_CHOICE%"=="2" call "%~dp0\04_AI_Work_Impact_Month.cmd" & goto advanced
if /I "%ADV_CHOICE%"=="3" call "%~dp0\05_Audio_Report_Trend_Once.cmd" & goto advanced
if /I "%ADV_CHOICE%"=="4" call "%~dp0\07_Daily_Log_Intelligence.cmd" & goto advanced
if /I "%ADV_CHOICE%"=="5" call "%~dp0\09_Audio_Report_Trend_Watch_3h.cmd" & goto advanced
if /I "%ADV_CHOICE%"=="6" call "%~dp0\10_Runtime_Audio_Follow_Visible.cmd" & goto advanced
if /I "%ADV_CHOICE%"=="7" call "%~dp0\11_Runtime_Audio_Follow_Minimized.cmd" & goto advanced
if /I "%ADV_CHOICE%"=="8" call "%~dp0\12_Runtime_Audio_Follow_Stop.cmd" & goto advanced
if /I "%ADV_CHOICE%"=="9" call "%~dp0\13_Register_Audio_Trend_Task.cmd" & goto advanced
if /I "%ADV_CHOICE%"=="10" call "%~dp0\14_Unregister_Audio_Trend_Task.cmd" & goto advanced
if /I "%ADV_CHOICE%"=="11" call "%~dp0\15_Register_Daily_Log_Task.cmd" & goto advanced
if /I "%ADV_CHOICE%"=="12" call "%~dp0\16_Unregister_Daily_Log_Task.cmd" & goto advanced
if /I "%ADV_CHOICE%"=="13" call "%~dp0\18_P4V_Audio_Changelist_Check.cmd" & goto advanced
if /I "%ADV_CHOICE%"=="14" call "%~dp0\23_AudioRequirement_ScanDiff_Once.cmd" & goto advanced
if /I "%ADV_CHOICE%"=="15" call "%~dp0\24_Register_AudioRequirement_Task.cmd" & goto advanced
if /I "%ADV_CHOICE%"=="16" call "%~dp0\25_Unregister_AudioRequirement_Task.cmd" & goto advanced
if /I "%ADV_CHOICE%"=="B" goto menu
if /I "%ADV_CHOICE%"=="Q" exit /b 0

echo.
echo Unknown choice.
pause
goto advanced
