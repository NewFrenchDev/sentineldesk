@echo off
REM SentinelDesk Launcher for Windows
REM Double-click this file to run SentinelDesk

echo.
echo ========================================
echo   SENTINELDESK - Local EDR
echo ========================================
echo.
echo Starting SentinelDesk...
echo.

python -m sentineldesk

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ERROR: Failed to start SentinelDesk
    echo.
    echo Make sure you have:
    echo   - Python 3.10+ installed
    echo   - PySide6 installed: pip install PySide6
    echo   - psutil installed:  pip install psutil
    echo.
    pause
)
