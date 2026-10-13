@echo off
setlocal
cd /d "%~dp0"
echo TechMedic v1.5.6 - OPTIONAL LIVE OpenAI/Jev service mode.
echo API credits/charges may apply. Use only fictional inputs.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\launch_windows.ps1" -Live
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" pause
exit /b %RC%
