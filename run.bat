@echo off
rem Run the FTTH Planner locally at http://127.0.0.1:8000 (first run installs dependencies)
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Creating virtual environment...
  python -m venv .venv || goto :error
)
.venv\Scripts\python -m pip install -q -r requirements.txt || goto :error
.venv\Scripts\python manage.py migrate --noinput || goto :error
.venv\Scripts\python -c "import os,django;os.environ.setdefault('DJANGO_SETTINGS_MODULE','planner_site.settings');django.setup();from django.contrib.auth import get_user_model;raise SystemExit(0 if get_user_model().objects.exists() else 1)"
if errorlevel 1 (
  echo.
  echo No users yet - create the administrator account:
  .venv\Scripts\python manage.py createsuperuser || goto :error
)
start "" http://127.0.0.1:8000
.venv\Scripts\python manage.py runserver 127.0.0.1:8000
goto :eof
:error
echo Setup failed. Make sure Python 3.11+ is installed and on PATH.
pause
