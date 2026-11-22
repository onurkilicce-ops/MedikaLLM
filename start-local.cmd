@echo off
rem MedicaLLM yerel calistirma: veritabani + backend + frontend.
rem Cift tiklayin; backend ve frontend ayri pencerelerde acilir.
chcp 65001 >nul
set "PG=C:\Users\Public\medicallm-pg"

rem 1) Veritabani (zaten calisiyorsa atlanir)
"%PG%\pginstall\bin\pg_isready.exe" -h localhost -p 5432 >nul 2>&1
if errorlevel 1 (
    echo Veritabani baslatiliyor...
    start "MedicaLLM DB" /min "%PG%\pginstall\bin\pg_ctl.exe" -D "%PG%\data" -l "%PG%\postgres.log" -o "-p 5432" -w start
    timeout /t 5 /nobreak >nul
)

rem 2) Backend (http://localhost:8000)
start "MedicaLLM backend" cmd /k "cd /d "%~dp0backend" && set PYTHONIOENCODING=utf-8 && uv run python run.py"

rem 3) Frontend (http://localhost:3000)
start "MedicaLLM frontend" cmd /k "cd /d "%~dp0frontend" && npm.cmd run dev"

timeout /t 15 /nobreak >nul
start "" http://localhost:3000
