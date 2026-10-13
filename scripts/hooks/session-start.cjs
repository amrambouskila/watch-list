const fs = require("node:fs");
const { PROJECT_DIR, head, readText } = require("./hookUtils.cjs");

function workbookCount() {
  try {
    return fs.readdirSync(PROJECT_DIR).filter((name) => name.endsWith(".xlsx") && !name.startsWith("~$")).length;
  } catch {
    return 0;
  }
}

function versionIn(text, pattern) {
  const match = text ? text.match(pattern) : null;
  return match ? match[1] : "unknown";
}

function firstHeading(text) {
  if (!text) return "(docs/versions.md missing)";
  const line = text.split(/\r?\n/).find((candidate) => candidate.startsWith("## v"));
  return line || "(no version heading)";
}

function main() {
  const backend = versionIn(readText("app/backend/pyproject.toml"), /^version = "([^"]+)"/m);
  const frontend = versionIn(readText("app/frontend/package.json"), /"version"\s*:\s*"([^"]+)"/);
  const status = readText("docs/status.md");
  console.log("=== TV WATCH LIST SESSION START ===");
  console.log("Read in full, in this order, before any change: CLAUDE.md, docs/TV_MASTER_PLAN.md, docs/status.md, docs/versions.md.");
  console.log(`Library: ${workbookCount()} workbooks at the repo root. They ARE the data; every write goes through Catalog._write.`);
  console.log("Build order: P0 close (T01a/T01b/T01c) -> P1 metadata spine (T04-T33) -> P3 playback + launcher -> P2 ten-foot (deferred). ADR-014.");
  console.log(`Versions: backend ${backend}, frontend ${frontend} (never hand-edit); pending heading: ${firstHeading(readText("docs/versions.md"))}`);
  console.log("--- docs/status.md, first lines ---");
  console.log(status ? head(status, 8) : "(docs/status.md missing - flag it)");
  console.log("--- Reminders ---");
  console.log("1. Workbooks: never written by a tool; Postgres is a projection, never authoritative for order.");
  console.log("2. Contracts (CLAUDE.md section 5) change in CLAUDE.md first, both sides together, minor bump.");
  console.log("3. No mocking of the workbook layer or the database; recorded fixtures for providers.");
  console.log("4. Git is the owner's. Report files and a suggested commit message; never commit.");
}

try {
  main();
} catch (error) {
  process.stderr.write(`[hook] session-start failed: ${error.message}\n`);
  process.exitCode = 0;
}
