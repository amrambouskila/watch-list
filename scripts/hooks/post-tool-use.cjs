const { emit, getToolFilePath, readHookPayload, toPosixPath } = require("./hookUtils.cjs");

const RULES = [
  {
    test: (p) => p.includes("/app/backend/src/tv_watchlist/workbook/"),
    context:
      "EXCEL LAYER EDITED. Before continuing verify: (1) every write still reaches disk only through Catalog._write -> _mutate (guard_fresh -> snapshot -> writer -> invalidate -> re-read); (2) the grid still ends at the first blank header cell, never sheet.max_column; (3) if rows moved or the grid widened, ranges.sync(sheet, last, width) ran so the table ref, dropdowns and conditional formats cover rows 2..last; (4) identity ('Row ID') and position ('Position (s)') columns are excluded by the reader from `columns` and WatchRow.cells but kept in build_columns so writer._validate accepts them; (5) a fingerprint test (tests/snapshot.py) covers the change against copies of the real workbooks.",
  },
  {
    test: (p) => p.includes("/app/backend/src/tv_watchlist/data/models/"),
    context:
      "ORM MODEL EDITED. Verify: one class per file; lazy=\"raise_on_sql\" on every relationship; every duration is Integer named *_seconds with a CHECK (never INTERVAL); every timestamp is DateTime(timezone=True); enum columns use pg_enum() so labels are member VALUES; a new enum value needs its own Alembic revision; any column change needs a hand-ordered revision and the round trip upgrade head -> downgrade base -> upgrade head; watch_event has no updated_at and no UPDATE/DELETE path.",
  },
  {
    test: (p) => p.includes("/app/backend/alembic/versions/"),
    context:
      "MIGRATION EDITED. downgrade() is hand-ordered: views drop before their tables, the watch_event_no_mutation trigger and its function before watch_event, tables in reverse dependency order, enum types last. Run `uv run alembic upgrade head && uv run alembic downgrade base && uv run alembic upgrade head` against the compose Postgres before calling it done.",
  },
  {
    test: (p) => p.includes("/app/backend/src/tv_watchlist/models/") || p.includes("/app/frontend/src/types/"),
    context:
      "CONTRACT FILE EDITED. A Pydantic model and its TypeScript twin move together in one commit (ColumnSpec <-> ColumnSpec.ts, WatchRow <-> WatchRow.ts, CategorySummary/CategoryDetail <-> theirs, RowChange/Proposal*/HeroCandidate/ChatEvent <-> theirs). Wire field names are snake_case on both sides. Write the change into CLAUDE.md section 5 FIRST and record a minor bump in docs/versions.md.",
  },
  {
    test: (p) => p.includes("/app/backend/src/tv_watchlist/services/"),
    context:
      "SERVICE EDITED. Any workbook write must be one Catalog._write call carrying every cell change (one snapshot, one temp file, one os.replace). The mirror pass must LOSE a race with a UI edit (catch StaleWorkbookError and retry next pass), and mirrored_watch_cell + category.workbook_mtime update in the same transaction as the successful apply_changes.",
  },
  {
    test: (p) => p.includes("/app/frontend/src/components/") || p.includes("/app/frontend/src/styles/"),
    context:
      "UI EDITED. jsdom has no layout engine: run `pnpm test:layout` (38 tests x 4 viewports) before calling this done. A new screen or overlay needs a surface in layout/surfaces.ts and an arrangement in layout/probes/arrangements.ts.",
  },
  {
    test: (p) => p.includes("/app/backend/src/tv_watchlist/config.py"),
    context:
      "SETTINGS EDITED. Every credential is SecretStr and never logged; the env var is TV_ + the field name, mechanically; absent provider credentials degrade, never crash; add the variable to .env.example with a placeholder and a one-line comment, and to CLAUDE.md section 8.",
  },
];

async function main() {
  const payload = await readHookPayload();
  const filePath = toPosixPath(getToolFilePath(payload));
  if (!filePath) {
    return;
  }
  const rule = RULES.find((candidate) => candidate.test(filePath));
  if (rule) {
    emit({ hookSpecificOutput: { hookEventName: "PostToolUse", additionalContext: rule.context } });
  }
}

main().catch((error) => {
  process.stderr.write(`[hook] post-tool-use failed: ${error.message}\n`);
  process.exitCode = 0;
});
