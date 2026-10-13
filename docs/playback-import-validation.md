# T52 playback and T65 identification — validation and handoff

Historical checkpoint. Current T53/T66 evidence is in
[Automatic snapshots and recoverable imports](snapshots-recovery-validation.md), measured 2026-09-24.

Measured 2026-09-23 against the uncommitted working tree, after the owner approved R104.
Both implementations are independently reviewed; no findings remain. This records local evidence,
not Phase 3/3.5 completion or a green remote pipeline. The earlier T51/T64 checkpoint is preserved
in [Continuation validation](continuation-validation.md).

## Verification

| Check | Result |
|---|---|
| Full backend, real PostgreSQL | **3656 passed, zero skips**, 89.09 seconds; **98.80%**, 8489/8592 statements, Python 3.14.7. |
| T52 focused backend | **206 passed, zero skips**; **337/337 statements** across playback route/response/model/service and Jellyfin client. |
| Independent T52 lifecycle re-review | **50 passed**; dependency-teardown leak and secret-bearing exception-chain regressions closed. |
| T65 focused backend | **97 passed, zero skips**; **149/149 statements** across parser, identifier and their two models. |
| Frontend | **279 passed / 34 files**; lines/statements/functions/branches **77.93/77.42/69.82/68.70%**. All eight new runtime modules are 100% on all four metrics. |
| Layout | **180 passed**, 23.7 seconds; 45 cases × four Chromium viewports, **21 surfaces**. Root rerun includes final focus-refresh changes. |
| Hooks | **31 passed**. |
| Lint / format / typecheck | Ruff clean, **413 Python files** formatted; TypeScript and scoped frontend ESLint clean. Whole-tree `pnpm lint`: zero errors, three existing warnings in generated `coverage/*.js`. |
| Application builds | `uv build --offline` and `pnpm build` pass; frontend builds 139 modules. |
| Frontend dependency audit | `pnpm audit --audit-level=high`: no known vulnerabilities. |
| API / schema | **20 OpenAPI paths / 23 operations**, eight routers; migration head remains `0003`. No migration added. |
| Bundle credential-marker scan | No synthetic Jellyfin key, fixture host/port, credential-header or environment-variable markers in built `dist/`. Owner key not obtained for this check. |
| Existing services | Read-only inspection: PostgreSQL and Jellyfin healthy. No restart or deployment. |
| Whitespace / versions | `git diff --check` passes with existing CRLF-normalisation warnings. Both manifests remain **0.1.0**; sole pending docs heading is **v0.2.0**. |
| Docker builds | **UNVERIFIED.** Previous checkpoint attempts stalled at Dockerfile frontend download 0B/13.01MB and were cancelled; not repeated here. |
| Full SAST / Python dependency audit | **UNVERIFIED.** Semgrep, gitleaks, Trivy and Python auditor unavailable locally; no scanner installation performed. |
| Remote CI / Windows / live owner media | **UNVERIFIED.** No push, remote run, Windows execution or live playback/fixture certification. |

Project floors remain backend 97%, frontend 56/54/45/45. All eight new backend modules have no
missing lines in the final combined report; no exclusions or threshold reductions were added.
Provider traffic is mocked at HTTP, not at the domain/database layer. Database tests use the
existing PID-isolated disposable PostgreSQL harness; workbook regressions use temporary copies.
The browser layout probes intercept fixture responses and do not use owner media.

Local coverage artifacts (ephemeral, not committed):

- `/tmp/tv-playback-import.Wy8QPs/backend-final-coverage.json`
- `/tmp/tv-playback-import.Wy8QPs/t52-coverage.json`
- `/tmp/tv-playback-import.Wy8QPs/t65-coverage.json`
- `app/frontend/node_modules/.coverage-t52/coverage-summary.json`

Reproduce from `app/backend`, with the existing environment already provisioned:

```sh
rtk proxy env TV_REQUIRE_POSTGRES=1 TV_POSTGRES_DB=tv_test uv run --no-sync pytest -q --cov=tv_watchlist --cov-fail-under=97
rtk proxy uv run --no-sync ruff check .
rtk proxy uv run --no-sync ruff format --check .
rtk proxy uv build --offline
```

From `app/frontend`: `rtk proxy pnpm test:coverage`, `rtk proxy pnpm test:layout`,
`rtk proxy pnpm exec tsc -b`, `rtk proxy pnpm lint`, `rtk proxy pnpm build`, and
`rtk proxy pnpm audit --audit-level=high`. From the root:
`rtk proxy node --test scripts/hooks/hooks.test.cjs`.

## Scope and decisions

- **R104 was documented before code.** A separate ordered playback-slot endpoint returns actual
  movie/episode file UUIDs. `CuratedEntryRead` remains unchanged; its series-level UUID is never
  reinterpreted as a streamable file. Missing/ambiguous slots and stored numbering remain visible.
- The native-video overlay starts with the first slot and allows explicit selection. Range files
  show a warning, not a guessed chapter offset. Closing unmounts video and restores focus. No
  resume, progress reporting, Next or Autoplay lands ahead of T53/T53a.
- Workbook rows receive badges only when category, mtime, unique sheet row and non-watch cells
  align. Focus refresh observes the existing pending-write guard; stale/aborted request IDs cannot
  replace current state. Shared pagination is extracted from review fetching instead of duplicated.
- The proxy accepts a live indexed movie/episode UUID, never a URL or series, and validates one
  ASCII start/end byte range. Suffix, duplicate, reversed, multi-range and malformed inputs are 416.
  Huge integer text is compared without conversion to an unbounded Python integer.
- Only safe headers and upstream 200/206 statuses pass. Stream-only identity encoding prevents
  decoded-body/Content-Length disagreement; a non-identity response is refused before headers.
  Direct ASGI tests prove incremental consumption, cancellation and cleanup on send/read failures.
- Upstream acquisition happens after function-scoped database teardown. The response owns cleanup
  once acquisition succeeds, including header-send failure. Acquisition failures send sanitized
  JSON outside the exception handler; later failures terminate without adding JSON to media or
  exposing the original provider exception. Review reproduced and closed both lifecycle regressions.
- FastAPI minimum is **0.121.0**, when function-scoped dependencies were added according to the
  [official documentation](https://fastapi.tiangolo.com/advanced/advanced-dependencies/#dependencies-with-yield-and-scope).
  The locked version remains **0.141.1**; no third-party version changed. One `uv run --frozen`
  lint invocation refreshed the local editable package metadata after this manifest change;
  subsequent checks used `--no-sync`. No new tool or third-party dependency was installed.
- T65 recognizes five explicit single-item filename forms and strips release metadata while
  preserving numeric titles. Ambiguous years, ranges/multiple episodes, paths/nulls and empty
  normalized tokens are refused. Exact normalized key precedes indexed pg_trgm matching; type/year
  constraints, raw-score tie refusal and `min(parse confidence, title similarity)` prevent guesses.
- Absolute numbering reuses `episode_for_sequence`; exact SxxExx matches TMDB's stored pair.
  The 1085 test is a **synthetic seeded projection**, not a claim about published numbering; a
  separate recorded One Piece fixture proves the S02E62 destination. No aired fallback/arithmetic.
- Identification locks/refreshes live undecided FOUND rows; batching uses `FOR UPDATE SKIP LOCKED`.
  Owner decisions and superseded history are preserved; callers own commit/rollback. No provider
  call, file-content read, move, hash, delete, workbook write, import route or migration is introduced.
- Local phase-awareness, dual-store, data-driven and validation protocols constrained scope,
  preserved workbook authority, required existing helpers/constants and enforced real-PostgreSQL
  tests plus all four layout viewports. They did not waive unavailable checks.

## Files changed in this continuation

This is task attribution, not the whole dirty worktree. Earlier work and unrelated root
`package.json` / `package-lock.json` plugin artifacts remain intact. Shared files already contained
uncommitted changes, so the owner should split by task-aware hunks rather than whole-file assumptions.

Backend paths below are relative to `app/backend/`:

| File | Why |
|---|---|
| `src/tv_watchlist/api/playback.py` | Ordered-slot and strict-range file-stream routes with function-scoped database lifetime. |
| `src/tv_watchlist/api/playback_response.py` | Deferred acquisition, backpressure, sanitized failures and shielded stream cleanup. |
| `src/tv_watchlist/models/playback_item_read.py` | Frozen R104 response contract. |
| `src/tv_watchlist/services/playback_items.py` | Reuse matching/selection for ordered slots without per-slot queries. |
| `src/tv_watchlist/clients/jellyfin_client.py` | Identity-encoded media requests and rejection of unsupported stream status/encoding. |
| `src/tv_watchlist/main.py` | Register the playback router. |
| `src/tv_watchlist/api/errors.py` | Playback 404/416/502 envelopes and service-neutral Jellyfin 503 wording. |
| `src/tv_watchlist/data/errors.py` | Named playback boundary errors. |
| `src/tv_watchlist/constants.py` | Named range, filename-pattern, metadata-token and confidence constants. |
| `src/tv_watchlist/models/filename_parse.py` | Frozen validated filename hints. |
| `src/tv_watchlist/models/identify_pass_result.py` | Frozen nonnegative identification counts. |
| `src/tv_watchlist/services/import_filename.py` | Conservative pure release-filename parsing. |
| `src/tv_watchlist/services/import_identify.py` | Local exact/fuzzy identification, safe row locking and caller-owned transactions. |
| `tests/api/test_playback_proxy.py` | Ranges, status/headers, secret safety, streaming/disconnects and dependency teardown. |
| `tests/api/test_playback_response.py` | Response lifecycle, backpressure, cleanup and exception-chain regressions. |
| `tests/api/test_playback_items_route.py` | HTTP contract, pagination, unavailable peer and no workbook access. |
| `tests/services/test_playback_items.py` | Ordered movie/episode slots, missing/ambiguous/range cases, picks and constant query counts. |
| `tests/models/test_playback_item_read.py` | Frozen model and exact Python/TypeScript field parity. |
| `tests/playback_server.py` | Shared isolated app/upstream fixture. |
| `tests/playback_stream.py` | Observable incremental async byte stream for lifecycle proofs. |
| `tests/api/test_library_sync_route.py` | Match the generalized Jellyfin-unavailable message. |
| `tests/models/test_filename_parse.py` | Frozen hint defaults and boundary validation. |
| `tests/models/test_identify_pass_result.py` | Frozen identification-count validation. |
| `tests/services/test_import_filename.py` | All supported shapes, numeric titles and conservative refusals. |
| `tests/services/test_import_identify.py` | Real-PG exact/fuzzy/tie/numbering, reference fixtures, rollback and owner races. |
| `pyproject.toml` | Raise only FastAPI's supported minimum for scoped dependencies; app version unchanged. |
| `uv.lock` | Match the root dependency requirement; locked packages unchanged. |

Frontend paths below are relative to `app/frontend/`:

| File | Why |
|---|---|
| `src/types/PlaybackItemRead.ts` | Exact snake_case R104 wire mirror. |
| `src/api/requestPages.ts` | One shared cancellable page walker. |
| `src/api/fetchEntries.ts` | Fetch availability projection pages. |
| `src/api/fetchPlaybackItems.ts` | Fetch ordered playback slots. |
| `src/api/fetchReviewQueue.ts` | Reuse pagination without changing the review API. |
| `src/stores/entriesSlice.ts` | Typed availability/playback state with stale-request guards. |
| `src/stores/store.ts` | Register the entries slice. |
| `src/stores/uiSlice.ts` | Entry/title overlay state, never a series stream ID. |
| `src/utils/entryForRow.ts` | Refuse stale, ambiguous or mismatched workbook/projection associations. |
| `src/components/AvailabilityBadge.tsx` | Text-plus-icon three-state badge. |
| `src/components/PlayButton.tsx` | Open playback only for in-library entries. |
| `src/components/PlayerOverlay.tsx` | Explicit slot selection, native video, safe retry and focus lifecycle. |
| `src/components/CategoryStage.tsx` | Load/refresh projection alongside the authoritative workbook. |
| `src/components/RouteList.tsx` | Pass only verified row-to-entry associations. |
| `src/components/RouteEntry.tsx` | Render availability and Play without changing workbook cells. |
| `src/App.tsx` | Mount the playback overlay and clear it on close. |
| `src/styles/player.css` | Accessible bounded overlay/native-video/control layout. |
| `src/index.css` | Import player styling. |
| `tests/support/aTestStore.ts` | Include the new reducer in test stores. |
| `tests/support/aPlaybackItemRead.ts` | Shared complete typed slot fixture. |
| `tests/components/AvailabilityBadge.test.tsx` | All three labels and icon/text states. |
| `tests/components/PlayButton.test.tsx` | Availability gating and correct entry/title dispatch. |
| `tests/components/PlayerOverlay.test.tsx` | Same-origin file IDs, slots, failures, range warning, cancellation and focus restoration. |
| `tests/components/CategoryPlayback.test.tsx` | Projection freshness, refocus and pending-write behavior. |
| `tests/api/requestPages.test.ts` | Shared page walking and cancellation. |
| `tests/api/fetchEntries.test.ts` | Entry endpoint paging contract. |
| `tests/api/fetchPlaybackItems.test.ts` | Playback endpoint paging contract. |
| `tests/utils/entryForRow.test.ts` | Unique/current sheet-row association and refusal cases. |
| `tests/stores/entriesSlice.test.ts` | Async state transitions and stale completion refusal. |
| `layout/probes/aPlayableCategory.ts` | Deterministic movie/episode playable fixture. |
| `layout/probes/aProbeLibrary.ts` | Typed projection and playback probe data. |
| `layout/probes/aFakeBackend.ts` | Intercept new GET surfaces without live services. |
| `layout/probes/arrangements.ts` | Build playable-category/player surface states. |
| `layout/surfaces.ts` | Two new surfaces and reachable promised-size controls. |
| `layout/support/openProbe.ts` | Open the fixture-driven player surface. |

Documentation:

| File | Why |
|---|---|
| `CLAUDE.md` | Contract-first R104, implemented phase/module/route inventory, B17/B20 and current gates. |
| `docs/TV_MASTER_PLAN.md` | Approved slot contract, completed T52/T65 and next dependency frontier. |
| `docs/phases/phase-3-plan.md` | T52 implementation record, lifecycle corrections and bounded acceptance evidence. |
| `docs/phases/phase-3.5-plan.md` | T65 models, matching/transaction decisions, completed acceptance and next task. |
| `docs/status.md` | Current checkpoint, measurements and unresolved environment gates. |
| `docs/versions.md` | T52/T65 and combined verification under the existing v0.2.0 heading. |
| `README.md` | Current frontend/layout verification counts. |
| `app/README.md` | Current frontend/layout tree measurements. |
| `docs/continuation-validation.md` | Mark the earlier audit historical and link this continuation. |
| `docs/playback-import-validation.md` | This evidence, per-file attribution and full completion audit. |

## Task-completion self-audit — CLAUDE §21

| Item | Verdict / evidence |
|---|---|
| 1. Summary | T52 safely plays explicit ordered slots; T65 identifies discovered files against the local projection. Independently reviewed, with no remaining findings. |
| 2. Reuse check | Searched/read `episode_match`, `episode_lookup`, `library_selections`, `library_selection`, `availability`, `import_naming`, `resolver/match_key`, `resolver/span`, `normalise`, `api/chat`, `api/errors`, `jellyfin_client`, `constants`, `fetchReviewQueue`, `request`, `useFocusTrap`, `CategoryStage`, `App`, shared test fixtures and layout probes. Existing helpers own matching, numbering, HTTP envelopes and focus; new modules isolate playback lifecycle and a distinct filename grammar. |
| 3. Tech-debt check | No new type escapes, dead code, TODOs, duplicate pagination/numbering/normalization, fake offsets or silent fallback picks. Encoding, teardown and exception-chain findings fixed with regressions. No third-party version change; dependency minimum now honestly describes the used API. |
| 4. File-organisation check | New models/components/hooks-equivalents/utilities have dedicated files and tests. Private tightly coupled helpers remain with their service/response; no catch-all module added. |
| 5. Data-contract check | R104 approved and documented before implementation; frozen Pydantic/TS snake_case parity tested. Existing entry and workbook contracts unchanged; no new persisted schema. |
| 6. Docs check | Ten files listed above. Existing pending **0.2.0** is the additive-feature minor from current **0.1.0**; no second pending heading, manifest version edit, port/registry change or `app/docs/` change. |
| 7. Test check | Exact files and measured results above. New modules 100%; overall project floors exceeded without lowering them. Remote CI, Docker and live-media demo are not claimed passed. |
| 8. Forward-compatibility check | Slot identities/numbering are suitable for T53/T53a; transaction ownership and import provenance support T66–T68. Workbook authority and TMDB join remain intact; no deferred P2 layout/navigation work. |
| 9. Git state | Pre-existing dirty worktree preserved; no git mutation. Task-specific files attributed above; suggested grouping below is owner-only. |
| 10. Security check | **PARTIAL.** Ruff and frontend dependency audit pass; full SAST/Python audit unavailable. B17 addresses SSRF/open proxy via indexed UUID/configured host, header injection via strict range and allowlists, key/log leakage via sanitized failures, and exhaustion via streaming/early DB release. B20 addresses SQL/identity confusion via bound typed/year-constrained matching, refusal thresholds and row locks; parser rejects paths/nulls. UI is escaped text, never HTML; no command, template, deserialization or chat/prompt boundary added. |
| 11. Excel-safety check | No production workbook write or new workbook access in either task. Freshness/lock/backup/atomic install/no-op-ingest funnel remains unchanged; regression tests use copies and no root workbook was modified. |
| 12. Derived-column-schema check | No fixed column index, role change or header-schema modification. New row association uses the existing sheet row/cells/mtime contracts; R104 fields are identical across the wire. |
| 13. Layout-guard check | **180/180**, all four viewports, including new playable-category and player surfaces; selector/video/Play/Close are reachable. |
| 14. Dual-store check | No watch fact or progress write is added before T53; append-only log, lossy one-way mirror, observed/mirrored-cell tracking and mirror-loses-race invariants remain unchanged. Workbooks still open independently. |

## Suggested commit grouping — owner only

Keep these as two cohesive feature groups atop their existing prerequisites; split shared constants
and documentation by task when staging. Nothing is staged or committed by this continuation.

1. **Suggested subject:** `feat(playback): add ordered-slot selection and safe same-origin streaming`
   **Suggested body:** Add the R104 slot contract, range proxy, badges and native-video overlay;
   preserve missing/ambiguous slots and workbook authority; prove stream lifetime, secret safety,
   stale-request handling and layout; align the FastAPI minimum with function-scoped dependencies.
2. **Suggested subject:** `feat(import): identify staged media against the local projection`
   **Suggested body:** Parse explicit release filename shapes; reuse normalized keys and stored
   numbering; refuse ties/low confidence; preserve owner choices through row locks and caller-owned
   transactions; add real-PostgreSQL, reference-fixture and concurrency tests.

Next implementation checkpoints: **T53 position reporting/Position (s)** and **T66 move/hash/supersede**.
T53's separate column-contract approval and T66's filesystem boundary deserve their own focused
work; this continuation does not start them. T55 remains owner-key-blocked, and T54/T69 still owe
their phase-wide/live-media/environment gates.
