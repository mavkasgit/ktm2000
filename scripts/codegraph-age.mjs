#!/usr/bin/env node
// Возраст codegraph-индекса (#359). Индекс вне git и стареет незаметно: ответы по
// коду, изменённому после последнего `sync`, выглядят как правда, но взяты из
// устаревшей выдачи. Поэтому возраст — шаг гейта, а не памятка.
//
// Различает два состояния, которые иначе путают: индекса нет (нужен `init`) и
// индекс есть, но старше HEAD (нужен `sync`).

import { existsSync, statSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = dirname(dirname(fileURLToPath(import.meta.url)));
const DB = ".codegraph/codegraph.db";
const SYNC = "npx @colbymchenry/codegraph sync";
const INIT = "npx @colbymchenry/codegraph init -y";

const args = process.argv.slice(2);
for (const flag of args) {
  if (!["--json", "--strict"].includes(flag)) {
    console.error(`codegraph-age: неизвестный флаг ${flag} (есть --json, --strict)`);
    process.exit(2);
  }
}
const strict = args.includes("--strict");

function git(...rest) {
  const r = spawnSync("git", rest, { cwd: ROOT, encoding: "utf8" });
  return r.status === 0 ? r.stdout.trim() : "";
}

const path = join(ROOT, DB);
const commitTs = Number(git("log", "-1", "--format=%ct") || "0");
const commitSha = git("rev-parse", "--short", "HEAD");
const now = Math.floor(Date.now() / 1000);

let verdict;
let detail;
let exitCode = 0;

if (!existsSync(path)) {
  // Не «устарел» и не падение: отдельное состояние с отдельной командой.
  verdict = "no-index";
  detail = `индекса нет (${DB}) — один раз на машину/клон: ${INIT}, затем ${SYNC}`;
  exitCode = strict ? 1 : 0;
} else {
  const mtime = Math.floor(statSync(path).mtimeMs / 1000);
  const ageHours = ((now - mtime) / 3600).toFixed(1);
  if (commitTs && mtime < commitTs) {
    verdict = "stale";
    const behind = Math.round((commitTs - mtime) / 60);
    detail =
      `индекс старше HEAD (${commitSha}): коммит на ${behind} мин новее индекса — ${SYNC} не делали; ` +
      `разведка по коду этих коммитов берётся из устаревшей выдачи. Команда: ${SYNC}`;
    // Локально — предупреждение: устаревший индекс не делает правку неправильной,
    // но обязывает знать, на чём стоит ответ. Красным становится в `--strict` (CI).
    exitCode = strict ? 1 : 0;
  } else {
    verdict = "ok";
    const sinceCommit = commitTs ? Math.round((mtime - commitTs) / 60) : null;
    detail =
      `индекс младше HEAD (${commitSha})${sinceCommit === null ? "" : `, на ${sinceCommit} мин новее коммита`}; ` +
      `возраст файла ${ageHours} ч`;
    exitCode = 0;
  }
}

if (args.includes("--json")) {
  console.log(
    JSON.stringify(
      { verdict, strict, detail, db: DB, head: commitSha, checked_at: new Date().toISOString() },
      null,
      2,
    ),
  );
} else {
  const mark = { ok: "·", "no-index": "!", stale: "⚠" }[verdict];
  const suffix = verdict === "stale" && !strict ? " (не блокирует; `--strict` ⇒ красный)" : "";
  console.log(`codegraph ${mark} ${verdict} — ${detail}${suffix}`);
}

process.exitCode = exitCode;
