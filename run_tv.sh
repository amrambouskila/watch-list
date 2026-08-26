#!/usr/bin/env bash
set -uo pipefail

cd "$(dirname "$0")"

TV_BACKEND_PORT="${TV_BACKEND_PORT:-8284}"
TV_FRONTEND_PORT="${TV_FRONTEND_PORT:-5284}"
export TV_BACKEND_PORT TV_FRONTEND_PORT

BACKEND_PID=""
FRONTEND_PID=""

banner() {
  cat <<BANNER

 ================================================================
  WATCH LIST
  Tracks the .xlsx watch orders in $(pwd)
 ================================================================

BANNER
}

bootstrap() {
  if [ ! -d "app/backend/.venv" ]; then
    echo " First run: installing the backend..."
    (cd app/backend && uv sync --group dev) || { echo " uv sync failed."; exit 1; }
  fi
  if [ ! -d "app/frontend/node_modules" ]; then
    echo " First run: installing the frontend..."
    (cd app/frontend && pnpm install) || { echo " pnpm install failed."; exit 1; }
  fi
}

# The SDK ships no binary and Chromium is a separate download, so say so here rather than
# letting the first chat message fail with a 503.
preflight() {
  local missing
  missing="$(cd app/backend && uv run python -m tv_watchlist.agent.preflight 2>/dev/null)"
  [ -z "$missing" ] && return
  echo " Chat needs these before it will work:"
  echo "$missing"
  echo
}

# The .bat opens the app for you once the servers are up; this side has to pick the opener, and
# on a headless box there is none, so a miss is silent rather than an error.
open_app() {
  local url="http://localhost:${TV_FRONTEND_PORT}"
  if command -v open >/dev/null 2>&1; then
    open "$url" >/dev/null 2>&1 &
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$url" >/dev/null 2>&1 &
  fi
}

start_services() {
  echo " Starting services..."
  # `exec` replaces the wrapper subshell, so $! is the server itself and not a shell that
  # would leave the real process orphaned when killed.
  ( cd app/backend && exec uv run uvicorn tv_watchlist.main:app --host 127.0.0.1 --port "$TV_BACKEND_PORT" ) &
  BACKEND_PID=$!
  ( cd app/frontend && exec pnpm dev ) &
  FRONTEND_PID=$!

  cat <<RUNNING

 ----------------------------------------------------------------
  Services are running

    App        http://localhost:${TV_FRONTEND_PORT}
    API        http://localhost:${TV_BACKEND_PORT}
    API docs   http://localhost:${TV_BACKEND_PORT}/docs

    Backups    app/.backups
 ----------------------------------------------------------------

RUNNING

  # The same pause the .bat takes, so the dev server is answering before the tab asks it anything.
  sleep 3
  open_app
}

# Anything still holding a port after the PIDs are gone (a shell that re-spawned, a stale run).
free_port() {
  local port="$1" pids=""
  if command -v lsof >/dev/null 2>&1; then
    pids="$(lsof -ti "tcp:${port}" 2>/dev/null)"
  elif command -v netstat >/dev/null 2>&1; then
    pids="$(netstat -ano 2>/dev/null | grep -E "[:.]${port}[[:space:]]" | grep -i listen | awk '{print $NF}' | sort -u)"
  fi
  for pid in $pids; do
    kill "$pid" 2>/dev/null || true
  done
}

stop_services() {
  for pid in "$BACKEND_PID" "$FRONTEND_PID"; do
    [ -n "$pid" ] && kill "$pid" 2>/dev/null
  done
  [ -n "$BACKEND_PID" ] && wait "$BACKEND_PID" 2>/dev/null
  [ -n "$FRONTEND_PID" ] && wait "$FRONTEND_PID" 2>/dev/null
  BACKEND_PID=""
  FRONTEND_PID=""
  free_port "$TV_BACKEND_PORT"
  free_port "$TV_FRONTEND_PORT"
}

trap 'stop_services; echo; echo " Stopped."; exit 0' INT TERM

banner
bootstrap
preflight
start_services

while true; do
  cat <<MENU

   [r] Restart both services
   [k] Stop and exit

MENU
  if ! read -r -p "  Choose an option: " choice; then
    stop_services
    echo " Stopped."
    exit 0
  fi
  case "$(printf '%s' "${choice:-}" | tr '[:upper:]' '[:lower:]')" in
    r)
      stop_services
      start_services
      ;;
    k)
      stop_services
      echo " Stopped."
      exit 0
      ;;
    *)
      echo "  \"${choice:-}\" is not an option."
      ;;
  esac
done
