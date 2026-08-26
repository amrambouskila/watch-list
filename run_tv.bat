@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

if "%TV_BACKEND_PORT%"=="" set TV_BACKEND_PORT=8284
if "%TV_FRONTEND_PORT%"=="" set TV_FRONTEND_PORT=5284

echo.
echo  ================================================================
echo   WATCH LIST
echo   Tracks the .xlsx watch orders in %CD%
echo  ================================================================
echo.

if not exist "app\backend\.venv" (
    echo  First run: installing the backend...
    pushd app\backend
    call uv sync --group dev
    if errorlevel 1 ( echo  uv sync failed. & popd & pause & exit /b 1 )
    popd
)

if not exist "app\frontend\node_modules" (
    echo  First run: installing the frontend...
    pushd app\frontend
    call pnpm install
    if errorlevel 1 ( echo  pnpm install failed. & popd & pause & exit /b 1 )
    popd
)

REM The SDK ships no binary and Chromium is a separate download, so say so here rather than
REM letting the first chat message fail with a 503.
set PREFLIGHT_MISSING=
pushd app\backend
for /f "delims=" %%m in ('uv run python -m tv_watchlist.agent.preflight 2^>nul') do (
    if not defined PREFLIGHT_MISSING echo  Chat needs these before it will work:
    set PREFLIGHT_MISSING=1
    echo %%m
)
popd
if defined PREFLIGHT_MISSING echo.

:start
echo  Starting services...
start "TV Watch List backend" /min cmd /c "cd /d %~dp0app\backend && uv run uvicorn tv_watchlist.main:app --host 127.0.0.1 --port %TV_BACKEND_PORT%"
start "TV Watch List frontend" /min cmd /c "cd /d %~dp0app\frontend && pnpm dev"

echo.
echo  ----------------------------------------------------------------
echo   Services are running
echo.
echo     App        http://localhost:%TV_FRONTEND_PORT%
echo     API        http://localhost:%TV_BACKEND_PORT%
echo     API docs   http://localhost:%TV_BACKEND_PORT%/docs
echo.
echo     Backups    app\.backups
echo  ----------------------------------------------------------------
echo.

timeout /t 3 /nobreak >nul
start "" http://localhost:%TV_FRONTEND_PORT%

:menu
echo.
echo    [r] Restart both services
echo    [k] Stop and exit
echo.
REM `choice` is used instead of `set /p` because Ctrl-C at a `set /p` prompt raises cmd's
REM "Terminate batch job" question, and answering yes exits before the servers are stopped.
choice /c rk /n /m "  Choose an option [r/k]: "
if errorlevel 2 goto stop
if errorlevel 1 goto restart
goto menu

:restart
echo.
call :shutdown
goto start

:stop
echo.
call :shutdown
echo  Stopped.
pause
exit /b 0

:shutdown
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":%TV_BACKEND_PORT% " ^| findstr LISTENING') do taskkill /F /PID %%p /T >nul 2>&1
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":%TV_FRONTEND_PORT% " ^| findstr LISTENING') do taskkill /F /PID %%p /T >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq TV Watch List backend*" /T >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq TV Watch List frontend*" /T >nul 2>&1
exit /b 0
