@echo off
cd /d "%~dp0"
set PYTHONDONTWRITEBYTECODE=1
python -B ProjectEF_Wwise_Template_Generator_GUI.py
pause
