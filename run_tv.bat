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
if "%TV_POSTGRES_PORT%"=="" set TV_POSTGRES_PORT=5525
if "%TV_POSTGRES_WAIT_SECONDS%"=="" set TV_POSTGRES_WAIT_SECONDS=60
REM No COMPOSE_FILE and no -f on any compose call: this script cd's to its own directory above, so
REM compose finds docker-compose.yml there. Keeping the two tokens out of the middle of every command
REM is also what lets tests/test_launchers.py grep for whole compose invocations.
set "IMAGE_PREFIX=tv-watchlist"
set /a POSTGRES_WAIT_SECONDS=%TV_POSTGRES_WAIT_SECONDS%
REM A display-only copy of the database name, for the URL block. Deliberately NOT `set TV_POSTGRES_DB=tv`:
REM an environment variable outranks the root .env for compose substitution, so defaulting it here would
REM override a TV_POSTGRES_DB the owner set only in .env. The .sh does the same with ${TV_POSTGRES_DB:-tv}.
set "PG_DB_LABEL=%TV_POSTGRES_DB%"
if "%PG_DB_LABEL%"=="" set "PG_DB_LABEL=tv"

echo.
echo  ================================================================
echo   WATCH LIST
echo   Tracks the .xlsx watch orders in %CD%
echo.
echo     App        host-native Vite        :%TV_FRONTEND_PORT%
echo     API        host-native uvicorn     :%TV_BACKEND_PORT%
echo     Postgres   compose service         :%TV_POSTGRES_PORT%
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

call :ensure_postgres
if errorlevel 1 ( call :restore_codepage & pause & exit /b 1 )

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
echo     Postgres   localhost:%TV_POSTGRES_PORT%  (db: %PG_DB_LABEL%)
echo.
echo     Backups    app\.backups
echo  ----------------------------------------------------------------
echo.

timeout /t 3 /nobreak >nul
start "" http://localhost:%TV_FRONTEND_PORT%

:menu
echo.
echo    [r] Restart both host services (Postgres stays up)
echo    [k] Stop and exit (keep images and volumes)
echo    [q] Stop, remove the %IMAGE_PREFIX% images (keep volumes)
echo    [v] Stop, remove the images AND the volumes (drops tv_postgres_data and the Jellyfin config)
echo.
REM `choice` is used instead of `set /p` because Ctrl-C at a `set /p` prompt raises cmd's
REM "Terminate batch job" question, and answering yes exits before the servers are stopped.
REM errorlevel tests go highest-first: `if errorlevel N` is true for every level >= N.
choice /c rkqv /n /m "  Choose an option [r/k/q/v]: "
if errorlevel 4 goto volumes
if errorlevel 3 goto quit
if errorlevel 2 goto stop
if errorlevel 1 goto restart
goto menu

:restart
echo.
call :shutdown
call :ensure_postgres
if errorlevel 1 echo  Postgres is not ready; starting the servers anyway.
goto start

:stop
echo.
call :shutdown
echo  Stopping containers (images and volumes kept)...
docker compose down
echo  Stopped.
call :restore_codepage
pause
exit /b 0

:quit
echo.
call :shutdown
echo  Stopping containers and removing project images (volumes kept)...
docker compose down --remove-orphans
call :remove_images
echo  Done.
call :restore_codepage
pause
exit /b 0

:volumes
echo.
call :shutdown
echo  Stopping containers, removing project images and volumes...
docker compose down --volumes --remove-orphans
call :remove_images
echo  Done.
call :restore_codepage
pause
exit /b 0

:ensure_postgres
REM Only Postgres comes from compose; the two servers stay host-native so chat keeps working, and
REM jellyfin is the owner's to start. The host-native backend does not migrate on boot the way the
REM container entrypoint does, so the launcher applies the migrations itself once Postgres answers.
REM Failure returns an errorlevel rather than exiting, so [r] can say so and go back to the menu
REM instead of taking the launcher down with it.
echo  Starting Postgres (compose)...
docker compose up -d postgres
if errorlevel 1 ( echo  docker compose up failed. Is Docker running? & exit /b 1 )
set "PG_CONTAINER="
for /f "delims=" %%c in ('docker compose ps -q postgres') do set "PG_CONTAINER=%%c"
if "%PG_CONTAINER%"=="" (
    echo  No postgres container was created. Check: docker compose ps postgres
    exit /b 1
)
set /a WAITED=0
REM Poll the container's own state as well as its health, so a container that never starts, dies, or
REM reports unhealthy is named immediately instead of burning the whole wait on a state that will
REM never become `healthy`.
:postgres_wait
set "PG_STATE="
set "PG_HEALTH="
for /f "tokens=1,2" %%s in ('docker inspect --format "{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}" "%PG_CONTAINER%" 2^>nul') do (
    set "PG_STATE=%%s"
    set "PG_HEALTH=%%t"
)
if "%PG_STATE%"=="" (
    echo  The postgres container disappeared while starting. Check: docker compose logs postgres
    exit /b 1
)
if "%PG_HEALTH%"=="healthy" goto postgres_ready
if "%PG_HEALTH%"=="unhealthy" goto postgres_bad
if "%PG_STATE%"=="exited" goto postgres_bad
if "%PG_STATE%"=="dead" goto postgres_bad
set /a WAITED+=1
if %WAITED% GEQ %POSTGRES_WAIT_SECONDS% (
    echo  Postgres is still %PG_STATE%/%PG_HEALTH% after %POSTGRES_WAIT_SECONDS%s. Check: docker compose logs postgres
    exit /b 1
)
timeout /t 1 /nobreak >nul
goto postgres_wait

:postgres_ready
echo  Applying migrations...
pushd app\backend
call uv run alembic upgrade head
if errorlevel 1 ( echo  alembic upgrade head failed. & popd & exit /b 1 )
popd
exit /b 0

:postgres_bad
echo  Postgres is %PG_STATE%/%PG_HEALTH%, not starting. Check: docker compose logs postgres
exit /b 1

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

:remove_images
REM Only the images this project builds. postgres:16-alpine and jellyfin/jellyfin are upstream
REM images that nothing here built, so they stay whatever the menu asked for.
REM
REM Removal is by image ID, not by `repository:tag`: a rebuild leaves the previous layer behind as
REM `tv-watchlist-frontend:<none>`, and `<none>` is not a tag docker can resolve, so a name-based
REM sweep announced a removal that always failed. A failure is now printed rather than swallowed.
echo  Removing %IMAGE_PREFIX% images...
set "FOUND_IMAGE="
for /f "tokens=1,2" %%R in ('docker images --format "{{.Repository}}:{{.Tag}} {{.ID}}" ^| findstr /B /C:"%IMAGE_PREFIX%"') do (
    set "FOUND_IMAGE=1"
    echo   removing %%R ^(%%S^)
    docker rmi -f "%%S" >nul 2>&1
    if errorlevel 1 echo     could not remove %%S - already gone, or a container still uses it.
)
if not defined FOUND_IMAGE echo   none found.
exit /b 0

:restore_codepage
if defined ORIGINAL_CODEPAGE chcp %ORIGINAL_CODEPAGE% >nul
exit /b 0
