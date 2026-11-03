/**
 * Проверка каталога ADR: номера уникальны, заголовок им соответствует, у каждого
 * решения есть «Дата:» и «Статус:».
 *
 * Коллизия 2026-11-02 (два файла с номером 0067, и ещё пара у 0027) делала цитату
 * «ADR-0067» двусмысленной, а `check-doc-links` её не видел: оба файла
 * существовали и открывались. Этот скрипт ловит класс целиком (#390).
 *
 * Запуск: `npm run check:adr` или `node scripts/check-adr.js`. В гейте — шаг
 * `adr-index`.
 */

"use strict";

const fs = require("node:fs");
const path = require("node:path");

const { inspectAdrFiles } = require("./check-adr-core");

const ADR_DIR = path.join("docs", "adr");
const LEGACY_FILE = path.join("docs", "quality", "adr-legacy.json");

const USAGE = `check-adr.js — проверка нумерации и шаблона ADR

  node scripts/check-adr.js            текстовый вывод, код 0 или 1
  node scripts/check-adr.js --json     находки как JSON (для гейта и пробников)
  node scripts/check-adr.js --help     эта справка

Исключения формата — ${LEGACY_FILE.replaceAll("\\", "/")} (датированный список,
правки видны в дифе). Новый ADR добавить туда нельзя без объяснения в ревью.`;

/** Русская форма счётного слова для итога. */
function plural(count, one, few, many) {
  const tens = count % 100;
  const unit = count % 10;
  if (tens >= 11 && tens <= 14) return many;
  if (unit === 1) return one;
  if (unit >= 2 && unit <= 4) return few;
  return many;
}

function readAdrFiles(repoRoot) {
  const dir = path.join(repoRoot, ADR_DIR);
  return fs
    .readdirSync(dir)
    .filter((name) => name.endsWith(".md"))
    .sort()
    .map((name) => ({
      name,
      path: `${ADR_DIR.replaceAll("\\", "/")}/${name}`,
      text: fs.readFileSync(path.join(dir, name), "utf8"),
    }));
}

function readLegacy(repoRoot) {
  const raw = JSON.parse(fs.readFileSync(path.join(repoRoot, LEGACY_FILE), "utf8"));
  if (!raw || typeof raw !== "object" || !Array.isArray(raw.files) || !raw.adopted) {
    throw new Error(`${LEGACY_FILE}: ожидаются поля "adopted" и "files"`);
  }
  return raw;
}

function main(argv) {
  const args = argv.slice(2);
  if (args.includes("--help") || args.includes("-h")) {
    console.log(USAGE);
    return 0;
  }
  const repoRoot = path.resolve(__dirname, "..");
  if (!fs.existsSync(path.join(repoRoot, ADR_DIR))) {
    console.error(`каталог ${ADR_DIR} не найден — запуск из корня репозитория?`);
    return 2;
  }

  let files;
  let legacy;
  try {
    files = readAdrFiles(repoRoot);
    legacy = readLegacy(repoRoot);
  } catch (error) {
    console.error(`не удалось прочитать ADR: ${error.message}`);
    return 2;
  }

  const findings = inspectAdrFiles(files, legacy);

  if (args.includes("--json")) {
    console.log(JSON.stringify({ checked: files.length, findings }, null, 2));
  } else if (findings.length === 0) {
    console.log(
      `ADR: ${files.length} ${plural(files.length, "файл", "файла", "файлов")}, ` +
        "номера уникальны, шаблон соблюдён " +
        `(исключений формата: ${legacy.files.length}, от ${legacy.adopted})`,
    );
  } else {
    for (const finding of findings) {
      console.log(`✗ ${finding.path}: ${finding.message}`);
    }
    console.log(
      `итог: ${findings.length} ${plural(findings.length, "находка", "находки", "находок")} ` +
        `в ${files.length} ${plural(files.length, "файле", "файлах", "файлах")} ` +
        `(исключения — ${LEGACY_FILE.replaceAll("\\", "/")})`,
    );
  }
  return findings.length === 0 ? 0 : 1;
}

if (require.main === module) {
  process.exitCode = main(process.argv);
}

module.exports = { main, readAdrFiles, readLegacy };
