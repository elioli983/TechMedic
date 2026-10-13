@echo off
setlocal
cd /d "%~dp0"
echo TechMedic v1.5.6 DEVELOPMENT / EVALUATION - OFFLINE synthetic mode.
echo No live OpenAI/Jev calls.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\launch_windows.ps1"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" pause
exit /b %RC%
