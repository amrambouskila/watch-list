@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

REM Both servers stream into this console through a PowerShell prefixing pipeline below, and
REM PowerShell decodes their bytes using the console codepage. Left at the OEM default, Vite's
REM box-drawing and its arrow come out as mojibake, so pin UTF-8 and put back what was here on
REM the way out - this console may be one the owner was already using.
for /f "tokens=2 delims=:" %%c in ('chcp') do set "ORIGINAL_CODEPAGE=%%c"
set "ORIGINAL_CODEPAGE=%ORIGINAL_CODEPAGE: =%"
chcp 65001 >nul

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
    if errorlevel 1 ( echo  uv sync failed. & popd & call :restore_codepage & pause & exit /b 1 )
    popd
)

if not exist "app\frontend\node_modules" (
    echo  First run: installing the frontend...
    pushd app\frontend
    call pnpm install
    if errorlevel 1 ( echo  pnpm install failed. & popd & call :restore_codepage & pause & exit /b 1 )
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
echo.

REM Both servers run in THIS console via `start /b`, each behind a PowerShell pipeline that tags
REM every line with the service it came from. Three things make that work:
REM   * PYTHONUNBUFFERED - uvicorn's access log goes to stdout, which Python block-buffers once it
REM     is a pipe rather than a console, so without this its lines arrive in bursts.
REM   * CI - `start /b` leaves stdin attached to this console, so Vite still sees a TTY and would
REM     bind its own r/u/o/c/q keys, fighting `choice` below for every keystroke. Vite's guard is
REM     `if (!server.httpServer || !process.stdin.isTTY || process.env.CI) return`, so CI settles it.
REM     It also stops Vite clearing the screen, which would wipe the URLs block printed below.
REM   * TVWL_SVC - a marker in the command line, so :shutdown can find these two wrappers again.
start "" /b powershell -NoProfile -ExecutionPolicy Bypass -Command "$e=[char]27; [Console]::OutputEncoding=[Text.Encoding]::UTF8; $env:TVWL_SVC='backend'; $env:PYTHONUNBUFFERED='1'; Set-Location '%~dp0app\backend'; uv run uvicorn tv_watchlist.main:app --host 127.0.0.1 --port %TV_BACKEND_PORT% --use-colors 2>&1 | ForEach-Object { Write-Host ($e + '[36m[backend] ' + $e + '[0m ' + $_) }"
start "" /b powershell -NoProfile -ExecutionPolicy Bypass -Command "$e=[char]27; [Console]::OutputEncoding=[Text.Encoding]::UTF8; $env:TVWL_SVC='frontend'; $env:CI='1'; Set-Location '%~dp0app\frontend'; pnpm dev 2>&1 | ForEach-Object { Write-Host ($e + '[35m[frontend]' + $e + '[0m ' + $_) }"

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
call :restore_codepage
pause
exit /b 0

:shutdown
REM Listeners first, by port, so each server dies with its own children still attached to it.
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":%TV_BACKEND_PORT% " ^| findstr LISTENING') do taskkill /F /PID %%p /T >nul 2>&1
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":%TV_FRONTEND_PORT% " ^| findstr LISTENING') do taskkill /F /PID %%p /T >nul 2>&1
REM Then the two wrappers, for the case where a server never reached the point of binding a port.
REM This cannot filter on WINDOWTITLE the way it used to: `start /b` gives these no window of
REM their own, so they carry THIS console's title and the old filter would have killed the
REM launcher mid-shutdown. Match the command line instead, skipping our own PID.
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $PID -and $_.Name -eq 'powershell.exe' -and $_.CommandLine -like '*$env:TVWL_SVC=*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1
exit /b 0

:restore_codepage
if defined ORIGINAL_CODEPAGE chcp %ORIGINAL_CODEPAGE% >nul
exit /b 0
