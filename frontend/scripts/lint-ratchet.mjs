/**
 * Трещотка предупреждений ESLint (issue #372).
 *
 * ## Зачем
 * `eslint . --max-warnings=0` на этом дереве красная уже сегодня: замер
 * 2026-11-03 — 48 предупреждений `react-hooks/exhaustive-deps` при 0 ошибок.
 * Ставить в CI ноль нельзя (он валит всё дерево), а без гейта число
 * предупреждений растёт незаметно. Поэтому потолок = текущее число, и
 * двигаться он может только вниз: рост красит прогон.
 *
 * ## Как работает
 * 1. Запускает локальный ESLint с `--format=json` (тот же конфиг и та же
 *    область, что у `npm run lint`).
 * 2. Считает предупреждения — всего и по каждому правилу.
 * 3. Сверяет с `frontend/eslint-warnings-baseline.json`:
 *    — превышение по правилу → красный (ловит и «перераспределение», когда
 *      одно исправили, другое добавили, а итог не изменился);
 *    — превышение общего числа → красный (отдельное сообщение);
 *    — уменьшение → зелёный плюс подсказка подтянуть потолок.
 * 4. Ошибки (`errorCount > 0`) и падение самого ESLint (код 2 — фатальная
 *    ошибка конфига/парсинга) тоже красные: гейт не должен «позеленеть» на
 *    несуществующей проверке.
 *
 * ## Почему потолок только вниз
 * `--update` переписывает базовый файл текущими цифрами, но рост потолка
 * требует `--force`: поднимать потолок — решение человека, оно должно попасть
 * в diff и в ревью, а не в лог прогона.
 *
 * ## Конечная цель
 * `npm run lint:strict` (`--max-warnings=0`) остаётся как «идеал»: когда
 * трещотка дойдёт до нуля, `lint:strict` станет обычным шагом CI, а базовый
 * файл станет не нужен.
 *
 * ## Тестируемость
 * `main(argv, deps)` принимает подменяемые `runEslint` и `baselineFile`, чтобы
 * тесты проверяли коды выхода без реального прогона линтера (он ~40 с).
 */
import { spawnSync } from "node:child_process";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND = path.resolve(HERE, "..");
/** Экспортирован: тестам и сообщению об ошибке нужен путь к потолку. */
export const BASELINE_PATH = path.join(FRONTEND, "eslint-warnings-baseline.json");
const ESLINT_BIN = path.join(FRONTEND, "node_modules", "eslint", "bin", "eslint.js");

/**
 * Запись базового файла (потолок предупреждений).
 *
 * @typedef {object} Baseline
 * @property {string} [measuredAt] дата замера (ISO, день)
 * @property {string} [command] чем меряли
 * @property {string} [eslintVersion] версия ESLint на момент замера
 * @property {number} total потолок предупреждений всего
 * @property {Record<string, number>} byRule потолок по правилу
 */

/**
 * @typedef {object} Counts
 * @property {number} total предупреждений
 * @property {Record<string, number>} byRule предупреждений по правилу
 * @property {number} errors ошибок (их трещотка не «потолком» не лечит)
 */

/**
 * @typedef {object} Diff
 * @property {string[]} problems что именно нарушает трещотку
 * @property {string[]} improvements где стало лучше (можно подтянуть потолок)
 * @property {boolean} ok нет ли проблем
 */

/**
 * Считает предупреждения по JSON-результату ESLint.
 *
 * @param {Array<{errorCount?: number, warningCount?: number, messages?: Array<{severity?: number, ruleId?: string|null}>}>} results
 * @returns {Counts}
 */
export function countWarnings(results) {
  let total = 0;
  let errors = 0;
  /** @type {Record<string, number>} */
  const byRule = {};
  for (const file of results) {
    errors += file.errorCount ?? 0;
    total += file.warningCount ?? 0;
    for (const message of file.messages ?? []) {
      if (message.severity !== 1) continue;
      const rule = message.ruleId ?? "(без правила)";
      byRule[rule] = (byRule[rule] ?? 0) + 1;
    }
  }
  return { total, byRule, errors };
}

/**
 * Сверяет текущие предупреждения с потолком.
 *
 * Проверка по правилам сильнее проверки по сумме: если каждое правило не
 * превысило свой потолок, то и сумма не может его превысить. Проверка суммы
 * оставлена ради понятного сообщения и на случай неполного `byRule` в
 * базовом файле.
 *
 * @param {Baseline} baseline
 * @param {Counts} current
 * @returns {Diff}
 */
export function compare(baseline, current) {
  /** @type {string[]} */
  const problems = [];
  /** @type {string[]} */
  const improvements = [];
  const capTotal = baseline.total ?? 0;

  if (current.errors > 0) {
    problems.push(
      `ошибок ESLint: ${current.errors} — трещотка их не узаконивает, их чинят правкой кода`,
    );
  }

  const baselineRules = baseline.byRule ?? {};
  const rules = [
    ...new Set([...Object.keys(baselineRules), ...Object.keys(current.byRule)]),
  ].sort();
  for (const rule of rules) {
    const cap = baselineRules[rule] ?? 0;
    const now = current.byRule[rule] ?? 0;
    if (now > cap) {
      problems.push(
        cap === 0
          ? `${rule}: ${now} предупреждений при потолке 0 — правило новое (или его потолок был обнулён)`
          : `${rule}: было ${cap}, стало ${now} (+${now - cap})`,
      );
    } else if (now < cap) {
      improvements.push(`${rule}: ${cap} → ${now} (${now - cap})`);
    }
  }

  if (current.total > capTotal) {
    problems.push(`всего предупреждений ${current.total} > потолка ${capTotal}`);
  } else if (current.total < capTotal) {
    improvements.push(
      `всего предупреждений ${current.total} < потолка ${capTotal} — потолок можно подтянуть вниз`,
    );
  }

  return { problems, improvements, ok: problems.length === 0 };
}

/**
 * Понятный человеку отчёт: числа до/после, а не «проверка упала».
 *
 * @param {Baseline} baseline
 * @param {Counts} current
 * @param {Diff} diff
 * @param {{files: number}} meta
 * @returns {string}
 */
export function renderReport(baseline, current, diff, meta) {
  const lines = [
    `ESLint: файлов ${meta.files}, ошибок ${current.errors}, предупреждений ${current.total} (потолок ${baseline.total})`,
  ];
  for (const rule of Object.keys(current.byRule).sort()) {
    lines.push(
      `  ${rule}: ${current.byRule[rule]} (потолок ${baseline.byRule?.[rule] ?? 0})`,
    );
  }
  for (const problem of diff.problems) lines.push(`  ✗ ${problem}`);
  for (const improvement of diff.improvements) lines.push(`  ✓ ${improvement}`);
  if (diff.ok && diff.improvements.length > 0) {
    lines.push("Трещотку можно подтянуть: npm run lint:ratchet -- --update");
  }
  if (!diff.ok) {
    lines.push(
      "Исправляй добавленное, а не поднимай потолок. Рост потолка — только явно: npm run lint:ratchet -- --update --force (он попадёт в diff и в ревью).",
    );
  }
  return lines.join("\n");
}

/**
 * Прогон локального ESLint с JSON-отчётом.
 *
 * @param {string[]} targets что линтеруем (по умолчанию `.`, то есть та же
 *   область, что у `npm run lint`)
 * @returns {{status: number|null, stdout: string, stderr: string, spawnError?: Error}}
 */
export function runEslint(targets) {
  if (!existsSync(ESLINT_BIN)) {
    return {
      status: null,
      stdout: "",
      stderr: `Не найден локальный ESLint: ${ESLINT_BIN}. Нужен \`npm ci --prefix frontend\` в этом дереве.`,
      spawnError: new Error("локальный ESLint не установлен"),
    };
  }
  const run = spawnSync(
    process.execPath,
    [ESLINT_BIN, ...targets, "--format=json"],
    {
      cwd: FRONTEND,
      encoding: "utf8",
      maxBuffer: 64 * 1024 * 1024,
    },
  );
  return {
    status: run.status,
    stdout: run.stdout ?? "",
    stderr: run.stderr ?? "",
    spawnError: run.error,
  };
}

/**
 * @param {string[]} argv
 * @param {{runEslint?: (targets: string[]) => {status: number|null, stdout: string, stderr: string, spawnError?: Error}, baselineFile?: string, log?: (text: string) => void, error?: (text: string) => void, eslintVersion?: string}} [deps]
 * @returns {Promise<number>} код выхода: 0 зелёный, 1 регресс, 2 сломанная проверка
 */
export async function main(argv, deps = {}) {
  const runEslintImpl = deps.runEslint ?? runEslint;
  const baselineFile = deps.baselineFile ?? BASELINE_PATH;
  const log = deps.log ?? ((text) => console.log(text));
  const fail = deps.error ?? ((text) => console.error(text));

  const update = argv.includes("--update");
  const force = argv.includes("--force");
  const targets = argv.filter(
    (arg) => arg !== "--update" && arg !== "--force",
  );
  const args = targets.length ? targets : ["."];

  const run = runEslintImpl(args);
  if (run.spawnError) {
    fail(`ESLint не запустился: ${run.stderr || run.spawnError.message}`);
    return 2;
  }
  if (run.status === 2) {
    // Фатальная ошибка: битый конфиг, нечитаемый файл и т.п. Считать это
    // «нулём предупреждений» нельзя — гейт позеленел бы на пустом месте.
    fail(
      `ESLint упал фатально (код 2), отчёт не читается:\n${(run.stderr || run.stdout || "").trim().slice(0, 4000)}`,
    );
    return 2;
  }

  /** @type {any[]} */
  let results;
  try {
    results = JSON.parse(run.stdout || "[]");
  } catch (error) {
    fail(`Не удалось разобрать JSON-отчёт ESLint: ${error.message}`);
    return 2;
  }
  const current = countWarnings(results);

  if (results.length === 0) {
    // Пустой отчёт = линтер ничего не проверил. Молча «зелено» в таком случае
    // быть не должно: гейт превратился бы в фиктиву (тот же класс ошибки,
    // что и `tsc` без `-p`).
    fail(
      "ESLint не вернул ни одного файла — проверка не работает, результат нечитаем",
    );
    return 2;
  }

  if (!existsSync(baselineFile)) {
    fail(
      `Нет базового файла ${baselineFile}. Первый замер: npm run lint:ratchet -- --update`,
    );
    return 2;
  }
  /** @type {Baseline} */
  let baseline;
  try {
    baseline = JSON.parse(readFileSync(baselineFile, "utf8"));
  } catch (error) {
    fail(`Базовый файл ${baselineFile} не читается как JSON: ${error.message}`);
    return 2;
  }

  if (update) {
    const capTotal = baseline.total ?? 0;
    const capRules = baseline.byRule ?? {};
    const grows =
      current.total > capTotal ||
      Object.entries(current.byRule).some(
        ([rule, now]) => now > (capRules[rule] ?? 0),
      );
    if (grows && !force) {
      fail(
        `--update отказался: сейчас ${current.total}, потолок ${capTotal} — это регресс, а не новая норма. Сначала исправь код; если рост осознанный — \`--update --force\`.`,
      );
      return 1;
    }
    const next = {
      measuredAt: new Date().toISOString().slice(0, 10),
      command: "node scripts/lint-ratchet.mjs --update",
      eslintVersion:
        deps.eslintVersion ??
        JSON.parse(
          readFileSync(
            path.join(FRONTEND, "node_modules/eslint/package.json"),
            "utf8",
          ),
        ).version,
      total: current.total,
      byRule: Object.fromEntries(
        Object.keys(current.byRule)
          .sort()
          .map((rule) => [rule, current.byRule[rule]]),
      ),
    };
    writeFileSync(
      baselineFile,
      `${JSON.stringify(next, null, 2)}\n`,
      "utf8",
    );
    log(`Потолок записан: ${capTotal} → ${next.total} (${baselineFile})`);
    return 0;
  }

  const diff = compare(baseline, current);
  log(renderReport(baseline, current, diff, { files: results.length }));
  return diff.ok ? 0 : 1;
}

// Экспорт ради тестов не должен запускать прогон линтера.
if (
  process.argv[1] &&
  path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)
) {
  process.exitCode = await main(process.argv.slice(2));
}
