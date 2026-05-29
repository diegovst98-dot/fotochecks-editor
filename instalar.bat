@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================================
echo   INSTALADOR - Editor de fotos fotochecks DISECOD
echo ============================================================
echo.

rem --- Buscar Python ---
set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not exist "%PY%" set "PY=python"

"%PY%" --version >nul 2>&1
if errorlevel 1 (
  echo  [!] No se encontro Python en esta PC.
  echo      Instala Python 3.12 desde https://www.python.org/downloads/
  echo      IMPORTANTE: marca la casilla "Add python.exe to PATH" al instalar.
  echo      Luego vuelve a ejecutar este instalar.bat
  echo.
  pause
  exit /b
)

echo  Python encontrado:
"%PY%" --version
echo.
echo  Instalando librerias (necesita internet, solo esta vez)...
echo.
"%PY%" -m pip install --upgrade pip
"%PY%" -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo  [!] Hubo un error instalando las librerias. Revisa la conexion a internet.
  pause
  exit /b
)

rem --- Dejar el modelo de IA en su lugar para que no lo descargue ---
if exist "modelo\u2net_human_seg.onnx" (
  if not exist "%USERPROFILE%\.u2net" mkdir "%USERPROFILE%\.u2net"
  copy /Y "modelo\u2net_human_seg.onnx" "%USERPROFILE%\.u2net\u2net_human_seg.onnx" >nul
  echo  Modelo de IA instalado.
)

echo.
echo ============================================================
echo   LISTO. Ya puedes usar el programa:
echo   1) Pon las fotos en la carpeta "entrada"
echo   2) Doble clic en "procesar.bat"
echo   3) Los resultados salen en la carpeta "salida"
echo ============================================================
echo.
pause
