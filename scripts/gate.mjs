#!/usr/bin/env node
// Единая точка входа локальной проверки: тот же набор, что гоняет CI (#351).
//
// Три яруса, восходя по стоимости:
//   gate:fast  — то, что обязаны проходить до коммита (бюджет ≤ 60 с)
//   gate       — fast + тесты (юниты backend и frontend)
//   gate:e2e   — Playwright smoke (отдельно: берёт слот семафора и свой стенд)
//
// Шаг, которого нет локально, печатается как `missing` с указанием, живёт ли он
// уже в CI, — молча опущенных проверок гейт не делает (#351, критерий д).
// В CI тот же вызов обязан идти с `--strict`: недоступный шаг красный.

import { spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { buildStepCommand } from "./gate-command-core.js";
import { checkProofCoverage, summarize } from "./proof-coverage-core.mjs";
import { resolvePython } from "./python-core.js";

const ROOT = dirname(dirname(fileURLToPath(import.meta.url)));
/**
 * Шаги `pins`, `seeds-validate`, `profile-settings-manifest` и `compose-audit`
 * зовут `python`. В смешанной сессии первым в PATH оказывается интерпретатор
 * соседнего проекта, и гейт краснел на зелёном дереве (T-384) — поэтому здесь
 * один раз резолвится `backend/.venv` проекта, а PATH остаётся запасным путём.
 */
const PYTHON = resolvePython({ root: ROOT });
const GATES_SHEET = "docs/quality/gates.md";
const PROVEN_SHEET = "docs/quality/proven-checks.json";
const GATES_BLOCK = /<!-- gates-steps:start -->([\s\S]*?)<!-- gates-steps:end -->/;

/** Поле `ci` — workflow, в котором шаг уже есть; `null` — в CI шага нет, причина записана комментарием рядом со шагом. */
const STEPS = [
  {
    name: "pins",
    tier: "fast",
    check: checkPins,
    // `ci: null`: в CI версия ставится из тех же pin-файлов (`node-version-file`
    // из `.nvmrc`, `.python-version`), поэтому шаг сравнивал бы файл с самим
    // собой. Смысл — поймать локальную машину, где PATH разошёлся с пином.
    ci: null,
    what: " фактические версии языков против pin-файлов",
  },
  {
    name: "registry",
    tier: "fast",
    command: "node scripts/check-registry.mjs",
    ci: "ci-lint.yml",
    what: " реестр инструментов против схем и закреплений",
  },
  {
    name: "freshness",
    tier: "fast",
    command: "node scripts/freshness.js",
    honorsStrict: true,
    ci: "freshness.yml",
    what: " как давно смотрели в пины реестра (локально; версии апстрима — только с --online)",
  },
  {
    name: "codegraph-age",
    tier: "fast",
    command: "node scripts/codegraph-age.mjs",
    honorsStrict: true,
    // `ci: null`: индекс `.codegraph` — локальный артефакт (codegraph из mise),
    // в CI его не строят; возраст индекса важен только на машине агента.
    ci: null,
    what: " возраст codegraph-индекса против HEAD",
  },
  {
    name: "docs-links",
    tier: "fast",
    command: "npm run check:docs",
    ci: "docs.yml",
    what: " битые ссылки и карды документации",
  },
  {
    name: "adr-index",
    tier: "fast",
    command: "npm run check:adr",
    ci: "docs.yml",
    what: " номера ADR уникальны, у каждого — Дата и Статус",
  },
  {
    name: "docs-lint",
    tier: "fast",
    // Скан всего дерева, а не staged-файлов: прогон 58 мс (2026-11-20), поэтому
    // дешевле проверять корпус целиком, чем зависеть от того, что попало в индекс.
    // `ci: null` честно: rumdl ставится через mise, а CI пока не переведён на mise
    // (шаг 3 плана #391) — шаг живёт в локальном гейте и pre-push.
    command: "rumdl check .",
    tool: "rumdl",
    ci: null,
    what: " структурные дефекты Markdown (fences без языка, списки, заголовки) и битые относительные ссылки",
  },
  {
    name: "scripts-tests",
    tier: "fast",
    command: "npm run test:scripts",
    ci: "docs.yml",
    what: " юнит-тесты node-скриптов корня",
  },
  {
    name: "labels-check",
    tier: "fast",
    command: "npm run gen:labels:check",
    cwd: "backend",
    ci: "migrations.yml",
    what: " сгенерированные подписи фронта сверены с бэкендом",
  },
  {
    name: "seeds-validate",
    tier: "fast",
    command: "python scripts/validate_seeds.py",
    cwd: "backend",
    tool: "python",
    ci: "migrations.yml",
    what: " сиды справочников внутренне непротиворечивы",
  },
  {
    name: "profile-settings-manifest",
    tier: "fast",
    command: "python scripts/verify-profile-settings.py verify --strict",
    tool: "python",
    ci: "migrations.yml",
    what: " манифест профилей настроек совпадает с кодом",
  },
  {
    name: "compose-audit",
    tier: "fast",
    command: "python backend/scripts/audit_compose.py --strict",
    tool: "python",
    // `ci: null`: compose — локальный стенд; e2e в CI поднимается сервис-контейнерами
    // GitHub, поэтому этих файлов там никто не запускает.
    ci: null,
    what: " потолки логов, healthcheck и restart-политика во всех compose-файлах",
  },
  {
    name: "ci-lint",
    tier: "fast",
    // `--strict-exit`: политика «ноль находок», а не «ноль ошибок» — предупреждение
    // тоже красное (критерии #365, принцип датированных исключений).
    command: "jactionlint --strict-exit",
    tool: "jactionlint",
    ci: "ci-lint.yml",
    what: " workflow GitHub Actions и dependabot.yml: схемы, выражения, пины, политики",
  },
  {
    name: "osv-allowlist",
    tier: "fast",
    // Сам скан зависимостей — advisory в CI (#369): находить новую CVE может
    // любой день, и блокировать merge этим сейчас нельзя. Блокирует решение:
    // исключение без причины или с прошедшей датой пересмотра.
    command: "node scripts/osv-allowlist.mjs --check",
    ci: "deps-audit.yml",
    what: " датированные исключения аудита зависимостей (.github/osv-allowlist.json)",
  },
  {
    name: "test-hygiene",
    tier: "fast",
    command: "npm run test:hygiene",
    ci: "backend-tests.yml",
    what: " в тестах нет мёртвых импортов",
  },
  {
    name: "backend-test-count",
    tier: "fast",
    command: "node scripts/test-count.js --only=backend",
    ci: "backend-tests.yml",
    what: " pytest-набор не меньше записанного (тесты нельзя удалять молча)",
  },
  {
    name: "ruff",
    tier: "fast",
    command: "node scripts/heavy.mjs -- ruff check backend",
    tool: "ruff",
    ci: "ruff.yml",
    what: " линтер backend",
  },
  {
    name: "frontend-types",
    tier: "fast",
    command: "npm run typecheck",
    cwd: "frontend",
    ci: "frontend-tests.yml",
    what: " типы продакшн-кода фронта",
  },
  {
    name: "frontend-types-e2e",
    tier: "fast",
    command: "npm run typecheck:e2e",
    cwd: "frontend",
    file: "frontend/tsconfig.e2e.json",
    ci: "frontend-tests.yml",
    what: " типы e2e-спек (без этого шага спеки проверяются только прогоном)",
  },
  {
    name: "frontend-lint",
    tier: "fast",
    command: "npm run lint:ratchet",
    ci: "frontend-tests.yml",
    what: " ESLint: архитектурные границы FSD (ошибки) и потолок предупреждений (рэтчет)",
  },
  {
    name: "modern-web",
    tier: "full",
    command: "node scripts/modern-web.mjs",
    // `ci: null`: baseline-ратчет живёт в pre-push (фронтовый скоуп) и локальном
    // гейте; CI совещательный (harness rules §1), прогон в PR ничего не блокирует.
    ci: null,
    what: " новые legacy-паттерны веб-платформы сверх базлайна docs/quality/modern-web-baseline.json",
  },
  {
    name: "reactuse-diff",
    tier: "fast",
    command: "node scripts/reactuse-diff.mjs",
    // `ci: null`: ловит новые примитивы в диффе ветки, пока агент ещё может всё
    // поправить, — это шаг pre-push; в совещательном CI он ничего не останавливает.
    ci: null,
    what: " новые ручные примитивы (matchMedia, clipboard, observers) вместо @siberiacancode/reactuse",
  },
  {
    name: "backend-tests",
    tier: "full",
    command: "npm run test:pytest",
    ci: "backend-tests.yml",
    infra: "test-postgres",
    what: " pytest backend (создаёт свою БД)",
  },
  {
    name: "frontend-unit",
    tier: "full",
    command: "npm test -- --coverage",
    cwd: "frontend",
    ci: "frontend-tests.yml",
    what: " vitest с покрытием",
  },
  {
    name: "frontend-test-count",
    tier: "full",
    command: "node scripts/test-count.js --only=frontend",
    ci: "frontend-tests.yml",
    what: " vitest-набор не меньше записанного (минута на сбор, поэтому не в fast)",
  },
  {
    name: "frontend-build",
    tier: "full",
    // Сборка + порог в одном шаге: порог читает dist/, и без свежей сборки он
    // мерил бы вчерашний пакет. `bundle:update` — отдельная команда человека:
    // гейт порог не двигает (#364).
    command: "npm --prefix frontend run build && node scripts/bundle-size.mjs",
    ci: "frontend-tests.yml",
    what: " сборка фронта и порог начального пакета (raw + gzip из dist/index.html)",
  },
  {
    name: "dev-deps",
    tier: "full",
    command: "node scripts/check-dev-deps.js",
    honorsStrict: true,
    ci: "frontend-tests.yml",
    what: " мёртвые dev-зависимости фронтенда (зовёт git ls-files и node_modules, поэтому не в fast)",
  },
];

/**
 * Проверки, которые в CI есть, а локально не запускаются. Причина не лень:
 * `alembic upgrade head` на dev-БД меняет базу живого стенда владельца, а
 * дрейф миграций обязан проверяться на клоне стенда — за этим #379.
 * Гейт печатает каждую строкой `missing`, чтобы зелёный итог не читался как
 * «проверено всё» (#351, критерий д).
 */
const NOT_RUN = [
  {
    name: "alembic-drift",
    ci: "migrations.yml",
    reason: "накатывает миграции на dev-БД живого стенда; локально — после #379 (клон стенда)",
  },
  {
    name: "e2e-smoke",
    ci: "e2e-smoke.yml",
    reason: "берёт слот машинного семафора и свой стенд; отдельный ярус `npm run gate:e2e`",
  },
];

const E2E_STEP = {
  name: "e2e-smoke",
  tier: "e2e",
  command: "npm --prefix frontend run test:e2e:smoke -- --retries=0",
  ci: "e2e-smoke.yml",
  infra: "test-postgres",
  what: " Playwright smoke на своём клоне базы",
  // e2e-контракт: пустой CI иначе включает retries: 2 и прячет флейки.
  env: { CI: "" },
};

const INFRA = {
  "test-postgres": { container: "ktm2000-postgres-test", hint: "npm run test:db:up" },
  "dev-postgres": { container: "ktm2000-postgres", hint: "docker compose --env-file .env.dev -f infra/compose/docker-compose.dev.yml up -d" },
};

const TIER_ORDER = { fast: 0, full: 1, e2e: 2 };

function parseArgs(argv) {
  const args = { tier: "full", json: false, strict: false, only: null, keepGoing: true };
  for (const raw of argv) {
    if (raw === "--fast" || raw === "fast") args.tier = "fast";
    else if (raw === "--json") args.json = true;
    else if (raw === "--strict") args.strict = true;
    else if (raw === "--e2e" || raw === "e2e") args.tier = "e2e";
    else if (raw === "--all") args.tier = "e2e";
    else if (raw.startsWith("--only=")) args.only = raw.slice("--only=".length).split(",").filter(Boolean);
    else if (raw === "--help" || raw === "-h") args.help = true;
    else throw new Error(`Неизвестный аргумент: ${raw}`);
  }
  return args;
}

function shell(command, cwd, env) {
  const result = spawnSync(command, {
    cwd: join(ROOT, cwd || "."),
    encoding: "utf8",
    shell: true,
    env: { ...process.env, ...env },
    maxBuffer: 64 * 1024 * 1024,
  });
  const out = `${result.stdout || ""}${result.stderr || ""}`;
  return { code: result.status ?? 1, out, error: result.error };
}

/** Путь в командной строке: кавычки только там, где в пути есть пробел. */
function quotePath(path) {
  return /\s/.test(path) ? `"${path}"` : path;
}

/**
 * Команда шага, начинающаяся с `python`, идёт через интерпретатор проекта.
 * Подстановка префиксная: `npm run …` и `node …` шаги не затрагиваются, а для
 * шагов, где python зовётся внутри npm-скрипта, он резолвится там же, где
 * объявлен (например, `backend-test-count` — в `scripts/test-count.js`).
 */
function withProjectPython(command) {
  return command.replace(/^python(?=\s|$)/, quotePath(PYTHON.exe));
}

/** Чем гейт запускает python — видно в шапке, а не догадкой о PATH. */
function pythonLabel() {
  return PYTHON.source === "venv" ? "backend/.venv" : `${PYTHON.exe} (PATH)`;
}

function tail(text, lines = 15) {
  const all = text.split(/\r?\n/).filter((l) => l.trim() !== "");
  return all.slice(-lines).join("\n");
}

function git(...args) {
  const r = spawnSync("git", args, { cwd: ROOT, encoding: "utf8" });
  return r.status === 0 ? r.stdout.trim() : "";
}

function probeInfra() {
  const names = new Set(
    (shell("docker ps --format \"{{.Names}}\"", ".", {}).out || "")
      .split(/\r?\n/)
      .map((l) => l.trim())
      .filter(Boolean),
  );
  return (key) => names.has(INFRA[key].container);
}

function probeTool(step) {
  if (!step.tool) return true;
  const tool = step.tool === "python" ? quotePath(PYTHON.exe) : step.tool;
  return shell(`${tool} --version`, ".", {}).code === 0;
}

/** Версия языка живёт в pin-файле; `engines` в package.json обязан с ним совпадать. */
const PINNED = [
  { label: "node", file: ".nvmrc", command: "node -v" },
  { label: "python", file: ".python-version", command: `${quotePath(PYTHON.exe)} -V` },
];

function checkPins() {
  const seen = [];
  const bad = [];
  let nodePin = null;
  for (const pin of PINNED) {
    const path = join(ROOT, pin.file);
    if (!existsSync(path)) {
      bad.push(`${pin.file} отсутствует`);
      continue;
    }
    const want = readFileSync(path, "utf8").trim();
    const out = shell(pin.command, ".", {}).out || "";
    const actual = (/\d+\.\d+\.\d+/.exec(out) || [])[0];
    if (!actual) {
      bad.push(`${pin.label}: ${pin.command} не вернул версию`);
      continue;
    }
    if (actual !== want && !actual.startsWith(`${want}.`)) {
      bad.push(`${pin.label} ${actual}, в ${pin.file} закреплено ${want}`);
      continue;
    }
    seen.push(`${pin.label} ${actual} (${pin.file} = ${want})`);
    if (pin.label === "node") nodePin = want;
  }
  if (nodePin) {
    const engines = (JSON.parse(readFileSync(join(ROOT, "package.json"), "utf8")).engines || {}).node;
    if (!engines) {
      bad.push("package.json: engines.node нет, а .nvmrc есть — два места разъезжаются");
    } else {
      const min = (/(\d+)/.exec(engines) || [])[1];
      if (min !== nodePin) bad.push(`engines.node ${engines} против .nvmrc ${nodePin}`);
    }
  }
  return { ok: !bad.length, detail: bad.length ? bad.join("; ") : seen.join(", ") };
}

function selectSteps(tier, only) {
  const max = TIER_ORDER[tier];
  let steps = STEPS.filter((s) => TIER_ORDER[s.tier] <= max);
  if (tier === "e2e") steps = [...steps, E2E_STEP];
  if (only) steps = steps.filter((s) => only.includes(s.name));
  return steps;
}

/** Шаг обязан быть назван в листе гейтов так же, как в STEPS: расхождение красным. */
function reconcile(names) {
  const path = join(ROOT, GATES_SHEET);
  if (!existsSync(path)) {
    return { status: "not-checked", detail: `${GATES_SHEET} не найден — сверять не с чем` };
  }
  const block = GATES_BLOCK.exec(readFileSync(path, "utf8"));
  if (!block) {
    return { status: "not-checked", detail: `в ${GATES_SHEET} нет блока <!-- gates-steps:start -->` };
  }
  const listed = new Set([...block[1].matchAll(/`([a-z0-9:_-]+)`/g)].map((m) => m[1]));
  const missing = names.filter((n) => !listed.has(n));
  const extra = [...listed].filter((n) => !names.includes(n));
  if (missing.length || extra.length) {
    const parts = [];
    if (missing.length) parts.push(`в гейте, но не в листе: ${missing.join(", ")}`);
    if (extra.length) parts.push(`в листе, но не в гейте: ${extra.join(", ")}`);
    return { status: "fail", detail: parts.join("; ") };
  }
  return { status: "ok", detail: `${listed.size} шагов сверены с ${GATES_SHEET}` };
}

/**
 * У каждого локального шага обязан быть доказанный красный ход (#357): проверка,
 * которую никогда не видели падающей, может молчать годами и выглядеть защитой.
 * Покрытие ведёт `npm run prove-checks` в docs/quality/proven-checks.json; шаги,
 * которые локально не запускаются или намеренно report-only, — там же в `exempt`
 * с причиной, датой обзора и сроком.
 *
 * Исключение без срока — это «нет проверки», только записанное словами: поэтому
 * у каждой записи `reviewed`/`expires`, и просроченный `expires` краснеет при
 * любом флаге (не только в strict). Возраст обзора — warn: запись не становится
 * ложью от того, что её год не перечитывали.
 */
function proofCoverage(names, strict) {
  const path = join(ROOT, PROVEN_SHEET);
  if (!existsSync(path)) {
    return {
      status: strict ? "fail" : "not-checked",
      detail: `${PROVEN_SHEET} не найден — красным не доказан ни один шаг; прогнать npm run prove-checks`,
    };
  }
  const record = JSON.parse(readFileSync(path, "utf8"));
  const result = checkProofCoverage(record, { steps: names });
  const lines = [...result.problems, ...result.warnings.map((w) => `warn: ${w}`)];
  const detail = [summarize(result), ...(result.uncovered.length ? [`нет доказательства и нет исключения: ${result.uncovered.join(", ")}`] : []), ...lines].join("; ");

  // Сломанный журнал (формат даты, истёкший срок, исключение без причины или
  // без условия) — красное, потому что иначе бессрочное исключение снова
  // станет невидимым. Отсутствие покрытия — по флагу, как и раньше.
  if (result.problems.length) return { status: "fail", detail };
  if (result.uncovered.length) return { status: strict ? "fail" : "warn", detail };
  if (result.warnings.length) return { status: "warn", detail };
  return { status: "ok", detail };
}

function runStep(step, infraUp, strict) {  if (step.check) {
    const started = Date.now();
    const { ok, detail } = step.check();
    const seconds = (Date.now() - started) / 1000;
    return ok
      ? { status: "ok", seconds, reason: detail }
      : { status: "fail", seconds, reason: detail };
  }
  if (step.file && !existsSync(join(ROOT, step.file))) {
    return { status: "missing", seconds: 0, reason: `нет ${step.file}` };
  }
  if (step.infra && !infraUp(step.infra)) {
    return {
      status: "missing",
      seconds: 0,
      reason: `нет ${INFRA[step.infra].container}; поднять: ${INFRA[step.infra].hint}`,
    };
  }
  if (!probeTool(step)) {
    return { status: "missing", seconds: 0, reason: `${step.tool} не установлен локально` };
  }
  const started = Date.now();
  const command = withProjectPython(buildStepCommand(step, strict));
  const { code, out, error } = shell(command, step.cwd, step.env || {});
  const seconds = (Date.now() - started) / 1000;
  if (error) return { status: "fail", seconds, reason: String(error.message), output: tail(out) };
  return code === 0
    ? { status: "ok", seconds }
    : { status: "fail", seconds, reason: `код ${code}`, output: tail(out) };
}

function ciPresence(step) {
  if (!step.ci) return "нет и в CI";
  const file = join(ROOT, ".github", "workflows", step.ci);
  return existsSync(file) ? `есть в CI: ${step.ci}` : `${step.ci} ещё не в репозитории`;
}

function main() {
  let args;
  try {
    args = parseArgs(process.argv.slice(2));
  } catch (error) {
    console.error(String(error.message));
    return 2;
  }
  if (args.help) {
    console.log(
      [
        "npm run gate          — fast + тесты",
        "npm run gate:fast     — только быстрая часть (бюджет ≤ 60 с)",
        "npm run gate:e2e      — добавить Playwright smoke",
        "",
        "  --json     машиночитаемый тайминг (источник метрики M1)",
        "  --strict   недоступный локально шаг красный; обязателен в CI",
        "  --only=a,b прогнать выбранные шаги",
      ].join("\n"),
    );
    return 0;
  }

  const tier = args.tier;
  const steps = selectSteps(tier, args.only);
  const infraUp = probeInfra();
  const results = [];
  for (const step of steps) {
    const r = runStep(step, infraUp, args.strict);
    results.push({ ...r, name: step.name, what: step.what.trim(), ci: step.ci ? ciPresence(step) : null });
    if (r.status === "fail" && !args.keepGoing) break;
  }
  // Карта гейтов — полный набор проверок, а не набор выбранного яруса: иначе
  // `gate:fast` краснел бы на том, что в full-ярусе, и vice versa. Выборочный
  // прогон --only не сверяется: он по построению не полный.
  const allNames = [...new Set([...STEPS.map((s) => s.name), ...NOT_RUN.map((s) => s.name)])];
  const skipped = {
    status: "not-checked",
    detail: `--only=${args.only ? args.only.join(",") : "?"} — карта и покрытие сверяются только на полном прогоне`,
  };
  const reconciliation = args.only ? skipped : reconcile(allNames);
  const coverage = args.only ? skipped : proofCoverage(allNames, args.strict);
  const notRun = NOT_RUN.map((s) => ({ ...s, ci: ciPresence(s) }));
  const seconds = results.reduce((sum, r) => sum + r.seconds, 0);
  const counts = {
    ok: results.filter((r) => r.status === "ok").length,
    fail: results.filter((r) => r.status === "fail").length,
    missing: results.filter((r) => r.status === "missing").length,
  };
  if (reconciliation.status === "fail") counts.fail += 1;
  if (coverage.status === "fail") counts.fail += 1;
  const notCovered = results.filter((r) => r.status === "missing").length;

  if (args.json) {
    console.log(
      JSON.stringify(
        {
          generated_at: new Date().toISOString(),
          sha: git("rev-parse", "HEAD"),
          branch: git("rev-parse", "--abbrev-ref", "HEAD"),
          node: process.version,
          tier,
          strict: args.strict,
          steps: results,
          not_run: notRun,
          reconcile: reconciliation,
          proof_coverage: coverage,
          totals: { ...counts, steps: results.length, seconds: Number(seconds.toFixed(2)) },
          local_coverage: `${results.length - notCovered}/${results.length} шагов реально проверено локально`,
        },
        null,
        2,
      ),
    );
  } else {
    console.log(
      `gate — ярус ${tier} — ${git("rev-parse", "--short", "HEAD")} — node ${process.version} — python ${pythonLabel()}`,
    );
    for (const r of results) {
      const line = `${r.name.padEnd(28)} ${(r.seconds ?? 0).toFixed(1).padStart(6)}  ${r.status}`;
      console.log(r.reason ? `${line} — ${r.reason}` : line);
      if (r.output) console.log(r.output.split("\n").map((l) => `      ${l}`).join("\n"));
    }
    for (const r of notRun) {
      console.log(`${r.name.padEnd(28)} ${"      "}  not-run — ${r.reason} (${r.ci})`);
    }
    const rec = `${"reconcile".padEnd(28)} ${"      "}  ${reconciliation.status} — ${reconciliation.detail}`;
    console.log(rec);
    console.log(
      `${"prove-coverage".padEnd(28)} ${"      "}  ${coverage.status} — ${coverage.detail}`,
    );
    console.log(
      `итог: ${results.length} шагов, ${counts.ok} ok, ${counts.fail} fail, ${counts.missing} missing — ${seconds.toFixed(1)} с`,
    );
    if (counts.missing) {
      const who = results.filter((r) => r.status === "missing").map((r) => `${r.name} (${r.ci ?? "нет и в CI"})`);
      console.log(`НЕ ПРОВЕРЕНО локально, шаг существует: ${who.join("; ")}`);
      console.log("Без этих проверок зелёный гейт — не «всё как в CI»; в CI зовите `npm run gate -- --strict`.");
    }
  }

  if (counts.fail) return 1;
  if (args.strict && counts.missing) return 1;
  return 0;
}

process.exitCode = main();
