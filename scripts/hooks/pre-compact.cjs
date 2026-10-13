const { emit, readHookPayload } = require("./hookUtils.cjs");

const KEEP = [
  "PRE-COMPACT - the summary MUST preserve, verbatim where short:",
  "(1) the current phase and task id (T-number) and the build order P0 -> P1 -> P3 -> P2 (ADR-014);",
  "(2) every architectural decision made this session and which ADR or CLAUDE.md section records it;",
  "(3) every measured number - test counts, coverage figures, resolver dry-run counts, timings;",
  "(4) every file created or modified and why, as path:line where known;",
  "(5) unresolved issues and owner-only steps (values to type into .env, commits to make);",
  "(6) any data-contract change (ColumnSpec, CuratedEntryRead, ORM columns, views) and whether docs/versions.md recorded the bump;",
  "(7) the computed next version and whether docs/status.md was updated.",
];

async function main() {
  const payload = await readHookPayload();
  const trigger = payload && typeof payload.trigger === "string" ? payload.trigger : "unknown";
  const systemMessage = `${KEEP.join(" ")} (trigger: ${trigger})`;
  emit({ systemMessage, hookSpecificOutput: { hookEventName: "PreCompact", additionalContext: systemMessage } });
}

main().catch((error) => {
  process.stderr.write(`[hook] pre-compact failed: ${error.message}\n`);
  process.exitCode = 0;
});
