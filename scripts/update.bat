@echo off
setlocal
cd /d "%~dp0.."

echo [gudang] stopping running instance (if any)...
taskkill /F /IM python.exe /FI "WINDOWTITLE eq GudangApp*" >nul 2>&1

echo [gudang] pulling updates...
git pull --ff-only
if errorlevel 1 (
  echo [gudang] git pull failed - aborting.
  pause
  exit /b 1
)

call .venv\Scripts\activate.bat
pip install --quiet -r requirements.txt
alembic upgrade head
if errorlevel 1 (
  echo [gudang] migration failed - aborting.
  pause
  exit /b 1
)

echo [gudang] restarting...
start "" "%~dp0..\GudangApp.bat"
endlocal
