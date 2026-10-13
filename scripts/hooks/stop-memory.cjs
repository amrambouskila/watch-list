const { emit } = require("./hookUtils.cjs");

const systemMessage = [
  "SESSION END — MEMORY REVIEW: review what was learned and suggest memories the user may want to save.",
  "Check the project's memory index first (~/.claude/projects/<slug>/memory/ for Claude, ~/.codex/memories/<slug>/memory/ for Codex) to avoid duplicates — update existing memories rather than creating new ones when the topic already exists.",
  "Memory types: user (role, preferences, knowledge), feedback (corrections / confirmed approaches — include WHY), project (decisions with external motivation, deadlines, stakeholders), reference (pointers to external systems).",
  "Worth saving: corrections the user gave you, non-obvious approaches they confirmed, decisions driven by external factors, pointers to external tools.",
  "NOT worth saving: anything derivable from code or git history, debugging solutions, ephemeral task details, things already in CLAUDE.md / AGENTS.md.",
  "Present a short bulleted list of suggested memories and let the user decide.",
].join(" ");

emit({ systemMessage });
