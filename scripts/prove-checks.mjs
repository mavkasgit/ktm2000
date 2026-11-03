#!/usr/bin/env node
// Каждая проверка гейта должна быть увидена красной хотя бы раз (#357).
//
// Принцип донора: «a check that was never seen failing is not known to work».
// Шаг, который всегда зелёный, выглядит как защита и не является ею: он может
// молча не запускать проверяемое (опечатка в команде, нет файла, инструмент не
// найден PATH, глоб проходит мимо каталога).
//
// Что делает пробник: вносит одно реальное нарушение → запускает шаг через
// `gate --only=<шаг>` (то есть проверяется интеграция, а не только утилита) →
// требует ненулевого выхода и узнаваемого текста → откатывает → требует, чтобы
// дерево снова было чистым.
//
// Ничего не правится в продуктовом коде: нарушения — временные файлы с префиксом
// `_probe357_` и точечные правки в файлах, которые создала эта же волна.
//
// Запуск: npm run prove-checks            — лёгкие пробники (все, кроме дорогих)
//         npm run prove-checks -- --heavy — добавить backend-tests/frontend-unit
//         npm run prove-checks -- --only=ruff,docs-links
//         npm run prove-checks -- --list

import { spawnSync } from "node:child_process";
import {
  closeSync,
  existsSync,
  mkdirSync,
  openSync,
  readFileSync,
  statSync,
  unlinkSync,
  utimesSync,
  writeFileSync,
} from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = dirname(dirname(fileURLToPath(import.meta.url)));
const RECORD = join(ROOT, "docs", "quality", "proven-checks.json");

/** Шаг, который локально не запускается, доказать пробником нельзя — он exempt. */
const EXEMPT = {
  "alembic-drift": "локально не запускается (накатывает миграции на dev-БД живого стенда); способность падать показана в CI migrations.yml",
  "e2e-smoke": "берёт слот семафора и свой стенд; отдельный ярус gate:e2e, красные ходы — в истории прогонов frontend/e2e",
  // Report-only по решению владельца (T-0012, сноска в #386): шаг не может
  // покраснеть намеренно. Блокирующую часть ловит ruff F401, а ruff пробником
  // доказан — значит «мёртвый импорт» в гейте всё равно красный, просто другим шагом.
  "test-hygiene": "сам шаг возвращает 0 при находках (report-only, T-0012) — краснеть не на чем; блокирует ruff F401, см. пробник шага ruff",
};

/**
 * `via` — команду шага не выбираем: всегда `gate --only=<шаг>`, чтобы краснел
 * именно гейт. Исключение — шаги, которым нужен strict (warn-only по умолчанию).
 */
const PROBES = [
  {
    step: "pins",
    mutate: [{ path: ".nvmrc", to: "1.0\n" }],
    expect: /nvmrc|node/i,
    note: "приписанный Node, которого нет на машине",
  },
  {
    step: "registry",
    mutate: [{ path: "tools.json", from: '"version": "0.16.9"', to: '"version": "0.0.0"' }],
    expect: /не найдено|реестр/i,
    note: "версия в реестре расходится с requirements-dev.txt",
  },
  {
    step: "registry",
    mutate: [{ path: "docs/toolchain.md", from: "| `0.16.9` |", to: "| `0.0.1` |" }],
    expect: /отстал от|пересобрать/i,
    note: "сгенерированный тулчейн поправили руками — сверка с реестром обязана покраснеть",
  },
  {
    step: "freshness",
    args: "--strict",
    mutate: [{ path: "tools.json", from: '"pinned_in": ".nvmrc"', to: '"pinned_in": ".nvmrc-probe357"' }],
    expect: /закреплён в .*nvmrc-probe357, но такого файла нет/,
    note: "реестр ссылается на несуществующее закрепление; без --strict шаг не блокирует",
  },
  {
    step: "codegraph-age",
    args: "--strict",
    touch: [{ path: ".codegraph/codegraph.db", mtime: new Date("2000-01-01T00:00:00Z") }],
    expect: /stale|старше HEAD/i,
    note: "индекс отброшен в 2000-й год; без --strict шаг только предупреждает",
    skip_if_absent: ".codegraph/codegraph.db",
    skip_reason: "индекса нет — пробник устаревания нечего накладывать (отдельная ветка текста в самом шаге)",
  },
  {
    step: "docs-links",
    mutate: [{ path: "docs/quality/hooks.md", from: "## Установка и проверка", to: "## Установка и проверка\n\n[ушедший документ](../no/such/doc.md)\n" }],
    expect: /бит[ыю]/i,
    note: "битая относительная ссылка в документе волны",
  },
  {
    step: "adr-index",
    write: [
      {
        path: "docs/adr/0067-probe-number-dubl.md",
        content: '# ADR-0067: Пробник коллизии номеров\n\nДата: 2026-11-03. Статус: принято.\n\n## Контекст\n\nВременный файл: воспроизводит коллизию #390 (два файла с одним номером). Пробник удаляется вместе с прогоном.\n',
      },
    ],
    expect: /дубль номера ADR-0067/,
    note: "второй файл с занятым номером — проверка обязана назвать оба",
  },
  {
    step: "scripts-tests",
    write: [
      {
        path: "scripts/_probe357.test.js",
        content: 'const test = require("node:test");\nconst assert = require("node:assert/strict");\ntest("пробник #357 обязан упасть", () => {\n  assert.equal(1, 2);\n});\n',
      },
    ],
    expect: /fail|1 test failed|✖/i,
    note: "тест с ровно неверным ожиданием",
  },
  {
    step: "labels-check",
    mutate: [{ path: "frontend/src/shared/lib/generated-labels.ts", from: "export const", to: "export const _PROBE357 = 1;\nexport const" }],
    expect: /stale|FAIL/i,
    note: "сгенерированный файл правится руками — сверка обязана покраснеть",
  },
  {
    step: "seeds-validate",
    mutate: [{ path: "backend/app/seeds/route_rule_profiles.py", from: '"route_sections": ["RAW_STOCK"', to: '"route_sections": ["_PROBE357_SECTION"' }],
    expect: /unknown section '_PROBE357_SECTION'/i,
    note: "маршрутный профиль ссылается на участок, которого нет в справочнике",
  },
  {
    step: "profile-settings-manifest",
    mutate: [
      {
        path: "scripts/profile-settings-manifest.json",
        from: '"frontend/src/modules/user-settings/types.ts": "a65d1b90',
        to: '"frontend/src/modules/user-settings/types.ts": "0000dead',
      },
    ],
    expect: /types\.ts|расхожд|stale|измен/i,
    note: "хеш одного файла в манифесте подменён — сверка обязана его назвать",
  },
  {
    step: "compose-audit",
    mutate: [{ path: "infra/compose/docker-compose.dev.yml", from: 'max-size: "20m"', to: 'max-size: "500m"' }],
    expect: /logging|потолок|НЕТ/i,
    note: "потолок лога задран с 20m до 500m — аудит обязан это увидеть",
  },
  {
    step: "ruff",
    write: [{ path: "backend/_probe357.py", content: 'def broken():\n    return undefined_name_357 + 1\n' }],
    expect: /F821|undefined_name_357/i,
    note: "ссылка на несуществующее имя",
  },
  {
    step: "frontend-types",
    write: [{ path: "frontend/src/_probe357.ts", content: 'export const n: number = "строка вместо числа";\n' }],
    expect: /_probe357|TS\d+/i,
    note: "присваивание строки числу",
  },
  {
    step: "frontend-types-e2e",
    write: [
      {
        path: "frontend/e2e/_probe357.spec.ts",
        content: 'import { test } from "@playwright/test";\n\ntest("пробник #357", async ({ page }) => {\n  const wrong: number = page;\n  void wrong;\n});\n',
      },
    ],
    expect: /_probe357|TS\d+/i,
    note: "страница присвоена числу в e2e-спеке",
  },
  {
    step: "frontend-lint",
    write: [{ path: "frontend/src/_probe357.tsx", content: 'export const Bad = () => {\n  return <div>{\n};\n' }],
    expect: /\(([1-9]\d*) error\b/i,
    note: "незакрытый JSX — линтер обязан упасть, а не промолчать (гейт отдаёт хвост вывода, поэтому сверяем итоговую строку с числом ошибок)",
  },
  {
    step: "backend-test-count",
    mutate: [
      {
        path: "scripts/test-count-baseline.json",
        to: '{\n  "sources": {\n    "backend": {\n      "collector": "pytest --collect-only -q",\n      "total": 999999,\n      "by_file": {\n        "tests/_probe358_нет_такого_файла.py": 999999\n      }\n    }\n  },\n  "updated": "2026-11-03"\n}\n',
      },
    ],
    expect: /собрано меньше минимума/,
    note: "в baseline записано тестов больше, чем собрано — рэтчет обязан покраснеть (заниженный минимум зелёный — это критерий (в), он покрыт npm run test:scripts)",
  },
  {
    step: "dev-deps",
    args: "--strict",
    mutate: [
      {
        path: "frontend/package.json",
        from: '"@playwright/test": "^1.60.0",',
        to: '"@playwright/test": "^1.60.0",\n    "_probe374_mertvyj_paket": "^1.0.0",',
      },
    ],
    expect: /_probe374_mertvyj_paket.*не названы/s,
    note: "в devDependencies появляется пакет, который никто не зовёт: проверка обязана назвать его и показать охват просмотра",
  },
  {
    step: "frontend-test-count",
    heavy: true,
    mutate: [
      {
        path: "scripts/test-count-baseline.json",
        to: '{\n  "sources": {\n    "frontend": {\n      "collector": "vitest list",\n      "total": 999999,\n      "by_file": {\n        "src/_probe358_нет_такого_файла.test.ts": 999999\n      }\n    }\n  },\n  "updated": "2026-11-03"\n}\n',
      },
    ],
    expect: /собрано меньше минимума/,
    note: "минимум vitest-набора завышен — рэтчет красный (сбор списка занимает минуту)",
  },
  {
    step: "backend-tests",
    heavy: true,
    write: [
      {
        path: "backend/tests/test_probe357.py",
        content: '"""Пробник #357: проваленное утверждение в основном наборе."""\n\n\ndef test_probe_357_must_fail():\n    assert 1 == 2, "пробник #357 обязан упасть"\n',
      },
    ],
    expect: /1 failed|FAILED test_probe357|assert/i,
    note: "assert False в обычном pytest-файле (полный прогон — минуты)",
  },
  {
    step: "frontend-unit",
    heavy: true,
    write: [
      {
        path: "frontend/src/_probe357.test.ts",
        content: 'import { describe, expect, test } from "vitest";\n\ndescribe("пробник #357", () => {\n  test("обязан упасть", () => {\n    expect(1).toBe(2);\n  });\n});\n',
      },
    ],
    expect: /_probe357|1 failed|FAIL/i,
    note: "vitest с неверным ожиданием (весь набор — минута-две)",
  },
];

function parseArgs(argv) {
  const a = { heavy: false, only: null, list: false, json: false };
  for (const raw of argv) {
    if (raw === "--heavy") a.heavy = true;
    else if (raw === "--list") a.list = true;
    else if (raw === "--json") a.json = true;
    else if (raw.startsWith("--only=")) a.only = raw.slice(7).split(",").filter(Boolean);
    else {
      console.error(`prove-checks: неизвестный аргумент ${raw} (есть --heavy, --only=…, --list, --json)`);
      process.exit(2);
    }
  }
  return a;
}

const args = parseArgs(process.argv.slice(2));

function sh(command, cwd = ROOT) {
  const r = spawnSync(command, { cwd, encoding: "utf8", shell: true, maxBuffer: 32 * 1024 * 1024 });
  return { code: r.status, out: `${r.stdout || ""}${r.stderr || ""}` };
}

function porcelain() {
  const r = spawnSync("git", ["-C", ROOT, "status", "--porcelain"], { encoding: "utf8" });
  return (r.stdout || "").split(/\r?\n/).filter(Boolean);
}

/**
 * Деревом правят два правила. До начала — чистое ли оно: грязное дерево означает
 * чужую работу, а пробник правит файлы и пишет временные, то есть в чужом дереве
 * он был бы порчей. После — вернулся ли baseline: следы проверяются на любом
 * исходе, в том числе когда шаг оказался зелёным или красным не по теме.
 */
const baseline = porcelain();
if (baseline.length && !process.env.PROVE_ALLOW_DIRTY) {
  console.error(
    `prove-checks: дерево грязно (${baseline.length} путей) — пробник правит файлы и не имеет права\n` +
      `делать это поверх чужого WIP. Сначала закоммить или уйти в чистое дерево.\n` +
      `Если это осознанно (свои правки): PROVE_ALLOW_DIRTY=1 npm run prove-checks.`,
  );
  process.exit(2);
}

if (args.list) {
  for (const p of PROBES) console.log(`${p.step.padEnd(28)} ${p.heavy ? "heavy " : "      "}${p.note}`);
  for (const [name, why] of Object.entries(EXEMPT)) console.log(`${name.padEnd(28)} exempt ${why}`);
  process.exit(0);
}

const backups = new Map();
const created = [];
const touched = new Map();

function apply(probe) {
  for (const w of probe.write || []) {
    const path = join(ROOT, w.path);
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, w.content);
    created.push(path);
  }
  for (const m of probe.mutate || []) {
    const path = join(ROOT, m.path);
    const original = readFileSync(path, "utf8");
    backups.set(path, original);
    const next = m.from === undefined ? m.to : original.replace(m.from, m.to);
    if (next === original) throw new Error(`мутация не применилась: в ${m.path} нет куска «${m.from}»`);
    writeFileSync(path, next);
  }
  for (const t of probe.touch || []) {
    const path = join(ROOT, t.path);
    const st = statSync(path);
    touched.set(path, { atime: st.atime, mtime: st.mtime });
    utimesSync(path, t.mtime, t.mtime);
  }
}

function rollback() {
  for (const [path, text] of backups) writeFileSync(path, text);
  backups.clear();
  for (const path of created) {
    if (existsSync(path)) unlinkSync(path);
  }
  created.length = 0;
  for (const [path, times] of touched) utimesSync(path, times.atime, times.mtime);
  touched.clear();
}

function runProbe(probe) {
  if (probe.skip_if_absent && !existsSync(join(ROOT, probe.skip_if_absent))) {
    return { step: probe.step, status: "skip", detail: probe.skip_reason };
  }
  try {
    apply(probe);
  } catch (e) {
    rollback();
    return { step: probe.step, status: "error", detail: e.message };
  }
  const gate = `node scripts/gate.mjs --only=${probe.step}${probe.args ? ` ${probe.args}` : ""}`;
  const { code, out } = sh(gate);
  rollback();
  const tail = out.trim().split(/\r?\n/).slice(-1)[0] || "";
  const verdict = (() => {
    if (code === 0)
      return {
        status: "red-не-доказан",
        detail: `шаг зелёный при внесённом нарушении (${probe.note}) — проверка ничего не ловит: ${tail}`,
      };
    if (!probe.expect.test(out))
      return {
        status: "red-чужой",
        detail: `шаг красный, но не по теме пробника (${probe.note}); ждали /${probe.expect}/: ${tail}`,
      };
    return { status: "ok", detail: `упал как надо (${probe.note}) — ${tail.slice(0, 160)}` };
  })();
  // Следы ищем при любом исходе: откат обязан сработать и на красном не по теме,
  // иначе пробник оставляет в дереве мусор, который потом уедет в коммит.
  const residue = porcelain().filter((l) => !baseline.includes(l));
  if (residue.length) {
    return {
      step: probe.step,
      status: "следы",
      detail: `после отката остались пути: ${residue.join(", ")} (исход пробника: ${verdict.status})`,
    };
  }
  return { step: probe.step, note: probe.note, ...verdict };
}

const selected = PROBES.filter((p) => (args.only ? args.only.includes(p.step) : args.heavy || !p.heavy));
const results = [];
for (const probe of selected) {
  process.stderr.write(`▸ ${probe.step} … `);
  const r = runProbe(probe);
  process.stderr.write(`${r.status}\n`);
  results.push(r);
}

const failed = results.filter((r) => r.status !== "ok");
// Дата локальная, а не UTC: ночная волна называется по числу на экране, и
// запись «2026-11-02» для прогона в 02:47 выглядела бы как вчерашняя.
const today = new Date().toLocaleDateString("sv-SE");

// Журнал доказанности — отслеживаемый файл: `gate --strict` сверяет с ним, что
// у каждого локального шага есть подтверждённый красный ход (критерий г #357).
// Запись дополняется, а не перезаписывается: частичные прогоны --only=… не
// должны стирать уже доказанное.
const record = existsSync(RECORD) ? JSON.parse(readFileSync(RECORD, "utf8")) : { steps: {}, exempt: {} };
record.exempt = EXEMPT;
// Команда прогона входит в запись: «prove-checks backend-tests» без --only/--heavy
// не воспроизводит то, что реально выполнялось (тяжёлые шаги идут отдельным
// вызовом, и это видно только из команды).
const runCommand = args.only
  ? `npm run prove-checks -- --only=${args.only.join(",")}${args.heavy ? " --heavy" : ""}`
  : `npm run prove-checks${args.heavy ? " -- --heavy" : ""} (полный прогон)`;
for (const r of results) {
  if (r.status !== "ok") continue;
  record.steps[r.step] = { proven_at: today, note: r.note, how: runCommand };
}
record.updated = today;
writeFileSync(RECORD, JSON.stringify(record, null, 2) + "\n");

if (args.json) {
  console.log(JSON.stringify({ proven_at: today, results, exempt: EXEMPT }, null, 2));
} else {
  for (const r of results) {
    console.log(`  ${{ ok: "✓", skip: "·", error: "✗", "red-не-доказан": "✗", "red-чужой": "⚠", следы: "✗" }[r.status] || "?"} ${r.step.padEnd(26)} ${r.status} — ${r.detail}`);
  }
  console.log(
    failed.length
      ? `итог: ${failed.length} из ${results.length} пробников не доказали красный ход — см. строки выше`
      : `итог: ${results.length} пробников прошли (красный ход каждого подтверждён)`,
  );
}

process.exitCode = failed.length ? 1 : 0;
