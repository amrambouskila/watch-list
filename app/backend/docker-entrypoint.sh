#!/bin/sh
# Migrations before the server. compose's `depends_on: condition: service_healthy` on postgres is what
# makes an unconditional `upgrade head` safe here; a failed migration stops the container instead of
# serving a schema the code does not expect. Under `restart: unless-stopped` a migration that keeps
# failing is therefore a crash loop by design: the API never serves an unmigrated schema, and the
# restarts are the visible symptom rather than a silent half-working container.
# `exec` so uvicorn is PID 1 and receives SIGTERM directly.
set -eu
cd /srv/app/backend
alembic upgrade head
exec uvicorn tv_watchlist.main:app --host 0.0.0.0 --port 8284
