const { emit, projectName, toPosixPath, uncommittedFiles } = require("./hookUtils.cjs");

function main() {
  const files = uncommittedFiles();
  if (files.length === 0) {
    return;
  }
  const posix = files.map((file) => toPosixPath(file));
  const parts = [
    `Uncommitted changes in ${projectName()}: ${files.length} file(s). The owner manages git - run no mutating git command; report the files and suggest a commit message only.`,
  ];
  if (!posix.some((file) => file.startsWith("docs/"))) {
    parts.push("Source changed but docs/ did not - docs/status.md and docs/versions.md need updating (one unreleased heading, computed number).");
  }
  const workbooks = posix.filter((file) => file.endsWith(".xlsx"));
  if (workbooks.length > 0) {
    parts.push(`Workbook(s) changed on disk: ${workbooks.join(", ")}. Confirm each went through Catalog._write (a snapshot exists in app/.backups) or was the owner's own Excel edit.`);
  }
  if (posix.some((file) => file.startsWith("app/frontend/src/components/") || file.startsWith("app/frontend/src/styles/"))) {
    parts.push("UI changed - pnpm test:layout must have run at all four viewports.");
  }
  emit({ systemMessage: parts.join(" ") });
}

try {
  main();
} catch (error) {
  process.stderr.write(`[hook] stop failed: ${error.message}\n`);
}
