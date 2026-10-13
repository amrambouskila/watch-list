const test = require("node:test");
const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const HOOKS_DIR = __dirname;
const PROJECT_DIR = path.resolve(HOOKS_DIR, "..", "..");

function runHook(name, payload) {
  return spawnSync(process.execPath, [path.join(HOOKS_DIR, name)], {
    input: payload === undefined ? "" : JSON.stringify(payload),
    encoding: "utf8",
    cwd: PROJECT_DIR,
    env: { ...process.env, CLAUDE_PROJECT_DIR: PROJECT_DIR },
  });
}

function writePayload(filePath) {
  return { tool_name: "Write", tool_input: { file_path: filePath } };
}

const BLOCKED = [
  "/repo/.env",
  "/repo/.env.production",
  "C:\\Users\\Amram\\IMPORTANT\\Personal\\TV\\.env.local",
  "/repo/app/credentials.json",
  "/repo/secrets.yaml",
  "/repo/certs/server.pem",
  "/repo/certs/server.key",
  "/repo/certs/client.p12",
  "/repo/Marvel.xlsx",
  "C:\\Users\\Amram\\IMPORTANT\\Personal\\TV\\One_Piece.xlsx",
  // Case must not be a way past the guard: isSensitivePath lowercases before it compares.
  "/repo/.ENV",
];

for (const blocked of BLOCKED) {
  test(`pre-tool-use denies a write to ${blocked}`, () => {
    const result = runHook("pre-tool-use.cjs", writePayload(blocked));
    assert.equal(result.status, 0);
    const out = JSON.parse(result.stdout);
    assert.equal(out.decision, "block");
    assert.equal(out.hookSpecificOutput.hookEventName, "PreToolUse");
    assert.equal(out.hookSpecificOutput.permissionDecision, "deny");
    assert.match(out.hookSpecificOutput.permissionDecisionReason, /owner|Catalog\._write/);
  });
}

// The last three are near-misses. They fail loudly if a pattern is ever broadened from an exact
// basename test to a substring one: `.env.example` is the file T01b writes, `.envrc` merely starts
// with the same five characters, and `key.txt` merely contains "key".
const ALLOWED = [
  "/repo/app/backend/src/tv_watchlist/config.py",
  "/repo/README.md",
  "/repo/.env.example",
  "/repo/.envrc",
  "/repo/key.txt",
];

for (const allowed of ALLOWED) {
  test(`pre-tool-use stays silent for ${allowed}`, () => {
    const result = runHook("pre-tool-use.cjs", writePayload(allowed));
    assert.equal(result.status, 0);
    assert.equal(result.stdout, "");
  });
}

test("pre-tool-use tolerates an empty payload", () => {
  const result = runHook("pre-tool-use.cjs");
  assert.equal(result.status, 0);
  assert.equal(result.stdout, "");
});

test("post-tool-use reminds about the funnel when the Excel layer is edited", () => {
  const result = runHook("post-tool-use.cjs", writePayload("/repo/app/backend/src/tv_watchlist/workbook/writer.py"));
  const out = JSON.parse(result.stdout);
  assert.equal(out.hookSpecificOutput.hookEventName, "PostToolUse");
  assert.match(out.hookSpecificOutput.additionalContext, /Catalog\._write/);
  assert.match(out.hookSpecificOutput.additionalContext, /ranges\.sync/);
});

test("post-tool-use reminds about both sides when a contract file is edited", () => {
  const result = runHook("post-tool-use.cjs", writePayload("/repo/app/frontend/src/types/ColumnSpec.ts"));
  const out = JSON.parse(result.stdout);
  assert.match(out.hookSpecificOutput.additionalContext, /minor/);
});

test("post-tool-use reminds about the ORM rules when a data model is edited", () => {
  const result = runHook("post-tool-use.cjs", writePayload("/repo/app/backend/src/tv_watchlist/data/models/title.py"));
  const out = JSON.parse(result.stdout);
  assert.match(out.hookSpecificOutput.additionalContext, /raise_on_sql/);
  assert.match(out.hookSpecificOutput.additionalContext, /_seconds/);
});

test("post-tool-use reminds about the hand-ordered downgrade when a revision is edited", () => {
  const result = runHook("post-tool-use.cjs", writePayload("/repo/app/backend/alembic/versions/0001_initial.py"));
  const out = JSON.parse(result.stdout);
  assert.match(out.hookSpecificOutput.additionalContext, /downgrade\(\) is hand-ordered/);
  assert.match(out.hookSpecificOutput.additionalContext, /watch_event_no_mutation/);
});

test("post-tool-use reminds about the funnel and the mirror when a service is edited", () => {
  const result = runHook("post-tool-use.cjs", writePayload("/repo/app/backend/src/tv_watchlist/services/catalog.py"));
  const out = JSON.parse(result.stdout);
  assert.match(out.hookSpecificOutput.additionalContext, /one Catalog\._write call/);
  assert.match(out.hookSpecificOutput.additionalContext, /StaleWorkbookError/);
});

test("post-tool-use reminds about the layout guard when the UI is edited", () => {
  for (const edited of [
    "/repo/app/frontend/src/components/CategoryCard.tsx",
    "/repo/app/frontend/src/styles/route.css",
  ]) {
    const result = runHook("post-tool-use.cjs", writePayload(edited));
    const out = JSON.parse(result.stdout);
    assert.match(out.hookSpecificOutput.additionalContext, /pnpm test:layout/, edited);
    assert.match(out.hookSpecificOutput.additionalContext, /jsdom has no layout engine/, edited);
  }
});

test("post-tool-use reminds about SecretStr when settings are edited", () => {
  const result = runHook("post-tool-use.cjs", writePayload("/repo/app/backend/src/tv_watchlist/config.py"));
  const out = JSON.parse(result.stdout);
  assert.match(out.hookSpecificOutput.additionalContext, /SecretStr/);
  assert.match(out.hookSpecificOutput.additionalContext, /\.env\.example/);
});

test("post-tool-use is silent for an unremarkable file", () => {
  const result = runHook("post-tool-use.cjs", writePayload("/repo/app/README.md"));
  assert.equal(result.stdout, "");
});

test("session-start prints the orientation banner in under 20 lines", () => {
  const result = runHook("session-start.cjs");
  assert.equal(result.status, 0);
  assert.match(result.stdout, /TV WATCH LIST SESSION START/);
  assert.match(result.stdout, /P0 .* P1 .* P3 .* P2/);
  assert.match(result.stdout, /workbooks/);
  assert.ok(result.stdout.trim().split("\n").length <= 20, `banner is ${result.stdout.trim().split("\n").length} lines`);
});

test("pre-compact tells the summariser what to keep", () => {
  const result = runHook("pre-compact.cjs", { trigger: "auto" });
  const out = JSON.parse(result.stdout);
  assert.match(out.systemMessage, /phase/i);
  assert.match(out.systemMessage, /versions\.md/);
});

test("stop-memory emits the memory review prompt", () => {
  const result = runHook("stop-memory.cjs");
  const out = JSON.parse(result.stdout);
  assert.match(out.systemMessage, /MEMORY REVIEW/);
});

test("stop never exits non-zero", () => {
  const result = runHook("stop.cjs");
  assert.equal(result.status, 0);
});

function gitIsAvailable() {
  const result = spawnSync("git", ["--version"], { encoding: "utf8", windowsHide: true });
  return Boolean(result) && result.status === 0;
}

// A throwaway repo under the OS temp dir, so the dirty-tree branches are exercised deterministically
// instead of depending on whatever the real working tree happens to hold. The project's own git state
// is never touched: nothing here runs against PROJECT_DIR.
function aDirtyRepo() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "tv-stop-hook-"));
  spawnSync("git", ["init", "-q", dir], { encoding: "utf8", windowsHide: true });
  fs.writeFileSync(path.join(dir, "Marvel.xlsx"), "");
  fs.mkdirSync(path.join(dir, "app", "frontend", "src", "components"), { recursive: true });
  fs.writeFileSync(path.join(dir, "app", "frontend", "src", "components", "Card.tsx"), "");
  return dir;
}

test("stop names a dirty tree without ever suggesting a git command", { skip: gitIsAvailable() ? false : "git is not on PATH" }, () => {
  const dir = aDirtyRepo();
  try {
    const result = spawnSync(process.execPath, [path.join(HOOKS_DIR, "stop.cjs")], {
      input: "",
      encoding: "utf8",
      cwd: dir,
      env: { ...process.env, CLAUDE_PROJECT_DIR: dir },
    });
    assert.equal(result.status, 0);
    const { systemMessage } = JSON.parse(result.stdout);
    assert.match(systemMessage, /Uncommitted changes/);
    // The three conditional branches: docs/ untouched, a workbook changed, the UI changed.
    assert.match(systemMessage, /docs\/status\.md/);
    assert.match(systemMessage, /Marvel\.xlsx/);
    assert.match(systemMessage, /pnpm test:layout/);
    // The standing rule (CLAUDE.md section 17.5): git is the owner's, so the hook reports and never prescribes.
    assert.doesNotMatch(systemMessage, /git (add|commit|push|checkout|stash|reset|rebase|merge|tag)/);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test("stop is silent for a clean tree", { skip: gitIsAvailable() ? false : "git is not on PATH" }, () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "tv-stop-hook-clean-"));
  try {
    spawnSync("git", ["init", "-q", dir], { encoding: "utf8", windowsHide: true });
    const result = spawnSync(process.execPath, [path.join(HOOKS_DIR, "stop.cjs")], {
      input: "",
      encoding: "utf8",
      cwd: dir,
      env: { ...process.env, CLAUDE_PROJECT_DIR: dir },
    });
    assert.equal(result.status, 0);
    assert.equal(result.stdout, "");
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
