#!/usr/bin/env bash
set -uo pipefail

cd "$(dirname "$0")"

TV_BACKEND_PORT="${TV_BACKEND_PORT:-8284}"
TV_FRONTEND_PORT="${TV_FRONTEND_PORT:-5284}"
TV_POSTGRES_PORT="${TV_POSTGRES_PORT:-5525}"
export TV_BACKEND_PORT TV_FRONTEND_PORT TV_POSTGRES_PORT

# No COMPOSE_FILE variable and no `-f` on any compose call: the script `cd`s to its own directory above,
# and docker-compose.yml is right there, so compose finds it. Passing `-f "$COMPOSE_FILE"` would only put
# two tokens between `docker compose` and its subcommand, which is exactly what tests/test_launchers.py
# greps across.
IMAGE_PREFIX="tv-watchlist"
POSTGRES_WAIT_SECONDS="${TV_POSTGRES_WAIT_SECONDS:-60}"

BACKEND_PID=""
FRONTEND_PID=""

banner() {
  cat <<BANNER

 ================================================================
  WATCH LIST
  Tracks the .xlsx watch orders in $(pwd)

    App        host-native Vite        :${TV_FRONTEND_PORT}
    API        host-native uvicorn     :${TV_BACKEND_PORT}
    Postgres   compose service         :${TV_POSTGRES_PORT}
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

# Only Postgres comes from compose; the two servers stay host-native so chat keeps working, and
# jellyfin is the owner's to start. The host-native backend does not migrate on boot the way the
# container entrypoint does, so the launcher applies the migrations itself once Postgres answers.
# This reports failure with a return rather than an exit, so [r] can say so and go back to the
# menu instead of taking the launcher down with it.
ensure_postgres() {
  echo " Starting Postgres (compose)..."
  docker compose up -d postgres || { echo " docker compose up failed. Is Docker running?"; return 1; }

  local container
  container="$(docker compose ps -q postgres)"
  if [ -z "$container" ]; then
    echo " No postgres container was created. Check: docker compose ps postgres"
    return 1
  fi

  # Poll the container's own state as well as its health, so a container that never starts, dies, or
  # reports unhealthy is named immediately instead of burning the whole wait on a state that will
  # never become `healthy`.
  local waited=0 reported state health
  while :; do
    if ! reported="$(docker inspect \
      --format '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' \
      "$container" 2>/dev/null)"; then
      echo " The postgres container disappeared while starting. Check: docker compose logs postgres"
      return 1
    fi
    state="${reported%% *}"
    health="${reported##* }"
    [ "$health" = "healthy" ] && break
    if [ "$health" = "unhealthy" ] || [ "$state" = "exited" ] || [ "$state" = "dead" ]; then
      echo " Postgres is ${state}/${health}, not starting. Check: docker compose logs postgres"
      return 1
    fi
    waited=$((waited + 1))
    if [ "$waited" -ge "$POSTGRES_WAIT_SECONDS" ]; then
      echo " Postgres is still ${state}/${health} after ${POSTGRES_WAIT_SECONDS}s. Check: docker compose logs postgres"
      return 1
    fi
    sleep 1
  done

  echo " Applying migrations..."
  (cd app/backend && uv run alembic upgrade head) || { echo " alembic upgrade head failed."; return 1; }
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
    Postgres   localhost:${TV_POSTGRES_PORT}  (db: ${TV_POSTGRES_DB:-tv})

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

# Only the images this project builds. postgres:16-alpine and jellyfin/jellyfin are upstream images
# that nothing here built, so they stay whatever the menu asked for.
#
# Removal is by image ID, not by `repository:tag`: a rebuild leaves the previous layer behind as
# `tv-watchlist-frontend:<none>`, and `<none>` is not a tag docker can resolve, so a name-based sweep
# announced a removal that always failed. A failure is now printed rather than swallowed.
remove_images() {
  echo " Removing ${IMAGE_PREFIX} images..."
  local listing reference id
  listing="$(docker images --format "{{.Repository}}:{{.Tag}} {{.ID}}" | grep "^${IMAGE_PREFIX}" || true)"
  if [ -z "$listing" ]; then
    echo "  none found."
    return 0
  fi
  while read -r reference id; do
    [ -n "$id" ] || continue
    echo "  removing ${reference} (${id})"
    docker rmi -f "$id" >/dev/null 2>&1 ||
      echo "    could not remove ${id} - already gone, or a container still uses it."
  done <<<"$listing"
}

stop_keep() {
  stop_services
  echo " Stopping containers (images and volumes kept)..."
  docker compose down
}

trap 'stop_keep; echo; echo " Stopped."; exit 0' INT TERM

banner
bootstrap
preflight
ensure_postgres || exit 1
start_services

while true; do
  cat <<MENU

   [r] Restart both host services (Postgres stays up)
   [k] Stop and exit (keep images and volumes)
   [q] Stop, remove the ${IMAGE_PREFIX} images (keep volumes)
   [v] Stop, remove the images AND the volumes (drops tv_postgres_data and the Jellyfin config)

MENU
  if ! read -r -p "  Choose an option: " choice; then
    stop_keep
    echo " Stopped."
    exit 0
  fi
  case "$(printf '%s' "${choice:-}" | tr '[:upper:]' '[:lower:]')" in
    r)
      stop_services
      ensure_postgres || echo " Postgres is not ready; starting the servers anyway."
      start_services
      ;;
    k)
      stop_keep
      echo " Stopped."
      exit 0
      ;;
    q)
      stop_services
      echo " Stopping containers and removing project images (volumes kept)..."
      docker compose down --remove-orphans
      remove_images
      echo " Done."
      exit 0
      ;;
    v)
      stop_services
      echo " Stopping containers, removing project images and volumes..."
      docker compose down --volumes --remove-orphans
      remove_images
      echo " Done."
      exit 0
      ;;
    *)
      echo "  \"${choice:-}\" is not an option."
      ;;
  esac
done
