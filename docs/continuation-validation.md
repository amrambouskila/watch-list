# Claude continuation — implementation and validation

Measured 2026-09-23 against the uncommitted working tree. This audit covers completion of T61's
interrupted review, T51 availability, T64 discovery, and reconciliation of the already-approved
T49/T50/T62 records. It does not certify either phase complete or remote CI green.

**Historical checkpoint:** the subsequent approved T52/T65 implementation and current measurements
are in [Playback/import validation](playback-import-validation.md). The figures below remain the
evidence for this earlier checkpoint, not current suite counts.

## Review and verification

| Check | Result |
|---|---|
| T61 independent review | Approved; 100 focused tests, zero skips. Removed two unused test helpers; no schema change. |
| T51 independent review | Approved; 207 focused tests, zero skips. Both owner-pick regressions and the R61 test-placement finding closed. |
| T64 independent review | Approved; 60 focused tests, zero skips. No outstanding findings. |
| Whole backend, real PostgreSQL | 3475 passed, zero skips; 98.75% line coverage, 8156/8259 statements. Local Python 3.14.7. |
| Per-module DTO tests (included above) | 23 passed; frozen/default/typed contracts, no production change. |
| T51/T64 implementation coverage | 100% on availability, its result/value/selection modules, the episode matcher, import scan/discovery/candidate/result, and changed entry/review services/routes. |
| Backend lint/format | Ruff clean; 394 Python files formatted. No new suppressions; source has seven justified `noqa` and zero `type: ignore`. |
| Frontend | 237 tests / 25 files; coverage lines 68.23%, statements 68.10%, functions 60.85%, branches 56.25%. ESLint and TypeScript pass. |
| Layout | 164 passed: 41 cases × four Chromium viewports, 19 surfaces. |
| Hooks | 31 passed. |
| Application builds | `uv build --offline` and `pnpm build` pass. |
| Frontend dependency audit | `pnpm audit --audit-level=high`: no known vulnerabilities. |
| API/migrations | 18 OpenAPI paths / 21 operations; one head `0003`; real-database chain round trip and Alembic metadata parity pass in the suite. |
| Compose | Syntax validation passes without loading the owner's environment; existing PostgreSQL and Jellyfin are healthy. No service lifecycle changes. |
| Docker builds | **UNVERIFIED:** both cancelled after 45 seconds while the Dockerfile frontend download remained at 0B / 13.01MB. |
| Semgrep / gitleaks / Trivy / Python dependency audit | **UNVERIFIED:** local tools unavailable; no scanner images cached. No claim of a clean full SAST set. |
| Remote CI / Windows / live Jellyfin fixtures | **UNVERIFIED:** no push or remote CI run; owner-assisted checks remain. |
| Git whitespace | `git diff --check` passes; only pre-existing CRLF-normalisation warnings. |

The backend's project-specific floor is 97%; frontend floors are 56/54/45/45. None changed.
The whole-suite command uses the existing PID-isolated disposable database harness; migration
round trips never run against the owner's persistent database. Provider traffic in tests uses
fixtures/MockTransport, and workbook operations use temporary copies.

Reproduce from `app/backend`:

```sh
rtk proxy env TV_REQUIRE_POSTGRES=1 TV_POSTGRES_DB=tv_test uv run pytest -q --cov=tv_watchlist --cov-fail-under=97
rtk proxy uv run ruff check .
rtk proxy uv run ruff format --check .
rtk proxy uv build --offline
```

From `app/frontend`: `rtk proxy pnpm test:coverage`, `rtk proxy pnpm test:layout`,
`rtk proxy pnpm lint`, `rtk proxy pnpm build`, and `rtk proxy pnpm audit --audit-level=high`.
From the root: `rtk proxy node --test scripts/hooks/hooks.test.cjs`.

## Scope and decisions

- T51 extends the existing entry response by exactly two fields, documented before implementation:
  computed availability and a nullable title-level movie/series item id. It adds no route or
  migration. Service-only notices do not alter the API envelope.
- Numbering remains owned by `numberings_for` / `within_numberings`; page batching does not
  duplicate it. Missing or ambiguous slots cannot be converted into a playable span by a title pick.
- Review preserved both edge cases of a remembered episode pick: missing parent metadata retains
  the existing exact-id fallback; an explicit live parent still resolves after its provider id changes.
- T64 only discovers. Its transaction advisory lock lasts through caller commit/rollback, replacing
  a process lock that would release before rows became visible and would not protect other workers.
- Discovery reuses resolved containment and the validated qBittorrent path helper. It counts refused
  paths and filesystem failures, deduplicates canonical paths, and never reads media content.
- The phase-awareness, dual-store, data-driven and validation protocols kept playback/identification
  out of scope, prohibited workbook writes, reused constants/contracts, and required real-PostgreSQL
  tests. These protocols did not waive the outstanding Docker/security checks.

## Changed files in this continuation

This is attribution for this session, not the entire dirty worktree. Earlier Phase 1/3 changes and
the unrelated root `package.json` / `package-lock.json` plugin artifacts were preserved.

Backend production paths are relative to `app/backend/src/tv_watchlist/`:

| File | Why |
|---|---|
| `data/enums.py` | Add the computed-only availability enum. |
| `models/curated_entry_read.py` | Add the two approved wire fields. |
| `services/availability.py` | Compute a page's three states with optional peer health and slot aggregation. |
| `services/availability_result.py` | Frozen page result and service-only notice. |
| `services/entry_availability.py` | Frozen per-entry value. |
| `services/library_selection.py` | Reduce candidates while preserving remembered-pick semantics. |
| `services/library_selections.py` | Fetch candidates/picks and an explicit remembered parent in one statement. |
| `services/episode_match.py` | Add page batching while retaining the single-entry API and numbering rules. |
| `services/entries.py` | Wire the shared availability result into entry reads. |
| `services/resolution_review.py` | Reuse the same read shape for review decisions and retries. |
| `api/entries.py` | Supply the optional Jellyfin dependency. |
| `api/review.py` | Supply it consistently to all review response paths. |
| `services/import_scan.py` | Orchestrate discovery and transaction-safe, batched idempotence checks. |
| `services/import_discovery.py` | Off-thread contained filesystem observations and refusal/error counts. |
| `services/import_candidate.py` | Immutable candidate metadata. |
| `models/import_scan_result.py` | Frozen discovery-only counts. |
| `constants.py` | Named scanner job, distinct advisory-lock key and lookup batch size. |

Backend test paths are relative to `app/backend/tests/`:

| File | Why |
|---|---|
| `services/test_availability.py` | Three states, outages, partial/empty spans and constant query counts. |
| `services/test_availability_result.py` | Frozen, typed page-result contract. |
| `services/test_entry_availability.py` | Frozen enum/UUID/default contract. |
| `services/test_library_selection.py` | Frozen selection/value defaults and empty reduction. |
| `services/test_library_selections.py` | Provider isolation and remembered-pick metadata regressions. |
| `services/test_episode_match.py` | Cross-title/per-order page batching without changing single-entry results. |
| `services/test_entries_service.py` | Fixed configured/unconfigured query totals for small and larger pages. |
| `api/test_entries_availability.py` | Category/review/decision/retry response integration. |
| `models/test_availability_contract.py` | Python enum / standalone TypeScript union parity only. |
| `models/test_read_models.py` | Replace absence guards with positive field/parity assertions. |
| `data/test_data_enums.py` | Computed enum present in Python but absent from database metadata/migrations. |
| `data/test_migration_0003.py` | Remove the two unused helpers found in T61's final review. |
| `services/test_import_scan.py` | Real-file/database discovery, retries, batching and concurrent transactions. |
| `services/test_import_discovery.py` | Filesystem refusals/errors and canonical metadata observations. |
| `services/test_import_candidate.py` | Frozen candidate contract. |
| `models/test_import_scan_result.py` | Frozen, nonnegative discovery-only result contract. |
| `import_scan_support.py` | Shared sparse-file fixture, avoiding repeated test setup. |

Frontend paths are relative to `app/frontend/`:

| File | Why |
|---|---|
| `src/types/Availability.ts` | One-concept availability union. |
| `src/types/CuratedEntryRead.ts` | Match the two backend fields. |
| `tests/support/aCuratedEntryRead.ts` | Keep the shared response fixture complete. |

Documentation:

| File | Why |
|---|---|
| `CLAUDE.md` | Contract-first additions; current phase, module, route, schema and security inventory. |
| `docs/TV_MASTER_PLAN.md` | Completed tasks, accepted contracts, B20/B21 and transaction-lock decision. |
| `docs/phases/phase-3-plan.md` | T49/T50/T51 completion and accepted cursor/matching rules. |
| `docs/phases/phase-3.5-plan.md` | T61/T62/T64 completion, R100/R101 and corrected next-task guidance. |
| `docs/status.md` | Current checkpoint, measurements, limitations and next dependencies. |
| `docs/versions.md` | Additive task entries under the existing pending v0.2.0 only. |
| `README.md` | Current verification commands, PID-isolated tests and import-phase overview. |
| `app/README.md` | Current frontend/layout measurements and backend evidence pointer. |
| `docs/continuation-validation.md` | This reproducible audit and session-specific file attribution. |

## Task-completion self-audit — CLAUDE §21

| Item | Verdict / evidence |
|---|---|
| 1. Summary | T61 review completed; T51 availability and T64 discovery implemented/reviewed; stale predecessor records reconciled. |
| 2. Reuse check | Searched/read `episode_match`, `episode_lookup`, `ingest/expansion`, `entries`, `resolution_review`, `library_sync`, `import_naming`, `qbittorrent_file`, `constants`, `tests/statement_support`, `tests/ts_types` and shared frontend fixtures. New modules separate the new availability/discovery responsibilities rather than duplicate those implementations. |
| 3. Tech-debt check | No new type escapes, dependencies, dead code, untracked TODOs or duplicate numbering/path logic. Review defects fixed; the transaction lock closes the draft concurrency gap. |
| 4. File-organisation check | New values/models/services have dedicated files and matching test subjects. Existing tightly coupled episode-match result types remain with their join; the sanctioned shared enum module is not broadened. |
| 5. Data-contract check | Exactly two planned entry fields, backend/TS parity, written into CLAUDE first. Availability is not persisted. New scan result has only produced discovery/refusal counts. |
| 6. Docs check | All nine documentation files listed above updated. Current manifests remain 0.1.0; additive features use the existing pending 0.2.0 minor entry, with no second heading. No port change; registry and `app/docs/` untouched. |
| 7. Test check | Named test changes and measured gates above; touched logic 100%, overall project floors exceeded. Remote CI is not certified. |
| 8. Forward-compatibility check | Preserves stored numbering, title-level picks, single-entry matcher, per-slot media ids and caller transaction ownership for T52/T65–T68. No ten-foot/P2 or import-UI work introduced. |
| 9. Git state | Existing dirty worktree preserved; no git mutation. Session-specific files listed above; suggestions below are not commits. |
| 10. Security check | **PARTIAL:** Ruff security rules and frontend dependency audit pass; full SAST/Docker/remote CI unverified. B20 documents resolved containment, off-thread bounded queries and repr-escaped logs; SQL uses bound expressions/advisory-lock parameters. B21 documents configured-origin SSRF defence and backend-only credentials; no acquisition, arbitrary URL, shell, XSS or chat-data surface added. |
| 11. Excel-safety check | No production workbook write in these tasks, so freshness/lock/backup/atomic-write funnel, no-op ingest and retirement behaviour are unchanged. Full regression suite uses workbook copies; no root workbook changed. |
| 12. Derived-column-schema check | Header-driven schema, first-blank boundary, validations, column roles and workbook contracts unchanged. Only the approved snake_case entry fields changed, with parity tests. |
| 13. Layout-guard check | 164/164 at all four viewports. No new screen/overlay; no new surface required. |
| 14. Dual-store check | No watch-fact/progress write added; append-only events, lossy one-way mirror, observed/mirrored-cell tracking and mirror-loses-race rules remain unchanged and covered by regression tests. Standalone workbooks remain independent. |

## Suggested commit grouping — owner only

Keep the two features separate if splitting this large pre-existing worktree:

1. `feat(api): compute three-state library availability on curated entries`
   — batch title/episode matching; preserve remembered picks; add matching Python/TS contracts and tests.
2. `feat(import): discover staged and completed media safely`
   — contained metadata-only discovery; optional read-only qBittorrent; transaction-safe deduplication.
3. `docs: reconcile reviewed playback and import checkpoints`
   — durable recovered task state, verification and security inventories; include the small T61 test cleanup
   with its provenance task when grouping the owner's existing changes.

Next implementation checkpoints: **T52 playback** and **T65 local-projection identification**.
T55 remains owner-key-blocked. Docker build/SAST, live fixture confirmation and Windows execution
remain explicit verification obligations, not waived gates.
