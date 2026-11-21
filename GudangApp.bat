@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

if not exist .venv (
  py -3.12 -m venv .venv || python -m venv .venv
)
call .venv\Scripts\activate.bat

pip install --quiet -r requirements.txt
python -m app.core.prestart
alembic upgrade head
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
endlocal
