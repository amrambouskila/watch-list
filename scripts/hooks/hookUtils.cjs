const childProcess = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

// Project root: Claude/Codex set CLAUDE_PROJECT_DIR and run hooks with cwd = root.
// Fall back to cwd so the same code works under both agents and any shell.
const PROJECT_DIR = process.env.CLAUDE_PROJECT_DIR || process.cwd();

function readStdin() {
  return new Promise((resolve) => {
    let input = "";
    process.stdin.setEncoding("utf8");
    process.stdin.on("data", (chunk) => {
      input += chunk;
    });
    process.stdin.on("end", () => {
      resolve(input);
    });
    // If nothing is piped, end never fires on some shells; guard with a tick.
    if (process.stdin.isTTY) {
      resolve("");
    }
  });
}

async function readHookPayload() {
  const input = await readStdin();
  const trimmed = input.trim();
  if (trimmed.length === 0) {
    return {};
  }
  try {
    return JSON.parse(trimmed);
  } catch {
    return {};
  }
}

function getToolFilePath(payload) {
  if (!payload || typeof payload !== "object") {
    return "";
  }
  const toolInput = payload.tool_input;
  if (toolInput && typeof toolInput === "object") {
    if (typeof toolInput.file_path === "string") {
      return toolInput.file_path;
    }
    if (typeof toolInput.path === "string") {
      return toolInput.path;
    }
  }
  const toolResponse = payload.tool_response;
  if (toolResponse && typeof toolResponse === "object" && typeof toolResponse.filePath === "string") {
    return toolResponse.filePath;
  }
  return "";
}

function toPosixPath(filePath) {
  return String(filePath).replace(/\\/g, "/");
}

// Block any .env / .env.* (except example/sample/template), credentials, secrets,
// and private-key material. Comprehensive union of every project's prior guard.
function isSensitivePath(filePath) {
  const normalized = toPosixPath(filePath).toLowerCase();
  if (!normalized) {
    return false;
  }
  const basename = path.posix.basename(normalized);
  const isEnv =
    basename === ".env" ||
    (basename.startsWith(".env.") &&
      !basename.endsWith(".example") &&
      !basename.endsWith(".sample") &&
      !basename.endsWith(".template"));
  return (
    isEnv ||
    normalized.includes("credentials.") ||
    normalized.includes("secrets.") ||
    basename.endsWith(".pem") ||
    basename.endsWith(".key") ||
    basename.endsWith(".p12") ||
    basename.endsWith(".pfx") ||
    basename.endsWith(".pickle") ||
    basename.includes("id_rsa") ||
    basename.includes("id_ed25519") ||
    normalized.includes("/.tokens/")
  );
}

function projectName() {
  return path.basename(PROJECT_DIR);
}

function readText(relativePath) {
  try {
    return fs.readFileSync(path.join(PROJECT_DIR, relativePath), "utf8");
  } catch {
    return null;
  }
}

function fileExists(relativePath) {
  try {
    return fs.existsSync(path.join(PROJECT_DIR, relativePath));
  } catch {
    return false;
  }
}

function splitLines(text) {
  return text.split(/\r?\n/);
}

function head(text, count) {
  return splitLines(text).slice(0, count).join("\n");
}

function tail(text, count) {
  const lines = splitLines(text);
  return lines.slice(Math.max(0, lines.length - count)).join("\n");
}

// Run git read-only against the project dir; "" on any failure (not a repo, no git).
function gitOutput(args) {
  const safeDirectory = toPosixPath(PROJECT_DIR);
  const result = childProcess.spawnSync(
    "git",
    ["-C", PROJECT_DIR, "-c", `safe.directory=${safeDirectory}`, ...args],
    { encoding: "utf8", windowsHide: true },
  );
  if (!result || result.status !== 0 || typeof result.stdout !== "string") {
    return "";
  }
  return result.stdout.trim();
}

function uncommittedFiles() {
  const changed = gitOutput(["diff", "--name-only"]);
  const staged = gitOutput(["diff", "--cached", "--name-only"]);
  const untracked = gitOutput(["ls-files", "--others", "--exclude-standard"]);
  return Array.from(
    new Set(
      `${changed}\n${staged}\n${untracked}`
        .split(/\r?\n/)
        .map((line) => line.trim())
        .filter(Boolean),
    ),
  );
}

function emit(object) {
  process.stdout.write(JSON.stringify(object));
}

module.exports = {
  PROJECT_DIR,
  emit,
  fileExists,
  getToolFilePath,
  gitOutput,
  head,
  isSensitivePath,
  projectName,
  readHookPayload,
  readText,
  tail,
  toPosixPath,
  uncommittedFiles,
};
