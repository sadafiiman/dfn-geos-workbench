@echo off
REM Double-click this file to set up the dfnWorks -> GEOS Workbench on Windows.
REM Arguments are passed through, e.g.:  setup_windows.cmd -WithGeos
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_windows.ps1" %*
if errorlevel 1 (
    echo.
    echo Setup did not finish. Read the message above, fix it, then run this file again.
    pause
    exit /b 1
)
echo.
pause
