# Automatic snapshots and recoverable imports — 2026-09-24

Scope: owner-approved **T53 / R105** and **T66 / R106**, on the existing dirty working tree.
Git belongs to the owner. No real workbook, owner media, credential file or running service was
modified. The previous completed checkpoint is [T52/T65 validation](playback-import-validation.md).

## Verification checkpoint

T53 and T66 are implemented, independently reviewed and locally verified. The Phase 3/3.5 gates,
deployment, remote CI and live owner-media verification remain open; this is not app completion.

| Check | Measured result |
|---|---|
| Full backend, real PostgreSQL | **3891 passed, zero skips**, 100.42 s; **98.93%**, 9347/9448 statements, Python 3.14.7. Final frozen-source run; all new runtime modules reach 100%. |
| T53 focused backend | **198 passed, zero skips**, 13.98 s; **256/256 statements** across six API/model/service subjects. |
| T66 focused backend | **154 passed, zero skips**, 13.59 s; **607/607 statements** across seven new runtime modules. Includes real-PG migration round trip and metadata parity. |
| Workbook regression | **147 passed**, 4.69 s; new `workbook.position` **23/23 statements**. Shape-selected copies of all nineteen owner workbooks; originals untouched. |
| Frontend | **320 passed / 46 files**; lines/statements/functions/branches **81.01/80.73/73.38/72.75%**. All eight new runtime modules **100%**: 103 lines, 123 statements, 29 functions, 70 branches. |
| Layout | **196 passed**, 24.0 s, 23 surfaces and four Chromium viewports. Includes both new retry surfaces. One concurrent earlier run measured an existing attribution logo at 0×0; isolated and full reruns passed without unrelated edits. |
| Hooks | **31 passed**. |
| Backend lint / format | Ruff passes; **444 files** already formatted. |
| Frontend quality gates | TypeScript, scoped ESLint and build pass; 147 built modules. Whole-tree lint: zero errors, three existing generated-coverage warnings. |
| Backend build | `uv build --offline` passes with version **0.1.0**. |
| Frontend dependency audit | `pnpm audit --audit-level=high`: no known vulnerabilities. |
| API / schema inspection | **21 OpenAPI paths / 24 operations**, eight routers; **14 domain tables**, single Alembic head **0004**. App inspection disables dotenv first. |
| Compose / services | Compose validates with dotenv disabled. Read-only inspection: PostgreSQL and Jellyfin healthy; neither restarted. |
| Docker builds | **UNVERIFIED.** Both fresh standalone attempts stalled resolving `docker.io/docker/dockerfile:1`; cancelled after approximately 45 s, before application build steps. |
| Full security-scanner set | **UNVERIFIED.** Semgrep, gitleaks, Trivy and Python dependency auditor unavailable; no scanner images cached or tools installed. |
| Remote CI / Windows / live owner media | **UNVERIFIED.** No push, remote run, Windows execution, real-media import or live-playback certification. |
| Versions / git | Manifests remain **0.1.0**; one pending **v0.2.0**. No git mutation. Diff whitespace check passes with existing CRLF-normalisation notices. |

Project floors remain backend **97%**, frontend **56/54/45/45**. No threshold was lowered and no
coverage exclusion was introduced. PostgreSQL tests use the PID-isolated disposable database
harness; file tests use temporary bytes and workbook copies, never the live library.

Artifacts, local and ephemeral:

- `/tmp/tv-snapshots-recovery.uL7ckA/backend-coverage.json`
- `/tmp/tv-snapshots-recovery.uL7ckA/backend-junit.xml`
- `/tmp/tv-snapshots-recovery.uL7ckA/workbook-coverage.json`
- `/tmp/tv-t53-backend.XTV6wY/coverage.json`
- `/tmp/tv-t66-coverage.json`
- `app/frontend/node_modules/.coverage-t53/coverage-summary.json`

Whole-backend reproduction from `app/backend` (the harness owns disposable database creation):

```sh
rtk proxy env TV_REQUIRE_POSTGRES=1 TV_POSTGRES_DB=tv_test COVERAGE_FILE=/tmp/tv-snapshots-recovery.uL7ckA/backend.coverage uv run --no-sync pytest -q --cov=tv_watchlist --cov-report=term:skip-covered --cov-report=json:/tmp/tv-snapshots-recovery.uL7ckA/backend-coverage.json --cov-fail-under=97 --junitxml=/tmp/tv-snapshots-recovery.uL7ckA/backend-junit.xml
rtk proxy uv run --no-sync ruff check .
rtk proxy uv run --no-sync ruff format --check .
rtk proxy uv build --offline
```

From `app/frontend`: `rtk proxy pnpm test`, `rtk proxy pnpm exec tsc -b`,
`rtk proxy pnpm lint`, `rtk proxy pnpm build`, `rtk proxy pnpm test:layout` and
`rtk proxy pnpm audit --audit-level=high`. From the root:
`rtk proxy node --test scripts/hooks/hooks.test.cjs` and
`rtk proxy env COMPOSE_DISABLE_ENV_FILE=1 docker compose --env-file /dev/null config --quiet`.
Vitest coverage used `rtk proxy pnpm exec vitest run --coverage --coverage.reportsDirectory=node_modules/.coverage-t53`.

## Decisions and review corrections

- Both stores save every **60 seconds while playing**, plus pause, ended and close/unmount.
  Never-played videos do not save; terminal callbacks deduplicate, while native Replay starts a new
  reporting cycle. Browser/process termination cannot guarantee a final asynchronous request.
- The existing watch-event body/response remains unchanged. Paired UUID player context validates
  live category/entry, actual selected file and exact queued subject; the server derives PLAYER.
  Known runtime clamps progress; completion requires the file end, not a percentage threshold.
  PostgreSQL Integer overflow is refused before insertion.
- Whole-file completion atomically records every episode proved by the actual stored numbering and
  inclusive range, including episodes outside the selected entry span. Missing/ambiguous numbering
  refuses the entire batch. No chapter offsets or alternate numbering are guessed.
- A committed event is followed by a typed Position projection request. The category-serialized
  server validates the event and projects the newest entry position plus all pending safe category
  status cells in **one** Catalog write, backup and atomic replacement. Current Row IDs, original
  expected mtime, human status/Position changes and dropdown vocabulary remain authoritative.
- Review caught two recovery bugs: dropping an uncommitted older fact after newer success, and
  permanently latching reporting after native Replay. Regressions now preserve all unsaved facts
  with original occurred_at, retire only committed obsolete projections, and reset reporting for a
  genuine replay. Job retirement occurs inside the write queue before its next callback begins.
- Repeated native `playing` events from rebuffering/seeking no longer restart an active save timer.
  A regression fires those events at 15/30/45 seconds and still observes both stores saved at 60.
- Cross-request retries retain the original projection stamp. A failed workbook write never
  appends another event on retry; failure remains visible after closing the player. Pending row
  edits are replayed over returned CategoryDetail rather than discarded.
- R106 journals claims before mutation, copies while retaining staging, archives replaced media,
  exclusively installs the new file, verifies its digest, commits provenance and only then removes
  an unchanged source. Unknown ownership and uncertain commits preserve bytes and active recovery
  state. Previous destinations are restored on owned pre-commit rollback.
- Import review reproduced missing committed-provenance checks for both present and already-removed
  sources, and changed-parent recovery. The fixes check actual row/path/digest/state evidence and
  revalidate confinement before destructive transitions. PostgreSQL plus OS source-file locks fence
  cooperating workers even after database connection loss; cancellation drains workers first.
- Precommit title/episode reads now refresh cached ORM objects, so an episode renamed during copying
  cannot commit under stale destination metadata. Bounded batch workers use TaskGroup: single or
  repeated parent cancellation waits for **every** worker to drain, not just the first. Independent
  re-review passed 46 move/concurrency cases, then seven final cancellation/batch cases.
- Native exclusive rename avoids both overwriting raced targets and a hard-link-only filesystem
  requirement. Unsupported filesystem primitives fail safely. Tests on this Mac do not certify
  Windows/Linux native execution, every external/NAS filesystem, power-loss durability, or isolation
  from arbitrary concurrent external pathname edits. Do not edit import roots while a job runs.
- Local phase-awareness, Excel-safety, dual-store, data-driven and validation protocols required
  the existing Catalog funnel, copy-only workbook testing, named constants, real PostgreSQL and all
  four layout viewports. The dual-store skill's old cadence was updated to the owner's R105 choice.

## Files changed in this continuation

This attributes this continuation only, not every pre-existing uncommitted file. Shared files need
task-aware hunk grouping. Root `package.json` and `package-lock.json` remain unrelated and untouched.

Backend paths are relative to `app/backend/`:

| File | Reason |
|---|---|
| `src/tv_watchlist/constants.py` | Position role/header/width, player Integer bound and import-native-operation constants. |
| `src/tv_watchlist/models/column_spec.py` | Add the approved position role. |
| `src/tv_watchlist/models/position_write.py` | Extra-forbidden committed-event projection request. |
| `src/tv_watchlist/workbook/schema.py` | Recognise the app-owned Position column. |
| `src/tv_watchlist/workbook/reader.py` | Keep Position out of the public grid; retain internal race-comparison values only. |
| `src/tv_watchlist/workbook/writer.py` | Share existing validated public-cell write-back without a duplicate implementation. |
| `src/tv_watchlist/workbook/position.py` | One atomic styled numeric Position/status write. |
| `src/tv_watchlist/services/catalog.py` | Route combined snapshots through the existing guarded write funnel. |
| `src/tv_watchlist/services/playback_entry.py` | Shared live-entry/category serialization. |
| `src/tv_watchlist/services/playback_events.py` | Validate selected file/subject and atomically complete covered episodes. |
| `src/tv_watchlist/services/playback_position.py` | Safe newest-position/all-pending-status projection and one guarded race retry. |
| `src/tv_watchlist/services/watch_events.py` | Accept validated selected-entry context without changing generic callers. |
| `src/tv_watchlist/api/watch_events.py` | Paired player UUID context and DB-first recording. |
| `src/tv_watchlist/api/playback.py` | Add the projection-only retry route. |
| `src/tv_watchlist/data/errors.py` | Typed playback conflict. |
| `src/tv_watchlist/api/errors.py` | Register playback conflict in both envelope tables. |
| `src/tv_watchlist/data/enums.py` | Native import operation phases. |
| `src/tv_watchlist/data/models/media_import_operation.py` | Durable journal and active ownership constraints. |
| `src/tv_watchlist/data/models/__init__.py` | Export/register the new table. |
| `src/tv_watchlist/models/import_file_identity.py` | Typed immutable filesystem identity. |
| `src/tv_watchlist/services/file_digest.py` | Stream stable regular-file sha256 with mutation checks. |
| `src/tv_watchlist/services/rename_exclusive.py` | Native no-overwrite publication adapter. |
| `src/tv_watchlist/services/import_source_lock.py` | OS ownership that survives PostgreSQL connection loss. |
| `src/tv_watchlist/services/import_files.py` | Confined copy/install/verify/cleanup and owned rollback. |
| `src/tv_watchlist/services/import_move.py` | Independent transactions, journal recovery and bounded cancellation-safe workers. |
| `alembic/versions/0004_import_operation.py` | Add/remove only the journal table and its new enum/indexes. |
| `tests/workbook/test_position_column.py` | All nineteen workbook shapes, styling/ranges, numeric cells and public-write refusal. |
| `tests/workbook/test_identity_role.py` | Keep role parity assertions current. |
| `tests/services/test_catalog_position_writeback.py` | Unthrottled backups, one combined result and freshness before mutation. |
| `tests/models/test_position_write.py` | Strict request boundary and Python/TS field parity. |
| `tests/services/test_playback_entry.py` | Live-entry/category lookup and serialization. |
| `tests/services/test_playback_events.py` | Exact file membership, range mapping, clipping and integer bounds. |
| `tests/services/test_playback_position.py` | Identity/human-edit races, recovery, category status repair and no regression. |
| `tests/api/test_player_snapshots.py` | Real-PG HTTP commit/423/409/retry and unchanged generic behavior. |
| `tests/playback_projection.py` | Shared real database/workbook projection fixture. |
| `tests/models/test_import_file_identity.py` | Identity shape and comparisons. |
| `tests/data/test_media_import_operation.py` | PostgreSQL journal checks, claims and retained history. |
| `tests/data/test_migration_0004.py` | Revision-specific SQL ordering and enum ownership. |
| `tests/data/test_models_metadata.py` | Current table/export metadata parity. |
| `tests/data/test_migration_round_trip.py` | Current-chain upgrade/downgrade/upgrade and schema parity. |
| `tests/services/test_file_digest.py` | Published abc vector, bounded-memory read and mutation refusal. |
| `tests/services/test_rename_exclusive.py` | Real macOS no-overwrite behavior and other platform adapter paths. |
| `tests/services/test_import_source_lock.py` | Ownership/content preservation and Windows adapter errors. |
| `tests/services/test_import_files.py` | Filesystem transitions and adverse artifact changes. |
| `tests/services/test_import_move.py` | Real-PG crash boundaries, commit failures, compensation and recovery. |
| `tests/services/test_import_move_concurrency.py` | Competing destination/digest claims and precommit source/parent changes. |
| `tests/import_move_support.py` | Independent-session temporary media/provenance fixture. |

Frontend paths are relative to `app/frontend/`:

| File | Reason |
|---|---|
| `src/api/recordPlaybackEvent.ts` | Record the captured player fact with paired context. |
| `src/api/writePlaybackPosition.ts` | Retry committed projection without a new fact. |
| `src/components/PlaybackSaveRetry.tsx` | Retry retained failed jobs after player close. |
| `src/components/PlaybackVideo.tsx` | Isolate native video/reporting lifecycle. |
| `src/hooks/usePlaybackReporter.ts` | Minute and terminal snapshots, stable timer through rebuffering, deduplication and Replay reset. |
| `src/stores/hasPendingWrites.ts` | Share pending-write detection with snapshot jobs. |
| `src/stores/playbackSavesSlice.ts` | Serialize pairs, preserve failed facts and committed projection stamps. |
| `src/types/PlaybackScope.ts` | Immutable playback ownership context. |
| `src/types/PlaybackSnapshot.ts` | Captured fact/file/scope job. |
| `src/types/PositionWrite.ts` | Exact projection request mirror. |
| `src/utils/playbackEvent.ts` | Round/clamp seconds and refuse invalid completion timing. |
| `src/App.tsx` | Pass captured scope into the player. |
| `src/components/CategoryStage.tsx` | Include player jobs in pending-write/focus safeguards. |
| `src/components/PlayButton.tsx` | Capture workbook identity/mtime when playback opens. |
| `src/components/PlayerOverlay.tsx` | Pass stable selected-slot context into the keyed native player. |
| `src/components/RouteEntry.tsx` | Carry the workbook save scope to Play. |
| `src/components/RouteList.tsx` | Thread scope through row rendering. |
| `src/components/ToastMessage.tsx` | Keep save errors persistent and expose retry. |
| `src/stores/categorySlice.ts` | Apply snapshot results while preserving optimistic row patches. |
| `src/stores/store.ts` | Register playback saves. |
| `src/stores/uiSlice.ts` | Captured player scope and save-error lifecycle. |
| `src/stores/writeFailure.ts` | Associate failures with retained snapshot jobs. |
| `src/types/ColumnSpec.ts` | Position role parity. |
| `src/types/Toast.ts` | Save-job association for retry notices. |
| `tests/api/recordPlaybackEvent.test.ts` | Player recording URL/body contract. |
| `tests/api/writePlaybackPosition.test.ts` | Projection URL/body contract. |
| `tests/components/PlaybackSaveRetry.test.tsx` | Retry states and recovered jobs. |
| `tests/components/PlaybackVideo.test.tsx` | Same-origin media and reporter wiring. |
| `tests/components/ToastMessage.test.tsx` | Persistent retry errors versus ordinary timed toasts. |
| `tests/hooks/usePlaybackReporter.test.tsx` | Five-minute and repeated-playing cadence, terminal/replay and old-slot cleanup. |
| `tests/stores/hasPendingWrites.test.ts` | Shared pending-write predicate. |
| `tests/stores/playbackSavesSlice.test.ts` | Queue settlement, original-stamp retry and preservation of older unsaved facts. |
| `tests/support/aPlaybackSnapshot.ts` | Complete captured snapshot fixture. |
| `tests/types/PlaybackScope.test.ts` | Scope type contract. |
| `tests/types/PlaybackSnapshot.test.ts` | Snapshot type contract. |
| `tests/types/PositionWrite.test.ts` | Projection type contract. |
| `tests/utils/playbackEvent.test.ts` | Integer timing and no early completion. |
| `tests/components/AvailabilityBadge.test.tsx` | Current scoped Play fixture. |
| `tests/components/CategoryPlayback.test.tsx` | Pending-save and workbook refresh integration. |
| `tests/components/PlayButton.test.tsx` | Immutable scope capture. |
| `tests/components/PlayerOverlay.test.tsx` | Updated scoped native-video lifecycle. |
| `tests/support/aTestStore.ts` | Include playback jobs in real test stores. |
| `layout/probes/aFakeBackend.ts` | Controlled save/refusal responses without live services. |
| `layout/probes/arrangements.ts` | Arrange failed saves with player open and closed. |
| `layout/surfaces.ts` | Two retry surfaces across four viewports. |

Documentation changed: `CLAUDE.md`, `README.md`, `app/README.md`, `docs/TV_MASTER_PLAN.md`,
`docs/phases/phase-3-plan.md`, `docs/phases/phase-3.5-plan.md`, `docs/status.md`, `docs/versions.md`,
`docs/playback-import-validation.md` (historical-checkpoint pointer) and this audit.
The ignored dual-store skill now matches the approved cadence.
Persistent feedback memory records the owner's reasons for automatic one-minute saving and
whole-file completion, not implementation state. No source version, credential or port changed.

## Task-completion self-audit — CLAUDE §21

| Exact item | Verdict / evidence |
|---|---|
| 1. Summary | Automatic dual-store snapshots and durable source-retaining imports implement R105/R106. Final combined local verification passes; environment gates remain explicitly open. |
| 2. Reuse check | Searched/read `Catalog`, writer/identity/ranges/schema/reader, watch_events/watch_mirror, episode_match/episode_lookup/library_selections, import_naming/media_filename, existing model/migration conventions, request/writeQueue/toWriteFailure/categorySlice, focus/native-overlay and layout fixtures. New files isolate new concerns; no second workbook writer funnel, numbering algorithm or Jellyfin client. |
| 3. Tech-debt check | No new Any/any, TODO stubs, coverage waivers or silent filesystem fallback. Recovery/lifecycle findings have regressions. Native adapters have explicit support limits rather than claiming every filesystem/platform was executed. |
| 4. File-organisation check | Dedicated runtime concepts/models/components/hooks and matching tests; tightly coupled private service helpers stay with their subject, enums use the documented exception. |
| 5. Data-contract check | R105/R106 documented before implementation; existing watch-event body/response unchanged. New Position role/request and journal revision follow the approved additive contracts. |
| 6. Docs check | Files listed above. One pending **v0.2.0** minor from current **0.1.0**, because features/routes/table/role are additive. Source manifests untouched; no second pending heading or port change. |
| 7. Test check | **3891 backend / 320 frontend / 196 layout / 31 hook cases pass**; tests are attributed above. Overall floors hold and every new runtime module has 100% coverage. Remote CI and live-media demonstrations remain unverified, not claimed passed. |
| 8. Forward-compatibility check | P2 remains deferred; workbook authority and TMDB joins remain intact. T53a range advancement and T67 exact-file path correlation need explicit contract work; neither is silently implemented. |
| 9. Git state | Dirty worktree preserved; task-specific attribution above. No staging, committing, branching, fetching or other git mutation. Suggested owner-only grouping below. |
| 10. Security check | **PARTIAL:** focused Ruff/front-end audit pass; unavailable SAST/Python/image scans are listed above. B19 covers typed player positions, live UUID membership, original stamps and contested cells; B22 covers confinement, stable identities/digests, durable claims, exclusive publication and source retention. SQL uses bound parameters; no new acquisition, external URL, shell, raw-HTML or prompt surface. |
| 11. Excel-safety check | Production snapshots use Catalog lock → freshness → unconditional backup → writer → invalidate/read, off-thread. Lock refusal, atomic temp installation, cleanup, style/range preservation and unchanged public grid are copy-tested. No root workbook write; imports never write workbooks. |
| 12. Contract check against the derived-column-schema rule | Header/validation-derived roles remain authoritative; first blank header still ends the grid. Position is app-owned and excluded from row/chat writes and ingest truth. Python/TS role and request fields move together. |
| 13. Layout-guard check | **196/196** at all four viewports, including persistent retry controls with player open/closed. No UI fix based solely on jsdom. |
| 14. Dual-store check | Every snapshot queues DB fact before Excel projection. Whole-file completion is atomic; newest Position plus all safe pending status cells repairs older failures. Original-stamp retries never overwrite a human edit or append a duplicate fact merely because Excel refused. Observed/mirrored fields advance only for written cells; invalid dropdown values are skipped. Workbooks remain independently readable. |

## Suggested commit grouping — owner only

Two cohesive feature groups atop the existing uncommitted prerequisites; split shared constants and
documentation by task-aware hunks. Nothing has been staged or committed.

1. **Suggested subject:** `feat(playback): save both stores every minute and complete whole files`
   **Suggested body:** Add R105 player recording and guarded Position/status projection; preserve
   unsaved facts and original retry stamps; prove range completion, workbook safety and UI lifecycle.
2. **Suggested subject:** `feat(import): journal and recover imports before source cleanup`
   **Suggested body:** Add revision0004 ownership journal, verified exclusive installation, archived
   replacement, independent transactions and recovery; retain staging until proven committed success.

## Native-platform references

Windows `os.rename` refuses an existing destination; Unix needs an explicit no-replace primitive.
[Python 3.13 rename documentation](https://docs.python.org/3.13/library/os.html#os.rename).
Linux `RENAME_NOREPLACE` requires filesystem support and refuses occupied targets.
[Linux man-pages rename(2)](https://man7.org/linux/man-pages/man2/rename.2.html).
The Darwin flag value comes from Apple's published XNU header.
[Apple RENAME_EXCL definition](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/sys/stdio.h).
The Windows lock adapter uses a read-only shared-delete handle and a nonblocking byte lock beyond
EOF so media bytes are not modified or blocked from reading.
[Microsoft locking documentation](https://learn.microsoft.com/en-us/cpp/c-runtime-library/reference/locking?view=msvc-170)
and [CreateFileW sharing semantics](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew).
Adapter tests verify these calls; actual Windows execution is still unverified.

## Decisions before the next tasks

- T53a needs a barrier-capable typed next-target contract and stable entry/slot cursor, since an
  unresolved entry has no queue row. The owner has been asked whether a finished range file should
  suppress only its already-covered episodes while preserving interleaved films; no global skip of
  Watched/repeated items is inferred.
- T67 must correlate the exact imported destination, not just another title/episode candidate.
  Backend and Jellyfin path namespaces need a documented mapping. Existing client/sync and canonical
  imported episode numbering are already specified; T51 availability remains independently derived.
- T68 still needs source authority for reimport after the original staging file is gone. No existing
  library file is silently adopted as a new move source.
- Owner filesystem confirmation, live Jellyfin fixtures, streaming-provider key and environment
  gates remain separate from code/unit-test completion.
