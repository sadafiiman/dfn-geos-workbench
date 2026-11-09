@echo off
REM Start the panel after setup has been done once.
REM Optional first argument is the port (default 8765):  start_windows.cmd 9000
setlocal
cd /d "%~dp0"

set "PORT=%~1"
if "%PORT%"=="" set "PORT=8765"

set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY (
    where py >nul 2>nul && set "PY=py -3"
)
if not defined PY (
    echo Python was not found. Run setup_windows.cmd first.
    pause
    exit /b 1
)

echo Starting the panel on http://localhost:%PORT% ...
start "" /min cmd /c "timeout /t 3 >nul & start http://localhost:%PORT%"
%PY% run_panel.py --port %PORT%
