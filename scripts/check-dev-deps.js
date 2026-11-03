/**
 * Мёртвые dev-зависимости фронтенда: назван ли каждый devDependency где-нибудь
 * в отслеживаемых файлах — по имени пакета или по имени его бинарника.
 *
 * Запуск: `npm run check:dev-deps` или `node scripts/check-dev-deps.js`.
 * По умолчанию **report-only** (код 0 при находках) — датированное исключение
 * от правила «блокирует, а не советует»: с 2026-11-03, пересмотр до
 * 2027-05-01 (`docs/quality/criteria.md`, п. 1). Причина: проверка появилась
 * позже своей посылки и первым делом обязана показать список, а не краснить
 * всех. В гейте шаг `dev-deps` идёт в ярусе `full` и краснеет с `--strict` —
 * тогда «мёртвый» пакет нужно либо удалить, либо объяснить в датированном
 * исключении. CI по условию #374 зовёт report-only: пока исключение не
 * пересмотрено, job печатает находки, но не краснеет.
 *
 * Исключения — `docs/quality/dev-deps-allowlist.json`: у каждой записи причина
 * и `reviewBy`. Без даты запись сама становится находкой (#386).
 *
 * Почему нельзя было просто grep'ом (#374). Посылка тикета — «`jest-dom` мёртв,
 * проверено grep'ом» — оказалась неверной: `frontend/vitest.config.ts` подключает
 * его через `setupFiles: ["@testing-library/jest-dom/vitest"]`, то есть пакет
 * зовётся с подпутём, а не «голым» именем. Тот же класс: `typescript` зовут как
 * `tsc`, `@vitest/coverage-v8` зовут как `provider: "v8"`. Отсюда и правила:
 * ищем имя пакета И его бинарники, а всё, что не видно ни так, ни эдак, —
 * находка со списком просмотренных файлов, а не тихое удаление.
 */

"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { execFileSync } = require("node:child_process");

const {
  inspectDevDependencies,
  isCodeFile,
  withoutComments,
  withoutDependencyDeclarations,
} = require("./check-dev-deps-core");
const { plural } = require("./format-utils");

const FRONTEND = "frontend";
const ALLOWLIST_FILE = path.join("docs", "quality", "dev-deps-allowlist.json");

/**
 * Где искать devDependencies. Фронтенд — свой манифест; корень — общий
 * оркестратор (границы #374 прямо называют его devDependencies), но корневой
 * скан не должен считать использованием упоминание в чужом пакете или доке:
 * `frontend/`, `backend/`, `docs/` и данные исключены.
 */
const SOURCES = [
  { name: FRONTEND, base: FRONTEND, manifest: path.join(FRONTEND, "package.json"), paths: [FRONTEND], exclude: [] },
  {
    name: "root",
    base: ".",
    manifest: "package.json",
    paths: [],
    exclude: [
      "frontend/",
      "backend/",
      "docs/",
      "data/",
      "excel/",
      "infra/",
      "storage/",
      "logs/",
      ".qoder/",
      // Самопроверка не доказывает использование: в тестах имена пакетов —
      // фикстуры, в реестре — запись инструмента, а не вызов.
      "tools.json",
      "scripts/check-dev-deps",
    ],
  },
];

const USAGE = `check-dev-deps.js — мёртвые dev-зависимости фронтенда

  node scripts/check-dev-deps.js            report-only: список находок, код 0
  node scripts/check-dev-deps.js --strict   находки = код 1 (так зовёт гейт)
  node scripts/check-dev-deps.js --json     вывод машиной (для гейта и пробников)
  node scripts/check-dev-deps.js --help     эта справка

Исключения — ${ALLOWLIST_FILE.replaceAll("\\", "/")} (причина + reviewBy).
Удаление пакета — только руками и только после зелёного полного vitest.`;

function readAllowlist(repoRoot) {
  const file = path.join(repoRoot, ALLOWLIST_FILE);
  if (!fs.existsSync(file)) {
    return { adopted: "файл не создан", exempt: {} };
  }
  const raw = JSON.parse(fs.readFileSync(file, "utf8"));
  if (!raw || typeof raw !== "object" || !raw.exempt || typeof raw.exempt !== "object") {
    throw new Error(`${ALLOWLIST_FILE}: ожидается объект с полем "exempt"`);
  }
  return raw;
}

/**
 * Отслеживаемые git файлы источника: путь и содержимое без деклараций
 * зависимостей (см. `withoutDependencyDeclarations` в core).
 *
 * В скан попадают только код и конфиги (`isCodeFile`): упоминание пакета в
 * Markdown — это проза, а не использование. `package-lock.json` исключён
 * отдельно: в нём каждое имя есть по определению.
 */
function readTrackedFiles(repoRoot, source) {
  const list = execFileSync("git", ["-C", repoRoot, "ls-files", "-z", ...source.paths], {
    encoding: "buffer",
  })
    .toString("utf8")
    .split("\0")
    .filter(Boolean);

  const files = [];
  for (const rel of list) {
    const normalized = rel.replaceAll("\\", "/");
    if (normalized.endsWith("package-lock.json") || !isCodeFile(normalized)) continue;
    if (source.exclude.some((prefix) => normalized.startsWith(prefix))) continue;
    const abs = path.join(repoRoot, rel);
    let stat;
    try {
      stat = fs.statSync(abs);
    } catch {
      continue; // индекс опережает рабочее дерево (файл удалён не нами)
    }
    if (stat.size > 512_000) continue;
    let text;
    try {
      text = fs.readFileSync(abs, "utf8");
    } catch {
      continue;
    }
    files.push({
      path: normalized,
      // Строка в `devDependencies` — это объявление, а не использование: без
      // удаления деклараций каждый пакет был бы «упомянут» в собственном
      // манифесте, и проверка всегда выдавала «всё живо».
      text: withoutDependencyDeclarations(
        // Корневые скрипты объясняют инструменты в комментариях; такие имена
        // — не вызов. У фронтенда есть магические комментарии, которые
        // являются использованием, поэтому там комментарии сохраняются.
        source.name === "root" ? withoutComments(text, normalized) : text,
      ),
    });
  }
  return files;
}

/**
 * Бинарники пакета из установленного `package.json` (`bin`).
 *
 * Поле бывает строкой (`"bin": "cli.js"`) и объектом; имя бинарника обычно
 * совпадает с пакетом, но `typescript` даёт `tsc` и `tsserver` — именно их видно
 * в scripts. Неустановленный пакет (нет `node_modules`) даёт []: проверка тогда
 * ищет только по имени, и честный вывод — в находке, а не в «всё чисто».
 */
function readBins(repoRoot, base, name) {
  const file = path.join(repoRoot, base, "node_modules", name, "package.json");
  let raw;
  try {
    raw = JSON.parse(fs.readFileSync(file, "utf8"));
  } catch {
    return [];
  }
  if (!raw.bin) return [];
  if (typeof raw.bin === "string") return [path.basename(raw.bin)];
  return Object.keys(raw.bin);
}

function main(argv, env = {}) {
  const args = argv.slice(2);
  if (args.includes("--help") || args.includes("-h")) {
    console.log(USAGE);
    return 0;
  }
  const repoRoot = path.resolve(__dirname, "..");

  let allowlist;
  try {
    allowlist = readAllowlist(repoRoot);
  } catch (error) {
    console.error(`не удалось прочитать исключения: ${error.message}`);
    return 2;
  }

  const packages = [];
  const files = [];
  const sources = [];
  for (const source of SOURCES) {
    const manifestFile = path.join(repoRoot, source.manifest);
    if (!fs.existsSync(manifestFile)) {
      console.error(`${source.manifest} не найден — запуск из корня репозитория?`);
      return 2;
    }
    const pkg = JSON.parse(fs.readFileSync(manifestFile, "utf8"));
    const devNames = Object.keys(pkg.devDependencies ?? {});
    packages.push(
      ...devNames.map((name) => ({
        name,
        source: source.name,
        bins: readBins(repoRoot, source.base, name),
      })),
    );
    const sourceFiles = readTrackedFiles(repoRoot, source);
    files.push(...sourceFiles);
    sources.push({ name: source.name, checked: devNames.length, scanned: sourceFiles.length });
  }

  const findings = inspectDevDependencies({
    packages,
    files,
    allowlist,
    now: env.KTM_DEV_DEPS_TODAY || undefined,
  });

  if (args.includes("--json")) {
    console.log(
      JSON.stringify(
        { checked: packages.length, scanned: files.length, sources, findings },
        null,
        2,
      ),
    );
  } else if (findings.length === 0) {
    const bySource = sources
      .map(
        (source) =>
          `${source.name}: ${source.checked} ${plural(source.checked, "пакет", "пакета", "пакетов")}`,
      )
      .join(", ");
    console.log(
      `dev-зависимости: ${packages.length} ${plural(packages.length, "пакет", "пакета", "пакетов")} ` +
        `(${bySource}) — каждый назван в коде или конфиге (просмотрено ${files.length} ` +
        `${plural(files.length, "файл", "файла", "файлов")}, исключений: ` +
        `${Object.keys(allowlist.exempt).length})`,
    );
  } else {
    for (const finding of findings) {
      console.log(`✗ ${finding.code}: ${finding.name} — ${finding.message}`);
    }
    console.log(
      `итог: ${findings.length} ${plural(findings.length, "находка", "находки", "находок")} ` +
        `в ${packages.length} ${plural(packages.length, "пакете", "пакетах", "пакетах")} ` +
        `(исключения — ${ALLOWLIST_FILE.replaceAll("\\", "/")})`,
    );
  }

  if (args.includes("--strict") && findings.length > 0) return 1;
  return 0;
}

if (require.main === module) {
  process.exitCode = main(process.argv, process.env);
}

module.exports = { main, readAllowlist, readTrackedFiles, readBins, ALLOWLIST_FILE, SOURCES };
