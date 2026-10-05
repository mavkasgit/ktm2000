/**
 * Проверка markdown-ссылок репозитория: каждая относительная ссылка должна
 * указывать на файл, который есть в git.
 *
 * Ловит то, чего не ловит ни один другой workflow: переименование документа
 * оставляет ссылку в силе, CI остаётся зелёным, и битый указатель живёт до
 * того момента, когда по нему кто-то пройдёт.
 *
 * Локальный запуск — `npm run check:docs` из корня.
 */

"use strict";

const { execFileSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const { findBrokenLinks } = require("./check-doc-links-core");

/**
 * Все отслеживаемые git пути — вселенная для целей ссылок: цель может вести
 * на `.ts` или `.mjs`, поэтому отсюда отсекать ничего нельзя.
 */
function listTrackedPaths(repoRoot) {
  const out = execFileSync("git", ["ls-files", "-z"], {
    cwd: repoRoot,
    encoding: "utf8",
    maxBuffer: 32 * 1024 * 1024,
  });
  return out.split("\0").filter(Boolean);
}

function main() {
  const repoRoot = path.resolve(__dirname, "..");
  const trackedPaths = listTrackedPaths(repoRoot);
  const markdownPaths = trackedPaths.filter((file) => file.endsWith(".md"));

  const files = markdownPaths.map((file) => ({
    path: file,
    content: fs.readFileSync(path.join(repoRoot, file), "utf8"),
  }));

  const broken = findBrokenLinks(files, trackedPaths);

  if (broken.length === 0) {
    console.log(
      `docs: битых ссылок нет — ${markdownPaths.length} markdown-файлов, ` +
        `ссылки резолвятся в ${trackedPaths.length} отслеживаемых путей`,
    );
    return 0;
  }

  console.error(`docs: битых ссылок — ${broken.length}\n`);
  for (const { file, target, resolved } of broken) {
    console.error(`  ${file} → ${target}  (нет такого пути: ${resolved})`);
  }
  console.error(
    "\nПравьте цель ссылки или восстанавливайте файл: docs/agents/domain.md",
  );
  return 1;
}

process.exit(main());