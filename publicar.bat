@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================================
echo   PUBLICAR ACTUALIZACION - Editor de Fotos DISECOD
echo ============================================================
echo.

set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not exist "%PY%" set "PY=python"

"%PY%" publicar.py
echo.
pause
