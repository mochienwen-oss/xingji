@echo off
rem ============================================================
rem  XingJi Trip - start portable PostgreSQL 16.2 (port 5433)
rem  Set PGROOT to the directory containing pgsql\ and pgdata\.
rem  Default    : %USERPROFILE%\trip-runtime
rem  Layout     : %PGROOT%\pgsql, %PGROOT%\pgdata, %PGROOT%\postgres.log
rem  Safe to double-click at any time; does nothing if already up.
rem  Stop   : pg_ctl.exe -D "%PGDATA%" stop -m fast
rem  Status : pg_ctl.exe -D "%PGDATA%" status
rem ============================================================
if not defined PGROOT set "PGROOT=%USERPROFILE%\trip-runtime"
set "PGBIN=%PGROOT%\pgsql\bin"
set "PGDATA=%PGROOT%\pgdata"
set "PGLOG=%PGROOT%\postgres.log"

"%PGBIN%\pg_isready.exe" -h 127.0.0.1 -p 5433 >nul 2>&1
if not errorlevel 1 (
    echo [OK] PostgreSQL is already running on port 5433.
    exit /b 0
)

echo Starting PostgreSQL on port 5433 ...
"%PGBIN%\pg_ctl.exe" -D "%PGDATA%" -l "%PGLOG%" -o "-p 5433" -w start
if errorlevel 1 (
    echo.
    echo [FAIL] PostgreSQL did not start. Last 15 log lines:
    powershell -NoProfile -Command "Get-Content -Tail 15 '%PGLOG%'"
    exit /b 1
)

"%PGBIN%\pg_isready.exe" -h 127.0.0.1 -p 5433
echo [OK] PostgreSQL started on port 5433.
