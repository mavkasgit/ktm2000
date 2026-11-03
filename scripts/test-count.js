// scripts/test-count.js
"use strict";

/**
 * Рэтчет числа тестов (#358): собранное количество сверяется с минимумом из
 * baseline, уменьшение — красный шаг.
 *
 * Собираются именно списки тестов без прогона: `pytest --collect-only` (секунды)
 * и `vitest list` (минута). Прогон не нужен — проверка про «исчезли ли тесты», а
 * не про «падают ли они»; падают они в шагах backend-tests и frontend-unit.
 *
 * Выход: 0 — рэтчет не нарушен, 1 — тестов стало меньше (или разбор сломался),
 * 2 — неверные аргументы.
 */

const { spawnSync } = require("node:child_process");
const { existsSync, readFileSync, writeFileSync } = require("node:fs");
const { dirname, join } = require("node:path");
const { parsePytestCollect, parseVitestList, formatReductions, evaluateStored } = require("./test-count-core.js");

const ROOT = dirname(__dirname);
const BASELINE_REL = "scripts/test-count-baseline.json";
const BASELINE = join(ROOT, "scripts", "test-count-baseline.json");

const USAGE = `test-count — рэтчет числа тестов против baseline ${BASELINE_REL}

  node scripts/test-count.js                  сверить backend и frontend
  node scripts/test-count.js --only=backend   один источник (backend — секунды, frontend — минута)
  node scripts/test-count.js --update         записать текущие числа (осознанный шаг после удаления тестов)
  node scripts/test-count.js --json           машинная выдача`;

const SOURCES = {
  backend: {
    dir: "backend",
    collector: "pytest --collect-only -q",
    run: () => [process.env.KTM_PYTHON || "python", ["-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"]],
    parse: parsePytestCollect,
  },
  frontend: {
    dir: "frontend",
    collector: "vitest list",
    run: () => ["npx", ["vitest", "list"]],
    parse: parseVitestList,
  },
};

const args = process.argv.slice(2);
const opts = { only: Object.keys(SOURCES), json: false, update: false };
for (const raw of args) {
  if (raw === "--json") opts.json = true;
  else if (raw === "--update") opts.update = true;
  else if (raw === "--help" || raw === "-h") {
    console.log(USAGE);
    process.exit(0);
  } else if (raw.startsWith("--only=")) {
    const picked = raw.slice(7).split(",").filter(Boolean);
    const unknown = picked.filter((p) => !SOURCES[p]);
    if (unknown.length) {
      console.error(`test-count: неизвестный источник ${unknown.join(", ")} (есть ${Object.keys(SOURCES).join(", ")})`);
      process.exit(2);
    }
    opts.only = picked;
  } else {
    console.error(`test-count: неизвестный аргумент ${raw} (есть --only=…, --update, --json, --help)`);
    process.exit(2);
  }
}

function collect(source) {
  const [bin, rest] = source.run();
  // Команда собирается строкой: `npx` на Windows — пакетник, без оболочки он не
  // запускается, а Node ругает передачу args вместе с shell:true предупреждением,
  // которое попало бы в хвост вывода гейта. Кавычки только вокруг путей с
  // пробелами: cmd.exe не понимает «"npx"». Аргументы — только литералы.
  const exe = /\s/.test(bin) ? `"${bin}"` : bin;
  const r = spawnSync(`${exe} ${rest.join(" ")}`, {
    cwd: join(ROOT, source.dir),
    encoding: "utf8",
    shell: true,
    maxBuffer: 64 * 1024 * 1024,
  });
  if (r.error) return { ok: false, reason: `не удалось запустить «${bin}»: ${r.error.message}` };
  if (r.status !== 0) {
    const tail = (r.stdout + (r.stderr || "")).trim().split(/\r?\n/).slice(-3).join(" / ");
    return { ok: false, reason: `сборщик упал (код ${r.status}): ${tail}` };
  }
  return source.parse(r.stdout);
}

function readBaseline() {
  if (!existsSync(BASELINE)) return null;
  try {
    return JSON.parse(readFileSync(BASELINE, "utf8"));
  } catch (e) {
    return { broken: `baseline не читается: ${e.message}` };
  }
}

const today = new Date().toLocaleDateString("sv-SE");
const results = [];

for (const name of opts.only) {
  const source = SOURCES[name];
  const current = collect(source);
  if (!current.ok) {
    results.push({ source: name, ok: false, reason: current.reason, anomalies: current.anomalies || [] });
    continue;
  }
  if (opts.update) {
    const baseline = readBaseline() || { sources: {} };
    if (baseline.broken) {
      results.push({ source: name, ok: false, reason: baseline.broken });
      continue;
    }
    baseline.sources[name] = {
      collector: source.collector,
      total: current.total,
      by_file: Object.fromEntries(Object.entries(current.by_file).sort(([a], [b]) => a.localeCompare(b))),
    };
    baseline.updated = today;
    writeFileSync(BASELINE, `${JSON.stringify(baseline, null, 2)}\n`);
    results.push({ source: name, ok: true, total: current.total, updated: true });
    continue;
  }

  const baseline = readBaseline();
  if (!baseline || baseline.broken) {
    results.push({
      source: name,
      ok: false,
      reason: baseline ? baseline.broken : `нет baseline ${BASELINE_REL} — собери его: npm run test-count -- --update`,
    });
    continue;
  }
  const stored = baseline.sources[name];
  if (!stored) {
    results.push({ source: name, ok: false, reason: `в baseline нет источника ${name} — обнови: npm run test-count -- --update` });
    continue;
  }
  const lost = evaluateStored(stored, current);
  results.push({ source: name, ...lost });
}

const red = results.filter((r) => !r.ok);

if (opts.json) {
  console.log(JSON.stringify({ verdict: red.length ? "NO-GO" : "GO", updated: opts.update, results }, null, 2));
} else if (opts.update) {
  for (const r of results) {
    console.log(r.ok ? `test-count ${r.source.padEnd(9)} baseline обновлён: ${r.total} тестов` : `test-count ${r.source.padEnd(9)} красный — ${r.reason}`);
  }
} else {
  for (const r of results) {
    if (r.ok) {
      const grew = r.total > r.baseline_total ? ` (+${r.total - r.baseline_total} с последней записи — самое время npm run test-count -- --update)` : "";
      console.log(`test-count ${r.source.padEnd(9)} ok — ${r.total} тестов в ${r.files} файлах, минимум ${r.baseline_total}${grew}`);
    } else {
      console.log(`test-count ${r.source.padEnd(9)} КРАСНЫЙ — ${r.reason}`);
      for (const line of formatReductions(r.reductions || [])) console.log(line);
      if ((r.reductions || []).length) {
        console.log("  если удаление намеренное — признай его явно: npm run test-count -- --update");
      }
    }
  }
}

process.exitCode = red.length ? 1 : 0;
