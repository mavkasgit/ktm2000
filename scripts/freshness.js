#!/usr/bin/env node
// Свежесть закреплённых инструментов (#368).
//
// Пины есть, их возраст неизвестен. Скрипт отвечает на два разных вопроса и
// не смешивает:
//
//   1. локально, без сети — как давно мы смотрели в этот пин (git-возраст файла
//      закрепления + дата last_reviewed из реестра);
//   2. с `--online` — есть ли версия свежее закреплённой (npm-реестр и PyPI).
//
// Вопрос «жив ли репозиторий» (archived/renamed) решается тем же `inspectFreshness`,
// но источников для него здесь нет: GitHub API без токена на 24 репозитория —
// это лимит 60 запросов в час на машину, а отказ опроса выглядел бы как
// «всё свеже». Отдельный tracking issue, который перезаписывает CI, тоже не
// завели: вместо него понедельничный прогон кладёт отчёт в Step Summary.
// Причины — docs/quality/not-adopted.md.
//
// По умолчанию шаг предупреждает: код выхода 0, даже когда есть флаги. Красным
// он становится с `--strict` (так его вызывает CI) и только по флагам уровня
// `fail` — «нет пин-файла» и «репозиторий в архиве». Warn-уровень («пин не
// смотрели больше полугода», «вышла версия свежее») намеренно не блокирует:
// иначе недельный cron краснел бы всегда и перестал бы что-то означать.

const { spawnSync } = require("node:child_process");
const { existsSync, readFileSync } = require("node:fs");
const { join } = require("node:path");
const { inspectFreshness, distNameFromPin, DEFAULT_THRESHOLDS } = require("./freshness-core.js");

const ROOT = join(__dirname, "..");
const REGISTRY = "tools.json";
const FETCH_TIMEOUT_MS = 8000;

const USAGE = `Использование: node scripts/freshness.js [--online] [--json] [--strict]

  --online   опросить npm-реестр и PyPI (нет сети — флаг upstream-unknown, не «свежо»)
  --json     выдача машиночитаемая
  --strict   флаги уровня fail красным кодом выхода (так вызывает CI)`;

function parseArgs(argv) {
  const out = { online: false, json: false, strict: false, help: false };
  for (const raw of argv) {
    if (raw === "--online") out.online = true;
    else if (raw === "--json") out.json = true;
    else if (raw === "--strict") out.strict = true;
    else if (raw === "--help" || raw === "-h") out.help = true;
    else {
      process.stderr.write(`freshness: неизвестный флаг ${raw}\n\n${USAGE}\n`);
      process.exit(2);
    }
  }
  return out;
}

/** Последняя дата коммита, тронувшего файл закрепления; один запрос на путь. */
function lastCommitDate(cache, path) {
  if (!cache.has(path)) {
    const r = spawnSync("git", ["log", "-1", "--date=short", "--format=%ad", "--", path], {
      cwd: ROOT,
      encoding: "utf8",
    });
    cache.set(path, r.status === 0 && r.stdout.trim() ? r.stdout.trim() : null);
  }
  return cache.get(path);
}

async function fetchJson(url) {
  const res = await fetch(url, {
    signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
    headers: { "user-agent": "ktm2000-freshness (#368)" },
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

/** npm: latest + дата выпуска этой версии (дата, не timestamp: сравнения по дням). */
async function fromNpm(pkg) {
  const meta = await fetchJson(`https://registry.npmjs.org/${encodeURIComponent(pkg)}`);
  const latest = (meta["dist-tags"] || {}).latest;
  if (!latest) throw new Error("нет dist-tags.latest");
  const time = (meta.time || {})[latest] || null;
  return { latest_version: latest, published_at: time ? time.slice(0, 10) : null };
}

/** PyPI: версия из info и дата первого файла релиза. */
async function fromPypi(name) {
  const data = await fetchJson(`https://pypi.org/pypi/${encodeURIComponent(name)}/json`);
  const latest = (data.info || {}).version;
  if (!latest) throw new Error("нет info.version");
  const files = (data.releases || {})[latest] || [];
  return { latest_version: latest, published_at: files[0] ? files[0].upload_time.slice(0, 10) : null };
}

/**
 * Чем опрашивать: npm-пакет из реестра, python-пакет — по строке закрепления.
 * Имя берётся из текста пина, а не из `name`: «coverage.py» на PyPI нет.
 */
function sourceFor(entry) {
  if (entry.npm_package) return { kind: "npm", name: entry.npm_package, fetch: fromNpm };
  const pinnedIn = entry.pinned_in || "";
  if (!/requirements[^/]*\.txt$/.test(pinnedIn)) return null;
  let text = "";
  try {
    text = readFileSync(join(ROOT, pinnedIn), "utf8");
  } catch {
    return { kind: "pypi", name: null, fetch: null, error: `не читается ${pinnedIn}` };
  }
  const name = distNameFromPin(text, entry.version);
  return name
    ? { kind: "pypi", name, fetch: fromPypi }
    : { kind: "pypi", name: null, fetch: null, error: `версия ${entry.version} не найдена в ${pinnedIn}` };
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    process.stdout.write(`${USAGE}\n`);
    return 0;
  }

  const registryPath = join(ROOT, REGISTRY);
  if (!existsSync(registryPath)) {
    process.stderr.write(`freshness: ${REGISTRY} не найден — реестра нет, проверять нечего\n`);
    return 2;
  }
  const tools = JSON.parse(readFileSync(registryPath, "utf8")).tools || [];

  const gitCache = new Map();
  const entries = tools.map((t) => {
    const pinPath = t.pinned_in;
    const exists = existsSync(join(ROOT, pinPath));
    return {
      ...t,
      pin_exists: exists,
      pin_committed_at: exists ? lastCommitDate(gitCache, pinPath) : null,
    };
  });

  const asked = [];
  if (args.online) {
    const settled = await Promise.allSettled(
      entries.map(async (e) => {
        const src = sourceFor(e);
        if (!src) return;
        if (!src.fetch) {
          // Имя пакета не выводится из закрепления: это наш пробел, а не
          // молчание реестра — сказано прямо.
          e.upstream = { kind: src.kind, repo: e.repo, error: src.error };
          return;
        }
        try {
          e.upstream = { kind: src.kind, repo: e.repo, ...(await src.fetch(src.name)) };
          asked.push(src.name);
        } catch (error) {
          e.upstream = { kind: src.kind, repo: e.repo, error: `${src.kind}: ${error.message}` };
          asked.push(src.name);
        }
      }),
    );
    // Ошибки самой обёртки (не реестра) тоже должны быть видны, а не проглочены.
    for (const one of settled) {
      if (one.status === "rejected") {
        process.stderr.write(`freshness: опрос упал вне реестра: ${one.reason}\n`);
      }
    }
  }

  const findings = inspectFreshness(entries, DEFAULT_THRESHOLDS, new Date().toISOString().slice(0, 10));
  const counts = findings.reduce(
    (acc, f) => ({ ...acc, [f.level]: (acc[f.level] || 0) + 1 }),
    { fail: 0, warn: 0, info: 0 },
  );

  if (args.json) {
    process.stdout.write(
      `${JSON.stringify(
        {
          registry: REGISTRY,
          thresholds: DEFAULT_THRESHOLDS,
          online: args.online,
          asked: asked.length,
          entries: entries.length,
          findings,
          counts,
          checked_at: new Date().toISOString(),
        },
        null,
        2,
      )}\n`,
    );
  } else {
    const scope = args.online
      ? `опрошено реестров: ${asked.length}`
      : "апстрим не опрашивался (добавить --online)";
    process.stdout.write(
      `Свежесть: ${entries.length} записей реестра, пороги ${DEFAULT_THRESHOLDS.review}/${DEFAULT_THRESHOLDS.release} дн., ${scope}\n`,
    );
    const mark = { fail: "✖", warn: "⚠", info: "·" };
    for (const f of findings) {
      process.stdout.write(`  ${mark[f.level] || "·"} ${f.code}: ${f.message}\n`);
    }
    if (!findings.length) {
      process.stdout.write("  флагов нет\n");
    }
    process.stdout.write(
      `итог: fail ${counts.fail}, warn ${counts.warn}, info ${counts.info}` +
        (args.strict ? "" : " — без --strict шаг не блокирует") +
        "\n",
    );
  }

  if (args.strict && counts.fail > 0) return 1;
  return 0;
}

main().then(
  (code) => {
    process.exitCode = code;
  },
  (error) => {
    process.stderr.write(`freshness: сбой разбора: ${error && error.stack ? error.stack : error}\n`);
    process.exitCode = 2;
  },
);
