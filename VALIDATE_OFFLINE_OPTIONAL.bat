@echo off
setlocal
cd /d "%~dp0"
echo Optional: v1.5.6 offline self-validation. Not required for setup.
if not exist ".venv\Scripts\python.exe" (echo Run INSTALL_WINDOWS.bat first.& exit /b 2)
".venv\Scripts\python.exe" -B run_release_offline_validation.py
exit /b %ERRORLEVEL%
