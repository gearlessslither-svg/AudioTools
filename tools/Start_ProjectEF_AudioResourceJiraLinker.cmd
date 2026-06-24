@echo off
setlocal
cd /d "%~dp0"
python "%~dp0ProjectEF_AudioResourceJiraLinker.py" --use-action-index --p4-max-changes 500 --p4-describe-limit 500 --p4-since 2026/06/01 --min-score 45 --max-links-per-resource 5
pause
