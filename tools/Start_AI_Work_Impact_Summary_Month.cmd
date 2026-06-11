@echo off
setlocal
set "SCRIPT=%USERPROFILE%\.codex\skills\ai-work-impact-ledger\scripts\ai_work_impact_ledger.py"
set "LEDGER=G:\AI\Material\Wwise\AI_Work_Impact_Ledger.csv"
set "OUT_MD=G:\AI\Material\Wwise\AI_Work_Impact_Summary_Month.md"
set "OUT_JSON=G:\AI\Material\Wwise\AI_Work_Impact_Summary_Month.json"

python "%SCRIPT%" --ledger "%LEDGER%" --period month --out-md "%OUT_MD%" --out-json "%OUT_JSON%"
pause
