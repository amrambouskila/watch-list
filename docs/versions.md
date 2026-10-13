# Versions

Strict semver, newest at the top.

**The source of truth for the current version is the two manifest files** — the `version` field in
`app/backend/pyproject.toml` (`:3`) and the `version` field in `app/frontend/package.json` (`:4`).
They move together and are both at `0.1.0` today. Nothing else on this page overrides them: if a
heading below sits above the manifests' number, that heading describes work that has landed in the
tree but has not been released.

Three rules govern this file, and they exist because version drift between sessions is expensive:

- **The next version is computed, never invented, and never written as "Unreleased".** Patch for a
  bug fix, a docs-only change, a styling tweak or a behaviour-preserving refactor; minor for a new
  feature, module or endpoint, or for a data-contract change; major for a break, and only after the
  owner has agreed to it.
- **Only one unreleased version exists at a time.** While the manifests read `0.1.0` and this file
  carries a `v0.2.0` heading, further work goes *under* that heading as a new subsection. A fresh
  heading is opened only once the previous one has actually been released.
- **The `version` fields are bumped by the release pipeline, by hand never.** A session's job is to
  compute the next number and document it here. The same applies to the `version="0.1.0"` argument
  to `FastAPI(...)` in `create_app` (`app/backend/src/tv_watchlist/main.py:24-27`) — it is kept in
  step by the release pipeline, not hand-edited by a session. (No release pipeline exists yet — see
  `docs/status.md` section 4, item 9.)

---

## v0.2.0 — Phase 0 closed, and the metadata spine beside the workbooks

**Phase 1 lands here in full, and Phase 0 closes with it.** Beside the nineteen workbooks — which stay
authoritative for watch order and hand curation, and which still open standalone in Excel — this
version adds a derived PostgreSQL 16 projection: eleven tables, two derived views and an append-only
`watch_event` trigger raised by the first Alembic revision (`T04`-`T11`); TMDB and TheTVDB v4 clients
driven entirely by recorded fixtures, with a token bucket, an SSRF guard and a Postgres response cache
(`T12`-`T15`); the resolver — `match_key`, franchise expansion, the `Unit` span parser and the
confidence ladder — which put **830 of 996 rows on automatic and 166 into the review queue** in the
dry run recorded at `docs/resolver-dry-run.md` (`T16`-`T20`, `T31`); the hidden `Row ID` identity
column and the reconciler that mints it, whose entire diff is **one** `Catalog._write` (`T21`-`T23`);
the flattened `curated_entry_item` queue that gives every film its own slot so Next never skips one
(`T24`, ADR-010); the four-value `Watched?` mirror, which loses its race with a human edit by design
(`T25`, `T26`); the bootstrap runner (`T27`); three new routers — `GET /api/categories/{id}/entries`,
`POST /api/watch-events` answering **201 `WatchEventRead`** with the entry's derived progress embedded
(Ruling 44), and the resolution review queue (`T28`-`T30`); provider attribution in the sidebar
(`T32`); and both launchers gaining `[q]` and `[v]` over a compose `postgres` service on host port
`5525` (`T09`, `T11`, `T32a`). The `jellyfin` compose service on `8096` (`T47a`) lands early, ahead of
Phase 3, so the owner can create its API key. **Contract additions, each mirrored in TypeScript in the
same change:** `ColumnSpec.role` gains `"identity"`; `CuratedEntryRead`, `EntryProgress`,
`EpisodeRead`, `TitleRead`, `WatchEventCreate`, `WatchEventRead` and `ResolutionUpdate` are new.
**Minor bump** from `0.1.0` — new modules, new endpoints and additive contract changes are all minor
under the change policy, and nothing pre-existing broke: every Phase 0 route behaves exactly as
before. Neither `version` field was touched; the release pipeline owns those. **Gate audit (`T33`,
2026-09-20): 22 of §10.1's 24 boxes verified with evidence, 1 unverifiable on this machine (the
compose bring-up — Docker pulls nothing under the owner's VPN), and 1 reopened** — SAST, on a single
HIGH from `js-yaml@4.3.1` reached through eslint's devDependencies (GHSA-2883-xcg3-v3hh, fixed in
4.3.2). Suite at the gate: **2506 passed / 0 failed / 0 skipped** against a real PostgreSQL 16.2 and
**2290 passed / 227 loud skips** offline (2517 collected once the final-review and fixture fixes landed; 2517 / 0 / 0 against the compose Postgres on 2026-09-21), backend line coverage **98.34%**, Vitest **219**, the layout
guard **156**, the hook suite **31**. **The reopened box was closed the same evening**: a lockfile-only
`pnpm update js-yaml` bumped unrelated caret floors across `app/frontend/package.json` (rejected as
out of scope), so the fix is a `pnpm.overrides` entry — `"js-yaml": "^4.3.2"`, matching
`@eslint/eslintrc`'s own declared `^4.1.0` major rather than reaching past it — in
`app/frontend/package.json`'s `"pnpm"` field, regenerated with `pnpm install` into `pnpm-lock.yaml`
(resolving to `js-yaml@4.3.2` exactly, confirmed with `pnpm why js-yaml`). `pnpm audit
--audit-level=high` now reports no known vulnerabilities;
`tsc -b`, `pnpm lint`, `pnpm test` (219 passed) and `pnpm build` all stayed green with only those two
files changed. **Gate now stands at 23 of 24 verified here, 1 unverifiable on this machine.**
**A final whole-branch review the same evening (Ruling 56) closed two more Important findings:**
`resolver/dry_run.py`'s `--out` must now end in `.md`, refused before `Settings`, a client or a
request exists, closing the path by which a mistyped `--out Marvel.xlsx` could have replaced a root
workbook outside `Catalog._write`; and `test_env_example.py`'s guard now derives its required name set
from `Settings.model_fields` itself, so it actually fails on drift rather than only comparing the file
to a second hand-written list.

**Test harness, 2026-09-21: the throwaway database is now one per process.** `tests/database_support.py`
folds the pid into the name the session start rebuilds — `TV_POSTGRES_DB=tv_test` becomes
`tv_p<pid>_test` — because that rebuild is a `DROP DATABASE … WITH (FORCE)`, so two local runners
sharing one name terminated each other's connections and removed each other's tables mid-suite. The
`database_url` fixture now drops that database at session end and the session start reclaims any
sibling whose pid is gone, so runs leave nothing on the compose volume; suite **2517 passed / 0 failed
/ 0 skipped**, three consecutive times, and two deliberately concurrent runs now both pass.

### Added — a root-level `docs/`

- **`docs/TV_MASTER_PLAN.md`** — the authoritative plan. Goals, the phase breakdown with
  deliverables and per-phase gates (section 10.1 is Phase 1's), architecture decisions with the
  reasoning behind each, the technology choices and what they were chosen over, cross-phase
  concerns, the security section (SAST wiring plus the untrusted-input boundary inventory), the task
  table, and the Phase 1 schema contract.
- **`docs/status.md`** — the live-state document: what exists now, what was decided, what is next,
  and the open items. It is state, not a log.
- **`docs/versions.md`** — this file.

`app/docs/` is unchanged and keeps its existing role: design notes, currently
`chat-feature-design.md`. The root `docs/` is the plan; `app/docs/` is the notes.

### Decided — the phase sequence, with Phase 0 named

```mermaid
graph LR
  P0["P0 — the shipped workbook app"] --> P1["P1 — metadata spine"] --> P2["P2 — ten-foot browser UI"] --> P3["P3 — playback"]
```

- **P0, the shipped workbook app.** The nineteen-workbook FastAPI + React app described under
  `v0.1.0` below. It shipped before this plan existed; this documentation pass is what closes it, on
  five tasks: `T00` (root `docs/`), `T01` (root `CLAUDE.md`), `T01a` (the `.claude/` wiring), `T01b`
  (`.env.example`) and `T01c` (the README reconciliation).
- **P1, metadata spine.** A Postgres 16 projection beside the workbooks, fed by TMDB and TheTVDB
  ingest.
- **P2, ten-foot browser UI.** Spatial navigation, a ten-foot type scale and safe-area tokens, and
  1920x1080 added to the Playwright layout guard's window matrix.
- **P3, playback.** Self-hosted Jellyfin, joined by `tmdb_id` — and only once a real file library
  exists to play from. There are no video files on this machine yet, so P3 is designed for and not
  built.

### Decided — dual store

The workbooks stay. Excel remains authoritative for watch **order** and hand curation and remains
editable in Excel; Postgres becomes authoritative for episodes, air dates, runtimes, artwork and
watch progress. The `Watched?` cell is mirrored back into the sheet — a lossy one-directional
projection of an append-only progress log onto the sheet's own four values, read as a signal that a
human changed something and never as truth — so a workbook opened standalone still means something.
A sheet row's identity becomes a UUID carried in a hidden `Row ID` column, because the existing
writer already relays whole row-value arrays through adds, moves and removes and therefore carries
that identity for free; the Excel row number and the `Order` value are both disqualified, since the
writer resequences them.

The **Phase 1** schema is eleven tables — `category`, `curated_entry`, `curated_entry_item`,
`title`, `season`, `episode`, `episode_order`, `external_id`, `artwork`, `watch_event`,
`sync_state` — and Phase 3's own revision adds `jellyfin_item` and `streaming_offer`, thirteen in
all (see "Decided — 2026-09-20" below) — with the curated order modelled as two levels: the user's
authored `position` over entries, and each entry's span over that title's own dense, 1-based episode
numbering.

### Decided — device and UI treatment

The app is watched on a TV driven from a PC or laptop over HDMI or a cast, and it **stays a browser
app**. No Tizen `.wgt`, no webOS `.ipk`, no `react-native-tvos`, no app stores, no second native
codebase. The ten-foot treatment is CSS tokens plus one focus library:
`@noriginmedia/norigin-spatial-navigation` (MIT), chosen over `react-tv-space-navigation` (stale) and
`bbc/lrud` (archived).

### Decided — Next and Autoplay follow the curated order

A **Next** button and an **Autoplay** toggle advance through a category's curated order across episodes
and films — from a One Piece episode to the film the workbook places next, then back into episodes —
recorded as `docs/TV_MASTER_PLAN.md` §6.9 and ADR-010, with deliverables 2.8 and 3.8, tasks T24, T41 and
T53a, and a line in each phase gate. The planned flattened queue, `curated_entry_item`, now holds one
slot per movie entry; as first designed it held episodes only, which would have made Next skip every
film. Dub versus sub is recorded as a Phase 3 decision (deliverable 3.9), because it is a property of
the video files, not of TMDB or TheTVDB.

### Verified — credentials and provider behaviour, live

All three credentials (the TMDB v4 Read Access Token; the TheTVDB v4 key on End-User Subscriptions
plus its subscriber PIN) authenticate and return data against the live services. The live APIs
corrected the plan in four places, now applied across the docs: TheTVDB's season types are
`official`, `dvd`, `absolute`, `alternate`, `regional`, `altdvd`, `alttwo` — `altdvd`, not `default`,
which is only an endpoint alias for `official`; the TheTVDB series id comes from TMDB's
`/tv/{id}/external_ids`, never from TheTVDB's search, which ranked the One Piece anime eighth behind a
2023 live-action namesake; names are requested through TheTVDB's `/eng` language variants because the
default is the original language; and One Piece is 23 regular seasons plus season 0, not "24 seasons".
One episode — Laboon, aired 2001-03-21 — is TMDB season 2 episode 62, TheTVDB absolute #62, dvd season
2 episode 1 and official season 5 episode 2: the case for `episode_order`, in a single row. Full
findings: `docs/status.md` §2.9.

### Measured — TMDB actually covers this library

Before any Phase 1 code, a stratified sample of 140 of the 686 distinct `(title, type)` pairs was
probed against the public TMDB catalogue: **100/100 ordinary and 39/40 hard titles found**, weighted
to **~99.5% of pairs and ~99.6% of rows**, with ~4 rows genuinely absent library-wide. Coverage is
therefore not a risk to this project. Resolution is: only **67%** of titles match TMDB
character-for-character, ~17% of pairs live inside a parent series as a season or season-0 episode
rather than as a top-level entry, ~24% collide with real same-titled works, and the true zero-touch
rate is **~47%**. T13, T16 and T18 were sharpened accordingly, and `title.tmdb_id` is nullable so a
handful of unmatchable OVAs cannot block the schema. Full findings: `docs/status.md` §2.8.

### Decided — metadata providers

- **TMDB** is the identity, artwork and metadata spine, read with `TV_TMDB_READ_ACCESS_TOKEN`
  server-side only. Its hard 6-month cache ceiling and its absolute-continuous anime episode
  numbering are designed into the schema rather than noted in a comment. One term is recorded
  precisely because it was first misread: TMDB prohibits using its content "in connection with,
  including for training" any machine-learning or AI application, which covers inference, so **no
  TMDB content ever reaches the chat agent** (verified against the terms text 2026-09-15).
- **TheTVDB v4** supplies alternate episode orders, authenticated with `TV_TVDB_API_KEY` plus
  `TV_TVDB_PIN`. The funding model is **decided: "End-User Subscriptions"** — instant approval against
  a TheTVDB user subscription, with the subscriber PIN sent on every login, chosen over "Negotiated
  Contract" because that key stays inactive until a human sales review. **Seven season types are live in production — `official`, `dvd`, `absolute`, `alternate`, `regional`, `altdvd`, `alttwo` (measured 2026-09-15) — and the OpenAPI spec lists
  them as examples rather than an `enum`, so the list is not closed.** The rule that follows: read
  the season-type list at runtime from a cached `GET /v4/seasons/types` and never hard-code it. An
  empty episode list is treated as *unknown* rather than as *no episodes*.
- **AniList** is **not adopted now, and is revisitable behind an ADR and a feature flag** — not a
  permanent non-goal. TheTVDB already supplies absolute order, so AniList is not needed for
  ordering; what it would add is franchise topology. It is held back because its API is currently
  degraded to 30 requests per minute, rate-limit-increase requests are not being accepted, and it
  returns HTTP 403 during outages.
- **Trakt** is design inspiration only and is **not adopted** — its February 2026 free tier caps a
  user at 1,000 total list items.
- **Plex** is **not adopted** — its 2026 remote-streaming paywall was extended to third-party API
  clients.
- **Jellyfin** is the designated Phase 3 playback layer, self-hosted.

### Rejected — streambert

`github.com/truelockmc/streambert` was evaluated and rejected outright; nothing from it is adopted.
It is an Electron desktop client under GPL-3.0 that scrapes unlicensed stream hosts and rips m3u8
with ffmpeg, and it self-tags as piracy. Zero technical overlap with a browser app over a personal
file library; GPL-3.0 contagion onto a repository that currently carries no `LICENSE` file, so
vendoring it would settle the licence question as a side effect of a code-reuse convenience rather
than as a decision, and settle it on GPL-3.0; and legal exposure — three independent disqualifiers.
It is recorded as ADR-006 in `docs/TV_MASTER_PLAN.md` and summarised in the status and versions
entries for this change. Nothing from it is adopted.

### Allocated — Postgres host port 5525

The first free slot in the documented `5520-5591` range, adjacent to `Torah_Learning_Sidra` at
`5524`. It is the only new host port the **Phase 1** design takes; Phase 3 adds `8096` for Jellyfin
(see "Decided — 2026-09-20" below). The allocation is an allocation only — no compose service,
`.env` default or launcher default claims it, and `PORT_ASSIGNMENTS.md` is **not** amended for
`5525` in this change. The registry row lands in the Phase 1 implementation commit that
actually publishes the port. The Phase 1 database is `tv` (`TV_POSTGRES_DB`, default `tv`), with
`tv_test` for the CI service container. The registry did gain this project's `8096` row on
2026-09-20 (`T47a`, the jellyfin service); `5525`'s row still lands with `T09`.

### Scheduled — Phase 1 deliverables that close known gaps

- **`docs/resolver-dry-run.md`** is the durable home of the Phase 1 resolver dry-run report: per
  workbook, rows / confirmed / auto-resolved / unresolved, plus the worst-confidence examples. It is
  a report, so it does not live in `docs/status.md`.
- **Both launchers gain `[q]` and `[v]`.** They are absent today because neither `run_tv.sh` nor
  `run_tv.bat` invokes `docker compose`; Phase 1 adds them, because compose then owns a Postgres
  service and a named volume. `[q]` runs `docker compose down --remove-orphans` and removes images
  matching the `tv-watchlist` prefix while keeping volumes; `[v]` additionally passes `--volumes` and
  drops `tv_postgres_data`.
- **`T01a`** copied and adapted the `.claude/` wiring — `settings.json` with the OS-agnostic `.cjs`
  hook set, `commands/` and `skills/` — done 2026-09-20. **`T01b`** wrote `.env.example`, done
  2026-09-20. **`T01c`** reconciled the READMEs: the `OWNER/REPO` placeholders, the
  eighteen/nineteen workbook count, the 712/722 test count, the Semgrep description, the "There is
  no database." opening, and a phase-flow mermaid diagram the global contract requires of a phased
  project's README — done 2026-09-20.

### Recorded, not fixed

`docs/status.md` section 4 carries the full list of convention gaps: no `LICENSE` file (**ADR-009**
— "Repository licence — OPEN. The owner has not decided. No licence has been chosen and none is
implied by this plan." — with `app/heroes/ATTRIBUTION.md` governing the artwork whatever the
repository's licence becomes, and `T01d` filling ADR-009 in once the owner decides, blocked on that
decision with no due phase), placeholder `OWNER/REPO` badge and clone URLs, no `.claude/` wiring
and no project-level `CLAUDE.md`, launchers missing `[q]`/`[v]`, no `.env.example`, a
`PORT_ASSIGNMENTS.md` row still to come, README counts that have drifted from what is on disk and in
the suite, ESLint without its security plugins, and no release workflow to bump the version fields.
Each is listed rather than quietly patched, because several of them are decisions and not chores —
and each now names the task that closes it. **Superseded within this same heading:** `T01` wrote
the project `CLAUDE.md`, `T01a` added the `.claude/` wiring and `scripts/hooks/`, `T01b` added
`.env.example`, and `T01c` reconciled the READMEs — all on 2026-09-20 (see their subsections above);
the launchers' `[q]`/`[v]` and the release workflow remain open.

### Researched — playback without files, the monthly bill, and what cannot be done

Documentation only; no code changed. The owner asked for one complete plan, with a monthly bill, before any
further building.

- **Findings.** `docs/status.md` §2.20–§2.30 records every finding behind that plan:
  - verified Israeli prices, VAT and card fees;
  - realistic coverage in Israel, as a range, including cheaper combinations of services;
  - a title-by-title check of the titles no subscription carries — only 6 cannot be watched legally
    anywhere;
  - TheTVDB's coverage as a fallback metadata source (95% of works);
  - control from the sofa;
  - what a launcher can and cannot do;
  - the services' terms, and the Streaming Availability API's licence;
  - Disney+, anime and English dubs in Israel;
  - Israeli TV operators;
  - the licensing of metadata and images.
- **ADR-011, proposed: the app never switches a VPN.** Catalogs follow the account's country, and Prime Video
  and Crunchyroll forbid VPN use in their terms.
- **ADR-012, proposed: playback starts as a launcher to the owner's own subscriptions.**
  - One press per title, and Next is a press too.
  - No Autoplay across streaming services.
  - Availability for Israel comes from the Streaming Availability API.
  - Disney+ availability is marked by hand.

### Decided — 2026-09-20: the four open items, and the Phase 3 shape

Documentation only; no code changed. Decided by the owner, in-session, 2026-09-20, and recorded in
`docs/TV_MASTER_PLAN.md` ADR-009 and ADR-011 to ADR-014 before any code. Where an entry above said
otherwise, this entry supersedes it on that point and the earlier text stands as history.

- **ADR-009 — repository licence — DECIDED: all rights reserved.** The repository stays public and
  unlicensed by choice; no `LICENSE` file is added, now or later — the absence is the decision, not a
  gap. `T01d` closes with the record (there is no file to add; `README.md`'s Licensing section is
  reworded in the T01c pass). The `app/heroes/` artwork stays governed by `ATTRIBUTION.md`. This
  supersedes the "Recorded, not fixed" line above that quoted ADR-009 as OPEN.
- **ADR-011 — the app never switches a VPN — DECIDED as proposed.** Availability is looked up for
  Israel only, in every phase; no NordVPN integration, no country picker, no per-title switching.
- **ADR-012 — the launcher — DECIDED as proposed, with its placement moved to Phase 3.** Every
  `NOT_IN_LIBRARY` entry falls through to a one-press launcher onto the owner's own subscriptions,
  beside the Phase 3 player. Availability comes from the Streaming Availability API with
  `country=il`, cached and attributed; Disney+ is marked by hand and opens its `/browse/entity-…`
  page; Next is a press and there is no Autoplay across services; the chat's fetch tool gains a
  denylist of streaming domains. The owner is signing up for the free plan. `T55` is blocked until
  `TV_STREAMING_AVAILABILITY_API_KEY` is present in the root `.env`; until then a `NOT_IN_LIBRARY`
  entry shows the launcher shell with no link.
- **ADR-013 — personal-use basis for playback — new, DECIDED.** A personal, single-instance,
  local-files application: the owner's own files on the owner's own disk, indexed by the owner's own
  Jellyfin on the same LAN, no internet at playback time beyond cached TMDB metadata under its
  six-month cap. The owner read `docs/status.md` §2.20 and §2.25 and accepted the residual risk; the
  "get legal advice before relying on it" line in §2.20 and the §2.11 open question — where the
  video comes from — are closed against this ADR. The deliverable is the honesty mechanism (the
  three-state availability enum, an unresolved view, an explicit "opens on your subscription"), not
  a further review gate. It re-opens only if the build stops being local.
- **ADR-014 — Phase 3 follows Phase 1 directly; Phase 2 is deferred; the Phase 3 shape — new, DECIDED.**

  ```mermaid
  graph LR
    P0["P0 — close: T01a, T01b, T01c"] --> P1["P1 — metadata spine: T04–T33"] --> P3["P3 — playback, with the launcher as the NOT_IN_LIBRARY fallback"]
    P3 -.-> P2["P2 — ten-foot browser UI: T34–T45 (deferred, not cancelled)"]
  ```

  - **Order.** Phase 0 close → Phase 1 → Phase 3, with the ADR-012 launcher folded in as the
    `NOT_IN_LIBRARY` fallback. **Phase 2 (T34–T45) is deferred, not cancelled**; its task rows read
    "2 (deferred)". `T52` depends on `T33`, not `T45`. Phase 3 adopts
    `GET /api/categories/{id}/entries` for its availability-and-progress layer only; the workbook
    `CategoryDetail` stays the editing contract, unchanged. This supersedes the P0 → P1 → P2 → P3
    sequence drawn under "Decided — the phase sequence" above, and its "no video files on this
    machine yet": `T46` is satisfied as of 2026-09-20 with the owner's own files, indexed by `T47a`.
  - **Jellyfin runs as a compose service.** `jellyfin/jellyfin:12.1`, `restart: unless-stopped`,
    named volumes `tv_jellyfin_config` and `tv_jellyfin_cache`, the media directory bind-mounted
    read-only from `${TV_JELLYFIN_MEDIA_HOST:-./media}` to `/media` (with `/media/` gitignored),
    healthcheck `GET /health`, host port `${TV_JELLYFIN_PORT:-8096}:8096`. **The backend takes no
    `depends_on` edge to `jellyfin`** — it is an optional peer, and the workbook app must boot and
    serve when it is stopped, exactly as it boots without provider credentials. Under compose the
    backend reaches it as `http://jellyfin:8096` (`TV_JELLYFIN_BASE_URL`, set in `environment:`);
    the host launchers reach it as `http://localhost:8096` from the root `.env`. No `@jellyfin/sdk`:
    only the backend talks to Jellyfin, over `httpx`. Deliverable 3.7 and `T47` close on this. The
    "Allocated — Postgres host port 5525" entry above is scoped to Phase 1 by this one: the project
    binds `5284`, `8284` and `5286` (live), `5525` (Phase 1) **and `8096` (Phase 3)**, each
    registered in `PORT_ASSIGNMENTS.md` in the commit that binds it (`8096` with `T47a`).
  - **Schema — two tables and a column, minor bump, recorded before code.** `jellyfin_item`, the
    `tmdb_id → Jellyfin Id` index — one row per movie, series and episode the library holds,
    maintained by `services/library_sync.py`; `streaming_offer`, the launcher's cached Streaming
    Availability lookups for Israel plus the hand-marked Disney+ rows; and a nullable
    `title.jellyfin_item_id`, the `AMBIGUOUS` picker's remembered choice — a per-title setting, not
    per file. All three land in **Phase 3's own Alembic revision**, not Phase 1's: the first revision
    holds the eleven Phase 1 tables, and the tree reads thirteen only after Phase 3's revision runs.
    Also decided, under the owner's standing autonomy rule: **`curated_entry_episode` is renamed
    `curated_entry_item`** now, before any migration exists —
    ADR-010 had left the rename open "to settle before T24", and a rename after the first migration
    would cost a revision. The two mentions above, under "Decided — dual store" and "Decided — Next
    and Autoplay follow the curated order", now carry the new name; ADR-010's own text keeps the old
    one as history with a one-line note.
  - **Position.** The plan's model stands — a `progressed` `watch_event` every 5 seconds from the
    player, carrying `source = 'player'` and never `'jellyfin'` (the position comes from the browser,
    the media from Jellyfin; `'jellyfin'` stays free for server-reported sessions), `position_seconds`
    an integer converted once at the boundary (Jellyfin .NET ticks ÷ 10 000 000;
    `<video>.currentTime` rounded), the four-value `Watched?` mirror on completion —
    **plus a `Position (s)` column** in each sheet, written **only on pause, ended and unmount**,
    never on the 5-second tick, through `Catalog._write`, so a hard kill (sleep, crash, a closed
    browser) still leaves something in the workbook. It is a projection, never read as truth.
    `ColumnRole` therefore gains **`"identity"`** (the hidden `Row ID`, at `T22` in Phase 1) **and
    `"position"`** (visible in Excel, at `T53` in Phase 3), both app-owned and both excluded by the
    reader from `columns` and `WatchRow.cells`, so the UI grid is unchanged and `RowWrite` can never
    address them.
  - **The stream is proxied by the backend.** A `<video>` element cannot send an `Authorization`
    header, so `GET /api/playback/{jellyfin_item_id}/stream` fetches Jellyfin's `/Videos/{id}/stream`
    with the key in a header and relays it: `Range` passed through both ways, `Content-Type` passed
    through, `Accept-Ranges: bytes` set, the body streamed and never buffered. The key never leaves
    the server, and because the `<video src>` is same-origin the nginx CSP needs no `media-src`.
  - **New settings, all `TV_`-prefixed.** `TV_JELLYFIN_BASE_URL`, `TV_JELLYFIN_API_KEY`
    (`SecretStr`), `TV_JELLYFIN_PORT`, `TV_JELLYFIN_MEDIA_HOST` (compose only) and
    `TV_STREAMING_AVAILABILITY_API_KEY` (`SecretStr`). The owner creates the Jellyfin API key in
    Jellyfin's own UI (Dashboard → API Keys) and types both Jellyfin values into the root `.env`
    themselves; no agent writes a credential.
  - **Tasks, deliverables and gate.** `T46` satisfied 2026-09-20; `T47` decided (12.1, no SDK); new
    `T47a` (the compose service, the `8096` registry row in the same commit, `/media/` gitignored),
    `T48` (`clients/jellyfin_client.py`), `T49` (`jellyfin_item` + `services/library_sync.py`), `T50`
    (episode join), `T51` (`services/availability.py`, the `Availability` enum,
    `CuratedEntryRead.availability` / `.jellyfin_item_id`), `T52` (`api/playback.py` stream proxy,
    the `<video>` overlay, the SPA reading `/entries` for the availability layer), `T53` (position
    reporting and the `Position (s)` column), `T53a` (Next / Autoplay), `T55` (the Streaming
    Availability client, `streaming_offer`, the One Piece episode-matching proof call, the chat
    denylist), `T56` (`AMBIGUOUS` picker: `PATCH /api/titles/{title_id}/jellyfin-item` + modal),
    `T57` (unresolved view, reachable from main nav), `T58` (launcher UI for `NOT_IN_LIBRARY`) and
    `T54` (gate audit). Deliverables 3.5 (browser `<video>` against the backend proxy) and 3.7 are
    decided; 3.10 (launcher), 3.11 (unresolved view), 3.12 (`AMBIGUOUS` picker), 3.13 (Jellyfin
    compose service) and 3.14 (`Position (s)` column + `ColumnRole` `"position"`) are added; gate
    10.3's item 1 reads "satisfied 2026-09-20" and the gate gains an item per addition — among them
    the proxy honouring `Range` (206) through a mock Jellyfin, a test proving zero workbook writes on
    the 5-second tick, the backend booting and serving with Jellyfin stopped, and the pinned `12.1`.
- **Corrected.** The plan's Jellyfin figure was right, not the brief's `10.9.x`: 12.0 went stable on
  2026-09-08 and 12.1 followed on 2026-09-15 (verified against Docker Hub and GitHub). `12.1` is the
  pinned version.

### Added — the `.claude/` wiring (T01a)

Tooling only; no application behaviour changed, so this folds into the pending `0.2.0` heading rather
than opening one of its own (the one-unreleased-heading rule, `CLAUDE.md` §17.4).

- **`scripts/hooks/` — committed, seven Node `.cjs` files, LF-pinned by `.gitattributes:27`.**
  `hookUtils.cjs` is a verbatim copy of the fleet reference (`llm-knowledge-base`, byte-identical to
  `oft-frontend`'s), so `readHookPayload`, `getToolFilePath`, `isSensitivePath`, `uncommittedFiles`
  and `emit` behave the same everywhere. Every hook reads its payload from **stdin**, never from a
  `$CLAUDE_*` variable, and none is a shell script — cmd.exe cannot parse a shell hook body and
  `python3` is missing on Windows.
- **`pre-tool-use.cjs` and `pre-compact.cjs` are new to the fleet** — neither reference project has
  them. `pre-tool-use` denies a `Write`/`Edit` to `.env`, `.env.*` (but **not** `.env.example`,
  `.sample` or `.template`), `credentials.*`, `secrets.*`, `*.pem`, `*.key`, `*.p12`, and to **any
  `*.xlsx`**, emitting both the `{"decision":"block","reason":…}` shape the global contract names and
  the `hookSpecificOutput.permissionDecision = "deny"` shape Claude Code documents. The workbook rule
  is the project-specific half: a tool writing an `.xlsx` would bypass the freshness guard, the
  snapshot, the Excel-lock check and the atomic swap at once, and `Catalog._write` is the only path
  (`CLAUDE.md` §3.4).
- **`session-start.cjs`** prints a 19-line banner: the four documents to re-read in order, the live
  workbook count read off disk, the ADR-014 build order (P0 close → P1 → P3 → P2 deferred), both
  manifest versions and the pending `docs/versions.md` heading, the first eight lines of
  `docs/status.md`, and four standing reminders.
- **`post-tool-use.cjs`** injects one contextual reminder per edited area — the Excel layer, an ORM
  model, an Alembic revision, a contract file, a service, the UI, `config.py` — and stays silent
  otherwise.
- **`stop.cjs`** notes uncommitted files and, conditionally, that `docs/` was not touched, that a
  workbook changed on disk, or that the UI changed without the layout guard. It **never suggests
  running git**; git is the owner's (`CLAUDE.md` §17.5). `stop-memory.cjs` is the fleet's verbatim
  memory-review prompt.
- **`scripts/hooks/hooks.test.cjs` — 31 tests on Node's built-in `node:test`, no dependency added.**
  Ten blocked paths, three allowed, an empty payload, four `post-tool-use` rules, the banner (content
  and its ≤20-line budget), `pre-compact`, `stop-memory` and `stop`. **Run it by naming the file —
  `node --test scripts/hooks/hooks.test.cjs`.** The directory form, `node --test scripts/hooks/`,
  fails on Node 24; the file form is the one that works, and it is the form the docs quote.
- **`.claude/settings.json`, `.claude/commands/` (6) and `.claude/skills/` (5) are local, not
  committed** — `.gitignore:27` ignores `.claude/`, which is the fleet convention. `settings.json`
  wires `SessionStart`, `PreToolUse`/`PostToolUse` (both matching `Write|Edit`), `PreCompact`
  (`auto|manual`) and two `Stop` hooks, each as
  `node -e "…require(p.join(process.env.CLAUDE_PROJECT_DIR||process.cwd(),'scripts','hooks','<hook>.cjs'))"`.
  The commands are `scaffold`, `review`, `pre-commit`, `validate`, `phase-status`, `new-model`; the
  skills are `phase-awareness`, `excel-safety-protocol`, `data-driven-check`, `validation-protocol`,
  `dual-store-protocol`. Every one opens with the same re-read block and cites this project's real
  files. Because the wiring is gitignored, a fresh clone gets the hooks but must be handed
  `settings.json`, `commands/` and `skills/` separately.

This closes `T01a` of the Phase 0 gate (`docs/TV_MASTER_PLAN.md` §10.0). What travels is
`scripts/hooks/` alone — `.claude/` is gitignored (`.gitignore:27`), so the hooks are in the
repository and the wiring that invokes them is not. The rule that writes to `.env*` are blocked by a
hook rather than by discipline is true from this change onward.

### Added — `.env.example` (T01b)

The repository had no `.env`, no `.env.example` and no `.env.*` at all, while `.gitignore:30-32`
already carried the `!.env.example` negation for a file that did not exist. It exists now, at the
repository root — the only place a `.env` lives — with **sixteen `TV_`-prefixed variables**, each on
its own line under its own comment line:

- **Live today (three):** `TV_BACKEND_PORT`, `TV_FRONTEND_PORT`, `TV_LIBRARY_HOST`.
- **Phase 1 (eight):** the five `TV_POSTGRES_*` values, plus `TV_TMDB_READ_ACCESS_TOKEN`,
  `TV_TVDB_API_KEY` and `TV_TVDB_PIN`.
- **Phase 3 (five), named now so the shape is settled before the code that reads them:**
  `TV_JELLYFIN_BASE_URL`, `TV_JELLYFIN_API_KEY`, `TV_JELLYFIN_PORT`, `TV_JELLYFIN_MEDIA_HOST` and
  `TV_STREAMING_AVAILABILITY_API_KEY`.

Every credential is a blank placeholder — the owner types the real values and no agent writes one,
which the `T01a` `pre-tool-use` hook now enforces for `.env` and `.env.*` while deliberately allowing
`.env.example` itself. No line carries an inline comment anywhere in the file: docker compose and
python-dotenv disagree about them, so each comment gets a line of its own.

`app/backend/tests/test_env_example.py` holds **19 tests** over the shared
`app/backend/tests/env_example_support.py` reader — the file exists at the repository root, it lists
exactly those sixteen names once each and in order, each of the five secrets is blank, each of the
ten non-secrets carries its documented default, every variable has a comment line directly above it,
and no line carries an inline comment. This closes `T01b` of the Phase 0 gate.

### Reconciled — both READMEs (T01c)

`README.md`'s known backlog, cleared in one pass rather than piecemeal:

- **`OWNER/REPO` is gone.** Both badge URLs and both clone commands name the real remote,
  `amrambouskila/watch-list`.
- **"There is no database." is gone**, replaced by the dual store stated plainly: the workbooks stay
  authoritative for order and curation, and from Phase 1 a Postgres projection sits beside them,
  derived from the sheets and never the other way round (ADR-001).
- **A phase-flow diagram**, which the global contract requires of a phased project's README:
  `P0 → P1 → P2 → P3` as the numbering, **with the note that the build order is P0 → P1 → P3 → P2**
  because ADR-014 defers Phase 2. Drawing the numbering without that note would have contradicted the
  plan on the page that a new reader reads first.
- **The counts agree with the tree.** Nineteen workbooks, not eighteen — corrected in `README.md`, in
  `.gitignore:4` and in the `docker-compose.yml` bind-mount comment, the three places still carrying
  the old figure. The pytest number moved off the stale `712` to the count measured during the pass,
  `741`; `T04` has since taken it to `745`, and `T33` re-measures before the owner commits Phase 1.
- **The Semgrep description names the six packs the workflow actually runs** — `p/default`,
  `p/owasp-top-ten`, `p/python`, `p/typescript`, `p/react`, `p/docker`, at `--severity ERROR` — and
  says outright that `--config auto` is not used.
- **The Ports table carries `8096`** (Jellyfin, bound by `T47a`) **and `5525`** (the Phase 1 Postgres
  projection, allocated but not yet bound), and the Docker section describes `jellyfin` as an optional
  peer that nothing `depends_on`.
- **Licensing states ADR-009 as decided** — the repository is public and unlicensed by choice, no
  `LICENSE` file exists and none will be added, with `app/heroes/ATTRIBUTION.md` still governing the
  artwork whatever the repository's licence is.

`app/README.md` was reconciled alongside it. This closes `T01c`, the last of the Phase 0 five.

### Added — the `jellyfin` compose service (T47a)

The first service to join the stack beside `backend` and `frontend`, and the change that makes this
heading minor rather than patch.

- **`jellyfin/jellyfin:12.1`**, pinned — 12.0 went stable 2026-09-08 and 12.1 followed on 2026-09-15 —
  with `restart: unless-stopped`, named volumes `tv_jellyfin_config` and `tv_jellyfin_cache`, the
  media directory bind-mounted read-only as `${TV_JELLYFIN_MEDIA_HOST:-./media}:/media:ro`, a
  `GET /health` healthcheck, and host port `${TV_JELLYFIN_PORT:-8096}:8096`.
- **No `depends_on` edge from `backend`.** Jellyfin is an optional peer: the workbook app must boot
  and serve every existing endpoint with it stopped, exactly as it boots without provider
  credentials. The edge would have made the whole app unstartable whenever the media server was down.
- **`/media/` is gitignored**, so the compose file validates on a clone with no media on disk.
- **`PORT_ASSIGNMENTS.md` carries the `8096` row** in the final host-listener map and a matching
  bullet in the `Personal/TV` inventory, in the same change that binds the port (Definition of Done
  item 13). With it the project binds `5284`, `8284` and `5286` (live) and `8096` (now); `5525`
  remains allocated for Phase 1 and unbound.

**The container is not yet running, and that is an environment problem rather than a configuration
one.** On this Mac, Docker Desktop's VM cannot pull any image while NordVPN's Shield network system
extension is active: the host reaches Docker Hub, the VM transfers nothing, and restarting Docker
Desktop does not help. The owner actions — pause NordVPN or add Docker to its exceptions (or run
compose on the Windows machine), then `docker compose up -d jellyfin`, create the admin account at
`http://localhost:8096/web`, mint an API key under Dashboard → API Keys, and type
`TV_JELLYFIN_API_KEY`, `TV_JELLYFIN_BASE_URL` and `TV_JELLYFIN_MEDIA_HOST` into the root `.env`,
alongside a free `TV_STREAMING_AVAILABILITY_API_KEY` — are recorded in `docs/status.md`.

### Added — the data layer's dependencies (T04)

The first Phase 1 code change. Three runtime dependencies, added with `uv add` so `pyproject.toml`
and `uv.lock` move together:

| Declared | Resolved |
|---|---|
| `sqlalchemy[asyncio]>=2.0.36` | 2.0.54 |
| `asyncpg>=0.30.0` | 0.31.0 |
| `alembic>=1.14.0` | 1.20.0 |

`greenlet` arrives transitively with the `asyncio` extra and is deliberately **not** pinned
separately. No sync Postgres driver is installed, so Alembic will run on the same
`postgresql+asyncpg://` URL the app does and the project keeps exactly one connection string.

`app/backend/tests/data/test_data_dependencies.py` asserts each import and each floor, so a lockfile
edit that dropped or downgraded one fails the suite rather than the first migration. The backend
suite now collects **745** tests and passes; `ruff check .` and `ruff format --check .` are clean.
The three packages enter the `sast` stage's audit surface through `uv export` → `uvx pip-audit` with
no change to the job.

Minor as of 2026-09-20, when `T47a` bound `8096`. Phase 1's remaining code — new tables, endpoints
and a contract change, all minor — lands under this same heading, per the one-unreleased-heading
rule.

### T05 — data layer foundations

`data/base.py`, `data/session.py` and `data/enums.py` (the eleven Phase 1 enums) land under
`app/backend/src/tv_watchlist/data/`; `Settings` gains the five `postgres_*` fields, the
`tmdb_read_access_token` / `tvdb_api_key` / `tvdb_pin` `SecretStr` fields, and `database_url`,
computed with `sqlalchemy.engine.URL.create(...).render_as_string(hide_password=False)` —
`quote_plus` was tried first and rejected because it turns a space into `+`. `env_file` is now the
absolute repo-root `.env`, so `tests/lifespan_support.py` and an autouse `declared_env_file` session
fixture blank it before `get_settings()` ever runs, keeping the owner's real credentials out of the
suite. No `Availability` enum and no `jellyfin_*` / `streaming_availability_api_key` fields land here
— those are Phase 3's, per the no-stubs-by-phase ruling. 34 tests.

### T06 — the eleven ORM models

One model per file under `data/models/` — `category`, `curated_entry`, `curated_entry_item`,
`title`, `season`, `episode`, `episode_order`, `external_id`, `artwork`, `watch_event`,
`sync_state` — carrying 34 named `CHECK` constraints under the `ck_` naming template. Every
lazy-loadable relationship is `lazy="raise_on_sql"`, paired with `passive_deletes=True` on
`Title.seasons` and `Season.episodes` so a cascade needs no round trip. Three deferrable uniques;
`title.tmdb_id` is nullable (risk register R2 — a handful of OVAs will never match); `watch_event`
carries `one_subject` (`num_nonnulls(...) = 1`) plus `kind_matches_column`, and `artwork` carries its
own `kind_matches_column`. 34 tests.

### T07 — Alembic wiring

`alembic.ini` carries no `sqlalchemy.url` — the DSN comes from `Settings.database_url` at runtime, so
the project keeps one connection string for the app and for migrations both. `alembic/env.py` bridges
the async engine into Alembic's sync migration context and filters the two Phase 1 views out of
autogenerate via `include_object`; `fileConfig(..., disable_existing_loggers=False)` keeps the app's
own loggers alive during an in-process migration. `script.py.mako` is ruff-clean. The append-only
trigger's function and its `CREATE TRIGGER` are two separate `op.execute()` calls, because asyncpg
prepares one statement at a time. `data/alembic_support.py`; 6 tests, asserted offline against the
rendered `alembic upgrade head --sql` DDL — no Postgres is reachable on this Mac.

### T12 — clients scaffolding

`clock.py`, plus `clients/errors.py`, `clients/http_guard.py`, `clients/rate_limiter.py`,
`clients/transport.py` and `clients/response_cache.py`; `constants.py` gains the provider block. The
SSRF guard reuses the existing `assert_public_http_url` shape (boundary B10) and survived 19
adversarial probes; a refused request closes its transport rather than leaving a connection dangling.
The rate limiter is one token-bucket-throttled worker per upstream, never per-request fan-out, because
TMDB's undocumented ~40 req/s budget is shared across the whole egress IP. 77 tests.

### T21 — the hidden Row ID column

`workbook/identity.py` — the one new module under `workbook/` — writes and hides a `Row ID` column at
the far right of a sheet (width 38); `Catalog.ensure_identity_column` and `Catalog.write_row_ids` both
go through `Catalog._write`, the same funnel every other mutation uses, because a second openpyxl
write path is the single most damaging change available in this repo (`CLAUDE.md` §3.4). 47 tests run
against copies of all nineteen real workbooks and assert `tests/snapshot.py:fingerprint()` is
unchanged — the column lands without disturbing a single table ref, dropdown or conditional format.

### T22 — ColumnRole gains identity

`ColumnRole` gains `"identity"` on both sides — `models/column_spec.py`'s `Literal` and
`src/types/ColumnSpec.ts` — with the member order `order, title, watch, identity, other` (identity
**before** other) on both the Python literal and the pinned TypeScript test. `workbook/schema.py`'s
`_role_for` learns the `Row ID` alias, `reader.read_category` excludes identity columns from both
`columns` and `WatchRow.cells` so the UI grid is unchanged, and `Catalog.projection` is the
reconciler's own uncached read path — the one place that does carry the ids the UI never renders.
`CategoryCreate` now rejects any of the app-owned header aliases in a submitted `columns` list —
`POST /api/categories` naming `Row ID` (or a header `normalize_header` maps onto it) is refused with
**422** rather than silently creating a column the reader would then hide — which was the fix
round's one open item. 9 tests in `tests/models/test_category_create_columns.py`. This is a
data-contract change, recorded here as a **minor bump, before code**, per the change policy
(§17.1). **Complete.**

### T08 — the first Alembic revision

`alembic/versions/0001_phase_1_schema.py` raises all eleven Phase 1 tables, two read-only views —
`episode_watch_state` and `curated_entry_watch_state`, the latter carrying a movie-slot roll-up
alongside the episode roll-up — and the append-only trigger as two separate `op.execute()` calls
(the function, then `CREATE TRIGGER`), because asyncpg prepares one statement at a time. The
hand-written `downgrade()` drops the trigger, then the views, then the tables in foreign-key order —
autogenerate does not know how to reverse either. `tests/data/test_first_revision_sql.py` (21 tests)
asserts the rendered `alembic upgrade head --sql` DDL offline — the verbatim
`(subject, occurred_at DESC, recorded_at DESC, id DESC)` tie-break chain, no fourth `DISTINCT ON`
column, and the FK-ordered `DROP`s — because no Postgres is reachable on this Mac.
`tests/data/test_first_revision.py` (20 tests) exercises the same revision live: the precedence
rule, all five roll-up branches, and the `watch_event` trigger's `SQLSTATE 23001` refusal. Both
suites skip loudly rather than silently when no Postgres answers, and run for real in CI's service
container. Complete.

### T09 + T11 — the Postgres compose service, the migrating entrypoint, the registry row

`docker-compose.yml` gains a fourth service, `postgres` (`postgres:16-alpine`), published
`127.0.0.1:${TV_POSTGRES_PORT:-5525}:5432` — **loopback only** (Ruling 24: every listener this
project publishes binds loopback, and the default credentials are dev-only), backed by the named
volume `tv_postgres_data` and a `CMD-SHELL pg_isready` healthcheck; `backend` gains
`depends_on: postgres: condition: service_healthy` plus `TV_POSTGRES_HOST=postgres` and
`TV_POSTGRES_PORT=5432` (the container's own port — 5525 is the host publication only).
`app/backend/Dockerfile` now `COPY`s `alembic.ini`, `alembic/`, `data/` and `docker-entrypoint.sh`;
the entrypoint runs `alembic upgrade head` then `exec uvicorn`, so under `restart: unless-stopped` a
persistently failing migration is a crash loop **by design** — the API never serves an unmigrated
schema, and the restarts are the visible symptom, not a silent half-working container. 46 tests
across `tests/compose_support.py`, `tests/test_compose.py` and `tests/test_docker_entrypoint.py`.
`README.md`'s ports table carries the `5525` row and `PORT_ASSIGNMENTS.md` carries the final-map row
plus the `tv` / `tv_test` database-name bullet under the `Personal/TV` inventory — both already
landed on disk. **Live bring-up is unverified**: Docker Desktop's VM cannot pull `postgres:16-alpine`
while NordVPN's Shield extension is active on this Mac, the same block already recorded against the
`jellyfin` pull. One owner action stands ahead of the next commit: `app/backend/data/franchise_prefixes.json`
is untracked, and the Dockerfile's new `COPY data ./data` line means a fresh clone's image build
fails without it staged in the same commit as the Dockerfile change.

### T10 — CI runs the database for real

`test-backend` in `.github/workflows/ci.yml` gains a `services: postgres` block
(`postgres:16-alpine`, database `tv_test`, port 5525) and job-level `TV_POSTGRES_*` env plus
`TV_REQUIRE_POSTGRES: "1"` — under that flag the database-gated tests **fail** rather than skip, so a
CI run can never quietly skip past the one thing Phase 1 must prove works. An "Alembic round trip"
step (`upgrade head && downgrade base && upgrade head`) runs before pytest, matching the master
plan's full-round-trip gate rather than a single-step reversal. `tests/conftest.py` gains
`db_session` — one connection, `join_transaction_mode="create_savepoint"`, `expire_on_commit=False`,
the outer transaction always rolled back, so every test starts from a clean database without a
per-test `CREATE`/`DROP`. `tests/database_support.py` provides `require_disposable_database`, a
`*_test`-name guard in front of a `DROP DATABASE … WITH (FORCE)` run against the maintenance
database, so a misconfigured `TV_POSTGRES_DB` can never point the drop at `tv`. 16 tests across
`test_migration_round_trip.py` (2, including `alembic check` parity), `test_watch_event_append_only.py`
(3), `test_db_session.py` (1) and `test_database_support.py` (10). Approved; one polish round is
open in re-review.

### T13 — the TMDB client

`clients/tmdb_client.py`, ten methods plus `build_tmdb_client`, sends the v4 Read Access Token as a
bearer header only — never the v3 `api_key` query parameter. Every response lands in a frozen,
`extra="ignore"` Pydantic model under the new `models/tmdb/` package (17 files). Requests are
conditional wherever TMDB supports it — `If-None-Match` from the cached `etag`, falling back to a
payload-digest comparison when TMDB sends none — so a nightly refresh across nineteen workbooks does
not rewrite rows that have not changed. `TMDB_CACHE_CEILING_DAYS = 170` is the self-imposed margin
inside TMDB's hard six-month cache-retention term. 21 recorded response fixtures, each with a header
sidecar, live under `tests/fixtures/tmdb/`; `tests/provider_fixtures.py` drives `httpx` through a
`MockTransport` built from them, so the suite makes zero live calls. 119 tests
(`tests/clients/test_tmdb_client.py` 68, `tests/models/test_tmdb_models.py` 51) — no credential
appears in any fixture body or sidecar. Approved; fix round 1 is open against Rulings 25 and 26: an
unknown cache age (`sync_state.last_success_at IS NULL`) must renew rather than trust a 304 when a
validator is present, and `CacheOutcome` gains a fifth member, `failed`, so a 401/404/429 refusal or
an invalid body is distinguishable in the log from a genuine `throttled` wait.

### T14 — the TheTVDB v4 client

`clients/tvdb_client.py` logs in with `apikey` plus the subscriber `pin` (the End-User Subscriptions
funding model), caches the returned bearer token for its one-month life and renews proactively at
~25 days rather than waiting on a 401 — TheTVDB's login has no refresh endpoint. The season-type
vocabulary is never hard-coded: it is read from `GET /v4/seasons/types` at request time and cached,
because TheTVDB's OpenAPI document lists its seven live types as *examples*, not an enum. Episode
names are requested through the `/eng` language variant, since TheTVDB's default is the original
language. A `200` response carrying an empty `episodes` array for an unrecognised season type is
treated as **unknown, never as "no episodes"** — the one shape that has already destroyed real data
elsewhere — and page count plus total are logged so a truncated fetch cannot pass as a complete one.
Eight models under the new `models/tvdb/` package. Recorded fixtures for One Piece (TVDB id 81797)
cover login, `/seasons/types`, the absolute/dvd/official episode pages, the unknown-type 200-empty
case, `/eng` translations and `/updates`. 85 tests (`tests/clients/test_tvdb_client.py` 50,
`tests/models/test_tvdb_models.py` 35). Implemented; review is running. A fix round after T13's own
fix round lands consolidates the refusal/retry-after/scrub helpers T14 duplicated from the TMDB
client into the shared `clients/transport.py` (Ruling 31).

### T15 — the Postgres response cache

`ingest/sync_cursor.py`'s `PostgresResponseCache` makes `sync_state` earn its name as the provider
response cache, not just its ledger: `lookup`/`store`/`record_failure` carry the ETag, `Last-Modified`
and payload-digest comparison that let a TMDB or TheTVDB call skip a network round trip entirely, and
`is_due`/`past_ceiling`/`due_for_refresh` are the module-level, argument-only functions (`backoff_delay`,
`attempt_is_due`, `success_past_ceiling`) that prove the backoff schedule and the six-month cutoff on a
workstation with no Postgres reachable — only the SQL itself needs the service container. `ceiling_cutoff`
moved to `clients/response_cache.py` so both the cache and the TMDB client compute the same six-month
boundary from one function rather than two. `MAX_LAST_ERROR_CHARS` caps `sync_state.last_error`, and a
provider error is redacted before it is stored: a `Bearer …` token is replaced with `Bearer [redacted]`
and every C0 control character, CR and LF included, is stripped, because `last_error` is provider-supplied
text that later reaches a log line and a reviewer's screen (CLAUDE.md section 10, header/log injection).
There is still no Redis and no second datastore — `sync_state` is the whole cache, exactly as designed.
Every provider leg the ingest runs is gated on `is_due`/`past_ceiling` before it spends a request. 41
tests in `tests/ingest/test_sync_cursor.py`.

### T16 — the resolver's match key

`resolver/match_key.py` and `resolver/franchise.py`, backed by `data/franchise_prefixes.json`,
normalise a title into the deterministic key the resolver joins on: lowercased, diacritics folded
through an explicit transliteration table (ł → l, ø → o, æ/œ → ae/oe, đ → d, þ → th, ð → d — Ruling
21), `×` folded to `x` (Ruling 19), punctuation stripped, a leading article dropped, and the release
year appended when known. Measured against all 996 rows across all 19 workbooks: 926 `Release` cells
parse, 922 of those to a year, and the only literal that does not parse is `"TBA"` (Ruling 23) — zero
empty match keys and zero collisions between genuinely distinct works. 91 tests
(`tests/resolver/test_match_key.py` + `test_franchise.py`), 100% coverage. Complete.

### T17 — the Unit span parser

`resolver/span.py` (`SpanParse`, `parse_unit`) turns a sheet's free-text `Unit` cell into a span over
a title's own numbering, never guessing where a parse would be ambiguous. Measured against all 996
`Unit` cells before the current fix round: 273 confident, 439 flagged, 284 unresolved (movie 273,
season 209, episodes 161, special 69, unknown 284 — 84 of the unresolved are WWII's `Event` column,
which carries no unit vocabulary at all, not a parser gap). 103 tests (`tests/resolver/test_span.py`),
100% coverage. Implemented; fix round 1 is open against three rulings: a blank `Unit` cell is not
`movie @ 1.00` — it parses at confidence 0.50, kind decided from the sheet's own Type/Format cell
where the sheet has one, else `movie`, with T18 allowed to raise confidence to 1.00 once TMDB's
`media_type` confirms it (Ruling 27); `SpanParse` gains read-only `episode_span` / `season_span`
properties so downstream consumers never read the raw `span_start`/`span_end` fields directly
(Ruling 29); and a season-scoped shape (`S5 E10-19`, `Season 2 E26-37`) emits `order_type=None`
rather than `aired`, because 8 of its 53 rows carry series-wide numbers that only the title's own
orders can confirm (Ruling 30).

### T18 — title resolution

`resolver/{resolution_request,candidate,scoring,verification,title_resolution}.py` turn one workbook row
into a TMDB match, or an honest refusal to guess one. Two passes, stopping at the first that produces a
verified candidate: a franchise-expanded top-level search, then — inside a matched parent series — its
seasons and season-zero episodes. Scoring (`score_candidate`) rewards title match, year agreement, media
type and plausibility, and deliberately never popularity, because TMDB's own popularity order is how a
2025 remake would win a row about a 1978 film. Confidence is reported on five rungs —
`EXACT_WITH_YEAR_CONFIDENCE = 0.95`, `EXACT_WITHOUT_YEAR_CONFIDENCE = 0.80`,
`WEAKER_TITLE_CONFIDENCE = 0.65`, `SECOND_PASS_CONFIDENCE = 0.50`, `UNRESOLVED_CONFIDENCE = 0.00` — and
never `confirmed`, because that rung is a human's alone, awarded in the review queue (T30).

Four rulings this task settled, each because a plan text turned out wrong once measured:

- **Ruling 33.** A season- or episode-level match exposes `title_tmdb_id` as the PARENT tv id, carrying
  the parent's own name and year, with the matched season or episode described separately by
  `resolver/candidate.py`'s `MatchedUnit`. `title.tmdb_id` never holds a season id (CLAUDE.md section
  5.13 `title`, section 10.3 B14).
- **Ruling 34.** The plan's idea of also searching a trailing roman numeral in its arabic form is
  retired: measured over all 996 rows it rescues none, TMDB spells `Blade II` exactly as the sheet does,
  and every extra form is another live call spent for nothing.
- **Ruling 35.** A tie on equal score is `unresolved`, with `chosen: None`, and a note listing every tied
  candidate up to `MAX_ALTERNATIVES` — `_ambiguous` in `title_resolution.py`. The page cannot tell the
  candidates apart, so nothing here breaks the tie by an arbitrary rule; a human does, in the review
  queue (CLAUDE.md section 18.2).
- **Ruling 37.** `TitleMatch.EXTENDED` — TMDB's title equals a leading segment of the row's, cut at a
  `:` or a space-surrounded dash — is accepted for **films only**, with an agreeing year required, at
  confidence 0.65 and scored below both `EXACT` and `CONTAINED` (`TITLE_SCORES[EXTENDED] = 0.25`,
  deliberately the lowest of the three accepted matches). It replaces section 18.2 rule 3's estimate
  with a measurement: it is the largest recoverable class in T31's dry run. For a series the same shape
  names a season of a parent, which is the second pass's job, not this rung's.

101 tests (`tests/resolver/test_title_resolution.py` 40, `test_scoring.py` 39, `test_verification.py`
22); the whole `resolver/` package — match key, franchise, span, title resolution, dry run — now stands
at 326 tests, 100% coverage. Complete.

### T19 — the TMDB ingest

`ingest/tmdb_ingest.py` writes a resolved title into `title` / `season` / `episode` / `external_id` /
`artwork`, backed by `ingest_outcome.py`, `artwork_candidate.py`, `services/tmdb_key.py` and
`services/artwork_cache.py`. Three rules shape it: minutes become seconds exactly once
(`minutes_to_seconds`, CLAUDE.md section 11.2 rule 7), an unchanged row produces no statement — every
write is preceded by a read and a field-by-field comparison, so a second pass over identical bytes never
touches `updated_at` — and numbering is stored verbatim, never turned into a rank here (`episode_order`
is T20's job): One Piece's season 2 is written 62-77, exactly as TMDB carries it, never renumbered 1-16.

`services/tmdb_key.py` is the canonical pointer grammar `watch_event.tmdb_key` needs to survive a full
metadata rebuild — `movie:603`, `tv:1399`, `tv:1399:s2:e5` — with `tmdb_key()`/`parse_tmdb_key()` as a
matched pair (no leading zeros, so a key can never be spelled two ways) and `hero_store.read_capped` made
public so `artwork_cache.py` reuses it instead of a second size-capped reader.

`services/artwork_cache.py` composes a TMDB image URL from `secure_base_url + size + remote_path` — never
from a payload-supplied URL — and reuses boundary B5's whole downloader: the same SSRF guard, the same
`follow_redirects=False`, the same magic-byte check, the same resolve-and-confine destination check.
Every refusal is logged and returns `None` rather than raising, because an ingest that could not cache one
poster has still ingested the title. `MAX_ARTWORK_BYTES_PER_RUN = 200_000_000` caps a whole run's artwork
spend, on top of the existing per-file `MAX_HERO_BYTES` cap (CLAUDE.md section 10.3, B11).

**Ruling 32.** `curated_entry.match_key` and the matching TMDB-side column both stay `String(255)` rather
than growing to fit the longest observed title; every value that would not fit is clipped, and every clip
is logged (`clipped table=… column=… from=… to=…`) so a truncation is visible rather than silent.

A digest match — TMDB's response is byte-identical to what is already stored — does **not** advance
`sync_state.last_success_at`, because no fetch actually happened; only a genuine round trip earns that
stamp. 69 tests in `tests/ingest/test_tmdb_ingest.py`. Complete.

### T20 — episode orders

`ingest/episode_orders.py` computes the one ordering this app derives itself — the aired rank — and
stores every ordering TheTVDB offers, all as `episode_order` rows sharing one shape: `sequence`, a dense
1-based rank within one numbering, is what the app computes with, and `order_season_number` /
`order_episode_number` travel beside it as what the UI prints (CLAUDE.md section 11.2, rule 9). The aired
walk excludes season 0 — the specials bucket — and gives it its own ordering instead
(`SPECIALS_ORDER_TYPE = OrderType.ALTERNATE.value`, labelled `SPECIALS_ORDER_LABEL = "Specials"`),
because without that exclusion forty specials would shift an anime's whole main run; a *provider*
ordering, by contrast, is stored exactly as the service listed it, specials in place, so `sequence == 1`
there is that ordering's first entry, not necessarily the first regular episode. `AIRED_ORDER_TYPE` is the
one ordering name this app refuses to accept from a provider — writing a TheTVDB ordering under it would
collide with the aired rank on the deferred unique and misattribute the source.

TheTVDB's season types are never a closed set in this codebase: they are read from a cached
`GET /v4/seasons/types` at request time, matched **by name**, and `default` is refused as an alias for
`official` rather than silently accepted as an eighth type — a test asserts no type name appears hard-coded
in the module. Measured against One Piece's recorded fixture bodies (the same reference episode, Laboon,
`docs/status.md` section 2.9 already carries), `dvd` orders **78** episode rows, not the 77 the plan
estimated — its second page carries a TV special the recorded specials bucket also holds, and the
`absolute` ordering does not list specials at all. An empty episode list for a type TheTVDB does not hold
for a title is treated as *unknown*, never as *no episodes*: nothing is written and nothing pruned, and
the cursor records why — the shape that has already deleted 194 seasons elsewhere when read the other way
(CLAUDE.md section 9.2).

`ingest/tvdb_matching.py` pairs one TheTVDB ordering's episodes onto the TMDB episodes already stored,
**never by position** — TMDB's absolute-continuous anime numbering means the nth TheTVDB entry is not the
nth stored row, and pairing by position would renumber a whole series while looking perfectly ordered on
screen. Two arms only, both exact: an air date unique on both sides, then the absolute number matching our
own aired rank — the second arm exists because of Laboon, which TMDB and TheTVDB both aired 2001-03-21
alongside something else that day, so only its absolute number (62, also its aired rank) pairs it. Both
arms carry a ±1-day air-date guard, because our aired rank is dense over the episodes this projection
*holds* while TheTVDB's `absoluteNumber` counts the whole series, and a gap between them — a season TMDB
answered 404 for — silently slides every pair after it wrong; the guard's measured cost on the recorded
orderings is zero. There is deliberately no third, name-based arm: anime episode names cross the two
services as romaji, English and synonyms, and an exact-name pair would add little while risking a wrong
one. **Ruling 38.** `TvdbEpisodesResult.reported` is read from `links.total_items`; a walk whose collected
length disagrees with it is refused rather than accepted as complete.

**Ruling 31.** T14's fix round consolidated `clients/transport.py` into the one home of `Cursor`,
`ProviderBody`, `elapsed_ms_since`, `retry_after_seconds`, `refusal_for(response, provider)` and
`scrubbed`, which `episode_orders.py` and `tvdb_matching.py` both import rather than reimplementing.

89 tests (`tests/ingest/test_episode_orders.py` 63, `tests/ingest/test_tvdb_matching.py` 26). Complete.

### T23 — the reconciler

`ingest/reconciler.py` projects one workbook into Postgres, master plan §6.5 verbatim. **The change
test is the digest and the identity cells together, never the stamp** — a pass is skipped only when
the sha256 over `ingest/workbook_digest.py`'s normalised grid matches the `category` row **and** the
sheet's `Row ID` cells are exactly the live entries' ids, and a skip records the new `workbook_mtime`
and touches nothing else (Ruling 49 as amended; the reasoning is under **Database verification**
below, and the rule is master plan §6.5 rule 1). Everything else is as designed: match rows by the
UUID in the hidden `Row ID` cell; adopt for a cleared cell on title, unit and position together;
re-mint a duplicate or an id another category already holds; mint for the rest; soft-delete what left
the sheet; renumber `position` for the whole category under the deferrable unique; re-resolve only
entries that are new, raw-changed or unresolved. Two refusals leave the workbook untouched, roll the
transaction back and record `category.last_ingest_error`: a `Row ID` cell that is not a canonical
UUID (Ruling 20), and a previously-ingested sheet whose rows have mostly stopped matching. The whole
diff reaches disk through **one** `Catalog.apply_ingest_writeback` → `Catalog._write` — one snapshot,
one temp file, one `os.replace` — and the **post-write** `st_mtime` is what gets stored, so the next
pass does not read our own write as a change. `workbook/writer.py` gains `apply_ingest_writeback` and
a shared `_append_styled_column` that `add_watch_column` and `identity.ensure_identity_column_on` now
both use instead of a second copy.

Six decisions landed after this entry was first drafted and are folded into it rather than opening a
second one, per section 17.4:

- **`workbook/curated_columns.py` moved out of `ingest/` (Ruling 39).** "Which column carries the
  title, the unit, the release and the type" is a schema question the resolver's dry run asks as often
  as the reconciler does, and neither owns the answer, so it now lives beside `workbook/schema.py`,
  whose header-folding it reuses. `resolver/` imports nothing from `ingest/` as a result.
- **The reconciler is wired into the app, not just written.** `api/dependencies.py` gains
  `get_ingest_runtime()`, an `lru_cache(maxsize=1)` singleton exactly like `get_catalog()`, and
  `main.py`'s lifespan closes it on shutdown — guarded by `get_ingest_runtime.cache_info().currsize` so
  a test that substitutes a plain callable, which carries no `cache_info`, does not crash the guard.
  `ingest/runtime.py` is the composition root behind it: one `httpx` client and one token bucket per
  upstream, and no HTTP route reaches ingest, which stays a service concern in Phase 1.
- **Retired entries are renumbered behind the live block, not interleaved with it.** `renumbered()`
  parks every retired entry's `position` starting at `len(live) + 1`, because `uq(category_id,
  position)` carries no partial predicate — a retired row still occupies its slot and would collide
  with a live row renumbering onto it. A removed row's position is not history worth preserving in
  place; it is only ever a collision waiting to happen.
- **A missing provider token never wipes a titled entry.** `_note_unconfigured` records the reason on
  the entry it could not resolve further and leaves whatever title it already carries untouched, rather
  than clearing it back to `unresolved` because no credential was available this pass.
- **One closed vocabulary for the per-workbook log line.** `reconcile_end job=… category=… …
  refused=<label>` fixes `refused=` to `none` or `refused` (never a bare boolean), so a log reader never
  has to infer whether a workbook was refused from the presence of a reason string.
- **The six-month cache ceiling drives a payload-only `_refreshed` pass, never a re-search.** When a
  title's cached payload has crossed `TMDB_CACHE_CEILING_DAYS`, the reconciler re-reads it without
  spending a TMDB search, and `ReconcileOutcome.refreshed` counts how many titles took that path per run.

Measured against the tree rather than restated from an earlier draft: 132 tests across
`tests/ingest/{test_reconciler,test_reconciler_rules,test_workbook_digest,test_ingest_runtime}.py` and
`tests/workbook/test_curated_columns.py` (21 + 44 + 25 + 10 + 32), of which 19 of `test_reconciler.py`'s
21 run against a real Postgres service container (`db_session`) and the rest run offline — the earlier
"65 tests: 51 offline … 14 against a real Postgres" line is superseded by this count. Complete.

### T24 — queue expansion

`ingest/expansion.py` rebuilds `curated_entry_item`, the flattened queue every "what plays next" and
"how far through this category" question walks. Every playable unit gets a row: one per episode of a
resolved span, and — because the plan as first designed gave a film no row at all, which would have made
Next skip every one of them (ADR-010) — exactly one row per movie entry too. A span is read as a range
over `episode_order.sequence`, never expanded into a list of episode ids, so One Piece's `E19-53` is one
range scan and stays one after TMDB inserts a recap episode (CLAUDE.md section 11.2, rule 10); an entry
naming an ordering its title does not carry expands to nothing and says so in its note, and never falls
back to the aired rank, because a confidently wrong span is the one failure shape that looks right on
screen. A season number written on a sheet is read as a TMDB season number, so a `(season, episode)`
lookup spans both numberings this app computes itself — the aired rank and the specials bucket the aired
walk excludes — which together hold every episode TMDB listed exactly once. `series`, `special` and
`unknown` unit kinds are all handled, and a movie-typed special takes the film branch rather than the
episode branch — the library carries 69 special rows, and the ones typed as films play as films.

The queue is rebuilt delete-then-insert inside the ingest transaction and never hand-edited;
`absolute_position` is renumbered for the whole category in one `UPDATE` statement, which the deferred
unique on `(category_id, absolute_position)` lets pass through its own transient duplicates.
`tests/ingest/ingest_support.py` is the recorded harness this task's tests share (Ruling 42's first
instance — see the Tidy note below). 48 tests in `tests/ingest/test_expansion.py`. Complete.

### T25 — the watch mirror

`services/watch_mirror.py` (plus `mirror_outcome.py`) is the four-value `Watched?` projection, exactly as
CLAUDE.md section 5.16 and section 11.2 rule 13 specify it: one dict, no branching, `started` and
`progressed` sharing `"In progress"`, and the two columns that contain the loss — `observed_watch_cell`
(what was last read) and `mirrored_watch_cell` (what was last written) — are what tell a human's edit
apart from the app's own echo. The status cell is never read as truth, only as a signal that a human
moved it.

**Ruling 41.** The mirror never fails an ingest pass over one bad cell. `writable_mirror_cells` skips a
value the sheet's own dropdown does not offer, on both the reconciler's path and the standalone seam,
logging `skipped=invalid_choice` rather than aborting the write-back that carries every other entry's
cell. `_still_ours` is the per-row guard that makes the mirror lose a race deliberately: the first
write is guarded by the mtime the last ingest stored, and a retry re-reads the sheet and gives up unless
every row it planned to touch still carries that entry's own id and still holds the value the app itself
last put there.

The reconciler's own pass carries its pending mirror cells inside the single `apply_ingest_writeback`
call already described under T23 — one snapshot, one temp file, one `os.replace` for the whole pass,
identity writes and mirror cells together — and calls `record_mirrored` immediately after that write
lands, so the stored `mirrored_watch_cell` can never drift from what actually reached disk.

`mirror_entry`, `mirror_category`, `write_mirror_cells`, `_still_ours` (the standalone form) and
`MIRROR_RETRY_ATTEMPTS = 3` are a **second, standalone seam**, for a progress write that did not come
from a workbook read — `POST /api/watch-events` in Phase 3. They have no Phase 1 production caller by
design; that is not dead code, and deleting it would take the Phase 3 write path with it. Operational
note carried into the master plan's section 6.3: a standalone mirror pass defers cleanly while the sheet
is ahead of it, so reconcile and mirror are scheduled together, not as two independent cron lines that
could race each other.

78 tests across `tests/services/test_watch_mirror.py` (48, offline — the pure `writable_mirror_cells`/
`_still_ours`/precedence logic), `test_watch_mirror_database.py` (13, every one against a real Postgres
service container) and `test_watch_mirror_writeback.py` (17, the reconciler-path write-back, offline).
Complete.

### T26 — the mirror race proof

Test-only: `tests/services/test_mirror_race.py`, 12 tests (8 xlsx-path — one of the six defined test
functions is parametrized three ways over what the second writer touched — plus 4 Postgres-gated through
the session-bound `mirror_entry` seam and the reconciler's own write-back). `services/watch_mirror.py`
itself is **unchanged**: the point of this task was to prove the production code already satisfies the
contract, not to add a mechanism for it. The race is injected at the real seam — a save between the
mirror's read and its write-back — and refused by the production `guard_fresh`, proven by mutation. The
mirror loses, retries once onto the fresh mtime, and defers after `MIRROR_RETRY_ATTEMPTS`; a deleted row
defers after a single attempt rather than retrying against a row that no longer exists; two writers
serialise correctly through `lock_for`; and a UI write racing ahead of the mirror gets the standard 409
`StaleWorkbookError` through the real app, not a mocked one. Complete (review approved).

### T27 — the bootstrap runner

`ingest/bootstrap.py` is the first ingest: every workbook in the library, one at a time, run as
`uv run python -m tv_watchlist.ingest.bootstrap [--dry-run] [--only <slug> …]` (`--help` prints the exact
flags). Three properties make it safe to point at nineteen irreplaceable files: one workbook at a time,
no fan-out, so a failure anywhere touches one file and one transaction; a refusal is a result, not a
crash — Excel holding a file, a sheet that changed mid-pass, an unreadable workbook, or an `--only` slug
nothing answers to are each recorded on that workbook's own outcome while the run carries on; and
`--dry-run` writes to **neither** store — a `Catalog` subclass overrides only `apply_ingest_writeback` to
decline the write, and the session is a savepoint inside a transaction the run always rolls back — but a
dry run still takes each workbook's lock, still needs a reachable database, still spends provider quota,
and still writes artwork to disk when tokens are set, because none of that is the write it is refusing.

One structured log record per workbook and one per run, zeros included — `bootstrap_start job=… dry_run=…
workbooks=%d`, `bootstrap_workbook job=… category=… … refused=%s …` — because a pass that changed nothing
has to say so (CLAUDE.md section 9.2), and the free-text reason is always the record's last field so a
reason carrying spaces can never be misread as another key.

Exit codes are a contract: `BOOTSTRAP_EXIT_OK = 0`, `BOOTSTRAP_EXIT_REFUSED = 1` (one or more workbooks
were refused — locked, stale, unreadable — while every other workbook still ran to completion),
`BOOTSTRAP_EXIT_FAILED = 2` (an infrastructure fault — the database is down, migrations are behind — and
the right response is to retry, not to inspect individual workbooks). The owner's live run, once off the
VPN block, is `docker compose up -d postgres` then, from `app/backend`,
`uv run python -m tv_watchlist.ingest.bootstrap`, expected to report `19 workbooks, 19 ingested, 0
skipped, 0 refused` and `996 rows projected, 996 identities minted, 19 workbooks written`, exit 0. 26
tests in `tests/ingest/test_bootstrap.py`. Implemented; a scoped re-review is running.

### T28 — read models and the entries route

`models/{title_read,episode_read,entry_progress,curated_entry_read}.py` are the Pydantic layer over the
ORM that CLAUDE.md section 5.15 requires: `from_attributes=True, frozen=True` on every one, and nothing
below the boundary that was not eagerly loaded. `services/entries.py` (`read_entries`, `WATCH_STATE`) is
the query, and `api/entries.py` serves it as `GET /api/categories/{category_id}/entries` →
`list[CuratedEntryRead]` — live entries only, ordered by `position`, windowed by `limit`/`offset` with
`MAX_ENTRIES_PAGE_SIZE = 500` as both the default and the ceiling, so the common call carries a whole
category and an over-large one is refused at the boundary rather than served. A category id nothing
answers to is a 404 through `CategoryNotFoundError` raised **before** any projection query runs; a
category that has never been ingested answers `[]`, not an error — an empty projection is a valid one,
exactly as an empty library already is (CLAUDE.md section 18.1).

`TitleRead.tmdb_id: int | None` mirrors the nullable column (a hand-entered local title with no provider
match is a first-class record, risk register R2). Deliberately absent from this task: `availability` and
`jellyfin_item_id` on `CuratedEntryRead` — those are T51's, once the service that computes them exists,
per the no-stubs-by-phase rule — and there is no `SeasonRead` or `ArtworkRead`, because nothing in Phase 1
consumes either. `EpisodeRead` itself ships with no Phase 1 consumer either; it exists because
`CuratedEntryRead` completes the boundary contract section 5.15 describes, and the read model for the
entity that contract names is not deferred just because nothing calls it yet.

The existing `CategoryDetail` contract is untouched — this route is served *alongside* it, never instead
of it (CLAUDE.md section 13.5). `tests/statement_support.py`'s `counted_statements` is the shared SQL tap
this task's own service suite uses to prove the page has no N+1, and three later suites (T19, T20, T29)
adopt the same helper rather than each writing their own (Ruling 42).

Frontend mirrors: `src/types/{TitleRead,EntryProgress,CuratedEntryRead}.ts`, snake_case throughout because
these cross the wire from Python (CLAUDE.md section 4.5). This is an additive contract change — four new
response models and one new route — and is a **minor bump**, folded into this same `0.2.0` heading per
the one-unreleased-heading rule. 20 tests in `tests/services/test_entries_service.py`, 26 in
`tests/models/test_read_models.py`, 14 in `tests/api/test_entries.py`. Complete.

### T29 — watch events

`models/watch_event_create.py` is CLAUDE.md section 5.15's `WatchEventCreate` verbatim — one field,
`subject_id`, standing in for three nullable ones, with the service mapping `(subject_kind, subject_id)`
onto the correct typed FK column, and a `model_validator` that duplicates the database `CHECK` on purpose:
one rejects a bad request with a 422 at the boundary, the other guarantees the invariant for every writer,
including a migration that never passes through this model. `models/watch_event_read.py` is new — the
model neither the master plan nor this file's earlier drafts of section 5.15 had committed to a shape.

**Ruling 44.** `POST /api/watch-events` answers **201 `WatchEventRead`** — the recorded event *with* the
entry's `progress: EntryProgress` embedded — rather than the bare `EntryProgress` cell section 13.5 had
described. The reasoning: the UI repaints from what the database now says, not from the request it just
sent, and a response that omitted the stored fact itself would make the caller re-fetch to learn what it
had just recorded. `services/watch_events.py` is the write path; `api/watch_events.py` wires two routes,
not one — the `POST` above, and `GET /api/categories/{category_id}/entries/{entry_id}/progress`, which
answers the same `EntryProgress` on its own, for a screen that recorded nothing and only wants to read.

**Dual store, on the UI's own write path.** The `POST` handler commits the watch-event insert first, then
schedules the sheet mirror as a `BackgroundTasks` job — never awaited inline — carrying its own session
from `session_factory` rather than the request's, because a background task outlives the request and a
workbook mirror must never make a watch-event write wait on Excel, nor fail because somebody has the file
open (CLAUDE.md section 0.2). The task only fires when the recorded event names a live `curated_entry_id`.

`data/errors.py` is new: `ProjectionError` as the base, with `EntryNotFoundError` and
`WatchSubjectNotFoundError` both mapping to 404 in both of `api/errors.py`'s tables (CLAUDE.md section
4.3) — `WatchSubjectNotFoundError` specifically so an id nothing answers to is a 404 the caller can act
on, resolved before any row is inserted, rather than the database's own `one_subject` integrity error
surfacing several frames deeper as an opaque 500.

Frontend mirrors: `src/types/{WatchEventCreate,WatchEventRead}.ts`. This is an additive contract change —
two new models, a new error class pair, two new routes — folded into this same `0.2.0` heading as a
minor bump. 33 tests in `tests/services/test_watch_events_service.py`, 13 in
`tests/services/test_watch_event_helpers.py`, 32 in `tests/models/test_watch_event_create.py`, 19 in
`tests/api/test_watch_events.py`. Complete (re-review approved).

### T30 — resolution review

`models/resolution_update.py` is one human decision about one curated entry: `action: "confirm" |
"correct" | "reject"`, `extra="forbid"`, and a `model_validator` that keeps the three actions from
blurring into each other — `correct` requires `media_type` and `tmdb_id` together (a correction that
named a title without also saying what kind of title it is would be a server guessing), `confirm` and
`reject` carry no title or span field at all, only the note, and a `span_end` before `span_start` is
refused regardless of action. `unit_kind`, `order_type` (an open string, `max_length=32`, validated
against the numberings the title actually carries at apply time rather than against a closed set — the
same open-vocabulary rule T20 established for TheTVDB's season types), `span_start`, `span_end` and
`season_number` are all optional and nullable; `note` defaults to `""`.

`services/resolution_review.py` and `api/review.py` wire two routes: `GET /api/review/entries` (query
`state`, `category_id`, `limit` ≤ `MAX_ENTRIES_PAGE_SIZE`, `offset`) and `POST /api/review/entries/{id}`
(`ResolutionUpdate` → `CuratedEntryRead`; `EntryNotFoundError` → 404, `ResolutionConflictError` → 409 —
the body was coherent and the entry real, but the world it names is not: no provider configured, TMDB has
nothing under that id, or the title carries no such numbering, each worth retrying once something
changes, which is what 409 says).

**Ruling 47.** The queue predicate is `resolution_state IN ('unresolved', 'auto')` — the partial index
`ix_curated_entry_needs_review`'s own predicate, and nothing more. There is **no** confidence threshold
anywhere in the code; any document saying "unresolved or confidence below 0.80" describes a rule that was
never built and is corrected wherever it appears.

**Ruling 45.** `CuratedEntryRead` gains `resolution_note: str = ""` — never `str | None`, because the
column itself is `NOT NULL DEFAULT ''` — carrying the resolver's own sentence, the expansion's `queue: `
clause, or a reviewer's `review: ` clause, so a row a human is asked to judge always says what was already
tried. Mirrored in `types/CuratedEntryRead.ts` as `resolution_note: string`.

**Ruling 46.** A successful `confirm` or `correct` rebuilds that entry's `curated_entry_item` rows
immediately — the queue T24 built is a cache, and a resolution change is exactly the kind of change it
promises to reflect without waiting for the next full ingest pass.

**Ruling 48.** A re-resolve after a later cell edit replaces `resolution_note` wholesale, so a reviewer's
`review: ` clause recorded by a `confirm` or `reject` does **not** survive across a subsequent cell edit
that sends the entry back through the resolver. This is a known, accepted gap, not an oversight: T57 (the
unresolved view, Phase 3) is where durability of that decision history is decided, not here.

`ResolutionUpdate.ts` mirrors the model with `?: T | null` on every nullable field, matching
`exactOptionalPropertyTypes` (CLAUDE.md section 4.2). This is an additive contract change — one new
model, one new field on an existing response model, two new routes, two new error classes — folded into
this same `0.2.0` heading as a minor bump. 21 tests in `tests/models/test_resolution_update.py`, 17 in
`tests/services/test_resolution_review.py`, 16 in `tests/services/test_resolution_review_rules.py`, 21 in
`tests/api/test_review.py`. Complete (re-review approved).

### T31 — the resolver dry run

`resolver/dry_run.py` (`uv run python -m tv_watchlist.resolver.dry_run --out
../../docs/resolver-dry-run.md`, run from `app/backend`) and `resolver/dry_run_report.py` are the
measurement master plan risk register item R1 asked for: "replace that estimate with a measurement."
It is deliberately the poorer half of the ingest — no Postgres, no cursor, no artwork, no `changes`
call, no season or episode ingest — because the only question it asks is how many of the library's rows
the resolver can place on its own. Three rules it may never break, each enforced in the module itself:
it never writes a workbook (the library is copied into a temporary directory first, because
`read_category` probes the Excel lock by opening the file `r+b` and the owner's own files are the
curated data); it never writes a credential (the token is read once through `Settings` and handed to the
client, which puts it in one header); and it never touches Postgres — `NullResponseCache` means every
fetch is a fresh one and no cursor moves, so a dry run can never make the real ingest believe a payload
has already been seen.

**`docs/resolver-dry-run.md`, run 2 on the final resolver, written 2026-09-20**: 830 of 996 rows across
all 19 workbooks auto-resolved (83%), 166 left for the review queue, 0 confirmed (the resolver never
awards that rung — a human does, in T30 — and the column is reported so the set matches the phase gate).
By confidence: 0.95 × 475, 0.80 × 187, 0.65 × 126, 0.50 × 42, 0.00 × 166. This is the measurement that
replaces section 18.2 rule 3's estimate, and Ruling 37 (T18) is the largest single class of the 0.65 rung.

**Ruling 36.** Two live dry runs were made in total against the real TMDB catalogue; this report is run
2, against the resolver as T18's fix round left it, not run 1 against an earlier draft.

**Ruling 40.** A franchise-form match landing at 0.65 confidence is exactly what that form exists for,
and it belongs in the review queue, not in a third category of its own.

31 tests (`tests/resolver/test_dry_run.py` 19, `tests/resolver/test_dry_run_report.py` 12). Complete.

### T32 — provider attribution

`components/ProviderAttribution.tsx` mounts once, in the sidebar foot — the one surface every screen has
— because both providers' terms read "displayed to end users viewing metadata," on the screen where the
data appears, not in a settings page, so one mount point satisfies both without a condition that could go
stale as more screens start rendering provider data. TMDB's notice is carried verbatim from their API
Terms of Use section 3: *"This product uses TMDB and the TMDB APIs but is not endorsed, certified, or
otherwise approved by TMDB."* TheTVDB's is their own published sample text, linked to `thetvdb.com`.
Both notices are rendered as plain text — no provider response is ever interpolated into either string.

`public/tmdb-logo.svg` is TMDB's own brand-page mark, served byte-for-byte
(sha256 `8e7b30f73a4020692ccca9c88bafe5dcb6f8a62a4c6bc55cd9ba82bb2cd95f6c`) because their terms forbid
recolouring or cropping it; it renders at a twelfth of this app's own wordmark height, which is what
their terms mean by "less prominent." The new `--mist-400` token in `src/styles/tokens.css` is the
attribution line's colour. `layout/surfaces.ts` gains `THE_ATTRIBUTION` inside `THE_WALL`, and
`layout/vite.config.ts` gains a plugin serving `public/` so the guard's own dev server can reach the SVG.

**Ruling 43.** `layout/support/openProbe.ts` now waits on `Promise.allSettled(document.getAnimations()…)`
rather than `Promise.all`, because a CSS transition cancelled mid-flight rejects `Animation.finished`
with `AbortError` — a pre-existing 1-3-in-152 flake this fixes rather than papers over (CLAUDE.md section
16.5 pitfalls).

The layout guard is now **39 tests × 4 viewports = 156 runs**: 36 controls (18 surfaces × 2 tests) + 2
proposal-diff + 1 new `layout/specs/attribution.spec.ts`, which asserts the mark is loaded, rendered at
12px, keeps its aspect ratio, is never recoloured, and stays visibly less prominent than the wordmark.
CLAUDE.md sections 4.4 and 16.1 and `app/README.md`'s guard line move to this arithmetic. Frontend Vitest
is now 21 files, 219 tests. Complete (re-review approved).

### Tidy — shared test seams, not deferred to T33

Two test-to-test import fixes landed as soon as the duplication was noticed, per Ruling 42, rather than
being carried forward as a T33 cleanup item:

- **`tests/workbook_edits.py`** now holds `narrow_the_status_dropdown`, the one shared helper for
  shrinking a sheet's `Watched?` dropdown in a test fixture, used by `tests/ingest/test_reconciler.py`
  and `tests/services/test_watch_mirror_writeback.py` — previously each file carried its own copy.
- **`tests/statement_support.py`'s `counted_statements`** is the one SQL-statement tap bound to a single
  engine, used by `tests/ingest/{test_tmdb_ingest,test_episode_orders,test_expansion}.py` and
  `tests/services/{test_watch_events_service,test_entries_service}.py` to prove a page has no N+1 or to
  count writes against a named table — a second copy is always the one that drifts (CLAUDE.md section 7).

### T32a — the launchers own the compose Postgres

`run_tv.sh` and `run_tv.bat` start `docker compose up -d postgres`, wait for its healthcheck, run
`uv run alembic upgrade head`, and only then start the two dev servers — Postgres and its migrations
are now a precondition of the host-native path, not something a session runs by hand. `[k]` stays
`docker compose down`; `[q]` adds `--remove-orphans` and removes only images matching the
`tv-watchlist-*` prefix; `[v]` adds `--volumes --remove-orphans`, dropping `tv_postgres_data` and the
Jellyfin volumes alongside the same image removal. A separately-started `jellyfin` container is
still removed by `[k]` — the global launcher contract's `docker compose down` reaches every compose
service regardless of which one a session brought up by hand — while its data survives in the named
volumes (Ruling 28). 4 tests in `app/backend/tests/test_launchers.py`. Complete — though neither
launcher has been run end to end yet, because the same VPN block that stops the image pulls stops
`docker compose up -d postgres`.

### Database verification — the suite run against a real PostgreSQL 16.2

The whole backend suite ran against a real Postgres for the first time on this machine: a `pgserver`
16.2 cluster on `127.0.0.1:5525` with `pg_trgm` built from the matching contrib source, no Docker
involved, so the tests that had only ever skipped here finally had a result. The first pass was
**2495 passed, 7 failed, 0 skipped**, and the Alembic round trip
(`upgrade head && downgrade base && upgrade head`) was green — eleven tables, two views, the
append-only trigger and `pg_trgm` all torn down and rebuilt from nothing. All seven failures
reproduced in single-test isolation, so none was an ordering artefact.

**One was production.** `reconciler._unchanged` ANDed the `st_mtime` stamp with the digest, which made
the digest dead weight — an equal stamp already implies equal bytes — and contradicted both its own
docstring and master plan §6.5. **Ruling 49** dropped the stamp; applying it then exposed the half the
digest cannot see, because `workbook_digest` excludes the `Row ID` column **by design** — that
exclusion is what lets a first ingest write 996 identities into nineteen sheets and still see nineteen
unchanged files on the next pass — so a cleared, blanked, hand-typed or duplicated id moves no digest
at all, and a digest-only skip would have retired adoption, re-minting and the malformed-identity
refusal for good. **Ruling 49 as amended** is therefore `digest equal AND identities_intact(entries,
row_ids)`: one `SELECT` on the pass's cheapest path, a pure function exact rather than heuristic, with
four rules tests of its own. **Ruling 54** records the one consequence accepted alongside it — an entry
a provider outage left `unresolved` is no longer retried by an Excel open moving the stamp, so the next
full pass over that workbook and the review queue are the paths that remain, and an automatic retry
over an untouched workbook is a recorded Phase 3 follow-up beside T57.

**Six were test defects**, each fixed where it sat. The reorder test recorded a `COMPLETED` event and
then asserted no mirror write, when section 5.16 requires one — it now levels the mirror through the
production `mirror_category` first and asserts position-only afterwards (**Ruling 50**). The refusal
test captured the workbook's stamp before its own mutating helpers instead of immediately before the
pass, which left its central claim — a refused pass does not touch the workbook — unfalsifiable.
Laboon was selected by air date, which two One Piece episodes share, and is now selected by episode
number. Two `dict(Result)` calls took SQLAlchemy's mapping path and raised `TypeError` before reading
a row, and are now `dict(result.all())`. The entries page's statement budget was a magic `3` where the
truth is `4`, now the named `STATEMENTS_PER_PAGE` with the poster query's short-circuit explained. And
`tests/fixtures/tmdb/tv_35610_external_ids.json` was simply missing: it is now **recorded live**
against TMDB with its header sidecar, the credential read through `Settings` and sent only as a header,
never hand-authored (**Ruling 51**).

After the fixes: **2506 passed, 0 failed, 0 skipped**, ruff clean, with no new `# noqa` and no
`# type: ignore` — the `src/` invariant stands at five named suppressions and zero ignores
(**Ruling 52**).

### T48 — the Jellyfin client (backend-only, key in one header)

`clients/jellyfin_client.py` (`JellyfinClient`, `build_jellyfin_http`, `build_jellyfin_client`) is the
first and only code in this repository that talks to Jellyfin — the Phase 3 build's opening task,
because Phase 3.5's whole import pipeline depends on nothing else in Phase 3 first. It never uses
`agent/url_guard.assert_public_http_url`, which rejects private and loopback addresses by design and
would refuse the very server this client exists to reach; instead `clients/http_guard.py` gains a
sibling, `assert_within_configured_base` (allows `http`, same exact-host-and-port and
credentials-in-URL refusals as the https-only `assert_within_base`), and `configured_url`, the
matching builder — both shared from the start with Phase 3.5's qBittorrent client rather than
duplicated later (Rulings 65, 66). The key travels in exactly one header,
`Authorization: MediaBrowser Token="…"`, never in a URL, a log record or an exception message.
`Settings.jellyfin_base_url` and `jellyfin_api_key` are now real, live `Settings` fields — the two
`TV_JELLYFIN_*` names leave `tests/test_env_example.py`'s `DECLARED_EXTRAS` — and the base URL carries
a boot-time `field_validator` running the same configured-base check, so a malformed value fails at
startup, naming the variable, rather than surfacing as a 503 at the first playback (Ruling 80). Four
models land under `models/jellyfin/` (`JellyfinItemDto`, `JellyfinItemPage`, `JellyfinProviderIds`, the
shared `JellyfinPayload` base), every one `extra="ignore"`; `RunTimeTicks` becomes `run_time_seconds`
by one integer division at the boundary, with no attribute exposing ticks twice.
`api/dependencies.get_jellyfin_client()` is an `lru_cache(maxsize=1)` singleton, closed in the
`main.py` lifespan beside the agent and ingest runtimes (Ruling 64).

Because no Jellyfin server has ever been reachable under the owner's VPN, the fixtures under
`tests/fixtures/jellyfin/` are **hand-authored from Jellyfin 12.1's own OpenAPI document**
(`https://api.jellyfin.org/openapi/jellyfin-openapi-stable.json`, fetched 2026-09-23) rather than
recorded — the one deliberate exception to Ruling 51, stated in `tests/fixtures/jellyfin/README.md`
alongside the five shapes a live server must confirm: `ProviderIds` key casing, whether
`DateLastSaved` ever arrives on a real item (it is not one of `BaseItemDto`'s declared properties in
12.1, though it is a valid `ItemFields` value), comma-delimited array parameters, item-id form, and
the `minDateLastSaved` wire format — all five now live in `docs/status.md` as an owner-run item ahead
of the T54 gate audit. `JellyfinClient.stream()` returns a narrowed `StreamedResponse` (status, three
allowlisted headers, a live byte iterator) rather than the raw `httpx.Response`, so a relay downstream
can never see an upstream `Set-Cookie` or `Server` header (Ruling 81); `refresh_library()`
(`POST /Library/Refresh`, no body, expects `204`) is this task's method from the start, for T67 to
consume unchanged later (Ruling 67).

A fix round closed a credential leak found by reproducing h11's own exception text directly: an
`Authorization` header containing a CR or LF took the `except httpx.HTTPError` path, and interpolating
`{error}` into the raised message put the key itself into the raised `ProviderUnavailableError`. The
fix, `clients/transport.unreachable(provider, error)`, formats only `type(error).__name__` and keeps
the detail on `__cause__`; the identical defect was live in `tmdb_client.py` and `tvdb_client.py` and
is now closed in all three from the one shared helper — a genuine security fix that reached beyond
this task's own file list, reported and applied rather than left for later. `clients/transport.py`
also gained `read_text()` beside `read_json()` (Ruling 63), shared with Phase 3.5's T62 qBittorrent
client, so `health()` and `refresh_library()` read a capped body instead of an unbounded one.

135 new tests across three files, then 78 more across two fix rounds — full suite **2734 passed,
0 failed, 0 skipped**; 100% coverage on `jellyfin_client.py`, `streamed_response.py`,
`models/jellyfin/`, `http_guard.py` and `transport.py`. No wire contract change and no new route, so
no semver bump beyond this subsection; the two `Settings` fields are additive. Complete, reviewed and
approved.

### T60 — the import settings (Phase 3.5)

Six new `Settings` fields for the Phase 3.5 import pipeline (ADR-015), appended after the T48 Jellyfin
block: `qbittorrent_url: str | None = None` (validated at boot exactly like `jellyfin_base_url`,
through the same `assert_within_configured_base` — shape only, not whether the host is actually
loopback or LAN — Ruling 80), `qbittorrent_user: str | None`, `qbittorrent_password: SecretStr | None`,
`import_staging_dir: Path | None = None`, the **new** `media_root: Path | None = None` (the backend's
own view of the media directory compose already mounts for Jellyfin at `/media`, kept as a field
separate from the compose-only `TV_JELLYFIN_MEDIA_HOST`, mirroring the existing
`TV_LIBRARY_HOST`/`TV_LIBRARY_DIR` split), and `import_concurrency: int = Field(default=2, ge=1,
le=8)`. **No committed default names a personal directory** (Ruling 68):
`.env.example`'s placeholders read `/absolute/path/to/tv-import-staging` and
`/absolute/path/to/tv-media-library`, and the compose-only `TV_IMPORT_STAGING_HOST` (default
`./staging`) makes the same host/container split `TV_JELLYFIN_MEDIA_HOST`/`media_root` already makes
(Ruling 73).

Fourteen constants for the import pipeline and the qBittorrent client land in one `--- T60 ---` block
in `constants.py`. `.env.example` gains seven lines at the end — the six `Settings`-backed names, then
the compose-only `TV_IMPORT_STAGING_HOST` — taking the file from **16 to 23** `TV_` variables;
`tests/test_env_example.py`'s `EXPECTED_NAMES`, `SECRET_NAMES`, `EXPECTED_DEFAULTS` and
`DECLARED_EXTRAS` all grow to match, plus a new test asserting neither machine-dependent path
placeholder is empty or names the owner's home directory.

**One deviation from the phase plan's draft text, by the controller's explicit instruction, corrected
in this same change:** `docs/phases/phase-3.5-plan.md`'s task text had shown
`qbittorrent_url: str = "http://localhost:8080"` as a real code-level default; it is implemented as
`str | None = None` instead, matching `jellyfin_base_url`'s shape exactly —
`http://localhost:8080` is the `.env.example` placeholder, never a `Settings` default.

64 tests across `test_env_example.py`, `test_config.py` and the new `test_import_settings.py`; full
offline regression **1781 passed**. No workbook, compose or wire-contract change. Additive `Settings`
fields are a minor addition under the standing heading. Complete, reviewed and approved.

### T57 — the unresolved view and its retry control (Phase 3)

The unresolved-and-auto review queue gets its own screen, and Ruling 54's open follow-up — "should an
untouched workbook's entry be retriable without a full pass or a hand edit" — closes with a per-row
control rather than a bootstrap `--force` flag. `AppView` gains a third value, `"unresolved"`, beside
`"home"` and `"category"`; the sidebar carries a nav entry to it; `UnresolvedView.tsx` and
`UnresolvedRow.tsx` render the queue, and `RetryResolutionButton.tsx` is the new control.

**No second listing route was built** (Ruling 71/R71): the view consumes the **existing**
`GET /api/review/entries` (T30) rather than a new `GET /api/entries/unresolved` — an earlier plan
sentence had named the latter, and the master plan wins that discrepancy. The listing is paged from
the frontend (`src/api/fetchReviewQueue.ts` walks `?limit=REVIEW_PAGE_SIZE&offset=n`, `REVIEW_PAGE_SIZE
= 500`, matching the route's own `MAX_ENTRIES_PAGE_SIZE` default and ceiling) so a 996-row library is
never silently truncated at one page — a fix-round correction after the first pass fetched only page
one.

**One new route:** `POST /api/review/entries/{entry_id}/retry` (`api/review.py:67`), no body, answering
`CuratedEntryRead`. It re-resolves exactly one entry through the reconciler's own store step — a new
`ingest/reconciler.resolve_stored_entry()`, extracted from `_resolve_one()` (the tail becomes
`_answered()`) so the retry and the ordinary ingest pass share one resolution leg, never two; the full
backend suite proved the refactor behaviour-identical. `workbook/curated_columns.py` gains
`raw_type_cell(cells)` so a retry — which resolves from a stored entry's own `raw_cells`, not a live
`ColumnSpec` list — can still answer Ruling 27's "a blank `Unit` is not `movie @ 1.00`" question from
the Type/Format cell. Refusals are checked before any provider call, so a refused retry writes nothing:
**404 `EntryNotFoundError`** for an unknown or removed entry; **409 `ResolutionConflictError`** for an
unconfigured TMDB (`NOT_CONFIGURED`) and, new in the fix round, for an entry a human has already
decided — `resolution_state` is `confirmed` **or** `rejected` (`HUMAN_DECIDED`, a frozen set checked
before `confirmed` alone was found to let a `rejected` row be silently overwritten).

**R82 — `CuratedEntryRead` gains `category_slug: str`,** placed immediately after `id`, in the fix
round: the queue spans every category in one request, and a row could not previously say which
workbook it came from. Served by a new `services/entries.py:_slugs_for()` — one `IN` query per page
over the distinct `category_id`s of that page, because `CuratedEntry.category` is `lazy="raise_on_sql"`
and a naive per-row load would turn one page into up to nineteen. Mirrored in `types/CuratedEntryRead.ts`
at the same position. Additive; recorded in `CLAUDE.md` §5.15 before this entry.

Every row, note and title renders as **text only** — no `dangerouslySetInnerHTML` anywhere in the two
new components, matching the rest of the tree. `resolution_note` renders exactly as it stands, with no
history (Ruling 48 stands, unchanged). The main-nav entry, the per-row Confirm and the per-row Retry
are the layout guard's new **`"unresolved-view"`** surface (`layout/surfaces.ts`, 18 → **19** surfaces;
`layout/probes/aLibraryWithUnresolvedRows.ts`), which is why the guard arithmetic moves from
18 × 2 + 2 + 1 = 39 per project to **19 × 2 + 2 + 1 = 41 per project × 4 = 164 runs**.

Backend: 47 tests on the three named suites (50 after the fix round's parametrized 409 and two new
retry tests), full backend scope **1409 passed**; ruff clean. Frontend: Vitest **237 tests across 25
files** (was 219 before this task); `pnpm build` and `pnpm exec tsc -b` clean; layout guard **164
passed, twice**. No workbook write in the retry path; no `ProviderError` can reach the route uncaught.
**No wire-contract break** — `category_slug` is additive and the one new route is additive — so this is
a **minor** addition under the standing `v0.2.0` heading. Complete, reviewed and approved (two review
rounds: the first found `category_slug`'s absence, the untested `raw_type_cell` path, and the
`confirmed`-only refusal gap; both rounds' findings are closed above).

### T63 — destination naming and path containment for media imports (Phase 3.5)

Two new service modules for the Phase 3.5 import pipeline, built and reviewed ahead of the file-move
task (T66) that will consume them: `services/media_filename.py` (`safe_component`,
`optional_component`) and `services/import_naming.py` (`DestinationPlan`, `assert_within`,
`plan_destination`). Together they answer "what path does an imported file land at" without ever
touching a byte on disk — the actual move is T66's job.

`safe_component` NFC-normalises, replaces every `ILLEGAL_FILENAME_CHARACTERS` character and every
codepoint below a space with a space, collapses whitespace runs, strips leading and trailing dots and
spaces, caps at `MAX_FILENAME_STEM_LENGTH` characters, appends the `RESERVED_FILENAME_STEMS` suffix
(`_`) when the result collides with a Windows device name, and raises `ImportNamingError` on an empty
result; `optional_component` returns `None` instead — the shape that lets a missing episode title drop
itself and its leading ` - ` separator together. `workbook/stem.validate_stem` is deliberately **not
reused**: it refuses `:`, and a filename sanitiser needs to replace, not refuse. Eight new constants
land in one `--- T63 ---` block in `constants.py`, reusing every existing name
(`ILLEGAL_FILENAME_CHARACTERS`, `RESERVED_FILENAME_STEMS`, `MAX_FILENAME_STEM_LENGTH`,
`MEDIA_IMPORT_EXTENSIONS`, `MEDIA_IMPORT_TV_DIRNAME`, `MEDIA_IMPORT_MOVIES_DIRNAME`) rather than
re-declaring any of them. `plan_destination(media_root, title, episode | None, source_suffix)` refuses
an unset `media_root` (naming `TV_MEDIA_ROOT`), refuses an extension outside
`MEDIA_IMPORT_EXTENSIONS`, names by `title.original_name or title.name` — correct for anime, whose
absolute-inside-season TMDB numbering (`CLAUDE.md` §11.2 rule 9) means `S02E62` and not `S02E01` — and
calls `assert_within` before returning, so a caller cannot forget the containment check.

**R84, from the fix round: every component is capped in bytes as well as characters.** ext4, overlayfs
(the compose mount), APFS and NTFS all cap one path component at **255 bytes**
(`MAX_MEDIA_COMPONENT_BYTES`), and a CJK glyph is three UTF-8 bytes, so the 113 characters the
character cap alone allowed came to 339 bytes — `ENAMETOOLONG` the moment T66 moves the file. Both
`safe_component` and `optional_component` gained `limit_bytes`, trimming with
`encoded[:limit_bytes].decode("utf-8", "ignore")` so a cut never splits a code point. The
**reserved-stem guard now runs after both caps, not before** — the fix round's one real bug: appending
`_` before truncating let the cap itself cut the suffix back off, or manufacture a device name out of a
longer title (`safe_component("con", limit=3)` had produced `"con"`, not `"co_"`). The guard now
replaces the tail when there is no room to append rather than appending past the limit.
`assert_within` additionally converts the `ValueError` that `Path.resolve()` raises on an embedded
null byte into `ImportPathError`, rather than letting it escape uncaught.

Two new `ProjectionError` subclasses in `data/errors.py`: `ImportNamingError`, `ImportPathError`.
**T68 still owes their `api/errors.py` status/message table rows** — until then either falls through to
a bare 400 (`CLAUDE.md` §4.3's documented default for an unregistered `WorkbookError`/`ProjectionError`
subclass). `superseded_destination_for` (`<media root>/_superseded/<stamp>/…`) is deliberately **not**
here — it is T66's, and writing it now would be a stub with no consumer.

163 tests across `tests/services/test_media_filename.py` and `test_import_naming.py` (130 before the
fix round), **100% coverage on both new modules**; ruff clean; whole backend suite green with zero
collection errors once T62's client landed alongside it. Covered with reference values: both path
templates verbatim; unpadded episode numbers past two digits; a missing episode title over five blank
shapes with no dangling separator; a 300-character title truncated to fit with the year and extension
intact; ten accepted/refused extensions; `media_root=None`; a 289-case hostile-input property test;
crafted traversal strings (`../../etc`, `..\..\etc`, `/etc/passwd`, `C:\Windows\System32`) defused and
contained; a **real symlink created in `tmp_path` pointing out of the root**, caught by `assert_within`;
every reserved stem swept against every cap width; three CJK inputs (series, film, episode) each
verified at ≤ 255 bytes per component with the `SxxEyy` marker, year and extension intact.

This is a **minor** addition — two new service modules, two new error classes, eight new constants,
no wire-contract change, no workbook write — under the standing `v0.2.0` heading. `CLAUDE.md` §10.3
gains boundary **B22** for this work (path traversal, symlink escape, filename injection, reserved
device names), scoped for now to path composition and containment; T66 extends the same letter with
the actual file move rather than taking a new one, per `docs/phases/phase-3.5-plan.md`'s own boundary
assignment. Complete, reviewed and approved (two review rounds; the fix round above closed the one
Important and four Minor findings from the first).

### T49 — Jellyfin index and library sync (Phase 3)

Revision `0002_phase_3_jellyfin_item.py` adds the derived movie/series/episode index and the nullable
owner pick on `title`. `services/library_sync.py` and `POST /api/library/sync` are complete and
reviewed. Sync is provider-id-only, preserves picks, and soft-deletes only during a full scan.
The accepted fixes use explicit `since`, then maximum live `last_seen_at`, then a full scan as the
cursor fallback (R87); hold a PostgreSQL advisory lock through caller commit/rollback (R88); and
scan episode deltas independently of series saves (R89). Disabled/unreachable Jellyfin yields the
normal safe 503 envelope. Live confirmation of the documented OpenAPI-derived fixtures remains T54
(R79), not a claim that tests called the owner's server.

### T62 — read-only qBittorrent client (Phase 3.5)

The configured-host client, frozen torrent/file models, capped text-response reader, cached
dependency and lifespan close are complete and reviewed. It supports only version/login/completed
list/file list, never acquisition. R85 accepts both 40- and 64-hex hashes; R86 verifies the actual
method and route surface; R90 shares configured-upstream handling with Jellyfin; R91 treats blank
credentials as unconfigured. Credentials and SID remain server-side, with redirects refused and
one bounded re-login on 403. Boundary B21 is now documented in both security inventories.

### T50 — episode matching on the stored numbering (Phase 3)

`episode_match` joins queued episodes through the stored `EpisodeOrder` printed season/episode pair,
including multi-episode files, and returns per-slot state, order type and label. It never joins by
series name or substitutes raw TMDB episode numbers. R97 reuses `numberings_for(entry)`; R98 keeps a
removed owner's pick ambiguous while candidates remain. The shared `within_numberings` predicate
and keyword-only `episode_for_sequence(..., sequence=...)` are reusable by T65 without duplicate
numbering logic. Claude's final review approved all fixes with **79 focused tests**; docs now reflect
that completed checkpoint. UI display of the selected order is still T52 work.

### T61 — import provenance schema and completed interrupted review (Phase 3.5)

Revision `0003_media_import.py` follows `0002` and adds `media_import`, three native enums, nine named
checks, provenance-preserving FKs and the partial unique live-digest index. `MediaImportRead` is
frozen and requires eager-loaded title data; its TypeScript consumer is deferred to T68 (R93).
R101 uses `BigInteger` for files above 2 GiB. R100 replaces the conflicting title-presence constraint
with `identified_records_how`: deleting a title must leave provenance intact in all eight statuses,
so title presence is enforced when T65 identifies a file, not by a check that defeats `SET NULL`.
R100a records **nine checks / ten violation cases**. Chain-wide migration tests are separate from
revision-specific assertions.

The final review interrupted by Claude's usage limit is now **approved**: **100 focused tests,
zero skips**, including the real-Postgres round trip and Alembic parity. Two unused migration-test
helpers were removed; no schema repair or second migration was needed. These additive features
remain under the existing minor-version entry; no additional pending heading is introduced.

### T51 — computed three-state library availability (Phase 3)

`CuratedEntryRead` and its TypeScript mirror gain exactly `availability` and `jellyfin_item_id`;
`Availability.ts` owns the union. Availability is computed, never a stored column or PostgreSQL enum.
All entry/review/decision/retry responses use the shared read path. A page performs one optional
health probe and two batched library lookups, with fixed five/seven total entry-query counts for
disabled/configured Jellyfin. Empty and partially missing queues remain absent; any ambiguous slot
wins, and only a fully matched queue is available (R96). Notices are service-only (R103); wire ids
identify the selected movie/series, while episode-file ids stay on each match.

The batch extension preserves `episodes_for_entry`, `numberings_for` and the existing join. Review
closed two owner-pick regressions: missing episode-parent metadata keeps the previous exact-ID
fallback, and an explicit live parent remains selected after its provider id changes. Removed picks
do not silently transfer to a surviving candidate. The computed-not-stored test lives with data
enums; the dedicated contract test only checks enum/TypeScript parity (R61).

Independent review: **207 focused tests, zero skips**. New availability/matching logic is fully
covered in the focused suite. No migration, workbook write, new route or playback UI was added.
This is an additive **minor** change under the existing `v0.2.0`, not a second pending version.

### T64 — safe discovery of staged and completed media (Phase 3.5)

The scanner creates only `found` provenance rows, using contained filesystem metadata on a worker
thread. It reuses path containment, validated qBittorrent `save_path / file.name`, transport error
types and the existing advisory-lock pattern. Canonical paths deduplicate aliases and both arms;
qBittorrent provenance wins when both report the same file. Any provider failure discards that
arm's accumulated paths and leaves staging discovery working. Unknown hashes are explicitly
skipped; missing staging configuration disables both arms because no containment root exists.

The caller owns commit/rollback. A PostgreSQL transaction advisory lock replaces the draft process
lock, which could release before commit and permit duplicates; bounded path lookups exclude live
nonfailed history. `ImportScanResult` reports unique regular-file outcomes, `path_refused` and
`unreadable`, with no identification counters. Real symlink escapes/loops and filesystem permission
failures are refused/counted without aborting the rest of discovery.

Independent review: **60 focused tests, zero skips**; **171/171 production statements covered**
across scanner, filesystem discovery, candidate and result. Tests include 1,001-path batching,
off-thread filesystem work, late provider failure, and concurrent real-PostgreSQL commit/rollback.
No files are identified, moved, hashed, deleted or written to workbooks; routes and import-progress
UI are not introduced. Boundary B20 and the transaction protocol are documented. This additive
service remains under the same pending **minor** version.

### Continuation verification — 2026-09-23

The combined implementation passes **3475 backend tests, zero skips**, against real PostgreSQL:
**98.75% line coverage (8156/8259 statements)**, with touched availability/matching and discovery
logic at **100%**. Frontend: **237 tests / 25 files**, coverage **68.23/68.10/60.85/56.25%**
(lines/statements/functions/branches); layout **164/164**; hooks **31/31**. Ruff lint/format,
ESLint/TypeScript, backend/frontend application builds and frontend dependency audit pass.
No coverage floor or source-manifest version changed.

Docker builds remain unverified after the Dockerfile frontend download stalled; Semgrep, gitleaks,
Trivy and the Python dependency auditor are unavailable locally. Remote CI, Windows execution and
live Jellyfin fixture confirmation are not certified. See `docs/continuation-validation.md` for the
full audit, changed-file attribution and next checkpoints T52/T65.

The version in flight is **0.2.0**; the manifests stay `0.1.0` until the release pipeline moves them.

---

### T65 — conservative filename parsing and local-projection identification

The five planned filename shapes feed separate frozen `FilenameParse` and `IdentifyPassResult`
models. Numeric film titles are preserved; ambiguous years, multiple/mixed episode shapes and
empty normalized tokens stay unidentified. Exact normalized keys precede indexed PostgreSQL
trigram matching; media type and supplied year constrain both paths, ties are refused, and
confidence is the lower of filename confidence and title similarity. Absolute numbers reuse
`episode_for_sequence`, with no arithmetic or fallback to aired ordering.

Identification locks live, undecided FOUND rows and preserves concurrent owner choices. Batch
identification skips rows held by another transaction; the caller still owns commit/rollback.
No provider request, file-content read, move, hash, deletion, workbook write, route or migration is
introduced. Tests include a seeded absolute-1085 projection, the recorded season-2 episode-62
naming proof, transaction rollback and owner races. **97 tests, zero skips; 149/149 new statements
covered**, Ruff clean. Additive service work stays under the existing pending minor **v0.2.0**.

### T52 — ordered playback slots and safe same-origin streaming

Owner-approved R104 adds `PlaybackItemRead` and `GET /api/playback/entries/{entry_id}/items`,
leaving `CuratedEntryRead` unchanged. Ordered movie/episode slots carry actual file UUIDs, stored
numbering labels and range warnings; missing/ambiguous slots are retained rather than skipped.
Availability badges and Play use a freshness-checked projection alongside the workbook grid.
The native-video overlay supports explicit slot selection, safe retry/cancellation, Escape/Close
and focus restoration, with no progress, resume or Next/Autoplay before their own tasks.

`GET /api/playback/{jellyfin_item_id}/stream` accepts only live indexed movie/episode UUIDs and
strict single ASCII byte ranges; malformed, suffix, multiple or reversed ranges return 416.
Response headers are narrowly allowlisted; the key stays backend-only. Direct ASGI tests prove
backpressure and shielded cleanup on header/body/disconnect failures. Stream acquisition occurs
after function-scoped database teardown; failures before headers return a sanitized 502 without
secret-bearing exception chaining. Identity encoding is requested and unexpected compression
refused, preventing decoded-body/Content-Length mismatches. FastAPI's declared minimum becomes
0.121.0 for scoped dependencies; locked 0.141.1 and application version 0.1.0 stay unchanged.
The dependency requirement follows the [official FastAPI documentation](https://fastapi.tiangolo.com/advanced/advanced-dependencies/#dependencies-with-yield-and-scope).

Focused backend gate: **206 passed, zero skips, 337/337 statements covered** across the playback
modules and Jellyfin client; independent lifecycle re-review: **50 passed**. Frontend **279 tests /
34 files**, all eight new runtime modules at 100%; **180 Chromium layout checks** across four
viewports. Shared pagination is extracted once and reused by entries, playback and review requests.

### T52/T65 — final combined verification

Backend: **3656 passed, zero skips, 98.80%** (8489/8592 statements), real PostgreSQL on Python
3.14.7. Frontend coverage: **77.93/77.42/69.82/68.70%** (lines/statements/functions/branches).
Ruff/format **413 files**, TypeScript, scoped ESLint, both app builds, **31 hook tests**, and
frontend dependency audit pass. Whole-tree frontend lint has three existing generated-coverage
warnings and no errors. OpenAPI has **20 paths / 23 operations**; no migration added.

Docker builds, full SAST/Python dependency audit, remote CI, Windows execution and live owner-media
verification remain unverified, not waived. No root workbook, credential or git-state mutation;
the two tasks stay under the sole pending **v0.2.0** minor heading. Full 14-item audit, file attribution
and suggested owner-only commit grouping: `docs/playback-import-validation.md`. Next: **T53 ∥ T66**.

### R105/R106 — approved automatic saving and recoverable imports (2026-09-24)

**Implemented and independently reviewed:** both stores save automatically every 60 seconds and on terminal player
events; range episodes complete only on whole-file ended. Paired player-context parameters and a
typed committed-event projection route preserve the existing watch-event body/response contracts.
The import operation table/migration records copy/install/verify/commit/cleanup and recovery;
staging remains until verified destination and successful database commit. Contracts were recorded
before code in master plan §6 and CLAUDE.md §5.17–5.18. Additive routes/schema belong to the existing
pending minor v0.2.0; source version fields remain 0.1.0.

Recovery retains unsaved facts and original workbook stamps, repairs safe pending status cells
without regressing Position, and keeps retry visible after player close. Native Replay resets the
reporter; repeated rebuffer/playing events do not postpone the minute timer. Imports use native
exclusive publication and OS source ownership, recheck actual committed provenance and fresh
episode metadata, and drain every batch worker before cancellation returns.

Final verification: **3891 backend tests, zero skips, 98.93%** (9347/9448 statements); **320 frontend
tests / 46 files**, **196 layout checks**, **31 hook tests**. All new runtime modules reach 100%
coverage; focused T53 backend **198**, workbook **147**, T66 **154**. Ruff check/format (444 files),
TypeScript, scoped ESLint, both application builds, compose validation and the frontend dependency
audit pass. Docker builds stopped at the image download; full SAST, remote CI, Windows and live
owner-media checks remain unverified. No real workbook/media, credential, port or git state was
mutated. Exact attribution, security limits and fourteen-item audit:
[Automatic snapshots and recoverable imports](snapshots-recovery-validation.md).
Next: T53a completed-file context lifetime/navigation contract; T67 exact-file path contract;
T68 reimport source authority.

### T53a — combined-file ordering approved; persistence scope pending (2026-09-24)

The owner approved finished episodes 1–3 file → interleaved movie → episode 4, without replaying
the completed file. The plan now distinguishes this approved ordering from the unresolved lifetime
of completed-file navigation context: in-memory while the player is open, or durable across
closing/reopening. Current watch events retain episode facts, not selected-file provenance.
Intentional repeat occurrences must not silently become global Watched-item skips.

This is a documentation-only decision checkpoint, not a shipped Next/Autoplay implementation.
No API/schema/source-version changes, tests or application builds were made in this pass.
It stays under the sole pending **v0.2.0**; no second unreleased heading or manual version bump.
Evidence, changed-file attribution and the 14-item audit: `docs/next-playback-decision.md`.

### T53a — durable file history approved (2026-09-24)

The owner approved PostgreSQL completion history across close/reopen, retaining manual rewatches.
The additive receipt/membership contract is documented before implementation in master plan §6.9
and CLAUDE.md §5.19. Revision 0005 adds two immutable tables retaining exact completed-event
membership, historical file identity and semantic queue evidence. Playback, curation/review and
same-title provider numbering now coordinate through fresh locked reads and nonblocking transaction
gates; Excel-only retries retain the receipt without appending another completion.

**Not ready:** independent review reproduced a cross-show episode-ID reassignment that bypasses
the source show's gate. The owner must choose refusal/flagging or automatic reassignment plus
watch-list reconciliation; an atomic correction and regression are still required. No Next/Autoplay
route or UI is shipped, and intentional-repeat navigation policy remains open.

Current local verification: **4,040 backend tests, zero skips, 98.94%** coverage (9,510/9,612),
**320 frontend tests**, **196 layout checks**, **31 hook tests**; Ruff, TypeScript and both package
builds pass. No coverage floor was lowered. The new receipt/queue/lock modules are 149/149;
revision 0005 separately 30/30. Migration testing used disposable PostgreSQL only; no live database,
owner workbook or credential file changed. Docker/scanner/remote-CI limitations remain explicit.
The current-code verdict, per-file attribution and 14-item audit are in
`docs/playback-completion-validation.md`. This joins the existing minor **v0.2.0**; source versions
remain **0.1.0**.

## v0.1.0 — the app as it stands

The Excel-backed watch-list app: Phase 0. No release date is recorded — both `version` fields were
set to `0.1.0` at the outset and have never moved, and no release tag exists. This entry is
reconstructed from the working tree so the changelog has a floor to build on, not from a release
event.

### The application

A local, single-user web app over nineteen hand-curated watch orders — Marvel, DCU, Star Wars,
Middle Earth, a WWII chronology and a shelf of anime. **There is no database.** The nineteen `.xlsx`
workbooks in the repository root are the store, committed on purpose so a clone arrives with the
library already in it: nothing to import, migrate or seed.

### Backend

Python 3.13, FastAPI, Pydantic v2, openpyxl and uvicorn, managed by `uv`; 83 modules and 4,160 lines
across `app/backend/src/tv_watchlist/`. Fourteen HTTP routes — nine REST over categories and rows
(`api/categories.py` six, `api/rows.py` three), five for chat (`api/chat.py`). Configuration is one
`Settings` model (`config.py:14-25`) with `env_prefix="TV_"` (`:17`). The Excel layer reads the first
sheet of each workbook whatever it is named, derives its columns and their roles from the header row
and the sheet's own data validations, and writes edits back in place while preserving the table,
dropdowns and conditional formatting, so opening the file in Excel afterwards shows exactly what the
browser did.

Every mutation funnels through one `Catalog`: a per-workbook lock, an `mtime` freshness guard that
refuses a write whose base changed on disk, a pre-write snapshot into `app/.backups/` (last ten
kept), and an atomic temp-file-and-swap save so a half-failed write never truncates the original.
A workbook open in Excel is refused with HTTP 423 (`api/errors.py:36`) rather than clobbered.
Retiring a category *moves* its workbook and artwork aside; nothing is ever unlinked. Files that
will not parse, and files shadowed by a namesake, are surfaced in the listing rather than silently
omitted.

### Frontend

React 18, TypeScript strict, Vite and Redux Toolkit, managed by `pnpm@9.15.9` — no router, no chart
library, no CSS framework, no UI kit. Four store slices (`catalog`, `category`, `chat`, `ui`), 31
components, 20 one-concept type files and 8 stylesheets. A wall of category cards with generated
geometric backdrops drawn from each category's id and accent colour, overlaid with franchise artwork
from `app/heroes/`; a category view whose rail cycles each entry through the sheet's own dropdown
vocabulary; a reference drawer for a workbook's supporting sheets; and dialogs for adding entries,
creating a category and retiring one. Writes are optimistic and queued per workbook, with each
response's `mtime` threaded into the next request so two quick clicks cannot manufacture a conflict
with themselves, and a stale refusal re-reads the workbook and replays whatever edits are still in
flight.

### Chat dock

A research assistant built on `claude-agent-sdk`, shelling out to the `claude` CLI and streaming a
turn as SSE frames. It reads categories and fetches pages through an SSRF-guarded fetcher that
escalates to Playwright Chromium when a plain request is blocked, and it can only ever *propose* —
every write it suggests is applied through the same `Catalog` calls the REST endpoints use, after
the user approves it, guarded by the `mtime` the proposal's row numbers were resolved against.
Artwork proposals are chosen by eye from downloaded candidates rather than approved blind, and each
pick is credited in `app/heroes/ATTRIBUTION.md`.

Chat is deliberately unavailable in the containers: the image carries neither the `claude` CLI nor
Chromium, and `/api/chat` answers HTTP 503 there while everything else works normally.

### Layout guard

`pnpm test:layout` mounts the real app with the real stylesheets in a real Chromium at four window
sizes and drives it into eighteen surfaces, asserting for every control that it is inside the
window, that nothing is painted over it, that enough of it is actually there, and that enough of it
answers a click. It exists because jsdom has no layout engine and five separate "button below the
fold" bugs shipped before it did. Nothing in a run touches the network.

### Containers and launchers

Two containers: FastAPI, and an unprivileged nginx serving the built SPA and proxying `/api` and
`/heroes`. The backend healthcheck probes `/openapi.json`, which touches no workbook
(`docker-compose.yml:40-43`). The repo root is bind-mounted as `/library`, so the containers read and
write the same workbooks the clone arrived with. `run_tv.sh` and `run_tv.bat` are the host-native
alternative — first-run install, both dev servers in one terminal, then a menu with `[r]` restart and
`[k]` stop (`run_tv.sh:120-121`, `run_tv.bat:84-85`). Neither launcher invokes `docker compose`, so
neither offers `[q]` or `[v]`. Ports: `5284` frontend, `8284` backend, and `5286` for the
layout-guard probe server (`app/frontend/layout/probeServer.ts:1`), which binds only during a guard
run.

### CI

GitHub Actions, six stages gated in order — `lint -> sast -> test -> coverage gate -> build ->
docker-build` — plus a separate CodeQL workflow. The SAST stage runs Semgrep against six named packs
— `p/default`, `p/owasp-top-ten`, `p/python`, `p/typescript`, `p/react`, `p/docker`
(`ci.yml:122-127`) — with its SARIF uploaded to the Security tab, `pip-audit` over the exported
lockfile, `pnpm audit --audit-level=high`, and gitleaks over the tree; `docker-build` scans both
images with Trivy. All three test jobs publish JUnit XML through `dorny/test-reporter`, so a run
shows per-test results including when it fails. The coverage gate holds each suite at the figure it
measures today — backend 97% lines, frontend 56% lines / 54% statements / 45% functions / 45%
branches (`ci.yml:39-43`) — and ratchets: coverage may rise, never slip. Every `uses:` is pinned to a
40-character commit SHA; the header comment (`ci.yml:7-11`) expects Dependabot's `github-actions`
ecosystem to bump those SHAs, and no `.github/dependabot.yml` exists yet to do it.

Suites at this version: **722** collected pytest tests, **207** Vitest tests across 20 files, and
**152** Playwright layout runs (38 tests x 4 viewports) in real Chromium.
