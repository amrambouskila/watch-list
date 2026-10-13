> **MANDATORY WORKFLOW: READ THIS ENTIRE FILE BEFORE EVERY CHANGE.** Every time. No skimming, no assuming prior-session context carries over — it does not.
>
> **Why:** This project spans multiple sessions and months of development. Skipping the re-read produces decisions that contradict the architecture, duplicate existing patterns, break data contracts, or introduce tech debt that compounds. This repository is worse than most for that: the nineteen `.xlsx` workbooks at its root are irreplaceable hand-curated data, and a write that bypasses the safety funnel described in this file can damage them permanently.
>
> **The workflow, every time:**
> 1. Read this entire file in full.
> 2. Read `docs/TV_MASTER_PLAN.md` — the master plan, at the repository root under `docs/`.
> 3. Read `docs/status.md` — current state / what was just built.
> 4. Read `docs/versions.md` — recent version history.
> 5. Read the source files you plan to modify — understand existing patterns first.
> 6. Then implement, following the rules and contracts defined here.

---

<critical_context>

## 0. Critical context — read this before anything else

### 0.1 The defining constraint: the workbooks are the curated data

Nineteen Excel workbooks sit at the repository root:

```
Attack_On_Titan.xlsx   Bleach.xlsx        DCU.xlsx            Demon_Slayer.xlsx
Fullmetal_Alchemist.xlsx  HunterXHunter.xlsx  Inuyasha.xlsx    Marvel.xlsx
Middle_Earth.xlsx      Misc_Anime.xlsx    Misc_Movies.xlsx    Misc_TV.xlsx
My_Hero_Academia.xlsx  Naruto.xlsx        One_Piece.xlsx      Pokemon.xlsx
Star_Wars.xlsx         WWII.xlsx          Yu-Gi-Oh!.xlsx
```

Between them they hold **996 data rows**, and they are **committed on purpose**. `.gitignore:1-7` opens with the banner "The workbooks ARE the database.", explaining that the root `*.xlsx` files and the artwork in `app/heroes/` are committed so a clone arrives with the library already in it, and instructing that `*.xlsx` is never added to that file. (T01c corrected the "eighteen" that banner and `README.md:47` both used to carry; `.gitignore:4` now reads nineteen.) `.gitattributes:54-56` marks `*.xlsx *.xlsm *.xls` as `binary`, and `.gitattributes:10` calls that "the single most important line in this file" — an `.xlsx` is a zip container, so a text-mode checkout would rewrite bytes inside it and corrupt every workbook.

These files are not a seed, an export, a fixture, or a legacy format waiting to be migrated. They are:

- **the authored artifact.** Marvel's 141 rows open X-Men → Blade II → Spider-Man → Daredevil: four consecutive rows carrying four different `Universe / Continuity` values. WWII's 84 rows are ordered by the historical event each film depicts, never by anything about the film — row 3 is *The Sound of Music*, released 1965, `Event` "Mar 1938, Anschluss"; row 4 is *1939 Battle of Westerplatte*, released 2013, `Event` "1 Sept 1939, invasion of Poland". No sort by air date, popularity or franchise could reproduce either. The order *is* the work.
- **still edited in Excel, by hand, by the owner.** Every safety mechanism in this codebase exists because the owner may have a workbook open in Excel right now.
- **the reason the app is worth having.** A clone arrives working: no database to create, no migration to run, no seed to load.

### 0.2 From Phase 1 onward: Postgres is a DERIVED PROJECTION, not a replacement

Phase 1 introduces PostgreSQL. It does **not** end the arrangement above. The store is deliberately **dual**, and the split of authority is fixed:

| Owned by the `.xlsx` workbooks | Owned by Postgres |
|---|---|
| Watch **order** (`position`, the authored chronology) | Episodes, seasons, air dates, runtimes |
| Hand curation — which titles, which spans, the prose in every other column | Alternate episode orderings (aired / dvd / absolute) |
| The four-value `Watched?` cell, as a **mirror** | Artwork metadata, external ids, sync cursors |
| Column layout, dropdowns, conditional formatting, accent colour | Watch **progress**, as an append-only event log |

Concretely, and non-negotiably:

- **Excel → Postgres on read.** Ingest reads a workbook through the existing `workbook/reader.py`, under the existing lock, and projects each data row into `curated_entry`. Postgres never invents, reorders, or "corrects" `position`.
- **Progress is written to BOTH.** A watch action appends a `watch_event` row (the rich, durable truth: which episode, how far in, when, from what device) *and* projects onto the sheet's four-value `Watched?` cell, so a workbook opened standalone in Excel still means something.
- **The `Watched?` cell is never read as truth.** It is read only to detect that a *human* changed it in Excel. See section 5.16.
- **Nothing is ever deleted.** Retirement moves a workbook into `app/.backups/` under a `retired-` stamp (`services/retirement.py:17-36`); Postgres mirrors that with soft deletes (`category.retired_at`, `curated_entry.removed_at`) and `ON DELETE RESTRICT` on `watch_event.curated_entry_id`.
- **The join key to any future media server is `tmdb_id`.** Chosen now, in Phase 1, so Phase 3 has nothing to retrofit (section 5.13, `title`).

If a proposed change would make Postgres authoritative for watch order, or would stop a workbook being independently openable and meaningful in Excel, it is out of scope regardless of how much simpler it looks. Stop and flag it.

### 0.3 What this project is NOT

- **Not an unlicensed streaming app.** It does not stream, proxy, transcode, or link to anything a licence does not cover. T52's native video plays the owner's indexed files through a same-origin backend proxy only.
- **Not a media server.** Jellyfin is the designated playback layer (Phase 3), self-hosted, joined by `tmdb_id`. This repository does not become one.
- **Not a piracy tool, and this has been decided explicitly.** `streambert` (github.com/truelockmc/streambert) was evaluated and **rejected**: it is an Electron desktop client, GPL-3.0, which scrapes unlicensed stream hosts (VidSrc, videasy, vidking, allmanga.to) and rips m3u8 with ffmpeg, and self-describes as piracy. Zero technical overlap, licence contagion, legal exposure. It is recorded as **ADR-006** in `docs/TV_MASTER_PLAN.md` and summarised in the status and versions entries for this change. Nothing from it is adopted. Do not revisit it, and do not add any stream-host scraper, m3u8 ripper, or "watch now" deep link to an unlicensed source.
  ADR-006's second ground does not depend on the repository's licence being settled. The repository carries no LICENSE file. Vendoring GPL-3.0 code would therefore settle the licence question as a side effect of a code-reuse convenience, rather than as a decision — and would settle it on GPL-3.0. That is reason enough on its own, before the other two grounds. The repository's own licence is **ADR-009 — Repository licence — DECIDED (owner, in-session, 2026-09-20): all rights reserved. The repository stays public and unlicensed on purpose; no `LICENSE` file is added, now or later — the absence is the decision, not a gap.** T01d closes with that record. The artwork in `app/heroes/` stays Wikimedia PD/CC0/CC BY material governed by `app/heroes/ATTRIBUTION.md`, whatever the repository's own terms.
- **Not a native TV app.** The app is watched on a TV via a PC or laptop over HDMI or cast. It **stays a browser app**. No Tizen `.wgt`, no webOS `.ipk`, no `react-native-tvos`, no app-store packaging, no second codebase. The ten-foot treatment in Phase 2 is CSS tokens plus a focus/spatial-navigation library — nothing else.
- **Not multi-user, and not authenticated.** One person, one machine, `127.0.0.1`. There is no login, no session, no user table, and none is planned.
- **Not a public service.** Every listener binds loopback. TMDB is used under its non-commercial terms, and one of them binds this app's chat feature directly: **TMDB's API Terms (§1.C, last updated 2023-10-20) prohibit using "the TMDB APIs or TMDB Content in connection with, including for training, a machine learning (ML) or artificial intelligence (AI) based Application", and §2.A lists LLM chatbots among commercial uses.** That covers inference as well as training. **TMDB content must never enter the chat agent's context.** An earlier draft of this file said the opposite; the terms text, verified 2026-09-15, governs. Section 10 (Security), boundary B6, carries the rule.

### 0.4 What phase we are in, and what that means for scope

**Phase 0 and Phase 1 are closed; Phase 3 and Phase 3.5 are running interleaved. Phase 2 is deferred
(ADR-014/ADR-015).** T33 closed 2026-09-21; the historical unverified Docker/Windows/CI checks remain
explicit in `docs/status.md`, not silently certified. The owner still owns all commits.
Phase 1 supplies the Postgres metadata projection, provider clients, resolver, queue and watch mirror.
Phase 3 builds playback over the owner's files through Jellyfin and the ADR-012 `NOT_IN_LIBRARY`
launcher; Phase 3.5 organises files the owner already has, with no acquisition surface. T48/T49/T50/T51/T52/T57
and T60/T61/T62/T63/T64/T65 are done and reviewed; **T53 automatic snapshots and T66 recoverable
imports are implemented and independently reviewed** (R105/R106, 2026-09-24). Final local evidence:
`docs/snapshots-recovery-validation.md`. T53a's range-advancement ordering rule is approved;
durable file history is now approved and its receipt contract is in §5.19. The foundation passes
local suites but is **not ready**: cross-show episode reassignment bypasses the source-title fence
and needs an owner decision before correction. Repeated-occurrence navigation policy also remains
open. Current evidence and exact blocker: `docs/playback-completion-validation.md`.
T67 needs an exact-file path-correlation contract before implementation.
The phase plans and `docs/status.md` carry their current checkpoints. Ten-foot CSS and
spatial navigation remain Phase 2 work after playback, not prerequisites for it.

Practical consequences for any task you are handed right now:

- New persistence work targets SQLAlchemy 2.0 async + asyncpg + Alembic against Postgres 16-alpine. Not SQLite, not "a JSON file for now", not an in-memory dict.
- Every workbook write — including the new ingest write-back and, in Phase 3, the `Position (s)` column — goes through `Catalog._write`. There is no second write path, and adding one is the single most damaging change that could be made to this repository.
- The Jellyfin index, availability, stream proxy, picker, unresolved view and launcher are **current
  Phase 3 scope** (sections 2.2, 5.13, 13.5, 14.9). T52 playback and T53 automatic snapshots are
  implemented; Next/Autoplay (T53a), the picker and launcher remain separate tasks.
- Ten-foot CSS, spatial navigation and a 1920×1080 layout project are **Phase 2, deferred behind Phase 3**. Design for them; do not build them (section 2.2).
- Docs to touch on every non-trivial change: `docs/status.md`, `docs/versions.md`, and — if a host port moves or is added — `C:\Users\Amram\IMPORTANT\Projects\PORT_ASSIGNMENTS.md`. Phase 1 binds `5525`; Phase 3 binds `8096`.

</critical_context>

---

<project_identity>

## 1. Project identity

### 1.1 What it is

A local, single-user web app for nineteen hand-curated watch orders — Marvel, DCU, Star Wars, Middle Earth, a WWII chronology, and a shelf of anime — that live as Excel workbooks and stay that way. One workbook is one category. The app shows a wall of cards, opens a category as a vertical route with a status rail, edits any cell the sheet allows, and writes every change straight back into the same `.xlsx`, preserving that workbook's table, dropdowns and conditional formatting.

It also carries a research chat: `claude-agent-sdk` shells out to the locally-installed `claude` CLI, with Playwright/Chromium for pages that block plain fetches. The model can research and *propose*; only a human approval writes.

### 1.2 Where it lives on disk

```
C:\Users\Amram\IMPORTANT\Personal\TV
```

Note this is under `Personal\`, **not** under `Projects\`. That does not exempt it from anything: `PORT_ASSIGNMENTS.md:3` states the registry is machine-wide and names `TV` explicitly — "Location on disk does not scope this registry; binding a host port does."

The repository is **public**, which is why CI is GitHub Actions (`.github/workflows/ci.yml`, `.github/workflows/codeql.yml`) and there is no `.gitlab-ci.yml`.

### 1.3 The tree, at the level that matters for orientation

```
TV/
├─ *.xlsx                     The library. Nineteen workbooks. THIS IS THE CURATED DATA.
├─ docs/                      Project trio — see section 1.4.
│  ├─ TV_MASTER_PLAN.md       THE master plan. Authoritative for goals, phases, gates, ADRs.
│  ├─ status.md               Current state. First thing a new session reads after this file.
│  ├─ versions.md             Semver changelog, newest at top.
│  └─ resolver-dry-run.md     Phase 1 artefact: the resolver dry-run report (section 2.1, item 9).
├─ docker-compose.yml         Compose v2, project name `tv-watchlist`. Four services.
├─ run_tv.sh / run_tv.bat     Launchers. Host-native servers over a compose Postgres.
├─ .gitattributes             LF for *.sh, CRLF for *.bat, BINARY for *.xlsx.
├─ .gitignore                 Banner: the workbooks ARE the database.
├─ .semgrepignore             Replaces semgrep's built-in defaults; ignores the library itself.
├─ .github/workflows/         ci.yml — twelve jobs in six stages — and codeql.yml.
└─ app/
   ├─ README.md               How the app works, for a human.
   ├─ backend/                FastAPI + openpyxl. Package `src/tv_watchlist/`.
   ├─ frontend/               React 18 + TS strict + Vite + Redux Toolkit, and the layout guard.
   ├─ heroes/                 Per-category card artwork + ATTRIBUTION.md.
   ├─ docs/                   DESIGN NOTES ONLY — see section 1.4.
   └─ .backups/               Automatic pre-write snapshots (local only, gitignored).
```

Backend package: `app/backend/src/tv_watchlist/` — **220 Python modules / 19,023 lines**, measured
2026-09-23; hatchling builds the wheel. Frontend package: `tv-watchlist-frontend`, managed by the
manifest-pinned `pnpm@9.15.9`.

### 1.4 The two `docs/` directories are not the same thing

This trips people up, so it is stated once, plainly:

- **`docs/` at the repository root** holds the project trio — `TV_MASTER_PLAN.md`, `status.md`, `versions.md` — plus `resolver-dry-run.md` once Phase 1 produces it. This is the directory the mandatory workflow at the top of this file points at. It is new as of the documentation pass that closes Phase 0 (task T00).
- **`app/docs/` holds design notes**, and stays exactly what it is. It currently contains `chat-feature-design.md`. Design notes are narrative documents about how one feature was reasoned through; they are not status, not the plan, and not a changelog. Do not move them, and do not put status or version history there.

### 1.5 The two README files

- **`README.md` (repo root)** is about the *repository*: what is in it, the stack table, how to clone and run on a fresh machine, Docker, the CI pipeline stage by stage, ports, licensing. It carries the CI and CodeQL badges.
- **`app/README.md`** is about the *app*: how a category works, how the card artwork is built (generated backdrop + logo overlay), the safety table, what the layout guard asserts and why, the commands.

Neither is the place for AI guidelines (this file), task tracking (the master plan), current state (`docs/status.md`) or version history (`docs/versions.md`).

Both use Mermaid generously, and both should keep doing so.

**`README.md` had a reconciliation backlog, tracked as task T01c — closed 2026-09-20 in one pass.** The table is kept as the record of what was wrong and where, so a later session recognises a regression rather than re-deriving it. Do not re-open these piecemeal; if one comes back, it comes back with the rest.

| What was wrong (all fixed by T01c) | Where |
|---|---|
| `OWNER/REPO` placeholders in the two badge URLs — the real path is `amrambouskila/watch-list` (the `origin` remote) | `README.md:3-5` |
| `OWNER/REPO` placeholders in the two clone commands | `README.md:86`, `README.md:94` |
| "Eighteen workbooks" — there are nineteen | `README.md:47` (and the same stale count in `.gitignore:4`) |
| Backend test count given as **712**; the real figure at the Phase 0 close was **722**. It is **2290 passed / 227 skipped as of 2026-09-20** and moved on almost every Phase 1 task — section 16.1 has the rule, and T33 re-measured it at the Phase 1 gate | `README.md:30`, `:168`, `:198`, and `app/README.md:130` |
| The Semgrep description does not name the six packs the workflow actually uses — `p/default`, `p/owasp-top-ten`, `p/python`, `p/typescript`, `p/react`, `p/docker` (`.github/workflows/ci.yml:121-131`), and specifically **not** `--config auto` | `README.md` CI section |
| The "There is no database." opening does not survive Phase 1 | `README.md` |
| No phase-flow diagram, which the global contract requires of a phased project's README | `README.md` — add **P0 → P1 → P2 → P3**, with the ADR-014 build order (P1 → P3 → P2 deferred) annotated |

### 1.6 Versioning — the source of truth, and what you may not touch

- Backend: the `version` field in `app/backend/pyproject.toml:3` — currently `0.1.0`.
- Frontend: the `version` field in `app/frontend/package.json:4` — currently `0.1.0`.
- `main.py:27` also passes `version="0.1.0"` into the `FastAPI(...)` constructor. It is a third copy of the same number — kept in step by the release pipeline, not hand-edited by a session.

**Never edit those version fields.** That is the release pipeline's job (and there is no release workflow yet — `.github/workflows/` holds only `ci.yml` and `codeql.yml`, so bumping is currently a deliberate manual act by the owner). Your job is to compute the next version and record it in `docs/versions.md`, per section 6 of the global `CLAUDE.md` (Versioning Protocol). Only one unreleased version entry may stand above the source-of-truth version at a time.

</project_identity>

---

<phase_constraints>

## 2. Phases

```mermaid
graph LR
  P0["P0 — the shipped workbook app<br/>FastAPI + openpyxl + React<br/>closed by this documentation pass"]
  P1["P1 — metadata spine<br/>Postgres projection<br/>TMDB + TVDB ingest"]
  P2["P2 — ten-foot browser UI<br/>spatial navigation<br/>10-foot type + safe-area tokens"]
  P3["P3 — playback<br/>self-hosted Jellyfin<br/>joined by tmdb_id"]
  P0 --> P1 --> P2 --> P3
```

**Phase 0 — the shipped workbook app** is a real phase, not a prologue. Everything described in sections 3-5 and 12-16 is Phase 0 output, already shipped and in daily use; its one remaining gap was documentation, which tasks **T00**, **T01**, **T01a**, **T01b** and **T01c** close. Wherever the phase sequence is drawn — here, in `docs/TV_MASTER_PLAN.md`, in `docs/status.md`, and in the `README.md` diagram T01c adds — the *numbering* reads **P0 → P1 → P2 → P3** and is never drawn starting at P1; since ADR-014 the *build order* (P0 close → P1 → P3 → P2 deferred) is drawn beside it, as `docs/status.md` §2 does.

**Build order after 2026-09-20: P0 close → P1 → P3 → P2 (deferred).** The numbering above is canonical and does not change; the *order of construction* does (ADR-014). Phase 3 — Jellyfin playback over the owner's own files, the backend stream proxy, three-state availability, the `AMBIGUOUS` picker, the unresolved view and the ADR-012 launcher as the `NOT_IN_LIBRARY` fallback — follows the Phase 1 gate directly, because every one of those joins on Phase 1 artefacts. Phase 2 (T34–T45) is deferred, not cancelled; T52 depends on T33, not T45. Phase 3 adopts `GET /api/categories/{id}/entries` only for its availability-and-progress layer; the workbook `CategoryDetail` stays the editing contract, unchanged. Its tasks are T46–T58 and its gate is `docs/TV_MASTER_PLAN.md` section 10.3.

### 2.1 Phase 1 — in scope

1. **A Postgres 16-alpine service** in `docker-compose.yml` — **built at T09, 2026-09-20** (`docker-compose.yml:92-116`), published on host port **`5525`** as `127.0.0.1:${TV_POSTGRES_PORT:-5525}:5432`. The bind address is part of the mapping, not decoration: every listener in this project is loopback-only and the dev credentials are `tv`/`tv`, so an all-interfaces publication would put a trivially-guessable database on the network (Ruling 24). Never on host `5432` — that is the machine's single shared local PostgreSQL listener and a containerized Postgres must never bind it. The database is **`tv`** (`${TV_POSTGRES_DB:-tv}`) and the CI service container uses **`tv_test`**; the `pg_isready` healthcheck names the same variable. `tv_watchlist` is the Python package name and the compose project / image prefix — it is **not** a database name.
2. **SQLAlchemy 2.0 async + asyncpg + Alembic** in `app/backend/src/tv_watchlist/data/`.
   Eleven tables in `0001`, plus two views and the append-only trigger; T49 adds `jellyfin_item` in
   `0002`, T61 adds `media_import` in `0003`, and T66 adds `media_import_operation` in `0004`.
   T53a's `0005` adds `playback_completion` and `playback_completion_event`: **sixteen domain tables now**.
   T55's future `streaming_offer` makes seventeen. The flattened queue is `curated_entry_item`.
3. **Ingest from Excel into Postgres** — the reconciliation whose algorithm `docs/TV_MASTER_PLAN.md` specifies, reusing `workbook/reader.py`, `lock_for`, and `Catalog._write`.
4. **Two app-owned columns, and one contract change per column.** Phase 1 writes the **`Row ID`** identity column into each workbook at the far right, hidden; Phase 3 adds a visible **`Position (s)`** column beside it (written every 60 seconds while playing and on pause, ended and unmount through `Catalog._write`; ADR-014). `ColumnSpec.role` gains **`"identity"` at T22 (Phase 1)** and **`"position"` at T53 (Phase 3, ADR-014)**; each is flagged in section 5.1 and each is a **minor** semver bump on its own commit. A `"position"` literal with no consumer until Phase 3 would be a stub, so it lands with the column it names. Both roles are app-owned and both are excluded by the reader from `columns` and `WatchRow.cells`, so the grid the UI renders is unchanged and `RowWrite` can never address them.
5. **TMDB ingest** — the primary metadata spine. The Read Access Token (`TV_TMDB_READ_ACCESS_TOKEN`, `Settings.tmdb_read_access_token` — `env_prefix="TV_"` derives the field name mechanically) travels as an `Authorization: Bearer` header against the `https://api.themoviedb.org/3` base URL. Never ship a TMDB credential to the browser bundle; proxy through the backend.
6. **TheTVDB v4 (End-User Subscriptions key; the owner holds the user subscription)** for alternate episode **orders** only, using `TV_TVDB_API_KEY` and `TV_TVDB_PIN`. **Seven season types are live in production (measured against `GET /v4/seasons/types`, 2026-09-15)** — `official`, `dvd`, `absolute`, `alternate`, `regional`, `altdvd`, `alttwo` — and TheTVDB's OpenAPI document lists them as *examples*, not as an enum, so the set is not closed. `default`, which earlier drafts of this list named, is **not** a season type: it is accepted as an episodes-endpoint path and returned exactly what `official` returned (measured 2026-09-15), so treat it as an alias, never as an eighth type. **The TheTVDB series id is never searched for** — TMDB's `/tv/{id}/external_ids` returns `tvdb_id` directly (verified 2026-09-15 for One Piece, Dexter and Pokémon), whereas TheTVDB's own search ranked the One Piece anime eighth behind a 2023 live-action namesake. **Names are requested through the `/eng` language variants**; TheTVDB's default is the original language, which is Japanese for anime. **The operative rule: read the season-type list at runtime from a cached `GET /v4/seasons/types`, and never hard-code it** — here or anywhere else this document discusses the orders.
7. **The watch-progress log and the four-value mirror** (section 5.16).
8. **The provider response cache lives in Postgres** — `sync_state` plus a payload digest (section 5.13). No cache service and no queue enters the stack; see section 2.2.
9. **The resolver dry-run report — done at T31, 2026-09-20.** Written to **`docs/resolver-dry-run.md`** — a durable file, deliberately *not* `docs/status.md`, which states the present and is explicitly not a log. One row per workbook, with the columns **rows, confirmed, auto-resolved, unresolved**, plus that workbook's worst-confidence examples. The risk register and the Phase 1 gate both reference that file by name. The measurement it records: **830 of 996 auto-resolved (83%), 166 for the review queue, `confirmed` 0** — section 18.2 rule 3 carries the confidence rungs.
10. **The launchers have gained `[q]` and `[v]` — T32a, 2026-09-20, review closed.** They were absent for one reason only: neither launcher invoked `docker compose` at all. Phase 1 changed that, because compose now owns a Postgres service and a named volume, and the launchers start it: the host path runs `docker compose up -d postgres`, waits for the healthcheck, applies `alembic upgrade head`, and only then starts the two host-native dev servers. `[k]` is `docker compose down` (Ruling 28 — the global contract's `[k]`, images and volumes kept); `[q]` is `docker compose down --remove-orphans` plus removal of the `tv-watchlist`-prefixed images, **keeping** volumes; `[v]` adds `--volumes`, dropping `tv_postgres_data` and the two Jellyfin volumes. `[r]` stays non-terminal and unlimited. Section 6.5 has the line references. Neither launcher has been run end to end yet — the VPN block stops `docker compose up`.
11. **The documentation and wiring tasks that close Phase 0**, each of which the **Phase 0** gate (`docs/TV_MASTER_PLAN.md` section 10.0) checks — not the Phase 1 gate. Phase 0 closes on five tasks: T00, T01, T01a, T01b and T01c. **All five are code-complete as of 2026-09-20 and nothing is committed yet — the owner commits.** Section 10.1 keeps only what it needs of T01c: the README's "There is no database." opening had to be rewritten before Phase 1 could close, because Phase 1 falsifies it; that rewrite has landed.
    - **T01a — done.** The `.claude/` wiring exists: `.claude/settings.json` with six PascalCase hook entries, six commands (`scaffold`, `review`, `pre-commit`, `validate`, `phase-status`, `new-model`) and five skills (`phase-awareness`, `excel-safety-protocol`, `data-driven-check`, `validation-protocol`, `dual-store-protocol`). The OS-agnostic `.cjs` hook set lives in **`scripts/hooks/`** (`hookUtils`, `session-start`, `pre-tool-use`, `post-tool-use`, `pre-compact`, `stop`, `stop-memory`, plus `hooks.test.cjs` — **31 node tests**, run as `node --test scripts/hooks/hooks.test.cjs`, the *file* form, because the directory form fails on Node 24). `.claude/` is gitignored, so **only `scripts/hooks/` travels with the repo**. **Node `.cjs` only, never shell hooks**; tool data is read from **stdin**, never from `$CLAUDE_*` environment variables.
    - **T01b — done.** `.env.example` exists at the repository root with **16 `TV_` variables**, each with a safe placeholder and a one-line comment, plus `app/backend/tests/env_example_support.py` and `app/backend/tests/test_env_example.py` (19 tests) keeping it in step with `Settings`. `.gitignore:30-32` carries the `!.env.example` negation, so the example is committed while the real `.env` is not.
    - **T01c — done.** The README reconciliation pass (section 1.5), including the `P0 → P1 → P2 → P3` phase-flow diagram with its build-order note, the dual-store opening, Licensing stating ADR-009, and the `jellyfin` service with `8096` and `5525` in the Ports table.
12. **Registry upkeep — done at T11, 2026-09-20.** The `5525` row is in `C:\Users\Amram\IMPORTANT\Projects\PORT_ASSIGNMENTS.md`, in both the final host-listener map and the per-project inventory, with the database-name line now reading `tv` / `tv_test`. **`5525` is the only host port Phase 1 allocates.** Phase 3's one extra port — **`8096`** for the Jellyfin compose service (T47a) — was bound and registered the same way on 2026-09-20, ahead of its phase (`PORT_ASSIGNMENTS.md:109`, map row, plus the inventory bullet). So the project's full host-listener set is `5284`, `8284`, `5286` (live), `8096` (bound 2026-09-20) and `5525` (bound and registered 2026-09-20, T09 and T11). The earlier line "5525 is the only host port across all three phases" is superseded by ADR-014.
13. **Phase 3 settings, declared now so the shape is settled** (read by no code until Phase 3): `TV_JELLYFIN_BASE_URL`, `TV_JELLYFIN_API_KEY` (`SecretStr`), `TV_JELLYFIN_PORT` and `TV_JELLYFIN_MEDIA_HOST` (compose-only), and `TV_STREAMING_AVAILABILITY_API_KEY` (`SecretStr`, the ADR-012 launcher's credential; the owner is signing up for the free plan and T55 is blocked until it is present). Section 8.3 carries the table. The owner creates the Jellyfin key in Jellyfin's own UI and types both Jellyfin values into the root `.env`; no agent writes any `.env*` file.

> The `PreToolUse` hook now exists (T01a, `scripts/hooks/pre-tool-use.cjs`) and enforces two rules mechanically rather than by discipline: it **blocks** a `Write`/`Edit` to `.env*`, `credentials.*`, `secrets.*`, `*.pem`, `*.key` and `*.p12` — with `.env.example` explicitly allowed, since it carries placeholders — and it **blocks** any direct `Write`/`Edit` of an `*.xlsx`, because a tool write bypasses the freshness guard, the snapshot, the Excel-lock check and the atomic swap that section 3.4 requires. Real credentials are still typed by the owner; the difference is that the rule is now a guard.

### 2.2 Do NOT add X — phase Y

| Do NOT add | Phase | Why |
|---|---|---|
| Any playback surface — `<video>`, HLS/DASH players, a transcode call, a "Play" button that does anything | **P3 — build after the Phase 1 gate** | The owner's files exist (T46 satisfied 2026-09-20) and the shape is decided (ADR-014): a browser `<video>` against the backend's same-origin stream proxy, never a direct browser-to-Jellyfin URL. It lands in Phase 3, which follows Phase 1 directly — not before `docs/TV_MASTER_PLAN.md` section 10.1 is green, because the player joins on `title.tmdb_id`, `curated_entry_item` and `watch_event`. |
| Any *further* Jellyfin API call beyond the client itself (sync, availability, playback) | **P3 — build after the Phase 1 gate** | `jellyfin/jellyfin:12.1` as a compose service on `8096`, `httpx` from the backend only — **no `@jellyfin/sdk`**, ever, because only the backend talks to Jellyfin. The join key (`tmdb_id`) is chosen in Phase 1. The compose service (T47a) landed 2026-09-20; **the client itself (T48) is now built** — one client, two `Settings` fields, no route of its own — and is reviewed and approved. The sync (T49, **in review**) and every route that reads from Jellyfin (`services/library_sync.py`, `api/library.py`, `api/playback.py`, T49/T51/T52) still land in the rest of Phase 3. |
| Ten-foot CSS tokens, safe-area insets, focus rings sized for a couch, a 1920×1080 Playwright project | **P2 — deferred behind P3 (ADR-014)** | Phase 2 owns the ten-foot pass as one coherent change. Half of it landing early makes the other half unreviewable. Nothing in Phase 3 needs it, so it waits. |
| `@noriginmedia/norigin-spatial-navigation` or any focus manager | **P2 — deferred behind P3 (ADR-014)** | The spatial-navigation library is *chosen* (MIT; **not** `react-tv-space-navigation`, which is stale; **not** `bbc/lrud`, which is archived) — but it is installed in Phase 2, not before. |
| Tizen `.wgt`, webOS `.ipk`, `react-native-tvos`, Electron, any app-store target | **never** | The app stays a browser app watched over HDMI or cast. A second codebase is not a phase; it is a rejected direction. |
| Auth, login, sessions, a `user` table, roles, sharing | **never** | Single-user, loopback-only, by design. |
| Links to unlicensed sources; any stream-host scraper; "where to watch" data from anything but the Streaming Availability API for Israel (ADR-012) | **never** | section 0.3 and ADR-006 stand. What *is* allowed, in Phase 3 only, is the ADR-012 launcher: one press opens a title in a new tab on the owner's own subscription, availability looked up for `country=il` through the Streaming Availability API and cached in `streaming_offer`, Disney+ marked by hand. The launcher never plays, proxies, frames, scrapes, reads or controls a service's page, and the chat never sees availability data or visits a streaming domain. |
| Trakt as a service integration | **never** | Design inspiration only (its scrobble model is borrowed; see ADR-004). Its Feb 2026 free tier caps **1,000 total list items** and this library already holds **996 rows** — five more entries breach the cap on day one. |
| Plex | **never** | Its 2026 remote-streaming paywall now extends to third-party API clients. |
| A cache service, a message queue, or any second datastore beside Postgres | **never in this design** | Nothing in a single-user, file-backed, single-process app earns one. The provider response cache is `sync_state` plus a payload digest, in Postgres (section 5.13); the launcher's availability cache is `streaming_offer`, also in Postgres. **`5525` (Postgres) and `8096` (Jellyfin) are the only host ports this project allocates beyond the three live ones**, so there is no reservation for anything else to grow into. |
| A second write path to any `.xlsx` | **never** | section 3.4. |
| Editing `version` in `pyproject.toml` / `package.json` | **never** | section 1.6. |

**AniList is deliberately not on that table.** It is **not adopted now, revisitable behind an ADR and a feature flag** — not a permanent non-goal. The rationale is sourced and narrow: TheTVDB already supplies absolute order, which is the one thing AniList would be reached for; AniList's public API is currently degraded to **30 requests per minute**, with rate-limit-increase requests **not being accepted**; and it returns **HTTP 403** during outages. If a measured gap ever forces it, write the ADR first and put it behind a flag. Do not read this paragraph as prior approval, and do not demote it back to a hard non-goal.

### 2.3 Phase gates

**The canonical Phase 1 gate is `docs/TV_MASTER_PLAN.md` section 10.1, and the canonical Phase 3 gate is section 10.3.** The project-specific checklists in section 19 of this file are **in addition to them, not a replacement**, and the two may not quietly diverge: a new gate item goes into section 10.1 or 10.3 first.

Every phase gate in `docs/TV_MASTER_PLAN.md` includes the standard line: **SAST green with zero HIGH findings.** A phase is not done while the `sast` stage is red or a MEDIUM finding is suppressed without a written justification. Phase 1's Alembic requirement is the full round trip — `alembic upgrade head && alembic downgrade base && alembic upgrade head` green in CI against a real Postgres 16 service container — not a single-step `downgrade -1`.

</phase_constraints>

---

<architecture>

## 3. Architecture

```mermaid
graph TD
  subgraph Library["The library — repo root"]
    X[("19 *.xlsx<br/>curated order + Watched?")]
    H[("app/heroes/<br/>card artwork + ATTRIBUTION.md")]
    K[("app/.backups/<br/>pre-write snapshots + retirements")]
  end

  subgraph Backend["app/backend — FastAPI :8284"]
    C["Catalog<br/>the mutation funnel"]
    W["workbook/<br/>openpyxl layer"]
    S["services/"]
    A["agent/<br/>chat + research"]
    D["data/  (P1)<br/>SQLAlchemy 2.0 async"]
    PLAY["api/playback.py  (P3)<br/>stream proxy — Range passthrough<br/>key never leaves the server"]
  end

  PG[("Postgres 16<br/>:5525 — DERIVED projection")]
  TM["TMDB /3"]
  TV["TheTVDB v4"]
  JF["Jellyfin 12.1  (P3)<br/>compose service :8096<br/>optional peer — no depends_on"]
  M[("${TV_JELLYFIN_MEDIA_HOST:-./media}<br/>the owner's files, :ro")]
  SA["Streaming Availability API  (P3)<br/>country=il — launcher only"]
  F["app/frontend — React 18 :5284"]
  U([Browser on the TV])
  CLI[["claude CLI + Chromium<br/>host only"]]

  X --> C
  C --> W
  W -->|atomic temp + os.replace| X
  C --> K
  S --> H
  C --> D
  D <--> PG
  D -->|ingest| TM
  D -->|alternate orders| TV
  S -->|library_sync: tmdb_id → Jellyfin Id| JF
  S -->|streaming_offer cache| SA
  M --> JF
  JF -->|/Videos/{id}/stream + key header| PLAY
  PLAY -->|same-origin video src| F
  C <-->|/api| F
  S -->|/heroes| F
  F --> U
  A -.->|propose only| C
  A -.-> CLI
```

### 3.1 One concept per file — as it applies here

The global rule is already lived in this repository, and the file counts are the proof: `models/` holds 20 files, one Pydantic model each; `frontend/src/types/` holds 20 files, one contract each; `frontend/src/api/` holds 16 files, one call each; `frontend/src/hooks/` holds 9, `frontend/src/utils/` holds 12. `workbook/` splits into 17 modules — `schema.py`, `cells.py`, `ranges.py`, `reader.py`, `writer.py`, `creator.py`, `renaming.py`, `discovery.py`, `naming.py`, `stem.py`, `locking.py`, `freshness.py`, `backup.py`, `backup_names.py`, `styling.py`, `heroes.py`, `errors.py` — rather than growing one `excel.py`.

Match it. Concretely:

- One SQLAlchemy model per file under `data/models/`.
- One Pydantic model per file under `models/`.
- One React component per `.tsx`, one hook per `useCamelCase.ts`, one utility per file, one interface per `types/*.ts`.
- **The single sanctioned exception is `data/enums.py`**, which holds every `StrEnum` plus the `pg_enum()` helper. They are one closed vocabulary the whole schema shares; a dozen-plus single-member modules would be ceremony. `JellyfinItemKind` (`movie` / `series` / `episode`) arrived at T49; **`Availability`** (`in_library` / `not_in_library` / `ambiguous`, ADR-013) arrives with its computing service at **T51**. Availability is computed, never stored: it has no Postgres enum type or migration. Do not use this exception as a precedent for anything else.
- `constants.py` (93 lines) is the only home for universal constants — header aliases, watch vocabulary, colours, widths, row indices, filename rules, caps, hero rules. `agent/constants.py` is its counterpart for the chat subsystem. Nothing else declares a magic literal.

### 3.2 The column schema is derived at runtime. Nothing about layout may be hard-coded.

Nineteen workbooks carry eight to twelve *different* columns. Marvel has `Universe / Continuity`; WWII has `Event` and `Theatre`; Pokemon has `Continuity`, `Status / Canon` and `Source`; `Misc_Anime` heads its order column `#` and carries its own `Started?`, `Progress` and `Priority` columns; `Misc_Movies` rows carry only `Order` and `Title` with every other cell `None`. This all works because **the schema is discovered, never assumed** (`workbook/schema.py`):

- **The grid ends at the first blank header cell.** `header_width()` (`workbook/schema.py:76-84`) walks row 1 until a blank and returns the width of that contiguous run. The writer's `_grid_width` (`workbook/writer.py:156-158`) takes the max of that and the highest `ColumnSpec.index`, and its docstring states the rule for both: "never sheet.max_column, which counts stray cells to the right".
- **The column key is `slugify(label)`**, falling back to `column-{index}` for an unslugifiable header, disambiguated `-2`, `-3`, … against keys already taken (`workbook/schema.py:64-73`). So `"When to Watch"` → `when-to-watch` and `"Watched?"` → `watched`. `unique_key` is the **one place column keys are minted** — `models/category_create.py:19` imports it rather than reimplementing, so a create request's vocabulary matches what the reader will derive from the headers that request writes.
- **The role comes from normalised header aliases** (`constants.py:7-9`, applied by `_role_for` at `workbook/schema.py:28-36`): `{"watched"}` → `watch`; `{"title","name","show"}` → `title`; `{"order","#","no","num"}` → `order`; everything else → `other`. Normalisation lowercases and strips punctuation, with `#` deliberately carved out of the punctuation class (`workbook/schema.py:18-19`) because `Misc_Anime` heads its order column with it.
- **The kind comes from data validations, not the header**: `kind="choice"` iff the column carries an inline list validation with at least one option, else `"text"`. A range-backed validation yields no choices and therefore a `text` column.
- **The width** comes from `sheet.column_dimensions` when present, else `None`.
- **The first worksheet is the watch order; every later worksheet is a read-only `ReferenceSheet`** (`read_category`, `workbook/reader.py:70-99`; the first sheet at `:73`, the rest at `:99`).
- **A category's identity is its filename.** `id = slugify(path.stem)`, `name = path.stem`, `file_name = path.name` (`workbook/naming.py:17-24`). Nothing about the name is stored inside the workbook. Renaming the file renames the category and changes its id, which is why `Catalog._carry_artwork` (`services/catalog.py:181-187`) moves the hero images across explicitly.

**Therefore:** never index a column by position. Never assume a column exists. Never assume `Watched?` is last, or that `Order` is called `Order`. Read the `ColumnSpec` list and key by `role` or by `key`. Any new code that would break if a workbook grew a column, dropped one, or renamed a header is wrong.

Two files that already do this correctly and are worth copying: `hooks/useWatchColumn.ts:6-8` (finds the column whose `role === "watch"`) and `hooks/useRowColumns.ts:15-25` (picks `order`, `title`, and up to four `other` columns narrower than 40 for a collapsed row).

### 3.3 The write-safety apparatus

Five mechanisms, all of which already exist, none of which may be bypassed:

1. **Freshness guard.** `guard_fresh(path, expected_mtime)` (`workbook/freshness.py:14-17`) raises `StaleWorkbookError` unless the file still carries the mtime the caller last read. Tolerance is `MTIME_TOLERANCE_SECONDS = 1e-6` (`workbook/freshness.py:11`), because "an mtime crosses the wire as a JSON float and comes back rounded, so equality is too strict a test." Maps to HTTP **409**. Every mutating call carries `expected_mtime`: in the body for `RowWrite` / `CategoryRename`, as a **required query parameter** for the three bodyless mutations, and as `ProposalEdit.read_mtime` for a chat approval.
2. **Excel-lock probe.** `is_locked_by_excel(path)` (`workbook/locking.py:31-39`) has two arms: the presence of a sibling `~$<name>.xlsx` owner file, **or** any `OSError` opening the file `r+b`. Either means locked. Maps to HTTP **423**. It is checked twice — once in `writer._open` (`workbook/writer.py:43-47`) before loading, and again as a `PermissionError` short-circuit inside `_install` (`workbook/writer.py:50-64`).
3. **Per-workbook serialisation.** `lock_for(path)` (`workbook/locking.py:15-23`) is a process-global `dict[Path, asyncio.Lock]` keyed by `path.resolve()`, with the registry mutation itself guarded by a `threading.Lock`. `HeroStore` reuses it for two non-workbook keys — `heroes.artwork_key(heroes_dir, id)` (`workbook/heroes.py:27`) and `heroes_dir / "ATTRIBUTION.md"` — **always in that order** (`services/hero_store.py:55-56`), so two artwork picks can never deadlock against each other.
4. **Atomic install.** `_save` (`workbook/writer.py:67-78`) writes to a sibling temp named `.~tv-write-<pid>-<stem>.tmp` in the same directory (so the rename is same-filesystem), then `_install` (`workbook/writer.py:50-64`) calls `os.replace`. A `PermissionError` is retried `REPLACE_RETRIES = 5` times with `REPLACE_RETRY_SECONDS = 0.08` sleeps (`constants.py:40-41`), short-circuiting immediately if the Excel owner file has appeared. Any `PermissionError` escaping becomes `WorkbookLockedError`; any other `BaseException` unlinks the temp and re-raises. **The original is never truncated.** The same temp-and-swap shape is reused by `create_category` (`workbook/creator.py:117-145`) and `_swapped_in` (`services/attribution.py:57-62`).
5. **Pre-write snapshots.** `snapshot(path, backup_dir, retention, interval_seconds)` (`workbook/backup.py:59`) copies the workbook aside before it is modified, into `app/.backups/`. `BACKUP_RETENTION = 10`, `BACKUP_INTERVAL_SECONDS = 900.0`, `BACKUP_TIMESTAMP_FORMAT = "%Y%m%d-%H%M%S"` (`constants.py:56-59`); ordinals `_02`, `_03`, … are zero-padded to `ORDINAL_WIDTH = 2` (`workbook/backup.py:21-25`) **because pruning reads names in sort order and an unpadded `_10` would sort ahead of `_2` and be dropped as the oldest**. The throttle is passed by **`Catalog.update_row` only**; every other write passes `backup.NO_THROTTLE = 0.0` (`workbook/backup.py:17`) and snapshots unconditionally. The stamp is recorded only *after* the copy succeeds, so a failed backup is retried rather than skipped. A retirement files under the `RETIRED_STAMP_PREFIX` (`constants.py:60-62`) that pruning can never reach.

Also: **nothing is deleted, ever.** `retire_category` (`services/retirement.py:17-36`) *moves* a workbook and every one of its hero suffixes into `app/.backups/` under one shared `retired-<timestamp>` stamp. `retire_heroes` (`services/hero_backup.py:13-25`) moves a superseded image aside rather than overwriting it, because "a hand-made, hand-recoloured mark is the one thing in this app that cannot be fetched again."

### 3.4 The mutation funnel — every write goes through it

`Catalog._write` (`services/catalog.py:131-141`) → `Catalog._mutate` (`services/catalog.py:122-129`) is **the** write path. `_mutate`'s five steps run in this fixed order, inside `async with lock_for(path)` and on a worker thread via `asyncio.to_thread` so openpyxl never blocks the event loop:

```
1. guard_fresh(path, expected_mtime)        → 409 if the file moved on
2. self._snapshot(path, interval_seconds)   → backup.snapshot, throttled or not
3. action()                                 → the workbook.writer call
                                              (re-checks the Excel lock; temp + os.replace)
4. self._invalidate(path)                   → drop the cache entry
5. self._read_live_lock(path)               → re-read and return a fresh CategoryDetail
```

Everything that mutates a sheet uses it: `update_row` (`services/catalog.py:143`), `append_row` (`:153`), `delete_row` (`:160`), `apply_changes` (`:164`), `add_watch_column` (`:168`). Chat approvals reuse it **verbatim** — `_applied` (`api/chat.py:76-80`) dispatches a `ProposalEdit` straight into `catalog.apply_changes(...)`, so a model-authored change gets the identical freshness guard, backup, lock check and atomic swap a human edit gets.

Rename, retire and create do not use `_write` because they change the path itself, but they take the same lock and run the same guard/snapshot sequence by hand (`services/catalog.py:172-212`).

**The Phase 1 rule that follows:** the ingest write-back — minted `Row ID` values, re-minted duplicates, `Watched?` mirror updates — is **one `Catalog._write` call carrying every cell change**. One snapshot, one temp file, one `os.replace`, one mtime bump, and the post-write `st_mtime` is what gets stored so the next pass does not see our own write as a change. Calling openpyxl directly from `data/` or from a service is forbidden.

### 3.5 The chat subsystem, and why the model can never write

- Four tools, exactly: `WebSearch`, `mcp__library__fetch_url`, `mcp__library__get_category`, `mcp__library__propose` (`AGENT_ALLOWED_TOOLS`, `agent/constants.py:26-31`; wired in `build_agent_options`, `agent/options.py:21-35`). `setting_sources=[]` (`agent/options.py:27`) so the machine's Claude config is not inherited; `env={}` (`:34`) so no environment passes through.
- `get_category` is read-only, hands the model only `columns` and `rows`, and stamps the session's `ReadLog` with the workbook mtime it read.
- `propose` is the only write-adjacent tool, and it **mints two fields the model cannot choose**: `id` (`uuid4().hex`) and, for an edit body, `read_mtime` (taken from the session `ReadLog`). Both are stripped from the tool's JSON schema by `_drop_field` / `_drop_field_everywhere` (`agent/tools/propose.py:44-70`), so the model literally cannot supply them. A category the session never read produces an error result telling the model to call `get_category` first.
- Nothing reaches disk until a human `POST /api/chat/proposals/{id}/approve` (or `.../hero/{choice}`).
- Fetched web content is wrapped in `<<<UNTRUSTED_WEB_CONTENT>>>` / `<<<END_UNTRUSTED_WEB_CONTENT>>>` (`agent/constants.py:61-62`) and the system prompt names a page that tells the model to ignore its rules an *attack*. Every outbound URL passes `assert_public_http_url` (`agent/url_guard.py:52`) — scheme must be `http`/`https` (`agent/constants.py:33`), and every resolved address must be publicly routable.
- Under Docker, chat answers **HTTP 503** by design: the image carries neither the `claude` CLI nor Chromium, and the Linux wheel's bundled ~340 MB `claude` binary is deliberately deleted in the same `RUN` layer so a chat turn fails cleanly rather than dying at authentication. Everything else in the image works normally.

### 3.6 Frontend architecture

- **Redux Toolkit** for app state — four slices, `configureStore({ reducer: { catalog, category, chat, ui } })` (`stores/store.ts:8`), default middleware only, no listener middleware, no persistence. React `useState` is used only for genuinely local UI concerns (`CategoryStage`'s `adding` / `retiring` flags, a `CellField`'s draft).
- **The write queue lives outside Redux**, in `stores/writeQueue.ts:22-41` — two module-level `Map`s, `chains` (categoryId → tail promise) and `latest` (categoryId → freshest mtime), declared at `:5-6`. It exists because "a thunk's promise settles before the store commits its result", so the fresh mtime cannot be read back out of Redux in time. Three details are load-bearing: `tail.then(start, start)` (`:29`) passes `start` as **both** handlers so a failed write does not stall the queue; the mtime handed to `run` is read at the moment the write *starts*, not when it was queued (`:27`); and the stored chain tail swallows both outcomes (`:33-39`) so an unhandled rejection can never escape. `retireWorkbook` is deliberately **not** queued (`stores/categorySlice.ts:134-145`, with the reason at `:129-132`), because its response carries no mtime to thread onward.
- **Optimistic paint with replay.** Only `writeRow` paints optimistically. `pending` is keyed by thunk `requestId` (`stores/categorySlice.ts:29-30`); `withPending` (`:173-176`) re-applies every in-flight edit on top of each server response, so an earlier response arriving while later edits are on screen does not repaint rows with pre-edit values. `patchRow` (`:159-164`) is a **shallow cell merge** — only the keys present in `cells` are overwritten.
- **One global toast source**: `addMatcher(isRejectedWithValue, ...)` in `stores/uiSlice.ts:91-99`. A stale-mtime refusal that produced a successful re-read becomes an **info** toast; every other refusal is an **error** toast.
- **No router.** Navigation is `state.ui.view` (`"home" | "category"`) plus `state.ui.activeCategoryId` (`stores/uiSlice.ts:11-12`).

### 3.7 No UI framework, and that is deliberate

`package.json` runtime dependencies are exactly: three `@fontsource` packages, `@reduxjs/toolkit`, `react`, `react-dom`, `react-redux`. **No router, no chart library, no CSS framework, no UI kit, no icon package.** Icons are inline SVG; the card backdrops are generated SVG from `utils/motifFor.ts`.

The design system is `src/styles/tokens.css` — 55 lines, one `:root` block. Five of its groups behave as a real design-token layer, consumed by `var()` across every stylesheet: the **ink/mist/paper ramp** (`--ink-950` … `--ink-650`, `--mist-500` … `--mist-200`, `--paper`, at `:2-13`), the **type scale** `--step-0` … `--step-6` (`:29-35`), the **spacing scale** `--gap-1` … `--gap-7` (`:37-43`), the **two radii** (`:45-46`), and the **layout dimensions plus `--toast-lane-max`** (`--sidebar-width`, `--rail-width`, `--order-width`, `--launcher-width`, `--toast-lane-max`, at `:48-54`). The file also declares two translucent edges (`:15-16`), the `--danger` / `--danger-dim` pair (`:18-19`), the `--accent` / `--accent-dim` / `--accent-soft` fallback trio (`:21-23`) that the per-category inline properties override, and the three font stacks `--display` / `--body` / `--mono` (`:25-27`). Eight stylesheets, imported in cascade order by `src/index.css:1-8`: `tokens`, `base`, `sidebar`, `category`, `route`, `home`, `overlays`, `chat`.

Do not add Tailwind, Bootstrap, MUI, styled-components, a router, or a chart library. If Phase 2 needs a new token, it goes in `tokens.css` beside `--launcher-width` and `--toast-lane-max`, which already set the precedent for *behavioural* rather than cosmetic tokens and carry comments saying why.

The accent colour is **data, not a token value**: each workbook's own header fill produces `CategorySummary.accent` (`workbook/reader.py:30-39`), which `utils/accentPalette.ts` lifts into `{accent, dim, soft}` and which reaches CSS only as inline custom properties on a subtree root. `app/frontend/nginx.conf:35-40` carries `style-src 'self' 'unsafe-inline'` for exactly that reason, and its comment names the four components responsible (`CategoryCard.tsx`, `CategoryLink.tsx`, `CategoryStage.tsx`, `NewCategoryDialog.tsx`).

</architecture>

---

<coding_standards>

## 4. Code rules specific to this project

These extend section 7 of the global `CLAUDE.md`; they do not replace it.

### 4.1 Backend

- `from __future__ import annotations` at the top of every module. Full type annotations everywhere — ruff `ANN` is on.
- Ruff config (`pyproject.toml:36-44`): `line-length = 120`, `src = ["src", "tests"]`, `select = ["E", "F", "I", "N", "UP", "ANN", "S"]` (`:41`), `per-file-ignores { "tests/*" = ["S101"] }` (`:43-44`). CI runs **both** `ruff check .` and `ruff format --check .`.
- Source has **seven** justified `# noqa` suppressions and **zero** `# type: ignore`
  (measured 2026-09-23): three `ANN401`s for heterogeneous openpyxl values in `workbook/cells.py`
  and `workbook/writer.py`; the public SQLAlchemy `Row._mapping` accessor in `ingest/tmdb_ingest.py`;
  the logged background-task exception boundary in `services/watch_events.py`; qBittorrent's
  password **field name**, not a secret, in `constants.py`; and its private `_Forbidden` control-flow
  exception in `clients/qbittorrent_client.py`. This continuation adds no suppression. Search both
  patterns before adding one, and require a specific inline reason. Tests are counted separately.
- Pytest: `asyncio_mode = "auto"`, `testpaths = ["tests"]`, `pythonpath = ["tests", "tests/agent", "tests/services"]` (`pyproject.toml:52`) — `tests` itself is on the path so the shared support modules at the tests root import the same way from every test directory.
- Settings are `pydantic-settings` with `env_prefix="TV_"`, `env_file=REPO_ROOT / ".env"` — an **absolute** path since T05, never a cwd-relative string (section 8.1) — and `extra="ignore"` (`config.py:24`), behind an `lru_cache(maxsize=1)` singleton (`config.py:61-64`). **Every new configuration value is a `Settings` field with a `TV_` env var**, never a literal in logic. The prefix derives the name mechanically, so `TV_TMDB_READ_ACCESS_TOKEN` is the field `tmdb_read_access_token` — there is no shorter alias.
- `config.py`'s defaults are computed from two module constants: `REPO_ROOT = Path(__file__).resolve().parents[4]` (`config.py:17`, the library and the `.env`) and `APP_DIR = REPO_ROOT / "app"` (`:18`, backups and heroes). **That path depth is load-bearing** — `app/backend/Dockerfile` sets `WORKDIR /srv/app/backend` in both stages (`:32` builder, `:85` runtime) specifically so the package sits at least five levels below `/`, or the module raises `IndexError` before the app starts. Do not move the package inside the image.

### 4.2 Frontend

- TypeScript strict, plus six stricter flags actually in force (`tsconfig.json:20-25`): `noUnusedLocals`, `noUnusedParameters`, `noFallthroughCasesInSwitch`, `noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`, `verbatimModuleSyntax`.
- `noUncheckedIndexedAccess` is why every indexed read is guarded (`row.cells[column.key] ?? ""`). Keep guarding; do not reach for `!`.
- `exactOptionalPropertyTypes` is why `hero_url?: string | null` accepts *absent* or `null` but **not** `undefined`.
- `verbatimModuleSyntax` is why every type-only import is written `import type { … }`.
- `@typescript-eslint/no-explicit-any` is `"error"` (`eslint.config.js:17`). No `any`, no `@ts-ignore`, no `@ts-nocheck`.
- Model output is rendered as **text**, never as markup. `ChatMessageBubble` (`components/ChatMessageBubble.tsx:10-12`) is one `<p>`; there is **zero** `dangerouslySetInnerHTML` in the tree and none may be added.
- `tsconfig.json` `include` (`:27-34`) covers `src`, `tests`, `layout`, and the three config files, so `pnpm build`'s `tsc -b` typechecks the tests and the layout guard too. That is why the frontend Docker build installs dev dependencies.

### 4.3 Errors are a contract

`api/errors.py` maps domain exceptions to statuses **by exact type, never by MRO** (`_STATUS_BY_ERROR` at `api/errors.py:39-55`, `_MESSAGE_BY_ERROR` at `:57-76`, both read with `.get(type(error), ...)` at `:89` and `:109`), and every refusal returns the same envelope (`payload_for`, `api/errors.py:86-90`):

```json
{ "error": "<ExceptionClassName>", "message": "<humanised>", "detail": "<str(error)>" }
```

| Exception | Status |
|---|---|
| `CategoryNotFoundError`, `RowNotFoundError`, `UnknownSessionError`, `UnknownProposalError` | 404 |
| `EntryNotFoundError`, `WatchSubjectNotFoundError` | 404 |
| `WorkbookLockedError` | **423 Locked** |
| `StaleWorkbookError`, `DuplicateCategoryError`, `ResolutionConflictError` | 409 |
| `UnknownColumnError`, `InvalidChoiceError`, `MissingWatchColumnError` | 400 |
| `UnreadableWorkbookError` | 422 |
| `CLINotFoundError` | 503 |
| `JellyfinUnavailableError` | 503 — disabled/unreachable sync or playback, safe configured-upstream detail |
| `PlaybackItemNotFoundError` | 404 — missing, removed or non-file library item; no upstream call |
| `PlaybackRangeError` | 416 — malformed/multiple/reversed byte range; no upstream call |
| `PlaybackUpstreamError` | 502 — sanitized stream failure; never the raw provider exception/body |
| `IllegalCharacterError` (openpyxl, raised from bare `Exception`) | 400, own handler (`api/errors.py:96-106`) |
| anything else under `WorkbookError` / `AgentError` / `ProjectionError` | 400 (default) |

**Four** base classes get handlers registered — `WorkbookError`, `AgentError`, `CLINotFoundError` and, since T30, `ProjectionError` (`_HANDLED_BASES`, `api/errors.py:78-83`, applied at `:112-113`). `ProjectionError` (`data/errors.py`) is the Postgres projection's own base, distinct from `workbook.errors`, which speaks for the `.xlsx` files, and from `clients.errors`, which never reaches a response at all. A new domain exception must subclass one of the four **and** be added to both tables, or it silently becomes a 400 carrying `str(error)` as its whole message. That is not hypothetical: `InvalidNameError` is the one `WorkbookError` subclass absent from **both** `_STATUS_BY_ERROR` and `_MESSAGE_BY_ERROR`, which is exactly why it falls through to a bare 400. Every route-reachable `ProjectionError` subclass is in both tables. `ImportNamingError` and `ImportPathError` are deliberately service-only until T68 adds import routes and their status/message rows; the fallback must not be mistaken for their final HTTP contract.

The frontend mirrors this in exactly one place: `api/ApiError.ts` carries `status`, `code`, and `get isStale()` returning `this.code === "StaleWorkbookError"` (`api/ApiError.ts:12-14`), and `api/request.ts` is the single `fetch` wrapper every JSON call goes through.

### 4.4 Testing

- Backend: the current real-PostgreSQL test/coverage results are recorded in `docs/status.md` and
  `docs/snapshots-recovery-validation.md`. The whole suite runs without exclusions; `TV_REQUIRE_POSTGRES=1`
  turns unavailable-Postgres skips into failures. Tests use PID-isolated disposable databases, not
  the owner's application database. Re-measure after changes rather than carrying forward a count.
- **The suite runs against copies of the real workbooks.** The `library` fixture (`tests/conftest.py:26-31`) copies every root `.xlsx` into a `tmp_path`; `tests/library_choice.py` picks subjects **by shape, never by name** (`a_category()` at `:85`, `a_category_with_at_least(rows)` at `:116`, `the_category_whose_order_column_is_not_headed_order()` at `:147`, …). Never hard-code a workbook filename in a test.
- `fingerprint(path)` (`tests/snapshot.py:11-12`) captures the structural properties a write must not disturb — dimensions, table refs, table column names, sorted validations, conditional-format ranges and rule count, column widths, header and body style tuples. Any new write operation gets a fingerprint test.
- **No mocking of the workbook layer, the openpyxl round-trip, or, from Phase 1, the database.** `tests/agent/` stands in only at process and network seams, never at a domain calculation: `stub_client.py` (a `ClaudeSDKClient` stand-in), `scripted_cli.py` (a stand-in at the SDK's *own transport* seam, so the real client and its buffering stay under test), `mock_responder.py` (an `httpx` transport with canned responses) and `recording_reader.py` (a `PageReader` that records instead of starting Chromium). Phase 1 integration tests use a real Postgres in a container — not a mock, and not SQLite.
- Frontend: **46 Vitest files, 320 tests, as of 2026-09-24** (T53), jsdom (`pnpm test`; `pnpm exec vitest list` counts them without running them). `tests/setup.ts:8-11` **must** keep calling `cleanup()` and `vi.unstubAllGlobals()` in `afterEach` — Vitest does not unmount between tests the way Jest does.
- Hooks: **31 tests** in `scripts/hooks/hooks.test.cjs`, on Node's own runner, no dependency. Run them as **`node --test scripts/hooks/hooks.test.cjs`** — the file form. The directory form (`node --test scripts/hooks/`) fails on Node 24, so do not "simplify" the command.
- The Playwright layout guard (`app/frontend/layout/`) is the standing answer to "jsdom has no layout engine". Since T53 (2026-09-24): **49 tests per project × four Chromium projects = 196 runs** — 23 surfaces × two control checks, two proposal-diff cases and one attribution case. T53 adds save-retry surfaces with the player open and closed. The four projects are `1512x900`, `1280x720`, `1024x768`, `960x1040`, using intercepted fixture responses rather than live services. Phase 2 adds **1920×1080**; the other four stay.
- Coverage floors are a **ratchet, not a target**, and they live only in CI (`.github/workflows/ci.yml:39-43`): backend lines **97**, frontend lines **56**, statements **54**, functions **45**, branches **45**. The `coverage-gate` job (`ci.yml:351-400`) prints per-metric `[ok]`/`[LOW]` and fails with "Add tests. Do not lower the floor." (`ci.yml:397`). Raising them is separate work; lowering one is a regression.

### 4.5 Naming

Backend `snake_case.py` / `PascalCase` classes / `UPPER_SNAKE_CASE` constants. Frontend `PascalCase.tsx` components, `useCamelCase.ts` hooks, `camelCaseSlice.ts` slices, `PascalCase.ts` types.

**Wire field names are `snake_case` on both sides.** `CategorySummary.file_name`, `has_watch_column`, `expected_mtime`, `read_mtime`, `total_cost_usd`, `reference_sheets` are snake_case in TypeScript too, deliberately, because they cross the wire from Python. camelCase appears only in frontend-only shapes: `StandingRows`, `Toast`, `ChatMessage`, `CategoryDraft`, `WriteFailure`, `AccentPalette`, `RowColumns`.

Note the British spelling `licence` on `HeroCandidate.licence`, on both sides. It is a contract field; do not "fix" it.

</coding_standards>

---

<data_contracts>

## 5. Domain model and data contracts — sacred

Everything in this section is a **contract**. Field names, types, defaults and validators do not drift without an explicit architectural decision recorded in `docs/TV_MASTER_PLAN.md` and approved by the owner. A contract change is a **minor** semver bump. When you meet a contract, look it up here and in the file it names — do not guess the shape.

### 5.1 `ColumnSpec` — `models/column_spec.py:9-22`

```python
ColumnKind = Literal["text", "choice"]
ColumnRole = Literal["order", "title", "watch", "identity", "position", "other"]


class ColumnSpec(BaseModel):
    """A single sheet column, as the UI needs to render and edit it."""

    key: str
    label: str
    index: int = Field(ge=1)
    kind: ColumnKind
    role: ColumnRole
    choices: list[str] = Field(default_factory=list)
    width: float | None = None
```

`index` is the 1-based Excel column. TypeScript mirror, `src/types/ColumnSpec.ts`:

```ts
export type ColumnKind = "text" | "choice";
export type ColumnRole = "order" | "title" | "watch" | "identity" | "position" | "other";

export interface ColumnSpec {
  key: string;
  label: string;
  index: number;
  kind: ColumnKind;
  role: ColumnRole;
  choices: string[];
  width: number | null;
}
```

> **Both app-owned roles land with their consumers.** T22 added `"identity"` for hidden `Row ID`;
> T53 adds `"position"` for visible `Position (s)` (R105). `_role_for` recognises both aliases,
> `build_columns` retains their internal specs, and `read_category` excludes both from public
> `columns` and `WatchRow.cells`. Public row/chat writes cannot address either column. These additive
> contracts share the existing pending minor `v0.2.0`; the release pipeline owns version bumps.
>
> `"identity"` is `Row ID`, hidden (`column_dimensions[letter].hidden = True`, set by `workbook/identity.py`), a UUID hex string per row. `"position"` is `Position (s)`, visible in Excel, an integer number of seconds written every 60 seconds while playing and on pause, ended and unmount, and never read back as truth — a projection of `watch_event.position_seconds` that survives a hard kill.

### 5.2 `WatchRow` — `models/watch_row.py:8-12`

```python
class WatchRow(BaseModel):
    """A sheet row keyed by column key; `row` is the 1-based Excel row number."""

    row: int = Field(ge=2)
    cells: dict[str, str]
```

`ge=2` because row 1 is always the header (`HEADER_ROW = 1`, `FIRST_DATA_ROW = 2`, `constants.py:33-34`). `cells` is keyed by `ColumnSpec.key`.

```ts
export interface WatchRow {
  row: number;                      // the sheet's own 1-based row number
  cells: Record<string, string>;    // keyed by ColumnSpec.key
}
```

### 5.3 `WatchCounts` — `models/watch_counts.py:8-16`

```python
class WatchCounts(BaseModel):
    """Row counts by watch status. `trackable` excludes skipped rows."""

    total: int = Field(ge=0)
    watched: int = Field(ge=0)
    in_progress: int = Field(ge=0)
    skipped: int = Field(ge=0)
    unwatched: int = Field(ge=0)
    trackable: int = Field(ge=0)
```

Computed in `_count` (`workbook/reader.py:42-55`): `unwatched = total - watched - in_progress - skipped`; `trackable = total - skipped`. **The Phase 1 progress views must agree with this arithmetic** — `curated_entry_watch_state` treats `completed + skipped = total` as complete for exactly that reason, so the two progress readouts in the app cannot disagree.

### 5.4 `CategorySummary` and `CategoryDetail`

```python
# models/category_summary.py:10-22
class CategorySummary(BaseModel):
    """Everything the category list needs, without the row payload."""

    id: str
    name: str
    file_name: str
    sheet_title: str
    accent: str
    mtime: float
    has_watch_column: bool
    locked_by_excel: bool
    hero_url: str | None = None
    counts: WatchCounts


# models/category_detail.py:11-16
class CategoryDetail(CategorySummary):
    """A category plus its editable grid and read-only reference sheets."""

    columns: list[ColumnSpec]
    rows: list[WatchRow]
    reference_sheets: list[ReferenceSheet]
```

`hero_url` is the only field with a default. `accent` is `#RRGGBB`, read from the fill of cell A1 by `_accent` (`workbook/reader.py:30-39`), which requires an 8-character ARGB string that is not `TRANSPARENT_ARGB` and otherwise falls back to `#1F2937` (`DEFAULT_ACCENT_RGB`, `constants.py:19`). `mtime` is `path.stat().st_mtime` and **is the freshness token every mutating call echoes back**. `hero_url` is shaped `/heroes/{name}?v={st_mtime_ns}` (`services/catalog.py:90-101`) — the stamp is a cache-buster, because a replacement keeps the filename.

`locked_by_excel` and `hero_url` are always recomputed **live** on top of the cached detail via `model_copy(update=...)` (`_read_live_lock`, `services/catalog.py:103-111`), because both can change without the workbook changing.

```ts
export interface CategorySummary {
  id: string;
  name: string;
  file_name: string;
  sheet_title: string;
  accent: string;
  mtime: number;
  has_watch_column: boolean;
  locked_by_excel: boolean;
  hero_url?: string | null;
  counts: WatchCounts;
}

export interface CategoryDetail extends CategorySummary {
  columns: ColumnSpec[];
  rows: WatchRow[];
  reference_sheets: ReferenceSheet[];
}
```

### 5.5 The listing and its two failure lists

```python
class CatalogListing(BaseModel):
    """Every category in the library, plus anything that failed to load or could not be reached."""

    categories: list[CategorySummary]
    unreadable: list[UnreadableWorkbook] = Field(default_factory=list)
    shadowed: list[ShadowedWorkbook] = Field(default_factory=list)
    library_dir: str


class UnreadableWorkbook(BaseModel):
    """Surfaced so a dropped-in file that fails to open is visible, not silently missing."""

    file_name: str
    reason: str          # f"{type(error).__name__}: {error}"


class ShadowedWorkbook(BaseModel):
    """Surfaced so a dropped-in namesake is visible, rather than silently hiding the file it shadows."""

    file_name: str
    category_id: str
    answered_by: str


class ReferenceSheet(BaseModel):
    """Non-editable supporting sheet shown in the info drawer."""

    title: str
    header: list[str]
    rows: list[list[str]]
```

**Shadowing is a real hazard, not a curiosity.** Two files can slugify to the same id, `discovery.resolve` (`workbook/discovery.py:23-28`) answers with the **first in sorted order**, and the loser is unreachable — every read *and every write* lands on the other workbook. Hence: `_listing` (`services/catalog.py:56-84`) reports it rather than quietly showing two cards; `create_category` (`workbook/creator.py:117-124`) and `rename_workbook` (`workbook/renaming.py:16-36`) both refuse to *create* such a clash; and the id is claimed at `services/catalog.py:70-72` **before** the file is opened, because an unreadable file still hides the namesake behind it.

### 5.6 Request bodies

```python
class RowWrite(BaseModel):
    """Cell values keyed by column key, guarded by the client's last-known mtime."""

    cells: dict[str, str] = Field(default_factory=dict)
    expected_mtime: float

    def sanitized_cells(self) -> dict[str, str]: ...


class CategoryRename(BaseModel):
    """The new filename stem, without the .xlsx suffix, guarded by the client's last-known mtime."""

    stem: str = Field(min_length=1, max_length=MAX_FILENAME_STEM_LENGTH)   # 120
    expected_mtime: float


class CategoryCreate(BaseModel):
    """A new workbook: display name, accent colour, columns, and either seed titles or full rows."""

    name: str = Field(min_length=1, max_length=MAX_TITLE_LENGTH)                       # 120
    accent: str = Field(default=f"#{DEFAULT_ACCENT_RGB[2:]}", pattern=HEX_COLOR_PATTERN)  # "#1F2937"; ^#?[0-9A-Fa-f]{6}$
    columns: list[str] = Field(default_factory=..., max_length=MAX_NEW_CATEGORY_COLUMNS)   # 64
    titles: list[str] = Field(default_factory=list, max_length=MAX_NEW_CATEGORY_ROWS)      # 500
    rows: list[dict[str, str]] = Field(default_factory=list, max_length=MAX_NEW_CATEGORY_ROWS)
```

`CategoryCreate`'s column default is `list(DEFAULT_NEW_CATEGORY_COLUMNS)` = `("Order", "Title", "Unit", "Release", "Type", "When to Watch", "Notes", "Watched?")` (`constants.py:43-52`). Cross-field rules, both in `_reject_incoherent_rows` (`models/category_create.py:50-59`): `titles` and `rows` are **mutually exclusive**, and every key in every `rows` entry must be one of `column_keys()` (`:45-48`) — which reuses `workbook.schema.unique_key`, the one place keys are minted.

`sanitize(value, limit=MAX_CELL_LENGTH)` (`models/cell_text.py:12-14`) is the **only** cell-text normaliser: it strips `ILLEGAL_CELL_CHARACTERS` (`[\x00-\x08\x0b\x0c\x0e-\x1f]`, `constants.py:92-93`) and clips to `MAX_CELL_LENGTH = 2000`. Every request model that carries cell text calls it in an `@field_validator`. Do not write a second one.

### 5.7 `RowChange` — the batch edit vocabulary

```python
RowChangeKind = Literal["add", "revise", "move", "remove"]


class RowChange(BaseModel):
    """A single add / revise / move / remove against a sheet's original row numbers."""

    kind: RowChangeKind
    row: int | None = Field(default=None, ge=FIRST_DATA_ROW)   # ge=2
    after_row: int | None = Field(default=None, ge=HEADER_ROW) # ge=1, so a row can be seated at the top
    cells: dict[str, str] = Field(default_factory=dict)
    reason: str = Field(default="", max_length=MAX_REASON_LENGTH)   # 240
```

Kind coherence, enforced by `_check_kind_coherence` (`models/row_change.py:29-50`):

| kind | `row` | `after_row` | `cells` |
|---|---|---|---|
| `add` | must be `None` | optional (absent = append at end) | required, non-empty |
| `revise` | required | — | required, non-empty |
| `move` | required | **required** | must be empty |
| `remove` | required | — | must be empty |

A `move` carries no cells because "the writer never reads these, so a diff that showed them would promise values no write would ever make" (`models/row_change.py:41-42`). On the TypeScript side `row` and `after_row` are **absent, never `null`** — the SSE stream omits empty fields — and `ProposalDiff` relies on `change.row !== undefined`.

### 5.8 The proposal union

```python
class Proposal(BaseModel):
    id: str
    summary: str
    sources: list[str] = Field(default_factory=list, max_length=MAX_PROPOSAL_SOURCES)   # 20
    body: ProposalCreate | ProposalEdit | ProposalHero = Field(discriminator="kind")


class ProposalCreate(BaseModel):
    kind: Literal["create"]
    category: CategoryCreate
    # model_validator: category.rows must be non-empty — "a create proposal needs rows,
    # since the diff is what the user approves". `titles` alone is rejected.


class ProposalEdit(BaseModel):
    kind: Literal["edit"]
    category_id: str
    read_mtime: float                     # minted by the backend from the session ReadLog
    changes: list[RowChange] = Field(max_length=MAX_PROPOSAL_CHANGES)   # 500


class ProposalHero(BaseModel):
    kind: Literal["hero"]
    category_id: str
    candidates: list[HeroCandidate] = Field(min_length=1, max_length=MAX_HERO_CANDIDATES)   # 3


class HeroCandidate(BaseModel):
    url: str = Field(max_length=MAX_HERO_URL_LENGTH, pattern=HTTP_URL_PATTERN)   # 2000, ^https?://
    source_file: str = Field(max_length=MAX_HERO_SOURCE_FILE_LENGTH)             # 200
    licence: str = Field(max_length=MAX_HERO_LICENCE_LENGTH)                     # 80  (British spelling)
    page: str = Field(max_length=MAX_HERO_URL_LENGTH, pattern=HTTP_URL_PATTERN)
    description: str = Field(max_length=MAX_HERO_DESCRIPTION_LENGTH)             # 240
```

`read_mtime` exists because "row numbers mean nothing except against the grid they were resolved on, so the write is guarded against this stamp. Reading one at approve time instead would always match and guard nothing."

### 5.9 `ChatEvent` — one SSE frame (`models/chat_event.py:14-26`)

```python
ChatEventType = Literal["text", "tool", "proposal", "error", "done"]


class ChatEvent(BaseModel):
    """A single streamed frame; only the fields its type uses are populated."""

    type: ChatEventType
    text: str | None = None
    name: str | None = None
    detail: str | None = None
    state: str | None = None
    proposal: Proposal | None = None
    code: str | None = None
    message: str | None = None
    turns: int | None = None
    total_cost_usd: float | None = None
```

Only `type` is required. The wire form is one `data: <json>\n\n` frame per event, serialised with `model_dump_json(exclude_none=True)` — **absent fields are omitted, not null**, which is why the TypeScript reader and `ProposalDiff` test for `undefined`. Which fields each type populates: `text` → `text`; `tool` → `name`, `detail`, `state` (`"running" | "done" | "escalated" | "failed"`); `proposal` → `proposal`; `error` → `code`, `message`; `done` → `turns`, `total_cost_usd`.

Stream headers are exactly `Cache-Control: no-cache, no-transform` and `X-Accel-Buffering: no`; the frames are produced by `sse_frames` (`api/chat.py:59`).

### 5.10 `FetchResult` — crosses the MCP tool boundary

```python
CHEAP_TRANSPORT: Final = "httpx"
BROWSER_TRANSPORT: Final = "chromium"
FetchTransport = Literal[CHEAP_TRANSPORT, BROWSER_TRANSPORT]


class FetchResult(BaseModel):
    """Readable page text, the path that read it, and whether it hit the size cap."""

    text: str
    via: FetchTransport
    truncated: bool
```

Serialised as JSON into a tool result, parsed back in `session._state_of` to decide whether a tool chip reads `escalated`.

### 5.11 Frontend-only shapes

These never cross the wire and are therefore camelCase:

```ts
export interface StandingRows {
  status: "loading" | "ready" | "failed";
  identifyingKey: string | null;
  cellsByRow: Readonly<Record<number, Readonly<Record<string, string>>>>;
}

export interface ChatMessage {
  id: string;
  role: "you" | "claude" | "tool" | "note" | "error";
  text: string;   // prose for a spoken entry; the tool's detail line for a tool entry
  tool: string;
  state: string;
}

export interface Toast { id: string; tone: "error" | "info"; message: string; }

// src/api/createCategory.ts
export interface CategoryDraft {
  readonly name: string; readonly accent: string; readonly titles: readonly string[];
}

// src/stores/writeFailure.ts
export interface WriteFailure { readonly message: string; readonly refreshed: CategoryDetail | null; }
```

Plus the watch vocabulary, which is shared by value with the backend:

```ts
export const UNWATCHED = "";
export const WATCHED = "Watched";
export const IN_PROGRESS = "In progress";
export const SKIPPED = "Skip";
export const WATCH_CYCLE: readonly string[] = [UNWATCHED, WATCHED, IN_PROGRESS, SKIPPED];
```

The TypeScript side is `types/WatchStatus.ts:1-8`; the Python side is `constants.py:12-16`, and `DEFAULT_WATCH_CHOICES` at `constants.py:16` is the same tuple. Note the sheet stores **`"Skip"`, not `"Skipped"`**; the UI label "Skipped" comes from `utils/statusLabel.ts:3-8`, which also renders `"In progress"` as "Watching" and `""` as "Not started". **All nineteen workbooks carry a `Watched?` dropdown offering exactly `["", "Watched", "In progress", "Skip"]`** — verified by reading every sheet's `dataValidation`. **The mirror target is exactly four values. Nothing richer fits.**

### 5.12 The HTTP surface

**Twenty-three HTTP operations across twenty OpenAPI paths as of 2026-09-23**, in eight routers.
Phase 0 contributes fourteen, Phase 1 five, and Phase 3 the library sync and review retry (section
13.5). There is deliberately **no `/health`** — compose probes `/openapi.json`, which touches no
workbook and therefore does not re-read the library on every healthcheck.

| Method | Path | Body | Query | Response | Status |
|---|---|---|---|---|---|
| GET | `/api/categories` | — | — | `CatalogListing` | 200 |
| POST | `/api/categories` | `CategoryCreate` | — | `CategoryDetail` | **201** |
| GET | `/api/categories/{category_id}` | — | — | `CategoryDetail` | 200 |
| DELETE | `/api/categories/{category_id}` | — | `expected_mtime` (**required**) | `CatalogListing` | 200 |
| POST | `/api/categories/{category_id}/rename` | `CategoryRename` | — | `CategoryDetail` | 200 |
| POST | `/api/categories/{category_id}/watch-column` | — | `expected_mtime` (**required**) | `CategoryDetail` | 200 |
| POST | `/api/categories/{category_id}/rows` | `RowWrite` | — | `CategoryDetail` | 200 |
| PATCH | `/api/categories/{category_id}/rows/{row}` | `RowWrite` | — | `CategoryDetail` | 200 |
| DELETE | `/api/categories/{category_id}/rows/{row}` | — | `expected_mtime` (**required**) | `CategoryDetail` | 200 |
| POST | `/api/chat/sessions` | — | — | `{"session_id": str}` | 200 |
| POST | `/api/chat/sessions/{session_id}/messages` | `{"text": str}` (max 16000) | — | SSE stream | 200 |
| POST | `/api/chat/proposals/{proposal_id}/approve` | — | — | `CategoryDetail` or 409 envelope | 200 / 409 |
| POST | `/api/chat/proposals/{proposal_id}/hero/{choice}` | — | — | `CategoryDetail` | 200 |
| DELETE | `/api/chat/sessions/{session_id}` | — | — | — | **204** |

Two behaviours that look surprising and are deliberate:

- `DELETE /api/categories/{id}` is a **retirement**, not a delete, and answers with the whole remaining `CatalogListing` rather than the removed category.
- **Every row endpoint returns the whole reloaded `CategoryDetail`**, never just the changed row. The client's optimistic-patch replay depends on it.

Mtime rides in the JSON body for methods that have one and in the query string for methods that do not; the wire field name is always `expected_mtime`.

### 5.13 Phase 1 — the SQLAlchemy entities

New package `app/backend/src/tv_watchlist/data/`, one model per file under `data/models/`, with `data/base.py` (Base + naming convention + `UuidPk` + `TimestampMixin`), `data/session.py` (async engine, session factory, FastAPI dependency) and `data/enums.py`.

**Conventions decided once, and binding:**

- A `MetaData(naming_convention=...)` with `ix/uq/ck/fk/pk` templates — without it Alembic autogenerate produces unusable migrations.
- `UuidPk`: `Uuid(as_uuid=True)` primary key, `default=uuid.uuid4` **and** `server_default=text("gen_random_uuid()")`. The client-side default is not decoration — the reconciler needs the UUID *before* flush so it can be written into the workbook cell in the same transaction. `gen_random_uuid()` is core Postgres from 13, so no `pgcrypto` extension is needed on `postgres:16-alpine`.
- `TimestampMixin`: `created_at` / `updated_at` as `DateTime(timezone=True)` → `timestamptz`, `server_default=func.now()`, `onupdate=func.now()`.
- **Durations are `Integer` seconds, named `*_seconds`, with a `CHECK`.** Never `INTERVAL`: playback position in Phase 3 is an integer from a `<video>` `currentTime` or a Jellyfin report, every comparison is `position_seconds >= runtime_seconds * threshold`, and `INTERVAL` on one side forces a cast on every predicate. TMDB returns runtime in whole minutes; the ingest multiplies by 60 once, at the boundary. The unit is in the column name and no mixed units survive that boundary.
- Genuine dates (`air_date`, `first_air_date`, `last_air_date`) are real `Date`. The workbook's free-text `Release` (`2002`, `1999–2000`, `1977-05-25`) lands in `curated_entry.raw_release` as text and **is never coerced into a date column**.
- Native Postgres enums via `pg_enum(members, name)`, which sets `values_callable` so the **member values** (`aired`) become the labels rather than the Python names (`AIRED`). Without it every round-trip fails. A migration that adds an enum value must be its own revision, separate from the revision that first inserts a row using it.

The vocabulary in `data/enums.py`: `MediaType`, `OrderType` (the app's own vocabulary, stored as an open string — not a `pg_enum`, since TheTVDB's season types are read at runtime and the set is never closed), `UnitKind`, `ResolutionState`, `EntityKind`, `ExternalSource`, `ArtworkKind`, `WatchEventKind`, `WatchEventSource`, `WatchSubjectKind`, `SyncResourceType` (Phase 1), plus `Availability` (`in_library` / `not_in_library` / `ambiguous`) and `JellyfinItemKind` (`movie` / `series` / `episode`) (Phase 3, ADR-013/ADR-014). **`WatchEventSource` names `player` — not `jellyfin` — for every event the in-app `<video>` produces** (decided 2026-09-20): the position comes from the browser, only the media comes from Jellyfin, so `jellyfin` stays free for a server-reported session if one is ever consumed.

**Sixteen current domain tables**: the eleven below from Phase 1, `jellyfin_item`,
`media_import`, `media_import_operation`, `playback_completion` and `playback_completion_event`.
The migration head is `0005`; `alembic_version` is separate. T55's future `streaming_offer` would
make seventeen domain tables. The flattened queue is **`curated_entry_item`**, described below.

```mermaid
erDiagram
    category      ||--o{ curated_entry          : "projects rows of"
    curated_entry }o--o| title                  : "resolves to a span of"
    curated_entry ||--o{ curated_entry_item     : "flattens into"
    title         ||--o{ season                 : has
    season        ||--o{ episode                : has
    title         ||--o{ episode                : "denormalised owner"
    title         ||--o{ episode_order          : "numbers under"
    episode       ||--o{ episode_order          : "occupies a slot in"
    episode       ||--o{ curated_entry_item     : "appears in"
    title         ||--o{ curated_entry_item     : "movie slot (movie_title_id)"
    title         ||--o{ external_id            : "keyed by"
    title         ||--o{ artwork                : "pictured by"
    episode       ||--o{ watch_event            : "logged against"
    curated_entry ||--o{ watch_event            : "logged against"
    title         }o--o| jellyfin_item          : "picker's remembered choice (P3)"
    title         ||--o{ streaming_offer        : "launcher offers, country=il (P3)"
    jellyfin_item }o--o| jellyfin_item          : "episode → series (series_jellyfin_id) (P3)"
```

**`category`** — the workbook projection. `slug` (unique), `file_name`, `sheet_title`, `accent`, `identity_column_key`, `workbook_mtime`, `workbook_digest`, `last_ingested_at`, `last_mirrored_at`, `last_ingest_error`, `retired_at`.
`workbook_mtime` is `Float` **on purpose** — it is the same `st_mtime` float the existing API already carries end to end (`CategorySummary.mtime`, `RowWrite.expected_mtime`, `guard_fresh`), and re-typing it here would fork a live data contract. `workbook_digest` is a sha256 over the normalised grid, so Excel merely opening and re-saving a file without an edit does not trigger a re-ingest. **The skip turns on the digest and the identity cells together, never on the stamp** (Ruling 49 as amended, `ingest/reconciler.py`'s `_unchanged` plus `identities_intact`): a pass is skipped only when the sha256 over the normalised grid matches `workbook_digest` **and** the sheet's `Row ID` cells are exactly the live entries' ids — the identity half is load-bearing because `workbook_digest` excludes the `Row ID` column **by design** (that exclusion is what lets a first ingest write 996 identities into nineteen sheets and still see nineteen unchanged files on the next pass), so a cleared, blanked, hand-typed or duplicated id moves no digest at all and must still reach adoption, re-minting or the malformed-identity refusal. A digest-equal, identities-intact pass with a moved `st_mtime` — exactly what Excel closing a file produces — records the new `workbook_mtime` on `category` and touches nothing else, with no row updates, no provider calls and no workbook write. ANDing the *stamp* with the digest, as an earlier draft did, made the digest pointless: an equal stamp already implies equal bytes, so the digest only ever earns its keep in the case the AND excluded. `identity_column_key` is per-workbook because the user may have renamed the header and because a never-ingested workbook has no such column yet.

**`title`** — the work. `media_type`, `tmdb_id`, `name`, `original_name`, `match_key`, `overview`, `first_air_date`, `last_air_date`, `runtime_seconds`, `episode_count`, `season_count`, `status`, `original_language`. Unique on `(media_type, tmdb_id)` — **this is the `tmdb_id` join key Phase 3 depends on.** `tmdb_id` is **nullable**: a hand-entered local title with no TMDB match is a first-class record (risk register R2), and Postgres treats NULLs as distinct, so the uniqueness constraint still holds across any number of such titles. `match_key` is the deterministic normalisation the resolver uses (lowercased, diacritics folded, punctuation stripped, leading article dropped, release year appended when known); it is a plain indexed column so the exact path needs no extension, with a `pg_trgm` GIN index on `name` backing the fuzzy fallback only. `match_key` stays `String(255)` and a value the resolver has to clip to fit is **logged** rather than silently truncated (`clipped table= column= from= to=`, Ruling 32) — a silently shortened key still matches, just not the thing it was derived from.
**`title.tmdb_id` never holds a season id or an episode id** (Ruling 33, T18). TMDB numbers a season and an episode under their own id spaces, and a curated row that resolves *into* a series — `Demon Slayer — Entertainment District Arc`, an OVA, a named arc — matches at the season or episode level. The resolver therefore exposes `title_tmdb_id` = the **parent tv id**, with the parent's own name and year, and carries the season or episode it actually matched beside it as a `MatchedUnit`. Storing the season id in this column would make `uq(media_type, tmdb_id)` collide two different works, and would hand Phase 3 a join key Jellyfin cannot answer.
Phase 3 adds one nullable column, **`jellyfin_item_id`** — FK to `jellyfin_item.id`, `ON DELETE SET NULL` — the `AMBIGUOUS` picker's remembered choice (T56, ADR-014). It is a **per-title** setting, not per file: when the library holds two candidates for one title (absolute-vs-official numbering, a remux beside an encode) the owner picks once and every later sync respects it. `NULL` means "no pick made", never "not in library" — availability is computed by `services/availability.py`, not read off this column.

**`Availability` is computed only (T51), with no database column, native enum or migration.** Its three values are `in_library`, `not_in_library` and `ambiguous`. The response's nullable id names the title-level movie or series row; episode file ids remain on the queue-slot match. An episode entry requires every queued slot to match before it is in-library, and an ambiguous slot takes precedence over missing slots (R96). Section 5.15 defines the two wire fields and the service-only outage notice.

**`season`** — `title_id` (cascade), `season_number` (`>= 0`; season 0 is the specials bucket and is kept), `name`, `overview`, `air_date`, `episode_count`. Unique on `(title_id, season_number)`.

**`episode`** — `title_id`, `season_id`, `season_number`, `episode_number`, `tmdb_episode_id` (unique), `name`, `overview`, `air_date`, `runtime_seconds`, `production_code`. Unique on `(season_id, episode_number)`. **`title_id` is denormalised deliberately** so every order query stays a single join; both copies are written in the same ingest transaction, and because a `CHECK` cannot express a cross-table invariant, `episode.title_id = season.title_id` is asserted in the ingest test suite instead.

**`episode_order`** — one episode's slot in one numbering of one title: `title_id`, `episode_id`, `order_type`, `label` (default `''`), `sequence`, `order_season_number`, `order_episode_number`, `source`.
`sequence` is a **dense, 1-based rank within one numbering**, not a season/episode pair, and that single choice is what makes all three orders one kind of object: absolute order *is* `sequence`; aired order is `sequence` assigned by walking `(season_number, episode_number)` with season 0 excluded and given its own `alternate` ordering; dvd order renumbers into different seasons entirely, which is exactly why `order_season_number` / `order_episode_number` exist beside the rank — they are what the UI prints, `sequence` is what the app computes with. A hand-written span like One Piece's `E19–53` becomes one range scan. The unique on `(title_id, order_type, label, sequence)` is `DEFERRABLE INITIALLY DEFERRED` so re-ranking after TMDB inserts an episode is a single `UPDATE`. `source` records which provider produced the ordering, because TMDB and TheTVDB disagree and the app must be able to say which one it is showing. `order_type` is not a closed set the code may hard-code: TheTVDB's seven live season types (`official`, `dvd`, `absolute`, `alternate`, `regional`, `altdvd`, `alttwo`, measured 2026-09-15) are documented as *examples*, so the ingest reads the list at runtime from a cached `GET /v4/seasons/types`. `order_type` itself (here and on `curated_entry`) is a plain `String(32)` column, never a Postgres enum, precisely so a season type TheTVDB adds tomorrow needs no migration at all (section 2.1, item 6). The "a migration that adds an enum value must be its own revision" rule above stays true only for the real `pg_enum` columns (`media_type`, `unit_kind`, `resolution_state`, and the rest); it does not apply to `order_type`.
`aired` is the only order guaranteed to exist; falling back to it is recorded on the entry (`resolution_note`), never applied silently.

**`curated_entry`** — the projection of one `.xlsx` data row, and the heart of the model. `category_id`, `position` (dense, 1-based, per category), `sheet_row`, `title_id` (nullable), `unit_kind`, `order_type`, `order_label`, `span_start`, `span_end`, `season_number`, `resolution_state`, `resolution_confidence`, `resolution_note`, `raw_cells` (**JSONB** — the verbatim row, because nineteen workbooks with different headers would otherwise need nineteen schemas), `raw_title`, `raw_unit`, `raw_release`, `match_key`, `observed_watch_cell`, `mirrored_watch_cell`, `first_seen_at`, `last_seen_at`, `removed_at`. `id` is the UUID written back into the sheet's hidden `Row ID` column.

Three properties make the cross-title order work, and each is load-bearing:

1. **The chronology is stored, never derived.** `position` comes straight from the sheet.
2. **One entry, one title.** A row never spans two titles; all ambiguity is pushed into `span_*`, which a human can confirm at a glance.
3. **The same title appears many times.** The title `One Piece` occupies **28 of that workbook's 71 rows**, each with a different span (`E1-18`, `E19-53`, `E54-61`, `E62-130`, …), so `title_id` is not unique per category and `uq(category_id, position)` — deferrable — is the structural constraint.

An `unresolved` entry is a **first-class citizen, not an error state**: it renders, it sorts, it accepts an entry-level watch event. `Misc_Movies` proves that is a normal case, not a defect — all four of its rows carry only `Order` and `Title`, with every other cell empty.

**`curated_entry_item`** — *derived*. `category_id`, `curated_entry_id`, `episode_id` (nullable), `movie_title_id` (nullable, with `CHECK num_nonnulls(episode_id, movie_title_id) = 1`), `position_in_entry`, `absolute_position`. Rebuilt delete-then-insert inside the ingest transaction; never hand-edited. It exists because the two questions the ten-foot UI asks constantly — "what do I play next" and "how far through am I" — are both `ORDER BY absolute_position` over a flat list, and computing that from spans is a lateral join per entry (141 for Marvel, 202 for DCU, 996 across the library) on every render. It is honestly a cache: stale between ingests, scoped rebuild, `absolute_position` renumbered for the whole category in one pass at the end of the transaction, which the deferred unique makes a single `UPDATE`. **Every playable unit has a row: one per episode in an entry's resolved span, and exactly one per movie entry** (`movie_title_id` set, `position_in_entry = 1`). That is what lets Next and Autoplay follow the curated order through a film and back into episodes — the owner's requirement, `docs/TV_MASTER_PLAN.md` §6.9 and ADR-010. An earlier draft gave movie entries no rows, which would have made "next" skip every film. **Naming: DECIDED 2026-09-20 — the table is `curated_entry_item`.** ADR-010 had proposed the rename from `curated_entry_episode` and left it open for the owner to settle before T24; it was closed under the owner's standing autonomy rule before any migration exists, so no revision ever carries the old name. ADR-010's own text keeps `curated_entry_episode` as history; everywhere else, including every Phase 1 and Phase 3 document, the name is `curated_entry_item`.

**`external_id`** — `entity_kind`, `source`, `value`, plus **three nullable typed FKs** (`title_id`, `season_id`, `episode_id`) with `CHECK num_nonnulls(...) = 1` and the kind matching the populated column. A polymorphic `(entity_type, entity_id)` pair cannot carry a foreign key, so it can neither cascade nor be trusted; two always-null columns per row is the price of real referential integrity on **the Phase 3 Jellyfin join surface**, where a dangling id surfaces to the user as a video that will not play.

**`artwork`** — `entity_kind`, `kind`, `source`, `remote_path`, `local_path`, `width`, `height`, `aspect_ratio`, `language`, `vote_average`, `is_primary`, and the same three typed FKs, guarded by the same `one_entity` / `kind_matches_column` CHECK pair `external_id` uses. Three **partial unique indexes** (`WHERE is_primary AND <fk> IS NOT NULL`) rather than one composite, so each index is both the constraint and the lookup path for "the primary poster of this title". **Bytes are not stored in Postgres** — `app/heroes/` with its `ATTRIBUTION.md` already owns on-disk image caching, licence attribution and cache-busting via `st_mtime_ns`; `local_path` points into it and that machinery is reused, not re-implemented.

**`watch_event`** — append-only, and the only durable record of what the user actually did. `occurred_at`, `recorded_at`, `subject_kind`, `kind`, `source`, `tmdb_key`, `episode_id` (SET NULL), `title_id` (SET NULL), `curated_entry_id` (**RESTRICT**), `category_id` (RESTRICT), `position_seconds`, `runtime_seconds`, `device`, `note`. Exactly one of `episode_id` / `title_id` / `curated_entry_id` is populated, enforced by the `one_subject` CHECK (`num_nonnulls(...) = 1`), with a second CHECK, `kind_matches_column`, tying `subject_kind` to whichever of the three is set — the pair is the database's own guarantee that `subject_kind` cannot lie about which column carries the row's subject. **No `TimestampMixin`** — an append-only table has no `updated_at`, and giving it one would be a lie the next reader has to disprove. `source` is a `WatchEventSource`, and the value the Phase 3 player writes is **`player`, never `jellyfin`** (decided 2026-09-20): the browser `<video>` reports the position, Jellyfin only serves the bytes, so a `jellyfin` row would claim a provenance no code has. `tmdb_key` (`movie:603`, `tv:1399:s2:e5`) is the **durable** pointer: a full TMDB re-ingest rebuilds every metadata row, and the log re-links by `tmdb_key`. That is the same `tmdb_id` join key chosen for Phase 3, reused as the log's own identity so the log outlives every metadata rebuild.

**`sync_state`** — `source`, `resource_type`, `resource_key` (unique together), `etag`, `last_modified`, `payload_digest`, `last_attempt_at`, `last_success_at`, `next_attempt_at`, `consecutive_failures`, `last_error`. `payload_digest` exists because TMDB does not send `ETag` on every endpoint; when it does not, the ingest hashes the normalised response body and skips the write path when the digest is unchanged, which is what keeps a nightly refresh across nineteen workbooks from rewriting every `episode` row and churning `updated_at` for nothing.

**`jellyfin_item`** — *Phase 3 (T49), derived from the owner's Jellyfin.* The `tmdb_id → Jellyfin Id` index that `services/library_sync.py` maintains, one row per movie, series and episode the library holds: `id` (UUID), `jellyfin_id` (text, **unique** — Jellyfin's own 32-hex item id), `kind` (`JellyfinItemKind`: `movie` / `series` / `episode`), `name`, `tmdb_id` (nullable — Jellyfin fills `ProviderIds.Tmdb` only when its own scan matched), `series_jellyfin_id` (nullable; an episode's parent series, by Jellyfin id), `parent_index_number`, `index_number`, `index_number_end` (all nullable; Jellyfin's season / episode / last-episode-of-a-multi-episode-file numbers, **verbatim**, never reinterpreted — the order they follow is whatever the file naming produced, which is why section 20.2 resolves the TheTVDB order before joining), `run_time_seconds` (`Integer`, from `RunTimeTicks ÷ 10_000_000`, converted **once** at the boundary — section 11.2, rule 7), `path` (the file path as Jellyfin reports it, for the picker to show), `date_last_saved` (nullable optional `DateLastSaved` metadata, **not the refresh cursor**), `first_seen_at`, `last_seen_at` (when this row was last written by a completed sync), `removed_at` (soft delete: a file that vanishes from a full scan is marked, never deleted, because `title.jellyfin_item_id` may still point at it). Indexed on `(kind, tmdb_id)` — the availability lookup — and on `series_jellyfin_id` — the episode join. It exists because **Jellyfin has no provider-id lookup endpoint** (section 20.2, item 1): the sync builds its local index by paging `/Items` and each series' episodes. Incremental refresh chooses the explicit timezone-aware `since`, otherwise the maximum live `last_seen_at`, otherwise a full scan (R87); it sends the chosen cursor as `minDateLastSaved`. Incremental scans additionally page changed episodes across all series (R89) and never infer deletion from a partial response. It is a cache in the same honest sense `curated_entry_item` is: stale between syncs, rebuilt by one job, never hand-edited.

**`streaming_offer`** — *Phase 3 (T55), the ADR-012 launcher's cache.* `title_id` (FK, cascade), `service` (text — the API's service id, e.g. `netflix`, `prime`, `hbo`, `apple`, `crunchyroll`, plus `disney` for the hand-marked rows), `country` (text, always `il` under ADR-011 — a real column anyway, part of the unique key, so a row can never be mistaken for another country's offer), `offer_kind` (text — the API's streaming-option type, `subscription` / `rent` / `buy` / `free` / `addon`), `link` (the deep link the launcher opens, `https://` only), `audio_languages`, `subtitle_languages` (text arrays), `fetched_at`, `manual` (`Boolean`, default `false`; **`true` marks a hand-entered Disney+ row**, because no data source covers Disney+ in Israel — ADR-012 rule 3 — and a manual row is never overwritten by a refresh). Unique on **`(title_id, service, country, offer_kind)`** — `country` is in the key even though ADR-011 pins it to `il`, so adding a second country later is data, not a migration of the constraint. Both the `service` and `offer_kind` vocabularies above are **proposed until T55** confirms them against the live Streaming Availability OpenAPI document; they are recorded here so the shape is settled, not because the strings are verified. **None of the API's images or descriptions are stored** — the terms allow the link and the attribution line, nothing more — and the chat never reads this table (ADR-012 rule 7). Refresh stays inside the free plan's 1,000 requests a month: one lookup per title, `country=il`, re-fetched no more often than the quota divided by the resolved-title count allows. The One Piece episode-matching proof call (ADR-012 rule 6) is the first real request T55 makes, before anything relies on the data.

**Deletion policy, restated as a rule:** metadata (`title` → `season` → `episode` → `episode_order`, plus `external_id` and `artwork`) cascades freely because it is disposable and re-derivable; so does `streaming_offer`, which is a cache with a refresh. The curated chain (`category` → `curated_entry`) is **soft-deleted**, matching `services/retirement.py`'s move-don't-delete behaviour, and `ON DELETE RESTRICT` on `watch_event.curated_entry_id` makes that a database rule rather than a convention someone can forget. `jellyfin_item` is soft-deleted too (`removed_at`), because `title.jellyfin_item_id` — the owner's pick — must survive a file being moved and re-indexed; `ON DELETE SET NULL` on that FK covers the one case where a row is truly purged.

### 5.14 Phase 1 — the append-only guarantee and the derived views

The append-only rule is enforced **in the database**, raised in the first migration alongside the tables:

```sql
CREATE OR REPLACE FUNCTION watch_event_reject_mutation() RETURNS trigger
LANGUAGE plpgsql AS $fn$
BEGIN
    RAISE EXCEPTION 'watch_event is append-only (attempted %)', TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$fn$;

CREATE TRIGGER watch_event_no_mutation
    BEFORE UPDATE OR DELETE ON watch_event
    FOR EACH ROW EXECUTE FUNCTION watch_event_reject_mutation();
```

A service-layer convention is not enough: an Alembic data migration, a `psql` session, or a `session.merge()` on a detached instance would each silently rewrite history. The matching test asserts that an `UPDATE` raises.

Two read-only views derive current status, both with `DISTINCT ON` and the tie-break chain `(subject, occurred_at DESC, recorded_at DESC, id DESC)` — `occurred_at` is client-supplied and can arrive late, `recorded_at` is server-assigned, and `id` is the final deterministic tie-break without which two identically-stamped events make the derived status non-deterministic:

- **`episode_watch_state`** — the latest event per episode.
- **`curated_entry_watch_state`** — an entry-level override joined to a **unit-level** roll-up, with the precedence rule stated plainly: **an entry-level event at or after the latest unit-level event in that entry wins; otherwise the roll-up wins.** That is what lets a coarse "Watched" typed into Excel sit on top of fine-grained history without erasing it, and lets the next unit-level event take the wheel back automatically.

  **"Unit-level" means every row of `curated_entry_item`, not only the episodes** — and the revision is written that way. Its `unit_states` CTE left-joins each item to `episode_watch_state` on `episode_id` **and** to a `title_states` CTE on `movie_title_id`, then `COALESCE`s the two, so a movie slot takes its state from the latest **title-level** event the same way an episode slot takes its from the latest episode-level one. Nothing about that is optional: ADR-010 gives every movie entry a `curated_entry_item` row precisely so Next walks through films, and a roll-up that counted only episodes would report a film-only entry as `unset` forever and would never mark a mixed entry complete. The roll-up's columns keep their `episode_*` names (`episode_total`, `episode_completed`, `episode_skipped`, `episode_started`) because they are the `EntryProgress` contract (section 5.15) — they count **units**, and the name is history, not a claim.

Alembic autogenerate does not know about views, so `env.py` filters them with an `include_object` hook and the `CREATE VIEW` statements live in explicit `op.execute()` calls inside the migration.

### 5.15 Phase 1 — the Pydantic layer over the ORM

**The ORM classes never leave the service layer.** Routers return Pydantic models built with `model_validate`. One model per file, mirroring the existing `models/` convention. `extra="forbid"` on every request model; `frozen=True` on every response model.

All seven models below are **built** (T28, T29, T30). Every wire field is `snake_case` on both sides, and each has a TypeScript mirror under `app/frontend/src/types/` — `TitleRead.ts`, `EntryProgress.ts`, `CuratedEntryRead.ts`, `WatchEventCreate.ts`, `WatchEventRead.ts`, `ResolutionUpdate.ts` — held to the Python spelling, field for field and in order, by `app/backend/tests/ts_types.py` and the model tests that use it. Change one side and the test names the other.

```python
# models/title_read.py
class TitleRead(BaseModel):
    """A resolved title. Runtime is whole seconds; `poster_url` is served from disk, never stored here."""

    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: uuid.UUID
    media_type: MediaType
    tmdb_id: int | None = None          # nullable, like the column: a hand-entered local title is first-class
    name: str
    original_name: str | None = None
    first_air_date: date | None = None
    last_air_date: date | None = None
    runtime_seconds: int | None = Field(default=None, gt=0)
    episode_count: int | None = Field(default=None, ge=0)
    season_count: int | None = Field(default=None, ge=0)
    status: str | None = None
    poster_url: str | None = None       # `/heroes/<artwork.local_path>?v=<st_mtime_ns>`, composed by the service
```

`poster_url` is **not a column** — it is composed the way `CategorySummary.hero_url` is (section 5.4), from `artwork.local_path` plus the file's own `st_mtime_ns` as a cache-buster, and is absent from the ORM class so the default stands whenever no poster's bytes are cached. `tmdb_id` is nullable here because it is nullable on `title` (section 5.13); a title with no provider match still renders.

```python
# models/episode_read.py
class EpisodeRead(BaseModel):
    """One episode as the API exposes it. Runtime is whole seconds."""

    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: uuid.UUID
    title_id: uuid.UUID
    season_number: int = Field(ge=0)
    episode_number: int = Field(ge=0)
    name: str | None = None
    air_date: date | None = None
    runtime_seconds: int | None = Field(default=None, gt=0)
    still_url: str | None = None
```

**`EpisodeRead` has no Phase 1 consumer, and that is deliberate.** No route returns it and no TypeScript mirror exists for it: the entries route answers with `CuratedEntryRead`, whose progress counters are the only per-episode fact the Phase 1 UI needs. It is built because the contract is settled and the Phase 3 player is its first caller. `(season_number, episode_number)` is a **key, never a human `SxxEyy`** — TMDB numbers anime absolutely inside season buckets, so what a screen prints comes from `episode_order` (section 11.2, rule 9). There is no `SeasonRead` and no `ArtworkRead`; neither has a consumer either, and a model with none would be a stub.

```python
# models/curated_entry_read.py
class CuratedEntryRead(BaseModel):
    """One row of a curated watch order, resolved as far as it currently is."""

    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: uuid.UUID
    category_slug: str
    position: int = Field(ge=1)
    sheet_row: int | None = None
    unit_kind: UnitKind
    order_type: str | None = None  # not OrderType: order_type is an open string, read from TheTVDB at runtime (5.13)
    order_label: str = ""
    span_start: int | None = Field(default=None, ge=1)
    span_end: int | None = Field(default=None, ge=1)
    resolution_state: ResolutionState
    resolution_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    resolution_note: str = ""                  # never None: the column is NOT NULL DEFAULT ''
    raw_title: str
    raw_unit: str
    raw_release: str
    cells: dict[str, str] = Field(validation_alias="raw_cells")
    title: TitleRead | None = None
    progress: EntryProgress
```

**`resolution_note` is `str`, never `str | None`** (Ruling 45, T30 — an additive contract field, a **minor** bump). It is why the row sits where it does, in one line, and it has three owners writing three clauses into it: the resolver's own sentence, the expansion's `queue: ` clause, and a reviewer's `review: ` clause. Each owner rewrites only its own clause. A row a human is asked to judge has to say what was already tried, which is why both the review queue (T30) and the Phase 3 unresolved view (T57) render it. **It is not a decision log** (Ruling 48): a re-resolve after the sheet's cells move replaces the note wholesale, so the `review: ` clause recording a confirm or a reject does **not** survive a cell edit. That is a deliberate limit of a one-line note, not an oversight — T57 decides whether a durable decision history is needed, and if it is, it is a new table rather than a longer string.

The TypeScript mirror is `types/CuratedEntryRead.ts`, live today, with the same snake_case names and `resolution_note: string`. **`category_slug: string`** sits right after `id` on both sides (T57, R82) — the workbook id `category.slug` carries, so a queue that spans nineteen categories at once (`GET /api/review/entries`) can say which workbook a row belongs to without a per-row category load; served by a new `services/entries.py:_slugs_for()`, one `IN` query per page over the distinct `category_id`s, because `CuratedEntry.category` is `lazy="raise_on_sql"`. Additive, minor bump, same `v0.2.0` heading.

`availability` and `jellyfin_item_id` are the two fields Phase 3 adds at **T51** (ADR-014, minor bump, recorded here before code), appended after `progress` on both `CuratedEntryRead` and its TypeScript mirror:

```python
    availability: Availability                 # in_library / not_in_library / ambiguous
    jellyfin_item_id: uuid.UUID | None = None  # the title-level movie or series row, only when in_library
```

Both are computed by `services/availability.py`, never inferred from a nullable id. An unconfigured or unreachable Jellyfin yields `not_in_library` and a service-level notice; the notice adds no wire field or response envelope (R103). A live stored pick wins over other candidates; a soft-deleted pick remains ambiguous while a live candidate survives, and becomes absent when none does (R98). Movies use their exact provider-id candidates. An episode entry is `in_library` only when every queued episode slot matched; any ambiguous slot wins over missing slots, otherwise any missing slot or an empty queue is `not_in_library` (R96). The wire id names the title-level movie or selected/sole series row; episode file ids stay on `EpisodeMatch` for the player. Both non-library states carry `None`. Category pages and every review response share the same batched computation; no provider name matching, inferred numbering or per-entry query is permitted.

**T52 playback selection (R104, owner-approved 2026-09-23).**
`GET /api/playback/entries/{entry_id}/items` serves the stored queue separately from this entry
contract, in `position_in_entry` order with the existing capped `limit`/`offset` pagination.
Unknown/removed entries or retired categories are 404; an unavailable Jellyfin is the existing 503.
The frozen `models/playback_item_read.py` response and `types/PlaybackItemRead.ts` match exactly:

```python
id: uuid.UUID
entry_id: uuid.UUID
episode_id: uuid.UUID | None
movie_title_id: uuid.UUID | None
position_in_entry: int                 # >= 1
absolute_position: int                 # >= 1
availability: Availability
jellyfin_item_id: uuid.UUID | None      # live movie/episode file, never a series
order_type: str | None
order_label: str
covers_range: bool
```

T50's join supplies episode matches and their actual numbering; existing movie selection supplies
film matches. Missing/ambiguous slots stay visible with null file IDs, never skipped. Multiple slots
may share a range file without being collapsed. The player initially selects the first slot and
offers explicit slot selection, with no Next/Autoplay or progress reporting before T53/T53a.

```python
# models/entry_progress.py
class EntryProgress(BaseModel):
    """Derived progress for one curated entry, straight off `curated_entry_watch_state`."""

    model_config = ConfigDict(from_attributes=True, frozen=True)

    kind: WatchEventKind
    episode_total: int = Field(ge=0)
    episode_completed: int = Field(ge=0)
    episode_skipped: int = Field(ge=0)
    episode_started: int = Field(ge=0)
    as_of: datetime | None = None
```

```python
# models/jellyfin_item_choice.py  (Phase 3, T56)
class JellyfinItemChoice(BaseModel):
    """Request body for PATCH /api/titles/{title_id}/jellyfin-item: the AMBIGUOUS picker's pick."""

    model_config = ConfigDict(extra="forbid")

    jellyfin_item_id: uuid.UUID
```

The service verifies the `jellyfin_item_id` exists, is not `removed_at`, and belongs to this title's `tmdb_id` (or to its series, for an episode pick) before writing `title.jellyfin_item_id`; a pick that fails any of those is a 404 or a 409, never a silent write. The response is `TitleRead`, and the next `library_sync` run respects the stored pick instead of re-deriving it.

```python
# models/watch_event_create.py
class WatchEventCreate(BaseModel):
    """Request body for recording one watch fact. This is the only write path into the log."""

    model_config = ConfigDict(extra="forbid")

    subject_kind: WatchSubjectKind
    subject_id: uuid.UUID
    kind: WatchEventKind
    category_id: uuid.UUID | None = None
    occurred_at: datetime | None = None
    position_seconds: int | None = Field(default=None, ge=0)
    runtime_seconds: int | None = Field(default=None, gt=0)
    device: str | None = Field(default=None, max_length=120)
    note: str | None = Field(default=None, max_length=240)

    @model_validator(mode="after")
    def _progress_carries_a_position(self) -> WatchEventCreate:
        if self.kind is WatchEventKind.PROGRESSED and self.position_seconds is None:
            raise ValueError("a progressed event needs position_seconds")
        return self
```

`subject_id` is deliberately one field rather than three nullable ones: the API surface is a discriminated pair, and the service maps `(subject_kind, subject_id)` onto the correct typed FK column before insert. The validator duplicates the database `CHECK` on purpose — one rejects a bad request with a 422 at the boundary, the other guarantees the invariant for every writer including migrations. The two caps are `MAX_DEVICE_LENGTH = 120` and `MAX_NOTE_LENGTH = 240` from `constants.py`, matching the `String(120)` / `String(240)` columns on `data/models/watch_event.py`.

```python
# models/watch_event_read.py  (T29)
class WatchEventRead(BaseModel):
    """The stored fact echoed back, plus the entry's derived progress so the UI repaints from the view,
    not the request (master plan section 6.6)."""

    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: uuid.UUID
    occurred_at: datetime
    recorded_at: datetime
    subject_kind: WatchSubjectKind
    kind: WatchEventKind
    source: WatchEventSource
    tmdb_key: str | None = None
    curated_entry_id: uuid.UUID | None = None
    category_id: uuid.UUID | None = None
    position_seconds: int | None = Field(default=None, ge=0)
    runtime_seconds: int | None = Field(default=None, gt=0)
    progress: EntryProgress | None = None
```

**This is what `POST /api/watch-events` answers with — 201, the event as recorded, with the entry's derived progress nested inside it** (Ruling 44). The UI therefore repaints from the view rather than from the request it just sent, which is the same discipline every row endpoint already follows by returning the whole reloaded `CategoryDetail` (section 5.12).

One field does not mean what its name suggests. `curated_entry_id` is **the entry this event moves**, which is the stored column only for a `curated_entry` subject: `one_subject` is a database `CHECK` allowing exactly one of `episode_id` / `title_id` / `curated_entry_id`, so an episode or movie event stores its own typed id and carries the live `curated_entry_item` slot holding it here instead — that is the row whose progress changed and the row the mirror projects onto. `progress` is `None` when no live slot holds the subject: an episode nothing curated covers is still a fact worth logging, and a progress reading invented for it would be a lie.

Three fields are the server's and are absent from the request body: `tmdb_key` (the log's own durable identity, derived from the subject row), `source` (`ui` from this route, `player` from the Phase 3 player, **never** `jellyfin` — section 5.13) and `recorded_at`. `extra="forbid"` on `WatchEventCreate` is what makes a body carrying any of them a 422. `occurred_at` is client-supplied and allowed to arrive late; `recorded_at` is server-assigned; the pair plus `id` is what makes the two `DISTINCT ON` views deterministic (section 11.2, rule 12).

```python
# models/resolution_update.py  (T30)
ReviewAction = Literal["confirm", "correct", "reject"]


class ResolutionUpdate(BaseModel):
    """A human decision about one entry.

    `confirm` carries no field but the note; `correct` requires `media_type` and `tmdb_id` and takes the
    span fields optionally; `reject` carries the note alone.
    """

    model_config = ConfigDict(extra="forbid")

    action: ReviewAction
    media_type: MediaType | None = None
    tmdb_id: int | None = Field(default=None, ge=1)
    unit_kind: UnitKind | None = None
    # An open string, validated at apply time against the numberings the title actually carries, never
    # against a list in this codebase (section 5.13).
    order_type: str | None = Field(default=None, max_length=MAX_ORDER_TYPE_LENGTH)   # 32, the column's width
    span_start: int | None = Field(default=None, ge=1)
    span_end: int | None = Field(default=None, ge=1)
    # Season 0 is the specials bucket and is kept, so this floor is zero rather than one.
    season_number: int | None = Field(default=None, ge=0)
    note: str = Field(default="", max_length=MAX_REASON_LENGTH)

    @model_validator(mode="after")
    def _coherent_for_its_action(self) -> ResolutionUpdate:
        """`correct` names a title; `confirm` and `reject` name none; a reversed span is refused."""
```

**`confirmed` is human-only, and it is the one state no heuristic writes.** A `correct` and a `confirm` both land `resolution_state = 'confirmed'` with `resolution_confidence = 1.00` — a value the resolver cannot produce, so "a human decided this" is legible from the confidence alone as well as from the state. `ingest/reconciler.py:needs_resolution` then answers `False` for that row for as long as its raw cells do not move, which is master plan §6.5 rule 5 enforced in one place rather than two.

**`reject` is not a delete.** The row keeps its `position`, its `sheet_row` and its verbatim `raw_cells`; what it loses is the match — `title_id`, `order_type`, the span, the season and the confidence. It leaves the review queue (which holds `unresolved` and `auto`) and stays a first-class row of `GET /api/categories/{id}/entries`, because tracked-but-not-available-here is a state, not an error (section 18.2). A successful `confirm` or `correct` **rebuilds that entry's `curated_entry_item` rows immediately** (Ruling 46) and renumbers the category, so a row leaving `unresolved` becomes expandable in the same request.

`CuratedEntryRead` is the response of **both** review routes — the review API adds no response model of its own. The frontend mirror is `types/ResolutionUpdate.ts`, snake_case, with `?: T | null` on each of the seven nullable fields.

**The one rule at the conversion boundary, which breaks loudly under asyncio if ignored:**

> **Nothing crosses the boundary unless it was eagerly loaded.**

`from_attributes=True` reads attributes off the ORM instance. Under asyncio, touching an unloaded relationship or an expired attribute triggers a lazy load outside a greenlet and SQLAlchemy raises `MissingGreenlet` — at serialisation time, deep inside FastAPI, with a stack trace that does not name the relationship. Load with `selectinload` / `joinedload` in the service, then convert.

### 5.16 The four-value mirror is a contract too

```python
# services/watch_mirror.py
_CELL_FOR_KIND: dict[WatchEventKind, str] = {
    WatchEventKind.COMPLETED: WATCHED,        # "Watched"
    WatchEventKind.SKIPPED: SKIPPED,          # "Skip"
    WatchEventKind.STARTED: IN_PROGRESS,      # "In progress"
    WatchEventKind.PROGRESSED: IN_PROGRESS,
    WatchEventKind.UNSET: UNWATCHED,          # ""
}


def watch_cell(kind: WatchEventKind) -> str:
    """The four-value `Watched?` value this derived state projects onto."""
    return _CELL_FOR_KIND[kind]
```

One dict, no branching, and **every constant is imported from the existing `constants.py:12-16`** — none is re-declared. The projection is one-directional and lossy by construction: the cell cannot express "9 of 35 episodes done", "42 minutes into episode 12", or "episodes 1–8 completed and 9–12 skipped". All of that lives in `watch_event`, and writing the cell deletes none of it.

Two columns on `curated_entry` contain the loss:

- **`mirrored_watch_cell`** — the value the app last *wrote* into the sheet.
- **`observed_watch_cell`** — the value the app last *read* from the sheet.

On ingest, per entry: if the sheet cell equals `mirrored_watch_cell`, it is our own echo and is ignored; if it differs, a **human** edited it in Excel, and one coarse `excel_mirror` event is appended at the **entry** level, carrying `occurred_at = now()` and a note recording the literal cell text. It touches no episode event, and by the precedence rule in section 5.14 it becomes the entry's status while the underlying episode history stays intact beneath it.

**The echo hazard, named so nobody removes the column that prevents it:** without `mirrored_watch_cell`, every mirror write would look like a human edit on the next ingest, generating an `excel_mirror` event, which would re-derive the same status, which would rewrite the same cell — a stable but ever-growing loop. The stored last-written value is the entire defence, and it is why that column is not redundant with `observed_watch_cell`.

The reverse write is throttled to real changes — an entry is written back only when `watch_cell(state.kind) != entry.mirrored_watch_cell` — and goes through `Catalog._write`, so a mirror pass while the workbook is open in Excel fails cleanly (423) and retries next pass. `mirrored_watch_cell` and `category.workbook_mtime` update **in the same transaction as the `apply_changes` call**; if the write raises, neither updates and the next pass replays the identical diff. That ordering is what makes the mirror idempotent.

**The mirror never fails an ingest pass** (Ruling 41, T25). The status column is the *owner's*, not the app's: a workbook dropped into the library may offer `Yes,No` where the nineteen offer the four values, and `writer._validate` refuses the whole write on the first value a dropdown does not recognise — which on the ingest path would roll the entire pass back and make that workbook permanently un-ingestable over one odd dropdown. So `writable_mirror_cells` (`services/watch_mirror.py`) drops the cells the column's own vocabulary refuses, logs each one (`mirror_skipped_cell … skipped=invalid_choice`), and lets the rest go in; the entries behind the dropped cells keep their old `mirrored_watch_cell`, so nothing claims a write that never happened. A `text` column has no vocabulary to contradict, so nothing is dropped for one. **The sheet's vocabulary wins.**

**How the mirror loses the race, per row.** On a `StaleWorkbookError` the retry does not simply re-read the mtime: `_still_ours` re-reads the sheet and checks **every planned row** twice over — that the row still carries that entry's own `Row ID`, because a row number means nothing except against the grid it was resolved on, and that the cell still holds exactly what this app last wrote there, because anything else is a human edit the mirror must lose to rather than overwrite. A single contested row abandons the whole retry (`mirror_contested … rows=N of=M`) and the pass defers; the identical diff replays next time. A workbook carrying no identities at all fails the first check for every row, which is the honest answer — the mirror cannot prove which row it would be writing. `tests/services/test_mirror_race.py` (T26, 12 tests) injects the race at the real seam and proves the production `guard_fresh` refuses it; `services/watch_mirror.py` needed no change to satisfy that contract.

### 5.17 R105 — automatic player snapshots (approved 2026-09-24)

The exact contract is `docs/TV_MASTER_PLAN.md` §6 R105, recorded before implementation. It
supersedes every earlier five-second/terminal-only playback rule in this file and local skills:
both PostgreSQL and Excel save every **60 seconds while playing**, plus pause/ended/close.
`ColumnRole` gains `position` in Python and TypeScript together; Position remains an app-owned,
visible-in-Excel projection excluded from public columns, cells and ingest truth.

`POST /api/watch-events` retains `WatchEventCreate` and 201 `WatchEventRead`, adding paired optional
UUID query parameters `playback_entry_id` and `jellyfin_item_id`. Validate the exact live entry,
queue subject and selected live file, derive PLAYER server-side, and suppress the ordinary
background mirror for this path. The existing non-player route behaviour is unchanged.

`POST /api/playback/entries/{entry_id}/position` accepts `PositionWrite`:

```python
watch_event_id: uuid.UUID
expected_mtime: float
```

The request forbids extras and returns the existing `CategoryDetail`. The server validates the
committed event and projects the newest player snapshot's position/runtime for that entry, never a
client row coordinate or text. One `Catalog._write` combines Position and all currently pending
eligible Watched cells for the selected workbook, including earlier failed completion projections. Resolve current
Row IDs before the first write; recheck identities and contested cells before one stale retry.
Both routes serialize on the category; an older player snapshot cannot overwrite a newer one.
Range siblings sharing occurred_at/kind/position/runtime are one snapshot, not competing UUIDs.

The frontend queues the entire event-plus-projection pair, captures occurred_at and immutable
entry/file/category/mtime scope, and retains a committed event id for projection-only retry after
423/409, retaining the original projection expected_mtime across requests rather than forcing a
stale snapshot over a human edit. Unsaved event facts remain retryable even after a newer snapshot
succeeds; their original occurred_at is retained, and recovery cannot regress the newest Position.
Only already-committed older workbook projections can be superseded. Failed saves remain visible after closing the player. Terminal duplicates are suppressed;
ended is latched before async work so cleanup cannot regress it. Hard browser/process termination
cannot guarantee a final network save.

No contained episode completes before the **whole file ends**. A completed request requires a
finite positive runtime and position >= runtime; clip stored/projected position to runtime.
Resolve all episodes through the selected title's actual stored order type/label and the file's
inclusive numbered range, including those outside the selected entry span; batch insert atomically.
Missing/conflicting mapping is 409 before any insert. Never guess offsets or use TMDB arithmetic.

### 5.18 R106 — recoverable import operation (approved 2026-09-24)

The complete column/index/service contract is `docs/TV_MASTER_PLAN.md` §6 R106. T66 adds
`MediaImportOperation` / `media_import_operation` and native phase enum in revision `0004`, without
changing `media_import` or MediaImportStatus. UUID/timestamps, media_import FK RESTRICT, canonical
root snapshots, relative source/destination/temp/archive paths, typed JSONB file identities,
source/previous-destination/verified digests, rollback status and error form the durable record.
Active unique claims cover import id, source and destination; terminal history is retained.

Commit prepared intent before mutation; copy while retaining staging; archive a replaced file under
a collision-safe operation stamp; atomically install and hash the destination; commit provenance and
supersede stamps; only then remove an unchanged source. Recovery checks actual committed state and
artifact identities/digests, not phase alone. Unknown ownership or changed roots/artifacts retains
bytes and active claims with an explicit error. Pre-commit rollback restores the archived original
and removes only proven owned copies. Sessions belong to each worker, with an operation lock held
across phase transactions; cancellation drains filesystem work before releasing the lock.
An OS source-file lock survives database-connection loss and remains held through cleanup; it never
modifies media bytes. COMMITTED recovery checks actual provenance plus installed bytes before removing
staging or declaring completion. Native exclusive rename refuses existing targets atomically; there
is no hard-link requirement or unsafe overwrite fallback. Unsupported filesystems retain recovery
state. Root/parent checks repeat before destructive transitions. Cooperating-worker exclusion does
not isolate against arbitrary concurrent external pathname replacement; leave import roots untouched
while a job runs. Filesystem power-loss guarantees are not inferred from process-crash tests.

### 5.19 T53a — approved ordering and durable completion history

Owner-approved 2026-09-24: a finished episodes 1–3 file must not replay for its covered continuation
slots; retain an interleaved movie and then continue to episode 4. Master plan §6.9 rule 8 is the
authoritative behavior. No global Watched-item skipping or maximum-position jump is implied.

The owner has approved PostgreSQL file-completion history surviving close/reopen, with explicit
Play available for rewatches. Before code, master plan §6.9 records the exact revision 0005 contract:
`playback_completion` (UuidPk; unique selected_watch_event_id FK; category_id/source_entry_id FKs;
historical jellyfin_item_id_snapshot UUID and nonempty jellyfin_id_snapshot String(64); nullable
order_type String(32), order_label String(120) default empty; nullable nonnegative parent/index/end;
SHA-256 queue_fingerprint String(64); typed occurrence_snapshot JSONB array) and
`playback_completion_event` (UuidPk; completion_id/watch_event_id RESTRICT FKs, unique event and
unique pair). All FKs point at retained category/entry/event records, not disposable metadata.
Both tables reject UPDATE/DELETE and omit TimestampMixin. Movie receipts have null order_type,
empty label and null indices; episode receipts have nonempty order and season/start, with end >=
start when present. Capture these snapshots from the validated selection, never from client claims.

Occurrence JSON uses frozen, extra-forbid Pydantic models with exactly entry_id UUID,
subject_kind episode/title, subject_id_snapshot UUID, tmdb_key nullable string and positive
position_in_entry. It records all matching live occurrences as evidence, not blanket skip permission.
The semantic queue fingerprint includes empty barriers and interleaved films but excludes queue UUIDs,
watch state and timestamps. Queue-cache rebuilds preserve it; curation edits stop auto-continuation.
Membership contains the selected event and every actual range sibling event, in the existing T53
completion transaction. No progressed/manual event receipt and no timestamp-based history backfill.
The master plan's coherence rule is mandatory: acquire the category lock before a fresh live-entry
read; reconciler and resolution writers use the same fence. Completed playback takes batched,
nonblocking shared transaction advisory locks for referenced titles; the sole numbering writer takes
the matching nonblocking exclusive lock before its comparison/write leg. TMDB episode upserts take
the same exclusive try-lock, including when TheTVDB is unconfigured. Contention refuses the
whole snapshot/ingest for retry; no partial ordering is accepted and no advisory lock waits behind
existing episode/FK or differently ordered title locks. Review retry keeps its existing 409 envelope.
No Next endpoint or navigation wire model is introduced by this persistence step.
The existing watch-event and playback-item contracts stay unchanged. A timestamp group is not a
persisted file identity. Reuse T53's completion transaction and projection retry rather than
introducing another writer. Keep intentional rewatches distinct from covered continuation slots.

**Open implementation blocker, 2026-09-24:** TMDB's globally unique episode-ID upsert can move an
episode from title A to B while locking only B. Independent real-database reproductions bypassed
A's shared completion gate. Refusing the reassignment versus moving it and reconciling existing
watch-list links is not decided; ask the owner and enforce the approved rule atomically before
calling this foundation complete. Same-title renumbering is protected, not cross-title ownership.
The local 4,040-test pass does not waive this finding; see `docs/playback-completion-validation.md`.

</data_contracts>

---

<containerization>

## 6. Containerization

### 6.1 Every Docker-related file in the repo

| File | Lines | What it is |
|---|---|---|
| `docker-compose.yml` | 148 | Repo root. Compose v2, no top-level `version:` key. `name: tv-watchlist` (`:16`). Four services — backend, frontend, `postgres` (the Phase 1 projection, T09) and `jellyfin` (an optional peer, no `depends_on`, T47a), both landed 2026-09-20 — plus three named volumes. |
| `app/backend/Dockerfile` | 112 | Two-stage `python:3.13-slim` build for the FastAPI service. Since T09 it also COPYs `alembic.ini`, `alembic/`, `data/` and `docker-entrypoint.sh`, and its `CMD` is the entrypoint. |
| `app/backend/docker-entrypoint.sh` | 11 | T09. `alembic upgrade head` then `exec uvicorn` — the image's `CMD`. See section 6.3. |
| `app/backend/.dockerignore` | 17 | Excludes `.venv/`, `**/__pycache__/`, `**/*.py[cod]`, `.pytest_cache/`, `.ruff_cache/`, `.mypy_cache/`, `.coverage`, `.coverage.*`, `coverage.xml`, `htmlcov/`, `junit-*.xml`, **`tests/`**, `Dockerfile`, `.dockerignore`, `.env`, `.env.*`. |
| `app/frontend/Dockerfile` | 46 | Two-stage `node:22-alpine` → `nginxinc/nginx-unprivileged:alpine`. |
| `app/frontend/.dockerignore` | 13 | Excludes `node_modules/`, `dist/`, `coverage/`, `test-results/`, `playwright-report/`, `blob-report/`, `*.tsbuildinfo`, `junit-*.xml`, `Dockerfile`, `.dockerignore`, `.env`, `.env.*`. |
| `app/frontend/nginx.conf` | 80 | Copied to `/etc/nginx/conf.d/default.conf` (`app/frontend/Dockerfile:40`). Serves `dist/`, reverse-proxies `/api/` and `/heroes/`, and carries every security header. |
| `.gitignore:82` | — | `docker-compose.override.yml` is ignored, so a local override never lands in a commit. |
| `.gitattributes:43-46` | — | `Dockerfile`, `*.Dockerfile`, `.dockerignore` and `nginx.conf` are pinned to `eol=lf` by name. A CRLF `Dockerfile` breaks its `RUN` lines on Linux. |

The gitignored root `.env` exists (owner-typed, created 2026-09-15; protected from agent inspection), and
**`.env.example` now exists beside it** — 16 `TV_` variables with placeholders, committed via the
`!.env.example` negation (T01b). There is no other `.env.*`. Every value the containers need is an
image default, a compose `environment:` entry, or root-`.env` substitution.
The 2026-09-24 baseline and some ordinary focused test imports may have loaded dotenv into process
memory before their fixture disabled it; no credentials were printed. The isolation gap and the
credential-safe final-suite command are disclosed in `docs/playback-completion-validation.md`, not
claimed fixed here.

### 6.2 What `docker-compose.yml` declares today

**`backend`** (`docker-compose.yml:19-71`)

- `build.context: ./app/backend` (`:20-21`), no `dockerfile:` key, so the default `Dockerfile`.
- `image: tv-watchlist-backend:local` (`:22`), `restart: unless-stopped` (`:23`).
- `environment:` — `TV_LIBRARY_DIR=/library` (`:28`), `TV_HEROES_DIR=/library/app/heroes` (`:29`),
  `TV_BACKUP_DIR=/library/app/.backups` (`:30`), `TV_BACKEND_PORT="8284"` **hard-coded** (`:32`;
  the comment at `:31` says only the *published* port is configurable, because the container's own
  listener is fixed by the entrypoint), `TV_FRONTEND_PORT="${TV_FRONTEND_PORT:-5284}"` (`:35`), which
  exists solely to build the CORS allowlist (`:33-34`), and — since 2026-09-20 —
  `TV_JELLYFIN_BASE_URL: "http://jellyfin:8096"` (`:39`) with
  `TV_JELLYFIN_API_KEY: "${TV_JELLYFIN_API_KEY:-}"` (`:40`), the key deliberately left to root-`.env`
  substitution rather than written into the file (`:36-38`). **Since T09 (2026-09-20) it also carries
  the five Postgres names** (`:43-47`): `TV_POSTGRES_HOST: postgres` — the compose service name, not a
  host — and `TV_POSTGRES_PORT: "5432"`, the **container's own** port, because inside the network the
  backend never goes through the host publication; then `TV_POSTGRES_DB`, `TV_POSTGRES_USER` and
  `TV_POSTGRES_PASSWORD`, each `${TV_POSTGRES_*:-tv}`. The comment at `:41-42` states the split so
  nobody "corrects" the 5432 to 5525.
- `volumes: - "${TV_LIBRARY_HOST:-.}:/library"` (`:52`). **The repo root is the library** — the
  nineteen `.xlsx` files, `app/heroes/` and `app/.backups/` are all bind-mounted in at `/library`.
  The comment at `:49` now reads "the 19 workbooks" — T01c corrected it along with the same
  off-by-one in `README.md:47` and `.gitignore:4`.
- `ports: - "${TV_BACKEND_PORT:-8284}:8284"` (`:54`).
- `depends_on: postgres: { condition: service_healthy }` (`:55-59`), added by T09. The entrypoint
  runs `alembic upgrade head` before uvicorn, and waiting on health is what makes that safe; the
  comment at `:56-57` says so, and a bare `depends_on` list is forbidden by the global contract.
- `healthcheck` (`:60-71`): exec form,
  `CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8284/openapi.json', timeout=5)"`,
  `interval: 15s`, `timeout: 10s`, `retries: 5`, `start_period: 20s`. The comment at `:49-50`
  states why `/openapi.json` and not a health route: **it touches no workbook**, so a probe every
  fifteen seconds does not re-read nineteen Excel files. There is no `/health` endpoint in the app
  and one must not be added just to satisfy a probe.

**`frontend`** (`docker-compose.yml:73-90`)

- `build.context: ./app/frontend` (`:74-75`), `image: tv-watchlist-frontend:local` (`:76`),
  `restart: unless-stopped` (`:77`).
- `ports: - "${TV_FRONTEND_PORT:-5284}:8080"` (`:80`). Container-internal `8080`, not `80`,
  because the nginx image is unprivileged and cannot bind a low port (`:79`).
- `depends_on: backend: { condition: service_healthy }` (`:81-84`). This is not decoration:
  `app/frontend/nginx.conf:14-16` declares `upstream tv_backend { server backend:8284; }` and
  **nginx resolves an upstream name once, at startup** — if the backend is not up, the frontend
  container starts with a dead upstream and stays that way.
- `healthcheck` (`:85-90`): `["CMD", "wget", "--quiet", "--tries=1", "--spider", "http://127.0.0.1:8080/"]`,
  `interval: 15s`, `timeout: 5s`, `retries: 5`, `start_period: 10s`.
- No `environment:` block, no volumes — the image ships `dist/` and `nginx.conf` and nothing else.

**`postgres`** (`docker-compose.yml:92-116`) — **built at T09, 2026-09-20.** `image:
postgres:16-alpine` (`:94`), `restart: unless-stopped` (`:95`); `POSTGRES_DB` / `POSTGRES_USER` /
`POSTGRES_PASSWORD` from `${TV_POSTGRES_*:-tv}` (`:96-99`); the named volume
`tv_postgres_data:/var/lib/postgresql/data` (`:100-101`); `ports:
- "127.0.0.1:${TV_POSTGRES_PORT:-5525}:5432"` (`:108`) — **loopback-bound, and the bind address is
part of the mapping** (Ruling 24), because the default credentials are `tv`/`tv` and the host side is
published at all only so the launchers' host-native backend can reach it (`:103-107`); `healthcheck`
`["CMD-SHELL", "pg_isready -U ${TV_POSTGRES_USER:-tv} -d ${TV_POSTGRES_DB:-tv}"]` (`:109-116`), the
shell form because that substitution needs one (`:110-111`). The comment at `:93` states the
standing rule in one line: derived from the workbooks, never authoritative for order.

**`jellyfin`** (`docker-compose.yml:118-143`) — landed 2026-09-20, ahead of Phase 3 and by owner
request, so the API key can be created in Jellyfin's own UI. `image: jellyfin/jellyfin:12.1` (`:122`),
pinned never `:latest` (`:119-121`); `restart: unless-stopped` (`:123`); the two named volumes
`tv_jellyfin_config:/config` and `tv_jellyfin_cache:/cache` (`:125-126`) plus the read-only media bind
mount `"${TV_JELLYFIN_MEDIA_HOST:-./media}:/media:ro"` (`:130`); `ports:
- "${TV_JELLYFIN_PORT:-8096}:8096"` (`:135`); `healthcheck` on `GET /health` (`:138-143`). **No
service depends on it** (`:136-137`) — it is an optional peer and the rule is section 6.6's. The
client, the sync and every API call remain Phase 3.

**The Jellyfin container is declared but has never started on the owner's Mac.** As of 2026-09-20,
Docker Desktop's VM cannot pull *any* image while NordVPN's Shield network system extension is
active: the host reaches Docker Hub, the VM transfers nothing, and restarting Docker Desktop does
not clear it. The unblock is the owner's, not an agent's — pause NordVPN or add Docker to its
exceptions (or bring the stack up on the Windows machine), then `docker compose up -d jellyfin`,
open <http://localhost:8096/web>, create the admin account, and Dashboard → API Keys → New, named
`tv-app`. The compose service, the volumes, the gitignored `/media/` and the `PORT_ASSIGNMENTS.md`
row are all in place and correct; only the running container is outstanding. **Nothing in Phase 1
depends on it**, and the backend must boot and serve with Jellyfin absent.

**The same caveat covers Postgres: declared and reviewed, never yet brought up on this Mac.** T09 is
code-complete and its compose, entrypoint and CI wiring are tested offline (`tests/test_compose.py`,
`tests/test_docker_entrypoint.py` — 46 tests between them, which read the files rather than run
them), but the VPN block above stops Docker Desktop's VM pulling `postgres:16-alpine`, so no agent
has watched `Running upgrade -> 0001` scroll past before `Uvicorn running`. That first live bring-up
is the owner's, off the VPN, and it is the one thing about the service that is asserted on paper only.

**Not present today:** no top-level `networks:` (the default bridge is used), no `env_file:`, no
profiles and no `deploy:`. **Present since 2026-09-20:** four services — `backend`, `frontend`,
`postgres` (T09) and `jellyfin` (T47a) — and a top-level `volumes:` with **three** named volumes,
`tv_postgres_data`, `tv_jellyfin_config` and `tv_jellyfin_cache` (`:145-148`).

### 6.3 The image shapes, and the decisions baked into them

`app/backend/Dockerfile`:

- Both stages are `python:3.13-slim`, **never alpine** (`:14-16`) — musl has no manylinux wheels and
  `pydantic-core` would compile from source.
- `WORKDIR /srv/app/backend` in **both** stages (`:32`, `:85`). The depth is load-bearing and is
  documented at `:26-31`: `config.py:17` computes `REPO_ROOT` from
  `Path(__file__).resolve().parents[4]`, so the package must sit at least five levels below `/` or
  the module raises `IndexError` at import, before uvicorn ever binds. Do not "tidy" this path.
- `:44-46` runs `uv sync --frozen --no-dev --no-install-project` and, **in the same `RUN` layer**,
  `find /srv/app/backend/.venv -type f -path '*/claude_agent_sdk/_bundled/claude*' -delete`. The
  Linux wheel of `claude-agent-sdk` bundles a ~340 MB `claude` binary; deleting it in the same layer
  keeps it out of the image entirely (`:38-42`).
- **`:54-58`, added by T09, copies four things `src/` alone does not carry** — `alembic.ini`,
  `alembic/`, `data/` and `docker-entrypoint.sh`, then `chmod 0755` on the last of them. The comment
  at `:50-53` says why each has to be there: the runtime stage copies the whole
  `/srv/app/backend` tree (`:86`), the entrypoint runs `alembic upgrade head` out of it, and
  `data/franchise_prefixes.json` is read at runtime by `resolver/franchise.py:16`
  (`parents[3] / "data"`), which raises if the file is absent. `data/` sits **outside** the package
  by the project skeleton (Ruling 22) and therefore is not in the wheel — the Dockerfile `COPY` is
  the only thing that puts it in the image, which is why the JSON must be staged in the same commit
  as this Dockerfile or a fresh-clone build fails.
- `:79-82` deliberately deletes `pip`, `pip-*.dist-info`, `pkg_resources` and the `pip`/`pip3`/
  `pip3.13` entry points, because pip vendors msgpack and setuptools and trivy reports both as HIGH
  (`:76-78`). Nothing in the app imports them.
- `:71-73` runs `apt-get update && apt-get upgrade -y` so that `trivy --ignore-unfixed` in CI only
  fails on findings a rebuild can actually clear (`:68-70`).
- `:103-106` creates `watcher` (uid 10001), `mkdir -p /library`, `chown`, `USER watcher` — the
  container **runs unprivileged**. `:108` `EXPOSE 8284`. `:112`
  `CMD ["/srv/app/backend/docker-entrypoint.sh"]`, JSON array form — **not uvicorn directly**, since
  T09.

`app/backend/docker-entrypoint.sh` (11 lines) is the whole of that indirection, and every line of it
is load-bearing: `set -eu`, `cd /srv/app/backend`, `alembic upgrade head`, then
`exec uvicorn tv_watchlist.main:app --host 0.0.0.0 --port 8284`. The migration is unconditional
because compose's `depends_on: condition: service_healthy` on `postgres` is what makes it safe, and
`exec` is what makes uvicorn PID 1 so it receives `SIGTERM` directly. **A migration that keeps
failing is therefore a crash loop by design** under `restart: unless-stopped` (`:2-7`): the API never
serves a schema the code does not expect, and the restarts are the visible symptom rather than a
silent half-working container. Do not add a retry loop, a `|| true`, or a fallback that starts
uvicorn anyway.

`app/frontend/Dockerfile`:

- `:14` `corepack enable && corepack prepare pnpm@9.15.9 --activate`, pinned to the writer of
  `pnpm-lock.yaml` (lockfileVersion 9.0). This machine's Corepack defaults to pnpm 11, which is why
  `package.json:6` also carries `"packageManager": "pnpm@9.15.9"`.
- `:18-21` installs **with** dev dependencies, deliberately (`:19-20`): `pnpm build` runs `tsc -b`
  first, and `tsconfig.json` includes `tests/` and `layout/`, which import vitest and
  `@playwright/test`.
- `:31` `FROM nginxinc/nginx-unprivileged:alpine`, chosen over `nginx:alpine` because the stock
  image's master process runs as root to bind `:80` (`:26-30`). `:36-37` `USER root` +
  `apk upgrade --no-cache` to clear exactly the findings CI's trivy gate fails on, then `:42`
  `USER nginx`, `:44` `EXPOSE 8080`.
- The final image carries **no `node_modules`, no Node runtime, no Playwright browsers, no source** —
  only `dist/` and the nginx config.

### 6.4 Chat answers 503 under Docker, on purpose

`docker-compose.yml:9-11` and `app/backend/Dockerfile:5-9` both state it, and it is the single most
important thing to know before "fixing" a container build:

**The backend image deliberately carries neither the `claude` CLI nor Playwright's Chromium.** The
chat subsystem drives `claude_agent_sdk.ClaudeSDKClient`, which spawns the locally installed
`claude` binary as a subprocess and speaks its JSON control protocol over stdio; there is no HTTP
call to an Anthropic endpoint anywhere in the package. Three facts converge:

1. The SDK ships no CLI on Windows, and on Linux the bundled one is deleted at build time
   (`app/backend/Dockerfile:38-46`).
2. The image installs no Node and no `@anthropic-ai/claude-code`, so `claude` is not on `PATH`.
3. `ClaudeSDKClient.connect()` then raises `claude_agent_sdk.CLINotFoundError`, which
   `src/tv_watchlist/api/errors.py:43` maps to **HTTP 503** with the message at `errors.py:58`:
   `"Claude Code is not installed, or \`claude\` is not on this machine's PATH."`

Deleting the bundled binary is what makes this a *clean* 503 rather than an authentication crash:
with the binary present a chat turn would reach it and die at authentication instead of never
starting (`app/backend/Dockerfile:38-42`). **Every other endpoint works normally in the containers.**
Chat is a host-only feature — run `./run_tv.sh` or `run_tv.bat`, whose preflight
(`src/tv_watchlist/agent/preflight.py`) prints the two install lines before the promise is made.

Do not add Node, the Claude CLI, or Chromium to the backend image to "make chat work in Docker".
That trades a documented, clean 503 for a ~1 GB image, a root-capable browser sandbox, and a
credential that would have to live in the container.

### 6.5 The two run paths are alternatives, not layers

The two *servers* are host-native on the launcher path: `run_tv.sh:93-120` and `run_tv.bat:64-95`
start `uv run uvicorn` and `pnpm dev` directly, because that is what keeps chat working. Docker is
still the separate whole-stack path documented in `README.md` (`docker compose up --build -d`).
**Since T32a (2026-09-20) the launcher path is no longer compose-free, though:** `ensure_postgres`
(`run_tv.sh:63-80`, `run_tv.bat:152-180`) runs `docker compose up -d postgres`, polls
`docker inspect` for `healthy` up to `POSTGRES_WAIT_SECONDS` = 60, then runs
`uv run alembic upgrade head` from `app/backend` — because the host-native backend has no entrypoint
to migrate for it (section 6.3). It reports failure with a `return` / `exit /b 1` rather than an
exit, so `[r]` can say so and go back to the menu instead of taking the launcher down. Consequences:

- Three host ports are open at once on the launcher path — 5284, 8284 and 5525 — where it used to be
  two. **The two modes must never run concurrently**; both bind the same ports.
- **All four menu options exist** (`run_tv.sh:172-216`, `run_tv.bat:96-151`), and T32a's review has
  closed — but **no agent has executed either launcher end to end**, because the same VPN block that
  stops the image pulls (section 6.2) stops `ensure_postgres`. The shapes below are therefore
  reviewed and asserted by test, never run: that gap is the owner's first bring-up to close, and it
  is the one thing about the launchers taken on paper.
  `app/backend/tests/test_launchers.py` (4 tests) greps both files for the whole
  compose invocations, which is why neither script puts `-f "$COMPOSE_FILE"` between
  `docker compose` and its subcommand — both `cd` to their own directory instead.
  - `[r]` — restart, non-terminal, unlimited (`run_tv.sh:187-191`, `run_tv.bat:113-118`). It stops
    the two servers, re-runs `ensure_postgres`, and starts them again; Postgres stays up.
  - `[k]` — **stop and exit, running `docker compose down`** (`run_tv.sh:192-196` through
    `stop_keep` at `:158-162`; `run_tv.bat:120-128`). Images and volumes are kept. Taking the
    containers down is the global launcher contract's `[k]`, not an embellishment (Ruling 28): a
    separately started `jellyfin` container goes down with it and its data survives in the named
    volumes.
  - `[q]` — `docker compose down --remove-orphans`, then removes only images matching the
    `tv-watchlist` prefix (`run_tv.sh:197-204` with `remove_images` at `:149-156`;
    `run_tv.bat:130-139`). **Volumes are kept.** `postgres:16-alpine` and `jellyfin/jellyfin` are
    upstream images nothing here built, so they stay.
  - `[v]` — the same, plus `--volumes`, dropping `tv_postgres_data` and the two Jellyfin volumes
    (`run_tv.sh:205-212`, `run_tv.bat:141-150`).
- Unrecognised input re-prompts rather than exiting (`run_tv.sh:213-215`; `run_tv.bat`'s
  `choice /c rkqv` at `:106` plus `:111 goto menu`, with the `errorlevel` tests highest-first at
  `:107-110` because `if errorlevel N` is true for every level `>= N`).

### 6.6 The Postgres service and the Jellyfin peer — both built 2026-09-20

Phase 1's half of this section is **done**. T09 added **one service, one named volume, one host port
and one `depends_on` edge** to the compose file, and nothing more; the Phase 3 half — **one more
service (`jellyfin`), two more named volumes, one read-only media bind mount and one more host port
(`8096`), and deliberately no `depends_on` edge** (ADR-014, T47a) — **landed early the same day, by
owner request**, so the API key could be created in Jellyfin's UI. Both are on disk and both are
reproduced below as built. The stack is therefore four services, three named volumes and two
allocated host ports beyond the three live ones — and that is the end state, not a waypoint. The
TMDB/TVDB response cache is `sync_state` plus the projection tables, in Postgres, where it is
already durable, already migrated and already visible to a query.

Neither service has been started on this machine yet: Docker Desktop's VM cannot pull an image while
the VPN is up (section 6.2). The files are reviewed; the live bring-up is the owner's.

```yaml
  postgres:
    # The Phase 1 projection. Derived from the workbooks, never authoritative for order (ADR-001).
    image: postgres:16-alpine
    restart: unless-stopped
    environment:
      POSTGRES_DB: "${TV_POSTGRES_DB:-tv}"
      POSTGRES_USER: "${TV_POSTGRES_USER:-tv}"
      POSTGRES_PASSWORD: "${TV_POSTGRES_PASSWORD:-tv}"
    volumes:
      - tv_postgres_data:/var/lib/postgresql/data
    ports:
      # 5525 is this project's reserved slot in the 5520-5591 range (PORT_ASSIGNMENTS.md). Never host
      # 5432 - that is the machine's single shared local PostgreSQL listener, for client connections only.
      # Bound to 127.0.0.1 explicitly: every listener in this project is loopback-only, and the default
      # credentials are tv/tv, so an all-interfaces bind would put a trivially-guessable database on the
      # network. The host side is published at all only so the launchers' host-native backend can reach it.
      - "127.0.0.1:${TV_POSTGRES_PORT:-5525}:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${TV_POSTGRES_USER:-tv} -d ${TV_POSTGRES_DB:-tv}"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 10s

volumes:
  tv_postgres_data:
```

and `backend` gained both the edge and the five names:

```yaml
    environment:
      # Inside the compose network the backend reaches the service by name on the container's own
      # 5432; 5525 is only the HOST publication on the postgres service above.
      TV_POSTGRES_HOST: postgres
      TV_POSTGRES_PORT: "5432"
      TV_POSTGRES_DB: "${TV_POSTGRES_DB:-tv}"
      TV_POSTGRES_USER: "${TV_POSTGRES_USER:-tv}"
      TV_POSTGRES_PASSWORD: "${TV_POSTGRES_PASSWORD:-tv}"
    depends_on:
      postgres:
        condition: service_healthy
```

**The Jellyfin service (T47a, ADR-014) landed 2026-09-20, ahead of its phase and by owner request, so
the API key could be created in Jellyfin's UI. It is on disk; everything else Phase 3 needs — the
client (T48), the sync (T49), every API call — still waits for the Phase 1 gate:**

```yaml
  jellyfin:
    # 12.1 verified against Docker Hub and the GitHub release feed 2026-09-20 (12.1 released
    # 2026-09-15; 12.0 on 2026-09-08). Pinned, never :latest — the API surface is what T48 codes to.
    image: jellyfin/jellyfin:12.1
    restart: unless-stopped
    volumes:
      - tv_jellyfin_config:/config
      - tv_jellyfin_cache:/cache
      # The owner's own files, read-only. The app never writes media and Jellyfin never needs to.
      - "${TV_JELLYFIN_MEDIA_HOST:-./media}:/media:ro"
    ports:
      # 8096 is Jellyfin's own default and this project's second allocated host port after 5525.
      - "${TV_JELLYFIN_PORT:-8096}:8096"
    healthcheck:
      test: ["CMD", "curl", "--fail", "--silent", "http://127.0.0.1:8096/health"]
      interval: 15s
      timeout: 5s
      retries: 5
      start_period: 30s

volumes:
  tv_postgres_data:
  tv_jellyfin_config:
  tv_jellyfin_cache:
```

and `backend`'s `environment:` gains, explicitly (no `env_file:`):

```yaml
      TV_JELLYFIN_BASE_URL: "http://jellyfin:8096"
      TV_JELLYFIN_API_KEY: "${TV_JELLYFIN_API_KEY:-}"
```

**Only those two Jellyfin names are in the compose file today** (`docker-compose.yml:39-40`).
`TV_STREAMING_AVAILABILITY_API_KEY` is **Phase 3 (T55)** and is deliberately *not* passed yet: it is
declared in `.env.example` so the shape is settled, but no `Settings` field reads it until the
launcher client that needs it exists, and a variable passed into a container nothing reads is a stub
in a file that should only carry live wiring. It joins the block above with T55:

```yaml
      TV_STREAMING_AVAILABILITY_API_KEY: "${TV_STREAMING_AVAILABILITY_API_KEY:-}"   # T55, not yet in the file
```

**The backend takes no `depends_on` edge to `jellyfin` — deliberately.** Jellyfin is an *optional
peer*, not a dependency: the workbook app must boot, serve every existing endpoint and pass its own
healthcheck when Jellyfin is stopped, absent or still scanning, exactly as it boots without provider
credentials. A `depends_on: condition: service_healthy` edge would make the nineteen workbooks
unreachable because a media server is down, which inverts the project's priorities. The Jellyfin
client (T48) therefore treats an unreachable base URL as "availability unknown" — every entry reports
`not_in_library` with a visible "Jellyfin unreachable" notice, in the same surface-it-as-data spirit as
`unreadable` and `shadowed` — and the compose-level assertion in gate 10.3 is precisely "the backend
boots and serves when `jellyfin` is stopped". `frontend` keeps its `depends_on: backend` edge and
gains none to `jellyfin`; the `<video>` source is the backend's same-origin proxy, so nginx never
declares a Jellyfin upstream and the CSP needs no `media-src`.

Hard rules, now that the change has landed:

- **Host port `5525`, bound to `127.0.0.1`.** Allocated from the documented containerized-Postgres range
  (`5433`, `5520-5591`) in `C:/Users/Amram/IMPORTANT/Projects/PORT_ASSIGNMENTS.md`. It continues
  the contiguous `5520 → 5524` run and keeps the two `Personal/*` projects adjacent
  (`Torah_Learning_Sidra` holds `5524`). Verified free across every `docker-compose*.yml`, `.env*`,
  `*.config.ts`, `run_*.{sh,bat}` and `config.py` under `Projects/`, `Personal/` and
  `side_projects/`. **`5525` is the only new host port Phase 1 allocates**, and the Postgres
  service is Phase 1's only new listener. Phase 3's one extra port, **`8096`** for `jellyfin`, was
  bound and registered in `PORT_ASSIGNMENTS.md` (map row and inventory bullet) with the T47a change
  on 2026-09-20. The earlier "only host port across all three phases" claim is
  superseded by ADR-014; the project's allocated set is `5525` and `8096`.
- **The Jellyfin healthcheck probes `GET /health` on the container's own `8096`.** The probe tool
  (`curl` above) is what T47a shipped against the `jellyfin/jellyfin:12.1` image and is swapped for
  `wget --spider` if a rebuild shows the image lacks it; the endpoint is the decision, the binary is not.
- **Never bind host `5432`, and never widen the bind address.** The container's internal `5432` maps
  to `127.0.0.1:5525` on the host. Host `5432` is the machine's single shared PostgreSQL listener and
  is used only by projects that connect to it as clients with distinct database names. Dropping the
  `127.0.0.1:` prefix to "make it reachable" publishes `tv`/`tv` on every interface (Ruling 24).
- **The registry is updated — T11, 2026-09-20.**
  `C:/Users/Amram/IMPORTANT/Projects/PORT_ASSIGNMENTS.md` carries the
  `5525 | Personal/TV | Postgres 16` row in the Final Host Listener Map (`:96`, quoting the
  loopback-bound mapping), the inventory entry under `### Personal/TV (watch-order app)`
  (`:481-485`), and the database-name line (`:469-470`) now reading **`tv` (app), `tv_test` (CI
  service container and local tests)** where it used to say the workbooks are the store. One port,
  two database names. Global Definition of Done item 13, satisfied.
- **Migrations run before the server.** `app/backend/docker-entrypoint.sh` runs
  `alembic upgrade head` and then `exec uvicorn`; the image's `CMD` is that script, not uvicorn
  (section 6.3). `depends_on: condition: service_healthy` is what makes that safe; a bare
  `depends_on` list is not sufficient and is forbidden by the global contract. A migration that keeps
  failing is a crash loop by design — do not soften it.
- **One connection string in the project.** Alembic runs on the same `postgresql+asyncpg://` URL as
  the app (`Settings.database_url`, see section 8). No sync driver is installed and no
  `sqlalchemy.url` is ever committed into `alembic.ini`.
- **The bind mount stays.** `${TV_LIBRARY_HOST:-.}:/library` is not replaced by the database. The
  workbooks remain authoritative for order and hand curation; Postgres is the projection.
- **The healthcheck's `CMD-SHELL` form is required**, because `pg_isready -U ${...}` needs shell
  substitution. The backend's existing healthcheck stays exec-form and keeps hitting
  `/openapi.json` — it must not be changed to a route that touches Postgres, or a database blip
  would mark the whole API unhealthy and take the frontend down with it.
- Chat still 503s in containers after Phase 1. Nothing in the ingest path needs the CLI.

</containerization>

---

<ci_cd>

## 7. CI/CD

This is a **public** repository, so CI is **GitHub Actions**. There is no `.gitlab-ci.yml` and there
must not be one. Two workflows exist:

- `.github/workflows/ci.yml` (462 lines) — the six-stage pipeline.
- `.github/workflows/codeql.yml` (57 lines) — GitHub's own analysis, deliberately **outside**
  `ci.yml`'s `needs:` graph. It gates nothing; it reports into Security → Code scanning alongside
  Semgrep, and the two find different things (`codeql.yml:1-2`).

### 7.1 The pipeline as it exists today

`ci.yml:19-23` triggers on `push: branches: [main]`, `pull_request:` (all branches), and
`workflow_dispatch:`. `:25-27` sets
`concurrency: { group: ci-${{ github.workflow }}-${{ github.ref }}, cancel-in-progress: true }`.
`:29-30` sets a workflow-level `permissions: contents: read`.

```
lint-backend  ─┐
lint-frontend ─┼─→ sast-semgrep ─┐
               ├─→ sast-audit   ─┼─→ sast ─┬─→ test-backend  ─┐
               └─→ sast-secrets ─┘         ├─→ test-frontend ─┼─→ coverage-gate → build → docker-build (matrix)
                                           └─→ test-layout   (leaf — nothing needs it)
```

| Stage | Job | Lines | What runs |
|---|---|---|---|
| lint | `lint / backend` | 49-66 | `uv sync --frozen --group dev` (`:62`), `uv run ruff check .` (`:64`), `uv run ruff format --check .` (`:66`), `working-directory: app/backend` (`:52-54`) |
| lint | `lint / frontend` | 68-89 | `pnpm install --frozen-lockfile` (`:85`), `pnpm lint` (`:87`), `pnpm exec tsc -b` (`:89`) |
| sast | `sast / semgrep` | 94-138 | `docker run --rm -v "$PWD:/src" -w /src semgrep/semgrep semgrep scan` with `--config p/default p/owasp-top-ten p/python p/typescript p/react p/docker --severity ERROR --error --metrics=off --sarif --output /src/semgrep.sarif` (`:121-131`), then `github/codeql-action/upload-sarif` with `category: semgrep`, `if: ${{ !cancelled() }}` (`:132-138`). `permissions: security-events: write` (`:98-100`) |
| sast | `sast / dependency audit` | 140-166 | `uv export --frozen --no-dev --no-emit-project --format requirements-txt --output-file requirements-audit.txt` (`:152`), `uvx pip-audit -r requirements-audit.txt --disable-pip` (`:156`), `pnpm audit --audit-level=high` (`:166`) |
| sast | `sast / secrets` | 168-179 | `docker run --rm -v "$PWD:/src" ghcr.io/gitleaks/gitleaks:latest detect --source /src --no-git --redact` (`:178-179`) |
| sast | `sast` (aggregator) | 181-187 | one `echo`; exists so the three test jobs depend on one name instead of three |
| test | `test / backend` | 192-256 | A **real Postgres 16 service container** (`:205-218` — `postgres:16-alpine`, `tv_test`, published `5525:5432`, `--health-cmd pg_isready`) and the job env that points at it (`:219-227`, including `TV_REQUIRE_POSTGRES: "1"`); then an **Alembic round trip** (`:236-238`) and `uv run pytest --cov=src --cov-report=xml --cov-report=term --junitxml=junit-backend.xml` (`:242`) |
| test | `test / frontend` | 258-304 | `pnpm test -- --reporter=default --reporter=junit --outputFile.junit=junit-frontend.xml --coverage --coverage.reporter=text-summary --coverage.reporter=json-summary` (`:283-290`) |
| test | `test / layout guard` | 306-346 | `pnpm exec playwright install --with-deps chromium` (`:332`), `pnpm exec playwright test --config layout/playwright.config.ts --reporter=list,junit` with `PLAYWRIGHT_JUNIT_OUTPUT_NAME: junit-layout.xml` (`:336-338`) |
| coverage gate | `coverage-gate` | 351-400 | downloads both coverage artifacts, then an inline `python3` heredoc compares them against five floors and `sys.exit(1)` on any shortfall |
| build | `build` | 405-433 | `uv build` (`:415-417`), `pnpm install --frozen-lockfile` + `pnpm build` (`:426-431`), `docker compose config --quiet` (`:432-433`) |
| docker-build | `docker-build / ${{ matrix.service }}` | 438-462 | matrix `[backend, frontend]`, `fail-fast: false`; `docker build -t tv-watchlist-<svc>:ci app/<svc>` (`:448-449`), then `aquasec/trivy:latest image --severity HIGH,CRITICAL --ignore-unfixed --scanners vuln --exit-code 1` (`:450-462`) |

**`uv build` in the `build` stage is a compile check, not a release step.** Nothing consumes the
wheel: the image installs the dependencies and copies `src/` (section 6.3), and the launchers run
`uv run uvicorn` out of the working tree. The stage exists to prove the package still builds. One
consequence has already bitten and is worth stating: `app/backend/data/franchise_prefixes.json` —
the resolver's seed — sits **outside** the package, per the project skeleton (Ruling 22), and
`[tool.hatch.build.targets.wheel] packages = ["src/tv_watchlist"]` therefore leaves it out of the
wheel. It reaches the image only through the Dockerfile's `COPY data ./data`. A green `uv build`
says nothing about whether that file will be there at runtime; the `docker-build` stage is what
covers it, and the file has to be staged in the same commit as the Dockerfile or a fresh-clone build
fails on `resolver/franchise.py`.

Every `uses:` is pinned to a **40-character commit SHA** with the release in the trailing comment
(`ci.yml:1-15`): `actions/checkout@11d5960a…` v4.4.0, `astral-sh/setup-uv@d0cc045d…` v6.8.0,
`pnpm/action-setup@b906affc…` v4.3.0, `actions/setup-node@49933ea5…` v4.4.0,
`github/codeql-action/*@6f5948df…` v3.37.9, `dorny/test-reporter@3eeb9fc8…` v1,
`actions/upload-artifact@ea165f8d…` v4.6.2, `actions/download-artifact@d3f86a10…` v4.3.0. A tag is
mutable, and Semgrep's `github-actions-mutable-action-tag` rule fails the `sast` stage on any tag
reference. **Adding an unpinned `uses:` breaks the build; that is the intended behaviour.** The
scanners are the deliberate exception and run from `:latest` images, because pinning a scanner
freezes its rule set and vulnerability database.

**There is deliberately no `dependabot.yml`** (`README.md`, Continuous integration). It opened
eleven PRs in its first hour across five ecosystems. Dependabot *security* alerts are a repository
setting rather than a file, so they keep working. The cost of that decision is that the SHAs above
are bumped by hand.

**There is no release/semver workflow.** `.github/workflows/` contains only `ci.yml` and
`codeql.yml`, so nothing bumps `app/backend/pyproject.toml:3` or `app/frontend/package.json:4` —
both at `0.1.0`. The same number appears a third time as the `version="0.1.0"` argument to `FastAPI`
(`app/backend/src/tv_watchlist/main.py:24-27`), where it becomes the OpenAPI document's version —
**kept in step by the release pipeline, not hand-edited by a session.** Until a manually-triggered
release workflow with a `BUMP` variable exists, **never edit any of the three**; document the
computed next version in `docs/versions.md` and stop there.

### 7.2 JUnit — the concrete requirement, met by all three test jobs

Every test job produces a **uniquely named** JUnit XML file and publishes it through
`dorny/test-reporter`. This is non-negotiable and it is already correct — do not regress it.

| Job | XML produced by | Report path | Publisher step |
|---|---|---|---|
| `test-backend` | `--junitxml=junit-backend.xml` appended to the pytest command (`ci.yml:242`); pytest's default `junit_family=xunit2` is correct and must not be downgraded to `legacy` | `app/backend/junit-backend.xml` | `ci.yml:243-249` |
| `test-frontend` | `--reporter=junit --outputFile.junit=junit-frontend.xml` (`ci.yml:286-287`) kept **alongside** `--reporter=default` (`:285`), so the console log survives; a junit-only reporter loses the human-readable output (`:282`) | `app/frontend/junit-frontend.xml` | `ci.yml:291-297` |
| `test-layout` | `--reporter=list,junit` with `env: PLAYWRIGHT_JUNIT_OUTPUT_NAME: junit-layout.xml` (`ci.yml:336-338`); invoked through `pnpm exec` because `pnpm run test:layout -- …` does not forward the extra reporter flags (`:334-335`) | `app/frontend/layout/junit-layout.xml` — Playwright resolves the JUnit filename against the **config's** directory, not the cwd (`:344`) | `ci.yml:339-346` |

Every publisher step is identical in shape and every part of it is load-bearing:

```yaml
      - name: Publish test report
        uses: dorny/test-reporter@3eeb9fc888e82e8be2fb356bbeec2750231672bc # v1
        if: ${{ !cancelled() }}
        with:
          name: backend tests          # the Check Run title in the UI; unique per job
          path: app/backend/junit-backend.xml
          reporter: java-junit
```

- `reporter: java-junit` is correct for **both** pytest's xunit2 output and Vitest's/Playwright's
  JUnit output — all three emit standard JUnit XML.
- `if: ${{ !cancelled() }}`, **not** `always()`: the report publishes whether tests pass or fail, but
  a cancelled run stays clean. The test `run:` step needs no special flag — a failing test fails the
  step and the reporter step still runs because of the `if:`.
- Each job declares `permissions: contents: read` / `checks: write` / `pull-requests: write`
  (`ci.yml:196-199`, `:262-265`, `:310-313`). **`checks: write` is what the action needs to create
  its Check Run**; without it the step fails with a permissions error, not a missing report.
- `dorny/test-reporter` is the fleet standard. Do not substitute
  `EnricoMi/publish-unit-test-result-action` or `mikepenz/action-junit-report`.
- Report filenames are unique per job so a multi-job run never clobbers a single file. **Any new
  test job must add its own `junit-<job>.xml` and its own reporter step with a distinct `name:`.**

### 7.3 Coverage threshold and how it is enforced

The gate is **not** 100%. Five floors are declared as workflow-level `env` (`ci.yml:39-43`):

| Variable | Line | Floor | Subject |
|---|---|---|---|
| `BACKEND_MIN_LINES` | 39 | **97** | backend line coverage |
| `FRONTEND_MIN_LINES` | 40 | **56** | frontend lines |
| `FRONTEND_MIN_STATEMENTS` | 41 | **54** | frontend statements |
| `FRONTEND_MIN_FUNCTIONS` | 42 | **45** | frontend functions |
| `FRONTEND_MIN_BRANCHES` | 43 | **45** | frontend branches |

Enforcement path: `test-backend` uploads `app/backend/coverage.xml` as artifact `coverage-backend`
(`ci.yml:250-256`); `test-frontend` uploads `app/frontend/coverage/coverage-summary.json` as
`coverage-frontend` (`:298-304`); both with `if: ${{ !cancelled() }}` and `retention-days: 7`.
`coverage-gate` (`:351-400`) downloads both and runs an inline `python3 - <<'PY'` heredoc that
parses the root `line-rate` attribute of `coverage.xml` × 100 (`:378-380`) and the `["total"]` block
of `coverage-summary.json` (`:382-391`), prints an `ok`/`LOW` table per metric, and exits 1 with
`"Coverage regressed:"` and `"Add tests. Do not lower the floor."` (`:394-398`). The job checks out
no source and installs no Python — it relies on the runner's `python3` and the two artifacts.

The floors are **measured, not aspirational** (`ci.yml:35-38`): the backend currently covers 8489 of 8592
lines; the frontend figures are what the Vitest suite alone reaches, because most components are
exercised by the Playwright layout guard in a real browser and that produces **no coverage data at
all**. The gate ratchets. **Raising a floor is a separate change; lowering one is a regression and
this gate exists to say so.** Fix a shortfall with tests, never by editing `ci.yml:39-43`.

There is **no local threshold**: `app/frontend/vitest.config.ts:10-17` declares no `thresholds`
block and `app/backend/pyproject.toml:46-52` sets no `--cov-fail-under`. The floors live only in CI.

### 7.4 Gaps against the required stage list — named, with what closes each

All six required stages exist, in the required order, and every required scanner is present. What
deviates:

1. **ESLint carries no security plugins.** `app/frontend/eslint.config.js` (20 lines) is
   `js.configs.recommended` + `tseslint.configs.recommended` + `react-hooks` + `react-refresh`,
   with `"@typescript-eslint/no-explicit-any": "error"` (`:17`) and
   `"react-refresh/only-export-components": ["warn", …]` (`:16`). **`eslint-plugin-security`,
   `eslint-plugin-no-unsanitized` and `react/no-danger` are all absent**, and `pnpm lint` is bare
   `eslint .` with **no `--max-warnings 0`** (`package.json:11`), so a warning does not fail the
   job. Closing it means: add both plugins, set their rules to `error` explicitly (the
   `recommended` config of `eslint-plugin-security` sets everything to `warn`, so a bare
   `eslint .` reports them and still exits 0), add `--max-warnings 0`, and expect to triage
   `security/detect-object-injection` with written suppressions.
2. **Semgrep does not use `--config auto`** and gates only on `--severity ERROR` (`ci.yml:121-128`).
   Both are deliberate and reasoned in-file (`:109-119`): `auto` took this pipeline from 0 findings
   to 41 in under an hour, none of them about this app's code, because the registry can introduce
   whole new rule categories between runs. WARNING and INFO findings still reach the Security tab
   through the SARIF upload; they just do not block. **Keep the six named packs.**
3. **Trivy runs with `--ignore-unfixed`** (`ci.yml:431`), a documented softening: a slim base image
   always carries distribution CVEs with no fix available, and failing on those makes the gate noise
   instead of signal (`:423-426`).
4. **`test-layout` is a dangling leaf.** `coverage-gate` needs only `[test-backend, test-frontend]`,
   so a layout-guard failure marks the run failed but does not stop `coverage-gate`,
   `build` or `docker-build`. If the layout guard is to be a real gate, `coverage-gate` (or `build`)
   must add it to `needs:`.
5. **No release workflow**, as above.
6. **`README.md`'s CI table used to be stale on one line**, describing the sast stage as
   "Semgrep (`auto` + OWASP/python/typescript/react/docker rulesets…)" while `ci.yml:122-127` names
   six packs starting at `p/default` and never uses `auto`. T01c corrected the README. If the two
   ever diverge again, fix the README, not the pipeline.
7. **No deploy stage.** Correct — deploy stages are added post-MVP.

### 7.5 What Phase 1 has added to CI (T10, 2026-09-20)

- **A real Postgres 16 service container on `test-backend`** (`ci.yml:205-218`). The global rule
  forbids mocking the database; integration tests hit a real server. `services: postgres:` is
  `postgres:16-alpine` with `POSTGRES_DB: tv_test`, `POSTGRES_USER: tv`, `POSTGRES_PASSWORD: tv`
  (`:208-211`), published `5525:5432` (`:212-213`) **so the job's env matches the compose file and a
  workstation run byte for byte**, and `options: --health-cmd "pg_isready -U tv -d tv_test"
  --health-interval 10s --health-timeout 5s --health-retries 5` (`:214-218`). The job env
  (`:219-227`) points `TV_POSTGRES_HOST` at `localhost` and the other four at that container.
  `pytest-asyncio` is already `asyncio_mode = "auto"` (`app/backend/pyproject.toml`); the fixture is
  `db_session` in `tests/conftest.py` — one connection, an outer transaction that is **always** rolled
  back, `join_transaction_mode="create_savepoint"`, `expire_on_commit=False`.
- **`TV_REQUIRE_POSTGRES: "1"` (`ci.yml:227`) — the escape hatch, closed in CI.** The `tests/data/`
  suite skips itself when nothing answers on the configured host, which is right on a workstation
  with no Postgres and wrong on a runner: a mis-wired service container would turn eleven tables'
  worth of tests into silence. With the variable set the skip becomes a **failure**. Never set it
  locally to "fix" a skip, and never unset it in CI to get a green run.
- **A migration round-trip check runs before pytest** (`ci.yml:236-238`):
  `uv run alembic upgrade head && uv run alembic downgrade base && uv run alembic upgrade head`,
  against that service container, because views must drop before their tables and the append-only
  trigger before `watch_event` — autogenerate orders neither correctly, so `downgrade` is
  hand-written and has to be exercised. `tests/data/test_migration_round_trip.py` asserts the same
  thing in-process, including `alembic check` parity, and
  `tests/database_support.py` guards the throwaway database it uses: `require_disposable_database`
  refuses any name that does not end `_test` before a `DROP DATABASE … WITH (FORCE)` ever runs.
- **New dependencies entered the audit surface.** `sqlalchemy[asyncio]`, `asyncpg` and `alembic`
  (and `greenlet` transitively — do not pin it separately) are picked up by `uv export` →
  `uvx pip-audit` with no change to the job.
- **Ruff's `S608` finally has something to check.** Every query in the Phase 1 code uses
  SQLAlchemy 2.0 constructs or `text()` with `:named` bind parameters; there is no string-built SQL
  anywhere in it, and `S608` is already selected (`app/backend/pyproject.toml:41`).
- **Secrets stay out of the repo.** `TV_TMDB_READ_ACCESS_TOKEN`, `TV_TVDB_API_KEY`, `TV_TVDB_PIN`
  and `TV_POSTGRES_PASSWORD` are GitHub Actions secrets, never committed — those exact names, since
  `env_prefix="TV_"` derives every one of them mechanically from its `Settings` field. `gitleaks`
  (`ci.yml:178-179`) fails the build if one lands in the tree, and `.gitignore:30-32` already ignores
  `.env` / `.env.*` while whitelisting `!.env.example`.
- **If ingest tests become their own job, they get their own `junit-ingest.xml` and their own
  reporter step.** No job may reuse another's report filename.

</ci_cd>

---

<environment>

## 8. Environment configuration

### 8.1 The root `.env` is owner-typed and gitignored; only `.env.example` is committed

The root `.env` **exists** — created 2026-09-15 at the owner's explicit request as a placeholder
template, with the values typed in by the owner and **never read or written by an agent**. It is
gitignored and stays that way. **`.env.example` now exists too** (T01b, grown to 23 `TV_` variables
by T48/T60): each variable has a safe placeholder and a one-line comment, kept in step with `Settings`
by `app/backend/tests/test_env_example.py` and its `tests/env_example_support.py` parser, plus
`test_config.py` and the new `test_import_settings.py` (T60) — 64 test cases together as of T60.
The guard derives the expected names from `Settings.model_fields` and tolerates exactly two declared
lists — `DECLARED_EXCLUSIONS` (the five path/backup knobs above, universal defaults, never typed) and
`DECLARED_EXTRAS` (the compose-only names and the one Phase 3 stub, `TV_STREAMING_AVAILABILITY_API_KEY`)
— so an undeclared drift in either direction fails (Ruling 57). There is no other `.env.*` anywhere in the tree. `.gitignore:30-32` carries `.env`, `.env.*`, and the
negation `!.env.example`, so the example is the one such file that is committed — and the one such
file `scripts/hooks/pre-tool-use.cjs` allows an agent to write.

`app/backend/src/tv_watchlist/config.py:24` declares
`SettingsConfigDict(env_prefix="TV_", env_file=REPO_ROOT / ".env", extra="ignore")`. **The path is
absolute, and that is the T05 fix (2026-09-20):** `REPO_ROOT` is `Path(__file__).resolve().parents[4]`
(`config.py:17`), computed the same way `library_dir` is, so the backend finds the repository-root
`.env` whichever directory it was started from — which matters because `run_tv.sh` starts it from
`app/backend`. An earlier draft of this section described a bare `env_file=".env"` resolved against
the process working directory; that is no longer what the code says. Section 8.3 carries the same
statement from the `.env` side, and the two now agree. Under Docker nothing changes: `REPO_ROOT`
resolves to `/srv`, no `.env` exists there, and compose passes every variable through
`environment:`.

**Every field on `Settings` is read with the `TV_` prefix.** That is a hard consequence of
`config.py:24` and it governs the naming of every variable this project will ever add: a field named
`tmdb_read_access_token` is set by `TV_TMDB_READ_ACCESS_TOKEN`, not `TMDB_API_READ_ACCESS_TOKEN`.
Do not add a bare-named variable and reach for `os.environ` to read it — that fragments
configuration across two mechanisms.

### 8.2 Every environment variable the project reads today

| Variable | Field / consumer | Default | Declared / read at | Also set at |
|---|---|---|---|---|
| `TV_LIBRARY_DIR` | `Settings.library_dir: Path` | `REPO_ROOT` = `Path(__file__).resolve().parents[4]` → the repo root | `config.py:26` | `docker-compose.yml:28`, `app/backend/Dockerfile:95` (`/library`) |
| `TV_BACKEND_PORT` | `Settings.backend_port: int`, `ge=1, le=65535` | `8284` | `config.py:27` | `run_tv.sh:6`, `run_tv.bat:13`, `app/frontend/vite.config.ts:6`, `docker-compose.yml:32,54`, `Dockerfile:98` |
| `TV_FRONTEND_PORT` | `Settings.frontend_port: int`, `ge=1, le=65535` | `5284` | `config.py:28` | `run_tv.sh:7`, `run_tv.bat:14`, `vite.config.ts:7`, `docker-compose.yml:35,80`, `Dockerfile:99` |
| `TV_BACKUP_DIR` | `Settings.backup_dir: Path` | `APP_DIR / ".backups"` → `app/.backups` | `config.py:29` | `docker-compose.yml:30`, `Dockerfile:97` |
| `TV_BACKUP_RETENTION` | `Settings.backup_retention: int`, `ge=1` | `BACKUP_RETENTION` = `10` (`constants.py:57`) | `config.py:30` | — (prefix only) |
| `TV_BACKUP_INTERVAL_SECONDS` | `Settings.backup_interval_seconds: float`, `ge=0` | `BACKUP_INTERVAL_SECONDS` = `900.0` (`constants.py:58`) | `config.py:31` | — (prefix only) |
| `TV_HEROES_DIR` | `Settings.heroes_dir: Path` | `APP_DIR / "heroes"` → `app/heroes` | `config.py:32` | `docker-compose.yml:29`, `Dockerfile:96` |
| `TV_LIBRARY_HOST` | compose bind-mount source only | `.` (repo root) | `docker-compose.yml:52` | — |
| `TV_POSTGRES_HOST` / `_PORT` / `_DB` / `_USER` / `_PASSWORD` | `Settings.postgres_*` (section 8.3) | `localhost` / `5525` / `tv` / `tv` / `tv` | `config.py:35-39` | `docker-compose.yml:43-47` (the backend container: `postgres` and `5432`), `:97-99` (the server itself), `run_tv.sh:8`, `ci.yml:220-224` (`tv_test`) |
| `TV_LAYOUT_PORT` | layout-guard probe server only | `5286` | `app/frontend/layout/probeServer.ts:4` (`DEFAULT_PORT = 5286` at `:1`) | — |
| `PLAYWRIGHT_BROWSERS_PATH` | Chromium preflight check | unset → per-OS cache path | `agent/preflight.py:12`, read at `:34` | — |
| `LOCALAPPDATA` | Windows Playwright cache path | OS-provided | `agent/preflight.py:38` | — |
| `PYTHONUNBUFFERED` | uvicorn's access log through a pipe | — | set to `1` at `run_tv.bat:64`, `Dockerfile:89` | — |
| `TV_REQUIRE_POSTGRES` | `tests/database_support.py` only — turns the data suite's skip into a failure | unset | `ci.yml:227` (`"1"`) | — (CI only; never set it locally) |
| `CI` | disables Vite's TTY key handling under `start /b` | — | set to `1` at `run_tv.bat:65` | — |
| `TVWL_SVC` | marker matched literally by `:shutdown` | — | set at `run_tv.bat:64-65`, matched at `:115` | — |
| `PLAYWRIGHT_JUNIT_OUTPUT_NAME` | Playwright JUnit filename | — | `ci.yml:309` | — |

**`.env.example` now lists 23 `TV_` variables, up from 16** — the seven Phase 0 names above, the
five Postgres names (live since T05, and in the table above), `TV_TMDB_READ_ACCESS_TOKEN` /
`TV_TVDB_API_KEY` / `TV_TVDB_PIN` (live since T13/T14), the four Jellyfin names, and — since **T60**
— six Phase 3.5 names plus one compose-only name for the import pipeline (`TV_QBITTORRENT_URL`,
`TV_QBITTORRENT_USER`, `TV_QBITTORRENT_PASSWORD`, `TV_IMPORT_STAGING_DIR`, `TV_MEDIA_ROOT`,
`TV_IMPORT_CONCURRENCY`, `TV_IMPORT_STAGING_HOST`). **The two Jellyfin `Settings` fields are live as
of T48** — `jellyfin_base_url` and `jellyfin_api_key` are real fields now, not stubs; see section 8.3
for both, plus the new qBittorrent/import block T60 added. **The only name left that no `Settings`
field reads is `TV_STREAMING_AVAILABILITY_API_KEY`** — `streaming_availability_api_key` lands at
**T55** (Ruling 12) — so `extra="ignore"` (`config.py:17`) drops just that one until then. A variable
being present in the environment is not the same as the app reading it — see section 8.3.

Where each `Settings` value is actually consumed:

- `library_dir` → `Catalog.library_dir` (`services/catalog.py:39-41`), used by
  `discovery.workbook_paths` / `resolve`, `creator.create_category` (`catalog.py:206-210`), and as
  the agent subprocess's `cwd` (`agent/options.py:21-35`, the `cwd=library_dir` argument at `:32`).
- `backend_port` is **never read by application code** — only the launchers and compose publish it.
  `frontend_port` is read solely to build the CORS allowlist (`main.py:31-32`).
- `backup_dir` → `Catalog._snapshot` (`catalog.py:120`), `_carry_artwork` (`:186`), `_retire`
  (`:196`), `HeroStore._write` (`services/hero_store.py:92`).
- `backup_retention` → `catalog.py:120`. `backup_interval_seconds` → passed **only** by
  `Catalog.update_row` (`catalog.py:150`); every other write takes `backup.NO_THROTTLE`
  (`catalog.py:136`).
- `heroes_dir` → the `/heroes` `StaticFiles` mount (`main.py:43-44`), `Catalog._hero_url`
  (`catalog.py:91`), `_carry_artwork` (`:186-187`), `_retire` (`:196`), `HeroStore`
  (`hero_store.py:49`, `:84-86`).

CORS is built from `frontend_port` and nothing else (`main.py:28-36`):
`allow_origins=[f"http://localhost:{settings.frontend_port}", f"http://127.0.0.1:{settings.frontend_port}"]`,
`allow_methods=["GET", "POST", "PATCH", "DELETE"]`, `allow_headers=["Content-Type"]` — **no
`allow_credentials`, no wildcard**. Under Docker the browser talks to nginx same-origin, so this
matters only when a browser is pointed straight at the published backend port
(`docker-compose.yml:30-31`).

`agent/options.py:34` passes `env={}` into `ClaudeAgentOptions`, so the spawned `claude` subprocess
inherits **no** environment through that channel, and `setting_sources=[]` (`options.py:27`) means
the machine's own Claude configuration is not inherited either.

### 8.3 The Postgres and provider settings (live), and the one Phase 3 stub left (not)

The split matters, so it is stated before the tables: **the five Postgres fields, the three metadata
provider credentials, the two Jellyfin fields (live since T48) and the six Phase 3.5 import/qBittorrent
fields (live since T60) are all real `Settings` fields, read by real code**
(`config.py:35-44` and the two blocks T48/T60 appended after them). **`TV_STREAMING_AVAILABILITY_API_KEY`
is the one name left that is still a stub** — declared in `.env.example` with **no `Settings` field
reading it** until **T55**. A variable being present in the environment is not the same as the app
reading it.

**Postgres connection** (on the `Settings` class, `config.py:35-39`):

| Variable | Field | Default | Notes |
|---|---|---|---|
| `TV_POSTGRES_HOST` | `postgres_host: str` | `localhost` | `postgres` under compose |
| `TV_POSTGRES_PORT` | `postgres_port: int`, `ge=1, le=65535` | `5525` | the **host** port, and only that. Compose overrides it to `"5432"` for the backend container (`docker-compose.yml:44`), because inside the network the backend reaches the service by name on the container's own port and never goes through the host publication — which is itself bound to `127.0.0.1` only (`:108`, Ruling 24). `5525` is what the *launcher* path and a local `pytest` use |
| `TV_POSTGRES_DB` | `postgres_db: str` | `tv` | **`tv`**, and the test database is **`tv_test`**. `tv_watchlist` is the Python package name and the compose project/image prefix; it is **not** a database name and must not appear as one |
| `TV_POSTGRES_USER` | `postgres_user: str` | `tv` | |
| `TV_POSTGRES_PASSWORD` | `postgres_password: SecretStr` | `SecretStr("tv")` | **`SecretStr`, not `str`** — a plain string renders into every log line and traceback that touches `Settings` |

The DSN is a computed property, never an environment variable of its own:

```python
    @property
    def database_url(self) -> str:
        """SQLAlchemy async URL. The password is only rendered here, never logged."""
        # URL.create escapes each component itself, so hand-quoting would double-encode it; building the
        # string by hand is what lets a `@`, `/`, `:` or `%` in a credential split the URL.
        return URL.create(
            drivername="postgresql+asyncpg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        ).render_as_string(hide_password=False)
```

`URL.create` (`from sqlalchemy.engine import URL`) does the escaping, and it replaced a `quote_plus`
call that was wrong: `quote_plus` is the query-string encoder, so it turns a space into `+`, which
SQLAlchemy's own URL parser does not turn back — a credential containing a space was silently
mis-sent (Ruling 14, 2026-09-20). Alembic reads the same property through `env.py` — **`sqlalchemy.url`
is never written into `alembic.ini`**, and a `%` in a password must be doubled when it is injected
there, because `alembic.ini` is ConfigParser syntax.

**Metadata provider credentials:**

| Variable | Field | Default | Notes |
|---|---|---|---|
| `TV_TMDB_READ_ACCESS_TOKEN` | `tmdb_read_access_token: SecretStr \| None` | `None` | The **v4 API Read Access Token**, sent as `Authorization: Bearer …` against the `/3` base URL. That is TMDB's documented default and it keeps the credential out of request URLs, proxy logs and browser history. Do **not** use the v3 `api_key` query parameter, and never ship either credential to the browser bundle — every TMDB call is proxied by the backend. |
| `TV_TVDB_API_KEY` | `tvdb_api_key: SecretStr \| None` | `None` | TheTVDB **v4** key — the one created under the dashboard's API keys with the End-User Subscriptions model. **Not** the "legacy" key that a TheTVDB user subscription also issues: TheTVDB's own FAQ (id 82) describes that as a legacy **v3** API key, and this project speaks only v4. `POST /v4/login` returns a bearer token valid for **one month**; there is no refresh endpoint, so the token is cached server-side with its issue time and re-fetched proactively at ~25 days, never reactively on a 401. |
| `TV_TVDB_PIN` | `tvdb_pin: SecretStr \| None` | `None` | **Required whenever the TheTVDB client runs.** This project uses an **"End-User Subscriptions"** key (decided in T03), the instant-approval funding model, so the subscriber PIN is sent as `pin` on every `POST /v4/login` and a login that omits it fails. The default stays `None` only so the app boots without provider credentials; the client refuses to start without it. The rejected "Negotiated Contract" model is the one whose login must have `pin` *removed* rather than sent empty — that shape is not used here. |

**Jellyfin — live since T48 (ADR-014).** `jellyfin_base_url` and `jellyfin_api_key` are real `Settings`
fields, not stubs. `jellyfin_base_url` carries a boot-time `field_validator`
(`_a_configured_base_must_be_one_the_guard_accepts`) that runs the same
`clients.http_guard.assert_within_configured_base` check the client itself uses, so a malformed value
(not `http(s)`, credentials embedded in the URL, unparseable) fails at **startup**, naming the
variable, rather than surfacing as a 503 at the first playback attempt. `None` stays a valid, fully
supported value — the disabled feature:

| Variable | Field | Default | Notes |
|---|---|---|---|
| `TV_JELLYFIN_BASE_URL` | `jellyfin_base_url: str \| None` | `None` | The Jellyfin origin the **backend** talks to. **`http://localhost:8096`** on the host launcher path, typed by the owner into the root `.env`; **`http://jellyfin:8096`** under compose, set explicitly in `backend`'s `environment:` (the compose service name, because both containers share the default bridge network and the backend never reaches Jellyfin through the host). `None` disables the client: every entry reports `not_in_library`, the player never renders, nothing crashes. Only the scheme, host and port are configuration — the paths (`/Items`, `/Videos/{id}/stream`, `/health`, `/Library/Refresh`) are constants in `clients/jellyfin_client.py`. This is the one allowlisted host the SSRF guard in section 10.3 (B16) accepts; it is **not** vetted by `agent/url_guard.assert_public_http_url`, which rejects private and loopback addresses by design. |
| `TV_JELLYFIN_API_KEY` | `jellyfin_api_key: SecretStr \| None` | `None` | **Created by the owner in Jellyfin's own UI** — Dashboard → API Keys → New, named `tv-app` — after the first-run admin account exists, and typed by the owner into the root `.env`. **No agent writes it, ever.** Sent as `Authorization: MediaBrowser Token="…"` (Jellyfin's header form) on every backend call, including the stream fetch the proxy makes; it never appears in a URL, a log line, the browser bundle or a `<video src>`. Section 10.3 B17 is the boundary that guards it. |
| `TV_JELLYFIN_PORT` | — (compose only) | `8096` | The **host** port compose publishes: `${TV_JELLYFIN_PORT:-8096}:8096`. No `Settings` field reads it — the backend reaches the container on its internal `8096` through the service name, and the host launchers reach it through `TV_JELLYFIN_BASE_URL`. Registered in `PORT_ASSIGNMENTS.md` at T47a. |
| `TV_JELLYFIN_MEDIA_HOST` | — (compose only) | `./media` | The host directory bind-mounted **read-only** at `/media` inside the Jellyfin container: `${TV_JELLYFIN_MEDIA_HOST:-./media}:/media:ro`. `/media/` at the repo root is gitignored (T47a) — the owner's files are never committed, exactly as `app/.backups/` is not. The backend never reads this variable directly; it never touches a media file, only Jellyfin's index of them — Phase 3.5's `media_root` (below) is the backend's own, separate view of the same directory. |

**The Streaming Availability launcher credential — the one name still a stub.**

| Variable | Field | Default | Notes |
|---|---|---|---|
| `TV_STREAMING_AVAILABILITY_API_KEY` | `streaming_availability_api_key: SecretStr \| None` | `None` | The ADR-012 launcher's credential for the Streaming Availability API (free plan: 1,000 requests a month, no payment details; the owner is signing up). Sent as a request header, never a query parameter. **T55 is blocked until the key is present in the root `.env`**; until then every `NOT_IN_LIBRARY` entry shows the launcher shell with no link, and a hand-marked Disney+ row still opens its `/browse/entity-…` page. The chat never sees this key or anything fetched with it (ADR-012 rule 7). |

**qBittorrent and the import pipeline — live since T60 (Phase 3.5, ADR-015).** Six new fields,
appended after the Jellyfin block. `qbittorrent_url` carries the **identical** boot-time
`field_validator` shape as `jellyfin_base_url` — same guard function, same failure mode, checking
shape only (an `http(s)` origin with no embedded credentials), never whether the host is actually
loopback or LAN. **No committed default names a personal directory** (Ruling 68): both path fields
default to `None`, exactly like a disabled provider credential, and the placeholders in `.env.example`
are generic (`/absolute/path/to/tv-import-staging`, `/absolute/path/to/tv-media-library`) rather than
the owner's real paths:

| Variable | Field | Default | Notes |
|---|---|---|---|
| `TV_QBITTORRENT_URL` | `qbittorrent_url: str \| None` | `None` | `http://localhost:8080` from the host launchers; compose supplies `http://host.docker.internal:8080` itself (T69). `None` disables the completed-torrents scan arm; the staging-folder arm still runs. |
| `TV_QBITTORRENT_USER` | `qbittorrent_user: str \| None` | `None` | qBittorrent WebUI login, if the owner has one configured. Optional even when a URL is set. |
| `TV_QBITTORRENT_PASSWORD` | `qbittorrent_password: SecretStr \| None` | `None` | Rendered only into the login request body, never logged. |
| `TV_IMPORT_STAGING_DIR` | `import_staging_dir: Path \| None` | `None` | Where completed downloads land before they are organised into the media library. `None` disables the staging-folder scan arm — the same degrade-don't-crash rule as a provider credential, never a boot failure. |
| `TV_MEDIA_ROOT` | `media_root: Path \| None` | `None` | The backend's **own** view of the media library directory — a field distinct from the compose-only `TV_JELLYFIN_MEDIA_HOST` above, mirroring the existing `TV_LIBRARY_HOST` (compose) / `TV_LIBRARY_DIR` (`Settings`) split. Compose sets it to `/media` (T69), read-write for this service; Jellyfin's own mount of the same host directory stays `:ro`. |
| `TV_IMPORT_CONCURRENCY` | `import_concurrency: int`, `ge=1, le=8` | `2` | How many files move at once during an import pass. |

`TV_IMPORT_STAGING_HOST` is **compose-only**, no `Settings` field, ever — the host-side name T69's
compose mount substitutes from, the same split `TV_LIBRARY_HOST`/`TV_LIBRARY_DIR` already makes
(Ruling 73). `.env.example`'s default for it is `./staging`.

Rules for all of them:

- **Absent credentials must degrade, not crash.** They are `… | None` so the app starts, serves
  every existing endpoint, and reports the ingest as unconfigured. A missing token is a disabled
  feature, not a boot failure.
- **The `.env` lives at the repository root — `C:\Users\Amram\IMPORTANT\Personal\TV\.env` — and nowhere else.**
  One file serves both consumers: `docker compose` auto-loads a root `.env` for variable
  substitution, and the backend's `Settings` reads the same file. **Fixed at T05 (2026-09-20).**
  `config.py:24` declares `env_file=REPO_ROOT / ".env"` — an absolute path, computed the same way
  `library_dir` is, never a cwd-relative string — so `run_tv.sh:61` starting the backend from
  `app/backend` no longer matters: the backend finds the repo-root `.env` regardless of its working
  directory. Under Docker nothing changes — `REPO_ROOT` resolves to `/srv`, no `.env` exists there,
  and compose passes the variables through `environment:` as below. The test suite never resolves
  the owner's real credentials through this path: an autouse session fixture, `declared_env_file`
  (`tests/conftest.py:21-30`), blanks `Settings.model_config["env_file"]` for the whole run and
  restores it afterward, so `get_settings()` inside a test process never reads the root `.env`. The
  root file was created 2026-09-15 **at the owner's explicit request, as a placeholder-only
  template**; the owner types the values, and no agent ever writes a credential into it.
- **`SecretStr` everywhere**, and never logged. The outbound-call log records the URL with any
  credential stripped, never the header.
- **`.env.example` exists (task T01b, done; grown to 23 names by T48/T60)**, listing every variable
  above with a safe placeholder and a one-line comment. `TV_STREAMING_AVAILABILITY_API_KEY` is the
  only name whose `Settings` field does not land until **T55**; every other name is live.
  `.gitignore:32` whitelists it via `!.env.example`; `:30-31` ignore the real `.env` and `.env.*`.
  `app/backend/tests/test_env_example.py` fails if the file and `Settings` drift.
- **Writes to `.env*` are blocked by the `PreToolUse` hook (`scripts/hooks/pre-tool-use.cjs`, task
  T01a, done).** It emits `{"decision":"block","reason":…}` for `.env*`, `credentials.*`,
  `secrets.*`, `*.pem`, `*.key` and `*.p12`, with **`.env.example` explicitly exempted** because it
  carries placeholders only — and it blocks a direct `Write`/`Edit` of any `*.xlsx` for the section
  3.4 reason. Real credentials are typed by the owner and never written by an agent; that is now a
  guard rather than discipline. `.gitignore:27` ignores `.claude/`, so the settings, commands and
  skills stay local while `scripts/hooks/` travels with the repo. The standing rule is unchanged:
  **never create or edit a real `.env` file here — hand it to the owner.**
- **Compose passes these through explicitly**, the same way it already does for `TV_LIBRARY_DIR` and
  friends. No `env_file:` — one mechanism, visible in the compose file.

</environment>

---

<observability>

## 9. Observability

### 9.1 What is captured today

**Errors reaching a client** go through one envelope, and only one. `api/errors.py:69-73`:

```python
def payload_for(error: Exception) -> dict[str, str]:
    """The `{error, message, detail}` envelope every refusal returns, whichever status carries it."""
    detail = str(error)
    template = _MESSAGE_BY_ERROR.get(type(error), "{detail}")
    return {"error": type(error).__name__, "message": template.format(detail=detail), "detail": detail}
```

`register(app)` (`errors.py:76-96`) attaches `_handle` to exactly three base classes —
`WorkbookError`, `AgentError`, `CLINotFoundError` (`errors.py:66`) — plus a dedicated handler for
openpyxl's `IllegalCharacterError` (`errors.py:79-89`), which is raised from bare `Exception` and
would otherwise be a 500. Status lookup in `_STATUS_BY_ERROR` (`errors.py:33-46`) is by **exact
type, never by MRO** (`errors.py:92`), so a subclass absent from the table falls through to `400`.
The frontend reads `body.error` as a machine-readable code — `ApiError.isStale`
(`src/api/ApiError.ts:12-14`) tests `code === "StaleWorkbookError"`, and that is what drives the
automatic re-read in `src/stores/writeFailure.ts:12-18`.

**Errors the SDK would swallow** are logged. `create_sdk_mcp_server` catches every handler
exception, so each of the three library tools is wrapped (`agent/handler_guard.py:15-25`): the
wrapper calls `_logger.exception("tool %s failed", tool_name)` and returns
`text_result(f"{type(error).__name__}: {error}", is_error=True)`. **That module is the only place a
tool failure is visible at all.**

**State that would otherwise be silently missing is surfaced as data, not logs.** This is the
project's dominant observability pattern and Phase 1 must extend it rather than replace it:

- `UnreadableWorkbook` (`models/unreadable_workbook.py:8-12`) — a file that would not parse, with
  `reason` populated as `f"{type(error).__name__}: {error}"` (`services/catalog.py:76`).
- `ShadowedWorkbook` (`models/shadowed_workbook.py:8-13`) — a file unreachable because a namesake
  already answers to its derived id, carrying `file_name`, `category_id` and `answered_by`.
- Both ride on `CatalogListing` (`models/catalog_listing.py:12-18`) and are rendered by the sidebar
  and the cards wall. A file that quietly vanished from the UI would be a bug; a file that appears
  in an "unreadable" block is a diagnosis.
- `CategorySummary.locked_by_excel` does the same for a workbook Excel is holding.

**Process-level signals:**

- uvicorn's access log is the only request log, on stdout. `PYTHONUNBUFFERED=1`
  (`app/backend/Dockerfile:78`, `run_tv.bat:64`) exists because Python block-buffers stdout once it
  is a pipe, so without it the lines arrive in bursts. `run_tv.bat:64-65` prefixes each server's
  output with a coloured `[backend]` / `[frontend]` tag so one console carries both.
- Container health is the compose healthcheck on `/openapi.json` (`docker-compose.yml:43-51`) and
  `wget --spider` on the frontend (`:66`).
- `agent/preflight.py` reports missing prerequisites **before** a chat is promised: `CLI_ADVICE` and
  `CHROMIUM_ADVICE` (`preflight.py:16-23`), printed by the launchers (`run_tv.sh:37-44`,
  `run_tv.bat:41-49`) and runnable standalone as `python -m tv_watchlist.agent.preflight`.
- CI surfaces per-test-case results through three JUnit reports and Semgrep findings through the
  SARIF upload into Security → Code scanning.

**What does not exist today, stated plainly:** no structured logging, no logging configuration at
all beyond Python's default, no request ids, no metrics, no tracing, no error aggregator, no
`/health` route. For a single-user local app that is the right amount — do not add Prometheus.

### 9.2 What Phase 1 needs

The ingest is the first thing in this project that runs **without a human watching it** and talks to
**someone else's server**. Three additions, and no more:

1. **Structured logging on the ingest jobs.** Key=value or JSON records, never interpolated prose,
   so a crafted title or overview cannot forge a log line (see the header/log-injection entry in
   section 10). One record per job start and end carrying: job name, `source` (`tmdb` / `tvdb`),
   the resource being ingested, counts of rows inserted / updated / unchanged / skipped, elapsed
   seconds, and the outcome. A run that changed nothing must log that it changed nothing — "no
   output" is indistinguishable from "did not run".
2. **A record of every outbound TMDB/TVDB call with its cache outcome.** `clients/transport.py`
   emits it — `log_call` writes one key=value line per request carrying method, host, the path with
   every credential stripped, HTTP status, elapsed milliseconds, bytes read, and the **cache
   outcome**. `CacheOutcome` has **five** members (`transport.py:19`): `fresh` (a real network fetch
   that changed something), `not-modified` (a 304, or a matching `payload_digest`), `cached` (served
   from `sync_state` without a request), `throttled` — **reserved for the token-bucket wait and a
   429 back-off, nothing else** — and `failed`. `failed` is Ruling 26 and it is the member that makes
   the log honest: a refusal (401, 404, 429), an outage or a body that would not validate produces
   *no* usable payload, and folding any of those into `throttled` or leaving them unlogged is how a
   silently-empty projection happens. The `changes` cursor key carries its own date window, so two
   windows are two rows in `sync_state` rather than one that keeps overwriting itself.
   This is not vanity instrumentation:
   - TMDB documents its limit as "somewhere in the 40 requests per second range" (docs updated
     2025-10-20), says it "could change at any time", and does not say whether it applies per IP or
     per key. An earlier draft of this file said ~50 per second with 20 connections per IP; that is
     not on TMDB's page. Throttle below 40 per second, honour every 429, and count the calls — the
     count is the only evidence the budget is being respected.
   - TheTVDB's rate limit is **undocumented**. Self-throttle conservatively, assume one exists and
     is enforced silently; the call log is the only evidence when it starts refusing.
   - TMDB's terms cap caching at **six months, hard**, so `fetched_at` and a scheduled refresh are a
     licensing requirement, not an optimisation. **Ruling 25 is the corner that cap creates:** when
     `sync_state.last_success_at` is `NULL` but a validator (an `etag` or a `payload_digest`) is
     present, the client **renews** rather than revalidating. An entry with a validator and no
     recorded success has an unknown age, and an unknown age cannot be trusted against a six-month
     ceiling — so a 304 is never taken on faith there.

   Never log a request header, never log an `Authorization` value, never log a full response body.
3. **`sync_state` makes a stale projection visible instead of silent.** The table
   (`data/models/sync_state.py`) is keyed `uq(source, resource_type, resource_key)` and carries
   `etag`, `last_modified`, `payload_digest`, `last_attempt_at`, `last_success_at`,
   `next_attempt_at`, `consecutive_failures` (with `CHECK >= 0`) and `last_error`, plus a partial
   index `ix_sync_state_due` on `next_attempt_at` where it is non-null. That shape is what turns
   three otherwise-invisible failure modes into answerable questions:
   - *"Is this episode list current?"* → `last_success_at`.
   - *"Is something failing quietly?"* → `consecutive_failures` and `last_error`, sorted worst-first.
   - *"Why did nothing change?"* → `payload_digest`. TMDB does not send `ETag` on every endpoint, so
     when it does not, the ingest hashes the normalised response body and skips the write path when
     the digest is unchanged. That is what keeps a nightly refresh across nineteen workbooks from
     rewriting every `episode` row and churning `updated_at` for nothing.

   **`sync_state` must be readable from the UI**, in the same spirit as `unreadable` and `shadowed`
   today: a category whose metadata last synced three weeks ago and has failed eleven times in a row
   should say so on screen, not require a `psql` session.

Two failure modes the ingest must never treat as data, both of which belong in the log **and** in
`sync_state.last_error`:

- **TheTVDB returns HTTP 200 with an empty `episodes` array for an unrecognised `season-type`**, not
  a 4xx. A zero-length episode list is `"unknown / do not mutate state"`, **never** `"this series
  has no episodes"`. The same shape has already destroyed real data elsewhere — a Jellyfin plugin
  treating an empty list as authoritative deleted 194 seasons per library scan.
  **Seven season types are live in production (measured against `GET /v4/seasons/types`, 2026-09-15) — `official`, `dvd`, `absolute`, `alternate`, `regional`, `altdvd`, `alttwo` — and TheTVDB's OpenAPI spec lists them as
  *examples*, not as an enum, so the list is not closed.** The operative rule follows from that:
  **read the season-type list at runtime from a cached `GET /v4/seasons/types` and never hard-code
  it.** Validate a `season_type` against that cached list before building a URL, and log a refusal
  rather than writing a deletion.
- **A partial fetch is indistinguishable from a sparse order** without following pagination to the
  last page. Log the page count and the total; a truncated ingest that reports success is worse than
  one that fails.

</observability>

---

<security>

## 10. Security

### 10.1 The SAST set wired into this pipeline

| Tool | Where | Gate |
|---|---|---|
| **Semgrep** | `ci.yml:103-138`, `sast / semgrep` | `--severity ERROR --error` over six named packs — `p/default`, `p/owasp-top-ten`, `p/python`, `p/typescript`, `p/react`, `p/docker`. SARIF uploaded to Security → Code scanning with `category: semgrep` (`:132-138`) |
| **ruff `S` (flake8-bandit)** | `app/backend/pyproject.toml:41` — `select = ["E", "F", "I", "N", "UP", "ANN", "S"]`, with `per-file-ignores` `"tests/*" = ["S101"]` (`:43-44`) | runs in the **lint** stage, before SAST: `subprocess(shell=True)`, `eval`/`exec`, `pickle`, `yaml.load`, hard-coded passwords, weak hashes and string-built SQL fail there first |
| **pip-audit** | `ci.yml:152-156` | `uv export --frozen --no-dev --no-emit-project` then `uvx pip-audit -r requirements-audit.txt --disable-pip` — the lockfile is the subject, so the project environment is never built |
| **pnpm audit** | `ci.yml:166` | `pnpm audit --audit-level=high`, reads `pnpm-lock.yaml` directly |
| **gitleaks** | `ci.yml:178-179` | `detect --source /src --no-git --redact` over the whole tree, every run |
| **Trivy** | `ci.yml:450-462`, inside `docker-build` | `image --severity HIGH,CRITICAL --ignore-unfixed --scanners vuln --exit-code 1` against each freshly built image |
| **CodeQL** | `.github/workflows/codeql.yml` | `security-and-quality` queries for `python` and `javascript-typescript`, on push, PR, and Mondays 04:17 UTC. Reports into the same Security tab; gates nothing |

`.semgrepignore` (44 lines) **replaces** Semgrep's built-in default ignore list, which is why the
usual suspects are repeated rather than assumed (`:1-5`): `node_modules/`, `.venv/`, `venv/`,
`.pnpm-store/`, build output and caches, **the library itself** (`*.xlsx`, `*.png`, `*.jpg`,
`*.jpeg`, `*.svg`, `*.webp`, `*.avif`, `*.gif`, `app/.backups/`), the two lockfiles, and `*.sarif`.

### 10.2 The exact local command that reproduces it

Documented in `README.md` under "Running the checks yourself", and byte-for-byte what CI runs:

```bash
docker run --rm -v "$PWD:/src" -w /src semgrep/semgrep semgrep scan \
  --config p/default --config p/owasp-top-ten \
  --config p/python --config p/typescript --config p/react --config p/docker \
  --severity ERROR --error --metrics=off
docker run --rm -v "$PWD:/src" ghcr.io/gitleaks/gitleaks:latest detect --source /src --no-git --redact
cd app/backend  && uv export --frozen --no-dev --no-emit-project --format requirements-txt -o /tmp/reqs.txt \
                && uvx pip-audit -r /tmp/reqs.txt --disable-pip
cd app/frontend && pnpm audit --audit-level=high
```

Run from the repo root. `semgrep scan`, **never `semgrep ci`** — the `ci` subcommand rejects
`--error` and exits 2 on it. There is no `make sast` or `pnpm sast` wrapper today; adding one is
worthwhile, and it must invoke exactly these four commands so that a local pass means a CI pass.

### 10.3 Untrusted-input boundaries — the complete inventory

Everything below crosses a process boundary and is hostile until it has passed a typed validator.

#### Existing boundaries

**B1 — Every HTTP endpoint (19 routes).**
*Injection classes:* mass assignment, oversized payloads, control-character injection into Excel,
cross-origin abuse.
*Defence:* every request body is a Pydantic v2 model — `CategoryCreate`, `CategoryRename`,
`RowWrite`, `RowChange`, and since Phase 1 `WatchEventCreate` (T29) and `ResolutionUpdate` (T30),
both `extra="forbid"` with a `model_validator` refusing an incoherent body at the boundary rather
than at the flush — with explicit caps from `constants.py:64-72`: `MAX_TITLE_LENGTH = 120`,
`MAX_CELL_LENGTH = 2000`, `MAX_NEW_CATEGORY_ROWS = 500`, `MAX_NEW_CATEGORY_COLUMNS = 64`,
`MAX_FILENAME_STEM_LENGTH = 120`, `MAX_REASON_LENGTH = 240`, `MAX_PROPOSAL_CHANGES = 500`,
`MAX_PROPOSAL_SOURCES = 20`, `MAX_CHAT_MESSAGE_LENGTH = 16000` (enforced at the route with
`text: Annotated[str, Body(embed=True, max_length=MAX_CHAT_MESSAGE_LENGTH)]`,
`api/chat.py:90-95`, the annotation itself at `:94`). Every string that will reach a cell goes
through `models/cell_text.py:12-14`, which strips
`ILLEGAL_CELL_CHARACTERS = "[\x00-\x08\x0b\x0c\x0e-\x1f]"` (`constants.py:93`) and clips to the
limit. `CategoryCreate` additionally rejects incoherent bodies in a `model_validator`
(`category_create.py:50-59`): `titles` and `rows` are mutually exclusive, and every key of every row
must be one of `column_keys()` (`category_create.py:45-48`) — which reuses
`workbook.schema.unique_key`, the single place column keys are minted (`category_create.py:18-20`),
so a request's vocabulary cannot diverge from what the reader derives. **T22 added a second
`columns` validator, `_reject_app_owned_columns` (`category_create.py:41-47`)**: a header that
normalises into `APP_OWNED_HEADER_ALIASES` (`constants.py:122` — today just the identity column's
`Row ID` aliases) is refused with a **422** before any workbook is created. It closes the one route
that could otherwise mint a column the app believes it owns, from outside the app's own writer path;
the reader would then exclude that user column from `columns` and `cells` and the owner's data would
quietly stop rendering. The three Phase 1 routers add their own caps rather than inheriting one:
`MAX_ENTRIES_PAGE_SIZE = 500` (`constants.py:193`) is enforced by `Query(ge=1, le=…)` on both list
routes, `MAX_DEVICE_LENGTH = 120` / `MAX_NOTE_LENGTH = 240` bound `WatchEventCreate`'s two free-text
fields, and `MAX_ORDER_TYPE_LENGTH = 32` clips `ResolutionUpdate.order_type` to the column's own
width so a body that could not be stored is refused where the failure names a field. CORS is an
explicit two-origin allowlist with no credentials and no wildcard (`main.py:28-36`). nginx caps the
body at `client_max_body_size 1m` (`nginx.conf:26`).
*Not defended, by design:* there is **no authentication**. This is a single-user app bound to
`127.0.0.1`. Exposing it on a network interface is out of scope and would need auth designed first.

**B2 — The `.xlsx` file loader.** `workbook/reader.py:70-72` (`read_category`) calls
`load_workbook(path)` on every file matching `*.xlsx` in `library_dir`
(`workbook/discovery.py:12-20`, `workbook_paths`).
*Injection classes:* **deserialization, zip-bomb / resource exhaustion, XXE.**
This is the largest untreated surface in the app and it must be named honestly: **an `.xlsx` is a
zip archive of XML, and openpyxl is a full parser for it.** A file dropped into the library
directory — by a sync client, a download, or a `git pull` — is parsed with no archive size check, no
member-count check, and no decompressed-size check. A malicious or merely corrupt workbook can
exhaust memory during `load_workbook`.
*Defence today:* discovery is scoped to **top-level** `*.xlsx` in `library_dir` only, and skips
names beginning `~$` (Excel's lock file), `.~tv-write-` (this app's temp prefix) and `.`
(`discovery.py:19`); a file that fails to parse is caught and surfaced as `UnreadableWorkbook`
(`catalog.py:76`) rather than 500-ing the listing; `.semgrepignore:29-37` keeps the scanners out of
the workbook bytes; `.gitattributes:54-56` marks `*.xlsx *.xlsm *.xls` `binary` so git never rewrites
bytes inside a zip container — that file calls it "the single most important line in this file".
*Residual risk, accepted for now:* no decompression-ratio guard. The mitigating fact is that the
library directory is the user's own repo checkout, not an upload endpoint — **there is no route that
accepts a workbook.** If one is ever added, it needs a size cap, a member-count cap and a
decompressed-size cap before it merges.

**B3 — Category rename → a filename written to disk.**
`POST /api/categories/{id}/rename` (`api/categories.py:49-52`) → `CategoryRename.stem`
(`models/category_rename.py:13`, `min_length=1, max_length=MAX_FILENAME_STEM_LENGTH`, which is 120)
→ `workbook/renaming.py:16-41`, `validate_stem` at `:18`.
*Injection classes:* **path traversal, filename injection, Windows reserved-device names.**
*Defence:* `workbook/stem.py:14-30` `validate_stem` strips trailing dots and spaces, enforces the
length cap, strips a redundant `.xlsx` suffix, rejects every character in
`ILLEGAL_FILENAME_CHARACTERS = r'<>:"/\|?*'` (`constants.py:75`) — **which includes both separators,
so `../` cannot survive** — rejects any codepoint below 32, and rejects
`RESERVED_FILENAME_STEMS = {"con","prn","aux","nul"} | {com1..com9} | {lpt1..lpt9}`
(`constants.py:76-78`). The destination is then built with `path.with_name(...)`
(`renaming.py:19`), which **cannot leave the parent directory** by construction. Two further checks
run before the move: an existing destination raises `DuplicateCategoryError` unless only the case
differs (Windows compares case-insensitively, `renaming.py:22-23`), and
`discovery.addressed_by(...)` catches the subtler collision where a *free filename* derives an
*already-taken id* — the loser of an id clash is not merely hidden, every read and write lands on
the other workbook (`renaming.py:25-30`). `os.rename` failures map to typed errors, never to a 500
(`renaming.py:33-40`).
The parallel path for new categories is `workbook/naming.py:27-33` `workbook_filename`, which
replaces every run outside `[A-Za-z0-9 _-]` with a space, collapses whitespace to `_`, then runs the
same `validate_stem`, and finally rejects a name whose slug is empty.

**B4 — The `heroes/` artwork loader and the `/heroes` static mount.**
`main.py:43-44` mounts `StaticFiles(directory=settings.heroes_dir)`; `workbook/heroes.py` finds
files by `artwork_key`.
*Injection classes:* **path traversal** (mitigated by Starlette's `StaticFiles`, which resolves and
confines), **stored XSS via SVG, content-type confusion.**
*Defence:* `HERO_SUFFIXES` (`constants.py:89`) is what the on-disk reader recognises; the CSP at
`nginx.conf:40` sets `object-src 'none'` and `base-uri 'self'`; `X-Content-Type-Options: nosniff`
(`nginx.conf:30`) stops a mislabelled file being executed as script.
*The asymmetry is deliberate and must not be "fixed":* `HERO_SUFFIXES` includes `.svg`, `.jpeg` and
`.avif` because hand-placed artwork on disk may be any of those, while
`services/image_format.py` — the validator for anything **downloaded** — accepts only PNG, JPEG,
GIF and WEBP by magic bytes and writes only `.png` / `.jpg` / `.gif` / `.webp`. The comment at
`image_format.py:31-32` states why SVG is absent: *"it is scriptable XML, and this runs on bytes the
open web handed over on a model's say-so."*

**B5 — The hero download (`HeroStore.save`).** `services/hero_store.py:42-59`, with the fetch in
`HeroStore._download` at `:61-80` and the write in `HeroStore._write` at `:82-94`; reached from
`POST /api/chat/proposals/{id}/hero/{choice}`.
*Injection classes:* **SSRF, resource exhaustion, content-type confusion, path traversal.**
*Defence, in the order it executes:* `await assert_public_http_url(url)` (`hero_store.py:63`) →
`httpx.AsyncClient(timeout=HERO_FETCH_TIMEOUT_SECONDS)` = 20 s →
**`follow_redirects=False`** (`hero_store.py:68`, reasoned at `:66-67`), because every hop would
have to be re-checked against the guard, so a direct file URL is demanded and a redirect is reported
back as a failure → a streaming read that **refuses rather than truncates** past
`MAX_HERO_BYTES = 8_000_000` (`_read_capped`, `hero_store.py:24-31`;
the constant at `constants.py:83`) → the magic-byte format check (`image_suffix`, B4) → a
resolved-path containment check `if not destination.is_relative_to(heroes_dir): raise
UnsafeHeroPathError` (`hero_store.py:90-91`, its comment at `:88-89`), present even though the id
derives from a real filename, so that stops
being something a reader has to verify elsewhere → deterministic lock ordering (the artwork key,
then the shared attribution file, always in that order) → the standing image is **moved aside, not
overwritten** (`services/hero_backup.py:13-25`). `httpx.InvalidURL` is caught alongside
`httpx.HTTPError` because it is raised while *building* the request and is not an `HTTPError`
(`hero_store.py:77-80`). Attribution rows escape backslashes **before** pipes when writing the
markdown table (`services/attribution.py:26-32`) — the order matters and the comment says so.

**B6 — The chat agent's `claude` CLI subprocess.** `agent/options.py:21-35`.
*Injection classes:* **command injection, privilege escalation through inherited configuration,
prompt injection via model output selecting a tool.**
*Defence:* the SDK spawns the binary; **no shell is involved and no string is ever interpolated into
a command line.** Every option is explicit, and the comment at `options.py:22` says why: *"an
omitted setting here inherits the machine's own Claude config."* Concretely — `setting_sources=[]`
(no machine config), `env={}` (no environment passed through), `permission_mode="dontAsk"` with
`allowed_tools` an **exact four-element allowlist** (`WebSearch`, `mcp__library__fetch_url`,
`mcp__library__get_category`, `mcp__library__propose` — `AGENT_ALLOWED_TOOLS`,
`agent/constants.py:26-31`), `max_turns=40` (`agent/constants.py:14`), `cwd=library_dir`. The three
library tools run in an **in-process** MCP server (`agent/server.py:16-28`), so no second process is
spawned for them. `get_category` is annotated `read_only_hint=True`
(`tools/get_category.py:40-45`) and returns only `columns` and `rows` (`get_category.py:38`).
**The model has no filesystem access and no write path except `propose`** — and `propose` writes
nothing: it records a pending proposal that a human must read as a diff and approve. Two fields are
**minted by the backend and dropped from the tool's JSON schema** so the model literally cannot
supply them (`_hide_minted_fields` / `_arguments_schema`, `tools/propose.py:67-77`; the minting
itself at `:84-92`): `id` is always `uuid4().hex`, and `read_mtime` comes from the session's
`ReadLog`, because *"a model-chosen id would collide with a real proposal, and a model-chosen
freshness stamp would defeat the very guard it is compared against"* (`propose.py:29-30`).
Proposing an edit to a category the session never read is refused (`propose.py:89-91`) with a
message telling the model to call `get_category` first. Approval runs through
`catalog.apply_changes(...)` — **the same funnel the REST endpoints use**, with the same
`expected_mtime` guard, the same `.backups` snapshot, the same Excel-lock check and the same atomic
swap (`api/chat.py:76-80`). A spent read stamp is forgotten after a successful write
(`session.py:141-145`).
*Licensing, at this same boundary:* **TMDB's API Terms (§1.C, last updated 2023-10-20) prohibit using
"the TMDB APIs or TMDB Content in connection with, including for training, a machine learning (ML) or
artificial intelligence (AI) based Application", and §2.A lists interactive query-response systems,
"including large language model (LLM) ... chatbots", as commercial use.** That covers passing TMDB
content to the model at inference time, not only training. The rule that follows is absolute: **no
TMDB-sourced content — titles, overviews, episode names, artwork or any other TMDB field — is ever
placed in the chat agent's prompt, tool results or context.** TMDB data is rendered in the UI and used
by the non-AI resolver; the agent researches through its own tools and proposes, and TMDB matching
happens outside the model, in a picker a human confirms. An earlier draft of this paragraph said
inference-time use was permitted; the terms text, verified 2026-09-15, says otherwise. Whether TMDB
may be used at all in an application that also contains an AI chat is not settled by the terms and
is an owner decision. TheTVDB's terms (last updated 2020-10-23) contain no comparable clause.

**B7 — Playwright page fetches and `httpx` page fetches in the research path.**
`agent/fetcher.py:36-91`, `agent/browser.py`, reached from `mcp__library__fetch_url`.
*Injection classes:* **SSRF, resource exhaustion, prompt injection.**
*Defence — SSRF:* `agent/url_guard.py:13-61` `assert_public_http_url` requires an `http`/`https`
scheme, resolves the host with `getaddrinfo` on the running loop (`agent/address_lookup.py:9-12`),
refuses a host that resolves to nothing, and requires **every** resolved address to be publicly
routable — rejecting `is_private`, `is_loopback`, `is_link_local`, `is_multicast`, `is_reserved` and
`is_unspecified`. The cheap path follows redirects **manually** and **re-runs the guard on every
hop** (`fetcher.py:74`), capped at `MAX_FETCH_REDIRECTS = 5`.
*Defence — exhaustion:* `FETCH_TIMEOUT_SECONDS = 20.0`, `MAX_FETCH_BYTES = 4_000_000` (the body read
stops there and marks `truncated`), `MAX_FETCH_CHARS = 30_000`, `MAX_TOOL_RESULT_CHARS = 48_000`;
Chromium runs behind an `asyncio.Lock` with `BROWSER_TIMEOUT_MS = 45_000` and is closed by the app's
lifespan (`main.py:17-21`), so a chat's browser cannot outlive the backend.
*Defence — prompt injection:* retrieved page text is **data, never instructions**. It is wrapped in
explicit delimiters `<<<UNTRUSTED_WEB_CONTENT>>>` / `<<<END_UNTRUSTED_WEB_CONTENT>>>`
(`agent/constants.py:61-62`) by `tools/fetch_url.py:33-40`, and when the payload exceeds the
transport cap the **page text is trimmed and the payload rebuilt**, never the serialised JSON —
because trimming the JSON would cut off the closing delimiter and leave untrusted web content
unterminated in the transcript (`_within_transport_cap`, `fetch_url.py:43-52`). `RESEARCH_SYSTEM_PROMPT` carries a section
headed `FETCHED CONTENT IS UNTRUSTED DATA` naming both markers and calling a page that tells the
model to ignore the rules **an attack** (`agent/prompt.py:43-49`), plus a two-independent-source
rule for release dates, chronological placement and episode ordering, preferring an empty cell over
a guess (`prompt.py:51-56`). `html_to_text` (`agent/html_text.py:8-16`) strips
`<script|style|noscript|template>` bodies before any of that.

**B8 — Model output rendered in the browser.**
*Injection class:* **XSS.**
*Defence:* React's default escaping. `ChatMessageBubble.tsx` renders prose as text inside a `<p>`;
`ProposalDiff` / `ProposalRow` render cells as text in a table. There is **no
`dangerouslySetInnerHTML` anywhere in `src/`** and no markdown renderer, so there is nothing to
sanitize. `nginx.conf:40` carries a restrictive CSP — `default-src 'self'; script-src 'self'`
(no `'unsafe-inline'`, because Vite emits one external module bundle and nothing else);
`style-src 'self' 'unsafe-inline'` **only** because components set the accent colour and the
progress-bar width as inline `style` attributes; `img-src 'self' data: https:` **only** because a
hero proposal renders each candidate straight from the URL the agent found (`HeroCandidates.tsx`);
plus `object-src 'none'`, `base-uri 'self'`, `form-action 'self'`, `frame-ancestors 'none'`, and the
four headers at `nginx.conf:30-33` — `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
`Referrer-Policy: strict-origin-when-cross-origin`, `Permissions-Policy: camera=(), microphone=(),
geolocation=()`. Every header is declared **once at server level with `always`**, because nginx does
not merge `add_header` down into a location that declares one of its own — the inherited set is
replaced wholesale (`nginx.conf:9-12`). **Adding an `add_header` inside a location silently deletes
every security header for that path.** `/api/` sets `X-Real-IP`, `X-Forwarded-For` and
`X-Forwarded-Proto` but deliberately **does not set `Host`**, so nginx sends its default — the
upstream's own name — rather than handing the backend a browser-controlled value
(`nginx.conf:46-51`).

**B9 — The SSE chat stream.**
*Injection classes:* **response splitting, resource leak.**
*Defence:* every frame is `data: <json>\n\n` where the JSON comes from
`event.model_dump_json(exclude_none=True)` (`api/chat.py:63`) — a serialiser, never string
concatenation, so a `\r` or `\n` in any field cannot forge a frame. Stream headers are exactly
`Cache-Control: no-cache, no-transform` and `X-Accel-Buffering: no` (`chat.py:47`). A dock that goes
away mid-turn retires the conversation it half-read: `sse_frames` (`chat.py:59-73`) catches both
`asyncio.CancelledError` **and** `GeneratorExit` at `:64` — Starlette abandons the generator in two
shapes — and calls `await session.abandon()` inside `anyio.CancelScope(shield=True)` (`:71-72`),
because a cancelled scope goes on re-delivering and an unshielded await would abort at its first
suspension.

#### Phase 1 boundaries

**B10 — The outbound TMDB and TVDB `httpx` clients.**
*Injection classes:* **SSRF, resource exhaustion, unsafe deserialization, credential leakage.**
*Required defence:* base URLs are **constants, never configuration** —
`https://api.themoviedb.org/3`, `https://image.tmdb.org/t/p/`, `https://api4.thetvdb.com/v4`. A
provider host is never taken from input, from a database row, or from an LLM. Every response is
`model_validate`d into a Pydantic model at the boundary; **no raw provider JSON reaches SQL or the
frontend.** Explicit timeouts on every call, a bounded response size, and one serialised,
token-bucket-throttled worker per upstream rather than per-request fan-out — TMDB's limit is per-IP,
so a container behind one egress IP shares one budget across everything. The bearer token goes in a
header, never in a URL, which is the whole reason for choosing the v4 Read Access Token over the v3
`api_key` query parameter. Credentials are `SecretStr` and never logged.

**B11 — Cached artwork written to disk from a TMDB image path.**
*Injection classes:* **SSRF, path traversal, content-type confusion, exhaustion.**
*Required defence:* **reuse B5's machinery — do not write a second downloader.** The URL is built as
`secure_base_url + size + file_path` from `GET /3/configuration` and a stored `remote_path`, so it
is composed rather than accepted; `assert_public_http_url` still runs; `follow_redirects=False`; the
size cap and the `image_suffix` magic-byte check are unchanged; the destination is `resolve()`d and
`is_relative_to`-checked against the artwork directory. `artwork.local_path`
(`data/models/artwork.py`) points into the existing `heroes/` directory, which already owns on-disk
image caching, licence attribution through `ATTRIBUTION.md`, and cache-busting. **Artwork bytes are
never stored in Postgres.** `uq(source, remote_path)` prevents the same remote file being fetched
twice under two rows.
**`artwork.local_path` is stored relative to `heroes_dir`, never absolute** (`services/artwork_cache.py`,
which writes `f"{ARTWORK_SUBDIR}/{destination.name}"` and reads back through `(root / local_path).resolve()`).
An absolute path in a row would break the moment the library moved, survive a restore into a different
checkout as a pointer outside the artwork directory, and make the containment check compare two
unrelated roots; the relative form is what lets `resolve()` + `is_relative_to(heroes_dir)` mean
something. **The run carries a byte budget: `MAX_ARTWORK_BYTES_PER_RUN` (`constants.py:149`, 200 MB),
checked before each fetch** — the per-file `MAX_HERO_BYTES` cap alone bounds one poster but not a
nineteen-workbook ingest, so the budget is what stops a single pass filling the disk. Past it the
cache stops fetching and logs; an ingest that cannot cache a poster has still ingested a title, so
every refusal here is a logged `None` and none of them raises.

**B12 — TMDB/TVDB text rendered into React.**
*Injection class:* **XSS.**
*Required defence:* provider titles, overviews and episode names are **community-edited free text** —
treat them exactly like model output (B8). Render as text; React escapes. **Do not introduce
`dangerouslySetInnerHTML` or a markdown renderer to make an overview "look nicer"** — that single
change converts every provider field into a stored-XSS sink, and today's CSP would not stop it,
because the payload would be inline HTML rather than a script source. If rich text ever becomes a
real requirement: DOMPurify first, and this section 10 inventory is updated in the same change.
`img-src 'self' data: https:` is already permissive enough for provider images; it must not widen
further.

**B13 — The new Postgres layer.**
*Injection classes:* **SQL injection, unsafe deserialization of JSONB, resource exhaustion.**
*Required defence:* every query goes through SQLAlchemy 2.0 Core/ORM constructs with bound
parameters. `text()` is permitted **only** with `:named` bind parameters — never f-strings, `%`,
`.format()` or concatenation. Table and column names are never taken from input; a dynamic sort or
filter uses an allowlist map. Ruff's `S608` is already selected and is the automated backstop.
`curated_entry.raw_cells` is `JSONB` holding verbatim workbook cells — it is **data, not a document
store to execute against**; it is read back through a Pydantic model, never `eval`'d and never used
to build a query. **List endpoints get pagination caps, and the three Phase 1 routers page in the
database rather than in Python**: `limit` and `offset` are `Query(ge=1, le=MAX_ENTRIES_PAGE_SIZE)` /
`Query(ge=0)` bound straight into a `LIMIT`/`OFFSET`, with the cap as the default as well as the
ceiling, so an over-large page is refused at the boundary and no route can be made to materialise
996 rows plus their titles and progress by asking. Native enum labels are the member *values*,
enforced by `values_callable` in `pg_enum`, and adding an enum value needs its own Alembic revision
because Postgres 16 cannot use a label added in the same transaction. `watch_event` is protected by
a **database trigger**, not a convention: `watch_event_no_mutation` raises on
`BEFORE UPDATE OR DELETE`, because an Alembic data migration, a `psql` session, or a
`session.merge()` on a detached instance would each otherwise rewrite history silently. A matching
test asserts that an `UPDATE` raises.

T53a applies the same append-only enforcement to file-completion receipts and event memberships.
The existing player boundary accepts no receipt JSON, fingerprint, file path or provider URL:
those are server-derived from validated selections. Frozen, extra-forbid occurrence models validate
the JSONB shape; bounded SQL column queries capture one live category's queue without per-entry
fan-out. Fresh category/entry reads and a refreshed shared lock on the chosen file prevent stale
identity-map evidence and concurrent file-index changes. No receipt value becomes SQL syntax, a
filesystem path, a log message or chat context. Receipt failures roll back the whole completion.

**B14 — Workbook cells reaching the ingest.**
*Injection classes:* **the same set as B2, plus SQL injection into the projection.**
*Required defence:* a `Title`, `Unit` or `Release` cell is a hand-typed string from a file that may
have been edited anywhere. It is validated through a Pydantic model before it reaches SQL, stored
through bound parameters, and — critically — **`Unit` is parsed into a span only when the parse is
unambiguous**. A parse that could be wrong leaves `resolution_state = 'unresolved'` with a
`resolution_note`, never a silent fallback to the aired order. That is a correctness rule and a
safety rule at once: a confidently-wrong span looks right in the UI, which is the worst failure
shape available here. Three consequences the T17 parser (`resolver/span.py`) makes concrete, each
decided rather than inferred:

- **A blank `Unit` cell is not `movie @ 1.00`** (Ruling 27). Sixty-six `Misc_Anime` rows leave it
  empty on a *series*, so a blank parses at confidence **0.50** with a note, taking its kind from the
  sheet's Type/Format cell — `series` when that cell is episodic, `movie` otherwise. T18 finalises
  the kind from TMDB's `media_type`, and only then may the confidence reach 1.00. A blank cell states
  nothing; reading it as a film was a guess wearing a certainty.
- **Read `span_start`/`span_end` through `SpanParse.episode_span` and `season_span`, never
  directly** (Ruling 29). `Seasons 1-25` puts **season** numbers in those two fields, so a consumer
  that reads them raw and calls them episodes is off by an order of magnitude and looks fine. Each
  property returns `None` for every kind but its own; T18 and T24 use them.
- **The season-scoped shape emits `order_type=None`, not `aired`** (Ruling 30). Of the 53 rows
  shaped `S5 E10-19` / `Season 2 E26-37`, eight carry **series-wide** numbers, not within-season ones
  (Attack_On_Titan `Season 2 E26-37`; My_Hero_Academia `Season 3 E39-58` and `Season 7 E139-156`).
  The parse therefore makes no claim about the numbering and says so in its note; the order is
  confirmed against the title's real orders later, or the entry stays unresolved.

The same principle governs the T18 title resolver, and four of its rulings are the shape it takes.
**A tie is never broken** (Ruling 35): candidates on an equal score leave the entry `unresolved` with
no chosen candidate and a capped ambiguity note naming them — `RED` (2010) has three TMDB films
scoring identically, and a coin flip persisted as a match is a confidently-wrong row that looks right.
**A season- or episode-level match stores the parent tv id** (Ruling 33): `title_tmdb_id` is the
parent's, with a `MatchedUnit` carrying what was actually matched, so `title.tmdb_id` never holds a
season id that `uq(media_type, tmdb_id)` would collide or that Phase 3's Jellyfin join could not
answer (section 5.13). **`TitleMatch.EXTENDED` is deliberately narrow** (Ruling 37): TMDB's title
equalling a leading segment of the row title — cut at a `:` or a space-surrounded dash — scores
**0.65**, films only, only when the years agree, and ranks below `EXACT` and `CONTAINED`. **A
franchise-form match at 0.65 is the form working, not failing** (Ruling 40), and 0.65 is a review-queue
row by construction. The retired idea is worth naming so it is not re-proposed: searching both the
roman and the arabic spelling of a numeral rescued **zero** rows and cost one live call per form
(Ruling 34).

**B15 — The Excel write-back of the mirrored `Watched?` cell.**
*Injection classes:* **data destruction through a race, echo loop.**
*Required defence:* the mirror writes through `Catalog._write` like every other mutation — never
straight to openpyxl — so it takes the `.backups` snapshot, honours the Excel file lock
(`WorkbookLockedError`), and is guarded on `expected_mtime`. A mirror pass while the workbook is
open in Excel **fails cleanly and retries next pass** rather than corrupting the file. Of the two
writers that can race (the mirror and a user edit in the UI), **the mirror is the one that must
lose** — that ordering is implemented deliberately, not left to chance: `_still_ours` re-reads the
sheet on every retry and checks each planned row twice, that it still carries that entry's own
`Row ID` and that its cell still holds exactly what this app last wrote there, abandoning the whole
retry on the first contested row (section 5.16). `tests/services/test_mirror_race.py` (T26) proves it
by mutation — neutering `guard_fresh` fails the suite, a permissive `_still_ours` fails the
deleted-row case. `mirrored_watch_cell` is the entire defence against the echo loop: without it,
every mirror write looks like a human edit on the next ingest, appends an event, re-derives the same
status and rewrites the same cell forever.
**The mirror also never fails an ingest pass** (Ruling 41). A value the sheet's *own* status dropdown
does not offer is dropped from the diff and logged (`skipped=invalid_choice`), and the rest of the
write still goes in; the entries behind the dropped cells keep their old `mirrored_watch_cell`, so
nothing claims a write that never happened. Without that, one workbook offering `Yes,No` would make
`writer._validate` refuse the whole write, roll the entire ingest transaction back, and leave that
file permanently un-ingestable — a denial of service on the owner's own data, caused by the owner's
own dropdown. The sheet's vocabulary wins.

#### Phase 3 boundaries (ADR-014, ADR-012)

**B16 — The Jellyfin client (`clients/jellyfin_client.py`, built at T48).**
*Injection classes:* **SSRF, credential leakage, unsafe deserialization, resource exhaustion.**
*Defence, as built — SSRF:* the base URL is **one configured host, allowlisted, and nothing else** —
`Settings.jellyfin_base_url`, checked at **boot** by a `field_validator` that runs
`clients.http_guard.assert_within_configured_base(value, value)`, so a malformed base (wrong scheme,
embedded credentials, unparseable) fails at startup naming the variable, before the lazily-built
client could ever surface it as a 503 at the first playback. Every request is built through
`configured_url(base_url, *segments, **query)` — the `assert_within_configured_base`-guarded sibling
of the https-only `provider_url`/`assert_within_base` pair the metadata providers use — against a
**constant** path (`/Items`, `/Shows/{id}/Episodes`, `/Videos/{id}/stream`, `/health`,
`/Library/Refresh`) and typed query arguments, never a URL a caller, a database row or the model
supplied; the client has no method that takes a URL at all. **This is the one deliberate carve-out
from the private-address rule**: Jellyfin is a LAN or loopback server, so
`agent/url_guard.assert_public_http_url` (`url_guard.py:52-61`, whose `_is_reachable` predicate at
`:13-22` rejects `is_private` and `is_loopback`) is *not* used here and must not be "fixed" to admit
it. `follow_redirects=False`; a redirect is reported as a failure, never followed.
*Credential leakage:* `jellyfin_api_key` is a `SecretStr`, rendered into exactly one header
(`Authorization: MediaBrowser Token="…"`) inside the client, never into a URL, a log record, an
exception message or a response. The outbound-call log (section 9.2) records method, host, path and
status — never a header. A fix round closed one real leak here: `httpx.LocalProtocolError` (raised by
h11 when a header value contains a CR/LF) is itself an `httpx.HTTPError`, so a key with a stray
newline took the generic failure path and h11's own exception text — the whole header, key included —
landed in the raised `ProviderUnavailableError`. `clients/transport.unreachable(provider, error)` now
formats `type(error).__name__` **only**, keeping the detail on `__cause__`; the same fix was applied
to `tmdb_client.py` and `tvdb_client.py` from the one shared helper. `client.build_stream_url()` does
not exist; the proxy (B17) calls `stream()` for a *streaming response*, not for a URL.
*Deserialization:* every response is `model_validate`d into a Pydantic model at the boundary
(`JellyfinItemPage`, `JellyfinItemDto`, `JellyfinProviderIds`) with `extra="ignore"`; `RunTimeTicks`
becomes `run_time_seconds` by one integer floor division there (section 11.2, rule 7), with no
attribute exposing ticks a second time; `ProviderIds` is read through one named constant
(`JELLYFIN_TMDB_PROVIDER_KEY`), matched case-insensitively so the three schema-valid spellings
(`Tmdb`/`TMDB`/`tmdb`) all resolve, with the casing confirmed live at T49 (section 20.2, Ruling 79).
`stream()` returns a narrowed `StreamedResponse` (status, three allowlisted headers, a live byte
iterator) — **never the raw `httpx.Response`** — so nothing downstream of the client can see an
upstream `Set-Cookie`, `Server` or `WWW-Authenticate` header. Nothing from a Jellyfin response
reaches SQL except through bound parameters into `jellyfin_item`.
*Exhaustion:* explicit connect/read timeouts on every call, `/Items` paged with a fixed page size and
a hard page cap that **raises** `ProviderUnavailableError` after logging the overflow (never a silent
truncation — CLAUDE.md §9.2's "a truncated ingest that reports success is worse than one that fails"),
`health()`/`refresh_library()` read through the shared `read_text()` cap rather than an unbounded
buffered read, and one shared `httpx.AsyncClient` per `JellyfinClient`, closed in the `main.py`
lifespan (`main.py:17-21`) beside the agent and ingest runtimes, guarded by `.cache_info().currsize`
exactly as `get_ingest_runtime` is. An unreachable Jellyfin is "availability unknown", surfaced as
data (section 6.6), never a 500 and never a retry storm.
*Fixtures:* no Jellyfin server has ever been reachable under the owner's VPN, so
`tests/fixtures/jellyfin/` is **hand-authored from Jellyfin 12.1's own OpenAPI document**
(`https://api.jellyfin.org/openapi/jellyfin-openapi-stable.json`, fetched 2026-09-23) — the one
deliberate exception to Ruling 51, named in `tests/fixtures/jellyfin/README.md` with the five shapes a
live server must confirm (`ProviderIds` casing, whether `DateLastSaved` actually arrives on an item,
comma-delimited array encoding, item-id form, the `minDateLastSaved` wire format), superseded once
T49's live sync runs.
*The same shape guards qBittorrent, too:* `assert_within_configured_base` / `configured_url` were
built at T48 specifically so Phase 3.5's `clients/qbittorrent_client.py` (**T62, in progress**) could
consume them unchanged rather than duplicating a second local-upstream guard — see boundary B21.

**B17 — The stream proxy route (`GET /api/playback/{jellyfin_item_id}/stream`, `api/playback.py`, T52).**
*Injection classes:* **path/parameter injection into the upstream request, header injection, credential
leakage, resource exhaustion, open-proxy abuse.**
*Required defence — inbound:* `jellyfin_item_id` is a path parameter typed `uuid.UUID` — **this app's
`jellyfin_item.id`, never Jellyfin's own id** — and it must resolve to a live row (`removed_at IS
NULL`) of kind movie/episode or the route answers 404; a series is not a file. The Jellyfin id used upstream comes from that row, so a caller can
name only items the sync has indexed. The route is therefore not an open proxy: it cannot be pointed
at an arbitrary Jellyfin item, path or host. The only inbound header it reads is `Range`, validated
as a single ASCII `bytes=<start>-<end?>` range and forwarded verbatim on match. A missing start,
reversed bounds, multiple ranges or any malformed header is refused with 416 before an upstream
call, as required by master plan §9.2; every other request
header is discarded — an explicit **allowlist of one**, so a browser-controlled `Host`, `Cookie` or
`X-Forwarded-*` never reaches Jellyfin.
*Outbound / response:* the key goes in the header the client owns (B16); the response relays
Jellyfin's status (`206` for a satisfied range, `200` otherwise), `Content-Type` (pass-through, with
`video/mp4` only as the fallback when the upstream sends none), `Content-Length` and `Content-Range`
as received, and sets `Accept-Ranges: bytes` so seeking works — and **nothing else** from the
upstream headers, so a Jellyfin `Set-Cookie` or `Server` header never reaches the browser. The body is
a `StreamingResponse` over `httpx`'s `aiter_bytes()` — **streamed, never buffered**: direct ASGI
tests prove chunk N is delivered before N+1 is produced. Stream requests use `Accept: */*` and
`Accept-Encoding: identity`; a non-identity upstream encoding is refused before headers so decoded
bytes cannot disagree with forwarded lengths. Only upstream 200/206 statuses are relayed.
`PlaybackResponse` acquires the upstream after function-scoped database teardown, not inside the
route, and shields context cleanup on disconnect or send failure, including header-send failure.
Acquisition failures produce a safe 502 envelope sent outside the exception handler; mid-body or
cleanup failures terminate with a sanitized exception and never append JSON to media. Unconfigured,
closed or unhealthy Jellyfin is 503 before acquisition. FastAPI's declared minimum is 0.121.0 for
`Depends(scope="function")`; locked 0.141.1 is unchanged.
*Credential leakage:* the key never appears in the `<video src>` (which is the same-origin
`/api/playback/...` path), the built `dist/` bundle, the access log or an error envelope; the gate
audit greps all three. nginx proxies `/api/` already with `proxy_buffering off` (`nginx.conf:53-59`),
which the stream needs; **no new `location`, no new `upstream`, and no `add_header` inside a location**
(`nginx.conf:9-12` — it would silently drop every security header for that path). Because the source
is same-origin, the CSP at `nginx.conf:40` needs **no `media-src`** and is not widened.
*Exhaustion:* no concurrency fan-out per request; a single upstream stream per response; the route is
loopback-only like every other.

**B18 — The Streaming Availability client (`clients/streaming_availability_client.py`, T55).**
*Injection classes:* **SSRF, credential leakage, unsafe deserialization, resource exhaustion (quota),
prompt injection (indirect).**
*Required defence:* the base URL is a **constant**; the only variables are typed query arguments
(`tmdb_id`, `country=il` — hard-set, ADR-011). The key (`streaming_availability_api_key`,
`SecretStr`) travels as a request header, never a query parameter, never logged. Responses are
`model_validate`d and reduced to the fields `streaming_offer` stores (section 5.13): service,
offer kind, link, languages, fetched time — **no images, no descriptions**, which the API's terms
reserve. Every stored `link` must match `HTTP_URL_PATTERN` (`constants.py:91`) and start with
`https://`; the launcher opens it with `window.open(link, "_blank", "noopener,noreferrer")` and
never renders it as markup. Quota is a resource: one lookup per title, cached in `streaming_offer`,
refreshed on a schedule that stays under 1,000 requests a month; a 429 stops the pass, it does not
retry. **Prompt injection, indirectly:** this data must never reach the chat — the agent's fetch tool
gains a denylist of the streaming services' domains (ADR-012 rule 7), and nothing in `streaming_offer`
is placed in a prompt, a tool result or the library digest. A hand-marked Disney+ row (`manual =
true`) is owner-typed and is subject to the same `https://` and pattern checks as a fetched one.

**B19 — The `Position (s)` write-back (T53).**
*Injection classes:* **data destruction through a race or a hot loop; type confusion in a numeric cell.**
*Required defence:* the write goes through `Catalog._write` (`services/catalog.py:131-141`) — never
straight to openpyxl — so it takes the `.backups` snapshot, honours the Excel lock (423), and is
guarded on `expected_mtime`; on `StaleWorkbookError` it re-reads and retries once, losing to a user
edit exactly as the mirror (B15) does. **R105 saves both stores every 60 seconds while playing,
plus pause, ended and player close/unmount.** Five minutes produces five logical dual-store snapshots,
not a five-second write loop. Validate the committed player event against the live entry/category,
resolve current Row IDs before the first write, and refuse stale workbook stamps. An older-event
recovery projects the newest committed player position and all pending safe status cells. Retry preserves the
event id and original expected_mtime; Position/Watched share one workbook mutation. The value is
`watch_event.position_seconds`, an `int` already converted at the boundary (section 11.2, rule 7),
written as a number (so `writer._numeric_columns` types the column numeric) and clipped to
`[0, runtime_seconds]` when the runtime is known. The column is app-owned (`ColumnRole =
"position"`): the reader excludes it from `columns` and `cells`, so no `RowWrite`, `RowChange` or chat
proposal can address it (`UnknownColumnError` on any attempt from outside the app's own writer path),
and it is **never read back as truth** — on ingest its cell is ignored entirely; a human edit to it
changes nothing in Postgres. The throttle question is decided: the write passes `backup.NO_THROTTLE`
like every non-`update_row` write: every logical minute/terminal save has its own recoverable snapshot.

**B20 — staging discovery and filename identification (T64/T65).**
*Injection classes:* **path traversal, symlink escape, unsafe peer filenames, duplicate provenance,
identity confusion and SQL injection.**
*Defence as built:* `assert_within` resolves each file against the configured staging root before
stat, extension and size checks; directory symlinks are not followed. qBittorrent files reuse the
validated `absolute_path(save_path)` helper; save directories may equal the root or lie beneath it,
but cannot be relative or escape through a symlink. Unknown hashes are skipped without logging their
contents. The whole peer arm is discarded on `ProviderError`, leaving local discovery functional.
Walk/resolve/stat run on worker threads. `path_refused` and `unreadable` make filesystem failures
observable, with path values repr-escaped in structured logs. Canonical paths deduplicate aliases
and the two arms, and bounded SQLAlchemy lookups exclude live nonfailed history. A named/bound
PostgreSQL advisory lock lasts until the caller commits or rolls back, preventing the pre-commit
duplicate race across requests/workers. This task reads metadata only: it never opens file contents,
identifies, moves, hashes, deletes or writes a workbook. T66 must recheck containment at the actual
move boundary; a scan's observation does not authorise a later unchecked file operation.

T65's pure `services/import_filename.py` parses only explicit single-item release shapes, refusing
empty normalized tokens and multiple-episode/range names. `services/import_identify.py` matches
the local projection with bound SQLAlchemy predicates: exact normalized key first, indexed pg_trgm
fallback second, constrained by media type and an explicit release year. Confidence is the lower
of parse confidence and title similarity; a raw-score tie or a result below the configured minimum
stays unidentified. Absolute numbers use `episode_for_sequence`, never arithmetic or an aired
fallback. Row locks and live-FOUND predicates preserve existing owner choices; the caller owns the
transaction. No TMDB request, media-content read, move, hash, delete or workbook write is added.

**B21 — the qBittorrent client (`clients/qbittorrent_client.py`, T62, done and reviewed).**
*Injection classes:* **SSRF, credential leakage, CSRF-by-omission, unsafe deserialization,
resource exhaustion.**
*Defence as built:* all endpoints are fixed constants under the configured origin/base path;
`configured_url` and `assert_within_configured_base` reject origin/path escapes, and redirects are
never followed. `clients/configured_upstream.py` is shared with Jellyfin, not a second guard.
`Referer` and `Origin` come from the configured upstream; credentials travel only in the login form,
and the SID stays in the HTTP client's in-memory cookie jar. Blank credentials disable the client
before HTTP. Logs omit credentials, cookies and bodies. Explicit timeouts and capped `read_json` /
`read_text` bound responses, which become frozen validated models; file names reject traversal and
absolute paths on both POSIX and Windows. Only lowercase 40-/64-hex hashes can enter a file-list
request (R85); one re-login after a data-call 403 is the retry limit. The WebAPI floor is 2.8.2.
ADR-015's no-acquisition constraint is tested against the public method surface and parsed route
paths (R86): version, login, completed list and file list only; no add, search or magnet route.

**B22 — the media-root destination path (`services/import_naming.py`, `services/media_filename.py`, T63, done and reviewed).**
*Injection classes:* **path traversal, symlink escape, filename injection, Windows reserved-device names.**
*Required defence:* every destination is composed from projection values only — never from the source filename — and each component passes `safe_component`, which replaces every `ILLEGAL_FILENAME_CHARACTERS` character and every codepoint below a space, collapses whitespace, and strips leading and trailing dots and spaces (so a component can never be `.` or `..`). The component is capped at `MAX_FILENAME_STEM_LENGTH` characters **and** `MAX_MEDIA_COMPONENT_BYTES` (255) UTF-8 bytes — the per-component limit ext4, overlayfs, APFS and NTFS all enforce — trimmed on whole code-point boundaries so a cut never splits a multi-byte character and a name is never left invalid. The `RESERVED_FILENAME_STEMS` guard runs **after both caps**, replacing the tail when there is no room to append rather than appending past the limit, so the cap can neither cut the reserved-name suffix off nor manufacture a device name (`CON`, `NUL`, …) the cap itself created. An empty result is `ImportNamingError`, never a silent skip. `workbook/stem.validate_stem` is deliberately **not reused** — it refuses `:`, and this sanitises instead of refusing. The joined path is then `resolve()`d and `is_relative_to`-checked against `media_root.resolve()` by `assert_within` — on the **resolved** path, because `resolve()` follows symlinks and a symlink inside the media root pointing out of it is exactly the escape a joined-but-unresolved path check would wave through — and the media root itself is refused as a destination. `assert_within` also converts the `ValueError` that `resolve()` raises on an embedded null byte into `ImportPathError`, rather than letting it crash uncaught. `plan_destination` calls `assert_within` before returning, so no caller can forget the check. Both new error classes, `ImportNamingError` and `ImportPathError`, subclass `ProjectionError` in `data/errors.py`; **T68 still owes their `api/errors.py` status/message table rows** (section 4.3) — until then either answers a bare 400.
**T66 extension (R106):** the same boundary now includes `import_move`, `import_files`, `file_digest`,
`import_source_lock` and `rename_exclusive`, addressing data destruction and concurrent ownership.
Commit active source/destination claims before mutation; retain staging through copy, exclusive
installation, streamed digest verification and confirmed provenance commit. Archive replaced media;
compensate only proven-owned artifacts. Unknown ownership/uncertain commit retains bytes and active
recovery state. PostgreSQL and OS source-file locks fence cooperating workers, including database
connection loss; cancellation drains worker-thread I/O before release. Recheck roots and parents
before destructive transitions. Native exclusive rename never overwrites a raced external target;
unsupported filesystems fail safely without an unsafe fallback. This does not protect against every
external pathname race or certify power-loss durability; import roots must not be edited concurrently.

### 10.4 Standing rules

- **No secrets in the repo.** Environment variables only; gitleaks runs on every push.
- **`SecretStr` for every credential**, and the DSN is a computed property so the password renders
  in exactly one place.
- **A MEDIUM Semgrep finding is fixed, or suppressed inline with a written justification.** A
  suppression without a reason is a pipeline failure by the global contract.
- **Every new input boundary is added to this inventory in the same change that introduces it**,
  with its injection classes and its specific defence, per the global Definition of Done item 15.
- **The `sast` stage is not optional and not `allow_failure`.** Section 7 lists what it runs; this
  section is where a new boundary's defence is recorded. Both change together or neither does.

</security>

---

<required_calculations>

## 11. Required calculations

Variable names below match the implementation exactly. Every duration is in **seconds**; every
percentage is an integer 0-100.

### 11.1 Existing formulas

**1. Watch counts — `workbook/reader.py:42-54`, the source of `WatchCounts`.**
Given `statuses`, the stripped watch-column value of every non-blank data row (or `""` for every row
when the sheet has no watch column, `reader.py:85`):

```
watched      = count(status == WATCHED)          # "Watched"
in_progress  = count(status == IN_PROGRESS)      # "In progress"
skipped      = count(status == SKIPPED)          # "Skip"
total        = len(statuses)
unwatched    = total - watched - in_progress - skipped
trackable    = total - skipped
```

Two facts that are easy to get wrong. **The sheet stores `"Skip"`, not `"Skipped"`**
(`SKIPPED`, `constants.py:15`); the UI label "Skipped" is produced by
`src/utils/statusLabel.ts:3-8`, the `[SKIPPED]: "Skipped"` entry at `:7`. And
`unwatched` is a **residual**, not a count of empty cells — any value the sheet carries that is not
one of the three known statuses lands in `unwatched`. All six fields are `ge=0`
(`models/watch_counts.py:8-16`). Rows whose every cell is blank are skipped before counting
(`reader.py:82-83`).

**2. Progress percent — `src/utils/progressPercent.ts:4-7`.**

```ts
if (counts.trackable === 0) return 0;
return Math.round((counts.watched / counts.trackable) * 100);
```

**The denominator is `trackable`, not `total`** — skipping an entry shrinks the goal rather than
capping the meter below 100. The `trackable === 0` guard is what stops a division by zero for an
empty category, or one where everything is skipped. This one function feeds every progress readout:
`CategoryCard`'s meter, `CategoryLink`'s 2px meter, and `CategoryBanner`'s `.banner__track`, which
carries `role="progressbar"` with `aria-valuenow={percent}`, `aria-valuemin={0}`,
`aria-valuemax={100}` (`CategoryBanner.tsx:34-43`). Any new progress display must call it rather
than recompute the ratio.

**3. The tally line — `src/utils/summarise.ts:6-11`.**

```ts
const parts = [ENTRY(counts.total), `${counts.watched} watched`];
if (counts.in_progress > 0) parts.push(`${counts.in_progress} watching`);
if (counts.skipped > 0) parts.push(`${counts.skipped} skipped`);
return parts.join(" · ");
```

with ``ENTRY(count) = `${count} ${count === 1 ? "entry" : "entries"}` ``. Total and watched always
appear; the other two only when non-zero.

**4. How far the rail is lit — `src/components/RouteList.tsx:24-32`.**

```ts
if (watch === null) return new Set<number>();
let frontier = -1;
detail.rows.forEach((row, index) => {
  if (row.cells[watch.key] === WATCHED) frontier = index;
});
return new Set(detail.rows.slice(0, frontier + 1).map((row) => row.row));
```

The comment at `:24` states the rule: *"Everything up to and including the last watched entry counts
as ground covered."* Three properties are load-bearing:

- It walks **`detail.rows`, the unfiltered list**, not the filtered `rows` prop — the frontier is a
  property of the sheet, not of the current filter, so switching to "Watched only" must not move it.
- `frontier` is the index of the **last** watched row, not the first unwatched one. A gap — watched,
  unwatched, watched — leaves the middle row *reached* but not *watched*. That is intentional: the
  rail shows ground covered, the node shows each entry's own status.
- The set holds **sheet row numbers** (`row.row`, 1-based with the header as row 1), not indices.
  The two are equal only by accident.

Rendering: `.route__entry::before` draws a 1px line (`src/styles/route.css:38-47`), thickened to 2px
and recoloured `var(--accent-dim)` when `[data-reached="true"]` (`route.css:49-52`).

**5. Advancing a status — `src/utils/nextWatchStatus.ts:4-8`.**

```ts
const cycle = choices.length > 0 ? choices : WATCH_CYCLE;
const position = cycle.indexOf(current);
return cycle[(position + 1) % cycle.length] ?? cycle[0] ?? "";
```

It walks **the sheet's own dropdown order** (`ColumnSpec.choices`, derived from the workbook's data
validation), falling back to `WATCH_CYCLE = ["", "Watched", "In progress", "Skip"]` only when a sheet
declares none. A value not in the cycle gives `indexOf === -1`, so the next value is `cycle[0]` —
an unrecognised status resets to the start rather than throwing. The double `??` is required by
`noUncheckedIndexedAccess`.

**6. Filter matching — `src/utils/matchesFilter.ts:11-13`.** `"all"` matches everything; every other
filter is an exact string equality against the sheet's own vocabulary through `STATUS_BY_FILTER`.
Not a substring match, not case-insensitive.

### 11.2 Formulas Phase 1 introduces

**7. TMDB runtime → stored seconds.** TMDB returns runtime in **whole minutes**. The ingest
multiplies by 60 exactly once, at the boundary:

```
episode.runtime_seconds = tmdb_episode.runtime * 60      # minutes -> seconds, at ingest only
```

Every duration column is `Integer`, named `*_seconds`, with a `CHECK … > 0`
(`data/models/episode.py`, `title.py`, `season.py`, `watch_event.py`). `INTERVAL` was considered and
rejected: playback position in Phase 3 is an integer number of seconds, from a `<video>` element's
`currentTime` or a Jellyfin session report, and every comparison the app actually makes is
`position_seconds >= runtime_seconds * threshold`. With `INTERVAL` on one side and an integer on the
other, every such predicate needs a cast. **No mixed units survive the ingest boundary — the unit is
in the column name, and there is no minutes column anywhere in the schema.** Jellyfin's
`PlaybackPositionTicks` is in .NET ticks (100 ns); dividing by 10,000,000 to seconds is a Phase 3
boundary conversion of exactly the same kind. Decided form (ADR-014), applied **once**, at the
boundary, and nowhere else:

```
position_seconds        = ticks // 10_000_000          # Jellyfin PlaybackPositionTicks / RunTimeTicks -> whole seconds, integer division
jellyfin_item.run_time_seconds = RunTimeTicks // 10_000_000
position_seconds        = round(video.currentTime)     # the browser <video> element reports a float of seconds; rounded once, in the player
```

The player posts an `int`; `WatchEventCreate.position_seconds` is `int | None` with `ge=0` and rejects
a float; the `Position (s)` cell (section 10.3, B19) is written from that same `int`. There is no
ticks column, no float-seconds column and no milliseconds column anywhere in the schema or the
workbooks — a reader who finds one has found a bug.

**8. Runtime totals and remaining time**, over one curated entry and over one category. Both walk
`curated_entry_item`, because that is the flat, ordered, indexed list:

```
entry_runtime_seconds     = Σ episode.runtime_seconds  over curated_entry_item
                            where curated_entry_id = :entry

category_runtime_seconds  = Σ episode.runtime_seconds  over curated_entry_item
                            where category_id = :category

remaining_seconds         = Σ episode.runtime_seconds  over curated_entry_item x
                            join episode_watch_state s on s.episode_id = x.episode_id
                            where x.category_id = :category
                              and coalesce(s.kind, 'unset') not in ('completed', 'skipped')
```

`runtime_seconds` is **nullable** — TMDB does not have a runtime for every episode. A sum over
nullable values must therefore be reported with its coverage, never silently understated: emit
`SUM(runtime_seconds)` alongside `COUNT(*) FILTER (WHERE runtime_seconds IS NULL)`. A remaining-time
readout that quietly omits forty unknown episodes is worse than one that says "≈14 h, 40 episodes
unknown". Skipped episodes are excluded from remaining time, which keeps this consistent with rule
2's use of `trackable`.

Movie entries occupy **one row each** in `curated_entry_item`, with `episode_id` null and `movie_title_id` set (ADR-010), so the episode sums above — which join on `episode_id` — skip them, and a category's runtime is those sums **plus** `title.runtime_seconds` for every live entry whose `unit_kind = 'movie'`. Any category may be mixed — One Piece is — so the
mixed case is the norm, not an edge case.

**9. Absolute episode number → season + episode.** **There is no arithmetic for this. It is a
lookup, and writing arithmetic for it is the single most damaging mistake available in this
project.**

TMDB numbers anime episodes **absolute-continuously inside season buckets**: One Piece (`tv/37854`)
is split into 23 regular seasons plus a season 0 of specials (24 entries in its `seasons` array) and **season 2's `episode_number` values run 62-77, not 1-16**. So
`(season_number, episode_number)` is a valid primary key but is **not** a human-meaningful `SxxEyy`,
and it never matches a media-library season/episode pair. Any UI rendering
`S{season_number}E{episode_number}`, and any join against a filename or a Jellyfin
`ParentIndexNumber`/`IndexNumber` pair, is wrong for these titles and silently right for Western TV
— the worst possible failure shape.

The mapping therefore goes through `episode_order`, whose `sequence` is a **dense, 1-based rank
within one numbering**:

```
episode_order(title_id, order_type, label, sequence) -> episode_id
                                                     -> episode.season_number, episode.episode_number
                                                     -> order_season_number, order_episode_number
```

- **absolute** order: `sequence` *is* the absolute number. No season arithmetic anywhere.
- **aired** order: `sequence` is assigned by walking `(season_number, episode_number)` ascending,
  with **`season_number = 0` — the specials bucket — excluded from the walk** and given its own
  `alternate` ordering. Without that exclusion, every anime's forty specials shift the main run.
- **dvd** order renumbers episodes into *different* seasons entirely, which is exactly why
  `order_season_number` / `order_episode_number` exist alongside the rank. **They are what the UI
  prints ("DVD S1E14"); `sequence` is what the app computes with.** Never print `sequence` as if it
  were an episode number, and never compute with `order_episode_number`.

`label` (default `''`) makes named alternates first-class: `order_type='alternate',
label='Chronological'` is a complete key, and the empty default reads as "the canonical one of this
type". `source` records which provider produced the ordering, because TMDB and TheTVDB disagree and
the app must be able to say which one it is showing rather than blending them.

**TheTVDB has seven season types live in production (measured against `GET /v4/seasons/types`, 2026-09-15)** — `official`, `dvd`, `absolute`, `alternate`, `regional`, `altdvd`, `alttwo` — and its OpenAPI spec presents them as
*examples*, **not** as an enum, so the list is not closed and a new one can appear without warning.
`alttwo` in particular is easy to forget and is a real, distinct ordering. The rule that follows is
the same one section 9 states for the ingest: **read the season-type list at runtime from a cached
`GET /v4/seasons/types`; never hard-code it, and never model it as a closed Python enum.**
`order_type` in this schema is the app's own vocabulary and maps onto whatever that call returns —
the mapping is data, not a `match` statement.

**10. A hand-written span → a range scan.** `E19–53` on One Piece resolves to:

```sql
WHERE title_id = :t AND order_type = 'absolute' AND label = '' AND sequence BETWEEN 19 AND 53
```

One index, one scan, no per-episode storage — and the span keeps meaning something after TMDB
inserts a recap episode, because it was stored as a **range over a numbering** rather than as a
frozen list of episode ids. The cost of that trade is stated honestly: if TMDB inserts an episode at
absolute position 25, `E19–53` still resolves, still returns 35 episodes, and now ends one episode
earlier in the story than the curator meant, and nothing in the data can detect it. `aired` is the
only order guaranteed to exist; when a curated entry names an order a title does not have, the
fallback is **recorded on the entry in `resolution_note`, never silently applied**.

**11. Flattening to a category queue — `curated_entry_item`.**

```
absolute_position = rank over (live entries ordered by curated_entry.position,
                               then by position_in_entry within each entry)
```

`position_in_entry` and `absolute_position` are both **1-based** (`CHECK >= 1`). `absolute_position`
is renumbered for the whole category in one pass at the end of the ingest transaction, which the
deferred unique on `(category_id, absolute_position)` makes a single `UPDATE`. The two questions the
ten-foot UI asks constantly — *"what do I play next"* and *"how far through this category am I"* —
are then both `ORDER BY absolute_position`, one indexed scan. Computing them from spans instead
would mean a lateral join per entry against `episode_order` on every render: 141 laterals for
Marvel, 202 for DCU. A movie entry contributes exactly one item, at `position_in_entry = 1`, so the ranking interleaves films and episodes exactly as the workbook orders them — which is what makes *"what do I play next"* correct for a mixed category like One Piece, and what Next and Autoplay walk in Phase 3.

**12. Deriving a status from the append-only `watch_event` log.** Two views, both `DISTINCT ON`,
which is why the partial indexes on `watch_event` are ordered
`(subject, occurred_at, recorded_at, id)`.

*Per episode* — `episode_watch_state`:

```sql
SELECT DISTINCT ON (e.episode_id) e.episode_id, e.kind, e.position_seconds, e.runtime_seconds,
       e.occurred_at, e.category_id
  FROM watch_event AS e
 WHERE e.episode_id IS NOT NULL
 ORDER BY e.episode_id, e.occurred_at DESC, e.recorded_at DESC, e.id DESC;
```

The tie-break chain is deliberate and all three keys are needed: `occurred_at` is **client-supplied**
(a Jellyfin report can arrive late for something watched an hour ago), `recorded_at` is
**server-assigned**, and `id` is the final deterministic tie-break. Without that third key, two
events carrying identical timestamps make the derived status non-deterministic across replans.

*Per curated entry* — `curated_entry_watch_state`, in precedence order:

```
IF an entry-level event exists AND (no unit event yet
                                    OR its occurred_at >= max(unit-level occurred_at))
                                        -> that event's kind
ELSIF episode_total = 0                 -> 'unset'
ELSIF skipped = total                   -> 'skipped'
ELSIF completed + skipped = total       -> 'completed'
ELSIF completed + started > 0           -> 'progressed'
ELSE                                    -> 'unset'
```

where `started` counts units whose latest kind is `started` **or** `progressed`. Stated plainly:
**an entry-level event at or after the latest unit-level event in that entry wins; otherwise the
roll-up wins.** That is what lets a coarse "Watched" typed into Excel sit on top of fine-grained
history without erasing it, and lets the next unit-level event take the wheel back automatically.

**A "unit" is a `curated_entry_item` row, which is an episode slot *or* a movie slot.** The revision's
`unit_states` CTE left-joins each item to `episode_watch_state` on `episode_id` and to a
`title_states` CTE — `DISTINCT ON (title_id)` over `subject_kind = 'title'` events, same tie-break
chain — on `movie_title_id`, and `COALESCE`s the two. So a film's state comes from the latest
title-level event, and the counters below it (`episode_total` and the rest, named for the contract in
section 5.15, not for what they count) include that film. Reading this as episodes-only is the one
misreading that breaks mixed categories: a film-only entry would sit at `unset` forever and One Piece
would never complete.

`completed + skipped = total` counting as complete is **the same semantics as
`WatchCounts.trackable = total - skipped`** (rule 1). That is not a coincidence and it must not
drift: the two progress readouts in the app would otherwise disagree about the same category.

**13. Projecting a derived status back onto the four-value cell — `services/watch_mirror.py`.**

```python
_CELL_FOR_KIND = {
    WatchEventKind.COMPLETED:  WATCHED,      # "Watched"
    WatchEventKind.SKIPPED:    SKIPPED,      # "Skip"
    WatchEventKind.STARTED:    IN_PROGRESS,  # "In progress"
    WatchEventKind.PROGRESSED: IN_PROGRESS,
    WatchEventKind.UNSET:      UNWATCHED,    # ""
}
```

One dict, no branching, because the view already collapsed the roll-up into one of five kinds and
those five map onto four cell values with `started` and `progressed` sharing `"In progress"`. Every
constant is imported from `constants.py`; **none is re-declared**. The projection is
**one-directional and lossy by construction** — the cell cannot express "9 of 35 episodes done",
"42 minutes into episode 12", or "1-8 completed and 9-12 skipped" — and the loss is contained by one
rule:

> **The `Watched?` cell is never read as truth. It is read only to detect that a human changed it.**

Mechanically: `observed_watch_cell` is what was last read from the sheet, `mirrored_watch_cell` is
what the app last wrote into it. A cell that differs from `mirrored_watch_cell` is a human edit and
appends **one coarse `excel_mirror` event at the entry level**, with `occurred_at = now()` and a note
recording the literal cell text; it touches no episode event, and by rule 12's precedence it becomes
the entry's status while the episode history stays intact beneath it. The reverse write is throttled
to real changes — an entry is written back only when
`watch_cell(state.kind) != entry.mirrored_watch_cell` — and `mirrored_watch_cell` updates in the
same transaction as the `apply_changes` call, which is what makes the mirror idempotent and stops the
echo loop.

</required_calculations>

---

<inventory>

## 12. Directory structure & key entrypoints

Everything below was read off the tree. Where a comment in the repo contradicts the tree, the tree wins and the stale comment is named.

### 12.1 Repository root

```
TV/
├─ *.xlsx                     THE DATABASE. 19 workbooks, one per category, committed on purpose.
│                             Attack_On_Titan, Bleach, DCU, Demon_Slayer, Fullmetal_Alchemist,
│                             HunterXHunter, Inuyasha, Marvel, Middle_Earth, Misc_Anime,
│                             Misc_Movies, Misc_TV, My_Hero_Academia, Naruto, One_Piece,
│                             Pokemon, Star_Wars, WWII, Yu-Gi-Oh!.
│                             The three comments that used to undercount them — `docker-compose.yml:42`,
│                             `README.md:47` and `.gitignore:4` — all say nineteen since T01c.
│                             No code counts them; the prose is now correct.
├─ README.md                  Repository-facing: what is here, clone-and-run, CI, ports, licensing.
├─ docker-compose.yml         Four services, plus three named volumes. Compose v2,
│                             `name: tv-watchlist`. backend, frontend, `postgres` (T09 —
│                             `postgres:16-alpine`, `127.0.0.1:5525:5432`, and the backend's
│                             `depends_on: service_healthy` edge) and `jellyfin` (T47a —
│                             `jellyfin/jellyfin:12.1`, `8096`, no `depends_on`). Both landed
│                             2026-09-20; neither has been started on this machine (VPN).
├─ media/                     PHASE 3, gitignored (T47a). The owner's own video files, bind-mounted
│                             read-only into the Jellyfin container as `/media`. Never committed,
│                             never read by the backend — only Jellyfin's index of it is.
├─ run_tv.sh                  bash launcher. Host-native servers, but since T32a it starts the compose
│                             Postgres first and applies the migrations. `[r]`/`[k]`/`[q]`/`[v]`.
├─ run_tv.bat                 Windows launcher. Same contract, plus per-line `[backend]`/`[frontend]`
│                             prefixing through two PowerShell pipelines.
├─ .gitattributes             LF for `*.sh`, CRLF for `*.bat`, `binary` for every `.xlsx` and raster.
│                             The `.xlsx` binary line is the single most load-bearing line in the repo.
├─ .gitignore                 Banner states the workbooks ARE the database. Do not add `*.xlsx`.
├─ .semgrepignore             Replaces semgrep's built-in defaults, so the usual suspects are restated.
├─ .env.example               T01b, grown to 23 `TV_` variables by T48/T60. Placeholders only, one
│                             comment each. The ONE `.env*` file that is committed
│                             (`.gitignore:32`'s `!.env.example`) and the one an agent may write. The
│                             real `.env` is owner-typed.
├─ scripts/hooks/             T01a, TRACKED. The OS-agnostic Node hook set the `.claude/` wiring
│  │                          points at — `.cjs` only, tool data read from stdin.
│  ├─ hookUtils.cjs           Shared stdin parse / decision helpers.
│  ├─ session-start.cjs       Orientation banner: phase, build order, re-read reminder.
│  ├─ pre-tool-use.cjs        BLOCKS `.env*` (bar `.env.example`), `credentials.*`, `secrets.*`,
│  │                          `*.pem`, `*.key`, `*.p12`, and any direct Write/Edit of an `*.xlsx`.
│  ├─ post-tool-use.cjs       Injects the invariants for the path just edited.
│  ├─ pre-compact.cjs         Tells the summariser what to preserve.
│  ├─ stop.cjs                Flags uncommitted state. Never suggests a commit — git is the owner's.
│  ├─ stop-memory.cjs         Memory upkeep at turn end.
│  └─ hooks.test.cjs          31 tests. `node --test scripts/hooks/hooks.test.cjs` — the FILE form;
│                             the directory form fails on Node 24.
├─ .claude/                   T01a, LOCAL ONLY (`.gitignore:27`). `settings.json` with six PascalCase
│                             hook entries pointing at `scripts/hooks/`, six `commands/` (scaffold,
│                             review, pre-commit, validate, phase-status, new-model) and five
│                             `skills/` (phase-awareness, excel-safety-protocol, data-driven-check,
│                             validation-protocol, dual-store-protocol). Does not travel with a clone.
├─ docs/                      NEW in this change. Root-level project docs; section 17 says which
│  │                          document changes for which kind of change.
│  ├─ TV_MASTER_PLAN.md       The authoritative master plan. Phases, gates, architecture, security.
│  ├─ status.md               Live state: what was just built, what is next. Not a history log.
│  ├─ versions.md             Semver changelog, newest first.
│  ├─ resolver-dry-run.md     WRITTEN 2026-09-20 (T31, run 2 on the final resolver). The dry-run
│  │                          resolver report, one table per workbook: rows, confirmed,
│  │                          auto-resolved, unresolved, and the worst-confidence examples. 830 of
│  │                          996 auto-resolved (83%), 166 for the review queue. Regenerate with `uv
│  │                          run python -m tv_watchlist.resolver.dry_run --out
│  │                          ../../docs/resolver-dry-run.md` (the `--out` path must end in `.md` —
│  │                          any other suffix is refused before a single live call, Ruling 56),
│  │                          which makes live TMDB calls. It lives here rather than in `status.md`
│  │                          because `status.md` is explicitly not a log, and this report is
│  │                          evidence that has to survive the next status rewrite.
│  └─ phases/                 Per-phase task breakdowns, supplementary to the master plan.
│     ├─ phase-1-plan.md      T04–T33: the data layer, resolver, ingest, providers, mirror.
│     └─ phase-3-plan.md      PLANNED, not yet written (when Phase 1 closes). T46–T58: Jellyfin
│                             compose service, client, sync, availability, stream proxy, player,
│                             position reporting, picker, unresolved view, launcher (ADR-014).
│                             Built after the Phase 1 gate; Phase 2 is deferred. Until it exists,
│                             the Phase 3 task table in `TV_MASTER_PLAN.md` and ADR-014 carry it.
├─ .github/workflows/
│  ├─ ci.yml                  462 lines. lint → sast → test → coverage gate → build → docker-build.
│                             `test-backend` carries a real Postgres 16 service container (T10).
│  └─ codeql.yml              57 lines. `python` + `javascript-typescript`, `security-and-quality`,
│                             weekly cron `17 4 * * 1`. Gates nothing in `ci.yml`.
├─ diff-faithfulness.png      Four local debugging screenshots, gitignored (`.gitignore:87-90`),
├─ dock-bug.png               present on disk, untracked. Artefacts of layout bugs already fixed.
├─ hero-dock-1280x720-fixed.png
└─ hero-dock-1512x900-fixed.png
```

Two things a reader coming from an older copy of this file will expect to be missing, and one that really is:

- **The `.claude/` wiring exists** (T01a, done 2026-09-20), split across two places on purpose. `scripts/hooks/` is **tracked**, so a clone gets the hook bodies; `.claude/` itself is **gitignored** (`.gitignore:27`), so settings, commands and skills stay local. Node `.cjs` only — never shell, never `jq`, never PowerShell, because cmd.exe cannot parse a shell hook body and `python3` is absent on Windows — and tool data is read from **stdin**, not from `$CLAUDE_*` environment variables. The `PreToolUse` hook is a real guard now: `.env*` (bar `.env.example`), credential and key files, and any direct `Write`/`Edit` of an `*.xlsx` are refused.
- **`.env.example` exists** (T01b, done 2026-09-20): 16 `TV_` variables with placeholders and one comment each, committed through the `!.env.example` negation while the owner-typed root `.env` (created 2026-09-15) stays out. `app/backend/tests/test_env_example.py` and `tests/env_example_support.py` fail if it drifts from `Settings`.
- **No `.gitlab-ci.yml`**, and there will not be one — this is a public GitHub repo and GitHub Actions is the only pipeline.

### 12.2 `app/`

```
app/
├─ README.md                  App-facing: how a category works, artwork, safety, the layout guard.
├─ heroes/                    Per-category card artwork, named `<category_id><suffix>`.
│  ├─ ATTRIBUTION.md          `| Category | Source file | Licence | Page |` markdown table,
│  │                          written by `services/attribution.py`. CC BY items depend on it.
│  └─ *.png / *.jpg           Wikimedia Commons marks, cropped and recoloured for a dark card.
├─ docs/
│  └─ chat-feature-design.md  Design note for the chat/agent subsystem. `app/docs/` stays design
│                             notes only — project docs live in the root `docs/`.
├─ .backups/                  Pre-write snapshots + retirements. Gitignored, local history.
├─ backend/                   See section 12.3.
└─ frontend/                  See section 12.4.
```

### 12.3 `app/backend/` — FastAPI + openpyxl

**220 Python modules / 19,023 lines under `src/tv_watchlist`**, measured 2026-09-23 with
`rg --files` and `wc -l`. The tree below itemises the original workbook app; the following
Phase 1/3/3.5 module list extends it. Hatchling's wheel target remains `src/tv_watchlist`.

```
app/backend/
├─ pyproject.toml             name `tv-watchlist`, version `0.1.0` (SEMVER SOURCE OF TRUTH, :3),
│                             `requires-python >=3.13`, ruff `line-length 120` +
│                             `select ["E","F","I","N","UP","ANN","S"]` (:33-41),
│                             pytest `asyncio_mode="auto"` (:43-48). No `[tool.coverage]`.
├─ uv.lock                    Frozen. `uv sync --frozen` everywhere; never resolve in CI.
├─ Dockerfile                 112 lines, two stages, both `python:3.13-slim` (never alpine — musl has
│                             no manylinux wheels). `WORKDIR /srv/app/backend` in BOTH stages because
│                             `config.py:17` computes `parents[4]` at import — the reason is spelled
│                             out in the comment at `Dockerfile:26-32`. Deletes the
│                             bundled 340 MB `claude` binary (:44-46) so chat 503s cleanly. COPYs
│                             `alembic.ini`, `alembic/`, `data/` and the entrypoint (:54-58, T09).
│                             Deletes pip/pkg_resources to clear trivy HIGH (:79-82). Non-root
│                             uid 10001. `CMD` is the entrypoint (:112), never uvicorn directly.
├─ docker-entrypoint.sh       T09. 11 lines: `alembic upgrade head`, then `exec uvicorn`. A migration
│                             that keeps failing is a crash loop by design. Section 6.3.
├─ alembic.ini / alembic/     Revisions `0001` → `0002` → `0003` → `0004` → `0005`; one head.
├─ data/                      OUTSIDE the package (Ruling 22). `franchise_prefixes.json`, the
│                             resolver's seed, read by `resolver/franchise.py:16`. Not in the wheel;
│                             it reaches the image only through the Dockerfile `COPY data ./data`.
├─ .dockerignore              Excludes `.venv/`, caches, coverage, `junit-*.xml`, `tests/`, `.env*`.
├─ tests/                     Mirrors `src/`, plus shared support modules. Since the Phase 0 close:
│                             `env_example_support.py` + `test_env_example.py` (T01b, 19 tests);
│                             `tests/data/` (T05-T10 — base, session, enums, `alembic_support`, the
│                             eleven-table metadata, the first revision and its `--sql` round trip,
│                             the live migration round trip, the append-only trigger, `db_session`);
│                             `tests/clients/` (T12-T14 — errors, the SSRF/loopback guard, the rate
│                             limiter, the response cache, the transport, the TMDB and TheTVDB
│                             clients); `tests/models/` (the provider response models, plus the
│                             Phase 1 read/write models); `tests/resolver/` (`match_key`,
│                             `franchise`, `span`, the resolution stack, the dry run);
│                             `tests/ingest/` (the cache, the TMDB ingest, the episode orders, the
│                             reconciler, the expansion, `bootstrap`, plus `ingest_support.py`, the
│                             recorded harness); `tests/fixtures/` (the recorded TMDB and TheTVDB
│                             bodies with their header sidecars, plus `tests/fixtures/jellyfin/` since
│                             T48 — six hand-authored bodies + `health.txt`, and a `README.md`
│                             recording the Ruling 51 exception and the schema source); `test_compose.py` and
│                             `test_docker_entrypoint.py` (T09, 46 between them);
│                             `test_launchers.py` (T32a, 4); plus `database_support.py`,
│                             `compose_support.py`, `backup_support.py`, `provider_fixtures.py`,
│                             `lifespan_support.py`, `statement_support.py` (the one engine-bound
│                             statement tap), `ts_types.py` (the Python↔TypeScript mirror check),
│                             `workbook_edits.py` (shared sheet edits such as
│                             `narrow_the_status_dropdown`), `review_support.py`, `retirement_files.py`,
│                             `workbook_facts.py` and the autouse `declared_env_file` fixture in
│                             `conftest.py`. Test-to-test duplication is extracted when it is found,
│                             not deferred (Ruling 42).
└─ src/tv_watchlist/
   ├─ main.py            61   App factory, CORS (two origins from `frontend_port`), error handlers,
   │                          **six routers** (`categories`, `entries`, `review`, `rows`,
   │                          `watch_events`, `chat`), `/heroes` StaticFiles mount, lifespan closing
   │                          the agent runtime, the ingest runtime (only if something ingested —
   │                          guarded by `cache_info`) and the database engine, in that order.
   ├─ config.py          64   `Settings` (pydantic-settings, env prefix `TV_`) + `get_settings()`.
   ├─ constants.py      224   Every universal constant. The only place hard numbers live.
   ├─ clock.py                `utcnow()` — the one timezone-aware clock the ingest and mirror inject.
   ├─ api/
   │  ├─ dependencies.py 33   `get_catalog()` / `get_hero_store()` / `get_ingest_runtime()`
   │  │                       `lru_cache(maxsize=1)` singletons.
   │  ├─ errors.py      113   Exception → HTTP status/message tables, `payload_for()`, `register()`.
   │  ├─ entries.py      35   `GET /api/categories/{id}/entries` (T28).
   │  ├─ review.py       64   The resolution review queue and one decision (T30).
   │  ├─ watch_events.py 52   `POST /api/watch-events` and the derived-progress GET (T29).
   │  ├─ categories.py   62   Router `/api/categories`.
   │  ├─ rows.py         39   Router `/api/categories/{category_id}/rows`.
   │  └─ chat.py        134   Router `/api/chat`. SSE, approve, hero choice.
   ├─ models/                 One Pydantic contract per file (28 files), plus `tmdb/` and `tvdb/`.
   │  ├─ column_spec.py       `ColumnSpec` + `ColumnKind` / `ColumnRole` literals.
   │  ├─ watch_row.py         `WatchRow` — `row: int = Field(ge=2)`, `cells: dict[str,str]`.
   │  ├─ watch_counts.py      `WatchCounts` — six `ge=0` ints.
   │  ├─ category_summary.py  `CategorySummary` — the sidebar/card shape, carries `mtime`.
   │  ├─ category_detail.py   `CategoryDetail(CategorySummary)` + columns / rows / reference_sheets.
   │  ├─ catalog_listing.py   `CatalogListing` — categories + unreadable + shadowed + library_dir.
   │  ├─ reference_sheet.py   `ReferenceSheet` — a read-only companion sheet.
   │  ├─ shadowed_workbook.py `ShadowedWorkbook` — a file unreachable behind a namesake.
   │  ├─ unreadable_workbook.py `UnreadableWorkbook` — a file that would not parse.
   │  ├─ cell_text.py         `sanitize()` — the ONLY cell-text normaliser.
   │  ├─ row_write.py         `RowWrite` + `sanitized_cells()`. `expected_mtime` required.
   │  ├─ category_create.py   `CategoryCreate` + validators + `column_keys()`.
   │  ├─ category_rename.py   `CategoryRename` — `stem` + `expected_mtime`.
   │  ├─ row_change.py        `RowChange` + `RowChangeKind` + the kind-coherence validator.
   │  ├─ proposal.py          `Proposal` — id, summary, sources, discriminated `body`.
   │  ├─ proposal_create.py   `ProposalCreate` (`kind="create"`); requires `category.rows`.
   │  ├─ proposal_edit.py     `ProposalEdit` (`kind="edit"`); carries backend-minted `read_mtime`.
   │  ├─ proposal_hero.py     `ProposalHero` (`kind="hero"`); 1..3 candidates.
   │  ├─ hero_candidate.py    `HeroCandidate` — url / source_file / licence / page / description.
   │  └─ chat_event.py        `ChatEvent` — one SSE frame; only `type` is required.
   ├─ workbook/               The Excel layer. Nothing above it touches openpyxl.
   │  ├─ errors.py       47   `WorkbookError` + **ten** subclasses (`workbook/errors.py:6-46`):
   │  │                       `CategoryNotFoundError`, `WorkbookLockedError`, `StaleWorkbookError`,
   │  │                       `MissingWatchColumnError`, `UnknownColumnError`, `InvalidChoiceError`,
   │  │                       `DuplicateCategoryError`, `RowNotFoundError`, `UnreadableWorkbookError`,
   │  │                       `InvalidNameError`. Nine of the ten are in `_STATUS_BY_ERROR`;
   │  │                       `InvalidNameError` is the one that is not, which is why the status
   │  │                       table below shows it answering 400 by default.
   │  ├─ schema.py      128   Derive `ColumnSpec`s from the header run + data validations.
   │  ├─ cells.py        46   `cell_text()`, `table_last_row`, `is_blank_row`, `last_data_row`.
   │  ├─ ranges.py      130   Keep table / dropdown / conditional-format ranges covering rows 2..last.
   │  ├─ reader.py      129   `read_category(path) -> CategoryDetail`.
   │  ├─ writer.py      469   Every in-place mutation + the atomic temp-file-and-`os.replace` save.
   │  ├─ creator.py     149   `create_category(library_dir, request) -> Path`.
   │  ├─ renaming.py     41   `rename_workbook(path, stem) -> Path`.
   │  ├─ discovery.py    36   `workbook_paths`, `resolve`, `addressed_by`.
   │  ├─ naming.py       33   `slugify`, `category_id`, `workbook_filename`.
   │  ├─ stem.py         30   `validate_stem` — filesystem-legal filename stem check.
   │  ├─ locking.py      39   Per-workbook `asyncio.Lock` registry + Excel-lock detection.
   │  ├─ freshness.py    17   `guard_fresh` + `MTIME_TOLERANCE_SECONDS = 1e-6`.
   │  ├─ backup.py       85   `snapshot()` with per-path throttle, `free_destination`, `_prune`.
   │  ├─ backup_names.py 38   The `<stem>__<stamp>` filing convention.
   │  ├─ styling.py      33   `apply_header_style`, `apply_body_style`, `clone_style`.
   │  └─ heroes.py       29   `hero_files`, `hero_file`, `move_heroes`, `artwork_key`.
   ├─ services/
   │  ├─ catalog.py     254   `Catalog` — THE MUTATION FUNNEL. Cache, lock, freshness, snapshot,
   │  │                       write, invalidate, re-read.
   │  ├─ retirement.py   36   `retire_category(...)` — moves, never unlinks.
   │  ├─ hero_store.py   98   `HeroStore.save()` — SSRF guard, size cap, magic bytes, attribution.
   │  ├─ hero_backup.py  25   `retire_heroes()` — move superseded artwork aside.
   │  ├─ image_format.py 36   `image_suffix(bytes)` — PNG/JPEG/GIF/WEBP only. SVG deliberately absent.
   │  └─ attribution.py 103   The `ATTRIBUTION.md` markdown-table writer.
   └─ agent/                  The chat/research subsystem — **27 `.py` files**, counting the two
      │                       package markers the rest of this tree would otherwise omit.
      ├─ __init__.py      0   Empty package marker.
      ├─ constants.py    83   Model, effort, permission mode, tool names, fetch caps, markers.
      ├─ errors.py       47   `AgentError` + **ten** subclasses (`agent/errors.py:6-46`):
      │                       `BlockedUrlError`, `FetchFailedError`, `UnknownSessionError`,
      │                       `UnknownProposalError`, `HeroDownloadError`, `UnsupportedImageError`,
      │                       `UnsafeHeroPathError`, `HeroChoiceRequiredError`,
      │                       `NoHeroCandidatesError`, `UnknownHeroCandidateError`.
      ├─ dependencies.py 16   `get_agent_runtime()` singleton.
      ├─ runtime.py      28   `AgentRuntime` — catalog, sessions, fetcher, client factory, `aclose()`.
      ├─ registry.py     92   `SessionRegistry` — create/get/close, idle eviction, proposal lookup.
      ├─ session.py     211   `ChatSession` — one SDK client, one pending proposal, `abandon()`.
      ├─ options.py      35   `build_agent_options()` — fully explicit `ClaudeAgentOptions`.
      ├─ prompt.py       88   `RESEARCH_SYSTEM_PROMPT`.
      ├─ agent_client.py 20   `AgentClient` Protocol (connect / query / receive_response / disconnect).
      ├─ server.py       28   `build_library_server()` — the in-process MCP server, three tools.
      ├─ tools/__init__.py      0  Empty package marker.
      ├─ tools/get_category.py 45  Read-only tool; stamps the session `ReadLog`.
      ├─ tools/fetch_url.py    71  Fetch tool; untrusted delimiters, transport cap.
      ├─ tools/propose.py     100  THE ONLY WRITE PATH. Mints `id` and `read_mtime`.
      ├─ tool_result.py  10   `ToolResult` alias + `text_result()`.
      ├─ handler_guard.py 25  Logs exceptions the SDK would otherwise swallow.
      ├─ fetcher.py      91   httpx first, Chromium escalation on block signals.
      ├─ fetch_result.py 19   `FetchResult` (`text`, `via`, `truncated`).
      ├─ browser.py      67   `ChromiumReader` — one lazily-launched Playwright Chromium.
      ├─ page_reader.py  13   `PageReader` Protocol.
      ├─ html_text.py    16   `html_to_text()`.
      ├─ url_guard.py    61   `assert_public_http_url()` — the SSRF guard.
      ├─ address_lookup.py 12 `resolve_addresses()` — async `getaddrinfo`.
      ├─ read_log.py     22   `ReadLog` — per-session category→mtime stamps.
      ├─ digest.py       53   `build_library_digest()` — the block that opens a session.
      └─ preflight.py    62   CLI / Chromium presence checks; runnable as `__main__`.
```

**Phase 1 has landed in full, as of 2026-09-20.** Every module below is on disk; T33 is the gate audit, not more code.

- `src/tv_watchlist/data/` — `base.py`, `session.py`, `enums.py`, `alembic_support.py`, `errors.py` (`ProjectionError`, `EntryNotFoundError`, `ResolutionConflictError`, `WatchSubjectNotFoundError` — section 4.3), and `models/` (eleven ORM models, one per file).
- `alembic/` + `alembic.ini`, with the first revision `alembic/versions/0001_phase_1_schema.py` (eleven tables, two views, the append-only trigger).
- `clients/` — `errors.py`, `http_guard.py`, `rate_limiter.py`, `response_cache.py`, `transport.py`, `tmdb_client.py` (T13) and `tvdb_client.py` (T14). **`transport.py` is the one home** of `Cursor`, `ProviderBody`, `elapsed_ms_since`, `retry_after_seconds`, `refusal_for(response, provider)`, `read_json`/`read_text`, `unreachable(provider, error)` and `scrubbed` (Ruling 31) — no client re-declares any of them. Since **T48**: `jellyfin_client.py` (`JellyfinClient`, `build_jellyfin_http`, `build_jellyfin_client`) and `streamed_response.py` (`StreamedResponse`, the narrowed status/headers/body surface `stream()` yields — never the raw `httpx.Response`); `http_guard.py` gained `assert_within_configured_base` and `configured_url`, the `http`-permitting siblings of the https-only `assert_within_base`/`provider_url` pair, shared with Phase 3.5's qBittorrent client.
- `models/tmdb/` (15 modules), `models/tvdb/` (9 modules) and, since **T48**, `models/jellyfin/` (4 modules: `jellyfin_payload.py` the shared `extra="ignore"` base, `jellyfin_item_dto.py`, `jellyfin_item_page.py`, `jellyfin_provider_ids.py`) — the provider response models, one per file, validated at the boundary.
- `models/` also gains the Phase 1 read and write contracts, one per file: `title_read.py`, `episode_read.py`, `entry_progress.py`, `curated_entry_read.py` (T28), `watch_event_create.py`, `watch_event_read.py` (T29) and `resolution_update.py` (T30). Section 5.15 carries all seven.
- `resolver/` — `match_key.py`, `franchise.py` (T16), `span.py` (T17), then the T18 resolution stack: `resolution_request.py`, `candidate.py`, `scoring.py`, `verification.py`, `title_resolution.py`; plus `dry_run.py` / `dry_run_report.py` (T31), which write `docs/resolver-dry-run.md`. **`resolver/` imports nothing from `ingest/`** (Ruling 39).
- `ingest/` — its own top-level package, not a corner of `services/`: `sync_cursor.py` (T15's `PostgresResponseCache`), `tmdb_ingest.py`, `ingest_outcome.py`, `artwork_candidate.py` (T19), `episode_orders.py`, `tvdb_matching.py` (T20), `reconciler.py`, `workbook_digest.py`, `reconcile_outcome.py`, `errors.py`, `runtime.py` (T23), `expansion.py` (T24) and `bootstrap.py` (T27, the first-ingest CLI — section 15.7). **T57 extracts `reconciler._resolve_one()`'s tail into `_answered()` and adds the public `resolve_stored_entry()`** — the same resolution leg run from a stored entry's own cells rather than a live sheet, so `services/resolution_review.retry_resolution()` and the ingest pass share one leg (`_store_resolution`, `_leave_unresolved`, `_ingested` reused verbatim, never copied); the full backend suite proved the refactor behaviour-identical.
- `services/` gains `tmdb_key.py`, `artwork_cache.py` (T19), `watch_mirror.py` + `mirror_outcome.py` (T25), `entries.py` (T28), `watch_events.py` (T29) and `resolution_review.py` (T30). **T57 adds `resolution_review.retry_resolution()`** beside the existing `confirm`/`correct`/`reject` handling, plus `_workbook_name()`, `_category_of()` and the `ALREADY_CONFIRMED` constant; `entries.py` gains `_slugs_for()` for `CuratedEntryRead.category_slug` (R82).
- `api/` gains `entries.py` (T28), `watch_events.py` (T29) and `review.py` (T30) — the five routes of section 13.5. **T57 (Phase 3, built and reviewed) adds a sixth route to `review.py`**: `POST /entries/{entry_id}/retry`, section 13.5.
- `workbook/` gains exactly two modules: `identity.py` (T22, the hidden `Row ID` column) and `curated_columns.py` (Ruling 39 — "which column is title / unit / release / type", moved out of `ingest/` so the resolver can ask without importing the ingest). **T57 adds `curated_columns.raw_type_cell(cells)`** — the Type/Format cell read back out of a stored entry's `raw_cells` by the slug `unique_key` mints, since a re-resolve works from `curated_entry`'s stored columns rather than a live `ColumnSpec` list and still has to answer Ruling 27's "blank `Unit` is not `movie @ 1.00`" question.
- `clock.py` at the package root, and, outside `src/`, `data/franchise_prefixes.json` (the resolver seed, Ruling 22) and `docker-entrypoint.sh` (T09).

**Phase 3/3.5 modules built and reviewed after the Phase 1 close (2026-09-21):**

- T49: `data/models/jellyfin_item.py`, revision `0002_phase_3_jellyfin_item.py`,
  `services/library_sync.py`, `models/library_sync_result.py`, and `api/library.py`.
- T50: `services/episode_match.py` and `services/episode_lookup.py`; stored numbering and printed
  season/episode joins, range files and dangling picks, with no name matching.
- T57: the unresolved view and the retry route, as detailed above.
- T61: `data/models/media_import.py`, `models/media_import_read.py`, and `0003_media_import.py`.
  T66 adds `data/models/media_import_operation.py` and revision `0004`.
- T53a's durable-history foundation adds `data/models/playback_completion.py`,
  `data/models/playback_completion_event.py` and revision `0005`: sixteen domain tables,
  single migration head `0005` (`alembic_version` is separate).
  `services/playback_completion.py` records exact event membership; `playback_queue_snapshot.py`
  captures semantic curation through the frozen `models/playback_coverage.py`,
  `playback_occurrence.py` and `playback_queue_snapshot.py` contracts.
- T62: `clients/qbittorrent_client.py`, shared `clients/configured_upstream.py`, and the two frozen
  models under `models/qbittorrent/`; a cached dependency and lifespan-owned HTTP client.
- T63: `services/media_filename.py` and `services/import_naming.py`, boundary B22.

T51 computed availability and T64 import discovery are also built and independently reviewed;
neither introduces a migration. Availability's dedicated result/selection modules extend the shared
episode matcher with page batching. Discovery separates `import_scan`, `import_discovery`,
`import_candidate` and `models/import_scan_result`, with matching tests and no HTTP surface yet.
T52 adds `api/playback`, `api/playback_response`, `services/playback_items` and the frozen
`models/playback_item_read` contract; frontend badges, entries slice and player use actual slot file
IDs. T65 adds `services/import_filename`, `services/import_identify`, `models/filename_parse` and
`models/identify_pass_result`; no import HTTP surface or migration is added.
T53 adds `models/position_write`, `services/playback_entry`, `playback_events`, `playback_position`
and `workbook/position`; the existing writer/Catalog funnel owns the combined workbook mutation.
T53a moves the category-lock helper to `services/locked_curated_entry` for reuse by resolution
review, and adds `data/episode_order_lock` plus `ingest/episode_order_busy_error` for coherent
completion evidence during provider refreshes.
TMDB's actual episode upsert uses the same exclusive try-lock, including TMDB-only configurations;
provider-client construction is unchanged.
The frontend adds the reporter, save-job slice, retry control and paired API calls. T66 adds
`services/import_move`, `import_files`, `file_digest`, `import_source_lock`, `rename_exclusive` and
the frozen `models/import_file_identity`; the durable journal is described in §5.18.
Still separate future work: Next/Autoplay (T53a), offers
(T55, including `streaming_offer`), the picker (T56), launcher (T58), and import
refresh, routes and deployment wiring (T67–T69). `ImportNamingError` and `ImportPathError`
already exist, but T68 still owes their API status/message registrations. No import task writes a
workbook.

### 12.4 `app/frontend/` — React 18 + TS strict + Vite + RTK

```
app/frontend/
├─ package.json          name `tv-watchlist-frontend`, version `0.1.0` (SEMVER SOURCE OF TRUTH, :4),
│                        `packageManager: pnpm@9.15.9` (:6). No router, no chart library, no CSS
│                        framework, no UI kit — the whole UI is hand-written CSS.
├─ pnpm-lock.yaml        lockfileVersion 9.0. `--frozen-lockfile` everywhere.
├─ tsconfig.json         One file, no project references. `strict` plus `noUnusedLocals`,
│                        `noUnusedParameters`, `noFallthroughCasesInSwitch`, `noUncheckedIndexedAccess`,
│                        `exactOptionalPropertyTypes`, `verbatimModuleSyntax`. `include` covers
│                        `src`, `tests`, `layout` — which is why `pnpm build` typechecks the guard.
├─ vite.config.ts        Ports from `TV_BACKEND_PORT` / `TV_FRONTEND_PORT`, `strictPort: true`,
│                        dev proxy `/api` and `/heroes` → `127.0.0.1:${backendPort}`.
├─ vitest.config.ts      jsdom, `setupFiles: ["./tests/setup.ts"]`, v8 coverage over `src/**`
│                        excluding `src/main.tsx`. NO thresholds block — the floors live in CI.
├─ eslint.config.js      Flat config. `no-explicit-any` promoted to error. No security plugins.
├─ index.html            `<meta name="color-scheme" content="dark">`, title `Watch List`.
├─ nginx.conf            Serves `dist/`, proxies `/api` and `/heroes` to `backend:8284`, declares
│                        every security header once at server level (section 6).
├─ Dockerfile            `node:22-alpine` build → `nginxinc/nginx-unprivileged:alpine` on 8080.
├─ public/favicon.svg
├─ src/
│  ├─ main.tsx           Entry. Five fontsource imports + `index.css`; asserts `#root`.
│  ├─ App.tsx            The shell. Loads catalog on mount, category on `activeCategoryId` change,
│  │                     re-reads both on window focus UNLESS a write is pending. `refresh()` also
│  │                     re-reads the review queue when `view === "unresolved"` (T57).
│  ├─ index.css          Nine `@import`s in cascade order — `unresolved.css` added last, after `chat` (T57).
│  ├─ types/       20    One contract per file. snake_case where it crosses the wire. `AppView.ts`
│  │                     now carries three values: `"home" | "category" | "unresolved"` (T57).
│  ├─ api/         19    One call per file, all through `request.ts`. `ApiError.isStale` is the
│  │                     stale-mtime discriminator. T57 adds `fetchReviewQueue.ts` (pages
│  │                     `?limit=REVIEW_PAGE_SIZE&offset=n`), `reviewEntry.ts` (the per-row Confirm,
│  │                     `POST /api/review/entries/{id}`) and `retryResolution.ts`
│  │                     (`POST /api/review/entries/{id}/retry`) — three files because a Confirm
│  │                     call and a Retry call are two different requests, one call per file.
│  ├─ stores/       8    `store.ts` (five slices), `catalogSlice`, `categorySlice`, `chatSlice`,
│  │                     `reviewSlice` (T57 — the unresolved queue), `uiSlice`, plus `writeQueue.ts`
│  │                     and `writeFailure.ts` — the last two are module state OUTSIDE Redux, because
│  │                     a thunk's promise settles before the store commits its result.
│  ├─ hooks/        9    `useAppDispatch`, `useAppSelector`, `useAccent`, `useFilteredCategories`,
│  │                     `useFocusTrap`, `useRowColumns`, `useStandingRows`, `useVisibleRows`,
│  │                     `useWatchColumn`.
│  ├─ utils/       14    `accentPalette`, `anchorOf`, `categoryIn`, `entryCount` (T57 — extracted so
│  │                     `summarise.ts` and `UnresolvedView` share one entry-count phrase rather than
│  │                     two), `identifyRow`, `isHttpUrl`, `matchesFilter`, `motifFor`,
│  │                     `nextWatchStatus`, `progressPercent`, `resolutionStateLabel` (T57, following
│  │                     `statusLabel.ts`'s shape — the state vocabulary lives in exactly one map),
│  │                     `standingRowsIn`, `statusLabel`, `summarise`.
│  ├─ components/  35    See the screen inventory below (`ProviderAttribution.tsx`, T32, was already
│  │                     on disk and is folded into this count for the first time here). T57 adds
│  │                     `UnresolvedView.tsx`, `UnresolvedRow.tsx` and `RetryResolutionButton.tsx`.
│  └─ styles/       9    `tokens.css` (55), `base.css` (146), `sidebar.css` (219),
│                        `category.css` (281), `route.css` (280), `home.css` (198),
│                        `overlays.css` (227), `chat.css` (520), `unresolved.css` (95, T57 — the
│                        nav-entry rule itself lives in `sidebar.css`, sharing `.category-link`'s
│                        selector list rather than duplicating it).
├─ tests/                25 `.test.ts(x)` files + `setup.ts` + `support/` builders (T57 adds
│                        `components/UnresolvedView.test.tsx`, `components/RetryResolutionButton.test.tsx`
│                        and `support/aCuratedEntryRead.ts`).
└─ layout/               The layout guard. Its own Vite root, its own port, its own fixtures.
   ├─ playwright.config.ts   Four chromium projects: 1512x900, 1280x720, 1024x768, 960x1040.
   ├─ probeServer.ts         `TV_LAYOUT_PORT`, default 5286.
   ├─ vite.config.ts         Roots at `layout/probes`, binds 127.0.0.1 explicitly.
   ├─ surfaces.ts            The 19 surfaces and what each promises — T57 adds `"unresolved-view"`.
   ├─ specs/                 `controls.spec.ts` (2 tests × 19 surfaces), `proposalDiff.spec.ts` (2),
   │                         `attribution.spec.ts` (1).
   ├─ support/               `openProbe.ts`, `measureControls.ts`.
   └─ probes/                17 files + `public/stub-artwork.png`. The fake backend and arrangements —
                             T57 adds `aLibraryWithUnresolvedRows.ts` and a `queue` field on
                             `ProbeLibrary` that every trouble-library probe now carries.
```

</inventory>

---

<endpoints>

## 13. Endpoint inventory

**Twenty-one HTTP operations on eighteen OpenAPI paths exist today (measured 2026-09-23):**
Phase 0's fourteen, Phase 1's five, T57's retry and T49's library sync. Both Phase 3 additions are
reviewed. T51 extends response fields and T64 is a service only; neither adds a route.
**There is no `/health` endpoint** — compose probes `/openapi.json`, which touches no workbook.

Every error response, whatever the status, carries the same envelope:

```json
{ "error": "<ExceptionClassName>", "message": "<humanised>", "detail": "<str(error)>" }
```

built by `api/errors.py:69-73` (`def payload_for`). Status lookup is by **exact type**, never by MRO — a `WorkbookError` or `AgentError` subclass absent from `_STATUS_BY_ERROR` falls through to **400**.

### 13.1 Categories — `api/categories.py`

| # | Method | Path | Request | Response | Success | What it does |
|---|---|---|---|---|---|---|
| 1 | GET | `/api/categories` | — | `CatalogListing` | 200 | Rescans the library folder on every call. Returns readable categories, the files that would not parse, the files hidden behind a namesake, and the library path. |
| 2 | POST | `/api/categories` | `CategoryCreate` | `CategoryDetail` | **201**, or **422** | Generates a brand-new workbook in the library folder, styled and tabled like a hand-built one. Since T22 a request whose `columns` name an **app-owned** header — anything normalising into `APP_OWNED_HEADER_ALIASES`, which today means `Row ID` — is refused by `CategoryCreate._reject_app_owned_columns` (`models/category_create.py:41-47`) with `"… is a column the app owns; pick another name"`. That is a Pydantic validator on the body, so it answers **422** in FastAPI's own `{"detail": [...]}` shape, not the project's `{error, message, detail}` envelope. |
| 3 | GET | `/api/categories/{category_id}` | — | `CategoryDetail` | 200 | One category with its full grid and its read-only reference sheets, read under the workbook lock. |
| 4 | DELETE | `/api/categories/{category_id}` | query `expected_mtime: float` **required** | `CatalogListing` | 200 | **Retires**, does not delete. Moves the workbook and every hero suffix into `.backups` under one shared `retired-<stamp>`. Answers with what is left, not with the removed category. |
| 5 | POST | `/api/categories/{category_id}/rename` | `CategoryRename` | `CategoryDetail` | 200 | Renames the file. The category id is derived from the filename, so **the id in the response differs from the id in the path**. Artwork is carried across. |
| 6 | POST | `/api/categories/{category_id}/watch-column` | query `expected_mtime: float` **required** | `CategoryDetail` | 200 | Appends a standard `Watched?` column with the four-value dropdown and the green `Watched` highlight. No-op if one already exists. |

### 13.2 Rows — `api/rows.py`

| # | Method | Path | Request | Response | Success | What it does |
|---|---|---|---|---|---|---|
| 7 | POST | `/api/categories/{category_id}/rows` | `RowWrite` | `CategoryDetail` | 200 | Appends a row at the end, cloning the previous last row's style, filling the order column and resequencing if it read `1..N`. |
| 8 | PATCH | `/api/categories/{category_id}/rows/{row}` | `RowWrite` | `CategoryDetail` | 200 | Writes one row's cells. **The only write the backup throttle coalesces** (15 min default). |
| 9 | DELETE | `/api/categories/{category_id}/rows/{row}` | query `expected_mtime: float` **required** | `CategoryDetail` | 200 | Deletes one row, re-anchoring hyperlinks and merges around the shift. |

Every row endpoint returns **the whole reloaded `CategoryDetail`**, never just the changed row. `row` is an unconstrained `int` at the route boundary; range checking happens in `workbook/writer.py:203-204` and `:246-247` and produces `RowNotFoundError` → 404.

### 13.3 Chat — `api/chat.py`

| # | Method | Path | Request | Response | Success | What it does |
|---|---|---|---|---|---|---|
| 10 | POST | `/api/chat/sessions` | — | `{"session_id": str}` | 200 | Starts a conversation and hands back the id every later call addresses it by. |
| 11 | POST | `/api/chat/sessions/{session_id}/messages` | `{"text": str}` embedded, `max_length=16000` | `StreamingResponse`, `text/event-stream` | 200 | One turn as `data: <json>\n\n` frames, one per `ChatEvent`, `exclude_none=True`. Headers are exactly `Cache-Control: no-cache, no-transform` and `X-Accel-Buffering: no`. |
| 12 | POST | `/api/chat/proposals/{proposal_id}/approve` | — | `CategoryDetail` or an error envelope | 200 or **409** | Writes what Claude proposed, through the same `Catalog` funnel the REST endpoints use. `WorkbookLockedError`, `StaleWorkbookError`, `UnknownColumnError` and `InvalidChoiceError` become an explicit 409 and **the proposal stays pending** so the diff on screen is still approvable. |
| 13 | POST | `/api/chat/proposals/{proposal_id}/hero/{choice}` | — | `CategoryDetail` | 200 | Downloads the candidate the user picked, validates it by magic bytes, files it as the category's artwork and credits it in `ATTRIBUTION.md`. `choice` is `ge=0` at the path level (422 for negative); out of range is `UnknownHeroCandidateError`. |
| 14 | DELETE | `/api/chat/sessions/{session_id}` | — | none | **204** | Ends a conversation, dropping whatever proposal it was still holding. |

**Chat answers 503 inside a container**, deliberately and by construction — the image carries neither the `claude` CLI nor Chromium, `ClaudeSDKClient.connect()` raises `CLINotFoundError`, and `api/errors.py:43` maps it to 503. Every other endpoint works normally there.

### 13.4 The status table, as the response contract

| Exception | Status | Message template |
|---|---|---|
| `CategoryNotFoundError` | 404 | `No workbook matches '{detail}'.` |
| `RowNotFoundError` | 404 | `Row {detail} is no longer in this sheet.` |
| `WorkbookLockedError` | **423 Locked** | `{detail} is open in Excel. Close it and try again.` |
| `StaleWorkbookError` | 409 | `{detail} changed on disk. Reloading so your edit does not overwrite it.` |
| `DuplicateCategoryError` | 409 | `{detail} already exists.` |
| `UnknownColumnError` | 400 | `This sheet has no column '{detail}'.` |
| `InvalidChoiceError` | 400 | `That value is not one of the sheet's options ({detail}).` |
| `MissingWatchColumnError` | 400 | `This sheet has no Watched? column yet.` |
| `UnreadableWorkbookError` | **422** | `{detail} could not be opened as a workbook.` |
| `InvalidNameError` | 400 (default) | `{detail}` |
| `CLINotFoundError` | **503** | `Claude Code is not installed, or 'claude' is not on this machine's PATH.` |
| `UnknownSessionError` | 404 | `Chat session '{detail}' has ended. Start a new one.` |
| `UnknownProposalError` | 404 | `Proposal '{detail}' is no longer pending. Ask Claude to propose it again.` |
| `HeroChoiceRequiredError` | 400 (default) | `Artwork is chosen, not approved. Pick one of this proposal's candidates instead.` |
| `NoHeroCandidatesError` | 400 (default) | `Proposal '{detail}' offers a change to approve, not artwork to choose.` |
| `UnknownHeroCandidateError` | 400 (default) | `This proposal has no candidate {detail}.` |
| `EntryNotFoundError` | 404 | `No entry matches '{detail}'. Reload the queue - the sheet may have dropped that row.` |
| `WatchSubjectNotFoundError` | 404 | `No {detail} to record a watch event against.` |
| `ResolutionConflictError` | **409** | `{detail}` |
| `IllegalCharacterError` (openpyxl) | 400, own handler | `That text contains characters Excel cannot store in a cell.` |

The three new rows are the projection's own failures, raised from `data/errors.py` and registered in both tables by T29 and T30. `WatchSubjectNotFoundError`'s `detail` is `f"{subject_kind.value} {subject_id}"`, so the rendered message reads `No curated_entry 4f1c… to record a watch event against.` `ResolutionConflictError` carries its own sentence as the whole message, because the reason is specific each time — no provider configured, TMDB has nothing under that id, the title carries no such numbering — and each of those is worth retrying once something has changed, which is what 409 says.

### 13.5 Phase 1 additions — built; Phase 3 additions — built and planned

**Phase 1 — five routes, built (T28, T29, T30). These exist today.**

| Method | Path | Request | Query | Response | Status | Notes |
|---|---|---|---|---|---|---|
| GET | `/api/categories/{category_id}/entries` | — | `limit` (`1..MAX_ENTRIES_PAGE_SIZE`, default the cap), `offset` (`>= 0`) | `list[CuratedEntryRead]` | 200 | `api/entries.py:24`. The Postgres projection of one category's live rows, in the sheet's own `position` order, served **alongside** the workbook-backed `CategoryDetail`, never instead of it: `CategoryDetail` stays the editing contract and this carries the derived side — resolution, titles, progress. Phase 3 adopts it for its availability-and-progress layer only (ADR-014). **404 `CategoryNotFoundError` before any query runs** — an unknown slug is a 404, not an empty list; a category that exists but has never been ingested is `[]`, which is the honest distinction. `MAX_ENTRIES_PAGE_SIZE` is **500** (`constants.py:193`), and it is the **default as well as the ceiling**, so the ordinary call carries a whole category (the largest is DCU at 202 rows) and an over-large one is refused at the boundary by `Query(le=…)` rather than served. |
| POST | `/api/watch-events` | `WatchEventCreate` | — | **`WatchEventRead`** | **201** | `api/watch_events.py:30`. The only write into the append-only log. The response is the event **as recorded** with the entry's `progress: EntryProgress` nested inside it (Ruling 44), so the UI repaints from the view rather than from its own request. Sequence: resolve the subject (**404 `WatchSubjectNotFoundError` before anything is written**) → `session.add` → flush → read `curated_entry_watch_state` → commit → **schedule** the mirror as a `BackgroundTasks` task when an entry was affected → return. The mirror is never awaited on the request path and takes its own session from the factory, because FastAPI closes a `yield` dependency before background tasks run; a locked workbook therefore defers with a log line rather than raising into a response already sent. This is the dual-store write on the UI path (section 0.2). |
| GET | `/api/categories/{category_id}/entries/{entry_id}/progress` | — | — | `EntryProgress` | 200 | `api/watch_events.py:49`. One entry's derived state on its own, for a screen that wrote nothing. Narrowed by `category_slug`, so the path's category is honoured rather than decorative: an entry of another category is a 404, not another category's progress. |
| GET | `/api/review/entries` | — | `state` (repeatable `ResolutionState`, default `unresolved` + `auto`), `category_id` (a slug), `limit` (`1..500`, default the cap), `offset` (`>= 0`) | `list[CuratedEntryRead]` | 200 | `api/review.py:30`. The resolution review queue, **worst first**: `resolution_confidence ASC NULLS FIRST`, then the category slug, then `position`. It spans every category at once, which is what makes "what is still unreviewed" one request instead of nineteen. The predicate is `resolution_state IN ('unresolved','auto')` on live entries of non-retired categories — **the partial index `ix_curated_entry_needs_review`'s own predicate, and there is no confidence threshold anywhere** (Ruling 47). |
| POST | `/api/review/entries/{entry_id}` | `ResolutionUpdate` | — | `CuratedEntryRead` | 200 | `api/review.py:47`. One human decision — `confirm`, `correct` or `reject` — answering with the row as it now stands. `{entry_id}` is `curated_entry.id`, the UUID the sheet's hidden `Row ID` column carries. **404 `EntryNotFoundError`** for an id no live entry answers to; **409 `ResolutionConflictError`** when the world the body names is not there (no provider configured, TMDB has nothing under that id, the title carries no such numbering) and nothing about the entry was changed; **422** for an incoherent body. A successful `confirm`/`correct` rebuilds that entry's `curated_entry_item` rows and renumbers the category (Ruling 46). The commit is in the route, not the service: one request is one decision, and nothing below the boundary closes a transaction it did not open. |

Ingest and mirror still run as backend services, not as routes. The first ingest is the `ingest/bootstrap.py` CLI (section 15.7), and there is deliberately **no "re-ingest everything" endpoint**; it stays a launcher/CLI concern.

**Phase 3 (ADR-014): sync, retry and three playback routes are built; the picker remains planned.**

| Method | Path | Request | Response | Status | Notes |
|---|---|---|---|---|---|
| GET | `/api/playback/{jellyfin_item_id}/stream` | header `Range` (optional) | the proxied media body | **206** for a satisfied range, **200** otherwise | The stream proxy (T52; boundary B17). `jellyfin_item_id` is this app's `jellyfin_item.id` (UUID), which must resolve to a live movie/episode row or the route is 404; a series is not a file. Relays Jellyfin's `/Videos/{id}/stream` with the key in a header; strict single-range validation returns 416 on malformed input; `Content-Type` passed through, `Accept-Ranges: bytes` set, body streamed never buffered. The `<video src>` is this same-origin path, so nginx's CSP needs no `media-src`. |
| GET | `/api/playback/entries/{entry_id}/items` | UUID path; `limit`/`offset` | `list[PlaybackItemRead]` | 200 | Owner-approved R104 (T52): ordered movie/episode queue slots with actual file IDs, availability and numbering labels. No title-level ID reinterpretation, implicit skip, progress write or workbook access. |
| POST | `/api/playback/entries/{entry_id}/position` | `PositionWrite` (`watch_event_id`, finite `expected_mtime`) | `CategoryDetail` | 200 | R105: validate the committed player fact, project the newest entry position and all pending safe status cells in one Catalog write. Original-stamp retry appends no event; stale/locked workbooks return 409/423. |
| POST | `/api/library/sync` | query `full: bool = false`, optional timezone-aware `since` | `LibrarySyncResult` (`seen`, `added`, `updated`, `removed`, `synced_at`, `incremental`) | 200, or **503** when Jellyfin is unreachable / unconfigured | **Built and reviewed (T49).** Transaction-serialised, provider-id-only indexing; cursor is explicit `since`, else latest live `last_seen_at`, else full scan. Full scan alone soft-deletes. Commit belongs to the route; owner picks are never changed. |
| PATCH | `/api/titles/{title_id}/jellyfin-item` | `JellyfinItemChoice` | `TitleRead` | 200 | The `AMBIGUOUS` picker's write (T56): persists `title.jellyfin_item_id`. 404 when the title or the item is unknown or removed; 409 when the item does not belong to the title's `tmdb_id`. The next sync respects the stored pick. |
| POST | `/api/review/entries/{entry_id}/retry` | — (no body) | `CuratedEntryRead` | 200 | `api/review.py:67`. **Built (T57).** Ruling 54's follow-up, closed: re-resolves exactly one entry through the reconciler's own store step (`ingest/reconciler.resolve_stored_entry`, extracted so this route and the ingest pass share one leg, never two) rather than waiting on the next full pass or the review queue. **404 `EntryNotFoundError`** for an unknown or removed entry; **409 `ResolutionConflictError`** both for an unconfigured TMDB (`NOT_CONFIGURED`) and for an entry a human has already decided (`resolution_state` is `confirmed` **or** `rejected` — the `HUMAN_DECIDED` guard) — both refusals are checked before any provider call, so a refused retry writes nothing. There is no second listing route: the unresolved view (section 14.9) consumes the existing `GET /api/review/entries` (Ruling 71/R71); `GET /api/entries/unresolved` was never built. |
| POST | `/api/watch-events` | `WatchEventCreate` | **`WatchEventRead`** (the event, with `progress: EntryProgress` nested) | **201** | **Built in Phase 1** (T29) and tabled above; repeated here because the Phase 3 player is its first high-volume caller: one `progressed` event every 60 seconds while playing, `completed` on `ended`. The paired player-context parameters derive PLAYER and suppress the ordinary background mirror; a following committed-event position request combines Position/Watched through Catalog (R105). The response shape is Ruling 44; an earlier draft of this cell said `EntryProgress`, which is the *nested* field, not the body. |

No route serves a Jellyfin URL, a Jellyfin id, or the API key to the browser. No route accepts a URL. The launcher (T58) needs no new route beyond reading `streaming_offer` through `CuratedEntryRead`'s title; its links open in a new tab from the browser.

**Route count, measured 2026-09-24:** `create_app().openapi()["paths"]` has **21 paths** and
**24 operations**, matching 24 router decorators: categories 6, chat 5, entries 1, library 1,
playback 3, review 3, rows 3, watch-events 2. Paths and operations are different counts because several paths
serve more than one method. App construction succeeds; the temporary T62 import failure is closed.

</endpoints>

---

<screens>

## 14. Screen inventory

The app has **no router**. Navigation is `state.ui.view` (`"home" | "category"`) plus `state.ui.activeCategoryId`. Everything else is an overlay.

`#root` is a two-row grid, `minmax(0, 1fr) auto` (`base.css:21-24`): the app in row 1, the toast lane in row 2. `<ToastStack />` sits **outside** `.shell` (`App.tsx:50-51`) so a toast can never land on a control and no panel can paint over a toast. That is a layout invariant, not a preference — do not move it inside.

### 14.1 The cards wall — `HomeView.tsx`

**Required behaviour.** A banner (`Watch List`), a one-line tally, a category search box, a `.cards` grid of `CategoryCard`s, an "Add a category" tile, and — when the listing carries them — an "Could not be opened" block and a "Hidden by another file" block.

- The tally reads `N categories · E entries · W watched` normally, and `N of M categories` while searching (`HomeView.tsx:34-38`).
- The search box writes `ui.categoryQuery`, which the **sidebar's box shares** (`useFilteredCategories.ts:6-14`, the hook's own docstring). Two boxes, one state, deliberately, so they cannot disagree. Matching is on `name` only, lower-cased — every workbook shares a `..._Master_Watch_Order` filename suffix, so matching the filename would match everything.
- Each `CategoryCard` is a single `<button class="card">` inside an `<li>`, with the accent palette pushed down as three inline custom properties (`--accent`, `--accent-dim`, `--accent-soft`).

**Edge cases.**
- `status === "loading" && total === 0` → `.empty` "Reading the workbooks…". A **refresh** never blanks the wall: `loadCatalog.pending` sets `status = listing === null ? "loading" : "ready"` (`catalogSlice.ts:24-26`).
- Searching with no match → `.empty` "Nothing matches “{query}”" plus a "Clear the search" link. The "Add a category" tile is hidden while searching, so the empty state is not competing with a tile.
- `locked_by_excel` puts an "Open in Excel" badge on the card. It does not disable the card — the category still opens read-only-ish; the refusal happens at write time.
- Artwork: `.png`/`.svg` are treated as logo marks over the generated backdrop; `.jpg`/`.jpeg`/`.webp`/`.avif`/`.gif` fill the card. `isLogo` strips the query string first, because `hero_url` always carries a `?v=<mtime_ns>` cache-buster.

### 14.2 The category view — `CategoryStage.tsx`

**Required behaviour.** `CategoryBanner` (back link, sheet-title eyebrow, Retire link, title with inline rename, tally, `role="progressbar"` track) → notices → `FilterBar` → `RouteList` or an empty state → the three overlays.

- `FilterBar` is five status chips with live counts (`aria-pressed`), an entry search labelled `Search entries in {name}`, an "Add entry" button, and a "Sheet notes" button **only when `reference_sheets.length > 0`**.
- The progress track carries `aria-valuenow` / `aria-valuemin=0` / `aria-valuemax=100` and `aria-label="{name} watch progress"`.
- `CategoryTitle` edits the **filename stem** — the category name *is* the filename. The form shows a `.xlsx` suffix and a `Saves as <stem>.xlsx` preview. Blank or unchanged submits cancel silently. Escape cancels.

**Edge cases.**
- `detail === null` and `status === "failed"` → `.empty` "That workbook would not open" with a "Try again" button that re-dispatches `loadCategory`.
- `detail === null` otherwise → "Opening the workbook…" or "Pick a category to start."
- `locked_by_excel` → `.notice.notice--locked`.
- `!has_watch_column` → a `.notice` with an "Add one" button dispatching `enableWatchColumn`.
- `rows.length === 0` → "Nothing matches", with the second line branching on `counts.total === 0`: "This sheet has no entries yet. Add the first one." vs "Clear the search or pick a different status."
- `adding` and `retiring` are **local `useState`**; `referenceOpen` is Redux. Do not move one to the other without a reason — the reference drawer is addressable from the filter bar, the dialogs are not.

### 14.3 The rail — `RouteList.tsx` / `RouteEntry.tsx` / `WatchNode.tsx`

**Required behaviour.** An `<ol class="route">` of `<li class="route__entry" data-reached data-status>`. Each entry is: rail node, order number, title, lead unit value, up to three tag chips, and an expand chevron.

- The **rail line** is a CSS pseudo-element (`route.css:38-61`), 1px normally, 2px in `var(--accent-dim)` when `[data-reached="true"]`, clipped at the first and last entries.
- **"Reached"** is computed over `detail.rows` — the *unfiltered* list — as everything up to and including the last row whose watch cell equals `Watched` (`RouteList.tsx:24-32`). Filtering the list must not change what is lit.
- `WatchNode` cycles through **the sheet's own dropdown order**, wrapping (`nextWatchStatus`). It never invents a value Excel would reject. Its `aria-label` is `"{title}: {status}. Mark {next}."`
- Collapsed columns come from `useRowColumns`: `order` and `title` by role, then columns with `role === "other"` **and** `(width ?? 0) < 40`, capped at four.
- Row expansion is a **single-open accordion** in Redux (`uiSlice.toggleRow`), so opening one closes another.

**Edge cases.**
- The sheet stores `"Skip"`, not `"Skipped"` — `WatchStatus.ts:4`. The UI label comes from `statusLabel.ts`. An unknown value passes through unchanged rather than being coerced.
- A category with no watch column renders no `WatchNode` at all (`RouteEntry.tsx:46-50`).
- Deleting a row clears `expandedRow` (`uiSlice.ts:76-79`) because row numbers shift up and a kept index would open a different entry.
- Deletion is confirmed with `window.confirm`: `Delete "{title}" from {name}? This rewrites the workbook.`

### 14.4 The expanded row — `RowDetail.tsx` / `CellField.tsx`

**Required behaviour.** Every column whose `role !== "order"` as a labelled `CellField`, then a `.detail__footer` with a `button--danger` "Delete entry".

`CellField` has exactly three branches, and the branch is chosen from the **sheet's own schema**:
1. `kind === "choice"` → `<select>`. Options are the column's own `choices`; a watch column renders them through `statusLabel`, anything else renders `choice || "—"`. Commits on change.
2. `role === "other" && (width ?? 0) >= 45` → `<textarea rows={3}>`. Commits on blur, only if the draft differs.
3. otherwise → `<input type="text">`. Enter blurs (committing); Escape restores the value.

**Edge cases.**
- The local draft is resynced from the prop by `useEffect(() => setDraft(value), [value])` — a server response or an optimistic replay must be able to overwrite what is on screen.
- Writing a value a `choice` column does not offer raises `InvalidChoiceError` → 400. The UI cannot produce this from a `<select>`; chat can, and that is why approve maps it to a 409 instead.
- Optimistic paint: only `writeRow` paints ahead of the server. `addRow`, `removeRow` and `enableWatchColumn` do not. A failed `writeRow` either adopts the server's re-read or restores `previous`, and in both cases replays the *remaining* in-flight patches on top.

### 14.5 The dialogs — `Modal.tsx` + three

All three use `Modal`, which is `.scrim` + `.dialog[role=dialog][aria-modal="true"][aria-labelledby]`, closes on scrim `mousedown` (the dialog's own `mousedown` stops propagation), and installs `useFocusTrap`. The trap records `document.activeElement`, focuses the first control, wraps Tab/Shift+Tab at the ends, closes on Escape via a **capture-phase** listener, and refocuses the opener on unmount. `onClose` is read through a ref with an empty dependency array — depending on the callback directly would re-focus the first field on every keystroke.

**`AddEntryDialog`** — title `Add to {name}`; hint "The entry lands at the end of {sheet_title}."; one `CellField` per non-`order` column. Ready requires a non-blank title cell, or any cell at all when the sheet has no title column. It closes **only** on `addRow.fulfilled` — a refused write leaves the dialog up with the values still in it.

**`NewCategoryDialog`** — name, one of nine accent swatches (`#C2410C` Burnt orange, `#B91C1C` Red, `#1D4ED8` Blue, `#1E3A8A` Navy, `#14532D` Forest green, `#065F46` Teal, `#7C2D12` Brown, `#6D28D9` Violet, `#1F2937` Slate), and an optional newline-separated title list. Titles are split on `\n`, trimmed, blanks dropped. On success it awaits `loadCatalog()`, selects the new category, then closes — in that order, so the wall is never briefly missing the card it is about to navigate to. Edge case: a name whose slug collides with an existing workbook's id is refused with `DuplicateCategoryError` → 409 **before anything is written**, because a free filename is not a free category.

**`RetireCategoryDialog`** — type-the-name-to-confirm, compared case-insensitively. An extra `.dialog__warning` when the workbook is open in Excel. The confirm field is `autoFocus autoComplete="off" spellCheck={false}` with the name as placeholder. The submit button is `button--danger` and disabled until confirmed. After `retireWorkbook.fulfilled` it returns **without clearing `busy`**, because the stage unmounts underneath it. The copy must keep saying where the file goes (`app/.backups`) — retirement moves, it never deletes.

### 14.6 The reference drawer — `ReferenceDrawer.tsx`

**Required behaviour.** A right-hand `<aside class="drawer" role="dialog" aria-modal="true" aria-label="{name} sheet notes">` with its **own** `useFocusTrap` — it does not use `Modal`, because it has no scrim and is not centred. A `.drawer__head` with a Close button, then a `.drawer__body.scroll` of one `<table class="sheet-table">` per sheet, each with a `<caption>` naming the sheet.

**Required semantics.** Read-only. These are worksheets 2..N of the workbook, surfaced verbatim; nothing here writes.

**Edge cases.**
- The "Sheet notes" button does not render at all when `reference_sheets` is empty, so the drawer is unreachable rather than empty.
- Its `Value` component linkifies a cell when `text.startsWith("http")` — a **looser** test than `isHttpUrl` used by the proposal and candidate components. Both exist on purpose; do not "unify" them without deciding which behaviour each surface wants.
- These sheets carry real signal (Bleach's "366 episodes", Naruto's OVA release dates, Pokemon's `Media Inventory` admitting the English/Japanese season mismatch). Phase 1 deliberately does **not** model them.

### 14.7 The chat dock — `ChatLauncher` / `ChatDock` / `ChatComposer` / `ProposalPreview`

**Required behaviour.** A vertical pull tab on the right edge ("Ask Claude"), which renders `null` while the dock is open. The dock is an overlay `<aside class="chat-dock" aria-label="Ask Claude">`, absolutely positioned against `.shell` — **it sits over the wall or a category without replacing either**. It widens to `chat-dock--wide` when a proposal is pending.

- Head: eyebrow, the turn cost as `$0.0000` (4 decimals) when known, "New chat" (disabled while streaming) and "Close".
- Log: auto-scrolls to bottom on every change to messages or proposal. `role === "tool"` renders a `ToolChip`, everything else a `ChatMessageBubble` — which is a plain `<p>`. **Nothing from the model becomes markup.** That is the XSS boundary; do not introduce a markdown renderer here without sanitising.
- Composer: `maxLength = 16000`, matching `MAX_CHAT_MESSAGE_LENGTH` on the backend. Enter sends, Shift+Enter newlines, and the hint says so. While streaming, Send is replaced by Stop, which aborts the fetch.
- `ProposalPreview`: target eyebrow (`New category · X` / `Artwork · X` / `Editing · X`), summary, sources (linkified only when `isHttpUrl`), then **either** hero UI **or** the diff, then the action row. The primary "Approve and write" button is absent entirely for a hero proposal — artwork is chosen, not approved.
- `ProposalDiff`: a `.diff` scroller (`tabIndex=0`, `role="group"`, `aria-label="Proposed rows"`) around `table.diff__table`. The "Now" column exists only when at least one line has a standing value. A revise renders `old → new`, with `(blank)` standing in for an erased value — a revise that blanks a cell must never render as an empty box indistinguishable from a line that changes nothing.

**Edge cases.**
- Stop mid-turn: the SSE generator is abandoned under `anyio.CancelScope(shield=True)` and the session's CLI conversation is retired and replaced, while the dock keeps its id, transcript, pending proposal and read stamps. An unshielded await there loses the interrupt — this was a real bug.
- A partial trailing SSE frame is held in the buffer and never delivered.
- Approve navigates: on success it reloads the catalog and selects the written category. A hero pick only reloads the catalog, because the wall is where new artwork actually shows.
- A 409 on approve leaves the proposal pending and the diff on screen. That is a conflict you retry, not a bad request.
- No chat at all inside Docker — 503 with the same message the launcher preflight prints.

### 14.8 The three error surfaces

These are the screens the owner only ever sees because something already went wrong, which is the worst possible moment for the control that answers them to be somewhere a mouse cannot go. All three are in the layout guard's 18 surfaces for exactly that reason.

**(a) Files that could not be opened.** `CatalogListing.unreadable` — a `.home__unreadable` block on the wall under the eyebrow "Could not be opened", and a `li.unreadable` row per file in the sidebar reading `{file_name}` / `Could not be opened as a workbook. {reason}`. `reason` is `f"{type(error).__name__}: {error}"`. Required behaviour: a dropped-in file that fails to parse is **visible**, never silently missing. Edge case: the file still claims its id — `discovery.resolve` picks by name alone, so an unreadable file hides the namesake behind it, and `_listing` claims the id *before* trying to open the file for exactly that reason.

**(b) Files hidden by another file.** `CatalogListing.shadowed` — eyebrow "Hidden by another file"; the sidebar row reads `Hidden: {answered_by} already answers to {category_id}.` Required behaviour: two files can slugify to the same id (`Yu Gi Oh` and `Yu-Gi-Oh!`), `resolve` answers with the first in sorted order, and every read *and write* for that id lands on it. The loser is named rather than quietly becoming a second card for an id only one file can be written to. Edge case: create and rename both **refuse** to manufacture such a clash (`DuplicateCategoryError` → 409); shadowing only arises from a file dropped in by hand.

**(c) A workbook Excel is holding.** `locked_by_excel` — an "Open in Excel" badge on the card, a flag titled "Open in Excel — edits are paused" in the sidebar, and a `.notice.notice--locked` on the stage. Required behaviour: the category still renders in full; only writes are refused, with **HTTP 423 Locked** and "{file} is open in Excel. Close it and try again." Edge cases: the flag is recomputed live on every read (`Catalog._read_live_lock`) because it can change without the workbook changing; the lock is detected two ways — the sibling `~$<name>.xlsx` owner file **or** the file refusing an `r+b` open; and it is checked twice, once before loading and again as a `PermissionError` short-circuit during the atomic swap.

A fourth surface worth naming, though it is a state rather than a screen: the **toast lane**. Errors from failed writes arrive there, `role="status" aria-live="polite"`, each toast owning its own 7000 ms timer so a newer toast never resets an older one's countdown. The lane is capped at `--toast-lane-max: 30vh`. Five of the guard's surfaces hold a toast on screen while measuring, because a toast over a control is invisible to every other test in this repo.

### 14.9 Phase 3 surfaces (built and planned — ADR-014)

**Play, availability badges, the player overlay (T52) and the unresolved view (T57) are built and
reviewed; picker and launcher remain planned.** Every new screen gets a layout-guard surface in
`layout/surfaces.ts` and an arrangement in `layout/probes/arrangements.ts` in the same change.
They ship at the four existing laptop-sized viewports; the ten-foot pass is Phase 2, deferred.

- **Play button per row** (`RouteEntry`). Rendered only when the entry's `availability === "in_library"`; it is the one control that opens the player. Disabled controls are measured, so it must be reachable even before the availability layer has loaded.
- **Availability badge**, three states, never a nullable id: `In library` (`in_library`), `Opens on your subscription` (`not_in_library` — the launcher's wording, ADR-013's "honesty mechanism"), `Needs a pick` (`ambiguous`). Text plus an icon; never colour alone. Drawn from `CuratedEntryRead.availability`, which the SPA reads from `GET /api/categories/{id}/entries` for this layer only — the row's cells still come from `CategoryDetail`.
- **`AMBIGUOUS` picker modal** (T56). A `Modal` listing the candidate `jellyfin_item` rows for the title — name, `path`, `run_time_seconds` rendered as `h:mm`, episode numbers where they exist — with one primary "Use this file" per candidate and a Cancel. Submits `PATCH /api/titles/{title_id}/jellyfin-item`; on success it reloads the entries and closes. Uses `useFocusTrap` like the three existing dialogs; the confirm buttons are in the guard's promised-size set because a picker whose button is below the fold is exactly the Approve bug again.
- **Player overlay** (T52/T53). A full-stage overlay over the category view, not a route; `AppView` is unchanged. `ui.playing: PlaybackScope | null` captures entry/title/category/mtime before the slot request completes. R104 supplies the ordered slots; the selected slot alone supplies the file UUID for `/api/playback/{jellyfin_item_id}/stream`. The overlay has native `<video controls>`, a title, explicit slot selection, the numbering actually used, and Close; no custom scrubber. Missing/ambiguous slots remain selectable but do not start a different file. Escape closes through `useFocusTrap`, restores the opener and unmounts the video. T53 (R105) adds one-minute dual-store snapshots and pause/ended/unmount write-back, with persistent retry after closing the player. Next/Autoplay remains T53a.
- **Unresolved view** (T57, built and reviewed, present tense). `AppView` gains `"unresolved"` beside `"home"` and `"category"` (`src/types/AppView.ts`), with a nav entry in the sidebar (`Sidebar.tsx`) and a back link. `UnresolvedView.tsx` lists the queue by consuming the **existing** `GET /api/review/entries` — **no `/api/entries/unresolved` route was built** (Ruling 71/R71: a second listing route was rejected because the queue already spans every category at once in one request). The listing is paged: `src/api/fetchReviewQueue.ts` walks `?limit=REVIEW_PAGE_SIZE&offset=n` (`REVIEW_PAGE_SIZE = 500`, the backend's own `MAX_ENTRIES_PAGE_SIZE` ceiling and default) until a short page ends the walk, so a 996-row library is never silently truncated at one page. `UnresolvedRow.tsx` renders each row as **text only** (no `dangerouslySetInnerHTML` anywhere): the workbook it came from (`category_slug`, R82 — added to `CuratedEntryRead` for exactly this row), its curated `position`, its verbatim `cells`, `resolution_state`, `resolution_confidence` and `resolution_note` rendered as it stands, with no history (Ruling 48 stands). Per row: a **Confirm** button (posts `{action: "confirm"}` through the existing `POST /api/review/entries/{entry_id}` and removes the row) and a **Retry resolution** button (`RetryResolutionButton.tsx`, posts the new `POST /api/review/entries/{entry_id}/retry` with no body and replaces the row in place with the response — Ruling 54's closed follow-up). An entry a human has already confirmed or rejected refuses a retry with 409 (`HUMAN_DECIDED`, both states, checked before any provider call). An empty queue renders a plain "nothing left to review" sentence rather than a blank pane. The main-nav entry, the per-row Confirm and the per-row Retry are the layout guard's **`"unresolved-view"`** surface (`layout/surfaces.ts`, `layout/probes/aLibraryWithUnresolvedRows.ts`), rooted at the shell and asserting the sidebar's attribution foot is still present beneath it. Confirming or correcting a resolution is the existing Phase 1 service (`services/resolution_review.py`); T57 added `retry_resolution()` beside it, which reuses the reconciler's own store step (`ingest/reconciler.resolve_stored_entry`, extracted from `_resolve_one` so the retry and the ingest pass share one leg, never two — the full suite proved this behaviour-identical) rather than writing a second resolution path. **The category is shown by design** — an earlier draft of this bullet said the view could not name the category; R82 closed that gap in T57's own fix round.
- **Launcher panel** (T58), the behaviour of every `not_in_library` entry. Where the Play button would be: one button per `streaming_offer` for the title (`Open on Netflix`, `Open on Prime Video`, …), each `window.open(link, "_blank", "noopener,noreferrer")`; a hand-marked Disney+ row opens its `/browse/entity-…` page; with no key configured (T55 blocked) the panel renders as the shell — the wording and a disabled control — so the state is visible, not hidden. Next-on-press: when the tab regains focus after a launch, a one-line prompt offers "Mark watched and open the next" (ADR-012 rule 4). The Streaming Availability API's attribution line sits at the panel's foot, as its terms require. Nothing here ever embeds, frames or scrapes a service page.

Two rules that hold across all six: model-free (no chat surface ever shows availability, offers or Jellyfin data — ADR-012 rule 7), and text-only rendering (a Jellyfin `name` or `path` is free text from the owner's filesystem and is rendered exactly like a provider overview, B12: React escapes it, no `dangerouslySetInnerHTML`).

</screens>

---

<local_commands>

## 15. Local commands

Two toolchains, two package managers, one repo. `uv` owns Python 3.13 for the backend; `pnpm@9.15.9` (via corepack) owns Node for the frontend. Never `pip`, never `npm`, never `yarn`.

### 15.1 First run — the launchers

```bat
run_tv.bat        :: Windows
```
```bash
./run_tv.sh       # macOS / Linux (chmod +x if the clone lost the bit)
```

Both launchers: bootstrap on first run (`uv sync --group dev` if `app/backend/.venv` is missing, `pnpm install` if `app/frontend/node_modules` is missing), run the chat preflight and name anything missing by hand, **bring up the compose Postgres and migrate it** — `docker compose up -d postgres`, wait up to 60 s for the healthcheck, then `uv run alembic upgrade head` — then start the two **host-native dev servers** (the servers stay off Docker so chat keeps working), print the URLs block, open a browser, and sit on a menu:

- `[r]` — restart both host services. Postgres stays up. Non-terminal, unlimited.
- `[k]` — stop and exit: `docker compose down`, images and volumes kept.
- `[q]` — stop, `docker compose down --remove-orphans`, remove the `tv-watchlist` images. Volumes kept.
- `[v]` — the same plus `--volumes`, dropping `tv_postgres_data` and the Jellyfin volumes.

**All four landed at T32a (2026-09-20) and that task's review has closed**; even so, **no agent has run either launcher end to end**, because the VPN block on image pulls (section 6.2) stops `docker compose up -d postgres`. The first live bring-up is the owner's. Unrecognised input re-prompts rather than exiting. Section 6.5 has the line references and the reasoning.

| | |
|---|---|
| App | <http://localhost:5284> |
| API | <http://localhost:8284> |
| API docs | <http://localhost:8284/docs> |
| Postgres | `localhost:5525` (db `tv`) |

Ports come from `TV_BACKEND_PORT` / `TV_FRONTEND_PORT` / `TV_POSTGRES_PORT`; the library folder from `TV_LIBRARY_DIR`.

### 15.2 Backend

```bash
cd app/backend
uv sync --group dev                                   # install (frozen in CI: --frozen)
uv run uvicorn tv_watchlist.main:app --host 127.0.0.1 --port 8284    # run
uv run pytest -q -p no:cacheprovider                  # 2290 passed, 227 skipped as of 2026-09-20;
                                                      # T33 re-measures. The 225 are the
                                                      # Postgres-gated tests, skipping LOUDLY
uv run pytest --cov=src --cov-report=term             # with coverage
uv run pytest --cov=src --cov-report=xml --junitxml=junit-backend.xml   # exactly what CI runs
uv run ruff check .                                   # lint
uv run ruff format --check .                          # formatting (CI runs both)
uv build                                              # build CHECK only - see below
uv run python -m tv_watchlist.agent.preflight         # what chat is missing on this machine
```

**`uv build` proves the package compiles and nothing more.** The wheel is not a runtime artefact —
the image installs dependencies and copies `src/`, and the launchers run out of the working tree.
`app/backend/data/franchise_prefixes.json` sits outside the package by the project skeleton
(Ruling 22), so it is *not* in the wheel; it reaches the image through the Dockerfile's
`COPY data ./data` and is read at runtime by `resolver/franchise.py:16`.

**Running the Postgres-gated tests on this workstation, without Docker.** Docker compose remains the
documented path and is what CI runs; this is the fallback while the VPN blocks image pulls
(section 6.2). A real PostgreSQL **16.2** runs on the Mac through `pgserver`, with `pg_trgm` built
from the matching 16.2 contrib source (`make USE_PGXS=1 PG_SYSROOT=$(xcrun --show-sdk-path)`), and
`title.match_key`'s GIN index needs that extension or the migration will not apply:

```bash
uv run --no-project --python 3.12 --with pgserver   # stand the server up on 127.0.0.1:5525, user/db `tv`
cd app/backend && TV_REQUIRE_POSTGRES=1 TV_POSTGRES_DB=tv_test uv run pytest -q
```

`TV_REQUIRE_POSTGRES=1` turns the loud skip into a **failure**, which is the point: it is how a
mis-wired connection shows up as a red suite rather than as 225 silent absences. Two rules come with
it. **Two local runners no longer collide** — `tests/database_support.py` still rebuilds the throwaway
database with `DROP DATABASE … WITH (FORCE)`, but the name it rebuilds now carries the pid
(`tv_test` → `tv_p<pid>_test`), so each run drops only its own and hands it back at session end
(section 16.5). And the name must end `_test`: `require_disposable_database` refuses anything else.

### 15.3 Frontend

```bash
cd app/frontend
pnpm install                                          # install (frozen in CI: --frozen-lockfile)
pnpm dev                                              # run on 5284, proxying /api + /heroes to 8284
pnpm exec tsc -b                                      # typecheck (also typechecks tests/ and layout/)
pnpm lint                                             # eslint
pnpm test                                             # 320 Vitest tests in jsdom
pnpm test:coverage                                    # with a v8 coverage report
pnpm build                                            # tsc -b && vite build
pnpm preview                                          # serve the built dist/
```

### 15.4 Docker

```bash
docker compose up --build -d        # app on http://localhost:5284
docker compose config --quiet       # validate the file (CI's build stage runs this)
docker compose down
docker compose down --volumes --remove-orphans
```

Four services: FastAPI, an unprivileged nginx serving the built SPA and proxying `/api` and `/heroes`, Postgres 16 (T09 — the backend waits on its healthcheck and migrates before uvicorn starts), and the jellyfin media server (T47a; it starts with the stack, nothing waits on it). The repo root is bind-mounted into the backend as `/library`, so the containers read and write the very same workbooks the clone arrived with. Override `TV_LIBRARY_HOST` to point them at a copy.

**Chat does not work in a container**, deliberately: `/api/chat` answers 503. Use the launchers if you want chat.

### 15.5 The layout guard, and Chromium

The guard needs its own Chromium download, and so does the backend's chat escalation. They are separate installs into separate caches:

```bash
cd app/backend  && uv run playwright install chromium        # for chat's bot-blocked-page reader
cd app/frontend && pnpm exec playwright install chromium     # for the layout guard
```

CI installs the guard's browser with `pnpm exec playwright install --with-deps chromium` (the `--with-deps` matters on the Linux runner and not on a workstation).

```bash
cd app/frontend
pnpm test:layout                                             # 196 runs: 49 tests × 4 viewports
pnpm exec playwright test --config layout/playwright.config.ts --reporter=list,junit   # CI's form
```

The guard boots its own Vite server on **5286** (`TV_LAYOUT_PORT`), specifically so a run never fights the app you have open on 5284. It touches no network: any request addressed off the probe origin aborts and fails the run.

**Any UI change means running `pnpm test:layout`.** It is not optional and it is not covered by Vitest — see section 16.

### 15.6 SAST, reproduced locally

All four are exactly what CI runs. Run them from the repo root unless noted.

```bash
docker run --rm -v "$PWD:/src" -w /src semgrep/semgrep semgrep scan \
  --config p/default --config p/owasp-top-ten \
  --config p/python --config p/typescript --config p/react --config p/docker \
  --severity ERROR --error --metrics=off

docker run --rm -v "$PWD:/src" ghcr.io/gitleaks/gitleaks:latest detect --source /src --no-git --redact

cd app/backend  && uv export --frozen --no-dev --no-emit-project --format requirements-txt -o /tmp/reqs.txt \
                && uvx pip-audit -r /tmp/reqs.txt --disable-pip

cd app/frontend && pnpm audit --audit-level=high
```

Three things about this set that are deliberate and must not be "fixed" without a decision:

1. **`semgrep scan`, never `semgrep ci`.** The `ci` subcommand rejects `--error` and exits 2 with a usage error.
2. **Six named packs, never `--config auto`.** `auto` took this pipeline from 0 findings to 41 in under an hour, none of them about this app's code.
3. **`--severity ERROR`.** WARNING and INFO findings still reach the Security tab through the SARIF upload; they do not block a build.

The container scan is the fifth member of the set and only runs against a built image:

```bash
docker build -t tv-watchlist-backend:ci app/backend
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock aquasec/trivy:latest \
  image --severity HIGH,CRITICAL --ignore-unfixed --scanners vuln --exit-code 1 tv-watchlist-backend:ci
```

### 15.7 Phase 1 additions

Landed at T07/T08 — `app/backend/alembic/`, `alembic.ini`, and the first revision
`0001_phase_1_schema.py`. T49, T61, T66 and T53a extend the chain through `0002`, `0003` and `0004`
to the single head **`0005`**.
Run destructive migration round trips only against the harness's disposable test database, never
the owner's application database. These are the underlying commands:

```bash
cd app/backend
uv run alembic revision --autogenerate -m "<what changed>"
uv run alembic upgrade head && uv run alembic downgrade base && uv run alembic upgrade head
docker compose up -d postgres        # Postgres 16-alpine, database `tv`, published 127.0.0.1:5525
```

The migration command written above is the **full round trip**, and it is the form CI runs (`ci.yml:236-238`) and the form the master plan's Phase 1 gate requires. A single-step `alembic downgrade -1` proves less and is not the gate.

**The first ingest is one command** (T27), run once by the owner after Postgres is up and the provider tokens are in the root `.env`:

```bash
uv run python -m tv_watchlist.ingest.bootstrap                     # the first ingest: 19 workbooks, 996 identities, 19 snapshots
uv run python -m tv_watchlist.ingest.bootstrap --dry-run           # plan it and report; writes to neither store
uv run python -m tv_watchlist.ingest.bootstrap --only marvel wwii  # one or more categories, by id
```

It takes **one workbook at a time** — no fan-out — each under that workbook's own `lock_for`, its own session and its own `app/.backups/` snapshot, so a failure anywhere touches one file and one transaction. **A refusal is a result**: Excel holding a file, a sheet that changed mid-pass, a workbook that will not open, an `--only` slug nothing answers to — each is recorded on that workbook's outcome and the run carries on. The expected output of the owner's live run is `19 workbooks, 19 ingested, 0 skipped, 0 refused` and `996 rows projected, 996 identities minted, 19 workbooks written`.

Three exit codes, and the distinction is the whole shell contract:

| Code | Constant | Meaning |
|---|---|---|
| `0` | `BOOTSTRAP_EXIT_OK` | every workbook asked for was ingested. |
| `1` | `BOOTSTRAP_EXIT_REFUSED` | at least one workbook was refused — locked, stale, unreadable, or an unknown slug. **The others still ran**; close Excel and run it again. |
| `2` | `BOOTSTRAP_EXIT_FAILED` | an infrastructure fault — the database is down, the migrations are behind. Nothing is reported per workbook; retry once the fault is fixed. |

**`--dry-run` writes to neither store, but it is neither free nor offline.** It answers the write-back with a catalog that declines to write and rolls its transaction back, so it reports the counts a real run would and leaves nothing behind — yet it still reads every workbook under that workbook's own lock (blocking the app's writes to that file for the duration), still needs a reachable database and holds that connection's row locks until the rollback, and with provider tokens configured still spends TMDB and TheTVDB quota and still downloads artwork into the heroes directory, which is an on-disk cache and neither of the two stores. Run it with the tokens unset for a preview that reaches no network. `--help` says all of this and contacts nothing.

`app/backend/docker-entrypoint.sh` runs `alembic upgrade head` before `exec uvicorn`, and the launchers do the same thing by hand for the host-native backend (section 6.5). There is exactly **one** connection string in the project: Alembic runs on the same `asyncpg` URL the app does, read from `Settings.database_url` through `alembic/env.py`. No sync driver is installed, and `sqlalchemy.url` is never written into `alembic.ini`. The one host port this phase allocates is **5525** for Postgres, loopback-bound.

Landed with the Phase 0 close (T01a, T01b) and part of this section now:

```bash
node --test scripts/hooks/hooks.test.cjs                 # 31 hook tests. The FILE form — the directory
                                                         # form (node --test scripts/hooks/) fails on Node 24
node -e "require('./scripts/hooks/session-start.cjs')"   # exercise one hook by hand
cp .env.example .env                                      # then the OWNER fills in the real credentials
```

**Phase 3 additions (ADR-014, after the Phase 1 gate).** Jellyfin is a compose service; the owner
creates its API key in Jellyfin's own UI, and no agent ever types it:

```bash
docker compose up -d jellyfin        # jellyfin/jellyfin:12.1, host port 8096, media from ${TV_JELLYFIN_MEDIA_HOST:-./media} read-only
open http://localhost:8096/web       # first run: create the admin account, add /media as a library, let the scan finish
#   then: Dashboard → API Keys → New, name it `tv-app`; copy the key into the root .env as
#   TV_JELLYFIN_API_KEY, with TV_JELLYFIN_BASE_URL=http://localhost:8096 for the host launchers
#   (compose sets http://jellyfin:8096 for the backend container itself). Owner-typed, never agent-written.
docker compose ps jellyfin           # healthy = GET /health answered; the backend must boot and serve even when it is not
curl -sI http://localhost:8284/api/playback/<jellyfin_item_id>/stream -H 'Range: bytes=0-1' | head   # expect 206 + Accept-Ranges: bytes
```

The Streaming Availability key (`TV_STREAMING_AVAILABILITY_API_KEY`, the launcher's, T55) is the same
shape: the owner signs up for the free plan, types the key into the root `.env`, and T55 starts only
once it is present. The one new host port Phase 3 allocates is **8096** for Jellyfin, registered in
`PORT_ASSIGNMENTS.md` in the same commit that binds it (T47a).

</local_commands>

---

<testing>

## 16. Testing requirements

### 16.1 What is in place today

| Suite | Framework | Count | Where |
|---|---|---|---|
| Backend | pytest + pytest-asyncio (`asyncio_mode = "auto"`) + pytest-cov | Whole-suite real-PostgreSQL results and coverage: `docs/status.md`; no exclusions or skips in the current verification | `app/backend/tests/` |
| Frontend | Vitest + React Testing Library, jsdom | **320 tests** across 46 files, as of 2026-09-24 (T53) | `app/frontend/tests/` |
| Layout | Playwright, real Chromium | **196 runs** — 49 tests × 4 viewports, 23 surfaces, as of 2026-09-24 (T53) | `app/frontend/layout/` |
| Hooks | `node --test`, no dependency | **31 tests** in one file | `scripts/hooks/hooks.test.cjs` |

**Measure the backend figure, do not quote an earlier session.** Run with `TV_REQUIRE_POSTGRES=1`
against the harness's PID-isolated disposable database. A missing server is a failure in CI, not a
silently accepted skip. Parametrisation explains why case counts exceed `def test_*` counts; the
current measurement and exact commands live in `docs/snapshots-recovery-validation.md`.

**One known flake, and it is not the suite's.** `tests/api/test_chat.py::test_chat_stop` raises an anyio `ResourceWarning` that only fails under `-W error`; the ordinary run is green and CI does not set `-W error`. It is recorded here so a session that meets it does not go hunting: it is an owner ticket, not a Phase 1 gate item, and it is not evidence of a real leak in the chat stream's shielded cancel path.

The hook suite is run as **`node --test scripts/hooks/hooks.test.cjs`**, the file form. The directory form fails on Node 24; do not shorten the command.

### 16.2 Coverage

The global standing target is 100%. **This project's enforced gate is a measured ratchet, not 100%**, and that is a deliberate, documented position (`ci.yml:35-43` — the comment stating why, then the five floors):

| Floor | Value |
|---|---|
| `BACKEND_MIN_LINES` | **97** (measured 2026-09-23: **98.80%**, 8489 of 8592 statements) |
| `FRONTEND_MIN_LINES` | 56 |
| `FRONTEND_MIN_STATEMENTS` | 54 |
| `FRONTEND_MIN_FUNCTIONS` | 45 |
| `FRONTEND_MIN_BRANCHES` | 45 |

The frontend numbers look low because Vitest is not the whole frontend test story: most components are exercised by the layout guard, in a real browser, and Playwright produces no coverage data for them. Only 6 of 31 components have a Vitest file.

The rule is one line and it is in the gate's own failure message: **"Add tests. Do not lower the floor."** Coverage may rise; it may never slip. Raising a floor toward 100 is separate work and does not belong in the same change as the feature that made it possible.

There is **no local threshold** — `vitest.config.ts` declares no `thresholds` block and `pyproject.toml` sets no `--cov-fail-under`. The floors exist only in `ci.yml`, parsed by an inline `python3` heredoc from `coverage.xml`'s `line-rate` and `coverage-summary.json`'s `total`.

### 16.3 What must be tested

- Every new module in `src/` gets a matching test file mirroring its path.
- Every new API endpoint gets an integration test through `httpx.ASGITransport` against the real app with the catalog dependency pointed at a throwaway library.
- Every workbook write is tested against **copies of the real committed workbooks**, and asserts `tests/snapshot.py:fingerprint()` — per sheet: dimensions, table refs, table column names, sorted validations, conditional-format ranges and rule count, column widths, header style, body style. A write that quietly drops a dropdown or a conditional format is a regression even when the cells are right.
- Subjects are picked **by shape, never by name** (`tests/library_choice.py`): `a_category()` wants an unmarked category with a free-text column, ranges that all end together, at least 8 rows, and a row a top deletion would retitle. Renaming a workbook must not break the suite.
- Every parametrised condition uses `@pytest.mark.parametrize` (Python) or `it.each` (Vitest).
- Any UI change runs `pnpm test:layout` before it is called done.

### 16.4 Phase 1 rules — non-negotiable

**The database is never mocked.** Integration tests run against a **real Postgres 16 service container** in GitHub Actions, with `pytest-asyncio` in the `asyncio_mode = "auto"` already configured and a per-test transaction-rollback fixture. Mocking a database in a project whose entire premise is a dual store hides exactly the class of bug the dual store can produce. There is no approved exception.

**TMDB and TheTVDB clients are tested against recorded fixtures, never live.** A live call in a test suite is a rate-limit budget the CI runner shares with every other job on that egress IP (TMDB documents roughly 40 requests per second without saying whether that is per IP or per key, so assume the runner's egress IP shares it), a non-deterministic assertion, and a network dependency in a stage that must be able to fail for exactly one reason. Record the response bodies, commit them, and drive `httpx` through a `MockTransport` — the existing `tests/agent/mock_responder.py` is the pattern to copy. The **only** live-call code paths anywhere in this repo are the chat feature, the resolver's dry run and the owner's bootstrap ingest; the test suite already stands in at the SDK transport seam rather than reaching the network.

**A missing provider fixture is recorded, never hand-authored** (Ruling 51). When a test needs a body the `tests/fixtures/` tree does not hold, run the **existing recorder** — one live call, the token read through `Settings()` — and commit what came back with its header sidecar. A JSON body typed by hand is a fixture that asserts what the author believed the provider returns, which is precisely the belief the test exists to check; every provider quirk this project has had to design around (TheTVDB's 200-with-an-empty-`episodes`-array, TMDB's season buckets, the `/eng` language variants) is one a hand-written fixture would have hidden. **The one narrow exception (Ruling 51 exception, T48):** when a server has **never been reachable at all** — the owner's Jellyfin under the VPN — a fixture is hand-authored from that server's own published OpenAPI document instead, with a `README.md` beside the fixtures naming the exact document URL and the date it was read, and listing what a later live run must confirm. `tests/fixtures/jellyfin/` is the only fixture directory built this way so far, and it is superseded, item by item, the first time T49 runs against a real Jellyfin.

**Never let an httpx error's own text reach a raised message or a log line.** `httpx.LocalProtocolError` — raised by h11 when a header value contains a CR, LF or NUL — is itself an `httpx.HTTPError`, and h11 builds that error's message by quoting the offending header **back in full**. A credential sent as `Authorization: Bearer <token>\n` therefore lands, token included, in anything that interpolates `{error}` from the `except httpx.HTTPError` path — the raised exception's own message, `sync_state.last_error`, the call log. `clients/transport.unreachable(provider, error)` is the one place this is handled: it formats `type(error).__name__` only and keeps the original on `__cause__`, and it is shared by all three provider clients (`tmdb_client.py`, `tvdb_client.py`, `jellyfin_client.py`) rather than reimplemented per client. A test that reproduces this has to build the exact header the transport would send and assert against `str(raised.value)`, every caplog record, **and** `__cause__` (which must still carry the detail) — asserting only that the message is short proves nothing if the leak moved to a log line instead.

**A reorder gate test asserts "position only" against a fully mirrored sheet** (Ruling 50). Before asserting that a pass moved nothing but `position`, mirror any pending state first: a `COMPLETED` event that has not yet reached its `Watched?` cell makes the *next* pass write that cell legitimately, and a test that skipped the mirror would read that correct write as a spurious change and fail. Section 5.16 requires the write; the test has to let it happen before it measures.

**Ingest correctness is asserted against ground truth from the sheets, not against the resolver's own output.** A test that says "the resolver returns what the resolver computed" proves nothing. At least one test per resolver rule validates against a hand-checked span from a real workbook.

**No mocking of the workbook layer in service tests.** `Catalog` tests write real `.xlsx` files in `tmp_path` and read them back with openpyxl.

### 16.5 Known testing pitfalls

These are recorded because they have each already cost time.

**Vitest does not auto-clean up the way Jest does.** `tests/setup.ts` must import `cleanup` from `@testing-library/react` and call it in `afterEach`, alongside `vi.unstubAllGlobals()`. Without it a component test leaks its DOM into the next one and the failure looks like a query matching "multiple elements" in a test that renders one. The file exists and does this; do not delete it and do not add a second setup file that shadows it.

**jsdom has no layout engine, and that is exactly why the layout guard exists.** No amount of component testing can see a control render where a mouse cannot reach it. Five real bugs shipped that way and every one was found by hand in a browser:

1. The **Approve button below the fold** in the chat dock.
2. The **artwork picks sliced out of their scroller** at 1280x720 — the shape that a six-candidate hero proposal produces.
3. A **revise's outcome ellipsised away**, so the diff read as a line that changed nothing.
4. The **last route row unreachable**, because flex children were allowed to shrink (`category.css:15-17`, `.stage > * { flex: none }`).
5. The **proposal action row cut off entirely** once the dock was short (`chat.css:163-181`, `.proposal { overflow: hidden auto }`).

A sixth — a **toast landing on the dock's Send button** — was found by widening the guard, which is why five surfaces now hold a toast on screen while measuring.

The guard's own rules that must not be softened:
- `retries: 0` and `forbidOnly: true`. A guard that may pass on the second go, or quietly run a subset, is not a guard.
- **Disabled controls are measured.** A disabled button that renders off-screen is still off-screen the moment it enables — that is exactly how the Approve button shipped.
- Controls are scrolled to through the panes a person can actually scroll, **never `Element.scrollIntoView`**, which also scrolls `overflow: hidden` boxes and would report a sliced-off button as reachable.
- A control passes only when it is on screen, unobstructed, at least **50%** of the size it was promised, and at least **75%** of it answers a click, sampled over a 5×5 grid plus an 84-point perimeter walk.
- The 960x1040 project sits **exactly on the 60rem breakpoint**, where the shell stacks and the dock goes full width. Nothing else in the repo reaches that width.

**Other pitfalls already paid for:**
- `noUncheckedIndexedAccess` is on. Every indexed read needs a `?? fallback`, in tests too.
- `exactOptionalPropertyTypes` is on. `hero_url: undefined` is not assignable; `null` is. Test builders must pass `?? null`.
- `tests/` and `layout/` are inside the TypeScript program, so `pnpm build` typechecks them. A broken test file fails the **build** stage, not just the test stage.
- The autouse `_reset_backup_state` fixture clears the process-global `backup._last_snapshot` before and after every test. The backup throttle is module state; a test that forgets it will see a snapshot silently skipped.
- The `main.py` lifespan closes the **module-global** `get_agent_runtime()`, not a dependency-overridden one, which is why the shutdown test monkeypatches `tv_watchlist.main.get_agent_runtime`.
- Playwright resolves `PLAYWRIGHT_JUNIT_OUTPUT_NAME` against the **config's** directory, not the cwd — the report lands at `app/frontend/layout/junit-layout.xml`.
- `test-layout` is a dangling leaf in the CI graph: nothing `needs:` it, so a guard failure marks the run failed without stopping `build` or `docker-build`. Read the guard's result; do not assume a green `build` means a green guard.
- **The throwaway database is named for the process that owns it, and nothing may weaken that.** The session start rebuilds it with `DROP DATABASE … WITH (FORCE)`, so when two local pytest runs shared one `tv_test` the second terminated the first's connections and removed its tables mid-suite — `ConnectionDoesNotExistError`, then `UndefinedTableError` on a table the migration had just built, then `UniqueViolationError` on `pg_database` when both reached CREATE at once. It reads as an order-dependent, "moving" failure and is not: solo runs were always green. `database_name()` (`tests/database_support.py`) therefore folds the pid in — `tv_test` becomes `tv_p<pid>_test`, the pid before the suffix so `require_disposable_database` still checks it — the `database_url` fixture drops it at session end, and the session start reclaims siblings whose pid is gone. **The fixture rule that prevents the whole class: every connection to the database comes from the session-scoped `database_url` fixture, and no test may name a database the harness did not derive.**
- **`layout/support/openProbe.ts` waits with `Promise.allSettled`, not `Promise.all`** (Ruling 43, T32). A CSS transition that is cancelled mid-flight rejects its `Animation.finished` promise with an `AbortError`, so a `Promise.all` over the page's animations turned an ordinary repaint into a failed run — a pre-existing 1–3 in 152 flake nobody could reproduce on demand. `allSettled` waits for each animation to *settle* whichever way it settles, which is what "the page has stopped moving" actually means. Do not tighten it back.
- **Test-to-test duplication is extracted the moment it is found** (Ruling 42), not queued: `tests/workbook_edits.py` holds shared sheet edits such as `narrow_the_status_dropdown`, `tests/statement_support.py` holds the one `before_cursor_execute` statement tap (`counted_statements`), and `tests/ingest/ingest_support.py` holds the recorded ingest harness. A hand-rolled second copy of any of them is the bug.

</testing>

---

<change_policy>

## 17. Change policy & local documentation

### 17.1 Which document changes for which change

| Change | Must update |
|---|---|
| Any non-trivial change at all | `docs/status.md`, `docs/versions.md` |
| Architecture decision, phase scope, gate criteria, technology choice | `docs/TV_MASTER_PLAN.md` **first**, before the code |
| A data contract (Pydantic model ↔ TypeScript type ↔ database column) | Section 5 (data contracts) **before** the change is made, plus `docs/TV_MASTER_PLAN.md` |
| A new or changed host port | `docs/status.md`, `docs/versions.md`, **and** `C:\Users\Amram\IMPORTANT\Projects\PORT_ASSIGNMENTS.md` — both the per-project inventory entry and the final host-listener map row |
| A new untrusted-input boundary (endpoint, socket, file loader, scraper, LLM call, upstream API client) | Section 10 (security), naming the injection classes it is exposed to and the defence in the code |
| How to run, test, lint or build anything | `README.md` (repository-facing) and/or `app/README.md` (app-facing), plus section 15 here |
| A new phase, or a change to the phase sequence | `docs/TV_MASTER_PLAN.md`, then `README.md` — which carries a **phase-flow Mermaid diagram** (`P0 → P1 → P2 → P3`, with the ADR-014 build order (P1 → P3 → P2 deferred) annotated) because the global contract requires a phased project's README to have one. Task T01c added it; keep it current |
| The Phase 1 resolver dry run | `docs/resolver-dry-run.md` — a durable document with one row per workbook, **not** `docs/status.md`, which is not a log |
| A task's scope, dependency, status or acceptance criteria in Phase 1 or Phase 3 | `docs/phases/phase-1-plan.md` or `docs/phases/phase-3-plan.md` (planned — written when Phase 1 closes; until then the Phase 3 task table in `docs/TV_MASTER_PLAN.md` and ADR-014 carry the breakdown) — the per-phase breakdown — **and** the task table in `docs/TV_MASTER_PLAN.md`, which stays the authoritative list. The phase plan elaborates; it never contradicts |
| A Phase 3 contract change (`CuratedEntryRead`, `JellyfinItemChoice`, `Availability`, `jellyfin_item`, `streaming_offer`, `title.jellyfin_item_id`, `ColumnRole`, the `/api/playback`, `/api/library`, `/api/titles` or `/api/entries` routes) | Section 5 (data contracts) and section 13.5 here **before** the code, `docs/TV_MASTER_PLAN.md` ADR-014 (or a new ADR if it changes a decision there), `docs/phases/phase-3-plan.md` (planned — written when Phase 1 closes; until then the Phase 3 task table in `docs/TV_MASTER_PLAN.md` and ADR-014 carry the breakdown), and the matching `app/frontend/src/types/*.ts` mirror in the same change. Minor bump |
| A new environment variable | `.env.example` (T01b), plus section 8 (environment configuration) |
| A new design note about a subsystem | `app/docs/` — that directory is design notes and stays that way |
| A CI stage, scanner, or coverage floor | `README.md`'s CI section and sections 15.6 and 16.2 here |

`docs/status.md` reflects **now**, not history. It is the first thing a new session reads after this file. `docs/versions.md` is the history.

### 17.2 Computing the next version

The source of truth for the current version is:

- **`app/backend/pyproject.toml:3`** — `version = "0.1.0"`
- **`app/frontend/package.json:4`** — `"version": "0.1.0"`

Both are at `0.1.0` today. Read them; never guess, never invent a number.

Semver rules as they apply here:

| Bump | Applies to |
|---|---|
| **patch** `0.1.0 → 0.1.1` | Documentation, comments, styling tweaks, refactors with no behaviour change, test additions. **The pending heading is `0.2.0`** — raised from `0.1.1` when T47a bound host port 8096; further docs-only work goes under that heading, not into a new `0.1.1`. |
| **minor** `0.1.0 → 0.2.0` | A new endpoint, a new module, a new column on a contract, the Postgres data layer, the `ColumnSpec.role` gaining `"identity"` (T22) or `"position"` (T53) — each on its own commit. Any additive contract change is a minor bump. |
| **major** `0.1.0 → 1.0.0` | A breaking change to a data contract, the public API shape, or the architecture. **Always ask before proposing one.** |

### 17.3 The version field itself is the release pipeline's job

**Never hand-edit `version` in `app/backend/pyproject.toml` or `app/frontend/package.json`.** Your job is to record the computed next version as a heading in `docs/versions.md` and to say what it should be. Bumping the field is a release action.

Today this repo has **no release workflow** — `.github/workflows/` holds only `ci.yml` and `codeql.yml`, so nothing bumps those fields automatically. That is a known gap, not a licence to edit them by hand. Adding a manually-triggered release workflow with a `BUMP` variable is its own change, made deliberately, and it goes in the master plan first.

Also never write "Unreleased" as a heading. Compute the explicit number.

### 17.4 One unreleased version at a time

`docs/versions.md` may carry **at most one** version heading above the source-of-truth version. As it stands: the source of truth reads `0.1.0` and `docs/versions.md` already carries `## v0.2.0` (raised from `v0.1.1` on 2026-09-20, when T47a bound host port 8096). This session's work goes **inside that `v0.2.0` heading as a subsection** — not into a new `## v0.2.1` or `## v0.3.0`. A new heading is minted only after `v0.2.0` has actually been released, meaning the version field moved.

If a session's work would raise the pending bump — a patch section that now contains a new endpoint — **rename the existing heading** to the higher number rather than opening a second one. There is one pending version, and it is whatever the accumulated work adds up to.

### 17.5 Git

Git is the owner's. Report what changed and suggest a commit message; never stage, commit, branch, merge, push, tag, stash, reset or clean. Read-only git (`status`, `diff`, `log`, `show`, `blame`) is fine and is often necessary to answer a question honestly.

</change_policy>

---

<empty_state>

## 18. Empty state & onboarding

### 18.1 Zero workbooks in the library

This is a real state, not a hypothetical: point `TV_LIBRARY_DIR` at an empty folder and it is what you get. `discovery.workbook_paths` returns `[]` and `GET /api/categories` answers a fully-populated, entirely empty listing:

```json
{ "categories": [], "unreadable": [], "shadowed": [], "library_dir": "<the path>" }
```

Note it is **not** an error and **not** a 404. An empty library is a valid library.

What the app looks like:

- **The cards wall.** The banner reads `Watch List` with the tally `0 categories · 0 entries · 0 watched`. The `.cards` grid contains exactly one tile: **"Add a category"**, subtitled "Creates a new workbook in the library folder". The loading state (`status === "loading" && total === 0`) resolves the moment the listing arrives, so "Reading the workbooks…" is a flash, not a resting state.
- **The sidebar.** The wordmark and the library path render normally — the path is the onboarding, because it tells you exactly which folder to drop an `.xlsx` into. The find-a-category box renders. The list renders one row: **"No category matches that name."** — because that row's condition is `listing !== null && categories.length === 0` (`Sidebar.tsx:46-48`), which an empty library satisfies just as a fruitless search does. **This is a known wording gap.** The sentence is wrong when nothing was searched. Fixing it means branching on `query.trim() === ""` and saying something like "No workbooks in this folder yet." — a small change, and it must not be made without also adding the case to the layout guard's surfaces, because an empty library is a screen the owner only sees when something is already wrong.
- **The stage.** `view` is `"home"`, so the stage is the wall. Selecting a category is impossible; there are none.
- **The chat dock.** Fully functional. The library digest opens with `LIBRARY DIGEST — 0 categories, 0 rows already tracked.` and Claude can propose a `create` — which is the intended path out of an empty library, alongside the "New category" button and dropping a file in by hand.

**Three ways out, all first-class:** drop any `.xlsx` into the folder (it appears on the next load; if it has no `Watched?` column the app offers to add one), press **New category** to generate a correctly-shaped workbook, or ask Claude for one.

### 18.2 A category with no matched TMDB data — after Phase 1

**"Tracked but not available here" is a first-class state, not an error.** The watch list is aspirational: it is a plan for what to watch, written before the files exist and independent of whether they ever will. A row that TMDB cannot be matched to, or that no media server holds, is still a row the owner meant.

This has three distinct shapes and they must not be collapsed into one another:

| State | Meaning | What it must look like |
|---|---|---|
| **Unresolved** | The entry has no `title_id` yet, or its `Unit` string did not parse into a span. `resolution_state = 'unresolved'`. | The row renders in full from its verbatim cells — order, title, unit, release, notes, watch status. It sorts in its curated position. It takes entry-level watch events. It carries a quiet "needs review" affordance, not a warning. Nothing about the app is broken while the review queue is unworked. |
| **Auto-resolved** | A heuristic produced a span and nobody has confirmed it. `resolution_state = 'auto'`, with `resolution_confidence` and `resolution_note`. | Renders with the resolved metadata, and with the same "needs review" affordance — **`auto` is not trusted**. A human confirming it sets `confirmed`, and a later heuristic pass may never overwrite a `confirmed` entry. |
| **Not in the library** | Phase 3 only. The entry is resolved, but no file answers to its `tmdb_id`. | An explicit `NOT_IN_LIBRARY` state. Never a null `jellyfinItemId` collapsed into "not found", and never conflated with `AMBIGUOUS` — which is real (absolute-vs-official numbering, multi-episode files) and produces a UI that quietly lies if it is folded into "not in library". |

Rules that follow from this and that the UI must honour:

1. **An unresolved category is a normal category.** The cards wall shows its card, its accent, its artwork, its counts. Counts come from the sheet, which always has them. Nothing about a card depends on TMDB.
2. **Span resolution never invents.** When a `Unit` parse is ambiguous, or the named order does not exist for that title, the entry is left `unresolved` with a note — it is **never** silently resolved against `aired` as a fallback. A confidently wrong span is worse than no span, and it is wrong in the direction that looks right on screen. Three parser rules carry that principle and are stated in full at section 10.3, B14: a **blank `Unit`** cell parses at confidence 0.50 with its kind taken from the Type/Format cell, never as a film at 1.00 (Ruling 27); `span_start`/`span_end` are read through `SpanParse.episode_span` / `season_span`, because `Seasons 1-25` puts season numbers in those fields (Ruling 29); and the **season-scoped shape** (`S5 E10-19`) emits `order_type=None`, since eight of the library's 53 such rows number series-wide rather than within the season (Ruling 30).
3. **The review queue is measured, not estimated.** The dry run has been made — twice, and the second run is the one on the final resolver (Ruling 36; live TMDB, nothing written). **830 of 996 rows across 19 workbooks resolve automatically (83%); 166 are left for the review queue; `confirmed` is 0, because the resolver never awards it — a human does.** The confidence rungs are `0.95 × 475`, `0.80 × 187`, `0.65 × 126`, `0.50 × 42`, `0.00 × 166`. `docs/resolver-dry-run.md` is the durable record, with a per-workbook table and each workbook's worst-confidence examples; read it rather than re-deriving the numbers. Three rulings explain the shape of what is left, and each is a deliberate refusal to guess: a **tie** on equal score is `unresolved` with a capped ambiguity note and no chosen candidate, because a coin flip persisted as a match is a confidently-wrong row (Ruling 35 — `RED` (2010) is the worked example, three TMDB films scoring identically); a **franchise-form match at 0.65** is the form working as intended and belongs in the queue rather than in the resolved set (Ruling 40); and the queue's predicate is simply `resolution_state IN ('unresolved','auto')` — the partial index `ix_curated_entry_needs_review`'s own predicate, with **no confidence threshold anywhere** (Ruling 47), so the 830 auto-resolved rows are reviewable too and the 166 are merely the worst of them. 166 is small enough that `unresolved` stays an exception state rather than the default rendering mode, which was the open question this measurement settled.
4. **The workbook keeps meaning something on its own.** That is the whole point of the dual store. A category whose Postgres side is entirely unresolved still opens in Excel, still shows the owner's watch order, and still carries a `Watched?` column that means what it always meant.
5. **An unresolved entry is retried by an edit, by a human's "Retry resolution" press, or by the review queue's confirm/correct — never by an Excel open** (Ruling 54, closed at T57). Now that the reconciler skips a workbook whose digest *and* identity cells are both unchanged (Ruling 49), a stamp moved by merely opening and closing a file no longer drags an entry a provider outage left `unresolved` back through resolution — that retry was incidental, never designed. The deliberate paths are: the next full pass over that workbook, where `needs_resolution` (`ingest/reconciler.py:196`) picks up everything still unresolved; the review queue's `confirm`/`correct` (`GET`/`POST /api/review/entries`, T30); and, **built at T57**, `POST /api/review/entries/{entry_id}/retry` — the unresolved view's per-row "Retry resolution" button, which re-resolves exactly that one entry through the same store step the ingest pass uses (`ingest/reconciler.resolve_stored_entry`), refusing with 409 before any provider call when the entry is `confirmed` or `rejected`, or when no provider is configured. The bootstrap runner gained no `--force` flag — the per-entry retry route closed the gap that flag would have covered.

</empty_state>

---

<phase_gate>

## 19. Phase 1 and Phase 3 completion gates

**The Phase 1 gate is `docs/TV_MASTER_PLAN.md` section 10.1; the Phase 3 gate is section 10.3. The project-specific items below are IN ADDITION to them, not a replacement.** If the two ever disagree, the master plan wins and this section is the thing that gets corrected. Phase 3 follows Phase 1 directly (ADR-014); its four project-specific items are at the end of this section. Phase 2's gate (section 10.2) is deferred with the phase.

Phase 1 is the **metadata spine**: a Postgres projection alongside the workbooks, fed by TMDB (identity, artwork, metadata) and TheTVDB v4 (alternate episode orders), with watch progress as an append-only log mirrored back into the sheets' four-value `Watched?` cell.

Requirements that used to live only here now live in the master plan's 10.1, where they belong — do not restate them as a rival list, satisfy them there: `expire_on_commit=False` with `lazy="raise_on_sql"`; provider clients driven by recorded fixtures with **zero** live network calls in the test suite; section 10 (security) updated with the two new input boundaries; and the `README.md` reconciliation (task T01c). The dry-run resolver report, the attribution rendering, the `[q]`/`[v]` launcher additions, the coverage floors, the compose bring-up and the `PORT_ASSIGNMENTS.md` row live there too, for the same reason.

What follows is the code shape that 10.1 assumes but does not spell out. Every line is required.

**Data layer**
1. `app/backend/src/tv_watchlist/data/` exists with `base.py`, `session.py`, `enums.py` and one model per file under `models/`, and `models/__init__.py` imports every model so `Base.metadata` is complete for Alembic.
2. All eleven Phase 1 tables exist in `0001`: `category`, `curated_entry`, `curated_entry_item`,
   `title`, `season`, `episode`, `episode_order`, `external_id`, `artwork`, `watch_event`, `sync_state`.
   Later revisions add `jellyfin_item`, `media_import`, `media_import_operation`, `playback_completion`
   and `playback_completion_event` (sixteen domain tables at head `0005`); T55's future
   `streaming_offer` makes seventeen. Later-phase tables are not
   Phase 1 gate criteria.
3. `alembic/` and `alembic.ini` exist. The migration requirement is the master plan's full round trip — `alembic upgrade head && alembic downgrade base && alembic upgrade head` green in CI against a real Postgres 16 — not a single-step reversal.
4. Every duration column is `Integer` named `*_seconds` with a `CHECK`. No `INTERVAL`. Every timestamp is `DateTime(timezone=True)`.
5. The curated chain (`category` → `curated_entry`) is soft-deleted; metadata cascades. `watch_event.curated_entry_id` is `ON DELETE RESTRICT`.

**Ingest and reconciliation**
6. `ColumnSpec.role` has gained `"identity"` (T22; `"position"` is Phase 3's, at T53, and is gated in 10.3 — not here), `workbook/schema.py:_role_for` (`schema.py:28`) knows that alias, and `reader.read_category` excludes the app-owned role from `columns` and from `WatchRow.cells` — so the grid the UI renders is byte-identical to before and no `RowWrite` can address that column.
7. `workbook/identity.py` writes and hides a `Row ID` column at the far right of each sheet, and `ranges.sync` (`workbook/ranges.py:87`) covers the new width so Excel does not report the table as damaged.
8. Every ingest write to a workbook goes through `Catalog._write` (`services/catalog.py:131`). Nothing calls openpyxl directly outside `workbook/`.
9. The mirror pass loses cleanly to a user edit: it retries on `StaleWorkbookError` rather than winning the race.

**API and contracts**
10. The five Phase 1 routes exist and the existing `CategoryDetail` contract is **unchanged**: `GET /api/categories/{category_id}/entries` → `list[CuratedEntryRead]`; `POST /api/watch-events` → **201 `WatchEventRead`**, the event as recorded with `progress: EntryProgress` nested (Ruling 44); `GET /api/categories/{category_id}/entries/{entry_id}/progress` → `EntryProgress`; `GET /api/review/entries` → `list[CuratedEntryRead]`; `POST /api/review/entries/{entry_id}` → `CuratedEntryRead`. Section 13.5 tables all five with their query parameters and statuses. The review queue's predicate is `resolution_state IN ('unresolved','auto')` with **no confidence threshold** (Ruling 47).
11. Every request model carries `extra="forbid"`; every response model carries `frozen=True` and `from_attributes=True`.
12. The `ColumnSpec.role` change is written into section 5 (data contracts) **before** the code lands, and mirrored in `app/frontend/src/types/ColumnSpec.ts`. So is every other additive contract field, `CuratedEntryRead.resolution_note: str = ""` included (Ruling 45 — a `str`, never `None`, because the column is `NOT NULL DEFAULT ''`), each mirrored in its `app/frontend/src/types/*.ts` twin and each a **minor** bump.

**Providers**
13. TMDB and TheTVDB clients are `httpx`-based, serialised through one token-bucket-throttled worker per upstream, with a persistent response cache in Postgres in front. No per-request fan-out.
14. The cache honours TMDB's hard **six-month** retention clause and TheTVDB's one-month token life (re-login proactively at ~25 days).

**Quality gates**
15. `uv run ruff check .` and `uv run ruff format --check .` are clean, with the `S` family on and no new `# noqa` that is not justified in a comment.
16. `pnpm exec tsc -b` and `pnpm lint` are clean.
17. pytest is green against a **real Postgres 16 service container**, with per-test rollback. Vitest is green. `pnpm test:layout` is green at all four viewports.
18. Every test job publishes its own JUnit XML through `dorny/test-reporter@v1` with `reporter: java-junit`, `checks: write`, and `if: ${{ !cancelled() }}`.

**Documentation**
19. `docs/status.md` and `docs/versions.md` are current, and the version computed for the phase is a **minor** bump recorded as a single heading.

### Phase 3 — the four project-specific items (in addition to `docs/TV_MASTER_PLAN.md` section 10.3)

Section 10.3 owns the Phase 3 gate: `compose` brings `jellyfin` up healthy on `8096` and the backend boots and serves with `jellyfin` stopped; the proxy honours `Range` (206), passes `Content-Type`, sets `Accept-Ranges: bytes` and never buffers (tested through a mock Jellyfin); `Position (s)` is written every 60 seconds and on pause, ended and unmount, and excluded from `columns` and `cells`; the picker persists `title.jellyfin_item_id` and the next sync respects it; the unresolved view lists every `unresolved` / `auto` entry with raw cells and is reachable from the main nav; every `NOT_IN_LIBRARY` entry offers the launcher (no key → the shell without a link; a Disney+ hand mark opens `/browse/entity-…`); `PORT_ASSIGNMENTS.md` carries `8096`; the pinned image is `jellyfin/jellyfin:12.1`; SAST green with zero HIGH findings. Satisfy those there. What follows is the code shape 10.3 assumes but does not spell out.

20. **The proxy never leaks the key — proven, not assumed.** `TV_JELLYFIN_API_KEY`'s value appears in exactly one place at runtime, the `Authorization` header the Jellyfin client builds (B16). The gate audit greps the built `app/frontend/dist/` bundle, the backend access log from a full playback session, every error envelope the proxy can return (404, 416, 502, 503) and the `CuratedEntryRead` payload for the key's value and for any Jellyfin URL, and finds none. The `<video src>` is the same-origin `/api/playback/{jellyfin_item_id}/stream` path and nothing else; the CSP at `nginx.conf:40` gained no `media-src`.
21. **Automatic snapshots reach both stores every minute (R105).** A five-minute playing session produces five logical PostgreSQL-plus-Excel snapshots, followed by immediate pause/ended/close saves when changed. Duplicate terminal callbacks do not append progressed after completion. Each workbook snapshot uses one Catalog write, one backup and one atomic swap; Excel locks return 423 while retaining the database event, and stale snapshots cannot overwrite a newer save or a human edit. Tests prove projection-only retry, current Row ID checks before the first write, safe one-retry races and all-episode completion only on whole-file ended. Position is the same integer posted in the event and is never ingest truth.
22. **Picker persistence survives the next sync.** A test picks one of two ambiguous `jellyfin_item` rows for a title through `PATCH /api/titles/{title_id}/jellyfin-item`, runs `library_sync` against a mock Jellyfin that still reports both files, and asserts `title.jellyfin_item_id` is unchanged, the entry's `availability` is `in_library` with that `jellyfin_item_id`, and a pick naming an item that does not belong to the title's `tmdb_id` is a 409 that writes nothing. Soft-deleting the picked item (`removed_at`) returns the entry to `ambiguous`; purging it nulls the column (`ON DELETE SET NULL`) rather than failing.
23. **Every `NOT_IN_LIBRARY` entry offers the launcher fallback, in every configuration.** With no `TV_STREAMING_AVAILABILITY_API_KEY`: the shell renders with its wording and a disabled control, never an empty cell. With a key and cached offers: one button per offer, each opening in a new tab with `noopener,noreferrer`, and the attribution line present. With a hand-marked Disney+ row: the `/browse/entity-…` link. In all three, the layout guard has a surface for the panel at all four viewports, no chat surface can see the offers, and nothing about the row's editing (`CategoryDetail`, `RowWrite`) changed.

</phase_gate>

---

<phase_transition>

## 20. Phase transition strategy

The sequence is **Phase 0 → Phase 1 → Phase 2 → Phase 3**, and it starts at zero because the app already exists. **Phase 0 — the shipped workbook app** is everything described in sections 3-5 and 12-16: nineteen workbooks, the FastAPI + openpyxl backend, the React frontend, the chat subsystem, the layout guard and the CI pipeline. It is closed by this documentation pass — tasks T00, T01, T01a, T01b and T01c, all five checked by the Phase 0 gate (`docs/TV_MASTER_PLAN.md` section 10.0). Nothing below is a migration away from Phase 0; each phase adds beside it.

**Build order after 2026-09-20 (ADR-014): P0 close → P1 → P3 → P2.** The numbering is canonical; the construction order is not the numbering. Phase 3 follows Phase 1 directly because every Phase 3 deliverable joins on Phase 1 artefacts, and Phase 2 is the only part of the sequence nothing in Phase 3 needs. Section 20.1 therefore describes a hand-off that happens *after* Phase 3; section 20.2 describes the one that happens next.

### 20.1 Phase 1 → Phase 2 (ten-foot browser UI) — deferred behind Phase 3

**Phase 2 (T34–T45) is deferred, not cancelled (ADR-014).** Nothing in it is dropped and nothing in it may land early; it becomes one coherent change after the Phase 3 gate. Everything below stays true when it does — with the one addition that P2 will inherit Phase 3's surfaces (section 14.9: the play button, availability badge, picker, player overlay, unresolved view and launcher panel) and must give each of them the ten-foot treatment and a 1920×1080 guard run too.

Phase 2 is a **browser app on a TV**, driven from a PC or laptop over HDMI or cast. There is no Tizen `.wgt`, no webOS `.ipk`, no `react-native-tvos`, no app store, and no second codebase. Ten-foot treatment is CSS tokens plus a focus/spatial-navigation library, and nothing else.

What P1 hands P2:

- **A second data source for the same screens.** `GET /api/categories/{id}/entries` exists and is already correct; P2 is where the frontend adopts it. `CuratedEntryRead.cells` is aliased from `raw_cells` specifically so the wire shape matches the existing `WatchRow.cells` contract and the row renderer does not change.
- **Episodes, air dates and runtimes** that the sheet never had — the material a ten-foot row actually needs to show at distance.
- **A review queue** for `unresolved` and `auto` entries, backed by the partial index `ix_curated_entry_needs_review`. This may be P1's largest deliverable and it is P2's first real screen.
- **Real progress**, from the append-only log, instead of a four-value cell. The cell stays as the lossy Excel-facing projection.

What P2 must add, and what it must not break:

- **Spatial navigation:** `@noriginmedia/norigin-spatial-navigation` (MIT). Not `react-tv-space-navigation` (stale), not `bbc/lrud` (archived). It layers over the existing DOM; every control in section 14 already has an accessible name because `measureControls.ts:nameOf` prefers `aria-label` then `placeholder` then text — that naming discipline is what makes focus management tractable.
- **Ten-foot tokens sit beside the existing ones**, in the one place tokens live: `src/styles/tokens.css`. The precedent is already set — `--launcher-width` and `--toast-lane-max` are *behavioural* tokens with comments explaining why they are layout rather than styling. Add the 10-foot type scale and `env(safe-area-inset-*)` there, not scattered through the eight stylesheets. Note that today there are **no** `env(safe-area-inset-*)` references, no `dvh`/`svh`/`lvh`, no `clamp()`, and no container queries anywhere in `src/styles/`.
- **1920×1080 joins the layout guard** as a fifth Playwright project. The existing four (1512×900, 1280×720, 1024×768, 960×1040) stay — a TV layout that breaks the laptop layout is a regression, not a trade.
- **Dark-only stays dark-only** unless a decision says otherwise. `index.html:6` declares `color-scheme: dark`, there is no `prefers-color-scheme` block and no light palette. A TV in a dark room is the correct default; adding a light theme is a separate change.
- **The accent stays data, not a token value.** Each workbook carries its own hex; `accentPalette` lifts it into three legible values and they reach CSS only as inline custom properties on a subtree root. Ten-foot contrast requirements may change the lightness constants — they must not change the mechanism.
- **The two `max-width` breakpoints (68rem, 60rem) are for narrow, not for wide.** A TV is wider than the design, not narrower. Do not repurpose them.

### 20.2 Phase 1 → Phase 3 (playback via self-hosted Jellyfin; Phase 2 deferred)

Phase 3 exists only once a real file library exists, and it now does: **the owner's own video files are on disk (T46 satisfied 2026-09-20)**, indexed by a self-hosted `jellyfin/jellyfin:12.1` declared as a compose service to index them (T47a) — the container has not started yet; see section 6 and `docs/status.md` §0. That is why Phase 3 is built next, directly after the Phase 1 gate, rather than after Phase 2 (ADR-014). The basis for playing them is ADR-013 — personal, single-instance, local files, no internet at playback time, one user, one machine — and it is decided; there is no further review gate. The ADR-012 launcher ships in the same phase as the behaviour of every `NOT_IN_LIBRARY` entry, so a title the owner still streams from a subscription opens in a new tab on that subscription, on a press, and never through anything unlicensed.

The join key is **`tmdb_id`, chosen in Phase 1** and already carried by `watch_event.tmdb_key` (`movie:603`, `tv:1399:s2:e5`) as the log's own durable pointer — so watch history survives every metadata rebuild and joins to a media server without a migration.

What P3 needs from P1, stated now so P1 does not make it impossible:

1. **An inverted index the app maintains itself.** Jellyfin has **no provider-ID lookup endpoint**. There is no `?tmdbId=` filter. P3 must page `/Items?recursive=true&includeItemTypes=Series&hasTmdbId=true&fields=ProviderIds` once, build `ProviderIds.Tmdb → Id`, cache it, and refresh on `minDateLastSaved`. Anyone who assumes the filter exists will discover it does not only after the data model is built around it.
2. **Three-layer join, in order:** series by provider id (exact, the only layer that may ever produce a match — **never fuzzy-match series titles**, anime romaji/English/synonym variants produce wrong matches silently); episodes by `(ParentIndexNumber, IndexNumber)`; then state from `UserData`. `PlaybackPositionTicks` is .NET ticks (100 ns), not milliseconds. `IndexNumberEnd` non-null means one file covers a range, so one library file satisfies several watch-list rows.
3. **Resolve the TVDB order before the episode join, and store which order was used — built at T50.**
   `numberings_for(entry)` selects the stored numbering, including unit-kind/specials rules; the join
   uses `EpisodeOrder.order_season_number` / `order_episode_number`, never TMDB's raw season pair
   or arithmetic over sequence. `IndexNumberEnd` can map several queue slots to one file.
   `EpisodeMatch` reports state, range coverage, order type and label; its UI presentation belongs to
   T52. `episode_lookup.within_numberings` is shared with `episode_for_sequence`, which T65 reuses.
   A soft-deleted owner pick remains ambiguous while candidates survive (R98). The provider's
   season-type vocabulary is still fetched at runtime, not hard-coded; no read-time fallback to
   aired numbering is permitted.
4. **Three explicit states per row** — `IN_LIBRARY` / `NOT_IN_LIBRARY` / `AMBIGUOUS` — not a nullable id.
5. **Progress writes to both stores.** A playback position is a `watch_event` in Postgres and, when it crosses into a coarser state, a mirrored `Watched?` cell in the workbook. `position_seconds` is an integer of seconds precisely so `position_seconds >= runtime_seconds * threshold` needs no cast.
6. **Next and Autoplay follow the curated order**, not a series' own episode order. From a One Piece episode whose next row is a film, both play the film; after it, the next episode in order. The queue is `curated_entry_item` by `absolute_position`, which holds movie entries as single slots for exactly this reason, and the full rule set — `Skip` items passed over, an unplayable item never silently jumped, one category's order at a time — is `docs/TV_MASTER_PLAN.md` §6.9 and ADR-010. Across streaming services there is no Autoplay at all — Next is a press (ADR-012 rules 4 and 5).
7. **The stream reaches the browser through the backend, never directly.** A `<video>` element cannot send an `Authorization` header, so `GET /api/playback/{jellyfin_item_id}/stream` relays Jellyfin's `/Videos/{id}/stream` with the key in a header — `Range` through both ways, `Content-Type` through, `Accept-Ranges: bytes` set, streamed never buffered (B17). Same-origin, so the CSP needs no `media-src` and nginx no Jellyfin upstream. The key never leaves the server.
8. **Position is an integer of seconds from the first line.** `ticks // 10_000_000` for anything Jellyfin reports, `round(video.currentTime)` for the browser, once, at the boundary (section 11.2, rule 7). The `Position (s)` sheet column is the same integer, written every 60 seconds while playing and on pause, ended and unmount.

Decisions P3 has made, and the one it still owes: **the Jellyfin server version is decided — `jellyfin/jellyfin:12.1`** (verified 2026-09-20 against Docker Hub and the GitHub release feed: 12.1 released 2026-09-15, 12.0 on 2026-09-08), pinned in compose, closing deliverable 3.7 and T47; **there is no `@jellyfin/sdk`** in the project, because only the backend talks to Jellyfin and it does so over `httpx` — the stale note that the latest SDK targets 10.11.x is moot. **Still to confirm live with the owner at T54 (R79 permits the documented OpenAPI-derived fixtures until then):** the exact casing of `ProviderIds` keys (`Tmdb` vs `TMDB` vs `tmdb` — the schema is `additionalProperties: string` with no enum). The sync reads the key through one explicit lookup so the confirmed spelling changes one line.

**Rejected, permanently, for the record:** `streambert` (github.com/truelockmc/streambert) — an Electron desktop client, GPL-3.0, that scrapes unlicensed stream hosts and rips m3u8 with ffmpeg, self-tagged "piracy". Zero technical overlap with this app, licence contagion, legal exposure. The contagion ground does not rest on the repository becoming open: the repository carries no LICENSE file, so vendoring GPL-3.0 code would settle the licence question as a side effect of a code-reuse convenience rather than as a decision — and would settle it on GPL-3.0. ADR-009 is now decided (owner, in-session, 2026-09-20): repository licence — all rights reserved; the repository stays public and unlicensed on purpose, no `LICENSE` file is added now or later, and nobody else may reuse the code. `app/heroes/` artwork is Wikimedia PD/CC0/CC BY material and stays governed by `app/heroes/ATTRIBUTION.md` regardless. It is recorded as ADR-006 in `docs/TV_MASTER_PLAN.md` and summarised in the status and versions entries for this change. Nothing from it is adopted. **Trakt** is design inspiration only and is not adopted as a service — its February 2026 free tier caps at 1,000 total list items, which is fewer than this library already tracks. **Plex** is not adopted: its 2026 remote-streaming paywall extends to third-party API clients.

</phase_transition>

---

<self_audit>

## 21. Task completion self-audit

Run this at the end of **every non-trivial task**, before declaring it done. Report the result. If an item fails, say so explicitly — do not paper over it.

### The universal ten

1. **Summary** — one or two sentences: what changed and why.
2. **Reuse check** — name the files you grepped before writing anything new. This repo has 12 utils, 9 hooks, 31 components, 16 API functions and 20 types, all one-concept-per-file; the odds that what you need already exists are high. If you wrote something new, say why nothing existing fit.
3. **Tech-debt check** — no shortcuts, no duplicated logic, no `any`/`Any`, no dead code, no commented-out blocks, no vague names, no `TODO` without a linked task. If a tradeoff was made, say why it was the least-debt option.
4. **File-organisation check** — one concept per file. No god file created or expanded. The one sanctioned exception in the whole project is `data/enums.py`, and it is argued for in the schema design.
5. **Data-contract check** — see the project item below; the universal form still applies to any type crossing a boundary.
6. **Docs check** — list every doc updated: `docs/status.md`, `docs/versions.md`, `docs/TV_MASTER_PLAN.md`, `README.md`, `app/README.md`, `app/docs/`. For `versions.md`, state the computed next version and the semver reasoning, and confirm you did not open a second unreleased heading. If a host port changed, confirm `PORT_ASSIGNMENTS.md` was updated.
7. **Test check** — list the tests added or updated. State the suite results you actually ran, not the ones you expect.
8. **Forward-compatibility check** — does this align with the next phase's requirements in `docs/TV_MASTER_PLAN.md`? Would it break P2's ten-foot layer or P3's `tmdb_id` join?
9. **Git state** — what files changed. Suggest a commit message, clearly labelled as a suggestion. You did not commit; you do not commit.
10. **Security check** — confirm the local SAST set (section 15.6) was run and is clean. For every input boundary touched, name the injection class(es) — SQL, command, path, XSS, SSRF, deserialisation, template, header/log, prompt — and the specific defence in the code. If a new boundary was added, confirm section 10 (security) was updated.

### The four project-specific items

**11. Excel-safety check.** Did every write to a workbook go through the funnel? Concretely: `Catalog._write` → `_mutate`, in this exact order — `guard_fresh(path, expected_mtime)` → `backup.snapshot(...)` → the `workbook.writer` call → `_invalidate(path)` → `_read_live_lock(path)`, all inside `async with lock_for(path)` and on a worker thread. Confirm:
   - The **freshness guard** ran. Every mutating call carries `expected_mtime` (body for `RowWrite`/`CategoryRename`, required query parameter for the three bodyless ones, `ProposalEdit.read_mtime` for a chat approval).
   - The **Excel lock** was honoured. `workbook/writer.py:_open` (`writer.py:43`) refuses a locked file with 423 before loading, and `workbook/writer.py:_install` (`writer.py:50`) short-circuits its retry loop the moment a `~$` owner file appears.
   - A **backup** was taken. Only `update_row` is throttled; everything else snapshots unconditionally.
   - The write was **atomic** — temp file in the same directory, then `os.replace`. The original is never truncated; the temp is unlinked on any exception.
   - **Nothing was deleted.** Retiring moves the workbook and every hero suffix into `.backups` under a `retired-` stamp that pruning can never reach. Replacing artwork moves the old image aside.
   - `ranges.sync` ran if rows moved or the grid widened, so the table ref, dropdowns and conditional formats still cover rows 2..last.
   - **A digest-equal, identities-intact ingest pass performs zero writes** (Ruling 49 as amended). If the normalised grid's sha256 is unchanged **and** the sheet's `Row ID` cells still match the live entries' ids — the digest leaves that column out by design, so it cannot see an identity someone cleared or duplicated — the reconciler records the new `workbook_mtime` on `category` and stops: no row updates, no provider calls, and above all no workbook write. Excel opening and re-saving a file moves the stamp without changing a cell, and that must cost nothing. If your change made a no-op pass open a workbook for writing, it is a defect.
   If your change wrote to a workbook outside this funnel, that is a defect, not a shortcut.

**12. Contract check against the derived-column-schema rule.** The sheet's own header row and data validations **are** the schema. Confirm:
   - Nothing keys on a fixed column index. Columns are found by `role` (`order` / `title` / `watch` / `identity` / `other`, plus `position` after T53), and cells by the slugified column **key**, never by the header label.
   - The grid still ends at the **first blank header cell**, never at `sheet.max_column`.
   - `kind` is still derived from data validations, not from the header text; a `choice` column still refuses a value its own dropdown does not offer.
   - No Pydantic model, TypeScript interface or database column that crosses a boundary changed shape without being written into section 5 (data contracts) **first** and flagged as a minor bump. The pairs that must move together: `ColumnSpec` ↔ `ColumnSpec.ts`, `WatchRow` ↔ `WatchRow.ts`, `CategorySummary`/`CategoryDetail` ↔ their `.ts` twins, `CatalogListing` ↔ `CatalogListing.ts`, `RowChange`/`Proposal*`/`HeroCandidate`/`ChatEvent` ↔ theirs.
   - Field names are identical on both sides. `snake_case` crosses the wire; `camelCase` exists only in frontend-only shapes.

**13. Layout-guard check.** For **any** change that touches `src/components/`, `src/styles/`, or anything that alters what renders: was `pnpm test:layout` run, and did it pass at all four viewports? State the result. jsdom has no layout engine — Vitest passing tells you nothing about whether a control is reachable, and five shipped bugs are the evidence. If the change adds a new screen or a new overlay, was a surface added to `layout/surfaces.ts` and an arrangement to `layout/probes/arrangements.ts`? A new screen with no surface is an untested screen.

**14. Dual-store check.** Phase 1 onward: was progress written to **both** stores? A watch fact is an append-only `watch_event` row in Postgres **and**, when it changes the coarse state, a mirrored value in the workbook's four-value `Watched?` cell — through `Catalog._write`, never straight to openpyxl. Confirm:
   - The mirror is **one-directional and lossy by construction**, and the cell is **never read as truth** — only as a signal that a human changed it, which appends one more coarse `excel_mirror` event rather than overwriting anything.
   - `mirrored_watch_cell` (what we last wrote) and `observed_watch_cell` (what we last read) are both maintained, or the reconciler cannot tell our own echo from a human edit.
   - The mirror **loses** a race with a user edit and retries, rather than winning it — per row, through `_still_ours`, which re-checks both the `Row ID` and the last-written cell value before it will retry at all.
   - **A value outside the sheet's own status dropdown is skipped, not written** (Ruling 41), logged with `skipped=invalid_choice`, and the rest of the diff still goes in. The mirror never fails an ingest pass; the entries behind the skipped cells keep their old `mirrored_watch_cell`, so nothing claims a write that never happened.
   - The workbook still means something opened standalone. If your change made a workbook depend on Postgres to be readable, it broke the premise of the dual store.

</self_audit>

---

<closing_reminder>

## 22. Closing reminder

Re-read this entire file before the next change. Not a section of it — all of it. Prior sessions do not carry over, and every rule here exists because a generic default would have been wrong.

Then, in order: `docs/TV_MASTER_PLAN.md`, `docs/status.md`, `docs/versions.md`, and the source files you intend to touch.

The three sentences that carry this project:

1. **The workbooks are the point.** Nineteen `.xlsx` files, hand-curated over years, that must still open in Excel and still mean what they meant. Postgres is a projection beside them, never above them.
2. **A refusal is a feature.** 423 when Excel holds the file, 409 when it changed underneath you, 503 when the CLI is absent — every one of those is the app declining to destroy something, and none of them may be softened into a silent success.
3. **jsdom has no layout engine.** Run the guard.

**Maximal clarity. Minimal tech debt. Optimal alignment.**

</closing_reminder>
