@echo off
setlocal
cd /d "%~dp0"
echo ==========================================================
echo TechMedic v1.5.6 - DEVELOPMENT / EVALUATION INSTALL
 echo This is a separate application; v1.5.5 is unchanged.
echo ==========================================================
if not exist ".venv\Scripts\python.exe" (
    where py >nul 2>nul
    if not errorlevel 1 (
        py -3.14 -m venv .venv
        if errorlevel 1 py -3 -m venv .venv
    ) else (
        python -m venv .venv
    )
    if errorlevel 1 goto failed
)
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check --only-binary=sqlcipher3-wheels -r requirements.txt
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -c "from sqlcipher3 import dbapi2 as db; c=db.connect(':memory:'); assert c.execute('PRAGMA cipher_version').fetchone(); c.close()"
if errorlevel 1 goto failed
if not exist ".env" copy /Y ".env.example" ".env" >nul
if not exist "data" mkdir "data"
echo.
echo INSTALL COMPLETE. No API keys required for offline demo.
echo Double-click START_TECHMEDIC.bat to run synthetic mode.
echo For OPTIONAL live services, see USER_MANUAL.md.
pause
exit /b 0
:failed
echo.
echo Setup failed; no changes made to the v1.5.5 installation.
pause
exit /b 1
