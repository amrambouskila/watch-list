const { emit, getToolFilePath, isSensitivePath, readHookPayload, toPosixPath } = require("./hookUtils.cjs");

// A workbook is written by Catalog._write and nothing else (CLAUDE.md section 3.4). An agent editing
// an .xlsx through a tool would bypass the freshness guard, the snapshot, the Excel-lock check and the
// atomic swap at once, so it is refused outright.
function isWorkbook(filePath) {
  return filePath.toLowerCase().endsWith(".xlsx");
}

function reasonFor(filePath) {
  if (isWorkbook(filePath)) {
    return `Refusing to write ${filePath}: workbooks are written only through Catalog._write (CLAUDE.md section 3.4), never by a tool call.`;
  }
  return `Refusing to write ${filePath}: credentials and .env files are typed by the owner, never written by an agent (CLAUDE.md section 8.3). .env.example is the one such file an agent may write.`;
}

async function main() {
  const payload = await readHookPayload();
  const filePath = toPosixPath(getToolFilePath(payload));
  if (!filePath) {
    return;
  }
  if (!isSensitivePath(filePath) && !isWorkbook(filePath)) {
    return;
  }
  const reason = reasonFor(filePath);
  // Both shapes on purpose: `decision`/`reason` is the form the global CLAUDE.md names; the
  // hookSpecificOutput form is the one current Claude Code documents for PreToolUse.
  emit({
    decision: "block",
    reason,
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: reason,
    },
  });
}

main().catch((error) => {
  process.stderr.write(`[hook] pre-tool-use failed: ${error.message}\n`);
  process.exitCode = 0;
});
